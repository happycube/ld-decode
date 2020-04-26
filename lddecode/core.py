from base64 import b64encode
import copy
from datetime import datetime
import getopt
import itertools
import io
from io import BytesIO
import logging
import os
import subprocess
import sys
import time

from numba import jit, njit

import threading
import queue

from multiprocessing import Process, Pool, Queue, JoinableQueue, Pipe

# standard numeric/scientific libraries
import numpy as np
import scipy as sp
import scipy.signal as sps
import scipy.interpolate as spi

# Use PyFFTW's faster FFT implementation if available
try:
    import pyfftw.interfaces.numpy_fft as npfft

    import pyfftw.interfaces
    pyfftw.interfaces.cache.enable()
    pyfftw.interfaces.cache.set_keepalive_time(10)
except ImportError:
    import numpy.fft as npfft

#internal libraries
from lddecode import efm_pll
from lddecode.utils import *

try:
    # If Anaconda's numpy is installed, mkl will use all threads for fft etc
    # which doesn't work when we do more threads, do disable that...
    import mkl
    mkl.set_num_threads(1)
except:
    # If not running Anaconda, we don't care that mkl doesn't exist.
    pass

logging.getLogger(__name__).setLevel(logging.DEBUG)

def calclinelen(SP, mult, mhz):
    if type(mhz) == str:
        mhz = SP[mhz]
        
    return int(np.round(SP['line_period'] * mhz * mult)) 

# These are invariant parameters for PAL and NTSC
SysParams_NTSC = {
    'fsc_mhz': (315.0 / 88.0),
    'pilot_mhz': (315.0 / 88.0),
    'frame_lines': 525,
    'field_lines': (263, 262),

    'ire0': 8100000,
    'hz_ire': 1700000 / 140.0,
    
    'vsync_ire': -40,

    # most NTSC disks have analog audio, except CD-V and a few Panasonic demos
    'analog_audio': True,
    # From the spec - audio frequencies are multiples of the (color) line rate
    'audio_lfreq': (1000000*315/88/227.5) * 146.25,
    # NOTE: this changes to 2.88mhz on AC3 disks
    'audio_rfreq': (1000000*315/88/227.5) * 178.75,

    'colorBurstUS': (5.3, 7.8),
    'activeVideoUS': (9.45, 63.555-1.0),

    # In NTSC framing, the distances between the first/last eq pulses and the 
    # corresponding next lines are different.
    'firstFieldH': (.5, 1),

    'numPulses': 6,         # number of equalization pulses per section
    'hsyncPulseUS': 4.7,
    'eqPulseUS': 2.3,
    'vsyncPulseUS': 27.1,
}

# In color NTSC, the line period was changed from 63.5 to 227.5 color cycles,
# which works out to 63.555(with a bar on top) usec
SysParams_NTSC['line_period'] = 1/(SysParams_NTSC['fsc_mhz']/227.5)
SysParams_NTSC['activeVideoUS'] = (9.45, SysParams_NTSC['line_period'] - 1.0)

SysParams_NTSC['FPS'] = 1000000/ (525 * SysParams_NTSC['line_period'])

SysParams_NTSC['outlinelen'] = calclinelen(SysParams_NTSC, 4, 'fsc_mhz')
SysParams_NTSC['outfreq'] = 4 * SysParams_NTSC['fsc_mhz']

SysParams_PAL = {
    'FPS': 25,
    
    # from wikipedia: 283.75 × 15625 Hz + 25 Hz = 4.43361875 MHz
    'fsc_mhz': ((1/64) * 283.75) + (25/1000000),
    'pilot_mhz': 3.75,
    'frame_lines': 625,
    'field_lines': (312, 313),
    'line_period': 64,

    'ire0': 7100000,
    'hz_ire': 800000 / 100.0,

    # only early PAL disks have analog audio
    'analog_audio': True,
    # From the spec - audio frequencies are multiples of the (colour) line rate
    'audio_lfreq': (1000000/64) * 43.75,
    'audio_rfreq': (1000000/64) * 68.25,

    'colorBurstUS': (5.6, 7.85),
    'activeVideoUS': (10.5, 64-1.5),

    # In PAL, the first field's line sync<->first/last EQ pulse are both .5H
    'firstFieldH': (1, .5),

    'numPulses': 5,         # number of equalization pulses per section
    'hsyncPulseUS': 4.7,
    'eqPulseUS': 2.35,
    'vsyncPulseUS': 27.3,
}

SysParams_PAL['outlinelen'] = calclinelen(SysParams_PAL, 4, 'fsc_mhz')
SysParams_PAL['outlinelen_pilot'] = calclinelen(SysParams_PAL, 4, 'pilot_mhz')
SysParams_PAL['outfreq'] = 4 * SysParams_PAL['fsc_mhz']

SysParams_PAL['vsync_ire'] = -.3 * (100 / .7)

# RFParams are tunable

RFParams_NTSC = {
    # The audio notch filters are important with DD v3.0+ boards
    'audio_notchwidth': 350000,
    'audio_notchorder': 2,

    'video_deemp': (120e-9, 320e-9),

    # This BPF is similar but not *quite* identical to what Pioneer did
    'video_bpf_low': 3400000, 
    'video_bpf_high': 13800000,
    'video_bpf_order': 4,

    # This can easily be pushed up to 4.5mhz or even a bit higher. 
    # A sharp 4.8-5.0 is probably the maximum before the audio carriers bleed into 0IRE.
    'video_lpf_freq': 4500000,   # in mhz
    'video_lpf_order': 6, # butterworth filter order

    # MTF filter
    'MTF_basemult': .4, # general ** level of the MTF filter for frame 0.
    'MTF_poledist': .9,
    'MTF_freq': 12.2, # in mhz

    # used to detect rot
    'video_hpf_freq': 10000000,
    'video_hpf_order': 4,

    'audio_filterwidth': 150000,
    'audio_filterorder': 800,
}

# Settings for use with noisier disks
RFParams_NTSC_lowband = {
    # The audio notch filters are important with DD v3.0+ boards
    'audio_notchwidth': 350000,
    'audio_notchorder': 2,

    'video_deemp': (120e-9, 320e-9),

    'video_bpf_low': 3800000, 
    'video_bpf_high': 12500000,
    'video_bpf_order': 4,

    'video_lpf_freq': 4200000,   # in mhz
    'video_lpf_order': 6, # butterworth filter order

    # MTF filter
    'MTF_basemult': .4, # general ** level of the MTF filter for frame 0.
    'MTF_poledist': .9,
    'MTF_freq': 12.2, # in mhz

    # used to detect rot
    'video_hpf_freq': 10000000,
    'video_hpf_order': 4,

    'audio_filterwidth': 150000,
    'audio_filterorder': 800,
}

RFParams_PAL = {
    # The audio notch filters are important with DD v3.0+ boards
    'audio_notchwidth': 200000,
    'audio_notchorder': 2,

    'video_deemp': (100e-9, 400e-9),

    # XXX: guessing here!
    'video_bpf_low': 2700000, 
    'video_bpf_high': 13500000,
    'video_bpf_order': 1,

    'video_lpf_freq': 4800000,
    'video_lpf_order': 7,

    # MTF filter
    'MTF_basemult': 1.0,  # general ** level of the MTF filter for frame 0.
    'MTF_poledist': .70,
    'MTF_freq': 10,

    # used to detect rot
    'video_hpf_freq': 10000000,
    'video_hpf_order': 4,

    'audio_filterwidth': 150000,
    'audio_filterorder': 800,
}

RFParams_PAL_lowband = {
    # The audio notch filters are important with DD v3.0+ boards
    'audio_notchwidth': 200000,
    'audio_notchorder': 2,

    'video_deemp': (100e-9, 400e-9),

    # XXX: guessing here!
    'video_bpf_low': 3200000, 
    'video_bpf_high': 13000000,
    'video_bpf_order': 1,

    'video_lpf_freq': 4800000,
    'video_lpf_order': 7,

    # MTF filter
    'MTF_basemult': 1.0,  # general ** level of the MTF filter for frame 0.
    'MTF_poledist': .70,
    'MTF_freq': 10,

    # used to detect rot
    'video_hpf_freq': 10000000,
    'video_hpf_order': 4,

    'audio_filterwidth': 150000,
    'audio_filterorder': 800,
}

