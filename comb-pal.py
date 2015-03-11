import numpy as np
import scipy as sp
import scipy.signal as sps
import sys

import matplotlib.pyplot as plt

freq = 4.0

freq_mhz = 4.43361875 * freq
freq_hz = freq * 1000000.0
blocklen = (1135*625) 

# inframe is a 1135x505 uint16 buffer.  basically an ntsc frame with syncs removed

prevframe = np.empty([625, 1135], dtype=np.uint16)
prevrgb = np.empty([576, 1135 * 3], dtype=np.uint8)

burst_len = 28 * 4

color_filter = sps.firwin(33, 0.6 / (freq / 2), window='hamming')
sync_filter = sps.firwin(65, 0.6 / (freq / 2), window='hamming')

color_filter = [2.214464531115009e-03, 2.779566868356983e-03, 4.009052177841430e-03, 6.041802526864055e-03, 8.964977379775094e-03, 1.280250319629312e-02, 1.750822265693915e-02, 2.296445273166145e-02, 2.898626064895014e-02, 3.533129030361252e-02, 4.171449995422212e-02, 4.782674655050909e-02, 5.335581047849616e-02, 5.800822770944922e-02, 6.153020526791717e-02, 6.372594980605055e-02, 6.447193442389310e-02, 6.372594980605055e-02, 6.153020526791718e-02, 5.800822770944922e-02, 5.335581047849616e-02, 4.782674655050909e-02, 4.171449995422215e-02, 3.533129030361253e-02, 2.898626064895015e-02, 2.296445273166145e-02, 1.750822265693915e-02, 1.280250319629313e-02, 8.964977379775097e-03, 6.041802526864056e-03, 4.009052177841434e-03, 2.779566868356985e-03, 2.214464531115009e-03]

# set up sync color heterodyne table first 
bhet = np.empty(8, dtype=np.complex)
for i in range(0, 8):
	bhet[i] = complex(+np.sin(((i / freq) * 2.0 * np.pi) - (00.0/180.0)), -(np.cos(((i / freq) * 2.0 * np.pi) - (00.0/180.0))))

burst_len = 65

def burst_detect(line):
	level = 0
	phase = 0

	obhet = np.empty(burst_len, dtype=np.complex)
	for i in range(0, burst_len):
		obhet[i] = bhet[i % 8] * line[i + 90]

	obhet_filt = sps.fftconvolve(obhet, sync_filter)
	obhet_levels = np.absolute(obhet_filt)
	obhet_angles = np.angle(obhet_filt)
	
#	plt.plot(obhet_levels)
#	plt.plot(obhet_angles)
#	plt.show()

	for i in range(0, burst_len):
		if obhet_levels[i] > level:
			level = obhet_levels[i]
			phase = obhet_angles[i]

	phase = np.mean(obhet_angles[52:78])

	return [level, phase]

def clamp(v, min, max):
	if v < min:
		return min

	if v > max:
		return max

	return v

irescale = 312

def torgb(y, u, v):
	# rebase y@0 to 0ire from -40
	y = (y / irescale) - 100
	u = u / irescale
	v = v / irescale 

	r = (y * 1.862) - (0.005 * u) + (2.121 * v);
	g = (y * 1.862) - (0.731 * u) - (1.083 * v);
	b = (y * 1.862) + (3.788 * u) - (0.002 * v);

	r /= 1.6
	g /= 1.6
	b /= 1.6

	r = np.clip(r * 2.56, 0, 255)	
	g = np.clip(g * 2.56, 0, 255)	
	b = np.clip(b * 2.56, 0, 255)	

	return [r, g, b]

# return 1135x576 rgb frame
def comb(inframe):
	rgb = np.zeros([625, 1135 * 3], dtype=np.uint8)
	prevframe = inframe
		
	lhet = np.empty([625, 8], dtype=np.complex)
	adji = np.empty([625, 1135 + 32], dtype=np.double)
	adjq = np.empty([625, 1135 + 32], dtype=np.double)
	lohet = np.empty([625, 1135], dtype=np.complex)
	lohet_filt = np.empty([625, 1135 + 32], dtype=np.complex)

	for l in range(24, 620):
	#for l in range(100, 320):
#		plt.plot(inframe[l])
#		plt.show()
#		exit()
		[level, phase] = burst_detect(inframe[l])
		print l, level, phase

		for i in range(0, 8):
			lhet[l][i] = complex(np.cos(phase + ((i / freq) * 2.0 * np.pi)), np.sin(phase + ((i / freq) * 2.0 * np.pi)))

		for i in range(0, 1135):
			lohet[l][i] = lhet[l][i % 8] * inframe[l][i]

		for i in range(0, 0 + 1135):
			adji[l][i] = 2 * lhet[l][(i - 5) % 8].imag 
			adjq[l][i] = 2 * lhet[l][(i - 5) % 8].real
#			print lohet[i].real, lohet[i].imag

		lohet_filt[l] = sps.fftconvolve(lohet[l], color_filter)
#		lohet_filt = np.delete(lohet_filt, np.s_[0:len(output)])
#		for i in range(0, 1135):
#			print inframe[l][i - 17], lohet_filt[i].real, lohet_filt[i].imag
		
	cmult = 3.5	
	inframe_fcomp = np.empty([1135 + 32], dtype=np.uint16)

	row = np.empty([1135 + 32], dtype=np.complex)

	for l in range(24, 620):
#	for l in range(100, 320):
		print l

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

		for i in range(0, 0 + 1135):
			if (l == 60):
				print i, a[i], agreep[i], agreen[i] 

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
	
		for i in range(0, 0 + 1135):
			rgb[l - 25][((i - 155) * 3) + 0] = r[i] 
			rgb[l - 25][((i - 155) * 3) + 1] = g[i] 
			rgb[l - 25][((i - 155) * 3) + 2] = b[i] 

#			print r, g, b
	
	return rgb

def isWhiteFlag(line):
	wc = 0
	for i in range(0, 1135):
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
		for i in range(0, 576):
			if (i % 2):
				outfile.write(prevrgb[i])
			else: 
				outfile.write(rgb[i])

	# determine if this is a whole (even+odd) or half (odd) frame using white flag detection for now
#	if (isWhiteFlag(inframe[2])):
	for i in range(0, 576):
		outfile.write(rgb[i])

#	if (isWhiteFlag(inframe[3])):
#			pf_useodd = True
	
	prevrgb = rgb
	
infile = open("testpal.tbc", "rb")
outfile = open("testpal.rgb", "wb")
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
	inframe = np.reshape(indata, (625, 1135))	
	rgbout = process(inframe)

#	indata = np.delete(indata, np.s_[0:len(output)])
	indata = np.array([])

	exit()
