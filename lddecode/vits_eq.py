"""Guarded residual video EQ fitted to a PAL disc's own VITS
(--pal_vits_eq).

The decoder's own equalisers (the MTF pole pair the 2T servo sets, the
inverse-MTF chroma lift and the multiburst video EQ, which anchors up to
3.6 MHz) all act inside the decode, where the servos read their result.
What they leave is measured here, on the same picture the servos read
(field.dspicture), and corrected by one fixed causal FIR applied to the
written picture only:

1. a one-pole tail inverse, the low-frequency smear the ITS bar's steps
   show (1 - c a^n over the first ~2 us after each edge), which no
   in-decode stage models;
2. a magnitude EQ, the inverse of the multiburst after that tail
   inverse (pchip through DC = 1, held above the top packet), realised
   minimum-phase so it adds no pre-ringing, and tapered back to unity
   over 4.8-5.6 MHz so nothing above the picture band is lifted.

Every gain is guarded by the disc's own signal:

- the EQ may boost only when the disc's conformance 2T pulse (peak over
  the bar step, 16x upsampled) is short of 0.98, and the boost is shrunk
  until that 2T after the EQ is at most 1.0;
- the boost is shrunk until the blank line's noise rises by at most
  NOISE_RISE_IRE;
- with no multiburst deficit and no reliable tail, or with neither
  measurement, the EQ stands down to identity.

Nothing here reads a disc-specific constant: the frequencies are the
PAL luminance band's, and every amplitude is measured.
"""

import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.signal import oaconvolve, resample

#: The minimum-phase FIR's length, samples (4fsc): room for the
#: slowest tail inverse the fit allows (tau <= 30 samples) to decay.
TOTAL_TAPS = 256
#: A response within this of unity (natural log, about 0.04 dB) at every
#: frequency is no filter at all.
IDENTITY_LOG = 0.005
#: Total gain limits: never cut below this, never boost above
#: MAX_BOOST (when the 2T shows a deficit at all).
MIN_GAIN = 0.75
MAX_BOOST = 10 ** (2.0 / 20)
#: The disc's own 2T below which a boost is allowed, and the 2T the
#: boost may raise it to.
T2_BOOST_BELOW = 0.98
T2_CAP = 1.0
#: How far the blank line's noise (IRE rms) may rise through the EQ.
NOISE_RISE_IRE = 0.08
#: A multiburst deficit under this, with no reliable tail, is no reason
#: to filter.
MIN_DEFICIT = 0.03
#: The magnitude EQ's anchors stop at the top packet at or below this
#: (the PAL multiburst's 4.8 MHz packet); the total gain tapers back to 1
#: from TAPER_LO to TAPER_HI (PAL luminance band edge).
TOP_ANCHOR_HZ = 4.8e6
TAPER_LO_HZ, TAPER_HI_HZ = 4.8e6, 5.6e6
#: A tail fit counts only with c >= MIN_TAIL_C and a residual under
#: MAX_TAIL_RMS of the step.
MIN_TAIL_C = 0.05
MAX_TAIL_RMS = 0.02
#: Readings pooled: at least MIN_FIELDS fields before a decision, the
#: newest KEEP_FIELDS kept.
MIN_FIELDS = 16
KEEP_FIELDS = 32
#: Refit interval (fields) and the change in total gain (dB, anywhere in
#: 0.5-5 MHz) a refit must show to be adopted.
REFIT_FIELDS = 100
ADOPT_DB = 0.25

NFFT = 4096


def _bar_steps(x, black=0.0, white=100.0):
    """(rise, fall) step responses (45 samples from each 50 % crossing,
    normalised 0 -> 1) of an ITS line x in IRE, its bar edges (a, b),
    or None when x does not hold a clean bar."""
    hi = x > black + 0.7 * (white - black)
    if not (hi[240:380].mean() > 0.98 and hi[150:190].mean() < 0.02):
        return None
    hm = x > black + 0.5 * (white - black)
    a = 150 + int(np.argmax(hm[150:]))
    b = a + int(np.argmin(hm[a:]))
    if b - a < 140 or a < 70 or b + 70 > len(x):
        return None
    top = np.median(x[a + 60:b - 60])
    lo1 = np.median(x[a - 60:a - 20])
    lo2 = np.median(x[b + 20:b + 60])
    if top - lo1 < 30 or top - lo2 < 30:
        return None
    r = a - 15 + int(np.argmax(x[a - 15:a + 10] > 0.5 * (top + lo1)))
    f = b - 10 + int(np.argmax(x[b - 10:b + 10] < 0.5 * (top + lo2)))
    if r + 45 > len(x) or f + 45 > len(x):
        return None
    return ((x[r:r + 45] - lo1) / (top - lo1),
            (top - x[f:f + 45]) / (top - lo2), (a, b, top, lo1))


