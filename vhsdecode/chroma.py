import math
from collections import namedtuple
import numpy as np
import lddecode.utils as lddu
import lddecode.core as ldd
from vhsdecode.utils import get_line
import scipy.signal as sps
from vhsdecode.rust_utils import sosfiltfilt_rust

from numba import njit


@njit(cache=True)
def needs_recheck(sum_0: float, sum_1: float):
    """Check if the magnitude difference between the sums is larger than the set threshold
    If it's small, we want to make sure we re-check on the next field.
    """
    # Trigger a re-check on next field if the magnitude difference is smaller than this value.
    RECHECK_THRESHOLD = 1.2
    return True if max(sum_0, sum_1) / min(sum_0, sum_1) < RECHECK_THRESHOLD else False


@njit(cache=True, nogil=True)
def chroma_to_u16(chroma):
    """Scale the chroma output array to a 16-bit value for output."""
    S16_ABS_MAX = 32767

    # Disabled for now as it's misleading.
    # if np.max(chroma) > S16_ABS_MAX:
    #     ldd.logger.warning("Chroma signal clipping.")
    return (chroma + S16_ABS_MAX).astype(np.uint16)


@njit(cache=True, nogil=True)
def acc(chroma, burst_abs_ref, burststart, burstend, linelength, lines):
    """Scale chroma according to the level of the color burst on each line."""
    STARTING_LINE = int(16)
    assert lines > STARTING_LINE

    output = np.zeros(chroma.size, dtype=np.double)
    mean_burst_accumulator = 0
    for linenumber in range(16, lines):
        linestart = linelength * linenumber
        lineend = linestart + linelength
        line = chroma[linestart:lineend]
        acced, rms = acc_line(line, burst_abs_ref, burststart, burstend)
        output[linestart:lineend] = acced
        mean_burst_accumulator += rms

    return output, mean_burst_accumulator / (lines - STARTING_LINE)


@njit(cache=True, nogil=True)
def acc_line(chroma, burst_abs_ref, burststart, burstend):
    """Scale chroma according to the level of the color burst the line."""
    output = np.zeros(chroma.size, dtype=np.double)

    line = chroma
    burst_abs_mean = lddu.rms(line[burststart:burstend])
    # np.sqrt(np.mean(np.square(line[burststart:burstend])))
    #    burst_abs_mean = np.mean(np.abs(line[burststart:burstend]))
    scale = burst_abs_ref / burst_abs_mean if burst_abs_mean != 0 else 1
    output = line * scale

    return output, burst_abs_mean


@njit(cache=True, nogil=True)
def comb_c_pal(data, line_len):
    """Very basic comb filter, adds the signal together with a signal delayed by 2H,
    and one advanced by 2H
    line by line. VCRs do this to reduce crosstalk.
    Helps chroma stability on LP tapes in particular.
    (VCRs only adds delayed by 1h instead)
    """

    # TODO: Compensate for PAL quarter cycle offset
    data2 = data.copy()
    numlines = len(data) // line_len
    for line_num in range(16, numlines - 2):
        adv2h = data2[(line_num + 2) * line_len : (line_num + 3) * line_len]
        delayed2h = data2[(line_num - 2) * line_len : (line_num - 1) * line_len]
        line_slice = data[line_num * line_len : (line_num + 1) * line_len]
        # Let the delayed signal contribute 1/4 and advanced 1/4.
        # Could probably make the filtering configurable later.
        data[line_num * line_len : (line_num + 1) * line_len] = (
            (line_slice * 2) - (delayed2h) - adv2h
        ) / 4
    return data


@njit(cache=True, nogil=True)
def comb_c_ntsc(data, line_len):
    """Very basic comb filter, adds the signal together with a signal delayed by 1H,
    and one advanced by 1h
    line by line. VCRs do this to reduce crosstalk.
    (VCRs only adds delayed by 1h instead)
    """

    data2 = data.copy()
    numlines = len(data) // line_len
    for line_num in range(16, numlines - 2):
        advanced1h = data2[(line_num + 1) * line_len : (line_num + 2) * line_len]
        delayed1h = data2[(line_num - 1) * line_len : (line_num) * line_len]
        line_slice = data[line_num * line_len : (line_num + 1) * line_len]
        # Let the delayed signal contribute 1/3.
        # Could probably make the filtering configurable later.
        data[line_num * line_len : (line_num + 1) * line_len] = (
            (line_slice * 2) - advanced1h - delayed1h
        ) / 4
    return data

