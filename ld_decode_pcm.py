#!/usr/bin/python
import numpy as np
import scipy.signal as sps
import sys

#
# Sample usage:
# cat ../raw_samples/ld_dig_audio.raw | ./ld_decode_pcm.py > raw-efm.raw
#
# Outputs what it decodes to stderr, and it's post processed output to stdout
#


# Notes
# Q-subcode decoding: http://bani.anime.net/iec958/q_subcode/project.htm
# Overview of frame scrambling: http://www.jmargolin.com/project/cdtermw.pdf

FREQ_MHZ = (315.0 / 88.0) * 8.0
FREQ_HZ = FREQ_MHZ * 1000000.0
NYQUIST_MHZ = FREQ_MHZ / 2

EFM_CLOCK_FREQ_MHZ = 4.3218
EFM_CLOCK_FREQ_HZ = EFM_CLOCK_FREQ_MHZ * 1e6
EFM_PIXEL_RATE = FREQ_MHZ / EFM_CLOCK_FREQ_MHZ

SAMPLES = 2000000  # Number of samples to decode

EFM_FRAME_LENGTH = 2352

# Via Chad - EFM bit pattern -> 8 bit integer
EFM_LOOKUP_RAW =\
"""01001000100000
10000100000000
10010000100000
10001000100000
01000100000000
00000100010000
00010000100000
00100100000000
01001001000000
10000001000000
10010001000000
10001001000000
01000001000000
00000001000000
00010001000000
00100001000000
10000000100000
10000010000000
10010010000000
00100000100000
01000010000000
00000010000000
00010010000000
00100010000000
01001000010000
10000000010000
10010000010000
10001000010000
01000000010000
00001000010000
00010000010000
00100000010000
00000000100000
10000100001000
00001000100000
00100100100000
01000100001000
00000100001000
01000000100000
00100100001000
01001001001000
10000001001000
10010001001000
10001001001000
01000001001000
00000001001000
00010001001000
00100001001000
00000100000000
10000010001000
10010010001000
10000100010000
01000010001000
00000010001000
00010010001000
00100010001000
01001000001000
10000000001000
10010000001000
10001000001000
01000000001000
00001000001000
00010000001000
00100000001000
01001000100100
10000100100100
10010000100100
10001000100100
01000100100100
00000000100100
00010000100100
00100100100100
01001001000100
10000001000100
10010001000100
10001001000100
01000001000100
00000001000100
00010001000100
00100001000100
10000000100100
10000010000100
10010010000100
00100000100100
01000010000100
00000010000100
00010010000100
00100010000100
01001000000100
10000000000100
10010000000100
10001000000100
01000000000100
00001000000100
00010000000100
00100000000100
01001000100010
10000100100010
10010000100010
10001000100010
01000100100010
00000000100010
01000000100100
00100100100010
01001001000010
10000001000010
10010001000010
10001001000010
01000001000010
00000001000010
00010001000010
00100001000010
10000000100010
10000010000010
10010010000010
00100000100010
01000010000010
00000010000010
00010010000010
00100010000010
01001000000010
00001001001000
10010000000010
10001000000010
01000000000010
00001000000010
00010000000010
00100000000010
01001000100001
10000100100001
10010000100001
10001000100001
01000100100001
00000000100001
00010000100001
00100100100001
01001001000001
10000001000001
10010001000001
10001001000001
01000001000001
00000001000001
00010001000001
00100001000001
10000000100001
10000010000001
10010010000001
00100000100001
01000010000001
00000010000001
00010010000001
00100010000001
01001000000001
10000010010000
10010000000001
10001000000001
01000010010000
00001000000001
00010000000001
00100010010000
00001000100001
10000100001001
01000100010000
00000100100001
01000100001001
00000100001001
01000000100001
00100100001001
01001001001001
10000001001001
10010001001001
10001001001001
01000001001001
00000001001001
00010001001001
00100001001001
00000100100000
10000010001001
10010010001001
00100100010000
01000010001001
00000010001001
00010010001001
00100010001001
01001000001001
10000000001001
10010000001001
10001000001001
01000000001001
00001000001001
00010000001001
00100000001001
01000100100000
10000100010001
10010010010000
00001000100100
01000100010001
00000100010001
00010010010000
00100100010001
00001001000001
10000100000001
00001001000100
00001001000000
01000100000001
00000100000001
00000010010000
00100100000001
00000100100100
10000010010001
10010010010001
10000100100000
01000010010001
00000010010001
00010010010001
00100010010001
01001000010001
10000000010001
10010000010001
10001000010001
01000000010001
00001000010001
00010000010001
00100000010001
01000100000010
00000100000010
10000100010010
00100100000010
01000100010010
00000100010010
01000000100010
00100100010010
10000100000010
10000100000100
00001001001001
00001001000010
01000100000100
00000100000100
00010000100010
00100100000100
00000100100010
10000010010010
10010010010010
00001000100010
01000010010010
00000010010010
00010010010010
00100010010010
01001000010010
10000000010010
10010000010010
10001000010010
01000000010010
00001000010010
00010000010010
00100000010010"""


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
        Be warned some calculators transpose a and b params we use (b)efore and (a)fter
    """
    x1, x2, y1, y2, y = 0.0, 0.0, 0.0, 0.0, 0.0
    while 1:
        x = (yield int(y))  # Sent by send
        y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2 = x1
        x1 = x
        y2 = y1
        y1 = y  # Shuffle samples along


def efm_table(efm_str):
    mapp = {}
    for v, linstr in enumerate(efm_str.splitlines()):
        mapp[tuple([int(x) for x in linstr])] = v
    return mapp

EFM_MAP = efm_table(EFM_LOOKUP_RAW)


def printerr(txt):
    """ Avoid clogging up the stdout with logging """
    sys.stderr.write(str(txt) + '\n')


def descramble(bit_gen):
    """ Per ECMA-130. Data pattern scrambling to avoid regular bit patterns overflowing the DC correction bits """
    register = ( [0] * 14 ) + [1]
    # TODO
    inp_bit = bit_gen.next()
    lsb_reg = register.pop(15)  # Pop the lsb
    x = (inp_bit != lsb_reg)  # XOR
    register.insert(0, x)
    yield x


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
            if next_sample - i > 0:
                next_sample -= 1  # phase locking a bit.
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
                bit = bit_gen.next()
                if bit and flag:
                    bit = bit_gen.next()  # One more zero (we hope)
                    if not bit:
                        printerr('Found start code !')
                        return
                    else:
                        flag = 0
                elif bit:
                    flag = 1
                else:
                    flag = 0
                cnt = 0
        else:
            flag = 0
            cnt = 0


def consume_merging_bites(bit_gen):
    """ Eat the three DC correction bits
         should be 000, 010, 001 """
    bit_gen.next()
    bit_gen.next()
    bit_gen.next()


def consume_f1_frame(byte_gen):
    """ A 2352 byte 'scrambled' sector, consisting of 106 F2 frames
    :param byte_gen:
    :return:
    """
    # TODO - implement


def consume_f2_frame(byte_gen):
    """ A 32 byte frame consisting of 24 data bytes, and 8 parity bytes
    :param byte_gen:
    :return:
    """
    # TODO - implement


def consume_f3_frame(bit_gen):
    """ Process an EFM F3 frame from the passed bit generator
        This consists of a header, control byte (channel bits) and a payload of 31"""
    buff = []
    buffer_append = buff.append
    i = 0
    while i <= 31:
        buffer_append(bit_gen.next())
        if len(buff) == 14:
            try:
                decoded_byte = EFM_MAP[tuple(buff)]
                printerr('%s %s' % (buff, hex(decoded_byte)))
                yield decoded_byte
            except KeyError:
                printerr('%s BAD_CODE' % buff)
                yield 0  # TODO - find closest match in EFM table, and return that
            buff[:] = []  # list.clear
            consume_merging_bites(bit_gen)
            i += 1
    printerr('consumed frame')


def auto_gain(data, peak, logline=None):
    """ Automatically apply gain to the passed nparray, with the aim of adjusting peak amplitude to passed peak """
    gain = float(peak) / max(max(data), abs(min(data)))
    if logline:
        printerr('auto_gain %s: %.2f' % (logline, gain))
    return data * gain


def consume_digital_data_sector(bit_gen):
    """ Per ECMA-130 : http://www.ecma-international.org/publications/files/ECMA-ST/Ecma-130.pdf
          Digital data sector consists of
          2352 'bytes' This can be either of the following Sector Mode (00,01,02)

            All start with a SYNC consisting of 0x00, [0xFF] * 10, 0x00
            Sector address on lead-in area is MIN + 0xA3, SEC, FRAC (Q-channel content) since start of lead-in
            Sector address on data-area and lead-out area contain time since start of data-area (A-MIN,A-SEC,A-FRAC)
             also Q-Channel content
            Mode is indicative of the Sector mode
            EDC is a 32bit CRC applied on bytes 0 to 2036, least significant bit first. EDC codeword must be divisible
             by P(x) = x^16 + x^15 + x^2 ) * (x^16 + x^2 + x + 1)
             The least significant parity bit is stored in the most significant bit position of byte 2067

            Intermediate Field
            P-Parity Field
            Q-Parity Field


            Sector Mode 00 is
                12 bytes Sync
                3 bytes Sector Address
                1 bytes Mode
                2336 bytes Data

            Sector Mode 01 is
                12 bytes Sync
                3 bytes Sector Address
                1 bytes Mode
                2048 bytes User Data
                4 bytes EDC
                8 bytes Intermediate
                172 bytes P-Parity
                172 bytes Q-Parity

            Sector Mode 02 is
                12 bytes Sync
                3 bytes Sector Address
                2 bytes Mode (?)
                2336 bytes User Data
    """
    pass
    # TODO implement


def to_audio_sample(msb, lsb):
    """ Convert the passed two bytes into a 2's complement signed 16 bit integer """
    value = msb * 255 + lsb
    if value <= 32767:
        return value
    else:
        return value - 65536