def conformance_2t(x, fs_hz, bar):
    """The 2T pulse after the bar, peak (16x upsampled) over the
    pre-bar baseline, per bar step - the conformance definition."""
    a, b, top, base = bar
    s0 = b + int(1.5e-6 * fs_hz)
    seg = x[s0:s0 + int(6e-6 * fs_hz)]
    if len(seg) < 20:
        return None
    k = int(np.argmax(seg))
    w = seg[max(0, k - 8):k + 9]
    return float((resample(w, len(w) * 16).max() - base) / (top - base))


def _tail_fit(steps):
    """(c, tau, rms) of the one-pole smear 1 - c a^(n+1), a = e^(-1/tau),
    fitted to the median step, or None."""
    if len(steps) < 4:
        return None
    S = np.median(np.array(steps), 0)
    n = np.arange(6, 41)
    best = (np.inf, 0.0, 1.0)
    for tau in np.linspace(3, 30, 109):
        e = np.exp(-n / tau)
        c = float(np.dot(1 - S[n], e) / np.dot(e, e))
        r = float(np.sum((1 - S[n] - c * e) ** 2))
        if r < best[0]:
            best = (r, c, tau)
    r, c, tau = best
    c = float(np.clip(c * np.exp(1 / tau), 0, 0.35))
    return c, float(tau), float(np.sqrt(r / len(n)))


def tail_impulse(c, tau, tol=1e-7, nmax=512):
    """Impulse response of the tail inverse (1 - a z^-1) /
    ((1 - c a) - (1 - c) a z^-1), truncated where it has decayed."""
    if c <= 0:
        return np.ones(1)
    a = np.exp(-1.0 / tau)
    b0, b1 = 1.0 / (1 - c * a), -a / (1 - c * a)
    p = (1 - c) * a / (1 - c * a)
    n = int(min(nmax, max(2, np.ceil(np.log(tol) / np.log(p)) + 2)))
    h = np.zeros(n)
    h[0] = b0
    prev = b0
    for i in range(1, n):
        prev = p * prev + (b1 if i == 1 else 0.0)
        h[i] = prev
    return h / h.sum()


