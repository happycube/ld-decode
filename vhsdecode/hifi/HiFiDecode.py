# This currently decodes raw VHS and Video8 HiFi RF.
# It could also do Beta HiFi, CED, LD and other stereo AFM variants,
# It has an interpretation of the noise reduction method described on IEC60774-2/1999

from dataclasses import dataclass
from fractions import Fraction
from math import log, pi, sqrt, ceil, floor
from typing import Tuple
from numpy.typing import NDArray
import sys

import numpy as np
from numba import njit
from scipy.signal import lfilter_zi, filtfilt, lfilter, iirpeak, iirnotch, butter, spectrogram, find_peaks
from scipy.interpolate import interp1d
from scipy.signal.signaltools import hilbert

from noisereduce.spectralgate.nonstationary import SpectralGateNonStationary

from lddecode.utils import unwrap_hilbert
from vhsdecode.addons.FMdeemph import FMDeEmphasisC, gen_shelf
from vhsdecode.addons.chromasep import samplerate_resample
from vhsdecode.addons.gnuradioZMQ import ZMQSend, ZMQ_AVAILABLE
from vhsdecode.utils import firdes_lowpass, firdes_highpass, StackableMA

import matplotlib.pyplot as plt

# lower increases expander strength and decreases overall gain
DEFAULT_NR_ENVELOPE_GAIN = 22
# sets logarithmic slope for the 1:2 expander
DEFAULT_EXPANDER_LOG_STRENGTH = 1.2
# set the amount of spectral noise reduction to apply to the signal before deemphasis
DEFAULT_SPECTRAL_NR_AMOUNT = 0.4
DEFAULT_RESAMPLER_QUALITY = "high"
DEFAULT_FINAL_AUDIO_RATE = 48000
REAL_DTYPE=np.float32

BLOCKS_PER_SECOND = 2

@dataclass
class AFEParamsFront:
    def __init__(self):
        self.cutoff = 3e6
        self.FDC = 1e6
        self.transition_width = 700e3

# assembles the current filter design on a pipe-able filter
class FiltersClass:
    def __init__(self, iir_b, iir_a, samp_rate, dtype=REAL_DTYPE):
        self.iir_b, self.iir_a = iir_b.astype(dtype), iir_a.astype(dtype)
        self.z = lfilter_zi(self.iir_b, self.iir_a)
        self.samp_rate = samp_rate

    def rate(self):
        return self.samp_rate

    def filtfilt(self, data):
        output = filtfilt(self.iir_b, self.iir_a, data)
        return output

    def lfilt(self, data):
        output, self.z = lfilter(self.iir_b, self.iir_a, data, zi=self.z)
        return output

class AFEBandPass:
    def __init__(self, filters_params, sample_rate):
        self.samp_rate = sample_rate
        self.filter_params = filters_params

        iir_lo = firdes_lowpass(self.samp_rate, self.filter_params.cutoff, self.filter_params.transition_width)
        iir_hi = firdes_highpass(self.samp_rate, self.filter_params.FDC, self.filter_params.transition_width)

        # filter_plot(iir_lo[0], iir_lo[1], self.samp_rate, type="lopass", title="Front lopass")
        self.filter_lo = FiltersClass(iir_lo[0], iir_lo[1], self.samp_rate, np.float64)
        self.filter_hi = FiltersClass(iir_hi[0], iir_hi[1], self.samp_rate, np.float64)

    def work(self, data):
        return self.filter_lo.lfilt(self.filter_hi.filtfilt(data))


class LpFilter:
    def __init__(self, sample_rate, cut=20e3, transition=10e3):
        self.samp_rate = sample_rate
        self.cut = cut

        iir_lo = firdes_lowpass(self.samp_rate, self.cut, transition)
        self.filter = FiltersClass(iir_lo[0], iir_lo[1], self.samp_rate)

    def work(self, data):
        return self.filter.lfilt(data)
    
    def filtfilt(self, data):
        return self.filter.filtfilt(data)


@dataclass
class AFEParamsVHS:
    def __init__(self):
        self.maxVCODeviation = 150e3

    @property
    def VCODeviation(self):
        return self.maxVCODeviation


@dataclass
class AFEParamsHi8:
    def __init__(self):
        self.maxVCODeviation = 100e3
        self.LCarrierRef = 1.5e6
        self.RCarrierRef = 1.7e6

    @property
    def VCODeviation(self):
        return self.maxVCODeviation


@dataclass
class AFEParamsPALVHS(AFEParamsVHS):
    def __init__(self):
        super().__init__()
        self.LCarrierRef = 1.4e6
        self.RCarrierRef = 1.8e6
        self.Hfreq = 15.625e3


@dataclass
class AFEParamsNTSCVHS(AFEParamsVHS):
    def __init__(self):
        super().__init__()
        self.LCarrierRef = 1.3e6
        self.RCarrierRef = 1.7e6
        self.Hfreq = 15.750e3


@dataclass
class AFEParamsNTSCHi8(AFEParamsHi8):
    def __init__(self):
        super().__init__()
        self.Hfreq = 15.750e3


@dataclass
class AFEParamsPALHi8(AFEParamsHi8):
    def __init__(self):
        super().__init__()
        self.Hfreq = 15.625e3


