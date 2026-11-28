
"""tests.py: sanity checks for ECHO. Run: python src/tests.py

Each test either checks a fast block-based routine against the course notes'
literal sample-by-sample recurrence, or checks a physical property such as
Doppler, ITD, or T60. Also tests browser integration and DSP performance.

Prints "ok" per test and "all N tests passed" at the end
"""

import time
import numpy as np
from echo import (
    Curve, DelaySettings, Echo, KeyframePath, PolarPath, ReverbSettings, Room, dsp, sources
)
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
            "automation": p.get("automation", {}),
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


# --------------------------------------------------------------------------- #
# Parameter automation
# --------------------------------------------------------------------------- #

def _raises(exc, fn):
    """True if calling fn() raises exc"""
    try:
        fn()
    except exc:
        return True
    return False


def _dry_scene(audio, **kw):
    """Scene with room, reverb and delay off, so only the source path is heard"""
    e = Echo()
    e.room.enabled = e.reverb.enabled = e.delay.enabled = False
    e.add_source(audio, "src", **kw)
    return e


def test_curve_interpolation():
    """Verify Curve holds its ends, interpolates linearly and with smoothstep, and handles jumps"""
    c = Curve([(1, 0), (3, 10)])
    assert np.allclose(c(np.array([0.0, 1.0, 2.0, 3.0, 5.0])), [0, 0, 5, 10, 10])
    assert c(2.0) == 5.0                               # scalar in, scalar out

    # smoothstep(u) = 3u^2 - 2u^3: 0.5 at u = 0.5, 3/16 - 2/64 = 0.15625 at u = 0.25
    s = Curve([(1, 0), (3, 10)], "smoothstep")
    assert np.isclose(s(2.0), 5.0) and np.isclose(s(1.5), 10*0.15625)
    eps = 1e-3                                         # zero slope at the keyframes
    assert s(1 + eps) < 0.01*c(1 + eps) and s(3 - eps) > 10 - 0.01*(10 - c(3 - eps))

    # a keyframe's own shape applies to the segment that starts there
    m = Curve([(0, 0, "smoothstep"), (2, 10), (4, 30)])
    assert np.isclose(m(0.5), 10*0.15625) and np.isclose(m(3.0), 20.0)

    # unsorted input is sorted; equal times make a jump to the later keyframe
    j = Curve([(2, 5), (0, 0), (1, 1), (1, 4)])
    assert np.allclose(j(np.array([0.5, 1.0, 1.5, 9.0])), [0.5, 4.0, 4.5, 5.0])
    assert np.allclose(Curve([(0, 0), (1, 1), (1, 2)])(np.array([0.5, 1.0, 2.0])), [0.5, 2.0, 2.0])
    assert np.allclose(Curve([(3, 7)])(np.array([0.0, 9.0])), 7.0)

    # a lone step: first value before it, last value from that instant on
    step = Curve([(2, 0), (2, 1)])
    assert np.allclose(step(np.array([0.0, 1.999, 2.0, 3.0])), [0, 0, 1, 1])
    lead = Curve([(0, 0), (0, 5), (4, 9)])
    assert np.allclose(lead(np.array([-1.0, 0.0, 2.0, 4.0, 6.0])), [0, 5, 7, 9, 9])


def test_automation_validation():
    """Verify bad keyframes, unknown parameter names and non-finite curve output are rejected"""
    assert _raises(ValueError, lambda: Curve([]))
    assert _raises(ValueError, lambda: Curve([(0, 1)], "cubic"))
    assert _raises(ValueError, lambda: Curve([(0, 1, "cubic")]))
    assert _raises(ValueError, lambda: Curve([(0, float("nan"))]))
    assert _raises(ValueError, lambda: Curve([(0, 1, "linear", 4)]))

    tone = np.sin(2*np.pi*200*np.arange(f_s)/f_s)
    assert _raises(ValueError, lambda: Echo().add_source(tone, automation={"gian_db": Curve([(0, 0)])}))
    assert _raises(TypeError, lambda: Echo().add_source(tone, automation={"gain_db": 3.0}))

    e = _dry_scene(tone, automation={"send": lambda t: np.full_like(t, np.nan)})
    assert _raises(ValueError, lambda: e.render(1.0))
    e = _dry_scene(tone)
    e.automation = {"time": Curve([(0, 0.3)])}         # only delay_feedback is a scene parameter
    assert _raises(ValueError, lambda: e.render(1.0))


