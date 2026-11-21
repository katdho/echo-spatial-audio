"""Built-in sound generators for ECHO, written as pyquist instruments so they
work with pq.Score exactly like the instruments in the course notes."""
from __future__ import annotations

from typing import Sequence

import numpy as np
import pyquist as pq

from . import dsp

F_S = 44100


def pluck_instrument(pitch, duration: float, t60: float | None = None, damping: float = 0.5,
                     pick_position: float = 0.0, f_s: int = F_S, seed: int | None = None) -> pq.Audio:
    """A Karplus-Strong string as a pyquist instrument. `pitch` is a name
    ("E3") or a MIDI number."""
    if isinstance(pitch, str):
        pitch = pq.helper.pitch_name_to_pitch(pitch)
    f0 = float(pq.helper.pitch_to_frequency(pitch))
    rng = np.random.default_rng(seed)
    y = dsp.pluck(f0, duration, f_s, t60=t60, damping=damping, pick_position=pick_position, rng=rng)
    return pq.Audio(y.astype(np.float32), f_s)


def pluck_line(notes: Sequence[tuple], t60: float = 2.0, damping: float = 0.5,
               pick_position: float = 0.0, f_s: int = F_S, seed: int = 0) -> pq.Audio:
    """Render [(onset_seconds, pitch, duration_seconds), ...] with the plucked-string
    model into one mono Audio, using pq.Score (as in the notes)."""
    score = pq.Score([(t, {"pitch": p, "duration": d, "seed": seed + i})
                      for i, (t, p, d) in enumerate(notes)])

    def inst(pitch, duration, seed):
        return pluck_instrument(pitch, duration, t60=t60, damping=damping,
                                pick_position=pick_position, f_s=f_s, seed=seed)
    return score.render(inst)


def noise_bursts(times: Sequence[float], length: float = 0.12, f_s: int = F_S, seed: int = 0) -> pq.Audio:
    """Short decaying noise ticks - a handy percussive source for hearing motion."""
    rng = np.random.default_rng(seed)
    total = int((max(times) + length + 0.05) * f_s)
    y = np.zeros(total)
    n = int(length * f_s)
    env = np.exp(-np.arange(n) / (0.15 * n))
    for t in times:
        i = int(t * f_s)
        y[i:i + n] += rng.uniform(-1, 1, n) * env
    return pq.Audio(y.astype(np.float32), f_s)
