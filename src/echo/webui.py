"""Browser control panel for ECHO.

    python app.py            # from src/  -> opens http://127.0.0.1:8765

This file is only the *bridge* between the web page (echo/web/index.html) and the
DSP: it turns the page's settings (JSON) into an `Echo` scene, asks the engine to
render, and sends the WAV back. All sound is still made by dsp.py / spatial.py /
engine.py. Uses only the Python standard library plus pyquist and NumPy.

Endpoints
    GET  /              the page
    GET  /api/catalog   sound types + demo scenes (single source of truth for the page)
    POST /api/scene     settings -> the path every sound travels (for the map)
    POST /api/render    settings -> stereo WAV bytes
    POST /api/upload    raw audio file bytes -> {id, name, seconds}
    POST /api/probe     {kind, arg} -> checks a sound can be loaded (Freesound ids)
"""
from __future__ import annotations

import json
import math
import tempfile
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pyquist as pq

from . import sources
from .engine import DelaySettings, Echo, ReverbSettings
from .spatial import Flyby, Orbit, Oscillate, Propagation, Room, Spiral, Static

WEB_DIR = Path(__file__).parent / "web"
MAX_UPLOAD = 100 * 1024 * 1024
MAX_SOURCES = 12

# --------------------------------------------------------------------------- #
# Sound catalog: what the page offers in "Pick your sounds"
# --------------------------------------------------------------------------- #

ARP = ["A3", "C4", "D4", "E4", "G4", "A4", "E4", "D4"]

# `defaults` = how a new sound of that kind is placed; `loop` = repeat to fill the render.
KINDS = [
    dict(id="arpeggio", label="Plucked arpeggio", loop=True,
         blurb="A guitar-like string playing a rising pattern.",
         defaults=dict(motion="Orbit", x=0, y=0, radius=3.5, speed=0.08, send=0.35)),
    dict(id="counter", label="Counter-melody", loop=True,
         blurb="Higher plucks that pair well with the arpeggio.",
         defaults=dict(motion="Orbit", x=0, y=0, radius=4, speed=-0.05, send=0.5)),
    dict(id="drone", label="Low drone", loop=True,
         blurb="A long, deep string note that fills the room.",
         defaults=dict(motion="Static", x=0, y=6, gain=-6, send=0.8)),
    dict(id="bells", label="Bell-like plucks", loop=True,
         blurb="Slow, ringing notes. Great with a big reverb.",
         defaults=dict(motion="Spiral", x=0, y=0, radius=14, speed=0.05, send=0.8, air=2)),
    dict(id="ticks", label="Noise ticks", loop=True,
         blurb="Short clicks. The easiest sound for hearing motion.",
         defaults=dict(motion="Oscillate", x=0, y=2, radius=5, speed=0.2, gain=-4, send=0.2)),
    dict(id="bass", label="Bass string pattern", loop=True,
         blurb="A steady low pattern that anchors a scene.",
         defaults=dict(motion="Static", x=-1.5, y=1, gain=-3, send=0.0)),
    dict(id="note", label="Single pluck", loop=False,
         blurb="One long note, played once. Good for a fly-by.",
         defaults=dict(motion="Flyby", x=0, y=3, radius=25, pass_time=5, send=0.3)),
    dict(id="file", label="Your audio file", loop=True, hidden=True,
         blurb="A recording you upload.",
         defaults=dict(motion="Orbit", x=0, y=0, radius=3.5, speed=0.08, send=0.3)),
    dict(id="freesound", label="Freesound sound", loop=True, hidden=True,
         blurb="A sound fetched by Freesound id.",
         defaults=dict(motion="Orbit", x=0, y=0, radius=3.5, speed=0.08, send=0.3)),
]
KIND_BY_ID = {k["id"]: k for k in KINDS}

