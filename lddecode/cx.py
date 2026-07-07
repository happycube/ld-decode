"""CX audio expander (and matching compressor) for ld-decode analog audio.

Implements the decoder for the IEC 60857-1986 Appendix B "AUDIO COMPRESSION
SYSTEM" (CBS CX noise reduction) as a standalone post-processor for the analog
audio .pcm that ld-decode emits, plus the mirror-image encoder used for testing.

The CX encoder is a *feedback* compressor whose control path ("sidechain") is
driven from its own (compressed) output.  The decoder is therefore the exact
mirror: a *feed-forward* expander with an identical control path driven from the
decoder input, applying the reciprocal gain.  Because the sidechain is fed by
the same compressed signal in both directions, tracking is exact by
construction once the control path is faithfully reproduced -- so only the
control path needs to be modelled, and it is modelled once here.

See cx-decoder-plan.md for the full derivation, calibration and test plan.  No
logs/antilogs appear anywhere in the audio path: the VCA is a plain
multiplier, which yields the spec's 2:1 curve automatically (plan sec. 1.1).
"""

import argparse
import logging

import numpy as np
import scipy.signal as sps
from numba import njit

from .filters import emphasis_iir

logger = logging.getLogger(__name__)

# PCM scaling from lddecode/dsp.py:410 -- deviation(Hz) -> int16 counts.
COUNTS_PER_HZ = 32767.0 / 371081.0

# Enumerations for the njit hot loop (strings don't belong in the inner loop).
_COMBINE = {"max": 0, "mean": 1}
_SLOW = {"offset": 0, "switch": 1}
_ATTACK = {"off": 0, "excess": 1, "excess-thresh": 2}
_MODE_PATHS = {"stereo": 1, "bilingual": 2}

# State-array layout (float64, length 16), shared by encoder and decoder.
#   0,1  HPF x[n-1]          (per channel)
#   2,3  HPF h[n-1]          (per channel)
#   4,5  F   fast follower   (per path)
#   6,7  Vcc common cap      (per path)
#   8,9  A   attack comp     (per path)
#  10,11 DC-blocker x[n-1]   (per channel, decode main path)
#  12,13 DC-blocker y[n-1]   (per channel, decode main path)
#  14,15 last V_c            (per path; encoder feedback delay)
_ST_LEN = 16


def deemp_gain_1khz(fs):
    """|D(1 kHz)| for the 75us/5.3us de-emphasis (rfdecode.py:654).

    Computed at runtime from emphasis_iir so this anchor stays consistent if
    the de-emphasis constants ever change (plan sec. 2)."""
    b, a = emphasis_iir(5.3e-6, 75e-6, fs)
    _, h = sps.freqz(b, a, worN=[2 * np.pi * 1000.0 / fs])
    return float(np.abs(h[0]))


def counts_per_khz(fs):
    """int16 PCM counts per kHz of on-disc deviation at 1 kHz (plan sec. 2)."""
    return 1000.0 * deemp_gain_1khz(fs) * COUNTS_PER_HZ


@njit(cache=True, nogil=True)
def _detector_mean(tone, a_hpf, a_fa, a_fr, tail):
    """Mean fast-follower level for a calibration tone (plan sec. 3.6).

    Runs only the HPF + full-wave rectifier + fast attack/release follower --
    with the slow blocks off (thresholds +inf) the common capacitor settles to
    exactly this mean, so it *is* V_CR (or, scaled, R_knee).  Measuring the
    follower directly avoids waiting out the 2 s integrator, whose partial
    settling would otherwise inflate the anchor."""
    hx = 0.0
    hp = 0.0
    F = 0.0
    acc = 0.0
    cnt = 0
    n = tone.shape[0]
    for i in range(n):
        x = tone[i]
        h = a_hpf * (hp + x - hx)
        hx = x
        hp = h
        r = h if h >= 0.0 else -h
        if r > F:
            F = F + a_fa * (r - F)
        else:
            F = F + a_fr * (r - F)
        if i >= n - tail:
            acc += F
            cnt += 1
    return acc / cnt


