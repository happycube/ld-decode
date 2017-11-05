#!/usr/bin/python3

# 11/29/14:  I worked out a new way to determine sync locations by using a butterworth filter to get a sync rate (0-1)

import numpy as np
import scipy as sp
import scipy.signal as sps
import sys
import os

import io

from scipy.interpolate import interp1d
import matplotlib.pyplot as plt
from matplotlib.mlab import find

# support code

 
def dosplot(B, A):
	w, h = sps.freqz(B, A)

	fig = plt.figure()
	plt.title('Digital filter frequency response')

	ax1 = fig.add_subplot(111)

	plt.plot(w * (freq/np.pi) / 2.0, 20 * np.log10(abs(h)), 'b')
	plt.ylabel('Amplitude [dB]', color='b')
	plt.xlabel('Frequency [rad/sample]')

	plt.show()

freq = 4.0 # output frequency - 4fsc

freq_mhz = (315.0 / 88.0) * freq
freq_hz = freq * 1000000.0
blocklen = 131072 

color_filter = sps.firwin(17, 0.1 / (freq_mhz / 2), window='hamming')

# NTSC: set up sync color heterodyne table first 
bhet = np.empty(4096, dtype=np.complex)
for i in range(0, 4096):
	bhet[i] = complex(np.cos(((i / freq) * 2.0 * np.pi) + (0.0/180.0)), -(np.sin(((i / freq) * 2.0 * np.pi) + (0.0/180.0))))

def printerr(*objs):
	print(*objs, file=sys.stderr)
	return

from scipy import interpolate

# This uses numpy's interpolator, which provides very good results
def scale(buf, begin, end, tgtlen):
	print("scaling ", begin, end, tgtlen)
	ibegin = np.floor(begin)
	iend = np.floor(end)

	linelen = end - begin

	dist = iend - ibegin + 1 
	arr = np.linspace(0, dist, num=dist)
#	print(arr, dist, begin, ibegin, ibegin + dist)
	spl = interpolate.splrep(arr, buf[ibegin:ibegin + dist])
	arrout = np.linspace(begin - ibegin, linelen, tgtlen)
						
	return interpolate.splev(arrout, spl)

def sub_angle(angle):
	if (angle > (np.pi / 2)):
		return (np.pi - angle)
	elif (angle < -(np.pi / 2)):
		return (-np.pi - angle)
	else:
		return -angle

def wrap_angle(angle, tgt):
	adjust = tgt - angle
	if (adjust > (np.pi)):
		adjust -= 2 * np.pi
	elif (adjust < (-np.pi)):
		adjust += 2 * np.pi

	return adjust

def align_angle(angle):
	pid2 = np.pi / 2
	pid4 = np.pi / 4

	fangle = np.fabs(angle)

#	if (np.pi - angle) < pid4:
	if (angle > 0) and (angle < pid2):
#		print("c1")
		return angle
	elif (angle > 0) and (angle < np.pi):
#		print("c2")
		return angle - pid2
	elif (angle > 0) and (angle < pid4):
#		print("c3")
		return angle
	elif angle > -pid4:
#		print("c4")
		return -angle
	elif angle > -pid2:
#		print("c5")
		return pid2 + angle
	elif (-np.pi - angle) < pid4:
#		print("c6")
		return np.pi + angle  


# new code

# sync filter, should be usable for 4x and 8x fsc
#f_sync_b, f_sync_a = sps.butter(1, 0.5 / 14.318)
f_sync_b = sps.firwin(17, 0.5/14.318)
f_sync_a = [1.0]

f_id_b, f_id_a = sps.butter(3, 0.002)

def is_sync(x):
	return 1 if x < 24000 else 0

tgt_angle = 0

sync_filter = sps.firwin(32, 0.8 / (freq_mhz / 2), window='hamming')

# pal parameters
bfreq = 4.43361875
ofreq = bfreq * 4
oline = 1135

# 14000000 * (68.7/1000000)
# s14line = 961.8 -  oh oh.  it rounds up to 962 OK, but this could complicate the math a bit.

