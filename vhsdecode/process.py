import math
import numpy as np
import itertools
import scipy as sp
import scipy.signal as sps
import scipy.fftpack as fftpack
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
    chromaavg = 0
    for l in range(16,lines):
        linestart = linelength * l
        lineend = linestart + linelength
        line = chroma[linestart:lineend]
        output[linestart:lineend] = acc_line(line, burst_abs_ref, burststart, burstend)

    return output


def acc_line(chroma, burst_abs_ref, burststart, burstend):
    """Scale chroma according to the level of the color burst the line."""
    output = np.zeros(chroma.size, dtype=np.double)

    line = chroma
    burst_abs_mean = np.mean(np.abs(line[burststart:burstend]))
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
    w0 = 2 * math.pi * (f0/fs)
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
    w0 = 2 * math.pi * (f0/fs)
    alpha = math.sin(w0) / (2 * qfactor)

    cosw0 = math.cos(w0)
    asquared = math.sqrt(a)

    b0 = a * ((a + 1) + (a - 1) * cosw0 + 2 * asquared * alpha)
    b1 = -2 * a * ((a - 1) + (a + 1) * cosw0)
    b2 = a * ((a + 1) + (a - 1) * cosw0 - 2 * asquared * alpha)
    a0 = (a + 1) - (a - 1) * cosw0 + 2 * asquared * alpha
    a1 = 2 * ((a - 1) -(a + 1) * cosw0)
    a2 = (a + 1) - (a - 1) * cosw0 - 2 * asquared * alpha
    return [b0, b1, b2], [a0, a1, a2]

def filter_simple(data, filter_coeffs):
    fb,fa = filter_coeffs
    return sps.filtfilt(fb,fa,data,padlen=150)

def comb_c_pal(data, linelen):
    """Very basic comb filter, adds the signal together with a signal delayed by 2H,
    line by line. VCRs do this to reduce crosstalk.
    """
    numlines = len(data) // linelen
    for l in range(16,numlines - 2):
        delayed2h = data[(l - 2) * linelen:(l - 1) * linelen]
        data[l * linelen:(l + 1) * linelen] -= delayed2h

    return data


# Phase comprensation stuff - needs rework.
# def phase_shift(data, angle):
#     return np.fft.irfft(np.fft.rfft(data) * np.exp(1.0j * angle), len(data)).real

# def detect_phase(data):
#     data = data / np.mean(abs(data))
#     return lddu.calczc(data, 1, 0, edge=1)

class FieldPALVHS(ldd.FieldPAL):
    def __init__(self, *args, **kwargs):
        super(FieldPALVHS, self).__init__(*args, **kwargs)


    def refine_linelocs_pilot(self, linelocs = None):
        """Override this as it's LD specific"""
        if linelocs is None:
            linelocs = self.linelocs2.copy()
        else:
            linelocs = linelocs.copy()

        return linelocs

    def processChroma(self):
        # Run TBC/downscale on chroma.
        chroma, _, _ = ldd.Field.downscale(self, channel="demod_burst")

        # Chroma upheterodyne
        uphet = np.zeros(chroma.size, dtype=np.double)

        lineoffset = self.lineoffset + 1
        linesout = self.outlinecount
        outwidth = self.outlinelen

        burstarea = (math.floor(self.usectooutpx(self.rf.SysParams['colorBurstUS'][0])),
                     math.ceil(self.usectooutpx(self.rf.SysParams['colorBurstUS'][1])))

        chroma = acc(chroma, 150.0, burstarea[0], burstarea[1], outwidth, linesout)

        # Naively assume field number/track relationship
        # TODO: Detect automatically.
        if self.rf.fieldNumber % 2 == 0:
            # Track 1 - for PAL, phase doesn't change.
            start = lineoffset
            end = lineoffset + (outwidth * linesout)
            heterodyne = self.rf.chroma_heterodyne[0][start:end]
            c = chroma[start:end]
            # Mixing the chroma signal with a signal at the frequency of colour under + fsc gives us
            # a signal with frequencies at the difference and sum, the difference is what we want as
            # it's at the right frequency.
            mixed = heterodyne * c

            uphet[start:end] = mixed

        else:
            # Track 2 - needs phase rotation or the chroma will be inverted.
            phase = 0
            for l in range(lineoffset, linesout + lineoffset):
                linenum = l - lineoffset
                linestart = (l - lineoffset) * outwidth
                lineend = linestart + outwidth

                heterodyne = self.rf.chroma_heterodyne[phase][linestart:lineend]

                c = chroma[linestart:lineend]

                line = heterodyne * c

                uphet[linestart:lineend] = line

                phase -= 1
                if phase < 0:
                    phase = 3

        # Filter out unwanted frequencies from the final chroma signal.
        # Mixing the signals will produce waves at the difference and sum of the
        # frequencies. We only want the difference wave which is at the correct color
        # carrier frequency here.
        # We do however want to be careful to avoid filtering out too much of the sideband.
        uphet = filter_simple(uphet,self.rf.Filters['FChromaFinal'])

        # Basic comb filter to reduce crosstalk and fluctuation.
        uphet[lineoffset:] = comb_c_pal(uphet[lineoffset:],outwidth)

        # Final automatic chroma gain.
        uphet = acc(uphet, vhs_formats.PAL_BURST_REF_MEAN_ABS,
                    burstarea[0], burstarea[1], outwidth, linesout)


        self.rf.fieldNumber += 1

        return chroma_to_u16(uphet)

    def downscale(self, final = False, *args, **kwargs):
        dsout, dsaudio, dsefm = super(FieldPALVHS, self).downscale(final, *args, **kwargs)
        dschroma = self.processChroma()

        return (dsout, dschroma), dsaudio, dsefm

    def calc_burstmedian(self):
        # Set this to a constant value for now to avoid the comb filter messing with chroma levels.
        return 1.0