def _min_phase(mag, ntaps):
    """Causal minimum-phase FIR of magnitude mag (rfft grid, NFFT),
    truncated to ntaps under a window flat over its first three
    quarters and a half-Hann over the last, and normalised to mag[0]
    at DC."""
    full = np.concatenate([mag, mag[-2:0:-1]])
    cep = np.fft.ifft(np.log(np.maximum(full, 1e-6))).real
    fold = np.zeros_like(cep)
    fold[0] = cep[0]
    fold[1:NFFT // 2] = 2 * cep[1:NFFT // 2]
    fold[NFFT // 2] = cep[NFFT // 2]
    h = np.fft.ifft(np.exp(np.fft.fft(fold))).real
    k = ntaps // 4
    w = np.ones(ntaps)
    w[ntaps - k:] = np.hanning(2 * k + 1)[k + 1:]
    h = h[:ntaps] * w
    return h / (h.sum() / mag[0])


def causal_filter(x, taps, history=None):
    """y[n] = sum_k taps[k] x[n-k] over x, continuing from history (the
    previous input's last len(taps)-1 samples; None repeats x[0]).
    Returns (y, new history)."""
    x = np.asarray(x, dtype=np.float64)
    n = len(taps) - 1
    if n == 0:
        return x * taps[0], history
    if history is None:
        history = np.full(n, x[0])
    xin = np.concatenate([history, x])
    y = oaconvolve(xin, taps)[n:n + len(x)]
    return y, xin[-n:]


def field_reading(field, its_line, mb):
    """One field's readings for the pool, from what main measures:
    (ITS line in IRE or None, multiburst packets or None, blank-line
    row in IRE or None).  its_line is the line measure_its_2t_ratio
    accepted, mb what measure_vits_multiburst returned."""
    def row(line, pic):
        sl = field.lineslice_tbc(line)
        return field.output_to_ire(pic[sl].astype(np.float64))
    its = None
    if its_line is not None:
        try:
            its = row(its_line, field.dspicture).astype(np.float32)
        except Exception:
            its = None
    packets = None
    if mb is not None:
        packets = tuple((float(f), float(a)) for f, a in mb[0])
    blank = None
    out = getattr(field, "dspicture_out", None)
    try:
        b = row(22, out if out is not None else field.dspicture)[200:1050]
        # blank only: near blanking and flat once low-passed
        lp = np.convolve(b, np.ones(25) / 25, "valid")
        if abs(np.median(b)) < 5.0 and np.ptp(lp) < 6.0:
            blank = b.astype(np.float32)
    except Exception:
        blank = None
    return its, packets, blank


def _pooled_multiburst(readings):
    """Median per-packet response relative to the lowest packet
    (<= 1.45 MHz), as (freqs_hz, response), or None."""
    sets = [p for _, p, _ in readings if p]
    if len(sets) < 2:
        return None
    ref = sets[0]
    if not ref or ref[0][0] > 1.45e6:
        return None
    freqs = [f for f, _ in ref]
    cols = [[] for _ in freqs]
    for pk in sets:
        if not pk or pk[0][0] > 1.45e6 or abs(pk[0][0] - ref[0][0]) > 0.2e6:
            continue
        a0 = pk[0][1]
        for i, f in enumerate(freqs):
            m = [a for g, a in pk if abs(g - f) < 0.2e6]
            if m and a0 > 0:
                cols[i].append(m[0] / a0)
    keep = [i for i, c in enumerate(cols) if len(c) >= 2]
    if len(keep) < 3:
        return None
    return (np.array([freqs[i] for i in keep]),
            np.array([np.median(cols[i]) for i in keep]))


def fit(readings, fs_hz, allow_boost=True):
    """The EQ for a pool of field readings: (taps or None for identity,
    report dict).  allow_boost False makes it cut-only whatever the 2T
    reads (the decoder's 2T servo is still able to raise the pulse
    itself)."""
    rep = {"allow_boost": bool(allow_boost)}
    its_rows = [r[0] for r in readings if r[0] is not None]
    steps, bars = [], []
    for x in its_rows:
        s = _bar_steps(np.asarray(x, np.float64))
        if s is not None:
            steps += [s[0], s[1]]
            bars.append(x)
    tf = _tail_fit(steps)
    c, tau = 0.0, 9.0
    if tf is not None:
        rep.update(tail_c=tf[0], tail_tau=tf[1], tail_rms=tf[2])
        if tf[0] >= MIN_TAIL_C and tf[2] <= MAX_TAIL_RMS:
            c, tau = tf[0], tf[1]
    rep["c"], rep["tau"] = c, tau
    g_tail = tail_impulse(c, tau)

    fq = np.fft.rfftfreq(NFFT, 1.0 / fs_hz)
    GT = np.abs(np.fft.rfft(g_tail, NFFT))

    # the disc's own 2T, on the median ITS line
    its, bar, t2 = None, None, None
    if len(bars) >= 2:
        its = np.median(np.array(bars, np.float64), 0)
        st = _bar_steps(its)
        if st is not None:
            bar = st[2]
            t2 = conformance_2t(its, fs_hz, bar)
    rep["t2"] = t2
    maxb = (MAX_BOOST if (allow_boost and t2 is not None
                          and t2 < T2_BOOST_BELOW) else 1.0)

    mbp = _pooled_multiburst(readings)
    deficit = None
    if mbp is not None:
        f_mb, r_mb = mbp
        inband = (f_mb > f_mb[0]) & (f_mb <= TOP_ANCHOR_HZ + 0.25e6)
        deficit = float(1 - np.min(r_mb[inband])) if inband.any() else 0.0
        rep["mb"] = [(float(f), float(r)) for f, r in zip(f_mb, r_mb)]
    rep["deficit"] = deficit
    if c < MIN_TAIL_C and (deficit is None or deficit < MIN_DEFICIT):
        rep["stand_down"] = True
        return None, rep

    if mbp is not None:
        use = f_mb <= TOP_ANCHOR_HZ + 0.25e6
        gt_at = np.interp(f_mb[use], fq, GT)
        # after the tail inverse, relative to DC (the lowest packet taken
        # as the tail-corrected low-frequency reference)
        r_t = r_mb[use] * gt_at / gt_at[0]
        fk = np.concatenate([[0.0], f_mb[use]])
        rk = np.concatenate([[1.0], r_t])
        rk[1] = 1.0
        top = fk[-1]
        M = 1.0 / PchipInterpolator(fk, rk)(np.minimum(fq, top))
    else:
        M = np.ones_like(fq)
    M = np.clip(M, MIN_GAIN / GT, maxb / GT)
    M[fq > TOP_ANCHOR_HZ] = np.interp(TOP_ANCHOR_HZ, fq, M)
    # taper the total gain back to 1 over the band edge (log gain)
    wt = np.clip((TAPER_HI_HZ - fq) / (TAPER_HI_HZ - TAPER_LO_HZ), 0, 1)
    wt = 0.5 - 0.5 * np.cos(np.pi * wt)
    T = np.exp(wt * np.log(np.maximum(GT * M, 1e-6)))   # total gain

    def taps_for(alpha):
        # The whole response, tail inverse included, as one minimum-phase
        # FIR: the tail inverse is itself minimum phase (its zero and
        # pole lie inside the unit circle), so this is exact up to the
        # FIR's length.
        return _min_phase(np.exp(alpha * np.log(T)), TOTAL_TAPS)

    taps = taps_for(1.0)
    if maxb > 1.0 and its is not None and bar is not None:
        def t2_after(h):
            return conformance_2t(causal_filter(its, h)[0], fs_hz, bar)

        def shrink(over):
            lo, hi = 0.0, 1.0
            for _ in range(12):
                a = 0.5 * (lo + hi)
                if over(taps_for(a)):
                    hi = a
                else:
                    lo = a
            return lo
        alpha = 1.0
        if t2_after(taps) > T2_CAP:
            alpha = shrink(lambda h: t2_after(h) > T2_CAP)
            rep["t2cap_alpha"] = alpha
            taps = taps_for(alpha)
        rep["t2_after"] = t2_after(taps)
        blanks = [r[2] for r in readings if r[2] is not None]
        if blanks:
            rows = np.array(blanks, np.float64)

            def noise(h):
                y = np.array([causal_filter(r, h)[0] for r in rows])
                y = (y - y.mean(1, keepdims=True))[:, 40:-40]
                return float(np.sqrt(np.mean(y ** 2)))
            n0 = float(np.sqrt(np.mean(
                (rows - rows.mean(1, keepdims=True))[:, 40:-40] ** 2)))
            rep["noise_in"] = n0
            if noise(taps) > n0 + NOISE_RISE_IRE:
                a_cap = shrink(lambda h: noise(h) > n0 + NOISE_RISE_IRE)
                alpha = min(alpha, a_cap)
                rep["noisecap_alpha"] = a_cap
                taps = taps_for(alpha)
            rep["noise_out"] = noise(taps)
    elif maxb > 1.0:
        # no ITS line to hold the 2T against: cut only
        taps = None
    T_cut = np.minimum(T, 1.0)
    if taps is None:
        taps = _min_phase(T_cut, TOTAL_TAPS)
    # the same fit with every boost taken out, for while its readings
    # are stale (see LDdecode.checkVitsEQ)
    rep["cut_taps"] = (None if np.max(np.abs(np.log(T_cut))) < IDENTITY_LOG
                       else _min_phase(T_cut, TOTAL_TAPS))
    H = np.abs(np.fft.rfft(taps, NFFT))
    if np.max(np.abs(np.log(np.maximum(H, 1e-9)))) < IDENTITY_LOG:
        rep["identity"] = True
        return None, rep
    H = np.abs(np.fft.rfft(taps, NFFT))
    rep["gain"] = {f"{f:.2f}": float(np.interp(f * 1e6, fq, H))
                   for f in (0.5, 1, 2, 3, 4, 4.43, 4.8, 5.5, 6.2)}
    return taps, rep


def gain_db(taps, fs_hz, freqs_hz):
    """|H| in dB of taps (None = identity) at freqs_hz."""
    if taps is None:
        return np.zeros(len(freqs_hz))
    fq = np.fft.rfftfreq(NFFT, 1.0 / fs_hz)
    H = np.abs(np.fft.rfft(np.asarray(taps), NFFT))
    return 20 * np.log10(np.maximum(np.interp(freqs_hz, fq, H), 1e-9))


class StreamEQ:
    """The write-side filter state of one output stream (the TBC file
    or the CVBS file): the taps of each block come with it, and the
    input history carries across blocks, so the output is continuous
    and the same whatever the block sizes."""

    #: Raw input samples kept: more than the longest filter.
    HISTORY = 1024

    def __init__(self):
        self.history = None

    def process(self, x, taps, floor=None):
        """x through taps (None: x as it is), continuing the stream.
        floor, when given, is the lowest level the decoder writes (its
        clipped sync tip): the filter's ringing on the sync edges below
        it is not picture and is held there."""
        x = np.asarray(x, dtype=np.float64)
        if len(x) == 0:
            return x
        hist = self.history
        if hist is None:
            hist = np.full(self.HISTORY, x[0])
        self.history = np.concatenate([hist, x])[-self.HISTORY:]
        if taps is None:
            return x
        taps = np.asarray(taps, dtype=np.float64)
        y, _ = causal_filter(x, taps, hist[len(hist) - (len(taps) - 1):]
                             if len(taps) > 1 else None)
        return y if floor is None else np.maximum(y, floor)
