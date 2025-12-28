from dataclasses import dataclass
import numpy as np
from numba import njit
import math

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
def find_dropouts_rf(env, start, end, threshold, hysteresis, merge_threshold):
    # list of tuples containing start and end
    down_thresh = threshold
    up_thresh = threshold * hysteresis

    dropouts = []
    dropout_idx = -1
    
    for i in range(start, end):
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
        dropouts[dropout_idx] = (dropouts[dropout_idx][0], end)

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

    start = field.linelocs[field.lineoffset]
    end = field.linelocs[field.linecount + field.lineoffset]

    dropouts_rf = find_dropouts_rf(env, start, end, threshold, hysteresis, vhs_formats.DOD_MERGE_THRESHOLD)

    # Drop very short dropouts that were not merged.
    # We do this after mergin to avoid removing short consecutive dropouts that
    # could be merged.
    dropouts_rf = list(filter(lambda s: s[1] - s[0] > vhs_formats.DOD_MIN_LENGTH, dropouts_rf))

    return map_dropouts_rf_to_tbc(dropouts_rf, field.linelocs, field.lineoffset, field.linecount, field.outlinelen)

def map_dropouts_rf_to_tbc(errlist, linelocs, lineoffset, linecount, outlinelen):
    rv_lines = []
    rv_starts = []
    rv_ends = []
    last_line = min(lineoffset + linecount, len(linelocs) - 1 - lineoffset)

    current_line_idx = lineoffset
    current_line_start = linelocs[current_line_idx]
    next_line_start = linelocs[current_line_idx+1]

    for (start, end) in errlist:
        while current_line_idx < last_line:
            # find the line that contains start of the dropout
            if start >= current_line_start and start < next_line_start:
                rv_lines.append(current_line_idx)
                
                # scale down to tbc line position
                start_rf_linepos = start - current_line_start
                start_linepos = math.floor(start_rf_linepos / (next_line_start - current_line_start) * outlinelen)

                rv_starts.append(start_linepos)
                break
            else:
                current_line_idx += 1
                current_line_start = linelocs[current_line_idx]
                next_line_start = linelocs[current_line_idx + 1]

        while current_line_idx < last_line:
            if end < next_line_start:
                # dropout is contained within this line
                # scale down to tbc line position
                end_rf_linepos = end - current_line_start
                end_linepos = math.ceil(end_rf_linepos / (next_line_start - current_line_start) * outlinelen)

                rv_ends.append(min(outlinelen, end_linepos))
                break
            else:
                # dropout spans multiple lines
                rv_ends.append(outlinelen)
                current_line_idx += 1

                if current_line_idx < last_line:
                    current_line_start = linelocs[current_line_idx]
                    next_line_start = linelocs[current_line_idx + 1]
                    
                    rv_starts.append(0)
                    rv_lines.append(current_line_idx)

    return rv_lines, rv_starts, rv_ends

