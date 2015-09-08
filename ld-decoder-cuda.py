#!/usr/bin/python
from __future__ import division
from __future__ import print_function

import numpy as np
import scipy as sp
import scipy.signal as sps
import scipy.fftpack as fftpack 
import matplotlib.pyplot as plt
import sys
import getopt

import fft8 as fft8 
import fdls as fdls
import ld_utils as utils

import pycuda.autoinit
import pycuda.driver as drv
import pycuda.gpuarray as gpuarray
from pycuda.compiler import SourceModule

import skcuda.fft as fft
import skcuda.misc as misc
    
import cProfile

pi = np.pi
tau = np.pi * 2

freq = (315.0 / 88.0) * 8.00
freq_hz = freq * 1000000.0

afreq = freq / 2.0
afreq_hz = afreq * 1000000.0

blocklenk = 64
blocklen = (blocklenk * 1024)  

lowpass_filter_b, lowpass_filter_a = sps.butter(8, (4.5/(freq/2)), 'low')

# stubs for later
f_deemp_b = []
f_deemp_a = []

# default deemp constants				
deemp_t1 = .825
deemp_t2 = 2.35

# audio filters
Baudiorf = sps.firwin(65, 3.5 / (freq / 2), window='hamming', pass_zero=True)
Aaudiorf = [1.0]

left_audfreq = 2.301136
right_audfreq = 2.812499

N, Wn = sps.buttord([(left_audfreq-.10) / afreq, (left_audfreq+.10) / afreq], [(left_audfreq-.15) / afreq, (left_audfreq+.15)/afreq], 1, 15)
#print(N,Wn)
Baudl, Aaudl = sps.butter(N, Wn, btype='bandpass')

N, Wn = sps.buttord([(right_audfreq-.10) / afreq, (right_audfreq+.10) / afreq], [(right_audfreq-.15) / afreq, (right_audfreq+.15)/afreq], 1, 15)
Baudr, Aaudr = sps.butter(N, Wn, btype='bandpass')

#Baudl = sps.firwin(129, [2.10 / (freq / 2.0), 2.50 / (freq / 2.0)], pass_zero=False)
#Aaudl = [1.0]

N, Wn = sps.buttord(0.016 / (afreq / 2.0), 0.024 / (afreq / 2.0), 2, 15) 
audiolp_filter_b, audiolp_filter_a = sps.butter(N, Wn)

N, Wn = sps.buttord(3.1 / (freq / 2.0), 3.5 / (freq / 2.0), 1, 20) 
audiorf_filter_b, audiorf_filter_a = sps.butter(N, Wn, btype='lowpass')

# from http://tlfabian.blogspot.com/2013/01/implementing-hilbert-90-degree-shift.html
hilbert_filter = np.fft.fftshift(
    np.fft.ifft([0]+[1]*200+[0]*200)
)

def fm_decode(hilbert, freq_hz):
	#hilbert = sps.hilbert(in_filt[0:hlen])
#	hilbert = sps.lfilter(hilbert_filter, 1.0, in_filt)

	# the hilbert transform has errors at the edges.  but it doesn't seem to matter much in practice 
	chop = 256 
	hilbert = hilbert[chop:len(hilbert)-chop]

	tangles = np.angle(hilbert) 
	dangles = np.diff(tangles)

	if (dangles[0] < -pi):
		dangles[0] += tau
	
	tdangles2 = np.unwrap(dangles) 
	
	output = (tdangles2 * (freq_hz / tau))

	errcount = 1
	while errcount > 0:
		errcount = 0

		# particularly bad bits can cause phase inversions.  detect and fix when needed - the loops are slow in python.
		if (output[np.argmax(output)] > freq_hz):
			errcount = 1
			for i in range(0, len(output)):
				if output[i] > freq_hz:
					output[i] = output[i] - freq_hz
	
		if (output[np.argmin(output)] < 0):
			errcount = 1
			for i in range(0, len(output)):
				if output[i] < 0:
					output[i] = output[i] + freq_hz

	return output

