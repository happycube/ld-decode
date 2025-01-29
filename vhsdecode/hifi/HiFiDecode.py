# This currently decodes raw VHS and Video8 HiFi RF.
# It could also do Beta HiFi, CED, LD and other stereo AFM variants,
# It has an interpretation of the noise reduction method described on IEC60774-2/1999

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from fractions import Fraction
from math import log, pi, sqrt
from typing import Tuple

import numpy as np
from numba import njit
from scipy.signal import iirpeak, iirnotch
from scipy.signal.signaltools import hilbert

from noisereduce.spectralgate.nonstationary import SpectralGateNonStationary

from lddecode.utils import unwrap_hilbert
from vhsdecode.addons.FMdeemph import FMDeEmphasisC, gen_shelf
from vhsdecode.addons.chromasep import samplerate_resample
from vhsdecode.addons.gnuradioZMQ import ZMQSend, ZMQ_AVAILABLE
from vhsdecode.utils import firdes_lowpass, firdes_highpass, FiltersClass, StackableMA

# lower increases expander strength and decreases overall gain
DEFAULT_NR_ENVELOPE_GAIN = 26
# increase gain to compensate for deemphasis gain loss
DEFAULT_NR_DEEMPHASIS_GAIN = 1.1
# sets logarithmic slope for the 1:2 expander
DEFAULT_EXPANDER_LOG_STRENGTH = 1.2
# set the amount of spectral noise reduction to apply to the signal before deemphasis
DEFAULT_SPECTRAL_NR_AMOUNT=0.4

BLOCKS_PER_SECOND = 8

@dataclass
class AFEParamsFront:
    def __init__(self):
        self.cutoff = 3e6
        self.FDC = 1e6
        self.transition_width = 700e3


class AFEBandPass:
    def __init__(self, filters_params, sample_rate):
        self.samp_rate = sample_rate
        self.filter_params = filters_params

        iir_lo = firdes_lowpass(self.samp_rate, self.filter_params.cutoff, self.filter_params.transition_width)
        iir_hi = firdes_highpass(self.samp_rate, self.filter_params.FDC, self.filter_params.transition_width)

        # filter_plot(iir_lo[0], iir_lo[1], self.samp_rate, type="lopass", title="Front lopass")
        self.filter_lo = FiltersClass(iir_lo[0], iir_lo[1], self.samp_rate)
        self.filter_hi = FiltersClass(iir_hi[0], iir_hi[1], self.samp_rate)

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
        self.samp_rate = sample_rate
        self.type = type
        self.carrier = carrier_freerun
        self.offset = 0

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
        return p[1] + np.cumsum(ph_correct)

    @staticmethod
    def unwrap_hilbert(analytic_signal: np.array, sample_rate: int):
        instantaneous_phase = FMdemod.unwrap(np.angle(analytic_signal))
        instantaneous_frequency = (
            np.diff(instantaneous_phase) / (2.0 * pi) * sample_rate
        )
        return instantaneous_frequency

    @staticmethod
    def inst_freq(signal: np.ndarray, sample_rate: int):
        return FMdemod.unwrap_hilbert(hilbert(signal.real), sample_rate)

    def work(self, data):
        if self.type == 2:
            return np.add(self.htdeFM(data, self.samp_rate), -self.offset)
        elif self.type == 1:
            return np.add(self.hhtdeFM(data), -self.offset)
        else:
            return np.add(FMdemod.inst_freq(data, self.samp_rate), -self.offset)


def getDeemph(tau, sample_rate):
    deemph = FMDeEmphasisC(sample_rate, tau)
    iir_b, iir_a = deemph.get()
    return FiltersClass(iir_b, iir_a, sample_rate)

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

        self.spectral_gate_left = SpectralGateNonStationary(**self.denoise_params)
        self.spectral_gate_right = SpectralGateNonStationary(**self.denoise_params)

        self.chunks_left = []
        self.chunks_right = []

        for i in range(self.chunk_count):
            self.chunks_left.append(np.zeros(self.chunk_size))
            self.chunks_right.append(np.zeros(self.chunk_size))

    def _get_chunk(self, audio, chunks):
        chunk = np.zeros((1, self.padding * 2 + self.chunk_size * self.chunk_count))
        
        chunks.pop(0)
        chunks.append(audio)

        for i in range(self.chunk_count):
            position = self.padding + self.chunk_size*i
            chunk[:, position : position + len(chunks[i])] = chunks[i]

        return chunk
    
    def _trim_chunk(self, nr, audio_len):
        last_chunk = self.chunk_size * (self.chunk_count-1) + self.padding

        return nr[0][last_chunk:last_chunk+audio_len]
    
    def _nr_channel(self, audio, gate_instance, chunk_instance):
        chunk = self._get_chunk(audio, chunk_instance)
        nr = gate_instance.spectral_gating_nonstationary(chunk)
        trimmed = self._trim_chunk(nr, len(audio))

        return trimmed

    def nr_left(self, audio):        
        return self._nr_channel(audio, self.spectral_gate_left, self.chunks_left)
                
    def nr_right(self, audio):
        return self._nr_channel(audio, self.spectral_gate_right, self.chunks_right)

