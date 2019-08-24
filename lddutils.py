# A collection of helper functions used in dev notebooks and lddecode_core.py

from base64 import b64encode
from collections import namedtuple
import copy
from datetime import datetime
import getopt
import io
from io import BytesIO
import os
import sys
import subprocess

from numba import jit, njit

# standard numeric/scientific libraries
import numpy as np
import scipy as sp
import scipy.signal as sps

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

def plotfilter(B, A, dfreq = None, freq = 40, zero_base = False):
    if dfreq is None:
        dfreq = freq / 2
        
    w, h = sps.freqz(B, A, whole=True, worN=4096)
    w = np.arange(0, freq, freq / len(h))
    
    keep = int((dfreq / freq) * len(h))
        
    return plotfilter_wh(w[1:keep], h[1:keep], freq, zero_base)

from scipy import interpolate

# This uses numpy's interpolator, which works well enough
def scale_old(buf, begin, end, tgtlen):
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
    
@njit(nogil=True)
def scale(buf, begin, end, tgtlen, mult = 1):
    linelen = end - begin
    sfactor = linelen/tgtlen

    output = np.zeros(tgtlen, dtype=buf.dtype)
    
    for i in range(0, tgtlen):
        coord = (i * sfactor) + begin
        start = int(coord) - 1
        p = buf[start:start+4]
        x = coord - int(coord)
        
        output[i] = mult * (p[1] + 0.5 * x*(p[2] - p[0] + x*(2.0*p[0] - 5.0*p[1] + 4.0*p[2] - p[3] + x*(3.0*(p[1] - p[2]) + p[3] - p[0]))))

    return output

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

frequency_suffixes = [
    ("ghz", 1.0e9),
    ("mhz", 1.0e6),
    ("khz", 1.0e3),
    ("hz", 1.0),
    ("fsc", 315.0e6 / 88.0),
    ("fscpal", (283.75 * 15625) + 25),
]

def parse_frequency(string):
    """Parse an argument string, returning a float frequency in MHz."""
    multiplier = 1.0e6
    for suffix, mult in frequency_suffixes:
        if string.lower().endswith(suffix):
            multiplier = mult
            string = string[:-len(suffix)]
            break
    return (multiplier * float(string)) / 1.0e6

'''

For this part of the loader phase I found myself going to function objects that implement this sample API:

```
infile: standard readable/seekable python binary file
sample: starting sample #
readlen: # of samples
```
Returns data if successful, or None or an upstream exception if not (including if not enough data is available)
'''

def make_loader(filename, inputfreq=None):
    """Return an appropriate loader function object for filename.

    If inputfreq is specified, it gives the sample rate in MHz of the source
    file, and the loader will resample from that rate to 40 MHz. Any sample
    rate specified by the source file's metadata will be ignored, as some
    formats can't represent typical RF sample rates accurately."""

    if inputfreq is not None:
        # We're resampling, so we have to use ffmpeg.

        if filename.endswith('.r16'):
            input_args = ['-f', 's16le']
        elif filename.endswith('.r8'):
            input_args = ['-f', 'u8']
        elif filename.endswith('.lds') or filename.endswith('.r30'):
            raise ValueError('File format not supported when resampling: ' + filename)
        else:
            # Assume ffmpeg will recognise this format itself.
            input_args = []

        # Use asetrate first to override the input file's sample rate.
        output_args = ['-filter:a', 'asetrate=' + str(inputfreq * 1e6) + ',aresample=' + str(40e6)]

        return LoadFFmpeg(input_args=input_args, output_args=output_args)

    elif filename.endswith('.lds'):
        return load_packed_data_4_40
    elif filename.endswith('.r30'):
        return load_packed_data_3_32
    elif filename.endswith('.r16'):
        return load_unpacked_data_s16
    elif filename.endswith('.r8'):
        return load_unpacked_data_u8
    elif filename.endswith('raw.oga') or filename.endswith('.ldf'):
        try:
            rv = LoadLDF(filename)
        except:
            #print("Please build and install ld-ldf-reader in your PATH for improved performance", file=sys.stderr)
            rv = LoadFFmpeg()

        return rv
    else:
        return load_packed_data_4_40

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