# Ready-made scenes; the first four mirror demo.py so the page and the renders agree.
PRESETS = [
    dict(
        id="doppler", label="Doppler fly-by", length=8,
        blurb="A ticking sound races past you. Listen for the pitch dropping as it leaves.",
        room=dict(enabled=False), reverb=dict(enabled=False), delay=dict(enabled=False),
        sources=[
            dict(kind="ticks", name="Fly-by ticks", motion="Flyby", x=0, y=3, radius=40,
                 pass_time=7, start=0.5, gain=0, send=0),
            dict(kind="bass", name="Bass string", motion="Static", x=-1.5, y=1, gain=-3, send=0),
        ]),
    dict(
        id="strings", label="Orbiting strings", length=16,
        blurb="An arpeggio circles your head in a small room, with a ping-pong echo.",
        room=dict(enabled=True, width=14, depth=11, absorption=0.25),
        reverb=dict(enabled=True, t60=3.0, damping=0.25, level_db=-8),
        delay=dict(enabled=True, time=0.375, feedback=0.5, level_db=-9),
        sources=[
            dict(kind="arpeggio", name="Arpeggio", motion="Orbit", x=0, y=0, radius=3.5,
                 speed=0.08, send=0.35),
            dict(kind="drone", name="Drone", motion="Static", x=0, y=5, gain=-4, send=0.6),
        ]),
    dict(
        id="cathedral", label="Distant cathedral", length=14,
        blurb="Bells drift in a huge, dark space with a seven-second reverb tail.",
        room=dict(enabled=True, width=40, depth=30, absorption=0.1),
        reverb=dict(enabled=True, t60=7.0, damping=0.4, size=1.8, predelay=0.06, level_db=-3),
        delay=dict(enabled=False),
        sources=[
            dict(kind="bells", name="Bells", motion="Spiral", x=0, y=0, radius=14, speed=0.05,
                 send=0.8, air=2),
        ]),
    dict(
        id="sketch", label="Composition sketch", length=26,
        blurb="Five layers enter one by one, then a fly-by marks the climax.",
        room=dict(enabled=True, width=16, depth=12, absorption=0.3),
        reverb=dict(enabled=True, t60=4.0, damping=0.3, level_db=-6),
        delay=dict(enabled=True, time=0.45, feedback=0.55, level_db=-10),
        sources=[
            dict(kind="drone", name="Drone", motion="Static", x=0, y=6, gain=-6, send=0.8),
            dict(kind="arpeggio", name="Arpeggio A", motion="Orbit", x=0, y=0, radius=4,
                 speed=0.07, start=6, send=0.4),
            dict(kind="counter", name="Counter-melody B", motion="Orbit", x=0, y=0, radius=4,
                 speed=-0.05, start=12, send=0.5),
            dict(kind="ticks", name="Ticks", motion="Oscillate", x=0, y=2, radius=5, speed=0.2,
                 start=18, gain=-8, send=0.2),
            dict(kind="note", name="Fly-by pluck", motion="Flyby", x=0, y=3, radius=25,
                 pass_time=5, start=22, send=0.3),
        ]),
]

# --------------------------------------------------------------------------- #
# Sound generation / loading
# --------------------------------------------------------------------------- #

_audio_cache: dict = {}
_cache_lock = threading.Lock()
_uploads: dict[str, tuple[Path, str]] = {}
_upload_dir = Path(tempfile.mkdtemp(prefix="echo_uploads_"))


def make_audio(kind: str, arg: str = ""):
    """Return (audio_or_path, display_name) for a sound kind. Cached."""
    key = (kind, arg)
    with _cache_lock:
        if key in _audio_cache:
            return _audio_cache[key]
    if kind == "arpeggio":
        notes = [(i * 0.25, p, 2.0) for i, p in enumerate(ARP * 4)]
        out = sources.pluck_line(notes, t60=2.0, damping=0.4, pick_position=0.2)
    elif kind == "counter":
        base = ["E4", "A4", "C5", "D5", "G4"]
        out = sources.pluck_line([(i * 0.45, base[i % 5], 2.0) for i in range(20)],
                                 t60=3.0, damping=0.5)
    elif kind == "drone":
        out = sources.pluck_line([(0, "A1", 12.0), (12, "F1", 12.0), (24, "E1", 10.0)], t60=30.0)
    elif kind == "bells":
        out = sources.pluck_line([(0, "E3", 6), (2.5, "B3", 6), (5, "G4", 6), (7.5, "E4", 6)],
                                 t60=5.0, damping=0.25, pick_position=0.12)
    elif kind == "ticks":
        out = sources.noise_bursts([i * 0.2 for i in range(60)], length=0.06)
    elif kind == "bass":
        out = sources.pluck_line([(i * 0.5, n, 1.5) for i, n in enumerate(["A2", "E3", "A3", "C4"] * 4)],
                                 t60=1.5, damping=0.5)
    elif kind == "note":
        out = sources.pluck_line([(0, "A3", 4)], t60=4.0)
    elif kind == "file":
        if arg not in _uploads:
            raise ValueError("That uploaded file is no longer available. Upload it again.")
        out = str(_uploads[arg][0])
    elif kind == "freesound":
        from pyquist.web.freesound import fetch_freesound
        sample, _meta = fetch_freesound(int(arg))
        out = sample
    else:
        raise ValueError(f"Unknown sound type '{kind}'.")
    with _cache_lock:
        _audio_cache[key] = (out, kind)
    return out, kind