@njit(cache=True, nogil=True, fastmath=True)
def _demod_burst(
    burst,
    burst_start,
    burst_end,
    burst_sin,
    burst_cos
):
    I = 0
    Q = 0

    for i in range(burst_end - burst_start):
        I += burst[i] * burst_cos[i + burst_start]
        Q += burst[i] * burst_sin[i + burst_start]

    burst_phase = np.arctan2(Q, I)
    burst_phase_deg = np.degrees(burst_phase) % 360

    return burst_phase_deg, I, Q

def get_upconverted_burst(
    chroma,
    phase,
    linenumber,
    lineoffset,
    outwidth,
    burstarea,
    chroma_heterodyne,
    chroma_filter,
    burst_sin,
    burst_cos
):
    burst_padding = burstarea[1] - burstarea[0] # pad the area being filtered

    line_start = (linenumber - lineoffset) * outwidth
    burst_start = line_start + burstarea[0]
    burst_start_padding = burst_start - max(0, burst_start - burst_padding)
    burst_start_with_padding = burst_start - burst_start_padding

    burst_end = line_start + burstarea[1]
    burst_end_padding = min(len(chroma), burst_end + burst_padding) - burst_end
    burst_end_with_padding = burst_end + burst_end_padding

    burst_padded = chroma_heterodyne[phase][burst_start_with_padding:burst_end_with_padding] * chroma[burst_start_with_padding:burst_end_with_padding]

    # filter out noise so only the color burst is present
    burst_padded_filtered =  sosfiltfilt_rust(chroma_filter, burst_padded)

    burst_filtered = burst_padded_filtered[burst_start_padding:-burst_end_padding]

    burst_phase_deg, I, Q = _demod_burst(burst_filtered, burst_start, burst_end, burst_sin, burst_cos)

    return burst_phase_deg, I, Q, burst_start, burst_end

# input
# (
#    isFirstField
#    detected color burst phase quadrant (n-180): where n is (0=0, 1=90, 2=180, 3=270)
#    phase delta from previous color burst: (0=0, 1=90, 2=180, 3=270)
# )
#
# output
# (
#    fieldPhaseId
#    startingPhase
# )
ntsc_phase_rotation_sequence = {
                       # frame # | field # | burst phase |        phase delta | fieldPhaseId |
    # frame 1          #         |         |             | (prev vs. current) |              |
    (1, 2, 0): (3, 0), # frame 1 | field 1 |         180 |                 +0 |            3 |
    (0, 3, 1): (2, 1), # frame 1 | field 2 |         270 |                +90 |            2 |
    # frame 2
    (1, 1, 2): (1, 1), # frame 2 | field 1 |          90 |               +180 |            1 |
    (0, 0, 3): (4, 0), # frame 2 | field 2 |           0 |               +270 |            4 |
    # frame 3
    (1, 0, 0): (3, 2), # frame 3 | field 1 |           0 |                 +0 |            3 |
    (0, 1, 1): (2, 3), # frame 3 | field 2 |          90 |                +90 |            2 |
    # frame 4
    (1, 3, 2): (1, 3), # frame 4 | field 1 |         270 |               +180 |            1 |
    (0, 2, 3): (4, 2), # frame 4 | field 2 |         180 |               +270 |            4 |
    # copy of the above, but without phase delta for the first field
    # frame 1
    (1, 2, -1): (3, 0),
    (0, 3, -1): (2, 1),
    # frame 2
    (1, 1, -1): (1, 1),
    (0, 0, -1): (4, 0),
    # frame 3
    (1, 0, -1): (3, 2),
    (0, 1, -1): (2, 3),
    # frame 4
    (1, 3, -1): (1, 3),
    (0, 2, -1): (4, 2),
}

