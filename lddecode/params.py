"""System- and filter-parameter tables for NTSC and PAL.

These dicts are mutated in place at import time by the derivation code that
follows each definition; that code is kept here so the tables are fully
initialised on import.  Split verbatim out of core.py.
"""

import numpy as np

from .dsp import nb_round


# This is the size of each block of data which is processed in
# parallel.  The beginning and end are cut off so that there's
# no distortion from the FFT and filtering.

BLOCKSIZE = 32 * 1024

# These are constant, system-level parameters for PAL and NTSC

SysParams_NTSC = {
    "fsc_mhz": 315.0 / np.double(88.0),
    # NTSC LD doesn't have a pilot signal, so just recycle FSC
    "pilot_mhz": 315.0 / np.double(88.0),
    "frame_lines": 525,
    "field_lines": (263, 262),
    "ire0": 8100000,
    "hz_ire": 1700000 / 140.0,
    "vsync_ire": -40,
    "burst_ire": 20.0,
    # most NTSC disks have analog audio, except CD-V and a few Panasonic demos
    "analog_audio": True,
    # From the spec - audio frequencies are multiples of the (color) line rate
    "audio_lfreq": (1000000 * 315 / 88 / 227.5) * 146.25,
    "audio_rfreq": (1000000 * 315 / 88 / 227.5) * 178.75,
    # On AC3 disks, the right channel is replaced by a QPSK 2.88mhz channel
    "audio_rfreq_AC3": 2880000,
    "colorBurstUS": (5.3, 7.8),
    # Known-good area for computing black SNR - for NTSC pull from VSYNC
    # tuple: (line, beginning, length)
    "blacksnr_slice": (1, 10, 20),
    # In NTSC framing, the distances between the first/last eq pulses and the
    # corresponding next lines are different.
    "firstFieldH": (0.5, 1),
    "numPulses": 6,  # number of equalization pulses per section
    "hsyncPulseUS": 4.7,
    "eqPulseUS": 2.3,
    "vsyncPulseUS": 27.1,
    # 16-bit digital output value for sync tip (-40 IRE)
    "outputZero": 1024,
    "fieldPhases": 4,
    # Likely locations of solid white in VITS on LD's (line, start, length)
    # The first three are typical VITS locations (first most common), and last
    # is the MCA Code first-field flag.
    "LD_VITS_whitelocs": [(20, 14, 12), (20, 52, 8), (13, 13, 15), (11, 12, 45)],
    # Similar but with percentile to use to compute white level
    # (in case VITS white test areas are not present)
    "LD_VITS_code_slices": [(16, 12, 48, 85), (17, 12, 48, 85), (10, 13, 39, 85)],
}

# Calculate the exact line length for a given situation (such as
# 4FSC)
def calclinelen(SysParams, mult, mhz):
    if isinstance(mhz, str):
        mhz = SysParams[mhz]

    return int(nb_round(SysParams["line_period"] * mhz * mult))

# Compute dictionary entries for things that use FSC, etc.

# In color NTSC, the line period was changed from 63.5 to 227.5 color cycles,
# which works out to 63.555(with a bar on top) usec
SysParams_NTSC["line_period"] = 1 / (SysParams_NTSC["fsc_mhz"] / np.double(227.5))
SysParams_NTSC["activeVideoUS"] = (9.45, SysParams_NTSC["line_period"] - 1.0)

SysParams_NTSC["FPS"] = 1000000 / (525 * SysParams_NTSC["line_period"])

SysParams_NTSC["outlinelen"] = calclinelen(SysParams_NTSC, 4, "fsc_mhz")
SysParams_NTSC["outfreq"] = 4 * SysParams_NTSC["fsc_mhz"]

SysParams_PAL = {
    "FPS": 25,
    # from wikipedia: 283.75 × 15625 Hz + 25 Hz = 4.43361875 MHz
    "fsc_mhz": ((1 / 64) * 283.75) + (25 / 1000000),
    "pilot_mhz": 3.75,
    "frame_lines": 625,
    "field_lines": (312, 313),
    "line_period": 64,
    "ire0": 7100000,
    "hz_ire": 800000 / 100.0,
    "burst_ire": 150 / 7.0,
    # only early PAL disks have analog audio
    "analog_audio": True,
    # From the spec - audio frequencies are multiples of the (colour) line rate
    "audio_lfreq": (1000000 / 64) * 43.75,
    "audio_rfreq": (1000000 / 64) * 68.25,
    "colorBurstUS": (5.6, 7.85),
    "activeVideoUS": (10.5, 64 - 1.5),
    # In PAL, the first field's line sync<->first/last EQ pulse are both .5H
    "firstFieldH": (1, 0.5),
    # Known-good area for computing black SNR - for PAL this is blanked in mastering
    # tuple: (line, beginning, length)
    "blacksnr_slice": (22, 12, 50),
    "numPulses": 5,  # number of equalization pulses per section
    "hsyncPulseUS": 4.7,
    "eqPulseUS": 2.35,
    "vsyncPulseUS": 27.3,
    # 16-bit digital output value for sync tip (-43 IRE)
    "outputZero": 256,
    "fieldPhases": 8,
    # Likely locations of solid white in VITS on LD's
    # (an array of line/start/length)
    "LD_VITS_whitelocs": [(19, 12, 8)],
    # Similar but with percentile to use to compute white level
    # (in case VITS white test areas are not present)
    "LD_VITS_code_slices": [(16, 11, 49, 85), (17, 11, 49, 85)],
}

