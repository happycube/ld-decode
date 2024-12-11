import cython
import numpy as np
cimport numpy as np
import math
import lddecode.utils as lddu
from libc.math cimport isnan, NAN

cdef Py_ssize_t NONE_INT = -1

cdef round_to_int(double a):
    return int(round(a))

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


cdef c_median(np.ndarray data):
    # TODO: For whatever reason the numba variant is massively faster than
    # calling np.median via cython.
    return lddu.nb_median(data)

@cython.wraparound(False)
@cython.boundscheck(False)
cdef bint is_out_of_range(double[:] data, double min, double max) nogil:
    """Check if data stays between min and max, returns fals if not."""
    cdef Py_ssize_t i
    if len(data) == 0:
        return True

    for i in range(0, len(data)):
        if data[i] < min or data[i] > max:
            return True

    return False

@cython.wraparound(False)
@cython.boundscheck(False)
cdef Py_ssize_t calczc_findfirst(double[:] data, double target, bint rising) nogil:
    """Find the index where data first crosses target, in the specified direction.
       returns NONE_INT if no crossing is found.
    """
    cdef Py_ssize_t i
    if rising:
        for i in range(0, len(data)):
            if data[i] >= target:
                return i

        return NONE_INT
    else:
        for i in range(0, len(data)):
            if data[i] <= target:
                return i

        return NONE_INT

cdef double calczc_do(double[:] data, Py_ssize_t _start_offset, double target, int edge=0, Py_ssize_t count=10) nogil:
    """Find the index where data first crosses target in the specified direction, and then try to estimate
    the exact crossing point between the samples.
    Will fail if the start point is already past the threshold in the requested direction.
    ."""
    cdef Py_ssize_t start_offset = max(1, _start_offset)
    cdef Py_ssize_t icount = count + 1

    if edge == 0:  # capture rising or falling edge
        if data[start_offset] < target:
            edge = 1
        else:
            edge = -1

    if edge == 1:
        if data[_start_offset] > target:
            return NAN
    elif edge == -1:
        if data[_start_offset] < target:
            return NAN

    cdef Py_ssize_t loc = calczc_findfirst(
        data[start_offset : start_offset + icount], target, edge == 1
    )

    # Need to use some proxy value instead of None here
    # if we want to avoid python interaction as there isn't an Option type in cython.
    if loc is NONE_INT:
        return NAN

    cdef Py_ssize_t x = start_offset + loc
    cdef double a = data[x - 1] - target
    cdef double b = data[x] - target
    cdef double y

    if b - a != 0:
        y = -a / (-a + b)
    else:
        # print(
        #     "RuntimeWarning: Div by zero prevented at lddecode/utils.calczc_do()", a, b
        # )
        y = 0

    return x - 1 + y


def calczc(double[:] data, Py_ssize_t _start_offset, double target, Py_ssize_t count=10, bint reverse=False, int edge=0):
    """ Calculate where data first crosses target in the direction specified by edge.
    edge:  -1 falling, 0 either, 1 rising
    count: How many samples to check
    reverse: If true, check in reverse direction
    """

    # NOTE:(oln) Not sure if we really need to specify start offset/count or if we could simply get by by
    # supplying the slice of data to look in.

    if reverse:
        # Instead of actually implementing this in reverse, use numpy to flip data
        rev_zc = calczc_do(data[_start_offset::-1], 0, target, edge, count)
        if isnan(rev_zc):
            return None

        return _start_offset - rev_zc

    res = calczc_do(data, _start_offset, target, edge, count)
    if isnan(res):
        return None
    return res

