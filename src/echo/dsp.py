"""ECHO low-level DSP (NumPy only).

Everything here is implemented from the delay-line recurrences in the course
notes (pcm-12-physical, pcm-13-effects). The notes write each recurrence as a
per-sample Python loop; here the *same* recurrences are evaluated a block at a
time so that a 20-second stereo render takes seconds instead of minutes:

* A feedback recurrence y[n] = x[n] + g*y[n-M] only depends on samples at least
  M back, so a whole block of M samples can be computed in one vector
  operation.  (`feedback_delay`, `allpass`, `pluck`, `ping_pong`, `FDN`.)
* A delay with NO feedback is just a (fractional) read of the input, so it is
  fully vectorized.  (`fractional_delay`.)
* A one-pole low-pass with a coefficient that is constant over short chunks is
  evaluated with a geometric-weights trick.  (`one_pole`.)
"""
from __future__ import annotations

import numpy as np

# --------------------------------------------------------------------------- #
# Delay-line primitives
# --------------------------------------------------------------------------- #


def fractional_delay(x: np.ndarray, d: np.ndarray) -> np.ndarray:
    """y[n] = x[n - d[n]] with a time-varying, fractional delay d[n] >= 0.

    Linear interpolation between x[n-k] and x[n-k-1] (as in the notes'
    `variable_feedback_delay`, which is where Doppler shift and flanging come
    from: when d[n] changes, the read head moves through the signal faster or
    slower than real time). Samples before the start / after the end are zero.
    """
    x = np.asarray(x, dtype=np.float64)
    p = np.arange(len(d)) - d                       # fractional read position
    i = np.floor(p).astype(np.int64)
    a = p - i
    n = len(x)

    def at(j):
        out = np.zeros(len(j))
        ok = (j >= 0) & (j < n)
        out[ok] = x[j[ok]]
        return out

    return (1.0 - a) * at(i) + a * at(i + 1)


def feedback_delay(x: np.ndarray, M: int, g: float = 1.0) -> np.ndarray:
    """Feedback delay line y[n] = x[n] + g*y[n-M] (the notes' circular-buffer
    version, evaluated M samples at a time; identical output)."""
    y = np.array(x, dtype=np.float64)
    N = len(y)
    for s in range(M, N, M):
        e = min(s + M, N)
        y[s:e] += g * y[s - M:e - M]
    return y


def delay(x: np.ndarray, M: int) -> np.ndarray:
    """y[n] = x[n - M] (zero padded)."""
    y = np.zeros(len(x))
    if M < len(x):
        y[M:] = x[:len(x) - M]
    return y


def allpass(x: np.ndarray, M: int, g: float) -> np.ndarray:
    """All-pass y[n] = -g x[n] + x[n-M] + g y[n-M], built from a feedback delay."""
    v = feedback_delay(x, M, g)
    return -g * v + delay(v, M)


