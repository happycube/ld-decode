import numpy as np
import matplotlib.pyplot as plt
import scipy as sp
import scipy.signal as sps
import sys

#binfile = open("ve-greynb50.tbc", "rb").read()
binfile = open(sys.argv[1], "rb").read()
#binfile = open("tgen.ld", "rb").read()
data = np.fromstring(binfile, dtype=np.uint8)

mean = np.mean(data)
c = data - mean

t = np.arange(len(c))
sp = np.fft.fft(c)
freq = np.fft.fftfreq(t.shape[-1])
d = []
#for i in range(0, len(data)):
#        d.append(np.sqrt((sp[i].real * sp[i].real) + (sp[i].imag * sp[i].imag)))

d = np.sqrt((sp.real * sp.real) + (sp.imag * sp.imag))

plt.plot(freq[4:], d[4:])
plt.show()
