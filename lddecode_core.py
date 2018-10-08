from base64 import b64encode
import copy
from datetime import datetime
import getopt
import io
from io import BytesIO
import os
import sys

# standard numeric/scientific libraries
import numpy as np
import pandas as pd
import scipy as sp
import scipy.signal as sps
import scipy.fftpack as fftpack 

#internal libraries which may or may not get used
import fdls
from lddutils import *

def calclinelen(SP, mult, mhz):
    if type(mhz) == str:
        mhz = SP[mhz]
        
    return int(np.round(SP['line_period'] * mhz * mult)) 

# These are invariant parameters 
SysParams_NTSC = {
    'fsc_mhz': (315.0 / 88.0),
    'pilot_mhz': (315.0 / 88.0),
    'frame_lines': 525,

    'ire0': 8100000,
    'hz_ire': 1700000 / 140.0,

    # From the spec - audio frequencies are multiples of the (color) line rate
    'audio_lfreq': (1000000*315/88/227.5) * 146.25,
    'audio_rfreq': (1000000*315/88/227.5) * 178.75,
    
    'philips_codelines': [16, 17, 18]
}

# In color NTSC, the line period was changed from 63.5 to 227.5 color cycles,
# which works out to 63.5(with a bar on top) usec
SysParams_NTSC['line_period'] = 1/(SysParams_NTSC['fsc_mhz']/227.5)
SysParams_NTSC['FPS'] = 1000000/ (525 * SysParams_NTSC['line_period']) # ~29.976

# XXX: more a decoder/tbc parameter, but 4X FSC is a standard that makes comb filters easy
SysParams_NTSC['outlinelen'] = calclinelen(SysParams_NTSC, 4, 'fsc_mhz')

SysParams_PAL = {
    'FPS': 25,
    
    'fsc_mhz': ((1/64) * 283.75) + (25/1000000),
    'pilot_mhz': 3.75,
    'frame_lines': 625,
    'line_period': 64,

    'ire0': 7100000,
    'hz_ire': 800000 / 100.0,

    # From the spec - audio frequencies are multiples of the (color) line rate
    'audio_lfreq': (1000000/64) * 43.75,
    'audio_rfreq': (1000000/64) * 68.25,

    'philips_codelines': [19, 20, 21]
}

# XXX: even moreso, this is a decoder parameter
SysParams_PAL['outlinelen'] = calclinelen(SysParams_PAL, 4, 'fsc_mhz')
SysParams_PAL['outlinelen_pilot'] = calclinelen(SysParams_PAL, 4, 'pilot_mhz')

SysParams_PAL['vsync_ire'] = .3 * (100 / .7)

RFParams_NTSC = {
    # The audio notch filters are important with DD v3.0+ boards
    'audio_notchwidth': 350000,
    'audio_notchorder': 2,

    # (note:  i don't know how to handle these values perfectly yet!)
    'video_deemp': (120*.32, 320*.32), # On some captures this is as low as .55.

    # This BPF is similar but not *quite* identical to what Pioneer did
    'video_bpf': [3500000, 13200000],
    'video_bpf_order': 3,

    # This can easily be pushed up to 4.5mhz or even a bit higher. 
    # A sharp 4.8-5.0 is probably the maximum before the audio carriers bleed into 0IRE.
    'video_lpf_freq': 4200000,   # in mhz
    'video_lpf_order': 5 # butterworth filter order
}

RFParams_PAL = {
    # The audio notch filters are important with DD v3.0+ boards
    'audio_notchwidth': 200000,
    'audio_notchorder': 2,

    'video_deemp': (100*.32, 400*.32),

    # XXX: guessing here!
    'video_bpf': (2600000, 12500000),
    'video_bpf_order': 3,

    'video_lpf_freq': 4800000,
    'video_lpf_order': 5,
    
}