def _get_phase_sequence(
    chroma,
    chroma_heterodyne,
    track_rotation,
    chroma_rotation,
    chroma_filter,
    burst_sin,
    burst_cos,
    burstarea,
    lineoffset,
    outwidth,
    linesout,
    last_line,
    do_phase_rotation_check,
    track_change_threshold,
    rotation_check_start_line,
):
    phase_sequence = []
    burst_phases = []

    # rewind to the previous phase (line -1)
    current_phase = 0
    for _ in range(3):
        current_phase = (current_phase + track_rotation) % 4

    for linenumber in range(lineoffset, last_line):
        current_phase = (current_phase + track_rotation) % 4
        current_burst_phase, current_burst_I, current_burst_Q, current_burst_start, current_burst_end = get_upconverted_burst(
            chroma,
            current_phase,
            linenumber,
            lineoffset,
            outwidth,
            burstarea,
            chroma_heterodyne,
            chroma_filter,
            burst_sin,
            burst_cos
        )

        if (
            do_phase_rotation_check and
            linenumber >= rotation_check_start_line and
            linenumber < last_line - 1
        ):
            # get the next burst using the phase rotation for the current track
            next_phase = (current_phase + track_rotation) % 4
            next_burst_phase, _, _, _, _ = get_upconverted_burst(
                chroma,
                next_phase,
                linenumber + 1,
                lineoffset,
                outwidth,
                burstarea,
                chroma_heterodyne,
                chroma_filter,
                burst_sin,
                burst_cos
            )

            phase_delta = abs((next_burst_phase - current_burst_phase + 180) % 360 - 180)
            if phase_delta > track_change_threshold:
                # positive correlation -> in phase
                # negative correlation -> out of phase
                # burst is more in phase than out of phase, flip rotation so it remains out of phase
                track_rotation = chroma_rotation[1] if track_rotation == chroma_rotation[0] else chroma_rotation[0]
        
        phase_sequence.append((linenumber, current_phase))
        burst_phases.append((linenumber, current_burst_phase, current_burst_I, current_burst_Q, current_burst_start, current_burst_end))

    return phase_sequence, burst_phases

