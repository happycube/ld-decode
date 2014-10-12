#!/usr/bin/python
import numpy as np
import sys

print len(sys.argv)

#binfile = open("ve-greynb50.tbc", "rb").read()
binfile = open(sys.argv[1], "rb").read()
#binfile = open("tgen.ld", "rb").read()
data = np.fromstring(binfile, dtype=np.uint16)

irescale = 327.68
def u16_to_ire(u):
	return (u / irescale) - 60

# MB on most disks
line = 21 
#line = 210 

# MB on late pioneer?
#line = 7

if len(sys.argv) > 2:
	line = int(sys.argv[2])

begin = 100
end = 700

if (len(sys.argv) == 5):
	begin = int(sys.argv[3])
	end = int(sys.argv[4])

#b = (data[84550:(84550+1024)])
#b = (data[((844 * 30) + 300):((844 * 30) + 1650)])
b = (data[((844 * line)):((844 * line) + 844)])

c = b[begin:end]
mean = np.mean(c)
mean_ire = u16_to_ire(np.mean(c)) 
std_ire = (np.std(c) / irescale) 

print "mean ire: ", mean, mean_ire 
print "stddev", std_ire
print "SNR", 20 * np.log10(mean_ire / std_ire)

import matplotlib.pyplot as plt

c = []
#for i in range(0, 512):
#	c.append(((b[i * 2] - mean) / 2) + ((b[(i * 2) + 1] - mean) / 2)) 

for i in range(0, len(b)):
	c.append(u16_to_ire(b[i])) 
#	c.append(((b[i] * ((9300000.0 - 7600000.0) / 57344.0))) + 7600000) 

print len(b), len(c)

mean = np.mean(c)
std_ire = np.std(c) 
print 20 * np.log10(70 / std_ire)

#freq = np.fft.fftfreq(t.shape[-1])
#print len(sp)
#plt.plot(freq, sp.real, freq, sp.imag)
plt.plot(range(0, len(c)), c)
#plt.ylim([7700000,9700000])
plt.show()

