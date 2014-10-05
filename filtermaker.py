# fdls.FDLS in python

import scipy
import numpy
import numpy as np
import scipy.signal as sps

import fdls as fdls

freq4 = 4 * 315.0 / 88.0
freq = 4 * 315.0 / 88.0
freq10 = 5 * 315.0 / 88.0

def WriteFilter(name, b, a = [1.0]):
	print("vector<double> c_",name,"_b = {",sep="",end="")
	for i in range(0, len(b)):
		print("%.15e" % b[i], ", ",sep="",end="")
	print("};")

	print("vector <double> c_",name,"_a = {",sep="",end="")
	for i in range(0, len(a)):
		print("%.15e" % a[i], ", ",sep="",end="")
	print("};")
	print()
	print("Filter f_",name,"(c_",name,"_b, c_",name,"_a);",sep="")
	print()


tH = 100.0/1000000000.0 # 100nS
tL = 300.0/1000000000.0 # 300nS

n = 512 
df = 512.0/(freq) 
Fr = np.zeros(n)
Am = np.zeros(n)
Th = np.zeros(n)

f_deemp_bil_b = [2.819257458245255e-01, -4.361485083509491e-01]
f_deemp_bil_a = [1.000000000000000e+00, -1.154222762526424e+00]

w, h = sps.freqz(f_deemp_bil_b, f_deemp_bil_a)
w = w / (np.pi * 1.0)
h.imag = h.imag * 1

Ndeemp = 8
Ddeemp = 8
for i in range(0, len(Fr)):
	cf = (float(i) / df)
	Fr[i] = cf / (freq * 2)

	Th[i] = (-((Fr[i] * 6.90) / h.real[i])) - (0 * (np.pi / 180)) 

[f_deemp_b, f_deemp_a] = fdls.FDLS(w, h.real*1, Th, Ndeemp, Ddeemp)

WriteFilter("deemp", f_deemp_b, f_deemp_a)
#fdls.doplot(freq, f_deemp_b, f_deemp_a)
#exit()

# [b, a] = bilinear([.3e-7], [.1e-7], 1/3, 1000000*5*315/88)
f_deemp10_bil_b = [2.678107124284971e-01, -4.643785751430057e-01]
f_deemp10_bil_a = [1.000000000000000e+00, -1.196567862714509e+00]

w, h = sps.freqz(f_deemp10_bil_b, f_deemp10_bil_a)
w = w / (np.pi * 1.0)
h.imag = h.imag * 1

df = 512.0/(freq10) 
Ndeemp10 = 8
Ddeemp10 = 8
for i in range(0, len(Fr)):
	cf = (float(i) / df)
	Fr[i] = cf / (freq10 * 2)

	Th[i] = (-((Fr[i] * 5.95) / h.real[i])) - (0 * (np.pi / 180)) 

[f_deemp10_b, f_deemp10_a] = fdls.FDLS(w, h.real*1, Th, Ndeemp10, Ddeemp10)
WriteFilter("deemp10", f_deemp10_b, f_deemp10_a)

#fdls.doplot2(freq10,f_deemp10_b, f_deemp10_a, 1.0, f_deemp10_bil_b, f_deemp10_bil_a, 1.0)
#exit()

Bboost = sps.firwin(33, 3.5 / (freq), window='hamming', pass_zero=False)
WriteFilter("boost", Bboost)
Bboost10 = sps.firwin(33, 3.5 / (freq10), window='hamming', pass_zero=False)
WriteFilter("boost10", Bboost10)

Ncolor = 32
Fcolor = sps.firwin(Ncolor + 1, 0.2 / (freq), window='hamming')
WriteFilter("color", Fcolor)

Nlpf = 30
lowpass_filter = sps.firwin(Nlpf + 1, 5.2 / (freq), window='hamming')
WriteFilter("lpf", lowpass_filter)

Nlpf = 30
lowpass_filter = sps.firwin(Nlpf + 1, 4.2 / (freq), window='hamming')
WriteFilter("lpf42", lowpass_filter)

Nlpf4 = 10
lowpass_filter4 = sps.firwin(Nlpf + 1, 5.2 / (freq4), window='hamming')
WriteFilter("lpf4", lowpass_filter4)