class LoadFFmpeg:
    """Load samples from a wide variety of formats using ffmpeg."""

    def __init__(self, input_args=[], output_args=[]):
        self.input_args = input_args
        self.output_args = output_args

        # ffmpeg subprocess
        self.ffmpeg = None

        # The number of the next byte ffmpeg will return
        self.position = 0

        # Keep a buffer of recently-read data, to allow seeking backwards by
        # small amounts. The last byte returned by ffmpeg is at the end of
        # this buffer.
        self.rewind_size = 2 * 1024 * 1024
        self.rewind_buf = b''

    def __del__(self):
        if self.ffmpeg is not None:
            self.ffmpeg.kill()
            self.ffmpeg.wait()

    def _read_data(self, count):
        """Read data as bytes from ffmpeg, append it to the rewind buffer, and
        return it. May return less than count bytes if EOF is reached."""

        data = self.ffmpeg.stdout.read(count)
        self.position += len(data)

        self.rewind_buf += data
        self.rewind_buf = self.rewind_buf[-self.rewind_size:]

        return data

    def __call__(self, infile, sample, readlen):
        sample_bytes = sample * 2
        readlen_bytes = readlen * 2

        if self.ffmpeg is None:
            command = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
            command += self.input_args
            command += ["-i", "-"]
            command += self.output_args
            command += ["-c:a", "pcm_s16le", "-f", "s16le", "-"]
            self.ffmpeg = subprocess.Popen(command, stdin=infile,
                                           stdout=subprocess.PIPE)

        if sample_bytes < self.position:
            # Seeking backwards - use data from rewind_buf
            start = len(self.rewind_buf) - (self.position - sample_bytes)
            end = min(start + readlen_bytes, len(self.rewind_buf))
            if start < 0:
                raise IOError("Seeking too far backwards with ffmpeg")
            buf_data = self.rewind_buf[start:end]
            sample_bytes += len(buf_data)
            readlen_bytes -= len(buf_data)
        else:
            buf_data = b''

        while sample_bytes > self.position:
            # Seeking forwards - read and discard samples
            count = min(sample_bytes - self.position, self.rewind_size)
            self._read_data(count)

        if readlen_bytes > 0:
            # Read some new data from ffmpeg
            read_data = self._read_data(readlen_bytes)
            if len(read_data) < readlen_bytes:
                # Short read - end of file
                return None
        else:
            read_data = b''

        data = buf_data + read_data
        assert len(data) == readlen * 2
        return np.fromstring(data, '<i2')

class LoadLDF:
    """Load samples from a wide variety of formats using ffmpeg."""

    def __init__(self, filename, input_args=[], output_args=[]):
        self.input_args = input_args
        self.output_args = output_args

        self.filename = filename

        # The number of the next byte ld-ldf-reader will return

        self.position = 0
        # Keep a buffer of recently-read data, to allow seeking backwards by
        # small amounts. The last byte returned by ffmpeg is at the end of
        # this buffer.
        self.rewind_size = 2 * 1024 * 1024
        self.rewind_buf = b''

        self.ldfreader = None

        # ld-ldf-reader subprocess
        self.ldfreader = self._open(0)

    def __del__(self):
        self._close()

    def _read_data(self, count):
        """Read data as bytes from ffmpeg, append it to the rewind buffer, and
        return it. May return less than count bytes if EOF is reached."""

        data = self.ldfreader.stdout.read(count)
        self.position += len(data)

        self.rewind_buf += data
        self.rewind_buf = self.rewind_buf[-self.rewind_size:]

        return data

    def _close(self):
        if self.ldfreader is not None:
            self.ldfreader.kill()
            self.ldfreader.wait()

        self.ldfreader = None

    def _open(self, sample):
        self._close()

        command = ["ld-ldf-reader", self.filename, str(sample)]

        ldfreader = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.position = sample * 2
        self.rewind_buf = b''

        return ldfreader

    def __call__(self, infile, sample, readlen):
        sample_bytes = sample * 2
        readlen_bytes = readlen * 2

        if self.ldfreader is None or ((sample_bytes - self.position) > 40000000):
            self.ldfreader = self._open(sample)

        if (sample_bytes < self.position):
            # Seeking backwards - use data from rewind_buf
            start = len(self.rewind_buf) - (self.position - sample_bytes)
            end = min(start + readlen_bytes, len(self.rewind_buf))
            if start < 0:
                #raise IOError("Seeking too far backwards with ffmpeg")
                self.ldfreader = self._open(sample)
                buf_data = b''
            else:
                buf_data = self.rewind_buf[start:end]
                sample_bytes += len(buf_data)
                readlen_bytes -= len(buf_data)
        elif ((sample_bytes - self.position) > (40*1024*1024*2)):
            self.ldfreader = self._open(sample)
            buf_data = b''
        else:
            buf_data = b''

        while sample_bytes > self.position:
            # Seeking forwards - read and discard samples
            count = min(sample_bytes - self.position, self.rewind_size)
            self._read_data(count)

        if readlen_bytes > 0:
            # Read some new data from ffmpeg
            read_data = self._read_data(readlen_bytes)
            if len(read_data) < readlen_bytes:
                # Short read - end of file
                return None
        else:
            read_data = b''

        data = buf_data + read_data
        assert len(data) == readlen * 2
        return np.fromstring(data, '<i2')


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

