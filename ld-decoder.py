import numpy as np
import scipy as sp
import scipy.signal as sps
import sys

freq = (315.0 / 88.0) * 8.0
freq_hz = freq * 1000000.0
blocklen = 2048 

bandpass_filter = sps.firwin(17, [0.10, 0.45])

bandpass_filter = [3.023991564221081e-03, 4.233186409767337e-03, 7.954665760931824e-03, 2.061366484849445e-03, -1.422694634466230e-03, -7.408019315126677e-02, -1.359026202658482e-01, -6.450343643150648e-01, 1.689996991838728e+00, -6.450343643150648e-01, -1.359026202658483e-01, -7.408019315126678e-02, -1.422694634466230e-03, 2.061366484849445e-03, 7.954665760931824e-03, 4.233186409767340e-03, 3.023991564221081e-03]
#for i in range(0, len(bandpass_filter)):
#	print bandpass_filter[i], ",",  

lowpass_filter = sps.firwin(17, 3.0 / (freq / 2))

def process(data):
	# perform general bandpass filtering
	in_len = len(data)
	in_filt = sps.fftconvolve(data, bandpass_filter)

	ohet = np.empty([len(bands), in_len], dtype=complex)
	ohet_filt = np.empty([len(bands), in_len], dtype=complex)
	ohet_filtn = np.empty([len(bands), in_len + 16], dtype=complex)
	angles = np.empty([len(bands), in_len + 16])
	levels = np.empty([len(bands), in_len + 16])
	output = np.empty(in_len)

	# heterodyning
	for b in range(len(bands)):
		for i in range(in_len): 
			ohet[b][i] = in_filt[i] * het[b][i]	

	# lowpass filtering
	for b in range(len(bands)):
		ohet_filtn[b] = sps.fftconvolve(ohet[b], lowpass_filter)
		levels[b] = np.absolute(ohet_filtn[0]) 
		angles[b] = np.angle(ohet_filtn[0]) 

	# select strongest signal
	for i in range(0, in_len):
		peaklevel = 0
		peakband = -1
		for b in range(len(bands)):
			if (levels[b][i] > peaklevel):
				peaklevel = levels[b][i]
				peakband = b

		adiff = angles[peakband][i] - angles[peakband][i - 1]

		if (adiff < -np.pi):
			adiff += (np.pi * 2)
		if (adiff > np.pi):
			adiff -= (np.pi * 2)

		output[i] = bands[peakband] - ((bands[peakband] / 2.0) * adiff)

	return np.delete(output, np.s_[0:128])

# setup

bands = [8100000, 8700000, 9300000] 
#bands = [8700000] 

# need extra entries for heterodyning, aparently fftconvolve can lengthen the signal?  huh?
het = np.empty([len(bands), blocklen + 128], dtype=complex)

for b in range(len(bands)):
	fmult = bands[b] / freq_hz 
	for i in range(blocklen + 128): 
		het[b][i] = complex(np.sin(i * 2.0 * np.pi * fmult), -(np.cos(i * 2.0 * np.pi * fmult))) 

# actual work

infile = open("rd.raw", "rb")
outfile = open("testpy.ld", "wb")
#indata = []

total = toread = 2048 
inbuf = infile.read(toread)
indata = np.fromstring(inbuf, 'uint8', toread)
	
deemp_loop = np.zeros(9)
for i in range(0, 9):
	deemp_loop[i] = 8700000
total = 0

while len(inbuf) > 0:
	toread = 2048 - indata.size 

	if toread > 0:
		inbuf = infile.read(toread)
		indata = np.append(indata, np.fromstring(inbuf, 'uint8', len(inbuf)))
	
	output = process(indata)
	output_16 = np.empty(len(output), dtype=np.uint16)

	for i in range(0, len(output)):
		# cruddy attempt at deemphasis
		idl = total % 7
		n = output[i]
		diff = n - deemp_loop[idl]
		n -= (diff * .25)
		deemp_loop[idl] = n

		n = (n - 7600000.0) / 1700000.0
		if n < 0:
			n = 0;
		n = 1 + (n * 57344.0)
		if n > 65535:
			n = 65535

		output_16[i] = n	
		total+=1

	outfile.write(output_16)
	
	indata = np.delete(indata, np.s_[0:len(output)])

	total += toread