# we need to include the next hsync pulse and round it up to an even #.
i15line = 960  # 15000000*(64/1000000) 
ia15line = 1029  # 15000000*(68.6/1000000) 
ia4fline = 1217 # scaled ia15line up to 8M*315/88 - ntsc-8fsc
iline = 1832.727 # ntsc-8fsc * (64/1M)
ialine = 1964.4545 # scaled ia15line up to 8M*315/88 - ntsc-8fsc

outbuf = np.empty((oline * 625), dtype=np.uint16)

pilot_filter_b, pilot_filter_a = sps.butter(1, [3.65 / 7.5, 3.85 / 7.5])
#pilot_filter = sps.firwin(16, 4.5 / 7.5, window='hamming')

phet = np.empty(2048, dtype=np.complex)
pfreq = 15 / 3.75
for i in range(0, 2048):
	phet[i] = complex(np.cos(((i / pfreq) * 2.0 * np.pi) + (0.0/180.0)), -(np.sin(((i / pfreq) * 2.0 * np.pi) + (0.0/180.0))))

def quadpeak(y):
	return (y[2] - y[0]) / (2 * (2 * y[1] - y[0] - y[2]))

def pilot_detect(line, loc = 0, ilen = 60):
	cropline = line[loc:loc+ilen]
#	cropline = sps.lfilter(pilot_filter_b, pilot_filter_a, cropline) 
	cropline -= np.mean(cropline)
	acropline = np.absolute(cropline)

#	print(len(cropline))

#	indices = find((cropline[1:] >= 0) & (cropline[:-1] < 0))
#	print(indices)
	toffset = 0
	count = 0
	phase = 0
	for i in range(15, 35):
		if (cropline[i] > 5000) and (cropline[i] > cropline[i - 1]) and (cropline[i] > cropline[i + 1]):	
			phase = i % 2 
			offset = quadpeak(cropline[i-1:i+2])
			toffset += offset
			count += 1
			print(i, offset, cropline[i - 1], cropline[i], cropline[i + 1])
		elif (cropline[i] < -5000) and (cropline[i] < cropline[i - 1]) and (cropline[i] < cropline[i + 1]):	
			phase = i % 2 
			offset = quadpeak(cropline[i-1:i+2])
			toffset += offset
			count += 1
			print(i, offset, cropline[i - 1], cropline[i], cropline[i + 1])

	rv = (phase + (toffset / count))
	rv *= 2.2
	return rv

def process(indata):
	global tgt_angle 

	tcount = 0

#	indata = indata[85000:105000]
#	indata = indata[7000:10000]
#	indata = indata[0000:120000]

	indata_lf = sps.lfilter(sync_filter, [1.0], indata)[16:]

	vis_sync = np.vectorize(is_sync)
	indata_bool = vis_sync(indata) 
	indata_bool_filt = sps.lfilter(f_id_b, f_id_a, indata_bool)[330:]

	insync = -1 
	line = 0
	cline = 0

	i = 0
	prev_peak = 0
	prev_begin = 0
	prev_end = 0
	prev_len = 0
	while ((i + 4096) < len(indata_bool_filt)):
		peak = i + np.argmax(indata_bool_filt[i:i+1300])

		peakval = indata_bool_filt[peak]

		boffset = 0

		begin = -1

		crosslev = 25000
		for j in range(peak, peak - 300, -1):
			if (begin == -1) and (indata_lf[j] > crosslev):
				begin = j
				boffset = indata_lf[j] - indata_lf[j + 1]
				begin += (indata_lf[j] - crosslev) / boffset
