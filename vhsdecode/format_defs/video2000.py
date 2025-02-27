"""Module containing parameters for v2000"""

# TODO: Needs to be 180 degrees on every four lines on each track
PAL_ROTATION = [0, -1]


def fill_rfparams_video2000_shared(rfparams: dict, tape_speed: int = 0) -> None:
    """Fill in parameters that are shared between systems for v2000"""

    # PAL and NTSC uses the same main de-emphasis
    # Temporary video emphasis filter constants
    # The values are calculated based on the v2000 spec IEC 774-1 (1994), page 67
    # A first-order shelf filter is given with these parameters:
    #  RC time constant: 1.3µs
    #  resistor divider ratio: 4:1 (=> gain factor 5)

    rfparams["deemph_mid"] = 273755.82  # sqrt(gain_factor)/(2*pi*r*c)
    rfparams["deemph_gain"] = 12.9794  # 20*log10(gain_factor)
    rfparams["deemph_q"] = (
        0.462088186  # 1/sqrt(sqrt(gain_factor) + 1/sqrt(gain_factor) + 2)
    )

    # Parameters for high-pass filter used for non-linear deemphasis, these are
    # probably not correct.
    rfparams["nonlinear_highpass_freq"] = 820000
    rfparams["nonlinear_highpass_limit_h"] = 5000
    rfparams["nonlinear_highpass_limit_l"] = -20000

    rfparams["nonlinear_scaling_1"] = 0.1
    rfparams["nonlinear_exp_scaling"] = 0.12
    rfparams["use_sub_deemphasis"] = [False, True, True, True][tape_speed]


def get_rfparams_pal_video2000(rfparams_pal: dict, tape_speed: int = 0) -> dict:
    """Get RF params for PAL v2000"""

    rfparams = {**rfparams_pal}

    # Band-pass filter for Video rf.
    # VR2020 has a 625 khz trap, 1 mhz hpf, and 6 mhz lpf on the luma in addition to
    # eq

    # TODO: Needs tweaking
    rfparams["video_bpf_low"] = 900000
    rfparams["video_bpf_high"] = 5980000
    # Band-pass filter order.
    # Order may be fine as is.
    rfparams["video_bpf_order"] = None
    # Sharper upper cutoff to get rid of high-frequency junk.
    rfparams["video_lpf_extra"] = 5910000
    rfparams["video_lpf_extra_order"] = 20

    rfparams["video_bpf_supergauss"] = False

    rfparams["video_hpf_extra"] = 900000
    rfparams["video_hpf_extra_order"] = 16

    # Low-pass filter on Y after demodulation
    rfparams["video_lpf_freq"] = 3000000
    rfparams["video_lpf_order"] = 6

    rfparams["color_under_carrier"] = ((625 * 25) * 40) + 1953  ## 625000

    # Upper frequency of bandpass to filter out chroma from the rf signal.
    # The VR2020 has a 1 mhz lpf
    rfparams["chroma_bpf_upper"] = 1100000
    rfparams["chroma_bpf_lower"] = 220000
    rfparams["chroma_bpf_order"] = 5

    # Video EQ after FM demod (PAL v2000)
    rfparams["video_eq"] = {
        "loband": {"corner": 2.62e6, "transition": 500e3, "order_limit": 20, "gain": 2},
    }

    # Video Y FM de-emphasis (1.25~1.35µs)
    rfparams["deemph_tau"] = 1.30e-6

    # Temporary video emphasis filter constants
    # Ideally we would calculate this based on tau and 'x' value, for now
    # it's eyeballed based on graph and output.
    # rfparams["deemph_mid"] = 260000
    # rfparams["deemph_gain"] = 14

    # Filter to pull out high frequencies for high frequency boost
    # This should cover the area around reference white.
    # Used to reduce streaks due to amplitude loss on phase change around
    # sharp transitions.
    rfparams["boost_bpf_low"] = 4200000
    rfparams["boost_bpf_high"] = 5600000
    # Multiplier for the boosted signal to add in.
    rfparams["boost_bpf_mult"] = None

    # Use linear ramp to boost RF
    # Lower number attenuates lower freqs more giving a "softer" look with less ringing but potentially less detail
    rfparams["boost_rf_linear_0"] = 0.75
    # This param doesn't really seem to matter.
    rfparams["boost_rf_linear_20"] = 1
    # Double up ramp filter to more closely mimic v2000 EQ
    rfparams["boost_rf_linear_double"] = False

    rfparams["start_rf_linear"] = 0  # rfparams["color_under_carrier"]

    # rfparams["video_rf_peak_freq"] = 4700000
    # rfparams["video_rf_peak_gain"] = 4
    # rfparams["video_rf_peak_bandwidth"] = 1.5e7

    # Parameters for high-pass filter used for non-linear deemphasis, these are
    # probably not correct.
    # rfparams["nonlinear_highpass_freq"] = 600000
    # rfparams["nonlinear_highpass_limit_h"] = 5000
    # rfparams["nonlinear_highpass_limit_l"] = -20000

    rfparams["chroma_rotation"] = PAL_ROTATION

    # Frequency of fm audio channels - used for notch filter
    # rfparams["fm_audio_channel_0_freq"] = 1400000
    # rfparams["fm_audio_channel_1_freq"] = 1800000

    fill_rfparams_video2000_shared(rfparams, tape_speed)

    return rfparams


def get_sysparams_pal_video2000(sysparams_pal: dict, tape_speed: int = 0) -> dict:
    """Get system params for PAL v2000"""

    sysparams = {**sysparams_pal}
    # frequency/ire IRE change pr frequency (Is this labeled correctly?)
    sysparams["hz_ire"] = 1.5e6 / (100 + (-sysparams["vsync_ire"]))

    # 0 IRE level after demodulation
    sysparams["ire0"] = 4.8e6 - (sysparams["hz_ire"] * 100)

    # Mean absolute value of color burst for Automatic Chroma Control.
    # The value is eyeballed to give ok chroma level as of now, needs to be tweaked.
    # This has to be low enough to avoid clipping, so we have to
    # tell the chroma decoder to boost it by a bit afterwards.
    sysparams["burst_abs_ref"] = 10000

    return sysparams
