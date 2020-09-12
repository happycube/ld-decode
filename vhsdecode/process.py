import math
import numpy as np
import scipy.signal as sps
import copy

import lddecode.core as ldd
import lddecode.utils as lddu
from lddecode.utils import unwrap_hilbert, inrange
import vhsdecode.utils as utils

import vhsdecode.formats as vhs_formats


def toDB(val):
    return 20 * np.log10(val)


def fromDB(val):
    return 10.0 ** (val / 20.0)


def chroma_to_u16(chroma):
    """Scale the chroma output array to a 16-bit value for output."""
    S16_ABS_MAX = 32767

    if np.max(chroma) > S16_ABS_MAX or abs(np.min(chroma)) > S16_ABS_MAX:
        print("Warning! Chroma signal clipping.")

    return np.uint16(chroma + S16_ABS_MAX)


def acc(chroma, burst_abs_ref, burststart, burstend, linelength, lines):
    """Scale chroma according to the level of the color burst on each line."""

    output = np.zeros(chroma.size, dtype=np.double)
    for l in range(16, lines):
        linestart = linelength * l
        lineend = linestart + linelength
        line = chroma[linestart:lineend]
        output[linestart:lineend] = acc_line(line, burst_abs_ref, burststart, burstend)

    return output


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


def genLowShelf(f0, dbgain, qfactor, fs):
    """Generate low shelving filter coeficcients (digital).
    f0: The frequency where the gain in decibel is at half the maximum value.
       Normalized to sampling frequency, i.e output will be filter from 0 to 2pi.
    dbgain: gain at the top of the shelf in decibels
    qfactor: determines shape of filter TODO: Document better
    fs: sampling frequency

    Based on: https://www.w3.org/2011/audio/audio-eq-cookbook.html
    """
    # Not sure if the implementation is quite correct here but it seems to work
    a = 10 ** (dbgain / 40.0)
    w0 = 2 * math.pi * (f0 / fs)
    alpha = math.sin(w0) / (2 * qfactor)

    cosw0 = math.cos(w0)
    asquared = math.sqrt(a)

    b0 = a * ((a + 1) - (a - 1) * cosw0 + 2 * asquared * alpha)
    b1 = 2 * a * ((a - 1) - (a + 1) * cosw0)
    b2 = a * ((a + 1) - (a - 1) * cosw0 - 2 * asquared * alpha)
    a0 = (a + 1) + (a - 1) * cosw0 + 2 * asquared * alpha
    a1 = -2 * ((a - 1) + (a + 1) * cosw0)
    a2 = (a + 1) + (a - 1) * cosw0 - 2 * asquared * alpha
    return [b0, b1, b2], [a0, a1, a2]


def genHighShelf(f0, dbgain, qfactor, fs):
    """Generate high shelving filter coeficcients (digital).
    f0: The frequency where the gain in decibel is at half the maximum value.
       Normalized to sampling frequency, i.e output will be filter from 0 to 2pi.
    dbgain: gain at the top of the shelf in decibels
    qfactor: determines shape of filter TODO: Document better
    fs: sampling frequency

    TODO: Generate based on -3db
    Based on: https://www.w3.org/2011/audio/audio-eq-cookbook.html
    """
    a = 10 ** (dbgain / 40.0)
    w0 = 2 * math.pi * (f0 / fs)
    alpha = math.sin(w0) / (2 * qfactor)

    cosw0 = math.cos(w0)
    asquared = math.sqrt(a)

    b0 = a * ((a + 1) + (a - 1) * cosw0 + 2 * asquared * alpha)
    b1 = -2 * a * ((a - 1) + (a + 1) * cosw0)
    b2 = a * ((a + 1) + (a - 1) * cosw0 - 2 * asquared * alpha)
    a0 = (a + 1) - (a - 1) * cosw0 + 2 * asquared * alpha
    a1 = 2 * ((a - 1) - (a + 1) * cosw0)
    a2 = (a + 1) - (a - 1) * cosw0 - 2 * asquared * alpha
    return [b0, b1, b2], [a0, a1, a2]


