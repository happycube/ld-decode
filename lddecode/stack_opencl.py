"""
stack_opencl - the stacked source's read and combination on an OpenCL device

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The OpenCL backend of :mod:`lddecode.stack` (``--device opencl``), ported
from the reference implementation's: the two stages that grow with the
number of captures - reading every capture at its own fractional positions
(the Kaiser-windowed sinc and the analytic video band) and combining them
(the carrier measure, the phase lock, the guard and the weights) - run on
the device.  The clock lines are subtracted on the host before the samples
are sent, and the cancellations run on the host after, as in the reference.

The kernels evaluate the plan the host evaluates: the same positions,
recomputed on the device in double precision from each segment's law, the
same sinc phase (rounded half away from zero), the same tables.  The dot
products and the combination run in the precision chosen (``single``, the
default: a consumer GPU's double precision is a small fraction of its
single, and the stream is then the host's to about 140 dB below the
signal; or ``double``).

pyopencl is an optional dependency, imported when a device is opened; this
module has no intra-package import (the tuning constants are passed in).

Thread-safety: one :class:`StackOpenCL` serves one thread at a time (the
stacked source's read-ahead producer).
"""

from __future__ import annotations

import logging
import os
from typing import Mapping, Sequence

import numpy as np

__all__ = ["KERNEL_SOURCE", "StackOpenCL", "open_device"]

_logger = logging.getLogger(__name__)

#: Outputs per work-group of the combination: the window terms of each
#: input are staged once per group in local memory.
TILE = 256

