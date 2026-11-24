"""
stack_corrections - signal corrections applied to a stacked RF capture

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Three corrections the stacking pipeline applies to the RF it reads:

- `cancel_crosstalk` takes out of the stream the part of the demodulated
  video that follows the two analog audio carriers.  On the disc they leak
  into the video carrier's phase; the leak is the same on every copy (one
  soundtrack), so no stacking removes it.
- `cancel_chroma_leak` takes out of the stream the composite chroma that
  leaks into the RF baseband around the colour subcarrier: it beats with the
  video carrier and makes the fine wavering vertical stripes of saturated
  areas, the NTSC "colour wobble".
- `CrystalLines` finds the narrow clock lines a capture carries (the
  player's EFM decoder crystal and the capture board's clocks) and subtracts
  them from the samples as they are read.

This module is a layer 0/1 primitive: pure signal maths over NumPy arrays,
with no file, network or clock access of its own.  The reader a caller
supplies is the only way data enters it, so the module is hermetically
testable.

Ported from the Rust implementation in `crates/ld-decode-cli/src/stack.rs`
of the ld-decode-rust project (branch `vrunk11_main`).
"""

from __future__ import annotations

import math
from collections import OrderedDict
from typing import Callable, Optional, Sequence

import numpy as np
import scipy.fft

from .stack_kernels import (
    crosstalk_correction_kernel,
    line_phasors_kernel,
    narrow_band_kernel,
    subtract_lines_kernel,
)

__all__ = [
    "cancel_crosstalk",
    "crosstalk_block_gains",
    "crosstalk_coupling",
    "crosstalk_phase",
    "cancel_chroma_leak",
    "CrystalLines",
    "AUDIO_CARRIERS_HZ",
    "PAL_AUDIO_CARRIERS_HZ",
    "XTALK_KEEP_HZ",
    "PAL_XTALK_KEEP_HZ",
    "LEAK_BAND_HZ",
    "EFM_XTAL_HZ",
    "XTAL_DIV",
    "LINE_EXCLUDE_HZ",
    "PAL_LINE_EXCLUDE_HZ",
    "NTSC_LINE_HZ",
    "PAL_LINE_HZ",
]

TAU = 2.0 * math.pi

# --------------------------------------------------------------------------
# Audio crosstalk cancellation
# --------------------------------------------------------------------------

#: The analog audio carriers (Hz), NTSC and PAL.
AUDIO_CARRIERS_HZ = (2.301136e6, 2.8125e6)
PAL_AUDIO_CARRIERS_HZ = (0.68359375e6, 1.06640625e6)

#: Length of each of the three cascaded boxcars that take a carrier out of
#: the RF (seconds): ~150 kHz around it, wide enough for its deviation.
XTALK_BOX_S = 320.0 / 75.0e6

#: The correction fades in and out over this much at each chunk's edges
#: (seconds), where the boxcars run out of signal: so it is continuous from
#: one chunk to the next.
XTALK_TAPER_S = 1024.0 / 75.0e6

#: The correction is kept above this raised-cosine edge (Hz, NTSC; PAL: its
#: video band split): the video is demodulated from above it, the audio
#: carriers and the EFM sit below.
XTALK_KEEP_HZ = (3.0e6, 3.6e6)
PAL_XTALK_KEEP_HZ = (1.9e6, 2.4e6)

#: The carriers, once at 0 Hz, are kept every this many samples.
XTALK_DEC = 16

#: The crosstalk gains are fitted on every this many samples of a chunk.
XTALK_FIT_STRIDE = 20

#: A coupling measured over a stretch of blocks (`crosstalk_coupling`) is
#: shrunk away unless it stands this many standard errors above zero.
XTALK_COUPLING_Z = 3.0

#: FFT length of the correction's high-pass, and the context it takes on
#: each side of each block (seconds).
XTALK_FFT_LEN = 1 << 15
XTALK_OV_S = 2048.0 / 75.0e6

#: Kept samples per span of running sums of the full-rate boxcar.
XTALK_BOX_SPAN = 1024

# --------------------------------------------------------------------------
# Chroma leak cancellation (NTSC)
# --------------------------------------------------------------------------

#: The band the leak is fitted in (rising and falling raised-cosine edges,
#: Hz: the chroma, 3.58 MHz +- 0.6), the lags of its fit (`LEAK_TAPS` lags
#: `LEAK_STEP` samples apart, centred), and the fit's sample stride.
LEAK_BAND_HZ = ((2.9e6, 3.1e6), (4.1e6, 4.3e6))
LEAK_TAPS = 13
LEAK_STEP = 2
LEAK_FIT_STRIDE = 7

#: A chunk is corrected only where the leak explains at least this share of
#: the RF's chroma band (a disc or a stretch with no leak is left untouched).
LEAK_MIN_SHARE = 0.05

#: FFT length of the band filter (overlap-save blocks: enough of them to
#: share out over the cores).
LEAK_FFT_LEN = 1 << 15

#: Fit samples per parallel span of the normal equations.
LEAK_FIT_SPAN = 1 << 12

# --------------------------------------------------------------------------
# Crystal lines
# --------------------------------------------------------------------------

#: A player's EFM decoder crystal (384 x 44.1 kHz) and the divisor its lines
#: in the RF are multiples of (its 192nd, 88.2 kHz).
EFM_XTAL_HZ = 16.9344e6
XTAL_DIV = 192.0

#: The crystal is looked for within this fraction of `EFM_XTAL_HZ`.
XTAL_SEARCH = 2e-3

#: Detection spectrum: FFT length, stretches of the capture (spread over it;
#: a steady line is in all), and the span around a bin its floor is the
#: median of (Hz).
XTAL_FFT = 1 << 21
XTAL_SEGMENTS = 4
XTAL_FLOOR_HZ = 20e3

#: Power over the floor for the crystal itself to count as found, and for a
#: multiple to be subtracted (10 dB both: a power ratio of ten).
XTAL_FIND = 10.0
XTAL_KEEP = 10.0

#: Lines above this are left: nothing the decoder reads reaches that high
#: (its video band ends at 13.8 MHz); nor below `XTAL_LOW_HZ`.
XTAL_TOP_HZ = 14.5e6
#: The LD-V4300D's digital-audio master clock is the crystal's 96th multiple
#: (192 x 44.1 kHz = 8.4672 MHz), modulated: its satellites sit 88.2 and
#: 176.4 kHz either side, the 94th to the 98th multiples but the 96th (rev 8
#: observed the 95th, 97th and 98th on PAL; the GGV1069 capture read on a
#: V4300D, NTSC, carries the 94th and 95th at 9.6 and 5.3 times the floor,
#: against 2.1 and 2.6 on another player).  They stand below XTAL_KEEP.
#: Where the master clock is found, they are kept from XTAL_SATELLITE_KEEP
#: (rev 8's V4300D_SAT_MIN_MED), unless they are a still picture's comb.
#: The reference keeps none of them.
V4300D_MASTER_MULTIPLE = 96
V4300D_SATELLITE_MULTIPLES = (94, 95, 97, 98)
XTAL_SATELLITE_KEEP = 3.0
XTAL_LOW_HZ = 0.3e6

