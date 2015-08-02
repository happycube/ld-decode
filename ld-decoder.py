#!/usr/bin/python3
import numpy as np
import scipy as sp
import scipy.signal as sps
import scipy.fftpack as fftpack 
import sys

import fdls as fdls
import matplotlib.pyplot as plt
import fft8 as fft8 

import ld_utils as utils

import getopt

π = np.pi
τ = np.pi * 2

#import ipdb

freq = (315.0 / 88.0) * 8.0
freq_hz = freq * 1000000.0
ffreq = freq/2.0

blocklen = (16 * 1024) + 512
hilbertlen = (16 * 1024)

lowpass_filter_b, lowpass_filter_a = sps.butter(8, (4.5/(freq/2)), 'low')

# stubs for later
f_deemp_b = []
f_deemp_a = []

# default deemp constants				
deemp_t1 = .825
deemp_t2 = 2.35

# audio filters
Baudiorf = sps.firwin(65, 3.5 / (freq / 2), window='hamming', pass_zero=True)

afreq = freq / 4

left_audfreq = 2.301136
right_audfreq = 2.812499

hfreq = freq / 8.0

N, Wn = sps.buttord([(left_audfreq-.10) / hfreq, (left_audfreq+.10) / hfreq], [(left_audfreq-.15) / hfreq, (left_audfreq+.15)/hfreq], 1, 15)
#print(N,Wn)
leftbp_filter_b, leftbp_filter_a = sps.butter(N, Wn, btype='bandpass')

N, Wn = sps.buttord([(right_audfreq-.10) / hfreq, (right_audfreq+.10) / hfreq], [(right_audfreq-.15) / hfreq, (right_audfreq+.15)/hfreq], 1, 15)
rightbp_filter_b, rightbp_filter_a = sps.butter(N, Wn, btype='bandpass')

N, Wn = sps.buttord(0.016 / hfreq, 0.024 / hfreq, 1, 8) 
audiolp_filter_b, audiolp_filter_a = sps.butter(N, Wn)

N, Wn = sps.buttord(3.1 / (freq / 2.0), 3.5 / (freq / 2.0), 1, 16) 
audiorf_filter_b, audiorf_filter_a = sps.butter(N, Wn)

# unused snippet: from http://tlfabian.blogspot.com/2013/01/implementing-hilbert-90-degree-shift.html
#hilbert_filter = np.fft.fftshift(
#    np.fft.ifft([0]+[1]*20+[0]*20)
#)

def fm_decode(in_filt, freq_hz, hlen = hilbertlen):
	hilbert = sps.hilbert(in_filt[0:hlen])
#	hilbert = sps.lfilter(hilbert_filter, 1.0, in_filt)

	# the hilbert transform has errors at the edges.  but it doesn't seem to matter much in practice 
	chop = 256 
	hilbert = hilbert[chop:len(hilbert)-chop]

	tangles = np.angle(hilbert) 
	dangles = np.diff(tangles)

	# If unwrapping at 0 is negative, flip 'em all around
	if (dangles[0] < -π):
		dangles[0] += τ
	
	tdangles2 = np.unwrap(dangles) 
	
	output = (tdangles2 * (freq_hz / τ))

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

minire = -60
maxire = 140

hz_ire_scale = (9300000 - 8100000) / 100
minn = 8100000 + (hz_ire_scale * -60)

out_scale = 65534.0 / (maxire - minire)
	
Bbpf, Abpf = sps.butter(3, [3.2/(freq/2), 14.0/(freq/2)], btype='bandpass')
Bcutl, Acutl = sps.butter(1, [2.055/(freq/2), 2.505/(freq/2)], btype='bandstop')
Bcutr, Acutr = sps.butter(1, [2.416/(freq/2), 3.176/(freq/2)], btype='bandstop')
# AC3 - Bcutr, Acutr = sps.butter(1, [2.68/(freq/2), 3.08/(freq/2)], btype='bandstop')

lowpass_filter_b, lowpass_filter_a = sps.butter(5, (4.4/(freq/2)), 'low')

#doplot(Bcutl, Acutl)

# octave:104> t1 = 100; t2 = 55; [b, a] = bilinear(-t2*(10^-8), -t1*(10^-8), t1/t2, freq); freqz(b, a)
# octave:105> printf("f_emp_b = ["); printf("%.15e, ", b); printf("]\nf_emp_a = ["); printf("%.15e, ", a); printf("]\n")
f_emp_b = [1.293279022403258e+00, -1.018329938900196e-02, ]
f_emp_a = [1.000000000000000e+00, 2.830957230142566e-01, ]

