"""Sync-pulse, dropout and burst detection helpers.

Originally split out of utils.py, which now only re-exports it.
"""

from collections import namedtuple

import numpy as np
from numba import njit

from .dsp import nb_median
from .filters import calczc_do, inrange


# Something like this should be a numpy function, but I can't find it.
def findareas(array, cross):
    """ Find areas where `array` is <= `cross`

    returns: array of tuples of said areas (begin, end, length)
    """
    starts = np.where(np.logical_and(array[1:] < cross, array[:-1] >= cross))[0]
    ends = np.where(np.logical_and(array[1:] >= cross, array[:-1] < cross))[0]

    if len(starts) == 0 or len(ends) == 0:
        return []

    # remove 'dangling' beginnings and endings so everything zips up nicely and in order
    if ends[0] < starts[0]:
        ends = ends[1:]
    if len(ends) == 0:
        return []

    if starts[-1] > ends[-1]:
        starts = starts[:-1]
    if len(starts) == 0:
        return []

    return [(*z, z[1] - z[0]) for z in zip(starts, ends)]


Pulse = namedtuple("Pulse", "start len")


@njit(cache=True, nogil=True)
def findpulses_numba_raw(sync_ref, high, min_synclen=0, max_synclen=5000):
    """Locate possible pulses by looking at areas within some range.
    Outputs arrays of starts and lengths
    """

    in_pulse = sync_ref[0] <= high

    # Start/lengths lists
    # It's possible this could be optimized further by using
    # a different data structure here.
    starts = []
    lengths = []

    cur_start = 0

    # Basic algorithm here is swapping between two states, going to the other one if we detect the
    # current sample passed the threshold.
    for pos, value in enumerate(sync_ref):
        if in_pulse:
            if value > high:
                length = pos - cur_start
                # If the pulse is in range, and it's not a starting one
                if inrange(length, min_synclen, max_synclen) and cur_start != 0:
                    starts.append(cur_start)
                    lengths.append(length)
                in_pulse = False
        elif value <= high:
            cur_start = pos
            in_pulse = True

    # Not using a possible trailing pulse
    # if in_pulse:
    #     # Handle trailing pulse
    #     length = len(sync_ref) - 1 - cur_start
    #     if inrange(length, min_synclen, max_synclen):
    #         starts.append(cur_start)
    #         lengths.append(length)

    return np.asarray(starts), np.asarray(lengths)


def _to_pulses_list(pulses_starts, pulses_lengths):
    """Make list of Pulse objects from arrays of pulses starts and lengths"""
    # Not using numba for this right now as it seemed to cause random segfault
    # in tests.
    return [Pulse(z[0], z[1]) for z in zip(pulses_starts, pulses_lengths)]


def findpulses(sync_ref, _, high):
    """Locate possible pulses by looking at areas within some range.
    .outputs a list of Pulse tuples
    """
    pulses_starts, pulses_lengths = findpulses_numba_raw(
        sync_ref, high
    )
    return _to_pulses_list(pulses_starts, pulses_lengths)


@njit(cache=True, nogil=True)
def _dropout_unflag_sync(iserr, demod, demod_05, start, end, sync_min, normal_max, sync_min_05, normal_max_05):
    for i in range(max(0, start), min(end, len(iserr))):
        if i < len(demod) and sync_min <= demod[i] <= normal_max:
            if i < len(demod_05) and sync_min_05 <= demod_05[i] <= normal_max_05:
                iserr[i] = False


#: Samples _dropout_span copies out of the video record array at a time.
DROPOUT_CHUNK = 2048


@njit(cache=True, nogil=True)
def _dropout_span(iserr, rfhpf, rf_lo, rf_hi, rot_delay,
                  demod, demod_05, demod_raw,
                  normal_min, normal_max, normal_min_05, normal_max_05,
                  sync_min, sync_min_05, absurd_hz, i0, i1, in_sync):
    """dropout_flags over [i0, i1), where in_sync is the same throughout
    and every i is at or past rot_delay.

    The three video channels are interleaved in one record array, so each
    chunk is first copied out into contiguous buffers; the test itself is
    then branch-free over plain slices, which vectorises.
    """
    d_buf = np.empty(DROPOUT_CHUNK, np.float32)
    d5_buf = np.empty(DROPOUT_CHUNK, np.float32)
    raw_buf = np.empty(DROPOUT_CHUNK, np.float32)
    for c0 in range(i0, i1, DROPOUT_CHUNK):
        m = min(DROPOUT_CHUNK, i1 - c0)
        d_src = demod[c0 : c0 + m]
        d5_src = demod_05[c0 : c0 + m]
        raw_src = demod_raw[c0 : c0 + m]
        for j in range(m):
            d_buf[j] = d_src[j]
            d5_buf[j] = d5_src[j]
            raw_buf[j] = raw_src[j]

        out = iserr[c0 : c0 + m]
        rf = rfhpf[c0 - rot_delay : c0 - rot_delay + m]
        for j in range(m):
            d = d_buf[j]
            d5 = d5_buf[j]
            err = ((d < normal_min) | (d > normal_max)
                   | (d5 < normal_min_05) | (d5 > normal_max_05))
            if in_sync:
                err &= ~((sync_min <= d) & (d <= normal_max)
                         & (sync_min_05 <= d5) & (d5 <= normal_max_05))
            x = rf[j]
            out[j] = err | (x < rf_lo) | (x > rf_hi) | (raw_buf[j] > absurd_hz)


