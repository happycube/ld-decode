"""
demod_opencl - the decoder's block demodulation on an OpenCL device

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

``--device opencl`` runs ``RFDecode.demodblock`` on a GPU, a batch of blocks
at a time, as the reference implementation's ``--gpu-fast`` does for its
7.4 decoder: the same signal path, the same filters, but not the host's
arithmetic.  The transforms are radix-8/4/2 Stockham FFTs with twiddles
tabulated in double precision, so the output agrees with the host's to its
last bits, not bit for bit.

The precision follows the host's: the block's spectrum, the analytic video
band and the discriminator in double precision, the
video channels' filters in single precision, after the discriminator's
output has been centred on blanking (as ``demodblock`` centres it).

What runs where, for each block of a batch:

    device  the block's FFT, the RF high-pass and the EFM products and
            their inverses, the video band (RF video filter, PAL carrier
            notch, MTF), its inverse at half rate, the discriminator, and the
            video channels' filters;
    host    the PAL carriers' presence and the analog audio's first stage,
            read off the block's spectrum (``demodblock``'s own code), and
            the assembly of the outputs.

``demodblock`` stays the reference and the fallback: the opt-in RF echo
cancellation and the V4300D coherent subtraction, which read and rewrite
the whole spectrum, run on the host.

pyopencl is an optional dependency, imported when a device is opened.

Thread-safety: one :class:`DemodOpenCL` serves one thread at a time.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

__all__ = ["DemodOpenCL", "DeviceFFT", "fft_radices"]

TAU = 2.0 * math.pi

# ---------------------------------------------------------------------------
# Kernels
# ---------------------------------------------------------------------------

#: The FFT passes and the demodulation kernels.  The FFT kernels are written
#: once and instantiated for double (``_d``) and float (``_f``).
KERNEL_SOURCE = r"""
#pragma OPENCL EXTENSION cl_khr_fp64 : enable
#pragma OPENCL FP_CONTRACT OFF

