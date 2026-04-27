# ******************
# Audio mode options
# ******************
AUDIO_MODE_STEREO = "s"
AUDIO_MODE_STEREO_MS = "ms"
AUDIO_MODE_DUAL_MONO = "d"
AUDIO_MODE_DUAL_MONO_MS = "dms"
AUDIO_MODE_MONO_L = "l"
AUDIO_MODE_MONO_R = "r"
AUDIO_MODE_MONO_SUM = "sum"

UI_STEREO = "Stereo (L, R)"
UI_STEREO_MS = "Stereo (L+R, L-R)"
UI_DUAL_MONO = "Dual Mono (L) (R)"
UI_DUAL_MONO_MS = "Dual Mono (L+R) (L-R)"
UI_MONO_L = "Mono (L)"
UI_MONO_R = "Mono (R)"
UI_MONO_SUM = "Mono Sum (L+R)"

DEFAULT_VHS_AUDIO_MODE = AUDIO_MODE_STEREO
DEFAULT_8MM_AUDIO_MODE = AUDIO_MODE_STEREO_MS

audio_mode_to_ui = {
    AUDIO_MODE_STEREO: UI_STEREO,
    AUDIO_MODE_STEREO_MS: UI_STEREO_MS,
    AUDIO_MODE_DUAL_MONO: UI_DUAL_MONO,
    AUDIO_MODE_DUAL_MONO_MS: UI_DUAL_MONO_MS,
    AUDIO_MODE_MONO_L: UI_MONO_L,
    AUDIO_MODE_MONO_R: UI_MONO_R,
    AUDIO_MODE_MONO_SUM: UI_MONO_SUM,
}

ui_to_audio_mode = {
    UI_STEREO: AUDIO_MODE_STEREO,
    UI_STEREO_MS: AUDIO_MODE_STEREO_MS,
    UI_DUAL_MONO: AUDIO_MODE_DUAL_MONO,
    UI_DUAL_MONO_MS: AUDIO_MODE_DUAL_MONO_MS,
    UI_MONO_L: AUDIO_MODE_MONO_L,
    UI_MONO_R: AUDIO_MODE_MONO_R,
    UI_MONO_SUM: AUDIO_MODE_MONO_SUM,
}

# ****************************
# Dropout Compensation Options
# ****************************
DOC_MODE_FULL = "full"
DOC_MODE_MUTE = "mute"
DOC_MODE_DISABLED = "off"

UI_DOC_MODE_FULL = "Full"
UI_DOC_MODE_MUTE = "Muting Only"
UI_DOC_MODE_DISABLED = "Off"

DEFAULT_DOC_MODE = DOC_MODE_FULL

doc_mode_to_ui = {
    DOC_MODE_FULL: UI_DOC_MODE_FULL,
    DOC_MODE_MUTE: UI_DOC_MODE_MUTE,
    DOC_MODE_DISABLED: UI_DOC_MODE_DISABLED,
}

ui_to_doc_mode = {
    UI_DOC_MODE_FULL: DOC_MODE_FULL,
    UI_DOC_MODE_MUTE: DOC_MODE_MUTE,
    UI_DOC_MODE_DISABLED: DOC_MODE_DISABLED,
}

# TAU_1         low end of shelf curve
# TAU_2         high end of shelf curve

# *********************
# VHS Filter Parameters
# *********************

ENV_DETECTION_RMS = "rms" # Some Panasonic VCRs use RMS detection https://www.tapeheads.net/threads/vhs-hifi-with-record-level-controls.30570/page-2#post-388924
ENV_DETECTION_PEAK = "peak" # JVC and IEC 60774-2

UI_ENV_DETECTION_RMS = "RMS"
UI_ENV_DETECTION_PEAK = "Peak"

DEFAULT_ENV_DETECTION = ENV_DETECTION_PEAK

expander_env_detection_to_ui = {
    ENV_DETECTION_PEAK: UI_ENV_DETECTION_PEAK,
    ENV_DETECTION_RMS: UI_ENV_DETECTION_RMS,
}

ui_to_expander_env_detection = {
    UI_ENV_DETECTION_PEAK: ENV_DETECTION_PEAK,
    UI_ENV_DETECTION_RMS: ENV_DETECTION_RMS,
}

