"""ECHO parameter automation: keyframe curves that change a parameter over time

A `Curve` is a list of keyframes (time_seconds, value). Evaluating it at an array
of times returns one value per time, so the renderer can ask for a whole
render's worth of values at once (the same way a trajectory is evaluated).

    gain = Curve([(0, -24), (8, 0), (20, -12)], "smoothstep")
    gain(np.array([0, 4, 8]))        # -> [-24, -12, 0]

Rules
  - Time is scene time (seconds from the start of the render), the same clock the
    trajectories use. It is not relative to a source's `start`.
  - Before the first keyframe the curve holds the first value; after the last
    keyframe it holds the last value.
  - Two keyframes at the same time make a jump: the later one wins from that
    instant on.
  - Each segment is "linear" or "smoothstep". A keyframe may carry its own shape,
    (time, value, "smoothstep"), which applies to the segment that STARTS there.
    The `interp` argument is the default for keyframes that don't name one.
  - A curve REPLACES the parameter's fixed value; it is not added to it.

Automatable parameters (`PARAMS`)
  per source   gain_db (dB), send (0..1 reverb send), doppler (0..4)
  per scene    delay_feedback (0..0.95, ping-pong repeats)
  position     motion=KeyframePath(...) or PolarPath(...) (below): trajectories
               whose coordinates are curves

Anything callable that maps a time array to an equal-length array also works as a
"curve" (an LFO, for example: lambda t: -12 + 6*np.sin(2*np.pi*0.25*t)).

Smoothstep
  Linear interpolation moves at a constant rate and changes speed abruptly at each
  keyframe. Smoothstep eases in and out. Choose the cubic s(u) = a u^3 + b u^2 + c u + d
  on u in [0, 1] with s(0) = 0, s(1) = 1 and zero slope at both ends:
      s(0) = 0       ->  d = 0
      s'(0) = 0      ->  c = 0           (s'(u) = 3a u^2 + 2b u + c)
      s(1) = 1       ->  a + b = 1
      s'(1) = 0      ->  3a + 2b = 0   ->  b = -3a/2
      a - 3a/2 = 1   ->  a = -2, b = 3
  so s(u) = 3u^2 - 2u^3. Across a segment, value = v0 + s(u)*(v1 - v0).
"""

from __future__ import annotations
import math
import numpy as np

INTERPOLATIONS = ("linear", "smoothstep")

# name -> (lowest, highest). Curve output is clamped to this range before use.
PARAMS = {
    "gain_db":        (-120.0, 24.0),   # -120 dB is effectively silence
    "send":           (0.0, 1.0),
    "doppler":        (0.0, 4.0),
    "delay_feedback": (0.0, 0.95),
}
SOURCE_PARAMS = ("gain_db", "send", "doppler")
SCENE_PARAMS = ("delay_feedback",)


def smoothstep(u):
    """Ease-in/ease-out ramp 3u^2 - 2u^3 on [0, 1] (clamps u outside that range)"""
    u = np.clip(u, 0.0, 1.0)
    return u*u*(3.0 - 2.0*u)


def _check_interp(name):
    if name not in INTERPOLATIONS:
        raise ValueError(f"unknown interpolation {name!r}; choose from {INTERPOLATIONS}")


class Curve:
    """Keyframe curve: value as a function of time

    `points` is an iterable of (time, value) or (time, value, interpolation).
    Keyframes are sorted by time; equal times make a jump.
    """

    def __init__(self, points, interp: str = "linear"):
        _check_interp(interp)
        rows = []
        for k, p in enumerate(points):
            if len(p) == 2:
                t, v = p
                shape = interp
            elif len(p) == 3:
                t, v, shape = p
                shape = interp if shape is None else shape
                _check_interp(shape)
            else:
                raise ValueError("a keyframe is (time, value) or (time, value, interpolation)")
            t, v = float(t), float(v)
            if not (math.isfinite(t) and math.isfinite(v)):
                raise ValueError(f"keyframe {k} is not a finite number: {tuple(p)!r}")
            rows.append((t, v, shape == "smoothstep"))
        if not rows:
            raise ValueError("a Curve needs at least one keyframe")
        rows.sort(key=lambda r: r[0])                 # stable: equal times keep their order
        self.interp = interp
        self.times = np.array([r[0] for r in rows])
        self.values = np.array([r[1] for r in rows])
        self.smooth = np.array([r[2] for r in rows])  # shape of the segment starting here

    def __call__(self, t):
        """Evaluate at time(s) `t` (seconds); returns an array shaped like `t`"""
        t = np.asarray(t, dtype=np.float64)
        scalar = t.ndim == 0
        t = np.atleast_1d(t)
        ts, vs = self.times, self.values
        if len(ts) == 1:
            out = np.full(t.shape, vs[0])
        else:
            # segment k runs from keyframe k to k+1; side="right" makes a jump
            # (equal times) resolve to the later keyframe
            seg = np.clip(np.searchsorted(ts, t, side="right") - 1, 0, len(ts) - 2)
            t0, t1 = ts[seg], ts[seg + 1]
            dt = t1 - t0
            u = np.divide(t - t0, dt, out=np.ones_like(t), where=dt > 0)    # position in segment
            shaped = np.where(self.smooth[seg], smoothstep(u), u)
            out = vs[seg] + shaped*(vs[seg + 1] - vs[seg])
            # Hold the ends. Done explicitly (not by clamping t) so that a jump at
            # the first or last keyframe time still has two sides.
            out = np.where(t < ts[0], vs[0], np.where(t >= ts[-1], vs[-1], out))
        return out[0] if scalar else out

    def __repr__(self):
        pts = [(float(t), float(v)) for t, v in zip(self.times, self.values)]
        return f"Curve({pts}, {self.interp!r})"


