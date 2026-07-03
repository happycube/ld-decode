"""Sync-pulse, dropout and burst detection helpers.

Split verbatim out of utils.py (see that module's compatibility shim).
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
