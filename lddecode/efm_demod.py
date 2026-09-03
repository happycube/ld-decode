"""
efm_demod - symbol-rate timing-recovery demodulator for the LaserDisc EFM signal

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

An alternative to ``efm_pll.EFM_PLL`` for turning the equalised EFM waveform
(int16 at the capture sample rate) into the run-length T values the ``.efm``
output carries.  Where the PLL times zero crossings against a free-running
clock, this demodulator recovers the 4.3218 Mbit/s channel clock itself and
takes one soft decision per channel bit:

1. **Decimation** (``StreamingDecimator``): cascaded half-band FIR stages
   halve the sample rate while it stays >= 8 MHz (40 MHz -> 10 MHz), cutting
   the timing loop's work rate without touching the 0-1.9 MHz EFM band.
2. **Conditioning** (``StreamingConditioner``): a one-pole DC blocker and a
   running-power AGC normalise the waveform to unit RMS so the timing-error
   detector's gain is amplitude-independent.
3. **Timing recovery** (``_TimingCore``): a cubic-interpolating fractional
   resampler emits one soft sample per channel bit; a Mueller & Muller
   timing-error detector updates a second-order proportional-integral loop
   every channel bit (K. H. Mueller and M. Muller, "Timing Recovery in
   Digital Synchronous Data Receivers", IEEE Trans. Comm. COM-24, 1976;
   loop-gain mapping per M. Rice, "Digital Communications: A Discrete-Time
   Approach", Appendix C).
4. **Framing and emission**: NRZI toggles shift into a 24-bit register;
   frame sync is the T11-T11 pattern 0x801002 (IEC 60908 section 9 frame
   sync, also IEC 60857 section 10.1) confirmed by a 588-bit position
   counter with lock hysteresis that flywheels across corrupted syncs.
   Emitted runs are legalised (runs < 3 merged into the following run,
   runs > 11 split) preserving the total channel-bit count, so the ``.efm``
   contract - int8 T values in 3..11 - is unchanged.  Each T value carries a
   uint8 confidence (255 = best) for confidence-packed output; T values inside
   frames that fail the sync/588 check are capped low (erasure candidates).

The architecture follows the timing-recovery design validated by the museld
project (https://github.com/staffanu/museld, GPLv3); the implementation here
is written from the published theory, not copied from museld's code.

All classes are streaming: state is carried across ``process`` calls, so the
output is independent of how the input is chunked.  ``process`` returns a
view into an internal buffer that the next call overwrites (the same
contract as ``EFM_PLL.process``).  Consumed by ``decoder.py`` when
``--efm_demod timing`` is selected.
"""

import numba
import numpy as np

try:
    from numba.experimental import jitclass
except ImportError:
    # Prior to numba 0.49
    from numba import jitclass

# IEC 60908 section 9: EFM channel bit rate, 4.3218 Mbit/s.  IEC 60857
# section 10.1 adopts the same coding for LaserDisc digital sound.
EFM_BIT_RATE_HZ = 4321800.0

# IEC 60908 section 9: the 24-bit frame sync pattern - two maximum-length
# T11 runs followed by the first two channel bits of the merging run.
SYNC_PATTERN = 0x801002
SYNC_MASK = 0xFFFFFF
SYNC_PATTERN_BITS = 24

# IEC 60908 section 9: 588 channel bits per frame; runs are T3..T11.
FRAME_CHANNEL_BITS = 588
T_MIN = 3
T_MAX = 11

# Keep the decimated rate at or above this so the 0-1.9 MHz EFM band and its
# transition edges stay far from the fold-over frequency.
MIN_DECIMATED_RATE_HZ = 8.0e6


def halfband_taps(num_taps=23, beta=8.0):
    """Half-band low-pass FIR taps (Kaiser-windowed ideal half-band).

    Every second tap away from the centre is exactly zero and the DC gain is
    exactly 1.  With the defaults the passband is flat within +/-0.01 dB up
    to 0.10 fs and the stopband (>= 0.40 fs) is below -60 dB, which is what
    the 1.9 MHz EFM band needs at every stage of a >= 8 MHz cascade.

    Returns a fresh float64 array of length ``num_taps`` (must be odd).
    """
    if num_taps % 2 != 1:
        raise ValueError("a half-band filter needs an odd tap count")
    mid = num_taps // 2
    n = np.arange(num_taps) - mid
    taps = 0.5 * np.sinc(n / 2.0) * np.kaiser(num_taps, beta)
    # Exact half-band zeros (the windowed sinc already puts them within
    # rounding of zero; force them so decimation-phase maths is exact).
    taps[(n % 2 == 0) & (n != 0)] = 0.0
    return taps / taps.sum()