def get_phase_rotation_sequence(
    chroma,
    rotation_check_start_line,
    lineoffset,
    linesout,
    outwidth,
    is_first_field,
    prev_burst_phase_avg,
    color_system,
    burst_sin,
    burst_cos,
    detect_chroma_track_phase,
    track_rotation,
    chroma_rotations,
    chroma_heterodyne,
    burstarea,
    chroma_filter,
):
    # *****************************************************
    # Gather the phase differences between each color burst
    # Color burst alternates phase between lines in a field
    # *****************************************************    
    track_change_threshold = 90
    burst_check_skip_lines = 16
    coherence_threshold = 0.3

    do_phase_rotation_check = detect_chroma_track_phase and chroma_rotations is not None and chroma_heterodyne is not None

    end = linesout + lineoffset
    phase_sequence, burst_phases = _get_phase_sequence(
        chroma,
        chroma_heterodyne,
        track_rotation,
        chroma_rotations,
        chroma_filter,
        burst_sin,
        burst_cos,
        burstarea,
        lineoffset,
        outwidth,
        linesout,
        end,
        do_phase_rotation_check,
        track_change_threshold,
        rotation_check_start_line,
    )

    # detect the track phase, and recalculate if needed
    burst_check_start = burst_check_skip_lines
    burst_check_end = end - burst_check_skip_lines

    if chroma_rotations:
        # get the average difference in phase across color bursts
        avg_delta = 0
        burst_count = 0

        for i in range(1, len(burst_phases)):
            _,                         previous_burst, _, _, _, _ = burst_phases[i-1]
            current_burst_line_number, current_burst, _, _, _, _  = burst_phases[i]

            if (
                current_burst_line_number > burst_check_start and
                current_burst_line_number < burst_check_end
            ):
                avg_delta = avg_delta + ((current_burst - previous_burst) % 360)
                burst_count += 1

        avg_delta /= burst_count
        
        # if the bursts are in phase, the track was miss-detected, flip phase and recalculate sequence
        # TODO: make work for PAL
        if avg_delta < 90:
            track_rotation = chroma_rotations[1] if track_rotation == chroma_rotations[0] else chroma_rotations[0]
            # recalculate with the fixed track rotation
            phase_sequence, burst_phases = _get_phase_sequence(
                chroma,
                chroma_heterodyne,
                track_rotation,
                chroma_rotations,
                chroma_filter,
                burst_sin,
                burst_cos,
                burstarea,
                lineoffset,
                outwidth,
                linesout,
                end,
                do_phase_rotation_check,
                track_change_threshold,
                rotation_check_start_line,
            )

    # ***************************************************************************************
    # detect the correct starting phase using the expected phase quadrant of the color bursts
    # ***************************************************************************************
    if color_system == "NTSC":
        # find the phase of the color burst for the entire field
        I_total = 0
        Q_total = 0
        for linenumber, _, I, Q, _, _ in burst_phases:
            if (
                linenumber > burst_check_start and
                linenumber < burst_check_end
            ):
                magnitude = np.hypot(I, Q) + 1e-12
                I_total += I / magnitude
                Q_total += Q / magnitude  

        burst_phase_avg = np.degrees(np.arctan2(Q_total, I_total)) % 360

        coherence = np.hypot(I_total, Q_total) / len(burst_phases)
        burst_detected = coherence >= coherence_threshold      

        if prev_burst_phase_avg is not None:
            # if we have the phase difference between the previous burst and this burst, we further refine the detection based on the known phase delta between rotations
            delta = (burst_phase_avg - prev_burst_phase_avg) % 360
            phase_delta = int(round(delta / 90)) % 4
        else:
            # since there is no prior phase to determine the phase delta, only use isFirstField and quadrant
            phase_delta = -1

        # quantize to 90 degrees
        quadrant = int(round(burst_phase_avg) / 90) % 4

        # match the phase using the first field, detected color burst phase quadrant, and the phase difference from the previous burst
        phase_info = ntsc_phase_rotation_sequence.get(
            (is_first_field, quadrant, phase_delta),
            # if no matches, try without phase delta populated, possible if there is a gap in field cadence
            # results may be incorrect
            ntsc_phase_rotation_sequence.get((is_first_field, quadrant, -1), None)
        )

        if phase_info:
            field_phase_id, ntsc_phase_rotation = phase_info
        else:
            # something is really wrong with the color, log an error
            # with the current phase sequence, this condition should never be hit
            ldd.logger.error(f"Invalid NTSC color sequence: isFirstField: {is_first_field}, colorBurstPhase: {burst_phase_avg}, previousColorBurstPhase: {prev_burst_phase_avg}")
            # use the entry for frame 1
            field_phase_id = 1
            ntsc_phase_rotation = 3

        # adjust the starting phase
        if ntsc_phase_rotation != 0:
            shifted_phase_sequence = []
            for linenumber, rotation in phase_sequence:
                shifted_phase_sequence.append((linenumber, (rotation + ntsc_phase_rotation) % 4))
            phase_sequence = shifted_phase_sequence
    else:
        burst_phases = None
        field_phase_id = None
        burst_phase_avg = None
        burst_detected = None

    return track_rotation, phase_sequence, field_phase_id, burst_phases, burst_phase_avg, burst_detected
    
@njit(cache=True, nogil=True, fastmath=True)
def upconvert_chroma(
    chroma,
    lineoffset,
    linesout,
    outwidth,
    chroma_heterodyne,
    phase_rotation_sequence
):
    uphet = np.zeros(len(chroma), dtype=np.float32)
    phase_index = 0

    for linenumber, current_phase in phase_rotation_sequence:
        linestart = (linenumber - lineoffset) * outwidth
        lineend = linestart + outwidth

        heterodyne = chroma_heterodyne[current_phase][linestart:lineend]
        c = chroma[linestart:lineend]
        uphet[linestart:lineend] = c * heterodyne

    return uphet


@njit(cache=True, nogil=True)
def burst_deemphasis(chroma, lineoffset, linesout, outwidth, burstarea):
    for line in range(lineoffset, linesout + lineoffset):
        linestart = (line - lineoffset) * outwidth
        lineend = linestart + outwidth

        chroma[linestart + burstarea[1] + 5 : lineend] *= 2

    return chroma

@njit(cache=True, nogil=True, fastmath=True)
def shift_chroma_and_remove_dc(out_chroma, move):
    out_chroma = np.roll(out_chroma, move)
    # crude DC offset removal
    out_chroma -= np.mean(out_chroma)
    return out_chroma


