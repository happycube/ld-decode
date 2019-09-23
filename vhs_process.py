import math
import numpy as np
import itertools
import scipy as sp
import scipy.signal as sps
import scipy.fftpack as fftpack
import copy


import matplotlib.pyplot as plt

import lddecode_core as ldd
import lddutils as lddu
from lddutils import unwrap_hilbert, inrange

import vhs_formats

def toDB(val):
    return 20 * np.log10(val)

def fromDB(val):
    return 10.0 ** (val / 20.0)

def scale_chroma(chroma):
    '''Scale the array to fit into signed 16-bit values.
    '''
    S16_ABS_MAX = 32767

    if chroma is None:
        print("Tried to scale an empty array!")
    #
    positive = np.max(chroma) * 1.5
    negative = np.min(chroma) * 1.5
    scale = S16_ABS_MAX / max(positive, abs(negative))
    return np.uint16((chroma * scale) + S16_ABS_MAX + 1)

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

    def _refine_linelocs_hsync(self):
        """Refine the hsync locations.
        The LD implementation doesn't seem to work well with VHS, so we just skip this for now as
        the original locations gives a reasonable result.
        """
        linelocs2 = self.linelocs1.copy()
        return linelocs2

    def processChroma(self):
        chroma, _, _ = ldd.Field.downscale(self, channel="demod_burst")

        ## Chroma upheterodyne
        uphet = np.zeros(chroma.size, dtype=np.double)

        lineoffset = self.lineoffset + 1
        linesout = self.outlinecount
        outwidth = self.outlinelen

#        burstlevel = np.zeros(linesout)
#        burstphase = np.zeros(linesout)

        burstarea = (math.floor(self.usectooutpx(self.rf.SysParams['colorBurstUS'][0])),
                     math.ceil(self.usectooutpx(self.rf.SysParams['colorBurstUS'][1])))

        if self.rf.fieldNumber % 2 == 0:
            for l in range(lineoffset, linesout + lineoffset):
                linenum = l - lineoffset
                linestart = (l - lineoffset) * outwidth
                lineend = linestart + outwidth
                phase = 0

                line = chroma[linestart:lineend] * self.rf.chroma_heterodyne[0]



                pos_peaks = sps.find_peaks(line[burstarea[0]:burstarea[1]])[0]
                neg_peaks = sps.find_peaks(-line[burstarea[0]:burstarea[1]])[0]

                print("l: ", linenum, " pos peaks: ", pos_peaks, " neg peaks: ", neg_peaks)

                #if linenum > 1:
                #    line *= uphet[linestart - (outwidth * 2):lineend - (outwidth*2)]

                linefilt = np.fft.ifft(np.fft.fft(line) * (self.rf.Filters['FChromaFinal'])).real


                uphet[linestart:lineend] = linefilt

        #            burstphase[l - lineoffset] = lddu.angular_mean(chroma[linestart + burstarea[0]:linestart + burstarea[1]])
        else:
            phase = 0
            for l in range(lineoffset, linesout + lineoffset):
                linenum = l - lineoffset
                linestart = (l - lineoffset) * outwidth
                lineend = linestart + outwidth

                line = chroma[linestart:lineend] * self.rf.chroma_heterodyne[phase]
                linefilt = np.fft.ifft(np.fft.fft(line) * self.rf.Filters['FChromaFinal']).real

                #pos_peaks = sps.find_peaks(line[burstarea[0]:burstarea[1]])[0]
                #neg_peaks = sps.find_peaks(-line[burstarea[0]:burstarea[1]])[0]

#                if l > lineoffset:
#                    linefilt = -(-linefilt + uphet[linestart - outwidth:linestart])

#                if l > lineoffset + 1:
#                    linefilt = -(linefilt + uphet[linestart - (outwidth*2):linestart - outwidth])


                uphet[linestart:lineend] = linefilt

                phase -= 1
                if phase < 0:
                    phase = 3


