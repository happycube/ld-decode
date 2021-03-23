import math
import numpy as np
import scipy.signal as sps
import copy

import itertools

import lddecode.core as ldd
import lddecode.utils as lddu
from lddecode.utils import unwrap_hilbert, inrange
import vhsdecode.utils as utils

import vhsdecode.formats as vhs_formats
from vhsdecode.addons.FMdeemph import FMDeEmphasisB
from vhsdecode.addons.chromasep import ChromaSepClass

from numba import njit

# Use PyFFTW's faster FFT implementation if available
try:
    import pyfftw.interfaces.numpy_fft as npfft
    import pyfftw.interfaces

    pyfftw.interfaces.cache.enable()
    pyfftw.interfaces.cache.set_keepalive_time(10)
except ImportError:
    import numpy.fft as npfft


def chroma_to_u16(chroma):
    """Scale the chroma output array to a 16-bit value for output."""
    S16_ABS_MAX = 32767

    if np.max(chroma) > S16_ABS_MAX or abs(np.min(chroma)) > S16_ABS_MAX:
        ldd.logger.warning("Chroma signal clipping.")
    return np.uint16(chroma + S16_ABS_MAX)


@njit
def acc(chroma, burst_abs_ref, burststart, burstend, linelength, lines):
    """Scale chroma according to the level of the color burst on each line."""

    output = np.zeros(chroma.size, dtype=np.double)
    for linenumber in range(16, lines):
        linestart = linelength * linenumber
        lineend = linestart + linelength
        line = chroma[linestart:lineend]
        output[linestart:lineend] = acc_line(line, burst_abs_ref, burststart, burstend)

    return output


@njit
def acc_line(chroma, burst_abs_ref, burststart, burstend):
    """Scale chroma according to the level of the color burst the line."""
    output = np.zeros(chroma.size, dtype=np.double)

    line = chroma
    burst_abs_mean = lddu.rms(line[burststart:burstend])
    # np.sqrt(np.mean(np.square(line[burststart:burstend])))
    #    burst_abs_mean = np.mean(np.abs(line[burststart:burstend]))
    scale = burst_abs_ref / burst_abs_mean if burst_abs_mean != 0 else 1
    output = line * scale

    return output


def getpulses_override(field):
    """Find sync pulses in the demodulated video sigal

    NOTE: TEMPORARY override until an override for the value itself is added upstream.
    """
    # pass one using standard levels

    # pulse_hz range:  vsync_ire - 10, maximum is the 50% crossing point to sync
    pulse_hz_min = field.rf.iretohz(field.rf.SysParams["vsync_ire"] - 10)
    pulse_hz_max = field.rf.iretohz(field.rf.SysParams["vsync_ire"] / 2)

    pulses = lddu.findpulses(
        field.data["video"]["demod_05"], pulse_hz_min, pulse_hz_max
    )

    if len(pulses) == 0:
        # can't do anything about this
        return pulses

    # determine sync pulses from vsync
    vsync_locs = []
    vsync_means = []

    for i, p in enumerate(pulses):
        if p.len > field.usectoinpx(10):
            vsync_locs.append(i)
            vsync_means.append(
                np.mean(
                    field.data["video"]["demod_05"][
                        int(p.start + field.rf.freq) : int(
                            p.start + p.len - field.rf.freq
                        )
                    ]
                )
            )

    if len(vsync_means) == 0:
        return None

    synclevel = np.median(vsync_means)

    if np.abs(field.rf.hztoire(synclevel) - field.rf.SysParams["vsync_ire"]) < 5:
        # sync level is close enough to use
        return pulses

    if vsync_locs is None or not len(vsync_locs):
        return None

    # Now compute black level and try again

    # take the eq pulses before and after vsync
    r1 = range(vsync_locs[0] - 5, vsync_locs[0])
    r2 = range(vsync_locs[-1] + 1, vsync_locs[-1] + 6)

    black_means = []

    for i in itertools.chain(r1, r2):
        if i < 0 or i >= len(pulses):
            continue

        p = pulses[i]
        if inrange(p.len, field.rf.freq * 0.75, field.rf.freq * 3):
            black_means.append(
                np.mean(
                    field.data["video"]["demod_05"][
                        int(p.start + (field.rf.freq * 5)) : int(
                            p.start + (field.rf.freq * 20)
                        )
                    ]
                )
            )

    blacklevel = np.median(black_means)

    pulse_hz_min = synclevel - (field.rf.SysParams["hz_ire"] * 10)
    pulse_hz_max = (blacklevel + synclevel) / 2

    return lddu.findpulses(field.data["video"]["demod_05"], pulse_hz_min, pulse_hz_max)