@njit(cache=True, nogil=True)
def dropout_flags(iserr, rfhpf, rf_lo, rf_hi, rot_delay,
                  demod, demod_05, demod_raw,
                  normal_min, normal_max, normal_min_05, normal_max_05,
                  sync_min, sync_min_05, absurd_hz,
                  sync_starts, sync_ends, keep_start, keep_end):
    """Field.dropout_detect_demod's whole per-sample test in one pass.

    A sample is a dropout when:

    - demod or demod_05 leaves its normal range - unless the sample is in
      one of the sync regions [sync_starts[r], sync_ends[r]) and both sit
      within the relaxed sync ranges (what _dropout_unflag_sync clears);
    - or the RF high-pass rot_delay samples earlier leaves (rf_lo, rf_hi);
    - or demod_raw exceeds absurd_hz;

    and only inside [keep_start, keep_end).  demod, demod_05 and
    demod_raw are fields of one record array, so testing them together
    reads it once rather than once per field.  rf_lo and rf_hi must be
    float32-representable: the RF test was a float32 comparison.
    """
    n = len(iserr)
    lo = max(0, keep_start)
    hi = min(n, keep_end)
    iserr[:lo] = False
    iserr[max(lo, hi):] = False

    # The samples before rot_delay have no RF sample to test: one at a
    # time, through the same test with the RF term left out.
    i = lo
    for i in range(lo, min(hi, rot_delay)):
        d = demod[i]
        d5 = demod_05[i]
        err = (d < normal_min or d > normal_max
               or d5 < normal_min_05 or d5 > normal_max_05)
        if err and sync_min <= d <= normal_max and sync_min_05 <= d5 <= normal_max_05:
            for r in range(len(sync_starts)):
                if sync_starts[r] <= i < sync_ends[r]:
                    err = False
                    break
        iserr[i] = err or demod_raw[i] > absurd_hz
    i = max(lo, min(hi, rot_delay))

    # The rest in spans that are wholly inside or wholly outside the sync
    # regions (merged, since lines can overlap).
    order = np.argsort(sync_starts)
    for k in order:
        start = max(sync_starts[k], i)
        end = min(sync_ends[k], hi)
        if end <= start:
            continue
        _dropout_span(iserr, rfhpf, rf_lo, rf_hi, rot_delay, demod, demod_05,
                      demod_raw, normal_min, normal_max, normal_min_05,
                      normal_max_05, sync_min, sync_min_05, absurd_hz,
                      i, start, False)
        _dropout_span(iserr, rfhpf, rf_lo, rf_hi, rot_delay, demod, demod_05,
                      demod_raw, normal_min, normal_max, normal_min_05,
                      normal_max_05, sync_min, sync_min_05, absurd_hz,
                      start, end, True)
        i = end
    _dropout_span(iserr, rfhpf, rf_lo, rf_hi, rot_delay, demod, demod_05,
                  demod_raw, normal_min, normal_max, normal_min_05,
                  normal_max_05, sync_min, sync_min_05, absurd_hz,
                  i, hi, False)


# Hotspot subroutines in FieldNTSC's compute_line_bursts function,
# removed so that they can be JIT'd


@njit(cache=True, nogil=True)
def clb_findbursts(
    isrising, zcs, burstarea, i, endburstarea, threshold,
    bstart, s_rem, zcburstdiv, phase_adjust,
):
    zc_count = 0
    rising_count = 0
    j = i

    isrising.fill(False)
    zcs.fill(0)

    while j < endburstarea and zc_count < len(zcs):
        if np.abs(burstarea[j]) > threshold:
            zc = calczc_do(burstarea, j, 0)
            if zc is not None:
                isrising[zc_count] = burstarea[j] < 0
                zcs[zc_count] = zc
                zc_count += 1
                j = int(zc) + 1
            else:
                break
        else:
            j += 1

    if zc_count:
        zc_cycles = ((bstart + zcs - s_rem) / zcburstdiv) + phase_adjust
        # numba doesn't support np.round over an array, so we have to do this
        zc_rounds = (zc_cycles + .5).astype(np.int32)
        phase_adjust += nb_median(zc_rounds - zc_cycles)
        rising_count = np.sum(np.bitwise_xor(isrising, (zc_rounds % 2) != 0))

    return zc_count, phase_adjust, rising_count
