"""spatial.py: where sounds are, and how they sound from there.

Coordinates are metres, seen from above. The listener's head is at the origin
facing +y; +x is to the listener's right. Ears sit at (+-HEAD/2, 0).

Contents:
  Trajectories   Static, Orbit, Spiral, Oscillate, Flyby, Waypoints. Each is
                 callable: time array -> (x, y) positions.
  Room           rectangle around the listener. Wall echoes use the image-source
                 method: one mirrored copy of the source per wall.
  Propagation    per-sound realism settings (Doppler, distance fade, air
                 absorption, head shadow).
  propagate()    mono sound + moving position -> stereo. Each ear reads the sound
                 through a fractional delay (distance / speed of sound). The
                 difference between ears is the interaural time difference; the
                 change over time is the Doppler shift. Then distance fade and
                 a distance- and shadow-dependent low-pass are applied.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import dsp

C_SOUND = 343.0      # m/s
HEAD = 0.175         # ear spacing, m
R_REF = 1.0          # distance at which gain = 1, m


# ------------------------------- trajectories ------------------------------ #
# Each trajectory is a callable t (seconds, array) -> (x, y) in metres.


@dataclass
class Static:
    x: float = 0.0
    y: float = 2.0

    def __call__(self, t):
        return np.full_like(t, self.x), np.full_like(t, self.y)


@dataclass
class Orbit:
    """Circle around (cx, cy). speed in revolutions per second (positive = counter-clockwise
    on the top-down map with +y up; negative = clockwise)."""
    cx: float = 0.0
    cy: float = 0.0
    radius: float = 3.0
    speed: float = 0.1
    phase: float = 0.0       # radians; 0 starts to the listener's right

    def __call__(self, t):
        a = 2 * np.pi * self.speed * t + self.phase
        return self.cx + self.radius * np.cos(a), self.cy + self.radius * np.sin(a)


@dataclass
class Spiral:
    """Orbit whose radius breathes between `r_min` and `r_max`."""
    cx: float = 0.0
    cy: float = 0.0
    r_min: float = 1.0
    r_max: float = 6.0
    speed: float = 0.1
    breathe: float = 0.04    # Hz
    phase: float = 0.0

    def __call__(self, t):
        a = 2 * np.pi * self.speed * t + self.phase
        r = self.r_min + (self.r_max - self.r_min) * (0.5 - 0.5 * np.cos(2 * np.pi * self.breathe * t))
        return self.cx + r * np.cos(a), self.cy + r * np.sin(a)


@dataclass
class Oscillate:
    """Sinusoidal sweep along the x axis (left <-> right) around (cx, cy)."""
    cx: float = 0.0
    cy: float = 2.0
    amplitude: float = 4.0
    speed: float = 0.15      # Hz
    phase: float = 0.0

    def __call__(self, t):
        a = 2 * np.pi * self.speed * t + self.phase
        return self.cx + self.amplitude * np.sin(a), np.full_like(t, self.cy)


@dataclass
class Flyby:
    """One constant-velocity pass from p0 to p1 lasting `duration` s starting at
    `start`; holds position before / after. The classic Doppler demonstration."""
    x0: float = -30.0
    y0: float = 2.0
    x1: float = 30.0
    y1: float = 2.0
    duration: float = 4.0
    start: float = 0.0

    def __call__(self, t):
        u = np.clip((t - self.start) / self.duration, 0.0, 1.0)
        return self.x0 + (self.x1 - self.x0) * u, self.y0 + (self.y1 - self.y0) * u


@dataclass
class Waypoints:
    """Smooth path through (t, x, y) points (cosine-eased between points)."""
    points: tuple = ((0.0, -3.0, 2.0), (5.0, 3.0, 4.0), (10.0, -3.0, 2.0))

    def __call__(self, t):
        P = np.asarray(self.points, dtype=np.float64)
        tt = np.clip(t, P[0, 0], P[-1, 0])
        k = np.clip(np.searchsorted(P[:, 0], tt, side="right") - 1, 0, len(P) - 2)
        u = (tt - P[k, 0]) / (P[k + 1, 0] - P[k, 0])
        u = 0.5 - 0.5 * np.cos(np.pi * u)
        return P[k, 1] + u * (P[k + 1, 1] - P[k, 1]), P[k, 2] + u * (P[k + 1, 2] - P[k, 2])


MOTIONS = {"Static": Static, "Orbit": Orbit, "Spiral": Spiral, "Oscillate": Oscillate,
           "Flyby": Flyby, "Waypoints": Waypoints}


# ---------------------------------- room ----------------------------------- #


@dataclass
class Room:
    """Rectangular room, listener at its centre. First-order image sources
    (one bounce off each of the 4 walls) are added as extra delay-line reads."""
    width: float = 12.0          # m (x extent)
    depth: float = 10.0          # m (y extent)
    absorption: float = 0.35     # 0 = mirror walls, 1 = anechoic
    enabled: bool = True

    def images(self, x, y):
        """Positions of the 4 first-order image sources (clamped inside room)."""
        hx, hy = self.width / 2, self.depth / 2
        x = np.clip(x, -hx + 0.1, hx - 0.1)
        y = np.clip(y, -hy + 0.1, hy - 0.1)
        return [(2 * hx - x, y), (-2 * hx - x, y), (x, 2 * hy - y), (x, -2 * hy - y)]


# ------------------------- binaural propagation model ----------------------- #


@dataclass
class Propagation:
    doppler: float = 1.0       # 0 = no pitch shift, 1 = physical, >1 exaggerated
    rolloff: float = 1.0       # distance gain exponent (1 = inverse distance)
    air_absorption: float = 1.0  # 0 = none; scales distance-dependent darkening
    head_shadow: float = 1.0   # 0 = none; darkening of the far ear


def propagate(x: np.ndarray, px: np.ndarray, py: np.ndarray, fs: int,
              prop: Propagation, gain: float = 1.0) -> np.ndarray:
    """Binaural rendering of mono `x` emitted from the moving point (px, py).

    For each ear:  y[n] = gain_n * LP_n( x[n - d_ear[n]] ),
      * d_ear = r_ear / c is the *propagation delay* read with a fractional
        delay line. The difference between ears is the interaural time
        difference; the change of d over time is the Doppler shift.
      * gain falls as (R_REF / r)^rolloff.
      * LP is a one-pole whose cutoff falls with distance (air absorption) and,
        for the ear facing away from the source, with head shadow.
    """
    N = len(px)
    r_c = np.hypot(px, py)                       # distance to head centre
    r_c = np.maximum(r_c, 0.05)
    # Doppler scaling: only the *change* of common delay is scaled.
    common = (prop.doppler - 1.0) * (r_c - r_c[0])
    side = px / r_c                              # +1 hard right ... -1 hard left
    gain_n = gain * (R_REF / np.maximum(r_c, R_REF)) ** prop.rolloff
    out = np.zeros((N, 2))
    for ch, ear_x in enumerate((-HEAD / 2, HEAD / 2)):
        r_ear = np.hypot(px - ear_x, py)
        d = (r_ear + common) * fs / C_SOUND
        d = np.maximum(d, 0.0)
        sig = dsp.fractional_delay(x, d)
        # far-ear shadow: ear on the left is shadowed by sources on the right
        shadow = np.clip(side if ch == 0 else -side, 0.0, 1.0)
        fc = 20000.0 / (1.0 + 0.06 * prop.air_absorption * r_c)
        fc = fc * (1.0 - 0.85 * prop.head_shadow * shadow)
        fc = np.clip(fc, 400.0, 0.45 * fs)
        sig = dsp.one_pole(sig, dsp.cutoff_to_alpha(fc, fs))
        out[:, ch] = sig * gain_n
    return out
