"""
    It provides a set of functions to DTW (Dynamic Time Warping) the tape signal
    in order to remove the reading jitter caused by mechanical issues.
    It also detects the head switch point in the process.
"""

import numpy as np
from pyhht.utils import inst_freq
from vhsdecode.utils import \
    FiltersClass, firdes_lowpass, firdes_bandpass, \
    gen_wave_at_frequency, filter_plot, moving_average, \
    pad_or_truncate, auto_chop, zero_cross_det, plot_scope, dualplot_scope, plot_image
from lddecode.utils import unwrap_hilbert
from samplerate import resample
import dtw


def cost(data):
    a = np.max(data) - np.min(data)
    b = np.mean(data)
    return pow(b, 2) / 5


def edge_pad(data, edge_len):
    head = np.linspace(0.0, data[0], edge_len, dtype=data.dtype)
    tail = np.linspace(data[len(data)-1], 0.0, edge_len, dtype=data.dtype)
    result = np.concatenate((head, data, tail))
    assert len(result) == len(head) + len(data) + len(tail)
    return result


def trim(data, edge_trim):
    return data[edge_trim: len(data) - edge_trim]

class TimeWarper:
    # fdc chroma subcarrier frequency
    def __init__(self, fdc, fv=60, fs=40e6, blocklen=pow(2, 15)):
        self.plots = True
        self.chunks = 4
        self.error = 0.1
        self.drift = 0
        self.sign = 1
        self.dev = 1 - self.error, 1 + self.error
        self.drc = self.chunks
        self.harmonic_limit = 3
        self.samp_rate = fs
        self.fdc = fdc
        self.fv = fv
        self.blocklen = blocklen
        self.blockid = 0
        assert self.blocklen % self.chunks == 0, 'chunks should be a divisor of blocklen'

        iir_slow = firdes_lowpass(self.samp_rate, self.harmonic_limit * self.fv, 1e3)
        self.slow_filter = FiltersClass(iir_slow[0], iir_slow[1], self.samp_rate)

        iir_bandpass = firdes_bandpass(
            self.samp_rate,
            fdc * 0.1,
            100e3,
            fdc * 1.1,
            100e3
        )

        self.bandpass = FiltersClass(iir_bandpass[0], iir_bandpass[1], self.samp_rate)
        self.framebuffer = list()
        self.min_dev = list()
        self.max_dev = list()

    def hhtdeFM(self, data):
        instf, t = inst_freq(data)
        return np.add(np.multiply(instf, -self.samp_rate), self.samp_rate /2)

    def htdeFM(self, data):
        return unwrap_hilbert(data, self.samp_rate)

    def deFM(self, data):
        return self.htdeFM(data)

    def edgeless_filt(self, data):
        edge_trim = int(self.drc / 8)
        padded = edge_pad(data, edge_trim)
        narrowband = self.bandpass.filtfilt(padded.real)
        return trim(narrowband, edge_trim)

    # Measures the head switch jitter
    def head_switch_jitter(self, data):
        narrowband = self.edgeless_filt(data)
        freq = self.deFM(narrowband)
        velocity = self.slow_filter.filtfilt(freq)
        acceleration = np.diff(velocity)
        rel_velocity = np.cumsum(acceleration)
        return velocity, \
            np.append(acceleration, acceleration[len(acceleration)-1]),

    def do(self, data):
        narrowband = self.edgeless_filt(data)
        amplitude = np.mean(np.abs(narrowband)) * 2
        zeroes = zero_cross_det(narrowband)
        diff = np.mean(np.diff(zeroes))
        freq = self.samp_rate / (diff * 2)
        ref_wave = amplitude * gen_wave_at_frequency(freq, self.samp_rate, self.blocklen)
        ref_wave, _, _ = auto_chop(ref_wave)
        #print(zeroes[0])
        ref_wave = np.roll(ref_wave, zeroes[0])
        #dualplot_scope(ref_wave[:1024], ref_wave[(len(ref_wave)-1024):])
        ref_wave = np.concatenate((ref_wave, ref_wave))[:self.blocklen]
        #dualplot_scope(ref_wave[:1024], narrowband[:1024])

        data_chunks = np.split(data, self.chunks)
        narrow_chunks = np.split(narrowband, self.chunks)
        wave_chunks = np.split(ref_wave, self.chunks)
        result = list()
        for id, chunk in enumerate(data_chunks):
            query = narrow_chunks[id]
            template = wave_chunks[id]
            alignment = dtw.dtw(query, template, keep_internals=True)
            wq = dtw.warp(alignment, index_reference=False)
            plot_scope(wq)
            #alignment.plot('threeway')
            dualplot_scope(query[:128], query[wq][:128])
            result.append(chunk[wq])

        flatten_warp = np.array(self.list_flatten(result))
        dualplot_scope(data[:128], flatten_warp[:128])
        return flatten_warp

    def loss_choose(self, losses):
        half = int(len(losses) / 2)
        hi_loss = losses[:half]
        lo_loss = np.flip(losses[half:])
        hi_diff = np.diff(hi_loss)
        lo_diff = np.diff(lo_loss)
        if hi_diff[0] < lo_diff[0]:
            comp_diff = hi_diff
            sign = self.sign
        else:
            comp_diff = lo_diff
            sign = self.sign * -1

        sub_id = 0
        id_limit = len(comp_diff) - 2
        while comp_diff[sub_id+1] < comp_diff[sub_id] and sub_id < id_limit:
            sub_id += 1

        id = half + (sign * sub_id) - self.drift
        return np.clip(id, a_min=0, a_max=len(losses) - 1)

    def loss_map(self, data):
        return None, self.do(data)
        data_chunks = np.split(data, self.chunks)
        dtwspace = np.linspace(self.dev[0], self.dev[1], self.drc)
        rows, columns = self.drc, len(data_chunks)
        image = np.ones((rows, columns))
        losses = list()
        ratios = list()
        warps_round = list()
        warps = list()
        edge_trim = int(self.drc / 8)
        for col, raw_chunk in enumerate(data_chunks):
            chunk = edge_pad(raw_chunk, edge_trim)
            for row, warp in enumerate(dtwspace):
                raw_warp = resample(raw_chunk, ratio=warp, converter_type='linear')
                warps_round.append(raw_warp)
                warped = resample(chunk, ratio=warp, converter_type='linear')
                _, acc = self.head_switch_jitter(warped)
                acc_trimmed = trim(acc, edge_trim)
                loss = cost(acc_trimmed)
                losses.append(loss)
                try:
                    image[row][col] = loss
                except IndexError:
                    print('Image indexes out of bounds %dx%d got %dx%d' %
                          (columns, rows, col, row))
                    assert False

            r_id = int(np.where(np.array(losses) == np.min(losses))[0])
                # self.loss_choose(losses)
            ratios.append(dtwspace[r_id])
            warps.append(warps_round[r_id])
            losses.clear()
            warps_round.clear()


        warp_flat = self.list_flatten(warps)
        ratio = len(data) / len(warp_flat)
        warp = resample(warp_flat, ratio, converter_type='linear')

        #print(len(data), len(warp_flat))
        self.min_dev.append(100 * np.min(ratios))
        self.max_dev.append(100 * np.max(ratios))
        print('DTW avg speed slip - min: %.4f max: %.4f %%' % (moving_average(self.min_dev, 1024), moving_average(self.max_dev, 1024)))
        if self.plots:
            vel0, acc0 = self.head_switch_jitter(data)
            velw, accw = self.head_switch_jitter(np.array(warp))
            dualplot_scope(np.cumsum(vel0), np.cumsum(velw))
            plot_image(image)
            plot_scope(ratios)
        return image, warp

    def list_flatten(self, list):
        flatten = []
        for buffer in list:
            flatten.extend(buffer)
        return flatten

    def out_or_zero(self):
        flatten = self.list_flatten(self.framebuffer)

        if len(flatten) > self.blocklen:
            head = flatten[:self.blocklen]
            tail = flatten[self.blocklen:]
            assert len(head) == self.blocklen
            assert len(head) + len(tail) == len(flatten), 'expected %d got %d' % ( len(flatten), len(head) + len(tail) )
            blockpos = self.blocklen * self.blockid
            print('DTW pos: %d ->> tape slip: %d samples' % (blockpos, (len(tail) - self.blocklen)))
            self.framebuffer.clear()
            self.framebuffer.append(tail)
            return head, True
        else:
            return np.zeros(self.blocklen), False

    def velocity_compensatorB(self, data):
        image, dewarp = self.loss_map(data)
        if len(self.framebuffer) == 0:
            self.framebuffer.append(dewarp)
        self.framebuffer.append(dewarp)
        self.blockid += 1
        return self.out_or_zero()