@njit(cache=True, nogil=True)
def _update_path(
    st, p, r, slow_model, attack_comp, theta_slow, theta_ac,
    a_fa, a_fr, a_sa, a_sr, a_i, beta_ac,
):
    """Advance one control path by one sample; returns V_c for this path.

    ``p`` selects the path's state slot (0 or 1).  ``r`` is the already
    rectified + knee-clamped level driving this path."""
    # Fast attack/release block (quasi-peak follower).
    F = st[4 + p]
    if r > F:
        F = F + a_fa * (r - F)
    else:
        F = F + a_fr * (r - F)
    st[4 + p] = F

    # Slow blocks + integrator all charging the common capacitor Vcc.
    Vcc = st[6 + p]
    e = F - Vcc
    dV = a_i * e
    if slow_model == 0:  # diode-offset: conduction proportional to excess
        if e > theta_slow:
            dV += a_sa * (e - theta_slow)
        elif e < -theta_slow:
            dV += a_sr * (e + theta_slow)
    else:  # switch: conduction proportional to full e once past threshold
        if e > theta_slow:
            dV += a_sa * e
        elif e < -theta_slow:
            dV += a_sr * e
    Vcc = Vcc + dV
    st[6 + p] = Vcc

    # Attack compensator (AC-coupled; ~0 at steady state, bridges the 30 ms
    # slow-attack lag on loud transients).
    A = st[8 + p]
    if attack_comp == 0:
        A = 0.0
    else:
        if F > theta_ac:
            cand = F - Vcc
            if attack_comp == 2:  # excess-minus-threshold variant
                cand = F - Vcc - theta_ac
            decayed = A * beta_ac
            A = cand if cand > decayed else decayed
        else:
            A = A * beta_ac
        if A < 0.0:
            A = 0.0
    st[8 + p] = A

    return Vcc + A


@njit(cache=True, nogil=True)
def _cx_run(
    x, st, encode, npaths, combine, slow_model, attack_comp, dc_block,
    V_100, R_knee, theta_slow, theta_ac,
    a_hpf, a_fa, a_fr, a_sa, a_sr, a_i, beta_ac, a_dc,
):
    """Run the CX sidechain + main path over an interleaved-stereo buffer.

    ``x`` is float64 interleaved [L, R, L, R, ...].  State ``st`` is mutated in
    place so calls can be chained for streaming.  Returns (out, vc_log) where
    ``out`` is float64 interleaved and ``vc_log`` is path-0 V_c per frame."""
    nframes = x.shape[0] // 2
    out = np.empty(nframes * 2, dtype=np.float64)
    vc_log = np.empty(nframes, dtype=np.float64)

    for n in range(nframes):
        xl = x[2 * n]
        xr = x[2 * n + 1]

        if encode:
            # Feedback compressor: gain from V_c reflecting the *previous*
            # output (one-sample delay breaks the algebraic loop).
            yl = xl * (V_100 / st[14])
            yr = xr * (V_100 / st[15])
            out[2 * n] = yl
            out[2 * n + 1] = yr
            fL = yl  # sidechain is fed by the output
            fR = yr
        else:
            fL = xl  # feed-forward expander: sidechain fed by the input
            fR = xr

        # Sidechain 500 Hz high-pass (one-pole/one-zero), per channel.
        h0 = a_hpf * (st[2] + fL - st[0])
        st[0] = fL
        st[2] = h0
        h1 = a_hpf * (st[3] + fR - st[1])
        st[1] = fR
        st[3] = h1

        r0 = h0 if h0 >= 0.0 else -h0  # full-wave rectify
        r1 = h1 if h1 >= 0.0 else -h1

        if npaths == 1:
            # Stereo: combine the two rectifiers into one shared control path.
            if combine == 0:
                rc = r0 if r0 > r1 else r1  # diode-OR
            else:
                rc = 0.5 * (r0 + r1)
            r = rc if rc > R_knee else R_knee
            vcL = _update_path(
                st, 0, r, slow_model, attack_comp, theta_slow, theta_ac,
                a_fa, a_fr, a_sa, a_sr, a_i, beta_ac,
            )
            vcR = vcL
        else:
            # Bilingual: two independent control paths.
            ra = r0 if r0 > R_knee else R_knee
            vcL = _update_path(
                st, 0, ra, slow_model, attack_comp, theta_slow, theta_ac,
                a_fa, a_fr, a_sa, a_sr, a_i, beta_ac,
            )
            rb = r1 if r1 > R_knee else R_knee
            vcR = _update_path(
                st, 1, rb, slow_model, attack_comp, theta_slow, theta_ac,
                a_fa, a_fr, a_sa, a_sr, a_i, beta_ac,
            )

        st[14] = vcL
        st[15] = vcR

        if not encode:
            # Main path: optional DC blocker, then reciprocal gain.
            if dc_block:
                dl = a_dc * (st[12] + xl - st[10])
                st[10] = xl
                st[12] = dl
                dr = a_dc * (st[13] + xr - st[11])
                st[11] = xr
                st[13] = dr
            else:
                dl = xl
                dr = xr
            out[2 * n] = dl * vcL / V_100
            out[2 * n + 1] = dr * vcR / V_100

        vc_log[n] = vcL

    return out, vc_log


