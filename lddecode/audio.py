#!/usr/bin/python3
import argparse
import copy
import itertools
import sys
import threading
import time

from multiprocessing import Process, Queue, JoinableQueue, Pipe

# standard numeric/scientific libraries
import numpy as np
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

# internal libraries

# XXX: figure out how to handle these module imports better for vscode imports
try:
    import efm_pll
except ImportError:
    from lddecode import efm_pll

try:
    import core
except ImportError:
    from lddecode import core

try:
    import utils
except ImportError:
    from lddecode import utils

try:
    import utils_logging 
except ImportError:
    from lddecode import utils_logging

try:
    # If Anaconda's numpy is installed, mkl will use all threads for fft etc
    # which doesn't work when we do more threads, do disable that...
    import mkl

    mkl.set_num_threads(1)
except ImportError:
    # If not running Anaconda, we don't care that mkl doesn't exist.
    pass

# Command line front end code

def handle_options(argstring = sys.argv):
    options_epilog = """foof"""

    parser = argparse.ArgumentParser(
        description="Extracts audio from raw/TBC'd RF laserdisc captures",
    #    epilog=options_epilog,
    )

    # This is -i instead of a positional, since the first pos can't be overridden
    parser.add_argument("-i", dest="infile", default='-', type=str, help="source file (must be signed 16-bit)")

    parser.add_argument("-o", dest="outfile", default='test', type=str, help="base name for destination files")
    
    parser.add_argument("-f", "--freq", dest='freq', default = "40.0mhz", type=str, help="Input frequency")
    
    parser.add_argument(
        "--PAL",
        "-p",
        "--pal",
        dest="pal",
        action="store_true",
        help="source is in PAL format",
    )

    parser.add_argument(
        "--NTSC", "-n", "--ntsc", dest="ntsc", action="store_true", help="source is in NTSC format"
    )

    parser.add_argument(
        "--noEFM",
        dest="noefm",
        action="store_true",
        default=False,
        help="Disable EFM front end",
    )

    parser.add_argument(
        "--preEFM",
        dest="prefm",
        action="store_true",
        default=False,
        help="Write filtered but otherwise pre-processed EFM data",
    )
    
    args = parser.parse_args(argstring[1:])

    if args.pal and (args.ntsc or args.ntscj):
        print("ERROR: Can only be PAL or NTSC")
        exit(1)

    args.vid_standard = "PAL" if args.pal else "NTSC"
    
    return args

testmode = False
if testmode:
    args = handle_options(['--NTSC', '-i', '../ggvsweep1.tbc.r16'])
    #args = handle_options(['--NTSC', '-i', '../ggv_1khz_4p.tbc.r16'])
else:
    args = handle_options(sys.argv)

if args.infile == '-':
    in_fd = sys.stdin
else:
    in_fd = open(args.infile, 'rb')

if args.outfile == '-':
    out_fd = sys.stdin
else:
    out_fd = open(args.outfile + '.pcm32', 'wb')
    
# Common top-level code
logger = utils_logging.init_logging(None)

# Set up SysParams to hand off to needed sub-tasks
SysParams = core.SysParams_PAL if args.vid_standard == 'PAL' else core.SysParams_NTSC

freq = utils.parse_frequency(args.freq)
SysParams['freq'] = freq
SysParams['freq_hz'] = freq * 1.0e6
SysParams['freq_hz'] = SysParams['freq_hz'] / 2

SysParams['audio_filterwidth'] = 150000

SysParams['blocklen'] = 65536
# We need to drop the beginning of each block
SysParams['blocklen_drop'] = 4096

from functools import partial

SP = SysParams

blocklen = SysParams['blocklen']
blockskip = SysParams['blocklen_drop']

afilt_len = 512

freq = utils.parse_frequency(args.freq)
freq_hz = (freq * 1.0e6)
freq_hz_half = freq_hz / 2

apass = 150000 #SysParams['audio_filterwidth']
audio_lfilt_full = utils.filtfft([sps.firwin(afilt_len, [(SP['audio_lfreq']-apass)/freq_hz_half, (SP['audio_lfreq']+apass)/freq_hz_half], pass_zero=False), 1.0], blocklen)
audio_rfilt_full = utils.filtfft([sps.firwin(afilt_len, [(SP['audio_rfreq']-apass)/freq_hz_half, (SP['audio_rfreq']+apass)/freq_hz_half], pass_zero=False), 1.0], blocklen)

lowbin, nbins, a1_freq = utils.fft_determine_slices(SP['audio_lfreq'], 150000, freq_hz, blocklen)
hilbert = utils.build_hilbert(nbins)
left_slicer = lambda x: utils.fft_do_slice(x, lowbin, nbins, blocklen)
#left_slicer = partial(utils.fft_do_slice, lowbin=lowbin, nbins=nbins, blocklen=blocklen)
left_filter = left_slicer(audio_lfilt_full) * hilbert

