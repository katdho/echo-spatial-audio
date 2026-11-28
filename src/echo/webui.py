"""webui.py: Browser interface for ECHO

Module connects the browser control panel to the audio engine. It runs a
local HTTP server that serves the UI, converts its JSON settings into an Echo
scene, and returns rendered stereo audio.

The browser handles controls and visualization; audio generation and DSP are
handled by sources.py, spatial.py, and engine.py.

Run from src/ with:
    python app.py

Endpoints:
    GET  /              Serve the control panel.
    GET  /api/catalog   Return available sounds and demo scenes.
    POST /api/scene     Return source trajectories for the scene map.
    POST /api/render    Render a scene and return stereo WAV audio.
    POST /api/upload    Upload an audio file.
    POST /api/probe     Check whether a sound can be loaded.
"""

from __future__ import annotations
import json
import math
import tempfile
import threading
import time
import uuid
import webbrowser
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import numpy as np
import pyquist as pq
from . import sources
from .automation import INTERPOLATIONS, PolarPath, Curve, KeyframePath
from .engine import DelaySettings, Echo, ReverbSettings
from .spatial import Flyby, Orbit, Oscillate, Propagation, Room, Spiral, Static

WEB_DIR = Path(__file__).parent / "web"
MAX_UPLOAD = 100*1024*1024
MAX_SOURCES = 12
MAX_KEYFRAMES = 256

# Explicit content types for the web files. Python's mimetypes module reads the
# operating system's registry, which can report the wrong type for .css or .js
# (notably on Windows), and browsers refuse to apply a stylesheet that is not
# served as text/css.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg":  "image/svg+xml",
    ".png":  "image/png",
    ".ico":  "image/x-icon",
}

def _approach_circle_recede(length=24.0, step=0.5):
    """Keyframes (t, x, y) for the 'Automation' demo: in from the left, one lap, out behind.
    Sampled from the same PolarPath as demo.py's demo 5, so the panel and the script agree"""
    path = PolarPath(
        distance=Curve([(0, 14), (8, 2.5), (16, 2.5), (24, 16)], "smoothstep"),
        azimuth=Curve([(0, 270), (8, 360), (16, 720), (24, 900)]))
    t = np.arange(0.0, length + step/2, step)
    x, y = path(t)
    return [[float(a), round(float(b), 3), round(float(c), 3)] for a, b, c in zip(t, x, y)]