def demod_chroma_filt(
    data, filter, blocklen, notch, do_notch=None, move=10, audio_notch=None
):
    out_chroma = sosfiltfilt_rust(filter, data[:blocklen])

    if audio_notch is not None:
        out_chroma = sps.filtfilt(
            audio_notch[0],
            audio_notch[1],
            out_chroma,
        )

    if do_notch is not None and do_notch:
        out_chroma = sps.filtfilt(
            notch[0],
            notch[1],
            out_chroma,
        )

    # Move chroma to compensate for Y filter delay.
    # value needs tweaking, ideally it should be calculated if possible.
    # TODO: Not sure if we need this after hilbert filter change, needs check.
    return shift_chroma_and_remove_dc(out_chroma, move)


def decode_chroma_phase_rotation(
    field,
    disable_tracking_cafc=False,
    chroma_rotation=None,
    detect_chroma_track_phase=False,
):
    chroma, _, _ = ldd.Field.downscale(field, channel="demod_burst")

    lineoffset = field.lineoffset + 1
    linesout = field.outlinecount
    outwidth = field.outlinelen

    burst_area_init = get_burst_area(field)
    burstarea = burst_area_init[0] - 5, burst_area_init[1] + 10

    prev_burst_phase = None
    if field.rf.color_system == "NTSC":
        if field.prevfield is not None:
            prev_burst_phase = field.prevfield.burst_phase_avg

    # Rotation per track
    # VHS PAL: Track1 0, Track2 -90
    # VHS NTSC: Track1 +90, Track2 -90
    # Betamax PAL: None - uses frequency offset instead
    # Betamax NTSC: Track1 180, Track2 0
    # Video8 NTSC: Track1 0, Track2 180
    # Video8 PAL: Track1 0, Track2 -90

    if field.rf.track_phase is None:
        # guess something for the first field
        if chroma_rotation:
            track_rotation = chroma_rotation[0]
        else:
            # Track 2 is rotated ccw in both NTSC and PAL for VHS
            # u-matic has no phase rotation.
            track_rotation = 0
    elif chroma_rotation:
        # flip
        if field.rf.track_phase == chroma_rotation[0]:
            track_rotation = chroma_rotation[1]
        else:
            track_rotation = chroma_rotation[0]
    else:
        track_rotation = field.rf.track_phase

    chroma_heterodyne = (
        field.rf.chroma_afc.getChromaHet()
        if (field.rf.do_cafc and not disable_tracking_cafc)
        else field.rf.chroma_heterodyne
    )

    return get_phase_rotation_sequence(
        chroma,
        lineoffset + linesout - 16, # check for track phase rotation around the headswitching area (bottom of field)
        lineoffset,
        linesout,
        outwidth,
        field.isFirstField,
        prev_burst_phase,
        field.rf.color_system,
        field.rf.fsc_wave,
        field.rf.fsc_cos_wave,
        detect_chroma_track_phase,
        track_rotation,
        chroma_rotation,
        chroma_heterodyne,
        burstarea,
        field.rf.Filters["FChromaFinal"],
    )