class RFDecode:
    """ RF decoding phase.
    This uses FFT-based overlapping/clipping to do filtering (TODO: try overlap-add?) - this should support
    GPU acceleration when someone/I gets along to it.
    
    Dataflow:
    
    all: Incoming Data -> FFT
    
    video path: inFFT -> video-frequency BPF[/optional analog audio filters] -> hilbert transform -> demod-FFT
        demod-FFT -> low-pass-filters -> video/0.5mhz/burst/[PAL only pilot]
        
    audio path (optional): inFFT -> split into L/R -> bandpass filters -> L/R stage 1
        Stage 2 then decimates further (4X) and applies low pass filters.
        
    """
    def __init__(self, inputfreq = 40, system = 'NTSC', blocklen = 16384, blockcut = 1024, decode_analog_audio = True, has_analog_audio = True):
        """The constructor - sets up demodulation parameters and sets up (initial) filters.
        
        Keyword arguments:
        inputfreq = frequency in Msps.  (NOTE: only tested with 40Msps at this time)
        system = video system (string, 'NTSC' or 'PAL')
        blocklen = FFT blocklen.  16384/16K seems ideal for software FFT.  GPU FFT should probably be larger
        blockcut = FFT block cut (default 1024 can be smaller if analog audio decoding is not done)
        decode_analog_audio = enable analog audio decoding
        has_analog_audio = set to False for NTSC/CD-V and digital sound PAL disks.
        """
        self.blocklen = blocklen
        self.blockcut = blockcut 
        self.system = system
        
        freq = inputfreq
        self.freq = freq
        self.freq_half = freq / 2
        self.freq_hz = self.freq * 1000000
        self.freq_hz_half = self.freq * 1000000 / 2
        
        if system == 'NTSC':
            self.SysParams = SysParams_NTSC.copy()
            self.DecoderParams = RFParams_NTSC
            
            self.Filters = {
                # The MTF filters were determined emprically and can probably be improved
                'MTF': sps.zpk2tf([], [polar2z(.7,np.pi*12.5/20), polar2z(.7,np.pi*27.5/20)], 1.11)
            }
        elif system == 'PAL':
            self.SysParams = SysParams_PAL.copy()
            self.DecoderParams = RFParams_PAL
            
            self.Filters = {
                # PAL disks spin at a lower rate, so the MTF compenstation is steeper
                'MTF': sps.zpk2tf([], [polar2z(.7,np.pi*10/20), polar2z(.7,np.pi*28/20)], 1.11)
            }
            
        self.SysParams['analog_audio'] = has_analog_audio

        # Compute the input line length
        linelen = self.freq_hz/(1000000.0/self.SysParams['line_period'])
        self.linelen = int(np.round(linelen)) # TODO: search+replace to inlinelen
        self.inlinelen = int(np.round(linelen))
        
        self.analog_audio = decode_analog_audio
            
        self.computevideofilters()
        if self.analog_audio: 
            self.computeaudiofilters()
            
    def computevideofilters(self):
        """ Computes the FFT filters used for processing video.
        """
        self.Filters = {}
        
        # Use some shorthand to compact the code.  good idea?  prolly not.
        SF = self.Filters
        SP = self.SysParams
        DP = self.DecoderParams
        
        SF['hilbert'] = np.fft.fft(hilbert_filter, self.blocklen)
        
        filt_rfvideo = sps.butter(DP['video_bpf_order'], [DP['video_bpf'][0]/self.freq_hz_half, DP['video_bpf'][1]/self.freq_hz_half], btype='bandpass')
        SF['RFVideo'] = filtfft(filt_rfvideo, self.blocklen)

        if self.SysParams['analog_audio']: 
            cut_left = sps.butter(DP['audio_notchorder'], [(SP['audio_lfreq'] - DP['audio_notchwidth'])/self.freq_hz_half, (SP['audio_lfreq'] + DP['audio_notchwidth'])/self.freq_hz_half], btype='bandstop')
            SF['Fcutl'] = filtfft(cut_left, self.blocklen)
            cut_right = sps.butter(DP['audio_notchorder'], [(SP['audio_rfreq'] - DP['audio_notchwidth'])/self.freq_hz_half, (SP['audio_rfreq'] + DP['audio_notchwidth'])/self.freq_hz_half], btype='bandstop')
            SF['Fcutr'] = filtfft(cut_right, self.blocklen)
        
            SF['RFVideo'] *= (SF['Fcutl'] * SF['Fcutr'])
            
        SF['RFVideo'] *= SF['hilbert']
        
        video_lpf = sps.butter(DP['video_lpf_order'], DP['video_lpf_freq']/self.freq_hz_half, 'low')
        SF['Fvideo_lpf'] = filtfft(video_lpf, self.blocklen)

        # The deemphasis filter.  This math is probably still quite wrong, but with the right values it works
        deemp0, deemp1 = DP['video_deemp']
        [tf_b, tf_a] = sps.zpk2tf(-deemp1*(10**-10), -deemp0*(10**-10), deemp0 / deemp1)
        SF['Fdeemp'] = filtfft(sps.bilinear(tf_b, tf_a, 1.0/self.freq_hz_half), self.blocklen)

        # The direct opposite of the above, used in test signal generation
        [tf_b, tf_a] = sps.zpk2tf(-deemp0*(10**-10), -deemp1*(10**-10), deemp1 / deemp0)
        SF['Femp'] = filtfft(sps.bilinear(tf_b, tf_a, 1.0/self.freq_hz_half), self.blocklen)
        
        # Post processing:  lowpass filter + deemp
        SF['FVideo'] = SF['Fvideo_lpf'] * SF['Fdeemp'] 
    
        # additional filters:  0.5mhz and color burst
        # Using an FIR filter here to get tighter alignment
        F0_5 = sps.firwin(65, [0.5/self.freq_half], pass_zero=True)
        SF['F0_5'] = filtfft((F0_5, [1.0]), self.blocklen)
        SF['FVideo05'] = SF['Fvideo_lpf'] * SF['Fdeemp']  * SF['F0_5']

        SF['Fburst'] = filtfft(sps.butter(1, [(SP['fsc_mhz']-.1)/self.freq_half, (SP['fsc_mhz']+.1)/self.freq_half], btype='bandpass'), self.blocklen) 
        SF['FVideoBurst'] = SF['Fvideo_lpf'] * SF['Fdeemp']  * SF['Fburst']

        if self.system == 'PAL':
            SF['Fpilot'] = filtfft(sps.butter(1, [3.7/self.freq_half, 3.8/self.freq_half], btype='bandpass'), self.blocklen) 
            SF['FVideoPilot'] = SF['Fvideo_lpf'] * SF['Fdeemp']  * SF['Fpilot']
        
        # emperical work determined that a single-pole low frequency filter effectively 
        # detects the end of a (regular) sync pulse when binary level detection is used. TODO: test with PAL
        f = sps.butter(1, 0.05/self.freq_half, btype='low')
        SF['FPsync'] = filtfft(f, self.blocklen)

    # frequency domain slicers.  first and second stages use different ones...
    def audio_fdslice(self, freqdomain):
        """ stage 1 frequency-domain decimation. """
        return np.concatenate([freqdomain[self.Filters['audio_fdslice_lo']], freqdomain[self.Filters['audio_fdslice_hi']]])

    def audio_fdslice2(self, freqdomain):
        """ stage 1 frequency-domain decimation. """
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
            
        SF['audio_fdiv1'] = audio_fdiv1
            
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

        apass = 150000 # audio RF bandpass.  150khz is the maximum transient.
        afilt_len = 800 # good for 150khz apass

        afilt_left = filtfft([sps.firwin(afilt_len, [(SP['audio_lfreq']-apass)/self.freq_hz_half, (SP['audio_lfreq']+apass)/self.freq_hz_half], pass_zero=False), 1.0], self.blocklen)
        SF['audio_lfilt'] = self.audio_fdslice(afilt_left * SF['hilbert']) 
        afilt_right = filtfft([sps.firwin(afilt_len, [(SP['audio_rfreq']-apass)/self.freq_hz_half, (SP['audio_rfreq']+apass)/self.freq_hz_half], pass_zero=False), 1.0], self.blocklen)
        SF['audio_rfilt'] = self.audio_fdslice(afilt_right * SF['hilbert'])

        # second stage audio filters (decimates further, and applies audio LPF)
        audio_fdiv2 = 4
        SF['audio_fdiv2'] = audio_fdiv2
        SF['audio_fdiv'] = audio_fdiv1 * audio_fdiv2
        SF['freq_aud2'] = SF['freq_arf'] / audio_fdiv2

        # slice areas for reduced FFT audio filters
        SF['audio_fdslice2_lo'] = slice(0, self.blocklen//(audio_fdiv2*2))
        SF['audio_fdslice2_hi'] = slice(self.blocklen-self.blocklen//(audio_fdiv2*2), self.blocklen)

        SF['audio_lpf2'] = filtfft([sps.firwin(65, [21000/(SF['freq_aud2']/2)]), [1.0]], self.blocklen // SF['audio_fdiv2'])

        # convert 75usec into the exact -3dB frequency
        d75freq = 1000000/(2*pi*75)

        # I was overthinking deemphasis for a while.  For audio it turns out a straight
        # 1-pole butterworth does a good job.
        adeemp_b, adeemp_a = sps.butter(1, [d75freq/(SF['freq_aud2']/2)], btype='lowpass')
        SF['audio_deemp2'] = filtfft([adeemp_b, adeemp_a],  self.blocklen // SF['audio_fdiv2'])
        
    def iretohz(self, ire):
        """ converts IRE (0 black, 100 white) to LD frequency per System Parameters.
        
        PAL does not use IRE, but rather 0v for SYNC, 0.3v for black, and 1.0v for white - but ld-decode does anyway...
        """
        return self.SysParams['ire0'] + (self.SysParams['hz_ire'] * ire)

    def hztoire(self, hz):
        """ Converts video HZ to IRE.  """
        return (hz - self.SysParams['ire0']) / self.SysParams['hz_ire']
    
    def demodblock(self, data, mtf_level = 0):
        """ The core stage 1 demodulation function
        
        Parameters:
        data: an array containing unfiltered RF data
        mtf_level:  the amount of MTF compensation needed.  (typically between 0 and 0.5)
        
        Output format:  A tuple with two members:
            video:  A numpy rec.array with channels for pure demod, 0.5mhz LPF, burst/pilot BPF, and a sync filter
            audio:  Left and right stage 1 channels
            
        All output is in Laserdisc RF frequencies to be downconverted later.  This allows processing for wow(/flutter)
        once the TBC works out the disk speed.
        """
        indata_fft = np.fft.fft(data[:self.blocklen])
        indata_fft_filt = indata_fft * self.Filters['RFVideo']

        if mtf_level != 0:
            indata_fft_filt *= self.Filters['MTF'] ** mtf_level

        hilbert = np.fft.ifft(indata_fft_filt)
        demod = unwrap_hilbert(hilbert, self.freq_hz)

        demod_fft = np.fft.fft(demod)

        out_video = np.fft.ifft(demod_fft * self.Filters['FVideo']).real
        out_video05 = np.fft.ifft(demod_fft * self.Filters['FVideo05']).real
        #out_videoburst = np.fft.ifft(demod_fft * self.Filters['FVideoBurst']).real
        
        # NTSC: filtering for vsync pulses from -55 to -25ire seems to work well even on rotted disks
        output_sync = inrange(out_video05, self.iretohz(-55), self.iretohz(-25))
        # Perform FFT convolution of above filter
        output_syncf = np.fft.ifft(np.fft.fft(output_sync) * self.Filters['FPsync']).real

        if False: #self.system == 'PAL':
            # PAL format includes a pilot signal. At some point NTSC color burst may be called pilot, since
            # PAL's burst is not really used.
            out_videopilot = np.fft.ifft(demod_fft * self.Filters['FVideoPilot']).real
            rv_video = np.rec.array([out_video, out_video05, output_syncf, out_videoburst, out_videopilot], names=['demod', 'demod_05', 'demod_sync', 'demod_burst', 'demod_pilot'])
        else:
            #rv_video = np.rec.array([out_video, out_video05, output_syncf, out_videoburst], names=['demod', 'demod_05', 'demod_sync', 'demod_burst'])
            rv_video = np.rec.array([out_video, out_video05, output_syncf], names=['demod', 'demod_05', 'demod_sync'])

        if self.analog_audio == False:
            return rv_video, None

        # Audio phase 1
        hilbert = np.fft.ifft(self.audio_fdslice(indata_fft) * self.Filters['audio_lfilt'])
        audio_left = unwrap_hilbert(hilbert, self.Filters['freq_arf']) + self.Filters['audio_lowfreq']

        hilbert = np.fft.ifft(self.audio_fdslice(indata_fft) * self.Filters['audio_rfilt'])
        audio_right = unwrap_hilbert(hilbert, self.Filters['freq_arf']) + self.Filters['audio_lowfreq']

        rv_audio = np.rec.array([audio_left, audio_right], names=['audio_left', 'audio_right'])

        return rv_video, rv_audio
    
    # Second phase audio filtering.  This works on a whole field's samples, since 
    # the frequency is reduced by 16/32x.

    def runfilter_audio_phase2(self, frame_audio, start):
        """ runs second stage filtering.  FIXME: this duplicates code for L/R. """
        left = frame_audio['audio_left'][start:start+self.blocklen].copy() 
        left_fft = np.fft.fft(left)
        audio_out_fft = self.audio_fdslice2(left_fft) * self.Filters['audio_lpf2']
        left_out = np.fft.ifft(audio_out_fft).real / self.Filters['audio_fdiv2']

        right = frame_audio['audio_right'][start:start+self.blocklen].copy() 
        right_fft = np.fft.fft(right)
        audio_out_fft = self.audio_fdslice2(right_fft) * self.Filters['audio_lpf2'] #* adeemp
        right_out = np.fft.ifft(audio_out_fft).real / self.Filters['audio_fdiv2']

        return np.rec.array([left_out, right_out], names=['audio_left', 'audio_right'])

    def audio_phase2(self, field_audio):
        """ The second phase audio filtering, which produces a ~200khz signal used for final downscaling """
        # this creates an output array with left/right channels.
        output_audio2 = np.zeros(len(field_audio['audio_left']) // self.Filters['audio_fdiv2'], dtype=field_audio.dtype)

        # copy the first block in it's entirety, to keep audio and video samples aligned
        tmp = self.runfilter_audio_phase2(field_audio, 0)
        output_audio2[:tmp.shape[0]] = tmp

        end = field_audio.shape[0] #// filterset['audio_fdiv2']

        askip = 64 # length of filters that needs to be chopped out of the ifft
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

    def demod(self, infile, start, length):
        end = int(start + length) + 1

        if (start > self.blockcut):
            start = int(start - self.blockcut)
        else:
            start = 0 # should this be an error?  prolly.

        # set a placeholder
        output = None
        output_audio = None

        for i in range(start, end, self.blocklen - self.blockcut):
            indata = loader(infile, i, self.blocklen)
            if indata is None:
                break

            tmp_video, tmp_audio = self.demodblock(indata)

            # if the output hasn't been created yet, do it now using the 
            # data types returned by dodemod (should be faster than multiple
            # allocations...)
            if output is None:
                output = np.zeros(end - start + 1, dtype=tmp_video.dtype)

            if i - start + (self.blocklen - self.blockcut) > len(output):
                copylen = len(output) - (i - start)
            else:
                copylen = self.blocklen - self.blockcut

            output_slice = slice(i - start, i - start + copylen)
            tmp_slice = slice(self.blockcut, self.blockcut + copylen)

            output[output_slice] = tmp_video[tmp_slice]

            # repeat the above - but for audio
            if tmp_audio is not None:
                audio_downscale = tmp_video.shape[0] // tmp_audio.shape[0]

                if output_audio is None:
                    output_audio = np.zeros(((end - start) // audio_downscale) + 1, dtype=tmp_audio.dtype)

                output_slice = slice((i - start) // audio_downscale, (i - start + copylen) // audio_downscale)
                tmp_slice = slice(self.blockcut // audio_downscale, (self.blockcut + copylen) // audio_downscale)

                output_audio[output_slice] = tmp_audio[tmp_slice]

        if tmp_audio is not None:
            return output, self.audio_phase2(output_audio)
        else:
            return output, None

# right now defualt is 16/48, so not optimal :)
def downscale_audio(audio, lineinfo, rf, linecount, timeoffset = 0, freq = 48000.0, scale=64):
    frametime = (rf.SysParams['line_period'] * linecount) / 1000000 
    soundgap = 1 / freq

#    lineinfo = lineinfo.copy()
    
#    while (len(lineinfo) < linecount + 5):
#        lineinfo.append(lineinfo[-1] + (lineinfo[-1] - lineinfo[-2]))

    print('audio ', linecount, len(lineinfo))
    
    # include one extra 'tick' to interpolate the last one and use as a return value
    # for the next frame
    arange = np.arange(timeoffset, frametime + soundgap, soundgap, dtype=np.double)
    locs = np.zeros(len(arange), dtype=np.float)
    swow = np.zeros(len(arange), dtype=np.float)
    
    lineloc = ((arange[-1] * 1000000) / rf.SysParams['line_period']) + 1    
    print('a ', lineloc)
    
    for i, t in enumerate(arange):
        lineloc = ((t * 1000000) / rf.SysParams['line_period']) + 1

        sampleloc = lineinfo[np.int(lineloc)]
        sampleloc += (lineinfo[np.int(lineloc) + 1] - lineinfo[np.int(lineloc)]) * (lineloc - np.floor(lineloc))

        swow[i] = ((lineinfo[int(lineloc) + 1] - lineinfo[int(lineloc)]) / rf.linelen)
        locs[i] = sampleloc / scale
        
        if False:        
            wowratio = 1 - (lineloc - np.floor(lineloc))
            wow = (lineinfo[l + 1] - lineinfo[l]) / rf.linelen
            swow[i] = wow[np.int(lineloc)] * (1 - wowratio)
            swow[i] += wow[np.int(lineloc + 1 )] * (wowratio)

            locs[i] = sampleloc / scale

    output = np.zeros((2 * (len(arange) - 1)), dtype=np.int32)
    output16 = np.zeros((2 * (len(arange) - 1)), dtype=np.int16)

    # FIXME: use the same Python routine used for video line scaling?  This proabably adds some jitter.
    # use two passes so the next location can be known
    for i in range(len(arange) - 1):    
        # rough linear approx for now
        output_left = audio['audio_left'][np.int(locs[i])]
        output_right = audio['audio_right'][np.int(locs[i])]

        output_left *= swow[i]
        output_right *= swow[i]
        
        output_left -= rf.SysParams['audio_lfreq']
        output_right -= rf.SysParams['audio_rfreq']
        
        output[(i * 2) + 0] = int(np.round(output_left * 32767 / 150000))
        output[(i * 2) + 1] = int(np.round(output_right * 32767 / 150000))
        
    np.clip(output, -32766, 32766, out=output16)
            
    return output16, arange[-1] - frametime

#audb, offset, arange, locs = downscale_audio(fields[0].rawdecode[1], fields[0].linelocs, rfd, 262)

class Field:
    """ Common code for NTSC/PAL field-level TBC. """

    def usectoinpx(self, x):
        return x * self.rf.freq
    
    def inpxtousec(self, x):
        return x / self.rf.freq
    
    def get_syncpeaks(self):
        # This is done as a while loop so each peak lookup is aligned to the previous one
        ds = self.data[0]['demod_sync']

        peaklist = []

        i = self.start
        while i < (len(ds) - (self.inlinelen * 2)):
            peakloc = np.argmax(ds[i:i + (self.inlinelen//2)])
            peak = ds[i + peakloc]

            if peak > .2:
                # TODO: validity check for lack of rot goes here?

                # TODO: Work out adjustments for NTSC and PAL automagically
                lineloc = i + peakloc + 0

                peaklist.append(lineloc)

                # This allows all peaks to get caught properly
                i += peakloc + int(self.rf.linelen * .4)
            else: # nothing valid found - keep looking!
                i += self.rf.linelen // 2
                
        return peaklist

    def determine_field(self, peaknum):
        if peaknum < 11:
            return None

        ds = self.data[0]['demod_sync']    

        # Determine first/second field
        # should this rely on what comes *after* the vsync too?
        line0 = None
        for i in range(peaknum - 10, peaknum + 1, 1):
            peak = ds[self.peaklist[i]]
            nextpeak = ds[self.peaklist[i + 1]]

            nextgap = self.peaklist[i + 1] - self.peaklist[i]

            if line0 is None and nextpeak < .525 and inrange(nextgap, self.rf.inlinelen * .4, self.rf.inlinelen * .6):
                line0 = i

        vsgap = self.peaklist[peaknum] - self.peaklist[line0]

        return line0, ds[self.peaklist[line0]] < .6
    
    def determine_vsyncs(self):
        # find vsyncs from the peaklist
        ds = self.data[0]['demod_sync']
        vsyncs = []

        prevpeak = 1.0
        for i, p in enumerate(self.peaklist):
            peak = ds[p]
            # XXX: write better detection code here
            if peak > .9 and prevpeak < .525:
                vsyncs.append((i, *self.determine_field(i)))

            prevpeak = peak
        
        print(vsyncs)
        return vsyncs

    def compute_linelocs(self):
        # Build actual line positions, skipping half-lines and adding padding as needed
        linelocs = [self.peaklist[self.vsyncs[0][1]]]

        for curindex in range(self.vsyncs[0][1] + 1, self.vsyncs[1][0]):
            curline = self.peaklist[curindex]
            #print(curline)

            # fill in as many missing lines as needed
            while (curline - linelocs[-1]) > (self.inlinelen * 1.95):
                linelocs.append(linelocs[-1] + (linelocs[-1] - linelocs[-2]))
        
            if (curline - linelocs[-1]) > (self.inlinelen * 1.05):
                linelocs.append(linelocs[-1] + self.inlinelen)
            elif (curline - linelocs[-1]) > (self.inlinelen * .95):
                linelocs.append(curline)
                
        return linelocs

    def refine_linelocs_hsync(self):
        # Adjust line locations to end of HSYNC.
        # This causes issues for lines 1-9, where only the beginning is reliable :P

        offset = 32 

        err = [False] * len(self.linelocs[0])

        linelocs2 = self.linelocs[-1].copy()
        for i in range(len(self.linelocs[0])):
            # First adjust the lineloc before the beginning of hsync - 
            # lines 1-9 are half-lines which need a smaller offset
            if i > 9:
                linelocs2[i] -= offset
            else:
                linelocs2[i] -= 200 # search for *beginning* of hsync

            zc = calczc(self.data[0]['demod_05'], linelocs2[i], self.rf.iretohz(-20), reverse=False, _count=400)

            #print(i, linelocs2[i], zc)
            if zc is not None:
                linelocs2[i] = zc - 32
                
                origdata = self.data[0]['demod_05'][int(zc)-40:int(zc)+100]

                if np.min(origdata) < self.rf.iretohz(-50):
                    err[i] = True

                if i >= 10: # don't run this special adjustment code on vsync lines (yet?)
                    # on some captures with high speed variation wow effects can mess up TBC.
                    # determine the low and high values and recompute zc along the middle

                    low = np.mean(origdata[0:20])
                    high = np.mean(origdata[100:120])

                    zc2 = calczc(origdata, 0, (low + high) / 2, reverse=False, _count=len(origdata))
                    zc2 += (int(zc)-40)

                    linelocs2[i] = zc2 - 32
            else:
                err[i] = True

            if i < 10:
                linelocs2[i] += self.usectoinpx(4.72)

            if i > 10 and err[i]:
                gap = linelocs2[i - 1] - linelocs2[i - 2]
                linelocs2[i] = linelocs2[i - 1] + gap
                #print(i, zc, lbinelocs2[i])
                
        # XXX: HACK!
        # On both PAL and NTSC this gets it wrong for VSYNC areas.  They need to be *reasonably* 
        # accurate for analog audio, but are never seen in the picture.
        for i in range(8, -1, -1):
            gap = linelocs2[i + 1] - linelocs2[i]
#            print(i, gap)
            if not inrange(gap, self.rf.linelen - (self.rf.freq * .2), self.rf.linelen + (self.rf.freq * .2)):
                gap = self.rf.linelen

            linelocs2[i] = linelocs2[i + 1] - gap
            
        # XXX2: more hack!  This one covers a bit at the end of a PAL field
        for i in range(300, len(linelocs2)):
            gap = linelocs2[i] - linelocs2[i - 1]
            #print(i, gap)
            if not inrange(gap, self.rf.linelen - (self.rf.freq * .2), self.rf.linelen + (self.rf.freq * .2)):
                gap = self.rf.linelen

            linelocs2[i] = linelocs2[i - 1] + gap
            

        return linelocs2, err    

    def downscale_line(self, linenum, lineinfo = None, outwidth = None, wow=True, channel='demod'):
        if lineinfo is None:
            lineinfo = self.linelocs[-1]
        if outwidth is None:
            outwidth = self.outlinelen

        scaled = scale(self.data[0][channel], lineinfo[linenum], lineinfo[linenum + 1], outwidth)

        if wow:
            linewow = (lineinfo[linenum + 1] - lineinfo[linenum]) / self.inlinelen
            scaled *= linewow
                
        return scaled
        
    def downscale(self, lineinfo = None, outwidth = None, wow=True, channel='demod', audio = False, offset = 0):
        if lineinfo is None:
            lineinfo = self.linelocs[-1]
        if outwidth is None:
            outwidth = self.outlinelen
            
        lineinfoc = np.array(lineinfo, dtype=np.double) + offset
            
        dsout = np.zeros((self.linecount * outwidth), dtype=np.double)    
        dsaudio = None

        sfactor = [None]

        for l in range(1, self.linecount):
            try:
                scaled = scale(self.data[0][channel], lineinfoc[l], lineinfoc[l + 1], outwidth)

                if wow:
                    linewow = (lineinfoc[l + 1] - lineinfoc[l]) / self.inlinelen
                    scaled *= linewow

                dsout[l * outwidth:(l + 1)*outwidth] = scaled
            except:
                pass
                
        if audio and self.rf.analog_audio:
            self.dsaudio, self.audio_next_offset = downscale_audio(self.data[1], lineinfo, self.rf, self.linecount, self.audio_next_offset)
            
        return dsout, self.dsaudio
    
    def decodephillipscode(self, linenum):
        linestart = self.linelocs[-1][linenum]
        data = self.data[0]['demod']
        curzc = calczc(data, int(linestart + self.usectoinpx(2)), self.rf.iretohz(50), _count=int(self.usectoinpx(12)))

        zc = []
        while curzc is not None:
            zc.append((curzc, data[int(curzc - self.usectoinpx(0.5))] < self.rf.iretohz(50)))
            curzc = calczc(data, curzc+self.usectoinpx(1.9), self.rf.iretohz(50), _count=int(self.usectoinpx(0.2)))

        usecgap = self.inpxtousec(np.diff([z[0] for z in zc]))
        valid = len(zc) == 24 and np.min(usecgap) > 1.85 and np.max(usecgap) < 2.15

        if valid:
            bitset = [z[1] for z in zc]
            linecode = []
            for b in range(0, 24, 4):
                linecode.append((np.packbits(bitset[b:b+4]) >> 4)[0])
            return linecode
        
        return None

    def processphilipscode(self):
        self.vbi = {
            'minutes': None,
            'seconds': None,
            'clvframe': None,
            'framenr': None,
            'statuscode': None,
            'status': None,
            'isclv': False,
        }
        
        for l in self.rf.SysParams['philips_codelines']:
            if self.linecode[l] is not None:
                lc = self.linecode[l]
                if lc[0] == 15 and lc[2] == 13: # CLV time code
                    self.vbi['minutes'] = 60 * lc[1]
                    self.vbi['minutes'] += lc[4] * 10
                    self.vbi['minutes'] += lc[5]
                    self.vbi['isclv'] = True
                    print('clv min ', self.vbi['minutes'])
                elif lc[0] == 15: # CAV frame code
                    frame = (lc[1] & 7) * 10000
                    frame += (lc[2] * 1000)
                    frame += (lc[3] * 100)
                    frame += (lc[4] * 10)
                    frame += lc[5] 
                    self.vbi['framenr'] = frame
                    print('cav frame ', frame)
                else:
                    h = lc[0] << 20
                    h |= lc[1] << 16
                    h |= lc[2] << 12
                    h |= lc[3] << 8
                    h |= lc[4] << 4
                    h |= lc[5] 
                    #print('%06x' % h)
                    
                    if lc[2] == 0xE: # seconds/frame goes here
                        self.vbi['seconds'] = lc[1] - 10
                        self.vbi['seconds'] += lc[3]
                        self.vbi['clvframe'] = lc[4] * 10
                        self.vbi['clvframe'] += lc[5]
                        self.vbi['isclv'] = True
                        print('clv s/f', self.seconds, self.clvframe)

                    htop = h >> 12
                    if htop == 0x8dc or htop == 0x8ba:
                        print('status code', h)
                        self.vbi['status'] = h
                    
                    if h == 0x87ffff:
                        self.vbi['isclv'] = True 

    # what you actually want from this:
    # decoded_field: downscaled field
    # burstlevels: 
    def __init__(self, rf, rawdecode, start, audio_offset = 0, keepraw = True):
        self.data = rawdecode
        self.rf = rf
        self.start = start
        
        self.inlinelen = self.rf.linelen
        self.outlinelen = self.rf.SysParams['outlinelen']
        
        self.valid = False
        
        self.peaklist = self.get_syncpeaks()
        self.vsyncs = self.determine_vsyncs()

        self.dspicture = None
        self.dsaudio = None
        self.audio_next_offset = audio_offset
        
        if len(self.vsyncs) == 0:
            self.nextfieldoffset = start + self.rf.linelen
            print("way too short")
            return
        elif len(self.vsyncs) == 1:
            self.nextfieldoffset = start + self.peaklist[self.vsyncs[0][1]-10]
            print("too short")
            return
        
        #print(self.peaklist[self.vsyncs[0][1]], self.peaklist[self.vsyncs[1][1]])
        self.nextfieldoffset = self.peaklist[self.vsyncs[1][1]-10]
        
        self.bottomfield = self.vsyncs[0][2]
        
        # On NTSC linecount is 262/263, PAL 312/313?
        self.linecount = self.rf.SysParams['frame_lines'] // 2
        if not self.bottomfield:
            self.linecount += 1
        
        self.linelocs = [self.compute_linelocs()]
        linelocs2, self.errs2 = self.refine_linelocs_hsync()
        self.linelocs.append(linelocs2)

        # VBI info
        self.isclv = False
        self.linecode = {}
        self.framenr = None
        for l in self.rf.SysParams['philips_codelines']:
            self.linecode[l] = self.decodephillipscode(l)
            
        self.processphilipscode()
        
        self.valid = True
        
        return

# These classes extend Field to do PAL/NTSC specific TBC features.

class FieldPAL(Field):
    def refine_linelocs_pilot(self, linelocs = None):
        if linelocs is None:
            linelocs = self.linelocs[1].copy()
        else:
            linelocs = linelocs.copy()

        for l in range(len(linelocs)):
            pilot = self.data[0]['demod'][int(linelocs[l]-self.usectoinpx(4.7)):int(linelocs[l])].copy()
            pilot -= self.data[0]['demod_05'][int(linelocs[l]-self.usectoinpx(4.7))+32:int(linelocs[l])+32]
            pilot = np.flip(pilot)

            adjfreq = self.rf.freq
            if l > 1:
                adjfreq /= (linelocs[l] - linelocs[l - 1]) / self.rf.inlinelen

            i = 0

            offsets = []

            while i < len(pilot):
                if inrange(pilot[i], -300000, -100000):
                    zc = calczc(pilot, i, 0)

                    if zc is not None:
                        zcp = zc / (adjfreq / 3.75)
                        #print(i, pilot[i], zc, zcp, np.round(zcp) - zcp)

                        offsets.append(np.round(zcp) - zcp)

                        i = np.int(zc + 1)

                i += 1

            if len(offsets) >= 3:
                offsetmedian = np.median(offsets[1:-1])
                #print(l, offsetmedian)
                linelocs[l] += offsetmedian * (self.rf.freq / 3.75) * .25

        return linelocs
    
    def downscale(self, final = False, *args, **kwargs):
        dsout, dsaudio = super(FieldPAL, self).downscale(audio = final, *args, **kwargs)
        
        if final:
            reduced = (dsout - self.rf.SysParams['ire0']) / self.rf.SysParams['hz_ire']
            reduced += self.rf.SysParams['vsync_ire']
            out_scale = np.double(0xd300 - 0x0100) / (100 + self.rf.SysParams['vsync_ire'])
            lines16 = np.uint16(np.clip(reduced * out_scale, 0, 65535) + 0.5)
            
            self.dspicture = lines16
            return lines16, dsaudio
                    
        return dsout, dsaudio
    
    def __init__(self, *args, **kwargs):
        super(FieldPAL, self).__init__(*args, **kwargs)
        
        if not self.valid:
            return
        
        self.linelocs.append(self.refine_linelocs_pilot())
        
        self.downscale(wow = True, final=True)

# These classes extend Field to do PAL/NTSC specific TBC features.

class FieldNTSC(Field):
    def refine_linelocs_burst(self, linelocs = None):
        if linelocs is None:
            linelocs = self.linelocs[1].copy()
        else:
            linelocs = linelocs.copy()

        fsc = self.rf.SysParams['fsc_mhz']     
        hz_ire_scale = 1700000 / 140        

        burstlevel = np.zeros_like(linelocs, dtype=np.float32)

        for l in range(len(linelocs)):
            begin = int(linelocs[l]+self.usectoinpx(0.5))
            end = int(linelocs[l]+self.usectoinpx(3.5))

            pilot = self.data[0]['demod'][begin:end].copy()
            pilot -= self.data[0]['demod_05'][begin+32:end+32]

            burstlevel[l] = np.max(np.abs(pilot))
            if not inrange(burstlevel[l] / hz_ire_scale, 5, 60):
                burstlevel[l] = 0
                continue        

            adjfreq = self.rf.freq
            if l > 1:
                linegap = linelocs[l] - linelocs[l - 1]
                ratio = linegap / self.rf.inlinelen
                adjfreq /= linegap / ratio

            # True:  hi->low, False: low->hi
            burstoffsets = {False: [], True:[]}

            i = 0
            while i < len(pilot):
                if inrange(np.abs(pilot[i]), 100000, 300000):
                    zc = calczc(pilot, i, 0)

                    if zc is not None:
                        zc_adj = zc + self.usectoinpx(0.5)
                        zcp = zc_adj / (adjfreq / fsc)
                        #print(l, i, pilot[i], zc, zcp, np.round(zcp) - zcp)

                        burstoffsets[pilot[i] > 0].append(np.round(zcp) - zcp)

                        i = np.int(zc + 1)

                i += 1

            if len(burstoffsets[False]) < 3 or len(burstoffsets[True]) < 3:
                burstlevel[l] = 0
                continue

            # Chop the first and last bursts since their phase can be off
            for v in [False, True]:
                burstoffsets[v] = np.array(burstoffsets[v][1:-1])

            if np.median(burstoffsets[False]) < np.median(burstoffsets[True]):
                offset = np.median(burstoffsets[False])
            else:
                offset = np.median(burstoffsets[True])
                burstlevel[l] = -burstlevel[l]

            adjust = np.round(offset) - offset
            adjust /= 2

            print('l', l, offset, adjust, adjust * (self.rf.freq / fsc) * .25)
            linelocs[l] += adjust * (self.rf.freq / fsc) * 1

        for l in range(11, len(linelocs) - 1):
            if burstlevel[l] == 0:
                gap = linelocs[l - 1] - linelocs[l - 2]
                linelocs[l] = linelocs[l - 1] + gap

        return linelocs, burstlevel
    
    def downscale(self, final = False, *args, **kwargs):
        if final:
            shift33 = ((33.0 / 360.0) * np.pi) * .5
            offset = (-1 - shift33) * (self.rf.freq / (4 * 315 / 88))
        else:
            offset = 0

        dsout, dsaudio = super(FieldNTSC, self).downscale(audio = final, offset = offset, *args, **kwargs)
        
        if final:
            reduced = (dsout - self.rf.SysParams['ire0']) / self.rf.SysParams['hz_ire']
            reduced += 40
            out_scale = 65534.0 / 160
            lines16 = np.uint16(np.clip(reduced * out_scale, 0, 65535) + 0.5)
            
            if self.burstlevel is not None:
                for i in range(1, self.linecount - 1):
                    hz_ire_scale = 1700000 / 140
                    if self.burstlevel[i] < 0:
                        lines16[((i + 0) * self.outlinelen)] = 16384
                    else:
                        lines16[((i + 0) * self.outlinelen)] = 32768

                    clevel = .4/hz_ire_scale

                    lines16[((i + 0) * self.outlinelen) + 1] = np.uint16(327.67 * clevel * np.abs(self.burstlevel[i]))

            self.dspicture = lines16
            return lines16, dsaudio
                    
        return dsout, dsaudio
    
    def apply_offsets(self, linelocs, phaseoffset, picoffset = 0):
        return np.array(linelocs) + picoffset + (phaseoffset * (self.rf.freq / (4 * 315 / 88)))

    def __init__(self, *args, **kwargs):
        self.burstlevel = None
        
        super(FieldNTSC, self).__init__(*args, **kwargs)
        
        if not self.valid:
            return
        
        # This needs to be run twice to get optimal burst levels
        linelocs3, self.burstlevel = self.refine_linelocs_burst(self.linelocs[-1])
        self.linelocs.append(linelocs3)
        
        # Now adjust 33 degrees for color decoding
        shift33 = ((33.0 / 360.0) * np.pi) * .5
        #offset = (-1 - shift33) * (phaseoffset * (self.rf.freq / (4 * 315 / 88)))
        self.linelocs.append(self.apply_offsets(self.linelocs[-1], -1 - shift33))
        
        self.downscale(wow = True, final=True)

#fp2 = FieldPAL(rfd, rawdecode, 0)


class Framer:
    def __init__(self, rf):
        self.rf = rf

        if self.rf.system == 'PAL':
            print("PAL")
            self.FieldClass = FieldPAL
            self.readlen = 1000000
            self.outlines = 610
            self.outwidth = 1052
            self.bottomfieldfirst = False
        else:
            self.FieldClass = FieldNTSC
            self.readlen = 900000
            self.outlines = 505
            self.outwidth = 844
            self.bottomfieldfirst = True
        
        self.audio_offset = 0

    def readfield(self, infile, sample):
        readsample = sample
        print('starting at ', sample)
        
        while True:
            if isinstance(infile, io.IOBase):
                rawdecode = self.rf.demod(infile, readsample, self.readlen)
                f = self.FieldClass(self.rf, rawdecode, 0, audio_offset = self.audio_offset)
                nextsample = readsample + f.nextfieldoffset
            else:
                f = self.FieldClass(self.rf, infile, readsample)
                nextsample = f.nextfieldoffset
                if not f.valid and len(f.vsyncs) == 0:
                    return None, None
            
            if not f.valid:
                print('invalid ', readsample, nextsample)
                readsample = nextsample # f.nextfieldoffset
            else:
                return f, nextsample # readsample + f.nextfieldoffset
        
    def mergevbi(self, fields):
        vbi_merged = copy.copy(fields[0].vbi)
        for k in vbi_merged.keys():
            if fields[1].vbi[k] is not None:
                vbi_merged[k] = fields[1].vbi[k]
                
        if vbi_merged['seconds'] is not None:
            fps = np.round() # XXX PAL
            vbi_merged['framenr'] = vbi_merged['minutes'] * 60 * fps
            vbi_merged['framenr'] += vbi_merged['seconds'] * fps
            vbi_merged['framenr'] += vbi_merged['clvframe']
                
        return vbi_merged

    def readframe(self, infile, sample, firstframe = False, usePhilipsCode = False):
        fieldcount = 0
        fields = [None, None]
        audio = []
        
        jumpto = 0
        while fieldcount < 2:
            f, sample = self.readfield(infile, sample)
            
            #return f, sample
            
            if f is not None:

                #tmpfield = f.downscale()
                
                print(f.bottomfield, f.vbi['framenr'])
                if f.bottomfield:
                    fields[1] = f
                else:
                    fields[0] = f
                
                if usePhilipsCode and (f.vbi['framenr'] or f.vbi['minutes']):
                    fieldcount = 1
                elif f.bottomfield == self.bottomfieldfirst:
                    fieldcount = 1
                elif fieldcount == 1:
                    fieldcount = 2
                
                if (fieldcount or not firstframe) and f.dsaudio is not None:
#                    print('a')
                    audio.append(f.dsaudio)

            else:
                #print('possible error', sample)
                pass
        
        if len(audio):
            conaudio = np.concatenate(audio)
            self.audio_offset = f.audio_next_offset
        else:
            conaudio = None
            
        linecount = (min(fields[0].linecount, fields[1].linecount) * 2) - 20

        combined = np.zeros((self.outwidth * self.outlines), dtype=np.uint16)

        for i in range(0, linecount, 2):
            curline = (i // 2) + 10
            combined[((i + 0) * self.outwidth):((i + 1) * self.outwidth)] = fields[0].dspicture[curline * fields[0].outlinelen: (curline * fields[0].outlinelen) + self.outwidth]
            combined[((i + 1) * self.outwidth):((i + 2) * self.outwidth)] = fields[1].dspicture[curline * fields[0].outlinelen: (curline * fields[0].outlinelen) + self.outwidth]
        
        self.vbi = self.mergevbi(fields)

        return combined, conaudio, sample, fields