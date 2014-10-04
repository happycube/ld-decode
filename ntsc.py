from __future__ import print_function
import numpy as np
import scipy as sp
import scipy.signal as sps
import sys

from scipy.interpolate import interp1d

freq = 8.0

freq_mhz = (315.0 / 88.0) * freq
freq_hz = freq * 1000000.0
blocklen = 65536 * 8 

# inframe is a 1685x505 uint16 buffer.  basically an ntsc frame with syncs removed

color_filter = sps.firwin(33, 0.3 / (freq), window='hamming')
sync_filter = sps.firwin(33, 0.1 / (freq), window='hamming')

frame = np.empty([505, 844], dtype=np.uint16)

# set up sync color heterodyne table first 
bhet = np.empty(4096, dtype=np.complex)
for i in range(0, 4096):
	bhet[i] = complex(np.cos(((i / freq) * 2.0 * np.pi) + (33.0/180.0)), -(np.sin(((i / freq) * 2.0 * np.pi) + (33.0/180.0))))
	bhet[i] = complex(np.cos(((i / freq) * 2.0 * np.pi) + (0.0/180.0)), -(np.sin(((i / freq) * 2.0 * np.pi) + (0.0/180.0))))

def printerr(*objs):
	print(*objs, file=sys.stderr)
	return

def burst_detect(line, loc = 0):
	level = 0
	phase = 0

	obhet = np.empty(100, dtype=np.complex)

	obhet = bhet[loc+140:loc+240] * line[loc+140:loc+240]

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
ntsc_linelength = 227.5 * freq
# this is the hblank interval except for front porch
ntsc_blanklen = 9.2
ntsc_hsynctoline = (ntsc_linelength * ntsc_blanklen / 63.5) 

scale_linelen = ((63.5 + ntsc_blanklen) / 63.5)	# add to non-TBC line length to get second hblank
scale_tgt = ntsc_linelength + ntsc_hsynctoline

# This uses numpy's interpolator, which provides very good results
def scale(buf, begin, end, tgtlen):
	ibegin = np.floor(begin)
	iend = np.floor(end)

	linelen = end - begin

	dist = iend - ibegin + 1 
	arr = np.linspace(0, dist, num=dist)
	spl = interpolate.splrep(arr, buf[ibegin:ibegin + dist])
	arrout = np.linspace(begin - ibegin, linelen, tgtlen)
						
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

	filtered = sps.fftconvolve(buf, sync_filter)[len(sync_filter) / 2:]

	cross = 5000
	prev_crosspoint = -1

	for i in range(0, len(buf) - 4096):
		if (filtered[i] < cross):
			if (count == 0):
				d = filtered[i - 1] - filtered[i]
				c = (filtered[i - 1] - cross) / d

				crosspoint = i + c
				
			count = count + 1
		else:
			if (count > 30):
				d = filtered[i] - filtered[i - 1]
				c = (filtered[i] - cross) / d

				l = buf[i:i + 1820]

				if (prev_crosspoint > 0):
					begin = prev_crosspoint
					end = begin + ((crosspoint - prev_crosspoint) * scale_linelen) 
					linelen = np.floor(crosspoint - prev_crosspoint)

					if (end > len(buf)):
						return np.floor(prev_crosspoint) - 100 

					# process a standard line
					if (line >= 0) and (linelen > 1800) and (count > 90):
						outl = getline(line)

						printerr(line, outl, crosspoint - prev_crosspoint, ((end - begin) / scale_tgt) * 1820.0) 

						out = scale(buf, begin, end, scale_tgt)
						angle = burst_detect(out, 0)[1]
						angle2 = burst_detect(out, 1820)[1]

						if tgt_phase:
							tgt_phase = -tgt_phase
						elif angle < 0 and (angle > -(3 * np.pi / 4)):
							tgt_phase = -np.pi / 2
							_tgt_phase = np.pi
						else:
							tgt_phase = np.pi / 2
							_tgt_phase = 0

						adjust = wrap_angle(angle, _tgt_phase) 
						begin = begin + (adjust * 1.3)
						
						printerr(angle, angle2, begin, end, ((end - begin) / scale_tgt) * 1820.0)

						out = scale(buf, begin, end, scale_tgt)
						
						angle = burst_detect(out, 0)[1]
						angle2 = burst_detect(out, 1820)[1]
						adjust2 = wrap_angle(angle2, _tgt_phase) 
						end = end + (adjust2 * 1.2)
						
						printerr(angle, angle2, begin, end, ((end - begin) / scale_tgt) * 1820.0)
						
						out = scale(buf, begin, end, scale_tgt / 2)

						ladjust = ((((end - begin) / scale_tgt) - 1) * 0.84) + 1
	
						out = ((out / 57344.0) * 1700000) + 7600000 
						out = out * ladjust 
						out = (out - 7600000) / 1700000.0
						
						# qa code only - determine final phases	
#						angle = burst_detect(out)[1]
#						angle2 = burst_detect(out, 1820)[1]
#						printerr(angle, angle2)
	
						outl = getline(line)
						if (outl >= 0):	
							np.copyto(frame[outl], np.clip(out[65:65+844] * 57344.0, 0, 65535), 'unsafe')
	
						line = line + 1
					else: 
						if ((line == -1) and (linelen < 1000) and (count > 80) and (count < 160)):
							line = 266.5
						elif ((line == -1) or (line > 520)) and (linelen > 1800) and (count < 80):
							if (line > 0):
								frame.tofile(sys.stdout)
							line = 1
							tgt_phase = 0
						elif (line == -2) and (linelen > 1800) and (count > 80):
							line = -1
						elif line >= 0 and (linelen > 800) and (linelen < 1000):
							line = line + 0.5
						elif line >= 0 and (linelen > 1700):
							line = line + 1
						printerr(line, prev_crosspoint, crosspoint, count) 

						# hack for phase inversion on second field
						if (np.floor(line) == 272):
							tgt_phase = -tgt_phase
	
				prev_crosspoint = crosspoint
			
			count = 0
	return np.floor(prev_crosspoint) - 100 
	
outfile = open("test.rgb", "wb")
infile = sys.stdin

toread = blocklen * 2 
inbuf = infile.buffer.read(131072)
indata = np.fromstring(inbuf, 'uint16', 65536)

while len(inbuf) > 0:
	toread = (blocklen - len(indata)) * 2 
	while toread > 0:
		inbuf = infile.buffer.read(65536)
		indata = np.append(indata, np.fromstring(inbuf, 'uint16', 32768))
		toread = (blocklen - len(indata)) 

	keep = find_sync(indata) * 1

	indata = indata[keep:len(indata)]