# --------------------------------------------------------------------------- #
# Settings (JSON from the page) -> engine objects
# --------------------------------------------------------------------------- #


def _num(d, k, default, lo=None, hi=None):
    try:
        v = float(d.get(k, default))
    except (TypeError, ValueError):
        v = float(default)
    if not math.isfinite(v):
        v = float(default)
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def build_motion(s: dict):
    x, y = _num(s, "x", 0, -60, 60), _num(s, "y", 0, -60, 60)
    r, sp = _num(s, "radius", 4, 0.1, 100), _num(s, "speed", 0.08, -2, 2)
    m = s.get("motion", "Static")
    if m == "Orbit":
        return Orbit(cx=x, cy=y, radius=r, speed=sp)
    if m == "Spiral":
        return Spiral(cx=x, cy=y, r_min=0.25 * r, r_max=r, speed=sp)
    if m == "Oscillate":
        return Oscillate(cx=x, cy=y, amplitude=r, speed=sp)
    if m == "Flyby":
        return Flyby(x0=x - r, y0=y, x1=x + r, y1=y,
                     duration=_num(s, "pass_time", 6, 0.5, 120), start=_num(s, "start", 0, 0, 90))
    return Static(x, y)


def build_echo(state: dict) -> tuple[Echo, float]:
    e = Echo()
    room, rv, dl = state.get("room", {}), state.get("reverb", {}), state.get("delay", {})
    e.room = Room(width=_num(room, "width", 12, 4, 80), depth=_num(room, "depth", 10, 4, 80),
                  absorption=_num(room, "absorption", 0.35, 0, 1), enabled=bool(room.get("enabled", True)))
    e.reverb = ReverbSettings(
        enabled=bool(rv.get("enabled", True)),
        kind="schroeder" if rv.get("kind") == "schroeder" else "fdn",
        t60=_num(rv, "t60", 2.5, 0.2, 12), damping=_num(rv, "damping", 0.25, 0, 0.5),
        size=_num(rv, "size", 1.0, 0.3, 3), predelay=_num(rv, "predelay", 0.02, 0, 0.3),
        level_db=_num(rv, "level_db", -6, -40, 12))
    e.delay = DelaySettings(
        enabled=bool(dl.get("enabled", False)), time=_num(dl, "time", 0.375, 0.02, 2),
        feedback=_num(dl, "feedback", 0.45, 0, 0.95), level_db=_num(dl, "level_db", -8, -40, 12))
    for s in state.get("sources", [])[:MAX_SOURCES]:
        kind = s.get("kind", "")
        audio, _ = make_audio(kind, str(s.get("arg", "")))
        e.add_source(
            audio, name=str(s.get("name", kind))[:60], motion=build_motion(s),
            gain_db=_num(s, "gain", 0, -40, 12), send=_num(s, "send", 0.3, 0, 1),
            start=_num(s, "start", 0, 0, 90), loop=KIND_BY_ID.get(kind, {}).get("loop", True),
            prop=Propagation(doppler=_num(s, "doppler", 1, 0, 4), rolloff=_num(s, "rolloff", 1, 0, 3),
                             air_absorption=_num(s, "air", 1, 0, 6), head_shadow=_num(s, "shadow", 1, 0, 1)))
    return e, _num(state, "length", 16, 3, 90)


def scene_paths(state: dict) -> dict:
    """The (x, y) path of every sound over the render length, for the map."""
    length = _num(state, "length", 16, 3, 90)
    n = int(min(1800, max(300, length * 25)))
    t = np.linspace(0, length, n)
    out = {}
    for i, s in enumerate(state.get("sources", [])[:MAX_SOURCES]):
        x, y = build_motion(s)(t)
        out[str(s.get("id", i))] = dict(x=np.round(x, 3).tolist(), y=np.round(y, 3).tolist())
    return dict(length=length, paths=out)


