#!/usr/bin/python
import numpy as np
import scipy as sp
import scipy.signal as sps
import sys

import fdls as fdls
import matplotlib.pyplot as plt

import getopt

#import ipdb

freq = (315.0 / 88.0) * 8.0
freq_hz = freq * 1000000.0
blocklen = (16 * 1024) 

def dosplot(B, A):
	w, h = sps.freqz(B, A)

	fig = plt.figure()
	plt.title('Digital filter frequency response')

	ax1 = fig.add_subplot(111)

	plt.plot(w * (freq/np.pi) / 2.0, 20 * np.log10(abs(h)), 'b')
	plt.ylabel('Amplitude [dB]', color='b')
	plt.xlabel('Frequency [rad/sample]')

	plt.show()

def doplot(B, A):
	w, h = sps.freqz(B, A)

	fig = plt.figure()
	plt.title('Digital filter frequency response')

	ax1 = fig.add_subplot(111)

	plt.plot(w * (freq/np.pi) / 2.0, 20 * np.log10(abs(h)), 'b')
	plt.ylabel('Amplitude [dB]', color='b')
	plt.xlabel('Frequency [rad/sample]')

	ax2 = ax1.twinx()
	angles = np.unwrap(np.angle(h))
	plt.plot(w * (freq/np.pi) / 2.0, angles, 'g')
	plt.ylabel('Angle (radians)', color='g')
	plt.grid()
	plt.axis('tight')
	plt.show()

def doplot2(B, A, C, B2, A2, C2):
	w, h = sps.freqz(B, A)
	w2, h2 = sps.freqz(B2, A2)

	h.real /= C
	h2.real /= C2

	begin = 0
	end = len(w)
#	end = int(len(w) * (12 / freq))

#	chop = len(w) / 20
	chop = 0
	w = w[begin:end]
	w2 = w2[begin:end]
	h = h[begin:end]
	h2 = h2[begin:end]

	v = np.empty(len(w))
	
#	print len(w)

	hm = np.absolute(h)
	hm2 = np.absolute(h2)

	v0 = hm[0] / hm2[0]
	for i in range(0, len(w)):
#		print i, freq / 2 * (w[i] / np.pi), hm[i], hm2[i], hm[i] / hm2[i], (hm[i] / hm2[i]) / v0
		v[i] = (hm[i] / hm2[i]) / v0

	fig = plt.figure()
	plt.title('Digital filter frequency response')

	ax1 = fig.add_subplot(111)

	v  = 20 * np.log10(v )

#	plt.plot(w * (freq/np.pi) / 2.0, v)
#	plt.show()
#	exit()

	plt.plot(w * (freq/np.pi) / 2.0, 20 * np.log10(abs(h)), 'r')
	plt.plot(w * (freq/np.pi) / 2.0, 20 * np.log10(abs(h2)), 'b')
	plt.ylabel('Amplitude [dB]', color='b')
	plt.xlabel('Frequency [rad/sample]')
	
	ax2 = ax1.twinx()
	angles = np.unwrap(np.angle(h))
	angles2 = np.unwrap(np.angle(h2))
	plt.plot(w * (freq/np.pi) / 2.0, angles, 'g')
	plt.plot(w * (freq/np.pi) / 2.0, angles2, 'y')
	plt.ylabel('Angle (radians)', color='g')
	plt.grid()
	plt.axis('tight')
	plt.show()

ffreq = freq/2.0

n = 128 
Fr = np.zeros(n)
Am = np.zeros(n)
Th = np.zeros(n)

for f in range(0, n):
	cf = freq * (float(f) / 256.0)
     
#	if (cf > 13.8):
#		Am[f] = 0
	if (cf > 6.0):
		Am[f] = 1  + ((cf - 6.0) / 12) 
	elif (cf > 4.0):
		Am[f] = 1 
	elif (cf > 3.0):
		Am[f] = 1 * (cf - 3.0)
	else:
		Am[f] = 0

	Fr[f] = float(f) / 256.0
	Th[f] = -(Fr[f] * 42) 

[Bboost, Aboost] = fdls.FDLS(Fr, Am, Th, 16, 8, 0)
#dosplot(Bboost, Aboost)
#exit()