@njit
def inrange(a, mi, ma):
    return (a >= mi) & (a <= ma)

def sqsum(cmplx):
    return np.sqrt((cmplx.real ** 2) + (cmplx.imag ** 2))

@njit
def calczc_findfirst(data, target, rising):
    if rising:
        for i in range(0, len(data)):
            if data[i] >= target:
                return i

        return None
    else:
        for i in range(0, len(data)):
            if data[i] <= target:
                return i

        return None

@njit
def calczc_do(data, _start_offset, target, edge=0, _count=10):
    start_offset = max(1, int(_start_offset))
    count = int(_count + 1)
    
    if edge == 0: # capture rising or falling edge
        if data[start_offset] < target:
            edge = 1
        else:
            edge = -1

    loc = calczc_findfirst(data[start_offset:start_offset+count], target, edge==1)
               
    if loc is None:
        return None

    x = start_offset + loc
    a = data[x - 1] - target
    b = data[x] - target
    
    y = -a / (-a + b)

    return x-1+y

def calczc(data, _start_offset, target, edge=0, _count=10, reverse=False):
    ''' edge:  -1 falling, 0 either, 1 rising '''
    if reverse:
        # Instead of actually implementing this in reverse, use numpy to flip data
        rev_zc = calczc_do(data[_start_offset::-1], 0, target, edge, _count)
        if rev_zc is None:
            return None

        return _start_offset - rev_zc

    return calczc_do(data, _start_offset, target, edge, _count)

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
@njit
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
@jit
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

def findpulses(array, low, high):
    ''' Find areas where `array` is between `low` and `high`
    
    returns: array of tuples of said areas (begin, end, length)
    '''
    
    Pulse = namedtuple('Pulse', 'start len')
    
    array_inrange = inrange(array, low, high)
    
    starts = np.where(np.logical_and(array_inrange[1:] == True, array_inrange[:-1] == False))[0]
    ends = np.where(np.logical_and(array_inrange[1:] == False, array_inrange[:-1] == True))[0]

    if len(starts) == 0 or len(ends) == 0:
        return []

    # remove 'dangling' beginnings and endings so everything zips up nicely and in order
    if ends[0] < starts[0]:
        ends = ends[1:]

    if starts[-1] > ends[-1]:
        starts = starts[:-1]

    return [Pulse(z[0], z[1] - z[0]) for z in zip(starts, ends)]

def findpeaks(array, low = None):
    if min is not None:
        array2 = array.copy()
        array2[np.where(array2 < low)] = 0
    else:
        array2 = array
    
    return [loc - 1 for loc in np.where(np.logical_and(array2[:-1] > array2[-1], array2[1:] > array2[:-1]))[0]]

def LRUupdate(l, k):
    ''' This turns a list into an LRU table.  When called it makes sure item 'k' is at the beginning,
        so the list is in descending order of previous use.
    '''
    try:
        l.remove(k)
    except:
        pass

    l.insert(0, k)

@njit
def nb_median(m):
    return np.median(m)

@njit
def nb_mean(m):
    return np.mean(m)

@njit
def nb_min(m):
    return np.min(m)

@njit
def nb_max(m):
    return np.max(m)

@njit
def nb_mul(x, y):
    return x * y

@njit
def nb_where(x):
    return np.where(x)

if __name__ == "__main__":
    print("Nothing to see here, move along ;)")
