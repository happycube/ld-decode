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

def get_first_hsync_loc(
    validpulses,
    double meanlinelen,
    bint is_ntsc,
    field_lines,
    first_field_h,
    int num_eq_pulses,
    int last_field_offset,
    int prev_first_field,
    int prev_first_hsync_loc
):
    """
    Returns: 
       * first_hsync_loc: Location of the first hsync pulse (first line after the vblanking)
       * next_field: Location of the next field (last line + 1 after this field)
       * first_field: True if this is the first field
    """    
    cdef np.ndarray[np.float64_t, ndim=1] field_order_lengths = np.full(4, -1, dtype=np.float64)
    cdef np.ndarray[np.int32_t, ndim=1] vblank_pulses = np.full(8, -1, dtype=np.int32)
    cdef np.ndarray[np.float64_t, ndim=1] vblank_lines = np.full(8, -1, dtype=np.float64)

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
            # hsync -> [eq 1]
            if last_pulse[0] == 0 and p[0] > 0:
                vblank_pulses[0 + group] = p[1].start
                field_order_lengths[0 + field_group] = round_nearest_line_loc((p[1].start - last_pulse[1].start) / meanlinelen)

            # eq 1 -> [vsync]
            if last_pulse[0] == 1 and p[0] == 2:
                vblank_pulses[1 + group] = p[1].start

            # [vsync] -> eq 2
            if last_pulse[0] == 2 and p[0] == 3:
                vblank_pulses[2 + group] = last_pulse[1].start
                
            # [eq 2] -> hsync
            if last_pulse[0] > 0 and p[0] == 0:
                vblank_pulses[3 + group] = last_pulse[1].start
                field_order_lengths[1 + field_group] = round_nearest_line_loc((p[1].start - last_pulse[1].start) / meanlinelen)

                # if there are more than two blanking intervals in this data
                # record only the first and last
                if group == 0:
                    group = 4
                    field_group = 2

        last_pulse = p

    # ********************************************************************
    # determine if this is the first or second field based on pulse length
    # ********************************************************************

    cdef int FIRST_HSYNC_LENGTH = 0
    cdef int FIRST_EQPL2_LENGTH = 1
    cdef int LAST_HSYNC_LENGTH = 2
    cdef int LAST_EQPL2_LENGTH = 3

    cdef np.ndarray[np.float64_t, ndim=1] first_field_lengths = np.full(4, -1, dtype=np.float64)
    cdef np.ndarray[np.float64_t, ndim=1] second_field_lengths = np.full(4, -1, dtype=np.float64)

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

    for i in range(0, 3):
        if field_order_lengths[i] == first_field_lengths[i]:
            field_boundaries_consensus += 1
            field_boundaries_detected += 1
        
        if field_order_lengths[i] == second_field_lengths[i]:
            field_boundaries_detected += 1

    if prev_first_field == 0:
        field_boundaries_consensus += 1
        field_boundaries_detected += 1
    elif prev_first_field == 1:
        field_boundaries_detected += 1
    
    # get a consensus if this is the first field or not
    if field_boundaries_detected == 0:
        first_field = True
    elif (round(field_boundaries_consensus / field_boundaries_detected) == 1):
        first_field = True
    else:
        first_field = False

    # print(
    #     "prev first field:", prev_first_field, 
    #     "field boundry consensus:", field_boundaries_consensus,
    #     "field boundries detected:", field_boundaries_detected, 
    #     field_order_lengths, 
    #     "curr first field:", first_field
    # )
       
    # ***********************************************************
    # calculate the expected line locations for each vblank pulse
    # ***********************************************************
    cdef double line0loc_line = 0
    cdef double vsync_section_lines = num_eq_pulses / 2

    # start of the last eq pulse before the first hsync pulse
    cdef double vblank_line_count = vsync_section_lines * 3 - .5
    cdef double hsync_start_line

    if first_field:
        vblank_lines[FIRST_VBLANK_EQ_1_START] = line0loc_line + first_field_lengths[FIRST_HSYNC_LENGTH]
        vblank_lines[FIRST_VBLANK_VSYNC_START] = vblank_lines[FIRST_VBLANK_EQ_1_START] + vsync_section_lines
        vblank_lines[FIRST_VBLANK_VSYNC_END] = vblank_lines[FIRST_VBLANK_VSYNC_START] + vsync_section_lines + .5
        vblank_lines[FIRST_VBLANK_EQ_2_END] = vblank_lines[FIRST_VBLANK_EQ_1_START] + vblank_line_count

        hsync_start_line = vblank_lines[FIRST_VBLANK_EQ_2_END] + first_field_lengths[FIRST_EQPL2_LENGTH]

        vblank_lines[LAST_VBLANK_EQ_1_START] = field_lines[0] + first_field_lengths[LAST_HSYNC_LENGTH]
        vblank_lines[LAST_VBLANK_VSYNC_START] = vblank_lines[LAST_VBLANK_EQ_1_START] + vsync_section_lines
        vblank_lines[LAST_VBLANK_VSYNC_END] = vblank_lines[LAST_VBLANK_VSYNC_START] + vsync_section_lines
        vblank_lines[LAST_VBLANK_EQ_2_END] = vblank_lines[LAST_VBLANK_EQ_1_START] + vblank_line_count
    else:
        vblank_lines[FIRST_VBLANK_EQ_1_START] = line0loc_line + second_field_lengths[FIRST_HSYNC_LENGTH]
        vblank_lines[FIRST_VBLANK_VSYNC_START] = vblank_lines[FIRST_VBLANK_EQ_1_START] + vsync_section_lines
        vblank_lines[FIRST_VBLANK_VSYNC_END] = vblank_lines[FIRST_VBLANK_VSYNC_START] + vsync_section_lines + .5
        vblank_lines[FIRST_VBLANK_EQ_2_END] = vblank_lines[FIRST_VBLANK_EQ_1_START] + vblank_line_count

        hsync_start_line = vblank_lines[FIRST_VBLANK_EQ_2_END] + second_field_lengths[FIRST_EQPL2_LENGTH]

        vblank_lines[LAST_VBLANK_EQ_1_START] = field_lines[1] + second_field_lengths[LAST_HSYNC_LENGTH]
        vblank_lines[LAST_VBLANK_VSYNC_START] = vblank_lines[LAST_VBLANK_EQ_1_START] + vsync_section_lines
        vblank_lines[LAST_VBLANK_VSYNC_END] = vblank_lines[LAST_VBLANK_VSYNC_START] + vsync_section_lines + .5
        vblank_lines[LAST_VBLANK_EQ_2_END] = vblank_lines[LAST_VBLANK_EQ_1_START] + vblank_line_count

    # find the location of the first hsync pulse using the vsync and line0loc
    cdef int first_pulse = -1
    cdef int second_pulse = -1
    cdef double first_line = -1
    cdef double second_line = -1
    cdef double actual_lines = -1
    cdef double expected_lines = -1

    # **********************************************************************************
    # Use the vsync pulses and their expected lines to derive first hsync pulse location
    #   (i.e. pulse right after the first vblanking interval)
    # **********************************************************************************
    cdef double first_hsync_loc = -1
    cdef double line0loc = -1
    cdef double delta = 0
    cdef int valid_location_count = 0
    cdef double offset = 0

    pulse_indexes = [
        FIRST_VBLANK_EQ_1_START,
        FIRST_VBLANK_VSYNC_START,
        FIRST_VBLANK_VSYNC_END,
        FIRST_VBLANK_EQ_2_END,
        LAST_VBLANK_EQ_1_START,
        LAST_VBLANK_VSYNC_START,
        LAST_VBLANK_VSYNC_END,
        LAST_VBLANK_EQ_2_END
    ]

    # check all possible known distances bewteen vblanking pulses and average the differences to derive the hsync_start_line
    for first_index in range(0, len(pulse_indexes)):
        # only care about distances one way, so no need to check the other direction
        for second_index in range(first_index+1, len(pulse_indexes)):
            first_pulse = vblank_pulses[first_index]
            second_pulse = vblank_pulses[second_index]
            first_line = vblank_lines[first_index]
            second_line = vblank_lines[second_index]
    
            # skip any pulses that are missing
            if first_pulse == -1 or second_pulse == -1:
                continue
        
            actual_lines = (first_pulse - second_pulse) / meanlinelen
            expected_lines = first_line - second_line
            actual_lines_rounded = round_nearest_line_loc(actual_lines)
    
            # TODO: What should the tolerance be here?
            if actual_lines_rounded <= expected_lines + .6 and actual_lines_rounded >= expected_lines - .6:
                offset += actual_lines - expected_lines
    
                delta = hsync_start_line - second_line
                first_hsync_loc += second_pulse + meanlinelen * delta
                valid_location_count += 1
                # print("syncing on distance", first_line, second_line, expected_lines, actual_lines)


    if valid_location_count == 0:
        # add any vsync pulses to the average if no valid distances were found, probably not synced
        for i in range(0,3):
            pulse = vblank_pulses[i]
            line = vblank_lines[i]
    
            if pulse == -1:
                continue
    
            # print("syncing on single vblank pulse", line)

            delta = hsync_start_line - line
            first_hsync_loc += pulse + meanlinelen * delta
            valid_location_count += 1

    # print(vblank_lines, vblank_pulses)

    # ******************************************************************************
    # Take the mean of the known vblanking locations to derive the first hsync pulse
    # ******************************************************************************
    if valid_location_count > 0:
        offset /= valid_location_count
        first_hsync_loc = round((first_hsync_loc + offset) / valid_location_count)
        line0loc = first_hsync_loc - meanlinelen * hsync_start_line
    else:
        # no sync pulses found
        return None, None, hsync_start_line, last_pulse, first_field

    # print(
    #     "next field",
    #     vblank_pulses[LAST_VBLANK_EQ_1_START], 
    #     first_hsync_loc + meanlinelen * (vblank_lines[LAST_VBLANK_EQ_1_START] - hsync_start_line),
    #     #validpulses[-1][1].start
    # )

    next_field = max(first_hsync_loc + meanlinelen * (vblank_lines[LAST_VBLANK_EQ_1_START] - hsync_start_line), vblank_pulses[LAST_VBLANK_EQ_1_START])

    prev_hsync_loc_from_0 = last_field_offset + prev_first_hsync_loc

    # print(prev_hsync_loc_from_0, vblank_pulses[LAST_VBLANK_EQ_1_START], first_hsync_loc)

    return line0loc, first_hsync_loc, hsync_start_line, next_field, first_field
    
