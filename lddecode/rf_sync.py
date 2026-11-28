"""
rf_sync - line location straight from a LaserDisc RF capture

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Locates the lines of a LaserDisc RF capture straight from the RF, without
demodulating it: a coarse frequency estimate finds every sync pulse, each
horizontal sync is then refined to a fraction of a sample, and the fields are
built on the line grid that follows.  The VBI frame codes of a frame are read
from the Philips code lines of its first field.

Consumed by stack.py, which needs the absolute position of every line of every
field to lay down the stacked timeline.

The module is self-contained (stdlib, NumPy and SciPy only): it never opens a
file, and the capture is reached through the injected `read_fn` seam.

The algorithm is the one of the Rust implementation this module was ported
from; the samples are handled in float64 there in float32.  The one place the
port departs from it is noted in `locate` (the broad pulse of the vertical
interval is remembered across the read chunks).
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass
from typing import Callable, Iterator, Optional, Sequence

import numpy as np
from scipy.signal import lfilter
from scipy.special import i0 as _bessel_i0

__all__ = [
    "SyncSystem",
    "FieldRecord",
    "system_for",
    "frame_code",
    "locate",
    "porch_window",
]


# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

#: The sample rate the sample counts below are given at; every count is
#: rescaled to the capture's own rate (see `_count_at_rate`).
REF_FS = 75.0e6

#: Coarse detector: taps and the step between taps, at REF_FS.
COARSE_TAPS = 48.0
COARSE_STEP = 32.0

#: Fine stage taps, at REF_FS.
FINE_TAPS = 191.0

#: Boxcar on the fine frequency for the edge and the levels (NTSC).
SMOOTH = 9.0

#: A line off the straight path of its measured neighbours by more than this
#: many samples (at REF_FS) is a damaged one.
MAX_LINE_DEV = 3.0

#: Samples processed per step, and the context read on each side of them.
CHUNK = 1 << 22
MARGIN = 1 << 17

#: Points of the coarse grid gathered at a time.  The gather is the whole
#: cost of the coarse stage, and a block that fits in the cache keeps it
#: there.
GRID_BLOCK = 1 << 15

#: Lines each field records past the next field's first line.
OVERLAP_LINES = 10

#: A vertical interval found within this many lines of the next predicted one
#: is taken as that one.
FIELD_SLACK = 3

#: Fields the structure fills in where their vertical intervals were not found.
FIELD_FILL = 4


def _round_half_away(x: float) -> float:
    """Round half away from zero, as Rust's `f64::round` does."""
    return math.floor(x + 0.5) if x >= 0.0 else math.ceil(x - 0.5)


def _at_rate(n: float, fs: float) -> float:
    """`n` samples at REF_FS, rescaled to `fs` (exact at REF_FS).

    Parameters
    ----------
    n : float
        Sample count at :data:`REF_FS`.
    fs : float
        The capture's sample rate, in Hz.

    Returns
    -------
    float
        The same duration at `fs`, in samples.
    """
    return n * fs / REF_FS


def _count_at_rate(n: float, fs: float, odd: bool) -> int:
    """`n` samples at REF_FS, rescaled to `fs` and rounded to a whole sample.

    Parameters
    ----------
    n : float
        Sample count at :data:`REF_FS`.
    fs : float
        The capture's sample rate, in Hz.
    odd : bool
        Keep the count odd, so the filter stays symmetric.

    Returns
    -------
    int
        The sample count at `fs`, at least 1.
    """
    c = max(1, int(_round_half_away(_at_rate(n, fs))))
    if odd and c % 2 == 0:
        c += 1
    return c


# --------------------------------------------------------------------------
# The video standards
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SyncSystem:
    """The per-standard constants the line location needs.

    Attributes
    ----------
    ntsc : bool
        True for NTSC (525 lines, 4.43 MHz... no: 3.58 MHz subcarrier), False
        for PAL (625 lines).
    fsc_hz : float
        The colour subcarrier, in Hz.  For NTSC this is the carrier the lines
        lock onto; for PAL it is the (unused here) 4.43361875 MHz subcarrier.
    lock_hz : float
        The carrier the lines lock onto, in Hz: the NTSC colour burst
        (3.579545454... MHz) or the PAL 3.75 MHz pilot.
    sync_hz : float
        The carrier frequency of the sync tip, in Hz.
    blank_hz : float
        The carrier frequency of the blanking level, in Hz.
    coarse_band : tuple[float, float]
        The band-pass of the coarse detector, in Hz.
    fine_band : tuple[float, float]
        The band-pass of the fine stage, in Hz.
    porch_us : float
        The start of the back-porch window, in microseconds after the start of
        the sync tip.  The window's end is `porch_window(system)[1]`.
    vbi_lines : tuple[int, int]
        The first and last line of the field that carry the Philips codes.
    field_lines : tuple[int, int]
        The number of lines of the first field and of the second field.
    line_hz : float
        The line rate, in Hz.
    line_us : float
        The line length, in microseconds.
    """

    ntsc: bool
    fsc_hz: float
    lock_hz: float
    sync_hz: float
    blank_hz: float
    coarse_band: tuple[float, float]
    fine_band: tuple[float, float]
    porch_us: float
    vbi_lines: tuple[int, int]
    field_lines: tuple[int, int]
    line_hz: float
    line_us: float


@dataclass(frozen=True)
class _Extra:
    """The per-standard values `SyncSystem` does not carry.

    Attributes
    ----------
    hz_ire : float
        The carrier frequency of one IRE, in Hz.
    porch_us : tuple[float, float]
        The back-porch window, in microseconds after the start of the sync tip.
    lock_us : tuple[float, float]
        The burst (NTSC) or pilot (PAL) window, in microseconds after the
        start of the sync tip.
    vbi_after_v : tuple[float, float]
        The window of lines after the broad pulse that carry the Philips codes.
    """

    hz_ire: float
    porch_us: tuple[float, float]
    lock_us: tuple[float, float]
    vbi_after_v: tuple[float, float]