Inner = 0

#lowpass_filter_b = [1.0]
#lowpass_filter_a = [1.0]


def process_video(data):
	# perform general bandpass filtering

	in_filt1 = sps.lfilter(Bbpf, Abpf, data)
	in_filt2 = sps.lfilter(Bcutl, Acutl, in_filt1)
	in_filt3 = sps.lfilter(Bcutr, Acutr, in_filt2)

	if Inner:
		in_filt = sps.lfilter(f_emp_b, f_emp_a, in_filt3)
	else:
		in_filt = in_filt3

#	fft8.plotfft(in_filt)
#	plt.plot(in_filt)
#	plt.show()

	output = fm_decode(in_filt, freq_hz)

	# save the original fm decoding and align to filters
	output_prefilt = output[(len(f_deemp_b) * 24) + len(f_deemp_b) + len(lowpass_filter_b):]

	output = sps.lfilter(lowpass_filter_b, lowpass_filter_a, output)

	doutput = (sps.lfilter(f_deemp_b, f_deemp_a, output)[len(f_deemp_b) * 32:len(output)]) 
	
	output_16 = np.empty(len(doutput), dtype=np.uint16)
	reduced = (doutput - minn) / hz_ire_scale
	output = np.clip(reduced * out_scale, 0, 65535) 
	
	np.copyto(output_16, output, 'unsafe')

#	plt.plot(range(0, len(data)), data)
#	plt.plot(range(0, len(output_16)), output_16)
#	plt.show()
	return output_16

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

	if test_mode > 0:
		outputf = np.empty(32768 * 2, dtype = np.float32)
		for i in range(0, 32768):
			outputf[i * 2] = np.cos((i + test_mode) / (freq_hz / 4.0 / 10000)) 
			outputf[(i * 2) + 1] = np.cos((i + test_mode) / (freq_hz / 4.0 / 10000)) 

		outputf *= 50000
	
		test_mode += 32768 
		return outputf, 32768 

#	print(len(indata), len(audiorf_filter_b * 2), len(leftbp_filter_b) * 1)

	in_filt = sps.lfilter(audiorf_filter_b, audiorf_filter_a, indata)[len(audiorf_filter_b) * 2:]

	in_filt4 = np.empty(int(len(in_filt) / 4) + 1)

	for i in range(0, len(in_filt), 4):
		in_filt4[int(i / 4)] = in_filt[i]

	in_left = sps.lfilter(leftbp_filter_b, leftbp_filter_a, in_filt4)[len(leftbp_filter_b) * 1:] 
	in_right = sps.lfilter(rightbp_filter_b, rightbp_filter_a, in_filt4)[len(rightbp_filter_b) * 1:] 

	out_left = fm_decode(in_left, freq_hz / 4)
	out_right = fm_decode(in_right, freq_hz / 4)

	out_left = np.clip(out_left - left_audfreqm, -150000, 150000) 
	out_right = np.clip(out_right - right_audfreqm, -150000, 150000) 

	out_left = sps.lfilter(audiolp_filter_b, audiolp_filter_a, out_left)[800:]
	out_right = sps.lfilter(audiolp_filter_b, audiolp_filter_a, out_right)[800:] 

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

def test():
	test = np.empty(blocklen, dtype=np.uint8)
#	test = np.empty(blocklen)

#	for hlen in range(3, 18):
	for vlevel in range(20, 100, 10):

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
			test[i] = (np.sin(vphase * τ) * vlevel)
			test[i] += (np.sin(alphase * τ) * vlevel / 10.0)
			test[i] += (np.sin(arphase * τ) * vlevel / 10.0)
			test[i] += 128

		output = process_video(test)[7800:8500]	
		plt.plot(range(0, len(output)), output)

		output = output[400:700]	
		mean = np.mean(output)
		std = np.std(output)
		print(vlevel, mean, std, 20 * np.log10(mean / std)) 

	plt.show()
	exit()

def main():
	global lowpass_filter_b, lowpass_filter_a 
	global hz_ire_scale, minn
	global f_deemp_b, f_deemp_a

	global deemp_t1, deemp_t2

	global Bcutr, Acutr
	
	global Inner 

	global blocklen

#	test()

	outfile = sys.stdout.buffer
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
			blocklen = (64 * 1024) + 2048 
			hilbertlen = (16 * 1024)
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
				exit()

		if audio_mode:	
			output, osamp = process_audio(indata)
			
			nread = osamp 
			outfile.write(output)
		else:
			output_16 = process_video(indata)
			outfile.write(output_16)
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

if __name__ == "__main__":
    main()


