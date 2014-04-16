import numpy as np
import scipy as sp
import scipy.signal as sps
import sys

freq = (315.0 / 88.0) * 8.0
freq_hz = freq * 1000000.0
blocklen = 32768 

bandpass_filter = [1.054426894146890e-04, -4.855229756583843e-05, -1.697044474992538e-04, -7.766136246382485e-04, 9.144665108615849e-04, -1.491605732025549e-04, -2.685488739297526e-03, 7.285040311086869e-03, -4.774190752742531e-03, 3.330240008284701e-03, 2.358989562928025e-02, -3.821800878599309e-02, 3.820884674542058e-02, 4.425991853422013e-02, -2.472175319907102e-01, -1.569521671065990e-02, 3.841248896214869e-01, -1.569521671065990e-02, -2.472175319907102e-01, 4.425991853422012e-02, 3.820884674542059e-02, -3.821800878599308e-02, 2.358989562928026e-02, 3.330240008284701e-03, -4.774190752742532e-03, 7.285040311086868e-03, -2.685488739297526e-03, -1.491605732025550e-04, 9.144665108615855e-04, -7.766136246382485e-04, -1.697044474992539e-04, -4.855229756583846e-05, 1.054426894146890e-04]

#for i in range(0, len(bandpass_filter)):
#	print bandpass_filter[i], ",",  

lowpass_filter = sps.firwin(18, 5.0 / (freq / 2), window='hamming')
for i in range(0, len(lowpass_filter)):
	print "%.15e" % lowpass_filter[i], ",",  
exit()
#print
#lowpass_filter = [-5.182956535966573e-04, -4.174028437151462e-03, -1.126381254549101e-02, -1.456598548706209e-02, 3.510439201231994e-03, 5.671595743858979e-02, 1.370914830220347e-01, 2.119161192395519e-01, 2.425762464437853e-01, 2.119161192395519e-01, 1.370914830220347e-01, 5.671595743858982e-02, 3.510439201231995e-03, -1.456598548706209e-02, -1.126381254549101e-02, -4.174028437151466e-03, -5.182956535966573e-04]

bands = [8700000] 
	
def process(data):
	# perform general bandpass filtering
	in_len = len(data)
	in_filt = sps.fftconvolve(data, bandpass_filter)

	ohet = np.empty([len(bands), in_len + 32], dtype=complex)
	ohet_filt = np.empty([len(bands), in_len + 32], dtype=complex)
	ohet_filtn = np.empty([len(bands), in_len + 48], dtype=complex)
	angles = np.empty([len(bands), in_len + 48])
	dangle = np.empty([len(bands), in_len + 48])
	abs_dangle = np.empty([len(bands), in_len + 48])
	levels = np.empty([len(bands), in_len + 48])
	output = np.empty(in_len)

#	print len(in_filt) 

	# heterodyning
	for b in range(len(bands)):
		if len(in_filt) == len(het[b]):
			ohet[b] = np.multiply(in_filt, het[b])
		else:
			for i in range(in_len): 
				ohet[b][i] = in_filt[i] * het[b][i]	

	# lowpass filtering
	for b in range(len(bands)):
		ohet_filtn[b] = sps.fftconvolve(ohet[b], lowpass_filter)
		levels[b] = np.absolute(ohet_filtn[b]) 
		angles[b] = np.angle(ohet_filtn[b]) 

		for i in range(0, in_len):
			adiff = angles[b][i] - angles[b][i - 1]

			if (adiff < -np.pi):
				adiff += (np.pi * 2)
			if (adiff > np.pi):
				adiff -= (np.pi * 2)
			
			dangle[b][i] = adiff

		abs_dangle[b] = np.fabs(dangle[b])

	# select strongest signal
	for i in range(0, in_len):
		peaklevel = 500 
		peakband = -1

#		print i, 
		for b in range(len(bands)):
#			print dangle[b][i], 
			if (abs_dangle[b][i] < peaklevel):
				peaklevel = abs_dangle[b][i]
				peakband = b

		output[i] = bands[peakband] - ((bands[peakband] / 2.0) * dangle[peakband][i])
	#	print levels[peakband][i], output[i]

	return np.delete(output, np.s_[0:128])

# setup

#bands = [8100000, 8700000, 9300000] 
#bands = [8700000] 

# need extra entries for heterodyning, aparently fftconvolve can lengthen the signal?  huh?
het = np.empty([len(bands), blocklen + 16], dtype=complex)

for b in range(len(bands)):
	fmult = bands[b] / freq_hz 
	for i in range(blocklen + 16): 
		het[b][i] = complex(np.sin(i * 2.0 * np.pi * fmult), -(np.cos(i * 2.0 * np.pi * fmult))) 
	print het[b][100],

print


# actual work

infile = open("mb.raw", "rb")
outfile = open("testpy.ld", "wb")
#indata = []

total = toread = blocklen 
inbuf = infile.read(toread)
indata = np.fromstring(inbuf, 'uint8', toread)
	
total = 0

charge = 0
scharge = 0
prev = 9300000

while len(inbuf) > 0:
	toread = blocklen - indata.size 

	if toread > 0:
		inbuf = infile.read(toread)
		indata = np.append(indata, np.fromstring(inbuf, 'uint8', len(inbuf)))
	
	output = process(indata)
	output_16 = np.empty(len(output), dtype=np.uint16)

	for i in range(0, len(output)):
		# (less) cruddy attempt at deemphasis
		n = output[i]

		charge = charge + ((n - prev) * 1.0)
#		print i, n, charge, 
		prev = n
		n = n - (charge * 0.60) 
		charge = charge * 0.90
#		print n

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

