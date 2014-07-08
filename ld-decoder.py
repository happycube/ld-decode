#!/usr/bin/python2
import numpy as np
import scipy as sp
import scipy.signal as sps
import sys

import fdls as fdls

#import ipdb

freq = (315.0 / 88.0) * 8.0
freq_hz = freq * 1000000.0
blocklen = 32768 

bandpass_filter = [1.054426894146890e-04, -4.855229756583843e-05, -1.697044474992538e-04, -7.766136246382485e-04, 9.144665108615849e-04, -1.491605732025549e-04, -2.685488739297526e-03, 7.285040311086869e-03, -4.774190752742531e-03, 3.330240008284701e-03, 2.358989562928025e-02, -3.821800878599309e-02, 3.820884674542058e-02, 4.425991853422013e-02, -2.472175319907102e-01, -1.569521671065990e-02, 3.841248896214869e-01, -1.569521671065990e-02, -2.472175319907102e-01, 4.425991853422012e-02, 3.820884674542059e-02, -3.821800878599308e-02, 2.358989562928026e-02, 3.330240008284701e-03, -4.774190752742532e-03, 7.285040311086868e-03, -2.685488739297526e-03, -1.491605732025550e-04, 9.144665108615855e-04, -7.766136246382485e-04, -1.697044474992539e-04, -4.855229756583846e-05, 1.054426894146890e-04]

Nboost = 6 
Fr = np.array([0, 3.2, 7.3, 9.3, 11.3, 12.5, freq]) / (freq * 1.0)
Am = np.array([0, 0, 1.3, 2.0, 1.3, .05, 0]) / 100.0
#Am = np.array([0, 0, 1.0, 1.0, 1.0, .05, 0]) / 100.0
Th = np.zeros(7)
[Bboost, Aboost] = fdls.FDLS(Fr, Am, Th, Nboost, Nboost)

lowpass_filter = sps.firwin(19, 5.0 / (freq / 2), window='hamming')

Ndeemp = 4
Ddeemp = 11
Fr = np.array([0,   .5000, 2.00, 2.90, 3.9, 6.0, 10]) / (freq)
Am = np.array([100, 84.0,    45,   45, 60,  70 , 00]) / 100.0
Am = np.array([100, 84.0,    40,  45, 55,  60 , 00]) / 100.0
Th = np.zeros(len(Fr))

[f_deemp_b, f_deemp_a] = fdls.FDLS(Fr, Am, Th, Ndeemp, Ddeemp)

def process(data):
	# perform general bandpass filtering
	in_len = len(data)
#	in_filt = sps.fftconvolve(data, bandpass_filter)
	in_filt = sps.lfilter(Bboost, Aboost, data)

	hilbert = sps.hilbert(in_filt) 

	tangles = np.angle(hilbert) 
	dangles = np.empty(in_len - 80)

	dangles = np.diff(tangles[64:])

	# make sure unwapping goes the right way
	if (dangles[0] < -np.pi):
		dangles[0] += (np.pi * 2)
	
	tdangles2 = np.unwrap(dangles) 
	
	output = (sps.fftconvolve(tdangles2, lowpass_filter) * 4557618)[32:len(tdangles2)]

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
else:
	total_len = 2^62

total = toread = blocklen 
inbuf = infile.read(toread)
indata = np.fromstring(inbuf, 'uint8', toread)
	
total = 0

charge = 0
scharge = 0
prev = 9300000

while (len(inbuf) > 0) and (total_len > 0):
	toread = blocklen - indata.size 
	total_len -= toread 

	if toread > 0:
		inbuf = infile.read(toread)
		indata = np.append(indata, np.fromstring(inbuf, 'uint8', len(inbuf)))
	
	output = process(indata)

	foutput = sps.lfilter(f_deemp_b, f_deemp_a, output)[32:len(output)]
	output_16 = np.empty(len(foutput), dtype=np.uint16)

	reduced = (foutput - 7600000) / 1700000.0
	output = np.clip(reduced * 57344.0, 1, 65535) 
	
	np.copyto(output_16, output, 'unsafe')

#	for i in range(0, len(output)):
#		output_16[i] = output[i]

	outfile.write(output_16)
	
	indata = indata[len(output_16):len(indata)]


