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

import bisect
import logging
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

import numpy as np
import scipy.signal
from numba import njit
from scipy.special import i0 as _bessel_i0

from .rf_sync import _round_half_away, frame_code
from .stack_kernels import PARAM_NAMES, combine_primary, combine_secondary, read_input_kernel

__all__ = [
    "StackInput",
    "StackedSource",
    "Timeline",
    "LiveTimeline",
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
#: Chunks kept beyond those, least recently used first out: the decoder's
#: field jobs (``-t N``) read several fields ahead of its inline reads, and
#: a field is up to 1.3 M samples at 75 MHz.  A chunk is 16 MB (float64).
SPARE_CHUNKS = 8
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
#: The tuning constants the compiled kernels take, in their order.
_KERNEL_PARAMS = np.array([globals()[name] for name in PARAM_NAMES], dtype=np.float64)


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
    open_reader : Callable[[], Callable[[int, int], np.ndarray]], optional
        A picklable factory that opens the capture again and returns a
        reader like ``read_fn`` (for a raw capture,
        ``functools.partial(fileio.open_raw_reader, filename)``).  With it,
        the capture's pass 0 runs in a process of its own, as the reference
        runs it on a thread of its own: the scan is Python and NumPy, and on
        a thread of this process it would hold the interpreter from the
        stream's own computation.  Without it, the scan runs on a thread.
    """

    path: str
    read_fn: Callable[[int, int], np.ndarray]
    length: int
    open_reader: Callable[[], Callable[[int, int], np.ndarray]] | None = None


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


class LiveTimeline:
    """The timeline, built while pass 0 runs.

    One pass-0 scan per input feeds its field records in (:meth:`push`), and
    the anchors are laid down as far as every input has been located.  The
    stream's reads wait on it (:meth:`slice`), so pass 0 runs alongside the
    decode of the stacked stream, and :meth:`stop` ends it where that decode
    ends.  This is the reference's ``Live``, step for step.

    The pairing: a secondary input's field is examined once that input is
    finished or has moved more than ``PAIR_LOOKAHEAD`` fields past it, and
    left unpaired when its code repeats within them (a skip back in that
    capture).  A primary field is laid down once every secondary input
    either knows its code, has been paired past it, or is finished.  Where a
    secondary skips back, the moment that last condition is met can depend
    on how far each scan has gone, as it does in the reference.

    Thread-safe: every method takes the one lock (``_cv``) that guards the
    state.
    """

    def __init__(
        self,
        ninputs: int,
        linelen: float,
        primary_length: int,
        names: Sequence[str] | None = None,
    ) -> None:
        self._n = int(ninputs)
        self._linelen = float(linelen)
        self._prim_len = float(primary_length)
        self._names = list(names) if names is not None else [f"input {i}" for i in range(ninputs)]
        self._cv = threading.Condition(threading.Lock())
        self._stop = threading.Event()
        n = self._n
        self._fields: list[list] = [[] for _ in range(n)]
        self._done = [False] * n
        self._error: str | None = None
        #: Primary field index of each key (its first occurrence).
        self._prim_map: dict = {}
        #: Per secondary, the paired field of each key (None: ambiguous).
        self._sec_map: list[dict] = [{} for _ in range(n)]
        #: Secondary fields examined for pairing so far.
        self._confirmed = [0] * n
        #: 1 + the furthest primary field each secondary was paired with.
        self._progress = [0] * n
        self._paired = [0] * n
        self._next_primary = 0
        self._last = -math.inf
        self._t: list[float] = []
        self._pos: list[list[float]] = [[] for _ in range(n)]
        self._finalized = False

    # -- the scans' side ---------------------------------------------------

    def push(self, index: int, rec: object) -> None:
        """A field record of input ``index``, in that input's order."""
        with self._cv:
            if index == 0:
                key = _rec_key(rec)
                if key is not None:
                    idx = self._prim_map.setdefault(key, len(self._fields[0]))
                    for s in range(1, self._n):
                        if key in self._sec_map[s]:
                            self._progress[s] = max(self._progress[s], idx + 1)
            self._fields[index].append(rec)
            self._advance()
            self._cv.notify_all()

    def finish(self, index: int, error: BaseException | None = None) -> None:
        """The scan of input ``index`` ended (``error``: it failed).

        A failure after :meth:`stop` is the scan being stopped, not an error.
        """
        with self._cv:
            self._done[index] = True
            if error is not None and not self._stop.is_set() and self._error is None:
                self._error = f"pass 0 of {self._names[index]}: {error}"
            else:
                _logger.info(
                    "read-time TBC pass 0: %d fields in %s",
                    len(self._fields[index]),
                    self._names[index],
                )
            self._advance()
            self._cv.notify_all()

    def stopped(self) -> bool:
        """Whether the decode is over, so the scans may stop."""
        return self._stop.is_set()

    def stop(self) -> None:
        """Stop the scans (the stacked decode is over)."""
        self._stop.set()
        with self._cv:
            self._cv.notify_all()

    # -- the stream's side -------------------------------------------------

    def wait_cover(self, end: float) -> int | None:
        """Block until the timeline reaches the ideal time ``end``, or is
        complete; return the stream's length (samples) once it is known."""
        with self._cv:
            while True:
                if self._error is not None:
                    raise RuntimeError(self._error)
                if self._finalized:
                    return int(self._t[-1])
                if self._t and self._t[-1] >= end:
                    return None
                self._cv.wait()

    def slice(self, s0: float, length: int) -> Timeline:
        """The anchors around ``[s0, s0 + length)``, copied out (waits for
        them)."""
        self.wait_cover(s0 + length)
        with self._cv:
            a = self._segment(s0)
            b = min(self._segment(s0 + length - 1) + 1, len(self._t) - 1)
            return Timeline(
                np.asarray(self._t[a : b + 1], dtype=np.float64),
                [np.asarray(p[a : b + 1], dtype=np.float64) for p in self._pos],
            )

    def first_lines(self) -> list[float | None]:
        """The absolute position of each input's first located line (waits
        for every input to locate one, or to finish without)."""
        with self._cv:
            while True:
                if self._error is not None:
                    raise RuntimeError(self._error)
                if all(self._done[i] or self._fields[i] for i in range(self._n)):
                    out: list[float | None] = []
                    for recs in self._fields:
                        lines = _rec_lines(recs[0]) if recs else np.zeros(0)
                        out.append(float(lines[0]) if lines.size else None)
                    return out
                self._cv.wait()

    def wait_done(self) -> Timeline:
        """Block until every scan has ended; the whole timeline.

        Raises ValueError when a scan failed or the primary has no usable
        line.
        """
        with self._cv:
            while not all(self._done):
                self._cv.wait()
            if self._error is not None:
                raise ValueError(self._error)
            return Timeline(
                np.asarray(self._t, dtype=np.float64),
                [np.asarray(p, dtype=np.float64) for p in self._pos],
            )

    # -- the pairing (caller holds the lock) --------------------------------

    def _segment(self, s: float) -> int:
        if len(self._t) < 2:
            return 0
        k = bisect.bisect_right(self._t, s) - 1
        return min(max(k, 0), len(self._t) - 2)

    def _advance(self) -> None:
        """Lay down every anchor all inputs are located for."""
        n = self._n
        linelen = self._linelen
        for s in range(1, n):
            fields = self._fields[s]
            while self._confirmed[s] < len(fields) and (
                self._done[s] or len(fields) - self._confirmed[s] > PAIR_LOOKAHEAD
            ):
                k = self._confirmed[s]
                self._confirmed[s] += 1
                key = _rec_key(fields[k])
                if key is None:
                    continue
                end = min(k + 1 + PAIR_LOOKAHEAD, len(fields))
                repeated = any(_rec_key(other) == key for other in fields[k + 1 : end])
                smap = self._sec_map[s]
                if key in smap:
                    smap[key] = None
                else:
                    smap[key] = None if repeated else k
                q = self._prim_map.get(key)
                if q is not None:
                    self._progress[s] = max(self._progress[s], q + 1)

        primary = self._fields[0]
        while self._next_primary < len(primary):
            pf = self._next_primary
            rec = primary[pf]
            key = _rec_key(rec)
            # Each secondary has this frame paired, or is past it (it has
            # been paired with a later primary field), or is finished.
            ready = all(
                self._done[s]
                or key is None
                or key in self._sec_map[s]
                or self._progress[s] > pf + 1
                for s in range(1, n)
            )
            if not ready:
                break
            matched: list[int | None] = [None] * n
            for s in range(1, n):
                if key is not None:
                    matched[s] = self._sec_map[s].get(key)
                if matched[s] is not None:
                    self._paired[s] += 1
            secondary_lines = [
                _rec_lines(self._fields[s][matched[s]]) if matched[s] is not None else None
                for s in range(n)
            ]
            for line, a in enumerate(_rec_lines(rec)):
                a = float(a)
                # Fields overlap by a few lines; keep each line once, in order.
                if a <= self._last + 0.25 * linelen:
                    continue
                if not self._t:
                    # The timeline starts at the primary's own first line;
                    # before it, the primary alone at its own rate (the
                    # decoder needs that lead-in to find the first field).
                    if a >= 1.0:
                        self._t.append(0.0)
                        self._pos[0].append(0.0)
                        for p in self._pos[1:]:
                            p.append(float("nan"))
                    tk = a
                else:
                    # Half-line resolution, rounded half away from zero as
                    # the reference rounds.
                    lines = max(0.5, _round_half_away(2.0 * (a - self._last) / linelen) / 2.0)
                    tk = self._t[-1] + lines * linelen
                self._t.append(tk)
                self._pos[0].append(a)
                for s in range(1, n):
                    lines_s = secondary_lines[s]
                    p = float("nan")
                    if lines_s is not None and line < lines_s.shape[0]:
                        p = float(lines_s[line])
                    self._pos[s].append(p)
                self._last = a
            self._next_primary += 1

        if not self._finalized and self._done[0] and self._next_primary == len(primary):
            self._finalized = True
            if len(self._t) < 2:
                if self._error is None:
                    self._error = "pass 0 found no usable lines in the primary input"
                return
            # After the last line, the primary alone again (the tail).
            tail = self._prim_len - self._pos[0][-1]
            if tail >= 1.0:
                self._t.append(self._t[-1] + tail)
                self._pos[0].append(self._pos[0][-1] + tail)
                for p in self._pos[1:]:
                    p.append(float("nan"))
            for s in range(1, n):
                _logger.info(
                    "stack: %s paired %d of the primary's %d fields",
                    self._names[s],
                    self._paired[s],
                    len(primary),
                )


def build_timeline(
    fields: Sequence[Sequence[object]], linelen: float, primary_length: int
) -> Timeline:
    """The virtual timeline from every input's complete pass-0 field records.

    The same pairing as the live one (:class:`LiveTimeline`), fed the whole
    of each input's records before they are finished.

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
    live = LiveTimeline(len(fields), linelen, primary_length)
    for index, recs in enumerate(fields):
        for rec in recs:
            live.push(index, rec)
    for index in range(len(fields)):
        live.finish(index)
    return live.wait_done()


# --------------------------------------------------------------------------
# Pass 0
# --------------------------------------------------------------------------


def locate_fields(
    read_fn: Callable[[int, int], np.ndarray],
    fs: float,
    ntsc: bool,
    stop: object = None,
    length: int | None = None,
) -> Iterable:
    """Locate the lines of one input, from its RF, field by field.

    This is the seam onto :func:`lddecode.rf_sync.locate` (imported lazily,
    so this module stands alone); the pass-0 records it yields are the
    field records :class:`LiveTimeline` takes, as they are found.

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
    Iterable
        The input's field records, in order, as the scan finds them.
    """
    from .rf_sync import locate, system_for

    return locate(read_fn, fs, system_for(ntsc), stop=stop, length=length)


def _scan_process(
    open_reader: Callable[[], Callable[[int, int], np.ndarray]],
    length: int,
    fs: float,
    ntsc: bool,
    stop: object,
    records: object,
) -> None:
    """Pass 0 of one capture, in a process of its own.

    Opens the capture through ``open_reader``, locates its fields and puts
    ``("rec", record)`` on ``records`` as they are found, then
    ``("done", None)``, or ``("error", message)``.  ``stop`` (an event) ends
    the scan at its next chunk.  The reader is cut at ``length``, as the
    stacked source's own readers are.
    """
    try:
        reader = open_reader()

        def read_fn(start: int, count: int) -> np.ndarray:
            data = np.asarray(reader(int(start), int(count)), dtype=np.float64).ravel()
            limit = max(0, int(length) - int(start))
            return data[:limit] if data.shape[0] > limit else data

        from .rf_sync import locate, system_for

        for rec in locate(read_fn, fs, system_for(ntsc), stop=stop.is_set, length=length):
            if stop.is_set():
                break
            records.put(("rec", rec))
        records.put(("done", None))
    except Exception as exc:  # noqa: BLE001 - sent to the parent
        records.put(("error", f"{type(exc).__name__}: {exc}"))


# --------------------------------------------------------------------------
# The plan and the reads
# --------------------------------------------------------------------------


@dataclass
class _InputSpan:
    """One input's samples, and where they are read for a span of the stream.

    The positions come either as an array (``positions``, one absolute
    position per sample, NaN where the input does not cover it) or as the
    per-segment law of a plan: ``seg`` (each sample's segment), ``seg_t0``
    (each segment's first ideal time), ``a0`` (the position there, NaN where
    the input does not cover the segment) and ``slope`` (input samples per
    virtual sample), from the ideal time ``s0``.  A sample's position is then
    ``a0[k] + ((s0 + j) - seg_t0[k]) * slope[k]``, which the kernels compute
    themselves, on the host or on the device, as the reference does.
    """

    raw: np.ndarray
    start: int
    positions: np.ndarray | None = None
    a0: np.ndarray | None = None
    slope: np.ndarray | None = None
    seg: np.ndarray | None = None
    seg_t0: np.ndarray | None = None
    s0: float = 0.0

    def law(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
        """``(seg, seg_t0, a0, slope, s0)``; from ``positions`` when the span
        was given them (one segment per sample, of zero slope)."""
        if self.a0 is not None:
            return self.seg, self.seg_t0, self.a0, self.slope, float(self.s0)
        positions = np.asarray(self.positions, dtype=np.float64)
        n = positions.shape[0]
        return (
            np.arange(n, dtype=np.int64),
            np.arange(n, dtype=np.float64),
            positions,
            np.zeros(n, dtype=np.float64),
            0.0,
        )

    def position_array(self) -> np.ndarray:
        """Every sample's absolute position (a new array)."""
        if self.positions is not None:
            return np.array(self.positions, dtype=np.float64)
        seg, seg_t0, a0, slope, s0 = self.law()
        times = s0 + np.arange(seg.shape[0], dtype=np.float64)
        return a0[seg] + (times - seg_t0[seg]) * slope[seg]


@dataclass
class _Plan:
    """What one span of virtual samples needs from the inputs."""

    s0: float
    length: int
    seg: np.ndarray
    seg_t0: np.ndarray
    inputs: list[_InputSpan | None]


#: The span a capture's DC offset is measured on, and where: a quarter into
#: the capture, at most twice the span from its end (where the cleaned source
#: detects the clock lines).
DC_SPAN = 1 << 21
#: The grid the offset is rounded to (see capture_dc).
DC_GRID = float(1 << 32)


def capture_dc(read_fn: Callable[[int, int], np.ndarray], length: int) -> float:
    """The capture's DC offset: its mean over ``DC_SPAN`` samples a quarter
    into it (all of it when it is shorter).

    The corrections assume a centred RF.  They read zero outside the chunk
    and outside the capture, so an offset makes a step there, which leaks
    into their fits: an unsigned capture (a .r30's 10-bit values sit on 512)
    was cleaned otherwise than the same capture signed.

    The offset is on a grid of 2^-32: an integer sample less it, and the
    difference plus it, are exact in double precision, so the stream of a
    source with nothing to cancel is the capture to the last bit.  Over the
    whole span (a power of two) the mean of integer samples is exact, so a
    capture at a power-of-two scale with an integer offset (a .r30 against
    the same samples in a .s16) gets the offset scaled and shifted exactly,
    and is cleaned to the same stream at that scale.
    """
    length = int(length)
    if length <= 0:
        return 0.0
    count = min(DC_SPAN, length)
    start = min(length // 4, max(length - 2 * DC_SPAN, 0), length - count)
    data = np.asarray(read_fn(int(start), int(count)), dtype=np.float64).ravel()[:count]
    if not data.size:
        return 0.0
    return float(np.round(data.mean() * DC_GRID) / DC_GRID)


class _CentredReader:
    """A capture's reader with its DC offset taken out of the samples inside
    the capture; outside it, the samples read as zero, as they did, so they
    now sit at the signal's level instead of a step away from it.  Picklable
    with a picklable reader."""

    def __init__(self, read_fn: Callable[[int, int], np.ndarray], dc: float, length: int) -> None:
        self.read_fn = read_fn
        self.dc = float(dc)
        self.length = int(length)

    def __call__(self, start: int, count: int) -> np.ndarray:
        data = np.array(self.read_fn(int(start), int(count)), dtype=np.float64).ravel()
        if self.dc:
            i0 = min(max(-int(start), 0), data.shape[0])
            i1 = min(max(self.length - int(start), 0), data.shape[0])
            if i1 > i0:
                data[i0:i1] -= self.dc
        return data


class _CentredOpener:
    """``open_reader`` for a centred capture, for another process."""

    def __init__(self, open_reader: Callable[[], Callable[[int, int], np.ndarray]],
                 dc: float, length: int) -> None:
        self.open_reader = open_reader
        self.dc = float(dc)
        self.length = int(length)

    def __call__(self) -> _CentredReader:
        return _CentredReader(self.open_reader(), self.dc, self.length)


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
    # Each segment's first and last sample: the positions are linear over a
    # segment, so their extremes are at these.
    ks = np.arange(nseg)
    j_first = np.searchsorted(seg, ks, side="left")
    j_last = np.searchsorted(seg, ks, side="right") - 1
    used = j_last >= j_first
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
        # A segment the input does not cover at both ends is not covered
        # (the device tests a0 alone).
        a0 = np.where(np.isfinite(slope), a0, np.nan)
        live = used & np.isfinite(a0)
        if not live.any():
            spans.append(None)
            continue
        ends = np.concatenate(
            (
                a0[live] + ((s0 + j_first[live]) - span_times[live]) * slope[live],
                a0[live] + ((s0 + j_last[live]) - span_times[live]) * slope[live],
            )
        )
        pmin = float(np.min(ends))
        pmax = float(np.max(ends))
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
        spans.append(
            _InputSpan(
                raw=raw, start=start, a0=a0, slope=slope, seg=seg, seg_t0=span_times, s0=s0
            )
        )
    return _Plan(s0=s0, length=length, seg=seg, seg_t0=span_times, inputs=spans)


def _read_input(
    span: _InputSpan, sinc: np.ndarray, hi: tuple[np.ndarray, np.ndarray]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Read one input at its own positions, on every core.

    ``hi`` is the video-band table's real and imaginary parts, each
    C-contiguous.  Returns the full signal, the analytic video band and the
    coverage (which samples the input covers at all), all new arrays.
    """
    seg, seg_t0, a0, slope, s0 = span.law()
    length = seg.shape[0]
    full = np.empty(length, dtype=np.float64)
    band = np.empty(length, dtype=np.complex128)
    covered = np.empty(length, dtype=np.bool_)
    read_input_kernel(
        np.ascontiguousarray(span.raw, dtype=np.float64),
        int(span.start),
        np.ascontiguousarray(seg, dtype=np.int64),
        np.ascontiguousarray(seg_t0, dtype=np.float64),
        np.ascontiguousarray(a0, dtype=np.float64),
        np.ascontiguousarray(slope, dtype=np.float64),
        float(s0),
        sinc,
        hi[0],
        hi[1],
        full,
        band,
        covered,
    )
    return full, band, covered


def _read_input_reference(
    span: _InputSpan, sinc: np.ndarray, hi: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Read one input at its own positions: the vectorised reference the
    kernel (:func:`_read_input`) is checked against.

    Returns the full signal, the analytic video band and the coverage (which
    samples the input covers at all).
    """
    positions = span.position_array()
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
    """Combine the inputs' reads into the virtual stream, on every core.

    The same parameters and results as :func:`_combine_reference`, the
    vectorised reference it is checked against.  The inputs are added in
    order, each over every sample at once.
    """
    full0, band0, cov0 = reads[0]
    length = full0.shape[0]
    nout = length - 2 * margin
    half = LOCK_WIN // 2
    chalf = CARRIER_WIN // 2
    fixed = mode == "fixed"
    acc = np.zeros(nout, dtype=np.float64)
    wsum = np.zeros(nout, dtype=np.float64)
    vacc = np.zeros(nout, dtype=np.complex128)
    q0 = np.empty(nout, dtype=np.float64)
    h0 = np.empty(nout, dtype=np.float64)
    combine_primary(
        full0, band0, cov0, lag, margin, nout, half, chalf,
        float(weight[0]), float(afloor[0]), fixed, _KERNEL_PARAMS, acc, wsum, vacc, q0, h0,
    )
    for i in range(1, len(reads)):
        full, band, cov = reads[i]
        if not cov[margin : margin + nout].any():
            continue
        combine_secondary(
            full, band, cov, band0, cov0, q0, h0, lag, margin, nout, half, chalf,
            float(weight[i]), float(afloor[i]), fixed, _KERNEL_PARAMS, acc, wsum, vacc,
        )

    safe = np.where(wsum > 0.0, wsum, 1.0)
    out = np.where(wsum > 0.0, acc / safe, 0.0)
    combined = np.where(wsum > 0.0, vacc / safe, 0.0)
    return out, wsum, combined


def _combine_reference(
    reads: Sequence[tuple[np.ndarray, np.ndarray, np.ndarray]],
    weight: Sequence[float],
    afloor: Sequence[float],
    mode: str,
    lag: int,
    margin: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Combine the inputs' reads into the virtual stream: the vectorised
    reference the kernels (:func:`_combine`) are checked against.

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

    ``compute(index, chunk)`` returns the chunk, or None past the end of
    the stream: the stream's length is only known once pass 0 has located
    the primary to its end, so the end is found, not given.  ``workers``
    producers compute different chunks at once (``compute`` must then be
    safe to call from several threads).
    """

    def __init__(
        self,
        compute: Callable[[int, int], np.ndarray | None],
        chunk: int = CHUNK,
        ahead: int = AHEAD,
        behind: int = BEHIND,
        workers: int = 1,
    ) -> None:
        self._compute = compute
        #: The first chunk past the end of the stream, once it is known.
        self._end: int | None = None
        self._chunk = int(chunk)
        self._ahead = int(ahead)
        self._behind = int(behind)
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._chunks: OrderedDict[int, np.ndarray] = OrderedDict()
        self._want = 0
        self._error: str | None = None
        self._stop = False
        #: The chunks a producer is computing.
        self._busy: set[int] = set()
        self._threads = [
            threading.Thread(target=self._produce, name=f"stack-ahead-{i}", daemon=True)
            for i in range(max(int(workers), 1))
        ]
        for thread in self._threads:
            thread.start()

    def _past_end(self, index: int) -> bool:
        return self._end is not None and index >= self._end

    def stop(self) -> None:
        """Stop the producer."""
        with self._cv:
            self._stop = True
            self._cv.notify_all()

    @property
    def capacity(self) -> int:
        """How many chunks the buffer keeps at most."""
        return self._ahead + self._behind + SPARE_CHUNKS

    def _evict(self) -> None:
        """Drop the least recently used chunks past the capacity.

        The chunks the producer is filling ahead of the read position are
        kept.  Eviction is by use, not by position: with ``-t N`` the
        decoder's field jobs read several fields ahead of its own inline
        reads, and a buffer that only kept what lies behind the last read
        would compute the same chunks over and over.  Caller holds the lock.
        """
        window = range(self._want, self._want + self._ahead)
        for k in list(self._chunks):
            if len(self._chunks) <= self.capacity:
                break
            if k not in window:
                del self._chunks[k]

    def get(self, index: int) -> np.ndarray | None:
        """The chunk ``index``, waiting for the producer; None past the end."""
        with self._cv:
            if index != self._want:
                self._want = index
                self._cv.notify_all()
            while True:
                if self._error is not None:
                    raise RuntimeError(self._error)
                data = self._chunks.get(index)
                if data is not None:
                    self._chunks.move_to_end(index)
                    return data
                if self._past_end(index) or self._stop:
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
                    for c in range(self._want, self._want + self._ahead):
                        if (not self._past_end(c) and c not in self._chunks
                                and c not in self._busy):
                            target = c
                            break
                    if target is not None:
                        self._busy.add(target)
                        break
                    self._cv.wait()
            try:
                data = self._compute(target, self._chunk)
            except Exception as exc:  # noqa: BLE001 - reported to the reader
                with self._cv:
                    self._busy.discard(target)
                    self._error = f"{exc}"
                    self._cv.notify_all()
                return
            with self._cv:
                self._busy.discard(target)
                if data is None:
                    self._end = target if self._end is None else min(self._end, target)
                else:
                    self._chunks[target] = data
                    self._evict()
                self._cv.notify_all()


def rf_out_scale(dtype: str) -> tuple[float, float]:
    """How the stream's values map to the ``--rf_out`` file's s16 values.

    Returns ``(scale, shift)``, s16 = value * scale + shift: the inverse of
    how the primary capture's sample type was widened, so an unsigned
    capture (centred on 32768, or on 128 for 8-bit) lands centred on zero
    instead of clipped.  The decoder ignores the DC offset either way.
    ``dtype`` is the capture's sample type, as ``fileio.RAW_LAYOUTS`` names
    it.
    """
    if dtype == "uint16":
        return 1.0, -32768.0
    if dtype == "uint8":
        return 256.0, -32768.0
    return 1.0, 0.0


class _RfOut:
    """The ``--rf_out`` file: the RF the decoder reads, as s16.

    The samples are written at their place in the stream, so a chunk that is
    computed late leaves the span it skipped at zero.  Each value is
    ``value * scale + shift`` (see :func:`rf_out_scale`), from the stream's
    single-precision chunk, rounded half away from zero and limited to the
    s16 range, as the reference writes it.

    Thread-safe: the producer writes while the decoder's thread may close;
    ``_lock`` guards the file.
    """

    def __init__(self, path: str, scale: float = 1.0, shift: float = 0.0) -> None:
        self.path = path
        self._scale = np.float32(scale)
        self._shift = np.float32(shift)
        self._lock = threading.Lock()
        # Created at once, so a path that cannot be written is reported
        # before the decode starts.
        self._file = open(path, "wb")

    def write(self, offset: int, data: np.ndarray) -> None:
        """Write the samples of the stream from ``offset`` (samples)."""
        values = np.asarray(data, dtype=np.float32) * self._scale + self._shift
        rounded = np.sign(values) * np.floor(np.abs(values) + np.float32(0.5))
        out = np.clip(rounded, -32768.0, 32767.0).astype("<i2")
        with self._lock:
            if self._file is None:
                return
            self._file.seek(int(offset) * 2)
            self._file.write(out.tobytes())

    def close(self) -> None:
        """Close the file."""
        with self._lock:
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
    decoder_filter : tuple | None
        The decoder's view of the RF the crosstalk cancellation measures and
        corrects through: the frequencies and the complex response of its
        video filter times its readout compensation (main builds it, from
        rev 8's own RFDecode, at the readout level measured on the
        capture; see measure_readout_tilt).  None: a flat view.
    cancel_disc_lines : bool
        Take out the lines the disc itself carries (a clock that leaked into
        the signal at mastering), found on the primary capture and only where
        shown not to be the picture (stack_corrections.find_disc_lines).  Off
        by default: no disc measured so far carries one.
    rf_out : str | None
        Where to write the RF the decoder reads, as s16.
    device : str
        "cpu" (every core) or "opencl": the read and the combination on an
        OpenCL device, as the reference's ``--device opencl``.
    device_precision : str
        The device's precision, "single" (the default) or "double".
    opencl_factory : callable, optional
        Builds the device backend (default
        :class:`lddecode.stack_opencl.StackOpenCL`); the seam the tests
        substitute.
    rf_out_dtype : str
        The primary capture's sample type (as ``fileio.RAW_LAYOUTS`` names
        it): an unsigned capture's offset is taken out of the ``--rf_out``
        file.

    One reader at a time: the decoder serialises its raw reads under its
    reader lock.  Pass 0 and the read-ahead run on threads of their own.
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
        cancel_disc_lines: bool = False,
        decoder_filter: tuple | None = None,
        rf_out: str | None = None,
        rf_out_dtype: str = "int16",
        device: str = "cpu",
        device_precision: str = "single",
        opencl_factory: Callable[..., object] | None = None,
    ) -> None:
        if device not in ("cpu", "opencl"):
            raise ValueError(f"unknown device {device!r}")
        if not inputs:
            raise ValueError("the stack needs at least one capture")
        if stack_weight not in ("adaptive", "fixed"):
            raise ValueError(f"unknown stack weight {stack_weight!r}")
        if device_precision not in ("double", "single"):
            raise ValueError(f"unknown device precision {device_precision!r}")
        self.device = device
        self.device_precision = device_precision
        self._opencl_factory = opencl_factory
        self._gpu = None
        self.inputs = list(inputs)
        self.fs = float(fs)
        self.ntsc = bool(ntsc)
        self.stack_weight = stack_weight
        self.cancel_xtalk = bool(cancel_xtalk)
        self.cancel_xtal = bool(cancel_xtal)
        self.cancel_leak = bool(cancel_leak)
        self.cancel_disc_lines = bool(cancel_disc_lines)
        self._decoder_filter = decoder_filter
        #: The carriers whose crosstalk is corrected (steady_carriers, in
        #: _setup); None: every one a chunk carries.
        self._xtalk_kept: list[bool] | None = None
        #: The disc's own lines, in Hz on the stream's timeline (see
        #: cancel_disc_lines); found in _setup.
        self._disc_lines: list[float] = []
        self.system = SYSTEM_NTSC if self.ntsc else SYSTEM_PAL
        self.line_us = NTSC_LINE_US if self.ntsc else PAL_LINE_US
        self.linelen = self.fs * self.line_us / 1e6
        self.lag = carrier_lag(self.fs)
        self._rf_out = _RfOut(rf_out, *rf_out_scale(rf_out_dtype)) if rf_out is not None else None
        self._crystal: list[object | None] = [None] * len(self.inputs)
        self._xtalk_broken = False
        self._leak_broken = False
        # The readers the sibling modules get: a read past the end of the
        # capture returns fewer samples, as they document (the crystal-line
        # detector finds the capture's length by probing it).
        self._readers = [self._reader(inp) for inp in self.inputs]
        # Each capture centred before it is combined and cleaned (see
        # capture_dc); the stream gets the primary's offset back, as it was.
        self._dc = [capture_dc(reader, inp.length)
                    for reader, inp in zip(self._readers, self.inputs)]
        self._raw_readers = self._readers
        self._readers = [_CentredReader(reader, dc, inp.length)
                         for reader, dc, inp in zip(self._readers, self._dc, self.inputs)]

        # Pass 0: one line-locating scan per input, each on its own thread,
        # feeding the timeline as it goes.  It runs alongside the decode and
        # is stopped by close(), where the decode stops.
        self._live = LiveTimeline(
            len(self.inputs),
            self.linelen,
            self.inputs[0].length,
            names=[inp.path for inp in self.inputs],
        )
        self._cache: _ChunkCache | None = None
        #: The pass 0 processes' stop events (see _scan_in_process).
        self._scan_stops: list = []
        self._pass0 = [
            threading.Thread(target=self._scan, args=(index,), name=f"stack-pass0-{index}", daemon=True)
            for index in range(len(self.inputs))
        ]
        for thread in self._pass0:
            thread.start()
        try:
            self._setup()
        except BaseException:
            self.close()
            raise

    def _setup(self) -> None:
        """The filters, the weights and the crystal lines, once every input
        has located its first line."""
        try:
            firsts = self._live.first_lines()
        except RuntimeError as exc:
            raise ValueError(str(exc)) from exc
        if firsts[0] is None:
            raise ValueError("pass 0 found no usable lines in the primary input")

        # The filters.
        split = (SPLIT_LO_HZ, SPLIT_HI_HZ) if self.ntsc else PAL_SPLIT_HZ
        self._sinc = sinc_lut()
        self._hi = video_band_lut(self.fs, split)
        self._hi_parts = (
            np.ascontiguousarray(self._hi.real),
            np.ascontiguousarray(self._hi.imag),
        )
        # The noise floor is a per-sample variance (white); through the video
        # band it is scaled by the filter's energy.
        gain = float(np.sum(np.abs(self._hi[0]) ** 2))
        self._gain = gain

        # The weights: 1/sigma^2 from each input's noise floor, measured
        # where pass 0 first located it.
        self.weight: list[float] = []
        for index, inp in enumerate(self.inputs):
            first = int(firsts[index]) if firsts[index] is not None else 0
            if self.cancel_xtal:
                self._crystal[index] = self._detect_crystal(index, first)
            sigma2 = noise_floor(self._readers[index], first, self.fs)
            _logger.info("stack: %s noise floor %.4e (weight %.4e)", inp.path, sigma2, 1.0 / sigma2)
            self.weight.append(1.0 / sigma2)
        self.afloor = [AMP_FLOOR * (gain / w) ** 0.5 for w in self.weight]

        if self.cancel_xtalk:
            self._xtalk_kept = _steady_carriers(
                self._readers[0], self.inputs[0].length, self.fs, self.ntsc,
                self._decoder_filter)

        if self.cancel_disc_lines:
            from .stack_corrections import find_disc_lines

            self._disc_lines = find_disc_lines(
                self._readers[0],
                self.fs,
                ntsc=self.ntsc,
                line_hz=LINE_HZ_NTSC if self.ntsc else LINE_HZ_PAL,
                length=self.inputs[0].length,
                start=int(firsts[0]),
            )

        self._gpu = None
        if self.device == "opencl":
            self._gpu = self._open_device()
        self._cache = _ChunkCache(self._compute_chunk)

    def _open_device(self) -> object:
        """The OpenCL backend, with the tables, the weights and the constants."""
        factory = self._opencl_factory
        if factory is None:
            from .stack_opencl import StackOpenCL as factory
        constants = {
            "PHASES": SINC_PHASES,
            "SINC_TAPS": SINC_TAPS,
            "HI_TAPS": HI_TAPS,
            "LOCK_WIN": LOCK_WIN,
            "CARRIER_WIN": CARRIER_WIN,
        }
        constants.update({name: globals()[name] for name in PARAM_NAMES})
        return factory(
            self._sinc,
            self._hi,
            self.weight,
            self.afloor,
            constants,
            lag=self.lag,
            adaptive=self.stack_weight == "adaptive",
            want_band=self._wants_band(),
            double=self.device_precision == "double",
        )

    @property
    def length(self) -> int:
        """The stream's length, in samples (waits for pass 0 to end)."""
        return int(self.timeline.t[-1])

    @property
    def timeline(self) -> Timeline:
        """The whole timeline (waits for pass 0 to end)."""
        return self._live.wait_done()

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

    def _scan(self, index: int) -> None:
        """Pass 0 of input ``index``: its field records into the timeline.

        In a process of its own when the input can be opened again
        (``StackInput.open_reader``), on this thread otherwise.
        """
        if self.inputs[index].open_reader is not None:
            self._scan_in_process(index)
            return
        live = self._live
        try:
            for rec in locate_fields(
                self._raw_readers[index],
                self.fs,
                self.ntsc,
                stop=live.stopped,
                length=self.inputs[index].length,
            ):
                if live.stopped():
                    break
                live.push(index, rec)
        except Exception as exc:  # noqa: BLE001 - reported to the stream's reader
            live.finish(index, exc)
        else:
            live.finish(index)

    def _scan_in_process(self, index: int) -> None:
        """Pass 0 of input ``index`` in a process of its own.

        The process opens the capture itself and sends its field records
        back; this thread hands them to the timeline.  ``close()`` stops the
        process through a shared event, at its next chunk.
        """
        import multiprocessing
        import queue as queue_module

        live = self._live
        inp = self.inputs[index]
        ctx = multiprocessing.get_context("spawn")
        records = ctx.Queue()
        stop = ctx.Event()
        self._scan_stops.append(stop)
        if live.stopped():
            stop.set()
        proc = ctx.Process(
            target=_scan_process,
            args=(inp.open_reader, inp.length, self.fs, self.ntsc, stop, records),
            name=f"stack-pass0-{index}",
            daemon=True,
        )
        proc.start()
        try:
            while True:
                try:
                    kind, value = records.get(timeout=0.5)
                except queue_module.Empty:
                    if live.stopped():
                        stop.set()
                    if not proc.is_alive():
                        raise RuntimeError(
                            f"the pass 0 process ended with exit code {proc.exitcode}"
                        ) from None
                    continue
                if kind == "rec":
                    if not live.stopped():
                        live.push(index, value)
                elif kind == "error":
                    raise RuntimeError(value)
                else:
                    break
        except Exception as exc:  # noqa: BLE001 - reported to the stream's reader
            live.finish(index, exc)
        else:
            live.finish(index)

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

    def _compute_chunk(self, index: int, chunk: int) -> np.ndarray | None:
        """The chunk ``index`` of the stream: ``chunk`` samples from its
        start, fewer at the end; None past the end.  Waits for pass 0 to
        cover it."""
        s0 = index * chunk
        margin = LOCK_MARGIN
        known = self._live.wait_cover(s0 + chunk + margin)
        n = chunk
        if known is not None:
            if s0 >= known:
                return None
            n = min(chunk, known - s0)
        timeline = self._live.slice(s0 - margin, n + 2 * margin)
        plan = _plan(timeline, s0 - margin, n + 2 * margin, self.inputs, self._readers)
        length = n + 2 * margin
        if self._gpu is not None:
            for i, span in enumerate(plan.inputs):
                if span is not None and self._crystal[i] is not None:
                    self._clean_crystal(i, span)
            out, combined = self._gpu.run(plan, margin, n)
            return self._finish_chunk(s0, out, combined)
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
            full, band, covered = _read_input(span, self._sinc, self._hi_parts)
            reads.append((full, band, covered))
        out, _, combined = _combine(
            reads, self.weight, self.afloor, self.stack_weight, self.lag, margin
        )
        return self._finish_chunk(s0, out, combined)

    def _wants_band(self) -> bool:
        """Whether a cancellation needs the combined video band."""
        return self.cancel_xtalk or (self.cancel_leak and self.ntsc)

    def _finish_chunk(self, s0: int, out: np.ndarray, combined: np.ndarray | None) -> np.ndarray:
        """The cancellations on a combined chunk, then the chunk as kept."""
        disc_lines = getattr(self, "_disc_lines", None)
        if disc_lines:
            from .stack_corrections import subtract_disc_lines

            # The lines are the disc's: in every copy, so in the combination.
            out = subtract_disc_lines(out, s0, disc_lines, self.fs)
        if self._wants_band():
            self._cancel(out, combined)
        dc = getattr(self, "_dc", None)
        if dc and dc[0]:
            out = out + dc[0]
        # Kept in double precision (the reference keeps f32): rounded to
        # single precision, a sample carries the capture's DC offset in its
        # error, so the same disc decoded otherwise from an unsigned capture
        # than from a signed one (a .r30's values sit on 512), by a level on
        # 2 % of a .tbc's samples.
        chunk_out = np.asarray(out, dtype=np.float64)
        if self._rf_out is not None:
            self._rf_out.write(s0, chunk_out)
        return chunk_out

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
                out[:] = cancel_crosstalk(out, self.fs, carriers, keep,
                                          getattr(self, "_decoder_filter", None),
                                          _blank_hz(self.ntsc),
                                          getattr(self, "_xtalk_kept", None))
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
        """Return up to ``readlen`` samples of the virtual stream from ``sample``.

        The samples are float64, in the captures' own units, neither rounded
        nor clipped (the reference's virtual source hands the decoder f32):
        a stack carries finer steps than any one capture, and an unsigned
        16-bit capture reads up to 65535, past the int16 range.

        Fewer samples come back at the end of the stream, none past it: the
        decoder takes a short read as the end of its input, as it does from
        a capture loader.  Returns a new array.
        """
        readlen = int(readlen)
        out = np.zeros(max(readlen, 0), dtype=np.float64)
        pos = 0
        while pos < readlen:
            at = int(sample) + pos
            if at < 0:
                break
            index = at // CHUNK
            chunk = self._cache.get(index)
            if chunk is None:
                break
            offset = at - index * CHUNK
            if offset >= chunk.shape[0]:
                break
            take = min(chunk.shape[0] - offset, readlen - pos)
            out[pos : pos + take] = chunk[offset : offset + take]
            pos += take
        return out[:pos]

    def close(self) -> None:
        """Stop pass 0 and the read-ahead, and close the ``--rf_out`` file.

        Pass 0 stops at its next chunk: it is not joined (its threads are
        daemons, and a scan mid-chunk would hold the close up).
        """
        live = getattr(self, "_live", None)
        if live is not None:
            live.stop()
        for stop in list(getattr(self, "_scan_stops", ())):
            stop.set()
        cache = getattr(self, "_cache", None)
        if cache is not None:
            cache.stop()
        rf_out = getattr(self, "_rf_out", None)
        if rf_out is not None:
            rf_out.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001 - never raise from a destructor
            pass


#: Where the cleaned source detects the clock lines: a quarter into the
#: capture (where there is picture), at most this far from its end.
CLEAN_PROBE_TAIL = 1 << 22

#: The cleaned source's producer processes, and the chunks it keeps ready
#: ahead of the read: one producer cleans about 7 M samples/s, a resample
#: decode on every core reads up to 14 M (ve-monitor, 10.5 frames/s), and
#: producers on threads of the decoder's own process would hold its
#: interpreter from the decode (as pass 0's scans would; see _scan).
CLEAN_WORKERS = 4
CLEAN_AHEAD = 6

#: How long closing the cleaned source waits for the chunks its workers are
#: computing (one is well under a second on a healthy pool) before it
#: terminates the workers that are still busy.
CLEAN_DRAIN_TIMEOUT_S = 10


def _crystal_params(lines: object) -> dict | None:
    """What rebuilds a capture's clock lines in another process (its own
    reader aside): CrystalLines keeps a reader and a cache of its own, and
    neither crosses a process boundary nor is shared between threads."""
    if lines is None:
        return None
    return {name: getattr(lines, name)
            for name in ("fs", "f0", "ks", "reference", "others", "length")}


def _clean_chunk(
    read_fn: Callable[[int, int], np.ndarray],
    crystal: object | None,
    h0: np.ndarray,
    s0: int,
    n: int,
    fs: float,
    ntsc: bool,
    cancel_xtalk: bool,
    cancel_leak: bool,
    dc: float = 0.0,
    decoder_filter: tuple | None = None,
    xtalk_kept: list | None = None,
) -> np.ndarray:
    """The cleaned source's chunk of ``n`` samples from ``s0``: the capture
    read as it is, its clock lines subtracted, then the audio crosstalk and
    the chroma leak cancelled on the chunk, as the stacked source cancels
    them; float64, as the stacked source keeps its chunks.  ``read_fn``
    reads the capture centred (_CentredReader): ``dc``, its offset, is put
    back on the chunk."""
    from .stack_corrections import cancel_chroma_leak, cancel_crosstalk

    pad = HI_TAPS
    raw = _read_span(read_fn, s0 - pad, n + 2 * pad)
    if crystal is not None:
        raw = crystal.clean(raw, s0 - pad)
    out = np.array(raw[pad : pad + n], dtype=np.float64)
    leak = cancel_leak and ntsc
    if cancel_xtalk:
        carriers = AUDIO_CARRIERS_HZ if ntsc else PAL_AUDIO_CARRIERS_HZ
        keep = XTALK_KEEP_HZ if ntsc else PAL_SPLIT_HZ
        out = cancel_crosstalk(out, fs, carriers, keep, decoder_filter, _blank_hz(ntsc),
                               xtalk_kept)
    if leak:
        # The stacked source's band at phase zero (_fir with the table's
        # first row): band[j] = sum_d h[d] raw[pad + j + d - (HI_TAPS/2 - 1)].
        # The filter is the same at every sample here, so it is one
        # convolution, by FFT.
        first = pad - (HI_TAPS // 2 - 1)
        band = scipy.signal.oaconvolve(raw, h0[::-1], mode="valid")[first : first + n]
        out = cancel_chroma_leak(out, band, fs, LEAK_BAND_HZ)
    if dc:
        out = out + dc
    return out


def _steady_carriers(read_fn, length, fs, ntsc, decoder_filter) -> list[bool]:
    """The carriers whose crosstalk is corrected on this capture
    (stack_corrections.steady_carriers), with the source's own carriers,
    keep band and blanking level."""
    from .stack_corrections import steady_carriers

    carriers = AUDIO_CARRIERS_HZ if ntsc else PAL_AUDIO_CARRIERS_HZ
    keep = XTALK_KEEP_HZ if ntsc else PAL_SPLIT_HZ
    return steady_carriers(read_fn, length, fs, carriers, keep, decoder_filter, _blank_hz(ntsc))


def _blank_hz(ntsc: bool) -> float:
    """The blanking carrier (Hz): the zero of the level the crosstalk's
    coupling follows."""
    from .params import SysParams_NTSC, SysParams_PAL

    return float((SysParams_NTSC if ntsc else SysParams_PAL)["ire0"])


#: Where the readout's tilt is measured: this many stretches spread over
#: the capture, each this long (seconds), the lines pass 0 locates in them,
#: their lines 20 to 250 (decoder metrics' SIDEBAND_LINES), and the window
#: trimmed this far inside the colour burst (us; SIDEBAND_TRIM_US).
READOUT_STRETCHES = 4
READOUT_STRETCH_S = 0.1
READOUT_LINES = (20, 250)
READOUT_TRIM_US = 0.2
#: PAL's pilot burst on the sync tip, in us from the sync edge (decoder
#: metrics' PILOT_WINDOW_US).
READOUT_PILOT_US = (0.8, 4.3)


def measure_readout_tilt(
    read_fn: Callable[[int, int], np.ndarray],
    fs: float,
    *,
    ntsc: bool,
    length: int,
) -> tuple[float, float, float, str] | None:
    """The readout's tilt, measured on the capture as the decoder measures
    it (decoder._readout_measurement): the channel passes f_lo `ratio`
    times as strongly as f_hi, from a tone's two first FM sidebands on the
    lines pass 0 locates (dsp.tone_sideband_powers) - PAL's pilot burst on
    the sync tip first, else the colour burst on blanking - the median of
    the fields' readings.  Returns (ratio, f_lo, f_hi, description), or None
    where no field gives a reading."""
    from .dsp import tone_sideband_powers
    from .params import SysParams_NTSC, SysParams_PAL
    from .rf_sync import locate, system_for

    sp = SysParams_NTSC if ntsc else SysParams_PAL
    blank = float(sp["ire0"])
    tones = []
    if not ntsc:
        tip = blank + float(sp["hz_ire"]) * float(sp["vsync_ire"])
        tones.append(("pilot", READOUT_PILOT_US, tip, float(sp["pilot_mhz"]) * 1e6))
    b0, b1 = sp["colorBurstUS"]
    tones.append(("burst", (b0 + READOUT_TRIM_US, b1 - READOUT_TRIM_US), blank,
                  float(sp["fsc_mhz"]) * 1e6))
    span = int(READOUT_STRETCH_S * fs)
    room = max(0, int(length) - span)
    fields = []
    for k in range(READOUT_STRETCHES):
        at = int(room * (0.05 + 0.9 * k / max(1, READOUT_STRETCHES - 1)))

        def read_at(s, count, at=at):
            return read_fn(at + int(s), int(count))

        for rec in locate(read_at, fs, system_for(ntsc), length=span):
            fields.append(np.asarray(rec.lines, dtype=np.float64) + at)
    for name, (w0, w1), carrier, tone in tones:
        ratios = []
        n = int((w1 - w0) * 1e-6 * fs)
        for lines in fields:
            segs = []
            for pos in lines[READOUT_LINES[0]:READOUT_LINES[1]]:
                seg = np.asarray(read_fn(int(pos + w0 * 1e-6 * fs), n), dtype=np.float64)
                if seg.shape[0] == n:
                    segs.append(seg)
            if not segs:
                continue
            powers = tone_sideband_powers(np.stack(segs), fs, carrier, tone)
            if powers is None:
                continue
            lower, upper, lower_noise, upper_noise = powers
            if lower < lower_noise or upper < upper_noise or upper <= 0:
                continue
            ratios.append(float(np.sqrt(lower / upper)))
        if ratios:
            ratio = float(np.median(ratios))
            return ratio, carrier - tone, carrier + tone, f"{name} sidebands {ratio:.3f}"
    return None


#: A producer process's state (_clean_worker_init).
_CLEAN_WORKER: dict = {}


def _clean_worker_init(open_reader, crystal_params, h0, fs, ntsc, cancel_xtalk, cancel_leak,
                       dc=0.0, decoder_filter=None, xtalk_kept=None):
    """A producer process: its own reader of the capture, and its own clock
    lines rebuilt on it."""
    read_fn = open_reader()
    crystal = None
    if crystal_params is not None:
        from .stack_corrections import CrystalLines
        crystal = CrystalLines(read_fn=read_fn, **crystal_params)
    _CLEAN_WORKER.update(read_fn=read_fn, crystal=crystal, h0=h0, fs=fs, ntsc=ntsc,
                         cancel_xtalk=cancel_xtalk, cancel_leak=cancel_leak, dc=dc,
                         decoder_filter=decoder_filter, xtalk_kept=xtalk_kept)


def _clean_worker_chunk(s0: int, n: int) -> np.ndarray:
    w = _CLEAN_WORKER
    return _clean_chunk(w["read_fn"], w["crystal"], w["h0"], s0, n, w["fs"], w["ntsc"],
                        w["cancel_xtalk"], w["cancel_leak"], w["dc"], w["decoder_filter"],
                        w["xtalk_kept"])


class CleanedSource(StackedSource):
    """``--tbc_mode resample``: one capture with the read-time TBC's
    cancellations but no time-base correction, the reference
    implementation's ``Live::identity``.

    Virtual sample ``s`` is capture sample ``s``.  The clock lines are
    subtracted, and the audio crosstalk and the chroma leak cancelled, on
    the same chunks and by the same code as the stacked source's; the
    decoder then resamples the demodulated video, its own way.  On a timeline
    that maps each sample to itself the stack's sinc read is the sample
    (its phase is always zero), so only the analytic video band, which the
    cancellations need, is computed: with the video band filter's phase-zero
    row, as the stacked source computes it there, as one convolution by FFT
    (the filter is the same at every sample).  The clock lines are detected
    a quarter into the capture (``CLEAN_PROBE_TAIL`` from its end at most),
    where there is picture.

    ``read_fn(start, count)`` reads the capture (zero outside it); ``length``
    is its length.  With ``open_reader``, a picklable factory of such a
    reader, the chunks are cleaned by ``CLEAN_WORKERS`` processes, each with
    its own reader; without it, by one thread of this process.  A detection
    that fails is an error, not a decode left uncleaned.
    """

    def __init__(
        self,
        read_fn: Callable[[int, int], np.ndarray],
        length: int,
        fs: float,
        *,
        ntsc: bool,
        cancel_xtalk: bool = True,
        cancel_xtal: bool = True,
        cancel_leak: bool = True,
        path: str = "capture",
        open_reader: Callable[[], Callable[[int, int], np.ndarray]] | None = None,
        decoder_filter: tuple | None = None,
    ) -> None:
        self.device = "cpu"
        self._gpu = None
        self.inputs = [StackInput(path=path, read_fn=read_fn, length=int(length),
                                  open_reader=open_reader)]
        # Centred before it is cleaned, as the stacked source centres its
        # captures (capture_dc); the chunks get the offset back.
        self._dc = [capture_dc(read_fn, length)]
        read_fn = _CentredReader(read_fn, self._dc[0], length)
        if open_reader is not None:
            open_reader = _CentredOpener(open_reader, self._dc[0], length)
        self._readers = [read_fn]
        self.fs = float(fs)
        self.ntsc = bool(ntsc)
        self.stack_weight = "fixed"
        self.cancel_xtalk = bool(cancel_xtalk)
        self.cancel_xtal = bool(cancel_xtal)
        self.cancel_leak = bool(cancel_leak)
        self._decoder_filter = decoder_filter
        self._xtalk_kept = None
        self.system = SYSTEM_NTSC if self.ntsc else SYSTEM_PAL
        self._rf_out = None
        self._xtalk_broken = False
        self._leak_broken = False
        self._length = int(length)
        self._live = None
        self._scan_stops = []
        self._cache = None
        self._pool = None
        self._inflight = set()
        self._inflight_lock = threading.Lock()
        split = (SPLIT_LO_HZ, SPLIT_HI_HZ) if self.ntsc else PAL_SPLIT_HZ
        self._h0 = np.ascontiguousarray(video_band_lut(self.fs, split)[0])
        self._crystal = [None]
        try:
            if self.cancel_xtal:
                probe = min(self._length // 4, max(self._length - CLEAN_PROBE_TAIL, 0))
                self._crystal[0] = self._detect_crystal(0, probe)
            if self.cancel_xtalk:
                self._xtalk_kept = _steady_carriers(read_fn, self._length, self.fs, self.ntsc,
                                                    self._decoder_filter)
            if open_reader is not None:
                import concurrent.futures
                import multiprocessing

                # Spawned, never forked, as the decoder's own pools are
                # (parallel.py): the decoder's process already runs threads
                # (the producers, numba's, the writer's), and a child forked
                # while one of them holds a lock keeps it held forever.
                self._pool = concurrent.futures.ProcessPoolExecutor(
                    max_workers=CLEAN_WORKERS,
                    mp_context=multiprocessing.get_context("spawn"),
                    initializer=_clean_worker_init,
                    initargs=(open_reader, _crystal_params(self._crystal[0]), self._h0,
                              self.fs, self.ntsc, self.cancel_xtalk, self.cancel_leak,
                              self._dc[0], self._decoder_filter, self._xtalk_kept),
                )
                self._cache = _ChunkCache(self._compute_chunk, ahead=CLEAN_AHEAD,
                                          workers=CLEAN_WORKERS)
            else:
                self._cache = _ChunkCache(self._compute_chunk)
        except BaseException:
            self.close()
            raise

    @property
    def length(self) -> int:
        return self._length

    def _compute_chunk(self, index: int, chunk: int) -> np.ndarray | None:
        s0 = index * chunk
        if s0 >= self._length:
            return None
        n = min(chunk, self._length - s0)
        pool = self._pool
        if pool is not None:
            future = pool.submit(_clean_worker_chunk, s0, n)
            with self._inflight_lock:
                self._inflight.add(future)
            try:
                out = future.result()
            finally:
                with self._inflight_lock:
                    self._inflight.discard(future)
        else:
            out = _clean_chunk(self._readers[0], self._crystal[0], self._h0, s0, n,
                               self.fs, self.ntsc, self.cancel_xtalk, self.cancel_leak,
                               self._dc[0], self._decoder_filter, self._xtalk_kept)
        return out

    def close(self) -> None:
        super().close()
        pool = getattr(self, "_pool", None)
        if pool is not None:
            self._pool = None
            # Cancel the chunks queued ahead of a decode that has ended, and
            # let those a worker is computing finish: a worker terminated
            # while it writes its result (a chunk is 16 MB) leaves the
            # executor's manager thread blocked on a truncated pickle, and the
            # interpreter's exit then joins it forever - the decode printed
            # its summary and never exited (decode-pal-basic on a CI runner).
            # Only a worker still busy after the drain is wedged: terminated,
            # as parallel.AffinityPool.close does.
            processes = list((getattr(pool, "_processes", None) or {}).values())
            pool.shutdown(wait=False, cancel_futures=True)
            with self._inflight_lock:
                pending = list(self._inflight)
            import concurrent.futures

            concurrent.futures.wait(pending, timeout=CLEAN_DRAIN_TIMEOUT_S)
            if any(not f.done() for f in pending):
                for proc in processes:
                    if proc.is_alive():
                        proc.terminate()
