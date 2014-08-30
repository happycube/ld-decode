from __future__ import print_function
import numpy as np
import scipy as sp
import scipy.signal as sps
import sys

from scipy.interpolate import interp1d

import fdls as fdls

freq = 8.0

freq_mhz = (315.0 / 88.0) * freq
freq_hz = freq * 1000000.0
blocklen = 65536 * 8 

# inframe is a 1685x505 uint16 buffer.  basically an ntsc frame with syncs removed

prevframe = np.empty([508, 1685], dtype=np.uint16)
prevrgb = np.empty([480, 1488 * 3], dtype=np.uint8)

burst_len = 28 * 4

color_filter = sps.firwin(33, 0.3 / (freq), window='hamming')
sync_filter = sps.firwin(33, 0.1 / (freq), window='hamming')

Nlpf = 8
Dlpf = 8
Fr = np.array([0, 0.6, 2.0, freq]) / (freq)
Am = np.array([100, 80, 00, 0]) / 100.0
#Am = np.array([0, 0, 1.0, 1.0, 1.0, .05, 0]) / 100.0
Th = np.zeros(4)
[Bcolor, Acolor] = fdls.FDLS(Fr, Am, Th, Nlpf, Dlpf)

Nlpf = 12 
Dlpf = 8 
Fr = np.array([0, 0.1, 0.3, freq]) / (freq *2)
Am = np.array([100, 95, 00, 0]) / 100.0
#Am = np.array([0, 0, 1.0, 1.0, 1.0, .05, 0]) / 100.0
Th = np.zeros(4)
for i in range(0, len(Fr)):
	Th[i] = -(Fr[i] * 2000) / 180.0
[Bsync, Async] = fdls.FDLS(Fr, Am, Th, Nlpf, Dlpf)

#fdls.doplot(freq_mhz, sync_filter, [1.0])
#fdls.doplot(freq_mhz, Bsync, Async)
#exit()

frame = np.empty([505, 1685], dtype=np.uint16)

# set up sync color heterodyne table first 
bhet = np.empty(100, dtype=np.complex)
for i in range(0, 100):
	bhet[i] = complex(np.cos(((i / freq) * 2.0 * np.pi) + (33.0/180.0)), -(np.sin(((i / freq) * 2.0 * np.pi) + (33.0/180.0))))
	bhet[i] = complex(np.cos(((i / freq) * 2.0 * np.pi) + (0.0/180.0)), -(np.sin(((i / freq) * 2.0 * np.pi) + (0.0/180.0))))

burst_len = 300

def printerr(*objs):
#	print(*objs, file=sys.stderr)
	return

def burst_detect(line):
	level = 0
	phase = 0

	obhet = np.empty(100, dtype=np.complex)

	obhet = bhet * line[140:240]
#	for i in range(140, 239):
#		obhet[i - 140] = bhet[i % 8] * line[i]

	obhet_filt = sps.lfilter(sync_filter, [1.0], obhet)
	obhet_levels = np.absolute(obhet_filt)
	obhet_angles = np.angle(obhet_filt)

	for i in range(0, 100):
		if (obhet_levels[i] > level) and (obhet_levels[i] < 10000):
			level = obhet_levels[i]
			phase = obhet_angles[i]

	return [level, phase]

level_m40ire = 1;
level_0ire = 16384;
level_7_5_ire = 16384+3071;
level_100ire = 57344;
level_120ire = 65535;

from scipy import interpolate

def getline(l):
	if (l != np.floor(l)):
		l = l + 0.5

	if (l < 10):
		return -1
	elif (l < 262):
		return (l - 10) * 2
	elif (l < 271):
		return -1
	elif (l > 524):
		return -1
	
	return ((l - 273) * 2) + 1 

# essential constants
freq = 8.0
ntsc_linelength = 227.5 * freq
# this is the hblank interval except for front porch
ntsc_blanklen = 9.2
ntsc_hsynctoline = np.floor(ntsc_linelength * ntsc_blanklen / 63.5) 

scale_linelen = ((63.5 + ntsc_blanklen) / 63.5)	# add to non-TBC line length to get second hblank
scale_tgt = ntsc_linelength + ntsc_hsynctoline

#frame = np.empty([505, 1685 + ntsc_hsynctoline], dtype=np.uint16)

def scale(buf, begin, end, tgtlen):
	ibegin = np.floor(begin)
	iend = np.floor(end)

	linelen = end - begin

	dist = iend - ibegin + 1 
	arr = np.linspace(0, dist, num=dist)
#	print len(arr), dist #, len(buf[np.floor(crosspoint):np.floor(crosspoint) + dist])
	spl = interpolate.splrep(arr, buf[ibegin:ibegin + dist])
	arrout = np.linspace(begin - ibegin, linelen, tgtlen)
						
#	return np.clip(interpolate.splev(arrout, spl), 0, 65535)
	return interpolate.splev(arrout, spl)

