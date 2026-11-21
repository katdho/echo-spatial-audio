"""Jupyter control panel for ECHO (ipywidgets). `launch()` shows it.

All sound comes from the DSP in dsp.py / spatial.py / engine.py; this file only
turns slider values into engine settings and calls Echo.render().
"""
from __future__ import annotations

import numpy as np
import pyquist as pq
import ipywidgets as W
from IPython.display import display, clear_output

from . import sources
from .engine import Echo
from .spatial import Flyby, Orbit, Oscillate, Propagation, Spiral, Static

MOTIONS = ["Static", "Orbit", "Spiral", "Oscillate", "Flyby"]
KINDS = ["Plucked arpeggio", "Plucked drone", "Noise ticks", "Audio file", "Freesound ID"]


def _slider(desc, lo, hi, val, step=0.01, **kw):
    return W.FloatSlider(description=desc, min=lo, max=hi, value=val, step=step,
                         style={"description_width": "110px"}, layout=W.Layout(width="420px"), **kw)


def build_motion(ui: dict):
    """Turn the per-source slider values into a trajectory object."""
    x, y, r, sp = ui["x"], ui["y"], ui["radius"], ui["speed"]
    m = ui["motion"]
    if m == "Orbit":
        return Orbit(cx=x, cy=y, radius=r, speed=sp)
    if m == "Spiral":
        return Spiral(cx=x, cy=y, r_min=0.25 * r, r_max=r, speed=sp)
    if m == "Oscillate":
        return Oscillate(cx=x, cy=y, amplitude=r, speed=sp)
    if m == "Flyby":
        return Flyby(x0=x - r, y0=y, x1=x + r, y1=y, duration=ui["pass_time"], start=0.0)
    return Static(x, y)


