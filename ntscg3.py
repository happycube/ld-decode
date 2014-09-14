from __future__ import print_function
import numpy as np
import scipy as sp
import scipy.signal as sps
import sys

from scipy.interpolate import interp1d

freq = 8.0

freq_mhz = (315.0 / 88.0) * freq
freq_hz = freq * 1000000.0

# store enough to hold two entire frames
blocklen = 1820*600*2

color_filter = sps.firwin(33, 0.3 / (freq), window='hamming')
sync_filter = sps.firwin(33, 0.1 / (freq), window='hamming')
sync_filter4 = sps.firwin(17, 0.5 / (freq), window='hamming')

# output format: 844x505, 16-bit grayscale
# (with a couple of metadata pieces in the first column)
frame = np.empty([505, 844], dtype=np.uint16)

# set up sync color heterodyne table first 
bhet = np.empty(4096, dtype=np.complex)
for i in range(0, 4096):
	bhet[i] = complex(np.cos(((i / freq) * 2.0 * np.pi) + (0.0/180.0)), -(np.sin(((i / freq) * 2.0 * np.pi) + (0.0/180.0))))

bhet4 = np.empty(4096, dtype=np.complex)
for i in range(0, 4096):
	bhet4[i] = complex(np.cos(((i / 4) * 2.0 * np.pi) + (0.0/180.0)), -(np.sin(((i / 4) * 2.0 * np.pi) + (0.0/180.0))))

def printerr(*objs):
	print(*objs, file=sys.stderr)
	return

def burst_detect(line, loc = 0):
	level = 0
	phase = 0

	for i in range(140, 240):
		if line[i] > 30000 or line[i] < 5000:
			line[i] = 16500

	obhet = np.empty(100, dtype=np.complex)

	obhet = bhet4[loc+140:loc+240] * line[loc+140:loc+240]

	obhet_filt = sps.lfilter(sync_filter, [1.0], obhet)
	obhet_levels = np.absolute(obhet_filt)
	obhet_angles = np.angle(obhet_filt)

	for i in range(0, 100):
		if (obhet_levels[i] > level) and (obhet_levels[i] < 10000):
			level = obhet_levels[i]
			phase = obhet_angles[i]

	return [level, phase]

def burst_detect4(line, loc = 0):
	level = 0
	phase = 0

	for i in range(70, 140):
		if line[i] > 30000 or line[i] < 5000:
			line[i] = 16500

	obhet = np.empty(60, dtype=np.complex)

	obhet = bhet4[loc+70:loc+130] * line[loc+70:loc+130]

	obhet_filt = sps.lfilter(sync_filter4, [1.0], obhet)
	obhet_levels = np.absolute(obhet_filt)
	obhet_angles = np.angle(obhet_filt)

	for i in range(0, 60):
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
tgt_phase = -100

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
						else:
							tgt_phase = np.pi / 2
	
						adjust = wrap_angle(angle, tgt_phase) 
						begin = begin + (adjust * 1.3)
						
						printerr(angle, angle2, begin, end, ((end - begin) / scale_tgt) * 1820.0)

						out = scale(buf, begin, end, scale_tgt)
						
						angle = burst_detect(out, 0)[1]
						angle2 = burst_detect(out, 1820)[1]
						adjust2 = wrap_angle(angle2, tgt_phase) 
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

def find_syncs(buf):
	filtered = sps.fftconvolve(buf, sync_filter)[len(sync_filter) / 2:]
	
	blist = []

	prev = [-1, 0]
	cur = [-1, 0]
	cross = 5000
	count = 0	

	for i in range(0, len(filtered)):
#	for i in range(0, 5000):
#		printerr(i, filtered[i])
		if (filtered[i] < cross):
			if (count == 0):
				d = filtered[i - 1] - filtered[i]
				c = (filtered[i - 1] - cross) / d

				begin = i + c

			count = count + 1
		elif (count > 0):
			d = filtered[i] - filtered[i - 1]
			c = (filtered[i] - cross) / d

			end = i + c

			if (cur[0] >= 0) and ((begin - (cur[0] + cur[1])) < 16): 
				cur[1] = end - cur[0]