def filter_simple(data, filter_coeffs):
    return sps.sosfiltfilt(filter_coeffs, data, padlen=150)


@njit
def comb_c_pal(data, line_len):
    """Very basic comb filter, adds the signal together with a signal delayed by 2H,
    and one advanced by 2H
    line by line. VCRs do this to reduce crosstalk.
    """

    data2 = data.copy()
    numlines = len(data) // line_len
    for line_num in range(16, numlines - 2):
        adv2h = data2[(line_num + 2) * line_len : (line_num + 3) * line_len]
        delayed2h = data2[(line_num - 2) * line_len : (line_num - 1) * line_len]
        line_slice = data[line_num * line_len : (line_num + 1) * line_len]
        # Let the delayed signal contribute 1/4 and advanced 1/4.
        # Could probably make the filtering configurable later.
        data[line_num * line_len : (line_num + 1) * line_len] = (
            (line_slice) - (delayed2h) - adv2h
        ) / 3
    return data


@njit
def comb_c_ntsc(data, line_len):
    """Very basic comb filter, adds the signal together with a signal delayed by 1H,
    line by line. VCRs do this to reduce crosstalk.
    """

    data2 = data.copy()
    numlines = len(data) // line_len
    for line_num in range(16, numlines - 2):
        delayed1h = data2[(line_num - 1) * line_len : (line_num) * line_len]
        line_slice = data[line_num * line_len : (line_num + 1) * line_len]
        # Let the delayed signal contribute 1/3.
        # Could probably make the filtering configurable later.
        data[line_num * line_len : (line_num + 1) * line_len] = (
            (line_slice * 2) - (delayed1h)
        ) / 3
    return data


@njit
def upconvert_chroma(
    chroma,
    lineoffset,
    linesout,
    outwidth,
    chroma_heterodyne,
    phase_rotation,
    starting_phase,
):
    uphet = np.zeros(len(chroma), dtype=np.double)
    if phase_rotation == 0:
        # Track 1 - for PAL, phase doesn't change.
        start = lineoffset
        end = lineoffset + (outwidth * linesout)
        heterodyne = chroma_heterodyne[0][start:end]
        c = chroma[start:end]
        # Mixing the chroma signal with a signal at the frequency of colour under + fsc gives us
        # a signal with frequencies at the difference and sum, the difference is what we want as
        # it's at the right frequency.
        mixed = heterodyne * c

        uphet[start:end] = mixed

    else:
        #        rotation = [(0,0),(90,-270),(180,-180),(270,-90)]
        # Track 2 - needs phase rotation or the chroma will be inverted.
        phase = starting_phase
        for linenumber in range(lineoffset, linesout + lineoffset):
            linestart = (linenumber - lineoffset) * outwidth
            lineend = linestart + outwidth

            heterodyne = chroma_heterodyne[phase][linestart:lineend]

            c = chroma[linestart:lineend]

            line = heterodyne * c

            uphet[linestart:lineend] = line

            phase = (phase + phase_rotation) % 4
    return uphet


def get_burst_area(field):
    return (
        math.floor(field.usectooutpx(field.rf.SysParams["colorBurstUS"][0])),
        math.ceil(field.usectooutpx(field.rf.SysParams["colorBurstUS"][1])),
    )


@njit
def get_line(data, line_length, line):
    return data[line * line_length : (line + 1) * line_length]


