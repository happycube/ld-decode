def get_rfparams_ntsc_vhd(rfparams_ntsc: dict) -> dict:
    rfparams = {**rfparams_ntsc}

    rfparams["deemph_mid"] = 350000
    rfparams["deemph_gain"] = 12.0

    rfparams["video_bpf_low"] = 2000000
    rfparams["video_bpf_high"] = 9980000

    # Band-pass filter order.
    # Order may be fine as is.
    rfparams["video_bpf_order"] = None
    rfparams["video_bpf_supergauss"] = False

    # Sharper upper cutoff to get rid of high-frequency junk.
    rfparams["video_lpf_extra"] = 10000000
    rfparams["video_lpf_extra_order"] = 25

    rfparams["video_hpf_extra"] = 2600000
    rfparams["video_hpf_extra_order"] = 20

    # Low-pass filter on Y after demodulation
    rfparams["video_lpf_freq"] = 5500000
    rfparams["video_lpf_order"] = 6
    rfparams["video_lpf_supergauss"] = False

    rfparams["boost_bpf_low"] = 6700000
    rfparams["boost_bpf_high"] = 8000000
    # Multiplier for the boosted signal to add in.
    rfparams["boost_bpf_mult"] = None

    # Use linear ramp to boost RF
    rfparams["boost_rf_linear_0"] = 1
    rfparams["boost_rf_linear_20"] = 2
    rfparams["boost_rf_linear_double"] = False
    rfparams["start_rf_linear"] = 0

    rfparams["video_rf_peak_freq"] = 7500000
    rfparams["video_rf_peak_gain"] = 4
    rfparams["video_rf_peak_bandwidth"] = 2.0e7

    rfparams["use_sub_deemphasis"] = False

    rfparams["color_under_carrier"] = 3.58e6  # TODO set to fsc properly
    rfparams["chroma_bpf_upper"] = (
        200000  # not used for composite formats but needs to be set atm, need to fix.
    )

    return rfparams


def get_sysparams_ntsc_vhd(sysparams_ntsc: dict) -> dict:
    sysparams = {**sysparams_ntsc}

    sysparams["hz_ire"] = 2e6 / 140

    # 0 IRE level after demodulation
    sysparams["ire0"] = 6.55e6

    return sysparams