@cython.boundscheck(False)
@cython.wraparound(False)
def get_first_hsync_loc(
    validpulses,
    double meanlinelen,
    bint is_ntsc,
    field_lines,
    int num_eq_pulses,
    int prev_first_field,
    double last_field_offset_lines,
    int prev_first_hsync_loc,
    double prev_hsync_diff,
    int fallback_line0loc
):
    """
    Returns: 
       * line0loc: Location of line 0 (last hsync pulse of the previous field)
       * first_hsync_loc: Location of the first hsync pulse (first line after the vblanking)
       * hsync_start_line: Line where the first hsync pulse is found
       * next_field: Location of the next field (last line + 1 after this field)
       * first_field: True if this is the first field
    """
    cdef int i
    cdef double VSYNC_TOLERANCE_LINES = .5

    cdef int field_order_lengths_len = 4
    cdef double *field_order_lengths = [-1, -1, -1, -1]
    cdef int *vblank_pulses = [-1, -1, -1, -1, -1, -1, -1, -1]
    cdef double *vblank_lines = [-1, -1, -1, -1, -1, -1, -1, -1]

    cdef int FIRST_VBLANK_EQ_1_START = 0
    cdef int FIRST_VBLANK_VSYNC_START = 1
    cdef int FIRST_VBLANK_VSYNC_END = 2
    cdef int FIRST_VBLANK_EQ_2_END = 3
    cdef int LAST_VBLANK_EQ_1_START = 4
    cdef int LAST_VBLANK_VSYNC_START = 5
    cdef int LAST_VBLANK_VSYNC_END = 6
    cdef int LAST_VBLANK_EQ_2_END = 7

    # **************************************************************************************
    # get the vblanking pulses and assign them to either the first or second vblanking group
    # **************************************************************************************
    last_pulse = None
    cdef int group = 0
    cdef int field_group = 0

    for p in validpulses:
        if last_pulse != None and p[2]:
            if (
                # move to the next vsync pulse group if we're currently on the first vsync interval
                group == 0 and

                # and the next vsync is close to the expected location of the next field
                p[1].start > validpulses[0][1].start + field_lines[0] * meanlinelen
            ):
                group = 4
                field_group = 2

            # hsync -> [eq 1]
            if last_pulse[0] == 0 and p[0] > 0:
                vblank_pulses[0 + group] = p[1].start
                field_order_lengths[0 + field_group] = round_nearest_line_loc((p[1].start - last_pulse[1].start) / meanlinelen)

            # eq 1 -> [vsync]
            elif last_pulse[0] == 1 and p[0] == 2:
                vblank_pulses[1 + group] = p[1].start

            # [vsync] -> eq 2
            elif last_pulse[0] == 2 and p[0] == 3:
                vblank_pulses[2 + group] = p[1].start
                
            # [eq 2] -> hsync
            elif last_pulse[0] > 0 and p[0] == 0:
                vblank_pulses[3 + group] = last_pulse[1].start
                field_order_lengths[1 + field_group] = round_nearest_line_loc((p[1].start - last_pulse[1].start) / meanlinelen)

        last_pulse = p

    # ********************************************************************
    # determine if this is the first or second field based on pulse length
    # ********************************************************************
    cdef int FIRST_HSYNC_LENGTH = 0
    cdef int FIRST_EQPL2_LENGTH = 1
    cdef int LAST_HSYNC_LENGTH = 2
    cdef int LAST_EQPL2_LENGTH = 3

    cdef double *first_field_lengths = [-1, -1, -1, -1]
    cdef double *second_field_lengths = [-1, -1, -1, -1]

    if is_ntsc:
        first_field_lengths[FIRST_HSYNC_LENGTH] = 1
        first_field_lengths[FIRST_EQPL2_LENGTH] = .5
        first_field_lengths[LAST_HSYNC_LENGTH] = .5
        first_field_lengths[LAST_EQPL2_LENGTH] = 1

        second_field_lengths[FIRST_HSYNC_LENGTH] = .5
        second_field_lengths[FIRST_EQPL2_LENGTH] = 1
        second_field_lengths[LAST_HSYNC_LENGTH] = 1
        second_field_lengths[LAST_EQPL2_LENGTH] = .5
    else:
        first_field_lengths[FIRST_HSYNC_LENGTH] = .5
        first_field_lengths[FIRST_EQPL2_LENGTH] = .5
        first_field_lengths[LAST_HSYNC_LENGTH] = 1
        first_field_lengths[LAST_EQPL2_LENGTH] = 1

        second_field_lengths[FIRST_HSYNC_LENGTH] = 1
        second_field_lengths[FIRST_EQPL2_LENGTH] = 1
        second_field_lengths[LAST_HSYNC_LENGTH] = .5
        second_field_lengths[LAST_EQPL2_LENGTH] = .5

    cdef int field_boundaries_consensus = 0
    cdef int field_boundaries_detected = 0

    for i in range(0, field_order_lengths_len):
        field_length = field_order_lengths[i]

        if field_length == first_field_lengths[i]:
            field_boundaries_consensus += 1
            field_boundaries_detected += 1

        elif field_length == second_field_lengths[i]:
            field_boundaries_detected += 1

    # guess the field order if no previous field exists
    if prev_first_field == -1:
        if field_boundaries_detected == 0 or round(field_boundaries_consensus / field_boundaries_detected) == 1:
            first_field = True
        else:
            first_field = False
    # default to the inverse of the previous field
    else:
        first_field = not prev_first_field
    
    # override previous first field, if consensus is sure about field order
    if (
        # if fallback vsync is enabled or we are previously synced, need a full field consensus to overide field order
        field_boundaries_detected == field_order_lengths_len or

        # otherwise, need more than half a consensus
        (fallback_line0loc == -1 and prev_first_hsync_loc < 0 and field_boundaries_detected >= field_order_lengths_len / 2)
    ):
        if field_boundaries_consensus / field_boundaries_detected == 1:
            first_field = True
        elif field_boundaries_consensus / field_boundaries_detected == 0:
            first_field = False
       
    # ***********************************************************
    # calculate the expected line locations for each vblank pulse
    # ***********************************************************
    cdef double line0loc_line = 0
    cdef double vsync_section_lines = num_eq_pulses / 2
    cdef double hsync_start_line
    cdef double current_field_lines
    cdef double previous_field_lines

    if first_field:
        current_field_lengths = first_field_lengths
        previous_field_lines = field_lines[1]
        current_field_lines = field_lines[0]
    else:
        current_field_lengths = second_field_lengths
        previous_field_lines = field_lines[0]
        current_field_lines = field_lines[1]

    vblank_lines[FIRST_VBLANK_EQ_1_START] = line0loc_line + current_field_lengths[FIRST_HSYNC_LENGTH]
    vblank_lines[FIRST_VBLANK_VSYNC_START] = vblank_lines[FIRST_VBLANK_EQ_1_START] + vsync_section_lines
    vblank_lines[FIRST_VBLANK_VSYNC_END] = vblank_lines[FIRST_VBLANK_VSYNC_START] + vsync_section_lines
    vblank_lines[FIRST_VBLANK_EQ_2_END] = vblank_lines[FIRST_VBLANK_VSYNC_END] + vsync_section_lines - .5

    hsync_start_line = vblank_lines[FIRST_VBLANK_EQ_2_END] + current_field_lengths[FIRST_EQPL2_LENGTH]

    vblank_lines[LAST_VBLANK_EQ_1_START] = current_field_lines + current_field_lengths[LAST_HSYNC_LENGTH]
    vblank_lines[LAST_VBLANK_VSYNC_START] = vblank_lines[LAST_VBLANK_EQ_1_START] + vsync_section_lines
    vblank_lines[LAST_VBLANK_VSYNC_END] = vblank_lines[LAST_VBLANK_VSYNC_START] + vsync_section_lines
    vblank_lines[LAST_VBLANK_EQ_2_END] = vblank_lines[LAST_VBLANK_VSYNC_END] + vsync_section_lines - .5

    # **********************************************************************************
    # Use the vsync pulses and their expected lines to derive first hsync pulse location
    #   (i.e. pulse right after the first vblanking interval)
    # **********************************************************************************
    def calc_sync_from_known_distances(
        int first_pulse,
        int second_pulse,
        double first_line,
        double second_line
    ):
        cdef distance_offset = 0
        cdef double hsync_loc = 0
        cdef int valid_locations = 0
        cdef double actual_lines
        cdef double expected_lines
        cdef double actual_lines_rounded

        # skip any pulses that are missing
        if first_pulse != -1 and second_pulse != -1:
            actual_lines = (first_pulse - second_pulse) / meanlinelen
            expected_lines = first_line - second_line
            actual_lines_rounded = round_nearest_line_loc(actual_lines)

            if (
                actual_lines < expected_lines + VSYNC_TOLERANCE_LINES and 
                actual_lines > expected_lines - VSYNC_TOLERANCE_LINES
            ):
                distance_offset = actual_lines - expected_lines
                hsync_loc = second_pulse + meanlinelen * (hsync_start_line - second_line)
                valid_locations = 1
                # print("syncing on distance", expected_lines - actual_lines, first_line, second_line)

        return distance_offset, hsync_loc, valid_locations

    cdef int first_index
    cdef int second_index

    # *************************************************************
    # check the vblanking area at the beginning for valid locations
    # *************************************************************
    cdef double first_vblank_first_hsync_loc = -1
    cdef int    first_vblank_valid_location_count = 0
    cdef double first_vblank_offset = 0
    cdef int first_vblank_pulse_indexes_len = 4
    cdef int *first_vblank_pulse_indexes = [
        FIRST_VBLANK_EQ_1_START,
        FIRST_VBLANK_VSYNC_START,
        FIRST_VBLANK_VSYNC_END,
        FIRST_VBLANK_EQ_2_END
    ]

    for first_index in range(0, first_vblank_pulse_indexes_len):
        for second_index in range(first_index+1, first_vblank_pulse_indexes_len):
            res = calc_sync_from_known_distances(
                vblank_pulses[first_vblank_pulse_indexes[first_index]],
                vblank_pulses[first_vblank_pulse_indexes[second_index]],
                vblank_lines[first_vblank_pulse_indexes[first_index]],
                vblank_lines[first_vblank_pulse_indexes[second_index]]
            )
            first_vblank_offset += res[0]
            first_vblank_first_hsync_loc += res[1]
            first_vblank_valid_location_count += res[2]

    # *******************************************************
    # check the vblanking area at the end for valid locations
    # *******************************************************
    cdef double last_vblank_first_hsync_loc = -1
    cdef int    last_vblank_valid_location_count = 0
    cdef double last_vblank_offset = 0
    cdef int last_vblank_pulse_indexes_len = 4
    cdef int *last_vblank_pulse_indexes = [
        LAST_VBLANK_EQ_1_START,
        LAST_VBLANK_VSYNC_START,
        LAST_VBLANK_VSYNC_END,
        LAST_VBLANK_EQ_2_END
    ]

    for first_index in range(0, last_vblank_pulse_indexes_len):
        for second_index in range(first_index+1, last_vblank_pulse_indexes_len):
            res = calc_sync_from_known_distances(
                vblank_pulses[last_vblank_pulse_indexes[first_index]],
                vblank_pulses[last_vblank_pulse_indexes[second_index]],
                vblank_lines[last_vblank_pulse_indexes[first_index]],
                vblank_lines[last_vblank_pulse_indexes[second_index]]
            )
            last_vblank_offset += res[0]
            last_vblank_first_hsync_loc += res[1]
            last_vblank_valid_location_count += res[2]

    cdef double first_hsync_loc = -1
    cdef int valid_location_count = 0
    cdef double offset = 0
    
    # ********************************************************
    # validate the distance between the two vblanking sections
    # ********************************************************
    cdef double first_vblank_hsync_estimate = first_vblank_first_hsync_loc / first_vblank_valid_location_count if first_vblank_valid_location_count != 0 else 0
    cdef double last_vblank_hsync_estimate = last_vblank_first_hsync_loc / last_vblank_valid_location_count if last_vblank_valid_location_count != 0 else 0
    
    # if both vblanks have estimated hsync start locations
    if (
        first_vblank_first_hsync_loc != -1 and 
        last_vblank_first_hsync_loc != -1 and
        # and the estimated starting locations are the same
        first_vblank_hsync_estimate < last_vblank_hsync_estimate + VSYNC_TOLERANCE_LINES * meanlinelen and
        first_vblank_hsync_estimate > last_vblank_hsync_estimate - VSYNC_TOLERANCE_LINES * meanlinelen
    ):
        # sync on both start and last vblanks

        first_hsync_loc = first_vblank_first_hsync_loc + last_vblank_first_hsync_loc
        valid_location_count = first_vblank_valid_location_count + last_vblank_valid_location_count
        offset = first_vblank_offset + last_vblank_offset
    
        # sync accross the two vblanks
        for first_index in range(0, first_vblank_pulse_indexes_len):
            for second_index in range(0, last_vblank_pulse_indexes_len):
                res = calc_sync_from_known_distances(
                    vblank_pulses[first_vblank_pulse_indexes[first_index]],
                    vblank_pulses[last_vblank_pulse_indexes[second_index]],
                    vblank_lines[first_vblank_pulse_indexes[first_index]],
                    vblank_lines[last_vblank_pulse_indexes[second_index]]
                )
                offset += res[0]
                first_hsync_loc += res[1]
                valid_location_count += res[2]
    
        # print("using both vblank intervals")

    # otherwise, if fallback vsync is enabled, use that
    elif fallback_line0loc != -1:
        first_hsync_loc = fallback_line0loc + meanlinelen * hsync_start_line
        valid_location_count = 1
        offset = 0

        # print("using fallback")

    # otherwise, if there is no estimated hsync (not yet synced), try to sync on any detected vblank
    elif prev_first_hsync_loc <= 0:
        # use the vblank that has the most valid locations
        if last_vblank_first_hsync_loc != -1 and last_vblank_valid_location_count > first_vblank_valid_location_count:
            first_hsync_loc = last_vblank_first_hsync_loc
            valid_location_count = last_vblank_valid_location_count
            offset = last_vblank_offset
    
            # print("using last vblank interval")
        else:
            first_hsync_loc = first_vblank_first_hsync_loc
            valid_location_count = first_vblank_valid_location_count
            offset = first_vblank_offset
    
            # print("using first vblank interval")

    # ********************************************************************************
    # estimate the hsync location based on the previous valid field using read offsets
    # ********************************************************************************
    # TODO: not sure why this is, it should always be the previous field lines for all formats
    cdef double estimated_hsync_field_lines = previous_field_lines if is_ntsc else current_field_lines 

    cdef int estimated_hsync_loc = round(
        (
            last_field_offset_lines + 
            estimated_hsync_field_lines +
            prev_first_hsync_loc / meanlinelen # previous line location of last hsync
        ) * meanlinelen
    )

    cdef int estimated_hsync_with_offset
    cdef bint used_estimated_hsync = 0
    if (
        # if there are no valid sync distances
        valid_location_count == 0 and

        # and the previous hsync location is before the current field
        prev_first_hsync_loc > 0
    ):
        # previous field                  current field
        # |-------|-----------------------|-------|-----------------------|
        # offset--prev--------------------0-------curr--------------------total
        #         ^-------------------------------^

        # use the difference from the previous hsync if within .5 lines
        if prev_hsync_diff <= .5 and prev_hsync_diff >= -.5:
            # TODO: determine when to add or subtract the prev_hsync_diff
            #       maybe this can be based on difference in tape speed, add if slower, subtract if faster
            estimated_hsync_with_offset = round(estimated_hsync_loc + meanlinelen * prev_hsync_diff)
        else:
            estimated_hsync_with_offset = estimated_hsync_loc
        
        # when estimated hsync is negative, just use the closest valid pulse or 0
        # we are not synced here, but continue to return a sync location to 
        # avoid dropping video and getting out of sync with audio
        if estimated_hsync_with_offset <= 0:
            estimated_hsync_with_offset = validpulses[0][1].start if len(validpulses) else 0

        first_hsync_loc += estimated_hsync_with_offset
        valid_location_count += 1
        used_estimated_hsync = 1

        # print("using estimated hsync")

        # validate the estimated hsync location with any existing vsync pulses
        #for i in range(0, len(pulse_indexes)):
        #    res = calc_sync_from_known_distances(
        #        vblank_pulses[pulse_indexes[i]],
        #        estimated_hsync_with_offset,
        #        vblank_lines[pulse_indexes[i]],
        #        hsync_start_line
        #    )
        #    offset += res[0]
        #    first_hsync_loc += res[1]
        #    valid_location_count += res[2]
        

    # use any sync pulses, if nothing is found
    #if valid_location_count == 0:
    #    for i in range(0, 4):
    #        res = calc_sync_from_known_distances(
    #            vblank_pulses[i],
    #            vblank_pulses[i],
    #            vblank_lines[i],
    #            vblank_lines[i],
    #        )
    #        offset += res[0]
    #        first_hsync_loc += res[1]
    #        valid_location_count += res[2]

    # ******************************************************************************
    # Take the mean of the known vblanking locations to derive the first hsync pulse
    # ******************************************************************************
    cdef int hsync_offset = 0
    cdef int hsync_count = 0
    cdef double lineloc
    cdef double line0loc
    cdef int rlineloc
    if valid_location_count > 0:
        offset /= valid_location_count
        first_hsync_loc = round((first_hsync_loc + offset) / valid_location_count)

        # don't change the previous distance if this is an estimated sync location
        # since we don't know what the actual current hsync is
        if not used_estimated_hsync:
            prev_hsync_diff = (first_hsync_loc - estimated_hsync_loc) / meanlinelen
        
        # ****************************************************************
        # Align estimated start with hsync pulses to prevent skipped lines
        # ****************************************************************
        for p in validpulses:
            lineloc = (p[1].start - first_hsync_loc) / meanlinelen + hsync_start_line
            rlineloc = round(lineloc)

            if rlineloc > current_field_lines:
                break

            if rlineloc >= hsync_start_line and p[0] == 0 and p[2]:
                hsync_offset += first_hsync_loc + meanlinelen * (rlineloc - hsync_start_line) - p[1].start
                hsync_count += 1

        if hsync_count > 0:
            hsync_offset /= hsync_count
            first_hsync_loc -= hsync_offset

        line0loc = first_hsync_loc - meanlinelen * hsync_start_line
        next_field = first_hsync_loc + meanlinelen * (vblank_lines[LAST_VBLANK_EQ_1_START] - hsync_start_line)

        ## vsync debugging
        # field order
        #print(
        #    "prev first field:", prev_first_field, 
        #    "field boundry consensus:", field_boundaries_consensus,
        #    "field boundries detected:", field_boundaries_detected, 
        #    [x for x in field_order_lengths[:field_order_lengths_len]],
        #    "curr first field:", first_field
        #)
        #
        ## vsync pulses
        #print([x for x in vblank_lines[:8]])
        #print("actual vblank", [x for x in vblank_pulses[:8]])
        #
        ## calculated vs actual vsync pulses
        #for i in range(0, 8):
        #    vblank_lines[i] = round(first_hsync_loc + meanlinelen * (vblank_lines[i] - hsync_start_line))
        #print("calc vblank", [x for x in vblank_lines[:8]])
        #print("next field", next_field)
        #
        ## estimated hsync locations
        #print(
        #    "first vblank hsync",
        #    first_vblank_hsync_estimate,
        #    "last vblank hsync",
        #    last_vblank_hsync_estimate,
        #    "estimated hsync",
        #    estimated_hsync_loc,
        #    "fallback hsync",
        #    fallback_line0loc
        #)
        #print(
        #    "actual hsync loc",
        #    first_hsync_loc
        #)
        #print()

        return line0loc, first_hsync_loc, hsync_start_line, next_field, first_field, prev_hsync_diff, np.asarray([x for x in vblank_pulses[:8]], dtype=np.int32)

    # no sync pulses found
    # print("no sync pulses found")
    return None, None, hsync_start_line, None, first_field, prev_hsync_diff, np.asarray([x for x in vblank_pulses[:8]], dtype=np.int32)


