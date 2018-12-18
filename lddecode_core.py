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
    
    'vsync_ire': -40,

    # most NTSC disks have analog audio, except CD-V and a few Panasonic demos
    'analog_audio': True,
    # From the spec - audio frequencies are multiples of the (color) line rate
    'audio_lfreq': (1000000*315/88/227.5) * 146.25,
    'audio_rfreq': (1000000*315/88/227.5) * 178.75,
    
    'philips_codelines': [15, 16, 17],
    
    'topfirst': True,
}

# In color NTSC, the line period was changed from 63.5 to 227.5 color cycles,
# which works out to 63.5(with a bar on top) usec
SysParams_NTSC['line_period'] = 1/(SysParams_NTSC['fsc_mhz']/227.5)
SysParams_NTSC['FPS'] = 1000000/ (525 * SysParams_NTSC['line_period'])

SysParams_NTSC['outlinelen'] = calclinelen(SysParams_NTSC, 4, 'fsc_mhz')

SysParams_PAL = {
    'FPS': 25,
    
    # from wiki: 283.75 × 15625 Hz + 25 Hz = 4.43361875 MHz
    'fsc_mhz': ((1/64) * 283.75) + (25/1000000),
    'pilot_mhz': 3.75,
    'frame_lines': 625,
    'line_period': 64,

    'ire0': 7100000,
    'hz_ire': 800000 / 100.0,

    # only early PAL disks have analog audio
    'analog_audio': True,
    # From the spec - audio frequencies are multiples of the (color) line rate
    'audio_lfreq': (1000000/64) * 43.75,
    'audio_rfreq': (1000000/64) * 68.25,

    # slight flaw:  different vbi lines in this phase
    'philips_codelines': [17, 18, 19, 20],
    
    'topfirst': False,    
}

SysParams_PAL['outlinelen'] = calclinelen(SysParams_PAL, 4, 'fsc_mhz')
SysParams_PAL['outlinelen_pilot'] = calclinelen(SysParams_PAL, 4, 'pilot_mhz')


SysParams_PAL['vsync_ire'] = -.3 * (100 / .7)

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
    'video_lpf_freq': 4800000,   # in mhz
    'video_lpf_order': 5 # butterworth filter order
}

RFParams_PAL = {
    # The audio notch filters are important with DD v3.0+ boards
    'audio_notchwidth': 200000,
    'audio_notchorder': 2,

    'video_deemp': (100*.34, 400*.34),

    # XXX: guessing here!
    'video_bpf': (2500000, 12500000),
    'video_bpf_order': 1,

    'video_lpf_freq': 4800000,
    'video_lpf_order': 9,
}

