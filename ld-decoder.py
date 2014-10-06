#!/usr/bin/python2
import numpy as np
import scipy as sp
import scipy.signal as sps
import sys

import fdls as fdls
import matplotlib.pyplot as plt

#import ipdb

freq = (315.0 / 88.0) * 8.0
freq_hz = freq * 1000000.0
blocklen = (3 * 1024) 

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
	
	print len(w)

	hm = np.absolute(h)
	hm2 = np.absolute(h2)

	v0 = hm[0] / hm2[0]
	for i in range(0, len(w)):
		print i, freq / 2 * (w[i] / np.pi), hm[i], hm2[i], hm[i] / hm2[i], (hm[i] / hm2[i]) / v0
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

Bboost = sps.firwin(17, [6.0/(freq/2.0), 12.5/(freq/2.0)], pass_zero=False) 
Bboost = sps.firwin(17, [4.5/(freq/2.0), 14.0/(freq/2.0)], pass_zero=False) 
Bboost = sps.firwin(33, 3.5 / (freq / 2), window='hamming', pass_zero=False)
#Bboost = sps.firwin2(25, [0, 5.4/(freq/2.0), 12.0/(freq/2.0), 14.0/(freq/2.0), 1.0], [0.0, 1.0, 2.0, 2.0, 1.0]) 
#Bboost = sps.firwin2(33, [0, 3.5/(freq/2.0), 12.0/(freq/2.0), 14.0/(freq/2.0), 1.0], [0.0, 1.0, 2.0, 2.0, 2.0]) 
#Bboost = sps.firwin2(33, [0, 3.5/(freq/2.0), 12.0/(freq/2.0), 14.0/(freq/2.0), 1.0], [0.0, 1.0, 1.0, 1.0, 1.0]) 
Bboosta = sps.firwin2(49, np.array([0, 2.0, 3.0, 4.5, 8.0, 10.0, 12.0, 14.0, freq/2.0]) / (freq/2.0), [0.0, 0.0, 0.1, 0.9, 1.0, 1.3, 2.0, 3.0, 4.0]) 
Aboost = [1.0]

#Bboost = Bboosta

n = 128 
Fr = np.zeros(n)
Am = np.zeros(n)
Th = np.zeros(n)

for f in range(0, n):
	cf = freq * (float(f) / 256.0)
     
	if (cf > 13.7):
		Am[f] = 0
	elif (cf > 9.0):
		Am[f] = 1 # + ((cf - 9.0) / 4) 
	elif (cf > 4.0):
		Am[f] = 1 
	elif (cf > 3.0):
		Am[f] = 1 * (cf - 3.0)
	else:
		Am[f] = 0

	Fr[f] = float(f) / 256.0
	Th[f] = -(Fr[f] * 42) 

[f_test_b, f_test_a] = fdls.FDLS(Fr, Am, Th, 16, 8, 0)
#doplot(f_afilt_b, f_afilt_a)
#exit()

#doplot2(Bboost, Aboost, 1.0, f_test_b, f_test_a, 1.0)
#exit()

Bboost = f_test_b
Aboost = f_test_a

lowpass_filter = sps.firwin(31, 5.2 / (freq / 2), window='hamming')
#doplot(lowpass_filter, [1.0])
#exit()

tH = 100.0/1000000000.0 # 100nS
tL = 300.0/1000000000.0 # 300nS

n = 512 
df = 512.0/(freq) 
Fr = np.zeros(n)
Am = np.zeros(n)
Th = np.zeros(n)

f_deemp_bil_b = [2.819257458245255e-01, -4.361485083509491e-01]
f_deemp_bil_a = [1.000000000000000e+00, -1.154222762526424e+00]

w, h = sps.freqz(f_deemp_bil_b, f_deemp_bil_a)
w = w / (2 * np.pi) 

Th1 = np.angle(h)
Am = np.absolute(h)/1.0

Ndeemp = 1 
Ddeemp = 1
for i in range(0, len(w)):
	Th[i] = -(Th1[i] * 1.0) 

[f_deemp_b, f_deemp_a] = fdls.FDLS(w, Am, Th, Ndeemp, Ddeemp, 0)

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

#[f_deemp_b, f_deemp_a] = fdls.FDLS(w, np.absolute(h)*1, Th, Ndeemp, Ddeemp)
[f_deemp_b, f_deemp_a] = fdls.FDLS(w, h.real*1, Th, Ndeemp, Ddeemp)

#doplot2(f_deemp_b, f_deemp_a, 1.0, f_deemp_bil_b, f_deemp_bil_a, 1.0)
#doplot2(f_deempc_b, f_deempc_a, 1.0, f_deemp_b, f_deemp_a, 1.0)
#exit()