@cython.boundscheck(False)
@cython.wraparound(False)
def valid_pulses_to_linelocs(
    np.ndarray[np.int32_t, ndim=1]  validpulses,
    int reference_pulse,
    int reference_line,
    double meanlinelen,
    double hsync_tolerance,
    int proclines,
    double gap_detection_threshold,
):
    """Goes through the list of detected sync pulses that seem to be valid,
    and maps the start locations to a line number and throws out ones that do not seem to match or are out of place.

    Args:
        validpulses ([int]): List of sync pulses
        reference_pulse (int): Sample location of the reference pulse
        reference_line (int): Line that the reference pulse represents
        meanlinelen (float): Average line length
        hsync_tolerance (float): How much a sync pulse can deviate from normal before being discarded.
        proclines (int): Total number of lines to process
        gap_detection_threshold (float): Threshold to check for skipped hsync pulses

    Returns:
        * line_locations: locations for each field line where in the index is the line number and the value is the start of the pulse
        * line_location_errs: array of boolean indicating if the pulse was esimated from other near pulses
        * last_valid_line_location: the last valid pulse detected
    """

    # Lists to fill
    cdef np.ndarray[np.int32_t, ndim=1] line_locations = np.full(proclines, -1, dtype=np.int32)
    cdef np.ndarray[np.int32_t, ndim=1] line_location_errs = np.full(proclines, 0, dtype=np.int32)

    cdef int i
    cdef int j
    
    # refine the line locations to pulses
    cdef float current_distance
    cdef float next_distance
    cdef float min_distance
    cdef int current_pulse
    cdef int current_pulse_index = 0

    for i in range(0, proclines):
        # estimate the line locations based on the mean line length
        line_locations[i] = round(reference_pulse + meanlinelen * (i - reference_line))

        # search for the closest pulse, pulse locations are assumed to be sorted
        if current_pulse_index < len(validpulses):
            current_distance = abs(validpulses[current_pulse_index] - line_locations[i])
            next_distance = -1
            current_pulse = -1
            min_distance = meanlinelen / 1.5
            j = current_pulse_index

            while j < len(validpulses) - 1:
                if current_distance <= min_distance:
                    min_distance = current_distance
                    current_pulse_index = j
                    current_pulse = validpulses[j]
    
                # if the distance starts to increase, we've moved past where the pulse should be
                next_distance = abs(validpulses[j+1] - line_locations[i])
                if next_distance > current_distance:
                    break
    
                current_distance = next_distance
                j += 1
    
            if current_pulse != -1:
                # print(i, "using nearest pulse", current_pulse)
                line_locations[i] = current_pulse
                current_pulse_index += 1
            # else:
            #     print(i, "using estimated pulse", line_locations[i])
            #     uncomment to fill any guessed lines with the previous field values
            #     line_location_errs[i] = 1

    return line_locations, line_location_errs, current_pulse