def extract_audio_samples(dataframes):
    """ De-interleave audio samples from the fully decoded frames. """
    left_audio = []
    right_audio = []

    # TODO - entirely untested. Exercise against .bin file
    # Jump to frame 106 (count zero ), then look backwards for the data
    i = 105
    while i < len(dataframes):
        left_audio.extend([to_audio_sample(dataframes[i - 105][0], dataframes[i - 102][1]),
                           to_audio_sample(dataframes[i - 43][16], dataframes[i - 40][17]),
                           to_audio_sample(dataframes[i - 97][2], dataframes[i - 94][3]),
                           to_audio_sample(dataframes[i - 35][18], dataframes[i - 32][19]),
                           to_audio_sample(dataframes[i - 89][4], dataframes[i - 86][5]),
                           to_audio_sample(dataframes[i - 27][20], dataframes[i - 24][21])])

        right_audio.extend([to_audio_sample(dataframes[i - 81][6], dataframes[i - 78][7]),
                            to_audio_sample(dataframes[i - 19][22], dataframes[i - 16][23]),
                            to_audio_sample(dataframes[i - 73][8], dataframes[i - 70][9]),
                            to_audio_sample(dataframes[i - 11][24], dataframes[i - 8][25]),
                            to_audio_sample(dataframes[i - 65][10], dataframes[i - 62][11]),
                            to_audio_sample(dataframes[i - 3][26], dataframes[i - 0][27])])
        i += 1

    return left_audio, right_audio


