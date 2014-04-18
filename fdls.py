# FDLS in python

import scipy
import numpy
import numpy as np
import scipy.signal as sps

def FDLS(Fr, Am, Th, N, D):
	wmtsa = Fr * (2*np.pi)

	ND = 0
	Xa = np.zeros((N + D + 1, len(Fr))) 

	for i in range(0, N):
		Xa[ND] = -Am * np.cos((-(i + 1) * wmtsa) + Th)
		ND = ND + 1

	for i in range(0, D + 1):
		Xa[ND] = np.cos(i * -wmtsa)
		ND = ND + 1

	X = Xa.transpose()
	Y = np.matrix(Am * np.cos(Th)).transpose()

	out = numpy.linalg.lstsq(X, Y)

	A = np.zeros(N + 1)
	A[0] = 1
	for i in range(0, N):
		A[1 + i] = out[0][i]

	B = np.zeros(D + 1)
	for i in range(0, D + 1):
		B[i] = out[0][i + D]

	return [B, A]

freq = 4 * 315.0 / 88.0

Ndeemp = 10
Fr = np.array([0,   .5000, 1.00, 2.00, 3.00, 3.58, 4.2, 5.5, 10.0]) / (freq * 2.0)
Am = np.array([100, 83.0,    60,   46,   57,   70,   88,  90 , 10]) / 100.0
Th = np.zeros(9)

[B, A] = FDLS(Fr, Am, Th, Ndeemp, Ndeemp)

#Nboost = 36
#boost_filter = sps.firwin2(Nboost + 1, [0, (3.2/freq), (7.3/freq), (9.3/freq), (11.3/freq), (12.5/freq), 1], [0, -.00, 1.15, 2.0, 1.15, .05, 0], window='hamming')

Nboost = 9
Fr = np.array([0, 3.2, 7.3, 9.3, 11.3, 12.5, freq]) / (freq * 2.0)
Am = np.array([0, 0, 1.3, 2.0, 1.3, .05, 0]) / 100.0
#Am = np.array([0, 0, 1.0, 1.0, 1.0, .05, 0]) / 100.0
Th = np.zeros(7)
[Bboost, Aboost] = FDLS(Fr, Am, Th, Nboost, Nboost) 

Nlpf = 18
lowpass_filter = sps.firwin(Nlpf + 1, 5.0 / (freq), window='hamming')

print "const double c_deemp_b[] {",
for i in range(0, len(B)):
        print "%.15e" % B[i], ",",
print "};"
print

print "const double c_deemp_a[] {",
for i in range(0, len(A)):
        print "%.15e" % A[i], ",",
print "};"
print
print "Filter f_deemp(", Ndeemp, ", c_deemp_a, c_deemp_b);"
print

print "const double c_boost_b[] {",
for i in range(0, len(Bboost)):
        print "%.15e" % Bboost[i], ",",
print "};"
print

print "const double c_boost_a[] {",
for i in range(0, len(Aboost)):
        print "%.15e" % Aboost[i], ",",
print "};"
print
print "Filter f_boost(", Nboost, ", c_boost_a, c_boost_b);"

#print "const double c_boost[] {",
#for i in range(0, len(boost_filter)):
#        print "%.15e" % boost_filter[i], ",",
#print "};"
#print
#print "Filter f_boost(", Nboost,", NULL, c_boost);"
#print

print "const double c_lpf[] {",
for i in range(0, len(lowpass_filter)):
        print "%.15e" % lowpass_filter[i], ",",
print "};"
print
print "Filter f_lpf(" ,Nlpf, ", NULL, c_lpf);"
print


