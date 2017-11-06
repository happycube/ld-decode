#!python

# this version is based off 11/05 PAL version, changed for 32mhz/16bit signed samples

import numpy as np
import scipy as sp
import scipy.signal as sps
import scipy.fftpack as fftpack 
import sys

import fdls as fdls
import matplotlib.pyplot as plt
import fft8 as fft8 

import getopt

π = np.pi
τ = np.pi * 2

#import ipdb

#freq = (315.0 / 88.0) * 8.0
freq = 32
freq_hz = freq * 1000000.0

blocklen = (16 * 1024) + 512
hilbertlen = (16 * 1024)

wide_mode = 0

def dosplot(B, A):
        w, h = sps.freqz(B, A)

        fig = plt.figure()
        plt.title('Digital filter frequency response')

        ax1 = fig.add_subplot(111)

        db = 20 * np.log10(abs(h))

        for i in range(1, len(w)):
                if (db[i] >= -10) and (db[i - 1] < -10):
                        print(">-10db crossing at ", w[i] * (freq/π) / 2.0) 
                if (db[i] >= -3) and (db[i - 1] < -3):
                        print("-3db crossing at ", w[i] * (freq/π) / 2.0) 
                if (db[i] < -3) and (db[i - 1] >= -3):
                        print("<-3db crossing at ", w[i] * (freq/π) / 2.0) 
                if (db[i] < -10) and (db[i - 1] >= -10):
                        print("<-10db crossing at ", w[i] * (freq/π) / 2.0) 
                if (db[i] < -20) and (db[i - 1] >= -20):
                        print("<-20db crossing at ", w[i] * (freq/π) / 2.0) 

        plt.plot(w * (freq/π) / 2.0, 20 * np.log10(abs(h)), 'b')
        plt.ylabel('Amplitude [dB]', color='b')
        plt.xlabel('Frequency [rad/sample]')

        plt.show()

def doplot(B, A):
        w, h = sps.freqz(B, A)

        fig = plt.figure()
        plt.title('Digital filter frequency response')
        
        db = 20 * np.log10(abs(h))
        for i in range(1, len(w)):
                if (db[i] >= -10) and (db[i - 1] < -10):
                        print(">-10db crossing at ", w[i] * (freq/π) / 2.0) 
                if (db[i] >= -3) and (db[i - 1] < -3):
                        print(">-3db crossing at ", w[i] * (freq/π) / 2.0) 
                if (db[i] < -3) and (db[i - 1] >= -3):
                        print("<-3db crossing at ", w[i] * (freq/π) / 2.0) 

        ax1 = fig.add_subplot(111)
        
        plt.plot(w * (freq/π) / 2.0, 20 * np.log10(abs(h)), 'b')
        plt.ylabel('Amplitude [dB]', color='b')
        plt.xlabel('Frequency [rad/sample]')

        ax2 = ax1.twinx()
        angles = np.unwrap(np.angle(h))
        plt.plot(w * (freq/π) / 2.0, angles, 'g')
        plt.ylabel('Angle (radians)', color='g')
        
        plt.grid()
        plt.axis('tight')
        plt.show()

def doplot2(B, A, B2, A2):
        w, h = sps.freqz(B, A)
        w2, h2 = sps.freqz(B2, A2)

#       h.real /= C
#       h2.real /= C2

        begin = 0
        end = len(w)
#       end = int(len(w) * (12 / freq))

#       chop = len(w) / 20
        chop = 0
        w = w[begin:end]
        w2 = w2[begin:end]
        h = h[begin:end]
        h2 = h2[begin:end]

        v = np.empty(len(w))
        
#       print len(w)

        hm = np.absolute(h)
        hm2 = np.absolute(h2)

        v0 = hm[0] / hm2[0]
        for i in range(0, len(w)):
                v[i] = (hm[i] / hm2[i]) / v0

        fig = plt.figure()
        plt.title('Digital filter frequency response')

        ax1 = fig.add_subplot(111)

        v  = 20 * np.log10(v )

        plt.plot(w * (freq/π) / 2.0, 20 * np.log10(abs(h)), 'r')
        plt.plot(w * (freq/π) / 2.0, 20 * np.log10(abs(h2)), 'b')
        plt.ylabel('Amplitude [dB]', color='b')
        plt.xlabel('Frequency [rad/sample]')
        
        ax2 = ax1.twinx()
        angles = np.unwrap(np.angle(h))
        angles2 = np.unwrap(np.angle(h2))
        plt.plot(w * (freq/π) / 2.0, angles, 'g')
        plt.plot(w * (freq/π) / 2.0, angles2, 'y')
        plt.ylabel('Angle (radians)', color='g')

        plt.grid()
        plt.axis('tight')
        plt.show()