def process_chroma(
    field,
    disable_deemph=False,
    disable_comb=False,
    disable_tracking_cafc=False,
    do_chroma_deemphasis=False,
):
    # Run TBC/downscale on chroma (if new field, else uses cache)
    # Cached if chroma process is run multiple times on one field due to track detection.
    if field.chroma_tbc_buffer is None:
        chroma, _, _ = ldd.Field.downscale(field, channel="demod_burst")

        # If chroma AFC is enabled
        if field.rf.do_cafc:
            # it does the chroma filtering AFTER the TBC
            chroma = demod_chroma_filt(
                chroma,
                field.rf.chroma_afc.get_chroma_bandpass(),
                len(chroma),
                field.rf.Filters["FVideoNotch"],
                field.rf.notch,
                move=(int(10 * (field.rf.sys_params["outfreq"] / 40))),
                audio_notch=field.rf.Filters.get("FChromaAudioNotch", None),
            )

            if not disable_tracking_cafc:
                spec, meas, offset, cphase = field.rf.chroma_afc.freqOffset(chroma)
                ldd.logger.debug(
                    "Chroma under AFC: %.02f kHz, Offset (long term): %.02f Hz, Phase: %.02f deg"
                    % (meas / 1e3, offset, cphase * 360 / (2 * np.pi))
                )

        field.rf.chroma_tbc_buffer = chroma
        field.chroma_tbc_buffer = chroma
    else:
        chroma = field.chroma_tbc_buffer

    lineoffset = field.lineoffset + 1
    linesout = field.outlinecount
    outwidth = field.outlinelen

    burst_area_init = get_burst_area(field)
    burstarea = burst_area_init[0] - 5, burst_area_init[1] + 10

    # For NTSC, the color burst amplitude is doubled when recording, so we have to undo that.
    if field.rf.color_system == "NTSC":
        if not disable_deemph:
            chroma = burst_deemphasis(chroma, lineoffset, linesout, outwidth, burstarea)

    chroma_heterodyne = (
        field.rf.chroma_afc.getChromaHet()
        if (field.rf.do_cafc and not disable_tracking_cafc)
        else field.rf.chroma_heterodyne
    )

    uphet = upconvert_chroma(
        chroma,
        lineoffset,
        linesout,
        outwidth,
        chroma_heterodyne,
        field.phase_sequence,
    )

    # Filter out unwanted frequencies from the final chroma signal.
    # Mixing the signals will produce waves at the difference and sum of the
    # frequencies. We only want the difference wave which is at the correct color
    # carrier frequency here.
    # We do however want to be careful to avoid filtering out too much of the sideband.
    uphet = sosfiltfilt_rust(field.rf.Filters["FChromaFinal"], uphet)

    # FFT filter way to use a supergauss filter to more sharply cut out the upper harmonic
    # This may be a better approach but slows down things a bit much so not using for now
    # orig_len = len(uphet)
    # uphet = np_fft.irfft(np_fft.rfft(uphet) * field.rf.Filters["FChromaFinal"], n=orig_len)

    if do_chroma_deemphasis:
        b, a = field.rf.Filters["chroma_deemphasis"]
        uphet = sps.lfilter(b, a, uphet)

    # Basic comb filter for NTSC to calm the color a little.
    if not disable_comb:
        if field.rf.color_system == "NTSC":
            uphet = comb_c_ntsc(uphet, outwidth)
        else:
            uphet = comb_c_pal(uphet, outwidth)

    # Final automatic chroma gain.
    uphet, mean_rms = acc(
        uphet,
        field.rf.SysParams["burst_abs_ref"],
        burstarea[0],
        burstarea[1],
        outwidth,
        linesout,
    )

    field.rf.field_averages.chroma_level.push(mean_rms)

    return uphet


def check_increment_field_no(rf, field):
    """Increment field number if the raw data location moved significantly since the last call"""
    return None
    raw_loc = rf.decoder.readloc / rf.decoder.bytes_per_field

    prev_loc = field.prevfield.readloc if field.prevfield else None

    # print("dec readloc: ", rf.decoder.readloc, " field readloc", field.readloc, " prev readloc", prev_loc)
    # print("dec raw loc", raw_loc, "field raw loc", field.readloc / rf.decoder.bytes_per_field)

    if rf.last_raw_loc is None:
        rf.last_raw_loc = raw_loc

    if raw_loc > rf.last_raw_loc:
        rf.field_number += 1
    else:
        ldd.logger.debug("Raw data loc didn't advance.")

    # print("self field number", field.field_number, " rf.field_number", rf.field_number)

    return raw_loc


def decode_chroma_simple(field):
    """Upconvert the chroma signal
    Simple upconversion with no rotation etc for umatic, vcr, eiaj and similar.
    """

    field.chroma_tbc_buffer = None

    # Use field number based on raw data position
    # This may not be 100% accurate, so we may want to add some more logic to
    # make sure we re-check the phase occasionally.
    raw_loc = check_increment_field_no(field.rf, field)

    uphet = process_chroma(
        field, True, field.rf.options.disable_comb, disable_tracking_cafc=False
    )
    # Release to avoid keeping this im memory - TODO: should do this in a cleaner manner.
    field.chroma_tbc_buffer = None
    field.uphet_temp = uphet
    return chroma_to_u16(uphet)


def decode_chroma(field, do_chroma_deemphasis=False):
    """Do track detection if needed and upconvert the chroma signal"""
    rf = field.rf
    field.chroma_tbc_buffer = None

    uphet = process_chroma(
        field,
        disable_comb=rf.options.disable_comb,
        disable_tracking_cafc=False,
        do_chroma_deemphasis=do_chroma_deemphasis,
    )
    field.uphet_temp = uphet
    # Release to avoid keeping this im memory - should do this in a cleaner manner.
    field.chroma_tbc_buffer = None
    return chroma_to_u16(uphet)