#define FFT_KERNELS(T, T2, SFX)                                                \
inline T2 cmul##SFX(T2 a, T2 b) {                                              \
    return (T2)(a.x * b.x - a.y * b.y, a.x * b.y + a.y * b.x);                 \
}                                                                              \
/* v * exp(s i pi k / 4), k = 1, 2, 3 */                                       \
inline T2 w81##SFX(T2 v, T s) {                                                \
    const T r = (T)0.70710678118654752440;                                     \
    return (T2)(r * (v.x - s * v.y), r * (v.y + s * v.x));                     \
}                                                                              \
inline T2 w82##SFX(T2 v, T s) { return (T2)(-s * v.y, s * v.x); }              \
inline T2 w83##SFX(T2 v, T s) {                                                \
    const T r = (T)0.70710678118654752440;                                     \
    return (T2)(r * (-v.x - s * v.y), r * (-v.y + s * v.x));                   \
}                                                                              \
/* One Stockham pass of radix R over rows of length L: Ns is the length of */  \
/* the sub-transforms done so far, tw[m] = exp(-2 pi i m / L).            */  \
__kernel void fft8##SFX(__global const T2* in, __global T2* out,              \
                        __global const T2* tw, const int L, const int Ns,     \
                        const T s) {                                           \
    int j = get_global_id(0), b = get_global_id(1);                            \
    if (j >= L / 8) return;                                                    \
    __global const T2* x = in + (size_t)b * L;                                 \
    __global T2* y = out + (size_t)b * L;                                      \
    int k = j % Ns;                                                            \
    T2 v[8];                                                                   \
    for (int r = 0; r < 8; r++) v[r] = x[j + r * (L / 8)];                     \
    if (Ns > 1) {                                                              \
        int step = L / (Ns * 8);                                               \
        for (int r = 1; r < 8; r++) {                                          \
            T2 t = tw[(k * r * step) & (L - 1)];                               \
            if (s > (T)0) t.y = -t.y;                                          \
            v[r] = cmul##SFX(v[r], t);                                         \
        }                                                                      \
    }                                                                          \
    T2 a0 = v[0] + v[4], a4 = v[0] - v[4];                                     \
    T2 a1 = v[1] + v[5], a5 = w81##SFX(v[1] - v[5], s);                        \
    T2 a2 = v[2] + v[6], a6 = w82##SFX(v[2] - v[6], s);                        \
    T2 a3 = v[3] + v[7], a7 = w83##SFX(v[3] - v[7], s);                        \
    T2 c0 = a0 + a2, c2 = a0 - a2, c1 = a1 + a3, c3 = w82##SFX(a1 - a3, s);    \
    T2 d0 = a4 + a6, d2 = a4 - a6, d1 = a5 + a7, d3 = w82##SFX(a5 - a7, s);    \
    T2 o[8];                                                                   \
    o[0] = c0 + c1; o[4] = c0 - c1; o[2] = c2 + c3; o[6] = c2 - c3;            \
    o[1] = d0 + d1; o[5] = d0 - d1; o[3] = d2 + d3; o[7] = d2 - d3;            \
    int idx = (j / Ns) * Ns * 8 + k;                                           \
    for (int r = 0; r < 8; r++) y[idx + r * Ns] = o[r];                        \
}                                                                              \
__kernel void fft4##SFX(__global const T2* in, __global T2* out,              \
                        __global const T2* tw, const int L, const int Ns,     \
                        const T s) {                                           \
    int j = get_global_id(0), b = get_global_id(1);                            \
    if (j >= L / 4) return;                                                    \
    __global const T2* x = in + (size_t)b * L;                                 \
    __global T2* y = out + (size_t)b * L;                                      \
    int k = j % Ns;                                                            \
    T2 v[4];                                                                   \
    for (int r = 0; r < 4; r++) v[r] = x[j + r * (L / 4)];                     \
    if (Ns > 1) {                                                              \
        int step = L / (Ns * 4);                                               \
        for (int r = 1; r < 4; r++) {                                          \
            T2 t = tw[(k * r * step) & (L - 1)];                               \
            if (s > (T)0) t.y = -t.y;                                          \
            v[r] = cmul##SFX(v[r], t);                                         \
        }                                                                      \
    }                                                                          \
    T2 a0 = v[0] + v[2], a1 = v[0] - v[2];                                     \
    T2 b0 = v[1] + v[3], b1 = w82##SFX(v[1] - v[3], s);                        \
    int idx = (j / Ns) * Ns * 4 + k;                                           \
    y[idx] = a0 + b0; y[idx + 2 * Ns] = a0 - b0;                               \
    y[idx + Ns] = a1 + b1; y[idx + 3 * Ns] = a1 - b1;                          \
}                                                                              \
__kernel void fft2##SFX(__global const T2* in, __global T2* out,              \
                        __global const T2* tw, const int L, const int Ns,     \
                        const T s) {                                           \
    int j = get_global_id(0), b = get_global_id(1);                            \
    if (j >= L / 2) return;                                                    \
    __global const T2* x = in + (size_t)b * L;                                 \
    __global T2* y = out + (size_t)b * L;                                      \
    int k = j % Ns;                                                            \
    T2 v0 = x[j], v1 = x[j + L / 2];                                           \
    if (Ns > 1) {                                                              \
        T2 t = tw[(k * (L / (Ns * 2))) & (L - 1)];                             \
        if (s > (T)0) t.y = -t.y;                                              \
        v1 = cmul##SFX(v1, t);                                                 \
    }                                                                          \
    int idx = (j / Ns) * Ns * 2 + k;                                           \
    y[idx] = v0 + v1; y[idx + Ns] = v0 - v1;                                   \
}

FFT_KERNELS(double, double2, _d)
FFT_KERNELS(float, float2, _f)

// The block's real samples as complex rows (double).
__kernel void load_raw(__global const float* raw, __global double2* x) {
    int i = get_global_id(0), b = get_global_id(1);
    if (i >= N) return;
    x[(size_t)b * N + i] = (double2)((double)raw[(size_t)b * N + i], 0.0);
}

// The full spectrum irfft inverts, of the half spectrum X[:N/2+1] times a
// real-signal filter f[:N/2+1] (the imaginary parts of the DC and Nyquist
// bins dropped, as irfft drops them).
__kernel void hermitian_product(__global const double2* X, __global const double2* f,
                                __global double2* out) {
    int k = get_global_id(0), b = get_global_id(1);
    if (k >= N) return;
    __global const double2* x = X + (size_t)b * N;
    double2 v;
    if (k == 0 || k == N / 2) v = (double2)(cmul_d(x[k], f[k]).x, 0.0);
    else if (k < N / 2) v = cmul_d(x[k], f[k]);
    else { double2 u = cmul_d(x[N - k], f[N - k]); v = (double2)(u.x, -u.y); }
    out[(size_t)b * N + k] = v;
}