#				printerr("merge ",begin, begin - cur[0], cur[0], cur[1])
			else:
				if (cur[0] > 0): 
#					printerr("o ", cur[0] - prev[0], cur[0], cur[1], cur[0] + cur[1])
					blist.append(cur)
				prev = cur
				cur = [begin, end - begin]

			count = 0

#	for i in range(1, len(blist)):
#		printerr(blist[i][0], blist[i][0] - blist[i - 1][0], blist[i][1])

	return blist

def filter_synclist(blist, min):
	slist = []
	l = 0

	for i in range(len(blist)):
		if (blist[i][1] > min):
			slist.append(blist[i])
			if (l > 0):
				printerr("f ",slist[l][0], slist[l][0] - slist[l - 1][0], slist[l][1])
			l = l + 1	

	return slist

def filter_synclist_field(blist, min):
	slist = []
	l = 0

	for i in range(0, 20):
		if (blist[i][1] > min):
			slist.append(blist[i])

	for i in range(20, 260):
		begin = blist[i][0] - blist[i - 1][0]
		end = begin + (blist[i][1] + 1)
		if (blist[i][1] > min) and ((begin > 1800) or (end > 1840)):
			slist.append(blist[i])
	
	for i in range(260, len(blist)):
		if (blist[i][1] > min):
			slist.append(blist[i])

	return slist

frame_phase = -1 

def adjust_line(lnum, buf, begin, end):
	phasemult = 1.591549430918953e-01 * 8
	end = begin + ((end - begin) * scale_linelen) 

	out = scale(buf, begin, end, scale_tgt / 2)
	[level, angle] = burst_detect4(out, 0)
	[level2, angle2] = burst_detect4(out, 910)

	printerr("0 ", level, angle, level2, angle2, begin)

	# todo:  make a comparison vs observed
	if (level < 500):
		return out
	
	global frame_phase

	if frame_phase < 0:
		frame_phase = (np.abs(angle) > (np.pi / 2)) ^ (lnum % 2)

	if (frame_phase ^ (lnum % 2)):
		tgt_phase = 0
	else:
		tgt_phase = np.pi 
	
	adjust = wrap_angle(angle, tgt_phase) 
	begin = begin + (adjust * phasemult)
						
	printerr("1 ", level, angle, angle2, adjust, begin, end, ((end - begin) / scale_tgt) * 1820.0)

	out = scale(buf, begin, end, scale_tgt / 2)
					
	[level, angle] = burst_detect4(out, 0)
	[level2, angle2] = burst_detect4(out, 910)
	
	if (level2 < 500):
		if (tgt_phase == 0):
			out[66] = 32768
		else:
			out[66] = 16384
		return out

	adjust2 = wrap_angle(angle2, tgt_phase) 
	end = end + (adjust2 * phasemult)
						
	printerr("2 ", level, angle, angle2, begin, end, ((end - begin) / scale_tgt) * 1820.0)
					
	out = scale(buf, begin, end, scale_tgt / 2)
	
	[level, angle] = burst_detect4(out, 0)
	[level2, angle2] = burst_detect4(out, 910)
	
	printerr("3 ", level, angle, angle2, begin, end, ((end - begin) / scale_tgt) * 1820.0)
	
	ladjust = ((((end - begin) / scale_tgt) - 1) * 0.84) + 1

	out = (out * 1700000) + 7600000 
	out = out * ladjust 
	out = ((out - 7600000) / 1700000.0) 
		
	if (tgt_phase == 0):
		out[66] = 32768
	else:
		out[66] = 16384

	return out

def handle_field(buf, blist, start, field):
	global frame_phase

	curline = 0
	i = start 
	halfcount = 0

	printerr(i, field)

	linelen = blist[i + 1][0] - blist[i][0]
	while linelen > 850 and linelen < 960:
		i = i + 1
		linelen = blist[i + 1][0] - blist[i][0]
		printerr(i, linelen)

	i = i - 1

	if field == 0:
		curline = 10 