#: The reference's kernels (``opencl.rs``), less the 16-bit code input of its
#: ``.rfx`` archives, which this port does not read.
KERNEL_SOURCE = r"""
#pragma OPENCL EXTENSION cl_khr_fp64 : enable
#pragma OPENCL FP_CONTRACT OFF

// One input read at its virtual samples: the full signal (sinc) and the
// analytic video band.
__kernel void read_input(
    __global const float* raw_all,
    __global const uint* seg,
    __global const double* seg_t0,
    __global const double* a0_all,
    __global const double* slope_all,
    const double s0,
    const int len,
    const int base,
    const long raw_off,
    const long start,
    const int seg_off,
    __global const REAL* sinc,
    __global const REAL2* hil,
    __global REAL* full,
    __global REAL2* hi,
    __global uchar* cov)
{
    int j = get_global_id(0);
    if (j >= len) return;
    __global const float* raw = raw_all + raw_off;
    __global const double* a0 = a0_all + seg_off;
    __global const double* slope = slope_all + seg_off;
    uint k = seg[j];
    double a = a0[k];
    if (isnan(a)) {
        full[base + j] = (REAL)0;
        hi[base + j] = (REAL2)((REAL)0, (REAL)0);
        cov[base + j] = 0;
        return;
    }
    // Absolute position, then the span index.
    double p = a + ((s0 + (double)j) - seg_t0[k]) * slope[k];
    double kf = floor(p);
    int k0 = (int)((long)kf - start);
    int ph = (int)round((p - kf) * (double)PHASES);
    int xs = k0 - (SINC_TAPS / 2 - 1), xh = k0 - (HI_TAPS / 2 - 1);
    __global const REAL* hs = sinc + ph * SINC_TAPS;
    __global const REAL2* hh = hil + ph * HI_TAPS;
    REAL f = (REAL)0;
    REAL2 h = (REAL2)((REAL)0, (REAL)0);
    for (int d = 0; d < SINC_TAPS; d++) f += hs[d] * (REAL)raw[xs + d];
    for (int d = 0; d < HI_TAPS; d++) h += hh[d] * (REAL)raw[xh + d];
    full[base + j] = f;
    hi[base + j] = h;
    cov[base + j] = 1;
}

// The carrier measure, the amplitude weight and the lock, in their order.
REAL carrier(REAL2 rl, REAL e, REAL n, REAL qn, REAL* q)
{
    REAL a = sqrt(rl.x * rl.x + rl.y * rl.y);
    *q = e > (REAL)0 ? fmin(fmax(a / e - qn, (REAL)0) / ((REAL)1 - qn), (REAL)Q_MAX) : (REAL)0;
    return fmax(a - qn * e, (REAL)0) / (((REAL)1 - qn) * n);
}

REAL amp_weight(REAL s, REAL afl, REAL w)
{
    return fmax(sqrt(s), afl) * w;
}

REAL2 lock(REAL2 r, REAL ea, REAL eb, REAL nj, REAL q0, REAL qi, REAL h0, REAL* g)
{
    REAL q = q0 * qi;
    REAL a = sqrt(r.x * r.x + r.y * r.y);
    *g = (REAL)1;
    if (q > (REAL)Q_LO) {
        REAL kappa = a / sqrt(ea * eb) / sqrt(q);
        REAL gk = clamp((kappa - (REAL)KAPPA_LO) / (REAL)KAPPA_SPAN, (REAL)0, (REAL)1);
        REAL hp = clamp((h0 - (REAL)H_LO) / (REAL)H_SPAN, (REAL)0, (REAL)1);
        *g = (REAL)1 - ((REAL)1 - gk) * fmin((q - (REAL)Q_LO) / (REAL)Q_SPAN, (REAL)1) * hp;
    }
    if (a <= (REAL)0) return (REAL2)((REAL)1, (REAL)0);
    REAL qr = fmax((q - (REAL)Q_ROT) / ((REAL)1 - (REAL)Q_ROT), (REAL)0);
    REAL wm = nj * qr / ((REAL)1 - qr);
    REAL vx = r.x / a * wm + (REAL)LOCK_PRIOR;
    REAL vy = r.y / a * wm;
    REAL b = sqrt(vx * vx + vy * vy);
    return (REAL2)(vx / b, vy / b);
}

// An input's carrier terms at t: the lag product, |z[t]|^2, 1; zero where t
// or t - LAG is not covered.
void lagged(__global const REAL2* hi, __global const uchar* cov, int t, int len, REAL2* v, REAL* p, REAL* k)
{
    *v = (REAL2)((REAL)0, (REAL)0);
    *p = (REAL)0;
    *k = (REAL)0;
    if (t >= LAG && t < len && cov[t] && cov[t - LAG]) {
        REAL2 x = hi[t], y = hi[t - LAG];
        *v = (REAL2)(x.x * y.x + x.y * y.y, x.y * y.x - x.x * y.y);
        *p = x.x * x.x + x.y * x.y;
        *k = (REAL)1;
    }
}

#define TILE 256
// XTALK: the combined video band as well, each input's turned by its lock
// rotation.
#ifdef XTALK
#define VACC(z, w) vacc += (z) * (w)
#define ROT(z, r) ((REAL2)((z).x * (r).x - (z).y * (r).y, (z).x * (r).y + (z).y * (r).x))
#define VOUT() vout[jo] = wsum > (REAL)0 ? vacc / wsum : (REAL2)((REAL)0, (REAL)0)
#else
#define VACC(z, w)
#define ROT(z, r) (z)
#define VOUT()
#endif
#ifdef CARRIER_COMBINE
// Weight every input by its carrier amplitude, phase-lock its video band onto
// the primary's over LOCK_WIN samples (the rest of each input as read), and
// sum.  A work-group of TILE outputs stages the window terms of each input in
// local memory once, so the 128-sample sums read it instead of global memory.
__kernel void combine(
    const int ni,
    const int len,
    const int m,
    const int n,
    __global const REAL* full,
    __global const REAL2* hi,
    __global const uchar* cov,
    __global const REAL* weight,
    __global const REAL* afloor,
    __global float* out
#ifdef XTALK
    , __global REAL2* vout
#endif
    )
{
    __local REAL2 prod[TILE + LOCK_WIN], pr[TILE + LOCK_WIN];
    __local REAL pa[TILE + LOCK_WIN], pb[TILE + LOCK_WIN], pj[TILE + LOCK_WIN];
    __local REAL po[TILE + LOCK_WIN], pn[TILE + LOCK_WIN];
    int lid = get_local_id(0);
    int jo = get_global_id(0);
    int j = jo + m;
    int t0 = (int)get_group_id(0) * TILE + m - LOCK_WIN / 2;
    bool active = jo < n;
    REAL acc = (REAL)0, wsum = (REAL)0, q0 = (REAL)0, h0 = (REAL)0;
    REAL2 vacc = (REAL2)((REAL)0, (REAL)0);
    for (int u = lid; u < TILE + LOCK_WIN; u += TILE) {
        REAL2 v;
        REAL p, k;
        lagged(hi, cov, t0 + u, len, &v, &p, &k);
        pr[u] = v;
        po[u] = p;
        pn[u] = k;
    }
    barrier(CLK_LOCAL_MEM_FENCE);
    if (active) {
        REAL2 rl = (REAL2)((REAL)0, (REAL)0), rs = (REAL2)((REAL)0, (REAL)0);
        REAL e = (REAL)0, c = (REAL)0, es = (REAL)0, cs = (REAL)0, q;
        for (int u = 0; u < LOCK_WIN; u++) { rl += pr[lid + u]; e += po[lid + u]; c += pn[lid + u]; }
        for (int u = LOCK_WIN / 2 - CARRIER_WIN / 2; u < LOCK_WIN / 2 + CARRIER_WIN / 2; u++) {
            rs += pr[lid + u]; es += po[lid + u]; cs += pn[lid + u];
        }
        REAL s = cs > (REAL)0 ? carrier(rs, es, cs, (REAL)QN_CARRIER, &q) : (REAL)0;
        if (c > (REAL)0) {
            REAL sl = carrier(rl, e, c, (REAL)QN_LOCK, &q0);
            h0 = sl > (REAL)0 ? s / sl : (REAL)0;
        }
        if (cov[j]) {
            REAL w = amp_weight(s, afloor[0], weight[0]);
            acc += full[j] * w;
            wsum += w;
            VACC(hi[j], w);
        }
    }
    barrier(CLK_LOCAL_MEM_FENCE);
    for (int i = 1; i < ni; i++) {
        int b = i * len;
        for (int u = lid; u < TILE + LOCK_WIN; u += TILE) {
            int t = t0 + u;
            REAL2 v = (REAL2)((REAL)0, (REAL)0);
            REAL ea = (REAL)0, eb = (REAL)0, cj = (REAL)0;
            if (t >= 0 && t < len && cov[t] && cov[b + t]) {
                REAL2 x = hi[t], y = hi[b + t];
                v = (REAL2)(x.x * y.x + x.y * y.y, x.y * y.x - x.x * y.y);
                ea = x.x * x.x + x.y * x.y;
                eb = y.x * y.x + y.y * y.y;
                cj = (REAL)1;
            }
            prod[u] = v;
            pa[u] = ea;
            pb[u] = eb;
            pj[u] = cj;
            REAL2 lv;
            REAL lp, lk;
            lagged(hi + b, cov + b, t, len, &lv, &lp, &lk);
            pr[u] = lv;
            po[u] = lp;
            pn[u] = lk;
        }
        barrier(CLK_LOCAL_MEM_FENCE);
        if (active && cov[b + j]) {
            REAL2 r = (REAL2)((REAL)0, (REAL)0), rl = (REAL2)((REAL)0, (REAL)0);
            REAL ea = (REAL)0, eb = (REAL)0, nj = (REAL)0, eo = (REAL)0, no = (REAL)0;
            for (int u = 0; u < LOCK_WIN; u++) {
                r += prod[lid + u];
                ea += pa[lid + u];
                eb += pb[lid + u];
                nj += pj[lid + u];
                rl += pr[lid + u];
                eo += po[lid + u];
                no += pn[lid + u];
            }
            REAL2 rs = (REAL2)((REAL)0, (REAL)0);
            REAL es = (REAL)0, cs = (REAL)0;
            for (int u = LOCK_WIN / 2 - CARRIER_WIN / 2; u < LOCK_WIN / 2 + CARRIER_WIN / 2; u++) {
                rs += pr[lid + u]; es += po[lid + u]; cs += pn[lid + u];
            }
            REAL qi = (REAL)0, q, s = (REAL)0, g = (REAL)1;
            if (no > (REAL)0) carrier(rl, eo, no, (REAL)QN_LOCK, &qi);
            if (cs > (REAL)0) s = carrier(rs, es, cs, (REAL)QN_CARRIER, &q);
            REAL2 rot = nj > (REAL)0 ? lock(r, ea, eb, nj, q0, qi, h0, &g) : (REAL2)((REAL)1, (REAL)0);
            REAL w = amp_weight(s, afloor[i], weight[i]) * g;
            REAL2 d = (REAL2)(rot.x - (REAL)1, rot.y);
            REAL2 z = hi[b + j];
            acc += (full[b + j] + (z.x * d.x - z.y * d.y)) * w;
            wsum += w;
            VACC(ROT(z, rot), w);
        }
        barrier(CLK_LOCAL_MEM_FENCE);
    }
    if (active) {
        out[jo] = wsum > (REAL)0 ? (float)(acc / wsum) : 0.0f;
        VOUT();
    }
}
#else
// --stack_weight fixed: phase-lock every input's video band onto the
// primary's over LOCK_WIN samples and sum with the fixed weights (the rest of
// each input as read; `afloor` unused).
__kernel void combine(
    const int ni,
    const int len,
    const int m,
    const int n,
    __global const REAL* full,
    __global const REAL2* hi,
    __global const uchar* cov,
    __global const REAL* weight,
    __global const REAL* afloor,
    __global float* out
#ifdef XTALK
    , __global REAL2* vout
#endif
    )
{
    __local REAL2 prod[TILE + LOCK_WIN];
    int lid = get_local_id(0);
    int jo = get_global_id(0);
    int j = jo + m;
    int t0 = (int)get_group_id(0) * TILE + m - LOCK_WIN / 2;
    bool active = jo < n;
    REAL acc = (REAL)0, wsum = (REAL)0;
    REAL2 vacc = (REAL2)((REAL)0, (REAL)0);
    if (active && cov[j]) { acc += full[j] * weight[0]; wsum += weight[0]; VACC(hi[j], weight[0]); }
    for (int i = 1; i < ni; i++) {
        int b = i * len;
        for (int u = lid; u < TILE + LOCK_WIN; u += TILE) {
            int t = t0 + u;
            REAL2 v = (REAL2)((REAL)0, (REAL)0);
            if (t >= 0 && t < len && cov[t] && cov[b + t]) {
                REAL2 x = hi[t], y = hi[b + t];
                v = (REAL2)(x.x * y.x + x.y * y.y, x.y * y.x - x.x * y.y);
            }
            prod[u] = v;
        }
        barrier(CLK_LOCAL_MEM_FENCE);
        if (active && cov[b + j]) {
            REAL2 r = (REAL2)((REAL)0, (REAL)0);
            for (int u = 0; u < LOCK_WIN; u++) r += prod[lid + u];
            REAL a = sqrt(r.x * r.x + r.y * r.y);
            REAL2 rot = a > (REAL)0 ? r / a : (REAL2)((REAL)1, (REAL)0);
            REAL2 d = (REAL2)(rot.x - (REAL)1, rot.y);
            REAL2 z = hi[b + j];
            acc += (full[b + j] + (z.x * d.x - z.y * d.y)) * weight[i];
            wsum += weight[i];
            VACC(ROT(z, rot), weight[i]);
        }
        barrier(CLK_LOCAL_MEM_FENCE);
    }
    if (active) {
        out[jo] = wsum > (REAL)0 ? (float)(acc / wsum) : 0.0f;
        VOUT();
    }
}
#endif
"""