ffreq = freq/2.0

Bboost, Aboost = sps.butter(1, (2.0/(freq/2)), 'high')

lowpass_filter_b, lowpass_filter_a = sps.butter(8, (5.5/(freq/2)), 'low')

# demphasis coefficients.

deemp_t1 = .75
deemp_t2 = 4.0

deemp_t1 = .5 
deemp_t2 = 4.5

# set up deemp filter
[tf_b, tf_a] = sps.zpk2tf(-deemp_t2*(10**-8), -deemp_t1*(10**-8), deemp_t1 / deemp_t2)
[f_deemp_b, f_deemp_a] = sps.bilinear(tf_b, tf_a, 1/(freq_hz/2))

# XXX
if True:
    Bboost, Aboost = sps.butter(1, [(2.0/(freq/2)), (13.5/(freq/2))], 'bandpass')

    deemp_t1 = .5
    deemp_t2 = 4.5

    # set up deemp filter
    [tf_b, tf_a] = sps.zpk2tf(-deemp_t2*(10**-8), -deemp_t1*(10**-8), deemp_t1 / deemp_t2)
    [f_deemp_b, f_deemp_a] = sps.bilinear(tf_b, tf_a, 1/(freq_hz/2))

    lowpass_filter_b, lowpass_filter_a = sps.butter(5, (5.0/(freq/2)), 'low')
# XXX

# audio filters
Baudiorf = sps.firwin(65, 3.5 / (freq / 2), window='hamming', pass_zero=True)

afreq = freq / 4

left_audfreq = 2.301136
right_audfreq = 2.812499

hfreq = freq / 8.0

N, Wn = sps.buttord([(left_audfreq-.10) / hfreq, (left_audfreq+.10) / hfreq], [(left_audfreq-.15) / hfreq, (left_audfreq+.15)/hfreq], 1, 15)
leftbp_filter_b, leftbp_filter_a = sps.butter(N, Wn, btype='bandpass')

N, Wn = sps.buttord([(right_audfreq-.10) / hfreq, (right_audfreq+.10) / hfreq], [(right_audfreq-.15) / hfreq, (right_audfreq+.15)/hfreq], 1, 15)
rightbp_filter_b, rightbp_filter_a = sps.butter(N, Wn, btype='bandpass')

N, Wn = sps.buttord(0.016 / hfreq, 0.024 / hfreq, 1, 8) 
audiolp_filter_b, audiolp_filter_a = sps.butter(N, Wn)

N, Wn = sps.buttord(3.1 / (freq / 2.0), 3.5 / (freq / 2.0), 1, 16) 
audiorf_filter_b, audiorf_filter_a = sps.butter(N, Wn)

# from http://tlfabian.blogspot.com/2013/01/implementing-hilbert-90-degree-shift.html
hilbert_filter = np.fft.fftshift(
    np.fft.ifft([0]+[1]*20+[0]*20)
)

def fm_decode(in_filt, freq_hz, hlen = hilbertlen):
        hilbert = sps.hilbert(in_filt[0:hlen])

        # the hilbert transform has errors at the edges.  but it doesn't seem to matter much IRL
        chop = 256 
        hilbert = hilbert[chop:len(hilbert)-chop]

        tangles = np.angle(hilbert) 

        dangles = np.diff(tangles)

        # make sure unwapping goes the right way
        if (dangles[0] < -π):
                dangles[0] += τ
        
        tdangles2 = np.unwrap(dangles) 
        
        output = (tdangles2 * (freq_hz / τ))

        errcount = 1
        while errcount > 0:
                errcount = 0

                # particularly bad bits can cause phase inversions.  detect and fix when needed - the loops are slow in python.
                if (output[np.argmax(output)] > freq_hz):
                        errcount = 1
                        for i in range(0, len(output)):
                                if output[i] > freq_hz:
                                        output[i] = output[i] - freq_hz
        
                if (output[np.argmin(output)] < 0):
                        errcount = 1
                        for i in range(0, len(output)):
                                if output[i] < 0:
                                        output[i] = output[i] + freq_hz

        return output

minire = -95
maxire = 145

hz_ire_scale = (8000000 - 7100000) / 100
minn = 7100000 + (hz_ire_scale * minire)

out_scale = 65534.0 / (maxire - minire)
        