ARP = ["A3", "C4", "D4", "E4", "G4", "A4", "E4", "D4"]
KINDS = [
    dict(id="arpeggio",
        label="Plucked arpeggio",
        loop=True,
        blurb="A guitar-like string playing a rising pattern.",
        defaults=dict(motion="Orbit", x=0, y=0, radius=3.5, speed=0.08, send=0.35)),
    dict(id="counter",
        label="Counter-melody",
        loop=True,
        blurb="Higher plucks that pair well with the arpeggio.",
        defaults=dict(motion="Orbit", x=0, y=0, radius=4, speed=-0.05, send=0.5)),
    dict(id="drone",
        label="Low drone",
        loop=True,
        blurb="A long, deep string note that fills the room.",
        defaults=dict(motion="Static", x=0, y=6, gain=-6, send=0.8)),
    dict(id="bells",
        label="Bell-like plucks",
        loop=True,
        blurb="Slow, ringing notes. Great with a big reverb.",
        defaults=dict(motion="Spiral", x=0, y=0, radius=14, speed=0.05, send=0.8, air=2)),
    dict(id="ticks",
        label="Noise ticks",
        loop=True,
        blurb="Short clicks. The easiest sound for hearing motion.",
        defaults=dict(motion="Oscillate", x=0, y=2, radius=5, speed=0.2, gain=-4, send=0.2)),
    dict(id="bass",
        label="Bass string pattern",
        loop=True,
        blurb="A steady low pattern that anchors a scene.",
        defaults=dict(motion="Static", x=-1.5, y=1, gain=-3, send=0.0)),
    dict(id="note",
        label="Single pluck",
        loop=False,
        blurb="One long note, played once. Good for a fly-by.",
        defaults=dict(motion="Flyby", x=0, y=3, radius=25, pass_time=5, send=0.3)),
    dict(id="file",
        label="Your audio file",
        loop=True,
        hidden=True,
        blurb="A recording you upload.",
        defaults=dict(motion="Orbit", x=0, y=0, radius=3.5, speed=0.08, send=0.3)),
    dict(id="freesound",
        label="Freesound sound",
        loop=True,
        hidden=True,
        blurb="A sound fetched by Freesound id.",
        defaults=dict(motion="Orbit", x=0, y=0, radius=3.5, speed=0.08, send=0.3))
]
KIND_BY_ID = {kind["id"]: kind for kind in KINDS}
PRESETS = [
    dict(id="doppler",
        label="Doppler fly-by",
        length=8,
        blurb="A ticking sound races past you. Listen for the pitch dropping as it leaves.",
        room=dict(enabled=False),
        reverb=dict(enabled=False),
        delay=dict(enabled=False),
        sources=[
            dict(kind="ticks", name="Fly-by ticks", motion="Flyby",
                x=0, y=3, radius=40, pass_time=7, start=0.5, gain=0, send=0),
            dict(kind="bass", name="Bass string", motion="Static",
                x=-1.5, y=1, gain=-3, send=0)]),
    dict(id="strings",
        label="Orbiting strings",
        length=16,
        blurb="An arpeggio circles your head in a small room, with a ping-pong echo.",
        room=dict(enabled=True, width=14, depth=11, absorption=0.25),
        reverb=dict(enabled=True, t60=3.0, damping=0.25, level_db=-8),
        delay=dict(enabled=True, time=0.375, feedback=0.5, level_db=-9),
        sources=[
            dict(kind="arpeggio", name="Arpeggio", motion="Orbit",
                x=0, y=0, radius=3.5, speed=0.08, send=0.35),
            dict(kind="drone", name="Drone", motion="Static",
                x=0, y=5, gain=-4, send=0.6)]),
    dict(id="cathedral",
        label="Distant cathedral",
        length=14,
        blurb="Bells drift in a huge, dark space with a seven-second reverb tail.",
        room=dict(enabled=True, width=40, depth=30, absorption=0.1),
        reverb=dict(enabled=True, t60=7.0, damping=0.4, size=1.8,
            predelay=0.06, level_db=-3),
        delay=dict(enabled=False),
        sources=[dict(kind="bells", name="Bells", motion="Spiral",
                x=0, y=0, radius=14, speed=0.05, send=0.8, air=2)]),
    dict(id="sketch",
        label="Composition sketch",
        length=26,
        blurb="Five layers enter one by one, then a fly-by marks the climax.",
        room=dict(enabled=True, width=16, depth=12, absorption=0.3),
        reverb=dict(enabled=True, t60=4.0, damping=0.3, level_db=-6),
        delay=dict(enabled=True, time=0.45, feedback=0.55, level_db=-10),
        sources=[
            dict(kind="drone", name="Drone", motion="Static",
                x=0, y=6, gain=-6, send=0.8),
            dict(kind="arpeggio", name="Arpeggio A", motion="Orbit",
                x=0, y=0, radius=4, speed=0.07, start=6, send=0.4),
            dict(kind="counter", name="Counter-melody B", motion="Orbit",
                x=0, y=0, radius=4, speed=-0.05, start=12, send=0.5),
            dict(kind="ticks", name="Ticks", motion="Oscillate",
                x=0, y=2, radius=5, speed=0.2, start=18, gain=-8, send=0.2),
            dict(kind="note", name="Fly-by pluck", motion="Flyby",
                x=0, y=3, radius=25, pass_time=5, start=22, send=0.3)]),
    dict(id="automation",
        label="Automation: approach and recede",
        length=24,
        blurb="One string arrives, circles you once, then drifts away into the reverb. Its volume, reverb and position all follow keyframes.",
        room=dict(enabled=True, width=18, depth=14, absorption=0.25),
        reverb=dict(enabled=True, t60=4.0, damping=0.3, level_db=-6),
        delay=dict(enabled=True, time=0.375, feedback=0.25, level_db=-10),
        # scene-level keyframes: the echo's repeats open up for the last bars
        automation=dict(delay_feedback=[[0, 0.25], [14, 0.25, "smoothstep"], [22, 0.75]]),
        sources=[
            dict(kind="arpeggio", name="Keyframed arpeggio", motion="Static",
                x=0, y=0, gain=0, send=0.1,
                path=_approach_circle_recede(),
                automation=dict(
                    gain=[[0, -24, "smoothstep"], [8, 0, "smoothstep"], [16, 0, "smoothstep"], [24, -10]],
                    send=[[0, 0.1, "smoothstep"], [12, 0.1, "smoothstep"], [24, 0.9]])),
            dict(kind="drone", name="Drone", motion="Static",
                x=0, y=6, gain=-8, send=0.6)]),
]