DEFAULT_VHS_EXPANDER_GAIN = 30
# IEC 60774-2 5.1: Noise Reduction
DEFAULT_VHS_EXPANDER_RATIO = 2 #           2:1 logarithmic
DEFAULT_VHS_EXPANDER_ATTACK_TAU = 6.5e-3 # 3ms to 10ms
DEFAULT_VHS_EXPANDER_HOLD_TAU = 0 #        None (only used for 8mm)
DEFAULT_VHS_EXPANDER_RELEASE_TAU = 70e-3 # 70ms +-20%

# IEC 60774-2 5.2: Pre-emphasis (filter parameters)
# IEC 60774-2 Figure 2, 4: Pre-emphasis (location in block diagram)
# for VHS, this deemphasis stage affects both the audio and weighted input to the expander
DEFAULT_VHS_DEEMPHASIS_TAU_1 = 56e-6 # 56us +- 20%
DEFAULT_VHS_DEEMPHASIS_TAU_2 = 20e-6 # 20us +- 20%

# IEC 60774-2 Figure 5: Weighting
DEFAULT_VHS_EXPANDER_WEIGHTING_TAU_1 = 240e-6
DEFAULT_VHS_EXPANDER_WEIGHTING_TAU_2 = 24e-6

# this low pass filter appears in Panasonic AN3664NFB HiFi signal processing chip, however it is not documented in IEC 60774-2
# parameters are guessed
# this may help to remove any high frequency noise interfering with the expander envelope
DEFAULT_VHS_EXPANDER_WEIGHTING_LOW_PASS = 20000
DEFAULT_VHS_EXPANDER_WEIGHTING_LOW_PASS_TRANSITION = 100000

# IEC 60774-2 Figure 5: Noise Reduction Emphasis
DEFAULT_VHS_NR_DEEMPHASIS_TAU_1 = 240e-6
DEFAULT_VHS_NR_DEEMPHASIS_TAU_2 = 56e-6


# *********************
# 8mm (Video 8, Hi 8) Filter Parameters
# *********************
DEFAULT_8MM_EXPANDER_GAIN = 6

# IEC 60843-1 6.5.1.1 Compression Ratio
DEFAULT_8MM_EXPANDER_RATIO = 2 #           2:1 logarithmic

# IEC 60843-1 6.5.1.2 Transient response
DEFAULT_8MM_EXPANDER_ATTACK_TAU = 3e-3 #   3ms +- 0.6ms
DEFAULT_8MM_EXPANDER_HOLD_TAU = 15e-3 #    15ms +- 3ms, gain is held until this time before releasing
DEFAULT_8MM_EXPANDER_RELEASE_TAU = 40e-3 # 40ms +- 3ms

# IEC 60843-1 6.5.1.5 Figure 34 Noise Reduction, System Configuration
# IEC 60843-1 6.5.1.5 Figure 34, Emphasis 1
DEFAULT_8MM_NR_DEEMPHASIS_TAU_1 = 75e-6
DEFAULT_8MM_NR_DEEMPHASIS_TAU_2 = 19e-6

# IEC 60843-1 6.5.1.5 Figure 34, Emphasis 2
DEFAULT_8MM_DEEMPHASIS_TAU_1 = 75e-6
DEFAULT_8MM_DEEMPHASIS_TAU_2 = 27e-6

# IEC 60843-1 6.5.1.5 Figure 34, Weighting
DEFAULT_8MM_EXPANDER_WEIGHTING_TAU_1 = 75e-6
DEFAULT_8MM_EXPANDER_WEIGHTING_TAU_2 = 27e-6

# this low pass filter appears in Panasonic AN3664NFB HiFi signal processing chip, however it is not documented in IEC 60843-1
# parameters are guessed
# this may help to remove any high frequency noise interfering with the expander envelope
DEFAULT_8MM_EXPANDER_WEIGHTING_LOW_PASS = 20000
DEFAULT_8MM_EXPANDER_WEIGHTING_LOW_PASS_TRANSITION = 100000

# set the amount of spectral noise reduction to apply to the signal before deemphasis
DEFAULT_SPECTRAL_NR_AMOUNT = 0.4
DEFAULT_RESAMPLER_QUALITY = "high"
DEFAULT_FINAL_AUDIO_RATE = 48000

# needs to be a power of 2 for effcient fft
DEMOD_HILBERT_IF_RATE = 2**23

DEMOD_QUADRATURE = "quadrature"
DEMOD_HILBERT = "hilbert"
DEFAULT_DEMOD = DEMOD_QUADRATURE