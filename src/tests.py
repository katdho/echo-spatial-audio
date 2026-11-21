
"""tests.py: sanity checks for ECHO. Run: python src/tests.py

Each test either checks a fast block-based routine against the course notes'
literal sample-by-sample recurrence, or checks a physical property such as
Doppler, ITD, or T60. Also tests browser integration and DSP performance.

Prints "ok" per test and "all 11 tests passed" at the end
"""

import time
import numpy as np
from echo import dsp
from echo.spatial import (
    C_SOUND, HEAD, Flyby, Propagation, Static, propagate
)

f_s = 44100
rng = np.random.default_rng(1)

def dominant_freq(x, fs=f_s):
    """Estimate the dominant frequency using a zero-padded FFT"""
    X = np.abs(np.fft.rfft(x*np.hanning(len(x)), 8*len(x)))
    return np.argmax(X)*fs/(8*len(x))


def test_feedback_delay_matches_notes():
    """Verify optimized feedback delay matches the course's circular-buffer recurrence"""
    def notes_version(x, M, g): # pcm-13 circular buffer
        buf, i, y = np.zeros(M), 0, np.zeros(len(x))
        for n in range(len(x)):
            y[n] = x[n] + g*buf[i]
            buf[i] = y[n]
            i = (i + 1) % M
        return y

    x = rng.standard_normal(5000)
    for M, g in [(7, 0.9), (441, 0.7), (1000, 0.95)]:
        assert np.allclose(
            notes_version(x, M, g),
            dsp.feedback_delay(x, M, g)
        )


def test_allpass_is_flat():
    """Verify all-pass filter preserves magnitude across all frequencies"""
    h = dsp.allpass(np.r_[1.0, np.zeros(44099)], 441, 0.7)
    mag = np.abs(np.fft.rfft(h))
    assert 0.99 < mag.min() and mag.max() < 1.01


