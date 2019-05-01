# NOTE:  These are not reduced from ld-decode notebook

from base64 import b64encode
import copy
from datetime import datetime
import getopt
import io
from io import BytesIO
import os
import sys

# standard numeric/scientific libraries
import numpy as np
import pandas as pd
import scipy as sp
import scipy.signal as sps
import scipy.fftpack as fftpack 

# plotting
import matplotlib
import matplotlib.pyplot as plt

#internal libraries which may or may not get used
import fdls

def todb(y, zero = False):
    db = 20 * np.log10(np.abs(y))
    if zero:
        return db - np.max(db)
    else:
        return db

def plotfilter_wh(w, h, freq, zero_base = False):
    db = todb(h, zero_base)
    
    above_m3 = None
    for i in range(1, len(w)):
        if (db[i] >= -10) and (db[i - 1] < -10):
            print(">-10db crossing at ", w[i]) 
        if (db[i] >= -3) and (db[i - 1] < -3):
            print(">-3db crossing at ", w[i])
            above_m3 = i
        if (db[i] < -3) and (db[i - 1] >= -3):
            if above_m3 is not None:
                peak_index = np.argmax(db[above_m3:i]) + above_m3
                print("peak at ", w[peak_index], db[peak_index])
            print("<-3db crossing at ", w[i]) 
        if (db[i] >= 3) and (db[i - 1] < 3):
            print(">3db crossing at ", w[i]) 
    
    fig, ax1 = plt.subplots(1, 1, sharex=True)
    ax1.set_title('Digital filter frequency response')

    ax1.plot(w, db, 'b')
    ax1.set_ylabel('Amplitude [dB]', color='b')
    ax1.set_xlabel('Frequency [rad/sample]')
    
    ax2 = ax1.twinx()
    angles = np.unwrap(np.angle(h))
    ax2.plot(w, angles, 'g')
    ax2.set_ylabel('Angle (radians)', color='g')

    plt.grid()
    plt.axis('tight')
    plt.show()
    
    return None

def plotfilter(B, A, freq = 40, whole = False, zero_base = False):
    w, h = sps.freqz(B, A, whole = whole, worN=4096)
    
    if whole:
        w = np.arange(0, freq, freq / len(h))
    else:
        w = np.arange(0, (freq / 2), (freq / 2) / len(h))
        
    return plotfilter_wh(w, h, freq, zero_base)


from scipy import interpolate

# This uses numpy's interpolator, which works well enough
def scale(buf, begin, end, tgtlen):
#        print("scaling ", begin, end, tgtlen)
        ibegin = int(begin)
        iend = int(end)
        linelen = end - begin

        dist = iend - ibegin + 0
        
        sfactor = dist / tgtlen
        
        arr, step = np.linspace(0, dist, num=dist + 1, retstep=True)
        spl = interpolate.splrep(arr, buf[ibegin:ibegin + dist + 1])
        arrout = np.linspace(begin - ibegin, linelen + (begin - ibegin), tgtlen + 1)

        return interpolate.splev(arrout, spl)[:-1]
    
def downscale_field(data, lineinfo, outwidth=1820, lines=625, usewow=False):
    ilinepx = linelen
    dsout = np.zeros((len(lineinfo) * outwidth), dtype=np.double)    

    sfactor = [None]

    for l in range(1, 262):
        scaled = scale(data, lineinfo[l], lineinfo[l + 1], outwidth)
        sfactor.append((lineinfo[l + 1] - lineinfo[l]) / outwidth)

        if usewow:
            wow = (lineinfo[l + 1] - lineinfo[l]) / linelen
            scaled *= wow
                
        dsout[l * outwidth:(l + 1)*outwidth] = scaled
        
    return dsout

'''

For this part of the loader phase I found myself going to function objects that implement this sample API:

```
infile: standard readable/seekable python binary file
sample: starting sample #
readlen: # of samples
```
Returns data if successful, or None or an upstream exception if not (including if not enough data is available)

This might probably need to become a full object once FLAC support is added.
'''

