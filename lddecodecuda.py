#!/usr/bin/python3.5

#from __future__ import division
#from __future__ import print_function

import numpy as np
import scipy as sp
import scipy.signal as sps
import scipy.fftpack as fftpack 
import matplotlib.pyplot as plt
import sys
import getopt

from datetime import  datetime

import fft8 as fft8 
import ld_utils as utils

import pycuda.autoinit
import pycuda.driver as drv
import pycuda.gpuarray as gpuarray
from pycuda.compiler import SourceModule

import skcuda.fft as fft
#import skcuda.misc as misc
    
#import cProfile

import copy

pi = np.pi
tau = np.pi * 2

freq = (315.0 / 88.0) * 8.00
freq_hz = freq * 1000000.0

afreq = freq / 8.0
afreq_hz = afreq * 1000000.0

blocklenk = 512 
blocklen = (blocklenk * 1024)  

ablocklenk = blocklenk//4 
ablocklen = (ablocklenk * 1024)  

# These are NTSC defaults.  They may be reprogrammed before starting
SysParams_NTSC = {
	'analog_audio': True, # not true for later PAL
	'audio_lfreq': 2301136,
	'audio_rfreq': 2812499,

	'fsc_mhz': (315.0 / 88.0),

	# video frequencies 
	'videorf_sync': 7600000,
	'videorf_0ire': 8100000,
	'videorf_100ire': 9300000, # slightly higher on later disks

	'ire_min': -60,
	'ire_max': 140,

	# changeable defaults
	'deemp': (.825, 2.35),

	'vbpf': (3200000, 14000000),
	'vlpf_freq': 4400000,	# in mhz
	'vlpf_order': 5		# butterworth filter order
}

SysParams_PAL = {
	'analog_audio': False, # not true for later PAL
	'audio_lfreq': 683593,
	'audio_rfreq': 1066400,

	'fsc_mhz': 4.43361875,

	# video frequencies 
	#'videorf_sync': 7600000,
	'videorf_0ire': 7100000,
	'videorf_100ire': 8000000,

	'ire_min': -95,
	'ire_max': 145,

	# changeable defaults
	'deemp': (.7, 4.0),

	# XXX: guessing here!
	'vbpf': (2200000, 11000000),

	'vlpf_freq': 5500000,	# in mhz
	'vlpf_order': 8		# butterworth filter order
}

# support reloading/rerunning from ipython
try:
	tmp = SysParams['fsc_mhz']
except:
	SysParams = copy.deepcopy(SysParams_NTSC)

# from http://tlfabian.blogspot.com/2013/01/implementing-hilbert-90-degree-shift.html
hilbert_filter = np.fft.fftshift(
    np.fft.ifft([0]+[1]*200+[0]*200)
    #np.fft.ifft([0]+[1]*(blocklen//4)+[0]*(blocklen//4))
)
fft_hilbert = np.fft.fft(hilbert_filter, blocklen)

mod = SourceModule("""
#include <cuComplex.h>

__global__ void anglediff(float *out, cuComplex *in) {
	const int i = threadIdx.x  + blockIdx.x * blockDim.x; // + (1024 * threadIdx.y);
	
	float tmp = atan2f(in[i + 1].y, in[i + 1].x) - atan2f(in[i].y, in[i].x);
	
	out[i] = (tmp >= 0) ? tmp : tmp + (3.14159265359 * 2);
}

__global__ void clamp16(unsigned short *y, float *x, float offset, float mul) {
	const int i = threadIdx.x  + blockIdx.x * blockDim.x; // + (1024 * threadIdx.y);

	float tmp = x[i];
	
	tmp += offset;
	tmp *= mul;

	y[i] = (unsigned short)max((float)0, min((float)65535, tmp));
}

__global__ void anglediff_mac(float *out, cuComplex *in, float mult, float add) {
	const int i = threadIdx.x  + blockIdx.x * blockDim.x; // + (1024 * threadIdx.y);
	
	float tmp = atan2f(in[i + 1].y, in[i + 1].x) - atan2f(in[i].y, in[i].x);
	
	tmp = (tmp >= 0) ? tmp : tmp + (3.14159265359 * 2);
	tmp *= mult;
	tmp += add;
	out[i] = max((float)-200000, min((float)200000, tmp));
}

__global__ void audioscale(float *out, float *in_left, float *in_right, float s, float offset)
{
	const int i = (threadIdx.x  + blockIdx.x * blockDim.x);

	int index = (s * i) + offset;

	out[i * 2] = in_left[index];
	out[(i * 2)+ 1] = in_right[index];
}

""")