mod = SourceModule("""
#include <cuComplex.h>

// The pycuda math library doesn't have atan2f.
__global__ void angle(float *out, cuComplex *in) {
	const int i = threadIdx.x  + blockIdx.x * blockDim.x; // + (1024 * threadIdx.y);
	out[i] = atan2f(in[i].y, in[i].x);
}

// Combines diff() and angle correction
__global__ void adiff(float *out, float *in) {
	const int i = threadIdx.x  + blockIdx.x * blockDim.x; // + (1024 * threadIdx.y);

	// XXX?  This could in theory overrun and cause a crash if CUDA got a strict MMU.
	float tmp = in[i + 1] - in[i];

	out[i] = (tmp >= 0) ? tmp : tmp + (3.14159265359 * 2);
}

// Clamp from 0 to 65535.  There ought to be a pyCUDA routine for this.
__global__ void clamp16(unsigned short *y, float *x) {
	const int i = threadIdx.x  + blockIdx.x * blockDim.x; // + (1024 * threadIdx.y);
	y[i] = (unsigned short)max((float)0, min((float)65535, x[i]));
}

__global__ void audioclamp(float *y, float *x) {
	const int i = threadIdx.x  + blockIdx.x * blockDim.x; // + (1024 * threadIdx.y);
	y[i] = max((float)-150000, min((float)150000, x[i]));
}

__global__ void decimate4to1d(cuComplex *out, cuComplex *in)
{
	const int i = threadIdx.x  + blockIdx.x * blockDim.x; // + (1024 * threadIdx.y);

	out[i] = in[i * 4];
} 

__global__ void scale_nn(float *out, float *in, float s, float offset)
{
	const int i = threadIdx.x  + blockIdx.x * blockDim.x; // + (1024 * threadIdx.y);

	int index = (s * i) + offset;	
	out[i] = in[index];
}

__global__ void scale_avg4(float *out, float *in)
{
	const int i = threadIdx.x  + blockIdx.x * blockDim.x; // + (1024 * threadIdx.y);

	float tmp;

	tmp = in[(i * 4) + 0];
	tmp += in[(i * 4) + 1];
	tmp += in[(i * 4) + 2];
	tmp += in[(i * 4) + 3];

	out[i] = tmp;
}

__global__ void scale_avg4c(cuFloatComplex *out, cuFloatComplex *in)
{
	const int i = threadIdx.x  + blockIdx.x * blockDim.x; // + (1024 * threadIdx.y);

	float2 *inf = (float2 *)in;
	float2 c;

	c.x = 0;
	c.y = 0;
	for (int x = 0; x < 4; x++) {
		c.x += inf[(i * 4) + x].x;
		c.y += inf[(i * 4) + x].y;
	}

	out[i] = (cuFloatComplex)c;
}

__global__ void scale_avg4a(cuComplex *out, cuComplex *in)
{
	const int i = threadIdx.x  + blockIdx.x * blockDim.x; // + (1024 * threadIdx.y);
	
	float cx, cy;

	cx = in[(i * 4) + 0].x;
	cx += in[(i * 4) + 1].x;
	cx += in[(i * 4) + 2].x;
	cx += in[(i * 4) + 3].x;

	cy = in[(i * 4) + 0].y;
	cy += in[(i * 4) + 1].y;
	cy += in[(i * 4) + 2].y;
	cy += in[(i * 4) + 3].y;

	out[i] = make_cuComplex(cx / 4.0, cy / 4.0);
}

""")

minire = -60
maxire = 140

hz_ire_scale = (9300000 - 8100000) / 100
minn = 8100000 + (hz_ire_scale * -60)

out_scale = 65534.0 / (maxire - minire)
	
