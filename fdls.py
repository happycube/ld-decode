# FDLS in python

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