#lowpass_filter_b = sps.firwin(25, 5.4 / (freq / 2)) #, window='hamming')
lowpass_filter_a = [1.0]
lowpass_filter_b = sps.firwin(31, 5.2 / (freq / 2)) #, window='hamming')

N, Wn = sps.cheb1ord(4.2/(freq/2), 5.0/(freq/2), 1, 10)
#lowpass_filter_b, lowpass_filter_a = sps.cheby1(N, 1, Wn, 'low')

#print N, Wn
#doplot(lowpass_filter_b, lowpass_filter_a)
#exit()

# XXX: this bilinear filter *should* be mostly accurate deemphasis, but it's unstable.  
# reversing the angle stabilizes it, which FDLS can do.

f_deemp_bil_b = [2.819257458245255e-01, -4.361485083509491e-01]
f_deemp_bil_a = [1.000000000000000e+00, -1.154222762526424e+00]

w, h = sps.freqz(f_deemp_bil_b, f_deemp_bil_a)
w = w / (2 * np.pi) 

Th = np.empty(len(w))
Th1 = np.angle(h)
Am = np.absolute(h)/1.0

Ndeemp = 1 
Ddeemp = 1
for i in range(0, len(w)):
	Th[i] = -(Th1[i] * 1.0) 

[f_deemp_b, f_deemp_a] = fdls.FDLS(w, Am, Th, Ndeemp, Ddeemp, 0)
#doplot2(f_deemp_b, f_deemp_a, 1.0, f_deemp_bil_b, f_deemp_bil_a, 1.0)
#exit()

# This version shouldn't work at all (uses just the real angle from the bilinear,
# computes the angle very oddly!), but it fits the current data well.

n = 512 
df = 512.0/(freq) 
Fr = np.zeros(n)
Am = np.zeros(n)
Th = np.zeros(n)

f_deemp_bil_b = [2.819257458245255e-01, -4.361485083509491e-01]
f_deemp_bil_a = [1.000000000000000e+00, -1.154222762526424e+00]

w, h = sps.freqz(f_deemp_bil_b, f_deemp_bil_a)
w = w / (np.pi * 1.0)
h.imag = h.imag * 1

Ndeemp = 8
Ddeemp = 8
for i in range(0, len(Fr)):
	cf = (float(i) / df)
	Fr[i] = cf / (freq * 2)

	Th[i] = (-((Fr[i] * 6.90) / h.real[i])) - (0 * (np.pi / 180)) 

[f_deemp_b, f_deemp_a] = fdls.FDLS(w, h.real*1, Th, Ndeemp, Ddeemp)

#doplot2(f_deemp_b, f_deemp_a, 1.0, f_deemp_bil_b, f_deemp_bil_a, 1.0)
#doplot2(f_deempc_b, f_deempc_a, 1.0, f_deemp_b, f_deemp_a, 1.0)
#exit()

#deemp_corr = 1
deemp_corr = .499 

# audio filters
Baudiorf = sps.firwin(65, 3.5 / (freq / 2), window='hamming', pass_zero=True)

afreq = freq / 4

leftbp_filter = sps.firwin(97, [2.15/(afreq/2), 2.45/(afreq/2)], window='hamming', pass_zero=False)
rightbp_filter = sps.firwin(97, [2.65/(afreq/2), 2.95/(afreq/2)], window='hamming', pass_zero=False)

audiolp_filter = sps.firwin(513, .05 / (afreq / 2), window='hamming')
#audiolp_filter = sps.firwin(129, .004 / (afreq / 2), window='hamming')

def fm_decode(in_filt, freq_hz):
	hilbert = sps.hilbert(in_filt)

	# the hilbert transform has errors at the edges.  but it doesn't seem to matter much IRL
	chop = 192	
	hilbert = hilbert[chop:len(hilbert)-chop]

	tangles = np.angle(hilbert) 

#	dangles = np.diff(tangles[128:])
	dangles = np.diff(tangles)

	# make sure unwapping goes the right way
	if (dangles[0] < -np.pi):
		dangles[0] += (np.pi * 2)
	
	tdangles2 = np.unwrap(dangles) 
	
	output = (tdangles2 * (freq_hz / (np.pi * 2)))

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