class RFDecode:
    def __init__(self, inputfreq = 40, system = 'NTSC', blocklen_ = 16384, decode_analog_audio = True, have_analog_audio = True, mtf_mult = 1.0, mtf_offset = 0):
        self.blocklen = blocklen_
        self.blockcut = 1024 # ???
        self.system = system
        
        freq = inputfreq
        self.freq = freq
        self.freq_half = freq / 2
        self.freq_hz = self.freq * 1000000
        self.freq_hz_half = self.freq * 1000000 / 2
        
        self.mtf_mult = mtf_mult
        self.mtf_offset = mtf_offset
        
        if system == 'NTSC':
            self.SysParams = SysParams_NTSC
            self.DecoderParams = RFParams_NTSC
            self.mtf_mult *= .7
        elif system == 'PAL':
            self.SysParams = SysParams_PAL
            self.DecoderParams = RFParams_PAL

        linelen = self.freq_hz/(1000000.0/self.SysParams['line_period'])
        self.linelen = int(np.round(linelen))
            
        self.decode_analog_audio = decode_analog_audio

        self.computefilters()    
            
        self.blockcut_end = self.Filters['F05_offset']

    def computefilters(self):
        self.computevideofilters()
        if self.decode_analog_audio: 
            self.computeaudiofilters()

    def computevideofilters(self):
        if self.system == 'NTSC':
            self.Filters = {
                'MTF': filtfft(sps.zpk2tf([], [polar2z(.7,np.pi*12.5/20), polar2z(.7,np.pi*27.5/20)], 1.11), self.blocklen)
            }
        elif self.system == 'PAL':
            self.Filters = {
                'MTF': filtfft(sps.zpk2tf([], [polar2z(.7,np.pi*10/20), polar2z(.7,np.pi*28/20)], 1.11), self.blocklen)
            }
        
        # Use some shorthand to compact the code.  good idea?  prolly not.
        SF = self.Filters
        SP = self.SysParams
        DP = self.DecoderParams
        
        SF['hilbert'] = np.fft.fft(hilbert_filter, self.blocklen)
        
        filt_rfvideo = sps.butter(DP['video_bpf_order'], [DP['video_bpf'][0]/self.freq_hz_half, DP['video_bpf'][1]/self.freq_hz_half], btype='bandpass')
        SF['RFVideo'] = filtfft(filt_rfvideo, self.blocklen)

        if SP['analog_audio']: 
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
        SF['F05_offset'] = 32
        SF['F05'] = filtfft((F0_5, [1.0]), self.blocklen)
        SF['FVideo05'] = SF['Fvideo_lpf'] * SF['Fdeemp']  * SF['F05']

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
        return self.SysParams['ire0'] + (self.SysParams['hz_ire'] * ire)

    def hztoire(self, hz):
        return (hz - self.SysParams['ire0']) / self.SysParams['hz_ire']
    
    def demodblock(self, data, mtf_level = 0):
        mtf_level *= self.mtf_mult
        mtf_level += self.mtf_offset
            
        indata_fft = np.fft.fft(data[:self.blocklen])
        indata_fft_filt = indata_fft * self.Filters['RFVideo']

        if mtf_level != 0:
            indata_fft_filt *= self.Filters['MTF'] ** mtf_level

        hilbert = np.fft.ifft(indata_fft_filt)
        demod = unwrap_hilbert(hilbert, self.freq_hz)

        demod_fft = np.fft.fft(demod)

        out_video = np.fft.ifft(demod_fft * self.Filters['FVideo']).real
        
        out_video05 = np.fft.ifft(demod_fft * self.Filters['FVideo05']).real
        out_video05 = np.roll(out_video05, -self.Filters['F05_offset'])

        out_videoburst = np.fft.ifft(demod_fft * self.Filters['FVideoBurst']).real
        
        # NTSC: filtering for vsync pulses from -55 to -25ire seems to work well even on rotted disks
        output_sync = inrange(out_video05, self.iretohz(-55), self.iretohz(-25))
        # Perform FFT convolution of above filter
        output_syncf = np.fft.ifft(np.fft.fft(output_sync) * self.Filters['FPsync']).real

        if self.system == 'PAL':
            out_videopilot = np.fft.ifft(demod_fft * self.Filters['FVideoPilot']).real
            rv_video = np.rec.array([out_video, out_video05, output_syncf, out_videoburst, out_videopilot], names=['demod', 'demod_05', 'demod_sync', 'demod_burst', 'demod_pilot'])
        else:
            rv_video = np.rec.array([out_video, out_video05, output_syncf, out_videoburst], names=['demod', 'demod_05', 'demod_sync', 'demod_burst'])

        if self.decode_analog_audio == False:
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

    def demod(self, indata, start, length, mtf_level = 0):
        end = int(start + length) + 1
        start = int(start - self.blockcut) if (start > self.blockcut) else 0

        # set a placeholder
        output = None
        output_audio = None

        blocklen_overlap = self.blocklen - self.blockcut - self.blockcut_end
        for i in range(start, end, blocklen_overlap):
            # XXX: process last block with 0 padding
            if (i + blocklen_overlap) > end:
                break

            tmp_video, tmp_audio = self.demodblock(indata[i:i+self.blocklen], mtf_level = mtf_level)

            # if the output hasn't been created yet, do it now using the 
            # data types returned by dodemod (should be faster than multiple
            # allocations...)
            if output is None:
                output = np.zeros(end - start + 1, dtype=tmp_video.dtype)

            if i - start + (self.blocklen - self.blockcut) > len(output):
                copylen = len(output) - (i - start)
            else:
                copylen = self.blocklen - self.blockcut - self.blockcut_end

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

    # include one extra 'tick' to interpolate the last one and use as a return value
    # for the next frame
    arange = np.arange(timeoffset, frametime + soundgap, soundgap, dtype=np.double)
    locs = np.zeros(len(arange), dtype=np.float)
    swow = np.zeros(len(arange), dtype=np.float)
    
    for i, t in enumerate(arange):
        linenum = (((t * 1000000) / rf.SysParams['line_period']) + 1)
        
        lineloc_cur = lineinfo[np.int(linenum)]
        try:
            lineloc_next = lineinfo[np.int(linenum) + 1]
        except:
            lineloc_next = lineloc_cur + rf.linelen

        sampleloc = lineloc_cur
        sampleloc += (lineloc_next - lineloc_cur) * (linenum - np.floor(linenum))

        swow[i] = ((lineloc_next - lineloc_cur) / rf.linelen)
        locs[i] = sampleloc / scale
        
        if False:        
            wowratio = 1 - (lineloc - np.floor(lineloc))
            wow = (lineinfo[l + 1] - lineinfo[l]) / rf.linelen
            swow[i] = wow[np.int(lineloc)] * (1 - wowratio)
            swow[i] += wow[np.int(lineloc + 1 )] * (wowratio)

            locs[i] = sampleloc / scale

    output = np.zeros((2 * (len(arange) - 1)), dtype=np.int32)
    output16 = np.zeros((2 * (len(arange) - 1)), dtype=np.int16)

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