deemp_corr = 1
deemp_corr = .496 

av = 13
# from http://tlfabian.blogspot.com/2013/01/implementing-hilbert-90-degree-shift.html
hilbert_filter = np.fft.fftshift(
   # np.fft.ifft([0]+[1]*20+[0]*20)
    np.fft.ifft([0]+[1]*av+[0]*av)
)

#hilbert_filter = [+0.0000000000, +0.0164307736, +0.0000000000, +0.0727931242, +0.0000000000, +0.2386781263, +0.0000000000, +0.9649845850, +0.0000000000, -0.9649845850, -0.0000000000, -0.2386781263, -0.0000000000, -0.0727931242, -0.0000000000, -0.0164307736, 0]

def process(data):
	# perform general bandpass filtering
	in_len = len(data)
#	in_filt = sps.fftconvolve(data, bandpass_filter)
	in_filt1 = sps.lfilter(Bboost, Aboost, data)
#	in_filt = sps.lfilter(f_afilt_b, f_afilt_a, in_filt1)
#	in_filt = sps.lfilter(arfilt, [1.0], in_filt2)

	in_filt = in_filt1
	
#	in_filt = sps.lfilter(Bboost, Aboost, data)

	#hilbert = sps.lfilter(hilbert_filter, 1.0, in_filt) 
	hilbert = sps.hilbert(in_filt)

	# the hilbert transform has errors at the edges.  but it doesn't seem to matter much IRL
	hilbert = hilbert[128:len(hilbert)-128]
	#hilberta = hilberta[128-av:len(hilbert)-128-av]

	in_len -= 256 

	tangles = np.angle(hilbert) 
	dangles = np.empty(in_len - 80)

	dangles = np.diff(tangles[128:])

	# make sure unwapping goes the right way
	if (dangles[0] < -np.pi):
		dangles[0] += (np.pi * 2)
	
	tdangles2 = np.unwrap(dangles) 
	
	output = (sps.fftconvolve(tdangles2, lowpass_filter) * 4557618)[128:len(tdangles2)]

	# particularly bad bits can cause phase inversions.  detect and fix when needed - the loops are slow in python.
	if (output[np.argmax(output)] > freq_hz):
		for i in range(0, len(output)):
			if output[i] > freq_hz:
				output[i] = output[i] - freq_hz
	
	if (output[np.argmin(output)] < 0):
		for i in range(0, len(output)):
			if output[i] < 0:
				output[i] = output[i] + freq_hz

	return output
	output = (sps.lfilter(f_deemp_b, f_deemp_a, output)[128:len(output)]) / deemp_corr
	print output

	plt.plot(range(0, len(output)), output)
#	plt.ylim([7500000,9500000])
	plt.show()
	exit()

outfile = sys.stdout
#outfile = open("snwp.ld", "wb")
#indata = []

argc = len(sys.argv)
if argc >= 2:
	infile = open(sys.argv[1], "rb")
else:
	infile = sys.stdin

if (argc >= 3):
	infile.seek(int(sys.argv[2]))

if (argc >= 4):
	total_len = int(sys.argv[3])
	limit = 1
else:
	limit = 0

total = toread = blocklen 
inbuf = infile.read(toread)
indata = np.fromstring(inbuf, 'uint8', toread)
	
total = 0

charge = 0
scharge = 0
prev = 9300000

hp_nr_filter = sps.firwin(31, 1.8 / (freq / 2), window='hamming', pass_zero=False)
#doplot(hp_nr_filter, [1.0])
#exit()

minire = -60
maxire = 140
hz_ire_scale = (9300000 - 8100000) / 100

minn = 8100000 + (hz_ire_scale * -60)

out_scale = 65534.0 / (maxire - minire)

while (len(inbuf) > 0):
	toread = blocklen - indata.size 

	if toread > 0:
		inbuf = infile.read(toread)
		indata = np.append(indata, np.fromstring(inbuf, 'uint8', len(inbuf)))
	
	output = process(indata)

	foutput = (sps.lfilter(f_deemp_b, f_deemp_a, output)[128:len(output)]) / deemp_corr

	output_16 = np.empty(len(foutput), dtype=np.uint16)

	reduced = (foutput - minn) / hz_ire_scale

	output = np.clip(reduced * out_scale, 0, 65535) 
	
	np.copyto(output_16, output, 'unsafe')

	outfile.write(output_16)
	
	indata = indata[len(output_16):len(indata)]
	
	if limit == 1:
		total_len -= toread 
		if (total_len < 0):
			inbuf = ""