#		if frame_phase >= 0:
#			frame_phase = frame_phase ^ 1 
	elif field == 1:
		curline = 272 

	for l in range(0, 254):
		linelen = blist[i + l][1] 
		if (linelen < 116) or (linelen > 140):
			eb = blist[i + l]	
			blist[i + l][0] = (blist[i + l - 1][0] + blist[i + l + 1][0]) / 2
			printerr("override ", eb, blist[i + l - 1], blist[i + l + 1], blist[i + l])

		begin = blist[i + l][0]
		end = blist[i + l + 1][0]
	
		if ((end - begin) > (1780 * 2)) and ((end - begin) < (1860 * 2)):
			printerr("override2 ", eb, blist[i + l - 1], blist[i + l + 1], blist[i + l])
			extlist = [begin + ((end - begin) / 2), 120] 
			blist.insert(i + l + 1, extlist)
		
			end = blist[i + l + 1][0]
	
		outl = getline(curline + l)
		printerr(curline + l, begin, end, end - begin, getline(curline + l), blist[i + l])

		if outl >= 0:
			outs = scale(buf, begin, end, 910)
			out = adjust_line(curline + l, buf, begin, end)
			np.copyto(frame[outl], np.clip(out[66:66+844] , 0, 65535), 'unsafe')

	printerr(i, blist[i + 1][0] - blist[i][0])

	return

# todo:  currently 8fsc dependant timing

valid = 0
framecount = 0

def find_frame(buf):
	global valid, framecount

	handled = 0
	blist = find_syncs(buf)

	# todo - run this after determining frequency
	slist = filter_synclist(blist, 47)

	# search for instances of (ideally) six serrated burst pulses in a row. 
	serlist = filter_synclist(blist, 340)

	while len(serlist) > 6:
		# check location of first sync
		firstent = slist.index(serlist[0])
		if ((serlist[5][0] - serlist[0][0]) > (910 * 7)) or (firstent < 9):
			printerr("First entry off target or corrupt", firstent)

			start = firstent - 9
			if (start < 0):
				start = 0

			for i in range(start, firstent + 5):
				printerr(i, serlist[i][0], serlist[i][1])

			serlist.pop(0)
		elif ((len(buf) - serlist[0][0]) < (1820 * 540)):
			printerr("First entry too late, drop ", serlist[0][0] - 16384)
			return serlist[0][0] - 16384
		else:
			fieldlist = filter_synclist_field(slist[-7 + firstent:], 45)

			if (fieldlist[1][0] - fieldlist[0][0]) > 1700: 
				field = 0
				valid = 1
			elif (fieldlist[1][0] - fieldlist[0][0]) < 1000: 
				field = 1

			printerr(field)
			handle_field(buf, fieldlist, 1, field)

			if (field == 1) and (valid == 1):
				frame.tofile(sys.stdout)
				framecount = framecount + 1
				if framecount == 3:
					exit()

			read = fieldlist[0][0] + (1820 * 200)

			for i in range(0, 6):
				serlist.pop(0)	

	exit()
	return read 

outfile = open("test.rgb", "wb")
infile = sys.stdin

toread = blocklen 
inbuf = infile.buffer.read(blocklen * 2)
indata = np.fromstring(inbuf, 'uint16', blocklen)

while len(inbuf) > 0:
	toread = (blocklen - len(indata)) * 2 
	while toread > 0:
		inbuf = infile.buffer.read(toread)
		printerr("read", toread, len(inbuf))
		if (len(inbuf) == 0):
			exit()
		indata = np.append(indata, np.fromstring(inbuf, 'uint16', int(len(inbuf) / 2)))
		toread = (blocklen - len(indata)) 

	keep = find_frame(indata)
#	exit()
#	keep = find_sync(indata) * 1

	indata = indata[keep:len(indata)]