def test_gain_automation_follows_curve():
    """Verify an automated gain_db shapes the rendered level as the curve says, within 0.25 dB"""
    tone = np.sin(2*np.pi*200*np.arange(f_s)/f_s)      # whole cycles, so it loops seamlessly
    prop = Propagation(air_absorption=0, head_shadow=0)
    g = Curve([(1.0, -30.0), (7.0, 0.0)])              # linear in dB
    a = _dry_scene(tone, motion=Static(0, 1), prop=prop, automation={"gain_db": g}
                   ).render(8.0, normalize=False).samples[:, 0]
    r = _dry_scene(tone, motion=Static(0, 1), prop=prop).render(8.0, normalize=False).samples[:, 0]

    w = f_s//10                                        # 0.1 s = 20 cycles
    for k in range(5, 75):
        seg = slice(k*w, (k + 1)*w)
        measured = 20*np.log10(np.sqrt(np.mean(a[seg]**2))/np.sqrt(np.mean(r[seg]**2)))
        assert abs(measured - float(g((k + 0.5)*0.1))) < 0.25, (k, measured)


def test_send_automation():
    """Verify automated reverb send matches a fixed send when constant and is causal when stepped"""
    def scene(send, auto=None):
        e = Echo()
        e.room.enabled = False
        e.reverb = ReverbSettings(t60=1.0)
        e.delay.enabled = False
        e.add_source(sources.noise_bursts([0.5*i for i in range(12)], length=0.05), "ticks",
                     motion=Static(0, 2), send=send, automation=auto or {})
        return e.render(5.0, normalize=False).samples

    fixed = scene(0.4)
    assert np.allclose(fixed, scene(0.0, {"send": Curve([(0, 0.4)])}), atol=1e-9)

    # send jumps from 0 to 1 at 2 s: the reverb hasn't been fed before that, so
    # nothing before 2 s can differ from the send = 0 render
    off = scene(0.0)
    step = scene(0.0, {"send": Curve([(2.0, 0.0), (2.0, 1.0)])})
    pre = int(2.0*f_s)
    assert np.abs(step[:pre] - off[:pre]).max() < 1e-9
    assert np.abs(step[pre:] - off[pre:]).max() > 1e-3


def test_keyframe_paths():
    """Verify KeyframePath and PolarPath hit their keyframes, ease correctly and hold the ends"""
    p = KeyframePath.from_points([(0, -4, 2), (2, 4, 2), (4, 4, 8)])
    x, y = p(np.array([0.0, 1.0, 2.0, 3.0, 9.0]))
    assert np.allclose(x, [-4, 0, 4, 4, 4]) and np.allclose(y, [2, 2, 2, 5, 8])

    s = KeyframePath.from_points([(0, 0, 0), (1, 1, 0)], "smoothstep")
    assert np.isclose(s(np.array([0.25]))[0][0], 0.15625)

    # 3 m away, from straight ahead (azimuth 0) to the listener's right (90)
    q = PolarPath(distance=3.0, azimuth=Curve([(0, 0), (2, 90)]))
    qx, qy = q(np.array([0.0, 1.0, 2.0]))
    assert np.allclose(qx, [0, 3*np.sin(np.pi/4), 3]) and np.allclose(qy, [3, 3*np.cos(np.pi/4), 0])

    # no wrap-around: 720 degrees over 4 s is 180 deg/s, two full turns that end where they began.
    # t = 0.5 -> 90 deg (right), 1 -> 180 (behind), 2 -> 360 (ahead again), 4 -> 720
    two = PolarPath(distance=2.0, azimuth=Curve([(0, 0), (4, 720)]))
    tx, ty = two(np.array([0.0, 0.5, 1.0, 2.0, 4.0]))
    assert np.allclose(tx, [0, 2, 0, 0, 0], atol=1e-9) and np.allclose(ty, [2, 0, -2, 2, 2], atol=1e-9)


