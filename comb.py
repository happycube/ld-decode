import numpy as np
import scipy as sp
import scipy.signal as sps
import sys

freq = 4.0

freq_mhz = (315.0 / 88.0) * freq
freq_hz = freq * 1000000.0
blocklen = (852*505) 

# inframe is a 852x505 uint16 buffer.  basically an ntsc frame with syncs removed

prevframe = np.empty([505, 852], dtype=np.uint16)
prevrgb = np.empty([480, 744 * 3], dtype=np.uint8)

burst_len = 28 * 4

color_filter = sps.firwin(17, 0.6 / (freq / 2), window='hamming')
sync_filter = sps.firwin(17, 0.1 / (freq / 2), window='hamming')

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

# return 744x480 rgb frame
def comb(inframe):
	rgb = np.zeros([480, 744 * 3], dtype=np.uint8)
	prevframe = inframe
		
	yiq = np.empty([480, 780, 4], dtype=np.double)
	fi = np.empty([480, 780], dtype=np.double)
	fq = np.empty([480, 780], dtype=np.double)

	i = 0
	q = 0

	for l in range(23, 503):
		linephase = inframe[l][0]

		for x in range(72, 850):
			prev = np.double(inframe[l][x - 2])
			cur = np.double(inframe[l][x])
			nex = np.double(inframe[l][x + 2])

			phase = x % 4

			c = (cur - ((prev + nex) / 2)) / 2

			if (linephase == 16384):
				c = -c

			if (phase == 0):
				q = c	
			elif (phase == 1):
				i = -c	
			elif (phase == 2):
				q = -c	
			elif (phase == 3):
				i = c	
	
			y = (cur - ((cur - prev) / 2))

#			print x, x % 4, cur, c, prev, nex, y, i, q, cur + c

			yiq[l - 23][x - 72] = [cur, y, i, q]
			fi[l - 23][x - 72] = i 
			fq[l - 23][x - 72] = q 
		
#	for l in range(23, 503):
	for l in range(23, 503):
		fi[l-23] = np.roll(sps.lfilter(color_filter, [1.0], fi[l - 23]), -9)
		fq[l-23] = np.roll(sps.lfilter(color_filter, [1.0], fq[l - 23]), -9)
	
	for l in range(23, 503):
		linephase = inframe[l][0]

		for x in range(72, 744+72):
			[cur, y, i, q] = yiq[l - 23][x - 72]
	
			if (l > 27) and (l <= 500):
				otheri = (fi[l-25][x - 72] + fi[l-21][x - 72]) / 2.0
				otherq = (fq[l-25][x - 72] + fq[l-21][x - 72]) / 2.0
			else:
				otheri = i
				otherq = q

			i = (fi[l-23][x - 72] + otheri) / 2.0
			q = (fq[l-23][x - 72] + otherq) / 2.0
	
			phase = x % 4
			if (phase == 0):
				comp = q	
			elif (phase == 1):
				comp = -i
			elif (phase == 2):
				comp = -q
			elif (phase == 3):
				comp = i
			
			if (linephase == 16384):
				comp = -comp

			_y = y
			y = cur - comp

#			print x, phase, cur, i, q, y, _y

			[r, g, b] = torgb(y, i, q)
			rgb[l - 23][((x - 72) * 3) + 0] = r 
			rgb[l - 23][((x - 72) * 3) + 1] = g 
			rgb[l - 23][((x - 72) * 3) + 2] = b 

	return rgb

def isWhiteFlag(line):
	wc = 0
	for i in range(0, 852):
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
#	if (isWhiteFlag(inframe[2])):
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
	inframe = np.reshape(indata, (505, 852))	
	rgbout = process(inframe)

#	indata = np.delete(indata, np.s_[0:len(output)])
	indata = np.array([])

	exit()
