#! /usr/bin/python
import math
import matplotlib.pyplot as plt
import numpy as np
import scipy as sp
import sys

SAMPLE_RATE = 3.579545 * 8
MAX_SAMPLES = int(1e6)

def load( filename ):
	if filename.endswith('.ld'):
		ttype = np.uint16
		max_samples = MAX_SAMPLES * 2
		print('Assuming 16 bits per pixel')
	else:
		ttype = np.uint8
		max_samples = MAX_SAMPLES
		print('Assuming 8 bits per pixel')
	with open(filename, "rb") as binfile:  
		data = np.fromstring(binfile.read(max_samples), dtype=ttype)  # Read at most 1e6 samples
		print('Loaded %d bytes of file %s' % (max_samples, filename))
	return data	

def load_and_plot( filename ):
	data     = load( filename )
	mean     = np.mean(data)
	rawmax   = max( data )
	rawmin   = min( data )
	sigrange = rawmax - rawmin
	data = data - mean
	freq = np.fft.fftfreq(np.arange(len(data)).shape[-1]) * SAMPLE_RATE  # Set frequency scale
	data = np.fft.fft(data)
	data = np.sqrt((data.real * data.real) + (data.imag * data.imag))
	data = data / max( data )  # Normalize to y to 1.0
	peak_to_background = 20 * math.log10( 1.0 / np.mean( data ) )
	plt.plot(freq[4:], data[4:])  
	plt.axis( [ 0, SAMPLE_RATE / 2, 0, 1 ] )
	plt.xlabel( 'Frequency (MHz)' )
	plt.ylabel( 'Power (linear)' )
	fig = plt.figure(1)
	fig.canvas.set_window_title( 'FFT8  %s  Range:%d(%d - %d) Mean:%.2f PkBG:%.2fdb' %\
					          ( filename, sigrange, rawmax, rawmin, mean, peak_to_background ) )
	plt.show()

load_and_plot( sys.argv[1] )
