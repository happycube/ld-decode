"""
    Provides a way to measure the power of each burst in the multiburst test pattern
    using the Goertzel algorithm
"""
try:
    from gofft.alg import goertzel
except ImportError:
    print('goertzel-fft missing:')
    print('exec: pip3 install git+https://github.com/NaleRaphael/goertzel-fft.git')
    exit(0)

from vhsdecode.addons.mbgen.multiburst_generator import burst_frequencies
import numpy as np
import csv

class GoertzelMBmetrics:

    # fs sampling frequency
    def __init__(self, fs=40e6):
        self.fs = fs
        self.intb = list()
        self.currlen = 0
        self.time = 0
        self.csvlog = list()

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
            self.time += len(input)
            return None
        else:
            secs = self.time / self.fs
            print('t= %.2f s Computing multiburst tones magnitude, please wait ...' % secs)
            data = self.flatten(self.intb)
            for burst in burst_frequencies():
                freq, phase = burst
                magnitude = goertzel(data, int(self.fs), freq, len(data))
                metrics.append({
                    'time': secs,
                    'frequency': freq,
                    'magnitude': magnitude
                })
            self.intb.clear()
            newlen = int(len(data) * 0.9)
            self.intb.append(data[:newlen])
            self.intb.append(input)
            self.currlen = newlen
            self.currlen += len(input)
            self.time += len(input)
            return metrics

    def print(self, metrics):
        for metric in metrics:
            print('\t MB tone: %d Hz, magnitude: %.3f' % (metric['frequency'], metric['magnitude']))

    def push(self, name):
        with open(name, mode='w') as log_file:
            writer = csv.writer(log_file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
            row = list()
            row.append('Time')
            for burst in burst_frequencies():
                freq, phase = burst
                row.append(freq)
            writer.writerow(row)
            row.clear()
            for log in self.csvlog:
                lastTime = 0
                for metric in log:
                    if lastTime != metric['time']:
                        writer.writerow(row)
                        row.clear()
                        row.append(metric['time'])
                        lastTime = metric['time']
                    row.append(metric['magnitude'])
                writer.writerow(row)

    def debug(self, data):
        result = self.get(data)
        if result is not None:
            self.csvlog.append(result)
            self.print(result)

        self.push('mblog.csv')