#doplot(Bcutl, Acutl)

Inner = 0

def process_video(data):
        # perform general bandpass filtering

        in_filt = sps.lfilter(Bboost, Aboost, data)

        output = fm_decode(in_filt, freq_hz)

        # save the original fm decoding and align to filters
        output_prefilt = output[(len(f_deemp_b) * 24) + len(f_deemp_b) + len(lowpass_filter_b):]

        # clip impossible values (i.e. rot)
#       output = np.clip(output, 7100000, 10800000) 

        output = sps.lfilter(lowpass_filter_b, lowpass_filter_a, output)
        doutput = (sps.lfilter(f_deemp_b, f_deemp_a, output)[len(f_deemp_b) * 32:len(output)]) # / deemp_corr

        output_16 = np.empty(len(doutput), dtype=np.uint16)
        reduced = (doutput - minn) / hz_ire_scale
        output = np.clip(reduced * out_scale, 0, 65535) 
        
        np.copyto(output_16, output, 'unsafe')

        err = 1
        while False: # err > 0:
                err = 0
        
                am = np.argmax(output_prefilt)  
                if (output_prefilt[np.argmax(output_prefilt)] > 11200000):
                        err = 1
                        output_prefilt[am] = 11200000
                        if (am < len(output_16)):
                                output_16[am] = 0
                
                am = np.argmin(output_prefilt)  
                if (output_prefilt[np.argmax(output_prefilt)] < 3000000):
                        err = 1
                        output_prefilt[am] = 3000000
                        if (am < len(output_16)):
                                output_16[am] = 0

        return output_16

        plt.plot(range(0, len(output_16)), output_16)
        plt.show()
        exit()

left_audfreqm = left_audfreq * 1000000
right_audfreqm = right_audfreq * 1000000

test_mode = 0

def process_audio(indata):
        global test_mode

        if test_mode > 0:
                outputf = np.empty(32768 * 2, dtype = np.float32)
                for i in range(0, 32768):
                        outputf[i * 2] = np.cos((i + test_mode) / (freq_hz / 4.0 / 10000)) 
                        outputf[(i * 2) + 1] = np.cos((i + test_mode) / (freq_hz / 4.0 / 10000)) 

                outputf *= 50000
        
                test_mode += 32768 
                return outputf, 32768 

        in_filt = sps.lfilter(audiorf_filter_b, audiorf_filter_a, indata)[len(audiorf_filter_b) * 2:]
        in_filt4 = np.empty(int(len(in_filt) / 4) + 1)

        for i in range(0, len(in_filt), 4):
                in_filt4[int(i / 4)] = in_filt[i]

        in_left = sps.lfilter(leftbp_filter_b, leftbp_filter_a, in_filt4)[len(leftbp_filter_b) * 1:] 
        in_right = sps.lfilter(rightbp_filter_b, rightbp_filter_a, in_filt4)[len(rightbp_filter_b) * 1:] 

        out_left = fm_decode(in_left, freq_hz / 4)
        out_right = fm_decode(in_right, freq_hz / 4)

        out_left = np.clip(out_left - left_audfreqm, -150000, 150000) 
        out_right = np.clip(out_right - right_audfreqm, -150000, 150000) 

        out_left = sps.lfilter(audiolp_filter_b, audiolp_filter_a, out_left)[800:]
        out_right = sps.lfilter(audiolp_filter_b, audiolp_filter_a, out_right)[800:] 

        outputf = np.empty((len(out_left) * 2.0 / 20.0) + 2, dtype = np.float32)

        tot = 0
        for i in range(0, len(out_left), 20):
                outputf[tot * 2] = out_left[i]
                outputf[(tot * 2) + 1] = out_right[i]
                tot = tot + 1

        return outputf[0:tot * 2], tot * 20 * 4 

        plt.plot(range(0, len(out_left)), out_left)
        plt.plot(range(0, len(out_right)), out_right + 150000)
        plt.show()
        exit()

def test():
        test = np.empty(blocklen, dtype=np.uint8)

        global hilbert_filter

        for vlevel in range(20, 100, 10):
                vphase = 0
                alphase = 0
                arphase = 0

                for i in range(0, len(test)):
                        if i > len(test) / 2:
                                vfreq = 9300000
                        else:
                                vfreq = 8100000

                        vphase += vfreq / freq_hz 
                        alphase += 2300000 / freq_hz 
                        arphase += 2800000 / freq_hz 
                        test[i] = (np.sin(vphase * τ) * vlevel)
                        test[i] += (np.sin(alphase * τ) * vlevel / 10.0)
                        test[i] += (np.sin(arphase * τ) * vlevel / 10.0)
                        test[i] += 128

                output = process_video(test)[7800:8500] 
                plt.plot(range(0, len(output)), output)

                output = output[400:700]        
                mean = np.mean(output)
                std = np.std(output)
                print(vlevel, mean, std, 20 * np.log10(mean / std)) 

        plt.show()
        exit()