def decimation_stages(sample_rate_hz, min_rate_hz=MIN_DECIMATED_RATE_HZ):
    """How many divide-by-two stages keep the output rate >= min_rate_hz.

    40 MHz -> 2 stages (10 MHz); 35 MHz -> 2 (8.75 MHz); 30 MHz -> 1
    (15 MHz, since 7.5 MHz would fall below the floor).
    """
    stages = 0
    rate = float(sample_rate_hz)
    while rate / 2.0 >= min_rate_hz:
        stages += 1
        rate /= 2.0
    return stages


@numba.njit(nogil=True, cache=True)
def _halfband_chunk(ext, i0, lags, coeffs, out_len):
    """Polyphase half-band outputs for one chunk (fixed summation order).

    ``ext`` is the carried (n_taps-1)-sample tail plus the new samples;
    outputs are taken at ext positions i0, i0+2, ... using only the filter's
    non-zero taps.  Each output is an independent fixed-order sum, so the
    result is bit-identical however the stream was chunked.
    """
    y = np.empty(out_len, np.float64)
    n_nz = len(lags)
    for m in range(out_len):
        base = i0 + 2 * m
        acc = 0.0
        for j in range(n_nz):
            acc += coeffs[j] * ext[base - lags[j]]
        y[m] = acc
    return y


class _HalfbandStage:
    """One streaming decimate-by-two stage (polyphase half-band FIR).

    Only the kept (even absolute index) output samples are computed, using
    only the filter's non-zero taps.  All indexing is in absolute stream
    position and the tap summation order is fixed, so the concatenated
    output is bit-identical however the input is chunked.
    """

    def __init__(self, taps):
        self.n_taps = len(taps)
        nonzero = np.flatnonzero(taps != 0.0)
        self._lags = nonzero
        self._coeffs = taps[nonzero].copy()
        self._tail = np.zeros(self.n_taps - 1)
        self._abs_pos = 0  # absolute index of the next input sample

    def process(self, x):
        ext = np.concatenate((self._tail, x))
        # ext[i] is the input sample at absolute index (abs_pos - (n-1) + i);
        # outputs are valid from i = n-1 and we keep even absolute indices.
        start_abs = self._abs_pos - (self.n_taps - 1)
        i0 = self.n_taps - 1
        if (start_abs + i0) % 2 != 0:
            i0 += 1
        out_len = (len(ext) - i0 + 1) // 2
        self._abs_pos += len(x)
        self._tail = ext[-(self.n_taps - 1) :].copy()
        if out_len <= 0:
            return np.zeros(0)
        return _halfband_chunk(ext, i0, self._lags, self._coeffs, out_len)


class StreamingDecimator:
    """Cascaded half-band decimate-by-two stages with carried filter state.

    Feed ``process`` successive chunks of the same stream; the FIR delay
    lines and the decimation phase are carried across calls, so the
    concatenated output is identical however the input is split.
    """

    def __init__(self, sample_rate_hz, min_rate_hz=MIN_DECIMATED_RATE_HZ, num_taps=23, beta=8.0):
        self.sample_rate_hz = float(sample_rate_hz)
        self.stages = decimation_stages(sample_rate_hz, min_rate_hz)
        self.output_rate_hz = self.sample_rate_hz / (2**self.stages)
        self.taps = halfband_taps(num_taps, beta)
        self._stage_filters = [_HalfbandStage(self.taps) for _ in range(self.stages)]

    def process(self, samples):
        """Filter and decimate one chunk. Returns a fresh float64 array."""
        x = np.asarray(samples, dtype=np.float64)
        if x.size == 0:
            return np.zeros(0)
        for stage in self._stage_filters:
            x = stage.process(x)
        return np.ascontiguousarray(x)