_audio_cache: dict = {}
_cache_lock = threading.Lock()
_uploads: dict[str, tuple[Path, str]] = {}
_upload_dir = Path(tempfile.mkdtemp(prefix="echo_uploads_"))

def make_audio(kind: str, arg: str = ""):
    """Load or generate a sound and return it with its display name

    Generated sounds are cached by sound kind and argument. Uploaded files
    are resolved from their temporary upload IDs; Freesound sounds are
    fetched by ID
    """
    key = (kind, arg)
    with _cache_lock:
        if key in _audio_cache:
            return _audio_cache[key]
        
    if kind == "arpeggio":
        notes = [(i*0.25, pitch, 2.0) for i, pitch in enumerate(ARP*4)]
        audio = sources.pluck_line(notes, t60=2.0, damping=0.4, pick_position=0.2)
    elif kind == "counter":
        pattern = ["E4", "A4", "C5", "D5", "G4"]
        notes = [(i*0.45, pattern[i%len(pattern)], 2.0) for i in range(20)]
        audio = sources.pluck_line(notes, t60=3.0, damping=0.5)
    elif kind == "drone":
        notes = [(0, "A1", 12.0), (12, "F1", 12.0), (24, "E1", 10.0)]
        audio = sources.pluck_line(notes, t60=30.0)
    elif kind == "bells":
        notes = [(0, "E3", 6), (2.5, "B3", 6), (5, "G4", 6), (7.5, "E4", 6)]
        audio = sources.pluck_line(notes, t60=5.0, damping=0.25, pick_position=0.12)
    elif kind == "ticks":
        audio = sources.noise_bursts([i*0.2 for i in range(60)], length=0.06,)
    elif kind == "bass":
        pattern = ["A2", "E3", "A3", "C4"]*4
        notes = [(i*0.5, pitch, 1.5) for i, pitch in enumerate(pattern)]
        audio = sources.pluck_line(notes, t60=1.5, damping=0.5)
    elif kind == "note":
        audio = sources.pluck_line([(0, "A3", 4)], t60=4.0)
    elif kind == "file":
        if arg not in _uploads:
            raise ValueError("That uploaded file is no longer available. Upload it again.")
        audio = str(_uploads[arg][0])
    elif kind == "freesound":
        from pyquist.web.freesound import fetch_freesound
        audio, _metadata = fetch_freesound(int(arg))
    else:
        raise ValueError(f"Unknown sound type '{kind}'.")

    result = (audio, kind)
    with _cache_lock:
        _audio_cache[key] = result
    return result

def _num(settings, key, default, lo=None, hi=None):
    """Read a finite numeric setting and clamp it to an optional range"""
    try:
        value = float(settings.get(key, default))
    except (TypeError, ValueError):
        value = float(default)

    if not math.isfinite(value):
        value = float(default)
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


