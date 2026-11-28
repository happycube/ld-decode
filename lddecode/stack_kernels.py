"""
stack_kernels - the stacked source's per-sample loops, compiled

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The two hot stages of :mod:`lddecode.stack`, as Numba kernels that run over
every core: reading each input at its own fractional positions (the
Kaiser-windowed sinc and the analytic video band, in one pass), combining
the inputs (the carrier measure, the phase lock, the alignment guard and
the weights), subtracting the clock lines from a capture as it is read, and
the audio crosstalk's narrow bands and correction.

Each output sample is computed on its own, from the same terms in the same
order whatever the number of threads, so a chunk comes out the same however
it is split.  The running sums behind the windowed measures are taken per
block of ``COMBINE_BLOCK`` samples, from the first sample the block's
windows reach: the blocks are fixed, so the sums do not depend on the
number of threads either.

The tuning constants are passed in (``params``, see :data:`PARAM_NAMES`), so
this module has no intra-package import and :mod:`lddecode.stack` keeps
their definitions and their reasons.
"""

from __future__ import annotations

import numpy as np
from numba import njit, prange

__all__ = [
    "PARAM_NAMES",
    "COMBINE_BLOCK",
    "read_input_kernel",
    "combine_primary",
    "combine_secondary",
    "subtract_lines_kernel",
    "narrow_band_kernel",
    "line_phasors_kernel",
    "crosstalk_phase_kernel",
    "turn_back_kernel",
]

#: The order of the constants in ``params``.
PARAM_NAMES = (
    "Q_MAX",
    "QN_LOCK",
    "QN_CARRIER",
    "LOCK_PRIOR",
    "KAPPA_LO",
    "KAPPA_SPAN",
    "Q_LO",
    "Q_SPAN",
    "Q_ROT",
    "H_LO",
    "H_SPAN",
)

_Q_MAX, _QN_LOCK, _QN_CARRIER, _LOCK_PRIOR = 0, 1, 2, 3
_KAPPA_LO, _KAPPA_SPAN, _Q_LO, _Q_SPAN, _Q_ROT, _H_LO, _H_SPAN = 4, 5, 6, 7, 8, 9, 10


@njit(cache=True, nogil=True, parallel=True)
def read_input_kernel(raw, start, seg, seg_t0, a0, slope, s0, sinc, hi_re, hi_im, full, band, covered):
    """Read one input at its own positions: the full signal and the video band.

    Parameters
    ----------
    raw : numpy.ndarray
        The input's samples (float64), ``raw[0]`` at absolute sample
        ``start``.
    start : int
        The absolute sample of ``raw[0]``.
    seg, seg_t0, a0, slope, s0
        The positions' law: output sample ``j`` is in segment ``seg[j]``
        (int64), and its absolute position is
        ``a0[k] + ((s0 + j) - seg_t0[k]) * slope[k]`` (float64), NaN where
        the input does not cover it.
    sinc, hi_re, hi_im : numpy.ndarray
        The sinc table and the video-band table's real and imaginary parts,
        one row per fractional phase (``phases + 1`` rows).
    full, band, covered : numpy.ndarray
        Written in place, one per output sample: the sinc read (float64), the
        analytic video band (complex128) and whether the input covers it.
        Uncovered samples read as zero.

    The fractional phase is rounded half away from zero, and a tap outside
    ``raw`` reads its first or last sample, as the reference does.
    """
    n = seg.shape[0]
    limit = raw.shape[0] - 1
    nphases = sinc.shape[0] - 1
    sinc_taps = sinc.shape[1]
    hi_taps = hi_re.shape[1]
    sinc_first = sinc_taps // 2 - 1
    hi_first = hi_taps // 2 - 1
    for i in prange(n):
        k = seg[i]
        p = a0[k] + ((s0 + i) - seg_t0[k]) * slope[k]
        if not np.isfinite(p) or limit < 0:
            full[i] = 0.0
            band[i] = 0.0
            covered[i] = False
            continue
        covered[i] = True
        k0 = np.floor(p)
        phase = int(np.floor((p - k0) * nphases + 0.5))
        if phase < 0:
            phase = 0
        elif phase > nphases:
            phase = nphases
        b = int(k0) - start
        s = 0.0
        for d in range(sinc_taps):
            idx = b + d - sinc_first
            if idx < 0:
                idx = 0
            elif idx > limit:
                idx = limit
            s += sinc[phase, d] * raw[idx]
        full[i] = s
        sr = 0.0
        si = 0.0
        for d in range(hi_taps):
            idx = b + d - hi_first
            if idx < 0:
                idx = 0
            elif idx > limit:
                idx = limit
            v = raw[idx]
            sr += hi_re[phase, d] * v
            si += hi_im[phase, d] * v
        band[i] = complex(sr, si)