#            burstphase[l - lineoffset] = lddu.angular_mean(chroma[linestart + burstarea[0]:linestart + burstarea[1]])
            if False:
                samplefreq = self.rf.SysParams['fsc_mhz'] * 4
                rate = np.full(outwidth , vhs_formats.VHS_COLOR_CARRIER_MHZ, dtype=np.double)
                rate[outwidth // 3:(outwidth // 3) * 2] = self.rf.SysParams['fsc_mhz']
                #test_wave = lddu.genwave(rate, samplefreq / 2)

                samples = np.arange(self.rf.SysParams['outlinelen'])
                wave_scale =  vhs_formats.VHS_COLOR_CARRIER_MHZ / (self.rf.SysParams['fsc_mhz'] * 4)
                cc_wave = np.sin(2 * np.pi * wave_scale * samples)

#                start = (80 - lineoffset) * outwidth

                #chroma_fft =  np.fft.fft(test_wave)#chroma[linestart:lineend])
                #            chroma_uphet_fft = np.fft.fft(uphet * 1000000)
                #            hetero_fft = np.fft.fft(self.rf.cc_raw)
                #cc_fft = np.fft.fft(cc_wave)
                self.fig, self.ax1 = plt.subplots()
#                self.ax2 = self.ax1.twinx()
                #            self.ax2 = self.ax1.twinx()
                #self.ax1.plot(range(0, len(chroma_fft)), chroma_fft.real)
                #self.ax1.plot(range(0, len(test_wave)), test_wave, color='#FF0000')
                #            self.ax1.plot(range(0, len(chroma_uphet_fft)), chroma_uphet_fft.real, color='#FF0000')
                #self.ax2.plot(range(0, len(cc_fft)), cc_fft.real, color='#FF0000')
                #self.ax1.plot(range(0, len(cc_wave)), cc_wave, color='#FFFF00')
                self.ax1.plot(range(0, len(self.rf.chroma_heterodyne[0])), self.rf.chroma_heterodyne[0], color='#FFFF00')
                self.ax1.plot(range(0, len(self.rf.chroma_heterodyne[0])), self.rf.chroma_heterodyne[1], color='#FF0000')
                self.ax1.plot(range(0, len(self.rf.chroma_heterodyne[0])), self.rf.chroma_heterodyne[2], color='#00FF00')
                self.ax1.plot(range(0, len(self.rf.chroma_heterodyne[0])), self.rf.chroma_heterodyne[3], color='#0000FF')

                plt.show()

        dschroma = scale_chroma(uphet)

        self.rf.fieldNumber += 1

        return dschroma

    def downscale(self, final = False, *args, **kwargs):
        dsout, dsaudio, dsefm = super(FieldPALVHS, self).downscale(final, *args, **kwargs)
        dschroma = self.processChroma()

        return (dsout, dschroma), dsaudio, dsefm

# Superclass to override laserdisc-specific parts of ld-decode with stuff that works for VHS
#
# We do this simply by using inheritance and overriding functions. This results in some redundant
# work that is later overridden, but avoids altering any ld-decode code to ease merging back in
# later as the ld-decode is in flux at the moment.
class VHSDecode(ldd.LDdecode):
    def __init__(self, fname_in, fname_out, freader, system = 'NTSC', doDOD = False,
                 inputfreq = 40):
        super(VHSDecode, self).__init__(fname_in, fname_out, freader, analog_audio = False,
                                        system = system, doDOD = doDOD)
        # Overwrite the rf decoder with the VHS-altered one
        self.rf = VHSRFDecode(system = system, inputfreq = inputfreq)
        self.FieldClass = FieldPALVHS
        self.demodcache = ldd.DemodCache(self.rf, self.infile, self.freader,
                                     num_worker_threads=self.numthreads)

        if fname_out is not None:
            self.outfile_chroma = open(fname_out + '.tbcc', 'wb')
        else:
            self.outfile_chroma = None

        plt.rcParams['figure.figsize'] = 15, 8

    # Override to avoid NaN in JSON.
    def calcsnr(self, f, snrslice):
        data = f.output_to_ire(f.dspicture[snrslice])

        signal = np.mean(data)
        noise = np.std(data)

        # Make sure signal is positive so we don't try to do log on a negative value.
        if signal < 0.0:
                print("WARNING: Negative mean for SNR, changing to absolute value.")
                signal = abs(signal)

        return 20 * np.log10(signal / noise)

    def calcpsnr(self, f, snrslice):
        data = f.output_to_ire(f.dspicture[snrslice])

#        signal = np.mean(data)
        noise = np.std(data)

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
                                              have_analog_audio = False)

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
        # filter at about twice the carrier.
        chroma_lowpass = sps.butter(2, [1.4/self.freq_half], btype='lowpass')
        self.Filters['FVideoBurst'] = lddu.filtfft(chroma_lowpass, self.blocklen)

        out_frequency_half = (self.SysParams['fsc_mhz'] * 4) / 2

        # Final band-pass filter for chroma output.
        chroma_bandpass_final = sps.butter(3, [(self.SysParams['fsc_mhz']-.08)/out_frequency_half,
                                               (self.SysParams['fsc_mhz']+.06)/out_frequency_half], btype='bandpass')
        self.Filters['FChromaFinal'] = lddu.filtfft(chroma_bandpass_final, self.SysParams['outlinelen'])

        het_freq = self.SysParams['fsc_mhz'] + cc

        het_filter = sps.butter(4, [(het_freq -.001)/out_frequency_half,
                                               (het_freq +.001)/out_frequency_half], btype='bandpass')
        het_filter = lddu.filtfft(het_filter, self.SysParams['outlinelen'])

        # Heterodyne wave
        # We combine the color carrier with a wave with a frequency of the
        # subcarrier + the downconverted chroma carrier to get the original
        # color wave back.
        samples = np.arange(self.SysParams['outlinelen'])
        # As this is done on the tbced signal, we need the sampling frequency of that,
        # which is 4fsc for NTSC and approx. 4 fsc for PAL.
        # TODO: Correct frequency for pal?
        wave_scale =  1/4.0##(self.SysParams['fsc_mhz']) / (self.SysParams['fsc_mhz'] * 4)

        cc_wave_scale = cc / (self.SysParams['fsc_mhz'] * 4)
        cc_wave = np.sin(2 * np.pi * cc_wave_scale * samples)
        cc_wave_90 = np.sin((2 * np.pi * cc_wave_scale * samples) + (np.pi / 2))
        cc_wave_180 = np.sin((2 * np.pi * cc_wave_scale * samples) + np.pi)
        cc_wave_270 = np.sin((2 * np.pi * cc_wave_scale * samples) + np.pi + (np.pi / 2))
        fsc_wave = np.sin(2 * np.pi * wave_scale * samples)
        fsc_wave_90 = np.sin((2 * np.pi * wave_scale * samples) + (np.pi / 2))
        fsc_wave_180 = np.sin((2 * np.pi * wave_scale * samples) + np.pi)
        fsc_wave_270 = np.sin((2 * np.pi * wave_scale * samples) - (np.pi / 2))
