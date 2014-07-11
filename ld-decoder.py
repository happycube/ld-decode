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

bandpass_filter = [1.054426894146890e-04, -4.855229756583843e-05, -1.697044474992538e-04, -7.766136246382485e-04, 9.144665108615849e-04, -1.491605732025549e-04, -2.685488739297526e-03, 7.285040311086869e-03, -4.774190752742531e-03, 3.330240008284701e-03, 2.358989562928025e-02, -3.821800878599309e-02, 3.820884674542058e-02, 4.425991853422013e-02, -2.472175319907102e-01, -1.569521671065990e-02, 3.841248896214869e-01, -1.569521671065990e-02, -2.472175319907102e-01, 4.425991853422012e-02, 3.820884674542059e-02, -3.821800878599308e-02, 2.358989562928026e-02, 3.330240008284701e-03, -4.774190752742532e-03, 7.285040311086868e-03, -2.685488739297526e-03, -1.491605732025550e-04, 9.144665108615855e-04, -7.766136246382485e-04, -1.697044474992539e-04, -4.855229756583846e-05, 1.054426894146890e-04]

Bboost = sps.firwin(15, [3.5/(freq/2.0), 13.0/(freq/2.0)], pass_zero=False) 
Aboost = [1.0]

lowpass_filter = sps.firwin(19, 5.0 / (freq / 2), window='hamming')

Ndeemp = 5 
Ddeemp = 7
Fr = np.array([0,   .5000, 1.60, 2.90, 3.9, 6.0, 12]) / (freq)
Am = np.array([100, 84.0,    40,  45, 55,  60 , 00]) / 100.0
Am = np.array([100, 84.0,    40,  43, 50,  50 , 00]) / 100.0
Am = np.array([100, 84.0,    40,  43, 55,  60 , 00]) / 100.0
Am = np.array([100, 84.0,    40,  40, 40,  50 , 33]) / 100.0

Fr = np.array([0,   .5000, 2.00, 5, freq]) / (freq)
Am = np.array([100,  85.0,   33, 40,   0]) / 100.0
Th = np.array([0, -100, -200, -300, -500]) / 180.0
Th = np.zeros(len(Fr))

# 503 v2, also good de-emp for 2800, but lower FR
#Fr = np.array([0,   .5000, 1.60, 3.00, 4.2, 5.0, 10.0]) / (freq * 2.0)
#Am = np.array([100, 84.0,    45,   45, 60,  70 , 00]) / 100.0
#Th = np.zeros(len(Fr))

tH = 100.0/1000000000.0 # 100nS
tL = 300.0/1000000000.0 # 300nS

n = 70
df = 5 
Fr = np.zeros(n)
Am = np.zeros(n)
Th = np.zeros(n)

for f in range(0, n):
        F = ((float(f) / df) * 1000000.0) + 1
        H = 2.0 * np.pi * F * tH
        L = 2.0 * np.pi * F * tL

#       print H, L

        A = 1.0 + (1.0 / (H * H))
        B = 1.0 + (1.0 / (L * L))

        DE = ((10.0*np.log(A/B))-21.9722457733) * (10.0 / 21.9722457733)
#        print f, np.log(A/B), np.power(10, DE / 24.0)

	cf = (float(f) / df)

        Fr[f] = cf / freq
        Am[f] = np.power(10, (DE/20.0)) 

	if (cf > 5.5):
		cf = 5.5

#	if (cf > 2.5) and (cf < 5.5):
#		Am[f] = Am[f] + (((cf - 3.0) / 3.0) * 0.05) 
	
	#print f, Fr[f] * freq, Am[f]

Ndeemp = 6 
Ddeemp = 4
#Fr = np.array([0,   0.3, 0.5,  1.6,  3.0,  5.0, freq]) / (freq)
#Am = np.array([100,  89,77.2,46.36,38.93,.3657,    0]) / 100.0
#Th = np.zeros(len(Fr))

for i in range(0, len(Fr)):
	Th[i] = -(Fr[i] * 4600) / 180.0
#	print i, Fr[i], Th[i]

[f_deemp_b, f_deemp_a] = fdls.FDLS(Fr, Am, Th, Ndeemp, Ddeemp)

w, h = sps.freqz(B, A)
deemp_corr = ((h[0].real - 1) / 2.0) + 1

#f_deemp_b = sps.firwin2(25, np.array([0, 0.3, 0.5, 1.6, 3.0, 5.0, freq/2]) / (freq/2), [2.4, 0.89, 0.772, .4636, .3893, .3657, .353]);
#f_deemp_a = [1.0]

#exit()

def process(data):
	# perform general bandpass filtering
	in_len = len(data)
#	in_filt = sps.fftconvolve(data, bandpass_filter)
	in_filt = sps.lfilter(Bboost, Aboost, data)

	hilbert = sps.hilbert(in_filt) 

	tangles = np.angle(hilbert) 
	dangles = np.empty(in_len - 80)

	dangles = np.diff(tangles[128:])

	# make sure unwapping goes the right way
	if (dangles[0] < -np.pi):
		dangles[0] += (np.pi * 2)
	
	tdangles2 = np.unwrap(dangles) 
	
	output = (sps.fftconvolve(tdangles2, lowpass_filter) * 4557618)[128:len(tdangles2)]
	#output = (tdangles2 * 4557618)[128:len(tdangles2)]

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

while (len(inbuf) > 0):
	toread = blocklen - indata.size 

	if toread > 0:
		inbuf = infile.read(toread)
		indata = np.append(indata, np.fromstring(inbuf, 'uint8', len(inbuf)))
	
	output = process(indata)

	foutput = (sps.lfilter(f_deemp_b, f_deemp_a, output)[128:len(output)])  / deemp_corr
#	for i in range(0, len(foutput)):
#		print i, output[i], foutput[i]

#	exit()

	output_16 = np.empty(len(foutput), dtype=np.uint16)

	reduced = (foutput - 7600000) / 1700000.0
	output = np.clip(reduced * 57344.0, 1, 65535) 
	
	np.copyto(output_16, output, 'unsafe')

	outfile.write(output_16)
	
	indata = indata[len(output_16):len(indata)]
	
	if limit == 1:
		total_len -= toread 
		if (total_len < 0):
			inbuf = ""
