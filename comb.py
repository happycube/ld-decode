import numpy as np
import scipy as sp
import scipy.signal as sps
import sys

freq = 8.0

freq_mhz = (315.0 / 88.0) * freq
freq_hz = freq * 1000000.0
blocklen = (1685*505) 

# inframe is a 1685x505 uint16 buffer.  basically an ntsc frame with syncs removed

prevframe = np.empty([505, 1685], dtype=np.uint16)
prevrgb = np.empty([480, 1488 * 3], dtype=np.uint8)

burst_len = 28 * 4

color_filter = sps.firwin(33, 0.6 / (freq / 2), window='hamming')
sync_filter = sps.firwin(65, 0.6 / (freq / 2), window='hamming')

# set up sync color heterodyne table first 
bhet = np.empty(8, dtype=np.complex)
for i in range(0, 8):
	bhet[i] = complex(np.sin((i / freq) * 2.0 * np.pi), -(np.cos((i / freq) * 2.0 * np.pi)))

def burst_detect(line):
	level = 0
	phase = 0

	obhet = np.empty(burst_len, dtype=np.complex)
	for i in range(0, burst_len):
		obhet[i] = bhet[i % 8] * line[i]

	obhet_filt = sps.fftconvolve(obhet, sync_filter)
	obhet_levels = np.absolute(obhet_filt)
	obhet_angles = np.angle(obhet_filt)

	for i in range(65, burst_len):
		if obhet_levels[i] > level:
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
	y = y - 16384

	r = (y * 1.164) + (1.596 * i);
	g = (y * 1.164) - (0.813 * i) - (q * 0.391);
	b = (y * 1.164) + (q * 2.018);

	r = clamp(r / 256, 0, 255)	
	g = clamp(g / 256, 0, 255)	
	b = clamp(b / 256, 0, 255)	

	return [r, g, b]

# return 1488x480 rgb frame
def comb(inframe):
	rgb = np.empty([480, 1488 * 3], dtype=np.uint8)
	prevframe = inframe
		
	lohet = np.empty(1685, dtype=np.complex)

	for l in range(25, 505):
		print l
		[level, phase] = burst_detect(inframe[l])
#		print level, phase

		lhet = np.empty(8, dtype=np.complex)
		for i in range(0, 8):
			lhet[i] = complex(np.sin(phase + ((i / freq) * 2.0 * np.pi)), -(phase + np.cos((i / freq) * 2.0 * np.pi)))

		for i in range(0, 1685):
			lohet[i] = lhet[i % 8] * inframe[l][i]

		lohet_filt = sps.fftconvolve(lohet, color_filter)
		
		cmult = 3.0	

		for i in range(113, 1600):
			iadj = lohet_filt[i].imag * 2 * lhet[(i + 1) % 8].imag
			qadj = lohet_filt[i].real * 2 * lhet[(i + 1) % 8].real

			[r, g, b] = torgb(inframe[l][i], cmult * lohet_filt[i].imag, cmult * lohet_filt[i].real)
			rgb[l - 25][((i - 113) * 3) + 0] = r 
			rgb[l - 25][((i - 113) * 3) + 1] = g 
			rgb[l - 25][((i - 113) * 3) + 2] = b 
	
	return rgb

def isWhiteFlag(line):
	wc = 0
	for i in range(0, 1400):
		if line[i] > 45000:
			wc = wc + 1

	print wc
	return (wc > 1000)

pf_useodd = 0

def process(inframe):
	global pf_useodd
	global prevrgb 

	rgb = comb(inframe)

	# if the previous odd field is the start of the current frame, combine and write	
	if pf_useodd:
		print "odd start"
		for i in range(0, 480):
			if (i % 2):
				outfile.write(prevrgb[i])
			else: 
				outfile.write(rgb[i])

	# determine if this is a whole (even+odd) or half (odd) frame using white flag detection for now
	if (isWhiteFlag(inframe[2])):
		for i in range(0, 480):
			outfile.write(rgb[i])
	
	if (isWhiteFlag(inframe[3])):
		pf_useodd = True
	
	prevrgb = rgb
	
infile = open("test.tbc", "rb")
outfile = open("test.rgb", "wb")
#indata = []

toread = blocklen * 2 
inbuf = infile.read(toread)
indata = np.fromstring(inbuf, 'uint16', toread / 2)
print toread
	
while len(inbuf) > 0:
	toread = (blocklen - len(indata)) * 2 
	while toread > 0:
		inbuf = infile.read(toread)
		indata = np.append(indata, np.fromstring(inbuf, 'uint16', len(inbuf) / 2))
		toread = (blocklen - len(indata)) * 2 

		if len(inbuf) == 0:
			exit()

		print len(inbuf), toread

	print len(indata)
	inframe = np.reshape(indata, (505, 1685))	
	rgbout = process(inframe)

#	indata = np.delete(indata, np.s_[0:len(output)])
	indata = np.array([])