def filter_simple(data, filter_coeffs):
    fb, fa = filter_coeffs
    return sps.filtfilt(fb, fa, data, padlen=150)


# def comb_c_pal(data, linelen):
#     """Very basic comb filter, adds the signal together with a signal delayed by 2H,
#     line by line. VCRs do this to reduce crosstalk.
#     """

#     data2 = data.copy()
#     numlines = len(data) // linelen
#     for l in range(16,numlines - 2):
#         delayed2h = data[(l - 2) * linelen:(l - 1) * linelen]
#         data[l * linelen:(l + 1) * linelen] += (delayed2h / 2)
#     return data


def upconvert_chroma(
    chroma,
    lineoffset,
    linesout,
    outwidth,
    chroma_heterodyne,
    phase_rotation,
    starting_phase,
):
    uphet = np.zeros(chroma.size, dtype=np.double)
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
        for l in range(lineoffset, linesout + lineoffset):
            linenum = l - lineoffset
            linestart = (l - lineoffset) * outwidth
            lineend = linestart + outwidth

            heterodyne = chroma_heterodyne[phase][linestart:lineend]

            c = chroma[linestart:lineend]

            line = heterodyne * c

            uphet[linestart:lineend] = line

            phase = (phase + phase_rotation) % 4
    return uphet


def burst_deemphasis(chroma, lineoffset, linesout, outwidth, burstarea):
    for l in range(lineoffset, linesout + lineoffset):
        linestart = (l - lineoffset) * outwidth
        lineend = linestart + outwidth

        chroma[linestart + burstarea[1] + 5 : lineend] *= 8

    return chroma


def process_chroma(field, track_phase):
    # Run TBC/downscale on chroma.
    chroma, _, _ = ldd.Field.downscale(field, channel="demod_burst")

    lineoffset = field.lineoffset + 1
    linesout = field.outlinecount
    outwidth = field.outlinelen

    burstarea = (
        math.floor(field.usectooutpx(field.rf.SysParams["colorBurstUS"][0]) - 5),
        math.ceil(field.usectooutpx(field.rf.SysParams["colorBurstUS"][1])) + 10,
    )

    # For NTSC, the color burst amplitude is doubled when recording, so we have to undo that.
    if field.rf.system == "NTSC":
        chroma = burst_deemphasis(chroma, lineoffset, linesout, outwidth, burstarea)

    # Track 2 is rotated ccw in both NTSC and PAL
    phase_rotation = -1
    # What phase we start on. (Needed for NTSC to get the color phase correct)
    starting_phase = 0

    if field.rf.field_number % 2 == track_phase:
        if field.rf.system == "PAL":
            # For PAL, track 1 has no rotation.
            phase_rotation = 0
        elif field.rf.system == "NTSC":
            # For NTSC, track 1 rotates cw
            phase_rotation = 1
            starting_phase = 1
        else:
            raise Exception("Unknown video system!", field.rf.system)

    uphet = upconvert_chroma(
        chroma,
        lineoffset,
        linesout,
        outwidth,
        field.rf.chroma_heterodyne,
        phase_rotation,
        starting_phase,
    )

    # uphet = comb_c_pal(uphet,outwidth)

    # Filter out unwanted frequencies from the final chroma signal.
    # Mixing the signals will produce waves at the difference and sum of the
    # frequencies. We only want the difference wave which is at the correct color
    # carrier frequency here.
    # We do however want to be careful to avoid filtering out too much of the sideband.
    uphet = filter_simple(uphet, field.rf.Filters["FChromaFinal"])

    # Final automatic chroma gain.
    uphet = acc(
        uphet,
        field.rf.SysParams["burst_abs_ref"],
        burstarea[0],
        burstarea[1],
        outwidth,
        linesout,
    )

    return uphet


def get_line(data, line_length, line):
    return data[line * line_length : (line + 1) * line_length]


class LineInfo:
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
    for l in range(IGNORED_LINES, lines - IGNORED_LINES):
        info = detect_burst_pal_line(
            chroma_data, sine_wave, cosine_wave, burst_area, line_length, l
        )
        line_data.append(info)
        burst_norm[l] = info.burst_norm

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