// The video band, M bins of the spectrum times the video filter (with the
// PAL carrier notch where the block's flag asks for it).
__kernel void video_band(__global const double2* X, __global const double2* fv,
                         __global const double2* fv_notch, __global const uchar* notch,
                         __global double2* H) {
    int k = get_global_id(0), b = get_global_id(1);
    if (k >= M) return;
    __global const double2* x = X + (size_t)b * N;
    double2 v = (k < NRF) ? x[k] : (double2)(0.0, 0.0);
    H[(size_t)b * M + k] = cmul_d(v, notch[b] ? fv_notch[k] : fv[k]);
}

// The discriminator: the phase advance from the sample before, in
// [0, 2 pi), as a frequency.  demod[0] is 0, as unwrap_hilbert has it.
__kernel void discriminate(__global const double2* H, const double fscale,
                           __global double* demod) {
    int i = get_global_id(0), b = get_global_id(1);
    if (i >= M) return;
    size_t o = (size_t)b * M + i;
    if (i == 0) { demod[o] = 0.0; return; }
    double2 h1 = H[o], h0 = H[o - 1];
    double re = h1.x * h0.x + h1.y * h0.y;
    double im = h1.y * h0.x - h1.x * h0.y;
    double d = atan2(im, re);
    if (d < 0.0) d += 2.0 * M_PI;
    demod[o] = d * fscale;
}

// demod_raw at the input rate, the discriminator clipped and centred on
// blanking (in double, then cast, as demodblock subtracts into float32),
// as complex rows for the video transform.
__kernel void centre(__global const double* demod, const double lo, const double hi,
                     const double c, __global float* raw_out, __global float2* C) {
    int i = get_global_id(0), b = get_global_id(1);
    if (i >= M) return;
    size_t o = (size_t)b * M + i;
    double d = demod[o];
#if M == N
    raw_out[(size_t)b * N + i] = (float)d;
#else
    // Each estimate over the two input-rate samples it was formed from.
    __global float* r = raw_out + (size_t)b * N;
    r[2 * i] = (float)d;
    if (i + 1 < M) r[2 * i + 1] = (float)demod[o + 1];
    else r[N - 1] = (float)d;
#endif
    double dc = fmin(fmax(d, lo), hi);
    C[o] = (float2)((float)(dc - c), 0.0f);
}

// One video channel's spectrum at the input rate: the centred demod's
// spectrum S[:M/2+1] times the channel's filter, as the full spectrum the
// zero-padded irfft to N inverts.
__kernel void video_spectrum(__global const float2* S, __global const float2* F,
                             const int ch, const int nch, __global float2* Y) {
    int k = get_global_id(0), b = get_global_id(1);
    if (k >= N) return;
    __global const float2* s = S + (size_t)b * M;
    __global const float2* f = F + (size_t)ch * (M / 2 + 1);
    float2 v = (float2)(0.0f, 0.0f);
    if (k == 0) v = (float2)(cmul_f(s[0], f[0]).x, 0.0f);
    else if (k <= M / 2) v = cmul_f(s[k], f[k]);
    else if (k >= N - M / 2) { float2 u = cmul_f(s[N - k], f[N - k]); v = (float2)(u.x, -u.y); }
    Y[((size_t)b * nch + ch) * N + k] = v;
}

// A video channel's samples: the real part over N, plus the channel's DC.
__kernel void video_out(__global const float2* Y, __global const float* dc,
                        const int nch, __global float* out) {
    int i = get_global_id(0), b = get_global_id(1), ch = get_global_id(2);
    if (i >= N) return;
    size_t o = ((size_t)b * nch + ch) * N + i;
    out[o] = Y[o].x / (float)N + dc[ch];
}

// A real signal out of a double inverse: the real part over N, as float32
// (RF high-pass) or clipped to int16 (EFM).
__kernel void real_f32(__global const double2* y, __global float* out) {
    int i = get_global_id(0), b = get_global_id(1);
    if (i >= N) return;
    size_t o = (size_t)b * N + i;
    out[o] = (float)(y[o].x / (double)N);
}