Bbpf, Abpf = sps.butter(1, [3.2/(freq/2), 14.0/(freq/2)], btype='bandpass')
Bcutl, Acutl = sps.butter(1, [2.25/(freq/2), 2.35/(freq/2)], btype='bandstop')
Bcutr, Acutr = sps.butter(1, [2.75/(freq/2), 2.850/(freq/2)], btype='bandstop')
Bcut, Acut = sps.butter(1, [2.055/(freq/2), 3.176/(freq/2)], btype='bandstop')
# AC3 - Bcutr, Acutr = sps.butter(1, [2.68/(freq/2), 3.08/(freq/2)], btype='bandstop')

lowpass_filter_b, lowpass_filter_a = sps.butter(5, (4.4/(freq/2)), 'low')

forder = 256 
forderd = 0 
[Bbpf_FDLS, Abpf_FDLS] = fdls.FDLS_fromfilt(Bbpf, Abpf, forder, forderd, 0, phasemult = 1.00)
[Bcutl_FDLS, Acutl_FDLS] = fdls.FDLS_fromfilt(Bcutl, Acutl, forder, forderd, 0, phasemult = 1.00)
[Bcutr_FDLS, Acutr_FDLS] = fdls.FDLS_fromfilt(Bcutr, Acutr, forder, forderd, 0, phasemult = 1.00)

Fbpf = np.fft.fft(Bbpf_FDLS, blocklen)
Fcutl = np.fft.fft(Bcutl_FDLS, blocklen)
Fcutr = np.fft.fft(Bcutr_FDLS, blocklen)

[Baudrf_FDLS, Aaudrf_FDLS] = fdls.FDLS_fromfilt(audiorf_filter_b, audiorf_filter_a, forder, forderd, 0)
Faudrf = np.fft.fft(Baudrf_FDLS, blocklen)
Faudrf_GPU = gpuarray.to_gpu(np.complex64(Faudrf))

audiolp_filter_fir = sps.firwin(257, .020 / (freq / 2.0))
[Baudiolp_FDLS, Aaudiolp_FDLS] = fdls.FDLS_fromfilt(audiolp_filter_b, audiolp_filter_a, forder, forderd, 0)
[Baudiolp_FDLS, Aaudiolp_FDLS] = fdls.FDLS_fromfilt(audiolp_filter_fir, [1.0], forder, forderd, 0)
FiltAPost = np.fft.fft(Baudiolp_FDLS, blocklen)
FiltAPost_GPU = gpuarray.to_gpu(np.complex64(FiltAPost))

[Baudl_FDLS, Aaudl_FDLS] = fdls.FDLS_fromfilt(Baudl, Aaudl, forder, forderd, 0)
[Baudr_FDLS, Aaudr_FDLS] = fdls.FDLS_fromfilt(Baudr, Aaudr, forder, forderd, 0)

Faudl = np.fft.fft(Baudl_FDLS, blocklen)
Faudr = np.fft.fft(Baudr_FDLS, blocklen)

Fhilbert = np.fft.fft(hilbert_filter, blocklen)

FiltV = Fbpf * Fcutl * Fcutr * Fhilbert
FiltAL = Faudrf * Faudl * Fhilbert
FiltAL_GPU = gpuarray.to_gpu(np.complex64(FiltAL))
FiltAR = Faudrf * Faudr * Fhilbert
FiltAR_GPU = gpuarray.to_gpu(np.complex64(FiltAR))

FiltV_GPU = gpuarray.to_gpu(np.complex64(FiltV))

# octave:104> t1 = 100; t2 = 55; [b, a] = bilinear(-t2*(10^-8), -t1*(10^-8), t1/t2, freq); freqz(b, a)
# octave:105> printf("f_emp_b = ["); printf("%.15e, ", b); printf("]\nf_emp_a = ["); printf("%.15e, ", a); printf("]\n")
f_emp_b = [1.293279022403258e+00, -1.018329938900196e-02, ]
f_emp_a = [1.000000000000000e+00, 2.830957230142566e-01, ]

