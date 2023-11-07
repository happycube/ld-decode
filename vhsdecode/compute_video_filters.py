import scipy.signal as sps

from vhsdecode.utils import filtfft
from vhsdecode.addons.FMdeemph import FMDeEmphasisB


def gen_video_main_deemp_fft(rf_params, freq_hz, block_len):
    """Generate real-value fft main video deemphasis filter from parameters"""
    db, da = FMDeEmphasisB(
        freq_hz,
        rf_params["deemph_gain"],
        rf_params["deemph_mid"],
        rf_params.get("deemph_q", 1 / 2),
    ).get()

    filter_deemp = filtfft((db, da), block_len, whole=False)
    return filter_deemp


def gen_video_lpf(rf_params, nyquist_hz, block_len):
    """Generate real-value fir and fft post-demodulation low pass filters from parameters"""
    video_lpf = sps.butter(
        rf_params["video_lpf_order"], rf_params["video_lpf_freq"] / nyquist_hz, "low"
    )

    video_lpf_fft = filtfft(video_lpf, block_len, False)
    return (video_lpf, video_lpf_fft)


def gen_nonlinear_bandpass(rf_params, nyquist_hz, block_len):
    """Generate bandpass or highpass real-value fft filter used for non-linear filtering."""
    upper_freq = rf_params.get("nonlinear_bandpass_upper", None)

    # Use a bandpass filter if upper frequency is specified, otherwise we use a high-pass filter.
    if upper_freq:
        nl_highpass_filter = filtfft(
            sps.butter(
                1,
                [
                    rf_params["nonlinear_highpass_freq"] / nyquist_hz,
                    upper_freq / nyquist_hz,
                ],
                btype="bandpass",
            ),
            block_len,
            whole=False,
        )
    else:
        nl_highpass_filter = filtfft(
            sps.butter(
                1,
                [rf_params["nonlinear_highpass_freq"] / nyquist_hz],
                btype="highpass",
            ),
            block_len,
            whole=False,
        )

    return nl_highpass_filter
