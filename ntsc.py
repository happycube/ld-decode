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
bhet = np.empty(8, dtype=np.complex)
for i in range(0, 8):
	bhet[i] = complex(np.cos(((i / freq) * 2.0 * np.pi) + (33.0/180.0)), -(np.sin(((i / freq) * 2.0 * np.pi) + (33.0/180.0))))
	bhet[i] = complex(np.cos(((i / freq) * 2.0 * np.pi) + (0.0/180.0)), -(np.sin(((i / freq) * 2.0 * np.pi) + (0.0/180.0))))

burst_len = 300

def printerr(*objs):
    print(*objs, file=sys.stderr)

def burst_detect(line):
	level = 0
	phase = 0

	obhet = np.empty(burst_len, dtype=np.complex)
	obhet = np.empty(1820, dtype=np.complex)
	#for i in range(0, burst_len):

	for i in range(8, 240):
		obhet[i] = bhet[i % 8] * line[i]

#	obhet_filt = sps.fftconvolve(obhet, color_filter)
	obhet_filt = sps.lfilter(sync_filter, [1.0], obhet)
	obhet_levels = np.absolute(obhet_filt)
	obhet_angles = np.angle(obhet_filt)

	#for i in range(65, burst_len):
	for i in range(130, 240):
#		print i, line[i]
#		if (level == 0):
#		print i, line[i], level, obhet_plevels[i], obhet_levels[i]
		if (obhet_levels[i] > level) and (obhet_levels[i] < 10000):
			level = obhet_levels[i]
			phase = obhet_angles[i]

	return [level, phase]

def clamp(v, min, max):
	if v < min:
		return min

	if v > max:
		return max

	return v

def torgb(y, i, q):
	# rebase y@0 to 0ire from -40
	y = (y - 16384) * 1.40
	i = i * 1.4
	q = q * 1.4

	r = (y * 1.164) + (1.596 * i);
	g = (y * 1.164) - (0.813 * i) - (q * 0.391);
	b = (y * 1.164) + (q * 2.018);

	r = np.clip(r / 256, 0, 255)	
	g = np.clip(g / 256, 0, 255)	
	b = np.clip(b / 256, 0, 255)	

	return [r, g, b]

# return 1488x480 rgb frame
def comb(inframe):
	rgb = np.zeros([480, 1488 * 3], dtype=np.uint8)
	prevframe = inframe
		
	lhet = np.empty([525, 8], dtype=np.complex)
	adji = np.empty([525, 1685 + 32], dtype=np.double)
	adjq = np.empty([525, 1685 + 32], dtype=np.double)
	lohet = np.empty([525, 1685], dtype=np.complex)
	lohet_filt = np.empty([525, 1685 + 32], dtype=np.complex)
	#for l in range(24, 504):
	for l in range(24, 504):
#		print l
		[level, phase] = burst_detect(inframe[l])
#		print level, phase

		for i in range(0, 8):
			lhet[l][i] = complex(np.cos(phase + ((i / freq) * 2.0 * np.pi)), np.sin(phase + ((i / freq) * 2.0 * np.pi)))

		for i in range(0, 1685):
			lohet[l][i] = lhet[l][i % 8] * inframe[l][i]

		for i in range(155, 155 + 1488):
			adji[l][i] = 2 * lhet[l][(i - 5) % 8].imag 
			adjq[l][i] = 2 * lhet[l][(i - 5) % 8].real
#			print lohet[i].real, lohet[i].imag

		lohet_filt[l] = sps.fftconvolve(lohet[l], color_filter)
#		lohet_filt = np.delete(lohet_filt, np.s_[0:len(output)])
#		for i in range(0, 1685):
#			print inframe[l][i - 17], lohet_filt[i].real, lohet_filt[i].imag
		
	cmult = 3.5	
	inframe_fcomp = np.empty([1717], dtype=np.uint16)

	row = np.empty([1685 + 32], dtype=np.complex)

	for l in range(24, 504):

		# compute 2D and adjustment arrays
		rowa = (0.5 * lohet_filt[l]) + (0.25 * lohet_filt[l - 2]) + (0.25 * lohet_filt[l + 2]) 
		rowp = (0.5 * lohet_filt[l]) + (0.5 * lohet_filt[l - 2]) 
		rown = (0.5 * lohet_filt[l]) + (0.5 * lohet_filt[l + 2]) 

		a = np.absolute(lohet_filt[l])
		diffp = np.fabs((np.absolute(lohet_filt[l] - lohet_filt[l - 2]) / a))
		diffn = np.fabs((np.absolute(lohet_filt[l] - lohet_filt[l + 2]) / a))

		dgreep = np.fabs(diffp - 2)
		dgreen = np.fabs(diffn - 2)
		
		agreep = np.fabs(diffp - 1)
		agreen = np.fabs(diffn - 1)

		for i in range(155, 155 + 1488):
#			if (l == 60) or (l == 61):
#				print i, lohet_filt[l][i], a[i], agreep[i], agreen[i] 

			if (a[i] < 400):
				row[i] = lohet_filt[l][i] 
			elif ((dgreep[i] < dgreen[i]) and (dgreep[i] < 0.2)):
				row[i] = rowp[i]
			elif (dgreen[i] < 0.2):
				row[i] = rown[i]
