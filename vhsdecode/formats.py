from lddecode.core import RFParams_PAL, RFParams_NTSC, SysParams_PAL, SysParams_NTSC

# We base the parameters off the original laserdisc ones and override the ones
# we need.
# NOTE: (This requires python 3.5+)
RFParams_PAL_VHS = {**RFParams_PAL}
RFParams_NTSC_VHS = {**RFParams_NTSC}

RFParams_NTSC_UMATIC = {**RFParams_NTSC}
# Add SP/hi-band etc later

# Tape-specific paramaters that differs from the laserdisc analogues
# VHS PAL section

# Band-pass filter for Video rf.
# TODO: Needs tweaking
RFParams_PAL_VHS["video_bpf_low"] = 3490000
RFParams_PAL_VHS["video_bpf_high"] = 5580000
# Band-pass filter order.
# Order may be fine as is.
RFParams_PAL_VHS["video_bpf_order"] = 1
# Sharper upper cutoff to get rid of high-frequency junk.
RFParams_PAL_VHS["video_lpf_extra"] = 5410000
RFParams_PAL_VHS["video_lpf_extra_order"] = 5

RFParams_PAL_VHS["video_hpf_extra"] = 1690000
RFParams_PAL_VHS["video_hpf_extra_order"] = 1

# Low-pass filter on Y after demodulation
RFParams_PAL_VHS["video_lpf_freq"] = 3200000
# Order may be fine as is.
RFParams_PAL_VHS["video_lpf_order"] = 1

# PAL color under carrier is 40H + 1953
RFParams_PAL_VHS["color_under_carrier"] = ((625 * 25) * 40) + 1953

# Upper frequency of bandpass to filter out chroma from the rf signal.
# For vhs decks it's typically a bit more than 2x cc
RFParams_PAL_VHS["chroma_bpf_upper"] = 1400000

# Video EQ after FM demod (PAL VHS)
RFParams_PAL_VHS["video_eq"] = {
    'loband': {
        'corner': 1.25e6,
        'transition': 39e6,
        'order_limit': 1,
        'gain': 12
    },
    'hiband': {
        'corner': 3e6,
        'transition': 15e6,
        'order_limit': 2,
        'gain': 60
    }
}

# Video Y FM de-emphasis (1.25~1.35µs)
RFParams_PAL_VHS["deemph_tau"] = 1.30e-6

# NTSC VHS section

# Band-pass filter for Video rf.
# TODO: Needs tweaking
RFParams_NTSC_VHS["video_bpf_low"] = 3350000
RFParams_NTSC_VHS["video_bpf_high"] = 5600000

RFParams_NTSC_VHS["video_bpf_order"] = 1

RFParams_NTSC_VHS["video_lpf_extra"] = 6080000
RFParams_NTSC_VHS["video_lpf_extra_order"] = 3

RFParams_NTSC_VHS["video_hpf_extra"] = 1690000
RFParams_NTSC_VHS["video_hpf_extra_order"] = 1

# Low-pass filter on Y after demodulation
RFParams_NTSC_VHS["video_lpf_freq"] = 3000000

# Order may be fine as is.
RFParams_NTSC_VHS["video_lpf_order"] = 1

# NTSC color under carrier is 40H
RFParams_NTSC_VHS["color_under_carrier"] = (525 * (30 / 1.001)) * 40

# Upper frequency of bandpass to filter out chroma from the rf signal.
RFParams_NTSC_VHS["chroma_bpf_upper"] = 1400000

RFParams_NTSC_VHS["luma_carrier"] = 455.0 * ((525 * (30 / 1.001)) / 2.0)

# Video EQ after FM demod (NTSC VHS)
RFParams_NTSC_VHS["video_eq"] = {
    'loband': {
        'corner': 1.25e6,
        'transition': 39e6,
        'order_limit': 1,
        'gain': 12
    },
    'hiband': {
        'corner': 3e6,
        'transition': 15e6,
        'order_limit': 2,
        'gain': 60
    }
}