def one_pole(x: np.ndarray, a: np.ndarray | float, chunk: int = 64) -> np.ndarray:
    """One-pole low-pass y[n] = (1-a) y[n-1] + a x[n].

    `a` is a scalar or a per-sample array; it is sampled once per `chunk`
    samples (control-rate, like the block-based control of Chapter 10).
    Within a chunk the recurrence has the closed form
        y[k] = r^(k+1) z + a * r^k * cumsum_j( r^-j x[j] ),  r = 1-a,
    so each chunk is one cumsum; chunk-to-chunk state is carried by a short
    loop over chunks only.
    """
    x = np.asarray(x, dtype=np.float64)
    N = len(x)
    K = -(-N // chunk)
    xp = np.zeros(K * chunk)
    xp[:N] = x
    X = xp.reshape(K, chunk)
    if np.isscalar(a):
        ac = np.full(K, float(a))
    else:
        a = np.asarray(a, dtype=np.float64)
        ac = a[np.minimum(np.arange(K) * chunk + chunk // 2, N - 1)]
    ac = np.clip(ac, 1e-4, 0.9)[:, None]            # keeps r^-j finite
    r = 1.0 - ac
    k = np.arange(chunk)[None, :]
    y0 = r ** k * np.cumsum(ac * r ** (-k) * X, axis=1)   # zero-state response
    z_in = np.zeros(K)
    rC = (r[:, 0]) ** chunk
    last = y0[:, -1]
    for c in range(K - 1):                          # carry state across chunks
        z_in[c + 1] = last[c] + rC[c] * z_in[c]
    y = y0 + r ** (k + 1) * z_in[:, None]
    return y.reshape(-1)[:N]


def cutoff_to_alpha(fc: np.ndarray | float, fs: int) -> np.ndarray | float:
    """One-pole coefficient for a cutoff frequency (Hz)."""
    return 1.0 - np.exp(-2.0 * np.pi * np.asarray(fc, dtype=np.float64) / fs)


def wet_ratio(db: float) -> float:
    """w such that w/(1-w) = db decibels (notes, Chapter 13)."""
    return 1.0 / (1.0 + 10.0 ** (-db / 20.0))


# --------------------------------------------------------------------------- #
# Physical model: Karplus-Strong plucked string (Chapter 12)
# --------------------------------------------------------------------------- #


def pluck(f0: float, duration: float, fs: int = 44100, t60: float | None = None,
          damping: float = 0.5, pick_position: float = 0.0,
          rng: np.random.Generator | None = None) -> np.ndarray:
    """Plucked string: noise burst through a damped feedback delay line.

        y[n] = x[n] + g * ((1-d) y[n-M] + d y[n-M-1])

    g gives a 60 dB decay in `t60` seconds (notes' `tune`), d in [0, 0.5] is the
    low-pass "damping" (0.5 = the notes' two-point average; 0 = no damping),
    and `pick_position` in (0, 1) removes the comb of harmonics that a pluck
    at that fraction of the string would not excite (0 = off).
    The loop delay is M + d samples, so M = round(fs/f0 - d) keeps it in tune.
    """
    rng = rng or np.random.default_rng()
    t60 = duration if t60 is None else t60
    d = float(np.clip(damping, 0.0, 0.5))
    M = max(2, int(round(fs / f0 - d)))
    g = 10.0 ** (-3.0 * M / (fs * t60))
    N = int(duration * fs)
    exc = rng.uniform(-1.0, 1.0, M)
    exc -= exc.mean()                # a DC offset would ring forever in the loop
    if pick_position > 0.0:
        P = int(round(np.clip(pick_position, 0.01, 0.99) * M))
        exc = exc - np.roll(exc, P)
    buf = np.zeros(N + M + 1)       # buf[M+1+n] = y[n]; first M+1 slots = silence
    x = np.zeros(N + M + 1)
    x[M + 1:M + 1 + min(M, N)] = exc[:min(M, N)]
    for s in range(0, N, M):
        e = min(s + M, N)
        i0, i1 = M + 1 + s, M + 1 + e
        buf[i0:i1] = x[i0:i1] + g * ((1 - d) * buf[i0 - M:i1 - M] + d * buf[i0 - M - 1:i1 - M - 1])
    y = buf[M + 1:]
    peak = np.max(np.abs(y)) or 1.0
    return y / peak


# --------------------------------------------------------------------------- #
# Stereo ping-pong delay (Chapter 13)
# --------------------------------------------------------------------------- #


def ping_pong(x: np.ndarray, M: int, g: float) -> np.ndarray:
    """Stereo cross-feedback delay; x is (N, 2).  Echoes bounce L <-> R:
        yL[n] = xL[n] + g yR[n-M],   yR[n] = xR[n] + g yL[n-M]
    (the notes' `ping_pong_delay`, generalized to a stereo input)."""
    y = np.array(x, dtype=np.float64)
    N = len(y)
    for s in range(M, N, M):
        e = min(s + M, N)
        y[s:e, 0] += g * y[s - M:e - M, 1]
        y[s:e, 1] += g * y[s - M:e - M, 0]
    return y


# --------------------------------------------------------------------------- #
# Reverbs (Chapter 13)
# --------------------------------------------------------------------------- #


def schroeder_reverb(x: np.ndarray, t60: float, fs: int = 44100) -> np.ndarray:
    """Schroeder 1962: four parallel feedback combs, then two all-pass filters.
    Returns only the reflections (as in the notes' `reverb`)."""
    wet = np.zeros(len(x))
    for T in (0.0297, 0.0371, 0.0411, 0.0437):
        M = round(T * fs)
        g = 10.0 ** (-3.0 * M / (fs * t60))
        wet += feedback_delay(x, M, g) - x
    wet /= 4.0
    for T in (0.005, 0.0017):
        wet = allpass(wet, round(T * fs), 0.7)
    return wet


def _hadamard(n: int) -> np.ndarray:
    H = np.array([[1.0]])
    while H.shape[0] < n:
        H = np.block([[H, H], [H, -H]])
    return H / np.sqrt(n)


FDN_DELAYS_MS = (31.1, 37.3, 43.7, 51.9, 59.3, 67.1, 74.9, 83.3)


def fdn_reverb(x: np.ndarray, t60: float, damping: float = 0.25, fs: int = 44100,
               size: float = 1.0) -> np.ndarray:
    """Feedback delay network: 8 delay lines mixed by an orthogonal Hadamard
    matrix (a lossless prototype), each line scaled by g_i = 10^(-3 M_i/(fs t60))
    and low-passed by a two-point average with weight `damping` (<= 0.5), so
    highs decay faster than lows.  `size` scales all delay lengths.

    Lines are read >= B samples back (B = shortest delay), so a block of B
    samples is computed at once.  Returns a stereo (N, 2) wet signal.
    """
    Ms = np.array([max(8, int(round(m * 1e-3 * fs * size))) for m in FDN_DELAYS_MS])
    B = int(Ms.min())
    L = len(Ms)
    g = 10.0 ** (-3.0 * Ms / (fs * t60))
    d = float(np.clip(damping, 0.0, 0.5))
    H = _hadamard(L)
    N = len(x)
    pad = int(Ms.max())
    dbuf = np.zeros((L, N + pad))            # d_i[n], stored at column n + pad
    u_prev = np.zeros(L)                      # last output sample of each line
    out = np.zeros((N, 2))
    in_gain = np.array([1, -1, 1, -1, 1, -1, 1, -1], dtype=np.float64) / np.sqrt(L)
    cL = np.array([1, 0, 1, 0, 1, 0, 1, 0], dtype=np.float64)
    cR = np.array([0, 1, 0, 1, 0, 1, 0, 1], dtype=np.float64)
    for s in range(0, N, B):
        e = min(s + B, N)
        n = e - s
        # u_i[n] = d_i[n - M_i]  (all already computed: M_i >= B)
        u = np.stack([dbuf[i, pad + s - Ms[i]:pad + e - Ms[i]] for i in range(L)])
        prev = np.concatenate([u_prev[:, None], u[:, :-1]], axis=1)
        lp = (1 - d) * u + d * prev           # damping inside the loop
        fb = H @ (g[:, None] * lp)
        dbuf[:, pad + s:pad + e] = in_gain[:, None] * x[None, s:e] + fb
        u_prev = u[:, -1]
        out[s:e, 0] = cL @ u
        out[s:e, 1] = cR @ u
    return out / np.sqrt(L / 2.0)


def unit_energy(fn, fs: int, seconds: float) -> float:
    """Energy of fn's impulse response (mean over channels); used to calibrate
    reverb level so that white noise in -> same RMS out."""
    imp = np.zeros(int(seconds * fs))
    imp[0] = 1.0
    h = fn(imp)
    h = h if h.ndim == 2 else h[:, None]
    return float(np.mean(np.sum(h ** 2, axis=0)))
