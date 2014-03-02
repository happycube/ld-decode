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

color_filter = [2.214464531115009e-03, 2.779566868356983e-03, 4.009052177841430e-03, 6.041802526864055e-03, 8.964977379775094e-03, 1.280250319629312e-02, 1.750822265693915e-02, 2.296445273166145e-02, 2.898626064895014e-02, 3.533129030361252e-02, 4.171449995422212e-02, 4.782674655050909e-02, 5.335581047849616e-02, 5.800822770944922e-02, 6.153020526791717e-02, 6.372594980605055e-02, 6.447193442389310e-02, 6.372594980605055e-02, 6.153020526791718e-02, 5.800822770944922e-02, 5.335581047849616e-02, 4.782674655050909e-02, 4.171449995422215e-02, 3.533129030361253e-02, 2.898626064895015e-02, 2.296445273166145e-02, 1.750822265693915e-02, 1.280250319629313e-02, 8.964977379775097e-03, 6.041802526864056e-03, 4.009052177841434e-03, 2.779566868356985e-03, 2.214464531115009e-03]

# set up sync color heterodyne table first 
bhet = np.empty(8, dtype=np.complex)
for i in range(0, 8):
	bhet[i] = complex(np.cos((i / freq) * 2.0 * np.pi), -(np.sin((i / freq) * 2.0 * np.pi)))

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
	y = (y - 16384) * 1.40
	i = i * 1.4
	q = q * 1.4

	r = (y * 1.164) + (1.596 * i);
	g = (y * 1.164) - (0.813 * i) - (q * 0.391);
	b = (y * 1.164) + (q * 2.018);

	r = clamp(r / 256, 0, 255)	
	g = clamp(g / 256, 0, 255)	
	b = clamp(b / 256, 0, 255)	

	return [r, g, b]

# return 1488x480 rgb frame
def comb(inframe):
	rgb = np.zeros([480, 1488 * 3], dtype=np.uint8)
	prevframe = inframe
		
	lhet = np.empty([525, 8], dtype=np.complex)
	lohet = np.empty([525, 1685], dtype=np.complex)
	lohet_filt = np.empty([525, 1685 + 32], dtype=np.complex)
	#for l in range(24, 504):
	for l in range(24, 504):
		[level, phase] = burst_detect(inframe[l])
#		print level, phase

		for i in range(0, 8):
			lhet[l][i] = complex(np.cos(phase + ((i / freq) * 2.0 * np.pi)), np.sin(phase + ((i / freq) * 2.0 * np.pi)))

		for i in range(0, 1685):
			lohet[l][i] = lhet[l][i % 8] * inframe[l][i]
#			print lohet[i].real, lohet[i].imag

		lohet_filt[l] = sps.fftconvolve(lohet[l], color_filter)
#		lohet_filt = np.delete(lohet_filt, np.s_[0:len(output)])
#		for i in range(0, 1685):
#			print inframe[l][i - 17], lohet_filt[i].real, lohet_filt[i].imag
		
	cmult = 3.5	

	for l in range(24, 504):
		for i in range(155, 155 + 1488):
#			print i, lohet_filt[l][i].imag * lhet[(i - 5) % 8].imag, lohet_filt[l][i].real * lhet[(i - 5) % 8].real, 
#			print lohet_filt[l - 2][i].imag * lhet[(i - 5) % 8].imag, lohet_filt[l - 2][i].real * lhet[(i - 5) % 8].real, 
#			print lohet_filt[l + 2][i].imag * lhet[(i - 5) % 8].imag, lohet_filt[l + 2][i].real * lhet[(i - 5) % 8].real, 
#			iadj = 2 * (lohet_filt[l][i].imag * lhet[l][(i - 5) % 8].imag)
#			qadj = 2 * (lohet_filt[l][i].real * lhet[l][(i - 5) % 8].real) 
			
#			iadj = lohet_filt[l][i].imag * lhet[(i - 5) % 8].imag + (0.5 * (lohet_filt[l + 2][i].imag * lhet[(i - 5) % 8].imag + lohet_filt[l - 2][i].imag * lhet[(i - 5) % 8].imag))
#			qadj = lohet_filt[l][i].real * lhet[(i - 5) % 8].real + (0.5 * (lohet_filt[l + 2][i].real * lhet[(i - 5) % 8].real + lohet_filt[l - 2][i].real * lhet[(i - 5) % 8].real)) 

			imag = (0.5 * lohet_filt[l][i].imag) + (0.25 * (lohet_filt[l - 2][i].imag + lohet_filt[l + 2][i].imag)) 
			real = (0.5 * lohet_filt[l][i].real) + (0.25 * (lohet_filt[l - 2][i].real + lohet_filt[l + 2][i].real)) 
			iadj = 2 * (imag * lhet[l][(i - 5) % 8].imag)
			qadj = 2 * (real * lhet[l][(i - 5) % 8].real) 

#			imag = lohet_filt[l][i].imag
#			real = lohet_filt[l][i].real

#			print i, inframe[l][i - 17], iadj, qadj, inframe[l][i - 17] + iadj + qadj, imag, real, 

#			print iadj, qadj
#			print i, inframe[l][i - 17], lohet_filt[i].imag, lohet_filt[i].real, iadj, qadj, iadj + qadj, inframe[l][i - 17] + iadj + qadj

#			[r, g, b] = torgb(inframe[l][i - 17] + iadj + qadj, 0, 0) 
#			[r, g, b] = torgb(inframe[l][i - 17] , 0, 0) 
			[r, g, b] = torgb(inframe[l][i - 17] + iadj + qadj, cmult * imag, -cmult * real)
			rgb[l - 25][((i - 155) * 3) + 0] = r 
			rgb[l - 25][((i - 155) * 3) + 1] = g 
			rgb[l - 25][((i - 155) * 3) + 2] = b 

#			print r, g, b
	
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
	inframe = np.reshape(indata, (505, 1685))	
	rgbout = process(inframe)

#	indata = np.delete(indata, np.s_[0:len(output)])
	indata = np.array([])

	exit()