class NoiseReduction:
    def __init__(
        self,
        notch_freq: float,
        side_gain: float,
        discard_size: int = 0,
        audio_rate: int = 192000,
        spectral_nr_amount = DEFAULT_SPECTRAL_NR_AMOUNT
    ):
        self.audio_rate = audio_rate
        self.discard_size = discard_size
        self.hfreq = notch_freq
        self.spectral_nr_amount = spectral_nr_amount
        self.spectral_nr = SpectralNoiseReduction(audio_rate, self.spectral_nr_amount)

        # noise reduction envelope tracking constants (this ones might need tweaking)
        self.NR_envelope_gain = side_gain
        # strength of the logarithmic function used to expand the signal
        self.NR_envelope_log_strength = DEFAULT_EXPANDER_LOG_STRENGTH

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

        self.nrWeightedLowpassL = LpFilter(
            self.audio_rate, cut=self.NR_Lo_cut, transition=self.NR_Lo_transition
        )
        self.nrWeightedLowpassR = LpFilter(
            self.audio_rate, cut=self.NR_Lo_cut, transition=self.NR_Lo_transition
        )

        # weighted filter for envelope detector
        self.NR_weighting_T1 = 240e-6
        self.NR_weighting_T2 = 24e-6
        self.NR_weighting_db_per_octave = 2.2

        env_iirb, env_iira = build_shelf_filter(
            "high", 
            self.NR_weighting_T1, 
            self.NR_weighting_T2, 
            self.NR_weighting_db_per_octave,
            1.85,
            self.audio_rate
        )

        self.nrWeightedHighpassL = FiltersClass(env_iirb, env_iira, self.audio_rate)
        self.nrWeightedHighpassR = FiltersClass(env_iirb, env_iira, self.audio_rate)

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

        self.nrDeemphasisLowpassL = FiltersClass(deemph_b, deemph_a, self.audio_rate)
        self.nrDeemphasisLowpassR = FiltersClass(deemph_b, deemph_a, self.audio_rate)

        # expander attack
        loenv_iirb, loenv_iira = firdes_lowpass(
            self.audio_rate,
            self.NR_weighting_attack_Lo_cut,
            self.NR_weighting_attack_Lo_transition,
        )
        self.envelope_attack_LowpassL = FiltersClass(
            loenv_iirb, loenv_iira, self.audio_rate
        )
        self.envelope_attack_LowpassR = FiltersClass(
            loenv_iirb, loenv_iira, self.audio_rate
        )

        # expander release
        loenvr_iirb, loenvr_iira = firdes_lowpass(
            self.audio_rate,
            self.NR_weighting_release_Lo_cut,
            self.NR_weighting_release_Lo_transition,
        )
        self.envelope_release_LowpassL = FiltersClass(
            loenvr_iirb, loenvr_iira, self.audio_rate
        )
        self.envelope_release_LowpassR = FiltersClass(
            loenvr_iirb, loenvr_iira, self.audio_rate
        )

    @staticmethod
    def cancelDC(c, dc):
        return c - dc

    @staticmethod
    def cancelDCpair(L, R, dcL, dcR):
        return NoiseReduction.cancelDC(L, dcL), NoiseReduction.cancelDC(R, dcR)

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
    def expand(log_strength, signal):
        # detect the envelope and use logarithmic expansion
        levels = np.clip(np.abs(signal), None, 1)
        return np.power(levels, log_strength)

    def rs_envelope(self, raw_data, channel=0):
        # prevent high frequency noise from interfering with envelope detector
        low_pass = (
            self.nrWeightedLowpassL.work(raw_data)
            if channel == 0 
            else self.nrWeightedLowpassR.work(raw_data)
        )

        # high pass weighted input to envelope detector
        weighted_high_pass = (
            self.nrWeightedHighpassL.lfilt(low_pass)
            if channel == 0
            else self.nrWeightedHighpassR.lfilt(low_pass)
        )

        return NoiseReduction.expand(self.NR_envelope_log_strength, weighted_high_pass)

    def noise_reduction(self, pre, channel=0):
        # takes the RMS envelope of each audio channel
        audio_env = self.rs_envelope(pre, channel)

        rsaC = (
            self.envelope_attack_LowpassL.lfilt(audio_env)
            if channel == 0
            else self.envelope_attack_LowpassR.lfilt(audio_env)
        )
        rsrC = (
            self.envelope_release_LowpassL.lfilt(audio_env)
            if channel == 0
            else self.envelope_release_LowpassR.lfilt(audio_env)
        )

        releasing_idx = np.where(rsaC < rsrC)
        rsC = rsaC
        for id in releasing_idx:
            rsC[id] = rsrC[id]

        # computes a sidechain signal to apply noise reduction
        # TODO If the expander gain is set to high, this gate will always be 1 and defeat the expander.
        #      This would benefit from some auto adjustment to keep the expander curve aligned to the audio.
        #      Perhaps a limiter with slow attack and release would keep the signal within the expander's range.
        gate = np.clip(rsC * self.NR_envelope_gain, a_min=0.0, a_max=1.0)

        audio_with_spectral_nr = (
            self.spectral_nr.nr_left(pre)
            if channel == 0
            else self.spectral_nr.nr_right(pre)
        ) if self.spectral_nr_amount > 0 else pre

        audio_with_deemphasis = (
            self.nrDeemphasisLowpassL.lfilt(audio_with_spectral_nr)
            if channel == 0
            else self.nrDeemphasisLowpassR.lfilt(audio_with_spectral_nr)
        )

        make_up_gain = (DEFAULT_NR_DEEMPHASIS_GAIN + self.spectral_nr_amount * 1.6)

        audio_with_gain = np.clip(audio_with_deemphasis * make_up_gain, a_min=-1.0, a_max=1.0)

        # applies noise reduction
        nr = np.multiply(audio_with_gain, gate)

        return nr

    def noise_reduction_stereo(self, audioL, audioR):
        return self.noise_reduction(audioL, channel=0), self.noise_reduction(
            audioR, channel=1
        )


