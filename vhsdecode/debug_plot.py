class DebugPlot():
    def __init__(self, stuff_to_plot: str):
        self.__stuff_to_plot = stuff_to_plot.casefold().split()

    def is_plot_requested(self, requested_info: str):
        return requested_info in self.__stuff_to_plot


def plot_input_data(raw_data, raw_fft, env, env_mean, demod_video, filtered_video, rfdecode):
    import matplotlib.pyplot as plt
    import numpy as np
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, sharex=True)

    # ax1.plot((20 * np.log10(self.Filters["Fdeemp"])))
    #        ax1.plot(hilbert, color='#FF0000')
    blocklen = len(raw_data)
    ax1.plot(raw_data, color="#00FF00")
    ax1.plot(env, label="Envelope", color="#0000FF")
    if rfdecode.dod_threshold_a:
        ax1.axhline(rfdecode.dod_threshold_a, label='DOD Threshold (absolute)', color="#001100")
    else:
        ax1.axhline(rfdecode.dod_threshold_p * env_mean, label='DOD Threshold', color="#110000")
        ax1.axhline(rfdecode.dod_threshold_p * env_mean * rfdecode.dod_hysteresis, label='DOD Hysteresis threshold', ls='--', color="#000011")
    ax1.set_title('Raw data')
    ax1.legend()
    # 20 * np.log10(raw_fft.real)
    ax2.plot(demod_video)
    ax2.set_title('Demodulated video')
    ax3.plot(filtered_video, color="#00FF00")
    ax3.axhline(rfdecode.iretohz(0), label='0 IRE', color="#000000")
    ax3.axhline(rfdecode.iretohz(100), label='100 IRE', color="#000000", ls='--')
    ax3.set_title('Output video (Deemphasized and filtered) ')
    ax3.legend()
    fig2, ax4 = plt.subplots(1, 1)
    ax4.plot(np.arange(blocklen) / blocklen * rfdecode.freq_hz, abs(raw_fft), color="#00FF00")
    ax4.set_xlabel('frequency')
    ax4.set_title('frequency spectrum of raw input')

    # ax3.plot(data_filtered)
    # ax3.plot(hilbert_t.real)
    # ax4.plot(hilbert.real)
    # ax1.axhline(self.iretohz(self.SysParams["vsync_ire"]))
    # ax1.axhline(self.iretohz(self.SysParams["vsync_ire"] - 5))
    # print("Vsync IRE", self.SysParams["vsync_ire"])
    # ax2 = ax1.twinx()
    # ax3 = ax1.twinx()
    # ax1.plot(
    #     np.arange(self.blocklen) / self.blocklen * self.freq_hz, indata_fft.real
    # )
    # # ax1.plot(env, color="#00FF00")
    # # ax1.axhline(0)
    # # ax1.plot(demod_b, color="#000000")
    # ax2.plot(
    #     np.arange(self.blocklen) / self.blocklen * self.freq_hz,
    #     20 * np.log10(abs(self.Filters["RFVideo"])),
    # )
    # ax2.axhline(0)
    # ax3.plot(
    #     np.arange(self.blocklen) / self.blocklen * self.freq_hz, indata_fft_filt
    # )
    # ax3.plot(np.arange(self.blocklen) / self.blocklen * self.freq_hz, )
    # ax3.axhline(0)
    # ax4.plot(np.pad(np.diff(hilbert), (0, 1), mode="constant"))
    # ax4.axhline(0)
    #            ax3.plot(np.angle(hilbert))
    #            ax4.plot(hilbert.imag)
    #            crossings = find_crossings(env, 700)
    #            ax3.plot(crossings, color="#0000FF")
    plt.show()
    # exit(0)