class AFEFilterable:
    def __init__(self, filters_params, sample_rate, channel=0):
        self.samp_rate = sample_rate
        self.filter_params = filters_params
        d = abs(self.filter_params.LCarrierRef - self.filter_params.RCarrierRef)
        QL = self.filter_params.LCarrierRef / (4 * self.filter_params.maxVCODeviation)
        QR = self.filter_params.RCarrierRef / (4 * self.filter_params.maxVCODeviation)
        if channel == 0:
            iir_front_peak = iirpeak(
                self.filter_params.LCarrierRef, QL, fs=self.samp_rate
            )
            iir_notch_other = iirnotch(
                self.filter_params.RCarrierRef, QR, fs=self.samp_rate
            )
            iir_notch_image = iirnotch(
                self.filter_params.LCarrierRef - d, QR, fs=self.samp_rate
            )
        else:
            iir_front_peak = iirpeak(
                self.filter_params.RCarrierRef, QR, fs=self.samp_rate
            )
            iir_notch_other = iirnotch(
                self.filter_params.LCarrierRef, QL, fs=self.samp_rate
            )
            iir_notch_image = iirnotch(
                self.filter_params.RCarrierRef - d, QL, fs=self.samp_rate
            )

        self.filter_reject_other = FiltersClass(
            iir_notch_other[0], iir_notch_other[1], self.samp_rate
        )
        self.filter_band = FiltersClass(
            iir_front_peak[0], iir_front_peak[1], self.samp_rate
        )
        self.filter_reject_image = FiltersClass(
            iir_notch_image[0], iir_notch_image[1], self.samp_rate
        )

    def work(self, data):
        return self.filter_band.lfilt(
            self.filter_reject_other.lfilt(self.filter_reject_image.lfilt(data))
        )


class FMdemod:
    def __init__(self, sample_rate, carrier_freerun, type=0):
        self.samp_rate = REAL_DTYPE(sample_rate)
        self.type = type
        self.carrier = carrier_freerun

    def hhtdeFM(self, data):
        return FMdemod.inst_freq(data, self.samp_rate)

    @staticmethod
    def htdeFM(data, samp_rate):
        return unwrap_hilbert(hilbert(data), samp_rate)

    @staticmethod
    @njit(cache=True, fastmath=True, nogil=True)
    def unwrap(p: np.array, discont: float = pi):
        dd = np.diff(p)
        ddmod = np.mod(dd + pi, 2 * pi) - pi
        to_pi_locations = np.where(np.logical_and(ddmod == -pi, dd > 0))
        ddmod[to_pi_locations] = pi
        ph_correct = ddmod - dd
        to_zero_locations = np.where(np.abs(dd) < discont)
        ph_correct[to_zero_locations] = 0
        return p[1] + np.cumsum(ph_correct).astype(REAL_DTYPE)

    @staticmethod
    def unwrap_hilbert(analytic_signal: np.array, sample_rate: REAL_DTYPE):
        instantaneous_phase = FMdemod.unwrap(np.angle(analytic_signal))
        instantaneous_frequency = (
            np.diff(instantaneous_phase) / (2.0 * pi) * sample_rate
        )
        return instantaneous_frequency

    @staticmethod
    def inst_freq(signal: np.ndarray, sample_rate: REAL_DTYPE):
        return FMdemod.unwrap_hilbert(hilbert(signal.real), sample_rate)

    def work(self, data):
        if self.type == 2:
            return self.htdeFM(data, self.samp_rate)
        elif self.type == 1:
            return self.hhtdeFM(data)
        else:
            return FMdemod.inst_freq(data, self.samp_rate)


def tau_as_freq(tau):
    return 1 / (2 * pi * tau)


# Creates a low or high pass shelving filter from two time constants and a db/octave gain
# Where:
#   * T1 is the low shelf frequency
#   * T2 is the high shelf frequency
#   * db/octave is the slope of the shelf at db/octave
#
#   ------\ T1
#          \
#           \ center
#            \
#          T2 \________
#
def build_shelf_filter(direction, t1_low, t2_high, db_per_octave, bandwidth, audio_rate):
    t1_f = tau_as_freq(t1_low)
    t2_f = tau_as_freq(t2_high)

    # find center of the frequencies
    center_f = sqrt(t2_f * t1_f)
    # calculate how many octaves exist between the center and outer frequencies
    # bandwidth = log(t2_f/center_f, 2)

    # calculate total gain between the two frequencies based db per octave
    gain = log(t2_f/t1_f, 2) * db_per_octave

    b, a = gen_shelf(
        center_f,
        gain,
        direction,
        audio_rate,
        bandwidth=bandwidth
    )

    # scale the filter such that the top of the shelf is at 0db gain
    scale_factor = 10 ** (-gain / 20)
    b = [x * scale_factor for x in b]
    
    return b, a