@numba.njit(nogil=True, cache=True)
def _condition_chunk(x, dc_pole, dc_x_prev, dc_y_prev, agc_beta, power, floor):
    """DC block + AGC for one chunk; returns (out, carried scalar states)."""
    out = np.empty(len(x), np.float64)
    for i in range(len(x)):
        xv = x[i]
        yv = xv - dc_x_prev + dc_pole * dc_y_prev
        dc_x_prev = xv
        dc_y_prev = yv
        power += agc_beta * (yv * yv - power)
        p = power if power > floor else floor
        out[i] = yv / np.sqrt(p)
    return out, dc_x_prev, dc_y_prev, power


class StreamingConditioner:
    """DC block and running-power AGC, streaming across chunks.

    The DC blocker is a one-pole high-pass (cutoff ``dc_cutoff_hz``); the
    AGC divides by the square root of an exponential moving average of the
    signal power (time constant ``agc_time_s``), normalising the output to
    unit RMS whatever the capture's EFM level.  ``power_init`` seeds the
    power estimate (int16-scale captures sit around 1e6-1e8) and
    ``power_floor`` bounds the gain on silence; both are fixed constants so
    the output is deterministic and chunking-independent.
    """

    def __init__(
        self, sample_rate_hz, dc_cutoff_hz=1000.0, agc_time_s=5e-4, power_init=1e7, power_floor=1.0
    ):
        fs = float(sample_rate_hz)
        self._dc_pole = float(np.exp(-2.0 * np.pi * dc_cutoff_hz / fs))
        self._dc_x_prev = 0.0
        self._dc_y_prev = 0.0
        self._agc_beta = float(1.0 - np.exp(-1.0 / (agc_time_s * fs)))
        self._power = float(power_init)
        self.power_floor = float(power_floor)

    def process(self, samples):
        """Condition one chunk. Returns a fresh float64 array (unit RMS)."""
        x = np.asarray(samples, dtype=np.float64)
        if x.size == 0:
            return np.zeros(0)
        out, self._dc_x_prev, self._dc_y_prev, self._power = _condition_chunk(
            np.ascontiguousarray(x),
            self._dc_pole,
            self._dc_x_prev,
            self._dc_y_prev,
            self._agc_beta,
            self._power,
            self.power_floor,
        )
        return out


def timing_loop_gains(fn_hz, zeta, bit_rate_hz, ted_gain):
    """Proportional/integral gains for the per-bit second-order timing loop.

    Standard continuous-to-discrete mapping (Rice, Appendix C) with the loop
    updating once per channel bit: ``kp = 2*zeta*wn*Tb / ted_gain`` and
    ``ki = (wn*Tb)**2 / ted_gain`` where ``wn = 2*pi*fn`` and ``Tb`` is the
    channel bit period.  ``ted_gain`` is the M&M detector's S-curve slope at
    the operating point (amplitude-normalised by the AGC, scaled by the EFM
    transition density); it calibrates the loop bandwidth, not its sign.
    """
    wn_tb = 2.0 * np.pi * fn_hz / bit_rate_hz
    return 2.0 * zeta * wn_tb / ted_gain, wn_tb * wn_tb / ted_gain


# Fixed capacity of the per-frame pending buffer (T values awaiting a frame
# boundary decision).  Two frames are ~272 runs; 4096 covers long unsynced
# stretches before the overflow flush engages.
PENDING_CAPACITY = 4096

_timing_core_spec = [
    ("step_nominal", numba.float64),
    ("kp", numba.float64),
    ("ki", numba.float64),
    ("kp_acq", numba.float64),
    ("ki_acq", numba.float64),
    ("e_ema", numba.float64),
    ("e_alpha", numba.float64),
    ("acq_enter", numba.float64),
    ("acq_leave", numba.float64),
    ("acquiring", numba.boolean),
    ("prop_limit", numba.float64),
    ("integ_limit", numba.float64),
    ("integrator", numba.float64),
    ("ctl", numba.float64),
    ("mu", numba.float64),
    ("p0", numba.float64),
    ("p1", numba.float64),
    ("p2", numba.float64),
    ("p3", numba.float64),
    ("y_prev", numba.float64),
    ("d_prev", numba.int8),
    ("conf_scale", numba.float64),
    ("conf_lowcap", numba.int64),
    ("run_count", numba.int64),
    ("carry", numba.int64),
    ("run_start_bit", numba.int64),
    ("run_min_abs", numba.float64),
    ("bit_idx", numba.int64),
    ("reg", numba.int64),
    ("locked", numba.boolean),
    ("consec", numba.int64),
    ("miss", numba.int64),
    ("last_match", numba.int64),
    ("expected_match", numba.int64),
    ("prev_boundary", numba.int64),
    ("lock_threshold", numba.int64),
    ("unlock_threshold", numba.int64),
    ("sync_window", numba.int64),
    ("pending_t", numba.int8[:]),
    ("pending_conf", numba.uint8[:]),
    ("pending_start", numba.int64[:]),
    ("pending_n", numba.int64),
    ("out_t", numba.int8[:]),
    ("out_conf", numba.uint8[:]),
    ("out_n", numba.int64),
    ("eq_n", numba.int64),
    ("eq_w", numba.float64[:]),
    ("eq_init", numba.float64[:]),
    ("eq_buf", numba.float64[:]),
    ("eq_mu", numba.float64),
    ("eq_leak", numba.float64),
    ("eq_bound", numba.float64),
]


