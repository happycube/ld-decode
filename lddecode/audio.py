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
        "--disable_analog_audio",
        "--disable_analogue_audio",
        "--daa",
        dest="daa",
        action="store_true",
        default=False,
        help="Disable analog(ue) audio decoding",
    )

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
    out_fd = sys.stdout
    args.prefm = False
    efm_decode = False
else:
    if not args.daa:
        out_fd = open(args.outfile + '.pcm32', 'wb')

    if args.prefm:
        rawefm_fd = open(args.outfile + '.prefm', 'wb')
    else:
        args.prefm = False

    efm_decode = not args.noefm
    if efm_decode:
        efm_pll = efm_pll.EFM_PLL()
        efm_fd = open(args.outfile + '.efm', 'wb')

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
# We need to drop the beginning (and end) of each block
SysParams['blocklen_dropb'] = 4096-512
SysParams['blocklen_drope'] = 512

from functools import partial

SP = SysParams

blocklen = SysParams['blocklen']
blockskip = SysParams['blocklen_dropb'] + SysParams['blocklen_drope']
dropb = SysParams['blocklen_dropb']
drope = SysParams['blocklen_drope']

afilt_len = 512

freq = utils.parse_frequency(args.freq)
freq_hz = (freq * 1.0e6)
freq_hz_half = freq_hz / 2

def audio_bandpass_butter(center, closerange = 125000, longrange = 180000):
    #center = SP['audio_lfreq']
    freqs_inner = [(center - closerange) / freq_hz_half, (center + closerange) / freq_hz_half]
    freqs_outer = [(center - longrange) / freq_hz_half, (center + longrange) / freq_hz_half]
    N, Wn = sps.buttord(freqs_inner, freqs_outer, 1, 15)
    return sps.butter(N, Wn, btype='bandpass')

audio_lfilt_full = utils.filtfft(audio_bandpass_butter(SP['audio_lfreq']), blocklen)
audio_rfilt_full = utils.filtfft(audio_bandpass_butter(SP['audio_rfreq']), blocklen)

lowbin, nbins, a1_freq = utils.fft_determine_slices(SP['audio_lfreq'], 200000, freq_hz, blocklen)
hilbert = utils.build_hilbert(nbins)
left_slicer = lambda x: utils.fft_do_slice(x, lowbin, nbins, blocklen)
#left_slicer = partial(utils.fft_do_slice, lowbin=lowbin, nbins=nbins, blocklen=blocklen)
left_filter = left_slicer(audio_lfilt_full) * hilbert

lowbin, nbins, a1_freq = utils.fft_determine_slices(SP['audio_rfreq'], 200000, freq_hz, blocklen)
hilbert = utils.build_hilbert(nbins)
right_slicer = lambda x: utils.fft_do_slice(x, lowbin, nbins, blocklen)
#right_slicer = partial(utils.fft_do_slice, lowbin=lowbin, nbins=nbins, blocklen=blocklen)
right_filter = right_slicer(audio_rfilt_full) * hilbert

# Compute stage 2 audio filters: 20k-ish LPF and deemp

N, Wn = sps.buttord(20000 / (a1_freq / 2), 24000 / (a1_freq / 2), 1, 9)
audio2_lpf = utils.filtfft(sps.butter(N, Wn), blocklen)
# 75e-6 is 75usec/2133khz (matching American FM emphasis) and 5.3e-6 is approx
# a 30khz break frequency
audio2_deemp = utils.filtfft(utils.emphasis_iir(5.3e-6, 75e-6, a1_freq), blocklen)

audio2_filter = audio2_lpf * audio2_deemp