# Rounds a line number to it's nearest line at intervals of .5 lines
def round_nearest_line_loc(double line_number):
    return round(0.5 * round(line_number / 0.5), 1)

def refine_linelocs_hsync(field, np.ndarray linebad, double hsync_threshold):
    """Refine the line start locations using horizontal sync data."""

    # Original used a copy here which resulted in a list.
    # Use an array instead for efficiency.
    cdef np.ndarray[np.float64_t, ndim=1] linelocs_original = np.asarray(field.linelocs1, dtype=np.float64)
    cdef np.ndarray[np.float64_t, ndim=1] linelocs_refined = np.array(linelocs_original, dtype=np.float64, copy=True)

    # Lookup these values here instead of doing it on every loop iteration.
    cdef np.ndarray[np.float64_t, ndim=1] demod_05 = field.data["video"]["demod_05"]
    rf = field.rf
    cdef int normal_hsync_length = field.usectoinpx(rf.SysParams["hsyncPulseUS"])
    cdef int one_usec = rf.freq
    cdef float sample_rate_mhz = rf.freq
    cdef bint is_pal = rf.system == "PAL"
    cdef bint disable_right_hsync = rf.options.disable_right_hsync
    cdef double zc_threshold = hsync_threshold #rf.iretohz(rf.SysParams["vsync_ire"] / 2)
    cdef double ire_30 = rf.iretohz(30)
    cdef double ire_n_55 = rf.iretohz(-55)
    cdef double ire_110 = rf.iretohz(110)

    cdef bint right_cross_refined
    cdef double refined_from_right_lineloc = -1
    cdef double zc_fr
    cdef double porch_level
    cdef double prev_porch_level = -1
    cdef double sync_level
    cdef int ll1
    cdef int i
    cdef np.ndarray[np.float64_t, ndim=1] hsync_area

    for i in range(len(linelocs_original)):
        # skip VSYNC lines, since they handle the pulses differently
        if inrange(i, 3, 6) or (is_pal and inrange(i, 1, 2)):
            linebad[i] = True
            continue

        # refine beginning of hsync

        # start looking 1 usec back
        ll1 = round(linelocs_original[i]) - one_usec
        # and locate the next time the half point between hsync and 0 is crossed.
        zc = calczc(
            demod_05,
            ll1,
            zc_threshold,
            reverse=False,
            count=one_usec * 2,
        )

        right_cross = None

        if not disable_right_hsync:
            right_cross = calczc(
                demod_05,
                ll1 + (normal_hsync_length) - one_usec,
                zc_threshold,
                reverse=False,
                count=round_to_int(one_usec * 3),
                edge=1,
            )
        right_cross_refined = False

        # If the crossing exists, we can check if the hsync pulse looks normal and
        # refine it.
        if zc is not None and not linebad[i]:
            linelocs_refined[i] = zc

            # The hsync area, burst, and porches should not leave -50 to 30 IRE (on PAL or NTSC)
            # TODO: Use correct values for NTSC/PAL here
            hsync_area = demod_05[
                round_to_int(zc - (one_usec * 0.75)) : round_to_int(zc + (one_usec * 3.5))
            ]
            back_porch = demod_05[
                round_to_int(zc + one_usec * 3.5) : round_to_int(zc + (one_usec * 8))
            ]
            if is_out_of_range(hsync_area, ire_n_55, ire_110): # or is_out_of_range(back_porch, ire_n_55, ire_110):
                # don't use the computed value here if it's bad
                linebad[i] = True
                linelocs_refined[i] = linelocs_original[i]
            else:

                if np.amax(hsync_area) < ire_30:
                    porch_level = c_median(
                        demod_05[round_to_int(zc + (one_usec * 8)) : round_to_int(zc + (one_usec * 9))]
                    )
                else:
                    if prev_porch_level > 0:
                        porch_level = prev_porch_level
                    else:
                        porch_level = c_median(
                            demod_05[round_to_int(zc - (one_usec * 1.0)) : round_to_int(zc - (one_usec * 0.5))]
                        )
                sync_level = c_median(
                    demod_05[round_to_int(zc + (one_usec * 1)) : round_to_int(zc + (one_usec * 2.5))]
                )

                # Re-calculate the crossing point using the mid point between the measured sync
                # and porch levels
                zc2 = calczc(
                    demod_05,
                    ll1,
                    (porch_level + sync_level) / 2,
                    reverse=False,
                    count=400,
                )

                # any wild variation here indicates a failure
                if zc2 is not None and abs(zc2 - zc) < (one_usec / 2):
                    linelocs_refined[i] = zc2
                    prev_porch_level = porch_level
                else:
                    # Give up
                    # front_porch_level = c_median(
                    #     demod_05[int(zc - (one_usec * 1.0)) : int(zc - (one_usec * 0.5))]
                    # )

                    if prev_porch_level > 0:
                        # Try again with a earlier measurement porch.
                        zc2 = calczc(
                            demod_05,
                            ll1,
                            (prev_porch_level + sync_level) / 2,
                            reverse=False,
                            count=400,
                        )
                        if zc2 is not None and abs(zc2 - zc) < (one_usec / 2):
                            linelocs_refined[i] = zc2
                        else:
                            linebad[i] = True
                    else:
                        # Give up
                        linebad[i] = True
        else:
            linebad[i] = True

        # Check right cross
        if right_cross is not None:
            zc2 = None

            zc_fr = right_cross - normal_hsync_length

            # The hsync area, burst, and porches should not leave -50 to 30 IRE (on PAL or NTSC)
            # NOTE: This is more than hsync area, might wanna also check max levels of level in hsync
            hsync_area = demod_05[
                round_to_int(zc_fr - (one_usec * 0.75)) : round_to_int(zc_fr + (one_usec * 8))
            ]

            if not is_out_of_range(hsync_area, ire_n_55, ire_30):

                porch_level = c_median(
                    demod_05[round_to_int(zc_fr + normal_hsync_length + (one_usec * 1)) : round_to_int(zc_fr + normal_hsync_length + (one_usec * 2))]
                )

                sync_level = c_median(
                    demod_05[
                        round_to_int(zc_fr + (one_usec * 1)) : round_to_int(zc_fr + (one_usec * 2.5))
                    ]
                )

                # Re-calculate the crossing point using the mid point between the measured sync
                # and porch levels
                zc2 = calczc(
                    demod_05,
                    ll1 + normal_hsync_length - one_usec,
                    (porch_level + sync_level) / 2,
                    reverse=False,
                    count=400,
                )

                # any wild variation here indicates a failure
                if zc2 is not None and abs(zc2 - right_cross) < (one_usec / 2):
                    # TODO: Magic value here, this seem to give be approximately correct results
                    # but may not be ideal for all inputs.
                    # Value based on default sample rate so scale if it's different.
                    refined_from_right_lineloc = right_cross - normal_hsync_length + (2.25 * (sample_rate_mhz / 40.0))
                    # Don't use if it deviates too much which could indicate a false positive or non-standard hsync length.
                    if abs(refined_from_right_lineloc - linelocs_refined[i]) < (one_usec * 2):
                        right_cross = zc2
                        right_cross_refined = True
                        prev_porch_level = porch_level

        if linebad[i]:
            linelocs_refined[i] = linelocs_original[
                i
            ]  # don't use the computed value here if it's bad

        if right_cross is not None and right_cross_refined:
            # If we get a good result from calculating hsync start from the
            # right side of the hsync pulse, we use that as it's less likely
            # to be messed up by overshoot.
            linebad[i] = False
            linelocs_refined[i] = refined_from_right_lineloc

    return linelocs_refined