def test_one_pole_matches_loop():
    """Verify block-based one-pole filtering matches the sample-by-sample recurrence"""
    x = rng.standard_normal(3000)
    a = 0.1 + 0.5*np.repeat(rng.random(3000 // 64+1), 64)[:3000]

    ref, z = np.zeros(3000), 0.0
    for c in range(0, 3000, 64):
        ac = np.clip(a[min(c+32, 2999)], 1e-4, 0.9)
        for n in range(c, min(c+64, 3000)):
            z = (1-ac)*z + ac*x[n]
            ref[n] = z

    assert np.allclose(ref, dsp.one_pole(x, a), atol=1e-9)


def test_fractional_delay_integer_and_half():
    """Verify fractional delay handles integer and half-sample delays correctly"""
    x = rng.standard_normal(100)

    # Integer delay should shift the signal by exactly 3 samples
    assert np.allclose(
        dsp.fractional_delay(x, np.full(100, 3.0))[3:],
        x[:-3]
    )
    # Half-sample delay should linearly interpolate neighboring samples
    h = dsp.fractional_delay(x, np.full(100, 2.5))[3:]
    assert np.allclose(h, 0.5*(x[1:-2] + x[0:-3]))


def test_pluck_pitch():
    """Verify synthesized plucked strings produce notes within 25 cents of the target pitch"""
    for f0 in (110.0, 261.63, 880.0):
        y = dsp.pluck(
            f0, 1.0, f_s, t60=1.5,
            rng=np.random.default_rng(0)
        )
        seg = y[2000:20000] # Pitch = 1st autocorrelation peak
        ac = np.correlate(seg, seg[:9000], "valid")
        lo, hi = int(f_s/(f0*1.1)), int(f_s/(f0*0.9))
        lag = lo + np.argmax(ac[lo:hi])

        # Parabolic interpolation for sub-sample lag
        a, b, c = ac[lag-1], ac[lag], ac[lag+1]
        lag = lag + 0.5*(a-c)/(a- 2*b + c)
        f = f_s/lag
        cents = 1200*np.log2(f/f0)
        assert abs(cents) < 25, (f0, f, cents)


def test_itd_matches_head_width():
    """Verify interaural time difference matches the expected delay from head width."""
    t = np.arange(f_s)/f_s
    x = np.random.default_rng(3).standard_normal(f_s)

    # Place source far to the right, ~90 degrees
    px, py = np.full(f_s, 20.0), np.zeros(f_s) + 0.01
    y = propagate(
        x, px, py, f_s,
        Propagation(head_shadow=0, air_absorption=0)
    )

    # Cross-correlate ear signals to measure their relative arrival time
    xc = np.correlate(y[1000:20000, 0], y[1000:20000, 1], "full")
    lag = np.argmax(xc)-(19000-1)

    expected = HEAD/C_SOUND*f_s # ~22.5 samples
    assert abs(abs(lag)-expected)<2.5, (lag, expected)

    # Right ear (channel 1) should receive sound first
    assert np.argmax(np.abs(y[:, 1])) <= np.argmax(np.abs(y[:, 0]))


def test_doppler_flyby():
    """Verify flyby motion shifts pitch up when approaching and down when receding."""
    N = 4*f_s
    t = np.arange(N)/f_s
    x = np.sin(2*np.pi*1000*t)
    px, py = Flyby(-30, 2, 30, 2, duration=4.0)(t)
    y = propagate(x, px, py, f_s, Propagation(doppler=1.0))[:, 0]
    f_in = dominant_freq(y[int(0.3*f_s):int(1.0*f_s)])
    f_out = dominant_freq(y[int(3.0*f_s):int(3.7*f_s)])
    assert f_in > 1000*1.03 and f_out < 1000*0.97, (f_in, f_out)

    # Disabling Doppler should preserve the original pitch
    y0 = propagate(x, px, py, f_s, Propagation(doppler=0.0))[:, 0]
    assert abs(dominant_freq(y0[int(0.3*f_s):int(1.0*f_s)])-1000) < 15


def test_fdn_t60():
    """Verify FDN decay matches the target T60 and damping shortens the reverb tail."""
    for t60 in (1.0, 2.5):
        imp = np.r_[1.0, np.zeros(int(1.5*t60*f_s))]
        h = dsp.fdn_reverb(imp, t60, damping=0.0, fs=f_s)

        # Schroeder integral: remaining energy from each time point onward
        e = np.cumsum((h**2).sum(axis=1)[::-1])[::-1]
        db = 10*np.log10(e/e[0] + 1e-30)
        i5, i25 = np.argmax(db < -5), np.argmax(db < -25)

        # Extrapolate the measured 20 dB decay slope to estimate T60.
        measured = 3.0*(i25-i5)/f_s
        assert 0.7*t60 < measured < 1.3*t60, (t60, measured)

    # Damping should reduce the energy remaining after one second.
    imp = np.r_[1.0, np.zeros(int(3*f_s))]
    assert (dsp.fdn_reverb(imp, 2.0, 0.45)[f_s:]**2).sum() < (
            dsp.fdn_reverb(imp, 2.0, 0.0)[f_s:]**2).sum()


def test_ping_pong_alternates():
    """Verify ping-pong echoes alternate between stereo channels with decreasing feedback."""
    x = np.zeros((f_s, 2))
    x[0, 0] = 1.0
    y = dsp.ping_pong(x, 4410, 0.8)
    assert np.isclose(y[4410, 1], 0.8) and np.isclose(y[8820, 0], 0.64)
    assert abs(y[4410, 0]) < 1e-12


def test_web_panel_backend():
    """Verify demo presets build and render audible stereo, and invalid inputs are handled safely"""
    from echo import webui

    for p in webui.PRESETS:
        st = {
            "length": 3,
            "room": p["room"],
            "reverb": {**p["reverb"], "t60": 0.5},
            "delay": p["delay"],
            "sources": [dict(s, id=str(i)) for i, s in enumerate(p["sources"])]
        }

        sc = webui.scene_paths(st)
        assert len(sc["paths"]) == len(p["sources"])
        assert all(
            len(v["x"]) == len(v["y"]) >= 300
            for v in sc["paths"].values()
        )

        e, length = webui.build_echo(st)
        out = e.render(length)

        assert out.samples.shape[1] == 2 and out.peak_amplitude > 0.1, p["id"]

    # Invalid inputs should be clamped or replaced rather than causing errors
    m = webui.build_motion({
        "motion": "Orbit",
        "radius": "nan",
        "speed": 99,
        "x": "oops"
    })
    assert m.speed == 2 and m.cx == 0


def test_speed():
    """Verify core DSP routines process 20 seconds of audio within the performance budget."""
    x = rng.standard_normal(20*f_s)

    t0 = time.time()
    dsp.fdn_reverb(x, 2.5)
    dsp.fractional_delay(x, np.full(len(x), 100.3))
    dsp.one_pole(x, 0.3)

    dt = time.time()-t0
    assert dt < 10, dt
    print(f"   20 s of FDN + delay read + one-pole: {dt:.2f} s")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print("ok  ", fn.__name__)
    print(f"\nall {len(tests)} tests passed")
