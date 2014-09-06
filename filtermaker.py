# fdls.FDLS in python

import scipy
import numpy
import numpy as np
import scipy.signal as sps

import fdls as fdls

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

[B, A] = fdls.FDLS(Fr, Am, Th, Ndeemp, Ddeemp)

#Nboost = 36
#boost_filter = sps.firwin2(Nboost + 1, [0, (3.2/freq), (7.3/freq), (9.3/freq), (11.3/freq), (12.5/freq), 1], [0, -.00, 1.15, 2.0, 1.15, .05, 0], window='hamming')

Nboost = 9
Fr = np.array([0, 3.2, 7.3, 9.3, 11.3, 12.5, freq]) / (freq * 2.0)
Am = np.array([0, 0, 1.3, 2.0, 1.3, .05, 0]) / 100.0
#Am = np.array([0, 0, 1.0, 1.0, 1.0, .05, 0]) / 100.0
Th = np.zeros(7)
[Bboost, Aboost] = fdls.FDLS(Fr, Am, Th, Nboost, Nboost) 

Nlpf = 14 
Dlpf = 2 
Fr = np.array([0, 4.2, 5.0, freq]) / (freq * 2.0)
Am = np.array([100, 80, 60, 0]) / 100.0
#Am = np.array([0, 0, 1.0, 1.0, 1.0, .05, 0]) / 100.0
Th = np.zeros(4)
[Blpf, Alpf] = fdls.FDLS(Fr, Am, Th, Nlpf, Dlpf) 

Ncolor = 2 
Dcolor = 32 
Fr = np.array([0, 0.6, 1.3, 2.0, 3.0, freq]) / (freq * 2.0)
Am = np.array([100, 100, 60, 30, 0, 0]) / 100.0
#Am = np.array([0, 0, 1.0, 1.0, 1.0, .05, 0]) / 100.0
Th = np.zeros(6)
[Bcolor, Acolor] = fdls.FDLS(Fr, Am, Th, Ncolor, Dcolor) 

Bcolor = sps.firwin(33, 0.8 / (freq), window='hamming')
Acolor = [1.0]

Ncolor = 32
Fcolor = sps.firwin(Ncolor + 1, 0.2 / (freq), window='hamming')

Nlpf = 18
lowpass_filter = sps.firwin(Nlpf + 1, 5.0 / (freq), window='hamming')

sync_filter = sps.firwin(Ncolor + 1, 0.1 / (freq), window='hamming')
#fdls.doplot(freq*2, sync_filter, [1.0])
#exit()

Nnr = 16
hp_nr_filter = sps.firwin(Nnr + 1, 1.8 / (freq / 2.0), window='hamming', pass_zero=False)
hp_nrc_filter = sps.firwin(Nnr + 1, 0.6 / (freq / 2.0), window='hamming', pass_zero=False)

Ncolorlp4 = 16 
colorlp4_filter = sps.firwin(Ncolorlp4 + 1, [0.6 / (freq / 2)], window='hamming')

Ncolorbp4 = 8
colorbp4_filter = sps.firwin(Ncolorbp4 + 1, [3.4006 / (freq / 2), 3.7585 / (freq / 2)], window='hamming', pass_zero=False)

Ncolorbp8 = 16
colorbp8_filter = sps.firwin(Ncolorbp8 + 1, [3.4006 / (freq), 3.7585 / (freq)], window='hamming', pass_zero=False)

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

print "const double c_sync[] {",
for i in range(0, len(sync_filter)):
        print "%.15e" % sync_filter[i], ",",
print "};"
print
print "Filter f_sync(" ,Ncolor, ", NULL, c_sync);"

print "const double c_lpf[] {",
for i in range(0, len(lowpass_filter)):
        print "%.15e" % lowpass_filter[i], ",",
print "};"
print
print "Filter f_lpf(" ,Nlpf, ", NULL, c_lpf);"
print

print "const double c_nr[] {",
for i in range(0, len(hp_nr_filter)):
        print "%.15e" % hp_nr_filter[i], ",",
print "};"
print
print "Filter f_nr(" ,Nnr, ", NULL, c_nr);"

print "const double c_nrc[] {",
for i in range(0, len(hp_nrc_filter)):
        print "%.15e" % hp_nrc_filter[i], ",",
print "};"
print
print "Filter f_nrc(" ,Nnr, ", NULL, c_nr);"

print "const double c_colorbp4[] {",
for i in range(0, len(colorbp4_filter)):
        print "%.15e" % colorbp4_filter[i], ",",
print "};"
print
print "Filter f_colorbp4(" ,Ncolorbp4, ", NULL, c_colorbp4);"

print "const double c_colorbp8[] {",
for i in range(0, len(colorbp8_filter)):
        print "%.15e" % colorbp8_filter[i], ",",
print "};"
print
print "Filter f_colorbp8(" ,Ncolorbp8, ", NULL, c_colorbp8);"

print "const double c_colorlp4[] {",
for i in range(0, len(colorlp4_filter)):
        print "%.15e" % colorlp4_filter[i], ",",
print "};"
print
print "Filter f_colorlp4(" ,Ncolorlp4, ", NULL, c_colorlp4);"

