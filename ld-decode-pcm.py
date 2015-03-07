#!/usr/bin/python
import numpy as np
import scipy.signal as sps
import sys

#
# Sample usage:
# cat ../raw_samples/ld_dig_audio.raw | ./ld-decode-pcm.py > raw-efm.raw
#
# Outputs what it decodes to stderr, and it's post processed output to stdout
#

FREQ_MHZ = (315.0 / 88.0) * 8.0
FREQ_HZ = FREQ_MHZ * 1000000.0
NYQUIST_MHZ = FREQ_MHZ / 2

EFM_CLOCK_FREQ_MHZ = 4.3218
EFM_CLOCK_FREQ_HZ = EFM_CLOCK_FREQ_MHZ * 1e6
EFM_PIXEL_RATE = FREQ_MHZ / EFM_CLOCK_FREQ_MHZ

SAMPLES = 2000000  # Number of samples to decode


def printerr(txt):
    """ Avoid clogging up the stdout with logging """
    sys.stderr.write(str(txt) + '\n')


def coroutine(func):
    """ Decorate a coroutine do deal with the ugly first yield/send problem """

    def start(*args, **kwargs):
        cr = func(*args, **kwargs)
        cr.next()
        return cr

    return start


@coroutine
def biquad_filter(a1, a2, b0, b1, b2):
    """ Biquadratic IIR filter (Direct form I)
        This is a co-routine, and uses yield and send to deliver and receive samples.
        Be warned some calculators transpose a and b params (we use (b)efore and (a)fter
    """
    x1, x2, y1, y2, y = 0.0, 0.0, 0.0, 0.0, 0.0
    while 1:
        x = (yield int(y))  # Sent by send
        y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2 = x1
        x1 = x
        y2 = y1
        y1 = y  # Shuffle samples along


def edge_pll(data, expected_rate):
    """ Ultra-naive Phase locked loop, looking for zero crossings at the expected rate (i.e. once every N samples),
        adjust a bit when we find one before that. """
    state = 0
    next_sample = 0
    val = 0
    for i, sample in enumerate(data):
        if (sample > 0 and not state ) or ( sample <= 0 and state ):
            state = sample > 0
            val = 1
            if next_sample - i > 1:
                next_sample = next_sample - 1  # phase locking a bit.
        if i == next_sample:
            yield int(val)
            val = 0
            next_sample = int(i + expected_rate)


def run_filter(ffilter, data):
    """ Run the passed coroutine filter over the data - returning a generator """
    for point in data:
        yield ffilter.send(point)


def run_until_start_code(bit_gen):
    """ Consume bits from a bit generator until we see a frame start code """
    cnt = 0
    flag = 0  # Need two start codes in a row
    while 1:
        bit = bit_gen.next()
        if not bit:
            cnt += 1
            if cnt == 11:
                if bit_gen.next():
                    if flag:
                        bit_gen.next()  # One more zero (we hope)
                        printerr('Found start code !')
                        return
                    flag = 1
                else:
                    flag = 0
                cnt = 0
        else:
            flag = 0
            cnt = 0


def eat_three_bits(bit_gen):
    """ Eat the three DC correction bits """
    bit_gen.next()
    bit_gen.next()
    bit_gen.next()


def process_efm_frame(bit_gen, num_words=31):
    """ Process an EFM frame from the passed bit generator, reading the passed number of words """
    buff = []
    buffer_append = buff.append
    i = 0
    while i <= num_words:
        buffer_append(bit_gen.next())
        if len(buff) == 14:
            printerr(buff)
            buff[:] = []  # Oh for list.clear in Python 2
            eat_three_bits(bit_gen)
            i += 1
    printerr('consumed frame')


def auto_gain(data, peak, logline=None):
    """ Automatically apply gain to the passed nparray, with the aim of adjusting peak amplitude to passed peak """
    gain = float(peak) / max(max(data), abs(min(data)))
    if logline:
        printerr('auto_gain %s: %.2f' % (logline, gain ))
    return data * gain


def decode_efm():
    """ Decode EFM from STDIN, assuming it's a 28Mhz 8bit raw stream  """
    datao = np.fromstring(sys.stdin.read(SAMPLES), dtype=np.uint8).astype(np.int16)
    datao = sps.detrend(datao, type='constant')  # Remove DC

    datao = auto_gain(datao, 10000, 'pre-filter')  # Expand before filtering, since we'll lose much of signal otherwise

    low_pass = sps.butter(4, 1.75 / FREQ_MHZ, btype='lowpass')  # Low pass at 1.75 Mhz
    datao = sps.lfilter(low_pass[0], low_pass[1], datao)

    high_pass = sps.butter(4, 0.01333 / FREQ_MHZ, btype='highpass')  # High pass at 13.333 khz
    datao = sps.lfilter(high_pass[0], high_pass[1], datao)

    # This is too slow, need to work out a way to do it in scipy
    de_emphasis_filter = biquad_filter(-1.8617006585639506, 0.8706642683920058, 0.947680874725466, -1.8659578411373265, 0.9187262110931641)
    datao = np.fromiter(run_filter(de_emphasis_filter, datao), np.int16)  # De-emph - 26db below 500khz

    # Could tie edge_pll and run_filter together as generators, but we want to see the filter output

    bit_gen = edge_pll(datao, EFM_PIXEL_RATE)  # This is a ultra-naive PLL that returns a bit-stream of 1 = edge, 0 = no-edge
    try:
        while 1:
            run_until_start_code(bit_gen)
            eat_three_bits(bit_gen)
            process_efm_frame(bit_gen, 31)  # 31 14 bit EFM codes in a frame
    except StopIteration:
        printerr('Hit the end of the bitstream')

    datao = np.clip(datao, 0, 255).astype(np.uint8)
    sys.stdout.write(datao.tostring())


if __name__ == "__main__":
    decode_efm()