SysParams_PAL["outlinelen"] = calclinelen(SysParams_PAL, 4, "fsc_mhz")
SysParams_PAL["outlinelen_pilot"] = calclinelen(SysParams_PAL, 4, "pilot_mhz")
SysParams_PAL["outfreq"] = 4 * SysParams_PAL["fsc_mhz"]

SysParams_PAL["vsync_ire"] = -0.3 * (100 / 0.7)

FilterParams_NTSC = {
    # The audio notch filters are important with DD v3.0+ boards
    "audio_notchwidth": 200000,
    "audio_notchorder": 2,
    "video_deemp": (120e-9, 320e-9),
    # Zero-phase (magnitude-only) video EQ: (freq_hz, dB) anchors smoothly
    # interpolated, flat 0 dB outside the anchored range.  Flattens the
    # residual amplitude ripple left after de-emphasis and the inverse-MTF
    # chroma correction, calibrated against NTC-7 multiburst VITS on the
    # he010 and ve-snw test discs.  Applied to the output and burst paths
    # identically, so burst-based auto-calibration and phase alignment are
    # unaffected (the EQ is real-valued in the FFT domain).
    "video_eq": [
        (0.5e6, -0.02),
        (1.0e6, 0.14),
        (2.0e6, 0.50),
        (3.0e6, -0.15),
        (3.58e6, -0.39),
        (4.2e6, -0.05),
    ],
    # NTSC builds its RF video filter as a split high-pass (low edge) + low-pass
    # (high edge) cascade so the two skirts can be shaped independently
    # (see computevideofilters).  The low edge is kept gentle (order 2) to
    # protect the lower chroma sideband (~4.5 MHz at blanking) and its group
    # delay; the high edge is sharper to reject HF noise while keeping the
    # upper chroma sideband (~11.7 MHz) flat.
    "video_bpf_low": 3700000,
    "video_bpf_low_order": 2,
    "video_bpf_high": 13800000,
    "video_bpf_high_order": 3,
    # video_bpf_order is retained for the --lowband override.
    "video_bpf_order": 4,
    # This can easily be pushed up to 4.5mhz or even a bit higher on most disks.
    # A sharp 4.8-5.0 is probably the maximum before the audio carriers bleed into 0IRE.
    "video_lpf_freq": 4500000,  # in mhz
    "video_lpf_order": 6,  # butterworth filter order
    # MTF filter
    "MTF_basemult": 0.4,  # general ** level of the MTF filter for frame 0.
    "MTF_poledist": 0.9,
    "MTF_freq": 12.2,  # in mhz
    # used to detect rot
    "video_hpf_freq": 10000000,
    "video_hpf_order": 4,
    # audio filter parameters
    "audio_filterwidth": 150000,
    "audio_filterorder": 512,
}

# Settings for use with noisier disks
FilterParams_NTSC_lowband = FilterParams_NTSC.copy()
FilterParams_NTSC_lowband['video_bpf_low']  = 3800000
FilterParams_NTSC_lowband['video_bpf_high'] = 12500000
FilterParams_NTSC_lowband['video_lpf_freq'] = 4200000

FilterParams_PAL = {
    # The audio notch filters are important with DD v3.0+ boards
    "audio_notchwidth": 200000,
    "audio_notchorder": 2,
    "video_deemp": (100e-9, 400e-9),
    # PAL builds its RF video filter as a split high-pass (low edge) + low-pass
    # (high edge) cascade so the two skirts can be shaped independently
    # (see computevideofilters).  The low edge is kept gentle (order 2) to
    # protect the lower chroma sideband (~2.67 MHz) and its group delay; the
    # high edge is a little sharper and a touch higher to better reject HF noise
    # and the folded upper-J2 product (~16 MHz) while keeping the upper chroma
    # sideband (~12.3 MHz) flat.
    "video_bpf_low": 2300000,
    "video_bpf_low_order": 2,
    "video_bpf_high": 14000000,
    "video_bpf_high_order": 3,
    # video_bpf_order is retained for the shared bandpass path (NTSC) and the
    # --lowband override below; the PAL split path uses the two orders above.
    "video_bpf_order": 2,
    # Zero-phase RF BPF + MTF: skirt/pole phase asymmetry across the chroma
    # sidebands demodulates as differential phase (+8..15 deg per 100 IRE
    # measured on test discs); amplitude-only filtering removes it at no SNR
    # cost.  NTSC keeps phased filters: measured DP is worse zero-phased
    # (-3.4 vs +1.2 deg on he010) because the tuned NTSC chain's filter
    # phase cancels the second-order DP from sideband amplitude asymmetry.
    "video_rf_zero_phase": True,
    # 5.8 MHz recovers recorded luma detail out to the 5.8 MHz VITS multiburst
    # (IEC 60856); the extra group delay this Butterworth adds is corrected by
    # the all-pass equaliser in build_groupdelay_equalizer().
    "video_lpf_freq": 5800000,
    "video_lpf_order": 7,
    # MTF filter
    "MTF_basemult": 1.0,  # general ** level of the MTF filter for frame 0.
    "MTF_poledist": 0.70,
    "MTF_freq": 10,
    # used to detect rot
    "video_hpf_freq": 10000000,
    "video_hpf_order": 4,
    "audio_filterwidth": 100000,
    "audio_filterorder": 900,
}

# Settings for use with noisier disks
FilterParams_PAL_lowband = FilterParams_PAL.copy()
FilterParams_PAL_lowband['video_bpf_low']   = 3200000
FilterParams_PAL_lowband['video_bpf_high']  = 13000000
FilterParams_PAL_lowband['video_bpf_order'] = 2
FilterParams_PAL_lowband['video_lpf_freq']  = 4800000