#: Where the disc's own signal makes steady lines, left out of the other
#: lines (Hz, NTSC then PAL): the analog audio carriers (a pure tone in
#: silence), the chroma leak's band, and the video carrier's swing (its
#: blanking and sync levels repeat line after line).
LINE_EXCLUDE_HZ = ((2.1e6, 2.5e6), (2.6e6, 3.0e6), (3.2e6, 4.0e6), (7.3e6, 9.6e6))
PAL_LINE_EXCLUDE_HZ = ((0.48e6, 0.88e6), (0.86e6, 1.27e6), (4.0e6, 4.9e6), (6.4e6, 8.3e6))

#: The line frequency of the picture (Hz, NTSC then PAL): a still picture's
#: RF is a comb of lines this far apart, which must not be taken for a
#: clock line.
NTSC_LINE_HZ = 15734.264
PAL_LINE_HZ = 15625.0

#: Samples a line's amplitude and phase are measured over, and the
#: super-blocks the crystal's drift is followed on (aligned on the capture,
#: so every read of a sample cleans it alike); super-blocks kept measured.
XTAL_BLOCK = 1 << 16
XTAL_SUPER = 1 << 22
XTAL_CACHE = 16

#: Samples between the exact seeds of a line's phasor in `clean`.
XTAL_SEED = 1024

#: Bins between the samples the spectrum's floor is taken at.
_FLOOR_STEP = 128

#: Neighbouring bins a line must be a local maximum over to be a line.
_XTAL_PEAK_HALFWIDTH = 3


# --------------------------------------------------------------------------
# Small shared helpers
# --------------------------------------------------------------------------