class _CXBase:
    """Shared control-path model, calibration and streaming state.

    Subclassed by CXExpander (decoder) and CXCompressor (encoder)."""

    _encode = 0

    def __init__(
        self,
        fs=44100,
        mode="stereo",
        stereo_combine="max",
        slow_model="offset",
        attack_comp="excess",
        dc_block=True,
    ):
        self.fs = fs
        self.mode = mode
        self.npaths = _MODE_PATHS[mode]
        self.combine = _COMBINE[stereo_combine]
        self.slow_model = _SLOW[slow_model]
        self.attack_comp = _ATTACK[attack_comp]
        self.dc_block = 1 if dc_block else 0

        T = 1.0 / fs
        # First-order smoother coefficients alpha(tau) = 1 - exp(-T/tau).
        self.a_fa = 1.0 - np.exp(-T / 1e-3)     # fast attack   1 ms
        self.a_fr = 1.0 - np.exp(-T / 10e-3)    # fast release  10 ms
        self.a_sa = 1.0 - np.exp(-T / 30e-3)    # slow attack   30 ms
        self.a_sr = 1.0 - np.exp(-T / 200e-3)   # slow release  200 ms
        self.a_i = 1.0 - np.exp(-T / 2.0)       # integrator    2 s
        self.beta_ac = np.exp(-T / 30e-3)       # attack-comp decay 30 ms
        self.a_hpf = np.exp(-2 * np.pi * 500.0 / fs)   # sidechain HPF 500 Hz
        self.a_dc = np.exp(-2 * np.pi * 5.0 / fs)      # main DC block 5 Hz

        # Absolute calibration anchor: 40 kHz deviation -> V_CR tone amplitude.
        self.A_40 = 40.0 * counts_per_khz(fs)

        self._calibrate()

        # Persistent streaming state, initialised to the knee (plan sec. 4).
        self.st = np.zeros(_ST_LEN, dtype=np.float64)
        self.st[4:8] = self.R_knee   # F, Vcc
        self.st[14:16] = self.R_knee  # last V_c
        self._warmed = False

    def _calibrate(self):
        """Self-simulate V_CR through the implemented sidechain (plan sec. 3.6).

        Every threshold is a ratio of V_CR, and V_CR includes the detector
        ballistics, so it is measured rather than derived analytically.  With
        the slow blocks disabled (thresholds +inf) the common capacitor settles
        to the mean of the fast follower, which is what we measure."""
        n = int(1.0 * self.fs)
        t = np.arange(n)
        tone = self.A_40 * np.sin(2 * np.pi * 1000.0 * t / self.fs)
        tail = int(0.5 * self.fs)
        self.V_CR = float(
            _detector_mean(tone, self.a_hpf, self.a_fa, self.a_fr, tail)
        )

        # Everything else is a ratio of V_CR (plan sec. 3.6).
        self.V_100 = 2.5 * self.V_CR       # 100 kHz deviation
        self.R_knee = 0.20 * self.V_CR     # 8 kHz clamp floor
        self.theta_slow = 0.26 * self.V_CR
        self.theta_ac = 0.52 * self.V_CR

        # Consistency check: an 8 kHz-equivalent tone (clamp off) must also
        # settle to 0.2*V_CR by linearity (plan sec. 3.6).
        self._check_knee_calibration()

        logger.debug(
            "CX calibrated: V_CR=%.3f V_100=%.3f R_knee=%.3f (fs=%d, %s)",
            self.V_CR, self.V_100, self.R_knee, self.fs, self.mode,
        )

    def _check_knee_calibration(self):
        # An 8 kHz-equivalent tone must settle to 0.2*V_CR by linearity of the
        # detector -- catches any clamp leak into the calibration path.
        n = int(1.0 * self.fs)
        t = np.arange(n)
        A_8 = 8.0 * counts_per_khz(self.fs)
        tone = A_8 * np.sin(2 * np.pi * 1000.0 * t / self.fs)
        tail = int(0.5 * self.fs)
        v8 = float(_detector_mean(tone, self.a_hpf, self.a_fa, self.a_fr, tail))
        rel = v8 / self.R_knee
        if abs(rel - 1.0) > 0.01:
            logger.warning(
                "CX knee calibration off by %.2f%% (8 kHz tone -> %.3f, "
                "expected R_knee=%.3f)", (rel - 1.0) * 100.0, v8, self.R_knee,
            )

    def _run(self, x):
        return _cx_run(
            x, self.st, self._encode, self.npaths, self.combine,
            self.slow_model, self.attack_comp, self.dc_block,
            self.V_100, self.R_knee, self.theta_slow, self.theta_ac,
            self.a_hpf, self.a_fa, self.a_fr, self.a_sa, self.a_sr,
            self.a_i, self.beta_ac, self.a_dc,
        )

    def process(self, pcm):
        """Expand/compress int16 interleaved-stereo PCM; state persists.

        Returns int16 interleaved output.  ``self.last_vc_log`` and
        ``self.last_clipped`` are populated for the analysis notebooks."""
        pcm = np.asarray(pcm)
        if pcm.dtype != np.int16:
            raise ValueError("CX process expects int16 PCM")
        if pcm.size % 2:
            raise ValueError("CX process expects interleaved stereo (even length)")

        x = pcm.astype(np.float64)

        if not self._warmed:
            # Warm up the sidechain over the first <=0.5 s so the 2 s
            # integrator does not audibly settle in-program (plan sec. 4).
            warm = min(int(0.5 * self.fs) * 2, x.size)
            if warm >= 2:
                self._run(x[:warm].copy())
            self._warmed = True

        out, vc_log = self._run(x)
        self.last_vc_log = vc_log / self.V_100

        rounded = np.round(out)
        self.last_clipped = int(np.count_nonzero(np.abs(rounded) > 32766))
        if self.last_clipped:
            logger.warning(
                "CX: %d output samples clipped (disc deviation exceeded "
                "100%% modulation?)", self.last_clipped,
            )
        return np.clip(rounded, -32766, 32766).astype(np.int16)