Nlpf10 = 30
lowpass_filter10 = sps.firwin(Nlpf + 1, 5.2 / (freq10), window='hamming')
WriteFilter("lpf10", lowpass_filter10)

Ncolor = 32
sync_filter = sps.firwin(Ncolor + 1, 0.1 / (freq), window='hamming')
WriteFilter("sync", sync_filter)

# used in ntsc to determine sync level
Ndsync = 32 
dsync_filter = sps.firwin(Ndsync + 1, 0.1 / (freq), window='hamming')
WriteFilter("dsync", dsync_filter)

Ndsync = 20 
dsync_filter4 = sps.firwin(Ndsync + 1, 0.1 / (freq4), window='hamming')
WriteFilter("dsync4", dsync_filter4)

Ndsync = 32 
dsync_filter10 = sps.firwin(Ndsync + 1, 0.1 / (freq10), window='hamming')
WriteFilter("dsync10", dsync_filter10)

Nsync = 20
sync_filter4 = sps.firwin(Nsync + 1, 0.1 / (freq4), window='hamming')
WriteFilter("sync4", sync_filter4)

Nsync = 32
sync_filter10 = sps.firwin(Nsync + 1, 0.1 / (freq10), window='hamming')
WriteFilter("sync10", sync_filter10)

Nnr = 16
hp_nr_filter = sps.firwin(Nnr + 1, 1.8 / (freq / 2.0), window='hamming', pass_zero=False)
WriteFilter("nr", hp_nr_filter)
Nnrc = 24
hp_nrc_filter = sps.firwin(Nnrc + 1, 0.5 / (freq / 2.0), window='hamming', pass_zero=False)
WriteFilter("nrc", hp_nrc_filter)

Ncolorlp4 = 8 
colorlp4_filter = sps.firwin(Ncolorlp4 + 1, [0.6 / (freq / 2)], window='hamming')
WriteFilter("colorlp4", colorlp4_filter)

Ncolorbp4 = 8
colorbp4_filter = sps.firwin(Ncolorbp4 + 1, [3.4006 / (freq / 2), 3.7585 / (freq / 2)], window='hamming', pass_zero=False)
WriteFilter("colorbp4", colorbp4_filter)

Ncolorbp8 = 16
colorbp8_filter = sps.firwin(Ncolorbp8 + 1, [3.4006 / (freq), 3.7585 / (freq)], window='hamming', pass_zero=False)
WriteFilter("colorbp8", colorbp8_filter)

audioin_filter = sps.firwin(65, 3.15 / (freq), window='hamming')
WriteFilter("audioin", audioin_filter)

leftbp_filter = sps.firwin(65, [2.15/(freq/4), 2.45/(freq/4)], window='hamming', pass_zero=False)
WriteFilter("leftbp", leftbp_filter)
rightbp_filter = sps.firwin(65, [2.65/(freq/4), 2.95/(freq/4)], window='hamming', pass_zero=False)
WriteFilter("rightbp", rightbp_filter)

audiolp_filter = sps.firwin(129, .004 / (freq / 4), window='hamming')
WriteFilter("audiolp", audiolp_filter)

# from http://tlfabian.blogspot.com/2013/01/implementing-hilbert-90-degree-shift.html
hilbert_filter = np.fft.fftshift(
    np.fft.ifft([0]+[1]*15+[0]*15)
)
WriteFilter("hilbertr", hilbert_filter.real)
WriteFilter("hilberti", hilbert_filter.imag)

# fm deemphasis (75us)
table = [[.000, 0], [.1, -.01], [.5, -.23], [1, -.87], [2, -2.76], [3, -4.77], [4, -6.58], [5, -8.16], [6, -9.54], [7, -10.75], [8, -11.82], [9, -12.78], [10, -13.66], [11, -14.45], [12, -15.18], [13, -15.86], [14, -16.49], [15, -17.07], [16, -17.62], [17, -18.14], [18, -18.63], [19, -19.09], [20, -19.53], [24, -20]]

Fr = np.empty([len(table)])
Am = np.empty([len(table)])
for i in range(0, len(table)):
	Fr[i] = (table[i][0] / 24.0)
	Am[i] = (np.exp(table[i][1] / 9.0))

Bfmdeemp = sps.firwin2(33, Fr, Am)
WriteFilter("fmdeemp", Bfmdeemp)