def test_polar_sweep_pans_left_to_right():
    """Verify a source swept from azimuth 270 to 450 (left, ahead, right) moves its level from the left ear to the right"""
    noise = 0.3*np.random.default_rng(5).standard_normal(f_s)
    e = _dry_scene(noise, motion=PolarPath(3.0, Curve([(0, 270), (4, 450)])))
    y = e.render(4.0, normalize=False).samples
    rms = lambda v: np.sqrt(np.mean(v**2))
    early, late = slice(0, f_s//2), slice(int(3.5*f_s), int(3.98*f_s))
    assert rms(y[early, 0]) > 1.3*rms(y[early, 1])
    assert rms(y[late, 1]) > 1.3*rms(y[late, 0])


def test_doppler_automation():
    """Verify per-sample Doppler equals the scalar case, bends pitch only while on, and never clicks"""
    N = 4*f_s
    t = np.arange(N)/f_s
    x = np.sin(2*np.pi*1000*t)
    px, py = Flyby(-30, 2, 30, 2, duration=4.0)(t)

    # a constant array reproduces the scalar formula (D-1)*(r - r0)
    y1 = propagate(x, px, py, f_s, Propagation(doppler=1.7))
    y2 = propagate(x, px, py, f_s, Propagation(), doppler=np.full(N, 1.7))
    assert np.abs(y1 - y2).max() < 1e-6

    # off while approaching, physical afterwards: pitch is flat early, falls late
    d = Curve([(1.2, 0.0), (1.3, 1.0)])
    y = propagate(x, px, py, f_s, Propagation(), doppler=d(t))[:, 0]
    assert abs(dominant_freq(y[int(0.3*f_s):int(1.0*f_s)]) - 1000) < 15
    assert dominant_freq(y[int(3.0*f_s):int(3.7*f_s)]) < 1000*0.97

    # a hard step 0 -> 3 mid-flight must not jump the delay (that would be a click):
    # no sample-to-sample change larger than a smoothly pitch-shifted 1 kHz sine allows
    step = np.where(t < 2.0, 0.0, 3.0)
    flat = Propagation(rolloff=0, air_absorption=0, head_shadow=0)
    q = propagate(x, px, py, f_s, flat, doppler=step)[:, 0]
    assert np.abs(np.diff(q)).max() < 0.2


def test_ping_pong_time_varying_feedback():
    """Verify ping_pong accepts per-sample feedback gains and stays exact"""
    M = 4410
    x = np.zeros((f_s, 2))
    x[0, 0] = 1.0
    assert np.allclose(dsp.ping_pong(x, M, np.full(f_s, 0.8)), dsp.ping_pong(x, M, 0.8))

    g = np.full(f_s, 0.8)
    g[M] = 0.5                                        # the knob when echo 1 is formed
    y = dsp.ping_pong(x, M, g)
    assert np.isclose(y[M, 1], 0.5) and np.isclose(y[2*M, 0], 0.5*0.8)


def test_delay_feedback_automation_and_tail():
    """Verify delay feedback automation cuts the echoes when it reaches zero and sizes the tail"""
    def scene(curve=None):
        e = Echo()
        e.room.enabled = e.reverb.enabled = False
        e.delay = DelaySettings(enabled=True, time=0.25, feedback=0.8, level_db=0.0)
        if curve is not None:
            e.automation = {"delay_feedback": curve}
        e.add_source(sources.noise_bursts([0.1], length=0.02), "click",
                     motion=Static(0, 2), loop=False)
        return e

    # Echoes form every 0.25 s from t = 0.1. Feedback 0.8 until 0.7 s, then 0:
    # echoes at 0.35 and 0.6 are made; the one that would form at 0.85 is not.
    e = scene(Curve([(0.0, 0.8), (0.7, 0.8), (0.7, 0.0)]))
    y = e.render(2.0, normalize=False).samples
    energy = lambda a, b: float((y[int(a*f_s):int(b*f_s)]**2).sum())
    assert energy(0.6, 0.65) > 1e-3 and energy(0.85, 1.0) < 1e-9

    # a constant curve equals the fixed setting
    a = scene().render(2.0, normalize=False).samples
    b = scene(Curve([(0, 0.8)])).render(2.0, normalize=False).samples
    assert a.shape == b.shape and np.allclose(a, b, atol=1e-9)

    # the tail follows the feedback that applies once the sources stop
    assert scene(Curve([(0, 0.8), (1, 0.0)]))._tail_seconds(2.0) == 0.0
    assert scene(Curve([(0, 0.0), (1, 0.9)]))._tail_seconds(2.0) > 5.0


def test_constant_curves_equal_fixed_values():
    """Verify automating gain, send and Doppler with constant curves renders the same as fixed values"""
    def scene(auto):
        e = Echo()
        e.room = Room(width=14, depth=11)
        e.reverb = ReverbSettings(t60=0.8)
        e.delay = DelaySettings(enabled=True, time=0.2, feedback=0.5)
        notes = sources.pluck_line([(0, "A3", 1.0), (0.5, "E4", 1.0)])
        kw = dict(gain_db=-4.0, send=0.4, prop=Propagation(doppler=1.7))
        if auto:
            e.automation = {"delay_feedback": Curve([(0, 0.5)])}
            kw["automation"] = {"gain_db": Curve([(0, -4.0)]), "send": Curve([(0, 0.4)]),
                                "doppler": Curve([(0, 1.7)])}
        e.add_source(notes, "s", motion=Flyby(-8, 2, 8, 2, duration=2.5), **kw)
        return e.render(3.0, normalize=False).samples

    fixed, auto = scene(False), scene(True)
    assert fixed.shape == auto.shape and np.abs(fixed - auto).max() < 1e-5


def test_web_automation_json():
    """Verify the panel's automation JSON builds curves and keyframed paths, and junk entries are ignored"""
    from echo import webui

    st = {
        "length": 4,
        "room": {"enabled": False}, "reverb": {"enabled": False}, "delay": {"enabled": True},
        "automation": {"delay_feedback": [[0, 0.2], [2, 5.0]]},             # 5.0 clamps to 0.95
        "sources": [{
            "kind": "ticks", "id": "a", "motion": "Static", "x": 0, "y": 3,
            "path": [[0, -3, 2], [2, 3, 2, "smoothstep"], ["bad"], [1, "nan", 0]],
            "automation": {"gain": [[0, -20], [2, 0]], "send": "oops", "doppler": [[0, 2]]},
        }],
    }
    e, length = webui.build_echo(st)
    src = e.sources[0]
    assert set(src.automation) == {"gain_db", "doppler"}                    # "send" was junk
    assert np.isclose(src.automation["gain_db"](1.0), -10.0)
    assert np.isclose(e.automation["delay_feedback"](2.0), 0.95)

    # the two good path rows survive; the junk ones are dropped
    xs = webui.scene_paths(st)["paths"]["a"]["x"]
    assert len(xs) >= 300 and abs(xs[0] + 3) < 1e-6 and abs(xs[-1] - 3) < 1e-6
    out = e.render(length)
    assert out.samples.shape[1] == 2 and out.peak_amplitude > 0.1

    # nothing usable -> falls back to the normal controls without raising
    m = webui.build_motion({"motion": "Static", "x": 1, "y": 2, "path": "oops"})
    assert (m.x, m.y) == (1, 2)
    assert webui.build_source_automation({"automation": {"gain": [[0, "x"]], "send": None}}) == {}
    assert webui.build_scene_automation({"automation": 7}) == {}


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print("ok  ", fn.__name__)
    print(f"\nall {len(tests)} tests passed")