def wrap_angle(angle, tgt):
	adjust = tgt - angle
	if (adjust > (np.pi)):
		adjust -= 2 * np.pi
	elif (adjust < (-np.pi)):
		adjust += 2 * np.pi

	return adjust

line = -2
tgt_phase = 0

def find_sync(buf):
	count = 0
	global line, tgt_phase

#	print buf
	filtered = sps.fftconvolve(buf, sync_filter)[len(sync_filter) / 2:]

	cross = 5000
	prev_crosspoint = -1

	for i in range(0, len(buf) - 4096):
#		print i, filtered[i], buf[i], buf[i + (len(sync_filter) / 2)]
		if (filtered[i] < cross):
			if (count == 0):
				d = filtered[i - 1] - filtered[i]
				c = (filtered[i - 1] - cross) / d

				crosspoint = i + c

				#print c, d, filtered[i - 1], filtered[i]
				
			count = count + 1
		else:
			if (count > 30):
				d = filtered[i] - filtered[i - 1]
				c = (filtered[i] - cross) / d
	#			print (i + c) - crosspoint, i - count, count

				l = buf[i:i + 1820]
	#			print burst_detect(l)

				if (prev_crosspoint > 0):
					begin = prev_crosspoint
					end = begin + ((crosspoint - prev_crosspoint) * scale_linelen) 
					linelen = np.floor(crosspoint - prev_crosspoint)

					if (end > len(buf)):
						return np.floor(prev_crosspoint) - 100 

#					print crosspoint, prev_crosspoint, crosspoint - prev_crosspoint, count
					if (line >= 0) and (linelen > 1800) and (count > 90):
						outl = getline(line)

#						print line, outl
						printerr(line, outl) 

						out = scale(buf, begin, end, scale_tgt)

						angle = burst_detect(out)[1]

						if tgt_phase:
							tgt_phase = -tgt_phase
						elif angle < 0 and (angle > -(3 * np.pi / 4)):
							tgt_phase = -np.pi / 2
						else:
							tgt_phase = np.pi / 2
	
						adjust = wrap_angle(angle, tgt_phase) 
						
#						print outl, angle, angle2, adjust
						rate = (crosspoint - prev_crosspoint) / 1820.0
#						printerr(outl, angle, angle2, (crosspoint - prev_crosspoint), end - begin, scale_tgt * rate, adjust)

						begin = begin + (adjust * 1.2)
						end = end + (adjust * 1.2)

						out = scale(buf, begin, end, scale_tgt)
						
						angle2 = burst_detect(out[1820:len(out)])[1]
						adjust2 = wrap_angle(angle2, -tgt_phase) 
						
						end = end + (adjust2 * 1.0)
						
						out = scale(buf, begin, end, scale_tgt)

						ladjust = ((((end - begin) / scale_tgt) - 1) * 1.01) + 1
	
						out = ((out / 57344.0) * 1700000) + 7600000 
						out = out * ladjust 
						out = (out - 7600000) / 1700000.0
	
						output_16 = np.empty(len(out), dtype=np.uint16)
						np.copyto(output_16, np.clip(out * 57344.0, 0, 65535), 'unsafe')
						
						outl = getline(line)
						if (outl >= 0):	
							#frame[outl] = output_16[130:130+1685+ntsc_hsynctoline]
							frame[outl] = output_16[130:130+1685]
#						print line, begin, outl, burst_detect(out), angle, burst_detect(out)[1], adjust
	
#						sys.stdout.write(output_16)
					
						line = line + 1
					else: 
						if ((line == -1) and (linelen < 1000) and (count > 80) and (count < 160)):
							line = 266.5
						elif ((line == -1) or (line > 520)) and (linelen > 1800) and (count < 80):
							if (line > 0):
								frame.tofile(sys.stdout)
#								sys.stdout.write(frame)
							line = 1
							tgt_phase = 0
						elif (line == -2) and (linelen > 1800) and (count > 80):
							line = -1
						elif line >= 0 and (linelen > 800) and (linelen < 1000):
							line = line + 0.5
						elif line >= 0 and (linelen > 1700):
							line = line + 1
						printerr(line, prev_crosspoint, crosspoint, count) 

						# hack
						if (np.floor(line) == 272):
							tgt_phase = -tgt_phase
	
				prev_crosspoint = crosspoint
			
			count = 0
	return np.floor(prev_crosspoint) - 100 
	
outfile = open("test.rgb", "wb")
infile = sys.stdin

#indata = []

toread = blocklen * 2 
inbuf = infile.buffer.read(131072)
indata = np.fromstring(inbuf, 'uint16', 65536)
#print toread

while len(inbuf) > 0:
	toread = (blocklen - len(indata)) * 2 
	while toread > 0:
		inbuf = infile.buffer.read(65536)
		indata = np.append(indata, np.fromstring(inbuf, 'uint16', 32768))
		toread = (blocklen - len(indata)) 

	keep = find_sync(indata) * 1

	indata = indata[keep:len(indata)]