#: Output samples per block of the combination: each block takes its own
#: running sums, from the first sample its windows reach, so the blocks run
#: in parallel and a sample's sums do not depend on how many threads ran.
COMBINE_BLOCK = 8192


@njit(cache=True, nogil=True, inline="always")
def _measure(rl, e, n, qn, q_max):
    """The carrier power and fraction (see ``stack.carrier_measure``)."""
    a = np.abs(rl)
    s = max(0.0, a - qn * e) / ((1.0 - qn) * n)
    q = 0.0
    if e > 0.0:
        q = min(q_max, max(0.0, a / e - qn) / (1.0 - qn))
    return s, q


@njit(cache=True, nogil=True, inline="always")
def _lag_sums(band, cov, lag, base, top, p_rl, p_e, p_c):
    """The running sums of the carrier terms over ``[base, top)``, from zero:
    per sample, the product with the sample one ``lag`` earlier, the energy
    and the count, where both samples are covered."""
    p_rl[0] = 0.0
    p_e[0] = 0.0
    p_c[0] = 0.0
    for t in range(base, top):
        rl = 0j
        e = 0.0
        c = 0.0
        if t >= lag and cov[t] and cov[t - lag]:
            rl = band[t] * np.conj(band[t - lag])
            e = np.abs(band[t]) ** 2
            c = 1.0
        u = t - base
        p_rl[u + 1] = p_rl[u] + rl
        p_e[u + 1] = p_e[u] + e
        p_c[u + 1] = p_c[u] + c


@njit(cache=True, nogil=True, parallel=True)
def combine_primary(
    full0, band0, cov0, lag, margin, nout, half, chalf,
    weight, afloor, fixed, params, acc, wsum, vacc, q0, h0,
):
    """The primary's share of the combination, block by block.

    Adds the primary's weighted samples to ``acc``, ``wsum`` and ``vacc``
    and writes its carrier fraction over the lock window (``q0``) and the
    share of its carrier it keeps at the sample (``h0``), which the
    secondaries' locks read.  ``half`` and ``chalf`` are the half widths of
    the lock window and of the carrier window (``chalf <= half``).
    """
    length = full0.shape[0]
    q_max = params[_Q_MAX]
    nblocks = (nout + COMBINE_BLOCK - 1) // COMBINE_BLOCK
    for blk in prange(nblocks):
        k0 = blk * COMBINE_BLOCK
        k1 = min(k0 + COMBINE_BLOCK, nout)
        base = max(margin + k0 - half, 0)
        top = min(margin + k1 - 1 + half, length)
        size = top - base + 1
        p_rl = np.empty(size, dtype=np.complex128)
        p_e = np.empty(size, dtype=np.float64)
        p_c = np.empty(size, dtype=np.float64)
        _lag_sums(band0, cov0, lag, base, top, p_rl, p_e, p_c)
        for k in range(k0, k1):
            j = margin + k
            lo = max(j - half, 0) - base
            hi = min(j + half, length) - base
            rl_l = p_rl[hi] - p_rl[lo]
            e_l = p_e[hi] - p_e[lo]
            c_l = p_c[hi] - p_c[lo]
            lo2 = max(j - chalf, 0) - base
            hi2 = min(j + chalf, length) - base
            cs = p_c[hi2] - p_c[lo2]
            has_lock = c_l > 0.0
            s_lock, q_lock = _measure(
                rl_l, e_l, c_l if has_lock else 1.0, params[_QN_LOCK], q_max
            )
            q0[k] = q_lock if has_lock else 0.0
            s0 = 0.0
            if cs > 0.0:
                s0, _ = _measure(
                    p_rl[hi2] - p_rl[lo2], p_e[hi2] - p_e[lo2], cs, params[_QN_CARRIER], q_max
                )
            h = 0.0
            if has_lock and s_lock > 0.0:
                h = s0 / s_lock
            h0[k] = h
            if fixed:
                w = weight
            else:
                w = max(np.sqrt(max(s0, 0.0)), afloor) * weight
            if cov0[j]:
                acc[k] += full0[j] * w
                wsum[k] += w
                vacc[k] += band0[j] * w