#: The width of a horizontal sync pulse (us), as the reference reads it: the
#: low bound is part of the range.
H_WIDTH_US = (3.6, 6.2)
#: The width of an equalizing pulse (us), as the reference reads it.
E_WIDTH_US = (1.6, 3.2)
#: The width of the broad pulse of the vertical sync (us).
V_WIDTH_US = (15.0, 40.0)
#: The spacing of the Philips code's mid-bit transitions (us), as the
#: reference reads it: the low bound is part of the range.
PHILIPS_STEP_US = (1.75, 2.25)


def _in_range(value: float, bounds: tuple[float, float]) -> bool:
    """Whether `value` is in the reference's range: the low bound included.

    The reference reads its windows as half-open ranges (the low bound
    included, the high bound not), and this is how it reads them.
    """
    return bounds[0] <= value < bounds[1]


# NTSC: the subcarrier is 315/88 MHz (SMPTE 170M-2004 Section 4.2) and one
# IRE is 1.7 MHz over 140 IRE (the sync tip sits at -40 IRE).
_NTSC_EXTRA = _Extra(
    hz_ire=1.7e6 / 140.0,
    porch_us=(8.0, 9.0),
    lock_us=(21.0e6 / (315.0e6 / 88.0), 28.0e6 / (315.0e6 / 88.0)),
    vbi_after_v=(6.0, 14.0),
)

# PAL: the sync tip sits at -0.3 * (100/0.7) IRE (ITU-R BT.470-6) and the
# pilot on the sync tip is at 3.75 MHz.
_PAL_EXTRA = _Extra(
    hz_ire=8000.0,
    porch_us=(8.3, 9.5),
    lock_us=(0.6, 3.4),
    vbi_after_v=(8.0, 24.0),
)


def system_for(ntsc: bool) -> SyncSystem:
    """The constants of the NTSC or the PAL line location.

    Parameters
    ----------
    ntsc : bool
        True for NTSC, False for PAL.

    Returns
    -------
    SyncSystem
        The frozen set of constants for that standard.
    """
    if ntsc:
        # SMPTE 170M-2004 Section 4.2: fsc = 315/88 MHz, 525 lines, 30 Hz.
        fsc = 315.0e6 / 88.0
        return SyncSystem(
            ntsc=True,
            fsc_hz=fsc,
            lock_hz=fsc,
            sync_hz=8.1e6 - 40.0 * _NTSC_EXTRA.hz_ire,
            blank_hz=8.1e6,
            coarse_band=(4.5e6, 12.5e6),
            fine_band=(3.8e6, 13.0e6),
            porch_us=8.0,
            vbi_lines=(12, 20),
            field_lines=(263, 262),
            line_hz=15734.264,
            # 227.5e6 / fsc, as the reference does: the line's own length,
            # not the rounded 63.5 us.
            line_us=227.5e6 * 88.0 / 315.0e6,
        )
    # ITU-R BT.470-6: 625 lines, 25 Hz, the 3.75 MHz pilot on the sync tip.
    return SyncSystem(
        ntsc=False,
        fsc_hz=4.43361875e6,
        lock_hz=3.75e6,
        sync_hz=7.1e6 - 0.3 * (100.0 / 0.7) * _PAL_EXTRA.hz_ire,
        blank_hz=7.1e6,
        coarse_band=(2.6e6, 11.5e6),
        fine_band=(2.4e6, 12.0e6),
        porch_us=8.3,
        vbi_lines=(10, 30),
        field_lines=(312, 313),
        line_hz=15625.0,
        line_us=64.0,
    )


def _extra(system: SyncSystem) -> _Extra:
    """The per-standard values `SyncSystem` does not carry."""
    return _NTSC_EXTRA if system.ntsc else _PAL_EXTRA


def porch_window(system: SyncSystem) -> tuple[float, float]:
    """The back-porch window of a standard, in microseconds.

    The window runs from the start of the sync tip; the porch level is the
    median of the fine frequency over it.

    Parameters
    ----------
    system : SyncSystem
        The standard.

    Returns
    -------
    tuple[float, float]
        The start and the end of the window, in microseconds.
    """
    return _extra(system).porch_us


# --------------------------------------------------------------------------
# The complex band-pass FIR
# --------------------------------------------------------------------------