# Video Y FM de-emphasis (1.25~1.35µs)
RFParams_NTSC_VHS["deemph_tau"] = 1.30e-6

# UMATIC section

RFParams_NTSC_UMATIC["video_bpf_low"] = 3200000
RFParams_NTSC_UMATIC["video_bpf_high"] = 6500000
RFParams_NTSC_UMATIC["video_bpf_order"] = 1
RFParams_NTSC_UMATIC["video_lpf_extra"] = 6900000
RFParams_NTSC_UMATIC["video_lpf_extra_order"] = 3
RFParams_NTSC_UMATIC["video_hpf_extra"] = 1200000
RFParams_NTSC_UMATIC["video_hpf_extra_order"] = 1
RFParams_NTSC_UMATIC["video_lpf_freq"] = 4000000
RFParams_NTSC_UMATIC["video_lpf_order"] = 2
RFParams_NTSC_UMATIC["color_under_carrier"] = 688373
RFParams_NTSC_UMATIC["chroma_bpf_upper"] = 1500000

# Video EQ after FM demod (NTSC UMATIC) (needs tweak)
RFParams_NTSC_UMATIC["video_eq"] = {
    'loband': {
        'corner': 1.25e6,
        'transition': 39e6,
        'order_limit': 1,
        'gain': 12
    },
    'hiband': {
        'corner': 3e6,
        'transition': 15e6,
        'order_limit': 2,
        'gain': 60
    }
}

# Video Y FM de-emphasis (550 ~ 650ns)
RFParams_NTSC_UMATIC["deemph_tau"] = 600e-9

SysParams_PAL_VHS = {**SysParams_PAL}
SysParams_NTSC_VHS = {**SysParams_NTSC}
SysParams_NTSC_UMATIC = {**SysParams_NTSC}

# 0 IRE level after demodulation
SysParams_PAL_VHS["ire0"] = 4100000

# frequency/ire IRE change pr frequency (Is this labeled correctly?)
SysParams_PAL_VHS["hz_ire"] = 700000 / 100.0

# Top/white point defined by the standard 4.8 MHz
SysParams_PAL_VHS["max_ire"] = 100

# Mean absolute value of color burst for Automatic Chroma Control.
# The value is eyeballed to give ok chroma level as of now, needs to be tweaked.
# This has to be low enough to avoid clipping, so we have to
# tell the chroma decoder to boost it by a bit afterwards.
SysParams_PAL_VHS["burst_abs_ref"] = 2500

# 0 IRE level after demodulation
SysParams_NTSC_VHS["ire0"] = 3685000

# frequency/ire IRE change pr frequency (Is this labeled correctly?)
SysParams_NTSC_VHS["hz_ire"] = 715000 / 100.0

# Top/white point defined by the standard
SysParams_NTSC_VHS["max_ire"] = 100

# Mean absolute value of color burst for Automatic Chroma Control.
# The value is eyeballed to give ok chroma level as of now, needs to be tweaked.
SysParams_NTSC_VHS["burst_abs_ref"] = 1750

SysParams_NTSC_UMATIC["ire0"] = 4257143
SysParams_NTSC_UMATIC["hz_ire"] = 1600000 / 140.0
SysParams_NTSC_UMATIC["burst_abs_ref"] = 2750

# SysParams_PAL['outlinelen'] = calclinelen(SysParams_PAL, 4, 'fsc_mhz')
# SysParams_PAL['outlinelen_pilot'] = calclinelen(SysParams_PAL, 4, 'pilot_mhz')
# SysParams_PAL['vsync_ire'] = -.3 * (100 / .7)

# TODO: SECAM

# Default thresholds for rf dropout detection.
DEFAULT_THRESHOLD_P_DDD = 0.12
DEFAULT_THRESHOLD_P_CXADC = 0.3
DEFAULT_HYSTERESIS = 1.25
# Merge dropouts if they there is less than this number of samples between them.
DOD_MERGE_THRESHOLD = 30
DOD_MIN_LENGTH = 10