@numba.njit(nogil=True)
def _consume_nogil(core, samples):
    """Run one chunk through the timing core with the GIL released.

    A jitclass method called from Python holds the GIL for its whole
    run; called from inside this nopython wrapper it does not, so the
    demodulator - which runs on the decoder's output thread when fields
    decode in parallel - stops contending with the commit thread for it.
    The compiled code is the same either way (the wrapper is not
    cacheable, jitclass arguments never are, but its compile subsumes
    the core's own first-call compile)."""
    core.begin()
    if samples.size:
        core.consume(samples)


@jitclass(_timing_core_spec)
class _TimingCore:
    """Per-bit timing loop, framing and T emission (internal, Numba-compiled).

    Consumes conditioned (unit-RMS) samples at the decimated rate and fills
    ``out_t``/``out_conf`` with legalised T values and their confidences.
    All state persists across ``consume`` calls; ``begin`` resets only the
    output cursor, so each call's output is a contiguous new segment.
    """

    def __init__(
        self,
        step_nominal,
        kp,
        ki,
        acq_boost,
        prop_limit,
        integ_limit,
        conf_scale,
        conf_lowcap,
        lock_threshold,
        unlock_threshold,
        sync_window,
        eq_taps,
        eq_mu,
        eq_leak,
        eq_bound,
    ):
        self.step_nominal = step_nominal
        self.kp = kp
        self.ki = ki
        # Acquisition gear: while the timing-error EMA is large (cold start,
        # frequency offset, post-dropout) the loop runs with its natural
        # frequency boosted by acq_boost (kp scales with fn, ki with fn^2),
        # collapsing the second-order pull-in time; once the error settles
        # the tracking gains take over.  Mild hysteresis stops chatter.
        self.kp_acq = kp * acq_boost
        self.ki_acq = ki * acq_boost * acq_boost
        self.e_ema = 1.0
        self.e_alpha = 1.0 / 256.0
        self.acq_enter = 0.40
        self.acq_leave = 0.25
        self.acquiring = True
        self.prop_limit = prop_limit
        self.integ_limit = integ_limit
        self.integrator = 0.0
        self.ctl = 0.0
        # Interpolator history and the next strobe's position relative to the
        # second-oldest sample; bounded, so no float accumulation drift.
        self.mu = 2.0
        self.p0 = 0.0
        self.p1 = 0.0
        self.p2 = 0.0
        self.p3 = 0.0
        self.y_prev = 0.0
        self.d_prev = 1

        self.conf_scale = conf_scale
        self.conf_lowcap = conf_lowcap

        self.run_count = 0
        self.carry = 0
        self.run_start_bit = 1
        self.run_min_abs = 1.0e30

        self.bit_idx = 0
        self.reg = 0
        self.locked = False
        self.consec = 0
        self.miss = 0
        self.last_match = -(1 << 40)
        self.expected_match = -1
        self.prev_boundary = -1
        self.lock_threshold = lock_threshold
        self.unlock_threshold = unlock_threshold
        self.sync_window = sync_window

        self.pending_t = np.empty(PENDING_CAPACITY, np.int8)
        self.pending_conf = np.empty(PENDING_CAPACITY, np.uint8)
        self.pending_start = np.empty(PENDING_CAPACITY, np.int64)
        self.pending_n = 0

        self.out_t = np.empty(1 << 16, np.int8)
        self.out_conf = np.empty(1 << 16, np.uint8)
        self.out_n = 0

        # Decision-directed sign-sign LMS equaliser at symbol rate
        # (eq_taps == 0 bypasses it entirely; the symbol path is then
        # untouched).  Centre-tap-initialised; leakage pulls the taps back
        # toward that identity and a hard per-tap bound keeps a noisy
        # stretch from walking them anywhere unrecoverable.
        self.eq_n = eq_taps
        self.eq_w = np.zeros(max(eq_taps, 1), np.float64)
        self.eq_init = np.zeros(max(eq_taps, 1), np.float64)
        if eq_taps > 0:
            self.eq_w[eq_taps // 2] = 1.0
            self.eq_init[eq_taps // 2] = 1.0
        self.eq_buf = np.zeros(max(eq_taps, 1), np.float64)
        self.eq_mu = eq_mu
        self.eq_leak = eq_leak
        self.eq_bound = eq_bound

    def begin(self):
        """Start a new output segment (the previous segment's view dies)."""
        self.out_n = 0

    def consume(self, samples):
        """Run the timing loop over one chunk of conditioned samples."""
        # T emissions can never outnumber channel bits, and channel bits
        # can never outnumber input samples here (step_nominal > 1), so
        # input length plus a full pending flush bounds this call's output.
        needed = self.out_n + samples.size + PENDING_CAPACITY
        if len(self.out_t) < needed:
            new_t = np.empty(needed * 2, np.int8)
            new_c = np.empty(needed * 2, np.uint8)
            new_t[: self.out_n] = self.out_t[: self.out_n]
            new_c[: self.out_n] = self.out_conf[: self.out_n]
            self.out_t = new_t
            self.out_conf = new_c

        for i in range(samples.size):
            self.p0 = self.p1
            self.p1 = self.p2
            self.p2 = self.p3
            self.p3 = samples[i]
            self.mu -= 1.0
            while self.mu < 1.0:
                f = self.mu
                if f < 0.0:
                    f = 0.0
                # Catmull-Rom cubic between p1 and p2 at fraction f.
                c1 = 0.5 * (self.p2 - self.p0)
                c2 = self.p0 - 2.5 * self.p1 + 2.0 * self.p2 - 0.5 * self.p3
                c3 = 0.5 * (self.p3 - self.p0) + 1.5 * (self.p1 - self.p2)
                y = ((c3 * f + c2) * f + c1) * f + self.p1
                if self.eq_n > 0:
                    y = self._equalise(y)
                self._symbol(y)
                self.mu += self.step_nominal * (1.0 + self.ctl)

    def _equalise(self, y):
        """Sign-sign LMS FIR over the per-bit soft samples (symbol rate).

        Output is centred on the middle tap, so the symbol chain runs
        eq_taps//2 symbols behind the resampler - transparent to framing,
        which is all relative.  The decision-directed error is taken
        against the AGC's unit target; sign-sign updates move each tap a
        fixed eq_mu per symbol, leakage decays the taps toward the
        centre-spike identity, and each tap is hard-bounded around its
        initial value.
        """
        n = self.eq_n
        for j in range(n - 1):
            self.eq_buf[j] = self.eq_buf[j + 1]
        self.eq_buf[n - 1] = y
        acc = 0.0
        for j in range(n):
            acc += self.eq_w[j] * self.eq_buf[j]
        err = acc - (1.0 if acc >= 0.0 else -1.0)
        step = self.eq_mu if err > 0.0 else -self.eq_mu
        for j in range(n):
            w = self.eq_w[j]
            w -= step if self.eq_buf[j] >= 0.0 else -step
            w += self.eq_leak * (self.eq_init[j] - w)
            low = self.eq_init[j] - self.eq_bound
            high = self.eq_init[j] + self.eq_bound
            if w < low:
                w = low
            elif w > high:
                w = high
            self.eq_w[j] = w
        return acc

    def _symbol(self, y):
        """One channel-bit soft sample: TED, loop update, bit and framing."""
        d = 1 if y >= 0.0 else -1

        # Mueller & Muller TED: e = d[k-1]*y[k] - d[k]*y[k-1].  Around an
        # edge this is the sum of the two straddling samples, zero when the
        # strobes are centred; negative means we are sampling late.
        e = self.d_prev * y - d * self.y_prev
        ae = -e if e < 0.0 else e
        self.e_ema += self.e_alpha * (ae - self.e_ema)
        if self.acquiring:
            if self.e_ema < self.acq_leave:
                self.acquiring = False
        elif self.e_ema > self.acq_enter:
            self.acquiring = True
        kp = self.kp_acq if self.acquiring else self.kp
        ki = self.ki_acq if self.acquiring else self.ki
        prop = kp * e
        if prop > self.prop_limit:
            prop = self.prop_limit
        elif prop < -self.prop_limit:
            prop = -self.prop_limit
        self.integrator += ki * e
        if self.integrator > self.integ_limit:
            self.integrator = self.integ_limit
        elif self.integrator < -self.integ_limit:
            self.integrator = -self.integ_limit
        self.ctl = prop + self.integrator

        ay = -y if y < 0.0 else y
        if ay < self.run_min_abs:
            self.run_min_abs = ay

        bit = 1 if d != self.d_prev else 0
        self.d_prev = d
        self.y_prev = y

        if bit == 1:
            # NRZI transition: the completed run ends here; this bit starts
            # the next run.  Legalise: merge < 3 into the following run,
            # split > 11 (progressive emission below keeps rr <= 13 here),
            # always preserving the total channel-bit count.
            rr = self.run_count + self.carry
            self.carry = 0
            conf = self._conf_value()
            if rr >= T_MIN:
                if rr > T_MAX:
                    self._emit(T_MAX, conf, self.run_start_bit)
                    self.carry = rr - T_MAX
                else:
                    self._emit(rr, conf, self.run_start_bit)
            elif rr > 0:
                self.carry = rr
            self.run_count = 1
            self.run_start_bit = self.bit_idx + 1
            self.run_min_abs = ay
        else:
            self.run_count += 1
            if self.run_count + self.carry >= T_MAX + 1:
                # Progressive split inside an over-long run (dropout or
                # missed transition): emit T11 now so the pending buffer
                # and the frame accounting keep flowing.
                self._emit(T_MAX, self._conf_value(), self.run_start_bit)
                self.carry = self.run_count + self.carry - T_MAX
                self.run_count = 0
                self.run_start_bit = self.bit_idx + 1

        self._push_bit(bit)

    def _conf_value(self):
        """Confidence from the weakest soft sample in the run (255 = best)."""
        c = self.run_min_abs / self.conf_scale
        if c > 1.0:
            c = 1.0
        elif c < 0.0:
            c = 0.0
        return np.uint8(255.0 * c)

    def _push_bit(self, bit):
        """Advance the frame-sync state machine by one channel bit."""
        self.bit_idx += 1
        self.reg = ((self.reg << 1) | bit) & SYNC_MASK
        matched = self.reg == SYNC_PATTERN

        if self.locked:
            delta = self.bit_idx - self.expected_match
            if matched and -self.sync_window <= delta <= self.sync_window:
                # Sync where the position counter expected it (within the
                # slip window): close the frame and re-anchor.
                self._accept_boundary(self.bit_idx - (SYNC_PATTERN_BITS - 1), True)
                self.expected_match = self.bit_idx + FRAME_CHANNEL_BITS
                self.miss = 0
            elif delta == self.sync_window + 1:
                # Window closed with no sync: flywheel a boundary at the
                # expected position; unlock after enough consecutive misses.
                boundary = self.expected_match - (SYNC_PATTERN_BITS - 1)
                self._restore_sync(boundary)
                self._accept_boundary(boundary, False)
                self.expected_match += FRAME_CHANNEL_BITS
                self.miss += 1
                if self.miss >= self.unlock_threshold:
                    self.locked = False
                    self.consec = 0
        else:
            if matched:
                if self.bit_idx - self.last_match == FRAME_CHANNEL_BITS:
                    self.consec += 1
                else:
                    self.consec = 1
                self.last_match = self.bit_idx
                if self.consec >= self.lock_threshold:
                    self.locked = True
                    self.miss = 0
                    # Frames seen before lock were never validated.
                    self._accept_boundary(self.bit_idx - (SYNC_PATTERN_BITS - 1), False)
                    self.expected_match = self.bit_idx + FRAME_CHANNEL_BITS

    def _restore_sync(self, boundary_bit):
        """Regenerate a T11-T11 sync the flywheel says must sit at boundary_bit.

        While frame-locked the 588-bit position counter is more reliable than
        a marginal local read, so - like a hardware CD/LaserDisc transport -
        a sync the pattern matcher missed is rewritten from the counter: the
        pending runs spanning the 22 sync channel bits become
        [head, 11, 11, tail], preserving the total channel-bit count.  The
        rewrite happens only when head and tail land on legal run lengths
        (a marginal edge misplaced by a bit or two); anything messier - real
        dropout garbage - is left alone.  Rewritten runs carry low
        confidence: they are counter-backed guesses, not reads.
        """
        first = -1
        last = -1
        for j in range(self.pending_n):
            start = self.pending_start[j]
            if start >= boundary_bit + SYNC_PATTERN_BITS - 1:
                break
            if start + self.pending_t[j] > boundary_bit:
                if first < 0:
                    first = j
                last = j
        if first < 0:
            return
        region_start = self.pending_start[first]
        region_len = 0
        for j in range(first, last + 1):
            region_len += self.pending_t[j]
        head = boundary_bit - region_start
        tail = region_start + region_len - (boundary_bit + 2 * T_MAX)
        if head < 0 or tail < 0:
            return
        if head != 0 and not (T_MIN <= head <= T_MAX):
            return
        if tail != 0 and not (T_MIN <= tail <= T_MAX):
            return
        new_t = np.empty(4, np.int8)
        new_start = np.empty(4, np.int64)
        n_new = 0
        if head:
            new_t[n_new] = head
            new_start[n_new] = region_start
            n_new += 1
        new_t[n_new] = T_MAX
        new_start[n_new] = boundary_bit
        new_t[n_new + 1] = T_MAX
        new_start[n_new + 1] = boundary_bit + T_MAX
        n_new += 2
        if tail:
            new_t[n_new] = tail
            new_start[n_new] = boundary_bit + 2 * T_MAX
            n_new += 1
        n_old = last - first + 1
        shift = n_new - n_old
        if self.pending_n + shift > PENDING_CAPACITY:
            return
        if shift > 0:
            for j in range(self.pending_n - 1, last, -1):
                self.pending_t[j + shift] = self.pending_t[j]
                self.pending_conf[j + shift] = self.pending_conf[j]
                self.pending_start[j + shift] = self.pending_start[j]
        elif shift < 0:
            for j in range(last + 1, self.pending_n):
                self.pending_t[j + shift] = self.pending_t[j]
                self.pending_conf[j + shift] = self.pending_conf[j]
                self.pending_start[j + shift] = self.pending_start[j]
        for j in range(n_new):
            self.pending_t[first + j] = new_t[j]
            self.pending_conf[first + j] = np.uint8(self.conf_lowcap)
            self.pending_start[first + j] = new_start[j]
        self.pending_n += shift

    def _accept_boundary(self, boundary_bit, sync_found):
        """Flush the pending T values that belong to the closing frame."""
        ok = (
            sync_found
            and self.prev_boundary >= 0
            and boundary_bit - self.prev_boundary == FRAME_CHANNEL_BITS
        )
        cut = 0
        while cut < self.pending_n and self.pending_start[cut] < boundary_bit:
            cut += 1
        self._flush(cut, ok)
        self.prev_boundary = boundary_bit

    def _emit(self, t, conf, start_bit):
        """Queue one T value; overflow-flush if no frame boundary arrives."""
        if self.pending_n >= PENDING_CAPACITY:
            # No accepted sync for thousands of runs (EFM gap, dead signal):
            # release the oldest half as unvalidated so output keeps flowing.
            self._flush(PENDING_CAPACITY // 2, False)
        self.pending_t[self.pending_n] = t
        self.pending_conf[self.pending_n] = conf
        self.pending_start[self.pending_n] = start_bit
        self.pending_n += 1

    def final_flush(self):
        """End of stream: release everything still pending, unvalidated."""
        if len(self.out_t) < self.out_n + self.pending_n:
            needed = self.out_n + self.pending_n
            new_t = np.empty(needed, np.int8)
            new_c = np.empty(needed, np.uint8)
            new_t[: self.out_n] = self.out_t[: self.out_n]
            new_c[: self.out_n] = self.out_conf[: self.out_n]
            self.out_t = new_t
            self.out_conf = new_c
        self._flush(self.pending_n, False)

    def _flush(self, count, frame_ok):
        """Move the oldest ``count`` pending T values to the output buffers.

        A frame that failed the sync/588 check (or was never validated) has
        its confidences capped at ``conf_lowcap`` - those T values are the
        downstream erasure candidates.
        """
        for j in range(count):
            conf = self.pending_conf[j]
            if not frame_ok and conf > self.conf_lowcap:
                conf = np.uint8(self.conf_lowcap)
            self.out_t[self.out_n] = self.pending_t[j]
            self.out_conf[self.out_n] = conf
            self.out_n += 1
        for j in range(count, self.pending_n):
            self.pending_t[j - count] = self.pending_t[j]
            self.pending_conf[j - count] = self.pending_conf[j]
            self.pending_start[j - count] = self.pending_start[j]
        self.pending_n -= count


class EFMTimingDemod:
    """Streaming EFM demodulator: decimate, condition, recover, frame.

    Drop-in alternative to ``efm_pll.EFM_PLL`` for ``decoder._process_efm``:
    ``process`` takes one chunk of the equalised EFM waveform (int16 at
    ``sample_rate_hz``) and returns the T values recovered from it as an
    int8 view that the next call overwrites; ``conf_view`` returns the
    parallel uint8 confidences (always 1:1 with the last ``process``
    result).  Feed chunks strictly in stream order.

    Up to one frame of T values sits in the framing buffer awaiting the
    next sync; call ``flush`` once at end of stream to drain it (the tail
    frame can never be validated, so it flushes with low confidence).

    Loop constants are exposed as constructor parameters; the defaults are
    fn = 1.2 kHz, zeta = 0.6 with per-symbol/integrator corrections clamped
    to 2 % / 4 % of the nominal step, and lock hysteresis of 7 frames.
    """

    def __init__(
        self,
        sample_rate_hz,
        bit_rate_hz=EFM_BIT_RATE_HZ,
        fn_hz=1200.0,
        zeta=0.6,
        ted_gain=0.5,
        acq_boost=6.0,
        prop_limit_frac=0.02,
        integ_limit_frac=0.04,
        lock_frames=7,
        sync_window_bits=2,
        conf_scale=0.5,
        conf_lowcap=64,
        eq_taps=0,
        eq_mu=1e-4,
        eq_leak=1e-5,
        eq_bound=0.5,
    ):
        if eq_taps != 0 and (eq_taps % 2 != 1 or not 3 <= eq_taps <= 15):
            raise ValueError("eq_taps must be 0 (off) or an odd count in 3..15")
        self.sample_rate_hz = float(sample_rate_hz)
        self.bit_rate_hz = float(bit_rate_hz)
        self.decimator = StreamingDecimator(sample_rate_hz)
        self.conditioner = StreamingConditioner(self.decimator.output_rate_hz)
        kp, ki = timing_loop_gains(fn_hz, zeta, bit_rate_hz, ted_gain)
        step_nominal = self.decimator.output_rate_hz / self.bit_rate_hz
        self.core = _TimingCore(
            step_nominal,
            kp,
            ki,
            acq_boost,
            prop_limit_frac,
            integ_limit_frac,
            conf_scale,
            conf_lowcap,
            lock_frames,
            lock_frames,
            sync_window_bits,
            eq_taps,
            eq_mu,
            eq_leak,
            eq_bound,
        )

    def process(self, input_buffer):
        """Demodulate one chunk of int16 EFM waveform.

        Returns an int8 view of the T values completed by this chunk (the
        next call overwrites it); the caller must copy to keep it.  The
        input array is not modified.
        """
        conditioned = self.conditioner.process(self.decimator.process(np.asarray(input_buffer)))
        _consume_nogil(self.core, conditioned)
        return self.core.out_t[: self.core.out_n]

    def flush(self):
        """Drain the T values still awaiting a frame boundary (end of stream).

        Returns them as an int8 view; ``conf_view`` afterwards returns their
        (low-capped) confidences.  Idempotent: a second call returns empty.
        """
        self.core.begin()
        self.core.final_flush()
        return self.core.out_t[: self.core.out_n]

    def conf_view(self):
        """uint8 confidences, 1:1 with the last ``process`` result (a view)."""
        return self.core.out_conf[: self.core.out_n]