# Superclass to override laserdisc-specific parts of ld-decode with stuff that works for VHS
#
# We do this simply by using inheritance and overriding functions. This results in some redundant
# work that is later overridden, but avoids altering any ld-decode code to ease merging back in
# later as the ld-decode is in flux at the moment.
class VHSDecode(ldd.LDdecode):
    def __init__(self, fname_in, fname_out, freader, system = 'NTSC', doDOD = False,
                 inputfreq = 40):
        super(VHSDecode, self).__init__(fname_in, fname_out, freader, analog_audio = False,
                                        system = system, doDOD = doDOD, threads = 1)
        # Overwrite the rf decoder with the VHS-altered one
        self.rf = VHSRFDecode(system = system, inputfreq = inputfreq)
        self.FieldClass = FieldPALVHS
        self.demodcache = ldd.DemodCache(self.rf, self.infile, self.freader,
                                     num_worker_threads=self.numthreads)

        if fname_out is not None:
            self.outfile_chroma = open(fname_out + '.tbcc', 'wb')
        else:
            self.outfile_chroma = None

        #plt.rcParams['figure.figsize'] = 15, 8

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

    def writeout(self, dataset):
        f, fi, (picturey, picturec), audio, efm = dataset

        fi['audioSamples'] = 0
        self.fieldinfo.append(fi)

        self.outfile_video.write(picturey)
        self.outfile_chroma.write(picturec)
        self.fields_written += 1

    def close(self):
        setattr(self, self.outfile_chroma, None)
        super(VHSDecode, self).close()

