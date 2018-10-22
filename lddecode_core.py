# Note:  This is a work in progress based on the ld-decode-r3 notebook.  This may not (or might) be up to date.

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
    
    'philips_codelines': [16, 17, 18],
    
    'topfirst': True,
}

# In color NTSC, the line period was changed from 63.5 to 227.5 color cycles,
# which works out to 63.5(with a bar on top) usec
SysParams_NTSC['line_period'] = 1/(SysParams_NTSC['fsc_mhz']/227.5)
SysParams_NTSC['FPS'] = 1000000/ (525 * SysParams_NTSC['line_period'])

SysParams_NTSC['outlinelen'] = calclinelen(SysParams_NTSC, 4, 'fsc_mhz')

SysParams_PAL = {
    'FPS': 25,
    
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

    'philips_codelines': [19, 20, 21],
    
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
    'video_lpf_freq': 4200000,   # in mhz
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
    def __init__(self, inputfreq = 40, system = 'NTSC', blocklen_ = 16384, decode_analog_audio = True, have_analog_audio = True):
        self.blocklen = blocklen_
        self.blockcut = 1024 # ???
        self.system = system
        
        freq = inputfreq
        self.freq = freq
        self.freq_half = freq / 2
        self.freq_hz = self.freq * 1000000
        self.freq_hz_half = self.freq * 1000000 / 2
        
        if system == 'NTSC':
            self.SysParams = SysParams_NTSC
            self.DecoderParams = RFParams_NTSC
            
            self.Filters = {
                'MTF': sps.zpk2tf([], [polar2z(.7,np.pi*12.5/20), polar2z(.7,np.pi*27.5/20)], 1.11)
            }
        elif system == 'PAL':
            self.SysParams = SysParams_PAL
            self.DecoderParams = RFParams_PAL
            
            self.Filters = {
                'MTF': sps.zpk2tf([], [polar2z(.7,np.pi*10/20), polar2z(.7,np.pi*28/20)], 1.11)
            }

        linelen = self.freq_hz/(1000000.0/self.SysParams['line_period'])
        self.linelen = int(np.round(linelen))
            
        self.decode_analog_audio = decode_analog_audio
            
        self.computevideofilters()
        if self.decode_analog_audio: 
            self.computeaudiofilters()
            
        self.blockcut_end = self.Filters['F05_offset']
            
    def computevideofilters(self):
        self.Filters = {}
        
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

    def demod(self, infile, start, length):
        end = int(start + length) + 1

        if (start > self.blockcut):
            start = int(start - self.blockcut)
        else:
            start = 0 # should this be an error?  prolly.

        # set a placeholder
        output = None
        output_audio = None

        for i in range(start, end, self.blocklen - self.blockcut - self.blockcut_end):
            try:
                indata = loader(infile, i, self.blocklen)
            except:
                return None
            
            if indata is None:
                return None
            
            tmp_video, tmp_audio = self.demodblock(indata)

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

#audb, offset, arange, locs = downscale_audio(fields[0].rawdecode[1], fields[0].linelocs, rfd, 262)

# The Field class contains a common 
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
            # With PAL both gap lines are the same length for each field type
            if self.rf.system == 'NTSC':
                vote -= 1
            else:
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
        
#        if self.is_second: # the first frame being top is a vote against the second being one
#            va[0][2] -= 1

        for i in range(0, len(vsyncs)):
            # see if determine_field (partially) failed.  use hints from input and other data
            if va[i][2] == 0:
                print("vsync vote needed", i)
                if (i < len(vsyncs) - 1) and vsyncs[i + 1][2] != 0:
                    va[i][2] = -va[i + 1][2]
                elif (i >= 1) and vsyncs[i - 1][2] != 0:
                    va[i][2] = -va[i - 1][2]
                    
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
                print(i, plist[i], plist[self.vsyncs[0][1]])
                firstvisidx = i

                break

        linelens = [self.inlinelen]
        prevlineidx = None
        for i in range(0, self.vsyncs[1][1]): #self.vsyncs[1][1]):
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

                #print(linenum, plist[i], ((plist[i] - plist[self.vsyncs[0][1]]) / med_linelen), med_linelen)

        linelocs2 = copy.deepcopy(linelocs)

        for l in range(1, self.linecount + 5):
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

                if next_valid is not None:
                    avglen = (linelocs[next_valid] - linelocs[prev_valid]) / (next_valid - prev_valid)
                    #print(prev_valid, next_valid, avglen)
                    linelocs2[l] = linelocs[prev_valid] + (avglen * (l - prev_valid))
                else:
                    avglen = linelocs[prev_valid] - linelocs2[prev_valid - 1]
                    linelocs2[l] = linelocs[prev_valid] + (avglen * (l - prev_valid))

                #print(l, linelocs2[l] - linelocs2[l - 1], avglen, linelocs2[l], linelocs[10], prev_valid, next_valid)

        rv = [linelocs2[l] for l in range(1, self.linecount + 5)]
        return rv

    def refine_linelocs_hsync(self):
        # Adjust line locations to end of HSYNC.
        # This causes issues for lines 1-9, where only the beginning is reliable :P

        err = [False] * len(self.linelocs1)

        linelocs2 = self.linelocs1.copy()
        for i in range(len(self.linelocs1)):
            # First adjust the lineloc before the beginning of hsync - 
            # lines 1-9 are half-lines which need a smaller offset
            if i < 9:
                linelocs2[i] -= 200 # search for *beginning* of hsync

            zc = calczc(self.data[0]['demod_05'], linelocs2[i], self.rf.iretohz(-20), reverse=False, _count=400)

            #print(i, linelocs2[i], zc)
            if zc is not None:
                linelocs2[i] = zc 

                if i >= 10:
                    # sanity check 0.5mhz filtered HSYNC and colo[u]r burst area

                    origdata_hsync = self.data[0]['demod_05'][int(zc-(self.rf.freq*1)):int(zc+(self.rf.freq*3))]
                    origdata_burst = self.data[0]['demod_05'][int(zc+(self.rf.freq*1)):int(zc+(self.rf.freq*3))]

                    if ((np.min(origdata_hsync) < self.rf.iretohz(-60) or np.max(origdata_hsync) > self.rf.iretohz(20)) or 
                           (np.min(origdata_burst) < self.rf.iretohz(-10) or np.max(origdata_burst) > self.rf.iretohz(10))):
                        err[i] = True
                    else:
                        # on some captures with high speed variation wow effects can mess up TBC.
                        # determine the low and high values and recompute zc along the middle

                        low = np.mean(origdata_hsync[0:20])
                        high = np.mean(origdata_hsync[100:120])

                        zc2 = calczc(origdata_hsync, 0, (low + high) / 2, reverse=False, _count=len(origdata_hsync))
                        zc2 += (int(zc)-(self.rf.freq*1))

                        if np.abs(zc2 - zc) < (self.rf.freq / 4):
                            linelocs2[i] = zc2 
                        else:
                            err[i] = True
            else:
                err[i] = True

            if i < 10:
                linelocs2[i] += self.usectoinpx(4.72)

            if i > 10 and err[i]:
                gap = linelocs2[i - 1] - linelocs2[i - 2]
                linelocs2[i] = linelocs2[i - 1] + gap

        # XXX: HACK!
        # On both PAL and NTSC this gets it wrong for VSYNC areas.  They need to be *reasonably* 
        # accurate for analog audio, but are never seen in the picture.
        for i in range(9, -1, -1):
            gap = linelocs2[i + 1] - linelocs2[i]
            if not inrange(gap, self.rf.linelen - (self.rf.freq * .2), self.rf.linelen + (self.rf.freq * .2)):
                gap = self.rf.linelen

            linelocs2[i] = linelocs2[i + 1] - gap

        # XXX2: more hack!  This one covers a bit at the end of a PAL field
        for i in range(len(linelocs2) - 10, len(linelocs2)):
            gap = linelocs2[i] - linelocs2[i - 1]
            if not inrange(gap, self.rf.linelen - (self.rf.freq * .2), self.rf.linelen + (self.rf.freq * .2)):
                gap = self.rf.linelen

            linelocs2[i] = linelocs2[i - 1] + gap


        return linelocs2, err   
    
    def downscale(self, lineoffset = 1, lineinfo = None, outwidth = None, wow=True, channel='demod', audio = False):
        if lineinfo is None:
            lineinfo = self.linelocs
        if outwidth is None:
            outwidth = self.outlinelen
            
        dsout = np.zeros((self.linecount * outwidth), dtype=np.double)    
        dsaudio = None

        sfactor = [None]

        for l in range(lineoffset, self.linecount + lineoffset):
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
                elif lc[0] == 15: # CAV frame code
                    frame = (lc[1] & 7) * 10000
                    frame += (lc[2] * 1000)
                    frame += (lc[3] * 100)
                    frame += (lc[4] * 10)
                    frame += lc[5] 
                    self.vbi['framenr'] = frame
                else:
                    h = lc[0] << 20
                    h |= lc[1] << 16
                    h |= lc[2] << 12
                    h |= lc[3] << 8
                    h |= lc[4] << 4
                    h |= lc[5] 
                    #print('%06x' % h)
                    
                    if lc[2] == 0xE: # seconds/frame goes here
                        self.vbi['seconds'] = (lc[1] - 10) * 10
                        self.vbi['seconds'] += lc[3]
                        self.vbi['clvframe'] = lc[4] * 10
                        self.vbi['clvframe'] += lc[5]
                        self.vbi['isclv'] = True
                        #print('clv ', self.seconds, self.clvframe)

                    htop = h >> 12
                    if htop == 0x8dc or htop == 0x8ba:
                        self.vbi['status'] = h
                    
                    if h == 0x87ffff:
                        self.vbi['isclv'] = True 

    # what you actually want from this:
    # decoded_field: downscaled field
    # burstlevels: 
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
            else:
                #print("too short", start, jumpto, self.vsyncs)
                pass
            
            return
        
        self.nextfieldoffset = self.peaklist[self.vsyncs[1][1]-10]
        
        self.istop = self.vsyncs[0][2]
        
        # On NTSC linecount is 262/263, PAL 312/313
        self.linecount = self.rf.SysParams['frame_lines'] // 2
        if self.istop:
            self.linecount += 1
        
        try:
            self.linelocs1 = self.compute_linelocs()
            self.linelocs2, self.errs2 = self.refine_linelocs_hsync()
        except:
            print('lineloc compute error')
            self.valid = False
            return

        self.linelocs = self.linelocs2
        
        # VBI info
        self.isclv = False
        self.linecode = {}
        self.framenr = None
        for l in self.rf.SysParams['philips_codelines']:
            self.linecode[l] = self.decodephillipscode(l)
            
        self.processphilipscode()
        
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
            pilot = self.data[0]['demod'][int(linelocs[l]-self.usectoinpx(4.7)):int(linelocs[l])].copy()
            pilot -= self.data[0]['demod_05'][int(linelocs[l]-self.usectoinpx(4.7)):int(linelocs[l])]
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
                        #print(i, pilot[i], zc, zcp, np.round(zcp) - zcp)

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
        #print(medianoffset)
        if inrange(medianoffset, 0.25, 0.75):
            tgt = .5
        else:
            tgt = 0

        for l in range(len(linelocs)):
            if offsets[l] != []:
                #print(l, np.median(offsets[l]), tgt - np.median(offsets[l]))
                adjustment = tgt - np.median(offsets[l])
                linelocs[l] += adjustment * (self.rf.freq / 3.75) * .25

        return linelocs    
    
    def downscale(self, final = False, *args, **kwargs):
        dsout, dsaudio = super(FieldPAL, self).downscale(lineoffset = 3, audio = final, *args, **kwargs)
        
        if final:
            reduced = (dsout - self.rf.SysParams['ire0']) / self.rf.SysParams['hz_ire']
            reduced -= self.rf.SysParams['vsync_ire']
            out_scale = np.double(0xd300 - 0x0100) / (100 - self.rf.SysParams['vsync_ire'])
            lines16 = np.uint16(np.clip((reduced * out_scale) + 256, 0, 65535) + 0.5)        
            
            self.dspicture = lines16
            return lines16, dsaudio
                    
        return dsout, dsaudio
    
    def __init__(self, *args, **kwargs):
        super(FieldPAL, self).__init__(*args, **kwargs)
        
        if not self.valid:
            return

        try:
            self.linelocs = self.refine_linelocs_pilot()
            self.downscale(wow = True, final=True)
        except:
            print("ERROR: Unable to decode frame, skipping")
            self.valid = False

# These classes extend Field to do PAL/NTSC specific TBC features.

class FieldNTSC(Field):

    def refine_linelocs_burst(self, linelocs2):
        hz_ire_scale = 1700000 / 140

        scaledburst, audio = self.downscale(outwidth=self.outlinelen, lineinfo=linelocs2, channel='demod_burst', lineoffset = 0)

        linelocs3 = linelocs2.copy()
        burstlevel = np.zeros_like(linelocs3, dtype=np.float32)

        # Compute the zero crossings first, and then determine if 
        # alignment should be to the nearest odd/even pixel.  Having a 2px
        # granularity seems to help (single frame) quality but may have issues
        # later on... :P

        phaseaverages = np.zeros([len(linelocs2), 2], dtype=np.double)

        for l in range(self.linecount):
            # Since each line is lined up to the beginning of HSYNC and this is 4fsc,
            # we can scan the burst area explicitly (~0.6 to ~2.9usec)
            ba = scaledburst[(self.outlinelen*l)+20:self.outlinelen*(l+0)+60].copy()
            ba -= np.mean(ba)
            burstlevel[l] = np.max(np.abs(ba))
            #print(l, burstlevel[l], np.std(ba) / hz_ire_scale)

            # max should be 20.  if there are any pixels > 30 there's probably a rot-spike
            if ((burstlevel[l] / hz_ire_scale) > 30) or (np.std(ba) / hz_ire_scale) < 3:
                burstlevel[l] = 0
                continue

            # True:  hi->low, False: low->hi
            burstoffsets = {False: [], True:[]}

            bi = 0
            while bi < len(ba):
                if np.abs(ba[bi]) > burstlevel[l] * .6:
                    zc = calczc(ba, bi, 0)

                    if zc is not None:
                        offset = zc - ((np.floor(zc/4)*4) - 1)
                        if offset > 3.5:
                            offset -= 4
                        burstoffsets[ba[bi] > 0].append(offset)
                        bi = np.int(zc)

                bi += 1

            if len(burstoffsets[False]) < 3 or len(burstoffsets[True]) < 3:
                continue

            # Chop the first and last bursts since their phase can be off
            for v in [False, True]:
                burstoffsets[v] = np.array(burstoffsets[v][1:-1])

            # deal with the 180 degree per-line shift here, then choose the closer group to 2.
            if l % 2:
                phaseaverages[l] = (2 - np.mean(burstoffsets[True]), 2 - np.mean(burstoffsets[False]))
            else:
                phaseaverages[l] = (2 - np.mean(burstoffsets[False]), 2 - np.mean(burstoffsets[True]))

        # need to remove lines with no/bad colorburst to compute medians
        phaseaverages_cut = phaseaverages[np.logical_or(phaseaverages[:,0] != 0, phaseaverages[:,1] != 0)]
        if np.abs(np.median(phaseaverages_cut[:,0])) < np.abs(np.median(phaseaverages_cut[:,1])):
            phasegroup = 0
        else:
            phasegroup = 1

        adjset = phaseaverages[:,phasegroup]
        burstlevel[phasegroup::2] = -burstlevel[phasegroup::2]

        for l in range(len(linelocs3)):
            if np.abs(adjset[l]) > 2:
                burstlevel[l] = 0
                continue

            linelocs3[l] -= adjset[l] * (self.rf.freq / (4 * 315 / 88)) * 1

        for l in range(2, len(linelocs3) - 1):
            if burstlevel[l] == 0:
                linelocs3[l] = (linelocs3[l - 1] + linelocs3[l + 1]) / 2

        return np.array(linelocs3), burstlevel#, phaseaverages

    def downscale(self, lineoffset = 1, final = False, *args, **kwargs):
        dsout, dsaudio = super(FieldNTSC, self).downscale(lineoffset = lineoffset, audio = final, *args, **kwargs)
        
        if final:
            reduced = (dsout - self.rf.SysParams['ire0']) / self.rf.SysParams['hz_ire']
            reduced -= self.rf.SysParams['vsync_ire']
            out_scale = np.double(0xc800 - 0x0400) / (100 - self.rf.SysParams['vsync_ire'])
            lines16 = np.uint16(np.clip((reduced * out_scale) + 1024, 0, 65535) + 0.5)        

            if self.burstlevel is not None:
                for i in range(1, self.linecount - 1):
                    hz_ire_scale = 1700000 / 140
                    if self.burstlevel[i] > 0:
                        lines16[((i + 0) * self.outlinelen)] = 16384
                    else:
                        lines16[((i + 0) * self.outlinelen)] = 32768

                    clevel = (1/self.colorlevel)/ hz_ire_scale

                    lines16[((i + 0) * self.outlinelen) + 1] = np.uint16(327.67 * clevel * np.abs(self.burstlevel[i]))

            self.dspicture = lines16
            return lines16, dsaudio
                    
        return dsout, dsaudio
    
    def apply_offsets(self, linelocs, phaseoffset, picoffset = 0):
        return np.array(linelocs) + picoffset + (phaseoffset * (self.rf.freq / (4 * 315 / 88)))

    #def __init__(self, colorphase = -63, colorlevel = 1.17, *args, **kwargs):
    def __init__(self, *args, **kwargs):
        self.burstlevel = None

        # HE010
        self.colorphase = 90+1.5 # colorphase
        self.colorlevel = 1.45 # colorlevel

        super(FieldNTSC, self).__init__(*args, **kwargs)
        
        if not self.valid:
            print('not valid')
            return

        try:

            # This needs to be run twice to get optimal burst levels
            self.linelocs3, self.burstlevel = self.refine_linelocs_burst(self.linelocs2)
            self.linelocs4, self.burstlevel = self.refine_linelocs_burst(self.linelocs3)

            # Now adjust 33 degrees (-90 - 33) for color decoding
            shift33 = self.colorphase * (np.pi / 180)
            self.linelocs = self.apply_offsets(self.linelocs4, shift33 - 8)
        
            self.downscale(wow = True, final=True)
        except:
            print("ERROR: Unable to decode frame, skipping")
            self.valid = False

class Framer:
    def readfield(self, infile, sample, fieldcount = 0):
        readsample = sample
        
        while True:
            if isinstance(infile, io.IOBase):
                rawdecode = self.rf.demod(infile, readsample, self.readlen)
                if rawdecode is None:
                    return None, None, None
                
                f = self.FieldClass(self.rf, rawdecode, 0, audio_offset = self.audio_offset)
                nextsample = readsample + f.nextfieldoffset
                if not f.valid:
                    if rawdecode is None:
                        return None, None, None
                    elif len(f.peaklist) < 100: 
                        # No recognizable data - jump 10 seconds to get past possible spinup
                        nextsample = readsample + (self.rf.freq_hz * 10)
                    elif len(f.vsyncs) == 0:
                        nextsample = readsample + (self.rf.freq_hz * 1)
            else:
                f = self.FieldClass(self.rf, infile, readsample)
                nextsample = f.nextfieldoffset
                if not f.valid and len(f.vsyncs) == 0:
                    nextsample = readsample + self.rf.freq_hz
                    #return None, None
            
            if not f.valid:
                readsample = nextsample # f.nextfieldoffset
            else:
                return f, readsample, nextsample # readsample + f.nextfieldoffset
        
    def mergevbi(self, fields):
        vbi_merged = copy.copy(fields[0].vbi)
        for k in vbi_merged.keys():
            if fields[1].vbi[k] is not None:
                vbi_merged[k] = fields[1].vbi[k]
                
        if vbi_merged['seconds'] is not None:
            vbi_merged['framenr'] = vbi_merged['minutes'] * 60 * self.clvfps
            vbi_merged['framenr'] += vbi_merged['seconds'] * self.clvfps
            vbi_merged['framenr'] += vbi_merged['clvframe']
                
        return vbi_merged
    
    def formatoutput(self, fields):
        linecount = (min(fields[0].linecount, fields[1].linecount) * 2) - 0

        combined = np.zeros((self.outwidth * self.outlines), dtype=np.uint16)
        for i in range(0, linecount, 2):
            curline = (i // 2) + 0
            combined[((i + 0) * self.outwidth):((i + 1) * self.outwidth)] = fields[0].dspicture[curline * fields[0].outlinelen: (curline * fields[0].outlinelen) + self.outwidth]
            combined[((i + 1) * self.outwidth):((i + 2) * self.outwidth)] = fields[1].dspicture[curline * fields[0].outlinelen: (curline * fields[0].outlinelen) + self.outwidth]

        # copy in the halfline.  bit hackish but so is the idea of a visible halfline ;)
        lf = np.argmax([fields[0].linecount, fields[1].linecount])
        curline = (linecount // 2) + 0
        combined[(linecount * self.outwidth):((linecount + 1) * self.outwidth)] = fields[lf].dspicture[curline * fields[0].outlinelen: (curline * fields[0].outlinelen) + self.outwidth]
            
        return combined
    
    def readframe(self, infile, sample, firstframe = False, CAV = False):
        fieldcount = 0
        fields = [None, None]
        audio = []
        
        jumpto = 0
        while fieldcount < 2:
            f, readsample, nextsample = self.readfield(infile, sample, fieldcount)
            if f is not None:
                print(sample, nextsample, f is not None, f.istop)
            else:
                print(sample, nextsample, f is not None)
            
            if f is not None:
                if f.istop:
                    fields[0] = f
                else:
                    fields[1] = f
                    
                if ((not CAV and (f.istop == self.rf.SysParams['topfirst'])) or 
                   (CAV and (f.vbi['framenr'] or f.vbi['minutes']))):
                    fieldcount = 1
                    firstsample = f.tbcstart + readsample
                elif fieldcount == 1:
                    fieldcount = 2

                if (fieldcount or not firstframe) and f.dsaudio is not None:
                    audio.append(f.dsaudio)
            elif readsample is None:
                return None, None, None, None
            
            sample = nextsample
        
        if len(audio):
            conaudio = np.concatenate(audio)
            self.audio_offset = f.audio_next_offset
        else:
            conaudio = None
        
        if self.full_decode:
            combined = self.formatoutput(fields)
        else:
            combined = None
            
        self.vbi = self.mergevbi(fields)

        return combined, conaudio, sample, fields #, audio

    def __init__(self, rf, full_decode = True):
        self.rf = rf
        self.full_decode = full_decode

        if self.rf.system == 'PAL':
            self.FieldClass = FieldPAL
            self.readlen = 1000000
            self.outlines = 625
            self.clvfps = 25
        else:
            self.FieldClass = FieldNTSC
            self.readlen = 1000000
            self.outlines = 525
            self.clvfps = 30
            
        if not self.full_decode:
            self.FieldClass = Field
        
        self.outwidth = self.rf.SysParams['outlinelen']
        self.audio_offset = 0

# Helper functions that rely on the classes above go here

def findframe(infile, rf, target, nextsample = 0):
    ''' Locate the sample # of the target frame. '''
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
