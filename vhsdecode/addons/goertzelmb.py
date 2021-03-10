"""
    Provides a way to measure the power of each burst in the multiburst test pattern
    using the Goertzel algorithm
"""
from gofft.alg import goertzel
from vhsdecode.addons.mbgen.multiburst_generator import burst_frequencies
import numpy as np


class GoertzelMBmetrics:

    # fs sampling frequency
    def __init__(self, fs=40e6):
        self.fs = fs
        self.intb = list()
        self.currlen = 0

    def flatten(self, buff):
        data = np.array([])
        for item in buff:
            data = np.append(data, item)
        return data

    def get(self, input):
        metrics = list()
        if self.currlen < self.fs:
            self.intb.append(input)
            self.currlen += len(input)
            return None
        else:
            print('Computing multiburst tones magnitude, please wait ...')
            data = self.flatten(self.intb)
            for burst in burst_frequencies():
                freq, phase = burst
                magnitude = goertzel(data, int(self.fs), freq, len(data))
                metrics.append({
                    'frequency': freq,
                    'magnitude': magnitude
                })
            self.intb.clear()
            self.intb.append(input)
            self.currlen = len(input)
            return metrics

    def print(self, metrics):
        for metric in metrics:
            print('\t MB tone: %d Hz, magnitude: %.3f' % (metric['frequency'], metric['magnitude']))

    def debug(self, data):
        result = self.get(data)
        if result is not None:
            self.print(result)