# The Field class contains common features used by NTSC and PAL
class Field:
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
                peaklist.append(i + peakloc)

                # This allows all peaks to get caught properly
                i += peakloc + int(self.rf.linelen * .4)
            else: # nothing valid found - keep looking!
                i += self.rf.linelen // 2
                
        return peaklist

    def get_hsync_median(self):
        ''' Sets the median and tolerance levels for filtered hsync pulses '''
        
        ds = self.data[0]['demod_sync']

        plist = self.peaklist
        plevel = [ds[p] for p in self.peaklist]

        plevel_hsync = [ds[p] for p in self.peaklist if inrange(ds[p], 0.6, 0.8)]
        self.med_hsync = np.median(plevel_hsync)
        self.std_hsync = np.std(plevel_hsync)

        self.hsync_tolerance = max(np.std(plevel_hsync) * 2, .01)

        return self.med_hsync, self.hsync_tolerance
    
    def is_regular_hsync(self, peaknum):
        if peaknum >= len(self.peaklist):
            return False
        
        if self.peaklist[peaknum] > len(self.data[0]['demod_sync']):
            return False

        plevel = self.data[0]['demod_sync'][self.peaklist[peaknum]]
        return inrange(plevel, self.med_hsync - self.hsync_tolerance, self.med_hsync + self.hsync_tolerance)
        
    def determine_field(self, peaknum):
        if peaknum < 11:
            return None

        vote = 0

        ds = self.data[0]['demod_sync']    

        # Determine first/second field
        # should this rely on what comes *after* the vsync too?
        line0 = None
        gap1 = None
        for i in range(peaknum - 1, peaknum - 20, -1):
            if self.is_regular_hsync(i) and line0 is None:
                line0 = i
                gap1 = (self.peaklist[line0 + 1] - self.peaklist[line0])
                break

        if gap1 is not None and gap1 > (self.inlinelen * .75):
            vote -= 1

        linee = None
        gap2 = None
        for i in range(peaknum, peaknum + 20, 1):
            if self.is_regular_hsync(i)  and linee is None:
                linee = i
                gap2 = (self.peaklist[linee] - self.peaklist[linee - 1])
                break

        if gap2 is not None and gap2 > (self.inlinelen * .75):
            if self.rf.system == 'NTSC':
                vote += 1
            else:
                vote -= 1
                
        if self.rf.system == 'PAL':
            vote += 1

        #print(line0, self.peaklist[line0], linee, gap1, gap2, vote)

        return line0, vote    
    
    def determine_vsyncs(self):
        # find vsyncs from the peaklist
        ds = self.data[0]['demod_sync']
        vsyncs = []
        
        if len(self.peaklist) < 200:
            return []

        med_hsync, hsync_tolerance = self.get_hsync_median()
        
        prevpeak = 1.0
        for i, p in enumerate(self.peaklist):
            peak = ds[p]
            if peak > .9 and prevpeak < med_hsync - (hsync_tolerance * 2):
                line0, vote = self.determine_field(i)
                if line0 is not None:
                    vsyncs.append((i, line0, vote))

            prevpeak = peak
            
        # punt early if there's 0 or 1 vsyncs, this is invalid
        if len(vsyncs) < 2:
            return vsyncs
        
        va = np.array(vsyncs)
        
        for i in range(0, len(vsyncs)):
            # see if determine_field (partially) failed.  use hints from input and other data
            if va[i][2] == 0:
                va[i][1] = -1
                print("vsync vote needed", i)
                if (i < len(vsyncs) - 1) and vsyncs[i + 1][2] != 0:
                    va[i][2] = -va[i + 1][2]
                elif (i >= 1) and vsyncs[i - 1][2] != 0:
                    va[i][2] = -va[i - 1][2]
                    
            if va[i][1] <= 0:
                # override the earlier last-good-line detection
                # XXX: not tested on PAL failures
                if self.rf.system == 'PAL':
                    va[i][1] = va[i][0] - 6
                else:
                    va[i][1] = va[i][0] - 7
                    
            va[i][2] = va[i][2] < 0

        return va

    def compute_linelocs(self):
        plist = self.peaklist

        # note: this is chopped on output, so allocating too many lines is OK
        linelocs = {}

        firstvisidx = None
        for i in range(0, self.vsyncs[1][1]): #self.vsyncs[1][1]):
            if i > self.vsyncs[0][0] and firstvisidx is None:
                #print(i, plist[i], plist[self.vsyncs[0][1]])
                firstvisidx = i

                break

        linelens = [self.inlinelen]
        prevlineidx = None
        for i in range(0, self.vsyncs[1][1] + 0): 
            med_linelen = np.median(linelens[-25:])

            if (self.is_regular_hsync(i)):
                if prevlineidx is not None:
                    linegap = plist[i] - plist[prevlineidx]

                    if inrange(linegap / self.inlinelen, .98, 1.02):
                        linelens.append(linegap)
                        linenum = prevlinenum + 1
                    else:
                        linenum = prevlinenum + int(np.round((plist[i] - plist[prevlineidx]) / med_linelen))
                else:
                    linenum = int(np.round((plist[i] - plist[self.vsyncs[0][1]]) / med_linelen))

                linelocs[linenum] = plist[i]

                prevlineidx = i
                prevlinenum = linenum

        linelocs2 = copy.deepcopy(linelocs)

        for l in range(1, self.linecount + 6):
            if l not in linelocs:
                prev_valid = None
                next_valid = None

                for i in range(l, -10, -1):
                    if i in linelocs:
                        prev_valid = i
                        break
                for i in range(l, self.linecount + 1):
                    if i in linelocs:
                        next_valid = i
                        break

                if prev_valid is None:
                    avglen = self.inlinelen
                    linelocs2[l] = linelocs[next_valid] - (avglen * (next_valid - l))
                elif next_valid is not None:
                    avglen = (linelocs[next_valid] - linelocs[prev_valid]) / (next_valid - prev_valid)
                    linelocs2[l] = linelocs[prev_valid] + (avglen * (l - prev_valid))
                else:
                    avglen = linelocs[prev_valid] - linelocs2[prev_valid - 1]
                    linelocs2[l] = linelocs[prev_valid] + (avglen * (l - prev_valid))

        rv_ll = [linelocs2[l] for l in range(1, self.linecount + 6)]
        rv_err = [l not in linelocs for l in range(1, self.linecount + 6)]
        
        for i in range(0, 10):
            rv_err[i] = False

        return rv_ll, rv_err

    def refine_linelocs_hsync(self):
        linelocs2 = self.linelocs1.copy()

        for i in range(len(self.linelocs1)):
            # Find beginning of hsync (linelocs1 is generally in the middle)
            ll1 = self.linelocs1[i] - self.usectoinpx(5.5)
            zc = calczc(self.data[0]['demod_05'], ll1, self.rf.iretohz(self.rf.SysParams['vsync_ire'] / 2), reverse=False, _count=400)

            if zc is not None and not self.linebad[i]:
                linelocs2[i] = zc 

                # The hsync area, burst, and porches should not leave -50 to 30 IRE (on PAL or NTSC)
                hsync_area = self.data[0]['demod_05'][int(zc-(self.rf.freq*1.25)):int(zc+(self.rf.freq*8))]
                if np.min(hsync_area) < self.rf.iretohz(-55) or np.max(hsync_area) > self.rf.iretohz(30):
                    self.linebad[i] = True
                else:
                    porch_level = np.median(self.data[0]['demod_05'][int(zc+(self.rf.freq*8)):int(zc+(self.rf.freq*9))])
                    sync_level = np.median(self.data[0]['demod_05'][int(zc+(self.rf.freq*1)):int(zc+(self.rf.freq*2.5))])

                    zc2 = calczc(self.data[0]['demod_05'], ll1, (porch_level + sync_level) / 2, reverse=False, _count=400)

                    #print(porch_level, sync_level, zc, zc2)

                    # any wild variation here indicates a failure
                    if np.abs(zc2 - zc) < (self.rf.freq / 4):
                        linelocs2[i] = zc2
                    else:
                        self.linebad[i] = True
            else:
                self.linebad[i] = True

            if (i >= 2) and self.linebad[i]:
                gap = linelocs2[i - 1] - linelocs2[i - 2]
                linelocs2[i] = linelocs2[i - 1] + gap

        return linelocs2

    def downscale(self, lineoffset = 0, lineinfo = None, linesout = None, outwidth = None, wow=True, channel='demod', audio = False):
        ''' 
        lineoffset: for NTSC the first line is the first containing the equalizing pulse (0), but for PAL fields start with the first VSYNC pulse (2 or 3).
        '''
        if lineinfo is None:
            lineinfo = self.linelocs
        if outwidth is None:
            outwidth = self.outlinelen
        if linesout is None:
            linesout = self.linecount

        dsout = np.zeros((linesout * outwidth), dtype=np.double)    
        dsaudio = None

        sfactor = [None]
        
        for l in range(lineoffset, linesout + lineoffset):
            scaled = scale(self.data[0][channel], lineinfo[l], lineinfo[l + 1], outwidth)

            if wow:
                linewow = (lineinfo[l + 1] - lineinfo[l]) / self.inlinelen
                scaled *= linewow

            dsout[(l - lineoffset) * outwidth:(l + 1 - lineoffset)*outwidth] = scaled

        if audio and self.rf.decode_analog_audio:
            self.dsaudio, self.audio_next_offset = downscale_audio(self.data[1], lineinfo, self.rf, self.linecount, self.audio_next_offset)
            
        return dsout, self.dsaudio
    
    def decodephillipscode(self, linenum):
        linestart = self.linelocs[linenum]
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
            linecode = 0

            for b in range(0, 24, 4):
                linecode *= 0x10
                linecode += (np.packbits(bitset[b:b+4]) >> 4)[0]

            return linecode
        
        return None

    def __init__(self, rf, rawdecode, start, audio_offset = 0, keepraw = True):
        if rawdecode is None:
            return None
        
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
            self.nextfieldoffset = start + (self.rf.linelen * 200)
            #print("way too short at", start)
            return
        elif len(self.vsyncs) == 1 or len(self.peaklist) < self.vsyncs[1][1]+4:
            jumpto = self.peaklist[self.vsyncs[0][1]-10]
            self.nextfieldoffset = start + jumpto
            
            if jumpto == 0:
                print("no/corrupt VSYNC found, jumping forward")
                self.nextfieldoffset = start + (self.rf.linelen * 240)
            
            return
        
        self.nextfieldoffset = self.peaklist[self.vsyncs[1][1]-10]
        
        self.istop = self.vsyncs[0][2]
        
        # On NTSC linecount is 262/263, PAL 312/313
        self.linecount = self.rf.SysParams['frame_lines'] // 2
        if self.istop:
            self.linecount += 1
        
        try:
            self.linelocs1, self.linebad = self.compute_linelocs()
            self.linelocs2 = self.refine_linelocs_hsync()
        except:
            print('unable to decode frame')
            self.valid = False
            return

        self.linelocs = self.linelocs2
        
        # VBI info
        self.linecode = []
        self.isFirstField = False
        self.cavFrame = None
        for l in self.rf.SysParams['philips_codelines']:
            self.linecode.append(self.decodephillipscode(l))
            if self.linecode[-1] is not None:
                print('lc', l, hex(self.linecode[-1]))
                # For either CAV or CLV, 0xfxxxx means this is the first field
                # All the data we *really* need here (for now) is the CAV frame # 
                if (self.linecode[-1] & 0xf00000) == 0xf00000:
                    self.isFirstField = True

                    fnum = 0
                    for y in range(16, -1, -4):
                        fnum *= 10
                        fnum += self.linecode[-1] >> y & 0x0f
                    
                    self.cavFrame = fnum if fnum < 80000 else fnum - 80000
            
        self.valid = True
        self.tbcstart = self.peaklist[self.vsyncs[1][1]-10]
        
        return

