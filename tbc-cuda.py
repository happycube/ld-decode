#!/usr/bin/python3
#from __future__ import division
#from __future__ import print_function

import numpy as np
import scipy as sp
import scipy.signal as sps
import scipy.fftpack as fftpack 
import matplotlib.pyplot as plt
import sys
import getopt

import fft8 as fft8 
import fdls as fdls
import ld_utils as utils

import pycuda.autoinit
import pycuda.driver as drv
import pycuda.gpuarray as gpuarray
from pycuda.compiler import SourceModule

import skcuda.fft as fft
import skcuda.misc as misc
    
import cProfile

pi = np.pi
tau = np.pi * 2

freq = (315.0 / 88.0) * 8.00
freq_hz = freq * 1000000.0

afreq = freq / 4.0
afreq_hz = afreq * 1000000.0

blocklenk = 64
blocklen = (blocklenk * 1024)  

ablocklenk = blocklenk//4 
ablocklen = (ablocklenk * 1024)  

# buffer enough to hold two entire frames and change - probably only need one
buftgt = 1820 * 1200

# ???
indata_valid = 0
indata = np.empty(buftgt, dtype=np.uint16)

# returns first byte that should be kept.  i.e. a couple of lines before vsync?
def process(data):
	return (1820 * 525)

def main(argv=None):
	outfile = open("test.tbc", "wb")
#	infile = sys.stdin.buffer
	infile = open("test.ld", "rb")

	done = 0

	inbuf = infile.read(buftgt * 2)
	indata = np.fromstring(inbuf, 'uint16', buftgt)

	while (done == 0):
		keep = process(indata)
		indata = indata[keep:]

		toread = buftgt - len(indata)
		inbuf = infile.read(toread * 2)
		
		print(toread * 2, len(inbuf), len(indata))

		if (len(inbuf) < toread):
			done = 1

		indata = np.append(indata, np.fromstring(inbuf, 'uint16', int(len(inbuf) / 2)))

		print(len(inbuf), len(indata))

if __name__ == "__main__":
    sys.exit(main())