def _points(raw, limits):
    """Clean JSON keyframes [[time, v1, ..., (shape)], ...] from the browser

    `limits` has one (low, high) pair per value after the time. Rows that aren't
    lists of finite numbers are dropped (like _num, bad input never raises)
    """
    out = []
    if not isinstance(raw, list):
        return out
    k = 1 + len(limits)
    for row in raw[:MAX_KEYFRAMES]:
        if not isinstance(row, (list, tuple)) or len(row) < k:
            continue
        try:
            nums = [float(v) for v in row[:k]]
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(v) for v in nums):
            continue
        shape = row[k] if len(row) > k and row[k] in INTERPOLATIONS else None
        values = [min(max(v, lo), hi) for v, (lo, hi) in zip(nums[1:], limits)]
        out.append((min(max(nums[0], 0.0), 600.0), *values, shape))
    return out


# panel field -> (library parameter, low, high); limits match the _num calls in build_echo
_SOURCE_CURVES = {"gain": ("gain_db", -40, 12), "send": ("send", 0, 1), "doppler": ("doppler", 0, 4)}


def build_source_automation(settings: dict) -> dict:
    """Source `automation` from the browser: {"gain": [[t, dB(, shape)], ...], "send": ..., "doppler": ...}"""
    raw = settings.get("automation")
    curves = {}
    if isinstance(raw, dict):
        for key, (name, lo, hi) in _SOURCE_CURVES.items():
            pts = _points(raw.get(key), [(lo, hi)])
            if pts:
                curves[name] = Curve(pts)
    return curves


def build_scene_automation(state: dict) -> dict:
    """Scene `automation` from the browser: {"delay_feedback": [[t, 0..0.95(, shape)], ...]}"""
    raw = state.get("automation")
    pts = _points(raw.get("delay_feedback"), [(0, 0.95)]) if isinstance(raw, dict) else []
    return {"delay_feedback": Curve(pts)} if pts else {}


def build_motion(settings: dict):
    """Create a source trajectory from its browser settings

    A `path` of [[t, x, y(, shape)], ...] keyframes overrides the movement pattern
    """
    path = _points(settings.get("path"), [(-60, 60), (-60, 60)])
    if path:
        return KeyframePath.from_points(path)
    x = _num(settings, "x", 0, -60, 60)
    y = _num(settings, "y", 0, -60, 60)
    radius = _num(settings, "radius", 4, 0.1, 100)
    speed = _num(settings, "speed", 0.08, -2, 2)
    motion = settings.get("motion", "Static")

    if motion == "Orbit":
        return Orbit(cx=x, cy=y, radius=radius, speed=speed)
    if motion == "Spiral":
        return Spiral(
            cx=x,
            cy=y,
            r_min=0.25*radius,
            r_max=radius,
            speed=speed,
        )
    if motion == "Oscillate":
        return Oscillate(cx=x, cy=y, amplitude=radius, speed=speed)
    if motion == "Flyby":
        return Flyby(
            x0=x - radius,
            y0=y,
            x1=x + radius,
            y1=y,
            duration=_num(settings, "pass_time", 6, 0.5, 120),
            start=_num(settings, "start", 0, 0, 90))
    return Static(x, y)


def build_echo(state: dict) -> tuple[Echo, float]:
    """Build an Echo engine and render duration from browser scene settings."""
    engine = Echo()
    room = state.get("room", {})
    reverb = state.get("reverb", {})
    delay = state.get("delay", {})

    engine.room = Room(
        width=_num(room, "width", 12, 4, 80),
        depth=_num(room, "depth", 10, 4, 80),
        absorption=_num(room, "absorption", 0.35, 0, 1),
        enabled=bool(room.get("enabled", True)))

    engine.reverb = ReverbSettings(
        enabled=bool(reverb.get("enabled", True)),
        kind="schroeder" if reverb.get("kind") == "schroeder" else "fdn",
        t60=_num(reverb, "t60", 2.5, 0.2, 12),
        damping=_num(reverb, "damping", 0.25, 0, 0.5),
        size=_num(reverb, "size", 1.0, 0.3, 3),
        predelay=_num(reverb, "predelay", 0.02, 0, 0.3),
        level_db=_num(reverb, "level_db", -6, -40, 12))

    engine.delay = DelaySettings(
        enabled=bool(delay.get("enabled", False)),
        time=_num(delay, "time", 0.375, 0.02, 2),
        feedback=_num(delay, "feedback", 0.45, 0, 0.95),
        level_db=_num(delay, "level_db", -8, -40, 12))

    engine.automation = build_scene_automation(state)

    for settings in state.get("sources", [])[:MAX_SOURCES]:
        kind = settings.get("kind", "")
        audio, _ = make_audio(kind, str(settings.get("arg", "")))
        engine.add_source(
            audio,
            name=str(settings.get("name", kind))[:60],
            motion=build_motion(settings),
            gain_db=_num(settings, "gain", 0, -40, 12),
            send=_num(settings, "send", 0.3, 0, 1),
            start=_num(settings, "start", 0, 0, 90),
            loop=KIND_BY_ID.get(kind, {}).get("loop", True),
            automation=build_source_automation(settings),
            prop=Propagation(
                doppler=_num(settings, "doppler", 1, 0, 4),
                rolloff=_num(settings, "rolloff", 1, 0, 3),
                air_absorption=_num(settings, "air", 1, 0, 6),
                head_shadow=_num(settings, "shadow", 1, 0, 1),
            ))
    length = _num(state, "length", 16, 3, 90)
    return engine, length