def valid_pulses_to_linelocs(
    validpulses,
    int first_hsync_loc,
    int hsync_start_line,
    double meanlinelen,
    double hsync_tolerance,
    int proclines,
    double gap_detection_threshold,
):
    """Goes through the list of detected sync pulses that seem to be valid,
    and maps the start locations to a line number and throws out ones that do not seem to match or are out of place.

    Args:
        validpulses ([type]): List of sync pulses
        first_hsync_loc (int): Start location of the first hsync pulse
        hsync_start_line (int): Line that the first hsync pulse represents
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
    cdef np.ndarray[np.float64_t, ndim=1] line_distances = np.full(proclines, 0, dtype=np.float64)

    cdef int last_valid_pulse = 0
    cdef int first_line_index = proclines-1
    cdef int last_line_index = 0

    # assign pulses to lines based on the first hsync pulse in this field
    for p in validpulses:
        # Calculate what line number the pulse corresponds closest too.
        lineloc = (p[1].start - first_hsync_loc) / meanlinelen + hsync_start_line
        rlineloc = round(lineloc)
        lineloc_distance = abs(lineloc - rlineloc)

        if (
            # skip lines that won't be returned
            rlineloc < 0 or rlineloc >= proclines

            # only record if it's closer to the (probable) beginning of the line
            or lineloc_distance > hsync_tolerance or
            (line_locations[rlineloc] != -1 and lineloc_distance > line_distances[rlineloc])
        ):
            continue

        # track the first and last line
        if rlineloc < first_line_index:
            first_line_index = rlineloc
        if rlineloc > last_line_index:
            last_line_index = rlineloc
        if last_valid_pulse < p[1].start:
            last_valid_pulse = p[1].start

        expected_next_line = rlineloc + 1

        line_locations[rlineloc] = p[1].start
        line_distances[rlineloc] = lineloc_distance

    
    # check for gaps and fill in missing pulses for each line
    cdef int previous_line = -1
    cdef int nearest_line
    cdef float distance
    cdef float new_distance
    cdef double estimated_location
    cdef int nearest_pulse

    # fill in the first and last vsyncs with estimated line locations
    # we don't care about refining these lines
    cdef int hsync_start_line_rounded = round(hsync_start_line)
    for i in range(0, hsync_start_line_rounded):
        estimated_location = line_locations[hsync_start_line_rounded] - meanlinelen * (hsync_start_line_rounded - i)
        if estimated_location >= 0:
            line_locations[i] = estimated_location

    for i in range(proclines - hsync_start_line_rounded, proclines):
        estimated_location = line_locations[hsync_start_line_rounded] + meanlinelen * (i - hsync_start_line_rounded)
        if estimated_location <= validpulses[-1][1].start:
            line_locations[i] = estimated_location

    # check for gaps in remaining lines
    for i in range(hsync_start_line_rounded + 1, proclines - hsync_start_line_rounded):
        if (
            # line_location_missing
            line_locations[i] == -1

            # line_hsync_gap_detected
            or (
                previous_line > -1 and
                line_locations[i] - previous_line > meanlinelen * 1.2
            )
        ):
            distance = -1
            nearest_line = 0

            # search from the beginning for the closest populated line
            for j in range(first_line_index, last_line_index):
                new_distance = abs(j - i)

                if i != j and line_locations[j] != -1:
                    if distance < 0 or new_distance < distance:
                        distance = new_distance
                        nearest_line = j
                    else:
                        break # already found the nearest line

            # estimate the pulse location based on the nearest populated line
            estimated_location = line_locations[nearest_line] + meanlinelen * (i - nearest_line)

            # check if a pulse exists that is closer than the estimate within the gap detection threshold
            distance = meanlinelen / 2
            nearest_pulse = -1

            for p in validpulses:
                new_distance = abs(p[1].start - estimated_location)
                if distance > new_distance:
                    distance = new_distance
                    nearest_pulse = p[1].start
                elif nearest_pulse != -1:
                    break; # already found the nearest pulse

            if nearest_pulse != -1:
                # use the pulse near this line's estimated position
                # print(i, "using nearest pulse", nearest_pulse)
                line_locations[i] = nearest_pulse
            else:
                # use the estimated position
                # print(i, "using estimated pulse", estimated_location)
                line_location_errs[i] = 1
                line_locations[i] = estimated_location
 
        previous_line = line_locations[i]

    return line_locations, line_location_errs, max(last_valid_pulse, line_locations[-1])

# Rounds a line number to it's nearest line at intervals of .5 lines
def round_nearest_line_loc(double line_number):
    return round(0.5 * round(line_number / 0.5), 1)

def refine_linelocs_hsync(field, np.ndarray linebad, double hsync_threshold):
    """Refine the line start locations using horizontal sync data."""

    # Original used a copy here which resulted in a list.
    # Use an array instead for efficiency.
    cdef np.ndarray[np.float64_t, ndim=1] linelocs2 = np.asarray(field.linelocs1, dtype=np.float64)

    # Lookup these values here instead of doing it on every loop iteration.
    demod_05 = field.data["video"]["demod_05"]
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
    cdef double[:] hsync_area

    # Make sure we've done a copy
    if type(field.linelocs1) == type(linelocs2):
        assert(field.linelocs1.dtype != linelocs2.dtype, "BUG! input to refine_linelocs_hsync was not copied!")

    for i in range(len(field.linelocs1)):
        # skip VSYNC lines, since they handle the pulses differently
        if inrange(i, 3, 6) or (is_pal and inrange(i, 1, 2)):
            linebad[i] = True
            continue

        # refine beginning of hsync

        # start looking 1 usec back
        ll1 = field.linelocs1[i] - one_usec
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
            linelocs2[i] = zc

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
                linelocs2[i] = field.linelocs1[i]
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
                    linelocs2[i] = zc2
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
                            linelocs2[i] = zc2
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
                    if abs(refined_from_right_lineloc - linelocs2[i]) < (one_usec * 2):
                        right_cross = zc2
                        right_cross_refined = True
                        prev_porch_level = porch_level

        if linebad[i]:
            linelocs2[i] = field.linelocs1[
                i
            ]  # don't use the computed value here if it's bad

        if right_cross is not None and right_cross_refined:
            # If we get a good result from calculating hsync start from the
            # right side of the hsync pulse, we use that as it's less likely
            # to be messed up by overshoot.
            linebad[i] = False
            linelocs2[i] = refined_from_right_lineloc

    return linelocs2