def _raised_cosine(f: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """A raised-cosine edge: 0 at and below `lo`, 1 at and above `hi` (Hz)."""
    f = np.asarray(f, dtype=np.float64)
    if hi <= lo:
        return (f >= hi).astype(np.float64)
    g = np.zeros(f.shape, dtype=np.float64)
    mid = (f > lo) & (f < hi)
    g[f >= hi] = 1.0
    g[mid] = 0.5 - 0.5 * np.cos(math.pi * (f[mid] - lo) / (hi - lo))
    return g


def _boxcar(x: np.ndarray, length: int) -> np.ndarray:
    """A centred moving average of `x` over `length` samples.

    The window runs from `i - length // 2` to `i - length // 2 + length`,
    clipped to the array at both ends (the start is zero-padded, the end
    truncated), and the sum is divided by `length`.
    """
    m = x.shape[0]
    if m == 0:
        return x.copy()
    c = np.concatenate((np.zeros(1, dtype=x.dtype), np.cumsum(x)))
    idx = np.arange(m)
    lo = np.maximum(0, idx - length // 2)
    hi = np.minimum(lo + length, m)
    return (c[hi] - c[lo]) / length


def _solve_linear(a: np.ndarray, b: np.ndarray) -> Optional[np.ndarray]:
    """Solve `a x = b` by Gaussian elimination with partial pivoting.

    Returns None when the matrix is singular (the Rust's `solve_n`).
    """
    a = np.array(a, dtype=np.float64, copy=True)
    b = np.array(b, dtype=np.float64, copy=True)
    n = b.shape[0]
    for c in range(n):
        # The reference keeps the last of the equal maxima.
        column = np.abs(a[c:, c])
        p = c + int(len(column) - 1 - np.argmax(column[::-1]))
        if not np.isfinite(a[p, c]) or abs(a[p, c]) < 1e-300:
            return None
        if p != c:
            a[[c, p]] = a[[p, c]]
            b[[c, p]] = b[[p, c]]
        for r in range(c + 1, n):
            f = a[r, c] / a[c, c]
            a[r, c:] -= f * a[c, c:]
            b[r] -= f * b[c]
    x = np.zeros(n, dtype=np.float64)
    for c in range(n - 1, -1, -1):
        x[c] = (b[c] - a[c, c + 1 :] @ x[c + 1 :]) / a[c, c]
    return x


def _instant_frequency(video_band: np.ndarray, fs: float) -> np.ndarray:
    """The video band's instantaneous frequency in Hz, one value per sample.

    Sample 0 reads zero: the phase advance needs the previous sample.
    """
    out = np.zeros(video_band.shape[0], dtype=np.float64)
    prod = video_band[1:] * np.conj(video_band[:-1])
    out[1:] = np.angle(prod) * fs / TAU
    return out


def _edge_taper(t: np.ndarray, n: int, taper: int) -> np.ndarray:
    """The raised-cosine fade at a chunk's edges (1 in the middle)."""
    if taper <= 0:
        return np.ones(t.shape, dtype=np.float64)
    e = np.minimum(t, n - 1 - t)
    g = np.ones(t.shape, dtype=np.float64)
    edge = e < taper
    g[edge] = 0.5 - 0.5 * np.cos(math.pi * e[edge] / taper)
    return g


# --------------------------------------------------------------------------
# Audio crosstalk cancellation
# --------------------------------------------------------------------------


def _carrier_narrow_band(
    out: np.ndarray, w: float, dec: int, boxl: int, box_span: int
) -> np.ndarray:
    """A carrier mixed down to 0 Hz, kept every `dec` samples.

    `w` is the carrier's frequency as a negative phase step (-2 pi f / fs),
    so the mixing down is by `exp(+j w t)`.  The narrow band is a boxcar of
    `boxl` full-rate samples taken from running sums over spans of
    `box_span` kept samples, so the memory used does not grow with the
    chunk's length.
    """
    n = out.shape[0]
    nd = -(-n // dec)
    first = np.zeros(nd, dtype=np.complex128)
    for k0 in range(0, nd, box_span):
        k1 = min(k0 + box_span, nd)
        lo0 = max(0, k0 * dec - boxl // 2)
        hi1 = min(max(0, (k1 - 1) * dec - boxl // 2) + boxl, n)
        if hi1 <= lo0:
            continue
        t = np.arange(lo0, hi1)
        sums = np.concatenate(
            (np.zeros(1, dtype=np.complex128), np.cumsum(out[lo0:hi1] * np.exp(1j * w * t)))
        )
        lo = np.maximum(0, np.arange(k0, k1) * dec - boxl // 2)
        hi = np.minimum(lo + boxl, n)
        first[k0:k1] = (sums[hi - lo0] - sums[lo - lo0]) / boxl
    return first


def _carrier_interp(narrow: np.ndarray, dec: int, t: np.ndarray) -> np.ndarray:
    """The carrier's narrow band at the positions `t`, read back by linear
    interpolation between the kept samples."""
    k = t // dec
    a = (t % dec) / dec
    k1 = np.minimum(k + 1, narrow.shape[0] - 1)
    return np.where(k + 1 < narrow.shape[0], narrow[k] * (1.0 - a) + narrow[k1] * a, narrow[k])


def _crosstalk_correction_reference(
    t: np.ndarray,
    narrow: Sequence[np.ndarray],
    ws: Sequence[float],
    gains: np.ndarray,
    carriers: Sequence[float],
    dec: int,
    n: int,
    taper: int,
    band: np.ndarray,
) -> np.ndarray:
    """The crosstalk correction at the positions ``t``: the vectorised
    reference the compiled kernel is checked against."""
    theta = np.zeros(t.shape, dtype=np.float64)
    for c in range(2):
        car = 2.0 * _carrier_interp(narrow[c], dec, t) * np.exp(-1j * ws[c] * t)
        theta += np.real(gains[c] * car / (1j * carriers[c]))
    theta *= _edge_taper(t, n, taper)
    small = np.abs(theta) < 0.05
    th2 = theta * theta
    # The turn is a few hundredths of a radian: its series, to the last bit
    # that matters.
    sn = np.where(small, theta * (1.0 - th2 / 6.0), np.sin(theta))
    cm1 = np.where(small, th2 * (th2 / 24.0 - 0.5), np.cos(theta) - 1.0)
    v = band[t]
    return v.real * cm1 + v.imag * sn


def _crosstalk_narrow(
    rf: np.ndarray, fs: float, carriers: Sequence[float]
) -> tuple[list, list]:
    """Each carrier mixed down to 0 Hz and through the three cascaded
    boxcars (the first in the compiled kernel, as _carrier_narrow_band takes
    it), kept every `XTALK_DEC` samples; and the carriers' phase steps."""
    n = rf.shape[0]
    dec = XTALK_DEC
    boxl = max(int(round(XTALK_BOX_S * fs)), 1)
    box_d = max(int(round(boxl / dec)), 1)
    ws = [-TAU * f / fs for f in carriers]
    narrow = []
    rf64 = np.ascontiguousarray(rf, dtype=np.float64)
    for w in ws:
        first = np.empty(-(-n // dec), dtype=np.complex128)
        narrow_band_kernel(rf64, w, dec, boxl, XTALK_BOX_SPAN, first)
        narrow.append(_boxcar(_boxcar(first, box_d), box_d))
    return narrow, ws


def _carrier_at(narrow: np.ndarray, w: float, t: np.ndarray) -> np.ndarray:
    """The carrier at its own frequency again, at the positions `t`: the
    narrow band mixed back up, with the factor two that makes it the
    analytic signal."""
    return 2.0 * _carrier_interp(narrow, XTALK_DEC, t) * np.exp(-1j * w * t)


def _crosstalk_gains(
    narrow: Sequence[np.ndarray],
    ws: Sequence[float],
    idx: np.ndarray,
    y: np.ndarray,
    lag: float,
) -> Optional[np.ndarray]:
    """The complex gain of each carrier on the video band's instantaneous
    frequency `y` (Hz, at the samples `idx`): least squares on the carriers'
    real and imaginary parts, means removed.  None when it is singular.

    `y` is a phase difference over the `lag` samples before each `idx`, so
    it is the frequency half of `lag` earlier: each gain is turned back by
    that half, or the phase it gives would lead the crosstalk's by
    `pi f lag / fs` (a tenth of a radian and more at 2.3 MHz, and a fifth
    or a third of the crosstalk left behind).
    """
    cols = np.empty((idx.size, 2 * len(ws)), dtype=np.float64)
    for c in range(len(ws)):
        car = _carrier_at(narrow[c], ws[c], idx)
        cols[:, 2 * c] = car.real
        cols[:, 2 * c + 1] = car.imag
    centred = cols - cols.mean(axis=0)
    k = _solve_linear(centred.T @ centred, centred.T @ (y - y.mean()))
    if k is None:
        return None
    return np.array([
        complex(k[2 * c], -k[2 * c + 1]) * np.exp(-0.5j * ws[c] * lag)
        for c in range(len(ws))
    ])


def crosstalk_block_gains(
    rf: np.ndarray,
    video_band: np.ndarray,
    step: int,
    fs: float,
    carriers: Sequence[float],
    fit: tuple[int, int],
) -> Optional[np.ndarray]:
    """The audio carriers' coupling into the video carrier's phase, as one
    decoder block measures it: `cancel_crosstalk`'s fit, for a caller that
    holds the analytic video band itself.

    One block (13 lines at 40 MHz) is far too short for it on its own: the
    picture's own detail at the carriers' frequencies correlates with them
    by chance, block to block, several times more than the coupling itself
    (white from one block to the next, around a coupling that holds over
    the capture).  The decoder takes the median of a few hundred blocks'
    (`crosstalk_coupling`) and applies that to every block.

    Parameters:
        rf: the RF block (real), length N, at `fs`.
        video_band: the block's analytic video band at the RF samples
            `0, step, 2 step, ...` (the decoder's half-rate band: step 2).
        step: RF samples between two samples of `video_band`.
        fs: the RF's sample rate in Hz.
        carriers: the analog audio carriers in Hz.
        fit: `(lo, hi)`, the RF samples the gains are fitted over (the
            block's kept span, clear of the boxcars' edges).

    Returns:
        One complex gain per carrier, or None where nothing can be fitted.
    """
    n = rf.shape[0]
    m = video_band.shape[0]
    lo = max(fit[0], step)
    lo = -(-lo // step) * step
    hi = min(fit[1], (m - 1) * step + 1)
    stride = max(XTALK_FIT_STRIDE // step, 1) * step
    idx = np.arange(lo, hi, stride)
    if n == 0 or idx.size < 8:
        return None
    narrow, ws = _crosstalk_narrow(rf, fs, carriers)
    j = idx // step
    # In [0, fs / step), as the decoder's discriminator (unwrap_hilbert)
    # reads it: at half rate the band's Nyquist is 10 MHz at 40 MHz, and an
    # NTSC white peak reaches it.  Read in (-fs / 2 step, fs / 2 step] those
    # peaks would wrap to -10 MHz, steps of 20 MHz that the demodulated
    # picture does not have and that the fit would follow.
    y = np.mod(np.angle(video_band[j] * np.conj(video_band[j - 1])), TAU) * fs / (TAU * step)
    return _crosstalk_gains(narrow, ws, idx, y, step)


def crosstalk_coupling(block_gains: Sequence[np.ndarray]) -> Optional[np.ndarray]:
    """The coupling of a stretch of blocks, from each block's own fit.

    The median of the blocks' gains, each carrier's real and imaginary
    parts apart (a block whose picture happens to follow a carrier closely
    is left out, where a mean would take it in), shrunk towards zero by how
    far it stands above its own standard error: by
    `max(0, 1 - (XTALK_COUPLING_Z * se / |g|) ** 2)`, per carrier.  A disc
    whose crosstalk is real keeps nearly all of it (the GGV1069 cut: 12 and
    24 standard errors, kept at 0.94 and 0.98); one where the blocks' gains
    point every way (a test pattern's detail near the carriers, which a
    carrier at 146.25 times the line frequency sits among) is left alone,
    where applying that median would add a line instead of taking one out.
    None without any block."""
    g = [x for x in block_gains if x is not None and np.all(np.isfinite(x))]
    if not g:
        return None
    g = np.asarray(g)
    med = np.median(g.real, axis=0) + 1j * np.median(g.imag, axis=0)

    def mad(v):
        return 1.4826 * np.median(np.abs(v - np.median(v, axis=0)), axis=0)

    # The median's standard error: sqrt(pi / 2) times the mean's.
    se = math.sqrt(math.pi / 2.0) * np.hypot(mad(g.real), mad(g.imag)) / math.sqrt(g.shape[0])
    mag2 = np.abs(med) ** 2
    with np.errstate(divide="ignore", invalid="ignore"):
        keep = np.where(mag2 > 0, 1.0 - (XTALK_COUPLING_Z * se) ** 2 / mag2, 0.0)
    return med * np.clip(keep, 0.0, 1.0)


def crosstalk_phase(
    rf: np.ndarray,
    m: int,
    step: int,
    fs: float,
    carriers: Sequence[float],
    gains: Sequence[complex],
) -> np.ndarray:
    """The audio carriers' crosstalk in the video carrier's phase, over a
    decoder block, for the coupling `gains` (`crosstalk_coupling`).

    The decoder's resample path demodulates its own analytic video band, so
    rather than correcting the RF and filtering it again, it turns that band
    back by the phase returned here, `band * exp(-1j * theta)`, before its
    discriminator: `cancel_crosstalk`'s correction, applied where the band
    is.  Only the carriers' own waveform comes from the block: nothing the
    picture does there moves the correction.

    Returns theta (radians, float64) at the RF samples `0, step, ...`, `m`
    of them.
    """
    narrow, ws = _crosstalk_narrow(rf, fs, carriers)
    t = np.arange(m) * step
    theta = np.zeros(m, dtype=np.float64)
    for c in range(len(ws)):
        theta += np.real(gains[c] * _carrier_at(narrow[c], ws[c], t) / (1j * carriers[c]))
    return theta


def cancel_crosstalk(
    out: np.ndarray,
    video_band: np.ndarray,
    fs: float,
    carriers: tuple[float, float],
    keep_band: tuple[float, float],
) -> np.ndarray:
    """Remove the analog audio carriers' crosstalk from the video.

    The carriers leak into the video carrier's phase on the disc.  Each
    carrier is taken out of the RF itself (mixed down, three boxcars, mixed
    back up), and the video band's instantaneous frequency is fitted on both
    by least squares (the picture does not follow the carriers): one complex
    gain each.  That frequency error is a phase error
    `theta = Re(C r / (j f))`, and the video band is turned back by it:
    `out + Re(v (exp(-j theta) - 1))`, kept above `keep_band` so the low band
    (audio, EFM) is left as it is.  Only this chunk's samples are used, so
    the same correction is made wherever it is computed.

    Parameters:
        out: the RF chunk (real, float32 or float64), length N.
        video_band: the analytic video band of the SAME chunk (complex,
            length N).
        fs: the sample rate in Hz.
        carriers: the two audio carrier frequencies in Hz.
        keep_band: `(lo_hz, hi_hz)`; the correction is kept only above this
            band.

    Returns:
        A NEW array (a copy of `out`, same dtype) with the correction
        applied.  Neither input is modified.
    """
    rf = np.asarray(out)
    band = np.asarray(video_band)
    n = rf.shape[0]
    result = np.array(rf, copy=True)
    if n == 0 or band.shape[0] < n:
        return result

    taper = int(round(XTALK_TAPER_S * fs))
    if n < 4 * taper:
        return result

    dec = XTALK_DEC
    narrow, ws = _crosstalk_narrow(rf, fs, carriers)

    # Least squares of the video band's instantaneous frequency on the
    # carriers' real and imaginary parts, means removed.
    idx = np.arange(taper, n - taper, XTALK_FIT_STRIDE)
    # Only at the fit's samples (idx starts past the taper, so idx - 1 >= 0).
    y = np.angle(band[idx] * np.conj(band[idx - 1])) * fs / TAU
    gains = _crosstalk_gains(narrow, ws, idx, y, 1)
    if gains is None:
        return result

    # The correction at every sample, in the compiled kernel (the same as
    # _crosstalk_correction_reference).
    corr = np.empty(n, dtype=np.float64)
    crosstalk_correction_kernel(
        narrow[0],
        narrow[1],
        np.asarray(ws, dtype=np.float64),
        gains,
        np.asarray(carriers, dtype=np.float64),
        dec,
        taper,
        np.ascontiguousarray(band[:n], dtype=np.complex128),
        corr,
    )

    # Only the part of the correction in the video band (`keep_band`, a
    # raised-cosine edge) is kept: below, turning the video band also moves
    # what lands on the audio carriers and the EFM, which the video never
    # reads.  Overlap-save, by FFT.
    size = XTALK_FFT_LEN
    ov = min(max(int(round(XTALK_OV_S * fs)), 1), size // 4)
    step = size - 2 * ov
    half = np.arange(size // 2 + 1) * fs / size
    gain = _raised_cosine(half, keep_band[0], keep_band[1])

    for pair in range((n + 2 * step - 1) // (2 * step)):
        s0 = 2 * pair * step - ov
        for which in range(2):
            start = s0 + which * step
            block = np.zeros(size, dtype=np.float64)
            lo = max(0, start)
            hi = min(n, start + size)
            if hi > lo:
                block[lo - start : hi - start] = corr[lo:hi]
            spec = scipy.fft.rfft(block) * gain
            filtered = scipy.fft.irfft(spec, size)
            out_lo = 2 * pair * step + which * step
            cnt = min(step, n - out_lo)
            if cnt > 0:
                result[out_lo : out_lo + cnt] += filtered[ov : ov + cnt]
    return result


# --------------------------------------------------------------------------
# Chroma leak cancellation
# --------------------------------------------------------------------------


def _leak_bands(
    video_band: np.ndarray,
    x: np.ndarray,
    fs: float,
    rise: tuple[float, float],
    fall: tuple[float, float],
) -> tuple[np.ndarray, np.ndarray]:
    """The two signals through a band of raised-cosine edges.

    Returns the video band's instantaneous frequency (Hz) and the RF, both
    through the band (rising edge `rise`, falling edge `fall`), by
    overlap-save FFT blocks.  One complex FFT carries the pair, the
    frequency as its real part and the RF as its imaginary part, the band's
    gain being real and even.
    """
    n = x.shape[0]
    size = LEAK_FFT_LEN
    ov = min(max(int(round(XTALK_OV_S * fs)), 1), size // 4)
    step = size - 2 * ov
    # The gain is real and even, so it is the same for both halves of the
    # spectrum: the bin's frequency is its distance from DC.
    bins = np.arange(size)
    freq = np.minimum(bins, size - bins) * fs / size
    gain = _raised_cosine(freq, rise[0], rise[1]) * (1.0 - _raised_cosine(freq, fall[0], fall[1]))

    inst = _instant_frequency(video_band, fs)
    oc = np.zeros(n, dtype=np.float32)
    orr = np.zeros(n, dtype=np.float32)
    for blk in range((n + step - 1) // step):
        s0 = blk * step
        t = np.arange(s0 - ov, s0 - ov + size)
        inside = (t >= 0) & (t < n)
        tc = np.clip(t, 0, max(n - 1, 0))
        re = np.where(inside & (t >= 1), inst[tc], 0.0)
        im = np.where(inside, x[tc], 0.0)
        buf = re + 1j * im
        spec = scipy.fft.fft(buf) * gain
        y = scipy.fft.ifft(spec)
        cnt = min(step, n - s0)
        oc[s0 : s0 + cnt] = y[ov : ov + cnt].real
        orr[s0 : s0 + cnt] = y[ov : ov + cnt].imag
    return oc, orr


def _subtract_leak(out: np.ndarray, leak: np.ndarray) -> None:
    """The leak is taken out of the RF in place, in double precision.

    The difference is computed in double precision and rounded once, as the
    reference does: rounding the leak first would round it twice.
    """
    out[...] = (out.astype(np.float64) - leak).astype(out.dtype)


def cancel_chroma_leak(
    out: np.ndarray,
    video_band: np.ndarray,
    fs: float,
    band: tuple[tuple[float, float], tuple[float, float]],
) -> np.ndarray:
    """Remove the composite chroma that leaks into the RF baseband (NTSC).

    The chroma beats with the video carrier (carrier minus 3.58 MHz) and
    makes the fine wavering vertical stripes of saturated areas.  The chroma
    is the demodulated video band's instantaneous frequency through the
    band; the RF's same band is fitted on it, shifted by `LEAK_TAPS` lags
    `LEAK_STEP` apart (least squares, every `LEAK_FIT_STRIDE`-th sample:
    the picture's own RF there does not follow it), and the fit subtracted,
    fading in and out at the chunk's edges.  Only this chunk's samples are
    used, so the same correction is made wherever it is computed.

    Parameters:
        out: the RF chunk (real, float32 or float64), length N.
        video_band: the analytic video band of the SAME chunk (complex,
            length N).
        fs: the sample rate in Hz.
        band: `((rise_lo, rise_hi), (fall_lo, fall_hi))`, the pass band's
            edges in Hz.

    Returns:
        A NEW array (a copy of `out`, same dtype) with the leak taken out.
        When the leak explains less than `LEAK_MIN_SHARE` of the RF's
        chroma band, the chunk is returned byte for byte as it was.
        Neither input is modified.
    """
    rf = np.asarray(out)
    v = np.asarray(video_band)
    n = rf.shape[0]
    result = np.array(rf, copy=True)
    if n == 0 or v.shape[0] < n:
        return result

    taper = int(round(XTALK_TAPER_S * fs))
    half = LEAK_TAPS // 2 * LEAK_STEP
    if n < 4 * taper + 2 * half:
        return result

    c, r = _leak_bands(v, rf, fs, band[0], band[1])
    lags = np.arange(LEAK_TAPS) * LEAK_STEP - half

    # The normal equations, summed over fixed spans and the spans added in
    # order: the same sums whatever the thread count.  Only the upper
    # triangle is accumulated, and the matrix is symmetrised afterwards, as
    # the reference does.
    fit = np.arange(taper + half, n - taper - half, LEAK_FIT_STRIDE)
    if fit.size < LEAK_TAPS:
        return result
    ata = np.zeros((LEAK_TAPS, LEAK_TAPS), dtype=np.float64)
    aty = np.zeros(LEAK_TAPS, dtype=np.float64)
    yy = 0.0
    for a in range(0, fit.size, LEAK_FIT_SPAN):
        ts = fit[a : a + LEAK_FIT_SPAN]
        rows = c[ts[:, None] + lags[None, :]].astype(np.float64)
        target = r[ts].astype(np.float64)
        upper = np.triu(rows.T @ rows)
        ata += upper
        aty += rows.T @ target
        yy += float(target @ target)
    ata = ata + np.triu(ata, 1).T

    h = _solve_linear(ata, aty)
    if h is None:
        return result

    # Share of the RF's chroma band the leak explains: below LEAK_MIN_SHARE
    # there is no leak to speak of, and the chunk is left as it is.
    share = float(h @ aty) / max(yy, 1e-300)
    if not (share >= LEAK_MIN_SHARE):
        return result

    # The predicted leak, taken out of the RF, faded in and out at the edges.
    # The subtraction is done in double precision and rounded once, as the
    # reference does.
    span = 1 << 14
    for a in range(half, n - half, span):
        b = min(a + span, n - half)
        t = np.arange(a, b)
        leak = c[t[:, None] + lags[None, :]].astype(np.float64) @ h
        leak *= _edge_taper(t, n, taper)
        _subtract_leak(result[a:b], leak)
    return result


# --------------------------------------------------------------------------
# Crystal lines
# --------------------------------------------------------------------------


def _capture_length(read_fn: Callable[[int, int], np.ndarray]) -> int:
    """The capture's length in samples, found by probing `read_fn`.

    `read_fn(start, count)` must return up to `count` samples, fewer only
    at the end of the capture; a read past the end may also raise.  The
    length is found with a doubling probe and a binary search, so no more
    than a handful of samples are read.
    """
    try:
        first = read_fn(0, 1)
    except Exception:  # pragma: no cover - an unreadable capture
        return 0
    if len(first) == 0:
        return 0

    def present(at: int) -> bool:
        try:
            return len(read_fn(at, 1)) > 0
        except Exception:
            return False

    hi = 1
    while present(hi):
        hi *= 2
        if hi > 1 << 40:
            break
    lo = 0
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if present(mid):
            lo = mid
        else:
            hi = mid
    return lo + 1


def _spectrum_floor(p: np.ndarray, h: int, step: int) -> np.ndarray:
    """The median of the spectrum within `h` bins, taken every `step` bins."""
    m = p.shape[0]
    n_out = (m + step - 1) // step
    out = np.zeros(n_out, dtype=np.float64)
    if m == 0:
        return out
    width = 2 * h
    if width <= m:
        wins = np.lib.stride_tricks.sliding_window_view(p, width)
        for a in range(0, n_out, 64):
            idx = np.arange(a, min(a + 64, n_out))
            start = idx * step - h
            ok = (start >= 0) & (start + width <= m)
            if np.any(ok):
                out[idx[ok]] = np.partition(wins[start[ok]], h, axis=1)[:, h]
            for j in idx[~ok]:
                lo = max(0, j * step - h)
                hi = min(j * step + h, m)
                w = np.sort(p[lo:hi])
                out[j] = w[w.shape[0] // 2]
    else:
        for j in range(n_out):
            lo = max(0, j * step - h)
            hi = min(j * step + h, m)
            w = np.sort(p[lo:hi])
            out[j] = w[w.shape[0] // 2]
    return out


def _floor_lookup(floor_sum: np.ndarray, m: int, step: int) -> np.ndarray:
    """The floor of every bin, from the medians taken every `step` bins."""
    if floor_sum.shape[0] == 0:
        return np.zeros(m, dtype=np.float64)
    idx = np.minimum(np.arange(m) // step, floor_sum.shape[0] - 1)
    return floor_sum[idx]


def _parabolic_offset(p: np.ndarray, k: int) -> float:
    """The offset of a spectral peak's bin from its parabolic vertex."""
    if k + 1 >= p.shape[0]:
        return 0.0
    with np.errstate(divide="ignore", invalid="ignore"):
        # The reference reads the bin before the peak, or the peak itself
        # when it is the first one.
        lg = np.log(p[[max(k - 1, 0), k, k + 1]])
        d = lg[0] - 2.0 * lg[1] + lg[2]
        off = 0.5 * (lg[0] - lg[2]) / d
    if not np.isfinite(d) or d >= 0.0:
        return 0.0
    return float(off)


def _peak(p: np.ndarray, b: int, w: int) -> tuple[int, float]:
    """The highest bin within `w` bins of `b`, with its parabolic offset."""
    lo = max(0, b - w)
    hi = min(b + w, p.shape[0] - 2)
    if hi < lo:
        return b, 0.0
    # The reference keeps the last of the equal maxima.
    window = p[lo : hi + 1]
    k = lo + int(len(window) - 1 - np.argmax(window[::-1]))
    return k, _parabolic_offset(p, k)


class _CrystalBlock:
    """The lines over one super-block of the capture.

    `XTAL_SUPER` samples from `k * XTAL_SUPER`: the EFM crystal's frequency
    there, and every line's complex amplitude on each `XTAL_BLOCK` within
    it (the EFM lines first, then the others).  The amplitudes are phasors
    referenced to the super-block's first sample.
    """

    __slots__ = ("f0", "amps")

    def __init__(self, f0: float, amps: list[np.ndarray]) -> None:
        self.f0 = f0
        self.amps = amps


class CrystalLines:
    """The narrow clock lines a capture carries, and their subtraction.

    Two kinds: the player's EFM decoder crystal (found near
    `EFM_XTAL_HZ`), whose lines are the multiples of its 192nd
    (`XTAL_DIV`, 88.2 kHz) that stand out of the spectrum, its drift
    followed as it goes; and any other line that stands out at one
    frequency all through the capture (the player's 4fsc video clock, the
    capture board's clocks, and at a low sample rate what of them folds
    down), outside the bands where the disc's own signal makes steady
    lines.

    The class is not thread-safe: its measured-block cache is shared state.
    """

    def __init__(
        self,
        *,
        read_fn: Callable[[int, int], np.ndarray],
        fs: float,
        f0: float,
        ks: Sequence[int],
        reference: int,
        others: Sequence[float],
        length: int,
    ) -> None:
        self._read_fn = read_fn
        self.fs = float(fs)
        #: The EFM crystal's 192nd (Hz).
        self.f0 = float(f0)
        #: The multiples of the 192nd that are subtracted.
        self.ks = tuple(int(k) for k in ks)
        #: The strongest of them: the drift is followed on it.
        self.reference = int(reference)
        #: The other lines (Hz).
        self.others = tuple(float(f) for f in others)
        #: The capture's length in samples.
        self.length = int(length)
        self._cache: OrderedDict[int, _CrystalBlock] = OrderedDict()

    # -- properties -------------------------------------------------------

    @property
    def has_lines(self) -> bool:
        """Whether any line was found (and so `clean` has work to do)."""
        return bool(self.ks or self.others)

    @property
    def lines(self) -> tuple[float, ...]:
        """Every line's frequency (Hz): the EFM multiples then the others."""
        return tuple(m * self.f0 for m in self.ks) + tuple(self.others)

    # -- detection --------------------------------------------------------

    @classmethod
    def detect(
        cls,
        read_fn: Callable[[int, int], np.ndarray],
        fs: float,
        *,
        ntsc: bool,
        line_hz: float,
        length: Optional[int] = None,
        start: int = 0,
    ) -> "CrystalLines":
        """Find the lines in a capture.

        `XTAL_SEGMENTS` stretches spread over the capture are examined (a
        line has to be in every one, at the same frequency).  A line with
        another one a line period's frequency (`line_hz`) away is the
        picture's (a still picture's RF is a comb of them) and is left.

        Parameters:
            read_fn: `read_fn(start, count) -> np.ndarray` of RF samples;
                it must return up to `count` samples, fewer only at the end
                of the capture.
            fs: the sample rate in Hz.
            ntsc: True for NTSC (its excluded bands and line frequency),
                False for PAL.
            line_hz: the picture's line frequency (Hz).
            length: the capture's length in samples.  It is found by probing
                `read_fn` when it is not given, which needs a reader that
                reports the end of the capture by returning fewer samples
                than were asked for; a reader that pads with zeros past the
                end never reports it.
            start: where the stretches start, in samples.  It is the
                capture's first located line: the stretches are spread from
                there to the end of the capture, so the detection covers the
                part of the capture that carries a picture.

        Returns:
            A `CrystalLines` holding the lines found (possibly none: its
            `has_lines` is then False and `clean` leaves the samples
            alone).
        """
        n = XTAL_FFT
        segments = XTAL_SEGMENTS
        total = int(length) if length is not None else _capture_length(read_fn)
        start = max(0, int(start))
        room = max(0, total - start - n)
        exclude = LINE_EXCLUDE_HZ if ntsc else PAL_LINE_EXCLUDE_HZ

        # The detection spectrum: Hann-windowed FFTs over the stretches.
        win = 0.5 - 0.5 * np.cos(TAU * np.arange(n) / n)
        seg_powers = []
        for seg in range(segments):
            at = start + room * seg // max(1, segments - 1)
            raw = np.asarray(read_fn(at, n), dtype=np.float64)
            if raw.shape[0] < n:
                raw = np.concatenate((raw, np.zeros(n - raw.shape[0], dtype=np.float64)))
            x = (raw - raw.mean()) * win
            spec = scipy.fft.rfft(x)
            seg_powers.append(spec.real**2 + spec.imag**2)
        power = np.sum(seg_powers, axis=0)[: n // 2]
        bin_hz = fs / n
        h = max(1, int(XTAL_FLOOR_HZ / bin_hz))

        floor_sum = _spectrum_floor(power, h, _FLOOR_STEP)
        floor = _floor_lookup(floor_sum, power.shape[0], _FLOOR_STEP)
        top = min(XTAL_TOP_HZ, 0.49 * fs)

        # The EFM crystal and its multiples.
        f0 = EFM_XTAL_HZ / XTAL_DIV
        ks: list[int] = []
        best = (0.0, 0)
        lo = int(EFM_XTAL_HZ * (1.0 - XTAL_SEARCH) / bin_hz)
        hi = int(EFM_XTAL_HZ * (1.0 + XTAL_SEARCH) / bin_hz)
        if hi + 2 < power.shape[0]:
            k, off = _peak(power, (lo + hi) // 2, (hi - lo) // 2)
            if power[k] >= floor[k] * XTAL_FIND:
                f0 = (k + off) * bin_hz / XTAL_DIV
                for m in range(1, int(top / f0) + 1):
                    kk, _ = _peak(power, int(round(m * f0 / bin_hz)), _XTAL_PEAK_HALFWIDTH)
                    with np.errstate(divide="ignore", invalid="ignore"):
                        ratio = power[kk] / floor[kk]
                    if ratio >= XTAL_KEEP:
                        ks.append(m)
                        if ratio > best[0]:
                            best = (float(ratio), m)
                if V4300D_MASTER_MULTIPLE in ks:
                    for m in V4300D_SATELLITE_MULTIPLES:
                        if m in ks or m * f0 >= top:
                            continue
                        kk, off = _peak(power, int(round(m * f0 / bin_hz)), _XTAL_PEAK_HALFWIDTH)
                        with np.errstate(divide="ignore", invalid="ignore"):
                            ratio = power[kk] / floor[kk]
                        if ratio >= XTAL_SATELLITE_KEEP and not _is_comb(
                            power, floor, bin_hz, (kk + off) * bin_hz, line_hz
                        ):
                            ks.append(m)
                    ks.sort()

        # Every other line that stands out in each stretch, at one frequency.
        others: list[float] = []
        if power.shape[0] > 4 * _XTAL_PEAK_HALFWIDTH:
            tall = []
            for s, p in enumerate(seg_powers):
                p = p[: n // 2]
                seg_floor = _floor_lookup(
                    _spectrum_floor(p, h, _FLOOR_STEP), p.shape[0], _FLOOR_STEP
                )
                tall.append((p >= seg_floor * XTAL_KEEP) & _local_max_mask(p, _XTAL_PEAK_HALFWIDTH))
            near = [_dilate(t, 1) for t in tall]
            cand = tall[0]
            for s in range(1, segments):
                cand &= near[s]
            lo_bin = int(XTAL_LOW_HZ / bin_hz)
            hi_bin = min(int(top / bin_hz), power.shape[0] - 2)
            cand[:lo_bin] = False
            cand[hi_bin:] = False
            bins = np.flatnonzero(cand)
            if bins.size:
                # The peak of each candidate, and its frequency.
                wins = np.lib.stride_tricks.sliding_window_view(power, 3)
                k = bins - 1 + np.argmax(wins[bins - 1], axis=1)
                offs = np.array([_parabolic_offset(power, int(kk)) for kk in k])
                freqs = (k + offs) * bin_hz
                # A line with another one a line period's frequency away is
                # the picture's (a still picture's RF is a comb of them).
                for f in freqs:
                    if any(lo_a <= f <= hi_a for lo_a, hi_a in exclude):
                        continue
                    if any(abs(m * f0 - f) < 3.0 * bin_hz for m in ks):
                        continue
                    if _is_comb(power, floor, bin_hz, float(f), line_hz):
                        continue
                    if any(abs(g - f) < 3.0 * bin_hz for g in others):
                        continue
                    others.append(float(f))
        return cls(
            read_fn=read_fn,
            fs=fs,
            f0=f0,
            ks=ks,
            reference=best[1],
            others=others,
            length=total,
        )

    # -- measurement ------------------------------------------------------

    def _at(self, raw: np.ndarray, f: float, a: int) -> complex:
        """The phasor of a line's frequency over a block of the capture.

        The block starts at `a` (within `raw`, the super-block's samples).
        The phasor is referenced to the super-block's first sample.

        This is the reference of `_ats`, which measures the same phasors
        over all the blocks at once.
        """
        w = TAU * f / self.fs
        seg = raw[a : a + XTAL_BLOCK]
        m = seg.shape[0]
        if m == 0:
            return 0j
        acc = np.dot(seg, np.exp(-1j * w * np.arange(m)))
        return complex((2.0 / m) * acc * np.exp(-1j * w * a))

    def _ats(self, raw: np.ndarray, freqs: Sequence[float]) -> list[np.ndarray]:
        """Every line's phasor on every block of a super-block.

        The blocks are the rows of the super-block's samples, and the lines'
        tables of exponentials are applied to all of them at once, in a
        compiled kernel: one pass over the samples for all the lines, the
        blocks in parallel.

        Parameters
        ----------
        raw : numpy.ndarray
            The super-block's samples (float64).
        freqs : sequence of float
            The lines' frequencies, in Hz.

        Returns
        -------
        list of numpy.ndarray
            One complex128 array per line, one phasor per block.
        """
        block = XTAL_BLOCK
        nb = XTAL_SUPER // block
        freqs = list(freqs)
        if not freqs:
            return []
        w = TAU * np.asarray(freqs, dtype=np.float64) / self.fs
        tables = np.exp(-1j * w[:, None] * np.arange(block)[None, :])
        turns = np.exp(-1j * w[:, None] * (np.arange(nb, dtype=np.float64) * block)[None, :])
        out = np.empty((len(freqs), nb), dtype=np.complex128)
        line_phasors_kernel(
            np.ascontiguousarray(raw[: nb * block], dtype=np.float64), block, tables, turns, out
        )
        return list(out)

    def _ats_reference(self, raw: np.ndarray, freqs: Sequence[float]) -> list[np.ndarray]:
        """`_ats` as matrix products: the reference the kernel is checked
        against."""
        block = XTAL_BLOCK
        nb = XTAL_SUPER // block
        blocks = raw[: nb * block].reshape(nb, block)
        out = []
        for f in freqs:
            w = TAU * f / self.fs
            table = np.exp(-1j * w * np.arange(block))
            # The block's own turn, and the phasor's scale.
            turn = np.exp(-1j * w * (np.arange(nb, dtype=np.float64) * block))
            acc = blocks @ table.real + 1j * (blocks @ table.imag)
            out.append((2.0 / block) * acc * turn)
        return out

    def _measure(self, raw: np.ndarray) -> _CrystalBlock:
        """The lines over one super-block: the crystal's drift there from
        its reference line's phase advance from block to block, then every
        line's amplitude on every block."""
        block = XTAL_BLOCK
        nb = XTAL_SUPER // block
        f0 = self.f0
        if self.ks and nb > 1:
            fr = self.reference * self.f0
            phasors = np.array(self._ats(raw, [fr])[0], dtype=np.complex128)
            phases = np.angle(phasors)
            d = np.diff(phases)
            # The phase advance is folded into (-pi, pi], rounded half away
            # from zero, as the reference does.
            ratio = d / TAU
            d -= TAU * np.where(ratio >= 0.0, np.floor(ratio + 0.5), np.ceil(ratio - 0.5))
            adv = float(d.sum())
            df = adv / (nb - 1) / (TAU * block / self.fs)
            f0 = self.f0 * (1.0 + df / fr)
        freqs = [m * f0 for m in self.ks] + list(self.others)
        amps = list(np.array(a, dtype=np.complex128) for a in self._ats(raw, freqs))
        return _CrystalBlock(f0, amps)

    def _block(self, k: int) -> _CrystalBlock:
        """Super-block `k`, measured or from the cache."""
        cached = self._cache.get(k)
        if cached is not None:
            self._cache.move_to_end(k)
            return cached
        raw = np.asarray(self._read_fn(k * XTAL_SUPER, XTAL_SUPER), dtype=np.float64)
        if raw.shape[0] < XTAL_SUPER:
            raw = np.concatenate((raw, np.zeros(XTAL_SUPER - raw.shape[0], dtype=np.float64)))
        block = self._measure(raw)
        self._cache[k] = block
        if len(self._cache) > XTAL_CACHE:
            self._cache.popitem(last=False)
        return block

    # -- subtraction ------------------------------------------------------

    def clean(self, samples: np.ndarray, start: int) -> np.ndarray:
        """Subtract the clock lines from `samples`, which start at absolute
        sample `start`, on every core.

        The same subtraction as `clean_reference` (the vectorised reference
        it is checked against), piece by piece in a compiled kernel.

        Returns:
            A NEW float64 array with the lines subtracted.  The input is not
            modified.
        """
        result = np.array(samples, dtype=np.float64, copy=True)
        n = result.shape[0]
        if n == 0 or not self.has_lines:
            return result
        sb = XTAL_SUPER
        block = XTAL_BLOCK
        t = max(start, 0)
        end = min(start + n, self.length)
        while t < end:
            k = t // sb
            b0 = k * sb
            b1 = min((k + 1) * sb, end)
            blk = self._block(k)
            w = np.array(
                [TAU * m * blk.f0 / self.fs for m in self.ks]
                + [TAU * f / self.fs for f in self.others],
                dtype=np.float64,
            )
            tables = np.exp(1j * w[:, None] * np.arange(XTAL_SEED)[None, :])
            first = t - b0
            count = b1 - t
            head = min((XTAL_SEED - first % XTAL_SEED) % XTAL_SEED, count)
            starts = np.arange(first + head, first + count, XTAL_SEED, dtype=np.int64)
            counts = np.minimum(XTAL_SEED, first + count - starts)
            if head > 0:
                starts = np.concatenate((np.array([first], dtype=np.int64), starts))
                counts = np.concatenate((np.array([head], dtype=np.int64), counts))
            subtract_lines_kernel(
                result[t - start : b1 - start],
                first,
                starts,
                counts.astype(np.int64),
                block,
                np.ascontiguousarray(np.array(blk.amps, dtype=np.complex128)),
                w,
                tables,
            )
            t = b1
        return result

    def clean_reference(self, samples: np.ndarray, start: int) -> np.ndarray:
        """Subtract the clock lines from `samples`, which start at absolute
        sample `start`.

        Each line's complex amplitude is interpolated linearly between the
        two neighbouring block centres, and the phasor is made exact at
        every `XTAL_SEED`-th sample of the super-block, so a sample gets
        the same value whatever read it is in: the subtraction is
        reproducible across chunk boundaries.

        Parameters:
            samples: the RF samples (real), starting at absolute sample
                `start`.
            start: the absolute sample number `samples[0]` is at.

        Returns:
            A NEW array (a copy of `samples`, same dtype) with the lines
            subtracted.  The input is not modified.
        """
        raw = np.asarray(samples)
        result = np.array(raw, copy=True)
        n = raw.shape[0]
        if n == 0 or not self.has_lines:
            return result

        sb = XTAL_SUPER
        block = XTAL_BLOCK
        nb = sb // block
        t = max(start, 0)
        end = min(start + n, self.length)
        while t < end:
            k = t // sb
            b0 = k * sb
            b1 = min((k + 1) * sb, end)
            blk = self._block(k)
            w = [TAU * m * blk.f0 / self.fs for m in self.ks]
            w += [TAU * f / self.fs for f in self.others]
            # The phasor of a line over a seed: the same table for every
            # piece of the super-block, each piece turning it by its own
            # position.
            tables = [np.exp(1j * wl * np.arange(XTAL_SEED)) for wl in w]
            lo = t - start
            hi = b1 - start
            span = result[lo:hi]
            first = t - b0
            # Pieces aligned on every XTAL_SEED-th sample of the
            # super-block (the first one up to the next): each line's
            # phasor is exact at that sample and turned by one step from
            # there (a read that starts between turns up to it), so a
            # sample gets the same value whatever read it is in.  A piece
            # lies between two block centres, so every line's amplitude is
            # one straight segment over it.
            head = min((XTAL_SEED - first % XTAL_SEED) % XTAL_SEED, span.shape[0])
            bounds = [(first, head)]
            pos = first + head
            while pos < first + span.shape[0]:
                cnt = min(XTAL_SEED, first + span.shape[0] - pos)
                bounds.append((pos, cnt))
                pos += XTAL_SEED
            for a, cnt in bounds:
                if cnt <= 0:
                    continue
                at = a - a % XTAL_SEED
                u0 = (at + 0.5) / block - 0.5
                j = int(min(max(math.floor(u0), 0.0), nb - 1))
                pos = np.arange(a, a + cnt)
                s = np.clip((pos + 0.5) / block - 0.5 - j, 0.0, 1.0)
                piece = span[a - first : a - first + cnt].astype(np.float64)
                for idx, wl in enumerate(w):
                    amp = blk.amps[idx]
                    if j + 1 < nb:
                        g0 = amp[j]
                        dg = amp[j + 1] - amp[j]
                    else:
                        g0 = amp[j]
                        dg = 0j
                    phasor = np.exp(1j * wl * a) * tables[idx][:cnt]
                    piece -= np.real((g0 + dg * s) * phasor)
                span[a - first : a - first + cnt] = piece.astype(result.dtype, copy=False)
            t = b1
        return result


def _local_max_mask(p: np.ndarray, w: int) -> np.ndarray:
    """The bins where `p` is the maximum over itself and its `w` neighbours."""
    m = p.shape[0]
    out = np.zeros(m, dtype=bool)
    if m < 2 * w + 1:
        return out
    wins = np.lib.stride_tricks.sliding_window_view(p, 2 * w + 1)
    out[w : m - w] = wins.max(axis=1) <= wins[:, w]
    return out


def _dilate(mask: np.ndarray, w: int) -> np.ndarray:
    """The mask with its `w` neighbours on each side folded in."""
    out = mask.copy()
    for k in range(1, w + 1):
        out[k:] |= mask[:-k]
        out[:-k] |= mask[k:]
    return out


def _is_comb(power: np.ndarray, floor: np.ndarray, bin_hz: float, f: float, line_hz: float) -> bool:
    """Whether a line at `f` has another one a line period's frequency away.

    A still picture's RF is a comb of lines a line frequency apart, which
    must not be taken for a clock line.
    """
    for g in (f - line_hz, f + line_hz):
        b = int(round(g / bin_hz))
        if b < 1 or b + 1 >= power.shape[0]:
            continue
        k, _ = _peak(power, b, 2)
        if power[k] >= floor[k] * XTAL_KEEP:
            return True
    return False