class SpectralNoiseReduction():
    def __init__(
        self,
        audio_rate,
        nr_reduction_amount
    ):
        self.chunk_size=int(audio_rate / BLOCKS_PER_SECOND)
        self.chunk_count = BLOCKS_PER_SECOND
        self.padding=int(self.chunk_size)
        self.nr_reduction_amount = nr_reduction_amount

        self.denoise_params = {
            "y": np.empty(1),
            "sr": audio_rate,
            "chunk_size": self.chunk_size,
            "padding": self.padding,
            "prop_decrease": self.nr_reduction_amount,
            "n_fft": 1024,
            "win_length": None,
            "hop_length": None,
            "time_constant_s": (self.chunk_size * self.chunk_count / 2) / audio_rate, #(self.chunk_size * (self.chunk_count - 1)) / audio_rate,
            "freq_mask_smooth_hz": 500,
            "time_mask_smooth_ms": 50,
            "thresh_n_mult_nonstationary": 2,
            "sigmoid_slope_nonstationary": 10,
            "tmp_folder": None,
            "use_tqdm": False,
            "n_jobs": 1
        }

        self.spectral_gate = SpectralGateNonStationary(**self.denoise_params)

        self.chunks = []

        for i in range(self.chunk_count):
            self.chunks.append(np.zeros(self.chunk_size))

    def _get_chunk(self, audio, chunks):
        chunk = np.zeros((1, self.padding * 2 + self.chunk_size * self.chunk_count), dtype=REAL_DTYPE)
        
        chunks.pop(0)
        chunks.append(audio)

        for i in range(self.chunk_count):
            position = self.padding + self.chunk_size*i
            chunk[:, position : position + len(chunks[i])] = chunks[i]

        return chunk
    
    def _trim_chunk(self, nr, audio_len):
        last_chunk = self.chunk_size * (self.chunk_count-1) + self.padding

        return nr[0][last_chunk:last_chunk+audio_len]
    
    def spectral_nr(self, audio):
        chunk = self._get_chunk(audio, self.chunks)

        nr = self.spectral_gate.spectral_gating_nonstationary(chunk)

        trimmed = self._trim_chunk(nr, len(audio))

        return trimmed

class NoiseReduction:
    def __init__(
        self,
        side_gain: float,
        audio_rate: int = 192000,
        spectral_nr_amount = DEFAULT_SPECTRAL_NR_AMOUNT,
    ):
        self.audio_rate = audio_rate

        # noise reduction envelope tracking constants (this ones might need tweaking)
        self.NR_envelope_gain = side_gain
        # strength of the logarithmic function used to expand the signal
        self.NR_envelope_log_strength = DEFAULT_EXPANDER_LOG_STRENGTH

        self.spectral_nr_amount = spectral_nr_amount

        # values in seconds
        NRenv_attack = 3e-3
        NRenv_release = 70e-3

        self.NR_weighting_attack_Lo_cut = tau_as_freq(NRenv_attack)
        self.NR_weighting_attack_Lo_transition = 1e3
        self.NR_weighting_release_Lo_cut = tau_as_freq(NRenv_release)
        self.NR_weighting_release_Lo_transition = 1e3

        # this is set to avoid high frequency noise to interfere with the NR envelope tracking
        self.NR_Lo_cut = 19e3
        self.NR_Lo_transition = 10e3

        self.nrWeightedLowpass = LpFilter(
            self.audio_rate, cut=self.NR_Lo_cut, transition=self.NR_Lo_transition
        )

        # weighted filter for envelope detector
        self.NR_weighting_T1 = 240e-6
        self.NR_weighting_T2 = 24e-6
        self.NR_weighting_db_per_octave = 2.1

        env_iirb, env_iira = build_shelf_filter(
            "high", 
            self.NR_weighting_T1, 
            self.NR_weighting_T2, 
            self.NR_weighting_db_per_octave,
            1.85,
            self.audio_rate
        )

        self.nrWeightedHighpass = FiltersClass(np.array(env_iirb), np.array(env_iira), self.audio_rate)

        # deemphasis filter for output audio
        self.NR_deemphasis_T1 = 240e-6
        self.NR_deemphasis_T2 = 56e-6
        self.NR_deemphasis_db_per_octave = 6.6

        deemph_b, deemph_a = build_shelf_filter(
            "low", 
            self.NR_deemphasis_T1,
            self.NR_deemphasis_T2,
            self.NR_deemphasis_db_per_octave,
            1.75,
            self.audio_rate
        )

        self.nrDeemphasisLowpass = FiltersClass(np.array(deemph_b), np.array(deemph_a), self.audio_rate)

        # expander attack
        loenv_iirb, loenv_iira = firdes_lowpass(
            self.audio_rate,
            self.NR_weighting_attack_Lo_cut,
            self.NR_weighting_attack_Lo_transition,
        )
        self.envelope_attack_Lowpass = FiltersClass(
            loenv_iirb, loenv_iira, self.audio_rate
        )

        # expander release
        loenvr_iirb, loenvr_iira = firdes_lowpass(
            self.audio_rate,
            self.NR_weighting_release_Lo_cut,
            self.NR_weighting_release_Lo_transition,
        )
        self.envelope_release_Lowpass = FiltersClass(
            loenvr_iirb, loenvr_iira, self.audio_rate
        )

    @staticmethod
    def audio_notch(samp_rate: int, freq: float, audio):
        cancel_shift = int(round(samp_rate / (2 * freq)))
        shift = audio[:-cancel_shift]
        return np.add(audio, np.pad(shift, (cancel_shift, 0), "wrap")) / 2

    @staticmethod
    def audio_notch_stereo(samp_rate: int, freq: float, audioL, audioR):
        return NoiseReduction.audio_notch(
            samp_rate, freq, audioL
        ), NoiseReduction.audio_notch(samp_rate, freq, audioR)
    
    @staticmethod
    @njit(cache=True, fastmath=True, nogil=True)
    def expand(log_strength: float, signal: np.array) -> np.array:
        # detect the envelope and use logarithmic expansion
        rectified = np.abs(signal)
        levels = np.clip(rectified, 0.0, 1.0)
        return np.power(levels, REAL_DTYPE(log_strength))
    
    @staticmethod
    @njit(cache=True, fastmath=True, nogil=True)
    def get_attacks_and_releases(attack: np.array, release: np.array) -> np.array:
        releasing_idx = np.where(attack < release)
        rsC = attack
        for id in releasing_idx:
            rsC[id] = release[id]

        return rsC
    
    @staticmethod
    @njit(cache=True, fastmath=True, nogil=True)
    def apply_gate(rsC: np.array, audio: np.array, nr_env_gain: float) -> np.array:
        # computes a sidechain signal to apply noise reduction
        # TODO If the expander gain is set to high, this gate will always be 1 and defeat the expander.
        #      This would benefit from some auto adjustment to keep the expander curve aligned to the audio.
        #      Perhaps a limiter with slow attack and release would keep the signal within the expander's range.
        gate = np.clip(rsC * nr_env_gain, a_min=0.0, a_max=1.0)
        return np.multiply(audio, gate)
    
    def rs_envelope(self, raw_data):
        # prevent high frequency noise from interfering with envelope detector
        low_pass = self.nrWeightedLowpass.work(raw_data)

        # high pass weighted input to envelope detector
        weighted_high_pass = self.nrWeightedHighpass.lfilt(low_pass)

        return NoiseReduction.expand(self.NR_envelope_log_strength, weighted_high_pass)

    def noise_reduction(self, pre, de_noise):
        # takes the RMS envelope of each audio channel
        audio_env = self.rs_envelope(pre)
        audio_with_deemphasis = self.nrDeemphasisLowpass.lfilt(de_noise)

        attack = self.envelope_attack_Lowpass.lfilt(audio_env)
        release = self.envelope_release_Lowpass.lfilt(audio_env)
        rsC = NoiseReduction.get_attacks_and_releases(attack, release)

        return NoiseReduction.apply_gate(rsC, audio_with_deemphasis, self.NR_envelope_gain)