def diff_bit_stream(bit_gen):
    i = 1
    try:
        prevsamp = bit_gen.next()
        while 1:
            samp = bit_gen.next()
            yield int(samp != prevsamp)
            i += 1
            prevsamp = samp
    except StopIteration:
        pass
    printerr('Diffed %d bits' % i)


def run_count_generator(raw_data, startat):
    i = startat
    s = startat
    runcount = 1
    samp = raw_data[i]
    runcount_dir = (samp > 0)
    while 1:
        samp = raw_data[i]
        if (samp >= 0 and runcount_dir) or (samp <= 0 and not runcount_dir):
            runcount += 1
        else:
            yield runcount, s
            s = i
            runcount = 1
            runcount_dir = ( samp > 0 )
        i += 1


def find_next_start_code(raw_data, startat, ):
    '''Find a run of pixels less than zero (or greater than zero) longer than 64 pixels (i.e. allowing 10% timebase shift)'''
    cgen = run_count_generator(raw_data, startat)
    curr, i = cgen.next()
    while 1:
        prev = curr
        j = i
        curr, i = cgen.next()
        if prev > 64 and curr > 64:
            sa = ""
            for ii in xrange(j, j + 128):
                sa += '%d' % bool(raw_data[ii] > 0)
            printerr(str((prev, curr, i, j)))
            printerr(sa)
            return j


