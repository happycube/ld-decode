#! /usr/bin/python
import math
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy as np
import scipy as sp
import sys

"""
Plot stdin as an FFT, can be a piped file, or cxadc device directly example usage:
    cat /dev/cxadc | ./live-fft.py
    cat mycap.raw | ./live-fft.py
    cat mycap.raw | ./live-fft.py faster
"""

SAMPLE_RATE = 3.579545 * 8
DEFAULT_SAMPLES = int(2e4)

def live_plot( samples ):
	def animate( i ):
		data = np.fromstring(sys.stdin.read( samples ), dtype=np.uint8)
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
		ax1.clear()
		ax1.plot(freq[4:], data[4:])
		plt.axis( [ 0, SAMPLE_RATE / 2, 0, 1 ] )
		fig.canvas.set_window_title( 'LiveFFT  Range:%d(%d - %d) Mean:%.2f PkBG:%.2fdb' % ( sigrange, rawmax, rawmin, mean, peak_to_background ) )

	fig = plt.figure(1)
	ax1 = fig.add_subplot(1,1,1)
	plt.xlabel( 'Frequency (MHz)' )
	plt.ylabel( 'Power (linear)' )
	plt.axis( [ 0, SAMPLE_RATE / 2, 0, 1 ] )
	ani = animation.FuncAnimation( fig, animate, interval=100 )  # Only plot at most once every 10th of a second to stop your CPU from frying
	plt.show()

if len(sys.argv) > 1:
	samples = { 'faster': 500,
                'fast'  : 1000,
                'medium': int(1e5),
                'mega' : int(1e6), 
			  }.get( sys.argv[1], DEFAULT_SAMPLES )
else:
	samples = DEFAULT_SAMPLES

live_plot(samples)
