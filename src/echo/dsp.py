
"""ECHO low-level DSP primitives implemented w/ NumPy

Implements delay lines, filters, plucked-string synthesis, stereo effects,
and reverberation

Contents:
  fractional_delay   time-varying, non-integer delay (gives ITD and Doppler)
  feedback_delay, delay, allpass, one_pole   basic delay/filter blocks
  pluck              Karplus-Strong plucked string (physical model)
  ping_pong          stereo cross-feedback echo
  schroeder_reverb, fdn_reverb   the two reverb algorithms
  unit_energy        calibrates reverb level so "level" means the same at any decay time
"""

from __future__ import annotations
import numpy as np

# --------------------------------------------------------------------------- #
# Delay-line primitives
# --------------------------------------------------------------------------- #

def fractional_delay(x: np.ndarray, d: np.ndarray) -> np.ndarray:
    """Read a signal at a time-varying fractional delay

    Uses linear interpolation btwn neighboring samples to support
    sub-sample delays. Changing the delay over time changes the playback
    read rate, producing effects such as Doppler pitch shifting and flanging.
    Samples outside the input signal are treated as 0
    """
    x = np.asarray(x, dtype=np.float64)
    p = np.arange(len(d))-d                      
    i = np.floor(p).astype(np.int64)
    a = p-i
    n = len(x)

    def at(j):
        out = np.zeros(len(j))
        ok = (j >= 0) & (j < n)
        out[ok] = x[j[ok]]
        return out

    return (1.0-a)*at(i) + a*at(i+1)


def feedback_delay(x: np.ndarray, M: int, g: float = 1.0) -> np.ndarray:
    """Implement the feedback delay recurrence y[n] = x[n] + g*y[n-M]

    Processes M samples per block instead of iterating over individual
    samples. This works bc each sample in a block only depends on
    samples from previously completed blocks
    """
    y = np.array(x, dtype=np.float64)
    N = len(y)
    for s in range(M, N, M):
        e = min(s+M, N)
        y[s:e] += g*y[s-M:e-M]
    return y


def delay(x: np.ndarray, M: int) -> np.ndarray:
    """Delay a signal by M samples, padding the beginning w/ zeros

    This is a feedforward delay: each output sample is read directly from
    the input, w/ no feedback or repeated echoes
    """
    y = np.zeros(len(x))
    if M < len(x):
        y[M:] = x[:len(x)-M]
    return y


def allpass(x: np.ndarray, M: int, g: float) -> np.ndarray:
    """Implement an all-pass filter using a feedback delay line

    Combines the input and delayed feedback signals so that the filter
    changes phase while ideally preserving frequency-domain magnitude;
    Used as a building block for reverberation
    """
    v = feedback_delay(x, M, g)
    return -g*v + delay(v, M)