class LineInfo:
    """Helper class to store line burst info for PAL."""

    def __init__(self, num):
        self.linenum = num
        self.bp = 0
        self.bq = 0
        self.vsw = -1
        self.burst_norm = 0

    def __str__(self):
        return "<num: %s, bp: %s, bq: %s, vsw: %s, burst_norm: %s>" % (
            self.linenum,
            self.bp,
            self.bq,
            self.vsw,
            self.burst_norm,
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
    line = LineInfo(line_number)
    if ((bp - bpo) * (bp - bpo) + (bq - bqo) * (bq - bqo)) < (bp * bp + bq * bq) * 2:
        line.vsw = 1

    # (Comment from palcolor.cpp)
    # Average the burst phase to get -U (reference) phase out -- burst
    # phase is (-U +/-V). bp and bq will be of the order of 1000.
    line.bp = (bp - bqo) / 2
    line.bq = (bq + bpo) / 2

    # (Comment from palcolor.cpp)
    # Normalise the magnitude of the bp/bq vector to 1.
    # Kill colour if burst too weak.
    # XXX magic number 130000 !!! check!
    burst_norm = max(math.sqrt(line.bp * line.bp + line.bq * line.bq), 130000.0 / 128)
    line.burst_norm = burst_norm
    line.bp /= burst_norm
    line.bq /= burst_norm

    return line


@njit
def detect_burst_ntsc(
    chroma_data, sine_wave, cosine_wave, burst_area, line_length, lines
):
    """Check the phase of the color burst."""

    # Ignore the first and last 16 lines of the field.
    # first ones contain sync and often doesn't have color burst,
    # while the last lines of the field will contain the head switch and may be distorted.
    IGNORED_LINES = 16
    odd_i_acc = 0
    even_i_acc = 0

    for linenumber in range(IGNORED_LINES, lines - IGNORED_LINES):
        bi, _, _ = detect_burst_ntsc_line(
            chroma_data, sine_wave, cosine_wave, burst_area, line_length, linenumber
        )
        #        line_data.append((bi, bq, linenumber))
        if linenumber % 2 == 0:
            even_i_acc += bi
        else:
            odd_i_acc += bi

    num_lines = lines - (IGNORED_LINES * 2)

    return even_i_acc / num_lines, odd_i_acc / num_lines


@njit
def detect_burst_ntsc_line(
    chroma_data, sine, cosine, burst_area, line_length, line_number
):
    bi = 0
    bq = 0
    # TODO:
    sine = sine[burst_area[0] :]
    cosine = cosine[burst_area[0] :]
    line = get_line(chroma_data, line_length, line_number)
    for i in range(burst_area[0], burst_area[1]):
        bi += line[i] * sine[i]
        bq += line[i] * cosine[i]

    burst_length = burst_area[1] - burst_area[0]

    bi /= burst_length
    bq /= burst_length

    burst_norm = max(math.sqrt(bi * bi + bq * bq), 130000.0 / 128)
    bi /= burst_norm
    bq /= burst_norm
    return bi, bq, burst_norm


def get_field_phase_id(field):
    """Try to determine which of the 4 NTSC phase cycles the field is.
    For tapes the result seem to not be cyclical at all, not sure if that's normal
    or if something is off.
    The most relevant thing is which lines the burst phase is positive or negative on.
    """
    burst_area = get_burst_area(field)

    sine_wave = field.rf.fsc_wave
    cosine_wave = field.rf.fsc_cos_wave

    # Try to detect the average burst phase of odd and even lines.
    even, odd = detect_burst_ntsc(
        field.uphet_temp,
        sine_wave,
        cosine_wave,
        burst_area,
        field.outlinelen,
        field.outlinecount,
    )

    # This map is based on (first field, field14)
    map4 = {
        (True, True): 1,
        (False, False): 2,
        (True, False): 3,
        (False, True): 4,
    }

    phase_id = map4[(field.isFirstField, even < odd)]

    # ldd.logger.info("Field: %i, Odd I %f , Even I %f, phase id %i, field first %i",
    #                field.rf.field_number, even, odd, phase_id, field.isFirstField)

    return phase_id


def find_crossings(data, threshold):
    """Find where the data crosses the set threshold."""

    # We do this by constructing array where positions above
    # the threshold are marked as true, other sfalse,
    # and use diff to mark where the value changes.
    crossings = np.diff(data < threshold)
    # TODO: See if we can avoid reduntantly looking for both up and
    # down crossing when we just need one of them.
    return crossings


def find_crossings_dir(data, threshold, look_for_down):
    """Find where the data crosses the set threshold
    the look_for_down parameters determines if the crossings returned are down
    or up crossings.
    ."""
    crossings = find_crossings(data, threshold)
    crossings_pos = np.argwhere(crossings)[:, 0]
    if len(crossings_pos) <= 0:
        return []
    first_cross = crossings_pos[0]
    if first_cross >= len(data):
        return []
    first_crossing_is_down = data[first_cross] > data[first_cross + 1]
    if first_crossing_is_down == look_for_down:
        return crossings_pos[::2]
    else:
        return crossings_pos[1::2]


def combine_to_dropouts(crossings_down, crossings_up, merge_threshold):
    """Combine arrays of up and down crossings, and merge ones with small gaps between them.
    Intended to be used where up and down crossing levels are different, the two lists will not
    always alternate or have the same length.
    Returns a list of start/end tuples.
    """
    used = []

    # TODO: Fix when ending on dropout

    cr_up = iter(crossings_up)
    last_u = 0
    # Loop through crossings and combine
    # TODO: Doing this via a loop is probably not ideal in python,
    # we may want to look for a way to more directly generate a list of down/up crossings
    # with hysteresis.
    for d in crossings_down:
        if d < last_u:
            continue

        # If the distance between two dropouts is very small, we merge them.
        if d - last_u < merge_threshold and len(used) > 0:
            # Pop the last added dropout and use it's starting point
            # as the start of the merged one.
            last = used.pop()
            d = last[0]

        for u in cr_up:
            if u > d:
                used.append((d, u))
                last_u = u
                break

    return used


def detect_dropouts_rf(field):
    """Look for dropouts in the input data, based on rf envelope amplitude.
    Uses either an percentage of the frame average rf level, or an absolute value.
    TODO: A more advanced algorithm with hysteresis etc.
    """
    env = field.data["video"]["envelope"]
    threshold_p = field.rf.dod_threshold_p
    threshold_abs = field.rf.dod_threshold_a
    hysteresis = field.rf.dod_hysteresis

    threshold = 0.0
    if threshold_abs is not None:
        threshold = threshold_abs
    else:
        # Generate a threshold based on the field envelope average.
        # This may not be ideal on a field with a lot of droputs,
        # so we may want to use statistics of the previous averages
        # to avoid the threshold ending too low.
        field_average = np.mean(field.data["video"]["envelope"])
        threshold = field_average * threshold_p

    errlist = []

    crossings_down = find_crossings_dir(env, threshold, True)
    crossings_up = find_crossings_dir(env, threshold * hysteresis, False)

    if (
        len(crossings_down) > 0
        and len(crossings_up) > 0
        and crossings_down[0] > crossings_up[0]
        and env[0] < threshold
    ):
        # Handle if we start on a dropout by adding a zero at the start since we won't have any
        # down crossing for it in the data.
        crossings_down = np.concatenate((np.array([0]), crossings_down), axis=None)

    errlist = combine_to_dropouts(
        crossings_down, crossings_up, vhs_formats.DOD_MERGE_THRESHOLD
    )

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


# Phase comprensation stuff - needs rework.
# def phase_shift(data, angle):
#     return np.fft.irfft(np.fft.rfft(data) * np.exp(1.0j * angle), len(data)).real


def check_increment_field_no(rf):
    """Increment field number if the raw data location moved significantly since the last call"""
    raw_loc = rf.decoder.readloc / rf.decoder.bytes_per_field

    if rf.last_raw_loc is None:
        rf.last_raw_loc = raw_loc

    if raw_loc > rf.last_raw_loc:
        rf.field_number += 1
    else:
        ldd.logger.info("Raw data loc didn't advance.")


class FieldPALCVBS(ldd.FieldPAL):
    def __init__(self, *args, **kwargs):
        super(FieldPALCVBS, self).__init__(*args, **kwargs)

    def refine_linelocs_pilot(self, linelocs=None):
        """Override this as regular-band u-matic does not have a pilot burst."""
        if linelocs is None:
            linelocs = self.linelocs2.copy()
        else:
            linelocs = linelocs.copy()

        return linelocs

    def downscale(self, final=False, *args, **kwargs):
        dsout, dsaudio, dsefm = super(FieldPALCVBS, self).downscale(
            final, *args, **kwargs
        )

        return (dsout, []), dsaudio, dsefm

    def calc_burstmedian(self):
        # Set this to a constant value for now to avoid the comb filter messing with chroma levels.
        return 1.0

    def determine_field_number(self):
        """Workaround to shut down phase id mismatch warnings, the actual code
        doesn't work properly with the vhs output at the moment."""
        return 1 + (self.rf.field_number % 8)

    def getpulses(self):
        """Find sync pulses in the demodulated video sigal

        NOTE: TEMPORARY override until an override for the value itself is added upstream.
        """
        return getpulses_override(self)

    def compute_deriv_error(self, linelocs, baserr):
        """Disabled this for now as tapes have large variations in line pos
        Due to e.g head switch.
        compute errors based off the second derivative - if it exceeds 1 something's wrong,
        and if 4 really wrong...
        """
        return baserr

    def dropout_detect(self):
        return detect_dropouts_rf(self)


class FieldNTSCCVBS(ldd.FieldNTSC):
    def __init__(self, *args, **kwargs):
        super(FieldNTSCCVBS, self).__init__(*args, **kwargs)

    def _refine_linelocs_burst(self, linelocs=None):
        """Override this as it's LD specific
        At some point in the future we could maybe use the burst location to improve hsync accuracy,
        but ignore it for now.
        """
        if linelocs is None:
            linelocs = self.linelocs2
        else:
            linelocs = linelocs.copy()

        return linelocs

    def calc_burstmedian(self):
        # Set this to a constant value for now to avoid the comb filter messing with chroma levels.
        return 1.0

    def downscale(self, linesoffset=0, final=False, *args, **kwargs):
        dsout, dsaudio, dsefm = super(FieldNTSCCVBS, self).downscale(
            linesoffset, final, *args, **kwargs
        )

        return (dsout, []), dsaudio, dsefm

    def dropout_detect(self):
        return detect_dropouts_rf(self)

    def getpulses(self):
        """Find sync pulses in the demodulated video sigal

        NOTE: TEMPORARY override until an override for the value itself is added upstream.
        """
        return getpulses_override(self)

    def compute_deriv_error(self, linelocs, baserr):
        """Disabled this for now as line starts can vary widely."""
        return baserr


# Superclass to override laserdisc-specific parts of ld-decode with stuff that works for VHS
#
# We do this simply by using inheritance and overriding functions. This results in some redundant
# work that is later overridden, but avoids altering any ld-decode code to ease merging back in
# later as the ld-decode is in flux at the moment.
class CVBSDecode(ldd.LDdecode):
    def __init__(
        self,
        fname_in,
        fname_out,
        freader,
        logger,
        system="NTSC",
        threads=1,
        inputfreq=40,
        level_adjust=0.2,
        rf_options={},
        extra_options={},
    ):
        super(CVBSDecode, self).__init__(
            fname_in,
            fname_out,
            freader,
            logger,
            analog_audio=False,
            system=system,
            doDOD=False,
            threads=threads,
            extra_options=extra_options,
        )
        # Adjustment for output to avoid clipping.
        self.level_adjust = level_adjust
        # Overwrite the rf decoder with the VHS-altered one
        self.rf = VHSRFDecode(
            system=system,
            tape_format="UMATIC",
            inputfreq=inputfreq,
            rf_options=rf_options,
        )

        # Store reference to ourself in the rf decoder - needed to access data location for track
        # phase, may want to do this in a better way later.
        self.rf.decoder = self
        if system == "PAL":
            self.FieldClass = FieldPALCVBS
        elif system == "NTSC":
            self.FieldClass = FieldNTSCCVBS
        else:
            raise Exception("Unknown video system!", system)

        self.demodcache = ldd.DemodCache(
            self.rf, self.infile, self.freader, num_worker_threads=self.numthreads
        )

    # Override to avoid NaN in JSON.
    def calcsnr(self, f, snrslice):
        data = f.output_to_ire(f.dspicture[snrslice])

        signal = np.mean(data)
        noise = np.std(data)

        # Make sure signal is positive so we don't try to do log on a negative value.
        if signal < 0.0:
            ldd.logger.info(
                "WARNING: Negative mean for SNR, changing to absolute value."
            )
            signal = abs(signal)
        if noise == 0:
            return 0
        return 20 * np.log10(signal / noise)

    def calcpsnr(self, f, snrslice):
        data = f.output_to_ire(f.dspicture[snrslice])

        #        signal = np.mean(data)
        noise = np.std(data)
        if noise == 0:
            return 0
        return 20 * np.log10(100 / noise)

    def buildmetadata(self, f):
        if math.isnan(f.burstmedian):
            f.burstmedian = 0.0
        return super(CVBSDecode, self).buildmetadata(f)

    # For laserdisc this decodes frame numbers from VBI metadata, but there won't be such a thing on
    # VHS, so just skip it.
    def decodeFrameNumber(self, f1, f2):
        return None

    # Again ignored for tapes
    def checkMTF(self, field, pfield=None):
        return True

    def writeout(self, dataset):
        f, fi, (picturey, picturec), audio, efm = dataset

        fi["audioSamples"] = 0
        self.fieldinfo.append(fi)

        self.outfile_video.write(picturey)
        self.fields_written += 1

    def close(self):
        super(CVBSDecode, self).close()

    def computeMetricsNTSC(self, metrics, f, fp=None):
        return None

    def build_json(self, f):
        try:
            jout = super(CVBSDecode, self).build_json(f)
            black = jout["videoParameters"]["black16bIre"]
            white = jout["videoParameters"]["white16bIre"]

            jout["videoParameters"]["black16bIre"] = black * (1 - self.level_adjust)
            jout["videoParameters"]["white16bIre"] = white * (1 + self.level_adjust)
            return jout
        except TypeError as e:
            print("Cannot build json: %s" % e)
            return None


class VHSRFDecode(ldd.RFDecode):
    def __init__(self, inputfreq=40, system="NTSC", tape_format="VHS", rf_options={}):

        # First init the rf decoder normally.
        super(VHSRFDecode, self).__init__(
            inputfreq, system, decode_analog_audio=False, has_analog_audio=False
        )

        self.chroma_trap = rf_options.get("chroma_trap", False)
        self.notch = rf_options.get("notch", None)
        self.notch_q = rf_options.get("notch_q", 10.0)

        self.hsync_tolerance = 0.8

        self.field_number = 0
        self.last_raw_loc = None

        # Then we override the laserdisc parameters with VHS ones.
        if system == "PAL":
            self.SysParams = copy.deepcopy(vhs_formats.SysParams_PAL_UMATIC)
            self.DecoderParams = copy.deepcopy(vhs_formats.RFParams_PAL_UMATIC)
        elif system == "NTSC":
            self.SysParams = copy.deepcopy(vhs_formats.SysParams_NTSC_UMATIC)
            self.DecoderParams = copy.deepcopy(vhs_formats.RFParams_NTSC_UMATIC)
        else:
            raise Exception("Unknown video system! ", system)

        # TEMP just set this high so it doesn't mess with anything.
        self.DecoderParams["video_lpf_freq"] = 6800000

        # Lastly we re-create the filters with the new parameters.
        self.computevideofilters()

        self.Filters["FVideo"] = self.Filters["Fvideo_lpf"]
        SF = self.Filters
        SF["FVideo05"] = SF["Fvideo_lpf"] * SF["F05"]

        # Filter to pick out color-under chroma component.
        # filter at about twice the carrier. (This seems to be similar to what VCRs do)
        # TODO: Needs tweaking
        # Note: order will be doubled since we use filtfilt.
        # chroma_lowpass = sps.butter(
        #     2,
        #     [50000 / self.freq_hz_half, DP["chroma_bpf_upper"] / self.freq_hz_half],
        #     btype="bandpass",
        #     output="sos",
        # )
        # self.Filters["FVideoBurst"] = chroma_lowpass

        if self.notch is not None:
            self.Filters["FVideoNotch"] = sps.iirnotch(
                self.notch / self.freq_half, self.notch_q
            )
            # self.Filters["FVideoNotchF"] = lddu.filtfft(
            #     self.Filters["FVideoNotch"], self.blocklen
            # )

        # The following filters are for post-TBC:
        # The output sample rate is at approx 4fsc
        fsc_mhz = self.SysParams["fsc_mhz"]
        out_sample_rate_mhz = fsc_mhz * 4
        out_frequency_half = out_sample_rate_mhz / 2

        # Final band-pass filter for chroma output.
        # Mostly to filter out the higher-frequency wave that results from signal mixing.
        # Needs tweaking.
        # Note: order will be doubled since we use filtfilt.
        chroma_bandpass_final = sps.butter(
            1,
            [
                (fsc_mhz - 0.1) / out_frequency_half,
                (fsc_mhz + 0.1) / out_frequency_half,
            ],
            btype="bandpass",
            output="sos",
        )
        self.Filters["FChromaBpf"] = chroma_bandpass_final

        # Increase the cutoff at the end of blocks to avoid edge distortion from filters
        # making it through.
        self.blockcut_end = 1024
        self.demods = 0

        self.chromaTrap = ChromaSepClass(self.freq_hz, self.SysParams["fsc_mhz"])

    def computedelays(self, mtf_level=0):
        """Override computedelays
        It's normally used for dropout compensation, but the dropout compensation implementation
        in ld-decode assumes composite color. This function is called even if it's disabled, and
        seems to break with the VHS setup, so we disable it by overriding it for now.
        """
        # Set these to 0 for now, the metrics calculations look for them.
        self.delays = {}
        self.delays["video_sync"] = 0
        self.delays["video_white"] = 0

    def demodblock(self, data=None, mtf_level=0, fftdata=None, cut=False):
        data = npfft.ifft(fftdata).real

        rv = {}

        # applies the Subcarrier trap
        # (this will remove most chroma info)
        # luma = self.chromaTrap.work(data)
        luma = data

        luma += 0xFFFF / 2
        luma /= 4 * 0xFFFF
        luma *= self.iretohz(100)
        luma += self.iretohz(self.SysParams["vsync_ire"])

        if self.notch is not None:
            luma = sps.filtfilt(
                self.Filters["FVideoNotch"][0],
                self.Filters["FVideoNotch"][1],
                luma,
            )

        luma_fft = npfft.rfft(luma)

        luma05_fft = (
            luma_fft * self.Filters["F05"][: (len(self.Filters["F05"]) // 2) + 1]
        )
        luma05 = npfft.irfft(luma05_fft)
        luma05 = np.roll(luma05, -self.Filters["F05_offset"])
        videoburst = npfft.irfft(
            luma_fft * self.Filters["Fburst"][: (len(self.Filters["Fburst"]) // 2) + 1]
        )

        if False:
            import matplotlib.pyplot as plt

            fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True)
            # ax1.plot((20 * np.log10(self.Filters["Fdeemp"])))
            #        ax1.plot(hilbert, color='#FF0000')
            # ax1.plot(data, color="#00FF00")
            ax1.axhline(self.iretohz(0))
            ax1.axhline(self.iretohz(self.SysParams["vsync_ire"]))
            ax1.axhline(self.iretohz(7.5))
            ax1.axhline(self.iretohz(100))
            # print("Vsync IRE", self.SysParams["vsync_ire"])
            #            ax2 = ax1.twinx()
            #            ax3 = ax1.twinx()
            ax1.plot(luma[:2048])
            ax2.plot(luma05[:2048])
            #            ax4.plot(env, color="#00FF00")
            #            ax3.plot(np.angle(hilbert))
            #            ax4.plot(hilbert.imag)
            #            crossings = find_crossings(env, 700)
            #            ax3.plot(crossings, color="#0000FF")
            plt.show()
        #            exit(0)

        video_out = np.rec.array(
            [luma, luma05, videoburst, data],
            names=["demod", "demod_05", "demod_burst", "raw"],
        )

        rv["video"] = (
            video_out[self.blockcut : -self.blockcut_end] if cut else video_out
        )

        return rv