def scene_paths(state: dict) -> dict:
    """Sample each source trajectory for display on the browser's scene map."""
    length = _num(state, "length", 16, 3, 90)
    num_samples = int(min(1800, max(300, length*25)))
    times = np.linspace(0, length, num_samples)
    paths = {}

    for i, settings in enumerate(state.get("sources", [])[:MAX_SOURCES]):
        x, y = build_motion(settings)(times)
        source_id = str(settings.get("id", i))
        paths[source_id] = {
            "x": np.round(x, 3).tolist(),
            "y": np.round(y, 3).tolist()}
    return {"length": length, "paths": paths}


_render_lock = threading.Lock()
_last_render = None

def _load_check(kind: str, arg: str) -> dict:
    """Verify that a sound can be loaded and return its duration"""
    audio, _ = make_audio(kind, arg)
    engine = Echo()
    source = engine.add_source(audio, "probe")

    return {
        "ok": True,
        "seconds": round(len(source.audio)/engine.fs, 2),
    }

class Handler(BaseHTTPRequestHandler):
    """Handle requests from the ECHO browser control panel"""
    server_version = "ECHO/1.0"

    def log_message(self, *args):
        """Suppress the default per-request terminal output"""
        pass

    def _send(self, code, body: bytes, ctype="application/json", extra=None):
        """Send an HTTP response with its content type and optional headers"""
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, str(value))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        """Serialize and send a JSON response"""
        self._send(code, json.dumps(obj).encode())

    def _error(self, message, code=400):
        """Send an error message as JSON"""
        self._json({"error": message}, code)

    def _body(self) -> bytes:
        """Read the request body, rejecting payloads larger than the upload limit"""
        size = int(self.headers.get("Content-Length") or 0)

        if size > MAX_UPLOAD:
            raise ValueError("That file is larger than 100 MB")

        return self.rfile.read(size)

    def do_GET(self):
        """Serve the control panel, static assets, or sound catalog."""
        path = urlparse(self.path).path
        if path == "/api/catalog":
            self._json({"kinds": KINDS, "presets": PRESETS})
            return

        if path in ("/", "/index.html"):
            file_path = WEB_DIR / "index.html"
        else:
            file_path = (WEB_DIR / path.lstrip("/")).resolve()
            try:
                file_path.relative_to(WEB_DIR.resolve())
            except ValueError:
                self._error("Not found", 404)
                return

        if not file_path.is_file():
            self._error("Not found", 404)
            return

        content_type = CONTENT_TYPES.get(
            file_path.suffix.lower(),
            mimetypes.guess_type(str(file_path))[0] or "application/octet-stream")
        self._send(200, file_path.read_bytes(), content_type)

    def do_POST(self):
        """Handle scene, render, upload, and sound-check requests"""
        path = urlparse(self.path).path

        try:
            if path == "/api/scene":
                self._json(scene_paths(json.loads(self._body())))
            elif path == "/api/render":
                self._render(json.loads(self._body()))
            elif path == "/api/upload":
                self._upload()
            elif path == "/api/probe":
                settings = json.loads(self._body())
                self._json(
                    _load_check(
                        settings.get("kind", ""),
                        str(settings.get("arg", ""))))
            else:
                self._error("Not found", 404)
        except Exception as exc:  
            message = (
                str(exc)
                if isinstance(exc, ValueError)
                else f"{type(exc).__name__}: {exc}")
            self._error(message)

    def _render(self, state):
        """Build a scene, render it, and return the resulting WAV file"""
        with _render_lock:
            start_time = time.time()
            engine, length = build_echo(state)
            if not engine.sources:
                raise ValueError("Add at least one sound first")
            raw = engine.render(length, normalize=False)
            samples = raw.samples*4.0
            peak = float(np.abs(samples).max())
            if peak > 0.95: 
                samples *= 0.95/peak
            audio = pq.Audio(samples.astype(np.float32), engine.fs)
            global _last_render
            change = ""
            if _last_render is not None:
                n = min(len(_last_render), len(samples))
                reference_rms = float(
                    np.sqrt(np.mean(_last_render[:n] ** 2))) + 1e-12
                difference_rms = float(
                    np.sqrt(np.mean((samples[:n] - _last_render[:n]) ** 2)))
                change = f"{difference_rms / reference_rms:.4f}"
            _last_render = samples.astype(np.float32)
            with tempfile.TemporaryDirectory() as directory:
                wav_path = Path(directory) / "echo.wav"
                audio.write(str(wav_path))
                data = wav_path.read_bytes()
        self._send(200, data, "audio/wav",
            {"X-Duration": f"{audio.duration:.2f}",
             "X-Render-Seconds": f"{time.time() - start_time:.1f}",
             "X-Change": change})

    def _upload(self):
        """Save an uploaded audio file and verify that the engine can read it"""
        query = parse_qs(urlparse(self.path).query)
        name = Path(query.get("name", ["audio"])[0]).name or "audio"
        suffix = Path(name).suffix.lower() or ".wav"
        upload_id = uuid.uuid4().hex[:10]
        destination = _upload_dir / f"{upload_id}{suffix}"
        destination.write_bytes(self._body())
        _uploads[upload_id] = (destination, name)

        try:
            info = _load_check("file", upload_id)
        except Exception:  
            _uploads.pop(upload_id, None)
            destination.unlink(missing_ok=True)
            raise ValueError("Couldn't read that file. Try a WAV, FLAC or MP3.")
        self._json({
            "id": upload_id,
            "name": name,
            "seconds": info["seconds"]})

