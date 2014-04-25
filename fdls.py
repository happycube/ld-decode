# FDLS in python

import scipy
import numpy
import numpy as np
import scipy.signal as sps

def FDLS(Fr, Am, Th, N, D):
	wmtsa = Fr * (2*np.pi)

	ND = 0
	Xa = np.zeros((N + D + 1, len(Fr))) 

	for i in range(0, D):
		Xa[ND] = -Am * np.cos((-(i + 1) * wmtsa) + Th)
		ND = ND + 1

	for i in range(0, N + 1):
		Xa[ND] = np.cos(i * -wmtsa)
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

freq = 4 * 315.0 / 88.0

Ndeemp = 10 
Ddeemp = 10 
Fr = np.array([0,   .5000, 1.00, 2.00, 3.00, 3.58, 4.2, 5.5, 6.5, 10.0]) / (freq * 2.0)
Am = np.array([100, 85.0,    68,   58,   65,   75,   75,  75 , 75, 0]) / 100.0
Th = np.zeros(10)
#Th = np.array([0, 0, 0, 0, 0, 0, -0, -1, -1])

#Fr = np.array([0, 0.5, 1.0, 2.0, 2.5, 3.0, 3.5, 4.0, 4.2, 4.5, 5.0, 6.0, freq]) / (freq * 2.0) 
#Am = np.array([1.00, .79, .66, .622, .64725, .7105, .8, .907, 1.24, 1.3986, 1.5, 1.5, 1.5, 1.5]) 
#Am = np.array([1.00, .82, .72, .64725, .7105, .8, .907, 1.24, 1.3986, 1.5, 1.5, 1.5, 1.5]) 
#Th = np.zeros(len(Fr))
#Fr = np.array([0,   .5000, 1.59, 2.00, 3.00, 3.58, 4.2, 5.5, 10.0]) / (freq * 2.0)
#Am = np.array([100, 83.0,    32, 47,   65,   83,   88,  90 , 10]) / 100.0
#Th = np.zeros(9)

Ndeemp = 4 
Ddeemp = 11 
# V2800
Fr = np.array([0,   .5000, 1.00, 2.00, 3.00, 3.58, 4.2, 5.5, 10.0]) / (freq * 2.0)
Am = np.array([100, 83.0,    60,   46,   57,   70,   88,  90 , 10]) / 100.0
Th = np.zeros(9)

# 503 v1
Fr = np.array([0,   .5000, 1.60, 3.00, 4.2, 5.5, 10.0]) / (freq * 2.0)
Am = np.array([100, 83.0,    44,   50, 70,  75 , 10]) / 100.0
Th = np.zeros(len(Fr))

# 503 v2, also good de-emp for 2800, but lower FR
Fr = np.array([0,   .5000, 1.60, 3.00, 4.2, 5.0, 10.0]) / (freq * 2.0)
Am = np.array([100, 84.0,    45,   45, 60,  70 , 00]) / 100.0
Th = np.zeros(len(Fr))

# v. good de-emp for 2800, but relatively low FR
#Fr = np.array([0,   .5000, 1.60, 3.00, 4.2, 5.0, 10.0]) / (freq * 2.0)
#Am = np.array([100, 84.0,    44,   45, 60,  70 , 00]) / 100.0
#Th = np.zeros(len(Fr))

# nice balance of de-emp and FR on 2800 
#Fr = np.array([0,   .5000, 1.60, 3.00, 4.2, 5.0, 10.0]) / (freq * 2.0)
#Am = np.array([100, 84.0,    44,   50, 68,  80 , 00]) / 100.0
#Th = np.zeros(len(Fr))

#nf = 256 
#Fr = np.zeros(nf)
#Am = np.zeros(nf)
#Th = np.zeros(nf)
#for i in range(0, len(Fr)):
#	Fr[i] = i / (nf * 2.0)
#	Am[i] = 1.0 

[B, A] = FDLS(Fr, Am, Th, Ndeemp, Ddeemp)

#Nboost = 36
#boost_filter = sps.firwin2(Nboost + 1, [0, (3.2/freq), (7.3/freq), (9.3/freq), (11.3/freq), (12.5/freq), 1], [0, -.00, 1.15, 2.0, 1.15, .05, 0], window='hamming')

Nboost = 9
Fr = np.array([0, 3.2, 7.3, 9.3, 11.3, 12.5, freq]) / (freq * 2.0)
Am = np.array([0, 0, 1.3, 2.0, 1.3, .05, 0]) / 100.0
#Am = np.array([0, 0, 1.0, 1.0, 1.0, .05, 0]) / 100.0
Th = np.zeros(7)
[Bboost, Aboost] = FDLS(Fr, Am, Th, Nboost, Nboost) 

Nlpf = 14 
Dlpf = 2 
Fr = np.array([0, 4.2, 5.0, freq]) / (freq * 2.0)
Am = np.array([100, 80, 60, 0]) / 100.0
#Am = np.array([0, 0, 1.0, 1.0, 1.0, .05, 0]) / 100.0
Th = np.zeros(4)
[Blpf, Alpf] = FDLS(Fr, Am, Th, Nlpf, Dlpf) 

Ncolor = 2 
Dcolor = 32 
Fr = np.array([0, 0.6, 1.3, 2.0, 3.0, freq]) / (freq * 2.0)
Am = np.array([100, 100, 60, 30, 0, 0]) / 100.0
#Am = np.array([0, 0, 1.0, 1.0, 1.0, .05, 0]) / 100.0
Th = np.zeros(6)
[Bcolor, Acolor] = FDLS(Fr, Am, Th, Ncolor, Dcolor) 

Ncolor = 32
Fcolor = sps.firwin(Ncolor + 1, 0.5 / (freq), window='hamming')

Nlpf = 18
lowpass_filter = sps.firwin(Nlpf + 1, 5.0 / (freq), window='hamming')

print "vector<double> c_deemp_b = {",
for i in range(0, len(B)):
        print "%.15e" % B[i], ",",
print "};"
print

print "vector <double> c_deemp_a = {",
for i in range(0, len(A)):
        print "%.15e" % A[i], ",",
print "};"
print
print "Filter f_deemp(c_deemp_b, c_deemp_a);"
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

print "vector<double> c_lpf_b = {",
for i in range(0, len(Blpf)):
        print "%.15e" % Blpf[i], ",",
print "};"
print

print "vector <double> c_lpf_a = {",
for i in range(0, len(Alpf)):
        print "%.15e" % Alpf[i], ",",
print "};"
print
#print "Filter f_lpf(c_lpf_b, c_lpf_a);"
print

print "vector<double> c_color_b = {",
for i in range(0, len(Bcolor)):
        print "%.15e" % Bcolor[i], ",",
print "};"
print

print "vector <double> c_color_a = {",
for i in range(0, len(Acolor)):
        print "%.15e" % Acolor[i], ",",
print "};"
print
#print "Filter f_color(c_color_b, c_color_a);"
print

print "const double c_color[] {",
for i in range(0, len(Fcolor)):
        print "%.15e" % Fcolor[i], ",",
print "};"
print
print "Filter f_color(" ,Ncolor, ", NULL, c_color);"
print

print "const double c_lpf[] {",
for i in range(0, len(lowpass_filter)):
        print "%.15e" % lowpass_filter[i], ",",
print "};"
print
print "Filter f_lpf(" ,Nlpf, ", NULL, c_lpf);"
print