# Phase comprensation stuff - needs rework.
# def phase_shift(data, angle):
#     return np.fft.irfft(np.fft.rfft(data) * np.exp(1.0j * angle), len(data)).real

# def detect_phase(data):
#     data = data / np.mean(abs(data))
#     return lddu.calczc(data, 1, 0, edge=1)


class FieldPALVHS(ldd.FieldPAL):
    def __init__(self, *args, **kwargs):
        super(FieldPALVHS, self).__init__(*args, **kwargs)

    def refine_linelocs_pilot(self, linelocs=None):
        """Override this as it's LD specific"""
        if linelocs is None:
            linelocs = self.linelocs2.copy()
        else:
            linelocs = linelocs.copy()

        return linelocs

    def processChroma(self):
        """Upconvert the chroma signal"""
        # Use field number based on raw data position
        # This may not be 100% accurate, so we may want to add some more logic to
        # make sure we re-check the phase occasionally.
        raw_loc = self.rf.decoder.readloc / self.rf.decoder.bytes_per_field

        # Re-check phase if we moved very far since last time.
        if raw_loc - self.rf.last_raw_loc > 2.0:
            if self.rf.detect_track:
                print("Possibly skipped track, re-checking phase..")
            self.rf.needs_detect

        if self.rf.detect_track and self.rf.needs_detect:
            self.rf.track_phase = self.try_detect_track()
            self.rf.needs_detect = False
        uphet = process_chroma(self, self.rf.track_phase)

        if raw_loc > self.rf.last_raw_loc:
            self.rf.field_number += 1

        self.rf.last_raw_loc = raw_loc

        return chroma_to_u16(uphet)

    def downscale(self, final=False, *args, **kwargs):
        dsout, dsaudio, dsefm = super(FieldPALVHS, self).downscale(
            final, *args, **kwargs
        )
        dschroma = self.processChroma()

        return (dsout, dschroma), dsaudio, dsefm

    def calc_burstmedian(self):
        # Set this to a constant value for now to avoid the comb filter messing with chroma levels.
        return 1.0

    def try_detect_track(self):
        """Try to detect what video track we are on.

        VHS tapes have two tracks with different azimuth that alternate and are read by alternating
        heads on the video drum. The phase of the color heterodyne varies depending on what track is
        being read from to avoid chroma crosstalk.
        Additionally, most tapes are recorded with a luma half-shift which shifts the fm-encoded
        luma frequencies slightly depending on the track to avoid luma crosstalk.
        """
        print("Trying to detect track phase...")
        burst_area = (
            math.floor(self.usectooutpx(self.rf.SysParams["colorBurstUS"][0])),
            math.ceil(self.usectooutpx(self.rf.SysParams["colorBurstUS"][1])),
        )

        # Upconvert chroma twice, once for each possible track phase
        uphet = [process_chroma(self, 0), process_chroma(self, 1)]

        sine_wave = self.rf.fsc_wave
        cosine_wave = self.rf.fsc_cos_wave

        # Try to decode the color burst from each of the upconverted chroma signals
        phase0, phase0_mean = detect_burst_pal(
            uphet[0],
            sine_wave,
            cosine_wave,
            burst_area,
            self.outlinelen,
            self.outlinecount,
        )
        phase1, phase1_mean = detect_burst_pal(
            uphet[1],
            sine_wave,
            cosine_wave,
            burst_area,
            self.outlinelen,
            self.outlinecount,
        )

        # We use the one where the phase of the chroma vectors make the most sense.
        assumed_phase = int(phase0_mean < phase1_mean)

        print("Phase previously set: ", self.rf.track_phase)
        print("phase0 mean: ", phase0_mean)
        print("phase1 mean: ", phase1_mean)
        print("assumed_phase: ", assumed_phase)

        return assumed_phase