def _make_server(port: int, host: str = "127.0.0.1", 
                    find_free_port: bool = True) -> ThreadingHTTPServer:
    """Create the HTTP server
    Local development can try the next 19 ports if needed.
    Deployment binds directly to the assigned port
    """
    ports = range(port, port+20) if find_free_port else (port,)
    last_error = None
    for candidate_port in ports:
        try:
            server = ThreadingHTTPServer((host, candidate_port), Handler)
            server.daemon_threads = True
            return server
        except OSError as exc:
            last_error = exc
    if find_free_port:
        raise RuntimeError(f"No free port between {port} and {port+19}: {last_error}")
    raise RuntimeError(f"Could not start ECHO on {host}:{port}: {last_error}")


def launch(port: int = 8765, open_browser: bool = True, host: str = "127.0.0.1",
            find_free_port: bool = True) -> None:
    """Run the control panel until interrupted w/ Ctrl+C"""
    server = _make_server(port, host, find_free_port)
    actual_port = server.server_address[1]

    if host == "0.0.0.0":
        print(f"\n  ECHO is listening on {host}:{actual_port}\n")
    else:
        url = f"http://127.0.0.1:{actual_port}/"
        print(f"\n  ECHO is running at {url}\n"
                "  Use headphones. Press Ctrl+C here to stop.\n")
        if open_browser:
            threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: print("\n  ECHO stopped.")
    finally:server.server_close()

def serve_background(port: int = 8765) -> str:
    """Start the control panel in a background thread and return its URL."""
    server = _make_server(port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}/"