##        cc_wave_90 =

        #wave_scale_t =  (self.SysParams['fsc_mhz'] + cc) / (self.SysParams['fsc_mhz'] * 4)

        #fsc_and_cc_mixed = cc_wave * fsc_wave
        #fsc_and_cc_freq = np.sin(2 * np.pi * wave_scale_t * samples)

        self.chroma_heterodyne = {}
#        self.chroma_heterodyne[0] = np.sin((2 * np.pi * ((cc + self.SysParams['fsc_mhz']) /  (self.SysParams['fsc_mhz'] * 4))) * samples)
        self.chroma_heterodyne[0] = np.fft.ifft(np.fft.fft(cc_wave * fsc_wave) * het_filter) #np.sin(2 * np.pi * wave_scale_t * samples)
        self.chroma_heterodyne[1] = np.fft.ifft(np.fft.fft(cc_wave_90 * fsc_wave_90) * het_filter)
        self.chroma_heterodyne[2] = np.fft.ifft(np.fft.fft(cc_wave_180 * fsc_wave_180) * het_filter)
        self.chroma_heterodyne[3] = np.fft.ifft(np.fft.fft(cc_wave_270 * fsc_wave_270) * het_filter)

        self.fig, self.ax1 = plt.subplots()


        #fsc_bandpass = sps.butter(5, [(het_freq-.10)/self.freq_half,
 #                                        (het_freq+.10)/self.freq_half], btype='bandpass')
        #fsc_bandpass = lddu.filtfft(fsc_bandpass, self.SysParams['outlinelen'])

        #test_wave = np.fft.ifft(np.fft.fft(cc_wave * fsc_wave) * fsc_bandpass)

        #self.ax1.plot(range(0, len(cc_wave)), cc_wave * fsc_wave, color='#FFFF00')
        #self.ax1.plot(range(0, len(cc_wave)), cc_wave_90 * fsc_wave , color='#FF0000')