class _Fir:
    """A complex band-pass FIR: a Kaiser-windowed sinc, as re/im taps.

    The taps are zero-padded to a multiple of eight (the product's lanes);
    the padding is at the end of the kernel, so the kernel's centre stays
    where it was designed.

    Attributes
    ----------
    kernel : numpy.ndarray
        The complex taps (a copy; never mutated).
    kernel_rev : numpy.ndarray
        The taps, reversed: the correlation the filter computes is a
        convolution with them (never mutated).
    half : int
        The kernel's half length, in taps.
    size : int
        The number of taps, padded.
    """

    def __init__(self, taps: int, band: tuple[float, float], beta: float, fs: float):
        half = (taps - 1) / 2.0
        bw = (band[1] - band[0]) / fs
        f0 = (band[1] + band[0]) / 2.0 / fs
        i0b = float(_bessel_i0(beta))
        k = np.arange(taps, dtype=np.float64) - half
        x = np.pi * bw * k
        sinc = np.ones(taps, dtype=np.float64)
        nz = k != 0.0
        sinc[nz] = np.sin(x[nz]) / x[nz]
        r = k / half
        w = _bessel_i0(beta * np.sqrt(np.maximum(0.0, 1.0 - r * r))) / i0b
        a = bw * sinc * w
        ph = -2.0 * np.pi * f0 * k
        # Reversed, so the output is a plain dot product with the input.
        re = a * np.cos(ph)
        im = a * np.sin(ph)
        padded = (taps + 7) // 8 * 8
        self.kernel = np.concatenate([re + 1j * im, np.zeros(padded - taps, dtype=np.complex128)])
        self.kernel_rev = np.ascontiguousarray(self.kernel[::-1])
        self.half = (taps - 1) // 2
        self.size = padded

    def outputs(self, x: np.ndarray, c0: int, c1: int) -> np.ndarray:
        """The complex output of the filter at every position in a range.

        The output at `c` is the filter centred on `x[c]`, as the Rust's
        `Fir::at` computes it.

        Parameters
        ----------
        x : numpy.ndarray
            The input samples (float64).
        c0 : int
            The first position.
        c1 : int
            The last position (inclusive).

        Returns
        -------
        numpy.ndarray
            A new complex128 array of `c1 - c0 + 1` outputs.
        """
        n = c1 - c0 + 1
        if n <= 0:
            return np.zeros(0, dtype=np.complex128)
        # The correlation is a convolution with the reversed kernel: the
        # convolution of the samples `[c0 - half, c0 - half + n + size)` holds
        # it from its `size - 1`th sample on.
        start = c0 - self.half
        xs = x[start : start + n + self.size - 1]
        conv = np.convolve(xs, self.kernel_rev)
        return conv[self.size - 1 : self.size - 1 + n]

    def outputs_grid(
        self,
        x: np.ndarray,
        base: int,
        step: int,
        count: int,
        shifts: Sequence[int],
        block: int = GRID_BLOCK,
    ) -> list[np.ndarray]:
        """The complex output of the filter on a grid of positions.

        The output is taken at the positions `base + m * step + s`, for
        `m = 0..count - 1` and every shift `s` of `shifts`.

        The samples the filter needs are gathered once per block of the grid
        and the taps are applied to them with one matrix product per shift:
        the coarse stage needs the filter at a few positions per step of the
        grid, and gathering them is what the whole stage costs.

        Parameters
        ----------
        x : numpy.ndarray
            The input samples (float64).
        base : int
            The position of the first point of the grid.
        step : int
            The step between two points of the grid, in samples.
        count : int
            The number of points of the grid.
        shifts : sequence of int
            The shifts of every point of the grid, in samples.
        block : int
            How many points of the grid are gathered at a time.

        Returns
        -------
        list of numpy.ndarray
            One complex128 array of the outputs per shift.  The arrays are
            shorter than `count` when the samples run out before the grid
            does.
        """
        out = [np.zeros(count, dtype=np.complex128) for _ in shifts]
        if count <= 0:
            return out
        size = self.size
        span = size + max(shifts) + 1
        valid = 0
        for s in range(0, count, block):
            e = min(s + block, count)
            m = e - s
            start = base - self.half + s * step
            xs = x[start : start + (m - 1) * step + span]
            if xs.size < span:
                break
            win = np.lib.stride_tricks.sliding_window_view(xs, span)[::step]
            m = win.shape[0]
            for j, shift in enumerate(shifts):
                out[j][s : s + m] = win[:, shift : shift + size] @ self.kernel
            valid = s + m
            if m < e - s:
                break
        return [o[:valid] for o in out]


def _inst_freq(fir: _Fir, x: np.ndarray, c0: int, c1: int, fs: float) -> np.ndarray:
    """The instantaneous frequency (Hz) at every position of a range.

    The frequency comes from the phase step between neighbouring outputs of
    the filter, as the Rust's `Fir::freq` computes it.

    Parameters
    ----------
    fir : _Fir
        The filter.
    x : numpy.ndarray
        The input samples (float64).
    c0 : int
        The first position.
    c1 : int
        The last position (inclusive).
    fs : float
        The sample rate, in Hz.

    Returns
    -------
    numpy.ndarray
        A new float64 array of `c1 - c0 + 1` frequencies, in Hz.
    """
    z = fir.outputs(x, c0 - 1, c1)
    prod = z[1:] * np.conj(z[:-1])
    return np.angle(prod) * (fs / (2.0 * math.pi))


# --------------------------------------------------------------------------
# Pulses
# --------------------------------------------------------------------------


class _Kind(enum.IntEnum):
    """The kind of a sync pulse."""

    H = 0  # horizontal sync
    E = 1  # equalizing pulse
    V = 2  # broad pulse of the vertical sync


@dataclass
class _Pulse:
    """A sync pulse: its absolute start (samples) and its kind."""

    start: float
    kind: _Kind


@dataclass
class _Fine:
    """The fine measurement of one horizontal sync."""

    edge: Optional[float] = None
    psi: Optional[float] = None
    code: Optional[int] = None


def _find_pulses(freq: np.ndarray, t0: float, step: int, thr: float, fs: float) -> list[_Pulse]:
    """The pulses in a coarse frequency estimate.

    A pulse is a run of the frequency below `thr`; its width gives its kind.

    Parameters
    ----------
    freq : numpy.ndarray
        The coarse frequency (Hz) at `t0 + i * step`.
    t0 : float
        The time (samples) of the first entry of `freq`.
    step : int
        The step between the entries, in samples.
    thr : float
        The threshold (Hz) the frequency has to fall below.
    fs : float
        The sample rate, in Hz.

    Returns
    -------
    list[_Pulse]
        The pulses found, in order, with their absolute start in samples.
    """
    if freq.size < 2:
        return []
    us = fs / 1e6
    a = freq[:-1]
    b = freq[1:]
    with np.errstate(divide="ignore", invalid="ignore"):
        frac = (a - thr) / (a - b)
    t = t0 + np.arange(a.size, dtype=np.float64) * step + step * frac
    falling = np.flatnonzero((a >= thr) & (b < thr))
    rising = np.flatnonzero((a < thr) & (b >= thr))
    out: list[_Pulse] = []
    if falling.size == 0 or rising.size == 0:
        return out
    # Each rising crossing closes the pulse the last falling crossing before it
    # opened (a falling crossing while a pulse is open replaces its start, as
    # the Rust's scan does).
    idx = np.searchsorted(falling, rising, side="left") - 1
    paired = idx >= 0
    idx_c = np.clip(idx, 0, None)
    previous = np.concatenate(([-1], rising[:-1]))
    paired &= falling[idx_c] > previous
    for r, f in zip(rising[paired], falling[idx_c[paired]]):
        start = float(t[f])
        width = (float(t[r]) - start) / us
        if _in_range(width, H_WIDTH_US):
            kind = _Kind.H
        elif _in_range(width, E_WIDTH_US):
            kind = _Kind.E
        elif _in_range(width, V_WIDTH_US):
            kind = _Kind.V
        else:
            continue
        out.append(_Pulse(start=start, kind=kind))
    return out