class HiFiDecode:
    def __init__(self, options=None):
        if options is None:
            options = dict()
        self.options = options
        self.sample_rate: int = options["input_rate"]
        self.rfBandPassParams = AFEParamsFront()
        self.audio_rate: int = 192000
        self.audio_final_rate: int = options["audio_rate"]
        self.decode_mode = options["mode"]
        self.gain = options["gain"]
        # downsamples the if signal to fit within the nyquist cutoff within an integer ratio of the audio rate
        min_if_rate = (self.rfBandPassParams.cutoff + self.rfBandPassParams.transition_width) * 2
        self.if_rate_audio_ratio = ceil(min_if_rate / self.audio_rate)
        self.if_rate: int = self.if_rate_audio_ratio * self.audio_rate

        (
            self.ifresample_numerator,
            self.ifresample_denominator,
            self.audioRes_numerator,
            self.audioRes_denominator,
            self.audioFinal_numerator,
            self.audioFinal_denominator
        ) = self.getResamplingRatios()

        # block overlap and edge discard
        self.blocks_second: int = BLOCKS_PER_SECOND
        self.block_size: int = int(self.sample_rate / self.blocks_second)
        self.block_audio_size: int = int(self.audio_rate / self.blocks_second)

        # trim off peaks at edges of if
        self.pre_trim = 50
        self.block_overlap_audio: int = int(self.audio_rate / (4e2 + self.pre_trim * 2))
        audio_final_rate = (self.options["audio_rate"] / self.audio_rate) * (
            self.audioRes_numerator / self.audioRes_denominator
        )
        self.block_overlap: int = round(
            self.block_overlap_audio
            * self.ifresample_denominator
            / (self.ifresample_numerator * audio_final_rate)
        )

        self.lopassRF = AFEBandPass(self.rfBandPassParams, self.sample_rate)
        a_iirb, a_iira = firdes_lowpass(
            self.if_rate, self.audio_rate * 3 / 4, self.audio_rate / 3, order_limit=10
        )
        self.preAudioResampleL = FiltersClass(a_iirb, a_iira, self.if_rate, np.float64)
        self.preAudioResampleR = FiltersClass(a_iirb, a_iira, self.if_rate, np.float64)

        self.dcCancelL = StackableMA(min_watermark=0, window_average=self.blocks_second)
        self.dcCancelR = StackableMA(min_watermark=0, window_average=self.blocks_second)

        if self.options["resampler_quality"] == "high":
            self.if_resampler_converter = "sinc_medium"
            self.audio_resampler_converter = "sinc_medium"
            self.audio_final_resampler_converter = "sinc_best"
        elif self.options["resampler_quality"] == "medium":
            self.if_resampler_converter = "sinc_fastest"
            self.audio_resampler_converter = "sinc_fastest"
            self.audio_final_resampler_converter = "sinc_medium"
        else: # low
            self.if_resampler_converter = "sinc_fastest"
            self.audio_resampler_converter = "sinc_fastest"
            self.audio_final_resampler_converter = "sinc_fastest"

        # filter_plot(envv_iirb, envv_iira, self.audio_rate, type="bandpass", title="audio_filter")

        if options["format"] == "vhs":
            if options["standard"] == "p":
                self.field_rate = 50
                self.afe_params = AFEParamsPALVHS()
                self.standard = AFEParamsPALVHS()
            else:
                self.field_rate = 59.94
                self.afe_params = AFEParamsNTSCVHS()
                self.standard = AFEParamsNTSCVHS()
        else:
            if options["standard"] == "p":
                self.field_rate = 50
                self.afe_params = AFEParamsPALHi8()
                self.standard = AFEParamsPALHi8()
            else:
                self.field_rate = 59.94
                self.afe_params = AFEParamsNTSCHi8()
                self.standard = AFEParamsNTSCHi8()

        self.headswitch_interpolation_enabled = self.options["head_switching_interpolation"]
        self.headswitch_passes = 2
        self.headswitch_signal_rate = self.audio_rate
        self.headswitch_hz = self.field_rate # frequency used to fit peaks to the expected headswitching interval
        self.headswitch_drift_hz = self.field_rate * 0.1 # +- 10% drift is normal
        self.headswitch_cutoff_freq = 25000 # filter cutoff frequency for peak detection
        # maximum seconds to widen the interpolation based on the strength of the peak
        #   setting too low prevents interpolation from covering the whole pulse
        #   setting too high causes audible artifacts where the interpolation occurs
        self.headswitch_interpolation_padding = 35e-6
        # time range to look for neighboring noise when a head switch event is detected
        # this helps to determine the correct width of the interpolation
        self.headswitch_interpolation_neighbor_range = 200e-6
        hs_b, hs_a = butter(3, self.headswitch_cutoff_freq / (0.5 * self.headswitch_signal_rate), btype='highpass')

        self.afeL, self.afeR, self.fmL, self.fmR = self.afeParams(self.afe_params)
        self.devL, self.devR = 0, 0
        self.afeL, self.afeR, self.fmL, self.fmR = self.updateDemod()

        if self.options["grc"]:
            print(f"Set gnuradio sample rate at {self.if_rate} Hz, type float")
            if ZMQ_AVAILABLE:
                self.grc = ZMQSend()
            else:
                print(
                    "ZMQ library is not available, please install the zmq python library to use this feature!"
                )

        self.audio_process_params = {
            "pre_trim": self.pre_trim,
            "gain": self.gain,
            "decode_mode": self.decode_mode,
            "audio_rate": self.audio_rate,
            "audioRes_numerator": self.audioRes_numerator,
            "audioRes_denominator": self.audioRes_denominator,
            "audio_resampler_converter": self.audio_resampler_converter,
            "audio_final_rate": self.audio_final_rate,
            "audioFinal_numerator": self.audioFinal_numerator,
            "audioFinal_denominator": self.audioFinal_denominator,
            "audio_final_resampler_converter": self.audio_final_resampler_converter,
            "headswitch_interpolation_enabled": self.headswitch_interpolation_enabled,
            "headswitch_passes": self.headswitch_passes,
            "headswitch_signal_rate": self.headswitch_signal_rate,
            "headswitch_hz": self.headswitch_hz,
            "headswitch_drift_hz": self.headswitch_drift_hz,
            "headswitch_cutoff_freq": self.headswitch_cutoff_freq,
            "headswitch_interpolation_padding": self.headswitch_interpolation_padding,
            "headswitch_interpolation_neighbor_range": self.headswitch_interpolation_neighbor_range,
            "hs_b": hs_b,
            "hs_a": hs_a
        }

    def getResamplingRatios(self):
        samplerate2ifrate = self.if_rate / self.sample_rate
        self.ifresample_numerator = Fraction(samplerate2ifrate).numerator
        self.ifresample_denominator = Fraction(samplerate2ifrate).denominator
        assert (
            self.ifresample_numerator > 0
        ), f"IF resampling numerator got 0; sample_rate {self.sample_rate}"
        assert (
            self.ifresample_denominator > 0
        ), f"IF resampling denominator got 0; sample_rate {self.sample_rate}"

        audiorate2ifrate = self.audio_rate / self.if_rate
        self.audioRes_numerator = Fraction(audiorate2ifrate).numerator
        self.audioRes_denominator = Fraction(audiorate2ifrate).denominator

        audiorate2FinalAudioRate = self.audio_final_rate / self.audio_rate
        self.audioFinal_numerator = Fraction(audiorate2FinalAudioRate).numerator
        self.audioFinal_denominator = Fraction(audiorate2FinalAudioRate).denominator
        return (
            self.ifresample_numerator,
            self.ifresample_denominator,
            self.audioRes_numerator,
            self.audioRes_denominator,
            self.audioFinal_numerator,
            self.audioFinal_denominator
        )

    def updateDemod(self):
        self.afeL, self.afeR, self.fmL, self.fmR = self.afeParams(self.afe_params)
        return self.afeL, self.afeR, self.fmL, self.fmR

    def updateStandard(self, devL, devR):
        newLC = self.afe_params.LCarrierRef - round(devL)
        newRC = self.afe_params.RCarrierRef - round(devR)
        self.updateAFE(newLC, newRC)

    def updateAFE(self, newLC, newRC):
        self.afe_params.LCarrierRef = (
            max(
                min(newLC, self.standard.LCarrierRef + 10e3),
                self.standard.LCarrierRef - 10e3,
            )
            if self.options["format"] == "vhs"
            else newLC
        )
        self.afe_params.RCarrierRef = (
            max(
                min(newRC, self.standard.RCarrierRef + 10e3),
                self.standard.RCarrierRef - 10e3,
            )
            if self.options["format"] == "vhs"
            else newRC
        )

    def afeParams(self, standard):
        afeL = AFEFilterable(standard, self.if_rate, 0)
        afeR = AFEFilterable(standard, self.if_rate, 1)
        if self.options["preview"]:
            fmL = FMdemod(self.if_rate, standard.LCarrierRef, 1)
            fmR = FMdemod(self.if_rate, standard.RCarrierRef, 1)
        elif self.options["original"]:
            fmL = FMdemod(self.if_rate, standard.LCarrierRef, 2)
            fmR = FMdemod(self.if_rate, standard.RCarrierRef, 2)
        else:
            fmL = FMdemod(self.if_rate, standard.LCarrierRef, 0)
            fmR = FMdemod(self.if_rate, standard.RCarrierRef, 0)

        return afeL, afeR, fmL, fmR
    
    @staticmethod
    @njit(cache=True, fastmath=True, nogil=True)
    def smooth(data: np.array, half_window: int) -> np.array:
        smoothed_data = data.copy()
    
        for i in range(len(data)):
            start = max(0, i - half_window)
            end = min(len(data), i + half_window + 1)
            smoothed_data[i] = np.mean(data[start:end])  # Apply moving average
    
        return smoothed_data

    @staticmethod
    def headswitch_interpolate_boundaries(
        audio: np.array,
        boundaries: list[Tuple[int, int]]
    ) -> np.array:
        interpolated_signal = np.copy(audio)

        # setup interpolator input by copying and removing any samples that are peaks
        time = np.arange(len(interpolated_signal), dtype=float)
        interpolator_in = np.copy(audio)

        for (start, end) in boundaries:
            time[start:end] = np.nan
            interpolator_in[start:end] = np.nan

        time = time[np.logical_not(np.isnan(time))]
        interpolator_in = interpolator_in[np.logical_not(np.isnan(interpolator_in))]

        # interpolate the gap where the peak was removed
        interpolator = interp1d(time, interpolator_in, kind="linear", copy=False, assume_sorted=True, fill_value="extrapolate")

        for (start, end) in boundaries:
            smoothing_size = 1 + end - start

            # sample and hold inteerpolation if boundaries are beyond this chunk
            if start < 0:
                interpolated_signal[0:end] = interpolated_signal[end]
            elif end > len(audio):
                interpolated_signal[start:len(audio)] = interpolated_signal[start]
            else:
                for i in range(start, end): interpolated_signal[i] = interpolator(i)
                # smooth linear interpolation
                interpolated_signal[start-smoothing_size:end+smoothing_size] = HiFiDecode.smooth(interpolated_signal[start-smoothing_size:end+smoothing_size], ceil(smoothing_size / 4))
    
        return interpolated_signal


    @staticmethod
    @njit(cache=True, fastmath=True, nogil=True)
    def mean_stddev(signal: np.array) -> tuple[float, float]:
        signal_mean = np.mean(signal)
        signal_std_dev = sqrt(np.mean(np.abs(signal - signal_mean)**2))

        return signal_mean, signal_std_dev

    @staticmethod
    def headswitch_detect_peaks(
        audio: np.array,
        audio_process_params: dict,
    ) -> Tuple[list[Tuple[float, float, float, float]], np.array, np.array]:
        # remove audible frequencies to avoid detecting them as peaks
        filtered_signal = filtfilt(audio_process_params["hs_b"], audio_process_params["hs_a"], audio)
        filtered_signal_abs = abs(filtered_signal)

        # detect the peaks that align with the headswitching speed
        # peaks should align roughly to the frame rate of the video system
        # account for small drifts in the head switching pulse (shows up as the sliding dot on video)
        peak_distance_seconds = 1 / (audio_process_params["headswitch_hz"] + audio_process_params["headswitch_drift_hz"])
        peak_centers, peak_center_props = find_peaks(
            filtered_signal_abs, 
            distance=peak_distance_seconds * audio_process_params["headswitch_signal_rate"],
            width=1
        )

        peaks = list(zip(
            peak_centers, 
            peak_center_props["left_ips"], 
            peak_center_props["right_ips"], 
            peak_center_props["prominences"]
        ))

        # using the head switching points, detect neighboring peaks around the headswitching pulse area
        filtered_signal_mean, filtered_signal_std_dev = HiFiDecode.mean_stddev(filtered_signal)

        # a neighboring peak theshold based on stadard deviation
        neighbor_threshold = filtered_signal_mean + filtered_signal_std_dev
        neighbor_search_width = round(audio_process_params["headswitch_interpolation_neighbor_range"] * audio_process_params["headswitch_signal_rate"])

        # search around the center peak for any neighboring noise that is above the threshold
        for (peak_center, peak_start, peak_end, peak_prominence) in peaks.copy():
            start_neighbor = max(0, floor(peak_start - neighbor_search_width))
            end_neighbor = min(ceil(peak_end + neighbor_search_width), len(filtered_signal_abs))

            # search for neighboring peaks and add to the list
            neighbor_peak_centers, neighbor_peak_props = find_peaks(
                filtered_signal_abs[start_neighbor:end_neighbor],
                threshold = neighbor_threshold,
                prominence=0.25,
                distance=1,
                width=1
            )

            for peak_log_neighbor_idx in range(len(neighbor_peak_centers)):
                peaks.append((
                    neighbor_peak_centers[peak_log_neighbor_idx] + start_neighbor,
                    neighbor_peak_props["left_ips"][peak_log_neighbor_idx] + start_neighbor,
                    neighbor_peak_props["right_ips"][peak_log_neighbor_idx] + start_neighbor,
                    neighbor_peak_props["prominences"][peak_log_neighbor_idx]
                ))

        return peaks, filtered_signal, filtered_signal_abs
    
    @staticmethod
    def headswitch_calc_boundaries(
        peaks: list[tuple[int, int, int, float]],
        audio_process_params: dict
    ) -> list[Tuple[int, int]]:
        peak_boundaries = list()

        # scale the peak width depending on how much the peak stands out from the base signal
        # use light scaling for headswtich peaks since they are usually very brief
        padding_samples = round(audio_process_params["headswitch_interpolation_padding"] * audio_process_params["headswitch_signal_rate"])
        for (peak_center, peak_start, peak_end, peak_prominence) in peaks:
            width_padding = peak_prominence * padding_samples
            # start and end peak at its bases
            start = floor(peak_start - width_padding)
            end = ceil(peak_end + width_padding)

            peak_boundaries.append((start, end))

        # merge overlapping or duplicate boundaries
        peak_boundaries.sort(key=lambda x: x[0])
        merged = list()

        for boundary in peak_boundaries:
            if not merged or merged[-1][1] < boundary[0]:
                merged.append(boundary)
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], boundary[1]))

        return merged

    def demodblock(self, data: np.array) -> Tuple[np.array, np.array]:
        filterL = self.afeL.work(data)
        filterR = self.afeR.work(data)

        if self.options["grc"] and ZMQ_AVAILABLE:
            self.grc.send(filterL + filterR)

        # demodulate
        ifL = self.fmL.work(filterL)
        ifR = self.fmR.work(filterR)

        return ifL, ifR

    @property
    def blockSize(self) -> int:
        return self.block_size
    
    @property
    def blockAudioSize(self) -> int:
        return self.block_audio_size

    @property
    def readOverlap(self) -> int:
        return self.block_overlap

    @property
    def audioDiscard(self) -> int:
        return self.block_overlap_audio

    @property
    def sourceRate(self) -> int:
        return int(self.sample_rate)

    @property
    def audioRate(self) -> int:
        return self.audio_rate

    @property
    def notchFreq(self) -> float:
        return self.standard.Hfreq

    def guessBiases(self, blocks):
        meanL, meanR = StackableMA(window_average=len(blocks)), StackableMA(
            window_average=len(blocks)
        )
        for block in blocks:
            data = samplerate_resample(
                block, self.ifresample_numerator, self.ifresample_denominator, self.if_resampler_converter
            )
            preL, preR = self.demodblock(data)
            meanL.push(np.mean(preL))
            meanR.push(np.mean(preR))

        return meanL.pull(), meanR.pull()

    def carrierOffsets(self, standard, cL, cR):
        return standard.LCarrierRef - cL, standard.RCarrierRef - cR
    
    @staticmethod
    def block_decode_worker(decoder, block, current_block):
        return decoder.block_decode(block, current_block)

    @staticmethod
    @njit(cache=True, fastmath=True, nogil=True)
    def cancelDC(audio: np.array) -> Tuple[np.array, float]:
        dc = REAL_DTYPE(np.mean(audio))
        return audio - dc, dc
    
    @staticmethod
    @njit(cache=True, fastmath=True, nogil=True)
    def clip(audio: np.array, clip: float) -> np.array:
        return audio / REAL_DTYPE(clip)
    
    @staticmethod
    def headswitch_remove_noise(audio: np.array, audio_process_params: dict) -> np.array:
        for _ in range(audio_process_params["headswitch_passes"]):
            peaks, filtered_signal, filtered_signal_abs = HiFiDecode.headswitch_detect_peaks(audio, audio_process_params)
            interpolation_boundaries = HiFiDecode.headswitch_calc_boundaries(peaks, audio_process_params)
            audio_interpolated = HiFiDecode.headswitch_interpolate_boundaries(audio, interpolation_boundaries)

            # uncomment to debug head switching pulse detection
            # HiFiDecode.debug_peak_interpolation(audio, filtered_signal, filtered_signal_abs, peaks, interpolation_boundaries, audio_interpolated, audio_process_params["headswitch_signal_rate"])
            # plt.show()
            # sys.exit(0)
        return audio_interpolated
    
    @staticmethod
    def mix_for_mode_stereo(
        l_raw: np.array,
        r_raw: np.array,
        decode_mode: str
    ) -> tuple[np.array, np.array]:
        if decode_mode == "mpx":
            l = np.multiply(np.add(l_raw, r_raw), 0.5)
            r = np.multiply(np.subtract(l_raw, r_raw), 0.5)
        elif decode_mode == "l":
            l = l_raw
            r = l_raw
        elif decode_mode == "r":
            l = r_raw
            r = r_raw
        elif decode_mode == "sum":
            l = np.multiply(np.add(l_raw, r_raw), 0.5)
            r = np.multiply(np.add(l_raw, r_raw), 0.5)
        else:
            l = l_raw
            r = r_raw
    
        return l, r

    @staticmethod
    def adjust_gain(
        audio: np.array,
        gain: float
    ) -> np.array:
        return np.multiply(audio, gain)

    @staticmethod
    def audio_process(audio: np.array, audio_process_params: dict) -> Tuple[np.array, float]:
        audio = samplerate_resample(audio, audio_process_params["audioRes_numerator"], audio_process_params["audioRes_denominator"], audio_process_params["audio_resampler_converter"])
        audio, dc = HiFiDecode.cancelDC(audio)
        audio = HiFiDecode.clip(audio, AFEParamsVHS().VCODeviation)

        if audio_process_params["headswitch_interpolation_enabled"]:
            audio = HiFiDecode.headswitch_remove_noise(audio, audio_process_params)

        if audio_process_params["audio_rate"] != audio_process_params["audio_final_rate"]:
            audio = samplerate_resample(audio, audio_process_params["audioFinal_numerator"], audio_process_params["audioFinal_denominator"], audio_process_params["audio_final_resampler_converter"])

        return audio, dc

    def block_decode(
        self,
        raw_data: NDArray[np.int16]
    ) -> Tuple[int, NDArray[REAL_DTYPE], NDArray[REAL_DTYPE]]:
        # Do a bandpass filter to remove any the video components from the signal.
        raw_data = self.lopassRF.work(raw_data)
        raw_data = raw_data.astype(REAL_DTYPE, copy=False)
        
        data = samplerate_resample(
            raw_data, self.ifresample_numerator, self.ifresample_denominator, converter_type=self.if_resampler_converter
        )
        # uses complex numbers so data comes out as float64
        preL, preR = self.demodblock(data)

        # low pass filter to remove any remaining high frequency noise
        # disabled since it interferes with head switching noise detection
        # preL = self.preAudioResampleL.lfilt(preL)
        # preR = self.preAudioResampleR.lfilt(preR)
        # preL = preL.astype(REAL_DTYPE, copy=False)
        # preR = preR.astype(REAL_DTYPE, copy=False)

        # remove peaks at edges of demodulated audio
        trim = self.if_rate_audio_ratio * self.pre_trim
        preL = preL[trim:-trim]
        preR = preR[trim:-trim]

        # with ProcessPoolExecutor(2) as stereo_executor:
        #     audioL_future = stereo_executor.submit(HiFiDecode.audio_process, preL, self.audio_process_params)
        #     audioR_future = stereo_executor.submit(HiFiDecode.audio_process, preR, self.audio_process_params)
        #     preL, dcL = audioL_future.result()
        #     preR, dcR = audioR_future.result()

        preL, dcL = HiFiDecode.audio_process(preL, self.audio_process_params)
        preR, dcR = HiFiDecode.audio_process(preR, self.audio_process_params)

        preL, preR = HiFiDecode.mix_for_mode_stereo(preL, preR, self.audio_process_params["decode_mode"])

        if self.audio_process_params["gain"] != 1:
            preL = HiFiDecode.adjust_gain(preL, self.audio_process_params["gain"])
            preR = HiFiDecode.adjust_gain(preR, self.audio_process_params["gain"])

        if self.options["auto_fine_tune"]:
            self.devL, self.devR = self.carrierOffsets(self.afe_params, dcL, dcR)
            self.updateStandard(self.devL, self.devR)
            self.updateDemod()

        assert preL.dtype == REAL_DTYPE, f"Audio data must be in {REAL_DTYPE} format, instead got {preL.dtype}"
        assert preR.dtype == REAL_DTYPE, f"Audio data must be in {REAL_DTYPE} format, instead got {preR.dtype}"

        return preL, preR
    
    @staticmethod
    def debug_peak_interpolation(audio, filtered_signal, filtered_signal_abs, peaks, interpolation_boundaries, interpolated, headswitch_signal_rate):
        fs = headswitch_signal_rate
        t = np.arange(0, len(audio)) / fs
        fft_signal = np.fft.fft(audio)
        fft_freqs = np.fft.fftfreq(len(t), 1/fs)
        
        # Only keep the positive half of the frequency spectrum
        positive_freqs = fft_freqs[:len(t)//2]
        positive_fft_signal = np.abs(fft_signal[:len(t)//2])
        
        # Perform the FFT on the filtered signal
        fft_filtered_signal = np.fft.fft(filtered_signal)
        positive_fft_filtered_signal = np.abs(fft_filtered_signal[:len(t)//2])
        
        plt.figure(figsize=(10, 6))
        plt.plot(positive_freqs, positive_fft_signal, label='Original Signal Spectrum')
        plt.plot(positive_freqs, positive_fft_filtered_signal, label='Filtered Signal Spectrum', color='orange')
        plt.title("Frequency Spectrum")
        plt.xlabel('Frequency [Hz]')
        plt.ylabel('Magnitude')
        plt.legend()

        plt.figure(figsize=(10, 6))
        
        plt.subplot(4, 1, 1)
        plt.plot(t, filtered_signal, label='Filtered Signal', color='green')
        plt.title("Filtered Signal")
        plt.xlabel('Time [s]')
        plt.ylabel('Amplitude')
        plt.legend()

        peak_centers = [round(x[0]) for x in peaks]
        peak_starts = [round(x[1]) for x in peaks]
        peak_ends = [round(x[2]) for x in peaks]
        peak_prominences = [x[3] for x in peaks]

        interpolation_starts = [start for start, end in interpolation_boundaries]
        interpolation_ends = [end for start, end in interpolation_boundaries]
        
        plt.subplot(4, 1, 2)
        plt.plot(t, filtered_signal_abs, label='Filtered Signal Absolute Value', color='black')
        plt.plot(t[interpolation_starts], filtered_signal_abs[interpolation_starts], 'r+', label='Interpolation Start')
        plt.plot(t[peak_starts], filtered_signal_abs[peak_starts], 'b+', label='Start')
        plt.plot(t[peak_centers], peak_prominences, 'gx', label='Prominence')
        plt.plot(t[peak_centers], filtered_signal_abs[peak_centers], 'go', label='Center')
        plt.plot(t[peak_ends], filtered_signal_abs[peak_ends], 'bx', label='End')
        plt.plot(t[interpolation_ends], filtered_signal_abs[interpolation_ends], 'rx', label='Interpolation End')
        plt.title("Filtered Signal with head switch points")
        plt.xlabel('Time [s]')
        plt.ylabel('Amplitude')
        plt.legend()

        plt.subplot(4, 1, 3)
        plt.plot(t, interpolated, label='Interpolated audio', color='green')
        plt.title("Interpolated Audio")
        plt.xlabel('Time [s]')
        plt.ylabel('Amplitude')
        plt.legend()


        plt.subplot(4, 1, 4)
        plt.plot(t, audio, label='Original Signal')
        plt.title("Original Signal")
        plt.xlabel('Time [s]')
        plt.ylabel('Amplitude')
        plt.legend()
