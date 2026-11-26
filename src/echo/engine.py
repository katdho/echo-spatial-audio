
"""engine.py: ECHO audio engine

Combines audio sources, spatial motion, room acoustics, and audio effects
into a stereo output

Rendering signal flow:
    Source audio
        |
        +--> Spatial propagation (direct sound and wall reflections)
        |         |
        |         +--> Stereo dry mix --> Ping-pong delay
        |
        +--> Reverb send --> Predelay --> Reverb
                                      |
        Dry mix + delay + reverb -----+--> Stereo output

The engine automatically adds a tail to allow reverb and echoes to decay

Automation (see automation.py): a source's `automation` dict can replace its
gain_db, send and doppler with keyframe curves, and `Echo.automation` can replace
the ping-pong delay_feedback. Curves are evaluated once per sample on scene time.
A source's position is automated by giving it a KeyframePath or PolarPath motion.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Union
import numpy as np
import pyquist as pq
from . import automation, dsp
from .spatial import Propagation, Room, Static, propagate

@dataclass
class ReverbSettings:
    """Configuration for the scene's shared reverb effect"""
    enabled: bool = True
    kind: str = "fdn"             # "fdn" or "schroeder"
    t60: float = 2.5              # Reverberation decay time in seconds
    damping: float = 0.25         # High-frequency damping in the FDN
    size: float = 1.0             # Scales FDN delay-line lengths
    predelay: float = 0.02        # Delay before the reverb begins, in seconds
    level_db: float = -6.0        # Reverb return level in dB

@dataclass
class DelaySettings:
    """Configuration for the shared stereo ping-pong delay"""
    enabled: bool = False
    time: float = 0.375           # Time btwn echoes, in seconds
    feedback: float = 0.45        # Amount of signal fed back into the delay
    level_db: float = -8.0        # Delay return level in dB

@dataclass
class Source:
    """An audio source and its spatial and playback configuration."""
    name: str
    audio: np.ndarray             # Mono audio at the engine's sample rate
    motion: Callable = field(default_factory=Static)
    gain_db: float = 0.0
    send: float = 0.3             # Amount sent to the shared reverb
    start: float = 0.0            # Playback start time, in seconds
    loop: bool = True
    prop: Propagation = field(default_factory=Propagation)
    # Curves that replace gain_db / send / doppler: {"gain_db": Curve, ...}
    automation: dict = field(default_factory=dict)

    def __post_init__(self):
        automation.check_names(self.automation, automation.SOURCE_PARAMS, f"source {self.name!r}")

    @property
    def duration(self) -> float:
        """Return the source audio length in samples"""
        return len(self.audio)

