# fdls.FDLS in python

import scipy
import numpy
import numpy as np
import scipy.signal as sps

import fdls as fdls

freq = 4 * 315.0 / 88.0

tH = 100.0/1000000000.0 # 100nS
tL = 300.0/1000000000.0 # 300nS

n = 128
df = 128.0/(freq) 
Fr = np.zeros(n)
Am = np.zeros(n)
Th = np.zeros(n)

for f in range(0, n):
        F = ((float(f) / df) * 1000000.0) + 1
        H = 2.0 * np.pi * F * tH
        L = 2.0 * np.pi * F * tL

        A = 1.0 + (1.0 / (H * H))
        B = 1.0 + (1.0 / (L * L))

        DE = ((10.0*np.log(A/B))-21.9722457733) * (10.0 / 21.9722457733)
	cf = (float(f) / df)

        Fr[f] = cf / (freq * 2)
        Am[f] = np.power(10, (DE/18.0)) 

Ndeemp = 8
Ddeemp = 5

for i in range(0, len(Fr)):
	Th[i] = -(Fr[i] * 5040) / 180.0
	Th[i] = -(Fr[i] * 29.4) 
	Th[i] = -(Fr[i] * 30.0) 
	Th[i] = -(Fr[i] * 30.0) 

[f_deemp_b, f_deemp_a] = fdls.FDLS(Fr, Am, Th, Ndeemp, Ddeemp)

#Ndeemp = 4 
#Ddeemp = 11 

# 503 v2, also good de-emp for 2800, but lower FR
Fr = np.array([0,   .5000, 1.60, 3.00, 4.2, 5.0, 10.0]) / (freq * 2.0)
Am = np.array([100, 84.0,    45,   45, 60,  70 , 00]) / 100.0
Th = np.zeros(len(Fr))

#[f_deemp_b, f_deemp_a] = fdls.FDLS(Fr, Am, Th, Ndeemp, Ddeemp)

Bboost = sps.firwin(33, 3.5 / (freq), window='hamming', pass_zero=False)

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

Nlpf = 30
lowpass_filter = sps.firwin(Nlpf + 1, 5.2 / (freq), window='hamming')

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

# from http://tlfabian.blogspot.com/2013/01/implementing-hilbert-90-degree-shift.html
hilbert_filter = np.fft.fftshift(
    np.fft.ifft([0]+[1]*20+[0]*20)
)

print "const double c_hilbertr[] {",
for i in range(0, len(hilbert_filter)):
        print "%.15e" % hilbert_filter.real[i], ",",
print "};"
print
print "Filter f_hilbertr(" ,len(hilbert_filter)-1, ", NULL, c_hilbertr);"
print

print "const double c_hilberti[] {",
for i in range(0, len(hilbert_filter)):
        print "%.15e" % hilbert_filter.imag[i], ",",
print "};"
print
print "Filter f_hilberti(" ,len(hilbert_filter)-1, ", NULL, c_hilberti);"
print

print "vector<double> c_deemp_b = {",
for i in range(0, len(f_deemp_b)):
        print "%.15e" % f_deemp_b[i], ",",
print "};"
print

print "vector <double> c_deemp_a = {",
for i in range(0, len(f_deemp_a)):
        print "%.15e" % f_deemp_a[i], ",",
print "};"
print
print "Filter f_deemp(c_deemp_b, c_deemp_a);"
print

print "const double c_boost_b[] {",
for i in range(0, len(Bboost)):
        print "%.15e" % Bboost[i], ",",
print "};"
print
print "Filter f_boost(", len(Bboost) - 1, ", NULL, c_boost_b);"

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