#        self.ax1.plot(range(0, len(cc_wave)), cc_wave_180 * fsc_wave, color='#00FF00')
#        self.ax1.plot(range(0, len(cc_wave)), cc_wave_270 * fsc_wave, color='#0000FF')

#        plt.show()

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

        indata_fft_filt = indata_fft * self.Filters['RFVideo']

        hilbert = np.fft.ifft(indata_fft_filt)
        demod = unwrap_hilbert(hilbert, self.freq_hz)

        demod_fft = np.fft.fft(demod)

        out_video = np.fft.ifft(demod_fft * self.Filters['FVideo']).real

        out_video05 = np.fft.ifft(demod_fft * self.Filters['FVideo05']).real
        out_video05 = np.roll(out_video05, -self.Filters['F05_offset'])

        out_chroma = np.fft.ifft(indata_fft * self.Filters['FVideoBurst']).real * 100

        # demod_burst is a bit misleading, but keeping the naming for compatability.
        video_out = np.rec.array(
                [out_video, demod, out_video05, out_chroma],
                names=['demod', 'demod_raw', 'demod_05', 'demod_burst'])

        rv['video'] = video_out[self.blockcut:-self.blockcut_end] if cut else video_out

        if False:
            self.fig, self.ax1 = plt.subplots()
            self.ax2 = self.ax1.twinx()
            fig, ax1 = self.fig, self.ax1
            #fig.clf()
            #fig.cla()
            ax1.cla()

            ax1.axhline(self.iretohz(100))
            ax1.axhline(self.iretohz(0))
            ax1.axhline(self.iretohz(-25))

            color = 'tab:red'
            #ax1.axhline(self.iretohz(self.SysParams['vsync_ire']), color=color)
            #ax1.axhline(self.iretohz(0), color='0.0')
            #ax1.axhline(min_level, color='#00FF00')
            #ax1.axhline(sync_filter_high, color='#0000FF')

#            ax1.plot(range(0, len(self.chroma_heterodyne)), self.chroma_heterodyne)
#            ax1.plot(range(0, len(uphet)), uphet)

            #ax1.plot(range(0, len(out_video)), out_video)
            ax1.plot(range(0, len(out_video05)), out_video05)

            #ax2 = self.ax2#ax1.twinx()
            #ax2.cla()

            #ax2.plot(range(0, len(out_chroma)), out_chroma, color='#FF0000')
            #ax2.plot(range(0, len(video_variation)), video_variation, color='#FFFF00')


#            ax2.plot(range(0, len(output_syncf)), output_syncf, color='tab:green')
#            ax2.plot(range(0, len(output_sync)), output_sync, color='tab:gray')


            #fig.tight_layout()

            #	plt.plot(range(0, len(doutput)), doutput)
            #	plt.plot(range(0, len(output_prefilt)), output_prefilt)
            #plt.show()
            #        plt.draw()

            #fig.canvas.draw()
            #fig.canvas.flush_events()
            plt.show()
            #plt.pause(0.1)

        return rv