#				print(boffset)

		end = -1
		for j in range(peak, peak + 300, 1):
			if (end == -1) and (indata_lf[j] > crosslev):
				end = j

		if begin > 0 and end > 0:
			synclen = end - begin
		else:
			synclen = 0

		print("l ", line, cline, peak, begin, end, "g", synclen, begin - prev_begin, peak - begin, indata_bool_filt[peak], indata[peak])

		if (insync <= 0) and (peakval < .18):
			if ((np.fabs(begin - prev_begin) - 910) < 100):
				print(line, "sync - half line detected")
				insync = 2 if (cline > 0) else 3
			else:
				print(line, "sync start")
				insync = 1

		if insync == 0 and cline > 0:
			inline = indata[prev_begin - 8:begin+150].astype(np.float32)

			boffset = prev_begin - np.floor(prev_begin) + 8
			eoffset = begin + 8 - np.floor(prev_begin) 

			# need to scale to 15mhz for pilot alignment
			alen = (begin - prev_begin) * (ialine / iline)
			aeoffset = boffset + alen 

			s15 = scale(inline, boffset, aeoffset, ia15line) 
			pilot_offset = pilot_detect(s15)
			print(line, " pass 1: ", boffset, aeoffset, pilot_offset)

			boffset += pilot_offset 
			aeoffset += pilot_offset 

			s15 = scale(inline, boffset, aeoffset, ia15line) 
			pilot_offset = pilot_detect(s15)
			pilot_offset2 = pilot_detect(s15, 960)
			print(boffset, pilot_offset, pilot_offset2) 
			print(line, " pass 2: ", boffset, aeoffset, pilot_offset, pilot_offset2)

			if (pilot_offset2 < 2.0):
				aeoffset += (pilot_offset2) 
				s15 = scale(inline, boffset, aeoffset, ia15line) 
				pilot_offset = pilot_detect(s15)
				pilot_offset2 = pilot_detect(s15, 960)
				print(line, " pass 3: ", boffset, aeoffset, pilot_offset, pilot_offset2)
	
#			plt.show()
#			exit()

			out1 = scale(inline, boffset, aeoffset, ia4fline)[0:1135] 
			#out1 = scale(inline, 8 + prev_begin - np.floor(prev_begin), eoffset, oline)
			out1 = np.clip(out1, 0, 65535)

			outbuf[(cline * oline):(cline + 1) * oline] = out1 

#			print("scaler", prev_begin, begin, end = ' ' ) 

		# needs to be done first becausse the first line is written normally
		if (insync >= 1):
			if (peakval > .18) and (peakval < .8):
				print(line, "sync over")
				if insync == 1:
					if (cline > 0):
						outfile.write(outbuf)				
					cline = 8
				elif insync == 2:
					cline = 7
				else:
					cline = 0

				insync = 0

		i = peak + 800
		prev_len = end - prev_end 
		prev_peak = peak
		prev_begin = begin
		prev_end = end 
		line = line + 1

		if (cline > 0):
			cline += 2

#	print(i, i - prev_i, indata_bool_filt[i])


#	print(len(indata), tcount)
#	exit()

#	for i in range(0, len(indata_bool_filt), 50000):
#		print(i, indata_bool_filt[np.argmax(indata_bool_filt[i:i+50000])])

#	plt.plot(range(0,len(indata_bool_filt)), indata_bool_filt)
#	plt.plot(range(0,len(indata_bool)), indata_bool)
#	plt.plot(range(0,len(indata)), indata / 65535.0)
#	plt.show()
	exit()

	return 1820*505

# buffer enough to hold two entire frames and change - probably only need one, but ram is cheap nowadays 
buftgt = 1820 * 1200

# ???
indata_valid = 0
indata = np.empty(buftgt, dtype=np.uint16)

outfile = open("testpal.tbc", "wb")

def main(argv=None):
	infile = sys.stdin.buffer

	done = 0

	inbuf = infile.read(buftgt * 2)
	indata = np.fromstring(inbuf, 'uint16', buftgt)

	while (done == 0):
		keep = process(indata)
		indata = indata[keep:]

		toread = buftgt - len(indata)
		inbuf = infile.read(toread * 2)
		
		print(toread * 2, len(inbuf), len(indata))

		if (len(inbuf) < toread):
			done = 1

		indata = np.append(indata, np.fromstring(inbuf, 'uint16', int(len(inbuf) / 2)))

		print(len(inbuf), len(indata))

if __name__ == "__main__":
    sys.exit(main())