def one_pole(x: np.ndarray, a: np.ndarray | float, chunk: int = 64) -> np.ndarray:
    """Apply a one-pole low-pass filter

    `a` is a scalar or a per-sample array (sampled once per `chunk` sample)
    Within a chunk the recurrence has the closed form:
        y[k] = r^(k+1) z + a*r^k*cumsum_j( r^-j x[j] ),  r = 1-a,
    so each chunk is one cumsum; chunk-to-chunk state is carried by a short loop over chunks only
    """
    x = np.asarray(x, dtype=np.float64)
    N = len(x)
    K = -(-N//chunk)
    xp = np.zeros(K*chunk)
    xp[:N] = x
    X = xp.reshape(K, chunk)
    if np.isscalar(a):
        ac = np.full(K, float(a))
    else:
        a = np.asarray(a, dtype=np.float64)
        ac = a[np.minimum(np.arange(K)*chunk + chunk//2, N-1)]
    ac = np.clip(ac, 1e-4, 0.9)[:, None]           
    r = 1.0-ac
    k = np.arange(chunk)[None, :]
    y0 = r ** k*np.cumsum(ac*r ** (-k)*X, axis=1)   
    z_in = np.zeros(K)
    rC = (r[:, 0]) ** chunk
    last = y0[:, -1]
    for c in range(K-1):                        
        z_in[c + 1] = last[c] + rC[c]*z_in[c]
    y = y0 + r**(k + 1)*z_in[:, None]
    return y.reshape(-1)[:N]


def cutoff_to_alpha(fc: np.ndarray | float, fs: int) -> np.ndarray | float:
    """Convert a low-pass cutoff frequency into a one-pole filter coefficient

    `fc` is the cutoff frequency in Hz and `fs` is the sample rate.
    The resulting coefficient controls how quickly the filter responds
    to changes in its input
    """
    return 1.0-np.exp(-2.0*np.pi*np.asarray(fc, dtype=np.float64) / fs)


def wet_ratio(db: float) -> float:
    """Convert a wet-to-dry level difference in decibels into a mix ratio

    Returns the wet proportion `w` satisfying w/(1-w) = db in linear
    amplitude terms (Ch. 13)
    """
    return 1.0 / (1.0 + 10.0 ** (-db / 20.0))


# --------------------------------------------------------------------------- #
# Physical model: Karplus-Strong plucked string
# --------------------------------------------------------------------------- #


def pluck(f0: float, duration: float, fs: int = 44100, t60: float | None = None,
          damping: float = 0.5, pick_position: float = 0.0,
          rng: np.random.Generator | None = None) -> np.ndarray:
    """Synthesize a plucked string using the Karplus-Strong algorithm

    Excites a feedback delay line w/ a short burst of noise. The delay
    determines the fundamental pitch, feedback controls decay time, and
    low-pass damping gradually removes high-frequency energy.

        y[n] = x[n] + g*((1-d) y[n-M] + d y[n-M-1])

    `g` gives a 60 dB decay in `t60` seconds (notes' `tune`), `d` in [0, 0.5]
    is the low-pass damping (0.5 = the notes' two-point average; 0 = no
    damping), and `pick_position` in (0, 1) removes the comb of harmonics
    that a pluck at that fraction of the string would not excite (0 = off).

    The loop delay is M+d samples, so M = round(fs/f0-d) keeps it in tune
    """
    rng = rng or np.random.default_rng()
    t60 = duration if t60 is None else t60
    d = float(np.clip(damping, 0.0, 0.5))
    M = max(2, int(round(fs / f0-d)))
    g = 10.0 ** (-3.0*M / (fs*t60))
    N = int(duration*fs)
    exc = rng.uniform(-1.0, 1.0, M)
    exc -= exc.mean()               
    if pick_position > 0.0:
        P = int(round(np.clip(pick_position, 0.01, 0.99)*M))
        exc = exc-np.roll(exc, P)
    buf = np.zeros(N+M+1) # buf[M+1+n] = y[n]; 1st M+1 slots = silence
    x = np.zeros(N+M+1)
    x[M + 1:M + 1 + min(M, N)] = exc[:min(M, N)]
    for s in range(0, N, M):
        e = min(s + M, N)
        i0, i1 = M + 1 + s, M + 1 + e
        buf[i0:i1] = x[i0:i1] + g*((1-d)*buf[i0-M:i1-M] + d*buf[i0-M-1:i1-M-1])
    y = buf[M + 1:]
    peak = np.max(np.abs(y)) or 1.0
    return y / peak


# --------------------------------------------------------------------------- #
# Stereo ping-pong delay 
# --------------------------------------------------------------------------- #

def ping_pong(x: np.ndarray, M: int, g: float) -> np.ndarray:
    """Create stereo ping-pong echoes using cross-channel feedback.

    Each channel receives delayed feedback from the opposite channel,
    causing echoes to alternate between left and right while gradually
    decreasing in amplitude.

        yL[n] = xL[n] + g*yR[n-M]
        yR[n] = xR[n] + g*yL[n-M]

    `x` is a stereo array w/ shape (N, 2).
    """
    y = np.array(x, dtype=np.float64)
    N = len(y)
    for s in range(M, N, M):
        e = min(s + M, N)
        y[s:e, 0] += g*y[s-M:e-M, 1]
        y[s:e, 1] += g*y[s-M:e-M, 0]
    return y


# --------------------------------------------------------------------------- #
# Reverbs
# --------------------------------------------------------------------------- 

def schroeder_reverb(x: np.ndarray, t60: float, fs: int = 44100) -> np.ndarray:
    """Generate reverberation using the Schroeder reverb architecture

    Combines 4 parallel feedback comb filters to create a decaying
    reflection pattern, then applies two serial all-pass filters to
    increase echo density.

    Returns only the reflections
    """
    wet = np.zeros(len(x))
    for T in (0.0297, 0.0371, 0.0411, 0.0437):
        M = round(T*fs)
        g = 10.0 ** (-3.0*M / (fs*t60))
        wet += feedback_delay(x, M, g)-x
    wet /= 4.0
    for T in (0.005, 0.0017):
        wet = allpass(wet, round(T*fs), 0.7)
    return wet


def _hadamard(n: int) -> np.ndarray:
    """Construct a normalized Hadamard matrix for mixing delay-line signals

    The normalized matrix is orthogonal, so the mixing operation preserves
    signal energy in the ideal lossless case
    """
    H = np.array([[1.0]])
    while H.shape[0] < n:
        H = np.block([[H, H], [H, -H]])
    return H/np.sqrt(n)


FDN_DELAYS_MS = (31.1, 37.3, 43.7, 51.9, 59.3, 67.1, 74.9, 83.3)

def fdn_reverb(x: np.ndarray, t60: float, damping: float = 0.25, fs: int = 44100,
               size: float = 1.0) -> np.ndarray:
    """Generate stereo reverberation using an 8-line feedback delay network.

    Mixes eight differently sized delay lines through an orthogonal
    Hadamard matrix. Feedback controls the decay time, while low-pass
    damping causes high frequencies to decay faster than low frequencies.
    `size` scales all delay lengths.

    Processes blocks of B samples bc every delay line is at least
    B samples long, ensuring all feedback samples are already available.
    Returns a stereo (N, 2) wet signal
    """
    Ms = np.array([max(8, int(round(m*1e-3*fs*size))) for m in FDN_DELAYS_MS])
    B = int(Ms.min())
    L = len(Ms)
    g = 10.0 ** (-3.0*Ms/(fs*t60))
    d = float(np.clip(damping, 0.0, 0.5))
    H = _hadamard(L)
    N = len(x)
    pad = int(Ms.max())
    dbuf = np.zeros((L, N + pad))           
    u_prev = np.zeros(L)                     
    out = np.zeros((N, 2))
    in_gain = np.array([1, -1, 1, -1, 1, -1, 1, -1], dtype=np.float64) / np.sqrt(L)
    cL = np.array([1, 0, 1, 0, 1, 0, 1, 0], dtype=np.float64)
    cR = np.array([0, 1, 0, 1, 0, 1, 0, 1], dtype=np.float64)
    for s in range(0, N, B):
        e = min(s + B, N)
        n = e-s
        # u_i[n] = d_i[n-M_i]  (all already computed: M_i >= B)
        u = np.stack([dbuf[i, pad + s-Ms[i]:pad + e-Ms[i]] for i in range(L)])
        prev = np.concatenate([u_prev[:, None], u[:, :-1]], axis=1)
        lp = (1-d)*u + d*prev          
        fb = H @ (g[:, None]*lp)
        dbuf[:, pad + s:pad + e] = in_gain[:, None]*x[None, s:e] + fb
        u_prev = u[:, -1]
        out[s:e, 0] = cL @ u
        out[s:e, 1] = cR @ u
    return out / np.sqrt(L/2.0)


def unit_energy(fn, fs: int, seconds: float) -> float:
    """Measure the impulse-response energy of an audio effect

    Creates an impulse, processes it through `fn`, and measures the
    average energy across output channels. Used to calibrate reverb levels
    so that white noise input produces a consistent RMS output level
    """
    imp = np.zeros(int(seconds*fs))
    imp[0] = 1.0
    h = fn(imp)
    h = h if h.ndim == 2 else h[:, None]
    return float(np.mean(np.sum(h**2, axis=0)))
