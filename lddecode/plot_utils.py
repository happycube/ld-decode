#!/usr/bin/python3

import io
from io import BytesIO

import numpy as np
import scipy as sp
import scipy.signal as sps
import sys

import matplotlib.pyplot as plt

# To support image displays
from PIL import Image
import IPython.display 
from IPython.display import HTML

pi = np.pi
tau = np.pi * 2

# Plotting routines

def dosplot(B, A, freq = (315.0/88.0) * 8.0):
	w, h = sps.freqz(B, A)

	fig = plt.figure()
	plt.title('Digital filter frequency response')

	ax1 = fig.add_subplot(111)

	db = 20 * np.log10(abs(h))

	for i in range(1, len(w)):
		if (db[i] >= -10) and (db[i - 1] < -10):
			print(">-10db crossing at ", w[i] * (freq/pi) / 2.0) 
		if (db[i] >= -3) and (db[i - 1] < -3):
			print("-3db crossing at ", w[i] * (freq/pi) / 2.0) 
		if (db[i] < -3) and (db[i - 1] >= -3):
			print("<-3db crossing at ", w[i] * (freq/pi) / 2.0) 
		if (db[i] < -10) and (db[i - 1] >= -10):
			print("<-10db crossing at ", w[i] * (freq/pi) / 2.0) 
		if (db[i] < -20) and (db[i - 1] >= -20):
			print("<-20db crossing at ", w[i] * (freq/pi) / 2.0) 

	plt.plot(w * (freq/pi) / 2.0, 20 * np.log10(abs(h)), 'b')
	plt.ylabel('Amplitude [dB]', color='b')
	plt.xlabel('Frequency [rad/sample]')

	plt.show()

def doplot(B, A, freq = (315.0/88.0) * 8.0):
	w, h = sps.freqz(B, A)

	fig = plt.figure()
	plt.title('Digital filter frequency response')
	
	db = 20 * np.log10(abs(h))
	for i in range(1, len(w)):
		if (db[i] >= -10) and (db[i - 1] < -10):
			print(">-10db crossing at ", w[i] * (freq/pi) / 2.0) 
		if (db[i] >= -3) and (db[i - 1] < -3):
			print(">-3db crossing at ", w[i] * (freq/pi) / 2.0) 
		if (db[i] < -3) and (db[i - 1] >= -3):
			print("<-3db crossing at ", w[i] * (freq/pi) / 2.0) 

	ax1 = fig.add_subplot(111)
	
	plt.plot(w * (freq/pi) / 2.0, 20 * np.log10(abs(h)), 'b')
	plt.ylabel('Amplitude [dB]', color='b')
	plt.xlabel('Frequency [rad/sample]')

	ax2 = ax1.twinx()
	angles = np.unwrap(np.angle(h))
	plt.plot(w * (freq/pi) / 2.0, angles, 'g')
	plt.ylabel('Angle (radians)', color='g')
	
	plt.grid()
	plt.axis('tight')
	plt.show()

def doplot2(B, A, B2, A2, freq = (315.0/88.0) * 8.0):
	w, h = sps.freqz(B, A)
	w2, h2 = sps.freqz(B2, A2)

#	h.real /= C
#	h2.real /= C2

	begin = 0
	end = len(w)
#	end = int(len(w) * (12 / freq))

#	chop = len(w) / 20
	chop = 0
	w = w[begin:end]
	w2 = w2[begin:end]
	h = h[begin:end]
	h2 = h2[begin:end]

	v = np.empty(len(w))
	
#	print len(w)

	hm = np.absolute(h)
	hm2 = np.absolute(h2)

	v0 = hm[0] / hm2[0]
	for i in range(0, len(w)):
#		print i, freq / 2 * (w[i] / pi), hm[i], hm2[i], hm[i] / hm2[i], (hm[i] / hm2[i]) / v0
		v[i] = (hm[i] / hm2[i]) / v0

	fig = plt.figure()
	plt.title('Digital filter frequency response')

	ax1 = fig.add_subplot(111)

	v  = 20 * np.log10(v )

#	plt.plot(w * (freq/pi) / 2.0, v)
#	plt.show()
#	exit()

	plt.plot(w * (freq/pi) / 2.0, 20 * np.log10(abs(h)), 'r')
	plt.plot(w * (freq/pi) / 2.0, 20 * np.log10(abs(h2)), 'b')
	plt.ylabel('Amplitude [dB]', color='b')
	plt.xlabel('Frequency [rad/sample]')
	
	ax2 = ax1.twinx()
	angles = np.unwrap(np.angle(h))
	angles2 = np.unwrap(np.angle(h2))
	plt.plot(w * (freq/pi) / 2.0, angles, 'g')
	plt.plot(w * (freq/pi) / 2.0, angles2, 'y')
	plt.ylabel('Angle (radians)', color='g')

	plt.grid()
	plt.axis('tight')
	plt.show()

# This matches FDLS-based conversion surprisingly well (i.e. FDLS is more accurate than I thought ;) )
def BA_to_FFT(B, A, blocklen):
    return np.complex64(sps.freqz(B, A, blocklen, whole=True)[1])

# Draws a uint16 image, downscaled to uint8
def draw_raw_bwimage(bm, x = 2800, y = 525, hscale = 1, vscale = 2, outsize = None):
    if y is None:
        y = len(bm) // x
        
    if outsize is None:
        outsize = (x * hscale, y * vscale)
    
    bmf = np.uint8(bm[0:x*y] / 256.0)
#    print(bmf.shape)
    if x is not None:
        bms = (bmf.reshape(len(bmf)//x, -1))
    else:
        bms = bmf
    
#    print(bms.dtype, bms.shape, bms[:][0:y].shape)
    im = Image.fromarray(bms[0:y])
    im = im.resize(outsize)
    b = BytesIO()
    im.save(b, format='png')
    return IPython.display.Image(b.getvalue())
 
def draw_field(field):
    return draw_raw_bwimage(field.dspicture, f.outlinelen, f.outlinecount)