def _as_curve(v):
    """Accept a number (constant), a Curve, or any function of a time array"""
    if isinstance(v, (int, float, np.integer, np.floating)):
        return Curve([(0.0, float(v))])
    if callable(v):
        return v
    raise TypeError(f"expected a number, a Curve or a function of time, got {type(v).__name__}")


class KeyframePath:
    """Trajectory whose x and y positions (metres) are curves of time

    `x` and `y` may each be a Curve, a function of time, or a plain number.
    For (time, x, y) keyframes use `KeyframePath.from_points`.
    Axes interpolate independently, so with "linear" a segment is a straight line
    at constant speed; with "smoothstep" the source eases into and out of each point.
    """

    def __init__(self, x, y):
        self.x = _as_curve(x)
        self.y = _as_curve(y)

    @classmethod
    def from_points(cls, points, interp: str = "linear"):
        """Build from (time, x, y) or (time, x, y, interpolation) keyframes"""
        xs, ys = [], []
        for p in points:
            if len(p) == 3:
                t, x, y = p
                shape = None
            elif len(p) == 4:
                t, x, y, shape = p
            else:
                raise ValueError("a position keyframe is (time, x, y) or (time, x, y, interpolation)")
            xs.append((t, x, shape))
            ys.append((t, y, shape))
        return cls(Curve(xs, interp), Curve(ys, interp))

    def __call__(self, t):
        t = np.asarray(t, dtype=np.float64)
        return np.broadcast_to(self.x(t), t.shape).copy(), np.broadcast_to(self.y(t), t.shape).copy()


class PolarPath:
    """Trajectory given as distance and compass angle around a centre point

    `distance` is in metres. `azimuth` is in degrees measured from straight ahead
    (+y) turning toward the listener's right (+x):
        0 = ahead, 90 = right, 180 = behind, 270 = left.
    Azimuth is interpolated as a plain number with no wrap-around, so
    (0, 0) -> (10, 720) is two full turns and (0, 350) -> (10, 10) goes the long
    way round. This makes "approach, circle, recede" a few keyframes:
        PolarPath(distance=Curve([(0, 14), (8, 3), (24, 16)], "smoothstep"),
                  azimuth=Curve([(0, 270), (24, 900)]))
    Each argument may be a Curve, a function of time or a plain number.
    """

    def __init__(self, distance, azimuth, cx: float = 0.0, cy: float = 0.0):
        self.distance = _as_curve(distance)
        self.azimuth = _as_curve(azimuth)
        self.cx = cx
        self.cy = cy

    def __call__(self, t):
        t = np.asarray(t, dtype=np.float64)
        r = np.maximum(np.broadcast_to(self.distance(t), t.shape), 0.0)
        a = np.radians(np.broadcast_to(self.azimuth(t), t.shape))
        return self.cx + r*np.sin(a), self.cy + r*np.cos(a)


def check_names(curves: dict, allowed, owner: str = "automation") -> None:
    """Raise if `curves` names a parameter that can't be automated or isn't callable"""
    bad = sorted(set(curves) - set(allowed))
    if bad:
        raise ValueError(f"{owner}: can't automate {bad}; choose from {sorted(allowed)}")
    for name, fn in curves.items():
        if not callable(fn):
            raise TypeError(f"{owner}: automation[{name!r}] must be a Curve or a function of time")


def resolve(curves: dict, name: str, static, t: np.ndarray):
    """The value of parameter `name` to use for the samples at times `t`

    Returns `static` untouched when `name` isn't automated (so un-automated scenes
    render exactly as before). Otherwise returns one clamped value per sample.
    """
    fn = curves.get(name)
    if fn is None:
        return static
    v = np.asarray(fn(t), dtype=np.float64)
    if not np.all(np.isfinite(v)):
        raise ValueError(f"automation for {name!r} produced a non-finite value")
    lo, hi = PARAMS[name]
    return np.broadcast_to(np.clip(v, lo, hi), np.shape(t))