def _import_pyopencl():
    """pyopencl, or a RuntimeError saying how to get it."""
    try:
        import pyopencl
    except ImportError as exc:
        raise RuntimeError(
            "--device opencl needs pyopencl (pip install 'ld-decode[opencl]') "
            "and an OpenCL driver for the GPU"
        ) from exc
    return pyopencl


def open_device(cl=None):
    """An OpenCL context and queue on the best GPU, or the one PYOPENCL_CTX names.

    Returns ``(context, queue, device_name)``.  The GPU with the most compute
    units is taken; without any GPU, the first device of any kind.  Raises
    RuntimeError when no device is found.
    """
    cl = cl if cl is not None else _import_pyopencl()
    if os.environ.get("PYOPENCL_CTX"):
        ctx = cl.create_some_context(interactive=False)
    else:
        devices = [d for p in cl.get_platforms() for d in p.get_devices()]
        if not devices:
            raise RuntimeError("--device opencl: no OpenCL device found")
        gpus = [d for d in devices if d.type & cl.device_type.GPU]
        device = max(gpus or devices, key=lambda d: d.max_compute_units)
        ctx = cl.Context([device])
    queue = cl.CommandQueue(ctx)
    return ctx, queue, ctx.devices[0].name


def build_options(
    constants: Mapping[str, float],
    *,
    lag: int,
    adaptive: bool,
    want_band: bool,
    double: bool,
) -> list[str]:
    """The kernels' compile-time definitions.

    ``constants`` holds PHASES, SINC_TAPS, HI_TAPS, LOCK_WIN, CARRIER_WIN and
    the tuning constants (QN_LOCK, QN_CARRIER, LOCK_PRIOR, KAPPA_LO,
    KAPPA_SPAN, Q_LO, Q_SPAN, Q_MAX, Q_ROT, H_LO, H_SPAN).  The floats are
    written with every digit (``repr``), so the device reads the host's
    values.
    """
    opts = []
    for name in ("PHASES", "SINC_TAPS", "HI_TAPS", "LOCK_WIN", "CARRIER_WIN"):
        opts.append(f"-D{name}={int(constants[name])}")
    for name in (
        "QN_LOCK", "QN_CARRIER", "LOCK_PRIOR", "KAPPA_LO", "KAPPA_SPAN",
        "Q_LO", "Q_SPAN", "Q_MAX", "Q_ROT", "H_LO", "H_SPAN",
    ):
        opts.append(f"-D{name}={float(constants[name])!r}")
    opts.append(f"-DLAG={int(lag)}")
    if adaptive:
        opts.append("-DCARRIER_COMBINE")
    if want_band:
        opts.append("-DXTALK")
    if double:
        opts += ["-DREAL=double", "-DREAL2=double2"]
    else:
        opts += ["-DREAL=float", "-DREAL2=float2"]
    return opts