class CXExpander(_CXBase):
    """CX decoder: feed-forward expander (the normal playback path)."""

    _encode = 0


class CXCompressor(_CXBase):
    """CX encoder: feedback compressor (for round-trip testing only)."""

    _encode = 1


def _main(argv=None):
    ap = argparse.ArgumentParser(
        prog="python3 -m lddecode.cx",
        description="CX audio expander for ld-decode analog audio PCM.",
    )
    ap.add_argument("infile", help="input .pcm (raw int16 LE, interleaved stereo)")
    ap.add_argument("outfile", help="output .pcm (raw int16 LE, interleaved stereo)")
    ap.add_argument("--rate", type=int, default=44100, help="sample rate (Hz)")
    ap.add_argument("--mode", choices=["stereo", "bilingual"], default="stereo")
    ap.add_argument("--stereo-combine", choices=["max", "mean"], default="max")
    ap.add_argument("--slow-model", choices=["offset", "switch"], default="offset")
    ap.add_argument(
        "--attack-comp", choices=["excess", "excess-thresh", "off"],
        default="excess",
    )
    ap.add_argument("--no-dc-block", action="store_true",
                    help="disable the 5 Hz main-path DC blocker")
    ap.add_argument("--encode", action="store_true",
                    help="run the CX compressor instead of the expander (testing)")
    ap.add_argument("--gain-log", metavar="FILE",
                    help="dump per-sample V_c/V_100 (float64) for analysis")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    cls = CXCompressor if args.encode else CXExpander
    cx = cls(
        fs=args.rate,
        mode=args.mode,
        stereo_combine=args.stereo_combine,
        slow_model=args.slow_model,
        attack_comp=args.attack_comp,
        dc_block=not args.no_dc_block,
    )

    pcm = np.fromfile(args.infile, dtype="<i2")
    if pcm.size % 2:
        logger.warning("input has odd sample count; dropping trailing sample")
        pcm = pcm[:-1]

    out = cx.process(pcm)
    out.astype("<i2").tofile(args.outfile)

    if args.gain_log:
        cx.last_vc_log.astype("<f8").tofile(args.gain_log)

    logger.info(
        "CX %s: %d frames, V_CR=%.1f counts, %d clipped -> %s",
        "encode" if args.encode else "expand",
        pcm.size // 2, cx.V_CR, cx.last_clipped, args.outfile,
    )


if __name__ == "__main__":
    _main()
