# FDLS in python

# FDLS created by Greg Berchin

# Python adaption Copyright (C) 2014 Chad Page

# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:

# Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
# Neither the name of Enthought nor the names of the SciPy Developers may be used to endorse or promote products derived from this software without specific prior written permission.
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE REGENTS OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

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
	plt.plot(w * (freq/np.pi) / 2.0, angles, 'g')
	plt.ylabel('Angle (radians)', color='g')
	plt.grid()
	plt.axis('tight')
	plt.show()

def FDLS(Fr, Am, Th, N, D, shift = 0):
	wmts = Fr * (2*np.pi)

	ND = 0
	Xa = np.zeros((N + D + 1, len(Fr))) 

	for i in range(0, D):
		Xa[ND] = -Am * np.cos((-(i + 1) * wmts) + Th - (shift * wmts))
		ND = ND + 1

	for i in range(0, N + 1):
		Xa[ND] = np.cos(i * -wmts)
		ND = ND + 1

	X = Xa.transpose()
	Y = np.matrix(Am * np.cos(Th)).transpose()

	out = numpy.linalg.lstsq(X, Y)

	A = np.zeros(D + 1)
	A[0] = 1
	for i in range(0, D):
		A[1 + i] = out[0][i]

	B = np.zeros(N + 1)
	for i in range(0, N + 1):
		B[i] = out[0][i + D]

	return [B, A]

def FDLS_fromfilt(B, A, N, D, shift = 0):

	w, h = sps.freqz(B, A, worN = 1024)
	w = w / (np.pi * 2.0)

	print(len(w))

	Am = np.absolute(h)
	Th = np.angle(h)

	return FDLS(w, Am, Th, N, D, shift)

def FDLS_fromfilt2(B, A, B2, A2, N, D, shift = 0):

	w, h = sps.freqz(B, A, worN = 1024)
	w = w / (np.pi * 2.0)
	
	w2, h2 = sps.freqz(B2, A2, worN = 1024)
	w = w / (np.pi * 2.0)

	h3 = (h + h2) / 2.0
	plt.plot(h.real)
	plt.plot(h.imag)
	plt.plot(h3.real)
	plt.plot(h3.imag)
	plt.show()

	print(len(w))

	Am = np.absolute(h3)
	Th = np.angle(h3)

	return FDLS(w, Am, Th, N, D, shift)