class StackOpenCL:
    """The read and the combination of the stack on an OpenCL device.

    Parameters
    ----------
    sinc : numpy.ndarray
        The sinc table (phases + 1 rows of taps).
    hi : numpy.ndarray
        The video-band table (complex, phases + 1 rows of taps).
    weight, afloor : Sequence[float]
        Per input, its 1/sigma^2 weight and its amplitude weight floor.
    constants : Mapping[str, float]
        The window sizes and tuning constants (see :func:`build_options`).
    lag : int
        The carrier measure's lag, in samples.
    adaptive : bool
        The adaptive weights and lock (``--stack_weight adaptive``), or the
        fixed ones.
    want_band : bool
        Whether the combined video band is read back (the cancellations need
        it).
    double : bool
        Double precision on the device, or single (the default).
    device : tuple, optional
        ``(context, queue, name)`` as :func:`open_device` returns; opened
        here when not given (the seam the tests substitute).
    """

    def __init__(
        self,
        sinc: np.ndarray,
        hi: np.ndarray,
        weight: Sequence[float],
        afloor: Sequence[float],
        constants: Mapping[str, float],
        *,
        lag: int,
        adaptive: bool,
        want_band: bool,
        double: bool = False,
        device: tuple | None = None,
        cl=None,
    ) -> None:
        self._cl = cl if cl is not None else _import_pyopencl()
        self._ctx, self._queue, self.device_name = device if device is not None else open_device(self._cl)
        self.double = bool(double)
        self.want_band = bool(want_band)
        self._real = np.float64 if self.double else np.float32
        self._ni = len(weight)
        options = build_options(
            constants, lag=lag, adaptive=adaptive, want_band=want_band, double=self.double
        )
        program = self._cl.Program(self._ctx, KERNEL_SOURCE).build(options=options)
        self._k_read = program.read_input
        self._k_combine = program.combine
        mf = self._cl.mem_flags
        # Single precision: the weights scaled to at most 1 (the output is
        # normalised by their sum, so the scale cancels).
        w = np.asarray(weight, dtype=np.float64)
        if not self.double:
            w = w / w.max()
        hil = np.empty((hi.shape[0], hi.shape[1], 2), dtype=np.float64)
        hil[..., 0] = hi.real
        hil[..., 1] = hi.imag

        def constant(data):
            return self._cl.Buffer(
                self._ctx,
                mf.READ_ONLY | mf.COPY_HOST_PTR,
                hostbuf=np.ascontiguousarray(data, dtype=self._real),
            )

        self._sinc = constant(sinc)
        self._hil = constant(hil)
        self._weight = constant(w)
        self._afloor = constant(np.asarray(afloor, dtype=np.float64))
        _logger.info(
            "stack: OpenCL device %s (%s precision)",
            self.device_name,
            "double" if self.double else "single",
        )

    def run(self, plan: object, margin: int, nout: int) -> tuple[np.ndarray, np.ndarray | None]:
        """The combined stream over the plan's samples ``margin .. margin + nout``.

        ``plan`` is the host's plan (:class:`lddecode.stack._Plan`): its
        ``s0``, ``length``, per-sample ``seg`` and per-segment ``seg_t0``,
        and per input a span (``raw``, ``start``, ``a0``, ``slope``) or None.
        The clock lines must already be out of the spans' samples.

        Returns the combined stream (float64, a new array) and, when the
        cancellations want it, the combined video band (complex128).
        """
        cl = self._cl
        ctx, queue = self._ctx, self._queue
        mf = cl.mem_flags
        length = int(plan.length)
        ni = self._ni
        nseg = int(np.asarray(plan.seg_t0).shape[0])
        # Every input's samples back to back, and its segment law at i * nseg
        # (all NaN for an input this read does not cover).
        raws = []
        offsets = []
        a0 = np.full(ni * max(nseg, 1), np.nan, dtype=np.float64)
        slope = np.zeros(ni * max(nseg, 1), dtype=np.float64)
        at = 0
        for i, span in enumerate(plan.inputs):
            if span is None:
                offsets.append((at, 0))
                continue
            raw = np.asarray(span.raw, dtype=np.float32)
            raws.append(raw)
            offsets.append((at, int(span.start)))
            at += raw.shape[0]
            a0[i * nseg : (i + 1) * nseg] = span.a0
            slope[i * nseg : (i + 1) * nseg] = span.slope
        raw_all = np.concatenate(raws) if raws else np.zeros(1, dtype=np.float32)

        def upload(data):
            return cl.Buffer(ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=np.ascontiguousarray(data))

        b_raw = upload(raw_all)
        b_seg = upload(np.asarray(plan.seg, dtype=np.uint32))
        b_seg_t0 = upload(np.asarray(plan.seg_t0, dtype=np.float64))
        b_a0 = upload(a0)
        b_slope = upload(slope)
        rsz = np.dtype(self._real).itemsize
        b_full = cl.Buffer(ctx, mf.READ_WRITE, size=ni * length * rsz)
        b_hi = cl.Buffer(ctx, mf.READ_WRITE, size=ni * length * 2 * rsz)
        b_cov = cl.Buffer(ctx, mf.READ_WRITE, size=ni * length)
        global_read = (_round_up(length, TILE),)
        for i, (off, start) in enumerate(offsets):
            self._k_read(
                queue, global_read, (TILE,),
                b_raw, b_seg, b_seg_t0, b_a0, b_slope,
                np.float64(plan.s0), np.int32(length), np.int32(i * length),
                np.int64(off), np.int64(start), np.int32(i * nseg),
                self._sinc, self._hil, b_full, b_hi, b_cov,
            )
        out = np.empty(nout, dtype=np.float32)
        b_out = cl.Buffer(ctx, mf.WRITE_ONLY, size=max(nout, 1) * 4)
        args = [
            np.int32(ni), np.int32(length), np.int32(margin), np.int32(nout),
            b_full, b_hi, b_cov, self._weight, self._afloor, b_out,
        ]
        vout = None
        if self.want_band:
            b_vout = cl.Buffer(ctx, mf.WRITE_ONLY, size=max(nout, 1) * 2 * rsz)
            args.append(b_vout)
        self._k_combine(queue, (_round_up(nout, TILE),), (TILE,), *args)
        cl.enqueue_copy(queue, out, b_out)
        if self.want_band:
            pairs = np.empty((nout, 2), dtype=self._real)
            cl.enqueue_copy(queue, pairs, b_vout)
            vout = pairs[:, 0].astype(np.float64) + 1j * pairs[:, 1].astype(np.float64)
        queue.finish()
        return out.astype(np.float64), vout


def _round_up(n: int, step: int) -> int:
    """``n`` rounded up to a multiple of ``step`` (at least one step)."""
    return max(step, -(-int(n) // step) * step)