#			elif ((agreep[i] < agreen[i]) and (agreep[i] < 0.2)):
#				row[i] = rowp[i]
#			elif (agreen[i] < 0.2):
#				row[i] = rown[i]
			else:
				row[i] = rowa[i] 
			inframe_fcomp[i] = inframe[l][i - 17]
		
		vadji = row.imag * adji[l]
		vadjq = row.real * adjq[l]

		[r, g, b] = torgb(inframe_fcomp + vadji + vadjq, cmult * row.imag, -cmult * row.real)
	
		for i in range(155, 155 + 1488):
			rgb[l - 25][((i - 155) * 3) + 0] = r[i] 
			rgb[l - 25][((i - 155) * 3) + 1] = g[i] 
			rgb[l - 25][((i - 155) * 3) + 2] = b[i] 

#			print r, g, b
	
	return rgb

def isWhiteFlag(line):
	wc = 0
	for i in range(0, 1400):
		if line[i] > 45000:
			wc = wc + 1

#	print wc
	return (wc > 1000)

pf_useodd = 0

def process(inframe):
	global pf_useodd
	global prevrgb 

	rgb = comb(inframe)

	# if the previous odd field is the start of the current frame, combine and write	
	if pf_useodd:
#		print "odd start"
		for i in range(0, 480):
			if (i % 2):
				outfile.write(prevrgb[i])
			else: 
				outfile.write(rgb[i])

	# determine if this is a whole (even+odd) or half (odd) frame using white flag detection for now
#	if (isWhiteFlag(inframe[2])):
	for i in range(0, 480):
		outfile.write(rgb[i])

	if (isWhiteFlag(inframe[3])):
			pf_useodd = True
	
	prevrgb = rgb

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

	if (l < 262):
		return (l - 10) * 2
	
	if (l < 271):
		return -1
	
	if (l > 524):
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
						
	return np.clip(interpolate.splev(arrout, spl), 0, 65535)

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
	numsyncs = 0
	global line, tgt_phase

#	print buf
	filtered = sps.fftconvolve(buf, sync_filter)[len(sync_filter) / 2:]

	cross = 5000
	prev_crosspoint = -1

	for i in range(0, len(filtered) - 4096):
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
				numsyncs = numsyncs + 1

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
						print(line, outl, file=sys.stderr) 

						out = scale(buf, begin, end, scale_tgt)

						angle = burst_detect(out)[1]
						angle2 = burst_detect(out[1820:len(out)])[1]

						if tgt_phase:
							tgt_phase = -tgt_phase
						elif angle < 0 and (angle > -(3 * np.pi / 4)):
							tgt_phase = -np.pi / 2
						else:
							tgt_phase = np.pi / 2
	
						adjust = wrap_angle(angle, tgt_phase) 
						
#						print outl, angle, angle2, adjust
						rate = (crosspoint - prev_crosspoint) / 1820.0
						printerr(outl, angle, angle2, (crosspoint - prev_crosspoint), end - begin, scale_tgt * rate, adjust)

						begin = begin + (adjust * 1.2)
						end = end + (adjust * 1.2)

						#out = scale(buf, prev_crosspoint, crosspoint, linelen)
#						printe(prev_crosspoint, prev_crosspoint + (linelen * scale_linelen), scale_tgt
						out = scale(buf, begin, end, scale_tgt)
						
						angle = burst_detect(out)[1]
						angle2 = burst_detect(out[1820:len(out)])[1]
						
						adjust2 = wrap_angle(angle2, -tgt_phase) 
						printerr(outl, angle, angle2, adjust2)
						
						end = end + (adjust2 * 1.0)
						
						out = scale(buf, begin, end, scale_tgt)
						angle = burst_detect(out)[1]
						angle2 = burst_detect(out[linelen:len(out)])[1]
						printerr(outl, angle, angle2, end - begin)
						
						output_16 = np.empty(len(out), dtype=np.uint16)
						np.copyto(output_16, out, 'unsafe')
						
						angle = burst_detect(out)[1]
						angle2 = burst_detect(out[1820:len(out)])[1]
#						print outl, angle, angle2

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
								sys.stdout.write(frame)
							line = 1
							tgt_phase = 0
						elif (line == -2) and (linelen > 1800) and (count > 80):
							line = -1
						elif line >= 0 and (linelen > 800) and (linelen < 1000):
							line = line + 0.5
						elif line >= 0 and (linelen > 1700):
							line = line + 1
						print(line, prev_crosspoint, crosspoint, count, file=sys.stderr) 

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
inbuf = infile.read(toread)
indata = np.fromstring(inbuf, 'uint16', toread / 2)
#print toread

while len(inbuf) > 0:
	toread = (blocklen - len(indata)) * 2 
	while toread > 0:
		inbuf = infile.read(toread)
		indata = np.append(indata, np.fromstring(inbuf, 'uint16', toread / 2))
		toread = (blocklen - len(indata)) 

#		print len(indata), toread
#		print len(inbuf), toread

#	print toread
	keep = find_sync(indata) * 1

#	print len(indata)
#	inframe = np.reshape(indata, (505, 1685))	
#	rgbout = process(inframe)

#	indata = np.delete(indata, np.s_[0:len(output)])
	indata = indata[keep:len(indata)]

#	exit()
