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
3. **Timing recovery** (``_consume`` / ``_symbol``): a cubic-interpolating fractional
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
   contract - int8 T values in 3..11 - is unchanged.
5. **Confidence**: each T value carries a uint8 confidence (255 = best) for
   confidence-packed output, from four sources, weakest wins:

   * *amplitude* - the weakest soft sample in the run against ``conf_scale``;
   * *timing* - the worse of the two edges bounding the run, measured as the
     normalised Mueller & Muller error, so a full-height run whose length was
     a coin toss is distrusted where the amplitude term alone sees nothing;
   * *fabrication* - a T value the legaliser invented rather than read (a run
     merged forward, a run split, or the remainder either leaves behind) is
     capped at ``conf_legalised``, and runs the flywheel rewrote at a restored
     sync are capped at ``conf_restored``.  Both are certain knowledge that
     the channel did not show what was emitted;
   * *validation* - every T value in a frame that fails the sync/588 check is
     capped at ``conf_lowcap``.

   The caps are ordered: fabrication is a per-symbol certainty and outranks
   whole-frame validation, which flags a whole frame for the sake of the few
   symbols in it that are actually wrong.

The architecture follows the timing-recovery design validated by the museld
project (https://github.com/staffanu/museld, GPLv3); the implementation here
is written from the published theory, not copied from museld's code.

All classes are streaming: state is carried across ``process`` calls, so the
output is independent of how the input is chunked.  ``process`` returns a
view into an internal buffer that the next call overwrites (the same
contract as ``EFM_PLL.process``).  Consumed by ``decoder.py`` as the default
EFM demodulator (``--efm_demod pll`` selects the previous ``EFM_PLL``).
"""

import numba
import numpy as np

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

# Confidence ceilings, in the 0-255 scale an .efm packs as
# ``doubt = 15 - (conf >> 4)``.  A fabricated T value (doubt 14) and a
# flywheel-rewritten sync run (doubt 15) are per-symbol certainties and sit
# above any sane erasure threshold; an unvalidated frame (doubt 8) flags all
# 74 of its T values for the sake of the few that are wrong, so it sits
# below one.
CONF_LOWCAP = 112
CONF_LEGALISED = 16
CONF_RESTORED = 0

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

# The timing core's state, held in plain arrays so every function that
# touches it can be cached on disk.  It used to be a Numba jitclass, which
# Numba cannot cache: every process paid ~7 s compiling it (2 s to build the
# type, 5 s on the first chunk) before the first T value came out.  Scalars
# live in one float64 and one int64 array, indexed by the names below
# (booleans as 0/1); the pending and output buffers and the equaliser taps
# are arrays of their own.  The functions below are the jitclass's methods
# with ``self.x`` spelled ``fs[_F_X]`` / ``iv[_I_X]`` and the arithmetic
# unchanged, operation for operation, so the T values and confidences are
# bit-identical to what the jitclass produced.
_F_STEP_NOMINAL = 0
_F_KP = 1
_F_KI = 2
_F_KP_ACQ = 3
_F_KI_ACQ = 4
_F_E_EMA = 5
_F_E_ALPHA = 6
_F_ACQ_ENTER = 7
_F_ACQ_LEAVE = 8
_F_PROP_LIMIT = 9
_F_INTEG_LIMIT = 10
_F_INTEGRATOR = 11
_F_CTL = 12
_F_MU = 13
_F_P0 = 14
_F_P1 = 15
_F_P2 = 16
_F_P3 = 17
_F_Y_PREV = 18
_F_CONF_SCALE = 19
_F_TIMING_SCALE = 20
_F_RUN_MIN_ABS = 21
_F_RUN_EDGE_MIN = 22
_F_EQ_MU = 23
_F_EQ_LEAK = 24
_F_EQ_BOUND = 25
_F_COUNT = 26

_I_ACQUIRING = 0
_I_D_PREV = 1
_I_CONF_LOWCAP = 2
_I_CONF_LEGALISED = 3
_I_CONF_RESTORED = 4
_I_RESTORE_SYNC = 5
_I_RUN_COUNT = 6
_I_CARRY = 7
_I_RUN_START_BIT = 8
_I_BIT_IDX = 9
_I_REG = 10
_I_LOCKED = 11
_I_CONSEC = 12
_I_MISS = 13
_I_LAST_MATCH = 14
_I_EXPECTED_MATCH = 15
_I_PREV_BOUNDARY = 16
_I_LOCK_THRESHOLD = 17
_I_UNLOCK_THRESHOLD = 18
_I_SYNC_WINDOW = 19
_I_PENDING_N = 20
_I_OUT_N = 21
_I_EQ_N = 22
_I_COUNT = 23


@numba.njit(nogil=True, cache=True)
def _equalise(fs, iv, eq_w, eq_init, eq_buf, y):
    """Sign-sign LMS FIR over the per-bit soft samples (symbol rate).

    Output is centred on the middle tap, so the symbol chain runs
    eq_taps//2 symbols behind the resampler - transparent to framing,
    which is all relative.  The decision-directed error is taken
    against the AGC's unit target; sign-sign updates move each tap a
    fixed eq_mu per symbol, leakage decays the taps toward the
    centre-spike identity, and each tap is hard-bounded around its
    initial value.
    """
    n = iv[_I_EQ_N]
    for j in range(n - 1):
        eq_buf[j] = eq_buf[j + 1]
    eq_buf[n - 1] = y
    acc = 0.0
    for j in range(n):
        acc += eq_w[j] * eq_buf[j]
    err = acc - (1.0 if acc >= 0.0 else -1.0)
    step = fs[_F_EQ_MU] if err > 0.0 else -fs[_F_EQ_MU]
    for j in range(n):
        w = eq_w[j]
        w -= step if eq_buf[j] >= 0.0 else -step
        w += fs[_F_EQ_LEAK] * (eq_init[j] - w)
        low = eq_init[j] - fs[_F_EQ_BOUND]
        high = eq_init[j] + fs[_F_EQ_BOUND]
        if w < low:
            w = low
        elif w > high:
            w = high
        eq_w[j] = w
    return acc


@numba.njit(nogil=True, cache=True)
def _conf_value(fs, edge_margin):
    """Confidence for one run: the worse of its amplitude and timing margins.

    Amplitude is the weakest soft sample in the run against
    ``conf_scale``; timing is the worse of the two edges bounding it
    against ``timing_scale``.  Amplitude alone cannot see the failure
    that matters here - a full-height run one channel bit adrift decodes
    to a legal but wrong symbol, and reaches the CIRC stages disguised
    as good data.
    """
    c = fs[_F_RUN_MIN_ABS] / fs[_F_CONF_SCALE]
    t = edge_margin / fs[_F_TIMING_SCALE]
    if t < c:
        c = t
    if c > 1.0:
        c = 1.0
    elif c < 0.0:
        c = 0.0
    return np.uint8(255.0 * c)


@numba.njit(nogil=True, cache=True)
def _fabricated(iv, conf):
    """Cap a T value the legaliser invented rather than read."""
    if conf > iv[_I_CONF_LEGALISED]:
        return np.uint8(iv[_I_CONF_LEGALISED])
    return conf


@numba.njit(nogil=True, cache=True)
def _flush(iv, pending_t, pending_conf, pending_start, out_t, out_conf, count, frame_ok):
    """Move the oldest ``count`` pending T values to the output buffers.

    A frame that failed the sync/588 check (or was never validated) has
    its confidences capped at ``conf_lowcap`` - those T values are the
    downstream erasure candidates.  The caller guarantees the output
    buffers have room.
    """
    out_n = iv[_I_OUT_N]
    for j in range(count):
        conf = pending_conf[j]
        if not frame_ok and conf > iv[_I_CONF_LOWCAP]:
            conf = np.uint8(iv[_I_CONF_LOWCAP])
        out_t[out_n] = pending_t[j]
        out_conf[out_n] = conf
        out_n += 1
    iv[_I_OUT_N] = out_n
    pending_n = iv[_I_PENDING_N]
    for j in range(count, pending_n):
        pending_t[j - count] = pending_t[j]
        pending_conf[j - count] = pending_conf[j]
        pending_start[j - count] = pending_start[j]
    iv[_I_PENDING_N] = pending_n - count


@numba.njit(nogil=True, cache=True)
def _emit(iv, pending_t, pending_conf, pending_start, out_t, out_conf, t, conf, start_bit):
    """Queue one T value; overflow-flush if no frame boundary arrives."""
    if iv[_I_PENDING_N] >= PENDING_CAPACITY:
        # No accepted sync for thousands of runs (EFM gap, dead signal):
        # release the oldest half as unvalidated so output keeps flowing.
        _flush(
            iv, pending_t, pending_conf, pending_start, out_t, out_conf,
            PENDING_CAPACITY // 2, False,
        )
    n = iv[_I_PENDING_N]
    pending_t[n] = t
    pending_conf[n] = conf
    pending_start[n] = start_bit
    iv[_I_PENDING_N] = n + 1


@numba.njit(nogil=True, cache=True)
def _restore_sync(iv, pending_t, pending_conf, pending_start, boundary_bit):
    """Regenerate a T11-T11 sync the flywheel says must sit at boundary_bit.

    While frame-locked the 588-bit position counter is more reliable than
    a marginal local read, so - like a hardware CD/LaserDisc transport -
    a sync the pattern matcher missed is rewritten from the counter: the
    pending runs spanning the 22 sync channel bits become
    [head, 11, 11, tail], preserving the total channel-bit count.  The
    rewrite happens only when head and tail land on legal run lengths
    (a marginal edge misplaced by a bit or two); anything messier - real
    dropout garbage - is left alone.  Rewritten runs carry
    ``conf_restored``: they are counter-backed guesses, not reads, and
    the consumer should treat them as erasures rather than data.
    """
    pending_n = iv[_I_PENDING_N]
    first = -1
    last = -1
    for j in range(pending_n):
        start = pending_start[j]
        if start >= boundary_bit + SYNC_PATTERN_BITS - 1:
            break
        if start + pending_t[j] > boundary_bit:
            if first < 0:
                first = j
            last = j
    if first < 0:
        return
    region_start = pending_start[first]
    region_len = 0
    for j in range(first, last + 1):
        region_len += pending_t[j]
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
    if pending_n + shift > PENDING_CAPACITY:
        return
    if shift > 0:
        for j in range(pending_n - 1, last, -1):
            pending_t[j + shift] = pending_t[j]
            pending_conf[j + shift] = pending_conf[j]
            pending_start[j + shift] = pending_start[j]
    elif shift < 0:
        for j in range(last + 1, pending_n):
            pending_t[j + shift] = pending_t[j]
            pending_conf[j + shift] = pending_conf[j]
            pending_start[j + shift] = pending_start[j]
    for j in range(n_new):
        pending_t[first + j] = new_t[j]
        pending_conf[first + j] = np.uint8(iv[_I_CONF_RESTORED])
        pending_start[first + j] = new_start[j]
    iv[_I_PENDING_N] = pending_n + shift


@numba.njit(nogil=True, cache=True)
def _accept_boundary(iv, pending_t, pending_conf, pending_start, out_t, out_conf,
                     boundary_bit, sync_found):
    """Flush the pending T values that belong to the closing frame."""
    ok = (
        sync_found
        and iv[_I_PREV_BOUNDARY] >= 0
        and boundary_bit - iv[_I_PREV_BOUNDARY] == FRAME_CHANNEL_BITS
    )
    cut = 0
    while cut < iv[_I_PENDING_N] and pending_start[cut] < boundary_bit:
        cut += 1
    _flush(iv, pending_t, pending_conf, pending_start, out_t, out_conf, cut, ok)
    iv[_I_PREV_BOUNDARY] = boundary_bit


@numba.njit(nogil=True, cache=True)
def _push_bit(iv, pending_t, pending_conf, pending_start, out_t, out_conf, bit):
    """Advance the frame-sync state machine by one channel bit."""
    bit_idx = iv[_I_BIT_IDX] + 1
    iv[_I_BIT_IDX] = bit_idx
    reg = ((iv[_I_REG] << 1) | bit) & SYNC_MASK
    iv[_I_REG] = reg
    matched = reg == SYNC_PATTERN

    if iv[_I_LOCKED]:
        delta = bit_idx - iv[_I_EXPECTED_MATCH]
        window = iv[_I_SYNC_WINDOW]
        if matched and -window <= delta <= window:
            # Sync where the position counter expected it (within the
            # slip window): close the frame and re-anchor.
            _accept_boundary(
                iv, pending_t, pending_conf, pending_start, out_t, out_conf,
                bit_idx - (SYNC_PATTERN_BITS - 1), True,
            )
            iv[_I_EXPECTED_MATCH] = bit_idx + FRAME_CHANNEL_BITS
            iv[_I_MISS] = 0
        elif delta == window + 1:
            # Window closed with no sync: flywheel a boundary at the
            # expected position; unlock after enough consecutive misses.
            boundary = iv[_I_EXPECTED_MATCH] - (SYNC_PATTERN_BITS - 1)
            if iv[_I_RESTORE_SYNC]:
                _restore_sync(iv, pending_t, pending_conf, pending_start, boundary)
            _accept_boundary(
                iv, pending_t, pending_conf, pending_start, out_t, out_conf,
                boundary, False,
            )
            iv[_I_EXPECTED_MATCH] += FRAME_CHANNEL_BITS
            iv[_I_MISS] += 1
            if iv[_I_MISS] >= iv[_I_UNLOCK_THRESHOLD]:
                iv[_I_LOCKED] = 0
                iv[_I_CONSEC] = 0
    else:
        if matched:
            if bit_idx - iv[_I_LAST_MATCH] == FRAME_CHANNEL_BITS:
                iv[_I_CONSEC] += 1
            else:
                iv[_I_CONSEC] = 1
            iv[_I_LAST_MATCH] = bit_idx
            if iv[_I_CONSEC] >= iv[_I_LOCK_THRESHOLD]:
                iv[_I_LOCKED] = 1
                iv[_I_MISS] = 0
                # Frames seen before lock were never validated.
                _accept_boundary(
                    iv, pending_t, pending_conf, pending_start, out_t, out_conf,
                    bit_idx - (SYNC_PATTERN_BITS - 1), False,
                )
                iv[_I_EXPECTED_MATCH] = bit_idx + FRAME_CHANNEL_BITS


@numba.njit(nogil=True, cache=True)
def _symbol(fs, iv, pending_t, pending_conf, pending_start, out_t, out_conf, y):
    """One channel-bit soft sample: TED, loop update, bit and framing."""
    d = 1 if y >= 0.0 else -1
    d_prev = iv[_I_D_PREV]
    y_prev = fs[_F_Y_PREV]

    # Mueller & Muller TED: e = d[k-1]*y[k] - d[k]*y[k-1].  Around an
    # edge this is the sum of the two straddling samples, zero when the
    # strobes are centred; negative means we are sampling late.
    e = d_prev * y - d * y_prev
    ae = -e if e < 0.0 else e
    fs[_F_E_EMA] += fs[_F_E_ALPHA] * (ae - fs[_F_E_EMA])
    if iv[_I_ACQUIRING]:
        if fs[_F_E_EMA] < fs[_F_ACQ_LEAVE]:
            iv[_I_ACQUIRING] = 0
    elif fs[_F_E_EMA] > fs[_F_ACQ_ENTER]:
        iv[_I_ACQUIRING] = 1
    kp = fs[_F_KP_ACQ] if iv[_I_ACQUIRING] else fs[_F_KP]
    ki = fs[_F_KI_ACQ] if iv[_I_ACQUIRING] else fs[_F_KI]
    prop = kp * e
    if prop > fs[_F_PROP_LIMIT]:
        prop = fs[_F_PROP_LIMIT]
    elif prop < -fs[_F_PROP_LIMIT]:
        prop = -fs[_F_PROP_LIMIT]
    integrator = fs[_F_INTEGRATOR] + ki * e
    if integrator > fs[_F_INTEG_LIMIT]:
        integrator = fs[_F_INTEG_LIMIT]
    elif integrator < -fs[_F_INTEG_LIMIT]:
        integrator = -fs[_F_INTEG_LIMIT]
    fs[_F_INTEGRATOR] = integrator
    fs[_F_CTL] = prop + integrator

    ay = -y if y < 0.0 else y
    if ay < fs[_F_RUN_MIN_ABS]:
        fs[_F_RUN_MIN_ABS] = ay

    bit = 1 if d != d_prev else 0
    if bit == 1:
        # Edge timing margin.  Across a transition d = -d_prev, so the
        # TED reduces to |e| = ||y| - |y_prev||: the imbalance of the two
        # samples straddling the crossing.  Normalised by their sum it is
        # level-independent - 1.0 when the crossing sits midway between
        # the strobes, 0.0 when it sits on one of them and the run length
        # is a coin toss between two legal values.
        ap = -y_prev if y_prev < 0.0 else y_prev
        span = ay + ap
        em = 1.0 - ae / span if span > 0.0 else 0.0
    else:
        em = 1.0
    iv[_I_D_PREV] = d
    fs[_F_Y_PREV] = y

    if bit == 1:
        # NRZI transition: the completed run ends here; this bit starts
        # the next run.  Legalise: merge < 3 into the following run,
        # split > 11 (progressive emission below keeps rr <= 13 here),
        # always preserving the total channel-bit count.
        edge = fs[_F_RUN_EDGE_MIN]
        if em < edge:
            edge = em
        rr = iv[_I_RUN_COUNT] + iv[_I_CARRY]
        # A non-zero carry means this run absorbed the remainder of an
        # earlier legalisation: its length is invented, not read.
        merged = iv[_I_CARRY] != 0
        iv[_I_CARRY] = 0
        conf = _conf_value(fs, edge)
        start = iv[_I_RUN_START_BIT]
        next_start = iv[_I_BIT_IDX] + 1
        next_min = ay
        next_edge = em
        if rr >= T_MIN:
            if rr > T_MAX:
                _emit(
                    iv, pending_t, pending_conf, pending_start, out_t, out_conf,
                    T_MAX, _fabricated(iv, conf), start,
                )
                iv[_I_CARRY] = rr - T_MAX
                # The remainder continues the same physical run, so it
                # keeps its start, its weakest sample and its margins.
                next_start = start + T_MAX
                next_min = fs[_F_RUN_MIN_ABS]
                next_edge = edge
            else:
                _emit(
                    iv, pending_t, pending_conf, pending_start, out_t, out_conf,
                    rr, _fabricated(iv, conf) if merged else conf, start,
                )
        elif rr > 0:
            iv[_I_CARRY] = rr
            next_start = start
            next_min = fs[_F_RUN_MIN_ABS]
            next_edge = edge
        iv[_I_RUN_COUNT] = 1
        iv[_I_RUN_START_BIT] = next_start
        fs[_F_RUN_MIN_ABS] = next_min
        fs[_F_RUN_EDGE_MIN] = next_edge
    else:
        iv[_I_RUN_COUNT] += 1
        if iv[_I_RUN_COUNT] + iv[_I_CARRY] >= T_MAX + 1:
            # Progressive split inside an over-long run (dropout or
            # missed transition): emit T11 now so the pending buffer
            # and the frame accounting keep flowing.  The boundary is
            # invented, so this T11 and the remainder are both suspect.
            _emit(
                iv, pending_t, pending_conf, pending_start, out_t, out_conf,
                T_MAX, _fabricated(iv, _conf_value(fs, fs[_F_RUN_EDGE_MIN])),
                iv[_I_RUN_START_BIT],
            )
            iv[_I_CARRY] = iv[_I_RUN_COUNT] + iv[_I_CARRY] - T_MAX
            iv[_I_RUN_COUNT] = 0
            iv[_I_RUN_START_BIT] = iv[_I_BIT_IDX] + 1

    _push_bit(iv, pending_t, pending_conf, pending_start, out_t, out_conf, bit)


@numba.njit(nogil=True, cache=True)
def _consume(fs, iv, pending_t, pending_conf, pending_start, out_t, out_conf,
             eq_w, eq_init, eq_buf, samples):
    """Run the timing loop over one chunk of conditioned samples.

    nogil: called from Python it releases the GIL for the whole chunk, so
    the demodulator - which runs on the decoder's output thread when
    fields decode in parallel - does not contend with the commit thread.
    The output buffers must already have room for this chunk's T values
    (see _TimingCore.consume).
    """
    for i in range(samples.size):
        fs[_F_P0] = fs[_F_P1]
        fs[_F_P1] = fs[_F_P2]
        fs[_F_P2] = fs[_F_P3]
        fs[_F_P3] = samples[i]
        fs[_F_MU] -= 1.0
        while fs[_F_MU] < 1.0:
            p0 = fs[_F_P0]
            p1 = fs[_F_P1]
            p2 = fs[_F_P2]
            p3 = fs[_F_P3]
            f = fs[_F_MU]
            if f < 0.0:
                f = 0.0
            # Catmull-Rom cubic between p1 and p2 at fraction f.
            c1 = 0.5 * (p2 - p0)
            c2 = p0 - 2.5 * p1 + 2.0 * p2 - 0.5 * p3
            c3 = 0.5 * (p3 - p0) + 1.5 * (p1 - p2)
            y = ((c3 * f + c2) * f + c1) * f + p1
            if iv[_I_EQ_N] > 0:
                y = _equalise(fs, iv, eq_w, eq_init, eq_buf, y)
            _symbol(fs, iv, pending_t, pending_conf, pending_start, out_t, out_conf, y)
            fs[_F_MU] += fs[_F_STEP_NOMINAL] * (1.0 + fs[_F_CTL])


class _TimingCore:
    """Per-bit timing loop, framing and T emission (internal).

    Holds the state the module's compiled functions work on: consumes
    conditioned (unit-RMS) samples at the decimated rate and fills
    ``out_t``/``out_conf`` with legalised T values and their confidences.
    All state persists across ``consume`` calls; ``begin`` resets only the
    output cursor, so each call's output is a contiguous new segment.
    Not thread-safe: one stream, fed from one thread at a time.
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
        timing_scale,
        conf_lowcap,
        conf_legalised,
        conf_restored,
        restore_sync,
        lock_threshold,
        unlock_threshold,
        sync_window,
        eq_taps,
        eq_mu,
        eq_leak,
        eq_bound,
    ):
        fs = np.zeros(_F_COUNT, np.float64)
        iv = np.zeros(_I_COUNT, np.int64)
        fs[_F_STEP_NOMINAL] = step_nominal
        fs[_F_KP] = kp
        fs[_F_KI] = ki
        # Acquisition gear: while the timing-error EMA is large (cold start,
        # frequency offset, post-dropout) the loop runs with its natural
        # frequency boosted by acq_boost (kp scales with fn, ki with fn^2),
        # collapsing the second-order pull-in time; once the error settles
        # the tracking gains take over.  Mild hysteresis stops chatter.
        fs[_F_KP_ACQ] = kp * acq_boost
        fs[_F_KI_ACQ] = ki * acq_boost * acq_boost
        fs[_F_E_EMA] = 1.0
        fs[_F_E_ALPHA] = 1.0 / 256.0
        fs[_F_ACQ_ENTER] = 0.40
        fs[_F_ACQ_LEAVE] = 0.25
        iv[_I_ACQUIRING] = 1
        fs[_F_PROP_LIMIT] = prop_limit
        fs[_F_INTEG_LIMIT] = integ_limit
        # Interpolator history and the next strobe's position relative to the
        # second-oldest sample; bounded, so no float accumulation drift.
        fs[_F_MU] = 2.0
        iv[_I_D_PREV] = 1

        fs[_F_CONF_SCALE] = conf_scale
        fs[_F_TIMING_SCALE] = timing_scale
        iv[_I_CONF_LOWCAP] = conf_lowcap
        iv[_I_CONF_LEGALISED] = conf_legalised
        iv[_I_CONF_RESTORED] = conf_restored
        iv[_I_RESTORE_SYNC] = int(bool(restore_sync))

        iv[_I_RUN_START_BIT] = 1
        fs[_F_RUN_MIN_ABS] = 1.0e30
        fs[_F_RUN_EDGE_MIN] = 1.0

        iv[_I_LAST_MATCH] = -(1 << 40)
        iv[_I_EXPECTED_MATCH] = -1
        iv[_I_PREV_BOUNDARY] = -1
        iv[_I_LOCK_THRESHOLD] = lock_threshold
        iv[_I_UNLOCK_THRESHOLD] = unlock_threshold
        iv[_I_SYNC_WINDOW] = sync_window
        self.fs = fs
        self.iv = iv

        self.pending_t = np.empty(PENDING_CAPACITY, np.int8)
        self.pending_conf = np.empty(PENDING_CAPACITY, np.uint8)
        self.pending_start = np.empty(PENDING_CAPACITY, np.int64)

        self.out_t = np.empty(1 << 16, np.int8)
        self.out_conf = np.empty(1 << 16, np.uint8)

        # Decision-directed sign-sign LMS equaliser at symbol rate
        # (eq_taps == 0 bypasses it entirely; the symbol path is then
        # untouched).  Centre-tap-initialised; leakage pulls the taps back
        # toward that identity and a hard per-tap bound keeps a noisy
        # stretch from walking them anywhere unrecoverable.
        iv[_I_EQ_N] = eq_taps
        self.eq_w = np.zeros(max(eq_taps, 1), np.float64)
        self.eq_init = np.zeros(max(eq_taps, 1), np.float64)
        if eq_taps > 0:
            self.eq_w[eq_taps // 2] = 1.0
            self.eq_init[eq_taps // 2] = 1.0
        self.eq_buf = np.zeros(max(eq_taps, 1), np.float64)
        fs[_F_EQ_MU] = eq_mu
        fs[_F_EQ_LEAK] = eq_leak
        fs[_F_EQ_BOUND] = eq_bound

    @property
    def out_n(self):
        return int(self.iv[_I_OUT_N])

    @property
    def pending_n(self):
        return int(self.iv[_I_PENDING_N])

    def begin(self):
        """Start a new output segment (the previous segment's view dies)."""
        self.iv[_I_OUT_N] = 0

    def _reserve(self, needed, spare):
        """Grow the output buffers to hold ``needed`` T values, keeping the
        current segment; ``spare`` is the growth factor."""
        if len(self.out_t) < needed:
            out_n = self.out_n
            new_t = np.empty(needed * spare, np.int8)
            new_c = np.empty(needed * spare, np.uint8)
            new_t[:out_n] = self.out_t[:out_n]
            new_c[:out_n] = self.out_conf[:out_n]
            self.out_t = new_t
            self.out_conf = new_c

    def consume(self, samples):
        """Run the timing loop over one chunk of conditioned samples."""
        # T emissions can never outnumber channel bits, and channel bits
        # can never outnumber input samples here (step_nominal > 1), so
        # input length plus a full pending flush bounds this call's output.
        self._reserve(self.out_n + samples.size + PENDING_CAPACITY, 2)
        _consume(
            self.fs, self.iv, self.pending_t, self.pending_conf, self.pending_start,
            self.out_t, self.out_conf, self.eq_w, self.eq_init, self.eq_buf,
            samples,
        )

    def _equalise(self, y):
        """One symbol through the equaliser (exposed for its unit tests)."""
        return _equalise(self.fs, self.iv, self.eq_w, self.eq_init, self.eq_buf, y)

    def final_flush(self):
        """End of stream: release everything still pending, unvalidated."""
        self._reserve(self.out_n + self.pending_n, 1)
        _flush(
            self.iv, self.pending_t, self.pending_conf, self.pending_start,
            self.out_t, self.out_conf, self.pending_n, False,
        )


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

    The confidence ceilings are parameters too.  Packed into an ``.efm``
    high nibble as ``doubt = 15 - (conf >> 4)`` the defaults give: a
    fabricated T value doubt 14, a flywheel-rewritten sync run doubt 15, and
    an unvalidated frame doubt 8.  Fabrication sits above a consumer's
    erasure threshold and whole-frame validation sits below it, because the
    first is per-symbol certainty and the second flags 74 T values for the
    sake of the two in them that are wrong.

    ``restore_sync=False`` stops the flywheel rewriting the runs at a sync
    the pattern matcher missed, leaving the damage in the T stream instead
    of repairing it.  Frames are still closed from the position counter, so
    framing is unaffected; only the emitted runs differ.
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
        timing_scale=0.5,
        conf_lowcap=CONF_LOWCAP,
        conf_legalised=CONF_LEGALISED,
        conf_restored=CONF_RESTORED,
        restore_sync=True,
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
            timing_scale,
            conf_lowcap,
            conf_legalised,
            conf_restored,
            restore_sync,
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
        self.core.begin()
        if conditioned.size:
            self.core.consume(conditioned)
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
