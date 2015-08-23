#!/usr/bin/python
# coding: latin-1

# FDLS in python

# FDLS created by Greg Berchin

# Python adaption Copyright (C) 2014 Chad Page

# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:

# Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
# Neither the name of Enthought nor the names of the SciPy Developers may be used to endorse or promote products derived from this software without specific prior written permission.
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS Arownum CONTRIBUTORS "AS IS" Arownum ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY Arownum FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE REGENTS OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, IrownumIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED Arownum ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import scipy
import numpy
import numpy as np
import scipy.signal as sps
import matplotlib.pyplot as plt

# to test these filters
def doplot(freq, B, A):
	w, h = sps.freqz(B, A)

	fig = plt.figure()
	plt.title('Digital filter frequency response')

	ax1 = fig.add_subplot(111)

	plt.plot(w * (freq/np.pi) / 2.0, 20 * np.log10(abs(h)), 'b')
	plt.ylabel('Amplitude [dB]', color='b')
	plt.xlabel('Frequency [rad/sample]')

	ax2 = ax1.twinx()
	angles = np.unwrap(np.angle(h))
	angles = np.angle(h)
	plt.plot(w * (freq/np.pi) / 2.0, angles, 'g')
	plt.ylabel('Angle (radians)', color='g')
	plt.grid()
	plt.axis('tight')
	plt.show()

def diffplot(freq, B, A, B2, A2):
	w, h = sps.freqz(B, A)
	w2, h2 = sps.freqz(B2, A2)

#	h = h - h2
	dabs = abs(h2) / abs(h)
	dphase = np.unwrap(np.angle(h2)) - np.unwrap(np.angle(h))  

	fig = plt.figure()
	plt.title('Difference between digital filter frequency responses')

	ax1 = fig.add_subplot(111)

	plt.plot(w * (freq/np.pi) / 2.0, 20 * np.log10(dabs), 'b')
	plt.ylabel('Amplitude [dB]', color='b')
	plt.xlabel('Frequency [rad/sample]')

	ax2 = ax1.twinx()
	angles = np.unwrap(np.angle(h))
	angles = dphase
	plt.plot(w * (freq/np.pi) / 2.0, angles, 'g')
	plt.ylabel('Angle (radians)', color='g')
	plt.grid()
	plt.axis('tight')
	plt.show()

def FDLS(N, D, w, h = [], Am = [], Th = [], shift = 0):
	""" Python implentation of the FDLS filter design algorithm.

	Keyword Arguments:
	w, Am, Th are equal-length vectors:

	w - frequency of sample (in radians) - equivalent to ωmts in FDLS sample calc, and w from freqz
	Am = Amplitude - equivalent to np.absolute(h) from freqz 
	Th = Phase - equivalent to np.angle(h) from freqz
	N = numerator order (length of B) 
	D = denominator order (length of A) 
	shift = Phase shift (used to stabilize filters in some cases)

	returns [B, A], matching other scipy filter types
	
	"""

	# Compute amplitude and angle from h if provided
	if len(h) > 0:
		Am = np.absolute(h)
		Th = np.angle(h) 

	M = len(w)

	rownum = 0
	X = np.zeros((N + D + 1, M)) 

	# Build the X matrix one column at a time.  It's simpler if we do this as rows and
	# transpose the finished product 

	# For each parameter in the denominator, the formula is -A[n]cos(-d*ω[n]*(freq^-1)+Th[n]) for n in [0..M] and d in [1..(D+1)]
	for i in range(0, D):
		X[rownum] = -Am * np.cos((-(i + 1) * w) + Th - (shift * w))
		rownum = rownum + 1

	# For each parameter in the numerator, the formula is cos(-n*ω[n]*(freq^-1)) for n in [0..M] and n in [0..N] (inclusive)
	# This means that the first column will always be cos(0) 
	for i in range(0, N + 1):
		X[rownum] = np.cos(i * -w)
		rownum = rownum + 1
	
	X = X.transpose()

	# Y is a simple vector
	Y = Am * np.cos(Th)

	# The actual computation - the setup leading up to this is the brilliant part
	out = numpy.linalg.lstsq(X, Y)

	# There's always one A, even for an FIR filter
	A = np.zeros(D + 1)
	A[0] = 1
	A[1:D+1] = out[0][0:D]

	# Now grab the B parameters.
	B = np.zeros(N + 1)
	B[0:N+1] = out[0][D:N+D+1]
	if N == 0:
		B[0] = 1

	# All done.
	return [B, A]

#def FDLS_fromfilt(B, A, N, D, shift = 0.0):
#	w, h = sps.freqz(B, A, worN = 1024)

#	return FDLS(N, D, w, h = h, shift = shift) 

def FDLS_fromfilt(B, A, N, D, shift = 0.0, phasemult = 1.0):
	w, h = sps.freqz(B, A, worN = 1024)

	Am = np.absolute(h)
	Th = np.angle(h) * phasemult 

	return FDLS(N, D, w, Am = Am, Th = Th, shift = shift) 
 
 