@njit(cache=True, nogil=True, inline="always")
def _lock(r, ea, eb, nj, q0, qi, h0, params):
    """The rotation and the guard (see ``stack.phase_lock``)."""
    q = q0 * qi
    a = np.abs(r)
    denom = np.sqrt(ea * eb)
    if denom > 0.0:
        kappa = a / denom / np.sqrt(q if q > 0.0 else 1.0)
    else:
        kappa = np.inf
    gk = min(max((kappa - params[_KAPPA_LO]) / params[_KAPPA_SPAN], 0.0), 1.0)
    hp = min(max((h0 - params[_H_LO]) / params[_H_SPAN], 0.0), 1.0)
    g = 1.0
    if q > params[_Q_LO]:
        g = 1.0 - (1.0 - gk) * min((q - params[_Q_LO]) / params[_Q_SPAN], 1.0) * hp
    qr = max(0.0, (q - params[_Q_ROT]) / (1.0 - params[_Q_ROT]))
    wm = nj * qr / (1.0 - qr)
    safe_a = a if a > 0.0 else 1.0
    vx = (r.real / safe_a) * wm + params[_LOCK_PRIOR]
    vy = (r.imag / safe_a) * wm
    b = np.hypot(vx, vy)
    rot = 1.0 + 0j
    if a > 0.0 and b > 0.0:
        rot = complex(vx, vy) / b
    return rot, g


@njit(cache=True, nogil=True, parallel=True)
def combine_secondary(
    full, band, cov, band0, cov0, q0, h0, lag,
    margin, nout, half, chalf, weight, afloor, fixed, params, acc, wsum, vacc,
):
    """A secondary input's share of the combination, block by block.

    Its video band is turned onto the primary's (the phase lock over the
    lock window, or the plain normalised correlation in the fixed mode) and
    its weighted samples are added to ``acc``, ``wsum`` and ``vacc``.
    """
    length = full.shape[0]
    q_max = params[_Q_MAX]
    nblocks = (nout + COMBINE_BLOCK - 1) // COMBINE_BLOCK
    for blk in prange(nblocks):
        k0 = blk * COMBINE_BLOCK
        k1 = min(k0 + COMBINE_BLOCK, nout)
        base = max(margin + k0 - half, 0)
        top = min(margin + k1 - 1 + half, length)
        size = top - base + 1
        # The correlation with the primary, where both cover the sample.
        p_x = np.empty(size, dtype=np.complex128)
        p_ea = np.empty(size, dtype=np.float64)
        p_eb = np.empty(size, dtype=np.float64)
        p_nj = np.empty(size, dtype=np.float64)
        p_x[0] = 0.0
        p_ea[0] = 0.0
        p_eb[0] = 0.0
        p_nj[0] = 0.0
        for t in range(base, top):
            x = 0j
            ea = 0.0
            eb = 0.0
            nj = 0.0
            if cov0[t] and cov[t]:
                x = band0[t] * np.conj(band[t])
                ea = np.abs(band0[t]) ** 2
                eb = np.abs(band[t]) ** 2
                nj = 1.0
            u = t - base
            p_x[u + 1] = p_x[u] + x
            p_ea[u + 1] = p_ea[u] + ea
            p_eb[u + 1] = p_eb[u] + eb
            p_nj[u + 1] = p_nj[u] + nj
        p_rl = np.empty(size, dtype=np.complex128)
        p_e = np.empty(size, dtype=np.float64)
        p_c = np.empty(size, dtype=np.float64)
        if not fixed:
            _lag_sums(band, cov, lag, base, top, p_rl, p_e, p_c)
        for k in range(k0, k1):
            j = margin + k
            if not cov[j]:
                continue
            lo = max(j - half, 0) - base
            hi = min(j + half, length) - base
            r = p_x[hi] - p_x[lo]
            if fixed:
                mag = np.abs(r)
                rot = r / mag if mag > 0.0 else 1.0 + 0j
                w = weight
            else:
                e_a = p_ea[hi] - p_ea[lo]
                e_b = p_eb[hi] - p_eb[lo]
                n_j = p_nj[hi] - p_nj[lo]
                ci = p_c[hi] - p_c[lo]
                qi = 0.0
                if ci > 0.0:
                    _, qi = _measure(p_rl[hi] - p_rl[lo], p_e[hi] - p_e[lo], ci, params[_QN_LOCK], q_max)
                lo2 = max(j - chalf, 0) - base
                hi2 = min(j + chalf, length) - base
                cs = p_c[hi2] - p_c[lo2]
                si = 0.0
                if cs > 0.0:
                    si, _ = _measure(
                        p_rl[hi2] - p_rl[lo2], p_e[hi2] - p_e[lo2], cs, params[_QN_CARRIER], q_max
                    )
                rot = 1.0 + 0j
                guard = 1.0
                if n_j > 0.0:
                    rot, guard = _lock(r, e_a, e_b, n_j, q0[k], qi, h0[k], params)
                w = max(np.sqrt(max(si, 0.0)), afloor) * weight * guard
            z = band[j]
            correction = (z * (rot - 1.0)).real
            acc[k] += (full[j] + correction) * w
            wsum[k] += w
            vacc[k] += z * rot * w