def bit_generator(raw_data, startat):
    i = startat
    ss = 0.0
    c = 0
    prev = 0
    first = True
    try:
        while 1:
            start_code_loc = find_next_start_code(raw_data, i)
            i = start_code_loc + 2500
            distance = start_code_loc - prev
            per_pixel = float(distance) / 588.
            ss += per_pixel
            c += 1
            printerr('Start code: %.2f %d %d %d ' % ( per_pixel, prev, start_code_loc, distance ))
            if first:
                first = False
                prev = start_code_loc
                continue
            else:
                for bit in bit_gen_from_pos_two(raw_data, prev, start_code_loc - 1, 588):
                    yield bit
            prev = start_code_loc
    except IndexError:
        max_possible = int(i / 3892.56)
        hit_rate = float(c) / float(max_possible)
        res = '%.2f, %d %.2f' % ( ss / c, c, hit_rate )
        printerr(res)


def bit_gen_from_start_pos(data, start_sample, end_sample, bits_expected):
    pace = (float(end_sample) - float(start_sample)) / float(bits_expected)
    i = float(start_sample)
    printerr('pace %f i %.2f %i %i %i %i' % ( pace, i, start_sample, data[start_sample], data[start_sample + 1], data[start_sample + 2] ))
    printerr('               %i %i %i %i' % (
    int(start_sample), data[end_sample - 2], data[end_sample - 1], data[end_sample]))

    while i <= end_sample:
        yield int(data[i] > 0)
        i += pace


def bit_gen_from_pos_two(data, start_sample, end_sample, bits_expected):
    pace = ( float(end_sample) - float(start_sample) ) / float(bits_expected)
    i = float(start_sample)
    printerr('pace %f i %.2f %i %i %i %i' % ( pace, i, start_sample, data[start_sample], data[start_sample + 1], data[start_sample + 2] ))
    printerr('               %i %i %i %i' % (
    int(start_sample), data[end_sample - 2], data[end_sample - 1], data[end_sample] ))

    # Find edges and compare with expectation
    sc = i
    start = data[sc] > 0
    while 1:
        curr = data[sc] > 0
        if curr != start:
            edgepos = sc
            start = curr
            break
        sc += 1

    # Next edge position should be edgepos+( pace * 3T ), let's start at edgepos + ( pace * 2.5 ) and scan forwards
    sc = edgepos + (pace * 2.5)
    expected = edgepos + (pace * 3)
    worst = edgepos + (pace * 3.5)
    while sc < end_sample:
        while sc < worst:
            curr = data[sc] > 0
            if curr != start:
                # Found an edge, that means the next edge will be 3T away, which means 100b
                edgepos = sc
                start = curr
                dev = abs(expected - sc)
                printerr('    edge deviation from expected pos: %d ' % dev)
                sc = edgepos + (pace * 2.5)
                expected = edgepos + (pace * 3)
                worst = edgepos + (pace * 3.5)
                yield 1
                yield 0
                yield 0
                break
            sc += 1
        else:
            # Didn't find an edge, so this is 0b
            edgepos = expected
            start = data[expected] > 0
            printerr('    zero  ')

            sc = edgepos + (pace * 0.75)
            expected = edgepos + (pace)
            worst = edgepos + (pace * 1.4)
            yield 0


SEARCH_POSITIONS = ( 0., 1., -1., 2., -2., 3., -3. )  # ,3.3,-3.3)