# These classes extend Field to do PAL/NTSC specific TBC features.

class FieldPAL(Field):
    def refine_linelocs_pilot(self, linelocs = None):
        if linelocs is None:
            linelocs = self.linelocs2.copy()
        else:
            linelocs = linelocs.copy()

        pilots = []
        alloffsets = []
        offsets = {}

        # first pass: get median of all pilot positive zero crossings
        for l in range(len(linelocs)):
            pilot = self.data[0]['demod'][int(linelocs[l]):int(linelocs[l]+self.usectoinpx(4.7))].copy()
            pilot -= self.data[0]['demod_05'][int(linelocs[l]):int(linelocs[l]+self.usectoinpx(4.7))]
            pilot = np.flip(pilot)

            pilots.append(pilot)
            offsets[l] = []

            adjfreq = self.rf.freq
            if l > 1:
                adjfreq /= (linelocs[l] - linelocs[l - 1]) / self.rf.linelen

            i = 0

            while i < len(pilot):
                if inrange(pilot[i], -300000, -100000):
                    zc = calczc(pilot, i, 0)

                    if zc is not None:
                        zcp = zc / (adjfreq / 3.75)
                        offsets[l].append(zcp - np.floor(zcp))
                        i = np.int(zc + 1)

                i += 1

            if len(offsets) >= 3:
                offsets[l] = offsets[l][1:-1]
                if i >= 11:
                    alloffsets += offsets[l]
            else:
                offsets[l] = []

        medianoffset = np.median(alloffsets)
        if inrange(medianoffset, 0.25, 0.75):
            tgt = .5
        else:
            tgt = 0

        for l in range(len(linelocs)):
            if offsets[l] != []:
                adjustment = tgt - np.median(offsets[l])
                linelocs[l] += adjustment * (self.rf.freq / 3.75) * .25

        return linelocs  

    def calc_burstmedian(self):
        burstlevel = np.zeros(314)

        for l in range(2, 313):
            # compute adjusted frequency from neighboring line lengths
            lfreq = self.rf.freq * (((self.linelocs[l+1] - self.linelocs[l-1]) / 2) / self.rf.linelen)

            bstart = int(6 * lfreq) # int(5.6 * lfreq)
            bend = int(9 * lfreq) #int(8.05 * lfreq)
            #bstart = int(5.6 * lfreq)
            #bend = int(8.05 * lfreq)

            burstarea = self.data[0]['demod_burst'][int(self.linelocs[l])+bstart:int(self.linelocs[l])+bend].copy()
            burstarea -= np.mean(burstarea)

            burstlevel[l] = np.max(np.abs(burstarea)) / 1

        return np.median(burstlevel / self.rf.SysParams['hz_ire'])

    def hz_to_ooutput(self, input):
        reduced = (input - self.rf.SysParams['ire0']) / self.rf.SysParams['hz_ire']
        reduced -= self.rf.SysParams['vsync_ire']
        out_scale = np.double(0xd300 - 0x0100) / (100 - self.rf.SysParams['vsync_ire'])

        return np.uint16(np.clip((reduced * out_scale) + 256, 0, 65535) + 0.5)

    def downscale(self, final = False, *args, **kwargs):
        # For PAL, each field starts with the line containing the first full VSYNC pulse
        kwargs['lineoffset'] = 3 if self.istop else 2
        dsout, dsaudio = super(FieldPAL, self).downscale(audio = final, *args, **kwargs)
        
        if final:
            self.dspicture = self.hz_to_ooutput(dsout)
            return self.dspicture, dsaudio
                    
        return dsout, dsaudio
    
    def __init__(self, *args, **kwargs):
        super(FieldPAL, self).__init__(*args, **kwargs)
        
        if not self.valid:
            return

        try:
            self.linelocs = self.refine_linelocs_pilot()
            self.burstmedian = self.calc_burstmedian()
            self.downscale(wow = True, final=True)
        except:
            print("ERROR: Unable to decode frame, skipping")
            self.valid = False