def main():
        global lowpass_filter_b, lowpass_filter_a 
        global wide_mode, hz_ire_scale, minn
        global f_deemp_b, f_deemp_a

        global Bcutr, Acutr
        
        global Inner 

        global blocklen

#       test()

        outfile = sys.stdout.buffer
        audio_mode = 0 
        CAV = 0

        byte_start = 0
        byte_end = 0

        f_seconds = False 

        optlist, cut_argv = getopt.getopt(sys.argv[1:], "hLCaAwSs:")

        for o, a in optlist:
                if o == "-a":
                        audio_mode = 1  
                        blocklen = (64 * 1024) + 2048 
                        hilbertlen = (16 * 1024)
                if o == "-L":
                        Inner = 1
                if o == "-A":
                        CAV = 1
                        Inner = 1
                if o == "-C":
                        Bcutr, Acutr = sps.butter(1, [2.68/(freq/2), 3.08/(freq/2)], btype='bandstop')
                if o == "-w":
                        lowpass_filter_b, lowpass_filter_a = sps.butter(7, (4.7/(freq/2)), 'low')
                        wide_mode = 1
                        hz_ire_scale = (9360000 - 8100000) / 100
                        minn = 8100000 + (hz_ire_scale * -60)
                if o == "-S":
                        f_seconds = True
                if o == "-s":
                        ia = int(a)
                        if ia == 0:
                                lowpass_filter_b, lowpass_filter_a = sps.butter(8, (5.2/(freq/2)), 'low')
                        if ia == 1:     
                                lowpass_filter_b, lowpass_filter_a = sps.butter(8, (5.5/(freq/2)), 'low')
                        if ia == 2:     
                                lowpass_filter_b, lowpass_filter_a = sps.butter(8, (5.8/(freq/2)), 'low')
                        if ia == 3:     
                                lowpass_filter_b, lowpass_filter_a = sps.butter(8, (6.1/(freq/2)), 'low')


        argc = len(cut_argv)
        if argc >= 1:
                infile = open(cut_argv[0], "rb")
        else:
                infile = sys.stdin

        byte_start = 0
        if (argc >= 2):
                byte_start = float(cut_argv[1])

        if (argc >= 3):
                byte_end = float(cut_argv[2])
                limit = 1
        else:
                limit = 0

        if f_seconds:
                byte_start *= freq_hz 
                byte_end *= freq_hz 
        else:
                # for backwards compat (for now)
                byte_end += byte_start

        byte_end -= byte_start

        byte_start = int(byte_start)
        byte_end = int(byte_end)

        if (byte_start > 0):    
                infile.seek(byte_start)
        
        if CAV and byte_start > 11454654400:
                CAV = 0
                Inner = 0 
        
        total = toread = blocklen 
        inbuf = infile.read(toread * 2)
        indata = np.fromstring(inbuf, 'int16', toread) + 32768
        
        total = 0
        total_prevread = 0
        total_read = 0

        while (len(inbuf) > 0):
                toread = blocklen - indata.size 

                if toread > 0:
                        inbuf = infile.read(toread * 2)
                        newdata = np.fromstring(inbuf, 'int16', len(inbuf) // 2) + 32768
                        indata = np.append(indata, newdata)

                        if indata.size < blocklen:
                                exit()

                if audio_mode:  
                        output, osamp = process_audio(indata)
#                       for i in range(0, osamp):
#                               print i, output[i * 2], output[(i * 2) + 1]
                        
                        nread = osamp 

#                       print len(output), nread

                        outfile.write(output)
                else:
                        output_16 = process_video(indata)
#                       output_16.tofile(outfile)
                        outfile.write(output_16)
                        nread = len(output_16)
                        
#                       print(len(output_16), nread)

                        total_pread = total_read 
                        total_read += nread

                        if CAV:
                                if (total_read + byte_start) > 11454654400:
                                        CAV = 0
                                        Inner = 0

                indata = indata[nread:len(indata)]

                if limit == 1:
                        byte_end -= toread 
                        if (byte_end < 0):
                                inbuf = ""

if __name__ == "__main__":
    main()