def computeefmfilter():
    """Frequency-domain equalisation filter for the LaserDisc EFM signal.
    This was inspired by the input signal equaliser in WSJT-X, described in
    Steven J. Franke and Joseph H. Taylor, "The MSK144 Protocol for
    Meteor-Scatter Communication", QEX July/August 2017.
    <http://physics.princeton.edu/pulsar/k1jt/MSK144_Protocol_QEX.pdf>

    This improved EFM filter was devised by Adam Sampson (@atsampson)
    """
    # Frequency bands
    freqs = np.linspace(0.0e6, 2.0e6, num=11)
    freq_per_bin = freq_hz / blocklen
    # Amplitude and phase adjustments for each band.
    # These values were adjusted empirically based on a selection of NTSC and PAL samples.
    amp = np.array([0.0, 0.2, 0.41, 0.73, 0.98, 1.03, 0.99, 0.81, 0.59, 0.42, 0.0])
    phase = np.array(
        [0.0, -0.95, -1.05, -1.05, -1.2, -1.2, -1.2, -1.2, -1.2, -1.2, -1.2]
    )
    coeffs = None

    """Compute filter coefficients for the given FFTFilter."""
    # Anything above the highest frequency is left as zero.
    coeffs = np.zeros(blocklen, dtype=np.complex)

    # Generate the frequency-domain coefficients by cubic interpolation between the equaliser values.
    a_interp = spi.interp1d(freqs, amp, kind="cubic")
    p_interp = spi.interp1d(freqs, phase, kind="cubic")

    nonzero_bins = int(freqs[-1] / freq_per_bin) + 1

    bin_freqs = np.arange(nonzero_bins) * freq_per_bin
    bin_amp = a_interp(bin_freqs)
    bin_phase = p_interp(bin_freqs)

    # Scale by the amplitude, rotate by the phase
    coeffs[:nonzero_bins] = bin_amp * (
        np.cos(bin_phase) + (complex(0, -1) * np.sin(bin_phase))
    )

    return coeffs * 8

efm_filter = computeefmfilter()

aa_channels = []

if True:
    aa_channels.append(('left', 'audio_lfreq'))
    
if True:
    aa_channels.append(('right', 'audio_rfreq'))

low_freq = {}
filt1 = {}
filt1f = {}
audio1_buffer = {}

apass = 150000 #SysParams['audio_filterwidth']

for ch in aa_channels:
    cname = ch[0]
    afreq = SP[ch[1]]
    
    audio1_fir = utils.filtfft([sps.firwin(afilt_len, [(afreq-apass)/freq_hz_half, (afreq+apass)/freq_hz_half], pass_zero=False), 1.0], blocklen)
    lowbin, nbins, audio1_freq = utils.fft_determine_slices(afreq, 200000, freq_hz, blocklen)
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

def proc1(fft_in):
    for ch in aa_channels:
        a1 = npfft.ifft(slicer(fft_in) * filt1[ch[0]])
        a1u = utils.unwrap_hilbert(a1, audio1_freq)
        a1u = a1u[audio1_clip:]

        audio1_buffer[ch[0]].add(a1u)
        
    return fft_in

def proc2():
    output = []
    inputs = []
    
    for ch in aa_channels:
        a2_in = audio1_buffer[ch[0]].get_block()
        a2_fft = npfft.fft(a2_in)
        inputs.append(a2_fft)
        a2 = npfft.ifft(a2_fft * audio2_filter)
        output.append(utils.sqsum(a2[dropb:-drope]))
        
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

        fft_in = npfft.fft(s16)

        if not args.daa:
            proc1(fft_in)

            if audio1_buffer['left'].have_block():
                infft, outputs = proc2()

                if testmode:
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

        if efm_decode:
            filtered_efm = npfft.ifft(fft_in * efm_filter)[dropb:-drope]
            filtered_efm2 = np.int16(np.clip(filtered_efm.real, -32768, 32767))

            if args.prefm:
                rawefm_fd.write(filtered_efm2.tobytes())

            efm_out = efm_pll.process(filtered_efm2)
            #print(efm_out.shape, max(filtered_efm.imag))
            efm_fd.write(efm_out.tobytes())
            