def edgeclock_decode(data, start_sample, pace, verbose=False):
    """ A PLL/DLL approach that just hunts for edges in expected places """
    i = float(start_sample)

    def detect_edge(data, sc, flag):
        cv = data[sc]
        nv = data[sc + 1]
        return (cv > 0) and (nv > 0)

    exp3t = pace * 3.0
    expz = pace

    # Find the first edgepos
    sc = i
    edge_state = data[sc] > 0
    try:
        tcount = [0] * 35
        while 1:
            curr = data[sc] > 0
            if curr != edge_state:
                edgepos = sc
                edge_state = curr
                break
            sc += 1

        # Next edge position should be edgepos + ( pace * 3T ), let's start a little before and scan forwards
        sc = edgepos + exp3t

        t = 3
        while 1:
            for pos in SEARCH_POSITIONS:
                curr = detect_edge(data, sc + pos, edge_state)
                if curr != edge_state:
                    # Found an edge, that means the next edge will be 3T away, which means 100b
                    edgepos = sc + pos
                    edge_state = curr
                    tcount[t] += 1
                    dev = pos
                    if verbose:
                        printerr(' edge deviation from expected pos: %.2f ' % dev)
                    sc = edgepos + exp3t
                    yield 1
                    yield 0
                    yield 0
                    t = 3
                    break
                sc += 1
            else:
                t = t + 1
                if t > 30:
                    tcount[34] += 1  # High pass filter wanted, apply within
                    t = 3
                # Didn't find an edge, so this is 0b
                edgepos = sc
                edge_state = detect_edge(data, sc, edge_state)
                if verbose:
                    printerr(' zero')
                sc = edgepos + expz
                yield 0
    except IndexError:
        pass
    printerr('Distribution of edge gaps %s ! should stop here but: %s ' % ( str(tcount[0:11]), str(tcount[11:]) ))


def decode_efm(apply_filters=True, apply_demp=False, just_log=True, random_input=False):
    """ Decode EFM from STDIN, assuming it's a 28Mhz 8bit raw stream.
          apply_filters    apply lowpass/highpass filters
          apply_demp       apply de-emphasis filter (False for CD Audio)
          just_log         just log to stderr, don't bother decoding
          random_input     run against white noise"""
    if random_input:
        data = np.random.random_integers(-10000, 10000, SAMPLES)
    else:
        data = np.fromstring(sys.stdin.read(SAMPLES), dtype=np.uint8).astype(np.int16)
        data = sps.detrend(data, type='constant')  # Remove DC
        data = auto_gain(data, 10000, 'pre-filter')  # Expand before filtering, since we'll lose much of signal otherwise

    if apply_demp:
        # This is too slow, need to work out a way to do it in scipy
        de_emphasis_filter = biquad_filter(-1.8617006585639506, 0.8706642683920058, 0.947680874725466,
                                           -1.8659578411373265, 0.9187262110931641)
        data = np.fromiter(run_filter(de_emphasis_filter, data), np.int16)  # De-emph - 26db below 500khz

    if apply_filters:
        # bandpass = sps.firwin(8191, [0.013 / FREQ_MHZ, 2.1 / FREQ_MHZ], pass_zero=False)
        # data = sps.lfilter(bandpass, 1, data)

        low_pass = sps.cheby2(16, 100., 4.3 / FREQ_MHZ)  # Looks a bit odd, but is a reasonable tie for the spec filter (-26db at 2.0 Mhz, -50+ at 2.3Mhz)
        # low_pass = sps.cheby2(10, 50., 4.3 / FREQ_MHZ)  # Looks a bit odd, but is a reasonable tie for the spec filter (-26db at 2.0 Mhz, -50+ at 2.3Mhz)
        data = sps.filtfilt(low_pass[0], low_pass[1], data)

    bit_gen = edgeclock_decode(data, 0., 6.26)
    data_frames = []

    try:
        frame_bytes = []
        frames = 0
        while 1:
            if just_log:
                printerr([ bit_gen.next(), bit_gen.next(),bit_gen.next(),bit_gen.next(),bit_gen.next(),bit_gen.next(),bit_gen.next(),bit_gen.next(),bit_gen.next(),bit_gen.next(),bit_gen.next(),bit_gen.next(),bit_gen.next(),bit_gen.next()])
            else:
                run_until_start_code(bit_gen)
                consume_merging_bites(bit_gen)
                frames += 1
                frame_bytes.append(list(consume_f3_frame(bit_gen)))  # 31 14 bit EFM codes in a frame
                if len(frame_bytes) == EFM_FRAME_LENGTH:
                    f2frame = consume_f2_frame(frame_bytes)
                    data_frames.append(consume_f1_frame(f2frame))
                    frame_bytes = []
                    #
    except StopIteration:
        printerr('Hit the end of the bitstream')
        printerr('Found %d frames ' % frames)
        printerr(' Expected %.2f frames' % ((SAMPLES / 6.26 ) / 588 ))
    ## Output data should now contain all the decoded frames
    audioleft, audioright = extract_audio_samples(data_frames)
    data = np.clip(data, 0, 255).astype(np.uint8)
    sys.stdout.write(data.tostring())


if __name__ == "__main__":
    decode_efm()