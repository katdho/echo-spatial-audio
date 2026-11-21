"""Sanity tests for ECHO's DSP:  python tests.py
Each test checks a block-vectorized routine against the notes' literal
per-sample recurrence, or checks a physical property (Doppler, ITD, T60)."""
import time

import numpy as np

from echo import dsp
from echo.spatial import C_SOUND, HEAD, Flyby, Propagation, Static, propagate

FS = 44100
rng = np.random.default_rng(1)


def dominant_freq(x, fs=FS):
    X = np.abs(np.fft.rfft(x * np.hanning(len(x)), 8 * len(x)))
    return np.argmax(X) * fs / (8 * len(x))


def test_feedback_delay_matches_notes():
    def notes_version(x, M, g):                      # pcm-13 circular buffer
        buf, i, y = np.zeros(M), 0, np.zeros(len(x))
        for n in range(len(x)):
            y[n] = x[n] + g * buf[i]
            buf[i] = y[n]
            i = (i + 1) % M
        return y
    x = rng.standard_normal(5000)
    for M, g in [(7, 0.9), (441, 0.7), (1000, 0.95)]:
        assert np.allclose(notes_version(x, M, g), dsp.feedback_delay(x, M, g))


def test_allpass_is_flat():
    h = dsp.allpass(np.r_[1.0, np.zeros(44099)], 441, 0.7)
    mag = np.abs(np.fft.rfft(h))
    assert 0.99 < mag.min() and mag.max() < 1.01