@njit(cache=True, nogil=True, parallel=True)
def subtract_lines_kernel(span, first, starts, counts, block, amps, w, tables):
    """Subtract the clock lines from ``span``, piece by piece (in place).

    Parameters
    ----------
    span : numpy.ndarray
        The samples of one super-block's stretch (float64), ``span[0]`` at
        sample ``first`` of the super-block.
    first : int
        The super-block sample of ``span[0]``.
    starts, counts : numpy.ndarray
        The pieces (int64): each starts at super-block sample ``starts[k]``
        and holds ``counts[k]`` samples; a piece lies between two block
        centres, and its phasors are exact at the seed-aligned sample below
        its start.
    block : int
        The samples per measured block.
    amps : numpy.ndarray
        Each line's complex amplitude at each block centre (lines x blocks).
    w : numpy.ndarray
        Each line's angular frequency (radians per sample).
    tables : numpy.ndarray
        Each line's phasor over one seed (lines x seed), turned from the
        piece's start.

    Each sample loses each line's ``Re((g0 + dg * s) * phasor)``, the lines
    in order, as ``stack_corrections.CrystalLines.clean`` subtracts them.
    """
    nb = amps.shape[1]
    nlines = w.shape[0]
    seed = tables.shape[1]
    for k in prange(starts.shape[0]):
        a = starts[k]
        cnt = counts[k]
        at = a - a % seed
        u0 = (at + 0.5) / block - 0.5
        j = int(min(max(np.floor(u0), 0.0), nb - 1))
        for line in range(nlines):
            g0 = amps[line, j]
            dg = 0j
            if j + 1 < nb:
                dg = amps[line, j + 1] - amps[line, j]
            base = np.exp(1j * w[line] * a)
            for m in range(cnt):
                pos = a + m
                s = min(max((pos + 0.5) / block - 0.5 - j, 0.0), 1.0)
                phasor = base * tables[line, m]
                span[pos - first] -= ((g0 + dg * s) * phasor).real