__kernel void real_s16(__global const double2* y, __global short* out) {
    int i = get_global_id(0), b = get_global_id(1);
    if (i >= N) return;
    size_t o = (size_t)b * N + i;
    double v = y[o].x / (double)N;
    out[o] = (short)fmin(fmax(v, -32768.0), 32767.0);
}
"""


def fft_radices(n: int) -> list:
    """The passes of a length-``n`` transform: radix 8 while it divides,
    then one radix-4 or radix-2 pass.  ``n`` must be a power of two."""
    if n < 2 or n & (n - 1):
        raise ValueError(f"FFT length must be a power of two, got {n}")
    radices = []
    while n % 8 == 0:
        radices.append(8)
        n //= 8
    if n == 4:
        radices.append(4)
    elif n == 2:
        radices.append(2)
    return radices


class DeviceFFT:
    """Batched complex FFTs of one length on the device (Stockham, out of
    place, ping-ponging between the input buffer and a scratch buffer of
    the same size).  ``double`` picks the precision.  Unscaled both ways,
    like the textbook DFT: the inverse leaves the 1/L to the caller."""

    def __init__(self, cl, ctx, kernels, length: int, double: bool):
        self._cl = cl
        self.length = int(length)
        self.radices = fft_radices(self.length)
        sfx = "_d" if double else "_f"
        self._dtype = np.complex128 if double else np.complex64
        self._real = np.float64 if double else np.float32
        self._kernels = {r: kernels[f"fft{r}{sfx}"] for r in (8, 4, 2)}
        tw = np.exp(-2j * np.pi * np.arange(self.length) / self.length)
        self._tw = cl.Buffer(ctx, cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR,
                             hostbuf=tw.astype(self._dtype))

    def run(self, queue, buf, scratch, batch: int, inverse: bool = False):
        """Transform ``batch`` rows of ``buf``; returns the buffer holding
        the result (``buf`` or ``scratch``)."""
        src, dst = buf, scratch
        ns = 1
        s = self._real(1.0 if inverse else -1.0)
        for r in self.radices:
            self._kernels[r](queue, (self.length // r, batch), None,
                             src, dst, self._tw, np.int32(self.length),
                             np.int32(ns), s)
            src, dst = dst, src
            ns *= r
        return src


# ---------------------------------------------------------------------------
# The demodulator
# ---------------------------------------------------------------------------

#: Blocks per device submission: bounds the device memory (about 5 MB a
#: block) and the host's staging arrays.
MAX_BATCH = 32


class DemodOpenCL:
    """``RFDecode.demodblock`` for a batch of blocks, on an OpenCL device.

    ``rf`` is the RFDecode whose filters and parameters the blocks are
    demodulated with; they are read at each call, and uploaded again when
    the host has replaced them (the MTF level, the video EQ, the inverse
    MTF, a filter rebuild).  ``ctx``/``queue`` may be given (tests);
    otherwise the device is opened as the stack opens it.
    """

    def __init__(self, rf, cl=None, ctx=None, queue=None):
        if cl is None:
            from .stack_opencl import _import_pyopencl
            cl = _import_pyopencl()
        self._cl = cl
        if ctx is None:
            from .stack_opencl import open_device
            ctx, queue, name = open_device(cl)
        else:
            name = ctx.devices[0].name
        self.device_name = name
        self._ctx, self._queue = ctx, queue
        self.rf = rf
        self.n = int(rf.blocklen)
        self.m = self.n if rf.full_rate_demod else self.n // 2
        self.nrf = self.n // 2 + 1
        program = cl.Program(ctx, KERNEL_SOURCE).build(
            options=[f"-DN={self.n}", f"-DM={self.m}", f"-DNRF={self.nrf}"])
        self._k = {k.function_name: k for k in program.all_kernels()}
        self._fft_n_d = DeviceFFT(cl, ctx, self._k, self.n, True)
        self._fft_m_d = DeviceFFT(cl, ctx, self._k, self.m, True)
        self._fft_m_f = DeviceFFT(cl, ctx, self._k, self.m, False)
        self._fft_n_f = DeviceFFT(cl, ctx, self._k, self.n, False)
        self._nch = int(rf.Filters["FVideo_rfft32"].shape[0])
        self._bufs = None
        self._uploaded = {}

    # -- device memory ------------------------------------------------------

    def _buffer(self, nbytes):
        return self._cl.Buffer(self._ctx, self._cl.mem_flags.READ_WRITE, size=int(nbytes))

    def _alloc(self):
        if self._bufs is not None:
            return self._bufs
        b, n, m, nch = MAX_BATCH, self.n, self.m, self._nch
        self._bufs = {
            "raw": self._buffer(b * n * 4),
            "X": self._buffer(b * n * 16), "Xs": self._buffer(b * n * 16),
            "R": self._buffer(b * n * 16), "Rs": self._buffer(b * n * 16),
            "H": self._buffer(b * m * 16), "Hs": self._buffer(b * m * 16),
            "demod": self._buffer(b * m * 8),
            "C": self._buffer(b * m * 8), "Cs": self._buffer(b * m * 8),
            "Y": self._buffer(b * nch * n * 8), "Ys": self._buffer(b * nch * n * 8),
            "rawout": self._buffer(b * n * 4),
            "video": self._buffer(b * nch * n * 4),
            "rfhpf": self._buffer(b * n * 4),
            "efm": self._buffer(b * n * 2),
            "notch": self._buffer(b),
        }
        return self._bufs

    def _const(self, key, array):
        """``array`` on the device, uploaded again only when its contents
        change."""
        array = np.ascontiguousarray(array)
        stamp = (array.shape, array.dtype.str, hash(array.tobytes()))
        held = self._uploaded.get(key)
        if held is not None and held[0] == stamp:
            return held[1]
        buf = self._cl.Buffer(self._ctx,
                              self._cl.mem_flags.READ_ONLY | self._cl.mem_flags.COPY_HOST_PTR,
                              hostbuf=array)
        self._uploaded[key] = (stamp, buf)
        return buf

    # -- the filters, as demodblock builds them ------------------------------

    def _video_filters(self, mtf_level):
        rf = self.rf
        fv = np.zeros(self.m, dtype=np.complex128)
        base = np.asarray(rf.Filters["RFVideo_half"], dtype=np.complex128)
        if mtf_level != 0:
            base = base * rf.mtf_response(mtf_level)
        upto = min(self.m, self.nrf)
        fv[:upto] = base[:upto]
        notch = rf.Filters.get("FcutPAL_half")
        fvn = fv.copy()
        if notch is not None:
            fvn[:upto] *= notch[:upto]
        return fv, fvn

    # -- the batch ------------------------------------------------------------

    def supported(self) -> bool:
        """Whether the device path covers this RFDecode's configuration: the
        opt-in RF echo cancellation and the V4300D coherent subtraction stay
        on the host."""
        rf = self.rf
        if getattr(rf, "rf_echo_cancel", False):
            return False
        if rf.system == "PAL" and getattr(rf, "PAL_V4300D_CoherentSubtract", False):
            return False
        return True

    def demod(self, blocks, mtf_level=0, cut=True):
        """``[rf.demodblock(data=b, mtf_level=mtf_level, cut=cut) for b in
        blocks]``, on the device."""
        out = []
        for i in range(0, len(blocks), MAX_BATCH):
            out.extend(self._batch(blocks[i:i + MAX_BATCH], mtf_level, cut))
        return out

    def _batch(self, blocks, mtf_level, cut):
        cl, q, k, rf = self._cl, self._queue, self._k, self.rf
        n, m, nrf, nch = self.n, self.m, self.nrf, self._nch
        nb = len(blocks)
        bufs = self._alloc()
        level = rf.scaled_mtf_level(mtf_level)

        raw = np.empty((nb, n), dtype=np.float32)
        for i, blk in enumerate(blocks):
            raw[i] = blk[:n]
        cl.enqueue_copy(q, bufs["raw"], raw)

        k["load_raw"](q, (n, nb), None, bufs["raw"], bufs["X"])
        X = self._fft_n_d.run(q, bufs["X"], bufs["Xs"], nb)

        # The host's share: the PAL carriers' presence and the analog audio
        # are read off the block's positive half spectrum.
        notch_filter = "FcutPAL_half" in rf.Filters
        half = None
        if notch_filter or rf.decode_analog_audio:
            half = np.empty((nb, nrf), dtype=np.complex128)
            cl.enqueue_copy(q, half, X, buffer_origin=(0, 0), host_origin=(0, 0),
                            region=(nrf * 16, nb), buffer_pitches=(n * 16,),
                            host_pitches=(nrf * 16,))
        notch = np.zeros(nb, dtype=np.uint8)
        if notch_filter:
            for i in range(nb):
                notch[i] = bool(rf.pal_audio_carriers_present(half[i]))
        cl.enqueue_copy(q, bufs["notch"], notch)

        # RF high-pass and EFM.
        k["hermitian_product"](q, (n, nb), None, X,
                               self._const("Frfhpf", rf.Filters["Frfhpf_half"]), bufs["R"])
        R = self._fft_n_d.run(q, bufs["R"], bufs["Rs"], nb, inverse=True)
        k["real_f32"](q, (n, nb), None, R, bufs["rfhpf"])
        if rf.decode_digital_audio:
            k["hermitian_product"](q, (n, nb), None, X,
                                   self._const("Fefm", rf.Filters["Fefm_half"]), bufs["R"])
            R = self._fft_n_d.run(q, bufs["R"], bufs["Rs"], nb, inverse=True)
            k["real_s16"](q, (n, nb), None, R, bufs["efm"])

        # The video band and the discriminator.
        fv, fvn = self._video_filters(level)
        fv_buf, fvn_buf = self._const("fv", fv), self._const("fvn", fvn)
        k["video_band"](q, (m, nb), None, X, fv_buf, fvn_buf, bufs["notch"], bufs["H"])
        H = self._fft_m_d.run(q, bufs["H"], bufs["Hs"], nb, inverse=True)
        k["discriminate"](q, (m, nb), None, H,
                          np.float64(rf.freq_hz_demod / TAU), bufs["demod"])

        # The video channels, in single precision about blanking.
        k["centre"](q, (m, nb), None, bufs["demod"], np.float64(1500000.0),
                    np.float64(rf.freq_hz_demod * 0.75),
                    np.float64(rf.Filters["FVideo_rfft_centre"]),
                    bufs["rawout"], bufs["C"])
        S = self._fft_m_f.run(q, bufs["C"], bufs["Cs"], nb)
        F = self._const("FVideo", np.asarray(rf.Filters["FVideo_rfft32"], dtype=np.complex64))
        for ch in range(nch):
            k["video_spectrum"](q, (n, nb), None, S, F, np.int32(ch), np.int32(nch), bufs["Y"])
        Y = self._fft_n_f.run(q, bufs["Y"], bufs["Ys"], nb * nch, inverse=True)
        dc = self._const("dc", np.asarray(rf.Filters["FVideo_rfft_dc"], dtype=np.float32))
        k["video_out"](q, (n, nb, nch), None, Y, dc, np.int32(nch), bufs["video"])

        video = np.empty((nb, nch, n), dtype=np.float32)
        rawout = np.empty((nb, n), dtype=np.float32)
        rfhpf = np.empty((nb, n), dtype=np.float32)
        cl.enqueue_copy(q, video, bufs["video"])
        cl.enqueue_copy(q, rawout, bufs["rawout"])
        cl.enqueue_copy(q, rfhpf, bufs["rfhpf"])
        efm = None
        if rf.decode_digital_audio:
            efm = np.empty((nb, n), dtype=np.int16)
            cl.enqueue_copy(q, efm, bufs["efm"])
        q.finish()

        return [self._assemble(i, video, rawout, rfhpf, efm, half, cut) for i in range(nb)]

    def _assemble(self, i, video, rawout, rfhpf, efm, half, cut):
        """One block's outputs, laid out as demodblock lays them out."""
        rf = self.rf
        n = self.n
        rv = {}
        rotdelay = 0
        if getattr(rf, "delays", None) is not None and "video_rot" in rf.delays:
            rotdelay = rf.delays["video_rot"]
        rv["rfhpf"] = rfhpf[i, rf.blockcut - rotdelay: n - rf.blockcut_end - rotdelay].copy()

        names = ["demod", "demod_raw", "demod_05", "demod_burst"]
        filtered = [("demod", 0), ("demod_05", 1), ("demod_burst", 2)]
        if rf.system == "PAL":
            names.append("demod_pilot")
            filtered.append(("demod_pilot", 3))
        video_out = np.recarray(n, dtype=[(name, np.float32) for name in names])
        video_out["demod_raw"] = rawout[i]
        for name, ch in filtered:
            video_out[name] = video[i, ch]
        rv["video"] = video_out[rf.blockcut: -rf.blockcut_end] if cut else video_out

        if efm is not None:
            e = efm[i]
            rv["efm"] = e[rf.blockcut: -rf.blockcut_end].copy() if cut else e.copy()
        if rf.decode_analog_audio:
            rv["audio"] = rf.audio_stage1(half[i], n, cut)
        rv["setupcount"] = rf.setupcount
        return rv
