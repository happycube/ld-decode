"""RF demodulation front-end (the RFDecode class).

Split verbatim out of core.py.
"""

import copy
import types

import numpy as np
import scipy.fft as npfft
import scipy.interpolate as spi
import scipy.signal as sps
from importlib.resources import files

from .params import (
    BLOCKSIZE,
    FilterParams_NTSC,
    FilterParams_NTSC_lowband,
    FilterParams_PAL,
    FilterParams_PAL_lowband,
    SysParams_NTSC,
    SysParams_PAL,
)
from .filters import (
    build_hilbert,
    calczc,
    emphasis_iir,
    fft_determine_slices,
    fft_do_slice,
    filtfft,
    gen_bpf_supergauss,
    polar2z,
    sqsum,
    unwrap_hilbert,
)
from .dsp import compute_mtf, genwave


try:
    # If Anaconda's numpy is installed, mkl will use all threads for fft etc
    # which doesn't work when we do more threads, do disable that...
    import mkl

    mkl.set_num_threads(1)
except ImportError:
    # If not running Anaconda, we don't care that mkl doesn't exist.
    pass


class RFDecode:
    """The core RF decoding code.

    This decoder uses FFT overlap-save processing(1) to allow for parallel processing and
    combination of operations.

    Video filter signal path:
    - FFT/iFFT stage 1: RF BPF (i.e. 3.5-13.5mhz NTSC) * hilbert filter
    - phase unwrapping
    - FFT stage 2, which is processed into multiple final products:
      - Regular video output
      - 0.5mhz LPF (used for HSYNC)
      - For fine-tuning HSYNC: NTSC: 3.5x mhz filtered signal, PAL: 3.75mhz pilot signal

    Analogue audio filter signal path:

        The audio signal path is actually more complex in some ways, since it reduces a
        multi-msps signal down to <100khz.  A two stage processing system is used which
        reduces the frequency in each stage.

        Stage 1 performs the audio RF demodulation per block typically with 32x decimation,
        while stage 2 is run once the entire frame is demodulated and decimates by 4x.

    EFM filtering simply applies RF front end filters that massage the output so that ld-process-efm
    can do the actual work.

    references:
    1 - https://en.wikipedia.org/wiki/Overlap–save_method

    """

    def __init__(
        self,
        inputfreq               = 40,
        system                  = "NTSC",
        blocklen                = BLOCKSIZE,
        decode_digital_audio    = False,
        decode_analog_audio     = 0,
        has_analog_audio        = True,
        extra_options           = None,
        decoder_params_override = None,
    ):
        """Initialize the RF decoder object.

        inputfreq            -- frequency of raw RF data (in Msps)
                                WARNING: only tested at 40Msps w/other frequencies
                                scaled to 40 in utils.py.
        system               -- Which system is in use (PAL or NTSC)
        blocklen             -- Block length for FFT processing
        decode_digital_audio -- Whether to apply EFM filtering
        decode_analog_audio  -- Whether or not to decode analog(ue) audio
        has_analog_audio     -- Whether or not analog(ue) audio channels are on the disk

        extra_options -- Dictionary of additional options (typically boolean) - these include:
          - PAL_V4300D_NotchFilter - cut 8.5mhz spurious signal
          - NTSC_ColorNotchFilter:  notch filter on decoded video to reduce color 'wobble'
          - lowband: Substitute different decode settings for lower-bandwidth disks
          - AC3: Supports AC3

        """

        if extra_options is None:
            extra_options = {}
        if decoder_params_override is None:
            decoder_params_override = {}

        sinc_lut_path = files(__package__).joinpath("sinc_lut.npz")
        self.downscale_sinc_lut = np.load(sinc_lut_path)["downscale_sinc_lut"]

        # uncomment to regenerate the sinc downscaling lookup table
        # from .utils import build_kaiser_lut, kaiser_beta, sinc_tap_count, sinc_phase_count
        # np.savez_compressed(
        #     sinc_lut_path,
        #     downscale_sinc_lut=build_kaiser_lut(
        #         kaiser_beta, sinc_tap_count, sinc_phase_count
        #     ),
        # )

        self.blocklen     = blocklen
        self.blockcut     = 1024
        self.blockcut_end = 0

        self.system       = system

        self.setupcount   = 0

        self.NTSC_ColorNotchFilter = extra_options.get("NTSC_ColorNotchFilter", False)
        self.PAL_V4300D_NotchFilter = extra_options.get("PAL_V4300D_NotchFilter", False)
        lowband = extra_options.get("lowband", False)

        freq = inputfreq
        self.freq = freq
        self.freq_half = freq / 2
        self.freq_hz = self.freq * 1000000
        self.freq_hz_half = self.freq_hz / 2

        self.mtf_mult   = extra_options.get("MTF_level", 1.0)
        self.mtf_offset = extra_options.get("MTF_offset", 0)

        SYSTEM_PARAMS = {
            "NTSC": (SysParams_NTSC, FilterParams_NTSC, FilterParams_NTSC_lowband),
            "PAL": (SysParams_PAL, FilterParams_PAL, FilterParams_PAL_lowband),
        }

        sys_params, filt_params, filt_params_lb = SYSTEM_PARAMS[system]
        self.SysParams = copy.deepcopy(sys_params)
        self.DecoderParams = copy.deepcopy(filt_params_lb if lowband else filt_params)

        # Make (intentionally) mutable copies of HZ<->IRE levels
        for irekey in ['ire0', 'hz_ire', 'vsync_ire']:
            self.DecoderParams[irekey] = self.SysParams[irekey]

        self.DecoderParams.update(decoder_params_override)

        self.SysParams["analog_audio"] = has_analog_audio
        self.SysParams["AC3"] = extra_options.get("AC3", False)
        if self.SysParams["AC3"]:
            self.SysParams["audio_rfreq"] = self.SysParams["audio_rfreq_AC3"]

        fw = extra_options.get("audio_filterwidth", 0)
        if fw is not None and fw > 0:
            self.DecoderParams['audio_filterwidth'] = fw

        deemp = list(self.DecoderParams["video_deemp"])

        # note that deemp[0] is the t1 (high freuqency) coefficient, and
        # deemp[1] is the t2 (low frequency) one.  These are passed in as
        # microseconds, but are converted to seconds here.

        deemp_low, deemp_high = extra_options.get("deemp_coeff", (0, 0))
        if deemp_low > 0:
            deemp[1] = 1 / (deemp_low  * 1000000)
        if deemp_high > 0:
            deemp[0] = 1 / (deemp_high * 1000000)

        self.DecoderParams["video_deemp"]          = deemp
        self.DecoderParams["video_deemp_strength"] = extra_options.get("deemp_str", 1.0)
        self.DecoderParams["inverse_mtf_strength"] = 0.0

        linelen = self.freq_hz / (1000000.0 / self.SysParams["line_period"])
        self.linelen = int(np.round(linelen))
        self.samplesperline = self.freq / self.linelen

        # How much horizontal sync position can deviate from previous/expected position
        # and still be interpreted as a horizontal sync pulse.
        # Too high tolerance may result in false positive sync pulses, too low may end up missing
        # them.
        # Tapes will need a wider tolerance than laserdiscs due to head switch etc.
        self.hsync_tolerance = 0.4

        self.decode_digital_audio = decode_digital_audio
        self.decode_analog_audio  = decode_analog_audio

        self.computefilters()

        # The 0.5mhz filter is rolled back to align with the data, so there
        # are a few unusable samples at the end.
        self.blockcut_end = self.Filters["F05_offset"]


    def computefilters(self):
        """ (re)compute the filter sets """

        self.setupcount += 1

        self.computevideofilters()

        # This is > 0 because decode_analog_audio is in khz (44.1, 48, 3xHSYNC, etc).
        if self.decode_analog_audio != 0:
            self.computeaudiofilters()

        if self.decode_digital_audio:
            self.computeefmfilter()

        if self.SysParams['AC3']:
            ac3_center = self.SysParams['audio_rfreq_AC3']
            ac3_half_bw = 144000  # 288000 * 0.5

            ac3_range = [(ac3_center - ac3_half_bw) / self.freq_hz_half,
                         (ac3_center + ac3_half_bw) / self.freq_hz_half]

            # This analog audio bandpass filter is an approximation of
            # http://sim.okawa-denshi.jp/en/RLCtool.php with resistor 2200ohm,
            # inductor 180uH, and cap 27pF (taken from Pioneer service manuals)
            # However, the above didn't work, and we wound up with two IIR filters
            # self.Filters['AC3_iir'] = sps.butter(5, [1.48/20, 3.45/20], btype='bandpass')
            self.Filters['AC3_bp1'] = sps.butter(3, [(2.88-.5)/20, (2.88+.5)/20], btype='bandpass')
            self.Filters['AC3_bp2'] = sps.butter(3, ac3_range, btype='bandpass')

            filt1 = filtfft(self.Filters['AC3_bp1'], self.blocklen)
            filt2 = filtfft(self.Filters['AC3_bp2'], self.blocklen)

            self.Filters['AC3'] = filt1 * filt2

        self.computedelays()


    def computeefmfilter(self):
        """Frequency-domain equalisation filter for the LaserDisc EFM signal.
        This was inspired by the input signal equaliser in WSJT-X, described in
        Steven J. Franke and Joseph H. Taylor, "The MSK144 Protocol for
        Meteor-Scatter Communication", QEX July/August 2017.
        <http://physics.princeton.edu/pulsar/k1jt/MSK144_Protocol_QEX.pdf>

        This improved EFM filter was devised by Adam Sampson (@atsampson)
        """

        # Frequency bands
        freqs = np.linspace(0.0e6, 1.9e6, num=11)
        freq_per_bin = self.freq_hz / self.blocklen
        # Amplitude and phase adjustments for each band.
        # These values were adjusted empirically based on a selection of NTSC and PAL samples.
        amp = np.array(
            [0.0, 0.215, 0.41, 0.73, 0.98, 1.03, 0.99, 0.81, 0.59, 0.42, 0.0]
        )
        phase = np.array(
            [0.0, -0.92, -1.03, -1.11, -1.2, -1.2, -1.2, -1.2, -1.05, -0.95, -0.8]
        )
        phase = [p * 1.25 for p in phase]

        # Compute filter coefficients for the given FFTFilter.
        # Anything above the highest frequency is left as zero.
        coeffs = np.zeros(self.blocklen, dtype=complex)

        # Generate the frequency-domain coefficients by cubic interpolation between the equaliser
        # values.
        a_interp = spi.interp1d(freqs, amp, kind="cubic")
        p_interp = spi.interp1d(freqs, phase, kind="cubic")

        nonzero_bins = int(freqs[-1] / freq_per_bin) + 1

        bin_freqs = np.arange(nonzero_bins) * freq_per_bin
        bin_amp = a_interp(bin_freqs)
        bin_phase = p_interp(bin_freqs)

        # Scale by the amplitude, rotate by the phase
        coeffs[:nonzero_bins] = polar2z(bin_amp, -bin_phase)

        self.Filters["Fefm"] = coeffs * 8
        self.Filters["Fefm"] *= gen_bpf_supergauss(20000, 1600000, 60, 20000000, 32768)

    # Lambda-scale functions used to simplify following filter builders

    # Split out the frequency list given to the filter builder
    def freqrange(self, f1, f2):
        return [f1 / self.freq_hz_half, f2 / self.freq_hz_half]

    # Like freqrange, but for notch filters
    def notchrange(self, f, notchwidth, hz = False):
        return [
            (f - notchwidth) / (self.freq_hz_half if hz else self.freq_half),
            (f + notchwidth) / (self.freq_hz_half if hz else self.freq_half)
        ]

    def build_groupdelay_equalizer(self, lpf_fft):
        """All-pass equaliser matching the IEC video group-delay pre-distortion.

        PAL:  IEC 60856 sub-clause 9.1.6
        NTSC: IEC 60857 sub-clause 9.1.7

        The disc is recorded with its video group delay pre-distorted so that
        the playback low-pass filter brings the overall group delay flat across
        the chroma band.  ld-decode's Butterworth video LPF undershoots the
        target, leaving the chroma sidebands sloped, which smears colour and
        contributes to differential phase.

        This returns a unit-magnitude (all-pass) FFT-domain filter whose group
        delay equals target - LPF, so that LPF * equaliser reproduces the spec
        curve.  De-emphasis is deliberately left out of the basis: its group
        delay is cancelled end-to-end by the disc's (inverse) pre-emphasis, so
        only the LPF's deviation needs correcting.
        """
        blocklen = self.blocklen
        fs = self.freq_hz
        binfreq = np.abs(np.fft.fftfreq(blocklen, 1.0 / fs))

        if self.system == "PAL":
            # IEC 60856 9.1.6 target group delay relative to 0.5 MHz, in seconds
            # (the spec tabulates pre-distortion of -10/-35/-85/-135/-200 ns; the
            # playback chain must supply the inverse, held flat above 4.8 MHz).
            gd_f = np.array([0.0, 0.5e6, 2.0e6, 3.0e6, 4.0e6, 4.4336e6, 4.8e6, 5.5e6])
            gd_t = np.array([0.0, 0.0, 10e-9, 35e-9, 85e-9, 135e-9, 200e-9, 200e-9])
        else:
            # IEC 60857 9.1.7 target group delay relative to 0.5 MHz, in seconds
            # (the spec tabulates pre-distortion of -15/-45/-80/-135/-200 ns; the
            # playback chain must supply the inverse, held flat above 4.2 MHz).
            gd_f = np.array([0.0, 0.5e6, 2.0e6, 3.0e6, 3.58e6, 4.0e6, 4.2e6, 4.8e6])
            gd_t = np.array([0.0, 0.0, 15e-9, 45e-9, 80e-9, 135e-9, 200e-9, 200e-9])
        target = np.interp(binfreq, gd_f, gd_t)

        # actual LPF group delay = -d(phase)/d(omega)
        phase = np.unwrap(np.angle(lpf_fft))
        lpf_gd = -np.gradient(phase) / (2 * np.pi * (fs / blocklen))
        i05 = np.argmin(np.abs(binfreq - 0.5e6))
        residual = target - (lpf_gd - lpf_gd[i05])

        # only act across the chroma band; taper to zero ~1.3 MHz past the LPF
        # cut-off (where the LPF has removed the signal) so the equaliser's
        # impulse response stays compact (well inside blockcut).  Tracking the
        # cut-off keeps this correct if video_lpf_freq changes.
        lpf_freq = self.DecoderParams["video_lpf_freq"]
        t0, t1 = lpf_freq + 0.3e6, lpf_freq + 1.3e6
        taper = np.clip((t1 - binfreq) / (t1 - t0), 0.0, 1.0)
        residual = residual * taper
        residual[binfreq < 0.4e6] = 0.0

        # integrate group delay -> phase over the positive half, then mirror for
        # a conjugate-symmetric (real impulse response) all-pass
        half = blocklen // 2
        dphi = -2 * np.pi * np.cumsum(residual[: half + 1]) * (fs / blocklen)
        eq = np.ones(blocklen, dtype=complex)
        eq[: half + 1] = np.exp(1j * dphi)
        eq[half + 1 :] = np.conj(eq[1:half][::-1])
        eq[0] = 1.0
        eq[half] = 1.0  # Nyquist (dead band past the LPF): keep unit-magnitude

        return eq

    def computevideofilters(self):
        self.Filters = {}

        # Use some shorthand to compact the code.
        SF = self.Filters
        SP = self.SysParams
        DP = self.DecoderParams

        # This high pass filter is intended to detect RF dropouts
        Frfhpf = sps.butter(1, 10 / self.freq_half, btype="highpass")
        self.Filters["Frfhpf"] = filtfft(Frfhpf, self.blocklen)

        # First phase FFT filtering

        # MTF filter section
        # compute the pole locations symmetric to freq_half (i.e. 12.2 and 27.8)
        MTF_polef_lo = DP["MTF_freq"] / self.freq_half
        MTF_polef_hi = (
            self.freq_half + (self.freq_half - DP["MTF_freq"])
        ) / self.freq_half

        def to_z(pole):
            return polar2z(DP["MTF_poledist"], np.pi * pole)

        MTF = sps.zpk2tf([], [to_z(MTF_polef_lo), to_z(MTF_polef_hi)], 1)
        SF["MTF"] = filtfft(MTF, self.blocklen)

        # The BPF filter, defined for each system in DecoderParams.
        # When split skirt parameters are available, build as independent
        # high-pass (low edge) + low-pass (high edge) so each can be ordered
        # separately — gentler low edge protects the lower chroma sideband and
        # its group delay, sharper high edge rejects HF noise.
        if "video_bpf_low_order" in DP:
            filt_rfvideo_hp = sps.butter(
                DP["video_bpf_low_order"],
                DP["video_bpf_low"] / self.freq_hz_half,
                btype="highpass",
            )
            filt_rfvideo_lp = sps.butter(
                DP["video_bpf_high_order"],
                DP["video_bpf_high"] / self.freq_hz_half,
                btype="lowpass",
            )
            SF["RFVideo"] = filtfft(filt_rfvideo_hp, self.blocklen) * filtfft(
                filt_rfvideo_lp, self.blocklen
            )
        else:
            filt_rfvideo = sps.butter(
                DP["video_bpf_order"],
                self.freqrange(DP["video_bpf_low"], DP["video_bpf_high"]),
                btype="bandpass",
            )
            SF["RFVideo"] = filtfft(filt_rfvideo, self.blocklen)

        # Notch filters for analog audio RF.  DdD captures on NTSC need this.
        if SP["analog_audio"] and self.system == "NTSC":
            cut_left = sps.butter(
                DP["audio_notchorder"],
                self.notchrange(SP["audio_lfreq"], DP['audio_notchwidth'], True),
                btype="bandstop",
            )
            SF["Fcutl"] = filtfft(cut_left, self.blocklen)

            cut_right = sps.butter(
                DP["audio_notchorder"],
                self.notchrange(SP["audio_rfreq"], DP['audio_notchwidth'], True),
                btype="bandstop",
            )
            SF["Fcutr"] = filtfft(cut_right, self.blocklen)

            SF["RFVideo"] *= SF["Fcutl"] * SF["Fcutr"]

        if DP.get("video_rf_zero_phase", False):
            # Discard the phase response of the pre-demod RF chain (BPF,
            # audio notches, MTF), keeping only its amplitude.  Skirt/notch/
            # pole phase differs at the two chroma sideband locations, and
            # that asymmetry moves with the FM carrier (i.e. with luma),
            # which demodulates as differential phase.  The MTF correction
            # is an amplitude compensation by design, and the FFT
            # overlap-save pipeline makes acausal zero-phase filters free.
            SF["RFVideo"] = np.abs(SF["RFVideo"])
            SF["MTF"] = np.abs(SF["MTF"])

        SF["hilbert"] = build_hilbert(self.blocklen)
        SF["RFVideo"] *= SF["hilbert"]

        # Second phase FFT filtering, which is performed after the signal is demodulated

        video_lpf = sps.butter(
            DP["video_lpf_order"], DP["video_lpf_freq"] / self.freq_hz_half, "low"
        )
        SF["Fvideo_lpf"] = filtfft(video_lpf, self.blocklen)

        if self.system == "NTSC" and self.NTSC_ColorNotchFilter:
            video_notch = sps.butter(
                3,
                [DP["video_lpf_freq"] / 1000000 / self.freq_half, 5.0 / self.freq_half],
                "bandstop",
            )
            SF["Fvideo_lpf"] *= filtfft(video_notch, self.blocklen)

        # The deemphasis filter
        deemp1, deemp2 = DP["video_deemp"]
        SF["Fdeemp"] = filtfft(
            emphasis_iir(deemp1, deemp2, self.freq_hz), self.blocklen
        )

        # The direct opposite of the above, used in test signal generation
        SF["Femp"] = filtfft(emphasis_iir(deemp2, deemp1, self.freq_hz), self.blocklen)

        fsc_hz = SP["fsc_mhz"] * 1e6

        # Inverse-MTF chroma correction: a zero-phase (real-valued) filter
        # whose shape comes from the disc's optical MTF.  Frequencies below
        # ~2 MHz are unity; above, the filter boosts proportionally to the
        # inverse of the MTF, raised to `inverse_mtf_strength`.  At strength 0
        # there is no boost; auto-calibration sets the strength from burst
        # amplitude measurements so that chroma recovers to spec level with
        # zero differential-phase cost (unlike de-emphasis adjustment).
        freq_array = np.abs(np.fft.fftfreq(self.blocklen, 1.0 / self.freq_hz))
        crossover = 2.0e6
        mtf_at_crossover = compute_mtf(crossover, cavframe=0)
        mtf_vals = compute_mtf(freq_array.copy(), cavframe=0)
        mtf_norm = np.clip(mtf_vals / mtf_at_crossover, 0.05, 1.0)
        SF["Finverse_mtf_base"] = 1.0 / mtf_norm

        fsc_bin = int(round(fsc_hz * self.blocklen / self.freq_hz))
        self.inverse_mtf_log_at_fsc = np.log(SF["Finverse_mtf_base"][fsc_bin])

        # Zero-phase magnitude EQ from (freq_hz, dB) anchor points.  Real
        # valued, so it cannot move phase; applied to both the output and
        # burst reference paths so burst-based auto-calibration measures the
        # corrected signal.
        SF["Fvideo_eq"] = self.build_video_eq(DP.get("video_eq"))

        # Post processing: lowpass filter + full de-emphasis + inverse MTF
        # chroma correction + group-delay equaliser.  De-emphasis stays at
        # full strength (1.0) for correct phase; the inverse MTF handles
        # chroma amplitude separately with zero phase contribution.
        SF["FVideo"] = SF["Fvideo_lpf"] * (SF["Fdeemp"] ** DP["video_deemp_strength"])
        SF["FVideo"] = SF["FVideo"] * SF["Fvideo_eq"]

        imtf_strength = DP.get("inverse_mtf_strength", 0.0)
        if imtf_strength > 0:
            SF["FVideo"] = SF["FVideo"] * (SF["Finverse_mtf_base"] ** imtf_strength)

        # Correct the post-demod video group delay to the IEC spec curve the
        # disc was pre-distorted against (PAL: IEC 60856 9.1.6, NTSC: IEC 60857
        # 9.1.7).  The Butterworth LPF alone undershoots the target across the
        # chroma band, smearing colour and contributing to differential phase.
        # This is a pure all-pass, so |FVideo| is unchanged; only the output
        # video path is equalised (the burst/pilot/sync reference paths are
        # left as-is).
        SF["FVideoGD"] = self.build_groupdelay_equalizer(SF["Fvideo_lpf"])
        SF["FVideo"] = SF["FVideo"] * SF["FVideoGD"]

        # additional filters:  0.5mhz and color burst
        # Using an FIR filter here to get a known delay

        F0_5 = sps.firwin(65, [0.5 / self.freq_half], pass_zero=True)
        SF["F05_offset"] = 32 # Reduced because filtfft is half-strength on FIR

        F0_5_fft = filtfft((F0_5, [1.0]), self.blocklen)
        SF["FVideo05"] = SF["Fvideo_lpf"] * SF["Fdeemp"] * F0_5_fft

        Fburst = sps.firwin(81, self.notchrange(SP["fsc_mhz"], 0.2), pass_zero=False)
        SF["FVideoBurst_offset"] = 40

        SF["Fburst"] = filtfft((Fburst, [1.0]), self.blocklen)
        SF["FVideoBurst"] = SF["Fvideo_lpf"] * SF["Fdeemp"] * SF["Fburst"] * SF["Fvideo_eq"]

        # Fold delay compensation into the frequency-domain filters so demodblock
        # doesn't need np.roll (which copies the entire array).  A circular shift
        # of d samples equals multiplying the DFT by exp(j·2π·d·k/N).
        bins = np.arange(self.blocklen)
        SF["FVideo05"] *= np.exp(1j * 2 * np.pi * SF["F05_offset"] * bins / self.blocklen)
        SF["FVideoBurst"] *= np.exp(1j * 2 * np.pi * SF["FVideoBurst_offset"] * bins / self.blocklen)

        if self.system == "PAL":
            SF["Fpilot"] = filtfft(
                sps.butter(
                    1,
                    self.notchrange(SP["pilot_mhz"], 0.1),
                    btype="bandpass",
                ),
                self.blocklen,
            )
            SF["FVideoPilot"] = SF["Fvideo_lpf"] * SF["Fdeemp"] * SF["Fpilot"]

    def recompute_fvideo(self):
        """Rebuild only FVideo after an inverse MTF strength change.

        Much cheaper than computefilters() — doesn't touch audio, EFM,
        delays, or any other filter.  Only the main video output path
        is affected (burst/sync/pilot reference paths are unchanged).
        """
        SF = self.Filters
        DP = self.DecoderParams

        SF["FVideo"] = SF["Fvideo_lpf"] * (SF["Fdeemp"] ** DP["video_deemp_strength"])
        SF["FVideo"] = SF["FVideo"] * SF["Fvideo_eq"]

        imtf_strength = DP.get("inverse_mtf_strength", 0.0)
        if imtf_strength > 0:
            SF["FVideo"] = SF["FVideo"] * (SF["Finverse_mtf_base"] ** imtf_strength)

        SF["FVideo"] = SF["FVideo"] * SF["FVideoGD"]

    def build_video_eq(self, points):
        """Zero-phase magnitude EQ from (freq_hz, gain_db) anchor points.

        Monotone-cubic interpolation in dB vs frequency, pinned to 0 dB at
        DC and held at 0 dB beyond the last anchor + 0.5 MHz.  Returns a
        real-valued array over the FFT bins, so applying it cannot change
        the phase of anything.
        """
        if not points:
            return np.ones(self.blocklen)
        freqs = np.array([0.0] + [p[0] for p in points]
                         + [points[-1][0] + 0.5e6, self.freq_hz_half])
        gains = np.array([0.0] + [p[1] for p in points] + [0.0, 0.0])
        interp = spi.PchipInterpolator(freqs, gains, extrapolate=False)
        freq_array = np.abs(np.fft.fftfreq(self.blocklen, 1.0 / self.freq_hz))
        db = interp(np.clip(freq_array, 0, self.freq_hz_half))
        db = np.nan_to_num(db, nan=0.0)
        return 10.0 ** (db / 20.0)

    def computeaudiofilters(self):
        SP = self.SysParams
        DP = self.DecoderParams

        apass      = DP["audio_filterwidth"]
        afilt_len  = DP["audio_filterorder"]

        self.audio = {}

        for channel, center_freq in zip(['left', 'right'], [SP['audio_lfreq'], SP['audio_rfreq']]):
            self.audio[channel] = types.SimpleNamespace()

            # Build an FIR filter for each channel's RF
            audio1_fir = filtfft(
                [
                    sps.firwin(
                        afilt_len,
                        self.notchrange(center_freq, apass, True),
                        pass_zero=False,
                    ),
                    1.0,
                ],
                self.blocklen,
            )

            # Determine the frequency offset (a1_freq) and bins (lowbin+nbin) that cover the
            # audio RF frequencies for this channel
            self.audio[channel].lowbin, self.audio[channel].nbins, self.audio[channel].a1_freq = (
                fft_determine_slices(center_freq, 200000, self.freq_hz, self.blocklen)
            )
            # Make a lambda to slice the regular block FFT into what we're demodulating
            # note, "ch=channel" is necessary to bind the channel ID to the lambda
            self.audio[channel].slicer = (
                lambda x, ch=channel: fft_do_slice(
                    x, self.audio[ch].lowbin, self.audio[ch].nbins, self.blocklen
                )
            )

            # Build a 'short' hilbert transform around the sliced FFT
            sliced_hilbert = build_hilbert(self.audio[channel].nbins)

            # Add the demodulated output to this to get the actual audio wave frequency
            self.audio[channel].low_freq = (
                self.freq_hz * (self.audio[channel].lowbin / self.blocklen)
            )
            # Finally create the stage 1 demodulation filter (including hilbert transform)
            self.audio[channel].filt1 = self.audio[channel].slicer(audio1_fir) * sliced_hilbert

            # Compute stage 2 audio filters: 20k-ish LPF and deemphasis.
            N, Wn = sps.buttord(
                20000 / (self.audio[channel].a1_freq / 2),
                24000 / (self.audio[channel].a1_freq / 2),
                1,
                9,
            )
            audio2_lpf = filtfft(sps.butter(N, Wn), self.blocklen)
            # 75e-6 is 75usec/2133khz (matching American FM emphasis) and 5.3e-6 is approx.
            # a 30khz break frequency
            audio2_deemp = filtfft(
                emphasis_iir(5.3e-6, 75e-6, self.audio[channel].a1_freq), self.blocklen
            )
            self.audio[channel].audio2_filter = audio2_lpf * audio2_deemp

            # Compute the sample rate decimation caused by stage 1 binning
            self.Filters['audio_fdiv'] = self.blocklen // self.audio[channel].nbins

    def _params(self, spec):
        return self.SysParams if spec else self.DecoderParams

    def iretohz(self, ire, spec=False):
        p = self._params(spec)
        return p["ire0"] + (p["hz_ire"] * ire)

    def hztoire(self, hz, spec=False):
        p = self._params(spec)
        return (hz - p["ire0"]) / p["hz_ire"]

    def demodblock(self, data=None, mtf_level=0, fftdata=None, cut=False,
                   raw_mtf=False):
        # raw_mtf: use mtf_level as-is (delay calibration passes the true
        # filter level); otherwise scale by the disc/player MTF model.
        if not raw_mtf:
            mtf_level = (mtf_level * self.mtf_mult + self.mtf_offset) * self.DecoderParams["MTF_basemult"]
        rv = {}

        if fftdata is not None:
            indata_fft = fftdata
        elif data is not None:
            indata_fft = npfft.fft(data[: self.blocklen])
        else:
            raise Exception("demodblock called without raw or FFT data")

        rotdelay = 0
        if getattr(self, "delays", None) is not None and "video_rot" in self.delays:
            rotdelay = self.delays["video_rot"]

        rv["rfhpf"] = npfft.ifft(indata_fft * self.Filters["Frfhpf"]).real
        rv["rfhpf"] = rv["rfhpf"][
            self.blockcut - rotdelay : -self.blockcut_end - rotdelay
        ].astype(np.float32)

        if self.system == "PAL" and self.PAL_V4300D_NotchFilter:
            # This routine works around an 'interesting' issue seen with LD-V4300D
            # players and some PAL digital audio disks, where there is a signal
            # somewhere between 8.47 and 8.57mhz.
            #
            # The idea here is to look for anomalies (3 std deviations) and snip
            # them out of the FFT.  There may be side effects, however, but
            # generally minor compared to the 'wibble' itself and only in
            # certain cases.
            # Copy before zeroing bins so we don't mutate the caller's FFT array.
            indata_fft = indata_fft.copy()
            sl = slice(
                int(self.blocklen * (8.42 / self.freq)),
                int(1 + (self.blocklen * (8.6 / self.freq))),
            )
            sq_sl = sqsum(indata_fft[sl])
            m = np.mean(sq_sl) + (np.std(sq_sl) * 3)

            for i in np.where(sq_sl > m)[0]:
                indata_fft[(i - 1 + sl.start)] = 0
                indata_fft[(i + sl.start)] = 0
                indata_fft[(i + 1 + sl.start)] = 0
                indata_fft[self.blocklen - (i + sl.start)] = 0
                indata_fft[self.blocklen - (i - 1 + sl.start)] = 0
                indata_fft[self.blocklen - (i + 1 + sl.start)] = 0

        indata_fft_filt = indata_fft * self.Filters["RFVideo"]

        if mtf_level != 0:
            indata_fft_filt *= self.Filters["MTF"] ** mtf_level

        hilbert = npfft.ifft(indata_fft_filt)
        demod = unwrap_hilbert(hilbert, self.freq_hz)

        # use a clipped demod for video output processing to reduce speckling impact
        demod_fft = npfft.fft(np.clip(demod, 1500000, self.freq_hz * 0.75))

        out_video = npfft.ifft(demod_fft * self.Filters["FVideo"]).real

        out_video05 = npfft.ifft(demod_fft * self.Filters["FVideo05"]).real

        out_videoburst = npfft.ifft(demod_fft * self.Filters["FVideoBurst"]).real

        if self.system == "PAL":
            out_videopilot = npfft.ifft(demod_fft * self.Filters["FVideoPilot"]).real
            video_out = np.rec.array(
                [
                    out_video.astype(np.float32),
                    demod.astype(np.float32),
                    out_video05.astype(np.float32),
                    out_videoburst.astype(np.float32),
                    out_videopilot.astype(np.float32),
                ],
                names=[
                    "demod",
                    "demod_raw",
                    "demod_05",
                    "demod_burst",
                    "demod_pilot",
                ],
            )
        else:
            video_out = np.rec.array(
                [
                    out_video.astype(np.float32),
                    demod.astype(np.float32),
                    out_video05.astype(np.float32),
                    out_videoburst.astype(np.float32),
                ],
                names=["demod", "demod_raw", "demod_05", "demod_burst"],
            )

        rv["video"] = (
            video_out[self.blockcut : -self.blockcut_end] if cut else video_out
        )

        if self.decode_digital_audio:
            efm_out = npfft.ifft(indata_fft * self.Filters["Fefm"])
            if cut:
                efm_out = efm_out[self.blockcut : -self.blockcut_end]
            rv["efm"] = np.int16(np.clip(efm_out.real, -32768, 32767))

        # NOTE: ac3 audio is filtered after RF TBC
        if self.decode_analog_audio:
            stage1_out = []
            for channel in ['left', 'right']:
                afilter = self.audio[channel]

                # Apply first stage audio filter
                a1 = npfft.ifft(afilter.slicer(indata_fft) * afilter.filt1)
                # Demodulate and restore frequency after bin slicing
                a1u = unwrap_hilbert(a1, afilter.a1_freq) + afilter.low_freq

                stage1_out.append(a1u.astype(np.float32))

            audio_out = np.rec.array(
                [
                    stage1_out[0].astype(np.float32),
                    stage1_out[1].astype(np.float32),
                ],
                names=["audio_left", "audio_right"],
            )

            fdiv = video_out.shape[0] // audio_out.shape[0]
            rv["audio"] = (
                audio_out[self.blockcut // fdiv : -self.blockcut_end // fdiv]
                if cut
                else audio_out
            )

        rv['setupcount'] = self.setupcount

        return rv

    # Second phase audio filtering.  This works on a whole field's samples, since
    # the frequency has already been reduced.

    def runfilter_audio_phase2(self, frame_audio, start):
        outputs = []

        clipmask = None

        for acname, center_freq, channel in [
            ["audio_left", self.SysParams["audio_lfreq"], "left"],
            ["audio_right", self.SysParams["audio_rfreq"], "right"],
        ]:
            raw = (
                frame_audio[acname][start : start + self.blocklen].copy()
            )
            raw -= center_freq

            if acname == "audio_left":
                # Flag clip/dropout excursions (>500 kHz deviation), widened
                # by 8 samples each side.  The whole excursion is blanked,
                # not just its peak, and the same mask is applied to both
                # channels.
                replacelen = 8
                clipmask = raw > 500000
                if np.any(clipmask):
                    clipmask = np.convolve(
                        clipmask.astype(np.float32),
                        np.ones(2 * replacelen + 1, dtype=np.float32),
                        mode="same",
                    ) > 0

            if clipmask is not None:
                raw[clipmask] = 0

            a2_in_real = raw
            if len(a2_in_real) < len(self.audio[channel].audio2_filter):
                a2_in = np.zeros_like(self.audio[channel].audio2_filter)
                a2_in[: len(a2_in_real)] = a2_in_real
            else:
                a2_in = a2_in_real

            a2_fft = npfft.fft(a2_in)
            fft_out = a2_fft * self.audio[channel].audio2_filter
            output = npfft.ifft(fft_out).real[: len(a2_in_real)] + center_freq

            outputs.append(output)

        return np.rec.array(outputs, names=["audio_left", "audio_right"])

    def audio_phase2(self, field_audio):
        # this creates an output array with left/right channels.
        output_audio2 = np.zeros(
            len(field_audio["audio_left"]),
            dtype=field_audio.dtype,
        )

        # copy the first block in it's entirety, to keep audio and video samples aligned
        tmp = self.runfilter_audio_phase2(field_audio, 0)



        if len(tmp) >= len(output_audio2):
            return tmp[: len(output_audio2)]

        output_audio2[: tmp.shape[0]] = tmp

        end = field_audio.shape[0]

        askip = 512  # length of filters that needs to be chopped out of the ifft
        sjump = self.blocklen - askip

        ostart = tmp.shape[0]
        for sample in range(sjump, field_audio.shape[0] - sjump, sjump):
            tmp = self.runfilter_audio_phase2(field_audio, sample)

            oend = ostart + tmp.shape[0] - askip
            output_audio2[ostart:oend] = tmp[askip:]
            ostart += tmp.shape[0] - askip

        tmp = self.runfilter_audio_phase2(field_audio, end - self.blocklen - 1)
        output_audio2[output_audio2.shape[0] - (tmp.shape[0] - askip) :] = tmp[askip:]

        return output_audio2

    def computedelays(self, mtf_level=0):
        """Generate a fake signal and compute filter delays.

        mtf_level -- Specify the amount of MTF compensation needed (default 0.0)
                     WARNING: May not actually work.
        """

        rf = self

        filterset = rf.Filters
        fakeoutput = np.zeros(rf.blocklen, dtype=np.double)

        # set base level to black
        fakeoutput[:] = rf.iretohz(0)

        synclen_full = int(4.7 * rf.freq)

        # sync 1 (used for gap determination)
        fakeoutput[1500 : 1500 + synclen_full] = rf.iretohz(rf.DecoderParams["vsync_ire"])
        # sync 2 (used for pilot/rot level setting)
        fakeoutput[2000 : 2000 + synclen_full] = rf.iretohz(rf.DecoderParams["vsync_ire"])

        porch_end = 2000 + synclen_full + int(0.6 * rf.freq)
        burst_end = porch_end + int(1.2 * rf.freq)

        rate = np.full(burst_end - porch_end, rf.SysParams["fsc_mhz"], dtype=np.double)
        fakeoutput[porch_end:burst_end] += (
            genwave(rate, rf.freq / 2) * rf.DecoderParams["hz_ire"] * 20
        )

        # white
        fakeoutput[3000:3500] = rf.iretohz(100)

        # white + burst
        fakeoutput[4500:5000] = rf.iretohz(100)

        rate = np.full(5500 - 4200, rf.SysParams["fsc_mhz"], dtype=np.double)
        fakeoutput[4200:5500] += (
            genwave(rate, rf.freq / 2) * rf.DecoderParams["hz_ire"] * 20
        )

        rate = np.full(synclen_full, rf.SysParams["fsc_mhz"], dtype=np.double)
        fakeoutput[2000 : 2000 + synclen_full] = rf.iretohz(
            rf.DecoderParams["vsync_ire"]
        ) + (
            genwave(rate, rf.freq / 2)
            * rf.DecoderParams["hz_ire"]
            * rf.DecoderParams["vsync_ire"]
        )

        # add filters to generate a fake signal

        # NOTE: group pre-delay is not implemented, so the decoded signal
        # has issues settling down.  Emphasis is correct AFAIK

        tmp = npfft.fft(fakeoutput)
        tmp2 = tmp * (filterset["Fvideo_lpf"] ** 1)
        tmp3 = tmp2 * (filterset["Femp"] ** 1)

        fakeoutput_emp = npfft.ifft(tmp3).real

        fakesignal = genwave(fakeoutput_emp, rf.freq_hz / 2)
        fakesignal *= 4096
        fakesignal += 8192
        fakesignal[6000:6005] = 0

        fakedecode = rf.demodblock(fakesignal, mtf_level=mtf_level, raw_mtf=True)

        vdemod = fakedecode["video"]["demod"]
        vdemod_raw = fakedecode["video"]["demod_raw"]
        vsync_cross_hz = rf.iretohz(rf.DecoderParams["vsync_ire"] / 2)

        # XXX: sync detector does NOT reflect actual sync detection, just regular filtering @ sync
        # level
        # (but only regular filtering is needed for DOD)
        rf.delays = {}
        rf.delays["video_sync"] = calczc(vdemod, 1500, vsync_cross_hz, count=512) - 1500
        rf.delays["video_white"] = (
            calczc(vdemod, 3000, rf.iretohz(50), count=512) - 3000
        )
        rf.delays["video_rot"] = int(
            np.round(calczc(vdemod, 6000, rf.iretohz(-10), count=512) - 6000)
        )

        rf.limits = {}
        rf.limits["sync"] = (
            np.min(vdemod_raw[1400:2800]),
            np.max(vdemod_raw[1400:2800]),
        )
        rf.limits["viewable"] = (
            np.min(vdemod_raw[2900:6000]),
            np.max(vdemod_raw[2900:6000]),
        )

        return fakedecode, fakeoutput_emp