def FFTtoGPU(fft):
	return gpuarray.to_gpu((np.complex64(fft))[0:len(fft)//2])

Inner = 0

# CUDA structures
cs_first = True
cs = {} 

def filtfft(filt, blen = blocklen):
	return sps.freqz(filt[0], filt[1], blen, whole=1)[1]

def prepare_video_filters(SP):
	# TODO:  test these CLV+innerCAV parameters.  Should be same on PAL+NTSC 
	t1 = 25
	t2 = 13.75
	
	[tf_b, tf_a] = sps.zpk2tf(-t2*(10**-8), -t1*(10**-8), t1 / t2)
	Femp = filtfft(sps.bilinear(tf_b, tf_a, 1/(freq_hz/2)))

	# RF BPF and analog audio cut filters
	Fbpf = filtfft(sps.butter(1, [SP['vbpf'][0]/(freq_hz/2), SP['vbpf'][1]/(freq_hz/2)], btype='bandpass'))

	# standard post-demod LPF
	Fplpf = filtfft(sps.butter(SP['vlpf_order'], SP['vlpf_freq']/(freq_hz/2), 'low'))
	
	# post-demod deemphasis filter
	[tf_b, tf_a] = sps.zpk2tf(-SP['deemp'][1]*(10**-8), -SP['deemp'][0]*(10**-8), SP['deemp'][0] / SP['deemp'][1])
	Fdeemp = filtfft(sps.bilinear(tf_b, tf_a, 1.0/(freq_hz/2)))

	SP['fft_video'] = Fbpf * fft_hilbert

	if SP['analog_audio'] == True:
		Fcutl = filtfft(sps.butter(1, [(SP['audio_lfreq'] - 750000)/(freq_hz/2), (SP['audio_lfreq'] + 750000)/(freq_hz/2)], btype='bandstop'))
		Fcutr = filtfft(sps.butter(1, [(SP['audio_rfreq'] - 750000)/(freq_hz/2), (SP['audio_rfreq'] + 750000)/(freq_hz/2)], btype='bandstop'))
		# if AC3:
		#SP['f_arightcut'] = sps.butter(1, [(2650000)/(freq_hz/2), (3150000)/(freq_hz/2)], btype='bandstop')

		SP['fft_video'] *= (Fcutl * Fcutr)
	
	SP['fft_video_inner'] = SP['fft_video'] * Femp

	# Post processing:  lowpass filter + deemp
	SP['fft_post'] = Fplpf * Fdeemp	

	# determine freq offset and mult for output stage	
	hz_ire_scale = (SP['videorf_100ire'] - SP['videorf_0ire']) / 100
	minn = SP['videorf_0ire'] + (hz_ire_scale * -60)
	SP['output_minfreq'] = sminn = minn / (freq_hz / tau)

	out_scale = 65534.0 / (SP['ire_max'] - SP['ire_min'])
	SP['output_scale'] = (freq_hz / tau) * (out_scale / hz_ire_scale)

def prepare_video_cuda():
	# Things go *a lot* faster when you have the memory structures pre-allocated
	cs['plan1'] = fft.Plan(blocklen, np.float32, np.complex64)
	cs['plan1i'] = fft.Plan(blocklen, np.complex64, np.complex64)
	
	cs['fft1_out'] = gpuarray.empty((blocklen//2)+1, np.complex64)

	cs['filtered1'] = gpuarray.empty(blocklen, np.complex64)
	cs['fm_demod'] = gpuarray.empty(blocklen, np.float32)

	cs['postlpf'] = gpuarray.empty(blocklen, np.float32)

	cs['fft2_out'] = gpuarray.empty((blocklen//2)+1, np.complex64)
	
	cs['clipped_gpu'] = gpuarray.empty(blocklen, np.uint16)
	
	cs['plan2'] = fft.Plan(blocklen, np.float32, np.complex64)
	cs['plan2i'] = fft.Plan(blocklen, np.complex64, np.float32)

	# CUDA functions.  The fewer setups we need, the faster it goes.	
	cs['doclamp16'] = mod.get_function("clamp16")
	cs['doanglediff'] = mod.get_function("anglediff")

	# GPU-stored frequency-fomain filters
	cs['filt_post'] = FFTtoGPU(SysParams['fft_post'])
	cs['filt_video'] = FFTtoGPU(SysParams['fft_video'])
	cs['filt_video_inner'] = FFTtoGPU(SysParams['fft_video_inner'])

def process_video_cuda(data):
	global cs, cs_first 
#	fft_overlap(data, FiltV_GPU) 

	if cs_first == True:
		prepare_video_filters(SysParams)
		prepare_video_cuda()
		cs_first = False

	fdata = np.float32(data)

	gpudata = gpuarray.to_gpu(fdata)

	# first fft->ifft cycle applies pre-decoding filtering (low pass filters, CAV/CLV emphasis)
	# and very importantly, performs the Hilbert transform
	fft.fft(gpudata, cs['fft1_out'], cs['plan1'])

	if Inner:	
		cs['fft1_out'] *= cs['filt_video_inner']
	else:
		cs['fft1_out'] *= cs['filt_video']
	
	fft.ifft(cs['fft1_out'], cs['filtered1'], cs['plan1i'], True)

	cs['doanglediff'](cs['fm_demod'], cs['filtered1'], block=(1024,1,1), grid=(blocklenk,1))

	# post-processing:  output low-pass filtering and deemphasis	
	fft.fft(cs['fm_demod'], cs['fft2_out'], cs['plan2'])
	cs['fft2_out'] *= cs['filt_post'] 
	fft.ifft(cs['fft2_out'], cs['postlpf'], cs['plan2i'], True)

	cs['doclamp16'](cs['clipped_gpu'], cs['postlpf'], np.float32(-SysParams['output_minfreq']), np.float32(SysParams['output_scale']), block=(1024,1,1), grid=(blocklenk,1)) 

	output_16 = cs['clipped_gpu'].get()

	chop = 512
	return output_16[chop:len(output_16)-chop]

# graph for debug

#	plt.plot(cs['postlpf'].get()[5000:7500])
	plt.plot(output_16[5000:7000])
#	plt.plot(range(0, len(output_16)), output_16)
#	plt.plot(range(0, len(doutput)), doutput)
#	plt.plot(range(0, len(output_prefilt)), output_prefilt)
	plt.show()
	exit()

csa_first = True
csa = {} 

def prepare_audio_filters():
	tf_rangel = 100000
	tf_rangeh = 170000

	# audio filters
	tf = SysParams['audio_lfreq']
	N, Wn = sps.buttord([(tf-tf_rangel) / (freq_hz / 2.0), (tf+tf_rangel) / (freq_hz / 2.0)], [(tf-tf_rangeh) / (freq_hz / 2.0), (tf+tf_rangeh)/(freq_hz / 2.0)], 5, 15)
	Faudl = filtfft(sps.butter(N, Wn, btype='bandpass')) 

	tf = SysParams['audio_rfreq']
	N, Wn = sps.buttord([(tf-tf_rangel) / (freq_hz / 2.0), (tf+tf_rangel) / (freq_hz / 2.0)], [(tf-tf_rangeh) / (freq_hz / 2.0), (tf+tf_rangeh)/(freq_hz / 2.0)], 5, 15)
	Faudr = filtfft(sps.butter(N, Wn, btype='bandpass')) 

	N, Wn = sps.buttord(0.016 / (afreq / 2.0), 0.024 / (afreq / 2.0), 5, 15) 
	FiltAPost = filtfft(sps.butter(N, Wn))
	
	N, Wn = sps.buttord(3.1 / (freq / 2.0), 3.5 / (freq / 2.0), 1, 20) 
	SysParams['fft_audiorf_lpf'] = Faudrf = filtfft(sps.butter(N, Wn, btype='lowpass')) 

	SysParams['fft_audiolpf'] = FiltAPost #* FiltAPost * FiltAPost

	SysParams['fft_audio_left'] = Faudrf * Faudl * fft_hilbert
	SysParams['fft_audio_right'] = Faudrf * Faudr * fft_hilbert

def prepare_audio_cuda():
	cs['plan1'] = fft.Plan(blocklen, np.float32, np.complex64)
	cs['plan1i'] = fft.Plan(ablocklen, np.complex64, np.complex64)
	
	cs['fft1_out'] = gpuarray.empty(blocklen, np.complex64)
	cs['ifft1_out'] = gpuarray.empty(ablocklen, np.complex64)
	
	cs['fm_left'] = gpuarray.empty(ablocklen, np.complex64)
	cs['fm_right'] = gpuarray.empty(ablocklen, np.complex64)
	
	cs['left_clipped'] = gpuarray.empty(ablocklen, np.float32)
	cs['right_clipped'] = gpuarray.empty(ablocklen, np.float32)
	
	cs['left_fft1'] = gpuarray.empty(blocklen//2+1, np.complex64)
	cs['right_fft1'] = gpuarray.empty(blocklen//2+1, np.complex64)
	cs['left_fft2'] = gpuarray.empty(ablocklen//2+1, np.complex64)
	cs['right_fft2'] = gpuarray.empty(ablocklen//2+1, np.complex64)

	cs['left_out'] = gpuarray.empty(ablocklen, np.float32)
	cs['right_out'] = gpuarray.empty(ablocklen, np.float32)
	
	cs['plan2'] = fft.Plan(ablocklen, np.float32, np.complex64)
	cs['plan2i'] = fft.Plan(ablocklen, np.complex64, np.float32)
	
	cs['outlen'] = outlen = ablocklen // 20 
	cs['scaledout'] = gpuarray.empty(outlen * 2, np.float32)
	cs['left_scaledout'] = gpuarray.empty(outlen, np.float32)
	cs['right_scaledout'] = gpuarray.empty(outlen, np.float32)
	
	cs['doanglediff_mac'] = mod.get_function("anglediff_mac")
	cs['doaudioscale'] = mod.get_function("audioscale")
	
	cs['filt_audiolpf'] = FFTtoGPU(SysParams['fft_audiolpf'])
	cs['filt_audio_left'] = FFTtoGPU(SysParams['fft_audio_left'])
	cs['filt_audio_right'] = FFTtoGPU(SysParams['fft_audio_right'])

def process_audio_cuda(data):
	global cs, csa, csa_first
	
	if csa_first == True:
		prepare_audio_filters()
		prepare_audio_cuda()
		csa_first = False	
	
	fdata = np.float32(data)
	gpudata = gpuarray.to_gpu(fdata)
	
	fft.fft(gpudata, cs['fft1_out'], cs['plan1'])

	cs['left_fft1'] = (cs['fft1_out'] * cs['filt_audio_left'])[0:(ablocklen//2)+1] # [0:blocklen])[0:(ablocklen//2)+1]
	cs['right_fft1'] = (cs['fft1_out'] * cs['filt_audio_right'])[0:(ablocklen//2)+1]

	fft.ifft(cs['left_fft1'], cs['fm_left'], cs['plan1i'], True)
	fft.ifft(cs['right_fft1'], cs['fm_right'], cs['plan1i'], True)

	cs['doanglediff_mac'](cs['left_clipped'], cs['fm_left'], np.float32((afreq_hz / 1.0 / np.pi)), np.float32(-SysParams['audio_lfreq']), block=(1024,1,1), grid=(ablocklenk,1))
	cs['doanglediff_mac'](cs['right_clipped'], cs['fm_right'], np.float32((afreq_hz / 1.0 / np.pi)), np.float32(-SysParams['audio_rfreq']), block=(1024,1,1), grid=(ablocklenk,1))

	fft.fft(cs['left_clipped'], cs['left_fft2'], cs['plan2'])
	fft.fft(cs['right_clipped'], cs['right_fft2'], cs['plan2'])
	
	cs['left_fft2'] *= cs['filt_audiolpf']
	cs['right_fft2'] *= cs['filt_audiolpf'] 
	
	fft.ifft(cs['left_fft2'], cs['left_out'], cs['plan2i'], True)
	fft.ifft(cs['right_fft2'], cs['right_out'], cs['plan2i'], True)

	aclip = 256 

	outlen = ablocklen

	cs['doaudioscale'](cs['scaledout'], cs['left_out'], cs['right_out'], np.float32(20), np.float32(0), block=(32, 1, 1), grid=(outlen//32,1));

	output = cs['scaledout'].get()[aclip:-aclip]
    
	return output, len(output) * 80 / 2

	plt.plot(cs['scaledout'].get())

#	plt.plot(cs['right_clipped'].get()[768:-768])
#	plt.plot(cs['right_out'].get()[768:-768] + 100000)
	plt.show()
	exit()

def test():
	test = np.empty(blocklen, dtype=np.int16)

#	infile = open("noise.raw", "rb")

#	noisebuf = infile.read(blocklen)
#	noisedata = (np.fromstring(noisebuf, 'uint8', blocklen)) 
#	noisedata = np.float(noisedata)

#	for hlen in range(3, 18):
	for vlevel in range(64, 101, 5):

		vphase = 0
		alphase = 0
		arphase = 0

		for i in range(0, len(test)):
			if i > len(test) / 2:
				vfreq = 9300000
			else:
				vfreq = 8100000

			vphase += vfreq / freq_hz  
			alphase += 2300000 / freq_hz 
			arphase += 2800000 / freq_hz 
			tmp = (np.sin(vphase * tau) * vlevel)
			tmp += (np.sin(alphase * tau) * vlevel / 10.0)
			tmp += (np.sin(arphase * tau) * vlevel / 10.0)
#			tmp += noisedata[i] * 1
			test[i] = tmp + 32768 

		output = np.float(process_video_cuda(test)[(blocklen/2)+1000:(blocklen/2)+5096])
		plt.plot(range(0, len(output)), output)

		output /= out_scale
		output -= 60

		mean = np.mean(output)
		std = np.std(output)
		print(vlevel, mean, std, 20 * np.log10(mean / std)) 

#	plt.show()
	exit()

def main():
	global hz_ire_scale, minn

	global SysParams, FiltPost, FiltPost_GPU

	global Bcutr, Acutr
	
	global Inner 

	global blocklen, blocklenk

	outfile = sys.stdout.buffer
	audio_mode = 0 
	CAV = 0

	byte_start = 0
	byte_end = 0

	f_seconds = False 

	optlist, cut_argv = getopt.getopt(sys.argv[1:], "Pd:D:hLCaAwSs:")

	for o, a in optlist:
		if o == "-P":
			SysParams = copy.deepcopy(SysParams_PAL)
		if o == "-d":
			SysParams['deemp'][0] = np.double(a)
		if o == "-D":
			SysParams['deemp'][1] = np.double(a)
		if o == "-a":
			audio_mode = 1	
#			blocklen = blocklen * 2 
#			blocklenk = blocklenk * 2 
		if o == "-L":
			Inner = 1
		if o == "-A":
			CAV = 1
			Inner = 1
		if o == "-C":
			#Bcutr, Acutr = sps.butter(1, [2.50/(freq/2), 3.26/(freq/2)], btype='bandstop')
			Bcutr, Acutr = sps.butter(1, [2.68/(freq/2), 3.08/(freq/2)], btype='bandstop')
		if o == "-w":
			hz_ire_scale = (9360000 - 8100000) / 100
			minn = 8100000 + (hz_ire_scale * -60)
		if o == "-S":
			f_seconds = True
#		if o == "-s":
#			ia = float(a)
#			SysParams['vlpf_freq'] = ia * 1000000 
#		if o == '-O':
#			ia = int(a)
#			SysParams['vlpf_order'] = ia 
		if o == "-s":
			ia = int(a)
			if ia == 0:
				SysParams['vlpf_freq'] = 4.2 * 1000000 
				SysParams['vlpf_order'] = 5 
			if ia == 1: # default
				SysParams['vlpf_freq'] = 4.4 * 1000000 
				SysParams['vlpf_order'] = 5 
			if ia == 2:
				SysParams['vlpf_freq'] = 5.0 * 1000000 
				SysParams['vlpf_order'] = 6 
			
			if ia >= 30:
				SysParams['vlpf_freq'] = (ia / 10.0) * 1000000 
				SysParams['vlpf_order'] = 5 
			
#			if ia == 40:
#				SysParams['vlpf_freq'] = 4.0 * 1000000 
#				SysParams['vlpf_order'] = 5 
					

	argc = len(cut_argv)
	if argc >= 1:
		infile = open(cut_argv[0], "rb")
	else:
		infile = sys.stdin

	byte_start = 0
	if (argc >= 2):
		byte_start = float(cut_argv[1])

	if (argc >= 3):
		byte_end = float(cut_argv[2])
		limit = 1
	else:
		limit = 0

	if f_seconds:
		byte_start *= freq_hz 
		byte_end *= freq_hz 
	else:
		byte_end += byte_start

	byte_end -= byte_start

	byte_start = int(byte_start)
	byte_end = int(byte_end)

	if (byte_start > 0):	
		infile.seek(byte_start)
	
	if CAV and byte_start > 11454654400:
		CAV = 0
		Inner = 0 

	total = toread = blocklen 
	inbuf = infile.read(toread)
	indata = np.fromstring(inbuf, 'uint8', toread)
	
	total = 0
	total_prevread = 0
	total_read = 0

	while (len(inbuf) > 0):
		toread = blocklen - indata.size 

		if toread > 0:
			inbuf = infile.read(toread)
			indata = np.append(indata, np.fromstring(inbuf, 'uint8', len(inbuf)))

			if indata.size < blocklen:
				pycuda.driver.stop_profiler()
				exit()

		if audio_mode:	
			output, osamp = process_audio_cuda(indata)
			
			nread = osamp 
			outfile.write(output)
		else:
			output_16 = process_video_cuda(indata)
			#outfile.write(output_16.tobytes())
			outfile.write(output_16)
			nread = len(output_16)
			
			total_read += nread

			if CAV:
				if (total_read + byte_start) > 11454654400:
					CAV = 0
					Inner = 0

		indata = indata[nread:len(indata)]

		if limit == 1:
			byte_end -= toread 
			if (byte_end < 0):
				inbuf = ""

	pycuda.driver.stop_profiler()


if __name__ == "__main__":
#	cProfile.run('main()')
	main()


