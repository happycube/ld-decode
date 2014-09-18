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
blocklen = 32768 

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

ffreq = freq/2.0

Bboost = sps.firwin(17, [6.0/(freq/2.0), 12.5/(freq/2.0)], pass_zero=False) 
Bboost = sps.firwin(17, [4.5/(freq/2.0), 14.0/(freq/2.0)], pass_zero=False) 
Bboost = sps.firwin(33, 3.5 / (freq / 2), window='hamming', pass_zero=False)
#Bboost = sps.firwin2(25, [0, 5.4/(freq/2.0), 12.0/(freq/2.0), 14.0/(freq/2.0), 1.0], [0.0, 1.0, 2.0, 2.0, 1.0]) 
#Bboost = sps.firwin2(37, [0, 4.0/(freq/2.0), 12.0/(freq/2.0), 14.0/(freq/2.0), 1.0], [0.0, 1.0, 2.0, 3.0, 2.0]) 
Aboost = [1.0]
#doplot(Bboost, Aboost)
#exit()

n = 128 
Fr = np.zeros(n)
Am = np.zeros(n)
Th = np.zeros(n)

for f in range(0, n):
	cf = freq * (float(f) / 256.0)
     
	if (cf > 1.0) and (cf < 3.5):
		Am[f] = 0 
	else:
		Am[f] = 1

	Fr[f] = float(f) / 256.0
	Th[f] = -(Fr[f] * 19) 

[f_afilt_b, f_afilt_a] = fdls.FDLS(Fr, Am, Th, 12, 1)
#doplot(f_afilt_b, f_afilt_a)
#exit()

#alfilt = sps.firwin(11, [2.10/ffreq, 3.10/ffreq])
#arfilt = sps.firwin(9, [2.60/ffreq, 3.00/ffreq])

freqh = freq / 2
lowpass_filter = sps.firwin(31, 5.2 / (freq / 2), window='hamming')
#lowpass_filter = sps.firwin(15, 4.3 / (freq / 2), window='hamming')
#doplot(lowpass_filter, [1.0])
#exit()

tH = 100.0/1000000000.0 # 100nS
tL = 300.0/1000000000.0 # 300nS

n = 128
df = 128.0/(freq/2) 
Fr = np.zeros(n + 1)
Frh = np.zeros(n + 1)
Am = np.zeros(n + 1)
Th = np.zeros(n + 1)

for f in range(0, n + 1):
        F = ((float(f) / df) * 1000000.0) + 1
        H = 2.0 * np.pi * F * tH
        L = 2.0 * np.pi * F * tL

        A = 1.0 + (1.0 / (H * H))
        B = 1.0 + (1.0 / (L * L))

        DE = ((10.0*np.log(A/B))-21.9722457733) * (10.0 / 21.9722457733)
        DE = ((10.0*np.log(A/B))-20) * (10.0 / 20)
	cf = (float(f) / df)

        Fr[f] = cf / freq
        Frh[f] = cf / (freq / 2.0)
        Am[f] = np.power(10, (DE/20.0)) 

#	print f, Fr[f], Fr[f] * freq, Am[f]

Ndeemp = 8
Ddeemp = 5

for i in range(0, len(Fr)):
	Th[i] = -(Fr[i] * 5040) / 180.0
	Th[i] = -(Fr[i] * 29.4) 
	Th[i] = -(Fr[i] * 30.0) 
	Th[i] = -(Fr[i] * 30.0) 
	Th[i] = -(Fr[i] * 29.5) 

[f_deemp_b, f_deemp_a] = fdls.FDLS(Fr, Am, Th, Ndeemp, Ddeemp)

# [b, a] = bilinear(.3e-8, .1e-8, (1/3), 28636363*2); freqz(b, a)

f_deemp_b = [0.28193,  -0.43615] 
f_deemp_a = [1.0000 , -1.1542]
#doplot(f_deemp_b, f_deemp_a)
#exit()

freqh = freq / 2
f_deemp_b = sps.firwin2(257, Frh, Am) 
f_deemp_a = 1.0
doplot(f_deemp_b, [1.0])
exit()

#f_deemp_b = sps.firwin2(125, Fr, Am)
#f_deemp_b = [1.0]
#f_deemp_a = [1.0]

w, h = sps.freqz(B, A)
deemp_corr = ((h[0].real - 1) / 1.15) + 1
deemp_corr = h[0].real 

#deemp_corr = 0.9945
#deemp_corr = 0.9915
deemp_corr = 1.0
deemp_corr = .988

#doplot(alfilt, [1.0])
#exit()

# from http://tlfabian.blogspot.com/2013/01/implementing-hilbert-90-degree-shift.html
hilbert_filter = np.fft.fftshift(
    np.fft.ifft([0]+[1]*20+[0]*20)
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

	hilbert = sps.lfilter(hilbert_filter, 1.0, in_filt) 

	# the hilbert transform has errors at the edges.  but it doesn't seem to matter much IRL
	hilbert = hilbert[128:len(hilbert)-128]
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

	output = output[1500:2800]

#	output = (sps.lfilter(Blpf, Alpf, tdangles2) * 4557618)[128:len(tdangles2)]
	#output = (tdangles2 * 4557618)[128:len(tdangles2)]
	reduced = (output - 7600000) / 1700000.0
	output = np.clip(reduced * 57344.0, 0, 65535) 

	mean = np.mean(output)
	mean_ire = ((160.0 / 65533.0) * mean) - 40
	std_ire = ((160.0 / 65533.0) * np.std(output))
	print "mean ire: ", mean, ((160.0 / 65533.0) * mean) - 40
	print "stddev", std_ire
	print "SNR", 20 * np.log10((((160.0 / 65533.0) * mean) - 40) / std_ire)


	exit()

	return output

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

zi = sps.lfilter_zi(f_deemp_b, f_deemp_a)

while (len(inbuf) > 0):
	toread = blocklen - indata.size 

	if toread > 0:
		inbuf = infile.read(toread)
		indata = np.append(indata, np.fromstring(inbuf, 'uint8', len(inbuf)))
	
	output = process(indata)

	foutput = (sps.lfilter(f_deemp_b, f_deemp_a, output)[128:len(output)]) / deemp_corr

#	print len(output), len(foutput)
#	for i in range(256, 3072):
#		print output[i + 128], foutput[i]

	output_16 = np.empty(len(foutput), dtype=np.uint16)

	reduced = (foutput - 7600000) / 1700000.0

	output = np.clip(reduced * 57344.0, 0, 65535) 
	
	np.copyto(output_16, output, 'unsafe')

	outfile.write(output_16)
	
	indata = indata[len(output_16):len(indata)]
	
	if limit == 1:
		total_len -= toread 
		if (total_len < 0):
			inbuf = ""