class Echo:
    """Manage audio sources and render a spatial stereo audio scene"""
    def __init__(self, fs: int = 44100):
        self.fs = fs
        self.sources: list[Source] = []
        self.room = Room()
        self.reverb = ReverbSettings()
        self.delay = DelaySettings()
        self.master_peak_dbfs = -1.0
        # Scene-level curves: {"delay_feedback": Curve}
        self.automation: dict = {}

    def add_source(
        self,
        audio: Union[pq.Audio, np.ndarray, str, Path],
        name: str = "",
        motion: Optional[Callable] = None,
        **kw
    ) -> Source:
        """Add a mono audio source to the scene

        Accepts a Pyquist Audio object, NumPy array, or audio file path.
        Pyquist audio is converted to mono, resampled if necessary, and
        normalized before being added. Additional keyword arguments
        configure the Source object
        """
        if isinstance(audio, (str, Path)):
            name = name or Path(audio).name
            audio = pq.Audio.from_file(audio)

        if isinstance(audio, pq.Audio):
            a = audio.as_mono()
            if a.sample_rate != self.fs:
                a = a.resample(self.fs)
            a = a.normalize(peak_dbfs=-6.0, in_place=False)
            x = np.asarray(a.samples[:, 0], dtype=np.float64)
        else:
            x = np.asarray(audio, dtype=np.float64).reshape(-1)

        src = Source(
            name or f"source {len(self.sources) + 1}",
            x,
            motion=motion or Static(),
            **kw
        )
        self.sources.append(src)
        return src

    def _tail_seconds(self, seconds: Optional[float] = None) -> float:
        """Estimate how long effects need to decay after source playback

        `seconds` is the main playback length; it lets the estimate follow an
        automated delay feedback (the largest value over the next 12 s)
        """
        tail = 0.0

        if self.reverb.enabled:
            tail = max(tail, self.reverb.t60 + self.reverb.predelay)

        if self.delay.enabled:
            fb = float(self.delay.feedback)
            fn = self.automation.get("delay_feedback")
            if fn is not None and seconds is not None:
                grid = np.linspace(seconds, seconds + 12.0, 25)
                fb = float(np.max(np.clip(fn(grid), *automation.PARAMS["delay_feedback"])))
            fb = min(fb, 0.95)
            if fb > 0.01:
                n_echoes = np.log(1e-3)/np.log(fb)
                tail = max(tail, min(12.0, n_echoes*self.delay.time))

        return min(tail, 14.0)

    def render(
        self,
        seconds: float,
        tail: Optional[float] = None,
        normalize: bool = True
    ) -> pq.Audio:
        """Render the scene as stereo audio

        `seconds` specifies the main playback duration. An additional
        effect tail is included automatically unless explicitly provided

        Each source is played according to its start time and looping
        settings, then spatialized and added to the dry mix. Its reverb
        send is accumulated separately. Shared delay and reverb effects
        are applied before the final stereo output is created.

        If `normalize` is True, the result is normalized to the configured
        master peak level
        """
        fs = self.fs
        automation.check_names(self.automation, automation.SCENE_PARAMS, "Echo.automation")
        tail = self._tail_seconds(seconds) if tail is None else tail
        n_dur = int(seconds*fs)
        N = n_dur + int(tail*fs)
        t = np.arange(N)/fs
        dry = np.zeros((N, 2))
        send_bus = np.zeros(N)
        fade = min(int(0.02 *fs), max(n_dur//4, 1))

        for s in self.sources:
            x = np.zeros(N)
            start = int(s.start*fs)
            n_play = max(n_dur-start, 0)
            
            if n_play > 0 and len(s.audio):
                if s.loop:
                    seg = np.resize(s.audio, n_play)
                else:
                    seg = np.pad(
                        s.audio,
                        (0, max(0, n_play-len(s.audio)))
                    )[:n_play]
                seg = seg.copy()
                seg[-fade:] *= np.linspace(1.0, 0.0, fade)
                x[start:start + n_play] = seg

            # Each of these is the source's fixed value, or one value per sample
            # if the parameter is automated.
            gain_db = automation.resolve(s.automation, "gain_db", s.gain_db, t)
            dop = automation.resolve(s.automation, "doppler", s.prop.doppler, t)
            send = automation.resolve(s.automation, "send", s.send, t)

            x *= 10.0**(gain_db/20.0)
            px, py = s.motion(t)
            dry += propagate(x, px, py, fs, s.prop, doppler=dop)

            if self.room.enabled:
                refl = np.sqrt(max(1.0-self.room.absorption, 0.0))
                for ix, iy in self.room.images(px, py):
                    dry += propagate(x, ix, iy, fs, s.prop, gain=refl, doppler=dop)
            send_bus += send*x
            
        out = dry.copy()

        if self.delay.enabled:
            M = max(1, int(round(self.delay.time*fs)))
            fb = automation.resolve(
                self.automation,
                "delay_feedback",
                float(np.clip(self.delay.feedback, 0, 0.95)),
                t)
            echoes = dsp.ping_pong(dry, M, fb)-dry
            out += echoes*10.0**(self.delay.level_db/20.0)

        if self.reverb.enabled:
            rv = self.reverb
            pre = int(rv.predelay*fs)
            bus = dsp.delay(send_bus, pre) if pre else send_bus
            if rv.kind == "schroeder":
                fn = lambda v: np.stack([
                    dsp.schroeder_reverb(v, rv.t60, fs),
                    dsp.delay(dsp.schroeder_reverb(v, rv.t60, fs), 23)
                ], axis=1)
            else:
                fn = lambda v: dsp.fdn_reverb(v, rv.t60, rv.damping, fs, rv.size)
            wet = fn(bus)
            E = dsp.unit_energy(fn, fs, min(1.2*rv.t60+0.5, 14.0))
            out += wet*(10.0**(rv.level_db/20.0)/np.sqrt(max(E, 1e-9)))

        audio = pq.Audio(out.astype(np.float32), fs)
        if normalize and audio.peak_amplitude > 0:
            audio.normalize(peak_dbfs=self.master_peak_dbfs)
        return audio


    def plot_scene(self, seconds: float = 20.0, ax=None):
        """Plot the room, listener, and source trajectories"""
        import matplotlib.pyplot as plt

        if ax is None:
            _, ax = plt.subplots(figsize=(5, 5))
        t = np.linspace(0, seconds, 400)
        hx, hy = self.room.width/2, self.room.depth/2
        if self.room.enabled:
            ax.plot(
                [-hx, hx, hx, -hx, -hx],
                [-hy, -hy, hy, hy, -hy],
                "k-",
                lw=1
            )
        ax.plot(0, 0, "k*", ms=14, label="listener")

        for s in self.sources:
            x, y = s.motion(t)
            line, = ax.plot(x, y, "-", alpha=0.5)
            ax.plot(
                x[0], y[0],
                "o",
                color=line.get_color(),
                label=s.name[:18]
            )

        ax.set_aspect("equal")
        ax.grid(alpha=0.25)
        ax.set_xlabel("x (m): left <-> right")
        ax.set_ylabel("y (m): behind <-> ahead")
        ax.legend(fontsize=7, loc="upper right")
        return ax