# These classes extend Field to do PAL/NTSC specific TBC features.

class FieldNTSC(Field):
    def refine_linelocs_burst(self, linelocs = None):
        if linelocs is None:
            linelocs = self.linelocs2

        linelocs_adj = linelocs.copy()
        burstlevel = np.zeros_like(linelocs_adj, dtype=np.float32)

        bstime = 17*(1 / self.rf.SysParams['fsc_mhz'])
        bmed = []

        zc_bursts = {}
        # Counter for which lines have + polarity.  TRACKS 1-BASED LINE #'s
        phase_votes = {'odd': 0, 'even': 0}

        badlines = np.full(266, False)
        
        for l in range(1, 266):
#            if self.linebad[l]:
                #badlines[l] = True
                #continue

            # calczc works from integers, so get the start and remainder
            s = int(linelocs[l])
            s_rem = linelocs[l] - s

            # compute adjusted frequency from neighboring line lengths
            lfreq = self.rf.freq * (((self.linelocs2[l+1] - self.linelocs2[l-1]) / 2) / self.rf.linelen)

            bstart = int(bstime * lfreq)
            bend = int(8.8 * lfreq)

            # copy and get the mean of the burst area to factor out wow/flutter
            burstarea = self.data[0]['demod_burst'][s+bstart:s+bend].copy()
            burstarea -= np.mean(burstarea)

            burstlevel[l] = np.max(np.abs(burstarea)) / 1

            i = 0
            zc_bursts[l] = {False: [], True: []}

            while i < (len(burstarea) - 1):
                if np.abs(burstarea[i]) > (8 * self.rf.SysParams['hz_ire']):
                    zc = calczc(burstarea, i, 0)
                    if zc is not None:
                        zc_burst = ((bstart+zc-s_rem) / lfreq) / (1 / self.rf.SysParams['fsc_mhz'])
                        zc_bursts[l][burstarea[i] < 0].append(np.round(zc_burst) - zc_burst)
                        #print(zc, np.round(zc_burst) - zc_burst)
                        i = int(zc) + 1

                i += 1
                
            # If the burst is so corrupt one ZC type is missing, punt.
            if (len(zc_bursts[l][False]) == 0) or (len(zc_bursts[l][True]) == 0):
                continue

            amed_falling = np.median(np.abs(zc_bursts[l][False]))
            amed_rising = np.median(np.abs(zc_bursts[l][True]))
            edge = False if amed_falling < amed_rising else True

            if np.abs(amed_falling - amed_rising) < .08:
                badlines[l] = True
            elif np.abs(amed_falling - amed_rising) > .1 and edge:
                if not (l % 2):
                    phase_votes['odd'] += 1
                else:
                    phase_votes['even'] += 1

        if phase_votes['even'] > phase_votes['odd']:
            field14 = False
        elif phase_votes['even'] < phase_votes['odd']:
            field14 = True
        else:
            print("WARNING: matching # of + crossling lines?")
            field14 = False # use prev field?
            
        for l in range(9, 266):
            if (field14 and not (l % 2)) or (not field14 and (l % 2)):
                edge = True
            else:
                edge = False
            
            if edge:
                burstlevel[l] = -burstlevel[l]

            if np.isnan(linelocs_adj[l]) or len(zc_bursts[l][edge]) == 0 or self.linebad[l]:
                #print('err', l, linelocs_adj[l])
                badlines[l] = True
            else:
                linelocs_adj[l] -= np.median(zc_bursts[l][edge]) * lfreq * (1 / self.rf.SysParams['fsc_mhz'])

        for l in np.where(badlines == True)[0]:
            prevgood = l - 1
            nextgood = l + 1
            while prevgood > 8 and badlines[prevgood]:
                prevgood -= 1
            while nextgood < 265 and badlines[nextgood]:
                nextgood += 1
                
            if prevgood > 8 and nextgood < 265:
                gap = (linelocs_adj[nextgood] - linelocs_adj[prevgood]) / (nextgood - prevgood)
                #print(l, prevgood, nextgood, gap + linelocs_adj[prevgood], linelocs[l])
                linelocs_adj[l] = (gap * (l - prevgood)) + linelocs_adj[prevgood]
                
        self.field14 = field14

        return linelocs_adj, burstlevel

    def hz_to_ooutput(self, input):
        reduced = (input - self.rf.SysParams['ire0']) / self.rf.SysParams['hz_ire']
        reduced -= self.rf.SysParams['vsync_ire']
        out_scale = np.double(0xc800 - 0x0400) / (100 - self.rf.SysParams['vsync_ire'])
        return np.uint16(np.clip((reduced * out_scale) + 1024, 0, 65535) + 0.5)

    def downscale(self, lineoffset = 0, final = False, *args, **kwargs):
        dsout, dsaudio = super(FieldNTSC, self).downscale(lineoffset = lineoffset, audio = final, *args, **kwargs)
        
        if final:
            lines16 = self.hz_to_ooutput(dsout)

            if self.burstlevel is not None:
                for i in range(1, self.linecount - 1):
                    hz_ire_scale = 1700000 / 140
                    clevel = (1/self.colorlevel)/ hz_ire_scale

                    lines16[((i + 0) * self.outlinelen)] = 16384 if (self.burstlevel[i] > 0) else 32768
                    lines16[((i + 0) * self.outlinelen) + 1] = np.uint16(327.67 * clevel * np.abs(self.burstlevel[i]))

            self.dspicture = lines16
            return lines16, dsaudio
                    
        return dsout, dsaudio
    
    def apply_offsets(self, linelocs, phaseoffset, picoffset = 0):
        return np.array(linelocs) + picoffset + (phaseoffset * (self.rf.freq / (4 * 315 / 88)))

    def __init__(self, *args, **kwargs):
        self.burstlevel = None

        # HE010
        self.colorphase = 90+1.5 # colorphase
        self.colorphase = 77 # colorphase
        self.colorlevel = 1.45 # colorlevel

        super(FieldNTSC, self).__init__(*args, **kwargs)
        
        if not self.valid:
            print('not valid')
            return

        try:
            # This needs to be run twice to get optimal burst levels
            self.linelocs3, self.burstlevel = self.refine_linelocs_burst(self.linelocs2)

            self.burstmedian = np.median(np.abs(self.burstlevel)) / self.rf.SysParams['hz_ire']

            # Now adjust 33 degrees (-90 - 33) for color decoding
            shift33 = self.colorphase * (np.pi / 180)
            #self.linelocs = self.apply_offsets(self.linelocs3, -shift33 - 2)
            self.linelocs = self.apply_offsets(self.linelocs3, -shift33 - 0)
        
            self.downscale(wow = True, final=True)
        except:
            print("ERROR: Unable to decode frame, skipping")
            self.valid = False

