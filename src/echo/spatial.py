
"""Spatial positioning and binaural propagation for ECHO.

Coordinates are in meters, viewed from above:
- The listener is at the origin, facing +y
- +x points to the listener's right
- The ears are at (-HEAD/2, 0) and (+HEAD/2, 0)

The module provides:
- Trajectories that map time to source positions (Static, Orbit, Spiral, Oscillate, Flyby, Waypoints)
- Room geometry and first-order wall reflections
- Propagation settings for distance, Doppler, and frequency-dependent effects
- Binaural rendering that converts a mono source into stereo audio
"""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from . import dsp

C_SOUND = 343.0  # Speed of sound in air, meters per second
HEAD = 0.175     # Distance between ears, meters
R_REF = 1.0      # Reference distance for distance-based gain, meters

@dataclass
class Static:
    """Keep a source at a fixed position"""
    x: float = 0.0
    y: float = 2.0
    def __call__(self, t):
        return np.full_like(t, self.x), np.full_like(t, self.y)


@dataclass
class Orbit:
    """Move a source in a circle around a center point

    Speed is measured in revolutions per second. Positive values move
    counter-clockwise; negative values move clockwise
    A phase of 0 starts at the rightmost point of the orbit
    """
    cx: float = 0.0
    cy: float = 0.0
    radius: float = 3.0
    speed: float = 0.1
    phase: float = 0.0

    def __call__(self, t):
        angle = 2*np.pi*self.speed*t + self.phase
        return (
            self.cx + self.radius*np.cos(angle),
            self.cy + self.radius*np.sin(angle),
        )

@dataclass
class Spiral:
    """Orbit while smoothly varying the distance from the center"""
    cx: float = 0.0
    cy: float = 0.0
    r_min: float = 1.0
    r_max: float = 6.0
    speed: float = 0.1
    breathe: float = 0.04
    phase: float = 0.0

    def __call__(self, t):
        angle = 2*np.pi*self.speed*t + self.phase
        radius_phase = 2*np.pi*self.breathe*t
        radius = self.r_min + (self.r_max-self.r_min)*(
            0.5 - 0.5*np.cos(radius_phase))

        return (
            self.cx + radius*np.cos(angle),
            self.cy + radius*np.sin(angle),
        )

@dataclass
class Oscillate:
    """Sweep a source left and right along the x-axis"""
    cx: float = 0.0
    cy: float = 2.0
    amplitude: float = 4.0
    speed: float = 0.15
    phase: float = 0.0

    def __call__(self, t):
        angle = 2*np.pi*self.speed*t + self.phase
        return (self.cx + self.amplitude*np.sin(angle),
                np.full_like(t, self.cy))

@dataclass
class Flyby:
    """Move a source at constant velocity from one position to another

    The source remains at its starting position before the pass and at
    its ending position afterward
    """
    x0: float = -30.0
    y0: float = 2.0
    x1: float = 30.0
    y1: float = 2.0
    duration: float = 4.0
    start: float = 0.0

    def __call__(self, t):
        u = np.clip((t-self.start)/self.duration, 0.0, 1.0)
        return (
            self.x0 + (self.x1-self.x0)*u,
            self.y0 + (self.y1-self.y0)*u,
        )

@dataclass
class Waypoints:
    """Move smoothly through a sequence of timed positions

    Each waypoint is a (time_seconds, x, y) tuple. Position is held
    before the first waypoint and after the last one. Movement between
    waypoints uses cosine easing
    """
    points: tuple = (
        (0.0, -3.0, 2.0),
        (5.0, 3.0, 4.0),
        (10.0, -3.0, 2.0),
    )

    def __call__(self, t):
        points = np.asarray(self.points, dtype=np.float64)
        times = np.clip(t, points[0, 0], points[-1, 0])

        segment = np.clip(
            np.searchsorted(points[:, 0], times, side="right")-1,
            0, len(points)-2)

        u = (times - points[segment, 0])/(points[segment+1, 0] - points[segment, 0])
        u = 0.5 - 0.5*np.cos(np.pi*u)

        x = points[segment, 1] + u*(points[segment+1, 1] - points[segment, 1])
        y = points[segment, 2] + u*(points[segment+1, 2] - points[segment, 2])
        return x, y


MOTIONS = {
    "Static": Static,
    "Orbit": Orbit,
    "Spiral": Spiral,
    "Oscillate": Oscillate,
    "Flyby": Flyby,
    "Waypoints": Waypoints,
}

@dataclass
class Room:
    """Rectangular room used to generate first-order wall reflections

    The listener is at the room center. Each wall contributes one
    mirrored source position using the image-source method
    """
    width: float = 12.0
    depth: float = 10.0
    absorption: float = 0.35
    enabled: bool = True

    def images(self, x, y):
        """Return the 4 first-order image-source positions

        Source coordinates are clamped slightly inside the room before
        mirroring to keep the reflected positions well-defined
        """
        half_width = self.width/2
        half_depth = self.depth/2

        x = np.clip(x, -half_width+0.1, half_width-0.1)
        y = np.clip(y, -half_depth+0.1, half_depth-0.1)
        return [
            (2*half_width-x, y),
            (-2*half_width-x, y),
            (x, 2*half_depth-y),
            (x, -2*half_depth-y),
        ]


@dataclass
class Propagation:
    """Settings controlling how a source sounds at the listener's position
    Values >1 exaggerate an effect; 0 disables it where applicable
    """
    doppler: float = 1.0
    rolloff: float = 1.0
    air_absorption: float = 1.0
    head_shadow: float = 1.0

def propagate(
    x: np.ndarray,
    px: np.ndarray,
    py: np.ndarray,
    fs: int,
    prop: Propagation,
    gain: float = 1.0,
    doppler: float | np.ndarray | None = None,
) -> np.ndarray:
    """Render a moving mono source as binaural stereo audio

    Each ear receives the source through a distance-dependent fractional
    delay. The difference between ear delays produces interaural time
    differences (ITD); changes in delay over time produce Doppler shift

    Distance-based gain and one-pole low-pass filtering then model
    amplitude falloff, air absorption, and head shadow
    """
    n = len(px)
    r_c = np.hypot(px, py)
    r_c = np.maximum(r_c, 0.05)
    side = px/r_c

    dop = np.asarray(prop.doppler if doppler is None else doppler, dtype=np.float64)
    if dop.ndim == 0:
        common_delay = (dop - 1.0)*(r_c - r_c[0])
    else:
        common_delay = np.cumsum((dop - 1.0)*np.diff(r_c, prepend=r_c[0]))
    gain_n = gain*(R_REF/np.maximum(r_c, R_REF)) ** prop.rolloff
    out = np.zeros((n, 2))

    for ch, ear_x in enumerate((-HEAD/2, HEAD/2)):
        r_ear = np.hypot(px - ear_x, py)
        delay = (r_ear + common_delay)*fs/C_SOUND
        delay = np.maximum(delay, 0.0)
        signal = dsp.fractional_delay(x, delay)
        shadow = np.clip(side if ch == 0 else -side, 0.0, 1.0)

        cutoff = 20000.0/(1.0 + 0.06*prop.air_absorption*r_c)
        cutoff *= 1.0 - 0.85*prop.head_shadow*shadow
        cutoff = np.clip(cutoff, 400.0, 0.45*fs)

        signal = dsp.one_pole(signal, dsp.cutoff_to_alpha(cutoff, fs))
        out[:, ch] = signal*gain_n
    return out