class FieldNTSCVHS(ldd.FieldNTSC):
    def __init__(self, *args, **kwargs):
        super(FieldNTSCVHS, self).__init__(*args, **kwargs)
        self.fieldPhaseID = 0

    def refine_linelocs_burst(self, linelocs=None):
        """Override this as it's LD specific
        At some point in the future we could maybe use the burst location to improve hsync accuracy,
        but ignore it for now.
        """
        if linelocs is None:
            linelocs = self.linelocs2
        else:
            linelocs = linelocs.copy()

        # self.Burstlevel is set to the second parameter,
        # but it does not seem to be used for anything, so leave it as 'None'.
        return linelocs, None

    def calc_burstmedian(self):
        # Set this to a constant value for now to avoid the comb filter messing with chroma levels.
        return 1.0

    def processChroma(self):
        uphet = process_chroma(self, self.rf.track_phase)
        return chroma_to_u16(uphet)

    def downscale(self, linesoffset=0, final=False, *args, **kwargs):
        dsout, dsaudio, dsefm = super(FieldNTSCVHS, self).downscale(
            linesoffset, final, *args, **kwargs
        )
        ## TEMPORARY
        dschroma = self.processChroma()
        self.fieldPhaseID = (self.rf.field_number % 4) + 1
        # dschroma = self.refine_linelocs_burst(self.linelocs1)

        return (dsout, dschroma), dsaudio, dsefm


# Superclass to override laserdisc-specific parts of ld-decode with stuff that works for VHS
#
# We do this simply by using inheritance and overriding functions. This results in some redundant
# work that is later overridden, but avoids altering any ld-decode code to ease merging back in
# later as the ld-decode is in flux at the moment.
class VHSDecode(ldd.LDdecode):
    def __init__(
        self,
        fname_in,
        fname_out,
        freader,
        system="NTSC",
        doDOD=False,
        inputfreq=40,
        track_phase=0,
    ):
        super(VHSDecode, self).__init__(
            fname_in,
            fname_out,
            freader,
            analog_audio=False,
            system=system,
            doDOD=doDOD,
            threads=1,
        )
        # Overwrite the rf decoder with the VHS-altered one
        self.rf = VHSRFDecode(
            system=system, inputfreq=inputfreq, track_phase=track_phase
        )
        # Store reference to ourself in the rf decoder - needed to access data location for track
        # phase, may want to do this in a better way later.
        self.rf.decoder = self
        if system == "PAL":
            self.FieldClass = FieldPALVHS
        elif system == "NTSC":
            self.FieldClass = FieldNTSCVHS
        else:
            raise Exception("Unknown video system!", system)
        self.demodcache = ldd.DemodCache(
            self.rf, self.infile, self.freader, num_worker_threads=self.numthreads
        )

        if fname_out is not None:
            self.outfile_chroma = open(fname_out + ".tbcc", "wb")
        else:
            self.outfile_chroma = None

    # Override to avoid NaN in JSON.
    def calcsnr(self, f, snrslice):
        data = f.output_to_ire(f.dspicture[snrslice])

        signal = np.mean(data)
        noise = np.std(data)

        # Make sure signal is positive so we don't try to do log on a negative value.
        if signal < 0.0:
            print("WARNING: Negative mean for SNR, changing to absolute value.")
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
        return super(VHSDecode, self).buildmetadata(f)

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
        self.outfile_chroma.write(picturec)
        self.fields_written += 1

    def close(self):
        setattr(self, "outfile_chroma", None)
        super(VHSDecode, self).close()

    def computeMetricsNTSC(self, metrics, f, fp=None):
        return None