[Bemp_FDLS, Aemp_FDLS] = fdls.FDLS_fromfilt(f_emp_b, f_emp_a, forder, forderd, 0)
Femp = np.fft.fft(Bemp_FDLS, blocklen)

FiltVInner = FiltV * Femp
FiltVInner_GPU = gpuarray.to_gpu(np.complex64(FiltVInner))

FiltPost = []
FiltPost_GPU = []

Inner = 0

cs_first = True
cs = {} 

# Things go *a lot* faster when you have the memory structures pre-allocated
def prepare_video_cuda(data):
	fdata = np.float32(data)
	gpudata = gpuarray.to_gpu(fdata)

	cs['plan1'] = fft.Plan(gpudata.shape, np.float32, np.complex64)
	cs['plan1i'] = fft.Plan(gpudata.shape, np.complex64, np.complex64)
	
	cs['fft1_out'] = gpuarray.empty(len(fdata)//2+1, np.complex64)
	fft.fft(gpudata, cs['fft1_out'], cs['plan1'])
	
	cs['filtered1'] = gpuarray.empty(len(fdata), np.complex64)
	fft.ifft(cs['fft1_out'], cs['filtered1'], cs['plan1i'], True)

	cs['fm_angles'] = gpuarray.empty(len(cs['filtered1']), np.float32)
	cs['fm_demod'] = gpuarray.empty(len(cs['filtered1']), np.float32)

	cs['doutput_gpu'] = gpuarray.empty(len(fdata), np.float32)
	cs['fftout_gpu'] = gpuarray.empty(len(fdata)//2+1, np.complex64)
	
	cs['clipped_gpu'] = gpuarray.empty(len(fdata), np.uint16)
	
	cs['plan2'] = fft.Plan(cs['fm_demod'].shape, np.float32, np.complex64)
	cs['plan2i'] = fft.Plan(cs['fm_demod'].shape, np.complex64, np.float32)
	
	cs['f_clamp16'] = mod.get_function("clamp16")
	cs['f_angle'] = mod.get_function("angle")
	cs['f_adiff'] = mod.get_function("adiff")

def fft_overlap(data, conv, overlap = 128, fftlen = 4096):
	num = len(data) // (4096 - (overlap * 2))
	print(num)

	fdata = np.float32(data)
	gd = gpuarray.empty(num*4096, dtype=np.float32)

	for i in range(0, num):
		index = i * (fftlen - (overlap * 2))
		print(i, index, index+fftlen)
		print(gd[i*fftlen:(i+1)*fftlen].shape)
		print(fdata[index:index+fftlen].shape)
		gd[i*fftlen:(i+1)*fftlen] = fdata[index:index+fftlen]
#		gd[i].set(data[index:index+fftlen])

	gd[0:1000] = gd[5000:6000]
	gd[1000:2000] = gd[5000:6000]

	print(gd.get())
	exit()

def process_video_cuda(data):
	global cs, cs_first 
#	fft_overlap(data, FiltV_GPU) 

	if cs_first == True:
		prepare_video_cuda(data)
		cs_first = False

	fdata = np.float32(data)

	gpudata = gpuarray.to_gpu(fdata)

	# first fft->ifft cycle applies pre-decoding filtering (low pass filters, CAV/CLV emphasis)
	# and very importantly, performs the Hilbert transform
	fft.fft(gpudata, cs['fft1_out'], cs['plan1'])

	if Inner:	
		cs['fft1_out'] *= FiltVInner_GPU 
	else:
		cs['fft1_out'] *= FiltV_GPU 
	
	fft.ifft(cs['fft1_out'], cs['filtered1'], cs['plan1i'], True)

	fft_overlap(data, FiltV_GPU) 
	
	cs['f_angle'](cs['fm_angles'], cs['filtered1'], block=(1024,1,1), grid=(blocklenk,1))
	cs['f_adiff'](cs['fm_demod'], cs['fm_angles'], block=(1024,1,1), grid=(blocklenk,1))

	# post-processing:  output low-pass filtering and deemphasis	
	fft.fft(cs['fm_demod'], cs['fftout_gpu'], cs['plan2'])
	cs['fftout_gpu'] *= FiltPost_GPU 
	fft.ifft(cs['fftout_gpu'], cs['doutput_gpu'], cs['plan2i'], True)

	sminn = minn / (freq_hz / tau)
	mfactor = out_scale / hz_ire_scale

	cs['doutput_gpu'] -= sminn
	cs['doutput_gpu'] *= (freq_hz / tau) * mfactor

	cs['f_clamp16'](cs['clipped_gpu'], cs['doutput_gpu'], block=(1024,1,1), grid=(blocklenk,1)) 

	output_16 = cs['clipped_gpu'].get()

	chop = 512
	return output_16[chop:len(output_16)-chop]

# graph for debug
#	output = (sps.lfilter(f_deemp_b, f_deemp_a, output)[128:len(output)]) / deemp_corr

	plt.plot(range(0, len(output_16)), output_16)
#	plt.plot(range(0, len(doutput)), doutput)
#	plt.plot(range(0, len(output_prefilt)), output_prefilt)
	plt.show()
	exit()

left_audfreqm = left_audfreq * 1000000
right_audfreqm = right_audfreq * 1000000

test_mode = 0

def process_audio(indata):
	global test_mode

#	print(len(indata), len(audiorf_filter_b * 2), len(Baudl) * 1)

#	in_filt = sps.lfilter(audiorf_filter_b, audiorf_filter_a, indata) #[len(audiorf_filter_b) * 2:]

	fft = np.fft.fft(indata,len(indata))

	in_left = np.fft.ifft(fft*FiltAL,len(indata))
	in_right = np.fft.ifft(fft*FiltAR,len(indata))
	#plt.plot(np.absolute(in_left[3000:4000]))

	out_left = fm_decode(in_left, freq_hz / 1)[384:]
	out_right = fm_decode(in_right, freq_hz / 1)[384:]

	out_left = np.clip(out_left - left_audfreqm, -150000, 150000) 
	out_right = np.clip(out_right - right_audfreqm, -150000, 150000) 

	out_left = sps.lfilter(audiolp_filter_b, audiolp_filter_a, out_left)[800:]
	out_right = sps.lfilter(audiolp_filter_b, audiolp_filter_a, out_right)[800:] 
	plt.plot(out_left)

#	plt.show()
#	exit()
	
	#plt.plot((out_left))
	return()

	outputf = np.empty((len(out_left) * 2.0 / 20.0) + 2, dtype = np.float32)

	tot = 0
	for i in range(0, len(out_left), 20):
		outputf[tot * 2] = out_left[i]
		outputf[(tot * 2) + 1] = out_right[i]
		tot = tot + 1

	return outputf[0:tot * 2], tot * 20 * 4 

	plt.plot(range(0, len(out_left)), out_left)
#	plt.plot(range(0, len(out_leftl)), out_leftl)
	plt.plot(range(0, len(out_right)), out_right + 150000)
#	plt.ylim([2000000,3000000])
	plt.show()
	exit()

csa_first = True
csa = {} 
	
def prepare_audio_cuda(data):
	fdata = np.float32(data)
	gpudata = gpuarray.to_gpu(fdata)

	ablocklen = blocklen//4
	ablocklenk = blocklenk//4

	cs['plan1'] = fft.Plan(gpudata.shape, np.float32, np.complex64)
	cs['plan1i'] = fft.Plan(gpudata.shape, np.complex64, np.complex64)
	
	cs['fft1_out'] = gpuarray.empty((len(fdata)//2)+1, np.complex64)
	cs['ifft1_out'] = gpuarray.empty(len(fdata), np.complex64)
	#fft.fft(gpudata, cs['fft1_out'], cs['plan1'])
	
	cs['fm_left1'] = gpuarray.empty(len(fdata), np.complex64)
	cs['fm_right1'] = gpuarray.empty(len(fdata), np.complex64)
	
	cs['fm_left'] = gpuarray.empty(blocklen, np.complex64)
	cs['fm_right'] = gpuarray.empty(blocklen, np.complex64)
	
	cs['left_angles'] = gpuarray.empty(blocklen, np.float32)
	cs['right_angles'] = gpuarray.empty(blocklen, np.float32)
	
	cs['left_demod1'] = gpuarray.empty(blocklen, np.float32)
	cs['right_demod1'] = gpuarray.empty(blocklen, np.float32)
	
	cs['left_demod'] = gpuarray.empty(blocklen, np.float32)
	cs['right_demod'] = gpuarray.empty(blocklen, np.float32)
	
	cs['left_clipped'] = gpuarray.empty(blocklen, np.float32)
	cs['right_clipped'] = gpuarray.empty(blocklen, np.float32)
	
	cs['left_fft1'] = gpuarray.empty(blocklen//2+1, np.complex64)
	cs['right_fft1'] = gpuarray.empty(blocklen//2+1, np.complex64)
	cs['left_fft2'] = gpuarray.empty(ablocklen//2+1, np.complex64)
	cs['right_fft2'] = gpuarray.empty(ablocklen//2+1, np.complex64)

	cs['left_out'] = gpuarray.empty(blocklen, np.float32)
	cs['right_out'] = gpuarray.empty(blocklen, np.float32)
	
	cs['plan2'] = fft.Plan(cs['left_demod'].shape, np.float32, np.complex64)
	cs['plan2i'] = fft.Plan(cs['left_demod'].shape, np.complex64, np.float32)
	
	cs['outlen'] = outlen = (((ablocklen - 1536) // 20) // 32) * 32
	cs['left_scaledout'] = gpuarray.empty(outlen, np.float32)
	cs['right_scaledout'] = gpuarray.empty(outlen, np.float32)
	
	cs['f_decimate4to1d'] = mod.get_function("decimate4to1d")
	cs['f_angle'] = mod.get_function("angle")
	cs['f_adiff'] = mod.get_function("adiff")
	cs['f_audioclamp'] = mod.get_function("audioclamp")

	cs['f_scale'] = mod.get_function("scale_nn")
	cs['f_scale4'] = mod.get_function("scale_avg4")
	cs['f_scale4c'] = mod.get_function("scale_avg4c")

def process_audio_cuda(data):
	global cs, csa, csa_first
	
	if csa_first == True:
		prepare_audio_cuda(data)
		csa_first = False	
	
	fdata = np.float32(data)
	gpudata = gpuarray.to_gpu(fdata)
	
	fft.fft(gpudata, cs['fft1_out'], cs['plan1'])

	cs['left_fft1'] = cs['fft1_out'] * FiltAL_GPU
	cs['right_fft1'] = cs['fft1_out'] * FiltAR_GPU

	fft.ifft(cs['left_fft1'], cs['fm_left'], cs['plan1i'], True)
	fft.ifft(cs['right_fft1'], cs['fm_right'], cs['plan1i'], True)

	cs['f_angle'](cs['left_angles'], cs['fm_left'], block=(1024,1,1), grid=(blocklenk,1))
	cs['f_angle'](cs['right_angles'], cs['fm_right'], block=(1024,1,1), grid=(blocklenk,1))

	cs['f_adiff'](cs['left_demod'], cs['left_angles'], block=(1024,1,1), grid=(blocklenk,1))
	cs['f_adiff'](cs['right_demod'], cs['right_angles'], block=(1024,1,1), grid=(blocklenk,1))

	cs['left_demod'] *= (freq_hz / 2.0 / np.pi)
	cs['right_demod'] *= (freq_hz / 2.0 / np.pi)

	cs['left_demod'] -= left_audfreqm 
	cs['right_demod'] -= right_audfreqm 
	
	cs['f_audioclamp'](cs['left_clipped'], cs['left_demod'], block=(1024,1,1), grid=(blocklenk,1)) 
	cs['f_audioclamp'](cs['right_clipped'], cs['right_demod'], block=(1024,1,1), grid=(blocklenk,1)) 
	
	fft.fft(cs['left_clipped'], cs['left_fft2'], cs['plan2'])
	fft.fft(cs['right_clipped'], cs['right_fft2'], cs['plan2'])
	
	cs['left_fft2'] *= FiltAPost_GPU
	cs['right_fft2'] *= FiltAPost_GPU

	fft.ifft(cs['left_fft2'], cs['left_out'], cs['plan2i'], True)
	fft.ifft(cs['right_fft2'], cs['right_out'], cs['plan2i'], True)

	outlen = (blocklen - 1536) // 80
	cs['f_scale'](cs['left_scaledout'], cs['left_out'], np.float32(80), np.float32(768), block=(32, 1, 1), grid=(outlen//32,1));
	cs['f_scale'](cs['right_scaledout'], cs['right_out'], np.float32(80), np.float32(768), block=(32, 1, 1), grid=(outlen//32,1));

	out_left = cs['left_scaledout'].get()
	out_right = cs['right_scaledout'].get()
	
	outputf = np.empty((len(out_left) * 2.0), dtype = np.float32)

	for i in range(0, len(out_left)):
		outputf[i * 2] = out_left[i]
		outputf[(i * 2) + 1] = out_right[i]

	return outputf, len(out_left) * 80 

	#plt.plot(cs['left_out'].get()[768:-768])
	plt.plot(left_scaledout.get())
	plt.show()
	exit()

def test():
	test = np.empty(blocklen, dtype=np.int16)

	infile = open("noise.raw", "rb")

	noisebuf = infile.read(blocklen)
	noisedata = np.float(np.fromstring(noisebuf, 'uint8', blocklen)) - 128

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
			tmp += noisedata[i] * 1
			test[i] = tmp + 32768 

		output = np.float(process_video(test)[(blocklen/2)+1000:(blocklen/2)+5096])
		plt.plot(range(0, len(output)), output)

		output /= out_scale
		output -= 60

		mean = np.mean(output)
		std = np.std(output)
		print(vlevel, mean, std, 20 * np.log10(mean / std)) 

#	plt.show()
	exit()

def main():
	global lowpass_filter_b, lowpass_filter_a 
	global hz_ire_scale, minn
	global f_deemp_b, f_deemp_a

	global deemp_t1, deemp_t2, FiltPost, FiltPost_GPU

	global Bcutr, Acutr
	
	global Inner 

	global blocklen, blocklenk

	outfile = sys.stdout #.buffer
	audio_mode = 0 
	CAV = 0

	byte_start = 0
	byte_end = 0

	f_seconds = False 

	optlist, cut_argv = getopt.getopt(sys.argv[1:], "d:D:hLCaAwSs:")

	for o, a in optlist:
		if o == "-d":
			deemp_t1 = np.double(a)
		if o == "-D":
			deemp_t2 = np.double(a)
		if o == "-a":
			audio_mode = 1	
#			blocklen = blocklen * 2 
#			blocklenk = blocklenk * 2 
		if o == "-L":
			Inner = 1
		if o == "-A":
			CAV = 1
			Inner = 1
		if o == "-h":
			# use full spec deemphasis filter - will result in overshoot, but higher freq resonse
			f_deemp_b = [3.778720395899611e-01, -2.442559208200777e-01]
			f_deemp_a = [1.000000000000000e+00, -8.663838812301168e-01]
		if o == "-C":
			Bcutr, Acutr = sps.butter(1, [2.50/(freq/2), 3.26/(freq/2)], btype='bandstop')
			Bcutr, Acutr = sps.butter(1, [2.68/(freq/2), 3.08/(freq/2)], btype='bandstop')
		if o == "-w":
			hz_ire_scale = (9360000 - 8100000) / 100
			minn = 8100000 + (hz_ire_scale * -60)
		if o == "-S":
			f_seconds = True
		if o == "-s":
			ia = int(a)
			if ia == 0:
				lowpass_filter_b, lowpass_filter_a = sps.butter(5, (4.2/(freq/2)), 'low')
			if ia == 1:	
				lowpass_filter_b, lowpass_filter_a = sps.butter(5, (4.4/(freq/2)), 'low')
			if ia == 2:	
				lowpass_filter_b, lowpass_filter_a = sps.butter(6, (4.6/(freq/2)), 'low')
				lowpass_filter_b, lowpass_filter_a = sps.butter(6, (4.6/(freq/2)), 'low')
				deemp_t1 = .825
				deemp_t2 = 2.35
			if ia == 3:	
				# high frequency response - and ringing.  choose your poison ;)	
				lowpass_filter_b, lowpass_filter_a = sps.butter(10, (5.0/(freq/2)), 'low')
				lowpass_filter_b, lowpass_filter_a = sps.butter(7, (5.0/(freq/2)), 'low')
			if ia == 4:	
				lowpass_filter_b, lowpass_filter_a = sps.butter(10, (5.3/(freq/2)), 'low')
				lowpass_filter_b, lowpass_filter_a = sps.butter(7, (5.3/(freq/2)), 'low')
			if ia == 51:	
				lowpass_filter_b, lowpass_filter_a = sps.butter(5, (4.4/(freq/2)), 'low')
			if ia == 61:	
				lowpass_filter_b, lowpass_filter_a = sps.butter(6, (4.4/(freq/2)), 'low')
			if ia == 62:	
				lowpass_filter_b, lowpass_filter_a = sps.butter(6, (4.7/(freq/2)), 'low')

	# set up deemp filter
	[tf_b, tf_a] = sps.zpk2tf(-deemp_t2*(10**-8), -deemp_t1*(10**-8), deemp_t1 / deemp_t2)
	[f_deemp_b, f_deemp_a] = sps.bilinear(tf_b, tf_a, 1/(freq_hz/2))

#	test()

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

	# set up deemp filter
	[tf_b, tf_a] = sps.zpk2tf(-deemp_t2*(10**-8), -deemp_t1*(10**-8), deemp_t1 / deemp_t2)
	[f_deemp_b, f_deemp_a] = sps.bilinear(tf_b, tf_a, 1/(freq_hz/2))

	[Bdeemp_FDLS, Adeemp_FDLS] = fdls.FDLS_fromfilt(f_deemp_b, f_deemp_a, forder, forderd, 0)
	Fdeemp = np.fft.fft(Bdeemp_FDLS, blocklen-1)
	[Blpf_FDLS, Alpf_FDLS] = fdls.FDLS_fromfilt(lowpass_filter_b, lowpass_filter_a, forder, forderd, 0)
	Flpf = np.fft.fft(Blpf_FDLS, blocklen-1)
	FiltPost = Fdeemp * Flpf 
	FiltPost_GPU = gpuarray.to_gpu(np.complex64(FiltPost))

#	utils.doplot(f_deemp_b, f_deemp_a)
#	utils.doplot(lowpass_filter_b, lowpass_filter_a)
#	plt.plot(FiltPost.real)	
#	plt.show()
#	exit()

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
#			process_audio(indata)
			output, osamp = process_audio_cuda(indata)
			
			nread = osamp 
#			outfile.write(output)
		else:
			output_16 = process_video_cuda(indata)
#			outfile.write(output_16)
			nread = len(output_16)
			
			total_pread = total_read 
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