class LDdecode:
    
    def __init__(self, fname_in, fname_out, freader, analog_audio = True, frameoutput = False, system = 'NTSC'):
        self.infile = open(fname_in, 'rb')
        self.freader = freader
        
        self.outfile_video = open(fname_out + '.tbc', 'wb')
        #self.outfile_json = open(fname_out + '.json', 'wb')
        self.outfile_audio = open(fname_out + '.pcm', 'wb') if analog_audio else None
        
        self.analog_audio = analog_audio
        self.frameoutput = frameoutput
        self.firstfield = None # In frame output mode, the first field goes here

        if system == 'PAL':
            self.rf = RFDecode(system = 'PAL', decode_analog_audio=analog_audio)
            self.FieldClass = FieldPAL
            self.readlen = self.rf.linelen * 350
            self.outlineoffset = 2
            self.clvfps = 25
        else: # NTSC
            self.rf = RFDecode(system = 'NTSC', decode_analog_audio=analog_audio)
            self.FieldClass = FieldNTSC
            self.readlen = self.rf.linelen * 300
            self.outlineoffset = 0
            self.clvfps = 30
        
        self.output_lines = (self.rf.SysParams['frame_lines'] // 2) + 1
        
        self.bytes_per_frame = int(self.rf.freq_hz / self.rf.SysParams['FPS'])
        self.bytes_per_field = int(self.rf.freq_hz / (self.rf.SysParams['FPS'] * 2)) + 1
        self.outwidth = self.rf.SysParams['outlinelen']

        self.fdoffset = 0
        self.audio_offset = 0
        self.mtf_level = 1

        self.fieldinfo = []
        
    def roughseek(self, fieldnr):
        self.fdoffset = fieldnr * self.bytes_per_field
    
    def checkMTF(self, field):
        if field.cavFrame is not None:
            newmtf = 1 - (field.cavFrame / 10000) if field.cavFrame < 10000 else 0
            oldmtf = self.mtf_level
            self.mtf_level = newmtf

            if np.abs(newmtf - oldmtf) > .1: # redo field if too much adjustment
                return False
            
        return True
    
    def decodefield(self):
        ''' returns field object if valid, and the offset to the next decode '''
        readloc = self.fdoffset - self.rf.blockcut
        if readloc < 0:
            readloc = 0
            
        indata = self.freader(self.infile, readloc, self.readlen)
        
        rawdecode = self.rf.demod(indata, self.rf.blockcut, self.readlen, self.mtf_level)
        if rawdecode is None:
            print("Failed to read data")
            return None, None
        
        f = self.FieldClass(self.rf, rawdecode, 0, audio_offset = self.audio_offset)
        
        if not f.valid:
            if len(f.peaklist) < 100: 
                # No recognizable data - jump 10 seconds to get past possible spinup
                print("No recognizable data - jumping 10 seconds")
                return None, self.rf.freq_hz * 10
            elif len(f.vsyncs) == 0:
                # Some recognizable data - possibly from a player seek
                print("Bad data - jumping one second")
                return None, self.rf.freq_hz * 1
            return f, f.nextfieldoffset                
        else:
            self.audio_offset = f.audio_next_offset
            print(f.isFirstField, f.cavFrame)
            
        return f, f.nextfieldoffset
        
    def readfield(self):
        # pretty much a retry-ing wrapper around decodefield with MTF checking
        self.curfield = None
        done = False
        
        while done == False:
            f, offset = self.decodefield()
            self.curfield = f
            self.fdoffset += offset
            
            if f is not None and f.valid:
                if self.checkMTF(f):
                    done = True
                else:
                    # redo field
                    self.fdoffset -= offset
                 
        if f is not None:
            self.processfield(f)
            
        return f
            
    def processfield(self, f):
        picture, audio = f.downscale(linesout = self.output_lines, lineoffset = self.outlineoffset, final=True)
            
        if audio is not None and self.outfile_audio is not None:
            self.outfile_audio.write(audio)
            
        fi = {'isEven': f.isFirstField, 'syncConf': 75, 'seqNo': len(self.fieldinfo) + 1, 'medianBurstIRE': f.burstmedian}
        #fi['isEven'] = fi['isFirstField'] if f.rf.system == 'NTSC' else not fi['isFirstField']

        if f.rf.system == 'NTSC':
            if f.isFirstField:
                fi['ntscFieldID'] = 1 if f.field14 else 3
            else:
                fi['ntscFieldID'] = 4 if f.field14 else 2

        self.fieldinfo.append(fi)

        if self.frameoutput == False:
            self.outfile_video.write(picture)
        else:
            if self.firstfield is not None:
                self.writeframe(self.firstfield, picture)
            elif f.isFirstField:
                self.firstfield = picture
                
    def writeframe(self, f1, f2):
        linecount = self.rf.SysParams['frame_lines']
        combined = np.zeros((self.outwidth * linecount), dtype=np.uint16)
        
        for i in range(0, linecount-1, 2):
            curline = (i // 2) + 0
            combined[((i + 0) * self.outwidth):((i + 1) * self.outwidth)] = f1[curline * self.outwidth: ((curline + 1) * self.outwidth)]
            combined[((i + 1) * self.outwidth):((i + 2) * self.outwidth)] = f2[curline * self.outwidth: ((curline + 1) * self.outwidth)]

        # need to copy in the last line here, i think it's different ntsc/pal
        self.outfile_video.write(combined)

        self.firstfield = None

    def build_json(self, f):
        jout = {}
        jout['pcmAudioParameters'] = {'bits':16, 'isLittleEndian': True, 'isSigned': True, 'sampleRate': 48000}

        vp = {}

        vp['numberOfSequentialFields'] = len(self.fieldinfo)
        
        vp['isSourcePal'] = True if f.rf.system == 'PAL' else False
        vp['isFieldOrderEvenOdd'] = False if f.rf.system == 'PAL' else True
        vp['isFieldOrderValid'] = True

        vp['fsc'] = int(f.rf.SysParams['fsc_mhz'] * 1000000)
        vp['fieldWidth'] = f.rf.SysParams['outlinelen']
        vp['sampleRate'] = vp['fsc'] * 4
        vp['samplesPerUs'] = vp['sampleRate'] / 1000000
        spu = vp['samplesPerUs']

        vp['black16bIre'] = np.float(f.hz_to_ooutput(f.rf.iretohz(0)))
        vp['white16bIre'] = np.float(f.hz_to_ooutput(f.rf.iretohz(100)))

        if f.rf.system == 'NTSC':
            vp['fieldHeight'] = 263
            badj = 0 # TODO: put the IQ shift here in px
            vp['colourBurstStart'] = np.round((5.3 * spu) + badj)
            vp['colourBurstEnd'] = np.round((7.8 * spu) + badj)
            vp['blackLevelStart'] = np.round((8.2 * spu) + badj)
            vp['blackLevelEnd'] = np.round((9.2 * spu) + badj)
            vp['activeVideoStart'] = np.round((9.4 * spu) + badj)
            vp['activeVideoEnd'] = np.round(((63.55 - 1.5) * spu) + badj)
        else: # PAL
            vp['fieldHeight'] = 313
            badj = 0 # TODO: put the IQ shift here in px
            vp['colourBurstStart'] = np.round((5.6 * spu) + badj)
            vp['colourBurstEnd'] = np.round((7.85 * spu) + badj)
            vp['blackLevelStart'] = np.round((8.2 * spu) + badj)
            vp['blackLevelEnd'] = np.round((10 * spu) + badj)
            vp['activeVideoStart'] = np.round((10.5 * spu) + badj)
            vp['activeVideoEnd'] = np.round(((64 - 1.5) * spu) + badj)

        jout['videoParameters'] = vp
        
        jout['fields'] = self.fieldinfo.copy()

        return jout

# Helper functions that rely on the classes above go here

def findframe(infile, rf, target, nextsample = 0):
    ''' Locate the sample # of the target frame. '''

    return

    framer = Framer(rf, full_decode = False)
    samples_per_frame = int(rf.freq_hz / rf.SysParams['FPS'])
    framer.vbi = {'framenr': None}
    
    iscav = False
    
    # First find a stable frame to seek *from*
    retry = 5
    while framer.vbi['framenr'] is None and retry:
        rv = framer.readframe(infile, nextsample, CAV=False)
        print(rv, framer.vbi)

        # because of 29.97fps, there may be missing frames
        if framer.vbi['isclv']:
            tolerance = 1
        else:
            tolerance = 0
            iscav = True
            
        # Jump forward ~10 seconds on failure
        nextsample = rv[2] + (rf.freq_hz * 10)
        retry -= 1
        
    if retry == 0 and framer.vbi['framenr'] is None:
        print("SEEK ERROR: Unable to find a usable frame")
        return None

    retry = 5
    while np.abs(target - framer.vbi['framenr']) > tolerance and retry:
        offset = (samples_per_frame * (target - 1 - framer.vbi['framenr'])) 
        nextsample = rv[2] + offset
        rv = framer.readframe(infile, nextsample, CAV=iscav)
        print(framer.vbi)
        retry -= 1

    if np.abs(target - framer.vbi['framenr']) > tolerance:
        print("SEEK WARNING: seeked to frame {0} instead of {1}".format(framer.vbi['framenr'], target))
        
    return nextsample