def load_unpacked_data(infile, sample, readlen, sampletype):
    # this is run for unpacked data - 1 is for old cxadc data, 2 for 16bit DD
    infile.seek(sample * sampletype, 0)
    inbuf = infile.read(readlen * sampletype)

    if sampletype == 2:
        indata = np.fromstring(inbuf, 'int16', len(inbuf) // 2)
    else:
        indata = np.fromstring(inbuf, 'uint8', len(inbuf))
    
    if len(indata) < readlen:
        return None

    return indata

def load_unpacked_data_u8(infile, sample, readlen):
    return load_unpacked_data(infile, sample, readlen, 1)

def load_unpacked_data_s16(infile, sample, readlen):
    return load_unpacked_data(infile, sample, readlen, 2)

# This is for the .r30 format I did in ddpack/unpack.c.  Depricated but I still have samples in it.
def load_packed_data_3_32(infile, sample, readlen):
    start = (sample // 3) * 4
    offset = sample % 3
    start, offset

    infile.seek(start)

    # we need another word in case offset != 0
    needed = int(np.ceil(readlen * 3 / 4) * 4) + 4

    inbuf = infile.read(needed)
    indata = np.fromstring(inbuf, 'uint32', len(inbuf) // 4)

    if len(indata) < needed:
        return None

    unpacked = np.zeros(len(indata) * 3, dtype=np.int16)

    # By using strides the unpacked data can be loaded with no additional copies
    np.bitwise_and(indata, 0x3ff, out = unpacked[0::3])
    # hold the shifted bits in it's own array to avoid an allocation
    tmp = np.right_shift(indata, 10)
    np.bitwise_and(tmp, 0x3ff, out = unpacked[1::3])
    np.right_shift(indata, 20, out = tmp)
    np.bitwise_and(tmp, 0x3ff, out = unpacked[2::3])

    return unpacked[offset:offset + readlen]


# The 10-bit samples from the Duplicator...

'''
From Simon's code:

// Original
// 0: xxxx xx00 0000 0000
// 1: xxxx xx11 1111 1111
// 2: xxxx xx22 2222 2222
// 3: xxxx xx33 3333 3333
//
// Packed:
// 0: 0000 0000 0011 1111
// 2: 1111 2222 2222 2233
// 4: 3333 3333
'''

# The bit twiddling is a bit more complex than I'd like... but eh.  I think
# it's debugged now. ;)
def load_packed_data_4_40(infile, sample, readlen):
    start = (sample // 4) * 5
    offset = sample % 4

    seekedto = infile.seek(start)
    
    # we need another word in case offset != 0
    needed = int(np.ceil(readlen * 5 // 4)) + 5

    inbuf = infile.read(needed)
    indata = np.frombuffer(inbuf, 'uint8', len(inbuf))

    if len(indata) < needed:
        return None

    rot2 = np.right_shift(indata, 2)

    unpacked = np.zeros(readlen + 4, dtype=np.uint16)

    # we need to load the 8-bit data into the 16-bit unpacked for left_shift to work
    # correctly...
    unpacked[0::4] = indata[0::5]
    np.left_shift(unpacked[0::4], 2, out=unpacked[0::4])
    np.bitwise_or(unpacked[0::4], np.bitwise_and(np.right_shift(indata[1::5], 6), 0x03), out=unpacked[0::4])

    unpacked[1::4] = np.bitwise_and(indata[1::5], 0x3f)
    np.left_shift(unpacked[1::4], 4, out=unpacked[1::4])
    np.bitwise_or(unpacked[1::4], np.bitwise_and(np.right_shift(indata[2::5], 4), 0x0f), out=unpacked[1::4])

    unpacked[2::4] = np.bitwise_and(indata[2::5], 0x0f)
    np.left_shift(unpacked[2::4], 6, out=unpacked[2::4])
    np.bitwise_or(unpacked[2::4], np.bitwise_and(np.right_shift(indata[3::5], 2), 0x3f), out=unpacked[2::4])

    unpacked[3::4] = np.bitwise_and(indata[3::5], 0x03)
    np.left_shift(unpacked[3::4], 8, out=unpacked[3::4])
    np.bitwise_or(unpacked[3::4], indata[4::5], out=unpacked[3::4])

    # convert back to original DdD 16-bit format (signed 16-bit, left shifted)
    rv_unsigned = unpacked[offset:offset + readlen].copy()
    rv_signed = np.left_shift(rv_unsigned.astype(np.int16) - 512, 6)
    
    return rv_signed



# Essential standalone routines 

pi = np.pi
tau = np.pi * 2

#https://stackoverflow.com/questions/20924085/python-conversion-between-coordinates
polar2z = lambda r,θ: r * np.exp( 1j * θ )
deg2rad = lambda θ: θ * (np.pi / 180)

# from http://tlfabian.blogspot.com/2013/01/implementing-hilbert-90-degree-shift.html

# hilbert_filter_terms has a direct impact on filter delays.  Emperical testing
# determined that 128 was a good value here.
hilbert_filter_terms = 128
hilbert_filter = np.fft.fftshift(
    np.fft.ifft([0]+[1]*hilbert_filter_terms+[0]*hilbert_filter_terms)
)

# Now construct the FFT transform of the hilbert filter.  
# This can be complex multiplied with the raw RF to do a good chunk of real demoduation work
#fft_hilbert = np.fft.fft(hilbert_filter, blocklen)

# This converts a regular B, A filter to an FFT of our selected block length
def filtfft(filt, blocklen):
    return sps.freqz(filt[0], filt[1], blocklen, whole=1)[1]

def inrange(a, mi, ma):
    return (a >= mi) & (a <= ma)

def sqsum(cmplx):
    return np.sqrt((cmplx.real ** 2) + (cmplx.imag ** 2))

def calczc(data, _start_offset, target, edge='both', _count=10, reverse=False):
    
    if reverse:
        # Instead of actually implementing this in reverse, use numpy to flip data
        rev_zc = calczc(data[_start_offset::-1], 0, target, edge, _count)
        if rev_zc is not None:
            return _start_offset - rev_zc
        else:
            return None
    
    start_offset = int(_start_offset)
    count = int(_count + 1)
    
    if edge == 'both': # capture rising or falling edge
        if data[start_offset] < target:
            edge = 'rising'
        else:
            edge = 'falling'

    if edge == 'rising':
        locs = np.where(data[start_offset:start_offset+count] >= target)[0]
        #print(locs)
        offset = 0
    else:
        locs = np.where(data[start_offset:start_offset+count] <= target)[0]
        offset = -1
               
    if len(locs) == 0:
        return None

    index = 0
        
    x = start_offset + locs[index] #+ offset
    
    if (x == 0):
        #print("BUG:  cannot figure out zero crossing for beginning of data")
        return None
    
    a = data[x - 1] - target
    b = data[x] - target
    
    y = -a / (-a + b)

    #print(x, y, locs, data[start_offset:start_offset+locs[0] + 1])

    return x-1+y

def calczc_sets(data, start, end, tgt = 0, cliplevel = None):
    zcsets = {False: [], True:[]}
    bi = start
    
    while bi < end:
        if np.abs(data[bi]) > cliplevel:
            zc = calczc(data, bi, tgt)

            if zc is not None:
                zcsets[data[bi] > tgt].append(offset)
                bi = np.int(zc)

        bi += 1
    
    return {False: np.array(zcsets[False]), True: np.array(zcsets[True])}

def unwrap_hilbert(hilbert, freq_hz):
    tangles = np.angle(hilbert)
    dangles = np.pad(np.diff(tangles), (1, 0), mode='constant')

    # make sure unwapping goes the right way
    if (dangles[0] < -pi):
        dangles[0] += tau

    tdangles2 = np.unwrap(dangles) 
    # With extremely bad data, the unwrapped angles can jump.
    while np.min(tdangles2) < 0:
        tdangles2[tdangles2 < 0] += tau
    while np.max(tdangles2) > tau:
        tdangles2[tdangles2 > tau] -= tau
    return (tdangles2 * (freq_hz / tau))

def genwave(rate, freq, initialphase = 0):
    ''' Generate an FM waveform from target frequency data '''
    out = np.zeros(len(rate), dtype=np.double)
    
    angle = initialphase
    
    for i in range(0, len(rate)):
        angle += np.pi * (rate[i] / freq)
        if angle > np.pi:
            angle -= tau
        
        out[i] = np.sin(angle)
        
    return out

# slightly faster than np.std for short arrays
def rms(arr):
    return np.sqrt(np.mean(np.square(arr - np.mean(arr))))

# MTF calculations
def get_fmax(cavframe = 0, laser=780, na=0.5, fps=30):
    loc = .055 + ((cavframe / 54000) * .090)
    return (2*na/(laser/1000))*(2*np.pi*fps)*loc

def compute_mtf(freq, cavframe = 0, laser=780, na=0.52):
    fmax = get_fmax(cavframe, laser, na)

    freq_mhz = freq / 1000000
    
    if type(freq_mhz) == np.ndarray:
        freq_mhz[freq_mhz > fmax] = fmax
    elif freq_mhz > fmax:
        return 0

    # from Compact Disc Technology AvHeitarō Nakajima, Hiroshi Ogawa page 17
    return (2/np.pi)*(np.arccos(freq_mhz/fmax)-((freq_mhz/fmax)*np.sqrt(1-((freq_mhz/fmax)**2))))

def roundfloat(fl, places = 3):
    ''' round float to (places) decimal places '''
    r = 10 ** places
    return np.round(fl * r) / r

# Something like this should be a numpy function, but I can't find it.

def findareas(array, cross):
    ''' Find areas where `array` is <= `cross`
    
    returns: array of tuples of said areas (begin, end, length)
    '''
    starts = np.where(np.logical_and(array[1:] < cross, array[:-1] >= cross))[0]
    ends = np.where(np.logical_and(array[1:] >= cross, array[:-1] < cross))[0]

    # remove 'dangling' beginnings and endings so everything zips up nicely and in order
    if ends[0] < starts[0]:
        ends = ends[1:]

    if starts[-1] > ends[-1]:
        starts = starts[:-1]

    return [(*z, z[1] - z[0]) for z in zip(starts, ends)]

def findareas_inrange(array, low, high):
    ''' Find areas where `array` is between `low` and `high`
    
    returns: array of tuples of said areas (begin, end, length)
    '''
    
    array_inrange = inrange(array, low, high)
    
    starts = np.where(np.logical_and(array_inrange[1:] == True, array_inrange[:-1] == False))[0]
    ends = np.where(np.logical_and(array_inrange[1:] == False, array_inrange[:-1] == True))[0]

    # remove 'dangling' beginnings and endings so everything zips up nicely and in order
    if ends[0] < starts[0]:
        ends = ends[1:]

    if starts[-1] > ends[-1]:
        starts = starts[:-1]

    return [(*z, z[1] - z[0]) for z in zip(starts, ends)]