def get_burst_area(field):
    return (
        math.floor(field.usectooutpx(field.rf.SysParams["colorBurstUS"][0])),
        math.ceil(field.usectooutpx(field.rf.SysParams["colorBurstUS"][1])),
    )


def mean_of_burst_sums(chroma_data, line_length, lines, burst_start, burst_end):
    """Sum the burst areas of two and two lines together, and return the mean of these sums."""
    IGNORED_LINES = 16

    burst_sums = []

    # We ignore the top and bottom 16 lines. The top will typically not have a color burst, and
    # the bottom 16 may be after or at the head switch where the phase rotation will be different.
    start_line = IGNORED_LINES
    end_line = lines - IGNORED_LINES

    for line_number in range(start_line, end_line, 2):
        burst_a = get_line(chroma_data, line_length, line_number)[burst_start:burst_end]
        burst_b = get_line(chroma_data, line_length, line_number + 1)[
            burst_start:burst_end
        ]

        # Use the absolute of the sums to differences cancelling out.
        mean_dev = np.mean(abs(burst_a + burst_b))

        burst_sums.append(mean_dev)

    mean_burst_sum = np.nanmean(burst_sums)
    return mean_burst_sum


@njit(cache=True, nogil=True)
def detect_burst_pal(
    chroma_data, sine_wave, cosine_wave, burst_area, line_length, lines
):
    """Decode the burst of most lines to see if we have a valid PAL color burst."""

    # Ignore the first and last 16 lines of the field.
    # first ones contain sync and often doesn't have color burst,
    # while the last lines of the field will contain the head switch and may be distorted.
    IGNORED_LINES = 16
    line_data = []
    burst_norm = np.full(lines, np.nan)

    # Decode the burst vectors on each line and try to get an average of the burst amplitude.
    for linenumber in range(IGNORED_LINES, lines - IGNORED_LINES):
        info = detect_burst_pal_line(
            chroma_data, sine_wave, cosine_wave, burst_area, line_length, linenumber
        )
        line_data.append(info)
        burst_norm[linenumber] = info.burst_norm

    burst_mean = np.nanmean(burst_norm[IGNORED_LINES : lines - IGNORED_LINES])

    return line_data, burst_mean


LineInfo = namedtuple("LineInfo", "linenum, bp, bq, vsw, burst_norm")