class EchoUI:
    def __init__(self, echo: Echo | None = None):
        self.echo = echo or Echo()
        self._syncing = False
        self._last = None
        self._build()

    # ------------------------------------------------------------------ build
    def _build(self):
        # --- add source ---
        self.kind = W.Dropdown(options=KINDS, description="New source")
        self.arg = W.Text(description="Path / ID", placeholder="file path or Freesound id",
                          layout=W.Layout(width="420px"))
        self.add_btn = W.Button(description="Add source", button_style="success")
        self.select = W.Dropdown(options=[], description="Edit source")
        self.remove_btn = W.Button(description="Remove", button_style="danger")
        # --- per-source controls ---
        self.motion = W.Dropdown(options=MOTIONS, description="Motion")
        self.x = _slider("X (m)", -15, 15, 0.0)
        self.y = _slider("Y (m)", -15, 15, 3.0)
        self.radius = _slider("Radius/Span (m)", 0.5, 40, 4.0)
        self.speed = _slider("Speed (Hz)", -0.5, 0.5, 0.08)
        self.pass_time = _slider("Flyby time (s)", 1, 30, 6.0, step=0.5)
        self.gain = _slider("Gain (dB)", -30, 6, 0.0, step=0.5)
        self.send = _slider("Reverb send", 0, 1, 0.3)
        self.doppler = _slider("Doppler", 0, 3, 1.0)
        self.rolloff = _slider("Distance rolloff", 0, 2, 1.0)
        self.air = _slider("Air absorption", 0, 4, 1.0)
        self.shadow = _slider("Head shadow", 0, 1, 1.0)
        self.src_widgets = [self.motion, self.x, self.y, self.radius, self.speed, self.pass_time,
                            self.gain, self.send, self.doppler, self.rolloff, self.air, self.shadow]
        # --- room ---
        self.room_on = W.Checkbox(value=True, description="Room reflections")
        self.room_w = _slider("Room width (m)", 4, 60, 12.0, 0.5)
        self.room_d = _slider("Room depth (m)", 4, 60, 10.0, 0.5)
        self.room_abs = _slider("Wall absorption", 0, 1, 0.35)
        # --- reverb ---
        self.rev_on = W.Checkbox(value=True, description="Reverb")
        self.rev_kind = W.Dropdown(options=["fdn", "schroeder"], description="Algorithm")
        self.t60 = _slider("T60 (s)", 0.3, 10, 2.5, 0.1)
        self.damp = _slider("Damping", 0, 0.5, 0.25)
        self.size = _slider("Size", 0.5, 2.5, 1.0)
        self.predelay = _slider("Pre-delay (s)", 0, 0.2, 0.02, 0.005)
        self.rev_db = _slider("Level (dB)", -30, 6, -6.0, 0.5)
        # --- delay ---
        self.del_on = W.Checkbox(value=False, description="Ping-pong delay")
        self.del_time = _slider("Time (s)", 0.05, 1.5, 0.375, 0.005)
        self.del_fb = _slider("Feedback", 0, 0.95, 0.45)
        self.del_db = _slider("Level (dB)", -30, 6, -8.0, 0.5)
        # --- render ---
        self.length = W.IntSlider(description="Render (s)", min=3, max=90, value=16,
                                  style={"description_width": "110px"})
        self.render_btn = W.Button(description="Render / play", button_style="primary")
        self.export_btn = W.Button(description="Export WAV")
        self.status = W.HTML()
        self.audio_out = W.Output()
        self.plot_out = W.Output()

        self.add_btn.on_click(self._add)
        self.remove_btn.on_click(self._remove)
        self.select.observe(self._load, names="value")
        for w in self.src_widgets:
            w.observe(self._store, names="value")
        for w in (self.room_on, self.room_w, self.room_d, self.room_abs, self.rev_on, self.rev_kind,
                  self.t60, self.damp, self.size, self.predelay, self.rev_db, self.del_on,
                  self.del_time, self.del_fb, self.del_db, self.length):
            w.observe(self._apply_global, names="value")
        self.render_btn.on_click(self._render)
        self.export_btn.on_click(self._export)

        src_box = W.VBox([W.HTML("<b>Source (per sound)</b>"), *self.src_widgets])
        glob = W.HBox([
            W.VBox([W.HTML("<b>Room</b>"), self.room_on, self.room_w, self.room_d, self.room_abs,
                    W.HTML("<b>Ping-pong delay</b>"), self.del_on, self.del_time, self.del_fb, self.del_db]),
            W.VBox([W.HTML("<b>Reverb</b>"), self.rev_on, self.rev_kind, self.t60, self.damp,
                    self.size, self.predelay, self.rev_db]),
        ])
        self.ui = W.VBox([
            W.HBox([self.kind, self.arg, self.add_btn]),
            W.HBox([self.select, self.remove_btn]),
            src_box, glob,
            W.HBox([self.length, self.render_btn, self.export_btn]),
            self.status, self.audio_out, self.plot_out,
        ])

    # --------------------------------------------------------------- sources
    def _make_audio(self):
        k, a = self.kind.value, self.arg.value.strip().strip('"')
        if k == "Plucked arpeggio":
            notes = [(i * 0.25, p, 2.0) for i, p in
                     enumerate(["A3", "C4", "D4", "E4", "G4", "A4", "E4", "D4"] * 4)]
            return sources.pluck_line(notes, t60=2.0, damping=0.4, pick_position=0.2), "arpeggio"
        if k == "Plucked drone":
            return sources.pluck_line([(0, "A1", 12.0)], t60=30.0), "drone"
        if k == "Noise ticks":
            return sources.noise_bursts([i * 0.2 for i in range(60)], length=0.06), "ticks"
        if k == "Freesound ID":
            from pyquist.web.freesound import fetch_freesound
            sample, meta = fetch_freesound(int(a))
            return sample, meta["name"]
        return a, a        # file path (Echo.add_source loads it with pq.Audio.from_file)

    def _add(self, _=None):
        try:
            audio, name = self._make_audio()
            src = self.echo.add_source(audio, name=str(name).split("/")[-1].split("\\")[-1])
        except Exception as e:                                       # noqa: BLE001
            self.status.value = f"<b>Could not add source:</b> {e}"
            return
        src.ui = dict(motion="Static", x=0.0, y=3.0, radius=4.0, speed=0.08, pass_time=6.0)
        self._refresh_select(len(self.echo.sources) - 1)
        self.status.value = f"Added {src.name}."

    def _remove(self, _=None):
        i = self.select.value
        if i is not None and i < len(self.echo.sources):
            self.echo.sources.pop(i)
            self._refresh_select(max(0, i - 1) if self.echo.sources else None)

    def _refresh_select(self, index):
        self._syncing = True
        self.select.options = [(f"{i + 1}. {s.name}", i) for i, s in enumerate(self.echo.sources)]
        self.select.value = index
        self._syncing = False
        self._load()

    def _sel(self):
        i = self.select.value
        return self.echo.sources[i] if i is not None and i < len(self.echo.sources) else None

    def _load(self, _=None):
        s = self._sel()
        if s is None:
            self._plot()
            return
        self._syncing = True
        u = s.ui
        self.motion.value, self.x.value, self.y.value = u["motion"], u["x"], u["y"]
        self.radius.value, self.speed.value, self.pass_time.value = u["radius"], u["speed"], u["pass_time"]
        self.gain.value, self.send.value = s.gain_db, s.send
        self.doppler.value, self.rolloff.value = s.prop.doppler, s.prop.rolloff
        self.air.value, self.shadow.value = s.prop.air_absorption, s.prop.head_shadow
        self._syncing = False
        self._plot()

    def _store(self, _=None):
        s = self._sel()
        if s is None or self._syncing:
            return
        s.ui.update(motion=self.motion.value, x=self.x.value, y=self.y.value, radius=self.radius.value,
                    speed=self.speed.value, pass_time=self.pass_time.value)
        s.motion = build_motion(s.ui)
        s.gain_db, s.send = self.gain.value, self.send.value
        s.prop = Propagation(doppler=self.doppler.value, rolloff=self.rolloff.value,
                             air_absorption=self.air.value, head_shadow=self.shadow.value)
        self._plot()

    # ---------------------------------------------------------------- global
    def _apply_global(self, _=None):
        e = self.echo
        e.room.enabled, e.room.width, e.room.depth, e.room.absorption = \
            self.room_on.value, self.room_w.value, self.room_d.value, self.room_abs.value
        r = e.reverb
        r.enabled, r.kind, r.t60, r.damping = self.rev_on.value, self.rev_kind.value, self.t60.value, self.damp.value
        r.size, r.predelay, r.level_db = self.size.value, self.predelay.value, self.rev_db.value
        d = e.delay
        d.enabled, d.time, d.feedback, d.level_db = self.del_on.value, self.del_time.value, self.del_fb.value, self.del_db.value
        self._plot()

    def _plot(self):
        import matplotlib.pyplot as plt
        with self.plot_out:
            clear_output(wait=True)
            fig, ax = plt.subplots(figsize=(5, 5))
            self.echo.plot_scene(seconds=self.length.value, ax=ax)
            plt.show()
            plt.close(fig)

    def _render(self, _=None):
        if not self.echo.sources:
            self.status.value = "Add at least one source first."
            return
        self._apply_global()
        self.status.value = "Rendering..."
        self._last = self.echo.render(self.length.value)
        with self.audio_out:
            clear_output(wait=True)
            pq.play(self._last, normalize=True)
        self.status.value = f"Rendered {self._last.duration:.1f} s (incl. reverb/delay tail). Use headphones."

    def _export(self, _=None):
        if self._last is None:
            self._render()
        if self._last is not None:
            self._last.write("ECHO_render.wav")
            self.status.value = "Exported <b>ECHO_render.wav</b> to the notebook's folder."


def launch(echo: Echo | None = None) -> EchoUI:
    ui = EchoUI(echo)
    display(ui.ui)
    return ui
