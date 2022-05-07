import cython
import numpy as np

cdef bint inrange(double a, double mi, double ma):
    return (a >= mi) & (a <= ma)

def pulse_qualitycheck(prev_pulse, pulse, int in_line_len):
    cdef double linelen
    cdef (double, double) exprange
    cdef bint inorder

    if prev_pulse[0] > 0 and pulse[0] > 0:
        exprange = (0.4, 0.6)
    elif prev_pulse[0] == 0 and pulse[0] == 0:
        exprange = (0.9, 1.1)
    else:  # transition to/from regular hsyncs can be .5 or 1H
        exprange = (0.4, 1.1)

    linelen = (pulse[1].start - prev_pulse[1].start) / in_line_len
    inorder = inrange(linelen, exprange[0], exprange[1])

    return inorder


def valid_pulses_to_linelocs(
    validpulses,
    double line0loc,
    bint skip_detected,
    double meanlinelen,
    int linecount,
    double hsync_tolerance,
    int lastlineloc,
):
    """Goes through the list of detected sync pulses that seem to be valid,
    and maps the start locations to a line number and throws out ones that do not seem to match or are out of place.

    Args:
        validpulses ([type]): List of sync pulses
        line0loc (float): Start location of line 0
        skip_detected (bool): TODO
        meanlinelen (float): Average line length
        linecount (int): Number of lines in the field
        hsync_tolerance (float): How much a sync pulse can deviate from normal before being discarded.
        lastlineloc (float): Start location of the last line

    Returns:
        [type]: Two dicts, one containing a list of linelocs mapped to line numbers, and one containing the distance between the line start and expected line start.
    """

    cdef double lineloc
    cdef int rlineloc
    cdef double lineloc_distance

    # Lists to fill
    # TODO: Could probably use arrays here instead of converting to arrays later.
    linelocs_dict = {}
    linelocs_dist = {}
    for p in validpulses:
        # Calculate what line number the pulse corresponds closest too.
        lineloc = (p[1].start - line0loc) / meanlinelen
        rlineloc = round(lineloc)
        lineloc_distance = abs(lineloc - rlineloc)

        # TODO doc
        if skip_detected:
            lineloc_end = linecount - ((lastlineloc - p[1].start) / meanlinelen)
            rlineloc_end = round(lineloc_end)
            lineloc_end_distance = abs(lineloc_end - rlineloc_end)

            if p[0] == 0 and rlineloc > 23 and lineloc_end_distance < lineloc_distance:
                lineloc = lineloc_end
                rlineloc = rlineloc_end
                lineloc_distance = lineloc_end_distance

        # only record if it's closer to the (probable) beginning of the line
        if lineloc_distance > hsync_tolerance or (
            rlineloc in linelocs_dict and lineloc_distance > linelocs_dist[rlineloc]
        ):
            continue

        # also skip non-regular lines (non-hsync) that don't seem to be in valid order (p[2])
        # (or hsync lines in the vblank area)
        if rlineloc > 0 and not p[2]:
            if p[0] > 0 or (p[0] == 0 and rlineloc < 10):
                continue

        linelocs_dict[rlineloc] = p[1].start
        linelocs_dist[rlineloc] = lineloc_distance

    return linelocs_dict, linelocs_dist
