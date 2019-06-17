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

class FieldPALVHS(ldd.FieldPAL):
    def __init__(self, *args, **kwargs):
        super(FieldPALVHS, self).__init__(*args, **kwargs)


    def refine_linelocs_pilot(self, linelocs = None):
        if linelocs is None:
            linelocs = self.linelocs2.copy()
        else:
            linelocs = linelocs.copy()

        return linelocs

    def refine_linelocs_hsync(self):
        """Refine the hsync locations.
        The LD implementation doesn't seem to work well with VHS, so we just skip this for now as
        the original locations gives a reasonable result.
        """
        linelocs2 = self.linelocs1.copy()
        return linelocs2

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

#        video_lpf = sps.butter(4,((vhs_formats.VHS_COLOR_CARRIER_MHZ + 0.05)/self.freq_half), 'low')
        video_lpf = sps.butter(4, [(cc-.15)/self.freq_half, (cc+.15)/self.freq_half], btype='bandpass')
        self.Filters['FVideoBurst'] = lddu.filtfft(video_lpf, self.blocklen)

        #plt.ion()
        #plt.show()
        #self.fig, self.ax1 = plt.subplots()
        #self.ax2 = self.ax1.twinx()


        # Override computedelays
        # It's normally used for dropout compensation, but the dropout compensation implementation
        # in ld-decode assumes composite color. This function is called even if it's disabled, and
        # seems to break with the VHS setup, so we disable it by overriding it for now.
    def computedelays(self, mtf_level = 0):
        # Set these to 0 for now, the metrics calculations look for them.
        self.delays = {}
        self.delays['video_sync'] = 0
        self.delays['video_white'] = 0

    def demodblock(self, data, mtf_level = 0):
        rv_efm = None

        #mtf_level *= self.mtf_mult
        #if self.system == 'NTSC':
        #    mtf_level *= .7
        #mtf_level += self.mtf_offset

        indata_fft = np.fft.fft(data[:self.blocklen])
        indata_fft_filt = indata_fft * self.Filters['RFVideo']

        #if mtf_level != 0:
        #    indata_fft_filt *= self.Filters['MTF'] ** mtf_level

        hilbert = np.fft.ifft(indata_fft_filt)
        demod = unwrap_hilbert(hilbert, self.freq_hz)

        demod_fft = np.fft.fft(demod)

        out_video = np.fft.ifft(demod_fft * self.Filters['FVideo']).real

        out_video05 = np.fft.ifft(demod_fft * self.Filters['FVideo05']).real
        out_video05 = np.roll(out_video05, -self.Filters['F05_offset'])

        min_level = np.nanmin(out_video05)
        min_ire = self.hztoire(min_level)
        sync_filter_high = self.iretohz(min_ire + 35)

        out_videoburst = np.fft.ifft(indata_fft * self.Filters['FVideoBurst']).real

        # NTSC: filtering for vsync pulses from -55 to -25ire seems to work well even on rotted disks
        # Need to change to
        output_sync = inrange(out_video05, min_ire, sync_filter_high)
        # Perform FFT convolution of above filter
        output_syncf = np.fft.ifft(np.fft.fft(output_sync) * self.Filters['FPsync']).real

        #print("min_ire ", min_ire)

        if self.system == 'PAL':
            out_videopilot = np.fft.ifft(demod_fft * self.Filters['FVideoPilot']).real
            rv_video = np.rec.array([out_video, demod, out_video05, output_syncf, out_videoburst, out_videopilot], names=['demod', 'demod_raw', 'demod_05', 'demod_sync', 'demod_burst', 'demod_pilot'])
        else:
            rv_video = np.rec.array([out_video, demod, out_video05, output_syncf, out_videoburst], names=['demod', 'demod_raw', 'demod_05', 'demod_sync', 'demod_burst'])

        if False:
            self.fig, self.ax1 = plt.subplots()
            self.ax2 = self.ax1.twinx()
            fig, ax1 = self.fig, self.ax1
            #fig.clf()
            #fig.cla()
            ax1.cla()

            ax1.axhline(self.iretohz(-55))
            ax1.axhline(self.iretohz(-25))

            color = 'tab:red'
            ax1.axhline(self.iretohz(self.SysParams['vsync_ire']), color=color)
            ax1.axhline(self.iretohz(0), color='0.0')
            ax1.axhline(min_level, color='#00FF00')
            ax1.axhline(sync_filter_high, color='#0000FF')

            ax1.plot(range(0, len(out_video)), out_video)
            ax1.plot(range(0, len(out_video05)), out_video05)

            ax2 = self.ax2#ax1.twinx()
            ax2.cla()

            ax2.plot(range(0, len(out_videoburst)), out_videoburst, color='#FF0000')

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

        if self.decode_analog_audio == False:
            return rv_video, None, rv_efm

        # Audio phase 1
        hilbert = np.fft.ifft(self.audio_fdslice(indata_fft) * self.Filters['audio_lfilt'])
        audio_left = unwrap_hilbert(hilbert, self.Filters['freq_arf']) + self.Filters['audio_lowfreq']

        hilbert = np.fft.ifft(self.audio_fdslice(indata_fft) * self.Filters['audio_rfilt'])
        audio_right = unwrap_hilbert(hilbert, self.Filters['freq_arf']) + self.Filters['audio_lowfreq']

        rv_audio = np.rec.array([audio_left, audio_right], names=['audio_left', 'audio_right'])

        return rv_video, rv_audio, rv_efm