def _median(v: np.ndarray) -> float:
    """The median of a small slice, as the Rust's `median` computes it.

    The slice is sorted in place and its upper middle element is taken, so an
    even count gives the larger of the two middle values.
    """
    if v.size == 0:
        raise ValueError("median of an empty slice")
    return float(np.sort(v)[v.size // 2])


def _philips(
    sm: np.ndarray, c0: int, edge: float, porch: float, fs: float, hz_ire: float
) -> Optional[int]:
    """A Philips code (24 bits, biphase, 2 us per bit) on one line.

    The code is read as the decoder reads it: transitions through 50 IRE
    above the porch level.  The bit is the direction of the transition (an
    upward one is a 1).

    Parameters
    ----------
    sm : numpy.ndarray
        The smoothed frequency of the line (Hz).
    c0 : int
        The index in `sm` of the sample at the absolute position 0.
    edge : float
        The absolute position (samples) of the line's leading edge.
    porch : float
        The porch level (Hz).
    fs : float
        The sample rate, in Hz.
    hz_ire : float
        The carrier frequency of one IRE, in Hz.

    Returns
    -------
    int or None
        The 24-bit code, or None when the line does not carry one.
    """
    us = fs / 1e6
    thr = porch + 50.0 * hz_ire
    below = sm < thr

    def cross(frm: float, length: float) -> Optional[float]:
        a = max(int(frm - c0), 1)
        b = min(int(frm + length - c0), sm.size)
        if b <= a:
            return None
        seg = below[a - 1 : b - 1]
        ch = np.flatnonzero(seg[:-1] != seg[1:])
        if ch.size == 0:
            return None
        i = a + int(ch[0])
        return c0 + (i - 1) + (sm[i - 1] - thr) / (sm[i - 1] - sm[i])

    zc: list[tuple[float, bool]] = []
    cur = cross(edge + 2.0 * us, 12.0 * us)
    while cur is not None:
        i = int(cur - 0.5 * us - c0)
        zc.append((cur, 0 <= i < sm.size and bool(sm[i] < thr)))
        if len(zc) > 24:
            return None
        # Next mid-bit transition 2 us on (boundary ones are 1 us away). The
        # window is wider than the decoder's 1.9..2.1: on the RF the rising
        # and falling edges sit ~0.1 us apart.
        cur = cross(cur + 1.75 * us, 0.5 * us)
    if len(zc) != 24:
        return None
    gaps = [(zc[i + 1][0] - zc[i][0]) / us for i in range(len(zc) - 1)]
    if not all(_in_range(g, PHILIPS_STEP_US) for g in gaps):
        return None
    value = 0
    for _, bit in zc:
        value = (value << 1) | (1 if bit else 0)
    return value


def _refine(
    x: np.ndarray,
    s: float,
    fir: _Fir,
    fs: float,
    vbi: bool,
    system: SyncSystem,
) -> _Fine:
    """Refine one horizontal sync whose coarse start is `s` (an index into `x`).

    The leading edge is the 50% crossing of the sync tip, the levels give the
    depth check, and the burst (NTSC) or the pilot (PAL) gives the phase.

    Parameters
    ----------
    x : numpy.ndarray
        The input samples (float64).
    s : float
        The coarse start of the pulse, as an index into `x`.
    fir : _Fir
        The fine filter.
    fs : float
        The sample rate, in Hz.
    vbi : bool
        The line is a VBI candidate (the Philips code is read on it).
    system : SyncSystem
        The standard.

    Returns
    -------
    _Fine
        The measurement; every field is None when the line was rejected.
    """
    extra = _extra(system)
    us = fs / 1e6
    half = fir.half
    c0 = int(s - 1.2 * us)
    # Up to the end of the porch window as seen from an edge up to 1.5 us
    # late (the tip search), plus the average's reach: every sample read
    # below, and no more.
    span = 64.0 if vbi else extra.porch_us[1] + 1.6
    c1 = int(s + span * us)
    if c0 < half + 1 or c1 + half + 8 >= x.size:
        return _Fine()
    c0 = max(c0, 0)
    c1 = min(c1, x.size - 1)
    if c1 <= c0:
        return _Fine()
    f = _inst_freq(fir, x, c0, c1, fs)
    # Centred boxcar for the edge and the levels: SMOOTH samples, or three
    # pilot periods on PAL (a whole number at 40 MHz, so it nulls the pilot;
    # one rounded period leaves a ripple that crosses the threshold at the
    # start of the sync tip). The edge, blurred symmetrically, keeps its 50%
    # point.
    if system.ntsc:
        blen = _count_at_rate(SMOOTH, fs, False)
    else:
        blen = int(_round_half_away(3.0 * fs / system.lock_hz))
    blen = max(1, blen)
    cs = np.concatenate(([0.0], np.cumsum(f)))
    lo = np.maximum(np.arange(f.size) - blen // 2, 0)
    hi = np.minimum(np.arange(f.size) + blen - blen // 2, f.size)
    sm = (cs[hi] - cs[lo]) / (hi - lo)

    def at(t: float) -> int:
        # The Rust's `as usize` cast: negative values saturate at 0.
        return max(int(t - c0), 0)

    i_sync = at(s + 1.0 * us)
    i_sync2 = min(at(s + 2.5 * us), sm.size)
    i_porch = at(s + extra.porch_us[0] * us)
    i_porch2 = min(at(s + extra.porch_us[1] * us), sm.size)
    if i_sync2 <= i_sync or i_porch2 <= i_porch:
        return _Fine()
    sync = _median(sm[i_sync:i_sync2])
    porch = _median(sm[i_porch:i_porch2])
    depth = (porch - sync) / extra.hz_ire
    if not (25.0 < depth < 55.0):
        return _Fine()
    mid = (porch + sync) / 2.0
    # The leading edge: the crossing closest to the sync tip, walking back
    # from inside it. A dark-going transition just before the front porch
    # undershoots through the threshold on the still pre-emphasized RF (PAL
    # especially); a forward search would stop there.
    frm = max(at(s - 1.0 * us), 1)
    tip = min(at(s + 1.5 * us), sm.size - 1)
    if tip <= frm or sm[tip] >= mid:
        return _Fine()
    below_mid = sm[frm : tip + 1] < mid
    cross_idx = np.flatnonzero(~below_mid[:-1] & below_mid[1:])
    if cross_idx.size == 0:
        return _Fine()
    i = frm + int(cross_idx[-1]) + 1
    edge = c0 + (i - 1) + (sm[i - 1] - mid) / (sm[i - 1] - sm[i])
    # Dropout check: the pulse and the porch stay within -90..50 IRE. Wider
    # than the decoder's -55..30, since on the RF the video is still
    # pre-emphasized (the edges overshoot); a dropout sends the carrier much
    # further off. The burst is left out (pre-emphasized as well).
    lo_ire = porch - 90.0 * extra.hz_ire
    hi_ire = porch + 50.0 * extra.hz_ire

    def ok(a: float, b: float) -> bool:
        ia = min(at(a), sm.size)
        ib = min(at(b), sm.size)
        if ib <= ia:
            return True
        seg = sm[ia:ib]
        return bool(np.all((seg >= lo_ire) & (seg <= hi_ire)))

    if not ok(edge - 0.75 * us, edge + 4.0 * us) or not ok(
        edge + extra.porch_us[0] * us, edge + extra.porch_us[1] * us
    ):
        return _Fine()
    # Burst (NTSC) or pilot (PAL): least-squares phase over its window.
    w = 2.0 * math.pi * system.lock_hz / fs
    b0 = edge + extra.lock_us[0] * us
    b1 = edge + extra.lock_us[1] * us
    i0 = max(at(b0), 0)
    i1 = min(at(b1), f.size)
    if i1 <= i0:
        return _Fine()
    seg = f[i0:i1]
    mean = float(seg.mean())
    idx = np.arange(i0, i1, dtype=np.float64) + c0 - edge
    ph = w * idx
    v = seg - mean
    pr = float(np.sum(v * np.cos(ph)))
    pi = -float(np.sum(v * np.sin(ph)))
    amp = 2.0 * math.hypot(pr, pi) / (i1 - i0) / extra.hz_ire
    psi = math.atan2(pi, pr) if amp > 5.0 else None
    code = None
    if vbi:
        if system.ntsc:
            code = _philips(sm, c0, edge, porch, fs, extra.hz_ire)
        else:
            # The code is read on the de-emphasized frequency (100/400 ns,
            # bilinear), lightly averaged: on the pre-emphasized RF its
            # transitions overshoot, and the sync tip's three-period average
            # blurs its 1 us half-cells.
            t1, t2 = 100e-9, 400e-9
            k = 2.0 * fs
            bb0 = (1.0 + k * t1) / (1.0 + k * t2)
            bb1 = (1.0 - k * t1) / (1.0 + k * t2)
            aa1 = (1.0 - k * t2) / (1.0 + k * t2)
            # The bilinear de-emphasis is a two-tap filter into a one-tap
            # recursive one: y = bb0 * f + bb1 * f[-1] - aa1 * y[-1].
            de = lfilter([bb0, bb1], [1.0, aa1], f)
            # The light average: nine samples, centred, the edges cut short.
            n = de.size
            cs = np.concatenate(([0.0], np.cumsum(de)))
            idx = np.arange(n)
            lo = np.maximum(idx - 4, 0)
            hi = np.minimum(idx + 5, n)
            light = (cs[hi] - cs[lo]) / (hi - lo)
            code = _philips(light, c0, edge, porch, fs, extra.hz_ire)
    return _Fine(edge=edge, psi=psi, code=code)


# --------------------------------------------------------------------------
# The tracker
# --------------------------------------------------------------------------


class _Tracker:
    """The tracking state: the line grid so far and the fields found on it.

    Attributes
    ----------
    fs : float
        The sample rate, in Hz.
    """

    def __init__(self, fs: float, system: SyncSystem):
        self.fs = fs
        self.system = system
        self.pal = not system.ntsc
        self.lock_hz = system.lock_hz
        self.vbi_lines = system.vbi_lines
        self.hlen = fs * system.line_us / 1e6
        self.base = 0
        # The grid's lines; a line with no hsync (vertical interval, dropout)
        # has no edge and is interpolated.
        self.lines: list[_Fine] = []
        # Absolute index and coarse position of the last line with an hsync.
        self.last_h: Optional[tuple[int, float]] = None
        self.rejects = 0
        self.in_vsync = False
        # A field start seen on its first equalizing pulse, kept once a broad
        # pulse confirms the vertical interval (a lone short pulse, such as an
        # hsync broken up by a dropout or by the PAL pilot, is not one).
        self.pending: Optional[tuple[int, bool]] = None
        # Fields found (absolute first-line index, first field) and not yet sent.
        self.fields: list[tuple[int, bool]] = []
        # Frame code of the last first field sent (a second field inherits it).
        self.last_code: Optional[tuple[bool, Optional[tuple[int, ...]]]] = None
        self.field_lines = system.field_lines
        # The last field found (absolute first line, first field), and how many
        # fields in a row have followed the field structure up to it.
        self.last_field: Optional[tuple[int, bool]] = None
        self.lock = 0
        # Pulses off the line grid since the last one on it.
        self.rejected: list[float] = []
        # The last two first fields' frame codes that identified a frame.
        self.recent_codes: list[list[int]] = []

    def end(self) -> int:
        """The absolute index past the grid's last line."""
        return self.base + len(self.lines)

    def reset(self) -> None:
        """Drop the grid (a jump in the capture).

        Fields found so far that can no longer be completed are lost.
        """
        self.base = self.end()
        self.lines.clear()
        self.last_h = None
        self.fields.clear()
        self.in_vsync = False
        self.last_field = None
        self.lock = 0
        self.rejected.clear()

    def repair_code(self, code: Optional[list[int]]) -> Optional[list[int]]:
        """A first field's frame code, with a dropout's losses put back.

        The words the last two codes share (a CLV disc's constant word next
        to its time code) are added where missing.  A code left with only
        such words identifies no frame (every field has them) and is dropped:
        the field stays unpaired rather than paired with a wrong one.

        Parameters
        ----------
        code : list[int] or None
            The code as read from the VBI lines.

        Returns
        -------
        list[int] or None
            The repaired code, or None when it identifies no frame.
        """
        shared: list[int] = []
        if len(self.recent_codes) == 2:
            a, b = self.recent_codes
            shared = [w for w in a if w in b]
        if code is None:
            return None
        c = list(code)
        for w in shared:
            if w not in c:
                c.append(w)
        c.sort()
        if shared and all(w in shared for w in c):
            return None
        self.recent_codes.append(list(c))
        if len(self.recent_codes) > 2:
            self.recent_codes.pop(0)
        return c

    def field_len(self, first: bool) -> int:
        """The number of lines of a field of the given parity."""
        return self.field_lines[0] if first else self.field_lines[1]

    def field_found(self, li: int, first: bool) -> None:
        """A vertical interval found at line `li`.

        Once two fields in a row have followed the field structure
        (alternating parities, fixed lengths), a start within FIELD_SLACK
        lines of the next predicted one is taken as that one, with its
        parity: a dropout over an hsync or an equalizing pulse moves the
        detection by a line or flips its parity.  Missed intervals (up to
        FIELD_FILL fields) are filled in, and one found well before the
        prediction is a false one and dropped.  Anything else is a jump in
        the capture: the structure starts over from it.
        """
        if self.last_field is not None and self.lock >= 2:
            last, lf = self.last_field
            e = last + self.field_len(lf)
            ef = not lf
            fill: list[tuple[int, bool]] = []
            while e + FIELD_SLACK < li and len(fill) < FIELD_FILL:
                fill.append((e, ef))
                e += self.field_len(ef)
                ef = not ef
            if li + FIELD_SLACK >= e and li <= e + FIELD_SLACK:
                self.fields.extend(fill)
                self.fields.append((e, ef))
                self.last_field = (e, ef)
                self.lock += 1
                return
            if li + FIELD_SLACK < last + self.field_len(lf):
                return
        follows = (
            self.last_field is not None
            and self.last_field[0] + self.field_len(self.last_field[1]) == li
            and self.last_field[1] != first
        )
        self.lock = self.lock + 1 if follows else 1
        self.fields.append((li, first))
        self.last_field = (li, first)

    def rejected_on_grid(self) -> bool:
        """Whether the rejected pulses lie on a line grid of their own.

        Such a grid means a jump in the capture, rather than a dropout's
        noise.
        """
        for i in range(len(self.rejected) - 1):
            d = self.rejected[i + 1] - self.rejected[i]
            kr = _round_half_away(d / self.hlen)
            if not (1.0 <= kr <= 40.0):
                return False
            if abs(d - kr * self.hlen) > (0.4 + 0.15 * (kr - 1.0)) * self.fs / 1e6:
                return False
        return True

    def pulse(self, p: _Pulse, fine: _Fine) -> None:
        """Feed one pulse (and its fine measurement) to the tracker."""
        if p.kind is _Kind.H:
            if self.last_h is not None:
                _, ls = self.last_h
                kr = _round_half_away((p.start - ls) / self.hlen)
                # Off the line grid by more than 0.4 us (plus slack for the
                # line length's drift across a gap, ~0.1 us per line seen): a
                # false pulse (dropout).
                off = abs(p.start - ls - kr * self.hlen)
                if kr < 1.0 or off > (0.4 + 0.15 * (kr - 1.0)) * self.fs / 1e6:
                    # Four pulses off the grid in a row start a new one only
                    # if they agree among themselves: in a dropout the false
                    # pulses do not, and the grid holds.
                    self.rejects += 1
                    self.rejected.append(p.start)
                    if self.rejects >= 4 and self.rejected_on_grid():
                        self.reset()
                    else:
                        if len(self.rejected) >= 4:
                            self.rejected.pop(0)
                        return
                elif kr > 40.0:
                    self.reset()
                else:
                    k = int(kr)
                    if k == 1:
                        # Follow the line length (spindle speed).
                        self.hlen += (p.start - ls - self.hlen) / 8.0
                    for _ in range(1, k):
                        self.lines.append(_Fine())
            self.rejects = 0
            self.rejected.clear()
            self.lines.append(fine)
            self.last_h = (self.end() - 1, p.start)
            self.in_vsync = False
            self.pending = None
        else:
            if self.last_h is None:
                return
            li, ls = self.last_h
            if self.in_vsync:
                if p.kind is _Kind.V and self.pending is not None:
                    pend_li, pend_first = self.pending
                    self.pending = None
                    self.field_found(pend_li, pend_first)
                return
            self.in_vsync = True
            if p.kind is not _Kind.E:
                return
            # The interval opens a full line after the last hsync on one
            # field, half a line after it on the other.
            frac = (p.start - ls) / self.hlen
            if 0.85 <= frac < 1.15:
                full = True
            elif 0.35 <= frac < 0.65:
                full = False
            else:
                return
            first = full != self.pal
            self.pending = (li + 1, first)

    def positions(self, a: int, b: int, psi0: Optional[float]) -> Optional[list[float]]:
        """The positions of the lines `a..b` (absolute indices).

        Measured where the line was measured, interpolated elsewhere.

        Parameters
        ----------
        a : int
            The first line (absolute index).
        b : int
            The last line (exclusive).
        psi0 : float or None
            The field's burst phase reference.

        Returns
        -------
        list[float] or None
            The positions (samples), or None when a line at either end cannot
            be interpolated.
        """
        w = 2.0 * math.pi * self.lock_hz / self.fs
        pos: list[float] = []
        for line in self.lines:
            if line.edge is not None and line.psi is not None and psi0 is not None:
                # The burst's phase, with its half-cycle ambiguity resolved
                # next to the edge. The correction is the edge's own error, a
                # fraction of a sample: a large one is a damaged burst, and
                # the edge is kept instead.
                d = line.psi - psi0
                d -= math.pi * _round_half_away(d / math.pi)
                if abs(d / w) < 2.5:
                    pos.append(line.edge - d / w)
                else:
                    pos.append(line.edge)
            elif line.edge is not None:
                pos.append(line.edge)
            else:
                pos.append(math.nan)

        def neighbours(i: int) -> Optional[tuple[int, int]]:
            j = None
            for jj in range(i - 1, -1, -1):
                if math.isfinite(pos[jj]):
                    j = jj
                    break
            if j is None:
                return None
            for kk in range(i + 1, len(pos)):
                if math.isfinite(pos[kk]):
                    return (j, kk)
            return None

        def dev(i: int) -> float:
            nb = neighbours(i)
            if not math.isfinite(pos[i]) or nb is None:
                return 0.0
            j, k = nb
            return abs(pos[i] - (pos[j] + (pos[k] - pos[j]) * (i - j) / (k - j)))

        # A line off the straight path of its measured neighbours (the nearest
        # on each side, across unmeasured lines) by more than MAX_LINE_DEV
        # samples is a damaged one (the time base moves far less than that
        # from one line to the next): interpolated instead. Of two adjacent
        # suspects, the worse goes.
        #
        # The whole set is decided first, on the positions as measured: a
        # line dropped out of the way does not change the verdict of its
        # neighbours, as the reference does it.
        max_dev = _at_rate(MAX_LINE_DEV, self.fs)
        bad = []
        for i in range(len(pos)):
            d = dev(i)
            if d <= max_dev:
                continue
            nb = neighbours(i)
            if nb is not None and dev(nb[0]) <= d and dev(nb[1]) <= d:
                bad.append(i)
        for i in bad:
            pos[i] = math.nan

        ia, ib = a - self.base, b - self.base
        out: list[float] = []
        for i in range(ia, ib):
            if 0 <= i < len(pos) and math.isfinite(pos[i]):
                out.append(pos[i])
                continue
            lo = None
            for jj in range(i - 1, -1, -1):
                if 0 <= jj < len(pos) and math.isfinite(pos[jj]):
                    lo = jj
                    break
            hi = None
            for kk in range(i + 1, len(pos)):
                if 0 <= kk < len(pos) and math.isfinite(pos[kk]):
                    hi = kk
                    break
            if lo is None or hi is None:
                return None
            t = (i - lo) / (hi - lo)
            out.append(pos[lo] + t * (pos[hi] - pos[lo]))
        return out

    def flush(self) -> Iterator[FieldRecord]:
        """Send every field whose lines are all placed."""
        while len(self.fields) >= 2:
            a, first = self.fields[0]
            nxt = self.fields[1][0]
            b = nxt + OVERLAP_LINES
            # A measured line past the end is needed to interpolate up to it.
            start = min(max(b - self.base, 0), len(self.lines))
            placed = any(line.edge is not None for line in self.lines[start:])
            if a < self.base or not placed:
                if a < self.base:
                    self.fields.pop(0)
                    continue
                return
            # The field's burst phase reference: circular mean over its lines,
            # modulo half a cycle (consecutive lines alternate by pi).
            c = 0.0
            s = 0.0
            for line in self.lines[a - self.base : nxt - self.base]:
                if line.psi is not None:
                    c += math.cos(2.0 * line.psi)
                    s += math.sin(2.0 * line.psi)
            psi0 = (math.atan2(s, c) / 2.0) if (c != 0.0 or s != 0.0) else None
            lines = self.positions(a, b, psi0)
            if lines is not None:
                code: Optional[tuple[int, ...]]
                if first:
                    words = [
                        line.code
                        for line in self.lines[
                            a - self.base + self.vbi_lines[0] : a - self.base + self.vbi_lines[1]
                        ]
                        if line.code is not None
                    ]
                    fc = list(frame_code(words))
                    repaired = self.repair_code(fc if fc else None)
                    code = tuple(repaired) if repaired is not None else ()
                else:
                    code = ()
                    if self.last_code is not None and self.last_code[0]:
                        code = self.last_code[1] or ()
                self.last_code = (first, code)
                yield FieldRecord(first=first, code=code, lines=np.asarray(lines, dtype=np.float64))
            self.fields.pop(0)
            # Keep a few lines before the next field for interpolation.
            keep_from = max(nxt - 64, self.base)
            del self.lines[: keep_from - self.base]
            self.base = keep_from


# --------------------------------------------------------------------------
# The driver
# --------------------------------------------------------------------------


@dataclass
class FieldRecord:
    """One located field.

    Attributes
    ----------
    first : bool
        The field's parity: True for the first field of a frame.
    code : tuple[int, ...]
        The VBI frame-code words of the frame the field belongs to, sorted
        and deduplicated.  Empty when the field's frame was not identified.
    lines : numpy.ndarray
        The absolute position (samples) of every line of the field, as
        float64.
    """

    first: bool
    code: tuple[int, ...]
    lines: np.ndarray


def frame_code(words: Sequence[int]) -> tuple[int, ...]:
    """The VBI words that identify a frame.

    These are the CAV picture numbers and the CLV time codes (a top nibble
    of 0xF or 0x8).  Two captures of the same frame give the same set; a
    misread gives a different one, so the field is just left unpaired.

    Parameters
    ----------
    words : sequence of int
        The 24-bit Philips codes read from the VBI lines.

    Returns
    -------
    tuple[int, ...]
        The identifying words, sorted and deduplicated.
    """
    keep = [w for w in words if w > 0 and ((w >> 20) & 0xF) in (0x8, 0xF)]
    return tuple(sorted(set(keep)))


def _read_window(
    read_fn: Callable[[int, int], np.ndarray], start: int, count: int
) -> tuple[np.ndarray, Optional[int]]:
    """Read a window of samples, zeros before the capture.

    Parameters
    ----------
    read_fn : callable
        ``read_fn(start, count) -> ndarray``: the samples
        `[start, start + count)`.  It returns fewer than `count` samples at
        the end of the capture.
    start : int
        The absolute position of the window's first sample.
    count : int
        The number of samples in the window.

    Returns
    -------
    tuple[numpy.ndarray, int or None]
        The window (a new float64 array) and the end of the capture when the
        read reached it, None while there is more to read.  The window holds
        the samples that exist: it is not padded out to `count`.
    """
    first = max(start, 0)
    n = count - (first - start)
    if n <= 0:
        return np.zeros(0, dtype=np.float64), 0
    data = np.asarray(read_fn(first, n), dtype=np.float64)
    if data.ndim != 1:
        raise ValueError("read_fn must return a 1-D array of RF samples")
    got = data.size
    eof = first + got if got < n else None
    if first > start:
        data = np.concatenate([np.zeros(first - start, dtype=np.float64), data])
    return data, eof


def locate(
    read_fn: Callable[[int, int], np.ndarray],
    fs: float,
    system: SyncSystem,
    *,
    stop: Optional[Callable[[], bool]] = None,
    length: Optional[int] = None,
) -> Iterator[FieldRecord]:
    """Locate every field of a capture, straight from its RF.

    The capture's carrier sits at its lowest frequency during a sync pulse
    (~7.6 MHz on NTSC, against ~8.1 MHz at blanking), so a coarse frequency
    estimate is enough to find every pulse: a short complex band-pass FIR
    evaluated only every `COARSE_STEP` samples (two neighbouring outputs give
    the phase step).  Pulse lengths tell hsyncs from the equalizing and broad
    pulses of the vertical interval, and where that interval starts against
    the line grid gives the field parity.

    Each hsync is then refined as the decoder refines it, on the
    instantaneous frequency of a longer band-pass FIR computed only around
    the pulse: the 50% crossing between the sync tip and the back porch,
    then the colour burst's phase (least squares at fsc), which fixes the
    line to a fraction of a sample.

    Parameters
    ----------
    read_fn : callable
        ``read_fn(start, count) -> ndarray``: the RF samples
        `[start, start + count)` as float.  The library never opens a file
        itself.
    fs : float
        The capture's sample rate, in Hz.
    system : SyncSystem
        The standard (see :func:`system_for`).
    stop : callable, optional
        Returns True when the caller wants the scan to stop (the decoder
        stops where the decode stops).
    length : int, optional
        The capture's length, in samples.  The scan stops there.

        The scan also stops where the reader reports the end of the capture
        by returning fewer samples than were asked for.  A reader that pads
        with zeros past the end of the capture - the project's own raw
        capture reader does - never reports it, so it must pass the length
        here, or the scan never ends.

    Yields
    ------
    FieldRecord
        One per located field, in order.
    """
    coarse = _Fir(_count_at_rate(COARSE_TAPS, fs, False), system.coarse_band, 6.0, fs)
    fine = _Fir(_count_at_rate(FINE_TAPS, fs, True), system.fine_band, 7.0, fs)
    thr = (system.sync_hz + system.blank_hz) / 2.0
    hlen = fs * system.line_us / 1e6
    extra = _extra(system)
    if system.ntsc:
        step = _count_at_rate(COARSE_STEP, fs, False)
        offsets = (0,)
    else:
        # PAL: a step of three pilot periods, the phase steps summed at
        # eight points spread over it, so the pilot averages out.
        step = int(_round_half_away(3.0 * fs / system.lock_hz))
        offsets = tuple(k * step // 8 for k in range(8))
    reach = offsets[-1]
    tracker = _Tracker(fs, system)
    own0 = 0
    total: Optional[int] = None if length is None else max(0, int(length))
    # The last broad pulse seen.  The reference resets it at every chunk
    # boundary, so the VBI candidate lines are the ones a few lines after a
    # broad pulse of the same chunk only.
    while total is None or own0 < total:
        b0 = own0 - MARGIN
        buf, eof = _read_window(read_fn, b0, CHUNK + 2 * MARGIN)
        if eof is not None:
            total = eof if total is None else min(total, eof)
        if stop is not None and stop():
            return
        # Coarse frequency on a grid aligned to absolute multiples of the
        # step, so chunk boundaries do not move it.
        h = coarse.half
        g0 = -(-max(b0 + h + 1, 0) // step) * step
        n = max(0, (b0 + buf.size - h - 10 - reach) - g0) // step
        if n > 1:
            # The coarse filter is needed at every point of the grid, and at
            # the sample just after it (the phase step between the two gives
            # the frequency).
            base = g0 - b0
            shifts = tuple(offsets) + tuple(off + 1 for off in offsets)
            values = coarse.outputs_grid(buf, base, step, n, shifts)
            m = values[0].size
            prods = np.zeros(m, dtype=np.complex128)
            for j in range(len(offsets)):
                a = values[j]
                b = values[len(offsets) + j]
                prods += b * np.conj(a)
            freq = np.angle(prods[:-1] + prods[1:]) * (fs / (2.0 * math.pi))
            t0 = g0 + step / 2.0
            pulses = _find_pulses(freq, t0, step, thr, fs)
            own1 = own0 + CHUNK if total is None else min(own0 + CHUNK, total)
            last_v = -math.inf
            for p in pulses:
                if p.kind is _Kind.V:
                    last_v = p.start
                if not (own0 <= p.start < own1):
                    continue
                vbi = p.kind is _Kind.H and _in_range((p.start - last_v) / hlen, extra.vbi_after_v)
                if p.kind is _Kind.H:
                    fr = _refine(buf, p.start - b0, fine, fs, vbi, system)
                    if fr.edge is not None:
                        fr.edge += b0
                else:
                    fr = _Fine()
                tracker.pulse(p, fr)
            yield from tracker.flush()
        own0 += CHUNK
        if total is not None and own0 >= total:
            break