class HiFiDecode:
    def __init__(self, options=None):
        if options is None:
            options = dict()
        self.options = options
        self.sample_rate: int = options["input_rate"]
        self.options = options
        self.rfBandPassParams = AFEParamsFront()
        # downsamples the if signal to fit within the nyquist cutoff
        self.if_rate: int = (self.rfBandPassParams.cutoff + self.rfBandPassParams.transition_width) * 2
        self.audio_rate: int = 192000

        (
            self.ifresample_numerator,
            self.ifresample_denominator,
            self.audioRes_numerator,
            self.audioRes_denominator,
        ) = self.getResamplingRatios()

        # block overlap and edge discard
        self.blocks_second: int = BLOCKS_PER_SECOND
        self.block_size: int = int(self.sample_rate / self.blocks_second)
        self.block_audio_size: int = int(self.audio_rate / self.blocks_second)
        self.block_overlap_audio: int = int(self.audio_rate / 5e2)
        audio_final_rate = (self.options["audio_rate"] / self.audio_rate) * (
            self.audioRes_numerator / self.audioRes_denominator
        )
        self.block_overlap: int = round(
            self.block_overlap_audio
            * self.ifresample_denominator
            / (self.ifresample_numerator * audio_final_rate)
        )
        
        self.lopassRF = AFEBandPass(self.rfBandPassParams, self.sample_rate)
        self.dcCancelL = StackableMA(min_watermark=0, window_average=self.blocks_second)
        self.dcCancelR = StackableMA(min_watermark=0, window_average=self.blocks_second)

        if self.options["resampler_quality"] == "medium":
            self.if_resampler_converter = "linear"
            self.audio_resampler_converter = "sinc_fastest"

        elif self.options["resampler_quality"] == "high":
            self.if_resampler_converter = "linear"
            self.audio_resampler_converter = "sinc_medium"

        else:
        #if self.options["resampler_quality"] == "low":
            self.if_resampler_converter = "linear"
            self.audio_resampler_converter = "linear"

        # filter_plot(envv_iirb, envv_iira, self.audio_rate, type="bandpass", title="audio_filter")

        if options["format"] == "vhs":
            if options["standard"] == "p":
                self.afe_params = AFEParamsPALVHS()
                self.standard = AFEParamsPALVHS()
            else:
                self.afe_params = AFEParamsNTSCVHS()
                self.standard = AFEParamsNTSCVHS()
        else:
            if options["standard"] == "p":
                self.afe_params = AFEParamsPALHi8()
                self.standard = AFEParamsPALHi8()
            else:
                self.afe_params = AFEParamsNTSCHi8()
                self.standard = AFEParamsNTSCHi8()

        self.afeL, self.afeR, self.fmL, self.fmR = self.afeParams(self.afe_params)
        self.devL, self.devR = 0, 0
        self.afeL, self.afeR, self.fmL, self.fmR = self.updateDemod()

        self.stereo_executor = ThreadPoolExecutor(2)
        self.stereo_queue = list()

        if self.options["grc"]:
            print(f"Set gnuradio sample rate at {self.if_rate} Hz, type float")
            if ZMQ_AVAILABLE:
                self.grc = ZMQSend()
            else:
                print(
                    "ZMQ library is not available, please install the zmq python library to use this feature!"
                )

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
        return (
            self.ifresample_numerator,
            self.ifresample_denominator,
            self.audioRes_numerator,
            self.audioRes_denominator,
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

    def demodblock(self, data):
        filterL = self.afeL.work(data)
        filterR = self.afeR.work(data)

        if self.options["grc"] and ZMQ_AVAILABLE:
            self.grc.send(filterL + filterR)

        # demodulate
        self.stereo_queue.append(self.stereo_executor.submit(self.fmL.work, (filterL)))
        self.stereo_queue.append(self.stereo_executor.submit(self.fmR.work, (filterR)))

        ifL = self.stereo_queue[0].result()
        ifR = self.stereo_queue[1].result()

        self.stereo_queue.clear()

        # resample decoded if to audio rate
        self.stereo_queue.append(self.stereo_executor.submit(
            samplerate_resample, ifL, self.audioRes_numerator, self.audioRes_denominator, converter_type=self.audio_resampler_converter)
        )
        self.stereo_queue.append(self.stereo_executor.submit(
            samplerate_resample, ifR, self.audioRes_numerator, self.audioRes_denominator, converter_type=self.audio_resampler_converter)
        )

        preL = self.stereo_queue[0].result()
        preR = self.stereo_queue[1].result()
        
        self.stereo_queue.clear()

        dcL = np.mean(preL)
        dcR = np.mean(preR)

        return dcL, dcR, preL, preR

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

    @staticmethod
    @njit(cache=True, fastmath=True, nogil=True)
    def cancelDC(c: np.array, dc: np.array):
        return c - dc

    @staticmethod
    def cancelDCpair(L, R, dcL, dcR):
        return HiFiDecode.cancelDC(L, dcL), HiFiDecode.cancelDC(R, dcR)

    def guessBiases(self, blocks):
        meanL, meanR = StackableMA(window_average=len(blocks)), StackableMA(
            window_average=len(blocks)
        )
        for block in blocks:
            lo_data = self.lopassRF.work(block)
            data = samplerate_resample(
                lo_data, self.ifresample_numerator, self.ifresample_denominator
            )
            dcL, dcR, preL, preR = self.demodblock(data)
            meanL.push(np.mean(preL))
            meanR.push(np.mean(preR))

        return meanL.pull(), meanR.pull()

    def carrierOffsets(self, standard, cL, cR):
        return standard.LCarrierRef - cL, standard.RCarrierRef - cR

    def block_decode(
        self, raw_data: np.array, block_count: int = 0
    ) -> Tuple[int, np.array, np.array]:
        lo_data = self.lopassRF.work(raw_data)
        data = samplerate_resample(
            lo_data, self.ifresample_numerator, self.ifresample_denominator, converter_type=self.if_resampler_converter
        )
        dcL, dcR, preL, preR = self.demodblock(data)

        if self.options["auto_fine_tune"]:
            self.devL, self.devR = self.carrierOffsets(self.afe_params, dcL, dcR)
            self.updateStandard(self.devL, self.devR)
            self.updateDemod()

        clip = AFEParamsPALVHS().VCODeviation
        preL, preR = HiFiDecode.cancelDCpair(preL, preR, dcL, dcR)
        preL /= clip
        preR /= clip

        return block_count, preL, preR