class RFDecode:
    """The core RF decoding code.  
    
    This decoder uses FFT overlap-save processing(1) to allow for parallel processing and combination of 
    operations.
    
    Video filter signal path:
    - FFT/iFFT stage 1: RF BPF (i.e. 3.5-13.5mhz NTSC) * hilbert filter
    - phase unwrapping
    - FFT stage 2, which is processed into multiple final products:
      - Regular video output
      - 0.5mhz LPF (used for HSYNC)
      - For fine-tuning HSYNC: NTSC: 3.5x mhz filtered signal, PAL: 3.75mhz pilot signal
    
    Analogue audio filter signal path:
    
        The audio signal path is actually more complex in some ways, since it reduces a
        multi-msps signal down to <100khz.  A two stage processing system is used which
        reduces the frequency in each stage.

        Stage 1 performs the audio RF demodulation per block typically with 32x decimation,
        while stage 2 is run once the entire frame is demodulated and decimates by 4x.

    EFM filtering simply applies RF front end filters that massage the output so that ld-process-efm
    can do the actual work.

    references:
    1 - https://en.wikipedia.org/wiki/Overlap–save_method

    """

    def __init__(self, inputfreq = 40, system = 'NTSC', blocklen = 32*1024, decode_digital_audio = False, decode_analog_audio = 0, has_analog_audio = True, extra_options = {}):
        """Initialize the RF decoder object.

        inputfreq -- frequency of raw RF data (in Msps)
        system    -- Which system is in use (PAL or NTSC)
        blocklen  -- Block length for FFT processing
        decode_digital_audio -- Whether to apply EFM filtering
        decode_analog_audio  -- Whether or not to decode analog(ue) audio
        has_analog_audio     -- Whether or not analog(ue) audio channels are on the disk

        extra_options -- Dictionary of additional options (typically boolean) - these include:
          - WibbleRemover - PAL: cut 8.5mhz spurious signal, NTSC: notch filter on decoded video
          - lowband: Substitute different decode settings for lower-bandwidth disks

        """

        self.blocklen = blocklen
        self.blockcut = 1024 # ???
        self.blockcut_end = 0
        self.system = system

        self.WibbleRemover = True if extra_options.get('WibbleRemover') == True else False
        lowband = True if extra_options.get('lowband') == True else False

        freq = inputfreq
        self.freq = freq
        self.freq_half = freq / 2
        self.freq_hz = self.freq * 1000000
        self.freq_hz_half = self.freq * 1000000 / 2
        
        self.mtf_mult = 1.0
        self.mtf_offset = 0
        
        if system == 'NTSC':
            self.SysParams = copy.deepcopy(SysParams_NTSC)
            if lowband:
                self.DecoderParams = copy.deepcopy(RFParams_NTSC_lowband)
            else:
                self.DecoderParams = copy.deepcopy(RFParams_NTSC)
        elif system == 'PAL':
            self.SysParams = copy.deepcopy(SysParams_PAL)
            if lowband:
                self.DecoderParams = copy.deepcopy(RFParams_PAL_lowband)
            else:
                self.DecoderParams = copy.deepcopy(RFParams_PAL)

        self.SysParams['analog_audio'] = has_analog_audio

        linelen = self.freq_hz/(1000000.0/self.SysParams['line_period'])
        self.linelen = int(np.round(linelen))
        # How much horizontal sync position can deviate from previous/expected position 
        #and still be interpreted as a horizontal sync pulse.
        # Too high tolerance may result in false positive sync pulses, too low may end up missing them.
        # Tapes will need a wider tolerance than laserdiscs due to head switch etc.
        self.hsync_tolerance = .4
            
        self.decode_digital_audio = decode_digital_audio
        self.decode_analog_audio = decode_analog_audio

        self.computefilters()

        # The 0.5mhz filter is rolled back, so there are a few unusable bytes at the end
        self.blockcut_end = self.Filters['F05_offset']

    def computefilters(self):
        ''' (re)compute the filter sets '''

        self.computevideofilters()

        # This is > 0 because decode_analog_audio is in khz.
        if self.decode_analog_audio > 0: 
            self.computeaudiofilters()

        if self.decode_digital_audio:
            self.computeefmfilter()

        # This high pass filter is intended to detect RF dropouts
        Frfhpf = sps.butter(1, [10/self.freq_half], btype='highpass')
        self.Filters['Frfhpf'] = filtfft(Frfhpf, self.blocklen)

        self.computedelays()

    def computeefmfilter(self):
        """Frequency-domain equalisation filter for the LaserDisc EFM signal.
        This was inspired by the input signal equaliser in WSJT-X, described in
        Steven J. Franke and Joseph H. Taylor, "The MSK144 Protocol for
        Meteor-Scatter Communication", QEX July/August 2017.
        <http://physics.princeton.edu/pulsar/k1jt/MSK144_Protocol_QEX.pdf>

        This improved EFM filter was devised by Adam Sampson (@atsampson)
        """
        # Frequency bands
        freqs = np.linspace(0.0e6, 2.0e6, num=11)
        freq_per_bin = self.freq_hz / self.blocklen
        # Amplitude and phase adjustments for each band.
        # These values were adjusted empirically based on a selection of NTSC and PAL samples.
        amp = np.array([0.0, 0.2, 0.41, 0.73, 0.98, 1.03, 0.99, 0.81, 0.59, 0.42, 0.0])
        phase = np.array([0.0, -0.95, -1.05, -1.05, -1.2, -1.2, -1.2, -1.2, -1.2, -1.2, -1.2])
        coeffs = None

        """Compute filter coefficients for the given FFTFilter."""
        # Anything above the highest frequency is left as zero.
        coeffs = np.zeros(self.blocklen, dtype=np.complex)

        # Generate the frequency-domain coefficients by cubic interpolation between the equaliser values.
        a_interp = spi.interp1d(freqs, amp, kind="cubic")
        p_interp = spi.interp1d(freqs, phase, kind="cubic")
        
        nonzero_bins = int(freqs[-1] / freq_per_bin) + 1
        #print(nonzero_bins)
        
        bin_freqs = np.arange(nonzero_bins) * freq_per_bin
        bin_amp = a_interp(bin_freqs)
        bin_phase = p_interp(bin_freqs)

        # Scale by the amplitude, rotate by the phase
        coeffs[:nonzero_bins] = bin_amp * (np.cos(bin_phase) + (complex(0, -1) * np.sin(bin_phase)))

        # TODO: figure out this flip, the filter is asymmetric but works better that way.  huh.
        #coeffs[-nonzero_bins:] = np.flip(coeffs[:nonzero_bins], 0)
        
        self.Filters['Fefm'] = coeffs * 8

    def computevideofilters(self):
        self.Filters = {}
        
        # Use some shorthand to compact the code.
        SF = self.Filters
        SP = self.SysParams
        DP = self.DecoderParams

        # First phase FFT filtering

        # MTF filter section
        # compute the pole locations symmetric to freq_half (i.e. 12.2 and 27.8)
        MTF_polef_lo = DP['MTF_freq']/self.freq_half
        MTF_polef_hi = (self.freq_half + (self.freq_half - DP['MTF_freq']))/self.freq_half

        MTF = sps.zpk2tf([], [polar2z(DP['MTF_poledist'],np.pi*MTF_polef_lo), polar2z(DP['MTF_poledist'],np.pi*MTF_polef_hi)], 1)
        SF['MTF'] = filtfft(MTF, self.blocklen)

        # The BPF filter, defined for each system in DecoderParams
        filt_rfvideo = sps.butter(DP['video_bpf_order'], [DP['video_bpf_low']/self.freq_hz_half, DP['video_bpf_high']/self.freq_hz_half], btype='bandpass')
        # Start building up the combined FFT filter using the BPF
        SF['RFVideo'] = filtfft(filt_rfvideo, self.blocklen)

        # Notch filters for analog audio.  DdD captures in particular need this.
        if SP['analog_audio']:
            cut_left = sps.butter(DP['audio_notchorder'], [(SP['audio_lfreq'] - DP['audio_notchwidth'])/self.freq_hz_half, (SP['audio_lfreq'] + DP['audio_notchwidth'])/self.freq_hz_half], btype='bandstop')
            SF['Fcutl'] = filtfft(cut_left, self.blocklen)
            cut_right = sps.butter(DP['audio_notchorder'], [(SP['audio_rfreq'] - DP['audio_notchwidth'])/self.freq_hz_half, (SP['audio_rfreq'] + DP['audio_notchwidth'])/self.freq_hz_half], btype='bandstop')
            SF['Fcutr'] = filtfft(cut_right, self.blocklen)
        
            SF['RFVideo'] *= (SF['Fcutl'] * SF['Fcutr'])

        # The hilbert filter is defined in utils.py - it performs a 90 degree shift on the input.
        SF['hilbert'] = npfft.fft(hilbert_filter, self.blocklen)
        SF['RFVideo'] *= SF['hilbert']
        
        # Second phase FFT filtering, which is performed after the signal is demodulated

        video_lpf = sps.butter(DP['video_lpf_order'], DP['video_lpf_freq']/self.freq_hz_half, 'low')
        SF['Fvideo_lpf'] = filtfft(video_lpf, self.blocklen)

        if self.system == 'NTSC' and self.WibbleRemover:
            video_notch = sps.butter(3, [DP['video_lpf_freq']/1000000/self.freq_half, 5.0/self.freq_half], 'bandstop')
            SF['Fvideo_lpf'] *= filtfft(video_notch, self.blocklen)

        video_hpf = sps.butter(DP['video_hpf_order'], DP['video_hpf_freq']/self.freq_hz_half, 'high')
        SF['Fvideo_hpf'] = filtfft(video_hpf, self.blocklen)

        # The deemphasis filter
        deemp1, deemp2 = DP['video_deemp']
        SF['Fdeemp'] = filtfft(emphasis_iir(deemp1, deemp2, self.freq_hz), self.blocklen)

        # The direct opposite of the above, used in test signal generation
        SF['Femp'] = filtfft(emphasis_iir(deemp2, deemp1, self.freq_hz), self.blocklen)

        # Post processing:  lowpass filter + deemp
        SF['FVideo'] = SF['Fvideo_lpf'] * SF['Fdeemp'] 
        #SF['FVideo'] = SF['Fdeemp'] 
        
        # additional filters:  0.5mhz and color burst
        # Using an FIR filter here to get a known delay
        F0_5 = sps.firwin(65, [0.5/self.freq_half], pass_zero=True)
        SF['F05_offset'] = 32
        SF['F05'] = filtfft((F0_5, [1.0]), self.blocklen)
        SF['FVideo05'] = SF['Fvideo_lpf'] * SF['Fdeemp']  * SF['F05']

        if self.system == 'NTSC':
            SF['Fburst'] = filtfft(sps.butter(1, [(SP['fsc_mhz']-.1)/self.freq_half, (SP['fsc_mhz']+.1)/self.freq_half], btype='bandpass'), self.blocklen) 
            SF['FVideoBurst'] = SF['Fvideo_lpf'] * SF['Fdeemp']  * SF['Fburst']
        else:
            SF['Fpilot'] = filtfft(sps.butter(1, [(SP['pilot_mhz']-.1)/self.freq_half, (SP['pilot_mhz']+.1)/self.freq_half], btype='bandpass'), self.blocklen) 
            SF['FVideoPilot'] = SF['Fvideo_lpf'] * SF['Fdeemp']  * SF['Fpilot']
        
    # frequency domain slicers.  first and second stages use different ones...
    def audio_fdslice(self, freqdomain):
        return np.concatenate([freqdomain[self.Filters['audio_fdslice_lo']], freqdomain[self.Filters['audio_fdslice_hi']]])

    def audio_fdslice2(self, freqdomain):
        return np.concatenate([freqdomain[self.Filters['audio_fdslice2_lo']], freqdomain[self.Filters['audio_fdslice2_hi']]])
    
    def computeaudiofilters(self):
        SF = self.Filters
        SP = self.SysParams
        DP = self.DecoderParams

        # first stage audio filters
        if self.freq >= 32:
            audio_fdiv1 = 32 # this is good for 40mhz - 16 should be ideal for 28mhz
        else:
            audio_fdiv1 = 16
            
        afft_halfwidth = self.blocklen // (audio_fdiv1 * 2)
        arf_freq = self.freq_hz / (audio_fdiv1 / 2)
        SF['freq_arf'] = arf_freq
        SF['audio_fdiv1'] = audio_fdiv1

        SP['audio_cfreq'] = (SP['audio_rfreq'] + SP['audio_lfreq']) // 2
        afft_center = int((SP['audio_cfreq'] / self.freq_hz) * (self.blocklen))

        # beginning and end symmetrical frequency domain slices.  combine to make a cut-down sampling
        afft_start = int(afft_center-afft_halfwidth)
        afft_end = int(afft_center+afft_halfwidth)

        # slice areas for reduced FFT audio demodulation filters
        SF['audio_fdslice_lo'] = slice(afft_start, afft_end)
        SF['audio_fdslice_hi'] = slice(self.blocklen-afft_end, self.blocklen-afft_start)

        # compute the base frequency of the cut audio range
        SF['audio_lowfreq'] = SP['audio_cfreq']-(self.freq_hz/(2*SF['audio_fdiv1']))

        apass = DP['audio_filterwidth'] # audio RF bandpass.  150khz is the maximum transient.
        afilt_len = DP['audio_filterorder'] # good for 150khz apass

        afilt_left = filtfft([sps.firwin(afilt_len, [(SP['audio_lfreq']-apass)/self.freq_hz_half, (SP['audio_lfreq']+apass)/self.freq_hz_half], pass_zero=False), 1.0], self.blocklen)
        SF['audio_lfilt'] = self.audio_fdslice(afilt_left * SF['hilbert']) 
        afilt_right = filtfft([sps.firwin(afilt_len, [(SP['audio_rfreq']-apass)/self.freq_hz_half, (SP['audio_rfreq']+apass)/self.freq_hz_half], pass_zero=False), 1.0], self.blocklen)
        SF['audio_rfilt'] = self.audio_fdslice(afilt_right * SF['hilbert'])

        # second stage audio filters (decimates further, and applies audio LPF)
        audio_fdiv2 = 4
        SF['audio_fdiv'] = audio_fdiv1 * audio_fdiv2
        SF['audio_fdiv2'] = audio_fdiv2
        SF['freq_aud2'] = SF['freq_arf'] / audio_fdiv2

        # slice areas for reduced FFT audio filters
        SF['audio_fdslice2_lo'] = slice(0, self.blocklen//(audio_fdiv2*2))
        SF['audio_fdslice2_hi'] = slice(self.blocklen-self.blocklen//(audio_fdiv2*2), self.blocklen)

        SF['audio_lpf2'] = filtfft([sps.firwin(65, [21000/(SF['freq_aud2']/2)]), [1.0]], self.blocklen // (SF['audio_fdiv2'] * 1))

        # XXX: This probably needs further tuning, but more or less flattens the 20hz-20khz response
        # on both PAL and NTSC
        d75freq = 1000000/(2*pi*62)
        adeemp_b, adeemp_a = sps.butter(1, [d75freq/(SF['freq_aud2']/2)], btype='lowpass')
        addemp2lp = filtfft([adeemp_b, adeemp_a], self.blocklen // audio_fdiv2)

        dxfreq = 1000000/(2*pi*45)
        adeemp_b, adeemp_a = sps.butter(1, [dxfreq/(SF['freq_aud2']/2)], btype='highpass')
        addemp2hp1 = filtfft([adeemp_b, adeemp_a], self.blocklen // audio_fdiv2)

        dxfreq = 1000000/(2*pi*8)
        adeemp_b, adeemp_a = sps.butter(1, [dxfreq/(SF['freq_aud2']/2)], btype='highpass')
        addemp2hp2 = filtfft([adeemp_b, adeemp_a], self.blocklen // audio_fdiv2)

        SF['audio_deemp2'] = addemp2lp + (addemp2hp1 * .14) + (addemp2hp2 * .29)

    def iretohz(self, ire):
        return self.SysParams['ire0'] + (self.SysParams['hz_ire'] * ire)

    def hztoire(self, hz):
        return (hz - self.SysParams['ire0']) / self.SysParams['hz_ire']
    
    def demodblock(self, data = None, mtf_level = 0, fftdata = None, cut=False):
        rv = {}

        mtf_level *= self.mtf_mult
        mtf_level *= self.DecoderParams['MTF_basemult']
        mtf_level += self.mtf_offset
        
        if fftdata is not None:
            indata_fft = fftdata
        elif data is not None:
            indata_fft = npfft.fft(data[:self.blocklen])
        else:
            raise Exception("demodblock called without raw or FFT data")

        try:
            rotdelay = self.delays['video_rot']
        except:
            rotdelay = 0

        rv['rfhpf'] = npfft.ifft(indata_fft * self.Filters['Frfhpf']).real
        rv['rfhpf'] = rv['rfhpf'][self.blockcut-rotdelay:-self.blockcut_end-rotdelay]

        if self.system == 'PAL' and self.WibbleRemover:
            ''' This routine works around an 'interesting' issue seen with LD-V4300D players and 
                some PAL digital audio disks, where there is a signal somewhere between 8.47 and 8.57mhz.

                The idea here is to look for anomolies (3 std deviations) and snip them out of the
                FFT.  There may be side effects, however, but generally minor compared to the 
                'wibble' itself and only in certain cases.
            '''
            sl = slice(int(self.blocklen*(8.42/self.freq)), int(1+(self.blocklen*(8.6/self.freq))))
            sq_sl = sqsum(indata_fft[sl])
            m = np.mean(sq_sl) + (np.std(sq_sl) * 3)        

            for i in np.where(sq_sl > m)[0]:
                indata_fft[(i - 1 + sl.start)] = 0
                indata_fft[(i + sl.start)] = 0
                indata_fft[(i + 1 + sl.start)] = 0
                indata_fft[self.blocklen - (i + sl.start)] = 0
                indata_fft[self.blocklen - (i - 1 + sl.start)] = 0
                indata_fft[self.blocklen - (i + 1 + sl.start)] = 0

        indata_fft_filt = indata_fft * self.Filters['RFVideo']

        if mtf_level != 0:
            indata_fft_filt *= self.Filters['MTF'] ** mtf_level

        hilbert = npfft.ifft(indata_fft_filt)
        demod = unwrap_hilbert(hilbert, self.freq_hz)

        demod_fft_full = npfft.fft(demod)
        demod_hpf = npfft.ifft(demod_fft_full * self.Filters['Fvideo_hpf']).real

        # use a clipped demod for video output processing to reduce speckling impact 
        demod_fft = npfft.fft(np.clip(demod, 1500000, self.freq_hz * .75))

        out_video = npfft.ifft(demod_fft * self.Filters['FVideo']).real
        
        out_video05 = npfft.ifft(demod_fft * self.Filters['FVideo05']).real
        out_video05 = np.roll(out_video05, -self.Filters['F05_offset'])

        if self.system == 'PAL':
            out_videopilot = npfft.ifft(demod_fft * self.Filters['FVideoPilot']).real
            video_out = np.rec.array([out_video, demod, demod_hpf, out_video05, out_videopilot], names=['demod', 'demod_raw', 'demod_hpf', 'demod_05', 'demod_pilot'])
        else:
            out_videoburst = npfft.ifft(demod_fft * self.Filters['FVideoBurst']).real
            video_out = np.rec.array([out_video, demod, demod_hpf, out_video05, out_videoburst], names=['demod', 'demod_raw', 'demod_hpf', 'demod_05', 'demod_burst'])

        rv['video'] = video_out[self.blockcut:-self.blockcut_end] if cut else video_out

        if self.decode_digital_audio:
            efm_out = npfft.ifft(indata_fft * self.Filters['Fefm'])
            if cut:
                efm_out = efm_out[self.blockcut:-self.blockcut_end]
            rv['efm'] = np.int16(np.clip(efm_out.real, -32768, 32767))

        if self.decode_analog_audio:
            # Audio phase 1
            hilbert = npfft.ifft(self.audio_fdslice(indata_fft) * self.Filters['audio_lfilt'])
            audio_left = unwrap_hilbert(hilbert, self.Filters['freq_arf']) + self.Filters['audio_lowfreq']

            hilbert = npfft.ifft(self.audio_fdslice(indata_fft) * self.Filters['audio_rfilt'])
            audio_right = unwrap_hilbert(hilbert, self.Filters['freq_arf']) + self.Filters['audio_lowfreq']

            audio_out = np.rec.array([audio_left, audio_right], names=['audio_left', 'audio_right'])
            
            fdiv = video_out.shape[0] // audio_out.shape[0]
            rv['audio'] = audio_out[self.blockcut//fdiv:-self.blockcut_end//fdiv] if cut else audio_out

        return rv

    # detect clicks that are impossibly large and snip them out
    def audio_dropout_detector(self, field_audio, padding = 48):
        rejects = None
        cmed = {}

        # Check left and right channels separately.
        for channel in ['audio_left', 'audio_right']:
            achannel = field_audio[channel]
            cmed[channel] = np.median(achannel)
            aabs = np.abs(achannel - cmed[channel])

            if rejects is None:
                rejects = aabs > 175000
            else:
                rejects |= aabs > 175000

        if np.sum(rejects) == 0:
            # If no spikes, return original
            return field_audio

        # Locate areas with impossible signals and perform interpolation

        reject_locs = np.where(rejects)[0]
        reject_areas = []
        cur_area = [reject_locs[0] - padding, reject_locs[0] + padding]

        for r in np.where(rejects)[0][1:]:
            if (r - padding) > cur_area[1]:
                reject_areas.append(tuple(cur_area))
                cur_area = [r - padding, r + padding]
            else:
                cur_area[1] = r + padding

        reject_areas.append(cur_area)

        field_audio_dod = field_audio.copy()

        for channel in ['audio_left', 'audio_right']:
            for ra in reject_areas:
                if ra[0] <= 1 and ra[1] >= len(field_audio_dod) - 1:
                    # The entire thing can be bad during spinup
                    pass
                elif ra[0] <= 1:
                    field_audio_dod[channel][0:ra[1]] = field_audio_dod[channel][ra[1]+1]
                elif ra[1] >= len(field_audio_dod) - 1:
                    field_audio_dod[channel][ra[0]:] = field_audio_dod[channel][ra[0]-1]
                else:
                    abeg = field_audio_dod[channel][ra[0]]
                    aend = field_audio_dod[channel][ra[1]]
                    # pad np.arange run by 1 and crop it so there's always enough data to fill in
                    # XXX: clean up
                    field_audio_dod[channel][ra[0]:ra[1]] = np.arange(abeg, aend, (aend - abeg) / (1 + ra[1] - ra[0]))[:ra[1]-ra[0]]

        return field_audio_dod

    # Second phase audio filtering.  This works on a whole field's samples, since 
    # the frequency has already been reduced by 16 or 32x.

    def runfilter_audio_phase2(self, frame_audio, start):
        outputs = []

        clips = None

        for c in [['audio_left', 'audio_lfreq'], ['audio_right', 'audio_rfreq']]:
            raw = frame_audio[c[0]][start:start+self.blocklen].copy() - self.SysParams[c[1]]

            if c[0] == 'audio_left':
                clips = findpeaks(raw, 300000)

            for l in clips:
                replacelen = 16*self.Filters['audio_fdiv2']
                raw[max(0, l - replacelen):min(l + replacelen, len(raw))] = 0# raw[replacement_idx]

            fft_in_real = self.audio_fdslice2(npfft.fft(raw))
            if len(fft_in_real) < len(self.Filters['audio_lpf2']):
                fft_in = np.zeros_like(self.Filters['audio_lpf2'])
                fft_in[:len(fft_in_real)] = fft_in_real
            else:
                fft_in = fft_in_real
            fft_out = fft_in * self.Filters['audio_lpf2'] * self.Filters['audio_deemp2']

            outputs.append((npfft.ifft(fft_out).real[:len(fft_in_real)] / self.Filters['audio_fdiv2']) + self.SysParams[c[1]])

        return np.rec.array(outputs, names=['audio_left', 'audio_right'])

    def audio_phase2(self, field_audio):
        # this creates an output array with left/right channels.
        output_audio2 = np.zeros(len(field_audio['audio_left']) // self.Filters['audio_fdiv2'], dtype=field_audio.dtype)

        field_audio = self.audio_dropout_detector(field_audio)

        # copy the first block in it's entirety, to keep audio and video samples aligned
        tmp = self.runfilter_audio_phase2(field_audio, 0)

        if len(tmp) >= len(output_audio2):
            return tmp[:len(output_audio2)]

        output_audio2[:tmp.shape[0]] = tmp

        end = field_audio.shape[0] #// filterset['audio_fdiv2']

        askip = 512 # length of filters that needs to be chopped out of the ifft
        sjump = self.blocklen - (askip * self.Filters['audio_fdiv2'])

        ostart = tmp.shape[0]
        for sample in range(sjump, field_audio.shape[0] - sjump, sjump):
            tmp = self.runfilter_audio_phase2(field_audio, sample)
            
            oend = ostart + tmp.shape[0] - askip
            output_audio2[ostart:oend] = tmp[askip:]
            ostart += tmp.shape[0] - askip

        tmp = self.runfilter_audio_phase2(field_audio, end - self.blocklen - 1)
        output_audio2[output_audio2.shape[0] - (tmp.shape[0] - askip):] = tmp[askip:]

        return output_audio2    

    def computedelays(self, mtf_level = 0):
        '''Generate a fake signal and compute filter delays.
        
        mtf_level -- Specify the amount of MTF compensation needed (default 0.0)
                     WARNING: May not actually work.
        '''

        rf = self

        filterset = rf.Filters
        fakeoutput = np.zeros(rf.blocklen, dtype=np.double)

        # set base level to black
        fakeoutput[:] = rf.iretohz(0)

        synclen_full = int(4.7 * rf.freq)
        
        # sync 1 (used for gap determination)
        fakeoutput[1500:1500+synclen_full] = rf.iretohz(rf.SysParams['vsync_ire'])
        # sync 2 (used for pilot/rot level setting)
        fakeoutput[2000:2000+synclen_full] = rf.iretohz(rf.SysParams['vsync_ire'])

        porch_end = 2000+synclen_full + int(0.6 * rf.freq)
        burst_end = porch_end + int(1.2 * rf.freq)

        rate = np.full(burst_end-porch_end, rf.SysParams['fsc_mhz'], dtype=np.double)
        fakeoutput[porch_end:burst_end] += (genwave(rate, rf.freq / 2) * rf.SysParams['hz_ire'] * 20)
        
        # white
        fakeoutput[3000:3500] = rf.iretohz(100)

        # white + burst
        fakeoutput[4500:5000] = rf.iretohz(100)

        rate = np.full(5500-4200, rf.SysParams['fsc_mhz'], dtype=np.double)
        fakeoutput[4200:5500] += (genwave(rate, rf.freq / 2) * rf.SysParams['hz_ire'] * 20)
        
        rate = np.full(synclen_full, rf.SysParams['fsc_mhz'], dtype=np.double)
        fakeoutput[2000:2000+synclen_full] = rf.iretohz(rf.SysParams['vsync_ire']) + (genwave(rate, rf.freq / 2) * rf.SysParams['hz_ire'] * rf.SysParams['vsync_ire'])

        # add filters to generate a fake signal

        # NOTE: group pre-delay is not implemented, so the decoded signal
        # has issues settling down.  Emphasis is correct AFAIK

        tmp = npfft.fft(fakeoutput)
        tmp2 = tmp * (filterset['Fvideo_lpf'] ** 1)
        tmp3 = tmp2 * (filterset['Femp'] ** 1)

        #fakeoutput_lpf = npfft.ifft(tmp2).real
        fakeoutput_emp = npfft.ifft(tmp3).real

        fakesignal = genwave(fakeoutput_emp, rf.freq_hz / 2)
        fakesignal *= 4096
        fakesignal += 8192
        fakesignal[6000:6005] = 0

        fakedecode = rf.demodblock(fakesignal, mtf_level=mtf_level)

        # XXX: sync detector does NOT reflect actual sync detection, just regular filtering @ sync level
        # (but only regular filtering is needed for DOD)
        dgap_sync = calczc(fakedecode['video']['demod'], 1500, rf.iretohz(rf.SysParams['vsync_ire'] / 2), _count=512) - 1500
        dgap_white = calczc(fakedecode['video']['demod'], 3000, rf.iretohz(50), _count=512) - 3000
        dgap_rot = calczc(fakedecode['video']['demod'], 6000, rf.iretohz(-10), _count=512) - 6000

        rf.delays = {}
        # factor in the 1k or so block cut as well, since we never *just* do demodblock
        rf.delays['video_sync'] = dgap_sync #- self.blockcut
        rf.delays['video_white'] = dgap_white #- self.blockcut
        rf.delays['video_rot'] = int(np.round(dgap_rot)) #- self.blockcut
        
        fdec_raw = fakedecode['video']['demod_raw']
        
        rf.limits = {}
        rf.limits['sync'] = (np.min(fdec_raw[1400:2800]), np.max(fdec_raw[1400:2800]))
        rf.limits['viewable'] = (np.min(fdec_raw[2900:6000]), np.max(fdec_raw[2900:6000]))

        return fakedecode, dgap_sync, dgap_white

class DemodCache:
    def __init__(self, rf, infile, loader, cachesize = 256, num_worker_threads=6, MTF_tolerance = .05):
        self.infile = infile
        self.loader = loader
        self.rf = rf

        self.currentMTF = 1
        self.MTF_tolerance = MTF_tolerance
    
        self.blocksize = self.rf.blocklen - (self.rf.blockcut + self.rf.blockcut_end)
        
        # Cache dictionary - key is block #, which holds data for that block
        self.lrusize = cachesize
        self.prefetch = 32 # TODO: set this to proper amount for format
        self.lru = []
        
        self.lock = threading.Lock()
        self.blocks = {}

        self.q_in = JoinableQueue()
        self.q_in_metadata = []

        self.q_out = Queue()

        self.threadpipes = []
        self.threads = []

        num_worker_threads = max(num_worker_threads - 1, 1)

        for i in range(num_worker_threads):
            self.threadpipes.append(Pipe())
            t = Process(target=self.worker, daemon=True, args=(self.threadpipes[-1][1],))
            t.start()
            self.threads.append(t)

        self.deqeue_thread = threading.Thread(target=self.dequeue, daemon=True)
        self.deqeue_thread.start()

    def end(self):            
        # stop workers
        for i in self.threads:
            self.q_in.put(None)

        for t in self.threads:
            t.join()

        self.q_out.put(None)

    def __del__(self):
        self.end()

    def flush(self):
        if len(self.lru) < self.lrusize:
            return 
        
        self.lock.acquire()
        for k in self.lru[self.lrusize:]:
            if k in self.blocks:
                del self.blocks[k]
        self.lock.release()

        self.lru = self.lru[:self.lrusize]

    def flushvideo(self):
        for k in self.blocks.keys():
            if self.blocks[k] is None:
                pass
            elif 'demod' in self.blocks[k]:
                self.lock.acquire()
                del self.blocks[k]['demod']
                self.lock.release()

    def apply_newparams(self, newparams):
        for k in newparams.keys():
            #print(k, k in self.rf.SysParams, k in self.rf.DecoderParams)
            if k in self.rf.SysParams:
                self.rf.SysParams[k] = newparams[k]

            if k in self.rf.DecoderParams:
                self.rf.DecoderParams[k] = newparams[k]

        self.rf.computefilters()

    def worker(self, pipein):
        while True:
            ispiped = False
            if pipein.poll():
                item = pipein.recv()
                ispiped = True
            else:
                item = self.q_in.get()
            
            if item is None or item[0] == "END":
                return

            if item[0] == 'DEMOD':
                blocknum, block, target_MTF = item[1:]

                output = {}

                if 'fft' not in block:
                    output['fft'] = npfft.fft(block['rawinput'])
                    fftdata = output['fft']
                else:
                    fftdata = block['fft']

                if 'demod' not in block or np.abs(block['MTF'] - target_MTF) > self.MTF_tolerance:
                    output['demod'] = self.rf.demodblock(fftdata = fftdata, mtf_level=target_MTF, cut=True)
                    output['MTF'] = target_MTF

                self.q_out.put((blocknum, output))
            elif item[0] == 'NEWPARAMS':
                self.apply_newparams(item[1])

            if not ispiped:
                self.q_in.task_done()

    def doread(self, blocknums, MTF, dodemod = True):
        need_blocks = []

        hc = 0

        self.lock.acquire()

        for b in blocknums:
            if b not in self.blocks:
                LRUupdate(self.lru, b)

                rawdata = self.loader(self.infile, b * self.blocksize, self.rf.blocklen)
                
                if rawdata is None or len(rawdata) < self.rf.blocklen:
                    self.blocks[b] = None
                    self.lock.release()
                    return None

                rawdatac = rawdata.copy()
                #rawdatac[16384:16388] = -32500

                self.blocks[b] = {}
                self.blocks[b]['rawinput'] = rawdatac

            if self.blocks[b] is None:
                self.lock.release()
                return None

            if dodemod:
                handling = need_demod = ('demod' not in self.blocks[b]) or (np.abs(self.blocks[b]['MTF'] - MTF) > self.MTF_tolerance)
            else:
                handling = need_demod = False

            # Check to see if it's already in queue to process
            if need_demod:
                for inqueue in self.q_in_metadata:
                    if inqueue[0] == b and (np.abs(inqueue[1] - MTF) <= self.MTF_tolerance):
                        handling = False
                        #print(b)

                need_blocks.append(b)
            
            if handling:
                self.q_in.put(("DEMOD", b, self.blocks[b], MTF))
                self.q_in_metadata.append((b, MTF))
                hc = hc + 1

        self.lock.release()

        #print(hc, len(need_blocks), len(self.q_in_metadata))

        return need_blocks

    def dequeue(self):
        while True: # not self.q_out.empty():
            rv = self.q_out.get()
            if rv is None:
                return

            self.lock.acquire()

            blocknum, item = rv

            if 'MTF' not in item or 'demod' not in item:
                # This shouldn't happen, but was observed by Simon on a decode
                logging.error('incomplete demodulated block placed on queue, block #%d', blocknum)
                self.q_in.put((blocknum, self.blocks[blocknum], self.currentMTF))
                self.lock.release()
                continue                

            self.q_in_metadata.remove((blocknum, item['MTF']))

            for k in item.keys():
                if k == 'demod' and (np.abs(item['MTF'] - self.currentMTF) > self.MTF_tolerance):
                    continue
                self.blocks[blocknum][k] = item[k]
        
            if 'input' not in self.blocks[blocknum]:
                self.blocks[blocknum]['input'] = self.blocks[blocknum]['rawinput'][self.rf.blockcut:-self.rf.blockcut_end]

            self.lock.release()

    def read(self, begin, length, MTF=0, dodemod=True):
        # transpose the cache by key, not block #
        t = {'input':[], 'fft':[], 'video':[], 'audio':[], 'efm':[], 'rfhpf':[]}

        self.currentMTF = MTF

        end = begin+length

        toread = range(begin // self.blocksize, (end // self.blocksize) + 1)
        toread_prefetch = range(end // self.blocksize, (end // self.blocksize) + self.prefetch)

        need_blocks = self.doread(toread, MTF, dodemod)

        if dodemod == False:            
            raw = [self.blocks[toread[0]]['rawinput'][begin % self.blocksize:]]
            for i in range(toread[1], toread[-2]):
                raw.append(self.blocks[i]['rawinput'])
            raw.append(self.blocks[-1]['rawinput'][:end % self.blocksize])
            
            rv = np.concatenate(raw)
            self.flush()
            return rv

        while need_blocks is not None and len(need_blocks):
            time.sleep(.005)
            need_blocks = self.doread(toread, MTF)

        if need_blocks is None:
            # EOF
            return None

        # Now coalesce the output
        for b in range(begin // self.blocksize, (end // self.blocksize) + 1):
            for k in t.keys():
                if k in self.blocks[b]['demod']:
                    t[k].append(self.blocks[b]['demod'][k])
                elif k in self.blocks[b]:
                    t[k].append(self.blocks[b][k])

        self.flush()

        rv = {}
        for k in t.keys():
            rv[k] = np.concatenate(t[k]) if len(t[k]) else None
        
        if rv['audio'] is not None:
            rv['audio_phase1'] = rv['audio']
            rv['audio'] = self.rf.audio_phase2(rv['audio'])

        rv['startloc'] = (begin // self.blocksize) * self.blocksize

        need_blocks = self.doread(toread_prefetch, MTF)

        return rv

    def setparams(self, params):
        for p in self.threadpipes:
            p[0].send(('NEWPARAMS', params))

        # Apply params to the core thread, so they match up with the decoders
        self.apply_newparams(params)

@njit
def dsa_rescale(infloat):
    return int(np.round(infloat * 32767 / 150000))

# right now defualt is 16/48, so not optimal :)
def downscale_audio(audio, lineinfo, rf, linecount, timeoffset = 0, freq = 48000.0, scale=64):
    failed = False

    frametime = linecount / (1000000 / rf.SysParams['line_period'])
    soundgap = 1 / freq

    # include one extra 'tick' to interpolate the last one and use as a return value
    # for the next frame
    arange = np.arange(timeoffset, frametime + (soundgap / 2), soundgap, dtype=np.double)
    locs = np.zeros(len(arange), dtype=np.float)
    swow = np.zeros(len(arange), dtype=np.float)
    
    for i, t in enumerate(arange):
        linenum = (((t * 1000000) / rf.SysParams['line_period']) + 1)
        
        # XXX: 
        # The timing handling can sometimes go outside the bounds of the known line #'s.  
        # This is a quick-ish fix that should work OK, but may need to be reworked if
        # analog audio is weak for some reason
        if linenum < 0:
            lineloc_cur = int(lineinfo[0] + (rf.linelen * linenum))
            lineloc_next = lineloc_cur + rf.linelen
        else:
            try:
                lineloc_cur = lineinfo[np.int(linenum)]
                lineloc_next = lineinfo[np.int(linenum) + 1]
            except:
                # Catch things that go past the last known line by using the last lines here.
                lineloc_cur = lineinfo[-2]
                lineloc_next = lineloc_cur + rf.linelen

        sampleloc = lineloc_cur
        sampleloc += (lineloc_next - lineloc_cur) * (linenum - np.floor(linenum))

        swow[i] = (lineloc_next - lineloc_cur) / rf.linelen
        # There's almost *no way* the disk is spinning more than 5% off, so mask TBC errors here
        # to reduce pops
        if i and np.abs(swow[i] - swow[i - 1]) > .015:
            swow[i] = swow[i - 1]

        locs[i] = sampleloc / scale

    output = np.zeros((2 * (len(arange) - 1)), dtype=np.int32)
    output16 = np.zeros((2 * (len(arange) - 1)), dtype=np.int16)

    for i in range(len(arange) - 1):
        try:
            output_left = nb_mean(audio['audio_left'][np.int(locs[i]):np.int(locs[i+1])])
            output_right = nb_mean(audio['audio_right'][np.int(locs[i]):np.int(locs[i+1])])

            output_left = (output_left * swow[i]) - rf.SysParams['audio_lfreq']
            output_right = (output_right * swow[i]) - rf.SysParams['audio_rfreq']
            
            output[(i * 2) + 0] = dsa_rescale(output_left) #int(np.round(output_left * 32767 / 150000))
            output[(i * 2) + 1] = dsa_rescale(output_right)
        except:
            # TBC failure can cause this (issue #389)
            if failed == False:
                logging.warning("Analog audio processing error, muting samples")

            failed = True
        
    #print(locs[len(arange)-1], len(audio['audio_left']), np.min(output), np.max(output), swow[len(arange) - 1], linenum)

    np.clip(output, -32766, 32766, out=output16)
            
    return output16, arange[-1] - frametime

# The Field class contains common features used by NTSC and PAL
class Field:
    def __init__(self, rf, decode, audio_offset = 0, keepraw = True, prevfield = None, initphase = False):
        self.rawdata = decode['input']
        self.data = decode
        self.initphase = initphase # used for seeking or first field

        prevfield = None
        self.prevfield = prevfield

        # XXX: need a better way to prevent memory leaks than this
        # For now don't let a previous frame keep it's prev frame
        if prevfield is not None:
            prevfield.prevfield = None

        self.rf = rf
        self.freq = self.rf.freq
        
        self.inlinelen = self.rf.linelen
        self.outlinelen = self.rf.SysParams['outlinelen']

        self.lineoffset = 0
        
        self.valid = False
        self.sync_confidence = 100
        
        self.dspicture = None
        self.dsaudio = None
        self.audio_offset = audio_offset
        self.audio_next_offset = audio_offset

        # On NTSC linecount rounds up to 263, and PAL 313
        self.outlinecount = (self.rf.SysParams['frame_lines'] // 2) + 1
        # this is eventually set to 262/263 and 312/313 for audio timing
        self.linecount = None

    def process(self):
        self.linelocs1, self.linebad, self.nextfieldoffset = self.compute_linelocs()
        if self.linelocs1 is None:
            if self.nextfieldoffset is None:
                self.nextfieldoffset = self.rf.linelen * 200

            return

        self.linebad = self.compute_deriv_error(self.linelocs1, self.linebad)

        self.linelocs2 = self.refine_linelocs_hsync()
        self.linebad = self.compute_deriv_error(self.linelocs2, self.linebad)

        self.linelocs = self.linelocs2
        self.wowfactor = self.computewow(self.linelocs)

        self.valid = True

    def get_linefreq(self, l = None):
        if l is None or l == 0:
            return self.freq
        else:
            return self.freq * (((self.linelocs[l+1] - self.linelocs[l-1]) / 2) / self.inlinelen)

    def usectoinpx(self, x, line = None):
        return x * self.get_linefreq(line)
    
    def inpxtousec(self, x, line = None):
        return x / self.get_linefreq(line)

    def lineslice(self, l, begin = None, length = None, linelocs = None, begin_offset = 0):
        ''' return a slice corresponding with pre-TBC line l, begin+length are uSecs '''
        
        # for PAL, each field has a different offset so normalize that
        l_adj = l + self.lineoffset

        _begin = linelocs[l_adj] if linelocs is not None else self.linelocs[l_adj]
        _begin += self.usectoinpx(begin, l_adj) if begin is not None else 0

        _length = self.usectoinpx(length, l_adj) if length is not None else 1

        return slice(int(np.floor(_begin + begin_offset)), int(np.ceil(_begin + _length + begin_offset)))

    def usectooutpx(self, x):
        return x * self.rf.SysParams['outfreq']

    def outpxtousec(self, x):
        return x / self.rf.SysParams['outfreq']

    def lineslice_tbc(self, l, begin = None, length = None, linelocs = None, keepphase = False):
        ''' return a slice corresponding with pre-TBC line l '''
        
        _begin = self.rf.SysParams['outlinelen'] * (l - 1)

        begin_offset = self.usectooutpx(begin) if begin is not None else 0
        if keepphase:
            begin_offset = (begin_offset // 4) * 4

        _begin += begin_offset 
        _length = self.usectooutpx(length) if length is not None else self.rf.SysParams['outlinelen']

        return slice(int(np.round(_begin)), int(np.round(_begin + _length)))

    def refinepulses(self, pulses):
        ''' returns validated pulses with type and distance checks '''
        
        hsync_typical = self.usectoinpx(self.rf.SysParams['hsyncPulseUS'])

        # Some disks have odd sync levels resulting in short and/or long pulse lengths.
        # So, take the median hsync and adjust the expected values accordingly

        hsync_checkmin = self.usectoinpx(self.rf.SysParams['hsyncPulseUS'] - 1.75)
        hsync_checkmax = self.usectoinpx(self.rf.SysParams['hsyncPulseUS'] + 2)

        hlens = []
        for p in pulses:
            if inrange(p.len, hsync_checkmin, hsync_checkmax):
                hlens.append(p.len)

        hsync_median = np.median(hlens)

        hsync_min = hsync_median + self.usectoinpx(-.5)
        hsync_max = hsync_median + self.usectoinpx(.5)

        hsync_offset = hsync_median - hsync_typical

        eq_min = self.usectoinpx(self.rf.SysParams['eqPulseUS'] - .5) + hsync_offset
        eq_max = self.usectoinpx(self.rf.SysParams['eqPulseUS'] + .5) + hsync_offset

        vsync_min = self.usectoinpx(self.rf.SysParams['vsyncPulseUS'] * .5) + hsync_offset
        vsync_max = self.usectoinpx(self.rf.SysParams['vsyncPulseUS'] + 1) + hsync_offset

        # Pulse validator routine.  Removes sync pulses of invalid lengths, does not 
        # fill missing ones.

        # states for first field of validpulses (second field is pulse #)
        HSYNC, EQPL1, VSYNC, EQPL2 = range(4)

        vsyncs = [] # VSYNC area (first broad pulse->first EQ after broad pulses)

        inorder = False
        validpulses = []

        vsync_start = None
        earliest_eq = 0
        earliest_hsync = 0

        # state order: HSYNC -> EQPUL1 -> VSYNC -> EQPUL2 -> HSYNC

        for p in pulses:
            spulse = None

            state = validpulses[-1][0] if len(validpulses) > 0 else -1

            if state == -1:
                # First valid pulse must be a regular HSYNC
                if inrange(p.len, hsync_min, hsync_max):
                    spulse = (HSYNC, p)
            elif state == HSYNC:
                # HSYNC can transition to EQPUL/pre-vsync at the end of a field
                if inrange(p.len, hsync_min, hsync_max):
                    spulse = (HSYNC, p)
                elif p.start > earliest_eq and inrange(p.len, eq_min, eq_max):
                    spulse = (EQPL1, p)
                elif p.start > earliest_eq and inrange(p.len, vsync_min, vsync_max):
                    vsync_start = len(validpulses)-1
                    spulse = (VSYNC, p)
            elif state == EQPL1:
                if inrange(p.len, eq_min, eq_max):
                    spulse = (EQPL1, p)
                elif inrange(p.len, vsync_min, vsync_max):
                    # len(validpulses)-1 before appending adds index to first VSYNC pulse
                    vsync_start = len(validpulses)-1
                    spulse = (VSYNC, p)
                elif inrange(p.len, hsync_min, hsync_max):
                    # previous state transition was likely in error!
                    spulse = (HSYNC, p)
            elif state == VSYNC:
                if inrange(p.len, eq_min, eq_max):
                    # len(validpulses)-1 before appending adds index to first EQ pulse
                    vsyncs.append((vsync_start, len(validpulses)-1))
                    spulse = (EQPL2, p)
                elif inrange(p.len, vsync_min, vsync_max):
                    spulse = (VSYNC, p)
                elif p.start > earliest_hsync and inrange(p.len, hsync_min, hsync_max):
                    spulse = (HSYNC, p)
                    earliest_eq = p.start + (self.inlinelen * (np.min(self.rf.SysParams['field_lines']) - 10))
            elif state == EQPL2:
                if inrange(p.len, eq_min, eq_max):
                    spulse = (EQPL2, p)
                elif inrange(p.len, hsync_min, hsync_max):
                    spulse = (HSYNC, p)
                    earliest_eq = p.start + (self.inlinelen * (np.min(self.rf.SysParams['field_lines']) - 10))

            if vsync_start is not None and earliest_hsync == 0:
                earliest_hsync = validpulses[vsync_start][1].start + (self.rf.SysParams['numPulses'] * self.inlinelen)

            # Quality check
            if spulse is not None and len(validpulses) >= 1:
                prevpulse = validpulses[-1]
                if prevpulse[0] > 0 and spulse[0] > 0:
                    exprange = (.4, .6)
                elif prevpulse[0] == 0 and spulse[0] == 0:
                    exprange = (.9, 1.1)
                else: # transition to/from regular hsyncs can be .5 or 1H
                    exprange = (.4, 1.1)

                linelen = (spulse[1].start - prevpulse[1].start) / self.inlinelen
                inorder = inrange(linelen, *exprange)

            if spulse is not None:
                validpulses.append((spulse[0], spulse[1], inorder))

        return validpulses

    def getblankrange(self, vpulses, start = 0):
        vp_type = np.array([p[0] for p in vpulses])

        try:
            firstvsync = np.where(vp_type[start:] == 2)[0][0] + start
            
            for newstart in range(firstvsync - 10, firstvsync - 4):
                firstblank = np.where(vp_type[newstart:] > 0)[0][0] + newstart
                lastblank = np.where(vp_type[firstblank:] == 0)[0][0] + firstblank - 1
                
                if (lastblank - firstblank) > 12:
                    return firstblank, lastblank
        except:
            pass
        
        # there isn't a valid range to find, or it's impossibly short
        return None, None

    def getBlankLength(self, isFirstField):
        core = (self.rf.SysParams['numPulses'] * 3 * .5)
        
        if self.rf.system == 'NTSC':
            return core + 1
        else:
            return core + .5 + (0 if isFirstField else 1)
        
        return core

    def processVBlank(self, validpulses, start):

        firstblank, lastblank = self.getblankrange(validpulses, start)

        ''' 
        First Look at each equalization/vblank pulse section - if the expected # are there and valid,
        it can be used to determine where line 0 is...
        '''
        # locations of lines before after/vblank.  may not be line 0 etc
        if firstblank is None:
            return None, None

        loc_presync = validpulses[firstblank-1][1].start

        HSYNC, EQPL1, VSYNC, EQPL2 = range(4)

        pt = np.array([v[0] for v in validpulses[firstblank:]])
        pstart = np.array([v[1].start for v in validpulses[firstblank:]])
        plen = np.array([v[1].len for v in validpulses[firstblank:]])

        numPulses = self.rf.SysParams['numPulses']

        for i in [VSYNC, EQPL1, EQPL2]:
            ptmatch = (pt == i)
            grouploc = None

            for j in range(0, lastblank - firstblank):
                if ptmatch[j:j+numPulses].all():
                    if ptmatch[j:j+numPulses+4].sum() != numPulses:
                        break

                    # take the (second) derivative of the line gaps and lengths to determine 
                    # if all are valid
                    gaps = np.diff(np.diff(pstart[j:j+numPulses]))
                    lengths = np.diff(plen[j:j+numPulses])

                    if np.max(gaps) < (self.rf.freq * .2) and np.max(lengths) < (self.rf.freq * .2):
                        grouploc = j
                        break

            if grouploc is None:
                continue

            setbegin = validpulses[firstblank+grouploc]
            firstloc = setbegin[1].start

            # compute the distance of the first pulse of this block to line 1
            # (line 0 may be .5H or 1H before that)
            distfroml1 = (((i - 1) * self.rf.SysParams['numPulses']) * .5)

            dist = (firstloc - loc_presync) / self.inlinelen
            # get the integer rounded X * .5H distance.  then invert to determine
            # the half-H alignment with the sync/blank pulses
            hdist = int(np.round(dist * 2))
            
            #isfirstfield = not ((hdist % 2) == self.rf.SysParams['firstField1H'][0])
            isfirstfield = (hdist % 2) == (self.rf.SysParams['firstFieldH'][1] != 1)

            # for PAL VSYNC, the offset is 2.5H, so the calculation must be reversed
            if (distfroml1 * 2) % 2:
                isfirstfield = not isfirstfield

            eqgap = self.rf.SysParams['firstFieldH'][isfirstfield]
            line0 = firstloc - ((eqgap + distfroml1) * self.inlinelen)

            return np.int(line0), isfirstfield

        '''
        If there are no valid sections, check line 0 and the first eq pulse, and the last eq
        pulse and the following line.  If the combined xH is correct for the standard in question
        (1.5H for NTSC, 1 or 2H for PAL, that means line 0 has been found correctly.
        '''

        self.sync_confidence = 50

        if validpulses[firstblank - 1][2] and validpulses[firstblank][2] and validpulses[lastblank][2] and validpulses[lastblank + 1][2]:
            gap1 = validpulses[firstblank][1].start - validpulses[firstblank - 1][1].start
            gap2 = validpulses[lastblank + 1][1].start - validpulses[lastblank][1].start
            
            if self.rf.system == 'PAL' and inrange(np.abs(gap2 - gap1), 0, self.rf.freq * 1):
                isfirstfield = inrange((gap1 / self.inlinelen), 0.45, 0.55)
            elif self.rf.system == 'NTSC' and inrange(np.abs(gap2 + gap1), self.inlinelen * 1.4, self.inlinelen * 1.6):
                isfirstfield = inrange((gap1 / self.inlinelen), 0.95, 1.05)
            else:
                self.sync_confidence = 0
                return None, None

            return validpulses[firstblank - 1][1].start, isfirstfield

        self.sync_confidence = 0
                
        return None, None

    def computeLineLen(self, validpulses):
        # determine longest run of 0's
        longrun = [-1, -1]
        currun = None
        for i, v in enumerate([p[0] for p in self.validpulses]):
            if v != 0:
                if currun is not None and currun[1] > longrun[1]:
                    longrun = currun
                currun = None
            elif currun is None:
                currun = [i, 0]
            else:
                currun[1] += 1

        if currun is not None and currun[1] > longrun[1]:
            longrun = currun

        linelens = []
        for i in range(longrun[0] + 1, longrun[0] + longrun[1]):
            linelen = self.validpulses[i][1].start - self.validpulses[i-1][1].start
            if inrange(linelen / self.inlinelen, .95, 1.05):
                linelens.append(self.validpulses[i][1].start - self.validpulses[i-1][1].start)

        return np.mean(linelens)

    # pull the above together into a routine that (should) find line 0, the last line of
    # the previous field.

    def getLine0(self, validpulses):
        line0loc, isFirstField = self.processVBlank(validpulses, 0)
        
        if line0loc is not None and self.sync_confidence == 100:
            return line0loc, isFirstField

        # If there isn't a valid transition in the first field's hsync, try the next
        line0loc_next, isNotFirstField = self.processVBlank(validpulses, 100)

        if line0loc_next is None:
            try:
                if self.prevfield is not None:
                    if self.initphase == False:
                        logging.warning("Severe VSYNC-area corruption detected.")
                    self.sync_confidence = 10
                    return self.prevfield.linelocs[self.prevfield.outlinecount - 1] - self.prevfield.nextfieldoffset, not self.prevfield.isFirstField
            except:
                # If the previous field is corrupt, something may fail up there
                pass

            if line0loc is None and self.initphase == False:
                logging.error("Extreme VSYNC-area corruption detected, dropping field")

            return line0loc, isFirstField

        isFirstField = not isNotFirstField

        meanlinelen = self.computeLineLen(validpulses)
        fieldlen = (meanlinelen * self.rf.SysParams['field_lines'][0 if isFirstField else 1])
        line0loc = int(np.round(line0loc_next - fieldlen))

        return line0loc, isFirstField        

    def getpulses(self):
        # pass one using standard levels 

        # pulse_hz range:  vsync_ire - 10, maximum is the 50% crossing point to sync
        pulse_hz_min = self.rf.iretohz(self.rf.SysParams['vsync_ire'] - 10)
        pulse_hz_max = self.rf.iretohz(self.rf.SysParams['vsync_ire'] / 2)

        pulses = findpulses(self.data['video']['demod_05'], pulse_hz_min, pulse_hz_max)

        if len(pulses) == 0:
            # can't do anything about this
            return pulses

        # determine sync pulses from vsync
        vsync_locs = []
        vsync_means = []

        for i, p in enumerate(pulses):
            if p.len > self.usectoinpx(10):
                vsync_locs.append(i)
                vsync_means.append(np.mean(self.data['video']['demod_05'][int(p.start+self.rf.freq):int(p.start+p.len-self.rf.freq)]))
                
        if len(vsync_means) == 0:
            return None

        synclevel = np.median(vsync_means)

        if np.abs(self.rf.hztoire(synclevel) - self.rf.SysParams['vsync_ire']) < 5:
            # sync level is close enough to use
            return pulses

        if vsync_locs is None or not len(vsync_locs):
            return None

        # Now compute black level and try again

        # take the eq pulses before and after vsync
        r1 = range(vsync_locs[0]-5,vsync_locs[0])
        r2 = range(vsync_locs[-1]+1,vsync_locs[-1]+6)

        black_means = []

        for i in itertools.chain(r1, r2):
            if i < 0 or i >= len(pulses):
                continue

            p = pulses[i]
            if inrange(p.len, self.rf.freq * .75, self.rf.freq * 2.5):
                black_means.append(np.mean(self.data['video']['demod_05'][int(p.start+(self.rf.freq*5)):int(p.start+(self.rf.freq*20))]))

        blacklevel = np.median(black_means)

        pulse_hz_min = synclevel - (self.rf.SysParams['hz_ire'] * 10)
        pulse_hz_max = (blacklevel + synclevel) / 2

        return findpulses(self.data['video']['demod_05'], pulse_hz_min, pulse_hz_max)

    def compute_linelocs(self):

        self.rawpulses = self.getpulses()
        if self.rawpulses is None or len(self.rawpulses) == 0:
            logging.error("Unable to find any sync pulses, jumping one second")
            return None, None, int(self.rf.freq_hz)

        self.validpulses = validpulses = self.refinepulses(self.rawpulses)

        line0loc, self.isFirstField = self.getLine0(validpulses)
        linelocs_dict = {}
        linelocs_dist = {}

        if line0loc is None:
            if self.initphase == False:
                logging.error("Unable to determine start of field - dropping field")

            return None, None, self.inlinelen * 200

        meanlinelen = self.computeLineLen(validpulses)

        if ((self.rawpulses[-1].start - line0loc) / meanlinelen) < (self.outlinecount + 7):
            return None, None, line0loc - (meanlinelen * 3)

        for p in validpulses:
            lineloc = (p[1].start - line0loc) / meanlinelen
            rlineloc = np.round(lineloc)
            lineloc_distance = np.abs(lineloc - rlineloc)

            #print(p, lineloc, rlineloc, lineloc_distance)

            # only record if it's closer to the (probable) beginning of the line
            if lineloc_distance > self.rf.hsync_tolerance or (rlineloc in linelocs_dict and lineloc_distance > linelocs_dist[rlineloc]):
                #print(rlineloc, p, 'reject')
                continue

            linelocs_dict[np.round(lineloc)] = p[1].start
            linelocs_dist[np.round(lineloc)] = lineloc_distance

        rv_err = np.full(self.outlinecount + 6, False)

        # Convert dictionary into list, then fill in gaps
        linelocs = [linelocs_dict[l] if l in linelocs_dict else -1 for l in range(0, self.outlinecount + 6)]
        linelocs_filled = linelocs.copy()

        self.linelocs0 = linelocs.copy()

        if linelocs_filled[0] < 0:
            next_valid = None
            for i in range(0, self.outlinecount + 1):
                if linelocs[i] > 0:
                    next_valid = i
                    break

            if next_valid is None:
                #logging.warning(next_valid)
                return None, None, line0loc + (self.inlinelen * self.outlinecount - 7)

            linelocs_filled[0] = linelocs_filled[next_valid] - (next_valid * meanlinelen)
            
            if linelocs_filled[0] < self.inlinelen:
                #logging.warning(linelocs_filled[0])
                return None, None, line0loc + (self.inlinelen * self.outlinecount - 7)

        for l in range(1, self.outlinecount + 6):
            if linelocs_filled[l] < 0:
                rv_err[l] = True

                prev_valid = None
                next_valid = None

                for i in range(l, 1, -1):
                    if linelocs[i] > 0:
                        prev_valid = i
                        break
                for i in range(l, self.outlinecount + 1):
                    if linelocs[i] > 0:
                        next_valid = i
                        break

                if prev_valid is None:
                    avglen = self.inlinelen
                    linelocs_filled[l] = linelocs[next_valid] - (avglen * (next_valid - l))
                elif next_valid is not None:
                    avglen = (linelocs[next_valid] - linelocs[prev_valid]) / (next_valid - prev_valid)
                    linelocs_filled[l] = linelocs[prev_valid] + (avglen * (l - prev_valid))
                else:
                    avglen = self.inlinelen 
                    linelocs_filled[l] = linelocs[prev_valid] + (avglen * (l - prev_valid))

        # *finally* done :)

        rv_ll = [linelocs_filled[l] for l in range(0, self.outlinecount + 6)]

        return rv_ll, rv_err, linelocs_filled[self.outlinecount - 7]

    def refine_linelocs_hsync(self):
        linelocs2 = self.linelocs1.copy()

        for i in range(len(self.linelocs1)):
            # skip VSYNC lines, since they handle the pulses differently 
            if inrange(i, 3, 6) or (self.rf.system == 'PAL' and inrange(i, 1, 2)):
                self.linebad[i] = True
                continue
                        
            # Find beginning of hsync (linelocs1 is generally in the middle)
            ll1 = self.linelocs1[i] - self.usectoinpx(5.5)
            #logging.info(i, ll1)
            #print(i, ll1, len(self.data['video']['demod_05']))
            zc = calczc(self.data['video']['demod_05'], ll1, self.rf.iretohz(self.rf.SysParams['vsync_ire'] / 2), reverse=False, _count=400)

            if zc is not None and not self.linebad[i]:
                linelocs2[i] = zc 

                # The hsync area, burst, and porches should not leave -50 to 30 IRE (on PAL or NTSC)
                hsync_area = self.data['video']['demod_05'][int(zc-(self.rf.freq*.75)):int(zc+(self.rf.freq*8))]
                if nb_min(hsync_area) < self.rf.iretohz(-55) or nb_max(hsync_area) > self.rf.iretohz(30):
                    self.linebad[i] = True
                    linelocs2[i] = self.linelocs1[i] # don't use the computed value here if it's bad
                else:
                    porch_level = nb_median(self.data['video']['demod_05'][int(zc+(self.rf.freq*8)):int(zc+(self.rf.freq*9))])
                    sync_level = nb_median(self.data['video']['demod_05'][int(zc+(self.rf.freq*1)):int(zc+(self.rf.freq*2.5))])

                    zc2 = calczc(self.data['video']['demod_05'], ll1, (porch_level + sync_level) / 2, reverse=False, _count=400)

                    # any wild variation here indicates a failure
                    if zc2 is not None and np.abs(zc2 - zc) < (self.rf.freq / 2):
                        linelocs2[i] = zc2
                    else:
                        self.linebad[i] = True
                        linelocs2[i] = self.linelocs1[i]  # don't use the computed value here if it's bad
            else:
                self.linebad[i] = True

        return linelocs2

    def compute_deriv_error(self, linelocs, baserr):
        ''' compute errors based off the second derivative - if it exceeds 1 something's wrong,
            and if 4 really wrong...
        '''

        derr1 = np.full(len(linelocs), False)
        derr1[1:-1] = np.abs(np.diff(np.diff(linelocs))) > 4
        
        derr2 = np.full(len(linelocs), False)
        derr2[2:] = np.abs(np.diff(np.diff(linelocs))) > 4

        return baserr | derr1 | derr2

    def fix_badlines(self, linelocs_in, linelocs_backup_in = None):
        self.linebad = self.compute_deriv_error(linelocs_in, self.linebad)
        linelocs = np.array(linelocs_in.copy())

        if linelocs_backup_in is not None:
            linelocs_backup = np.array(linelocs_backup_in.copy())
            badlines = np.isnan(linelocs)
            linelocs[badlines] = linelocs_backup[badlines]

        for l in np.where(self.linebad)[0]:
            prevgood = l - 1
            nextgood = l + 1

            while prevgood >= 0 and self.linebad[prevgood]:
                prevgood -= 1

            while nextgood < len(linelocs) and self.linebad[nextgood]:
                nextgood += 1

            #print(l, prevgood, nextgood)

            if prevgood >= 0 and nextgood < len(linelocs):
                gap = (linelocs[nextgood] - linelocs[prevgood]) / (nextgood - prevgood)
                linelocs[l] = (gap * (l - prevgood)) + linelocs[prevgood]
                
        return linelocs

    def computewow(self, lineinfo):
        wow = np.ones(len(lineinfo))

        for l in range(0, len(wow)-1):
            wow[l] = (lineinfo[l + 1] - lineinfo[l]) / self.inlinelen

        return wow

        # early work on issue 37, hits a FutureWarning in scipy

        # apply a simple 5-tap filter to the wowfactor
        #filt = (0.1, 0.2, 0.4, 0.2, 0.1)
        # do not use the first or last lines, which are often inaccurate...
        #wf_filter = sps.lfilter(filt, (1.0), wow[1:-1])

        # copy the valid new wowfactors (drop the first few lines since they were 0...)
        #wf2 = copy.copy(wow)
        #wf2[4:-3] = wf_filter[5:]

    def downscale(self, lineinfo = None, linesout = None, outwidth = None, channel='demod', audio = 0):
        if lineinfo is None:
            lineinfo = self.linelocs
        if outwidth is None:
            outwidth = self.outlinelen
        if linesout is None:
            # for video always output 263/313 lines
            linesout = self.outlinecount

        dsout = np.zeros((linesout * outwidth), dtype=np.double)    
        # self.lineoffset is an adjustment for 0-based lines *before* downscaling so add 1 here
        lineoffset = self.lineoffset + 1

        for l in range(lineoffset, linesout + lineoffset):
            if lineinfo[l + 1] > lineinfo[l]:
                scaled = scale(self.data['video'][channel], lineinfo[l], lineinfo[l + 1], outwidth, self.wowfactor[l])
#                scaled *= self.wowfactor[l]

                dsout[(l - lineoffset) * outwidth:(l + 1 - lineoffset)*outwidth] = scaled
            else:
                logging.warning("WARNING: TBC failure at line %d", l)
                dsout[(l - lineoffset) * outwidth:(l + 1 - lineoffset)*outwidth] = self.rf.SysParams['ire0']

        if audio > 0 and self.rf.decode_analog_audio:
            self.dsaudio, self.audio_next_offset = downscale_audio(self.data['audio'], lineinfo, self.rf, self.linecount, self.audio_offset, freq = audio)
            
        if self.rf.decode_digital_audio:
            self.efmout = self.data['efm'][int(self.linelocs[1]):int(self.linelocs[self.linecount + 1])]
        else:
            self.efmout = None

        return dsout, self.dsaudio, self.efmout
    
    def decodephillipscode(self, linenum):
        linestart = self.linelocs[linenum]
        data = self.data['video']['demod']
        curzc = calczc(data, int(linestart + self.usectoinpx(2)), self.rf.iretohz(50), _count=int(self.usectoinpx(12)))

        zc = []
        while curzc is not None:
            zc.append((curzc, data[int(curzc - self.usectoinpx(0.5))] < self.rf.iretohz(50)))
            curzc = calczc(data, curzc+self.usectoinpx(1.9), self.rf.iretohz(50), _count=int(self.usectoinpx(0.2)))

        usecgap = self.inpxtousec(np.diff([z[0] for z in zc]))
        valid = len(zc) == 24 and np.min(usecgap) > 1.85 and np.max(usecgap) < 2.15

        if valid:
            bitset = [z[1] for z in zc]
            linecode = 0

            for b in range(0, 24, 4):
                linecode *= 0x10
                linecode += (np.packbits(bitset[b:b+4]) >> 4)[0]

            return linecode
        
        return None

    def compute_syncconf(self):
        ''' use final lineloc data to compute sync confidence '''
        
        newconf = 100
        
        lld = np.diff(self.linelocs[self.lineoffset:self.lineoffset+self.linecount])
        lld2 = np.diff(lld)
        lld2max = np.max(lld2)

        if lld2max > 4:
            newconf = int(50 - (5 * np.sum(lld2max > 4)))
        
        newconf = max(newconf, 0)
        
        self.sync_confidence = min(self.sync_confidence, newconf)
        return int(self.sync_confidence)

    def dropout_detect_demod(self):
        # current field
        f = self

        isPAL = self.rf.system == 'PAL'

        rfstd = np.std(f.data['rfhpf'])
        #iserr_rf = np.full(len(f.data['video']['demod']), False, dtype=np.bool)
        iserr_rf1 = (f.data['rfhpf'] < (-rfstd * 3)) | (f.data['rfhpf'] > (rfstd * 3)) # | (f.rawdata <= -32000)
        iserr_rf = np.full_like(iserr_rf1, False)
        iserr_rf[self.rf.delays['video_rot']:] = iserr_rf1[:-self.rf.delays['video_rot']]
        
        # detect absurd fluctuations in pre-deemp demod, since only dropouts can cause them
        # (current np.diff has a prepend option, but not in ubuntu 18.04's version)
        iserr1 = f.data['video']['demod_raw'] > self.rf.freq_hz_half
        # This didn't work right for PAL (issue #471)
        # iserr1 |= f.data['video']['demod_hpf'] > 3000000

        # build sets of min/max valid levels 
        valid_min = np.full_like(f.data['video']['demod'], f.rf.iretohz(-60 if isPAL else -50))
        valid_max = np.full_like(f.data['video']['demod'], f.rf.iretohz(150 if isPAL else 140))
        
        # the minimum valid value during VSYNC is lower for PAL because of the pilot signal
        minsync = -100 if isPAL else -50

        # these lines should cover both PAL and NTSC's hsync areas
        if False:
            for i in range(0, len(f.linelocs)):
                l = f.linelocs[i]
                # Could compute the estimated length of setup, but we can cut this a bit early...
                valid_min[int(l-(f.rf.freq * .5)):int(l+(f.rf.freq * 8))] = f.rf.iretohz(minsync)
                valid_max[int(l-(f.rf.freq * .5)):int(l+(f.rf.freq * 8))] = f.rf.iretohz(40)

                if self.rf.system == 'PAL':
                    # basically exclude the pilot signal altogether
                    # This is needed even though HSYNC is excluded later, since failures can be expanded
                    valid_min[int(l-(f.rf.freq * .5)):int(l+(f.rf.freq * 4.7))] = f.rf.iretohz(-80)
                    valid_max[int(l-(f.rf.freq * .5)):int(l+(f.rf.freq * 4.7))] = f.rf.iretohz(50)

        iserr2 = f.data['video']['demod'] < valid_min
        iserr2 |= f.data['video']['demod'] > valid_max

        valid_min05 = np.full_like(f.data['video']['demod_05'], f.rf.iretohz(-20 if isPAL else -20))
        valid_max05 = np.full_like(f.data['video']['demod_05'], f.rf.iretohz(115 if isPAL else 110))

        iserr3 = f.data['video']['demod_05'] < valid_min05
        iserr3 |= f.data['video']['demod_05'] > valid_max05

        iserr = iserr1 | iserr2 | iserr3 | iserr_rf

        # Each valid pulse is definitely *not* an error, so exclude it here at the end
        for v in self.validpulses:
            iserr[int(v[1].start-self.rf.freq):int(v[1].start+v[1].len+self.rf.freq)] = False
        
        return iserr


    def build_errlist(self, errmap):
        errlist = []

        firsterr = errmap[np.nonzero(errmap >= self.linelocs[self.lineoffset])[0][0]]
        curerr = (firsterr, firsterr)

        for e in errmap:
            if e > curerr[0] and e <= (curerr[1] + 20):
                pad = ((e - curerr[0])) * 1.7
                pad = min(pad, self.rf.freq * 12)
                epad = curerr[0] + pad
                curerr = (curerr[0], epad)
            elif e > firsterr:
                #errlist.append((curerr[0] - 4, curerr[1] + 4))
                errlist.append((curerr[0] - 8, curerr[1] + 4))
                curerr = (e, e)

        errlist.append(curerr)
                
        return errlist

    def dropout_errlist_to_tbc(self, errlist):
        dropouts = []

        if len(errlist) == 0:
            return dropouts

        # Now convert the above errlist into TBC locations
        errlistc = errlist.copy()
        curerr = errlistc.pop(0)

        lineoffset = -self.lineoffset

        for l in range(lineoffset, self.linecount + self.lineoffset):
            while curerr is not None and inrange(curerr[0], self.linelocs[l], self.linelocs[l + 1]):
                start_rf_linepos = curerr[0] - self.linelocs[l]
                start_linepos = start_rf_linepos / (self.linelocs[l + 1] - self.linelocs[l])
                start_linepos = int(start_linepos * self.outlinelen)

                end_rf_linepos = curerr[1] - self.linelocs[l]
                end_linepos = end_rf_linepos / (self.linelocs[l + 1] - self.linelocs[l])
                end_linepos = int(np.round(end_linepos * self.outlinelen))

                if end_linepos > self.outlinelen:
                    # need to output two dropouts
                    dropouts.append((l + 1 + lineoffset, start_linepos, self.outlinelen))
                    dropouts.append((l + 1 + lineoffset + (end_linepos // self.outlinelen), 0, np.remainder(end_linepos, self.outlinelen)))
                else:
                    dropouts.append((l + 1 + lineoffset, start_linepos, end_linepos))

                if len(errlistc):
                    curerr = errlistc.pop(0)
                else:
                    curerr = None

        return dropouts

    def dropout_detect(self):
        ''' returns dropouts in three arrays, to line up with the JSON output '''

        rv_lines = []
        rv_starts = []
        rv_ends = []

        iserr = self.dropout_detect_demod()
        errmap = np.nonzero(iserr)[0]

        if len(errmap) > 0 and errmap[-1] > self.linelocs[self.lineoffset]:
            errlist = self.build_errlist(errmap)

            rvs = self.dropout_errlist_to_tbc(errlist)    
            for r in rvs:
                rv_lines.append(r[0] - 1)
                rv_starts.append(int(r[1]))
                rv_ends.append(int(r[2]))

        return rv_lines, rv_starts, rv_ends

# These classes extend Field to do PAL/NTSC specific TBC features.

class FieldPAL(Field):

    def refine_linelocs_pilot(self, linelocs = None):
        if linelocs is None:
            linelocs = self.linelocs2.copy()
        else:
            linelocs = linelocs.copy()

        plen = {}

        zcs = []
        for l in range(0, 312):
            adjfreq = self.rf.freq
            if l > 1:
                adjfreq /= (linelocs[l] - linelocs[l - 1]) / self.rf.linelen

            plen[l] = (adjfreq / self.rf.SysParams['pilot_mhz']) / 2

            ls = self.lineslice(l, 0, 6, linelocs)
            lsoffset = linelocs[l] - ls.start

            pilots = self.data['video']['demod_pilot'][ls]

            peakloc = np.argmax(np.abs(pilots))

            try:
                zc = (calczc(pilots, peakloc, 0) - lsoffset) / plen[l]
            except:
                zc = zcs[-1] if len(zcs) else 0
                
            zcs.append(zc)

        am = angular_mean(zcs)

        #print(am, np.std(zcs - np.floor(zcs)))

        for l in range(0, 312):
            #print(l, phase_distance(zcs[l], am))
            linelocs[l] += (phase_distance(zcs[l], am) * plen[l]) * 1

        return np.array(linelocs)

    def calc_burstmedian(self):
        burstlevel = np.zeros(314)

        for l in range(3, 313):
            burstarea = self.data['video']['demod'][self.lineslice(l, 6, 3)]
            burstlevel[l] = rms(burstarea) * np.sqrt(2)

        return nb_median(burstlevel / self.rf.SysParams['hz_ire'])

    def hz_to_output(self, input):
        reduced = (input - self.rf.SysParams['ire0']) / self.rf.SysParams['hz_ire']
        reduced -= self.rf.SysParams['vsync_ire']
        
        return np.uint16(np.clip((reduced * self.out_scale) + 256, 0, 65535) + 0.5)

    def output_to_ire(self, output):
        return ((output- 256.0) / self.out_scale) + self.rf.SysParams['vsync_ire']

    def downscale(self, final = False, *args, **kwargs):
        # For PAL, each field starts with the line containing the first full VSYNC pulse
        dsout, dsaudio, dsefm = super(FieldPAL, self).downscale(*args, **kwargs)
        
        if final:
            self.dspicture = self.hz_to_output(dsout)
            return self.dspicture, dsaudio, dsefm
                    
        return dsout, dsaudio, dsefm
    
    def __init__(self, *args, **kwargs):
        super(FieldPAL, self).__init__(*args, **kwargs)

    def process(self):
        super(FieldPAL, self).process()

        self.out_scale = np.double(0xd300 - 0x0100) / (100 - self.rf.SysParams['vsync_ire'])

        if not self.valid:
            return

        if True:
            self.linelocs3 = self.refine_linelocs_pilot(self.linelocs2)
            # do a second pass for fine tuning (typically < .1px), because the adjusted 
            # frequency changes slightly from the first pass
            self.linelocs3a = self.refine_linelocs_pilot(self.linelocs3)
            self.linelocs = self.fix_badlines(self.linelocs3a)
        else:
            self.linelocs = self.fix_badlines(self.linelocs2)

        self.wowfactor = self.computewow(self.linelocs)
        self.burstmedian = self.calc_burstmedian()

        self.linecount = 312 if self.isFirstField else 313
        self.lineoffset = 2 if self.isFirstField else 3

        self.linecode = [self.decodephillipscode(l + self.lineoffset) for l in [16, 17, 18]]

        #self.downscale(final=True)

# These classes extend Field to do PAL/NTSC specific TBC features.

# Hotspots found in profiling are refactored here and boosted by numba's jit.
@njit(cache=True)
def clb_findnextburst(burstarea, i, endburstarea, threshold):
    for j in range(i, endburstarea):
        if np.abs(burstarea[j]) > threshold:
            return j, burstarea[j]

    return None

@njit(cache=True)
def clb_subround(x):
    # Yes, this was a hotspot.
    return np.round(x) - x

class FieldNTSC(Field):

    def get_burstlevel(self, l, linelocs = None):
        burstarea = self.data['video']['demod'][self.lineslice(l, 5.5, 2.4, linelocs)].copy()

        return rms(burstarea) * np.sqrt(2)


    def compute_line_bursts(self, linelocs, line):
        '''
        Compute the zero crossing for the given line using calczc
        '''
        # calczc works from integers, so get the start and remainder
        s = int(linelocs[line])
        s_rem = linelocs[line] - s

        # compute adjusted frequency from neighboring line lengths
        if line > 0:
            lfreq = self.rf.freq * (((self.linelocs2[line+1] - self.linelocs2[line-1]) / 2) / self.rf.linelen)
        elif line == 0:
            lfreq = self.rf.freq * (((self.linelocs2[line+1] - self.linelocs2[line-0]) / 1) / self.rf.linelen)
        elif line >= 262:
            lfreq = self.rf.freq * (((self.linelocs2[line+0] - self.linelocs2[line-1]) / 1) / self.rf.linelen)

        # compute approximate burst beginning/end
        bstime = 17 * (1 / self.rf.SysParams['fsc_mhz']) # approx start of burst in usecs

        bstart = int(bstime * lfreq)
        bend = int(8.8 * lfreq)

        zc_bursts = {False: [], True: []}

        # copy and get the mean of the burst area to factor out wow/flutter
        burstarea = self.data['video']['demod_burst'][s+bstart:s+bend]
        if len(burstarea) == 0:
            #logging.info( line, s + bstart, s + bend, linelocs[line])
            return zc_bursts

        burstarea = burstarea - nb_mean(burstarea)

        threshold = 8 * self.rf.SysParams['hz_ire']

        fsc_n1 = (1 / self.rf.SysParams['fsc_mhz'])
        zcburstdiv = (lfreq * fsc_n1)

        numpos = 0
        numneg = 0
        zc_bursts_t = np.zeros(64, dtype=np.float)
        zc_bursts_n = np.zeros(64, dtype=np.float)

        i = clb_findnextburst(burstarea, 0, len(burstarea) - 1, threshold)
        zc = 0

        while i is not None and zc is not None:
            zc = calczc(burstarea, i[0], 0)
            if zc is not None:
                zc_burst = clb_subround((bstart+zc-s_rem) / zcburstdiv) 
                if i[1] < 0:
                    zc_bursts_t[numpos] = zc_burst
                    numpos = numpos + 1
                else:
                    zc_bursts_n[numneg] = zc_burst
                    numneg = numneg + 1

                i = clb_findnextburst(burstarea, int(zc + 1), len(burstarea) - 1, threshold)

        return {False: zc_bursts_n[:numneg], True:zc_bursts_t[:numpos]}
        #return {False: np.array(zc_bursts[False]), True:np.array(zc_bursts[True])}

    def compute_burst_offsets(self, linelocs):
        linelocs_adj = linelocs

        burstlevel = np.zeros_like(linelocs_adj, dtype=np.float32)

        zc_bursts = {}
        # Counter for which lines have + polarity.  TRACKS 1-BASED LINE #'s
        bursts = {'odd': [], 'even': []}

        for l in range(0, 266):
            zc_bursts[l] = self.compute_line_bursts(linelocs, l)
            burstlevel[l] = self.get_burstlevel(l, linelocs)

            if (len(zc_bursts[l][True]) == 0) or (len(zc_bursts[l][False]) == 0):
                continue

            if not (l % 2):
                bursts['even'].append(zc_bursts[l][True])
                bursts['odd'].append(zc_bursts[l][False])
            else:
                bursts['even'].append(zc_bursts[l][False])
                bursts['odd'].append(zc_bursts[l][True])

        bursts_arr = {}
        bursts_arr[True] = np.concatenate(bursts['even'])
        bursts_arr[False] = np.concatenate(bursts['odd'])

        amed = {}
        amed[True] = np.abs(angular_mean(bursts_arr[True], zero_base=False))
        amed[False] = np.abs(angular_mean(bursts_arr[False], zero_base=False))
        
        field14 = amed[True] < amed[False]

        # if the medians are too close, recompute them with a 90 degree offset.

        # XXX: print a warning message here since some disks will suffer phase errors
        # if this code runs.  (OTOH, any disk that triggers this is *seriously* out of
        # spec...)
        if (np.abs(amed[True] - amed[False]) < .025):
            amed = {}
            amed[True] = np.abs(angular_mean(bursts_arr[True] + .25, zero_base=False))
            amed[False] = np.abs(angular_mean(bursts_arr[False] + .25, zero_base=False))
            # Use > instead of < to maintain polarity in *most* cases
            field14 = amed[True] > amed[False]

        self.amed = amed
        self.zc_bursts = zc_bursts

        return zc_bursts, field14, burstlevel

    def refine_linelocs_burst(self, linelocs = None):
        if linelocs is None:
            linelocs = self.linelocs2

        linelocs_adj = linelocs.copy()
        burstlevel = np.zeros_like(linelocs_adj, dtype=np.float32)

        zc_bursts, field14, burstlevel = self.compute_burst_offsets(linelocs_adj)

        adjs = {}

        for l in range(1, 9):
            self.linebad[l] = True

        # compute the adjustments for each line but *do not* apply, so
        # outliers can be bypassed
        for l in range(0, 266):
            if self.linebad[l]:
                continue

            edge = not ((field14 and (l % 2)) or (not field14 and not (l % 2)))

            if not (np.isnan(linelocs_adj[l]) or len(zc_bursts[l][edge]) == 0 or self.linebad[l]):
                if l > 0:
                    lfreq = self.rf.freq * (((self.linelocs2[l+1] - self.linelocs2[l-1]) / 2) / self.rf.linelen)
                elif l == 0:
                    lfreq = self.rf.freq * (((self.linelocs2[l+1] - self.linelocs2[l-0]) / 1) / self.rf.linelen)
                elif l >= 262:
                    lfreq = self.rf.freq * (((self.linelocs2[l+0] - self.linelocs2[l-1]) / 1) / self.rf.linelen)

                adjs[l] = -(nb_median(zc_bursts[l][edge]) * lfreq * (1 / self.rf.SysParams['fsc_mhz']))

        try:
            adjs_median = np.median([adjs[a] for a in adjs])
            
            for l in range(0, 266):
                if l in adjs and inrange(adjs[l] - adjs_median, -2, 2):
                    linelocs_adj[l] += adjs[l]
                else:
                    linelocs_adj[l] += adjs_median
                    if l >= 20:
                        # issue #217: if possible keep some line data even if burst is bad 
                        self.linebad[l] = True

            if self.isFirstField:
                self.fieldPhaseID = 1 if field14 else 3
            else:
                self.fieldPhaseID = 4 if field14 else 2
        except:
            self.fieldPhaseID=1
            return linelocs_adj, burstlevel

        return linelocs_adj, burstlevel
    
    def hz_to_output(self, input):
        reduced = (input - self.rf.SysParams['ire0']) / self.rf.SysParams['hz_ire']
        reduced -= self.rf.SysParams['vsync_ire']

        return np.uint16(np.clip((reduced * self.out_scale) + 1024, 0, 65535) + 0.5)

    def output_to_ire(self, output):
        return ((output - 1024) / self.out_scale) + self.rf.SysParams['vsync_ire']

    def downscale(self, lineoffset = 0, final = False, *args, **kwargs):
        if final == False:
            if 'audio' in kwargs:
                kwargs['audio'] = 0

        dsout, dsaudio, dsefm = super(FieldNTSC, self).downscale(*args, **kwargs)
        
        if final:
            lines16 = self.hz_to_output(dsout)

            self.dspicture = lines16
            return lines16, dsaudio, dsefm
                    
        return dsout, dsaudio, dsefm
    
    def calc_burstmedian(self):
        burstlevel = [self.get_burstlevel(l) for l in range(11, 264)]

        return np.median(burstlevel) / self.rf.SysParams['hz_ire']

    def apply_offsets(self, linelocs, phaseoffset, picoffset = 0):
        #logging.info(phaseoffset, (phaseoffset * (self.rf.freq / (4 * 315 / 88))))
        return np.array(linelocs) + picoffset + (phaseoffset * (self.rf.freq / (4 * 315 / 88)))

    def __init__(self, *args, **kwargs):
        self.burstlevel = None
        self.burst90 = False

        super(FieldNTSC, self).__init__(*args, **kwargs)

    def process(self):
        super(FieldNTSC, self).process()

        self.out_scale = np.double(0xc800 - 0x0400) / (100 - self.rf.SysParams['vsync_ire'])
        
        if not self.valid:
            return

        self.linecount = 263 if self.isFirstField else 262

        self.linecode = [self.decodephillipscode(l + self.lineoffset) for l in [16, 17, 18]]

        self.linelocs3, self.burstlevel = self.refine_linelocs_burst(self.linelocs2)
        self.linelocs3 = self.fix_badlines(self.linelocs3, self.linelocs2)

        self.burstmedian = self.calc_burstmedian()

        # Now adjust 33 degrees to get the downscaled image onto I/Q color axis
        # self.linelocs = np.array(self.linelocs3) + ((33/360.0) * (63.555555/227.5) * self.rf.freq)
        # Now adjust 33 degrees (-90 - 33) for color decoding
        shift33 = 84 * (np.pi / 180)
        self.linelocs = self.apply_offsets(self.linelocs3, -shift33 - 0)        

        self.wowfactor = self.computewow(self.linelocs)        

class CombNTSC:
    ''' *partial* NTSC comb filter class - only enough to do VITS calculations ATM '''
    
    def __init__(self, field):
        self.field = field
        self.cbuffer = self.buildCBuffer()

    def getlinephase(self, line):
        ''' determine if a line has positive color burst phase '''
        fieldID = self.field.fieldPhaseID
        
        fieldPositivePhase = (fieldID == 1) | (fieldID == 4)
        
        return fieldPositivePhase if ((line % 2) == 0) else not fieldPositivePhase

    def buildCBuffer(self, subset = None):
        ''' 
        prev_field: Compute values for previous field
        subset: a slice computed by lineslice_tbc (default: whole field) 
        
        NOTE:  first and last two returned values will be zero, so slice accordingly
        '''
        
        data = self.field.dspicture
        
        if subset:
            data = data[subset]
            
        # this is a translation of this code from tools/ld-chroma-decoder/comb.cpp:
        #
        # for (qint32 h = configuration.activeVideoStart; h < configuration.activeVideoEnd; h++) {
        #  qreal tc1 = (((line[h + 2] + line[h - 2]) / 2) - line[h]);
                        
        fldata = data.astype(np.float32)
        cbuffer = np.zeros_like(fldata)
        
        cbuffer[2:-2] = (fldata[:-4] + fldata[4:]) / 2
        cbuffer[2:-2] -= fldata[2:-2]
        
        return cbuffer

    def splitIQ(self, cbuffer, line = 0):
        ''' 
        NOTE:  currently? only works on one line
        
        This returns normalized I and Q arrays, each one half the length of cbuffer 
        '''
        linephase = self.getlinephase(line)
        
        sq = cbuffer[::2].copy()
        si = cbuffer[1::2].copy()

        if not linephase:
            si[0::2] = -si[0::2]
            sq[1::2] = -sq[1::2]
        else:
            si[1::2] = -si[1::2]
            sq[0::2] = -sq[0::2]
    
        return si, sq
    
    def calcLine19Info(self, comb_field2 = None):
        ''' returns color burst phase (ideally 147 degrees) and (unfiltered!) SNR '''
        
        # Don't need the whole line here, but start at 0 to definitely have an even #
        l19_slice = self.field.lineslice_tbc(19, 0, 40)
        l19_slice_i70 = self.field.lineslice_tbc(19, 14, 18)

        # fail out if there is obviously bad data
        if not ((np.max(self.field.output_to_ire(self.field.dspicture[l19_slice_i70])) < 100) and
                (np.min(self.field.output_to_ire(self.field.dspicture[l19_slice_i70])) > 40)):
            #logging.info("WARNING: line 19 data incorrect")
            #logging.info(np.max(self.field.output_to_ire(self.field.dspicture[l19_slice_i70])), np.min(self.field.output_to_ire(self.field.dspicture[l19_slice_i70])))
            return None, None, None

        cbuffer = self.cbuffer[l19_slice]
        if comb_field2 is not None:
            # fail out if there is obviously bad data
            if not ((np.max(self.field.output_to_ire(comb_field2.field.dspicture[l19_slice_i70])) < 100) and
                    (np.min(self.field.output_to_ire(comb_field2.field.dspicture[l19_slice_i70])) > 40)):
                return None, None, None

            cbuffer -= comb_field2.cbuffer[l19_slice]
            cbuffer /= 2
            
        si, sq = self.splitIQ(cbuffer, 19)

        sl = slice(110,230)
        cdata = np.sqrt((si[sl] ** 2.0) + (sq[sl] ** 2.0))

        phase = np.arctan2(np.mean(si[sl]),np.mean(sq[sl]))*180/np.pi
        if phase < 0:
            phase += 360

        # compute SNR
        signal = np.mean(cdata)
        noise = np.std(cdata)

        snr = 20 * np.log10(signal / noise)
        
        return signal / (2 * self.field.out_scale), phase, snr

class LDdecode:
    
    def __init__(self, fname_in, fname_out, freader, analog_audio = 0, digital_audio = False, system = 'NTSC', doDOD = True, threads=4, extra_options = {}):
        self.demodcache = None

        self.infile = open(fname_in, 'rb')
        self.freader = freader

        self.numthreads = threads

        self.fields_written = 0

        self.blackIRE = 0

        self.analog_audio = int(analog_audio * 1000)
        self.digital_audio = digital_audio

        self.has_analog_audio = True
        if system == 'PAL':
            if analog_audio == 0:
                self.has_analog_audio = False

        self.outfile_json = None

        self.lastvalidfield = {False: None, True: None}

        if fname_out is not None:        
            self.outfile_video = open(fname_out + '.tbc', 'wb')
            #self.outfile_json = open(fname_out + '.json', 'wb')
            self.outfile_audio = open(fname_out + '.pcm', 'wb') if self.analog_audio else None
            self.outfile_efm = open(fname_out + '.efm', 'wb') if self.digital_audio else None
        else:
            self.outfile_video = None
            self.outfile_audio = None
            self.outfile_efm = None

        if fname_out is not None and digital_audio:
            # feed EFM stream into ld-ldstoefm
            self.efm_pll = efm_pll.EFM_PLL()

        self.fname_out = fname_out

        self.firstfield = None # In frame output mode, the first field goes here
        self.fieldloc = 0

        self.internalerrors = 0 # exceptions seen

        # if option is missing, get returns None
            
        self.system = system
        self.rf = RFDecode(system=system, decode_analog_audio=analog_audio, decode_digital_audio=digital_audio, has_analog_audio = self.has_analog_audio, extra_options = extra_options)

        if system == 'PAL':
            self.FieldClass = FieldPAL
            self.readlen = self.rf.linelen * 400
            self.clvfps = 25
        else: # NTSC
            self.FieldClass = FieldNTSC
            self.readlen = ((self.rf.linelen * 350) // 16384) * 16384
            self.clvfps = 30

        self.blocksize = self.rf.blocklen

        self.output_lines = (self.rf.SysParams['frame_lines'] // 2) + 1
        
        self.bytes_per_frame = int(self.rf.freq_hz / self.rf.SysParams['FPS'])
        self.bytes_per_field = int(self.rf.freq_hz / (self.rf.SysParams['FPS'] * 2)) + 1
        self.outwidth = self.rf.SysParams['outlinelen']

        self.fdoffset = 0
        self.audio_offset = 0
        self.mtf_level = 1

        self.prevfield = None
        self.curfield = None

        self.doDOD = doDOD

        self.fieldinfo = []

        self.leadIn = False
        self.leadOut = False
        self.isCLV = False
        self.frameNumber = None

        self.autoMTF = True

        self.verboseVITS = False

        self.demodcache = DemodCache(self.rf, self.infile, self.freader, num_worker_threads=self.numthreads)

        self.bw_ratios = []

    def __del__(self):
        del self.demodcache
        
    def close(self):
        ''' deletes all open files, so it's possible to pickle an LDDecode object '''

        # use setattr to force file closure
        for outfiles in ['infile', 'outfile_video', 'outfile_audio', 'outfile_json', 'outfile_efm']:
            setattr(self, outfiles, None)

        self.demodcache.end()

    def roughseek(self, location, isField = True):
        self.prevPhaseID = None

        if isField:
            self.fdoffset = location * self.bytes_per_field
        else:
            self.fdoffset = location

    def checkMTF_calc(self, field):
        if not self.isCLV and self.frameNumber is not None:
            newmtf = 1 - (self.frameNumber / 10000) if self.frameNumber < 10000 else 0
            oldmtf = self.mtf_level
            self.mtf_level = newmtf

            if np.abs(newmtf - oldmtf) > .1: # redo field if too much adjustment
                #logging.info(newmtf, oldmtf, field.cavFrame)
                return False
            
        return True

    def checkMTF(self, field, pfield = None):
        if not self.autoMTF:
            return self.checkMTF_calc(field)

        oldmtf = self.mtf_level

        if (len(self.bw_ratios) == 0):
            return True

        # scale for NTSC - 1.1 to 1.55
        self.mtf_level = np.clip((np.mean(self.bw_ratios) - 1.08) / .38, 0, 1)

        return np.abs(self.mtf_level - oldmtf) < .05

    def detectLevels(self, field):
        # Returns sync level and ire0 level of a field, computed from serration pulses
            
        # Build a list of each half-line's average
        hlevels = []

        for l in range(1,8):
            lsa = field.lineslice(l, 10, 10)
            lsb = field.lineslice(l, 40, 10)
            
            hlevels.append(np.mean(field.data['video']['demod_05'][lsa]))
            hlevels.append(np.mean(field.data['video']['demod_05'][lsb]))

        # Now group them by level (either sync or ire 0) and return the means of those
        sync_hzs = []
        ire0_hzs = []

        for hz in hlevels:
            ire = field.rf.hztoire(hz)
            if ire < field.rf.SysParams['vsync_ire'] / 2:
                sync_hzs.append(hz)
            else:
                ire0_hzs.append(hz)

        return np.mean(sync_hzs), np.mean(ire0_hzs)

    def writeout(self, dataset):
        f, fi, picture, audio, efm = dataset

        fi['audioSamples'] = 0 if audio is None else int(len(audio) / 2)
        self.fieldinfo.append(fi)

        self.outfile_video.write(picture)
        self.fields_written += 1

        if audio is not None and self.outfile_audio is not None:
            self.outfile_audio.write(audio)

        if self.digital_audio == True:
            efm_out = self.efm_pll.process(efm)
            self.outfile_efm.write(efm_out.tobytes())
        else:
            efm = None
        
    def decodefield(self, initphase = False):
        ''' returns field object if valid, and the offset to the next decode '''
        self.readloc = int(self.fdoffset - self.rf.blockcut)
        if self.readloc < 0:
            self.readloc = 0

        self.readloc_block = self.readloc // self.blocksize
        self.numblocks = ((self.readlen + (self.readloc % self.blocksize)) // self.blocksize) + 1

        self.rawdecode = self.demodcache.read(self.readloc_block * self.blocksize, self.numblocks * self.blocksize, self.mtf_level)

        if self.rawdecode is None:
            logging.info("Failed to demodulate data")
            return None, None
        
        self.indata = self.rawdecode['input']

        f = self.FieldClass(self.rf, self.rawdecode, audio_offset = self.audio_offset, prevfield = self.curfield, initphase = initphase)
        try:
            f.process()
            self.curfield = f
        except Exception as e:
            # XXX: Get better diagnostics for this
            self.internalerrors.append(e)
            if len(self.internalerrors) == 3:
                logging.info("Three internal errors seen, aborting")
                return None, None

            logging.info("Internal error, jumping ahead")
            return None, self.rf.linelen * 200

        if not f.valid:
            logging.info("Bad data - jumping one second")
            return f, f.nextfieldoffset
            
        return f, f.nextfieldoffset - (self.readloc - self.rawdecode['startloc'])

    def readfield(self, initphase = False):
        # pretty much a retry-ing wrapper around decodefield with MTF checking
        self.prevfield = self.curfield
        done = False
        adjusted = False
        
        while done == False:
            self.fieldloc = self.fdoffset
            f, offset = self.decodefield(initphase = initphase)

            if f is None:                
                if offset is None:
                    # EOF, probably
                    return None
            
            self.curfield = f
            self.fdoffset += offset
            
            if f is not None and f.valid:
                picture, audio, efm = f.downscale(linesout = self.output_lines, final=True, audio=self.analog_audio)

                self.audio_offset = f.audio_next_offset

                metrics = self.computeMetrics(f, None, verbose=True)
                if 'blackToWhiteRFRatio' in metrics and adjusted == False:
                    keep = 900 if self.isCLV else 30
                    self.bw_ratios.append(metrics['blackToWhiteRFRatio'])
                    self.bw_ratios = self.bw_ratios[-keep:]

                    #logging.info(metrics['blackToWhiteRFRatio'], np.mean(self.bw_ratios))

                redo = False

                if not self.checkMTF(f, self.prevfield):
                    redo = True
                
                sync_hz, ire0_hz = self.detectLevels(f)
                sync_ire_diff = np.abs(self.rf.hztoire(sync_hz) - self.rf.SysParams['vsync_ire'])

                if (sync_ire_diff > 2) or (np.abs(self.rf.hztoire(ire0_hz)) > 2):
                    redo = True

                self.rf.SysParams['ire0'] = ire0_hz
                # Note that vsync_ire is a negative number, so (sync_hz - ire0_hz) is correct
                self.rf.SysParams['hz_ire'] = (sync_hz - ire0_hz) / self.rf.SysParams['vsync_ire']
                    
                if adjusted == False and redo == True:
                    self.demodcache.flushvideo()
                    adjusted = True
                    self.fdoffset -= offset
                else:
                    done = True

        if f is not None and self.fname_out is not None:
            # Only write a FirstField first
            if len(self.fieldinfo) == 0 and not f.isFirstField:
                return f

            # XXX: this routine currently performs a needed sanity check
            fi, needFiller = self.buildmetadata(f)

            self.lastvalidfield[f.isFirstField] = (f, fi, picture, audio, efm)

            if needFiller:
                if self.lastvalidfield[not f.isFirstField] is not None:
                    self.writeout(self.lastvalidfield[not f.isFirstField])
                    self.writeout(self.lastvalidfield[f.isFirstField])

                # If this is the first field to be written, don't write anything                
                return f

            self.writeout(self.lastvalidfield[f.isFirstField])
            
        return f

    def decodeFrameNumber(self, f1, f2):
        ''' decode frame #/information from Philips code data on both fields '''

        # CLV
        self.isCLV = False
        self.earlyCLV = False
        self.clvMinutes = None
        self.clvSeconds = None
        self.clvFrameNum = None

        def decodeBCD(bcd):
            """Read a BCD-encoded number.
            Raise ValueError if any of the digits aren't valid BCD."""

            if bcd == 0:
                return 0
            else:
                digit = bcd & 0xF
                if digit > 9:
                    raise ValueError("Non-decimal BCD digit")
                return (10 * decodeBCD(bcd >> 4)) + digit

        # With newer versions of the duplicator software, there may 
        # only be one *field* with leadout, so handle each field 
        # in turn. (issue #414)
        for i in [f1.linecode, f2.linecode]:
            leadoutCount = 0
            for v in i:
                if v is not None and v == 0x80eeee:
                    leadoutCount += 1

            if leadoutCount == 2:
                self.leadOut = True

        for l in f1.linecode + f2.linecode:
            if l is None:
                continue

            if l == 0x80eeee: # lead-out reached
                pass
            elif l == 0x88ffff: # lead-in
                self.leadIn = True
            elif (l & 0xf0dd00) == 0xf0dd00: # CLV minutes/hours
                try:
                    self.clvMinutes = decodeBCD(l & 0xff) + (decodeBCD((l >> 16) & 0xf) * 60)
                    self.isCLV = True
                    #logging.info('CLV', mins)
                except ValueError:
                    pass
            elif (l & 0xf00000) == 0xf00000: # CAV frame
                # Ignore the top bit of the first digit, used for PSC
                try:
                    return decodeBCD(l & 0x7ffff)
                except ValueError:
                    pass
            elif (l & 0x80f000) == 0x80e000: # CLV picture #
                try:
                    sec1s = decodeBCD((l >> 8) & 0xf)
                    sec10s = ((l >> 16) & 0xf) - 0xa
                    if sec10s < 0:
                        raise ValueError("Digit 2 not in range A-F")

                    self.clvFrameNum = decodeBCD(l & 0xff)
                    self.clvSeconds = sec1s + (10 * sec10s)
                    self.isCLV = True
                except ValueError:
                    pass

            if self.clvMinutes is not None:
                if self.clvSeconds is not None: # newer CLV
                    return (((self.clvMinutes * 60) + self.clvSeconds) * self.clvfps) + self.clvFrameNum
                else:
                    self.earlyCLV = True
                    return (self.clvMinutes * 60)

        return None #seeking won't work w/minutes only

    def calcsnr(self, f, snrslice):
        data = f.output_to_ire(f.dspicture[snrslice])
        
        signal = np.mean(data)
        noise = np.std(data)

        return 20 * np.log10(signal / noise)

    def calcpsnr(self, f, snrslice):
        # if dspicture isn't converted to float, this underflows at -40IRE
        data = f.output_to_ire(f.dspicture[snrslice].astype(float))
        
        noise = np.std(data)

        return 20 * np.log10(100 / noise)

    def computeMetricsPAL(self, metrics, f, fp = None):
        
        if f.isFirstField:
            # compute IRE50 from field1 l13
            # Unforunately this is too short to get a 50IRE RF level
            wl_slice = f.lineslice_tbc(13, 4.7+15.5, 3)
            metrics['greyPSNR'] = self.calcpsnr(f, wl_slice)
            metrics['greyIRE'] = np.mean(f.output_to_ire(f.dspicture[wl_slice]))
        else:
            # There's a nice long burst at 50IRE block on field2 l13
            b50slice = f.lineslice_tbc(13, 36, 20)
            metrics['palVITSBurst50Level'] = rms(f.dspicture[b50slice]) / f.out_scale

        return metrics    

    def computeMetricsNTSC(self, metrics, f, fp = None):
        # check for a white flag - only on earlier discs, and only on first "frame" fields
        wf_slice = f.lineslice_tbc(11, 15, 40)
        if inrange(np.mean(f.output_to_ire(f.dspicture[wf_slice])), 92, 108):
            metrics['ntscWhiteFlagSNR'] = self.calcpsnr(f, wf_slice)

        # use line 19 to determine 0 and 70 IRE burst levels for MTF compensation later
        c = CombNTSC(f)

        level, phase, snr = c.calcLine19Info()
        if level is not None:
            metrics['ntscLine19ColorPhase'] = phase
            metrics['ntscLine19ColorRawSNR'] = snr

        ire50_slice = f.lineslice_tbc(19, 36, 10)
        metrics['greyPSNR'] = self.calcpsnr(f, ire50_slice)
        metrics['greyIRE'] = np.mean(f.output_to_ire(f.dspicture[ire50_slice]))

        ire50_rawslice = f.lineslice(19, 36, 10)
        rawdata = f.rawdata[ire50_rawslice.start - int(self.rf.delays['video_white']):ire50_rawslice.stop - int(self.rf.delays['video_white'])]
        metrics['greyRFLevel'] = np.std(rawdata)
        
        if not f.isFirstField and fp is not None:
            cp = CombNTSC(fp)
            
            level3d, phase3d, snr3d = c.calcLine19Info(cp)
            if level3d is not None:
                metrics['ntscLine19Burst70IRE'] = level3d
                metrics['ntscLine19Color3DRawSNR'] = snr3d

                sl_cburst = f.lineslice_tbc(19, 4.7+.8, 2.4)
                diff = (f.dspicture[sl_cburst].astype(float) - fp.dspicture[sl_cburst].astype(float))/2

                metrics['ntscLine19Burst0IRE'] = np.sqrt(2)*rms(diff)/f.out_scale

        return metrics    

    def computeMetrics(self, f, fp = None, verbose = False):
        if not self.curfield:
            raise ValueError("No decoded field to work with")

        system = f.rf.system
        if self.verboseVITS:
            verbose = True
            
        metrics = {}

        if system == 'NTSC':
            self.computeMetricsNTSC(metrics, f, fp)
            whitelocs = [(20, 14, 12), (20, 52, 8), (13, 13, 15)]#, (20, 13, 2)]
        else:
            self.computeMetricsPAL(metrics, f, fp)
            whitelocs = [(19, 12, 8)]
        
        for l in whitelocs:
            wl_slice = f.lineslice_tbc(*l)
            #logging.info(l, np.mean(f.output_to_ire(f.dspicture[wl_slice])))
            if inrange(np.mean(f.output_to_ire(f.dspicture[wl_slice])), 90, 110):
                metrics['wSNR'] = self.calcpsnr(f, wl_slice)
                metrics['whiteIRE'] = np.mean(f.output_to_ire(f.dspicture[wl_slice]))

                rawslice = f.lineslice(*l)
                rawdata = f.rawdata[rawslice.start - int(self.rf.delays['video_white']):rawslice.stop - int(self.rf.delays['video_white'])]
                metrics['whiteRFLevel'] = np.std(rawdata)

                break
        
        if system == 'PAL':
            # these metrics handle various easily detectable differences between fields
            bl_slice = f.lineslice(22, 12, 50)
            bl_slicetbc = f.lineslice_tbc(22, 12, 50)
        else: # NTSC
            bl_slice = f.lineslice(1, 10, 20)
            bl_slicetbc = f.lineslice_tbc(1, 10, 20)            

        delay = int(f.rf.delays['video_sync'])
        bl_sliceraw = slice(bl_slice.start - delay, bl_slice.stop - delay)
        metrics['blackLineRFLevel'] = np.std(f.rawdata[bl_sliceraw])

        metrics['blackLinePreTBCIRE'] = f.rf.hztoire(np.mean(f.data['video']['demod'][bl_slice]))
        metrics['blackLinePostTBCIRE'] = f.output_to_ire(np.mean(f.dspicture[bl_slicetbc]))

        metrics['bPSNR'] = self.calcpsnr(f, bl_slicetbc)

        if 'whiteRFLevel' in metrics:
            #metrics['syncToWhiteRFRatio'] = metrics['syncRFLevel'] / metrics['whiteRFLevel']
            metrics['blackToWhiteRFRatio'] = metrics['blackLineRFLevel'] / metrics['whiteRFLevel']

        outputkeys = metrics.keys() if verbose else ['wSNR', 'bPSNR']

        metrics_rounded = {}

        for k in outputkeys:
            if k not in metrics:
                continue

            if 'Ratio' in k:
                digits = 4
            elif 'Burst' in k:
                digits = 3
            else:
                digits = 1
            rounded = roundfloat(metrics[k], places=digits)
            if np.isfinite(rounded):
                metrics_rounded[k] = rounded

        return metrics_rounded

    def buildmetadata(self, f):
        ''' returns field information JSON and whether or not a backfill field is needed '''
        prevfi = self.fieldinfo[-1] if len(self.fieldinfo) else None

        fi = {'isFirstField': True if f.isFirstField else False, 
              'syncConf': f.compute_syncconf(), 
              'seqNo': len(self.fieldinfo) + 1, 
              #'audioSamples': 0 if audio is None else int(len(audio) / 2),
              'diskLoc': np.round((self.fieldloc / self.bytes_per_field) * 10) / 10,
              'fileLoc': np.floor(self.fieldloc),
              'medianBurstIRE': roundfloat(f.burstmedian)}

        if self.doDOD:
            dropout_lines, dropout_starts, dropout_ends = f.dropout_detect()
            if len(dropout_lines):
                fi['dropOuts'] = {'fieldLine': dropout_lines, 'startx': dropout_starts, 'endx': dropout_ends}

        # This is a bitmap, not a counter
        decodeFaults = 0

        if f.rf.system == 'NTSC':
            fi['fieldPhaseID'] = f.fieldPhaseID

            if prevfi:
                if not ((fi['fieldPhaseID'] == 1 and prevfi['fieldPhaseID'] == 4) or
                        (fi['fieldPhaseID'] == prevfi['fieldPhaseID'] + 1)):
                    logging.warning('NTSC field phaseID sequence mismatch (player may be paused)')
                    decodeFaults |= 2

        if prevfi is not None and prevfi['isFirstField'] == fi['isFirstField']:
            #logging.info('WARNING!  isFirstField stuck between fields')
            if inrange(fi['diskLoc'] - prevfi['diskLoc'], .95, 1.05):
                decodeFaults |= 1
                fi['isFirstField'] = not prevfi['isFirstField']
                fi['syncConf'] = 10
            else:
                logging.error('Skipped field')
                decodeFaults |= 4
                fi['syncConf'] = 0
                return fi, True

        fi['decodeFaults'] = decodeFaults
        fi['vitsMetrics'] = self.computeMetrics(self.curfield, self.prevfield)

        fi['vbi'] = {'vbiData': [int(lc) for lc in f.linecode if lc is not None]}

        self.frameNumber = None
        if f.isFirstField:
            self.firstfield = f
        else:
            # use a stored first field, in case we start with a second field
            if self.firstfield is not None:
                # process VBI frame info data
                self.frameNumber = self.decodeFrameNumber(self.firstfield, f)

                rawloc = np.floor((self.readloc / self.bytes_per_field) / 2)

                try:
                    if self.isCLV and self.earlyCLV: # early CLV
                        print("file frame %d early-CLV minute %d" % (rawloc, self.clvMinutes), file=sys.stderr)
                    elif self.isCLV and self.frameNumber is not None:
                        print("file frame %d CLV timecode %d:%.2d.%.2d frame %d" % (rawloc, self.clvMinutes, self.clvSeconds, self.clvFrameNum, self.frameNumber), file=sys.stderr)
                    elif self.frameNumber:
                        print("file frame %d CAV frame %d" % (rawloc, self.frameNumber), file=sys.stderr)
                    elif self.leadIn:
                        print("file frame %d lead in" % (rawloc), file=sys.stderr)
                    elif self.leadOut:
                        print("file frame %d lead out" % (rawloc), file=sys.stderr)
                    else:
                        print("file frame %d unknown" % (rawloc), file=sys.stderr)
                    sys.stderr.flush()

                    if self.frameNumber is not None:
                        fi['frameNumber'] = int(self.frameNumber)

                    if self.verboseVITS and self.isCLV and self.clvMinutes is not None:
                        fi['clvMinutes'] = int(self.clvMinutes)
                        if self.earlyCLV == False:
                            fi['clvSeconds'] = int(self.clvSeconds)
                            fi['clvFrameNr'] = int(self.clvFrameNum)
                except:
                    logging.warning("file frame %d : VBI decoding error", rawloc)

        return fi, False

    # seek support function
    def seek_getframenr(self, start):
        self.roughseek(start)

        for fields in range(10):
            self.fieldloc = self.fdoffset
            f, offset = self.decodefield(initphase = True)

            self.prevfield = self.curfield
            self.curfield = f
            self.fdoffset += offset

            if self.prevfield is not None and f is not None and f.valid:
                fnum = self.decodeFrameNumber(self.prevfield, self.curfield)

                if self.earlyCLV:
                    logging.error("Cannot seek in early CLV disks w/o timecode")
                    return None
                elif fnum is not None:
                    rawloc = np.floor((self.readloc / self.bytes_per_field) / 2)
                    logging.info('seeking: file loc %d frame # %d', rawloc, fnum)
                    return fnum
        
        return False
        
    def seek(self, start, target):
        cur = start * 2
        
        logging.info("Beginning seek")

        if not sys.warnoptions:
            import warnings
            warnings.simplefilter("ignore")

        for retries in range(3):
            fnr = self.seek_getframenr(cur)
            if fnr is None:
                return None

            cur = int((self.fieldloc / self.bytes_per_field))
            if fnr == target:
                logging.info("Finished seek")
                print("Finished seeking, starting at frame", fnr, file=sys.stderr)
                self.roughseek(cur)
                return cur

            cur += ((target - fnr) * 2) - 1

        return None

    def build_json(self, f):
        ''' build up the JSON structure for file output. '''
        jout = {}
        jout['pcmAudioParameters'] = {'bits':16, 'isLittleEndian': True, 'isSigned': True, 'sampleRate': self.analog_audio}

        vp = {}

        vp['numberOfSequentialFields'] = len(self.fieldinfo)
        
        vp['isSourcePal'] = True if f.rf.system == 'PAL' else False

        vp['fsc'] = int(f.rf.SysParams['fsc_mhz'] * 1000000)
        vp['fieldWidth'] = f.rf.SysParams['outlinelen']
        vp['sampleRate'] = vp['fsc'] * 4
        spu = vp['sampleRate'] / 1000000

        vp['black16bIre'] = np.float(f.hz_to_output(f.rf.iretohz(self.blackIRE)))
        vp['white16bIre'] = np.float(f.hz_to_output(f.rf.iretohz(100)))

        vp['fieldHeight'] = f.outlinecount

        badj = -1.4 # current burst adjustment as of 2/27/19, update when #158 is fixed!
        vp['colourBurstStart'] = np.round((f.rf.SysParams['colorBurstUS'][0] * spu) + badj)
        vp['colourBurstEnd'] = np.round((f.rf.SysParams['colorBurstUS'][1] * spu) + badj)
        vp['activeVideoStart'] = np.round((f.rf.SysParams['activeVideoUS'][0] * spu) + badj)
        vp['activeVideoEnd'] = np.round((f.rf.SysParams['activeVideoUS'][1] * spu) + badj)

        jout['videoParameters'] = vp
        
        jout['fields'] = self.fieldinfo.copy()

        return jout
