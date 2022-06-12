class DebugPlot:
    def __init__(self, stuff_to_plot: str):
        self.__stuff_to_plot = stuff_to_plot.casefold().split()

    def is_plot_requested(self, requested_info: str):
        return requested_info in self.__stuff_to_plot


def plot_input_data(
    raw_data, raw_fft, env, env_mean, demod_video, filtered_video, rfdecode
):
    import matplotlib.pyplot as plt
    import numpy as np

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, sharex=True)

    # ax1.plot((20 * np.log10(self.Filters["Fdeemp"])))
    #        ax1.plot(hilbert, color='#FF0000')
    blocklen = len(raw_data)
    ax1.plot(raw_data, color="#00FF00")
    ax1.plot(env, label="Envelope", color="#0000FF")
    if rfdecode.dod_threshold_a:
        ax1.axhline(
            rfdecode.dod_threshold_a, label="DOD Threshold (absolute)", color="#001100"
        )
    else:
        ax1.axhline(
            rfdecode.dod_threshold_p * env_mean, label="DOD Threshold", color="#110000"
        )
        ax1.axhline(
            rfdecode.dod_threshold_p * env_mean * rfdecode.dod_hysteresis,
            label="DOD Hysteresis threshold",
            ls="--",
            color="#000011",
        )
    ax1.set_title("Raw data")
    ax1.legend()
    # 20 * np.log10(raw_fft.real)
    ax2.plot(demod_video)
    ax2.set_title("Demodulated video")
    ax3.plot(filtered_video, color="#00FF00")
    ax3.axhline(rfdecode.iretohz(0), label="0 IRE", color="#000000")
    ax3.axhline(rfdecode.iretohz(100), label="100 IRE", color="#000000", ls="--")
    ax3.set_title("Output video (Deemphasized and filtered) ")
    ax3.legend()
    fig2, ax4 = plt.subplots(1, 1)
    ax4.plot(
        np.arange(blocklen) / blocklen * rfdecode.freq_hz, abs(raw_fft), color="#00FF00"
    )
    ax4.set_xlabel("frequency")
    ax4.set_title("frequency spectrum of raw input")

    plt.show()
    # exit(0)


def plot_deemphasis(rf, filter_video_lpf, decoder_params, filter_deemp):
    import math
    import matplotlib.pyplot as plt
    import numpy as np
    import scipy.signal as sps
    from vhsdecode.addons.FMdeemph import FMDeEmphasisB

    corner_freq = 1 / (math.pi * 2 * decoder_params["deemph_tau"])

    db, da = FMDeEmphasisB(
        rf.freq_hz, decoder_params["deemph_gain"], decoder_params["deemph_mid"]
    ).get()

    fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True)

    w1, h1 = sps.freqz(db, da, fs=rf.freq_hz)

    # VHS eyeballed freqs.
    test_arr = np.array(
        [
            [
                0.04,
                0.05,
                0.07,
                0.1,
                corner_freq / 1e6,
                0.2,
                0.3,
                0.4,
                0.5,
                0.7,
                1,
                2,
                3,
                4,
                5,
            ],
            [
                0.4,
                0.6,
                1.2,
                2.2,
                3,
                5.25,
                7.5,
                9.2,
                10.5,
                11.75,
                12.75,
                13.5,
                13.8,
                13.9,
                14,
            ],
        ]
    )
    test_arr[0] *= 1000000.0

    ax1.plot(test_arr[0], test_arr[1], color="#000000")
    ax1.plot(w1, -20 * np.log10(h1))
    ax1.axhline(-3)
    ax1.axhline(-7)
    ax1.axvline(corner_freq)

    blocklen_half = rf.blocklen // 2
    freqs = np.linspace(0, rf.freq_hz_half, blocklen_half)
    ax2.plot(
        freqs, 20 * np.log10(filter_deemp[:blocklen_half]), label="Deemphasis only"
    )
    ax2.plot(freqs, 20 * np.log10(filter_video_lpf[:blocklen_half]), label="lpf")
    ax2.plot(
        freqs,
        20 * np.log10(rf.Filters["FVideo"][:blocklen_half]),
        label="Deemphasis + lpf",
    )
    ax2.legend()
    plt.show()
    exit()
