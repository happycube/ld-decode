"""
stack - multi-source RF stacking with read-time time-base correction

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Combines several raw RF captures of the same disc into ONE synthetic RF
stream, in the RF domain, BEFORE demodulation: the ordinary decoder then
reads that stream unchanged, so its sync, VBI, dropout and output
resampling stages are the same code.

Pass 0 locates every input's lines straight from the RF
(:mod:`lddecode.rf_sync`) and keeps, per field, the VBI frame code, the
parity and the absolute position of each line.  Fields of the same frame
are paired across the inputs by their frame code and parity, and the
primary's (the first input's) lines define a timeline of nominal-length
lines, laid down as far as every input is located.  Each output sample
then reads every input at its own position for that instant; the inputs
are combined with 1/sigma^2 weights (scaled by each input's carrier
amplitude, per sample, in the "adaptive" mode) and the result is the
stream the decoder reads.

Each input is read with two filters evaluated at the fractional position:
a Kaiser-windowed sinc (the full signal) and an analytic video-band
filter (above ~3 MHz).  The video band is phase-locked to the primary's
over 128 samples before the sum; the rest (the full signal minus the
video band: the EFM and the analog audio carriers) is summed as read,
since a phase lock tuned on the video carrier would be wrong there.

The fractional-delay filters are the hottest loops of the module and run
in Numba (``_fir_kernel``); the rest is vectorised NumPy.

The sibling modules are imported lazily, so this module stands alone:

* :mod:`lddecode.rf_sync` - the line locator (``locate_fields`` below is
  the seam onto it) and the frame code.
* :mod:`lddecode.stack_corrections` - the crystal-line cleaner
  (``CrystalLines``) and the audio crosstalk and chroma leak
  cancellations (``cancel_crosstalk``, ``cancel_chroma_leak``).  The two
  cancellations are called as ``cancel(out, band, fs, ...)`` with the
  combined stream ``out`` and its combined analytic video band ``band``
  (both in the signal's own units), as the Rust does.
"""

from __future__ import annotations

import logging
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np
from numba import njit
from scipy.special import i0 as _bessel_i0

from .rf_sync import _round_half_away, frame_code

__all__ = [
    "StackInput",
    "StackedSource",
    "Timeline",
    "build_timeline",
    "locate_fields",
    "carrier_lag",
    "carrier_measure",
    "amp_weight",
    "phase_lock",
    "sinc_lut",
    "video_band_lut",
    "noise_floor",
]

_logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Constants (from the Rust implementation this module is ported from; every
# one of them is explained there).
# --------------------------------------------------------------------------

#: Virtual samples per parallel task: small enough that one decoder read
#: (~2M samples) splits into more tasks than there are cores.
TASK = 1 << 16
#: Largest input span one read may cover; an input that jumps further within
#: one read (a skip in that capture) is left out of that read.
MAX_SPAN = 1 << 25
#: FFT length of the noise-floor estimate.
NOISE_FFT = 1 << 17
#: Virtual samples computed beyond each end of a task for the phase lock.
LOCK_MARGIN = 128
#: Phase-lock window (samples).
LOCK_WIN = 128
#: Kaiser-windowed sinc: taps, beta, fractional phases tabulated.
SINC_TAPS = 32
SINC_BETA = 8.0
SINC_PHASES = 1024
#: Crossover between the summed low band and the phase-locked video band
#: (a raised cosine from 2.5 to 3.5 MHz).
SPLIT_LO_HZ = 2.5e6
SPLIT_HI_HZ = 3.5e6
#: PAL: the video FM's lower chroma sideband reaches down to ~2.7 MHz (the
#: pilot's to 3.0), while the EFM stays below 1.75 MHz and the audio
#: carriers at 0.68 / 1.07 MHz.
PAL_SPLIT_HZ = (1.9e6, 2.4e6)
#: Video-band filter: taps and Kaiser beta.  Only the crossover's shape
#: depends on it (the low band is the full signal minus this band), and 128
#: taps put the leakage across the crossover near -37 dB.
HI_TAPS = 128
HI_BETA = 8.0
#: Audio crosstalk cancellation: the analog audio carriers (Hz), NTSC and PAL.
AUDIO_CARRIERS_HZ = (2.301136e6, 2.8125e6)
PAL_AUDIO_CARRIERS_HZ = (0.68359375e6, 1.06640625e6)
#: The correction is kept above this raised-cosine edge (Hz, NTSC; PAL: its
#: video band split): the video is demodulated from above it, the audio
#: carriers and the EFM sit below.
XTALK_KEEP_HZ = (3.0e6, 3.6e6)
#: Chroma leak cancellation (NTSC): the band the leak is fitted in (rising
#: and falling raised-cosine edges, Hz: the chroma, 3.58 MHz +- 0.6).
LEAK_BAND_HZ = ((2.9e6, 3.1e6), (4.1e6, 4.3e6))
#: Band used to estimate each input's noise floor (no signal there), kept
#: below ``NOISE_TOP`` of the Nyquist frequency (the capture's anti-alias
#: filter); where less than ``NOISE_MIN_BW`` of it remains (a capture at
#: 30 MHz), it reaches down to ``NOISE_LOW_HZ``, where the RF has already
#: fallen to the floor.
NOISE_BAND_HZ = (16.0e6, 19.5e6)
NOISE_TOP = 0.95
NOISE_MIN_BW = 1.0e6
NOISE_LOW_HZ = 13.5e6
#: The floor of the noise-floor estimate (a variance, in signal units
#: squared).
NOISE_FLOOR = 1e-12
#: A paired line whose length differs from the primary's by more than this
#: ratio is treated as a skip in that input (not covered).
MAX_LINE_RATIO_DEV = 0.02
#: Amplitude weight floor, as a fraction of the input's video-band noise
#: RMS: where every input has lost its carrier the sum still has weights.
AMP_FLOOR = 0.05
#: Weight of the zero-phase prior of the phase lock, against the window's
#: ``samples * snr`` (an ordinary lock is ~10^3 or more): pass 0 aligns the
#: carriers within a few hundredths of a radian, so where the measured
#: rotation is noise (a dropout in either input) the lock holds still.
LOCK_PRIOR = 10.0
#: Alignment guard: the coherence with the primary over the lock window, as
#: a fraction of what the two inputs' carrier fractions allow, below which an
#: input is left out (fading in over ``KAPPA_SPAN``).  It applies once that
#: expected coherence squared exceeds ``Q_LO`` (fully from ``Q_LO +
#: Q_SPAN``): unless both carriers are clean over the whole window (a
#: dropout in either lowers the coherence as a misalignment would) the
#: coherence says nothing about alignment.
KAPPA_LO = 0.5
KAPPA_SPAN = 0.3
Q_LO = 0.7
Q_SPAN = 0.15
#: The lock follows its measured rotation above this expected coherence
#: squared, and holds still (``LOCK_PRIOR``) below.
Q_ROT = 0.5
#: The guard applies only where the primary keeps at the sample (carrier
#: window) at least this fraction of its carrier over the lock window, fully
#: from ``H_LO + H_SPAN``.
H_LO = 0.5
H_SPAN = 0.3
#: Window of the carrier measure behind the weights, centred on the sample:
#: short, so an input weighs little as soon as the sample itself is in a
#: dropout (over the lock window, a part of healthy carrier would dominate).
CARRIER_WIN = 64
#: Ceiling of a carrier fraction (the lock's ``snr`` stays finite).
Q_MAX = 0.999
#: What the carrier measure reads on noise alone, over the lock window and
#: over the carrier window (about its 99th and 90th percentiles on the video
#: band's noise; a carrier reads ~0.99): taken out, so a dropout reads no
#: carrier.
QN_LOCK = 0.4
QN_CARRIER = 0.5
#: Band width the carrier lag is set from: the video band's noise
#: decorrelates after about ``fs / CARRIER_BW`` samples.
CARRIER_BW = 15.0e6
#: A secondary input's field is paired only once this many later fields of
#: that input are known, so a frame code it repeats within them (a skip back
#: in that capture) is seen as ambiguous and left out, as a whole-file pass
#: would.
PAIR_LOOKAHEAD = 16
#: Virtual samples per read-ahead chunk.
CHUNK = 1 << 21
#: Chunks computed ahead of the decoder's read position.
AHEAD = 3
#: Chunks kept behind it, for the decoder's short rewinds.
BEHIND = 1
#: Where the disc's own signal makes steady lines, left out of the crystal
#: search (Hz, NTSC then PAL): the analog audio carriers, the chroma leak's
#: band, and the video carrier's swing.  The crystal-line module holds these
#: bands; they are named here for the record.
LINE_EXCLUDE_HZ = ((2.1e6, 2.5e6), (2.6e6, 3.0e6), (3.2e6, 4.0e6), (7.3e6, 9.6e6))
PAL_LINE_EXCLUDE_HZ = ((0.48e6, 0.88e6), (0.86e6, 1.27e6), (4.0e6, 4.9e6), (6.4e6, 8.3e6))
#: The line frequency the crystal search leaves alone (Hz): a still
#: picture's RF is a comb of lines at the picture's own line frequency.
LINE_HZ_NTSC = 15734.264
LINE_HZ_PAL = 15625.0
#: The video standard's line length (microseconds): NTSC's line is
#: 227.5 / fsc long (63.5555... us), PAL's is 64 us.
NTSC_LINE_US = 227.5e6 * 88.0 / 315.0e6
PAL_LINE_US = 64.0
#: The video standards' names, as the rest of the project spells them.
SYSTEM_NTSC = "NTSC"
SYSTEM_PAL = "PAL"


# --------------------------------------------------------------------------
# The inputs
# --------------------------------------------------------------------------


@dataclass
class StackInput:
    """One capture of the stack.

    Parameters
    ----------
    path : str
        The capture's name (for the log and the error messages).
    read_fn : Callable[[int, int], np.ndarray]
        The capture's samples: ``read_fn(start_sample, count)`` returns
        ``count`` samples (float) from ``start_sample``.  Samples before
        the capture and past its end read as zero.
    length : int
        The capture's length, in samples.
    """

    path: str
    read_fn: Callable[[int, int], np.ndarray]
    length: int


# --------------------------------------------------------------------------
# The filters
# --------------------------------------------------------------------------


def sinc_lut() -> np.ndarray:
    """The Kaiser-windowed sinc table.

    Returns a ``(SINC_PHASES + 1, SINC_TAPS)`` float64 array: row ``p`` is
    the filter for the fractional position ``p / SINC_PHASES``, its taps at
    the offsets ``-(SINC_TAPS/2 - 1) ..= SINC_TAPS/2`` from the integer
    sample, each row normalised to a unit sum.
    """
    half = SINC_TAPS // 2
    i0b = float(_bessel_i0(SINC_BETA))
    frac = np.arange(SINC_PHASES + 1, dtype=np.float64) / SINC_PHASES
    taps = np.arange(SINC_TAPS, dtype=np.float64)
    x = (taps - (half - 1))[None, :] - frac[:, None]
    window = np.maximum(0.0, 1.0 - (x / half) ** 2)
    row = np.sinc(x) * (_bessel_i0(SINC_BETA * np.sqrt(window)) / i0b)
    return row / row.sum(axis=1, keepdims=True)


def _int_exp(c: np.ndarray, a: float, b: float) -> np.ndarray:
    """The integral of ``exp(j c f)`` from ``a`` to ``b``, over the array ``c``."""
    width = b - a
    with np.errstate(invalid="ignore", divide="ignore"):
        limit = width * np.exp(0.5j * c * (a + b))
        general = (np.exp(1j * c * b) - np.exp(1j * c * a)) / (1j * c)
        return np.where(np.abs(c * width) < 1e-9, limit, general)


def _video_band_response(
    tau: np.ndarray, fs: float, split: tuple[float, float], top: tuple[float, float]
) -> np.ndarray:
    """The impulse response, at ``tau`` input samples, of the analytic video band.

    ``2 g(f)`` for f > 0 and 0 below, ``g`` rising as a raised cosine over
    ``split``, flat, then falling over ``top`` (a raised cosine too, so the
    response stays short).  Closed form, so the table is exact.
    """
    pi = np.pi
    c = 2.0 * pi * tau / fs

    def edge(f0: float, f1: float, sign: float) -> np.ndarray:
        k = pi / (f1 - f0)
        cosine = 0.5 * np.exp(-1j * k * f0) * _int_exp(c + k, f0, f1) + 0.5 * np.exp(
            1j * k * f0
        ) * _int_exp(c - k, f0, f1)
        return _int_exp(c, f0, f1) * 0.5 + cosine * (0.5 * sign)

    total = (
        edge(split[0], split[1], -1.0) + _int_exp(c, split[1], top[0]) + edge(top[0], top[1], 1.0)
    )
    return total * (2.0 / fs)


def video_band_lut(fs: float, split: tuple[float, float]) -> np.ndarray:
    """The video-band filter at the sinc's fractional phases.

    Returns a ``(SINC_PHASES + 1, HI_TAPS)`` complex128 array: row ``p``
    holds the filter for the fractional position ``p / SINC_PHASES``, tap
    ``d`` weighting the input sample ``k0 - (HI_TAPS/2 - 1) + d`` for a
    position ``k0 + p/SINC_PHASES``, Kaiser windowed.
    """
    top = (min(18.0e6, 0.4 * fs), min(22.0e6, 0.5 * fs))
    half = HI_TAPS // 2
    i0b = float(_bessel_i0(HI_BETA))
    frac = np.arange(SINC_PHASES + 1, dtype=np.float64) / SINC_PHASES
    taps = np.arange(HI_TAPS, dtype=np.float64)
    tau = frac[:, None] + (half - 1) - taps[None, :]
    window = np.maximum(0.0, 1.0 - (tau / half) ** 2)
    return _video_band_response(tau, fs, split, top) * (_bessel_i0(HI_BETA * np.sqrt(window)) / i0b)


@njit(cache=True, nogil=True)
def _fir_kernel(
    raw: np.ndarray,
    base: np.ndarray,
    phase: np.ndarray,
    lut: np.ndarray,
    first_tap: int,
    out: np.ndarray,
) -> None:
    """The tabulated fractional-delay filter at the given positions.

    One output per position: the taps of the filter's phase applied to the
    input's samples around it, the samples outside the input read as its
    first or its last one (the same clipping the NumPy path does).

    Parameters
    ----------
    raw : numpy.ndarray
        The input's samples (float64, contiguous).
    base : numpy.ndarray
        The integer sample of each position (int64).
    phase : numpy.ndarray
        The fractional phase of each position (int64): the row of `lut`.
    lut : numpy.ndarray
        The filter table (float64, one row per phase).
    first_tap : int
        The offset of the table's first tap from the integer sample.
    out : numpy.ndarray
        Where the outputs are written (float64, one per position).
    """
    ntaps = lut.shape[1]
    limit = raw.shape[0] - 1
    if limit < 0:
        return
    nphases = lut.shape[0]
    for i in range(base.shape[0]):
        b = base[i]
        p = phase[i]
        if p < 0:
            p = 0
        elif p >= nphases:
            p = nphases - 1
        s = 0.0
        for d in range(ntaps):
            idx = b + d - first_tap
            if idx < 0:
                idx = 0
            elif idx > limit:
                idx = limit
            s += lut[p, d] * raw[idx]
        out[i] = s


def _fir(
    raw: np.ndarray, base: np.ndarray, phase: np.ndarray, lut: np.ndarray, first_tap: int
) -> np.ndarray:
    """Evaluate a tabulated fractional-delay filter at the given positions.

    ``raw`` is the input's samples, ``base`` the integer sample of each
    position (as an index into ``raw``), ``phase`` the fractional phase of
    each position and ``lut`` the filter table (``(phases + 1, taps)``).
    ``first_tap`` is the offset of the table's first tap from the integer
    sample.  Returns a new float64 array.
    """
    out = np.zeros(base.shape, dtype=np.float64)
    _fir_kernel(
        np.ascontiguousarray(raw, dtype=np.float64),
        np.ascontiguousarray(base, dtype=np.int64),
        np.ascontiguousarray(phase, dtype=np.int64),
        np.ascontiguousarray(lut, dtype=np.float64),
        int(first_tap),
        out,
    )
    return out


# --------------------------------------------------------------------------
# The carrier measure, the weights and the phase lock
# --------------------------------------------------------------------------


def carrier_lag(fs: float) -> int:
    """The carrier lag, in samples, at a sample rate ``fs`` (Hz).

    The video band's noise decorrelates after about ``fs / CARRIER_BW``
    samples; the lag is at least one sample.  The rounding is the
    reference's (half away from zero).
    """
    return max(1, int(math.floor(fs / CARRIER_BW + 0.5)))


def carrier_measure(rl: complex, e: float, n: float, qn: float) -> tuple[np.floating, np.floating]:
    """The carrier power and carrier fraction of a video band.

    Parameters
    ----------
    rl : complex
        ``sum(z[t] * conj(z[t - lag]))`` over the window: the correlation
        of the band with itself one lag earlier.
    e : float
        The energy of those ``z[t]``.
    n : float
        How many samples the window holds (must be positive).
    qn : float
        What the measure reads on noise alone, as a fraction of the energy.

    Returns
    -------
    (s, q) : tuple[numpy.floating, numpy.floating]
        The carrier power (the signal's own units squared) and the carrier
        fraction (dimensionless, 0..1).
    """
    rl = np.asarray(rl, dtype=np.complex128)
    e = np.asarray(e, dtype=np.float64)
    n = np.asarray(n, dtype=np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.abs(rl)
        s = np.maximum(0.0, a - qn * e) / ((1.0 - qn) * n)
        q = np.where(
            e > 0.0,
            np.minimum(Q_MAX, np.maximum(0.0, a / e - qn) / (1.0 - qn)),
            0.0,
        )
    return s, q


def amp_weight(s: float, afl: float, w: float) -> np.floating:
    """An input's weight at one sample, from its carrier power ``s``.

    The carrier amplitude (floored at ``afl``) times the maximal-ratio
    combining weight ``w`` (1/sigma^2).
    """
    s = np.asarray(s, dtype=np.float64)
    return np.maximum(np.sqrt(np.maximum(s, 0.0)), afl) * w


def phase_lock(
    r: complex, ea: float, eb: float, nj: float, q0: float, qi: float, h0: float
) -> tuple[np.ndarray, np.ndarray]:
    """The phase lock of an input onto the primary over the lock window.

    Parameters
    ----------
    r : complex
        The correlation of the two bands over the window.
    ea, eb : float
        The energies of the two bands over the window.
    nj : float
        How many samples the two bands share over the window.
    q0, qi : float
        The carrier fractions of the primary and of this input over the
        window.
    h0 : float
        How much of the primary's carrier it keeps at the sample itself.

    Returns
    -------
    (rot, g) : tuple[numpy.ndarray, numpy.ndarray]
        The rotation to apply to this input's video band, and the factor
        its weight is scaled by (the alignment guard).
    """
    r = np.asarray(r, dtype=np.complex128)
    ea = np.asarray(ea, dtype=np.float64)
    eb = np.asarray(eb, dtype=np.float64)
    nj = np.asarray(nj, dtype=np.float64)
    q0 = np.asarray(q0, dtype=np.float64)
    qi = np.asarray(qi, dtype=np.float64)
    h0 = np.asarray(h0, dtype=np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        q = q0 * qi
        a = np.abs(r)
        denom = np.sqrt(ea * eb)
        kappa = np.where(
            denom > 0.0,
            a / np.where(denom > 0.0, denom, 1.0) / np.sqrt(np.where(q > 0.0, q, 1.0)),
            np.inf,
        )
        gk = np.clip((kappa - KAPPA_LO) / KAPPA_SPAN, 0.0, 1.0)
        # Only with the primary's carrier at the sample itself: at the edge
        # of a dropout of the primary the window still reads its carrier, but
        # the coherence falls, and the input left out would be the healthy
        # one.
        hp = np.clip((h0 - H_LO) / H_SPAN, 0.0, 1.0)
        g = 1.0 - (1.0 - gk) * np.minimum((q - Q_LO) / Q_SPAN, 1.0) * hp
        g = np.where(q > Q_LO, g, 1.0)
        # The measured rotation counts only where both carriers are clearly
        # healthy: a window part noise gives a rotation part noise.
        qr = np.maximum(0.0, (q - Q_ROT) / (1.0 - Q_ROT))
        wm = nj * qr / (1.0 - qr)
        safe_a = np.where(a > 0.0, a, 1.0)
        vx = (r.real / safe_a) * wm + LOCK_PRIOR
        vy = (r.imag / safe_a) * wm
        b = np.hypot(vx, vy)
        rot = np.where((a > 0.0) & (b > 0.0), (vx + 1j * vy) / np.where(b > 0.0, b, 1.0), 1.0 + 0j)
    return rot, g


# --------------------------------------------------------------------------
# The timeline
# --------------------------------------------------------------------------


class Timeline:
    """The line anchors of the virtual stream.

    Attributes
    ----------
    t : numpy.ndarray
        The ideal time of each anchor (samples of the virtual stream).
    pos : list[numpy.ndarray]
        Per input, its absolute position (input samples) at each anchor;
        NaN where the input does not cover that anchor.
    """

    def __init__(self, t: np.ndarray, pos: Sequence[np.ndarray]) -> None:
        self.t = np.asarray(t, dtype=np.float64)
        self.pos = [np.asarray(p, dtype=np.float64) for p in pos]

    def __len__(self) -> int:
        return int(self.t.shape[0])

    def segment(self, s: float) -> int:
        """The index of the anchor segment containing the ideal time ``s``.

        The last segment past the end of the timeline.
        """
        if self.t.shape[0] < 2:
            return 0
        k = int(np.searchsorted(self.t, s, side="right")) - 1
        if k < 0:
            return 0
        return min(k, self.t.shape[0] - 2)

    def position(self, i: int, k: int, s: float) -> float:
        """The position of input ``i`` at the ideal time ``s`` within segment ``k``.

        NaN where the input does not cover the segment, or where its line
        length differs from the primary's by more than
        ``MAX_LINE_RATIO_DEV``.
        """
        a0 = float(self.pos[i][k])
        a1 = float(self.pos[i][k + 1])
        if not (np.isfinite(a0) and np.isfinite(a1)):
            return float("nan")
        if i > 0:
            p0 = float(self.pos[0][k])
            p1 = float(self.pos[0][k + 1])
            ratio = (a1 - a0) / (p1 - p0)
            if abs(ratio - 1.0) > MAX_LINE_RATIO_DEV:
                return float("nan")
        u = (s - self.t[k]) / (self.t[k + 1] - self.t[k])
        return a0 + u * (a1 - a0)


def _rec_lines(rec: object) -> np.ndarray:
    """The absolute position of each line of a pass-0 field record."""
    lines = getattr(rec, "lines", None)
    if lines is None:
        raise TypeError(f"a field record has no lines: {rec!r}")
    return np.asarray(lines, dtype=np.float64)


def _rec_first(rec: object) -> bool:
    """The parity of a pass-0 field record: True for the first field of a frame."""
    for name in ("first", "parity"):
        value = getattr(rec, name, None)
        if value is not None:
            return bool(value)
    raise TypeError(f"a field record has no parity: {rec!r}")


def _frame_code(words: Sequence[int]) -> list[int]:
    """The frame code words of a field: the ones that identify its frame.

    :func:`lddecode.rf_sync.frame_code` reduces the VBI words to the CAV
    picture numbers and the CLV time codes.
    """
    return [int(w) for w in frame_code(list(words))]


def _rec_key(rec: object) -> tuple[tuple[int, ...], bool] | None:
    """The pairing key of a pass-0 field record: its frame code and its parity.

    None where the field carries no frame code (it cannot be paired).
    """
    code = getattr(rec, "code", None)
    if code is None:
        return None
    words = _frame_code(code)
    if not words:
        return None
    return (tuple(words), _rec_first(rec))


def build_timeline(
    fields: Sequence[Sequence[object]], linelen: float, primary_length: int
) -> Timeline:
    """The virtual timeline from the pass-0 field records of every input.

    The fields of the same frame are paired across the inputs by their
    frame code and their parity.  A secondary's field is examined only
    once this many later fields of that input are known (``PAIR_LOOKAHEAD``),
    so a frame code it repeats within them (a skip back in that capture) is
    seen as ambiguous and the field is left unpaired, as a whole-file pass
    would leave it.

    The primary's lines define the timeline: each of them is an anchor, at
    an ideal time of the nominal line length from the previous one (at half
    a line's resolution), and every input's position at that anchor is
    where its own line of the same field sits (NaN where it does not cover
    it).

    Parameters
    ----------
    fields : Sequence[Sequence[object]]
        Per input, its pass-0 field records; ``fields[0]`` is the primary's.
        A record carries ``lines`` (the absolute position of each line, in
        input samples), ``code`` (the frame code words, empty when the
        field's frame was not identified) and ``first`` (the parity).
    linelen : float
        The nominal line length, in samples.
    primary_length : int
        The primary's length, in samples: the stream's tail ends there.

    Returns
    -------
    Timeline
        The anchors of the virtual stream.

    Raises
    ------
    ValueError
        When the primary has no usable line.
    """
    ninputs = len(fields)
    primary = fields[0]

    # The secondaries' keys: the field of each frame code, or None where the
    # code repeats in that input (ambiguous, so the field is left unpaired).
    # A repeat within PAIR_LOOKAHEAD fields is seen as the field is examined;
    # a later repeat leaves the key ambiguous as well, so the field is never
    # paired with the wrong one.
    sec_maps: list[dict[tuple[tuple[int, ...], bool], int | None]] = []
    for s in range(1, ninputs):
        smap: dict[tuple[tuple[int, ...], bool], int | None] = {}
        for index, rec in enumerate(fields[s]):
            key = _rec_key(rec)
            if key is None:
                continue
            if key in smap:
                smap[key] = None
                continue
            end = min(index + 1 + PAIR_LOOKAHEAD, len(fields[s]))
            repeated = any(_rec_key(other) == key for other in fields[s][index + 1 : end])
            smap[key] = None if repeated else index
        sec_maps.append(smap)

    times: list[float] = []
    positions: list[list[float]] = [[] for _ in range(ninputs)]
    last = -np.inf
    for rec in primary:
        key = _rec_key(rec)
        matched: list[int | None] = [None] * ninputs
        for s in range(1, ninputs):
            if key is not None:
                matched[s] = sec_maps[s - 1].get(key)
        primary_lines = _rec_lines(rec)
        secondary_lines = [
            _rec_lines(fields[s][matched[s]]) if matched[s] is not None else None
            for s in range(1, ninputs)
        ]
        for line, a in enumerate(primary_lines):
            # Fields overlap by a few lines; keep each line once, in order.
            if a <= last + 0.25 * linelen:
                continue
            if not times:
                # The timeline starts at the primary's own first line;
                # before it, the primary alone at its own rate (the decoder
                # needs that lead-in to find the first field).
                if a >= 1.0:
                    times.append(0.0)
                    positions[0].append(0.0)
                    for p in positions[1:]:
                        p.append(float("nan"))
                tk = float(a)
            else:
                # Half-line resolution: the ideal time of an anchor.
                # The rounding is the reference's (half away from zero), so
                # an exact half lands on the same side as in the Rust.
                lines = max(
                    0.5,
                    _round_half_away(2.0 * (a - last) / linelen) / 2.0,
                )
                tk = times[-1] + lines * linelen
            times.append(tk)
            positions[0].append(float(a))
            for s in range(1, ninputs):
                lines_s = secondary_lines[s - 1]
                p = float("nan")
                if lines_s is not None and line < lines_s.shape[0]:
                    p = float(lines_s[line])
                positions[s].append(p)
            last = a

    if len(times) < 2:
        raise ValueError("pass 0 found no usable lines in the primary input")

    # After the last line, the primary alone again (the tail).
    tail = float(primary_length) - positions[0][-1]
    if tail >= 1.0:
        times.append(times[-1] + tail)
        positions[0].append(positions[0][-1] + tail)
        for p in positions[1:]:
            p.append(float("nan"))

    return Timeline(np.asarray(times, dtype=np.float64), positions)


# --------------------------------------------------------------------------
# Pass 0
# --------------------------------------------------------------------------


def locate_fields(
    read_fn: Callable[[int, int], np.ndarray],
    fs: float,
    ntsc: bool,
    stop: object = None,
    length: int | None = None,
) -> list:
    """Locate the lines of one input, from its RF.

    This is the seam onto :func:`lddecode.rf_sync.locate` (imported lazily,
    so this module stands alone); the pass-0 records it returns are the
    field records :func:`build_timeline` takes.

    Parameters
    ----------
    read_fn : Callable[[int, int], np.ndarray]
        The input's samples: ``read_fn(start_sample, count)``.
    fs : float
        The capture's sample rate, in Hz.
    ntsc : bool
        True for NTSC, False for PAL.
    stop : object
        An optional callable the locator polls to know it may stop.
    length : int, optional
        The capture's length, in samples.  The scan stops there; without it
        the reader has to report the end of the capture by returning fewer
        samples than were asked for.

    Returns
    -------
    list
        The input's field records, in order.
    """
    from .rf_sync import locate, system_for

    return list(locate(read_fn, fs, system_for(ntsc), stop=stop, length=length))


# --------------------------------------------------------------------------
# The plan and the reads
# --------------------------------------------------------------------------


@dataclass
class _InputSpan:
    """One input's samples, and where they are read for a span of the stream."""

    raw: np.ndarray
    start: int
    positions: np.ndarray


@dataclass
class _Plan:
    """What one span of virtual samples needs from the inputs."""

    s0: float
    length: int
    seg: np.ndarray
    seg_t0: np.ndarray
    inputs: list[_InputSpan | None]


def _read_span(reader: Callable[[int, int], np.ndarray], start: int, count: int) -> np.ndarray:
    """The samples ``[start, start + count)`` of an input, as float64.

    Samples past the capture's end read as zero, so a span may overhang
    either end.
    """
    if count <= 0:
        return np.zeros(0, dtype=np.float64)
    data = np.asarray(reader(int(start), int(count)), dtype=np.float64).ravel()
    if data.shape[0] < count:
        data = np.concatenate((data, np.zeros(count - data.shape[0], dtype=np.float64)))
    elif data.shape[0] > count:
        data = data[:count]
    return data


def _plan(
    timeline: Timeline,
    s0: float,
    length: int,
    inputs: Sequence[StackInput],
    readers: Sequence[Callable[[int, int], np.ndarray]],
) -> _Plan:
    """The plan for the virtual samples ``[s0, s0 + length)``.

    Every input's position is absolute, so a position rounds the same
    whatever span or chunk it is computed in.
    """
    t = timeline.t
    first = timeline.segment(s0)
    last = min(timeline.segment(s0 + length - 1) + 1, t.shape[0] - 1)
    seg_t = t[first : last + 1]
    nseg = seg_t.shape[0] - 1
    times = s0 + np.arange(length, dtype=np.float64)
    seg = np.searchsorted(seg_t, times, side="right") - 1
    np.clip(seg, 0, max(nseg - 1, 0), out=seg)

    spans: list[_InputSpan | None] = []
    prim0 = timeline.pos[0][first:last]
    prim1 = timeline.pos[0][first + 1 : last + 1]
    span_times = seg_t[:nseg]
    span_width = seg_t[1 : nseg + 1] - span_times
    for i, inp in enumerate(inputs):
        a0 = timeline.pos[i][first:last].copy()
        a1 = timeline.pos[i][first + 1 : last + 1].copy()
        if i > 0:
            with np.errstate(invalid="ignore", divide="ignore"):
                ratio = (a1 - a0) / (prim1 - prim0)
            bad = np.abs(ratio - 1.0) > MAX_LINE_RATIO_DEV
            a0 = np.where(bad | ~np.isfinite(a0), np.nan, a0)
            a1 = np.where(bad | ~np.isfinite(a1), np.nan, a1)
        slope = (a1 - a0) / span_width
        positions = a0[seg] + (times - span_times[seg]) * slope[seg]
        covered = np.isfinite(positions)
        if not covered.any():
            spans.append(None)
            continue
        pmin = float(np.min(positions[covered]))
        pmax = float(np.max(positions[covered]))
        margin = HI_TAPS // 2 + 2
        start = int(np.floor(pmin)) - margin
        end = int(np.floor(pmax)) + margin
        if end - start > MAX_SPAN:
            _logger.warning(
                "stack: %s jumps %.0f samples within one read near virtual sample %.0f;"
                " left out there",
                inp.path,
                pmax - pmin,
                s0,
            )
            spans.append(None)
            continue
        raw = _read_span(readers[i], start, end - start)
        spans.append(_InputSpan(raw=raw, start=start, positions=positions))
    return _Plan(s0=s0, length=length, seg=seg, seg_t0=span_times, inputs=spans)


def _read_input(
    span: _InputSpan, sinc: np.ndarray, hi: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Read one input at its own positions.

    Returns the full signal, the analytic video band and the coverage (which
    samples the input covers at all).
    """
    positions = span.positions
    length = positions.shape[0]
    full = np.zeros(length, dtype=np.float64)
    band = np.zeros(length, dtype=np.complex128)
    covered = np.isfinite(positions)
    index = np.flatnonzero(covered)
    if index.size == 0:
        return full, band, covered
    pos = positions[index]
    k0 = np.floor(pos)
    # The phase is rounded half away from zero, as the reference does.
    phase = np.floor((pos - k0) * SINC_PHASES + 0.5).astype(np.int64)
    np.clip(phase, 0, SINC_PHASES, out=phase)
    base = k0.astype(np.int64) - span.start
    raw = span.raw
    full[index] = _fir(raw, base, phase, sinc, SINC_TAPS // 2 - 1)
    band[index] = _fir(raw, base, phase, hi.real, HI_TAPS // 2 - 1) + 1j * _fir(
        raw, base, phase, hi.imag, HI_TAPS // 2 - 1
    )
    return full, band, covered


def _carrier_terms(
    band: np.ndarray, covered: np.ndarray, lag: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """An input's carrier terms per sample: the lag product, the energy, the count.

    A sample counts only where it and the sample one lag earlier are both
    covered.
    """
    length = band.shape[0]
    rl = np.zeros(length, dtype=np.complex128)
    energy = np.zeros(length, dtype=np.float64)
    count = np.zeros(length, dtype=np.float64)
    if lag < length:
        mask = covered[lag:] & covered[:-lag]
        rl[lag:] = np.where(mask, band[lag:] * np.conj(band[:-lag]), 0.0)
        energy[lag:] = np.where(mask, np.abs(band[lag:]) ** 2, 0.0)
        count[lag:] = mask
    return rl, energy, count


def _prefix(values: np.ndarray) -> np.ndarray:
    """The running sum of ``values``, with a leading zero (length + 1)."""
    out = np.zeros(values.shape[0] + 1, dtype=values.dtype)
    np.cumsum(values, out=out[1:])
    return out


def _window_pair(
    prefix_rl: np.ndarray,
    prefix_energy: np.ndarray,
    prefix_count: np.ndarray,
    j: np.ndarray,
    half: int,
    length: int,
) -> tuple[tuple[np.ndarray, np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """The lock window's and the carrier window's sums, centred on ``j``."""
    lo = np.maximum(j - half, 0)
    hi = np.minimum(j + half, length)
    lock = (
        prefix_rl[hi] - prefix_rl[lo],
        prefix_energy[hi] - prefix_energy[lo],
        prefix_count[hi] - prefix_count[lo],
    )
    lo2 = np.maximum(j - (CARRIER_WIN // 2), 0)
    hi2 = np.minimum(j + (CARRIER_WIN // 2), length)
    short = (
        prefix_rl[hi2] - prefix_rl[lo2],
        prefix_energy[hi2] - prefix_energy[lo2],
        prefix_count[hi2] - prefix_count[lo2],
    )
    return lock, short


def _combine(
    reads: Sequence[tuple[np.ndarray, np.ndarray, np.ndarray]],
    weight: Sequence[float],
    afloor: Sequence[float],
    mode: str,
    lag: int,
    margin: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Combine the inputs' reads into the virtual stream.

    Parameters
    ----------
    reads : Sequence[tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray]]
        Per input, the full signal, the analytic video band and the
        coverage, over the extended range (the output range plus
        ``margin`` samples at each end).
    weight : Sequence[float]
        Per input, its maximal-ratio weight (1/sigma^2).
    afloor : Sequence[float]
        Per input, its amplitude weight floor.
    mode : str
        "adaptive" (every input weighted at every sample by its carrier
        amplitude, with the alignment guard) or "fixed" (the fixed
        1/sigma^2 weights and the plain phase lock).
    lag : int
        The carrier measure's lag, in samples.
    margin : int
        The samples of context at each end of the reads.

    Returns
    -------
    (out, wsum, band) : tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray]
        The combined stream, the sum of the weights at each sample and the
        combined analytic video band (all over the output range).
    """
    full0, band0, cov0 = reads[0]
    length = full0.shape[0]
    nout = length - 2 * margin
    j = np.arange(margin, margin + nout)
    half = LOCK_WIN // 2

    acc = np.zeros(nout, dtype=np.float64)
    wsum = np.zeros(nout, dtype=np.float64)
    vacc = np.zeros(nout, dtype=np.complex128)

    # The primary's carrier terms, over the lock window and the carrier one.
    rl0, e0, c0 = _carrier_terms(band0, cov0, lag)
    (rl_l, e_l, c_l), (rs_s, es_s, cs_s) = _window_pair(
        _prefix(rl0), _prefix(e0), _prefix(c0), j, half, length
    )
    has_lock = c_l > 0.0
    s_lock, q_lock = carrier_measure(rl_l, e_l, np.where(has_lock, c_l, 1.0), QN_LOCK)
    q0 = np.where(has_lock, q_lock, 0.0)
    has_short = cs_s > 0.0
    s_carrier, _ = carrier_measure(rs_s, es_s, np.where(has_short, cs_s, 1.0), QN_CARRIER)
    s0 = np.where(has_short, s_carrier, 0.0)
    h0 = np.where(has_lock & (s_lock > 0.0), s0 / np.where(s_lock > 0.0, s_lock, 1.0), 0.0)

    if mode == "fixed":
        # The fixed mode weighs every input by its 1/sigma^2 weight alone.
        w0 = np.full(nout, weight[0], dtype=np.float64)
    else:
        w0 = amp_weight(s0, afloor[0], weight[0])
    live0 = cov0[j]
    acc += np.where(live0, full0[j] * w0, 0.0)
    wsum += np.where(live0, w0, 0.0)
    vacc += np.where(live0, band0[j] * w0, 0.0)

    for i in range(1, len(reads)):
        full, band, cov = reads[i]
        live = cov[j]
        if not live.any():
            continue
        # The correlation with the primary over the lock window.
        joint = cov0 & cov
        cross = np.where(joint, band0 * np.conj(band), 0.0)
        ea = np.where(joint, np.abs(band0) ** 2, 0.0)
        eb = np.where(joint, np.abs(band) ** 2, 0.0)
        nj = joint.astype(np.float64)
        pre_cross, pre_ea, pre_eb, pre_nj = (
            _prefix(cross),
            _prefix(ea),
            _prefix(eb),
            _prefix(nj),
        )
        lo = np.maximum(j - half, 0)
        hi = np.minimum(j + half, length)
        r = pre_cross[hi] - pre_cross[lo]
        e_a = pre_ea[hi] - pre_ea[lo]
        e_b = pre_eb[hi] - pre_eb[lo]
        n_j = pre_nj[hi] - pre_nj[lo]

        # This input's own carrier terms.
        rli, ei, ci = _carrier_terms(band, cov, lag)
        (rli_l, ei_l, ci_l), (rsi_s, esi_s, csi_s) = _window_pair(
            _prefix(rli), _prefix(ei), _prefix(ci), j, half, length
        )
        has_lock_i = ci_l > 0.0
        qi = np.zeros(nout, dtype=np.float64)
        if has_lock_i.any():
            _, frac = carrier_measure(rli_l, ei_l, np.where(has_lock_i, ci_l, 1.0), QN_LOCK)
            qi = np.where(has_lock_i, frac, 0.0)
        has_short_i = csi_s > 0.0
        si = np.zeros(nout, dtype=np.float64)
        if has_short_i.any():
            power_s, _ = carrier_measure(
                rsi_s, esi_s, np.where(has_short_i, csi_s, 1.0), QN_CARRIER
            )
            si = np.where(has_short_i, power_s, 0.0)

        shared = n_j > 0.0
        if mode == "fixed":
            # The plain phase lock: the correlation, normalised.
            with np.errstate(invalid="ignore", divide="ignore"):
                mag = np.abs(r)
                rot = np.where(mag > 0.0, r / np.where(mag > 0.0, mag, 1.0), 1.0 + 0j)
            guard = np.ones(nout, dtype=np.float64)
            w = np.full(nout, weight[i], dtype=np.float64)
        else:
            rot, guard = phase_lock(r, e_a, e_b, n_j, q0, qi, h0)
            rot = np.where(shared, rot, 1.0 + 0j)
            guard = np.where(shared, guard, 1.0)
            w = amp_weight(si, afloor[i], weight[i]) * guard
        correction = np.real(band[j] * (rot - 1.0))
        acc += np.where(live, (full[j] + correction) * w, 0.0)
        wsum += np.where(live, w, 0.0)
        vacc += np.where(live, band[j] * rot * w, 0.0)

    safe = np.where(wsum > 0.0, wsum, 1.0)
    out = np.where(wsum > 0.0, acc / safe, 0.0)
    combined = np.where(wsum > 0.0, vacc / safe, 0.0)
    return out, wsum, combined


# --------------------------------------------------------------------------
# The noise floor
# --------------------------------------------------------------------------


def _noise_band(fs: float) -> tuple[float, float]:
    """The noise-floor band at a sample rate ``fs`` (Hz)."""
    top = NOISE_TOP * fs / 2.0
    lo, hi = NOISE_BAND_HZ[0], min(NOISE_BAND_HZ[1], top)
    if hi - lo >= NOISE_MIN_BW:
        return lo, hi
    if top - NOISE_LOW_HZ < NOISE_MIN_BW / 4.0:
        raise ValueError(f"input rate {fs} Hz too low: no noise-floor band left above the RF")
    return NOISE_LOW_HZ, top


def noise_floor(read_fn: Callable[[int, int], np.ndarray], start: int, fs: float) -> float:
    """The noise floor of an input, as a variance (the signal's units squared).

    Measured over a NOISE_FFT-long stretch of the capture from ``start``,
    in the band where the RF carries no signal; floored at ``NOISE_FLOOR``.
    """
    data = np.asarray(read_fn(int(start), NOISE_FFT), dtype=np.float64).ravel()
    if data.shape[0] < NOISE_FFT:
        data = np.concatenate((data, np.zeros(NOISE_FFT - data.shape[0], dtype=np.float64)))
    spectrum = np.fft.rfft(data)
    power = np.abs(spectrum) ** 2
    freqs = np.arange(power.shape[0], dtype=np.float64) * fs / NOISE_FFT
    lo, hi = _noise_band(fs)
    band = (freqs > lo) & (freqs < hi)
    if not band.any():
        raise ValueError(f"input rate {fs} Hz too low for the noise-floor band")
    sigma2 = float(power[band].mean() / NOISE_FFT)
    return max(sigma2, NOISE_FLOOR)


# --------------------------------------------------------------------------
# The read-ahead buffer
# --------------------------------------------------------------------------


class _ChunkCache:
    """The read-ahead buffer of the virtual stream.

    The producer computes the chunks the decoder is about to need, so the
    stacking overlaps the decode instead of stalling it on every read.
    """

    def __init__(
        self,
        compute: Callable[[int, int], np.ndarray],
        length: int,
        chunk: int = CHUNK,
        ahead: int = AHEAD,
        behind: int = BEHIND,
    ) -> None:
        self._compute = compute
        self._length = int(length)
        self._chunk = int(chunk)
        self._ahead = int(ahead)
        self._behind = int(behind)
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._chunks: dict[int, np.ndarray] = {}
        self._want = 0
        self._error: str | None = None
        self._stop = False
        self._thread = threading.Thread(target=self._produce, name="stack-ahead", daemon=True)
        self._thread.start()

    @property
    def count(self) -> int:
        """How many chunks the stream holds."""
        return (self._length + self._chunk - 1) // self._chunk

    def stop(self) -> None:
        """Stop the producer."""
        with self._cv:
            self._stop = True
            self._cv.notify_all()

    def get(self, index: int) -> np.ndarray | None:
        """The chunk ``index``, waiting for the producer; None past the end."""
        with self._cv:
            if index != self._want:
                self._want = index
                keep = index - self._behind
                self._chunks = {k: v for k, v in self._chunks.items() if k >= keep}
                self._cv.notify_all()
            while True:
                if self._error is not None:
                    raise RuntimeError(self._error)
                data = self._chunks.get(index)
                if data is not None:
                    return data
                if index >= self.count:
                    return None
                self._cv.wait()

    def _produce(self) -> None:
        try:
            self._produce_loop()
        except Exception as exc:  # noqa: BLE001 - reported to the reader
            with self._cv:
                self._error = f"{exc}"
                self._cv.notify_all()

    def _produce_loop(self) -> None:
        while True:
            with self._cv:
                while True:
                    if self._stop or self._error is not None:
                        return
                    target = None
                    for c in range(self._want, min(self._want + self._ahead, self.count)):
                        if c not in self._chunks:
                            target = c
                            break
                    if target is not None:
                        break
                    self._cv.wait()
            try:
                data = self._compute(target, self._chunk)
            except Exception as exc:  # noqa: BLE001 - reported to the reader
                with self._cv:
                    self._error = f"{exc}"
                    self._cv.notify_all()
                return
            with self._cv:
                self._chunks[target] = data
                keep = self._want - self._behind
                self._chunks = {k: v for k, v in self._chunks.items() if k >= keep}
                self._cv.notify_all()


class _RfOut:
    """The ``--rf-out`` file: the RF the decoder reads, as s16.

    The samples are written at their place in the stream, so a chunk that is
    computed late leaves the span it skipped at zero.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._file = None

    def write(self, offset: int, data: np.ndarray) -> None:
        """Write the samples of the stream from ``offset`` (samples)."""
        if self._file is None:
            self._file = open(self.path, "wb")
        values = np.clip(np.rint(data), -32768.0, 32767.0).astype("<i2")
        self._file.seek(int(offset) * 2)
        self._file.write(values.tobytes())

    def close(self) -> None:
        """Close the file."""
        if self._file is not None:
            self._file.close()
            self._file = None


# --------------------------------------------------------------------------
# The source
# --------------------------------------------------------------------------


class StackedSource:
    """Serves the stacked, time-base-corrected RF stream to the decoder.

    Parameters
    ----------
    inputs : list[StackInput]
        The captures of the stack; the first is the primary, whose lines
        define the timeline.
    fs : float
        The captures' sample rate, in Hz.
    ntsc : bool
        True for NTSC, False for PAL.
    stack_weight : str
        "adaptive" (every input weighted at every sample by its carrier
        amplitude, with the alignment guard) or "fixed" (one 1/sigma^2
        weight per input for the whole run, and the plain phase lock).
    cancel_xtalk : bool
        Cancel the analog audio carriers' crosstalk into the video.
    cancel_xtal : bool
        Subtract the capture's crystal lines as it is read.
    cancel_leak : bool
        Cancel the chroma leak (NTSC only).
    rf_out : str | None
        Where to write the RF the decoder reads, as s16.

    The class is not thread-safe: one reader at a time.
    """

    def __init__(
        self,
        inputs: list[StackInput],
        fs: float,
        *,
        ntsc: bool,
        stack_weight: str = "adaptive",
        cancel_xtalk: bool = True,
        cancel_xtal: bool = True,
        cancel_leak: bool = True,
        rf_out: str | None = None,
    ) -> None:
        if not inputs:
            raise ValueError("the stack needs at least one capture")
        if stack_weight not in ("adaptive", "fixed"):
            raise ValueError(f"unknown stack weight {stack_weight!r}")
        self.inputs = list(inputs)
        self.fs = float(fs)
        self.ntsc = bool(ntsc)
        self.stack_weight = stack_weight
        self.cancel_xtalk = bool(cancel_xtalk)
        self.cancel_xtal = bool(cancel_xtal)
        self.cancel_leak = bool(cancel_leak)
        self.system = SYSTEM_NTSC if self.ntsc else SYSTEM_PAL
        self.line_us = NTSC_LINE_US if self.ntsc else PAL_LINE_US
        self.linelen = self.fs * self.line_us / 1e6
        self.lag = carrier_lag(self.fs)
        self._rf_out = _RfOut(rf_out) if rf_out is not None else None
        self._crystal: list[object | None] = [None] * len(self.inputs)
        self._xtalk_broken = False
        self._leak_broken = False
        # The readers the sibling modules get: a read past the end of the
        # capture returns fewer samples, as they document (the crystal-line
        # detector finds the capture's length by probing it).
        self._readers = [self._reader(inp) for inp in self.inputs]

        # Pass 0: one line-locating pass per input, in parallel.
        fields = self._run_pass0()
        self.timeline = build_timeline(fields, self.linelen, self.inputs[0].length)
        self.length = int(self.timeline.t[-1])

        # The filters.
        split = (SPLIT_LO_HZ, SPLIT_HI_HZ) if self.ntsc else PAL_SPLIT_HZ
        self._sinc = sinc_lut()
        self._hi = video_band_lut(self.fs, split)
        # The noise floor is a per-sample variance (white); through the video
        # band it is scaled by the filter's energy.
        gain = float(np.sum(np.abs(self._hi[0]) ** 2))
        self._gain = gain

        # The weights: 1/sigma^2 from each input's noise floor, measured
        # where pass 0 first located it.
        self.weight: list[float] = []
        for index, (inp, recs) in enumerate(zip(self.inputs, fields)):
            first = 0
            if recs:
                lines = _rec_lines(recs[0])
                if lines.size:
                    first = int(lines[0])
            if self.cancel_xtal:
                self._crystal[index] = self._detect_crystal(index, first)
            sigma2 = noise_floor(self._readers[index], first, self.fs)
            _logger.info("stack: %s noise floor %.4e (weight %.4e)", inp.path, sigma2, 1.0 / sigma2)
            self.weight.append(1.0 / sigma2)
        self.afloor = [AMP_FLOOR * (gain / w) ** 0.5 for w in self.weight]

        self._cache = _ChunkCache(self._compute_chunk, self.length)

    # -- pass 0 ----------------------------------------------------------

    def _reader(self, inp: StackInput) -> Callable[[int, int], np.ndarray]:
        """The input's samples, with a short read at the end of the capture.

        The line locator and the crystal-line detector find the capture's
        length by probing it, so the reader they get must not hand out
        samples past the end.
        """

        def read_fn(start: int, count: int) -> np.ndarray:
            data = np.asarray(inp.read_fn(int(start), int(count)), dtype=np.float64).ravel()
            limit = max(0, inp.length - int(start))
            if data.shape[0] > limit:
                data = data[:limit]
            return data

        return read_fn

    def _run_pass0(self) -> list[list]:
        """Locate every input's lines, one pass per input, in parallel."""
        with ThreadPoolExecutor(max_workers=len(self.inputs)) as pool:
            futures = [
                pool.submit(
                    locate_fields,
                    reader,
                    self.fs,
                    self.ntsc,
                    length=inp.length,
                )
                for reader, inp in zip(self._readers, self.inputs)
            ]
            return [list(future.result()) for future in futures]

    def _detect_crystal(self, index: int, first: int) -> object | None:
        """The capture's crystal lines, or None when there are none."""
        try:
            from .stack_corrections import CrystalLines
        except ImportError:
            _logger.warning("stack: no crystal-line module; the lines are left in")
            return None
        line_hz = LINE_HZ_NTSC if self.ntsc else LINE_HZ_PAL
        try:
            lines = CrystalLines.detect(
                self._readers[index],
                self.fs,
                ntsc=self.ntsc,
                line_hz=line_hz,
                length=self.inputs[index].length,
                start=first,
            )
        except TypeError as exc:
            _logger.warning("stack: the crystal-line detector does not fit: %s", exc)
            return None
        return lines if getattr(lines, "has_lines", True) else None

    # -- the stream ------------------------------------------------------

    def _compute_chunk(self, index: int, chunk: int) -> np.ndarray:
        """The chunk ``index`` of the stream: ``chunk`` samples from its start."""
        s0 = index * chunk
        n = max(0, min(chunk, self.length - s0))
        margin = LOCK_MARGIN
        plan = _plan(self.timeline, s0 - margin, n + 2 * margin, self.inputs, self._readers)
        length = n + 2 * margin
        reads = []
        for i, span in enumerate(plan.inputs):
            if span is None:
                reads.append(
                    (
                        np.zeros(length, dtype=np.float64),
                        np.zeros(length, dtype=np.complex128),
                        np.zeros(length, dtype=bool),
                    )
                )
                continue
            if self._crystal[i] is not None:
                self._clean_crystal(i, span)
            full, band, covered = _read_input(span, self._sinc, self._hi)
            reads.append((full, band, covered))
        out, _, combined = _combine(
            reads, self.weight, self.afloor, self.stack_weight, self.lag, margin
        )
        if self.cancel_xtalk or (self.cancel_leak and self.ntsc):
            self._cancel(out, combined)
        if self._rf_out is not None:
            self._rf_out.write(s0, out)
        return out

    def _clean_crystal(self, index: int, span: _InputSpan) -> None:
        """Subtract the capture's crystal lines from the samples read."""
        crystal = self._crystal[index]
        try:
            span.raw = crystal.clean(span.raw, span.start)
        except TypeError as exc:
            _logger.warning("stack: the crystal-line cleaner does not fit: %s", exc)
            self._crystal[index] = None

    def _cancel(self, out: np.ndarray, band: np.ndarray) -> None:
        """The audio crosstalk and chroma leak cancellations, on the chunk."""
        if self.cancel_xtalk and not self._xtalk_broken:
            try:
                from .stack_corrections import cancel_crosstalk

                carriers = AUDIO_CARRIERS_HZ if self.ntsc else PAL_AUDIO_CARRIERS_HZ
                keep = XTALK_KEEP_HZ if self.ntsc else PAL_SPLIT_HZ
                out[:] = cancel_crosstalk(out, band, self.fs, carriers, keep)
            except (ImportError, TypeError, ValueError) as exc:
                _logger.warning("stack: the crosstalk cancellation does not fit: %s", exc)
                self._xtalk_broken = True
        if self.cancel_leak and self.ntsc and not self._leak_broken:
            try:
                from .stack_corrections import cancel_chroma_leak

                out[:] = cancel_chroma_leak(out, band, self.fs, LEAK_BAND_HZ)
            except (ImportError, TypeError, ValueError) as exc:
                _logger.warning("stack: the chroma leak cancellation does not fit: %s", exc)
                self._leak_broken = True

    def read(self, sample: int, readlen: int) -> np.ndarray:
        """Return ``readlen`` samples of the virtual stream from ``sample``.

        The samples are int16, as the capture loaders return them; the
        samples past the end of the stream read as zero.
        """
        readlen = int(readlen)
        out = np.zeros(readlen, dtype=np.int16)
        if readlen <= 0:
            return out
        pos = 0
        while pos < readlen:
            at = int(sample) + pos
            if at < 0 or at >= self.length:
                break
            index = at // CHUNK
            chunk = self._cache.get(index)
            if chunk is None:
                break
            offset = at - index * CHUNK
            if offset >= chunk.shape[0]:
                break
            take = min(chunk.shape[0] - offset, readlen - pos)
            values = np.clip(np.rint(chunk[offset : offset + take]), -32768.0, 32767.0)
            out[pos : pos + take] = values.astype(np.int16)
            pos += take
        return out

    def close(self) -> None:
        """Stop the read-ahead and close the ``--rf-out`` file."""
        self._cache.stop()
        if self._rf_out is not None:
            self._rf_out.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001 - never raise from a destructor
            pass
