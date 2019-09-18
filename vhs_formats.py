from lddecode_core import RFParams_PAL,SysParams_PAL

# We base the parameters off the original laserdisc ones and override the ones
# we need.
# NOTE: (This requires python 3.5+)
RFParams_PAL_VHS = {**RFParams_PAL}

# Tape-specific paramaters that differs from the laserdisc analogues
# Video Y deemphasis
# Not used, generated elsewhere.
# RFParams_PAL_VHS['video_deemp'] = (100*.24, 400*.24)

# Band-pass filter for Video rf.
# TODO: Needs tweaking
RFParams_PAL_VHS['video_bpf_low'] = 3200000
RFParams_PAL_VHS['video_bpf_high'] = 5200000
# Band-pass filter order.
# Order may be fine as is.
#RFParams_PAL_VHS['video_bpf_order'] = 1

# Low-pass filter on Y after demodulation
RFParams_PAL_VHS['video_lpf_freq'] = 4200000
# Order may be fine as is.
# RFParams_PAL_VHS['video_lpf_order'] = 9


SysParams_PAL_VHS = {**SysParams_PAL}

#0 IRE level after demodulation
SysParams_PAL_VHS['ire0'] = 4180000 #4100000

# frequency/ire IRE change pr frequency (Is this labeled correctly?)
SysParams_PAL_VHS['hz_ire'] = 860000 / 100.0

# Heterodyned color carrier frequency in Mhz.
# On VHS the same frequency is used for both NTSC and PAL.
VHS_COLOR_CARRIER_MHZ = 0.626953

#SysParams_PAL['outlinelen'] = calclinelen(SysParams_PAL, 4, 'fsc_mhz')
#SysParams_PAL['outlinelen_pilot'] = calclinelen(SysParams_PAL, 4, 'pilot_mhz')
#SysParams_PAL['vsync_ire'] = -.3 * (100 / .7)

#TODO: NTSC, SECAM
