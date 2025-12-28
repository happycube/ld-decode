from dataclasses import dataclass
import numpy as np
from numba import njit

from lddecode.utils import inrange
import vhsdecode.formats as vhs_formats


@dataclass
class DodOptions:
    dod_threshold_p: float
    dod_threshold_a: float
    dod_hysteresis: float


@njit(cache=True)
def find_crossings(data, threshold):
    """Find where the data crosses the set threshold."""

    # We do this by constructing array where positions above
    # the threshold are marked as true, other sfalse,
    # and use diff to mark where the value changes.
    crossings = np.diff(data < threshold)
    # TODO: See if we can avoid reduntantly looking for both up and
    # down crossing when we just need one of them.
    return crossings


@njit(cache=True, nogil=True, fastmath=True)
def find_dropouts(env, threshold, hysteresis, merge_threshold):
    # list of tuples containing start and end
    down_thresh = threshold
    up_thresh = threshold * hysteresis

    dropouts = []
    dropout_idx = -1
    
    n = len(env)
    for i in range(n):
        v = env[i]
        dropout_ended = False

        if v <= down_thresh:
            if dropout_idx == -1 or (dropout_ended := dropouts[dropout_idx][1] != -1 and i - dropouts[dropout_idx][1] > merge_threshold):
                # start dropout if none exist or distance from previous is greater than the merge threshold
                dropout_idx += 1
                dropouts.append((i, -1))
            elif dropout_ended:
                # continue existing dropout
                dropouts[dropout_idx] = (dropouts[dropout_idx][0], -1)
        elif v >= up_thresh:
            # end dropout
            if dropout_idx != -1 and dropouts[dropout_idx][1] == -1:
                dropouts[dropout_idx] = (dropouts[dropout_idx][0], i)

    if dropout_idx != -1 and dropouts[dropout_idx][1] == -1:
        # set the dropout ending to the last sample when the dropout happens at the end of the field
        dropouts[dropout_idx] = (dropouts[dropout_idx][0], n-1)

    return dropouts


def detect_dropouts_rf(field, dod_options):
    """Look for dropouts in the input data, based on rf envelope amplitude.
    Uses either an percentage of the frame average rf level, or an absolute value.
    TODO: A more advanced algorithm with hysteresis etc.
    """
    env = field.data["video"]["envelope"]
    threshold_p = dod_options.dod_threshold_p
    threshold_abs = dod_options.dod_threshold_a
    hysteresis = dod_options.dod_hysteresis

    threshold = 0.0
    field_average = np.mean(field.data["video"]["envelope"])
    # Store the average for later.
    field.rf.field_averages.rf_level.push(field_average)
    if threshold_abs is not None:
        threshold = threshold_abs
    else:
        # Generate a threshold based on the field envelope average.
        # This may not be ideal on a field with a lot of droputs,
        # so we may want to use statistics of the previous averages
        # to avoid the threshold ending too low.
        threshold = field_average * threshold_p

    errlist = find_dropouts(env, threshold, hysteresis, vhs_formats.DOD_MERGE_THRESHOLD)

    # Drop very short dropouts that were not merged.
    # We do this after mergin to avoid removing short consecutive dropouts that
    # could be merged.
    errlist = list(filter(lambda s: s[1] - s[0] > vhs_formats.DOD_MIN_LENGTH, errlist))

    rv_lines = []
    rv_starts = []
    rv_ends = []

    # Convert to tbc positions.
    dropouts = dropout_errlist_to_tbc(field, errlist)
    for r in dropouts:
        rv_lines.append(r[0] - 1)
        rv_starts.append(int(r[1]))
        rv_ends.append(int(r[2]))

    return rv_lines, rv_starts, rv_ends


def dropout_errlist_to_tbc(field, errlist):
    """Convert data from raw data coordinates to tbc coordinates, and splits up
    multi-line dropouts.
    """
    dropouts = []

    if len(errlist) == 0:
        return dropouts

    # Now convert the above errlist into TBC locations
    errlistc = errlist.copy()

    lineoffset = -field.lineoffset

    # Remove dropouts occuring before the start of the frame so they don't
    # cause the rest to be skipped
    curerr = errlistc.pop(0)
    while len(errlistc) > 0 and curerr[0] < field.linelocs[field.lineoffset]:
        curerr = errlistc.pop(0)

    # TODO: This could be reworked to be a bit cleaner and more performant.

    for line in range(field.lineoffset, field.linecount + field.lineoffset):
        while curerr is not None and inrange(
            curerr[0], field.linelocs[line], field.linelocs[line + 1]
        ):
            start_rf_linepos = curerr[0] - field.linelocs[line]
            start_linepos = start_rf_linepos / (
                field.linelocs[line + 1] - field.linelocs[line]
            )
            start_linepos = int(start_linepos * field.outlinelen)

            end_rf_linepos = curerr[1] - field.linelocs[line]
            end_linepos = end_rf_linepos / (
                field.linelocs[line + 1] - field.linelocs[line]
            )
            end_linepos = int(np.round(end_linepos * field.outlinelen))

            first_line = line + 1 + lineoffset

            # If the dropout spans multiple lines, we need to split it up into one for each line.
            if end_linepos > field.outlinelen:
                num_lines = end_linepos // field.outlinelen

                # First line.
                dropouts.append((first_line, start_linepos, field.outlinelen))
                # Full lines in the middle.
                for n in range(num_lines - 1):
                    dropouts.append((first_line + n + 1, 0, field.outlinelen))
                # leftover on last line.
                dropouts.append(
                    (
                        first_line + (num_lines),
                        0,
                        np.remainder(end_linepos, field.outlinelen),
                    )
                )
            else:
                dropouts.append((first_line, start_linepos, end_linepos))

            if len(errlistc):
                curerr = errlistc.pop(0)
            else:
                curerr = None

    return dropouts