def test_one_pole_matches_loop():
    x = rng.standard_normal(3000)
    a = 0.1 + 0.5 * np.repeat(rng.random(3000 // 64 + 1), 64)[:3000]
    # reference: per-sample loop, a sampled at chunk centres like one_pole()
    ref, z = np.zeros(3000), 0.0
    for c in range(0, 3000, 64):
        ac = np.clip(a[min(c + 32, 2999)], 1e-4, 0.9)
        for n in range(c, min(c + 64, 3000)):
            z = (1 - ac) * z + ac * x[n]
            ref[n] = z
    assert np.allclose(ref, dsp.one_pole(x, a), atol=1e-9)


def test_fractional_delay_integer_and_half():
    x = rng.standard_normal(100)
    assert np.allclose(dsp.fractional_delay(x, np.full(100, 3.0))[3:], x[:-3])
    h = dsp.fractional_delay(x, np.full(100, 2.5))[3:]
    assert np.allclose(h, 0.5 * (x[:-3] + x[1:-2]) if False else 0.5 * (x[1:-2] + x[0:-3]))


def test_pluck_pitch():
    for f0 in (110.0, 261.63, 880.0):
        y = dsp.pluck(f0, 1.0, FS, t60=1.5, rng=np.random.default_rng(0))
        seg = y[2000:20000]                       # pitch = first autocorrelation peak
        ac = np.correlate(seg, seg[:9000], "valid")
        lo, hi = int(FS / (f0 * 1.1)), int(FS / (f0 * 0.9))
        lag = lo + np.argmax(ac[lo:hi])
        # parabolic interpolation for sub-sample lag
        a, b, c = ac[lag - 1], ac[lag], ac[lag + 1]
        lag = lag + 0.5 * (a - c) / (a - 2 * b + c)
        f = FS / lag
        cents = 1200 * np.log2(f / f0)
        assert abs(cents) < 25, (f0, f, cents)


def test_itd_matches_head_width():
    t = np.arange(FS) / FS
    x = np.random.default_rng(3).standard_normal(FS)
    px, py = np.full(FS, 20.0), np.zeros(FS) + 0.01     # far right, 90 degrees
    y = propagate(x, px, py, FS, Propagation(head_shadow=0, air_absorption=0))
    xc = np.correlate(y[1000:20000, 0], y[1000:20000, 1], "full")
    lag = np.argmax(xc) - (19000 - 1)
    expected = HEAD / C_SOUND * FS                      # ~22.5 samples
    assert abs(abs(lag) - expected) < 2.5, (lag, expected)
    assert np.argmax(np.abs(y[:, 1])) <= np.argmax(np.abs(y[:, 0]))   # right ear first


def test_doppler_flyby():
    N = 4 * FS
    t = np.arange(N) / FS
    x = np.sin(2 * np.pi * 1000 * t)
    px, py = Flyby(-30, 2, 30, 2, duration=4.0)(t)
    v = 60.0 / 4.0
    y = propagate(x, px, py, FS, Propagation(doppler=1.0))[:, 0]
    f_in, f_out = dominant_freq(y[int(0.3 * FS):int(1.0 * FS)]), dominant_freq(y[int(3.0 * FS):int(3.7 * FS)])
    assert f_in > 1000 * 1.03 and f_out < 1000 * 0.97, (f_in, f_out)
    # no Doppler when doppler = 0
    y0 = propagate(x, px, py, FS, Propagation(doppler=0.0))[:, 0]
    assert abs(dominant_freq(y0[int(0.3 * FS):int(1.0 * FS)]) - 1000) < 15


def test_fdn_t60():
    for t60 in (1.0, 2.5):
        imp = np.r_[1.0, np.zeros(int(1.5 * t60 * FS))]
        h = dsp.fdn_reverb(imp, t60, damping=0.0, fs=FS)
        e = np.cumsum((h ** 2).sum(axis=1)[::-1])[::-1]           # Schroeder integral
        db = 10 * np.log10(e / e[0] + 1e-30)
        i5, i25 = np.argmax(db < -5), np.argmax(db < -25)
        measured = 3.0 * (i25 - i5) / FS                           # 20 dB slope -> 60 dB
        assert 0.7 * t60 < measured < 1.3 * t60, (t60, measured)
    # damping shortens the tail
    imp = np.r_[1.0, np.zeros(int(3 * FS))]
    assert (dsp.fdn_reverb(imp, 2.0, 0.45)[FS:] ** 2).sum() < (dsp.fdn_reverb(imp, 2.0, 0.0)[FS:] ** 2).sum()


def test_ping_pong_alternates():
    x = np.zeros((FS, 2))
    x[0, 0] = 1.0
    y = dsp.ping_pong(x, 4410, 0.8)
    assert np.isclose(y[4410, 1], 0.8) and np.isclose(y[8820, 0], 0.64)
    assert abs(y[4410, 0]) < 1e-12


def test_web_panel_backend():
    """The browser panel's bridge: every demo scene builds, paths are sane, and a short render is stereo + audible."""
    from echo import webui
    for p in webui.PRESETS:
        st = {"length": 3, "room": p["room"], "reverb": {**p["reverb"], "t60": 0.5},
              "delay": p["delay"], "sources": [dict(s, id=str(i)) for i, s in enumerate(p["sources"])]}
        sc = webui.scene_paths(st)
        assert len(sc["paths"]) == len(p["sources"])
        assert all(len(v["x"]) == len(v["y"]) >= 300 for v in sc["paths"].values())
        e, length = webui.build_echo(st)
        out = e.render(length)
        assert out.samples.shape[1] == 2 and out.peak_amplitude > 0.1, p["id"]
    # junk input is clamped, not fatal
    m = webui.build_motion({"motion": "Orbit", "radius": "nan", "speed": 99, "x": "oops"})
    assert m.speed == 2 and m.cx == 0


def test_speed():
    x = rng.standard_normal(20 * FS)
    t0 = time.time()
    dsp.fdn_reverb(x, 2.5)
    dsp.fractional_delay(x, np.full(len(x), 100.3))
    dsp.one_pole(x, 0.3)
    dt = time.time() - t0
    assert dt < 10, dt
    print(f"   20 s of FDN + delay read + one-pole: {dt:.2f} s")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print("ok  ", fn.__name__)
    print(f"\nall {len(tests)} tests passed")