lowbin, nbins, a1_freq = utils.fft_determine_slices(SP['audio_rfreq'], 150000, freq_hz, blocklen)
hilbert = utils.build_hilbert(nbins)
right_slicer = lambda x: utils.fft_do_slice(x, lowbin, nbins, blocklen)
#right_slicer = partial(utils.fft_do_slice, lowbin=lowbin, nbins=nbins, blocklen=blocklen)
right_filter = right_slicer(audio_rfilt_full) * hilbert

# Compute stage 2 audio filters: 20k-ish LPF and deemp

audio2_lpf_b = sps.firwin(512, [22000/(a1_freq/2)], pass_zero=True)
audio2_lpf = utils.filtfft([audio2_lpf_b, 1.0], blocklen)
#audio2_deemp = utils.filtfft(utils.emphasis_iir(-20e-6, 75e-6, a1_freq), blocklen)
# XXX: the first value here is all wrong.
audio2_deemp = utils.filtfft(utils.emphasis_iir(-7e-6, 75e-6, a1_freq), blocklen)

audio2_filter = audio2_lpf * audio2_deemp


aa_channels = []

if True:
    aa_channels.append(('left', 'audio_lfreq'))
    
if True:
    aa_channels.append(('right', 'audio_rfreq'))

low_freq = {}
filt1 = {}
filt1f = {}
audio1_buffer = {}

for ch in aa_channels:
    cname = ch[0]
    afreq = SP[ch[1]]
    
    audio1_fir = utils.filtfft([sps.firwin(afilt_len, [(afreq-apass)/freq_hz_half, (afreq+apass)/freq_hz_half], pass_zero=False), 1.0], blocklen)
    lowbin, nbins, audio1_freq = utils.fft_determine_slices(afreq, 150000, freq_hz, blocklen)
    hilbert = utils.build_hilbert(nbins)

    # Add the demodulated output to this to get actual freq
    low_freq[cname] = freq_hz * (lowbin / blocklen)
    
    slicer = lambda x: utils.fft_do_slice(x, lowbin, nbins, blocklen)
    #left_slicer = partial(utils.fft_do_slice, lowbin=lowbin, nbins=nbins, blocklen=blocklen)
    filt1[cname] = slicer(audio1_fir) * hilbert
    filt1f[cname] = audio1_fir * utils.build_hilbert(blocklen)
    
    audio1_buffer[cname] = utils.StridedCollector(blocklen, blockskip)

audio1_clip = blockskip // (blocklen // nbins)

# Have input_buffer store 8-bit bytes, then convert afterwards
input_buffer = utils.StridedCollector(blocklen*2, blockskip*2)

def proc1(data_in):
    fft_in = npfft.fft(data_in)

    for ch in aa_channels:
        a1 = npfft.ifft(slicer(fft_in) * filt1[ch[0]])
        a1u = utils.unwrap_hilbert(a1, audio1_freq)
        a1u = a1u[audio1_clip:]

        audio1_buffer[ch[0]].add(a1u)
        
    return audio1_buffer[ch[0]].have_block()

def proc2():
    output = []
    inputs = []
    
    for ch in aa_channels:
        a2_in = audio1_buffer[ch[0]].get_block()
        a2_fft = npfft.fft(a2_in)
        inputs.append(a2_fft)
        a2 = npfft.ifft(a2_fft * audio2_filter)
        output.append(utils.sqsum(a2[blockskip:]))
        
    return inputs, output    

inputs = []
output = []
allout = []

while True:
#for x in range(5000):
    inbuf = in_fd.read(65536)
    if len(inbuf) == 0:
        break
        
    # store the input buffer as a raw 8-bit data, then repack into 16-bit
    # (this allows reading of an odd # of bytes)
    input_buffer.add(np.frombuffer(inbuf, 'int8', len(inbuf)))
    
    while input_buffer.have_block():
        buf = input_buffer.get_block()
        b = buf.tobytes()
        s16 = np.frombuffer(b, 'int16', len(b)//2)

        if proc1(s16):
            infft, outputs = proc2()
            inputs.append(infft)
            allout.append(outputs)
            
            oleft = outputs[0] + low_freq['left'] - SP['audio_lfreq']
            olefts32 = np.clip(oleft, -150000, 150000) * (2**31 / 150000)
            
            if len(outputs) == 2:
                oright = outputs[1] + low_freq['right'] - SP['audio_rfreq']
                orights32 = np.clip(oright, -150000, 150000) * (2**31 / 150000)
                
                outdata = np.zeros(len(olefts32) * 2, dtype=np.int32)
                outdata[0::2] = olefts32
                outdata[1::2] = orights32
            else:
                outdata = np.array(olefts32, dtype=np.int32)
                
            out_fd.write(outdata)

            