#! /usr/bin/python
import math
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy as np
import sys

"""
Plot stdin as an FFT, can be a piped file, or cxadc device directly example usage:
    cat /dev/cxadc | ./live-fft.py
    cat mycap.raw | ./live-fft.py mega DN
    cat mycap.raw | ./live-fft.py faster
    cat mycap.raw | ./live-fft.py DN
"""

SAMPLE_RATE = 3.579545 * 8
DEFAULT_SAMPLES = int(2e4)

SAMPLE_OPTIONS = {
     'faster' : 500,
     'fast'   : 1000,
     'medium' : int(1e5),
     'mega'   : int(1e6)
}

max_value = 1.0  # Track the maximum value seen for setting the axis in denormalized mode


def live_plot(samples, normalize=True):
    def animate(_i):
        global max_value
        data = np.fromstring(sys.stdin.read(samples), dtype=np.uint8)
        mean = np.mean(data)
        rawmax = max(data)
        rawmin = min(data)
        sigrange = rawmax - rawmin
        data = data - mean
        freq = np.fft.fftfreq(np.arange(len(data)).shape[-1]) * SAMPLE_RATE  # Set frequency scale
        data = np.fft.fft(data)
        data = np.sqrt((data.real * data.real) + (data.imag * data.imag))
        max_data = max(data)
        if normalize:
            data = data / max_data  # Normalize to y to 1.0
            max_data = 1.0
        max_value = max_data if max_data > max_value else max_value
        peak_to_background = 20 * math.log10(1.0 / np.mean(data))
        ax1.clear()
        ax1.plot(freq[4:], data[4:])
        plt.axis([0, SAMPLE_RATE / 2, 0, max_value])
        fig.canvas.set_window_title(
            'LiveFFT  Range:%d(%d - %d) Mean:%.2f PkBG:%.2fdb' % ( sigrange, rawmax, rawmin, mean, peak_to_background ))
        print 'LiveFFT  Range:%d(%d - %d) Mean:%.2f PkBG:%.2fdb' % ( sigrange, rawmax, rawmin, mean, peak_to_background )
	if (sigrange > 240):
		print 'high range'

    fig = plt.figure(1)
    ax1 = fig.add_subplot(1, 1, 1)
    plt.xlabel('Frequency (MHz)')
    plt.ylabel('Power (linear)')
    plt.axis([0, SAMPLE_RATE / 2, 0, 1])
    _ani = animation.FuncAnimation(fig, animate,
                                  interval=100)  # Only plot at most once every 10th of a second to stop your CPU frying
    plt.show()

def main():
    normalize = True
    samples   = DEFAULT_SAMPLES
    args = list(sys.argv)
    if len(args) > 1:
        while args:
            parg = args.pop()
            if parg in SAMPLE_OPTIONS.keys():
                samples = SAMPLE_OPTIONS.get(sys.argv[1], DEFAULT_SAMPLES)
            if parg == 'DN':
                normalize = False

    live_plot(samples, normalize)

if __name__ == "__main__":
    main()
