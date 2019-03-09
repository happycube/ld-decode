# Tape-specific paramaters that differs from the laserdisc analogues


RFParams_PAL_VHS = {
    # Video Y deemphasis
    # TODO - get from VHS specs
    'video_deemp': (100*.24, 400*.24),

    # Band-pass filter for Video Y
    'video_bpf': (3000000, 5500000),
    'video_bpf_order': 1,

    # Low-pass filter on Y after demodulation
    'video_lpf_freq': 4500000,
    'video_lpf_order': 9,
}


SysParams_PAL_VHS = {
#    'ire0': 7100000,
    #0 IRE level after demodulation
    'ire0': 4050000,
    'hz_ire': 800000 / 100.0,

    # Same for NTSC and PAL
    'color_carrier_mhz': 0.629,
}

#SysParams_PAL['outlinelen'] = calclinelen(SysParams_PAL, 4, 'fsc_mhz')
#SysParams_PAL['outlinelen_pilot'] = calclinelen(SysParams_PAL, 4, 'pilot_mhz')
#SysParams_PAL['vsync_ire'] = -.3 * (100 / .7)

#TODO: NTSC, SECAM