@njit(cache=True, nogil=True, parallel=True)
def narrow_band_kernel(out, w, dec, boxl, box_span, first):
    """A carrier mixed down to 0 Hz and kept every ``dec`` samples (in place).

    ``first`` (complex128, one per kept sample) receives, for kept sample
    ``k``, the mean of ``out[t] * exp(j w t)`` over the ``boxl`` samples from
    ``k * dec - boxl // 2`` (clipped to the chunk).  The running sums are
    taken per span of ``box_span`` kept samples, as
    ``stack_corrections._carrier_narrow_band`` takes them, so the spans run
    in parallel.
    """
    n = out.shape[0]
    nd = first.shape[0]
    nspans = (nd + box_span - 1) // box_span
    for sp in prange(nspans):
        k0 = sp * box_span
        k1 = min(k0 + box_span, nd)
        lo0 = max(0, k0 * dec - boxl // 2)
        hi1 = min(max(0, (k1 - 1) * dec - boxl // 2) + boxl, n)
        if hi1 <= lo0:
            for k in range(k0, k1):
                first[k] = 0j
            continue
        sums = np.empty(hi1 - lo0 + 1, dtype=np.complex128)
        sums[0] = 0j
        for t in range(lo0, hi1):
            sums[t - lo0 + 1] = sums[t - lo0] + out[t] * np.exp(1j * w * t)
        for k in range(k0, k1):
            lo = max(0, k * dec - boxl // 2)
            hi = min(lo + boxl, n)
            first[k] = (sums[hi - lo0] - sums[lo - lo0]) / boxl


@njit(cache=True, nogil=True, parallel=True)
def line_phasors_kernel(raw, block, tables, turns, out):
    """Every line's phasor on every block of a super-block (in place).

    ``raw`` holds the super-block's samples (float64), ``nb = out.shape[1]``
    blocks of ``block`` samples.  ``tables[line]`` is ``exp(-j w t)`` over a
    block and ``turns[line, b]`` the block's own turn ``exp(-j w b block)``;
    ``out[line, b]`` receives ``(2 / block) * sum(raw * table) * turn``, the
    blocks in parallel and every line from one pass over the samples.
    """
    nlines = out.shape[0]
    nb = out.shape[1]
    for b in prange(nb):
        re = np.zeros(nlines, dtype=np.float64)
        im = np.zeros(nlines, dtype=np.float64)
        base = b * block
        for t in range(block):
            v = raw[base + t]
            for line in range(nlines):
                z = tables[line, t]
                re[line] += v * z.real
                im[line] += v * z.imag
        for line in range(nlines):
            out[line, b] = (2.0 / block) * complex(re[line], im[line]) * turns[line, b]


@njit(cache=True, nogil=True, parallel=True)
def crosstalk_phase_kernel(lines, ws, carriers, dec, taper, theta):
    """The phase the crosstalk's lines integrate to, at every sample of the
    chunk (in place): per line ``c``, its narrow band (kept every ``dec``
    samples, linear between them) mixed back up by ``exp(-j ws[c] t)`` and
    integrated over a turn of its carrier, ``Re(z / (j carriers[c]))``,
    summed, and faded at the chunk's edges over ``taper`` samples (a raised
    cosine).  One pass, the samples in parallel."""
    n = theta.shape[0]
    m = lines.shape[1]
    for t in prange(n):
        k = t // dec
        a = (t % dec) / dec
        acc = 0.0
        for c in range(lines.shape[0]):
            if k + 1 < m:
                v = lines[c, k] * (1.0 - a) + lines[c, k + 1] * a
            else:
                v = lines[c, k]
            ph = -ws[c] * t
            # Re(v e^{j ph} / (j f)) = Im(v e^{j ph}) / f
            acc += (v.real * np.sin(ph) + v.imag * np.cos(ph)) / carriers[c]
        e = min(t, n - 1 - t)
        if e < taper:
            acc *= 0.5 - 0.5 * np.cos(np.pi * e / taper)
        theta[t] = acc


@njit(cache=True, nogil=True, parallel=True)
def turn_back_kernel(view, theta, out):
    """``view (exp(-j theta) - 1)`` at every sample (in place into ``out``):
    the view turned back by the crosstalk's phase, less the view."""
    for t in prange(view.shape[0]):
        c = np.cos(theta[t])
        s = np.sin(theta[t])
        out[t] = view[t] * complex(c - 1.0, -s)