@njit(cache=True, nogil=True)
def detect_burst_pal_line(
    chroma_data, sine, cosine, burst_area, line_length, line_number
):
    """Detect burst function ported from the C++ chroma decoder (palcolour.cpp)

    Tries to decode the PAL chroma vectors from the line's color burst
    """
    empty_line = np.zeros_like(chroma_data[0:line_length])
    num_lines = chroma_data.size / line_length

    # Use an empty line if we try to access outside the field.
    def line_or_empty(line):
        return (
            get_line(chroma_data, line_length, line)
            if line >= 0 and line < num_lines
            else empty_line
        )

    in0 = line_or_empty(line_number)
    in1 = line_or_empty(line_number - 1)
    in2 = line_or_empty(line_number + 1)
    in3 = line_or_empty(line_number - 2)
    in4 = line_or_empty(line_number + 2)
    bp = 0
    bq = 0
    bpo = 0
    bqo = 0

    # (Comment from palcolor.cpp)
    # Find absolute burst phase relative to the reference carrier by
    # product detection.
    #
    # To avoid hue-shifts on alternate lines, the phase is determined by
    # averaging the phase on the current-line with the average of two
    # other lines, one above and one below the current line.
    #
    # For PAL we use the next-but-one line above and below (in the field),
    # which will have the same V-switch phase as the current-line (and 180
    # degree change of phase), and we also analyse the average (bpo/bqo
    # 'old') of the line immediately above and below, which have the
    # opposite V-switch phase (and a 90 degree subcarrier phase shift).
    for i in range(burst_area[0], burst_area[1]):
        bp += ((in0[i] - ((in3[i] + in4[i]) / 2.0)) / 2.0) * sine[i]
        bq += ((in0[i] - ((in3[i] + in4[i]) / 2.0)) / 2.0) * cosine[i]
        bpo += ((in2[i] - in1[i]) / 2.0) * sine[i]
        bqo += ((in2[i] - in1[i]) / 2.0) * cosine[i]

    # (Comment from palcolor.cpp)
    # Normalise the sums above
    burst_length = burst_area[1] - burst_area[0]

    bp /= burst_length
    bq /= burst_length
    bpo /= burst_length
    bqo /= burst_length

    # (Comment from palcolor.cpp)
    # Detect the V-switch state on this line.
    # I forget exactly why this works, but it's essentially comparing the
    # vector magnitude /difference/ between the phases of the burst on the
    # present line and previous line to the magnitude of the burst. This
    # may effectively be a dot-product operation...

    line_bp = 0
    line_bq = 0
    line_vsw = -1
    line_burst_norm = 0

    if ((bp - bpo) * (bp - bpo) + (bq - bqo) * (bq - bqo)) < (bp * bp + bq * bq) * 2:
        line_vsw = 1

    # (Comment from palcolor.cpp)
    # Average the burst phase to get -U (reference) phase out -- burst
    # phase is (-U +/-V). bp and bq will be of the order of 1000.
    line_bp = (bp - bqo) / 2
    line_bq = (bq + bpo) / 2

    # (Comment from palcolor.cpp)
    # Normalise the magnitude of the bp/bq vector to 1.
    # Kill colour if burst too weak.
    # XXX magic number 130000 !!! check!
    burst_norm = max(math.sqrt(line_bp * line_bp + line_bq * line_bq), 10000.0 / 128)
    line_burst_norm = burst_norm
    line_bp /= burst_norm
    line_bq /= burst_norm

    return LineInfo(line_number, line_bp, line_bq, line_vsw, line_burst_norm)


# Phase comprensation stuff - needs rework.
# def phase_shift(data, angle):
#     return np.fft.irfft(np.fft.rfft(data) * np.exp(1.0j * angle), len(data)).real


def get_burstarea(field):
    return (
        math.floor(field.usectooutpx(field.rf.SysParams["colorBurstUS"][0])),
        math.ceil(field.usectooutpx(field.rf.SysParams["colorBurstUS"][1])),
    )


def log_track_phase(track_phase, phase0_mean, phase1_mean, assumed_phase):
    ldd.logger.debug("Phase previously set: %i", track_phase)
    ldd.logger.debug("phase0 mean: %.02f", phase0_mean)
    ldd.logger.debug("phase1 mean: %.02f", phase1_mean)
    ldd.logger.debug("assumed_phase: %d", assumed_phase)


def try_detect_track_betamax_pal(field):
    pass


def try_detect_track_vhs_pal(field, chroma_rotation=None):
    """Try to detect what video track we are on.

    VHS tapes have two tracks with different azimuth that alternate and are read by alternating
    heads on the video drum. The phase of the color heterodyne varies depending on what track is
    being read from to avoid chroma crosstalk.
    Additionally, most tapes are recorded with a luma half-shift which shifts the fm-encoded
    luma frequencies slightly depending on the track to avoid luma crosstalk.
    """
    ldd.logger.debug("Trying to detect PAL track phase...")
    burst_area = get_burstarea(field)

    # Upconvert chroma twice, once for each possible track phase
    uphet = [
        process_chroma(field, True, True),
        process_chroma(field, True, True),
    ]

    sine_wave = field.rf.fsc_wave
    cosine_wave = field.rf.fsc_cos_wave

    # Try to decode the color burst from each of the upconverted chroma signals
    phase = list()
    for ix, uph in enumerate(uphet):
        phase.append(
            detect_burst_pal(
                uph,
                sine_wave,
                cosine_wave,
                burst_area,
                field.outlinelen,
                field.outlinecount,
            )
        )

    # We use the one where the phase of the chroma vectors make the most sense.
    phase0_mean, phase1_mean = phase[0][1], phase[1][1]
    assumed_phase = int(phase0_mean < phase1_mean)

    log_track_phase(field.rf.track_phase, phase0_mean, phase1_mean, assumed_phase)

    return assumed_phase, needs_recheck(phase0_mean, phase1_mean)