class VHSRFDecode(ldd.RFDecode):
    def __init__(self, inputfreq = 40, system = 'NTSC'):

        # First init the rf decoder normally.
        super(VHSRFDecode, self).__init__(inputfreq, system, decode_analog_audio = False,
                                              has_analog_audio = False)

        # Then we override the laserdisc parameters with VHS ones.
        if system == 'PAL':
                # Give the decoder it's separate own full copy to be on the safe side.
            self.SysParams = copy.deepcopy(vhs_formats.SysParams_PAL_VHS)
            self.DecoderParams = copy.deepcopy(vhs_formats.RFParams_PAL_VHS)
        else:
            print("Non-PAL Not implemented yet!")
            exit(1)

        # Lastly we re-create the filters with the new parameters.
        self.computevideofilters()

        cc = vhs_formats.VHS_COLOR_CARRIER_MHZ

        # More advanced rf filter - disabled for commit
        # DP = self.DecoderParams
        # y_fm = sps.butter(DP['video_bpf_order'], [DP['video_bpf_low']/self.freq_hz_half,
        #                                    DP['video_bpf_high']/self.freq_hz_half], btype='bandpass')
        # y_fm = lddu.filtfft(y_fm, self.blocklen)

        # y_fm_lowpass = lddu.filtfft(sps.butter(1, [5.7/self.freq_half], btype='lowpass'),
        #                             self.blocklen)

        # y_fm_chroma_trap = lddu.filtfft(sps.butter(1,
        #                                         [(cc * 0.9)/self.freq_half, (cc * 1.1)/self.freq_half],
        #                                         btype='bandstop'),
        #                             self.blocklen)

        # y_fm_filter = y_fm * y_fm_lowpass * y_fm_chroma_trap * self.Filters['hilbert']

        # self.Filters['RFVideo'] = y_fm_filter

        # Video (luma) de-emphasis
        # Not sure about the math of this but, by using a high-shelf filter and then
        # swapping b and a we get a low-shelf filter that goes from 0 to -14 dB rather
        # than from 14 to 0 which the high shelf function gives.
        da, db = genHighShelf(0.26, 14, 1/2, inputfreq)
        w, h = sps.freqz(db, da)

        self.Filters['Fdeemp'] = lddu.filtfft((db, da), self.blocklen)
        self.Filters['FVideo'] = self.Filters['Fvideo_lpf'] * self.Filters['Fdeemp']
        SF = self.Filters
        SF['FVideo05'] = SF['Fvideo_lpf'] * SF['Fdeemp'] * SF['F05']

        # Filter to pick out color-under chroma component.
        # filter at about twice the carrier. (This seems to be similar to what VCRs do)
        chroma_lowpass = sps.butter(4, [1.2/self.freq_half], btype='lowpass')
        self.Filters['FVideoBurst'] = chroma_lowpass

        # The following filters are for post-TBC:

        # The output sample rate is at approx 4fsc
        fsc_mhz = self.SysParams['fsc_mhz']
        out_sample_rate_mhz = fsc_mhz * 4
        out_frequency_half = out_sample_rate_mhz / 2
        het_freq = fsc_mhz + cc
        outlinelen = self.SysParams['outlinelen']
        fieldlen = self.SysParams['outlinelen'] * max(self.SysParams['field_lines'])

        # Final band-pass filter for chroma output.
        # Mostly to filter out the higher-frequency wave that results from signal mixing.
        # Needs tweaking.
        chroma_bandpass_final = sps.butter(2, [(fsc_mhz - .64)/out_frequency_half,
                                               (fsc_mhz + .24)/out_frequency_half], btype='bandpass')
        self.Filters['FChromaFinal'] = chroma_bandpass_final

        ## Bandpass filter to select heterodyne frequency from the mixed fsc and color carrier signal
        het_filter = sps.butter(2, [(het_freq -.001)/out_frequency_half,
                                               (het_freq +.001)/out_frequency_half], btype='bandpass')
        samples = np.arange(fieldlen)

        # As this is done on the tbced signal, we need the sampling frequency of that,
        # which is 4fsc for NTSC and approx. 4 fsc for PAL.
        # TODO: Correct frequency for pal?
        wave_scale =  fsc_mhz / out_sample_rate_mhz

        cc_wave_scale = cc / out_sample_rate_mhz
        self.cc_ratio = cc_wave_scale
        # 0 phase downconverted color under carrier wave
        self.cc_wave = np.sin(2 * np.pi * cc_wave_scale * samples)
        # +90 deg and so on phase wave for track2 phase rotation
        cc_wave_90 = np.sin((2 * np.pi * cc_wave_scale * samples) + (np.pi / 2))#
        cc_wave_180 = np.sin((2 * np.pi * cc_wave_scale * samples) + np.pi)
        cc_wave_270 = np.sin((2 * np.pi * cc_wave_scale * samples) + np.pi + (np.pi / 2))

        # Standard frequency color carrier wave.
        self.fsc_wave = utils.gen_wave_at_frequency(fsc_mhz, out_sample_rate_mhz, fieldlen)

        # Heterodyne wave
        # We combine the color carrier with a wave with a frequency of the
        # subcarrier + the downconverted chroma carrier to get the original
        # color wave back.
        self.chroma_heterodyne = {}

        self.chroma_heterodyne[0] = sps.filtfilt(het_filter[0], het_filter[1],self.cc_wave * self.fsc_wave)
        self.chroma_heterodyne[1] = sps.filtfilt(het_filter[0], het_filter[1],cc_wave_90 * self.fsc_wave)
        self.chroma_heterodyne[2] = sps.filtfilt(het_filter[0], het_filter[1],cc_wave_180 * self.fsc_wave)
        self.chroma_heterodyne[3] = sps.filtfilt(het_filter[0], het_filter[1],cc_wave_270 * self.fsc_wave)

        self.fieldNumber = 0

    def computedelays(self, mtf_level = 0):
        '''Override computedelays
        It's normally used for dropout compensation, but the dropout compensation implementation
        in ld-decode assumes composite color. This function is called even if it's disabled, and
        seems to break with the VHS setup, so we disable it by overriding it for now.
        '''
        # Set these to 0 for now, the metrics calculations look for them.
        self.delays = {}
        self.delays['video_sync'] = 0
        self.delays['video_white'] = 0

    def demodblock(self, data = None, mtf_level = 0, fftdata = None, cut = False):
        rv = {}

        if fftdata is not None:
            indata_fft = fftdata
        elif data is not None:
            indata_fft = np.fft.fft(data[:self.blocklen])
        else:
            raise Exception("demodblock called without raw or FFT data")

        if data is None:
            data = np.fft.ifft(indata_fft).real

        indata_fft_filt = indata_fft * self.Filters['RFVideo']

        hilbert = np.fft.ifft(indata_fft_filt)
        demod = unwrap_hilbert(hilbert, self.freq_hz)

        demod_fft = np.fft.fft(demod)

        out_video = np.fft.ifft(demod_fft * self.Filters['FVideo']).real

        out_video05 = np.fft.ifft(demod_fft * self.Filters['FVideo05']).real
        out_video05 = np.roll(out_video05, -self.Filters['F05_offset'])

        # Filter out the color-under signal from the raw data.
        out_chroma = filter_simple(data[:self.blocklen],self.Filters['FVideoBurst'])

        # Move chroma to compensate for Y filter delay.
        # value needs tweaking, ideally it should be calculated if possible.
        out_chroma = np.roll(out_chroma, 140)
        # crude DC offset removal
        out_chroma = out_chroma - np.mean(out_chroma)


        # demod_burst is a bit misleading, but keeping the naming for compatability.
        video_out = np.rec.array(
                [out_video, demod, out_video05, out_chroma],
                names=['demod', 'demod_raw', 'demod_05', 'demod_burst'])

        rv['video'] = video_out[self.blockcut:-self.blockcut_end] if cut else video_out

        return rv