# --------------------------------------------------------------------------- #
# HTTP server
# --------------------------------------------------------------------------- #

_render_lock = threading.Lock()
_last_render = None          # previous render's samples, to report how much a change mattered


def _load_check(kind: str, arg: str) -> dict:
    audio, _ = make_audio(kind, arg)
    e = Echo()
    src = e.add_source(audio, "probe")
    return dict(ok=True, seconds=round(len(src.audio) / e.fs, 2))


class Handler(BaseHTTPRequestHandler):
    server_version = "ECHO/1.0"

    def log_message(self, *a):            # keep the terminal quiet
        pass

    # --- helpers
    def _send(self, code, body: bytes, ctype="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, str(v))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode())

    def _error(self, msg, code=400):
        self._json({"error": msg}, code)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_UPLOAD:
            raise ValueError("That file is larger than 100 MB.")
        return self.rfile.read(n)

    # --- routes
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, (WEB_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/catalog":
            self._json(dict(kinds=KINDS, presets=PRESETS))
        else:
            self._error("Not found", 404)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/scene":
                self._json(scene_paths(json.loads(self._body())))
            elif path == "/api/render":
                self._render(json.loads(self._body()))
            elif path == "/api/upload":
                self._upload()
            elif path == "/api/probe":
                d = json.loads(self._body())
                self._json(_load_check(d.get("kind", ""), str(d.get("arg", ""))))
            else:
                self._error("Not found", 404)
        except Exception as exc:          # noqa: BLE001  - report every failure to the page
            self._error(f"{type(exc).__name__}: {exc}" if not isinstance(exc, ValueError) else str(exc))

    def _render(self, state):
        with _render_lock:
            t0 = time.time()
            e, length = build_echo(state)
            if not e.sources:
                raise ValueError("Add at least one sound first.")
            raw = e.render(length, normalize=False)
            # Fixed make-up gain (+12 dB) instead of peak-normalising, so changing a sound's Volume or
            # the reverb level really changes how loud the result is. Only scales down if it would clip.
            y = raw.samples * 4.0
            peak = float(np.abs(y).max())
            if peak > 0.95:
                y = y * (0.95 / peak)
            audio = pq.Audio(y.astype(np.float32), e.fs)
            global _last_render
            change = ""
            if _last_render is not None:
                n = min(len(_last_render), len(y))
                ref = float(np.sqrt(np.mean(_last_render[:n] ** 2))) + 1e-12
                change = f"{float(np.sqrt(np.mean((y[:n] - _last_render[:n]) ** 2))) / ref:.4f}"
            _last_render = y.astype(np.float32)
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "echo.wav"
                audio.write(str(p))
                data = p.read_bytes()
        self._send(200, data, "audio/wav",
                   {"X-Duration": f"{audio.duration:.2f}", "X-Render-Seconds": f"{time.time() - t0:.1f}",
                    "X-Change": change})

    def _upload(self):
        name = Path(parse_qs(urlparse(self.path).query).get("name", ["audio"])[0]).name or "audio"
        suffix = Path(name).suffix.lower() or ".wav"
        uid = uuid.uuid4().hex[:10]
        dest = _upload_dir / f"{uid}{suffix}"
        dest.write_bytes(self._body())
        _uploads[uid] = (dest, name)
        try:
            info = _load_check("file", uid)
        except Exception:                # noqa: BLE001
            _uploads.pop(uid, None)
            dest.unlink(missing_ok=True)
            raise ValueError("Couldn't read that file. Try a WAV, FLAC or MP3.")
        self._json(dict(id=uid, name=name, seconds=info["seconds"]))


def _make_server(port: int) -> ThreadingHTTPServer:
    last = None
    for p in range(port, port + 20):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            srv.daemon_threads = True
            return srv
        except OSError as exc:
            last = exc
    raise RuntimeError(f"No free port between {port} and {port + 19}: {last}")


def launch(port: int = 8765, open_browser: bool = True) -> None:
    """Run the control panel until Ctrl+C."""
    srv = _make_server(port)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"\n  ECHO is running at {url}\n  Use headphones. Press Ctrl+C here to stop.\n")
    if open_browser:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  ECHO stopped.")
    finally:
        srv.server_close()


def serve_background(port: int = 8765) -> str:
    """Start the panel in a background thread (for Jupyter) and return its URL."""
    srv = _make_server(port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}/"