def process_video(data):
	# perform general bandpass filtering
	in_filt = sps.lfilter(Bboost, Aboost, data)

	output = fm_decode(in_filt, freq_hz) 

	output = sps.lfilter(lowpass_filter_b, lowpass_filter_a, output)[len(lowpass_filter_b):]

	doutput = (sps.lfilter(f_deemp_b, f_deemp_a, output)[64:len(output)]) / deemp_corr
	
	output_16 = np.empty(len(doutput), dtype=np.uint16)
	reduced = (doutput - minn) / hz_ire_scale
	output = np.clip(reduced * out_scale, 0, 65535) 
	np.copyto(output_16, output, 'unsafe')

	return output_16

# graph for debug
#	output = (sps.lfilter(f_deemp_b, f_deemp_a, output)[128:len(output)]) / deemp_corr
#	print output

	plt.plot(range(0, len(output)), output)
#	plt.ylim([7500000,9500000])
	plt.show()
	exit()

def process_audio(indata):
	in_filt = sps.lfilter(Baudiorf, [1.0], indata)[len(Baudiorf):]
	in_filt4 = np.empty(int(len(in_filt) / 4) + 1)

	for i in range(0, len(in_filt), 4):
		in_filt4[int(i / 4)] = in_filt[i]

	in_left = sps.lfilter(leftbp_filter, [1.0], in_filt4)[len(leftbp_filter):] 
	in_right = sps.lfilter(rightbp_filter, [1.0], in_filt4)[len(rightbp_filter):] 

	out_left = fm_decode(in_left, [1.0], freq_hz / 4)
	out_right = fm_decode(in_right, [1.0], freq_hz / 4)

	# fast but not as good	
	out_left = np.clip(out_left, 2150000, 2450000) 
	out_right = np.clip(out_right, 2650000, 2950000) 

	out_left = sps.lfilter(audiolp_filter, [1.0], out_left)[len(audiolp_filter):]
	out_right = sps.lfilter(audiolp_filter, [1.0], out_right)[len(audiolp_filter):] 

	output = np.empty((len(out_left) * 2 / 20) + 1)
	outputf = np.empty((len(out_left) * 2 / 20) + 1, dtype = np.float32)

#	print len(out_left), len(output)

	tot = 0
	for i in range(0, len(out_left), 20):
		tot = tot + 1
		output[(i / 10)] = out_left[i]
		output[(i / 10) + 1] = out_right[i]
#		print i, i / 10, output[(i / 10)], output[(i / 10) + 1] 	

#	exit()
	
	np.copyto(outputf, output, 'unsafe')

	return outputf, tot 

	plt.plot(range(0, len(out_left)), out_left)
	plt.plot(range(0, len(out_right)), out_right)
	plt.show()
	exit()
	
def main():
	outfile = sys.stdout
	audio_mode = 0 

	optlist, cut_argv = getopt.getopt(sys.argv[1:], "a")

	for o, a in optlist:
		if o == "-a":
			audio_mode = 0	# XXX: audio mode is broken

	argc = len(cut_argv)
	if argc >= 1:
		infile = open(cut_argv[0], "rb")
	else:
		infile = sys.stdin

	if (argc >= 2):
		infile.seek(int(cut_argv[1]))

	if (argc >= 3):
		total_len = int(cut_argv[2])
		limit = 1
	else:
		limit = 0

	total = toread = blocklen 
	inbuf = infile.read(toread)
	indata = np.fromstring(inbuf, 'uint8', toread)
	
	total = 0

	while (len(inbuf) > 0):
		toread = blocklen - indata.size 

		if toread > 0:
			inbuf = infile.read(toread)
			indata = np.append(indata, np.fromstring(inbuf, 'uint8', len(inbuf)))

		if audio_mode:	
			output, osamp = process_audio(indata)
#			for i in range(0, osamp):
#				print i, output[i * 2], output[(i * 2) + 1]

#			outfile.write(output)
			nread = osamp * 20 * 4
		else:
			output_16 = process_video(indata)
#			output_16.tofile(outfile)
			outfile.write(output_16)
			nread = len(output_16)

		indata = indata[nread:len(indata)]
	
		if limit == 1:
			total_len -= toread 
			if (total_len < 0):
				inbuf = ""

if __name__ == "__main__":
    main()