class VHSRFDecode(ldd.RFDecode):
    def __init__(self, inputfreq=40, system="NTSC", track_phase=None):

        # First init the rf decoder normally.
        super(VHSRFDecode, self).__init__(
            inputfreq, system, decode_analog_audio=False, has_analog_audio=False
        )

        if track_phase is None:
            self.track_phase = 0
            self.detect_track = True
            self.needs_detect = True
        elif track_phase == 0 or track_phase == 1:
            self.track_phase = track_phase
            self.detect_track = False
            self.needs_detect = False
        else:
            raise Exception("Track phase can only be 0, 1 or None")
        self.hsync_tolerance = 0.8

        self.field_number = 0
        self.last_raw_loc = 0

        # Then we override the laserdisc parameters with VHS ones.
        if system == "PAL":
            # Give the decoder it's separate own full copy to be on the safe side.
            self.SysParams = copy.deepcopy(vhs_formats.SysParams_PAL_VHS)
            self.DecoderParams = copy.deepcopy(vhs_formats.RFParams_PAL_VHS)
        elif system == "NTSC":
            self.SysParams = copy.deepcopy(vhs_formats.SysParams_NTSC_VHS)
            self.DecoderParams = copy.deepcopy(vhs_formats.RFParams_NTSC_VHS)
        else:
            raise Exception("Unknown video system! ", system)

        # Lastly we re-create the filters with the new parameters.
        self.computevideofilters()

        cc = self.DecoderParams["color_under_carrier"] / 1000000

        DP = self.DecoderParams

        # More advanced rf filter - only used for NTSC for now.
        if system == "NTSC":
            y_fm = sps.butter(
                DP["video_bpf_order"],
                [
                    DP["video_bpf_low"] / self.freq_hz_half,
                    DP["video_bpf_high"] / self.freq_hz_half,
                ],
                btype="bandpass",
            )
            y_fm = lddu.filtfft(y_fm, self.blocklen)

            y_fm_lowpass = lddu.filtfft(
                sps.butter(8, [5.6 / self.freq_half], btype="lowpass"), self.blocklen
            )

            y_fm_chroma_trap = lddu.filtfft(
                sps.butter(
                    1,
                    [(cc * 0.9) / self.freq_half, (cc * 1.1) / self.freq_half],
                    btype="bandstop",
                ),
                self.blocklen,
            )

            y_fm_filter = (
                y_fm * y_fm_lowpass * y_fm_chroma_trap * self.Filters["hilbert"]
            )

            self.Filters["RFVideo"] = y_fm_filter

        # Video (luma) de-emphasis
        # Not sure about the math of this but, by using a high-shelf filter and then
        # swapping b and a we get a low-shelf filter that goes from 0 to -14 dB rather
        # than from 14 to 0 which the high shelf function gives.
        da, db = genHighShelf(0.26, 14, 1 / 2, inputfreq)
        w, h = sps.freqz(db, da)

        self.Filters["Fdeemp"] = lddu.filtfft((db, da), self.blocklen)
        self.Filters["FVideo"] = self.Filters["Fvideo_lpf"] * self.Filters["Fdeemp"]
        SF = self.Filters
        SF["FVideo05"] = SF["Fvideo_lpf"] * SF["Fdeemp"] * SF["F05"]

        # Filter to pick out color-under chroma component.
        # filter at about twice the carrier. (This seems to be similar to what VCRs do)
        chroma_lowpass = sps.butter(
            4, [0.05 / self.freq_half, 1.4 / self.freq_half], btype="bandpass"
        )  # sps.butter(4, [1.2/self.freq_half], btype='lowpass')
        self.Filters["FVideoBurst"] = chroma_lowpass

        # The following filters are for post-TBC:

        # The output sample rate is at approx 4fsc
        fsc_mhz = self.SysParams["fsc_mhz"]
        out_sample_rate_mhz = fsc_mhz * 4
        out_frequency_half = out_sample_rate_mhz / 2
        het_freq = fsc_mhz + cc
        outlinelen = self.SysParams["outlinelen"]
        fieldlen = self.SysParams["outlinelen"] * max(self.SysParams["field_lines"])

        # Final band-pass filter for chroma output.
        # Mostly to filter out the higher-frequency wave that results from signal mixing.
        # Needs tweaking.
        chroma_bandpass_final = sps.butter(
            2,
            [
                (fsc_mhz - 0.64) / out_frequency_half,
                (fsc_mhz + 0.24) / out_frequency_half,
            ],
            btype="bandpass",
        )
        self.Filters["FChromaFinal"] = chroma_bandpass_final

        chroma_burst_check = sps.butter(
            2,
            [
                (fsc_mhz - 0.14) / out_frequency_half,
                (fsc_mhz + 0.04) / out_frequency_half,
            ],
            btype="bandpass",
        )
        self.Filters["FChromaBurstCheck"] = chroma_burst_check

        ## Bandpass filter to select heterodyne frequency from the mixed fsc and color carrier signal
        het_filter = sps.butter(
            2,
            [
                (het_freq - 0.001) / out_frequency_half,
                (het_freq + 0.001) / out_frequency_half,
            ],
            btype="bandpass",
        )
        samples = np.arange(fieldlen)

        # As this is done on the tbced signal, we need the sampling frequency of that,
        # which is 4fsc for NTSC and approx. 4 fsc for PAL.
        # TODO: Correct frequency for pal?
        wave_scale = fsc_mhz / out_sample_rate_mhz

        cc_wave_scale = cc / out_sample_rate_mhz
        self.cc_ratio = cc_wave_scale
        # 0 phase downconverted color under carrier wave
        self.cc_wave = np.sin(2 * np.pi * cc_wave_scale * samples)
        # +90 deg and so on phase wave for track2 phase rotation
        cc_wave_90 = np.sin((2 * np.pi * cc_wave_scale * samples) + (np.pi / 2))  #
        cc_wave_180 = np.sin((2 * np.pi * cc_wave_scale * samples) + np.pi)
        cc_wave_270 = np.sin(
            (2 * np.pi * cc_wave_scale * samples) + np.pi + (np.pi / 2)
        )

        # Standard frequency color carrier wave.
        self.fsc_wave = utils.gen_wave_at_frequency(
            fsc_mhz, out_sample_rate_mhz, fieldlen
        )
        self.fsc_cos_wave = utils.gen_wave_at_frequency(
            fsc_mhz, out_sample_rate_mhz, fieldlen, np.cos
        )

        # Heterodyne wave
        # We combine the color carrier with a wave with a frequency of the
        # subcarrier + the downconverted chroma carrier to get the original
        # color wave back.
        self.chroma_heterodyne = {}

        self.chroma_heterodyne[0] = sps.filtfilt(
            het_filter[0], het_filter[1], self.cc_wave * self.fsc_wave
        )
        self.chroma_heterodyne[1] = sps.filtfilt(
            het_filter[0], het_filter[1], cc_wave_90 * self.fsc_wave
        )
        self.chroma_heterodyne[2] = sps.filtfilt(
            het_filter[0], het_filter[1], cc_wave_180 * self.fsc_wave
        )
        self.chroma_heterodyne[3] = sps.filtfilt(
            het_filter[0], het_filter[1], cc_wave_270 * self.fsc_wave
        )

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
        rv = {}

        if fftdata is not None:
            indata_fft = fftdata
        elif data is not None:
            indata_fft = np.fft.fft(data[: self.blocklen])
        else:
            raise Exception("demodblock called without raw or FFT data")

        if data is None:
            data = np.fft.ifft(indata_fft).real

        indata_fft_filt = indata_fft * self.Filters["RFVideo"]

        hilbert = np.fft.ifft(indata_fft_filt)
        demod = unwrap_hilbert(hilbert, self.freq_hz)

        demod_fft = np.fft.fft(demod)

        out_video = np.fft.ifft(demod_fft * self.Filters["FVideo"]).real

        out_video05 = np.fft.ifft(demod_fft * self.Filters["FVideo05"]).real
        out_video05 = np.roll(out_video05, -self.Filters["F05_offset"])

        # Filter out the color-under signal from the raw data.
        out_chroma = filter_simple(data[: self.blocklen], self.Filters["FVideoBurst"])

        # Move chroma to compensate for Y filter delay.
        # value needs tweaking, ideally it should be calculated if possible.
        out_chroma = np.roll(out_chroma, 140)
        # crude DC offset removal
        out_chroma = out_chroma - np.mean(out_chroma)

        # demod_burst is a bit misleading, but keeping the naming for compatability.
        video_out = np.rec.array(
            [out_video, demod, out_video05, out_chroma],
            names=["demod", "demod_raw", "demod_05", "demod_burst"],
        )

        rv["video"] = (
            video_out[self.blockcut : -self.blockcut_end] if cut else video_out
        )

        return rv
