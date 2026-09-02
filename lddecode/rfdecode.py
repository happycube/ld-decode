"""RF demodulation front-end (the RFDecode class).

Split verbatim out of core.py.
"""

import copy
import os
import types

import numpy as np
import scipy.fft as npfft
import scipy.interpolate as spi
import scipy.ndimage as ndi
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
        self.PAL_V4300D_CoherentSubtract = extra_options.get("PAL_V4300D_CoherentSubtract", False)
        # Deferred V4300D filtering: keep the spur filter off until sync is
        # acquired (the flat lead-in loses legitimate energy to it and can fail
        # to lock).  The "acquired" signal is a shared threading.Event flipped
        # from the decode loop; the decoder forces serial demod when this is set.
        self.v4300_defer = extra_options.get("V4300_defer", False)
        self._acquired_event = extra_options.get("_acquired_event", None)
        # Cancel the capture/player multi-path reflection ("ghost").  Opt-in via
        # --rf_echo_cancel (auto-detect from the RF cepstrum, re-estimated across
        # the disc) or --rf_echo (manual taps); applies the correction only when
        # it measurably reduces the echo - see _echo_update()/_echo_reestimate().
        # Each worker owns its own RFDecode (hence its own echo state).
        self.rf_echo_cancel = extra_options.get("rf_echo_cancel", False)
        self._echo_inv = None
        self._echo_accum = None      # spur-free RF cepstrum (set at re-estimate)
        self._echo_magacc = None     # magnitude-spectrum EMA
        self._echo_n = 0
        self._echo_manual = bool(
            isinstance(self.rf_echo_cancel, (list, tuple)) and len(self.rf_echo_cancel)
        )
        if self._echo_manual:
            self._echo_inv = self._build_echo_inverse(self.rf_echo_cancel)
        # Time-base-correct the EFM waveform onto the video line time-base before
        # the PLL: removes wow/flutter drift and - crucially for multi-disc
        # stacking - aligns the EFM of different captures of the same disc to a
        # common disc-position time-base so the pre-PLL EFM waveforms can be
        # averaged.  Experimental / off by default: it does NOT improve
        # single-capture decode (output is the same sector set), so it is only
        # useful for aligning captures.  LDDECODE_TBC_EFM=1 or --tbc_efm.
        self.tbc_efm = extra_options.get("tbc_efm", False) or os.environ.get("LDDECODE_TBC_EFM", "") == "1"
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
        if self.system == "PAL":
            # Tuned 2026: boosted-low EFM-peak band (peaks ~0.8MHz, not 1.0MHz).
            # Validated on Domesday/City PAL discs vs the legacy curve below:
            # +146 valid sectors on NationalA, -30% invalid-C1s across National/
            # Community/City, biggest gains on the worst (lowest-SNR) areas, no
            # regression on the cleanest. NTSC keeps the legacy curve (unvalidated).
            amp = np.array(
                [0.0, 0.45, 0.75, 0.95, 1.03, 1.0, 0.9, 0.75, 0.55, 0.35, 0.0]
            )
        else:
            amp = np.array(
                [0.0, 0.215, 0.41, 0.73, 0.98, 1.03, 0.99, 0.81, 0.59, 0.42, 0.0]
            )
        # Sweep override: LDDECODE_EFM_AMP="v0,..,v10" (11 points over 0..1.9MHz)
        _ampenv = os.environ.get("LDDECODE_EFM_AMP", "")
        if _ampenv:
            amp = np.array([float(x) for x in _ampenv.split(",")])
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
        # Super-gaussian band-pass: order = rolloff steepness (60 ~ brick-wall;
        # lower = gentler, less ringing).  Env-tunable for sweeps.
        _sgorder = int(os.environ.get("LDDECODE_EFM_SGORDER", "60"))
        # PAL: 1.75MHz upper edge (IEC 60856 spec value, slightly beats 1.6MHz on
        # the validation discs). NTSC keeps the legacy 1.6MHz edge (unvalidated).
        _sghigh_default = "1750000" if self.system == "PAL" else "1600000"
        _sghigh = float(os.environ.get("LDDECODE_EFM_SGHIGH", _sghigh_default))
        _sglow = float(os.environ.get("LDDECODE_EFM_SGLOW", "20000"))   # low band edge (bandwidth)
        self.Filters["Fefm"] *= gen_bpf_supergauss(_sglow, _sghigh, _sgorder, 20000000, 32768)

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
        # Frfhpf is a real (conjugate-symmetric) filter and the input RF is real,
        # so ifft(indata_fft * Frfhpf).real is exactly irfft over the half spectrum
        # at ~half the transform cost.  Keep the positive-frequency half.
        self.Filters["Frfhpf_half"] = self.Filters["Frfhpf"][: self.blocklen // 2 + 1]

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
        if SP["analog_audio"]:
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

            if self.system == "NTSC":
                SF["RFVideo"] *= SF["Fcutl"] * SF["Fcutr"]
            else:
                # PAL: the carriers sit inside the video FM lower sideband, so
                # the notch is not folded into RFVideo unconditionally; it is
                # applied per block in demodblock, only when the carriers are
                # actually on the disc (pal_audio_carriers_present) - EFM-only
                # discs keep the full sideband.
                SF["FcutPAL"] = SF["Fcutl"] * SF["Fcutr"]

        if DP.get("video_rf_zero_phase", False):
            # Discard the phase response of the pre-demod RF chain (BPF,
            # audio notches, MTF), keeping only its amplitude.  Skirt/notch/
            # pole phase differs at the two chroma sideband locations, and
            # that asymmetry moves with the FM carrier (i.e. with luma),
            # which demodulates as differential phase.  The MTF correction
            # is an amplitude compensation by design, and the FFT
            # overlap-save pipeline makes acausal zero-phase filters free.
            SF["RFVideo"] = np.abs(SF["RFVideo"])
            # Amplitude-only MTF was also tried for NTSC alone
            # (2026-08-31): it removes the DP the MTF poles' phase adds
            # per mtf_level (+1.7 deg at level 1.5 on he010), but the
            # phased response turns out to be load-bearing for FM
            # demodulation there — |MTF|**level loses sync lock
            # entirely at effective exponent ~0.4 at inner radius,
            # where the phased filter is still healthy at 0.6.  Do not
            # re-split this without re-running the he010 offset sweeps.
            SF["MTF"] = np.abs(SF["MTF"])
            if "FcutPAL" in SF:
                # The per-block audio-carrier notch multiplies into the same
                # pre-demod chain, so it must be amplitude-only too: its
                # Butterworth phase alone measures +8/+7 deg of DP on
                # ggv-mb-1khz (deviation from the dp11 original, which only
                # ever exercised the notch on EFM discs where it is a no-op).
                SF["FcutPAL"] = np.abs(SF["FcutPAL"])

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
        self._imtf_2t_gain_cache = {}
        self._veq_2t_gain_cache = {}

        # Zero-phase magnitude EQ from (freq_hz, dB) anchor points.  Real
        # valued, so it cannot move phase; applied to both the output and
        # burst reference paths so burst-based auto-calibration measures the
        # corrected signal.
        SF["Fvideo_eq"] = self.build_video_eq(DP.get("video_eq"))
        # Dynamic per-disc EQ measured from VITS multiburst lines by the
        # decoder's servo (decoder._veq_estimate).  Zero-phase, pinned to
        # 0 dB from DC and beyond its last anchor + 0.5 MHz, so with
        # anchors capped below ~3.6 MHz the chroma band stays owned by
        # the burst-based inverse-MTF calibration.
        SF["Fvideo_eq_auto"] = self.build_video_eq(
            DP.get("video_eq_auto"))

        # Post processing: lowpass filter + full de-emphasis + inverse MTF
        # chroma correction + group-delay equaliser.  De-emphasis stays at
        # full strength (1.0) for correct phase; the inverse MTF handles
        # chroma amplitude separately with zero phase contribution.
        SF["FVideo"] = SF["Fvideo_lpf"] * (SF["Fdeemp"] ** DP["video_deemp_strength"])
        #SF["FVideo"] = SF["FVideo"] * SF["Fvideo_eq"]

        imtf_strength = DP.get("inverse_mtf_strength", 0.0)
        if imtf_strength > 0:
            SF["FVideo"] = SF["FVideo"] * (SF["Finverse_mtf_base"] ** imtf_strength)

        if DP.get("video_eq_auto"):
            SF["FVideo"] = SF["FVideo"] * SF["Fvideo_eq_auto"]

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

        self.build_video_rfft_stack()

    def build_video_rfft_stack(self):
        """Stack the video output filters' positive-frequency halves.

        demod and all four video products are real, so the half spectrum is
        exact (see demodblock).  Keeping them in one contiguous 2-D array lets
        demodblock do a single batched irfft instead of one call per output.
        Must be rebuilt by anything that changes one of these filters --
        recompute_fvideo() does.
        """
        SF = self.Filters
        nr = self.blocklen // 2 + 1

        stack = [SF["FVideo"][:nr], SF["FVideo05"][:nr], SF["FVideoBurst"][:nr]]
        if self.system == "PAL":
            stack.append(SF["FVideoPilot"][:nr])

        SF["FVideo_rfft"] = np.asarray(stack)

    def inverse_mtf_2t_peak_gain(self, strength):
        """Peak gain of the inverse-MTF chroma filter on an ideal 2T pulse.

        The correction filter shapes the whole upper video band, so it
        also lifts the ITS 2T pulse the MTF servo measures; dividing the
        measured pulse-to-bar ratio by this factor decouples the two
        control loops (otherwise: servo raises mtf_level -> burst drops
        -> chroma strength rises -> 2T rises -> servo raises further).
        Computed by passing a sine-squared pulse (HAD = 2 video periods)
        through Finverse_mtf_base ** strength; cached per strength.
        """
        key = round(float(strength), 6)
        g = self._imtf_2t_gain_cache.get(key)
        if g is not None:
            return g
        if key <= 0:
            g = 1.0
        else:
            # 2T sine-squared pulse: full width twice the half-amplitude
            # duration (nominal HAD 200 ns PAL, 250 ns NTSC)
            had_s = 200e-9 if self.system == "PAL" else 250e-9
            n = max(int(round(2 * had_s * self.freq_hz)), 4)
            t = np.arange(n)
            pulse = np.zeros(self.blocklen)
            pulse[:n] = 0.5 * (1 - np.cos(2 * np.pi * t / n))
            out = np.real(np.fft.ifft(
                np.fft.fft(pulse)
                * (self.Filters["Finverse_mtf_base"] ** key)))
            g = float(np.max(out) / np.max(pulse))
        self._imtf_2t_gain_cache[key] = g
        return g

    def inverse_mtf_log_db(self, freq_hz):
        """dB the inverse-MTF filter adds at freq_hz per unit strength.

        The filter is applied as ``Finverse_mtf_base ** strength``, so its
        contribution is linear in strength once expressed in dB.  Callers
        that need to convert a measured response deviation into the
        strength that accounts for it divide by this.
        """
        base = self.Filters.get("Finverse_mtf_base")
        if base is None:
            return 0.0
        index = int(round(freq_hz * self.blocklen / self.freq_hz))
        if not 0 <= index < len(base):
            return 0.0
        return float(20.0 * np.log10(np.abs(base[index])))

    def video_eq_2t_peak_gain(self, points):
        """Peak gain of the dynamic video EQ on an ideal 2T pulse.

        Divided out of the MTF servo's pulse-to-bar measurement so the
        EQ and mtf_level loops stay decoupled (the servo then sees the
        pre-EQ response); analogous to inverse_mtf_2t_peak_gain.
        """
        if not points:
            return 1.0
        key = tuple(points)
        g = self._veq_2t_gain_cache.get(key)
        if g is not None:
            return g
        had_s = 200e-9 if self.system == "PAL" else 250e-9
        n = max(int(round(2 * had_s * self.freq_hz)), 4)
        t = np.arange(n)
        pulse = np.zeros(self.blocklen)
        pulse[:n] = 0.5 * (1 - np.cos(2 * np.pi * t / n))
        out = np.real(np.fft.ifft(
            np.fft.fft(pulse) * self.build_video_eq(list(points))))
        g = float(np.max(out) / np.max(pulse))
        self._veq_2t_gain_cache[key] = g
        return g

    def recompute_fvideo(self):
        """Rebuild only FVideo after an inverse MTF strength change.

        Much cheaper than computefilters() — doesn't touch audio, EFM,
        delays, or any other filter.  Only the main video output path
        is affected (burst/sync/pilot reference paths are unchanged).
        """
        SF = self.Filters
        DP = self.DecoderParams

        SF["FVideo"] = SF["Fvideo_lpf"] * (SF["Fdeemp"] ** DP["video_deemp_strength"])
        # post-equalizer disabled (bd7281e1) — must match computefilters()
        # exactly, or worker processes (which rebuild via computefilters)
        # produce different output than the parent after a recompute here
        #SF["FVideo"] = SF["FVideo"] * SF["Fvideo_eq"]

        imtf_strength = DP.get("inverse_mtf_strength", 0.0)
        if imtf_strength > 0:
            SF["FVideo"] = SF["FVideo"] * (SF["Finverse_mtf_base"] ** imtf_strength)

        SF["Fvideo_eq_auto"] = self.build_video_eq(
            DP.get("video_eq_auto"))
        if DP.get("video_eq_auto"):
            SF["FVideo"] = SF["FVideo"] * SF["Fvideo_eq_auto"]

        SF["FVideo"] = SF["FVideo"] * SF["FVideoGD"]

        self.build_video_rfft_stack()

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

    def v4300d_coherent_subtract(self, indata_fft, maxlines=10):
        """Coherent (PLL-style, but stateless per block) removal of the
        spurious ~8.47-8.57 MHz tone emitted by LD-V4300D players on some PAL
        digital audio discs.

        For each sufficiently prominent spectral line in the window (see
        gating below): refine its frequency to the value that maximises the
        captured single-tone energy, least-squares fit the complex amplitude
        over the block, and subtract the reconstructed sinusoid in the time
        domain.  Unlike bin zeroing this also removes the off-bin spectral
        leakage skirts, and removes nothing else (no holes in the underlying
        video sidebands).  Self-disabling: with no anomalous line present the
        gate never trips and the input FFT is returned unchanged.  Stateless
        per block, so it fits the out-of-order block-cache architecture where a
        tracking PLL would not.

        Gating: static video content puts a comb of legitimate FM sideband
        lines (line-rate spacing) in this window, measuring up to ~27x the
        window's median power on the test captures, so a new line is only
        accepted at >40x median; follow-up cleanup of fit residuals is allowed
        within +-30 kHz of a confirmed line at a relaxed >5x gate.  maxlines
        bounds the loop; blocks without a spur pay only the detection cost."""
        sl = slice(
            int(self.blocklen * (8.42 / self.freq)),
            int(1 + (self.blocklen * (8.6 / self.freq))),
        )
        fpb = self.freq_hz / self.blocklen

        X = indata_fft
        x = None
        lines = []
        for _ in range(maxlines):
            sq_sl = sqsum(X[sl])
            med = np.median(sq_sl)
            if med <= 0:
                break
            k = int(np.argmax(sq_sl))
            ratio = sq_sl[k] / med
            fpeak = (k + sl.start) * fpb
            near_known = any(abs(fpeak - f) < 30e3 for f in lines)
            if not (ratio > 40 or (near_known and ratio > 5)):
                break

            if x is None:
                # enter the time domain on first detection only
                x = npfft.ifft(indata_fft).real.copy()
                n = np.arange(self.blocklen)
                # per-sample phase ramp, so exp(ph * f_hz) is the tone at f_hz
                ph = (-2j * np.pi / self.freq_hz) * n

            # Refine the peak frequency to the value that maximises the captured
            # single-tone energy |P(f)|^2.  Three-point parabolic interpolation
            # of the rectangular-window magnitude is biased ~0.1-0.2 bin, and a
            # 0.2-bin error alone leaves sinc^2(0.2) ~ -9 dB of the tone behind.
            # The true peak lies within +-0.5 bin of the argmax bin, so search a
            # fine grid bracketing it and parabolically interpolate the energy
            # maximum; this pins the frequency to <0.01 bin.
            i = k + sl.start
            grid = i + np.linspace(-0.6, 0.6, 9)
            P = np.exp(np.outer(grid * fpb, ph)) @ x
            mag = P.real ** 2 + P.imag ** 2
            g = int(np.argmax(mag))
            if 0 < g < len(grid) - 1:
                d2 = mag[g - 1] - (2 * mag[g]) + mag[g + 1]
                frac = np.clip(0.5 * (mag[g - 1] - mag[g + 1]) / d2, -1.0, 1.0) if d2 else 0.0
            else:
                frac = 0.0
            fhat = (grid[g] + frac * (grid[1] - grid[0])) * fpb

            # least-squares complex amplitude of the tone at fhat, then subtract
            e = np.exp(ph * fhat)
            amp = np.dot(x, e) / (self.blocklen / 2)
            x -= np.real(amp * np.conj(e))
            lines.append(fhat)

            X = npfft.fft(x)

        return X

    def _build_echo_inverse(self, taps):
        """Stable exact inverse 1/H of the echo channel h = 1 + sum a_i z^-d_i
        (taps are small, so |H| stays bounded away from zero)."""
        h = np.zeros(self.blocklen)
        h[0] = 1.0
        for d, a in taps:
            d = int(round(d))
            if 0 < d < self.blocklen:
                h[d] += a
        return 1.0 / npfft.fft(h)

    # Echo auto-detection tuning (opt-in via --rf_echo_cancel).
    _ECHO_WARMUP = 30      # blocks observed before the first estimate
    _ECHO_REEST = 30       # blocks between re-estimates (continuous adaptation)
    _ECHO_TAU = 30         # magnitude-EMA memory, in blocks
    _ECHO_QMIN = 10        # min quefrency searched
    _ECHO_QMAX = 400       # max quefrency searched
    _ECHO_SPUR_WIN = 129   # bins; wide median window for spur baseline
    _ECHO_SPUR_K = 5.0     # spur if |mag| > K * wide-median baseline
    _ECHO_BASE_WIN = 21    # quefrency window for the cepstral envelope baseline
    _ECHO_PEAK_K = 4.0     # echo peak must exceed K * local cepstral baseline
    _ECHO_FLOOR_K = 6.0    # ...and K * the deep-quefrency noise floor
    _ECHO_MIN_AMP = 0.06   # don't correct echoes fainter than this (ambiguous +
                           # 1/H would boost noise for little visible gain)

    def _echo_despur(self, magacc):
        """Replace narrow spectral spurs (e.g. the LD-V4300D ~8.5 MHz tone) with
        the local baseline so they do not contaminate the cepstrum.  A spur is a
        bin standing far above a *wide* local median (which follows the broad
        video-FM envelope but not a narrow tone); contiguous spur bins are
        linearly interpolated across using their clean neighbours.  Operates on
        the positive half and mirrors, keeping the magnitude even."""
        m = magacc.copy()
        half = len(m) // 2
        pos = m[: half + 1].copy()
        base = ndi.median_filter(pos, size=self._ECHO_SPUR_WIN, mode="nearest")
        spur = pos > self._ECHO_SPUR_K * base
        if spur.any():
            idx = np.where(spur)[0]
            # split into contiguous runs and interpolate each across clean edges
            for run in np.split(idx, np.where(np.diff(idx) > 1)[0] + 1):
                lo, hi = run[0], run[-1]
                a = pos[lo - 1] if lo > 0 else pos[hi + 1]
                b = pos[hi + 1] if hi + 1 <= half else pos[lo - 1]
                pos[lo : hi + 1] = np.interp(np.arange(lo, hi + 1), [lo - 1, hi + 1], [a, b])
        m[: half + 1] = pos
        m[half + 1 :] = pos[1:half][::-1]
        return m

    def _estimate_echo(self, maxechoes=3):
        """Detect echo delays in the spur-free RF cepstrum.  A real echo is an
        *isolated* spike: it must stand above both the deep-quefrency noise floor
        and a local median baseline (the _ECHO_BASE_WIN envelope tracker), so the
        smooth de-emphasis/band-pass envelope - which decays gradually and so
        sits right on its own local baseline - is not picked up as an echo.  The
        cepstrum value at a peak is a first-order amplitude (refined later)."""
        cep = self._echo_accum
        if cep is None:
            return []
        qmin, qmax = self._ECHO_QMIN, self._ECHO_QMAX
        ac = np.abs(cep)
        floor = np.median(ac[80:qmax])
        if floor <= 0:
            return []
        base = ndi.median_filter(ac[: qmax + 2], size=self._ECHO_BASE_WIN, mode="nearest")
        peaks = [(k, float(cep[k])) for k in range(qmin, qmax)
                 if ac[k] > self._ECHO_FLOOR_K * floor
                 and ac[k] > self._ECHO_PEAK_K * base[k]
                 and ac[k] >= ac[k - 1] and ac[k] >= ac[k + 1]]
        peaks.sort(key=lambda t: -abs(t[1]))
        return peaks[:maxechoes]

    def _refine_taps(self, cep, taps, iters=5):
        """Refine the raw cepstral tap amplitudes with a few homomorphic Newton
        steps.  A real echo of amplitude A registers in the real cepstrum as
        only A/2 at its delay (the cosine of the log-spectrum ripple splits to
        +/-d), plus O(A^2) harmonic/cross terms from the whole echo set, so a
        raw cepstral read-out under-corrects ~2x.  Instead we match the *model*
        cepstrum to the measurement at each tap delay; the Newton step converges
        geometrically to the true tap amplitudes (a few iterations -> ~1%)."""
        if not taps:
            return taps
        blocklen = self.blocklen
        refined = [(int(round(d)), float(a)) for d, a in taps
                   if 0 < int(round(d)) < blocklen]
        for _ in range(iters):
            h = np.zeros(blocklen)
            h[0] = 1.0
            for d, a in refined:
                h[d] += a
            c_model = npfft.ifft(np.log(np.abs(npfft.fft(h)) + 1e-12)).real
            refined = [(d, a + (cep[d] - c_model[d])) for d, a in refined]
        return refined

    def _verify_and_build(self, taps, local_margin=0.4, hmin=0.25):
        """Build the echo inverse only if it is worth applying:

        * the strongest tap must be at least _ECHO_MIN_AMP - fainter "echoes"
          are ambiguous (indistinguishable from disc/player structure) and 1/H
          would boost noise for little visible gain, so they are left alone;
        * 1/H must stay well-conditioned (min|H| >= hmin) so it cannot blow up
          noise on a spurious detection;
        * the model must cancel the cepstral energy *at and around the tap
          delays* (and their 2nd harmonics) by at least `local_margin`.  This is
          measured locally, not over the whole band, because the smooth
          de-emphasis/band-pass envelope dominates the low-quefrency band energy
          and would otherwise swamp a genuine echo's contribution.

        Returns the inverse FFT filter, or None to leave the signal untouched
        (the auto path then acts as a no-op)."""
        if not taps:
            return None
        if max(abs(a) for _, a in taps) < self._ECHO_MIN_AMP:
            return None
        blocklen = self.blocklen
        cep = self._echo_accum
        h = np.zeros(blocklen)
        h[0] = 1.0
        for d, a in taps:
            d = int(round(d))
            if 0 < d < blocklen:
                h[d] += a
        Hf = npfft.fft(h)
        if np.min(np.abs(Hf)) < hmin:
            return None
        # cepstrum(1/H) = -cepstrum(H), so the corrected cepstrum is cep - c_model.
        c_model = npfft.ifft(np.log(np.abs(Hf) + 1e-12)).real
        idx = set()
        for d, _ in taps:
            d = int(round(d))
            for q in (d, 2 * d):
                for off in range(-2, 3):
                    k = q + off
                    if self._ECHO_QMIN <= k < self._ECHO_QMAX:
                        idx.add(k)
        idx = np.fromiter(idx, dtype=int)
        e_before = float(np.sum(cep[idx] ** 2))
        e_after = float(np.sum((cep[idx] - c_model[idx]) ** 2))
        if e_before <= 0 or e_after >= (1.0 - local_margin) * e_before:
            return None
        return 1.0 / Hf

    def _echo_reestimate(self):
        """Despur the magnitude EMA, take its cepstrum, detect + refine echo taps
        and (re)build the inverse - or clear it to a no-op when nothing clean is
        found.  Run on the warm-up / re-estimate cadence, not per block."""
        mag = self._echo_despur(self._echo_magacc)
        self._echo_accum = npfft.ifft(np.log(mag + 1e-9)).real
        taps = self._refine_taps(self._echo_accum, self._estimate_echo())
        was_off = self._echo_inv is None
        self._echo_inv = self._verify_and_build(taps)
        if was_off and self._echo_inv is not None:
            # Auto mode runs serial in the main process, so logging is safe
            # here (addition over the dp11 original, which corrects silently).
            from . import utils_logging as logs
            if logs.logger is not None:
                logs.logger.info(
                    "RF echo detected - cancelling taps %s",
                    ", ".join(f"{d}:{a:.3f}" for d, a in taps),
                )

    def _echo_update(self, indata_fft):
        """Observe one block (auto mode), keeping the magnitude spectrum as an
        exponential moving average (memory _ECHO_TAU blocks) so the estimate
        tracks slow echo drift across the disc.  Always called on the *raw*
        spectrum before the inverse is applied, so it never feeds back on
        itself.  The expensive cepstrum/detection only runs on the re-estimate
        cadence in _echo_reestimate(), not every block."""
        m = np.abs(indata_fft)
        self._echo_n += 1
        if self._echo_magacc is None:
            self._echo_magacc = m.astype(np.float64)
        else:
            w = 1.0 / min(self._echo_n, self._ECHO_TAU)
            self._echo_magacc *= (1.0 - w)
            self._echo_magacc += w * m

        n = self._echo_n
        if n >= self._ECHO_WARMUP and (n == self._ECHO_WARMUP or (n % self._ECHO_REEST) == 0):
            self._echo_reestimate()

    def pal_audio_carriers_present(self, indata_fft, threshold=5.0):
        """Detect whether the PAL analog audio FM carriers are present in this
        block, by comparing the mean RF power around each carrier (+-40 kHz,
        covering their FM deviation) against the spectrum flanking it
        (+-100..250 kHz).  Discs with analog audio measure >15x on both
        carriers; discs without (EFM/digital-only) measure ~1x or less, so a
        threshold of 5 separates them cleanly."""
        fpb = self.freq_hz / self.blocklen

        def bandpower(f0, width):
            lo, hi = int((f0 - width) / fpb), int((f0 + width) / fpb) + 1
            return np.mean(sqsum(indata_fft[lo:hi]) ** 2)

        for fcarrier in (self.SysParams["audio_lfreq"], self.SysParams["audio_rfreq"]):
            carrier = bandpower(fcarrier, 40e3)
            flank = (
                bandpower(fcarrier - 175e3, 75e3) + bandpower(fcarrier + 175e3, 75e3)
            ) / 2
            if carrier < threshold * flank:
                return False

        return True

    def apply_v4300d(self, indata_fft):
        """PAL LD-V4300D spur removal, if enabled.  Returns the input FFT
        unchanged (not a copy) when the workaround is off."""

        # In deferred mode the spur filter stays off until sync is acquired
        # (shared event flips for all pipeline threads); see __init__.
        v4300_on = (not self.v4300_defer) or (
            self._acquired_event is not None and self._acquired_event.is_set()
        )

        if self.system != "PAL" or not v4300_on:
            return indata_fft

        if self.PAL_V4300D_CoherentSubtract:
            # Experimental upgrade of the V4300D workaround below: instead of
            # zeroing FFT bins (which leaves the off-bin spectral-leakage skirts
            # of the interfering tone behind), estimate the tone(s) coherently
            # and subtract them in the time domain.  See v4300d_coherent_subtract.
            return self.v4300d_coherent_subtract(indata_fft)

        if not self.PAL_V4300D_NotchFilter:
            return indata_fft

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

        return indata_fft

    def demodblock_sync(self, data=None, fftdata=None, cut=False):
        """Demodulate only the 0.5 MHz path used for vertical-sync detection.

        A stripped-down demodblock for cheap "is there video here?" probes
        (ld-find-start): no audio, EFM, dropout or burst/pilot products, and
        no MTF.  Not a substitute for a real decode.
        """

        if fftdata is not None:
            indata_fft = fftdata
        elif data is not None:
            indata_fft = npfft.fft(data[: self.blocklen])
        else:
            raise Exception("demodblock_sync called without raw or FFT data")

        indata_fft = self.apply_v4300d(indata_fft)

        hilbert = npfft.ifft(indata_fft * self.Filters["RFVideo"])
        demod = unwrap_hilbert(hilbert, self.freq_hz)

        # FVideo05 carries its delay compensation as a phase ramp, so no roll
        # is needed here (see computevideofilters).
        demod_fft = npfft.rfft(np.clip(demod, 1500000, self.freq_hz * 0.75))
        sync = npfft.irfft(
            demod_fft * self.Filters["FVideo05"][: demod_fft.shape[0]],
            n=self.blocklen,
        )

        if cut:
            sync = sync[self.blockcut : -self.blockcut_end]

        return sync.astype(np.float32)

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
            # The RF input is real, so its DFT is conjugate-symmetric.  Use rfft
            # (moves ~half the bytes of a full complex fft) and mirror it back to
            # the full spectrum that demodblock's consumers (hilbert/EFM/audio and
            # the symmetric V4300D notch below) expect.  Byte-identical to
            # npfft.fft(real); helps under the memory-bandwidth contention of
            # parallel decodes.
            raw = data[: self.blocklen]
            nfft = raw.shape[0]
            half = npfft.rfft(raw)
            nr = half.shape[0]
            full = np.empty(nfft, dtype=half.dtype)
            full[:nr] = half
            full[nr:] = np.conj(half[1:nfft - nr + 1])[::-1]
            indata_fft = full
        else:
            raise Exception("demodblock called without raw or FFT data")

        if self.rf_echo_cancel:
            if not self._echo_manual:
                self._echo_update(indata_fft)
            if self._echo_inv is not None:
                indata_fft = indata_fft * self._echo_inv

        rotdelay = 0
        if getattr(self, "delays", None) is not None and "video_rot" in self.delays:
            rotdelay = self.delays["video_rot"]

        # Real filter + real RF input => half-spectrum irfft is exact (see
        # computevideofilters).
        nrf = indata_fft.shape[0] // 2 + 1
        rv["rfhpf"] = npfft.irfft(
            indata_fft[:nrf] * self.Filters["Frfhpf_half"], n=self.blocklen
        )
        rv["rfhpf"] = rv["rfhpf"][
            self.blockcut - rotdelay : -self.blockcut_end - rotdelay
        ].astype(np.float32)

        indata_fft = self.apply_v4300d(indata_fft)

        indata_fft_filt = indata_fft * self.Filters["RFVideo"]

        # PAL: notch the analog audio carriers out of the video path, but only
        # when they're actually on the disc (see computevideofilters)
        if "FcutPAL" in self.Filters and self.pal_audio_carriers_present(indata_fft):
            indata_fft_filt = indata_fft_filt * self.Filters["FcutPAL"]

        if mtf_level != 0:
            indata_fft_filt *= self.Filters["MTF"] ** mtf_level

        hilbert = npfft.ifft(indata_fft_filt)
        demod = unwrap_hilbert(hilbert, self.freq_hz)

        # use a clipped demod for video output processing to reduce speckling impact.
        # demod is real and these video outputs are real, so the half-spectrum
        # rfft/irfft pair is mathematically identical to fft/ifft.real (the filters
        # are conjugate-symmetric) at ~2.3x the speed of the full complex transforms.
        # All four products share demod's transform, so filter and invert them
        # together in one batched irfft (see build_video_rfft_stack).
        demod_fft = npfft.rfft(np.clip(demod, 1500000, self.freq_hz * 0.75))
        bl = self.blocklen

        video_results = npfft.irfft(
            demod_fft * self.Filters["FVideo_rfft"], n=bl, axis=1
        )

        out_video, out_video05, out_videoburst = video_results[:3]

        if self.system == "PAL":
            out_videopilot = video_results[3]
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

        # NOTE: AC3 RF is demodulated from the raw input samples at write time
        # (see LDdecode.AC3demodulate), not from the demod outputs here.
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
        # A rot (the 5 zeroed samples above) demodulates as a phase glitch
        # whose shape depends chaotically on the exact carrier phases at
        # the cut - i.e. on the calibrated decode parameters.  It can
        # swing far below baseline, barely below it, or mostly ABOVE it:
        # one disc's post-AGC snapshot (hz_ire +1.5%, vsync_ire -37.59)
        # produced a dip bottoming at 7.99 MHz - above the fixed -10 IRE
        # threshold this code used to look for, so calczc() found no
        # crossing and worker spawns crashed - while spiking up to
        # 10.9 MHz.  Detect the glitch onset against its own amplitude
        # instead: the first sample deviating from the local baseline by
        # more than 20% of the peak deviation, in either direction.  (20%
        # sits early on the glitch's rise: across AGC-range parameter
        # sweeps the onset stays within a few samples, where a half-peak
        # threshold latches onto whichever ringing lobe happens to
        # dominate and jitters by 10+.)
        rot_base = np.median(vdemod[5900:5990])
        rot_dev = np.abs(vdemod[6000:6512] - rot_base)
        rf.delays["video_rot"] = int(np.argmax(rot_dev > 0.2 * rot_dev.max()))

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
