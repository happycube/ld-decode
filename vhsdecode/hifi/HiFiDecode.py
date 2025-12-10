# This currently decodes raw VHS and Video8 HiFi RF.
# It could also do Beta HiFi, CED, LD and other stereo AFM variants,
# It has an interpretation of the noise reduction method described on IEC60774-2/1999

from dataclasses import dataclass
from fractions import Fraction
from math import log, pi, sqrt, ceil, floor, atan2, log1p, cos, sin, lcm, exp
from typing import Tuple
from time import perf_counter
from setproctitle import setproctitle
from multiprocessing import current_process
from copy import deepcopy
import string
from random import SystemRandom

import atexit

import numpy as np
import numba
from numba import njit, guvectorize
from scipy.signal import (
    lfilter_zi,
    filtfilt,
    lfilter,
    iirpeak,
    iirnotch,
    butter,
    stft,
    istft,
    fftconvolve,
    find_peaks,
    freqz
)
from scipy.interpolate import interp1d
from soxr import ResampleStream, resample

from noisereduce.spectralgate.nonstationary import SpectralGateNonStationary

from vhsdecode.addons.FMdeemph import gen_shelf
from vhsdecode.addons.gnuradioZMQ import ZMQSend, ZMQ_AVAILABLE
from vhsdecode.utils import firdes_lowpass, firdes_highpass, StackableMA

from vhsdecode.hifi.TimeProgressBar import TimeProgressBar
from vhsdecode.hifi.utils import DecoderSharedMemory, NumbaAudioArray

import matplotlib.pyplot as plt


# lower increases expander strength and decreases overall gain
DEFAULT_EXPANDER_GAIN = 20
DEFAULT_EXPANDER_RATIO = 2
DEFAULT_EXPANDER_ATTACK_TAU = 5e-3
DEFAULT_EXPANDER_RELEASE_TAU = 70e-3

# TAU_1         low end of shelf curve
# TAU_2         high end of shelf curve
# DB_PER_OCTAVE slope of the filter

# High shelf filter filter for weighted input to expander
DEFAULT_VHS_EXPANDER_WEIGHTING_TAU_1 = 240e-6
DEFAULT_VHS_EXPANDER_WEIGHTING_TAU_2 = 6.4e-5
DEFAULT_VHS_EXPANDER_WEIGHTING_DB_PER_OCTAVE = 6
DEFAULT_VHS_EXPANDER_WEIGHTING_BANDWIDTH = 2.58

DEFAULT_8MM_EXPANDER_WEIGHTING_TAU_1 = 5.5e-5
DEFAULT_8MM_EXPANDER_WEIGHTING_TAU_2 = 2.35e-5
DEFAULT_8MM_EXPANDER_WEIGHTING_DB_PER_OCTAVE = 6
DEFAULT_8MM_EXPANDER_WEIGHTING_BANDWIDTH = 2.4

# Low shelf filter for deemphasis
DEFAULT_VHS_DEEMPHASIS_TAU_1 = 230e-6
DEFAULT_VHS_DEEMPHASIS_TAU_2 = 21.8e-6
DEFAULT_VHS_DEEMPHASIS_DB_PER_OCTAVE = 6
DEFAULT_VHS_DEEMPHASIS_BANDWIDTH = 2.9

DEFAULT_8MM_DEEMPHASIS_TAU_1 = 1.1e-4
DEFAULT_8MM_DEEMPHASIS_TAU_2 = 1.3e-5
DEFAULT_8MM_DEEMPHASIS_DB_PER_OCTAVE = 6
DEFAULT_8MM_DEEMPHASIS_BANDWIDTH = 2.4

# set the amount of spectral noise reduction to apply to the signal before deemphasis
DEFAULT_SPECTRAL_NR_AMOUNT = 0.4
DEFAULT_RESAMPLER_QUALITY = "high"
DEFAULT_FINAL_AUDIO_RATE = 48000

# needs to be a power of 2 for effcient fft
DEMOD_HILBERT_IF_RATE = 2**23

# audio processing precision
REAL_DTYPE = np.float32

# demodulation section precision
DEMOD_DTYPE_NP = np.float64
DEMOD_DTYPE_NB = numba.types.float64

DEMOD_QUADRATURE = "quadrature"
DEMOD_HILBERT = "hilbert"
DEFAULT_DEMOD = DEMOD_QUADRATURE

BLOCKS_PER_SECOND = 2


@dataclass
class AFEParamsFront:
    def __init__(self):
        self.cutoff = 3e6
        self.FDC = 1e6
        self.transition_width = 700e3


# assembles the current filter design on a pipe-able filter
class FiltersClass:
    def __init__(self, iir_b, iir_a, dtype=REAL_DTYPE):
        self.iir_b, self.iir_a = iir_b.astype(dtype), iir_a.astype(dtype)
        self.z = lfilter_zi(self.iir_b, self.iir_a)

    def filtfilt(self, data):
        return filtfilt(self.iir_b, self.iir_a, data)

    def lfilt(self, data):
        output, self.z = lfilter(self.iir_b, self.iir_a, data, zi=self.z)
        return output


class AFEBandPass:
    def __init__(self, filters_params, sample_rate):
        self.samp_rate = sample_rate
        self.filter_params = filters_params

        iir_lo = firdes_lowpass(
            self.samp_rate,
            self.filter_params.cutoff,
            self.filter_params.transition_width,
        )
        iir_hi = firdes_highpass(
            self.samp_rate, self.filter_params.FDC, self.filter_params.transition_width
        )

        # filter_plot(iir_lo[0], iir_lo[1], self.samp_rate, type="lopass", title="Front lopass")
        self.filter_lo = FiltersClass(iir_lo[0], iir_lo[1], dtype=np.float64)
        self.filter_hi = FiltersClass(iir_hi[0], iir_hi[1], dtype=np.float64)

    def work(self, data):
        return self.filter_lo.lfilt(self.filter_hi.filtfilt(data))


@dataclass
class AFEParamsVHS:
    def __init__(self):
        self.VCODeviation = 150e3


@dataclass
class AFEParams8mm:
    def __init__(self):
        self.VCODeviation = 100e3
        self.LCarrierRef = 1.5e6
        self.RCarrierRef = 1.7e6


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
class AFEParamsNTSC8mm(AFEParams8mm):
    def __init__(self):
        super().__init__()
        self.Hfreq = 15.750e3


@dataclass
class AFEParamsPAL8mm(AFEParams8mm):
    def __init__(self):
        super().__init__()
        self.Hfreq = 15.625e3


class AFEFilterable:
    def __init__(self, filters_params, sample_rate, channel=0):
        self.samp_rate = sample_rate
        self.filter_params = filters_params
        d = abs(self.filter_params.LCarrierRef - self.filter_params.RCarrierRef)
        QL = self.filter_params.LCarrierRef / (4 * self.filter_params.VCODeviation)
        QR = self.filter_params.RCarrierRef / (4 * self.filter_params.VCODeviation)
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
            iir_notch_other[0], iir_notch_other[1], dtype=DEMOD_DTYPE_NP
        )
        self.filter_band = FiltersClass(
            iir_front_peak[0], iir_front_peak[1], dtype=DEMOD_DTYPE_NP
        )
        self.filter_reject_image = FiltersClass(
            iir_notch_image[0], iir_notch_image[1], dtype=DEMOD_DTYPE_NP
        )

    def work(self, data):
        return self.filter_band.filtfilt(
            self.filter_reject_other.filtfilt(self.filter_reject_image.filtfilt(data))
        )

QUADRATURE_LP_ORDER = 5

class FMdemod:
    def __init__(
        self, sample_rate, carrier_center, deviation, max_iq_len, type
    ):
        self.sample_rate = np.int32(sample_rate)
        self.carrier = np.int32(round(carrier_center))
        self.deviation = np.int32(deviation)
        self.type = type
        
        float_info = np.finfo(np.float32)
        self.max_float = float_info.max - float_info.eps
        self.min_float = float_info.min + float_info.epsneg

        if self.type == DEMOD_QUADRATURE:
            quadrature_lp_b, quadrature_lp_a = butter(QUADRATURE_LP_ORDER, self.carrier / self.sample_rate / 2)
            self.quadrature_lp_b = quadrature_lp_b.astype(DEMOD_DTYPE_NP)
            self.quadrature_lp_a = quadrature_lp_a.astype(DEMOD_DTYPE_NP)
        
            iq_len = self._get_min_iq_length(max_iq_len)
            self.i_osc = np.empty(iq_len, dtype=DEMOD_DTYPE_NP)
            self.q_osc = np.empty(iq_len, dtype=DEMOD_DTYPE_NP)
            FMdemod._generate_iq_oscillators(
                self.i_osc,
                self.q_osc,
                self.carrier,
                self.sample_rate
            )

    def _get_min_iq_length(self, max_iq_len):
        # calculates the minimum i/q oscillator size to avoid discontinuities
        samples_per_period = self.sample_rate / self.carrier
        min_periods = lcm(self.sample_rate, self.carrier) / self.sample_rate
        min_samples = int(samples_per_period * min_periods / 2)

        return min(min_samples, max_iq_len)

    @staticmethod
    @njit(
        [
            (
                numba.types.Array(DEMOD_DTYPE_NB, 1, "C"),
                numba.types.Array(DEMOD_DTYPE_NB, 1, "C"),
                numba.types.int32,
                numba.types.int32,
            )
        ],
        cache=True,
        fastmath=False,
        nogil=True,
    )
    def _generate_iq_oscillators(
        i_osc, q_osc, carrier, sample_rate
    ):
        two_pi_carrier = 2 * pi * carrier

        for i in range(len(i_osc)):
            t = i / sample_rate
            i_osc[i] = cos(two_pi_carrier * t)  #  In-phase
            q_osc[i] = -sin(two_pi_carrier * t)  # Quadrature

    @staticmethod
    def compute_analytic_signal(input):
        axis = -1
        N = input.shape[axis]
        h = np.zeros(N, dtype=np.complex64)
        h[0] = h[N // 2] = 1
        h[1 : N // 2] = 2

        i = 0
        for hilbert_value in np.fft.ifft(
            np.fft.fft(input, N, axis=axis) * h, axis=axis
        ):
            input[i] = atan2(hilbert_value.imag, hilbert_value.real)  # np.angle(analytic_signal)
            i+=1

    @staticmethod
    @njit(
        [
            (
                NumbaAudioArray,
                NumbaAudioArray,
                numba.types.float32,
                numba.types.float32,
                numba.types.float32,
                numba.types.int32
            ),
            (
                numba.types.Array(DEMOD_DTYPE_NB, 1, "C"),
                NumbaAudioArray,
                numba.types.float32,
                numba.types.float32,
                numba.types.float32,
                numba.types.int32
            ),
            (
                numba.types.Array(DEMOD_DTYPE_NB, 1, "A"),
                NumbaAudioArray,
                numba.types.float32,
                numba.types.float32,
                numba.types.float32,
                numba.types.int32
            ),
        ],
        cache=True,
        fastmath=True,
        nogil=True,
    )
    def demod_hilbert(analytic_signal, output, min_float, max_float, sample_rate, deviation):
        two_pi = 2 * pi
        analytic_signal_value = 0
        analytic_signal_value_prev = 0
        discont = pi
        ph_correct = 0
        ph_correct_prev = 0

        i = 1
        instantaneous_frequency_len = len(output)
        for analytic_signal_value in analytic_signal:
            if i >= instantaneous_frequency_len:
                break

            dd = analytic_signal_value - analytic_signal_value_prev
            analytic_signal_value_prev = analytic_signal_value  #      dd = np.diff(p)

            # FMdemod.unwrap
            ddmod = (
                (dd + pi) % two_pi
            ) - pi  #           ddmod = np.mod(dd + pi, 2 * pi) - pi
            if (
                ddmod == -pi and dd > 0
            ):  #                 to_pi_locations = np.where(np.logical_and(ddmod == -pi, dd > 0))
                ddmod = pi  #                              ddmod[to_pi_locations] = pi
            ph_correct = ddmod - dd  #                     ph_correct = ddmod - dd
            if (
                -dd if dd < 0 else dd
            ) < discont:  #       to_zero_locations = np.where(np.abs(dd) < discont)
                ph_correct = (
                    0  #                          ph_correct[to_zero_locations] = 0
                )

            ph_correct = (
                ph_correct_prev + ph_correct
            )  #    p[1] + np.cumsum(ph_correct).astype(REAL_DTYPE)

            # FMdemod.unwrap_hilbert
            out = (ph_correct - ph_correct_prev) / two_pi * sample_rate / deviation # np.diff(instantaneous_phase) / (2.0 * pi) * sample_rate
            output[i - 1] = max(min_float, min(max_float, out))
            ph_correct_prev = ph_correct
            i += 1

    @staticmethod
    @njit(
        [
            (
                numba.types.Array(DEMOD_DTYPE_NB, 1, "C"),
                NumbaAudioArray,
                numba.types.float32,
                numba.types.float32,
                numba.types.Array(DEMOD_DTYPE_NB, 1, "C"),
                numba.types.Array(DEMOD_DTYPE_NB, 1, "C"),
                numba.types.Array(DEMOD_DTYPE_NB, 1, "C"),
                numba.types.Array(DEMOD_DTYPE_NB, 1, "C"),
                numba.types.int32,
                numba.types.int32,
                numba.types.int32,
            ),
            (
                numba.types.Array(DEMOD_DTYPE_NB, 1, "A"),
                NumbaAudioArray,
                numba.types.float32,
                numba.types.float32,
                numba.types.Array(DEMOD_DTYPE_NB, 1, "C"),
                numba.types.Array(DEMOD_DTYPE_NB, 1, "C"),
                numba.types.Array(DEMOD_DTYPE_NB, 1, "C"),
                numba.types.Array(DEMOD_DTYPE_NB, 1, "C"),
                numba.types.int32,
                numba.types.int32,
                numba.types.int32,
            ),
        ],
        cache=True,
        fastmath=True,
        nogil=True,
    )
    def demod_quadrature(
        in_rf,
        out_demod,
        min_float,
        max_float,
        i_osc,
        q_osc,
        filter_b,
        filter_a,
        sample_rate,
        carrier,
        deviation,
    ):
        # Numba optimized implementation of:
        #
        # # mix in  i/q
        # i_signal = in_rf * i_osc
        # q_signal = in_rf * q_osc
        #
        # # low pass filter
        # i_filtered = lfilter(filter_b, filter_a, i_signal)
        # q_filtered = lfilter(filter_b, filter_a, q_signal)
        #
        # # unwrap angles
        # phase = np.arctan2(q_filtered, i_filtered)
        # inst_freq = np.diff(np.unwrap(phase)) / (2 * pi * (1 / sample_rate))
        # demod = inst_freq - carrier

        # constants
        two_pi = 2 * pi
        diff_divisor = two_pi * (1 / sample_rate)
        iq_len = len(i_osc)
        rf_len = len(in_rf)

        #
        # low pass filter history
        #
        i_in_hist = np.zeros(QUADRATURE_LP_ORDER, dtype=np.float64)
        q_in_hist = np.zeros(QUADRATURE_LP_ORDER, dtype=np.float64)
        i_filtered_hist = np.zeros(QUADRATURE_LP_ORDER, dtype=np.float64)
        q_filtered_hist = np.zeros(QUADRATURE_LP_ORDER, dtype=np.float64)

        prev_angle = 0  # doesn't matter since the final chunks have overlap
        prev_unwrapped = prev_angle

        for i in range(1, rf_len - QUADRATURE_LP_ORDER):
            #
            # mix in i/q, reflect the sine and cosine
            #
            iq_index = i % iq_len
            sign = 1 - 2 * ((i // iq_len) % 2)

            i_in = in_rf[i] * i_osc[iq_index] * sign
            q_in = in_rf[i] * q_osc[iq_index] * sign

            #
            # low pass filter
            #
            i_filtered = filter_b[0] * i_in
            q_filtered = filter_b[0] * q_in

            i_filtered += filter_b[QUADRATURE_LP_ORDER] * i_in_hist[QUADRATURE_LP_ORDER - 1] - filter_a[QUADRATURE_LP_ORDER] * i_filtered_hist[QUADRATURE_LP_ORDER - 1]
            q_filtered += filter_b[QUADRATURE_LP_ORDER] * q_in_hist[QUADRATURE_LP_ORDER - 1] - filter_a[QUADRATURE_LP_ORDER] * q_filtered_hist[QUADRATURE_LP_ORDER - 1]

            for f_idx in range(QUADRATURE_LP_ORDER - 2, -1, -1):
                next_f_idx = f_idx + 1
                i_filtered += filter_b[next_f_idx] * i_in_hist[f_idx] - filter_a[next_f_idx] * i_filtered_hist[f_idx]
                q_filtered += filter_b[next_f_idx] * q_in_hist[f_idx] - filter_a[next_f_idx] * q_filtered_hist[f_idx]

                # Shift histories forward
                i_in_hist[next_f_idx] = i_in_hist[f_idx]
                i_filtered_hist[next_f_idx] = i_filtered_hist[f_idx]

                q_in_hist[next_f_idx] = q_in_hist[f_idx]
                q_filtered_hist[next_f_idx] = q_filtered_hist[f_idx]

            i_in_hist[0] = i_in
            i_filtered_hist[0] = i_filtered

            q_in_hist[0] = q_in
            q_filtered_hist[0] = q_filtered

            #
            # unwrap angles
            #
            current_angle = atan2(q_filtered, i_filtered)
            delta = current_angle - prev_angle

            correction = -two_pi * (delta > pi) + two_pi * (delta < -pi)
            unwrapped = prev_unwrapped + delta + correction

            diff = prev_unwrapped - unwrapped
            out = (carrier - diff / diff_divisor) / deviation

            out_demod[i - 1] = min(max(out, min_float), max_float)

            prev_angle = current_angle
            prev_unwrapped = unwrapped

    def work(self, input: np.array, output: np.array):
        if self.type == DEMOD_HILBERT:
            FMdemod.compute_analytic_signal(input)
            FMdemod.demod_hilbert(
                input,
                output,
                self.min_float,
                self.max_float,
                np.float32(self.sample_rate),
                self.deviation,
            )
        elif self.type == DEMOD_QUADRATURE:
            FMdemod.demod_quadrature(
                input,
                output,
                self.min_float,
                self.max_float,
                self.i_osc,
                self.q_osc,
                self.quadrature_lp_b,
                self.quadrature_lp_a,
                self.sample_rate,
                self.carrier,
                self.deviation,
            )


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
def build_shelf_filter(
    direction, t1_low, t2_high, db_per_octave, bandwidth, audio_rate
):
    t1_f = tau_as_freq(t1_low)
    t2_f = tau_as_freq(t2_high)

    # find center of the frequencies
    center_f = sqrt(t2_f * t1_f)
    # calculate how many octaves exist between the center and outer frequencies
    # bandwidth = log(t2_f/center_f, 2)

    # calculate total gain between the two frequencies based db per octave
    gain = log(t2_f / t1_f, 2) * db_per_octave

    b, a = gen_shelf(center_f, gain, direction, audio_rate, bandwidth=bandwidth)

    # scale the filter such that the top of the shelf is at 0db gain
    scale_factor = 10 ** (-gain / 20)
    b = [x * scale_factor for x in b]

    return b, a


class SpectralNoiseReduction:
    class SpectralGateNonStationaryNumba(SpectralGateNonStationary):
        # Adapted from noisereduce
        def __init__(self, params):
            super().__init__(**params)

            self.t_frames = self._time_constant_s * self.sr / self._hop_length

            # By default, this solves the equation for b:
            #   b**2  + (1 - b) / t_frames  - 2 = 0
            # which approximates the full-width half-max of the
            # squared frequency response of the IIR low-pass filt
            b = (np.sqrt(1 + 4 * self.t_frames**2) - 1) / (2 * self.t_frames**2)
            self.smooth_filter_b = [b]
            self.smooth_filter_a = [1, b - 1]

        @staticmethod
        @njit(
            numba.types.void(
                numba.types.Array(numba.types.float64, 2, "A"),
                numba.types.Array(numba.types.float32, 2, "F"),
                numba.types.int64,
                numba.types.int64,
            ),
            cache=True,
            fastmath=True,
            nogil=True,
        )
        def _get_sig_mask(
            sig_stft_smooth,
            abs_sig_stft,
            thresh_n_mult_nonstationary,
            sigmoid_slope_nonstationary,
        ):
            # get the number of X above the mean the signal is
            sig_stft_smooth_x, sig_stft_smooth_y = sig_stft_smooth.shape
            # prevent divide by zero
            epsilon = np.finfo(np.float64).eps

            for x in range(sig_stft_smooth_x):
                for y in range(sig_stft_smooth_y):
                    sig_stft_smooth[x][y] = 1 / (
                        1
                        + np.exp(
                            (
                                thresh_n_mult_nonstationary
                                - (abs_sig_stft[x][y] - sig_stft_smooth[x][y])
                                / (sig_stft_smooth[x][y] + epsilon)
                            )
                            * sigmoid_slope_nonstationary
                        )
                    )

        @staticmethod
        @njit(
            numba.types.void(
                numba.types.Array(numba.types.complex64, 2, "F"),
                numba.types.Array(numba.types.float64, 2, "C"),
                numba.types.float64,
            ),
            cache=True,
            fastmath=True,
            nogil=True,
        )
        def _mask_signal(sig_stft, sig_mask, prop_decrease):
            # multiply signal with mask
            sig_mask_x, sig_mask_y = sig_mask.shape

            for x in range(sig_mask_x):
                for y in range(sig_mask_y):
                    sig_stft[x][y] = sig_stft[x][y] * (
                        sig_mask[x][y] * prop_decrease + 1 * (1.0 - prop_decrease)
                    )

        def spectral_gating_nonstationary_single_channel(self, chunk):
            """non-stationary version of spectral gating"""
            _, _, sig_stft = stft(
                chunk,
                nfft=self._n_fft,
                noverlap=self._win_length - self._hop_length,
                nperseg=self._win_length,
                padded=False,
            )
            # get abs of signal stft
            abs_sig_stft = np.abs(sig_stft)

            # get the smoothed mean of the signal
            sig_stft_smooth = filtfilt(
                self.smooth_filter_b,
                self.smooth_filter_a,
                abs_sig_stft,
                axis=-1,
                padtype=None,
            )

            SpectralNoiseReduction.SpectralGateNonStationaryNumba._get_sig_mask(
                sig_stft_smooth,
                abs_sig_stft,
                self._thresh_n_mult_nonstationary,
                self._sigmoid_slope_nonstationary,
            )
            sig_mask = sig_stft_smooth

            if self.smooth_mask:
                # convolve the mask with a smoothing filter
                sig_mask = fftconvolve(sig_mask, self._smoothing_filter, mode="same")

            SpectralNoiseReduction.SpectralGateNonStationaryNumba._mask_signal(
                sig_stft, sig_mask, self._prop_decrease
            )
            sig_stft_denoised = sig_stft

            # invert/recover the signal
            _, denoised_signal = istft(
                sig_stft_denoised,
                nfft=self._n_fft,
                noverlap=self._win_length - self._hop_length,
                nperseg=self._win_length,
            )

            return denoised_signal.astype(REAL_DTYPE)

    def __init__(self, audio_rate, nr_reduction_amount):
        self.chunk_size = int(audio_rate / BLOCKS_PER_SECOND)
        self.chunk_count = BLOCKS_PER_SECOND
        self.end_padding = int(self.chunk_size / 8)
        self.nr_reduction_amount = nr_reduction_amount

        self.denoise_params = {
            "y": np.empty(1),
            "sr": audio_rate,
            "chunk_size": self.chunk_size,
            "padding": self.end_padding,
            "prop_decrease": self.nr_reduction_amount,
            "n_fft": 1024,
            "win_length": None,
            "hop_length": None,
            "time_constant_s": (
                (self.chunk_size * self.chunk_count / 2) / audio_rate
            ),  # (self.chunk_size * (self.chunk_count - 1)) / audio_rate,
            "freq_mask_smooth_hz": 500,
            "time_mask_smooth_ms": 50,
            "thresh_n_mult_nonstationary": 2,
            "sigmoid_slope_nonstationary": 10,
            "tmp_folder": None,
            "use_tqdm": False,
            "n_jobs": 1,
        }

        self.spectral_gate = SpectralNoiseReduction.SpectralGateNonStationaryNumba(
            self.denoise_params
        )
        self.chunks = []
        for i in range(self.chunk_count):
            self.chunks.append(np.zeros(self.chunk_size, dtype=REAL_DTYPE))

    @staticmethod
    @njit(
        numba.types.Tuple((NumbaAudioArray, NumbaAudioArray))(
            numba.types.int64,
            NumbaAudioArray,
            NumbaAudioArray,
            NumbaAudioArray,
        ),
        cache=True,
        fastmath=True,
        nogil=True,
    )
    def _get_chunk(end_padding, audio, chunk1, chunk2):
        # merge the chunks into one array for processing
        chunks = [chunk1, chunk2]
        chunk = np.zeros(
            len(chunk1) + len(chunk2) + len(audio) + end_padding, dtype=REAL_DTYPE
        )

        chunk_offset = 0
        for i in range(len(chunks)):
            chunk_data = chunks[i]

            for j in range(len(chunk_data)):
                chunk[j + chunk_offset] = chunk_data[j]

            chunk_offset += len(chunk_data)

        # add the input audio to the chunks
        audio_copy = np.empty_like(audio)
        for i in range(len(audio)):
            audio_copy[i] = audio[i]
            chunk[i + chunk_offset] = audio[i]

        return chunk, audio_copy

    def spectral_nr(self, audio_in, audio_out):
        chunk, audio_copy = SpectralNoiseReduction._get_chunk(
            self.end_padding,
            audio_in,
            self.chunks[0],
            self.chunks[1],
        )
        self.chunks.append(audio_copy)
        self.chunks.pop(0)

        nr = self.spectral_gate.spectral_gating_nonstationary_single_channel(chunk)

        DecoderSharedMemory.copy_data_src_offset_float32(
            nr, audio_out, len(nr) - len(audio_out) - self.end_padding, len(audio_out)
        )

class DCBlocker:
    def __init__(self, sample_rate, cutoff):
        # Compute pole R so cutoff is approximately fc Hz:
        R = 1 - (2 * np.pi * cutoff) / sample_rate
        if R < 0:
            R = 0
        if R > 0.999999:
            R = 0.999999  # numerical stability

        self.R = R

        # State
        self.prev_x = 0.0
        self.prev_y = 0.0

    @staticmethod
    @njit(
        [
            numba.types.UniTuple(numba.types.float32, 2)(
                NumbaAudioArray,
                numba.types.float32,
                numba.types.float32,
                numba.types.float32
            )
        ],
        cache=True,
        fastmath=True,
        nogil=True,
    )
    def dc_block(audio, px, py, R):
        for i in range(len(audio)):
            y = audio[i] - px + R * py

            px = audio[i]
            py = y

            audio[i] = y

        return px, py

    def process(self, audio):
        self.prev_x, self.prev_y = DCBlocker.dc_block(audio, self.prev_x, self.prev_y, self.R)
        

class Deemphasis:
    def __init__(
        self,
        audio_rate,
        deemphasis_low_tau: float,
        deemphasis_high_tau: float,
        deemphasis_db_per_octave: float,
        deemphasis_bandwidth: float,
    ):
        self.audio_rate = audio_rate

        # deemphasis filter for output audio
        self.deemphasis_T1 = deemphasis_low_tau
        self.deemphasis_T2 = deemphasis_high_tau
        self.deemphasis_db_per_octave = deemphasis_db_per_octave
        self.deemphasis_bandwidth = deemphasis_bandwidth

        self.deemph_b, self.deemph_a = build_shelf_filter(
            "low",
            self.deemphasis_T1,
            self.deemphasis_T2,
            self.deemphasis_db_per_octave,
            self.deemphasis_bandwidth,
            self.audio_rate,
        )

        self.DeemphasisLowpass = FiltersClass(np.array(self.deemph_b), np.array(self.deemph_a))

    def get_response(self):
        # compute frequency response
        w, h_total = freqz(self.deemph_b, self.deemph_a, worN=4096, fs=self.audio_rate)
    
        magnitude_db = 20 * np.log10(np.abs(h_total))

        return w, magnitude_db
    
    @staticmethod
    @njit(
        [
            (
                NumbaAudioArray,
                NumbaAudioArray,
            )
        ],
        cache=True,
        fastmath=True,
        nogil=True,
    )
    def align_audio(audio_in, audio_out):
        audio_end = len(audio_out)
        audio_start = audio_end - len(audio_in)
        for i in range(0, audio_start):
            audio_out[i] = 0

        for i in range(audio_start, audio_end):
            audio_out[i] = audio_in[i-audio_start]

    def process(self, audio_out):
        audio_filtered = self.DeemphasisLowpass.lfilt(audio_out)
        Deemphasis.align_audio(audio_filtered, audio_out)


class Expander:
    def __init__(
        self,
        audio_rate,
        gain: float = DEFAULT_EXPANDER_GAIN,
        ratio: float = DEFAULT_EXPANDER_RATIO,
        attack_tau: float = DEFAULT_EXPANDER_ATTACK_TAU,
        release_tau: float = DEFAULT_EXPANDER_RELEASE_TAU,
        weighting_low_tau: float = DEFAULT_VHS_EXPANDER_WEIGHTING_TAU_1,
        weighting_high_tau: float = DEFAULT_VHS_EXPANDER_WEIGHTING_TAU_2,
        weighting_db_per_octave: float = DEFAULT_VHS_EXPANDER_WEIGHTING_DB_PER_OCTAVE,
        weighting_bandwidth: float = DEFAULT_VHS_EXPANDER_WEIGHTING_BANDWIDTH,
    ):
        self.audio_rate = audio_rate
        self.linear_to_db = 20 / log(10)
        self.db_to_linear = log(10) / 20

        # makeup gain to apply after expansion
        self.gain = 10 ** (gain / 20)
        self.ratio = float(ratio)
        self.atkCoeff = np.exp(-1.0 / (attack_tau * self.audio_rate))
        self.relCoeff = np.exp(-1.0 / (release_tau * self.audio_rate))

        self.env_db = -120.0

        # this is set to avoid high frequency noise to interfere with the NR envelope tracking
        self.Lo_cut = 19e3
        self.Lo_transition = 10e3

        self.locut_iirb, self.locut_iira = firdes_lowpass(
            self.audio_rate,
            self.Lo_cut,
            self.Lo_transition,
        )

        self.WeightedLowpass = FiltersClass(
            np.array(self.locut_iirb), np.array(self.locut_iira), dtype=np.float32
        )

        # weighted filter for envelope detector
        self.weighting_T1 = weighting_low_tau
        self.weighting_T2 = weighting_high_tau
        self.weighting_db_per_octave = weighting_db_per_octave
        self.weighting_bandwidth = weighting_bandwidth

        self.env_iirb, self.env_iira = build_shelf_filter(
            "high",
            self.weighting_T1,
            self.weighting_T2,
            self.weighting_db_per_octave,
            self.weighting_bandwidth,
            self.audio_rate,
        )

        self.WeightedHighpass = FiltersClass(np.array(self.env_iirb), np.array(self.env_iira), dtype=np.float32)

    def get_response(self):
        # compute frequency response
        w, h_low = freqz(self.locut_iirb, self.locut_iira, worN=4096, fs=self.audio_rate)
        _, h_high = freqz(self.env_iirb, self.env_iira, worN=4096, fs=self.audio_rate)
    
        h_total = h_low * h_high
    
        magnitude_db = 20 * np.log10(np.abs(h_total))

        return w, magnitude_db

    @staticmethod
    @njit(
        [(
            NumbaAudioArray,
            NumbaAudioArray,
            numba.types.float32,
            numba.types.float32,
            numba.types.float32,
            numba.types.float32,
            numba.types.float32,
            numba.types.float32,
            numba.types.float32
        )],
        cache=True,
        fastmath=True,
        nogil=True
    )
    def expand(
        audio,
        side_chain,
        env_db,
        linear_to_db,
        db_to_linear,
        atkCoeff,
        relCoeff,
        gain,
        ratio,
    ):
        audio_len = audio.shape[0]
        ratio_m1 = ratio - 1

        for i in range(audio_len):
            # envelope in db
            sc_db = log(abs(side_chain[i]) + 1e-20) * linear_to_db

            coeff = relCoeff + (atkCoeff - relCoeff) * (sc_db > env_db)
            env_db = coeff * env_db + (1.0 - coeff) * sc_db

            gain_db = ratio_m1 * env_db

            audio[i] *= exp(gain_db * db_to_linear) * gain
    
        return env_db

    def process(self, pre_in, audio_out):
        # prevent high frequency noise from interfering with envelope detector
        pre_in_low_pass = self.WeightedLowpass.filtfilt(pre_in)

        # high pass weighted input to envelope detector
        side_chain = self.WeightedHighpass.lfilt(pre_in_low_pass)

        self.env_db = Expander.expand(
            audio_out,
            side_chain,
            self.env_db,
            self.linear_to_db,
            self.db_to_linear,
            self.atkCoeff,
            self.relCoeff,
            self.gain,
            self.ratio
        )


@dataclass
class HiFiAudioParams:
    pre_trim: int
    gain: int
    decode_mode: str
    preview: bool
    demod_type: str
    auto_fine_tune: bool
    format: str
    if_rate: int
    input_rate: int
    audio_rate: int
    ifresample_numerator: int
    ifresample_denominator: int
    if_resampler_converter: str
    audioRes_numerator: int
    audioRes_denominator: int
    audio_resampler_converter: str
    audio_final_rate: int
    audioFinal_numerator: int
    audioFinal_denominator: int
    audio_final_resampler_converter: str
    headswitch_interpolation_enabled: bool
    headswitch_passes: int
    headswitch_signal_rate: int
    headswitch_hz: int
    headswitch_drift_hz: int
    headswitch_cutoff_freq: int
    headswitch_peak_prominence_limit: int
    headswitch_interpolation_padding: int
    headswitch_interpolation_neighbor_range: int
    hs_b: float
    hs_a: float
    muting_enabled: bool
    muting_cutoff_freq: int
    muting_window_size: int
    muting_window_hop_size: int
    muting_fade_samples: int
    muting_amplitude_threshold: int
    muting_std_threshold: int
    muting_fft_start: int
    muting_fft_end: int


class HiFiDecode:
    def __init__(self, options=None, is_main_process=True, bias_guess=False):
        if options is None:
            options = dict()
        self.options = options
        self.is_main_process = is_main_process
        self.decode_mode = options["mode"]
        self.gain = options["gain"]

        self.input_rate: int = int(options["input_rate"])
        if self.options["demod_type"] == DEMOD_HILBERT:
            self.if_rate: int = DEMOD_HILBERT_IF_RATE
        elif self.options["demod_type"] == DEMOD_QUADRATURE:
            self.if_rate: int = (
                self.input_rate
            )  # do not resample rf when doing quadrature demodulation

        self.audio_rate: int = 192000
        self.audio_final_rate: int = int(options["audio_rate"])

        self.rfBandPassParams = AFEParamsFront()
        (
            self.ifresample_numerator,
            self.ifresample_denominator,
            self.audioRes_numerator,
            self.audioRes_denominator,
            self.audioFinal_numerator,
            self.audioFinal_denominator,
        ) = HiFiDecode.getResamplingRatios(
            self.input_rate, self.if_rate, self.audio_rate, self.audio_final_rate
        )

        if self.options["resampler_quality"] == "high":
            self.if_resampler_converter = "VHQ"
            self.audio_resampler_converter = "VHQ"
            self.audio_final_resampler_converter = "VHQ"
        elif self.options["resampler_quality"] == "medium":
            self.if_resampler_converter = "LQ"
            self.audio_resampler_converter = "MQ"
            self.audio_final_resampler_converter = "HQ"
        else:  # low
            self.if_resampler_converter = "LQ"
            self.audio_resampler_converter = "LQ"
            self.audio_final_resampler_converter = "LQ"

        self.if_resampler = ResampleStream(self.ifresample_denominator, self.ifresample_numerator, 1, np.float32, self.if_resampler_converter)
        self.audio_resampler_l = ResampleStream(self.audioRes_denominator, self.audioRes_numerator, 1, REAL_DTYPE, self.audio_resampler_converter)
        self.audio_resampler_r = ResampleStream(self.audioRes_denominator, self.audioRes_numerator, 1, REAL_DTYPE, self.audio_resampler_converter)
        self.audio_final_resampler_l = ResampleStream(self.audioFinal_denominator, self.audioFinal_numerator, 1, REAL_DTYPE, self.audio_final_resampler_converter)
        self.audio_final_resampler_r = ResampleStream(self.audioFinal_denominator, self.audioFinal_numerator, 1, REAL_DTYPE, self.audio_final_resampler_converter)

        self.set_block_sizes()
        self._set_block_overlap()

        self.bandpassRF = AFEBandPass(self.rfBandPassParams, self.input_rate)
        a_iirb, a_iira = firdes_lowpass(
            self.if_rate, self.audio_rate * 3 / 4, self.audio_rate / 3, order_limit=10
        )
        self.preAudioResampleL = FiltersClass(a_iirb, a_iira, dtype=np.float64)
        self.preAudioResampleR = FiltersClass(a_iirb, a_iira, dtype=np.float64)

        self.standard, self.field_rate = HiFiDecode.get_standard(
            options["format"],
            options["standard"],
            options["afe_vco_deviation"],
            options["afe_left_carrier"],
            options["afe_right_carrier"],
        )
        self.standard_original = deepcopy(self.standard)

        self.headswitch_interpolation_enabled = self.options[
            "head_switching_interpolation"
        ]
        self.headswitch_passes = 1
        self.headswitch_signal_rate = self.audio_rate
        self.headswitch_hz = (
            self.field_rate
        )  # frequency used to fit peaks to the expected headswitching interval
        self.headswitch_drift_hz = self.field_rate * 0.1  # +- 10% drift is normal
        self.headswitch_cutoff_freq = (
            25000  # filter cutoff frequency for peak detection
        )
        # upper limit for peak promience which is used to widen the interpoation boundary
        # when a peak is detected. Head switching peaks may exceed this number; however,
        # the width of the interpolation will only be expanded up to this number.
        # If there is noise that is a greater duration than this, it should probably be muted instead.
        self.headswitch_peak_prominence_limit = 3
        # maximum seconds to widen the interpolation based on the strength of the peak
        #   setting too low prevents interpolation from covering the whole pulse
        #   setting too high causes audible artifacts where the interpolation occurs
        self.headswitch_interpolation_padding = 35e-6
        # time range to look for neighboring noise when a head switch event is detected
        # this helps to determine the correct width of the interpolation
        self.headswitch_interpolation_neighbor_range = 200e-6
        hs_b, hs_a = butter(
            3,
            self.headswitch_cutoff_freq / (0.5 * self.headswitch_signal_rate),
            btype="highpass",
        )
        hs_b = np.float32(hs_b)
        hs_a = np.float32(hs_a)

        # hifi carrier loss results in broadband noise
        # mute the audio when this broadband noise exists above the audible frequencies
        self.muting_enabled = self.options["muting"]
        self.muting_audio_rate = self.audio_rate
        # number of samples to fade out before muting, and fade in after muting
        self.muting_fade_samples = 128
        # muting detection thresholds
        self.muting_window_size = 128
        self.muting_window_hop_size = 128
        self.muting_amplitude_threshold = 1  # 1 is 100% gain
        self.muting_std_threshold = 1  # +- standard deviation of fft before muting

        # remove signals that may be from the recorded audio
        self.muting_cutoff_freq = 40000
        muting_fft_freqs = np.fft.fftfreq(
            self.muting_window_size, d=1 / self.muting_audio_rate
        )
        for i in range(len(muting_fft_freqs)):
            freq = muting_fft_freqs[i]
            if freq < 0:
                self.muting_fft_end = i - 1
                break
            if freq <= self.muting_cutoff_freq:
                self.muting_fft_start = i

        if not bias_guess:
            # defer until carriers can be determined
            self.afeL, self.afeR = self._get_afe()

            self.fmL, self.fmR = self._get_fm_demod(
                self.if_rate, self.options["demod_type"]
            )

        if self.options["grc"]:
            print(f"Set gnuradio sample rate at {self.if_rate} Hz, type float")
            if ZMQ_AVAILABLE:
                self.grc = ZMQSend()
            else:
                print(
                    "ZMQ library is not available, please install the zmq python library to use this feature!"
                )

        self.audio_process_params = HiFiAudioParams(
            pre_trim=self.pre_trim,
            gain=self.gain,
            decode_mode=self.decode_mode,
            preview=options["preview"],
            demod_type=options["demod_type"],
            auto_fine_tune=options["auto_fine_tune"],
            format=options["format"],
            if_rate=self.if_rate,
            input_rate=self.input_rate,
            audio_rate=self.audio_rate,
            ifresample_numerator=self.ifresample_numerator,
            ifresample_denominator=self.ifresample_denominator,
            if_resampler_converter=self.if_resampler_converter,
            audioRes_numerator=self.audioRes_numerator,
            audioRes_denominator=self.audioRes_denominator,
            audio_resampler_converter=self.audio_resampler_converter,
            audio_final_rate=self.audio_final_rate,
            audioFinal_numerator=self.audioFinal_numerator,
            audioFinal_denominator=self.audioFinal_denominator,
            audio_final_resampler_converter=self.audio_final_resampler_converter,
            headswitch_interpolation_enabled=self.headswitch_interpolation_enabled,
            headswitch_passes=self.headswitch_passes,
            headswitch_signal_rate=self.headswitch_signal_rate,
            headswitch_hz=self.headswitch_hz,
            headswitch_drift_hz=self.headswitch_drift_hz,
            headswitch_cutoff_freq=self.headswitch_cutoff_freq,
            headswitch_peak_prominence_limit=self.headswitch_peak_prominence_limit,
            headswitch_interpolation_padding=self.headswitch_interpolation_padding,
            headswitch_interpolation_neighbor_range=self.headswitch_interpolation_neighbor_range,
            hs_b=hs_b,
            hs_a=hs_a,
            muting_enabled=self.muting_enabled,
            muting_cutoff_freq=self.muting_cutoff_freq,
            muting_window_size=self.muting_window_size,
            muting_window_hop_size=self.muting_window_hop_size,
            muting_fade_samples=self.muting_fade_samples,
            muting_amplitude_threshold=self.muting_amplitude_threshold,
            muting_std_threshold=self.muting_std_threshold,
            muting_fft_start=self.muting_fft_start,
            muting_fft_end=self.muting_fft_end,
        )

    @staticmethod
    def get_standard(
        format, system, afe_vco_deviation, afe_left_carrier, afe_right_carrier
    ):
        if format == "vhs":
            if system == "p":
                field_rate = 50
                standard = AFEParamsPALVHS()
            elif system == "n":
                field_rate = 59.94
                standard = AFEParamsNTSCVHS()
        elif format == "8mm":
            if system == "p":
                field_rate = 50
                standard = AFEParamsPAL8mm()
            elif system == "n":
                field_rate = 59.94
                standard = AFEParamsNTSC8mm()

        if afe_vco_deviation != 0:
            standard.VCODeviation = afe_vco_deviation
        if afe_left_carrier != 0:
            standard.LCarrierRef = afe_left_carrier
        if afe_right_carrier != 0:
            standard.RCarrierRef = afe_right_carrier

        return standard, field_rate

    def calculate_block_sizes(self, block_size=None):
        # block overlap and edge discard
        blocks_per_second_ratio = 1 / BLOCKS_PER_SECOND

        if block_size == None:
            block_size: int = ceil(
                self.input_rate * blocks_per_second_ratio
            )
        else:
            block_size: int = block_size
            blocks_per_second_ratio: float = block_size / self.input_rate

        block_resampled_size: int = ceil(
            self.if_rate * blocks_per_second_ratio
        )
        block_audio_size: int = ceil(
            self.audio_rate * blocks_per_second_ratio
        )
        block_audio_final_size: int = ceil(
            self.audio_final_rate * blocks_per_second_ratio
        )

        return {
            "blocks_per_second_ratio": blocks_per_second_ratio,
            "block_size": block_size,
            "block_resampled_size": block_resampled_size,
            "block_audio_size": block_audio_size,
            "block_audio_final_size": block_audio_final_size,
        }

    def set_block_sizes(self, block_size=None):
        block_calculations = self.calculate_block_sizes(block_size)

        self._blocks_per_second_ratio = block_calculations["blocks_per_second_ratio"]
        self._initial_block_size = block_calculations["block_size"]
        self._initial_block_resampled_size = block_calculations["block_resampled_size"]
        self._initial_block_audio_size = block_calculations["block_audio_size"]
        self._initial_block_audio_final_size = block_calculations["block_audio_final_size"]

        return {
            "block_size": self._initial_block_size,
            "block_audio_size": self._initial_block_audio_size,
            "block_audio_final_size": self._initial_block_audio_final_size,
        }

    def _set_block_overlap(self):
        # Blocks are overlapped before and after by `block_overlap samples``
        # Block n+1 is:
        #   * Last half of the start overlap
        #   * All the non-overlapping data
        #   * First half of the end overlap
        # Block 0 is:
        #   * Copied data from beginning of non-overlapping data to simulate an overlap
        #   * All the non-overlapping data
        #   * First half of the end overlap
        # Block end is:
        #   * Last half of the start overlap
        #   * All the non-overlapping data up to the end of the audio
        #   * First half of the end overlap (last half of this overlap is discarded)
        #
        # reads:                |0000|1111111111|1111|          |2222|3333333333|3333|
        #        xxxx|0000000000|0000|          |1111|2222222222|2222|          |3333|44444444444444
        #          ^               ^               ^               ^               ^
        # block:   0               1               2               3               4

        # use the greatest common divisor to calculate the minimum size of overlap samples so it divides evenly against the input and final sample rates
        block_size_gcd = np.gcd.reduce(
            [self._initial_block_size, self._initial_block_audio_final_size]
        )

        if block_size_gcd > 5:
            block_audio_overlap_divisor = int(
                self._initial_block_audio_size / block_size_gcd
            )
        else:
            print(
                f"WARNING: The input sample rate is not evenly divisible by the output sample rate. Audio sync issues may occur. Input Rate: {self.input_rate}, Output Rate: {self.audio_final_rate}."
            )
            block_audio_overlap_divisor = 1

        # trims out the discontinuity errors at the beginning and end of each block
        # the duration of the discontiunity errors seem to increase as the distance between the carrier frequency and nyquist limit of the rf decreases
        self.pre_trim = 1000

        # minimum overlap to account for loss during resampling
        min_resampler_overlap = self.pre_trim + 50
        # min overlap in terms of final sample rate
        min_overlap = ceil(
            min_resampler_overlap / self.audio_rate * self.audio_final_rate
        )
        # overlap rounded up to the nearest evenly divisible chunk
        self._block_audio_final_overlap = (
            ceil(min_overlap / block_audio_overlap_divisor)
            * block_audio_overlap_divisor
        )

        overlap_seconds = self._block_audio_final_overlap / self.audio_final_rate

        self._block_overlap = round(self.input_rate * overlap_seconds)
        self._block_audio_overlap = ceil(self.input_rate * overlap_seconds)
        self._block_read_overlap = self._block_overlap * 2
        self._block_audio_final_overlap = round(self.audio_final_rate * overlap_seconds)

    def get_block_overlap(self):
        return {
            "block_read_overlap": self._block_read_overlap,
            "block_overlap": self._block_overlap,
            "block_audio_final_overlap": self._block_audio_final_overlap,
        }

    @staticmethod
    def getResamplingRatios(input_rate, if_rate, audio_rate, audio_final_rate):
        samplerate2ifrate = if_rate / input_rate

        ifresample_numerator = Fraction(samplerate2ifrate).numerator
        ifresample_denominator = Fraction(samplerate2ifrate).denominator
        assert (
            ifresample_numerator > 0
        ), f"IF resampling numerator got 0; sample_rate {input_rate}"
        assert (
            ifresample_denominator > 0
        ), f"IF resampling denominator got 0; sample_rate {input_rate}"

        audiorate2ifrate = audio_rate / if_rate
        audioRes_numerator = Fraction(audiorate2ifrate).numerator
        audioRes_denominator = Fraction(audiorate2ifrate).denominator

        audiorate2FinalAudioRate = audio_final_rate / audio_rate
        audioFinal_numerator = Fraction(audiorate2FinalAudioRate).numerator
        audioFinal_denominator = Fraction(audiorate2FinalAudioRate).denominator

        return (
            ifresample_numerator,
            ifresample_denominator,
            audioRes_numerator,
            audioRes_denominator,
            audioFinal_numerator,
            audioFinal_denominator,
        )

    def _get_fm_demod(self, if_rate, demod_type):
        return (
            FMdemod(
                if_rate,
                self.standard.LCarrierRef,
                self.standard.VCODeviation,
                self.initialBlockResampledSize,
                demod_type
            ),
            FMdemod(
                if_rate,
                self.standard.RCarrierRef,
                self.standard.VCODeviation,
                self.initialBlockResampledSize,
                demod_type
            )
        )

    def guessBiases(self, blocks: list[np.array]) -> Tuple[float, float]:
        meanL, meanR = StackableMA(window_average=len(blocks)), StackableMA(
            window_average=len(blocks)
        )

        (
            ifresample_numerator,
            ifresample_denominator,
            _,
            _,
            _,
            _,
        ) = HiFiDecode.getResamplingRatios(
            self.input_rate,
            DEMOD_HILBERT_IF_RATE,
            self.audio_rate,
            self.audio_final_rate,
        )
        afeL, afeR = self._get_afe()
        fmL, fmR = self._get_fm_demod(
            DEMOD_HILBERT_IF_RATE, DEMOD_HILBERT
        )

        progressB = TimeProgressBar(len(blocks), len(blocks))

        for i in range(len(blocks)):
            data = self.bandpassRF.work(blocks[i])
            data = data.astype(REAL_DTYPE, copy=False)

            data = resample(
                data,
                ifresample_denominator,
                ifresample_numerator,
                "LQ",
            )

            filterL = afeL.work(data)
            filterR = afeR.work(data)
            preL = np.empty(len(filterL), dtype=REAL_DTYPE)
            preR = np.empty(len(filterR), dtype=REAL_DTYPE)

            fmL.work(filterL.astype(DEMOD_DTYPE_NP), preL)
            fmR.work(filterR.astype(DEMOD_DTYPE_NP), preR)

            # remove dc spikes at beginning and end
            preL = preL[self.pre_trim : -self.pre_trim]
            preR = preR[self.pre_trim : -self.pre_trim]

            meanL.push(np.mean(preL))
            meanR.push(np.mean(preR))

            meanLResult = meanL.pull() * self.standard.VCODeviation
            meanRResult = meanR.pull() * self.standard.VCODeviation

            progressB.label = "Carrier L %.06f MHz, R %.06f MHz" % (
                meanLResult / 10e5,
                meanRResult / 10e5,
            )
            progressB.print(i + 1, False)

        # update the standard
        self.afeL, self.afeR = self._get_afe(meanLResult, meanRResult)

        # update all the filters and iq oscilators with the new bias
        self.fmL, self.fmR = self._get_fm_demod(
            self.if_rate, self.options["demod_type"]
        )

        return meanLResult, meanRResult

    def log_bias(self):
        devL = (self.standard_original.LCarrierRef - self.standard.LCarrierRef) / 1e3
        devR = (self.standard_original.RCarrierRef - self.standard.RCarrierRef) / 1e3

        if self.audio_process_params.decode_mode == 'l':
            print("Bias L %.02f kHz" % (devL), end=" ")
        elif self.audio_process_params.decode_mode == 'r':
            print("Bias R %.02f kHz" % (devR), end=" ")
        else:
            print("Bias L %.02f kHz, R %.02f kHz" % (devL, devR), end=" ")

        if abs(devL) < 9 and abs(devR) < 9:
            print("(good player/recorder calibration)")
        elif 9 <= abs(devL) < 10 or 9 <= abs(devR) < 10:
            print("(maybe marginal player/recorder calibration)")
        else:
            print(
                "\nWARN: the player or the recorder may be uncalibrated and/or\n"
                "the standard and/or the sample rate specified are wrong"
            )

    def _get_afe(self, newLC=None, newRC=None):
        if newLC:
            self.standard.LCarrierRef = (
                max(
                    min(newLC, self.standard_original.LCarrierRef + 10e3),
                    self.standard_original.LCarrierRef - 10e3,
                )
                if self.options["format"] == "vhs"
                else newLC
            )

        if newRC:
            self.standard.RCarrierRef = (
                max(
                    min(newRC, self.standard_original.RCarrierRef + 10e3),
                    self.standard_original.RCarrierRef - 10e3,
                )
                if self.options["format"] == "vhs"
                else newRC
            )

        afeL = AFEFilterable(self.standard, self.if_rate, 0)
        afeR = AFEFilterable(self.standard, self.if_rate, 1)

        return afeL, afeR

    def auto_fine_tune(
        self, dcL: float, dcR: float
    ) -> Tuple[AFEFilterable, AFEFilterable, FMdemod, FMdemod]:
        if self.audio_process_params.decode_mode != 'r':
            left_carrier_dc_offset = (
                self.standard.LCarrierRef - dcL * self.standard.VCODeviation
            )
            left_carrier_updated = self.standard.LCarrierRef - round(left_carrier_dc_offset)
            self.standard.LCarrierRef = max(
                min(left_carrier_updated, self.standard_original.LCarrierRef + 10e3),
                self.standard_original.LCarrierRef - 10e3,
            )
            
        if self.audio_process_params.decode_mode != 'l':
            right_carrier_dc_offset = (
                self.standard.RCarrierRef - dcR * self.standard.VCODeviation
            )
            right_carrier_updated = self.standard.RCarrierRef - round(
                right_carrier_dc_offset
            )
            self.standard.RCarrierRef = max(
                min(right_carrier_updated, self.standard_original.RCarrierRef + 10e3),
                self.standard_original.RCarrierRef - 10e3,
            )

        # auto fine tune can't adjust quadrature demodulation since the i/q oscillators are generated once, disabling for now
        # use the --bg option to adjust for bias at the beginning of the decode
        if self.options["demod_type"] == DEMOD_HILBERT:
            self.afeL, self.afeR = self._get_afe()
            self.fmL, self.fmR = self._get_fm_demod(
                self.if_rate, self.options["demod_type"]
            )

    @staticmethod
    @njit(
        numba.types.containers.Tuple((numba.types.float32, numba.types.float32))(
            numba.types.Array(numba.types.float32, 1, "A")
        ),
        cache=True,
        fastmath=True,
        nogil=True,
    )
    def mean_stddev(signal: np.array) -> tuple[float, float]:
        signal_mean = np.mean(signal)
        signal_std_dev = sqrt(np.mean(np.abs(signal - signal_mean) ** 2))

        return signal_mean, signal_std_dev

    @staticmethod
    def headswitch_detect_peaks(
        audio: np.array,
        audio_process_params: HiFiAudioParams,
    ) -> Tuple[list[Tuple[float, float, float, float]], np.array, np.array]:
        # remove audible frequencies to avoid detecting them as peaks
        filtered_signal = filtfilt(
            audio_process_params.hs_b, audio_process_params.hs_a, audio
        )
        filtered_signal_abs = abs(filtered_signal)
        filtered_signal_mean, filtered_signal_std_dev = HiFiDecode.mean_stddev(
            filtered_signal
        )

        # detect the peaks that align with the headswitching speed
        # peaks should align roughly to the frame rate of the video system
        # account for small drifts in the head switching pulse (shows up as the sliding dot on video)
        peak_distance_seconds = 1 / (
            audio_process_params.headswitch_hz
            + audio_process_params.headswitch_drift_hz
        )
        peak_centers, peak_center_props = find_peaks(
            filtered_signal_abs,
            distance=peak_distance_seconds
            * audio_process_params.headswitch_signal_rate,
            width=1,
        )

        # setup the neighboring peak theshold based on stadard deviation
        neighbor_threshold = filtered_signal_mean + filtered_signal_std_dev
        neighbor_search_width = round(
            audio_process_params.headswitch_interpolation_neighbor_range
            * audio_process_params.headswitch_signal_rate
        )

        peaks = []
        # add the peaks and search around the center peak for any neighboring noise that is above the threshold
        for i in range(len(peak_centers)):
            peak_start = peak_center_props["left_ips"][i]
            peak_end = peak_center_props["right_ips"][i]

            peaks.append(
                (
                    peak_centers[i],
                    peak_start,
                    peak_end,
                    # limit peak prominence from balooning too high in empty audio or broadband noise causing an entire chunk to be interpolated
                    max(
                        min(
                            peak_center_props["prominences"][i],
                            audio_process_params.headswitch_peak_prominence_limit,
                        ),
                        0,
                    ),
                )
            )

            start_neighbor = max(0, floor(peak_start - neighbor_search_width))
            end_neighbor = min(
                ceil(peak_end + neighbor_search_width), len(filtered_signal_abs)
            )

            # search for neighboring peaks and add to the list
            neighbor_peak_centers, neighbor_peak_props = find_peaks(
                filtered_signal_abs[start_neighbor:end_neighbor],
                threshold=neighbor_threshold,
                prominence=0.25,
                distance=1,
                width=1,
            )

            for peak_log_neighbor_idx in range(len(neighbor_peak_centers)):
                peaks.append(
                    (
                        neighbor_peak_centers[peak_log_neighbor_idx] + start_neighbor,
                        neighbor_peak_props["left_ips"][peak_log_neighbor_idx]
                        + start_neighbor,
                        neighbor_peak_props["right_ips"][peak_log_neighbor_idx]
                        + start_neighbor,
                        # limit peak prominence from balooning too high in empty audio or broadband noise causing an entire chunk to be interpolated
                        max(
                            min(
                                neighbor_peak_props["prominences"][
                                    peak_log_neighbor_idx
                                ],
                                audio_process_params.headswitch_peak_prominence_limit,
                            ),
                            0,
                        ),
                    )
                )

        return peaks, filtered_signal, filtered_signal_abs

    @staticmethod
    def headswitch_calc_boundaries(
        peaks: list[tuple[int, int, int, float]],
        audio_process_params: HiFiAudioParams,
    ) -> list[list[int, int]]:
        peak_boundaries = list()

        # scale the peak width depending on how much the peak stands out from the base signal
        # use light scaling for headswtich peaks since they are usually very brief
        padding_samples = round(
            audio_process_params.headswitch_interpolation_padding
            * audio_process_params.headswitch_signal_rate
        )
        for peak_center, peak_start, peak_end, peak_prominence in peaks:
            width_padding = peak_prominence * padding_samples
            # start and end peak at its bases
            start = floor(peak_start - width_padding)
            end = ceil(peak_end + width_padding)

            peak_boundaries.append([start, end])

        # merge overlapping or duplicate boundaries
        return HiFiDecode.merge_boundaries(peak_boundaries)

    @staticmethod
    @njit(
        numba.types.void(NumbaAudioArray, NumbaAudioArray, numba.types.int32),
        cache=True,
        fastmath=True,
        nogil=True,
    )
    def smooth(data_in: np.array, data_out: np.array, half_window: int):
        data_in_len = len(data_in)
        for i in range(data_in_len):
            start = max(0, i - half_window)
            end = min(data_in_len, i + half_window + 1)
            data_out[i] = np.mean(data_in[start:end])  # Apply moving average

    @staticmethod
    def merge_boundaries(boundaries):
        # merge overlapping or duplicate boundaries
        boundaries.sort(key=lambda x: x[0])
        merged = list()

        for boundary in boundaries:
            if not merged or merged[-1][1] < boundary[0]:
                merged.append(boundary)
            else:
                merged[-1] = [merged[-1][0], max(merged[-1][1], boundary[1])]

        return merged

    @staticmethod
    def headswitch_interpolate_boundaries(
        audio: np.array, boundaries: list[list[int, int]]
    ) -> np.array:
        interpolated_signal = np.empty_like(audio)
        interpolator_in = np.empty_like(audio)
        DecoderSharedMemory.copy_data_float32(
            audio, interpolated_signal, len(interpolated_signal)
        )
        DecoderSharedMemory.copy_data_float32(
            audio, interpolator_in, len(interpolator_in)
        )

        # setup interpolator input by copying and removing any samples that are peaks
        time = np.arange(len(interpolated_signal), dtype=float)

        for [start, end] in boundaries:
            time[start:end] = np.nan
            interpolator_in[start:end] = np.nan

        time = time[np.logical_not(np.isnan(time))]
        interpolator_in = interpolator_in[np.logical_not(np.isnan(interpolator_in))]

        # interpolate the gap where the peak was removed
        interpolator = interp1d(
            time,
            interpolator_in,
            kind="linear",
            copy=False,
            assume_sorted=True,
            fill_value="extrapolate",
        )

        for [start, end] in boundaries:
            smoothing_size = 1 + end - start

            # sample and hold inteerpolation if boundaries are beyond this chunk
            if start < 0:
                interpolated_signal[0:end] = interpolated_signal[end]
            elif end > len(audio):
                interpolated_signal[start : len(audio)] = interpolated_signal[start]
            else:
                for i in range(start, end):
                    interpolated_signal[i] = interpolator(i)
                # smooth linear interpolation
                smoothed_out = interpolated_signal[
                    start - smoothing_size : end + smoothing_size
                ]
                smoothed_in = np.empty_like(smoothed_out)
                DecoderSharedMemory.copy_data_float32(
                    smoothed_out, smoothed_in, len(smoothed_in)
                )
                HiFiDecode.smooth(smoothed_in, smoothed_out, ceil(smoothing_size / 4))

        return interpolated_signal

    @staticmethod
    def headswitch_remove_noise(
        audio: np.array, audio_process_params: HiFiAudioParams
    ) -> np.array:
        for _ in range(audio_process_params.headswitch_passes):
            peaks, filtered_signal, filtered_signal_abs = (
                HiFiDecode.headswitch_detect_peaks(audio, audio_process_params)
            )
            interpolation_boundaries = HiFiDecode.headswitch_calc_boundaries(
                peaks, audio_process_params
            )
            interpolated_audio = HiFiDecode.headswitch_interpolate_boundaries(
                audio, interpolation_boundaries
            )

            # uncomment to debug head switching pulse detection
            # HiFiDecode.debug_peak_interpolation(audio, filtered_signal, filtered_signal_abs, peaks, interpolation_boundaries, interpolated_audio, audio_process_params.headswitch_signal_rate)
            # plt.show()

            audio = interpolated_audio

        return interpolated_audio

    # size of the raw data block coming in
    @property
    def initialBlockSize(self) -> int:
        return self._initial_block_size

    # size of the resampled IF data
    @property
    def initialBlockResampledSize(self) -> int:
        return self._initial_block_resampled_size

    # size of the audio decoded audio before resampling
    @property
    def initialBlockAudioSize(self) -> int:
        return self._initial_block_audio_size

    # size of the audio decoded audio after resampling
    @property
    def initialBlockFinalAudioSize(self) -> int:
        return self._initial_block_audio_final_size

    @property
    def blockOverlap(self) -> int:
        return self._block_overlap

    @property
    def blockAudioFinalOverlap(self) -> int:
        return self._block_audio_final_overlap

    @property
    def sourceRate(self) -> int:
        return int(self.input_rate)

    @property
    def audioRate(self) -> int:
        return self.audio_rate

    @property
    def notchFreq(self) -> float:
        return self.standard_original.Hfreq

    @staticmethod
    @njit(
        [numba.types.float32(NumbaAudioArray, numba.types.int16)],
        cache=True,
        fastmath=True,
    )
    def cancelDC_trim(audio: np.array, trim: int) -> float:
        dc = REAL_DTYPE(np.mean(audio[trim:-trim]))

        for i in range(trim, len(audio) - trim):
            audio[i] = audio[i] - dc

        for i in range(trim):
            audio[i] = 0

        for i in range(len(audio) - trim, len(audio)):
            audio[i] = 0

        return dc

    @staticmethod
    def mute(audio: np.array, audio_process_params: HiFiAudioParams) -> np.array:
        # Parameters for the sliding window
        window_size = (
            audio_process_params.muting_window_size
        )  # Size of each window (in samples)
        hop_size = (
            audio_process_params.muting_window_hop_size
        )  # Hop size (how much to move the window each time)

        mute_point_ranges = []
        full_spectrum_ranges_count = 0

        fft_start = audio_process_params.muting_fft_start
        fft_end = audio_process_params.muting_fft_end

        # Loop through the audio in overlapping windows
        for start in range(0, len(audio) - window_size, hop_size):
            # Extract the current window of the signal
            end = start + window_size
            window = audio[start:end]

            # Compute the FFT of the window
            fft_output = np.fft.fft(window)

            # Compute the magnitude of the FFT, using the positive frequencies only
            magnitude = np.abs(fft_output[fft_start:fft_end]).astype(REAL_DTYPE)

            magnitude_mean, magnitude_std = HiFiDecode.mean_stddev(magnitude)

            if (
                magnitude_mean > audio_process_params.muting_amplitude_threshold
                and magnitude_std > audio_process_params.muting_std_threshold
            ):
                # start the mute point, if not currently muted
                if len(mute_point_ranges) == full_spectrum_ranges_count:
                    mute_point_ranges.append(
                        [start, len(audio)]
                    )  # default to end muting at the end of the audio
            else:
                # end the mute point, if currently muted
                if len(mute_point_ranges) > full_spectrum_ranges_count:
                    mute_point_ranges[full_spectrum_ranges_count][1] = end
                    full_spectrum_ranges_count += 1

        # sort and merge any overlapping boundaries
        mute_point_boundaries = HiFiDecode.merge_boundaries(mute_point_ranges)

        for boundary in mute_point_boundaries:
            start = boundary[0]
            fade_start = max(0, start - audio_process_params.muting_fade_samples)
            fade_start_duration = start - fade_start
            if fade_start_duration > 0:
                fade_start_rate = log1p(fade_start_duration)

            end = boundary[1]
            fade_end = min(len(audio), end + audio_process_params.muting_fade_samples)
            fade_end_duration = fade_end - end
            if fade_end_duration > 0:
                fade_end_rate = log1p(fade_end_duration)

            # fade out
            for i in range(fade_start_duration):
                audio[fade_start + i] = (
                    audio[fade_start + i]
                    * log1p(fade_start_duration - i)
                    / fade_start_rate
                )
            # mute
            for i in range(start, end):
                audio[i] = np.finfo(
                    np.float16
                ).eps  # not quite zero to prevent issues with noise reduction
            # fade in
            for i in range(fade_end_duration):
                audio[end + i] = audio[end + i] * log1p(i) / fade_end_rate

    @staticmethod
    def mix_for_mode_stereo(
        l_raw: np.array, r_raw: np.array, decode_mode: str
    ) -> Tuple[np.array, np.array]:
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
    @njit(
        numba.types.void(NumbaAudioArray, numba.types.float32),
        cache=True,
        fastmath=True,
        nogil=True,
    )
    def adjust_gain(audio: np.array, gain: float) -> np.array:
        for i in range(len(audio)):
            audio[i] = audio[i] * gain

    @staticmethod
    def demod_process_audio(
        filtered: np.array, fm: FMdemod, audio_process_params: dict, audio_resampler, audio_final_resampler, measure_perf: bool
    ) -> Tuple[np.array, float, dict]:
        perf_measurements = {
            "start_demod": 0,
            "end_demod": 0,
            "start_audio_resample": 0,
            "end_audio_resample": 0,
            "start_dc_trim": 0,
            "end_dc_trim": 0,
            "start_headswitch": 0,
            "end_headswitch": 0,
            "start_audio_final_resample": 0,
            "end_audio_final_resample": 0,
        }

        # demodulate
        if measure_perf:
            perf_measurements["start_demod"] = perf_counter()
        audio = np.empty(len(filtered), dtype=REAL_DTYPE)
        fm.work(filtered, audio)
        if measure_perf:
            perf_measurements["end_demod"] = perf_counter()

        # resample if sample rate to audio sample rate
        if measure_perf:
            perf_measurements["start_audio_resample"] = perf_counter()
        audio: np.array = audio_resampler.resample_chunk(audio, True)
        audio_resampler.clear()
        if measure_perf:
            perf_measurements["end_audio_resample"] = perf_counter()

        # cancel dc based on mean, remove spikes at end of signal
        if measure_perf:
            perf_measurements["start_dc_trim"] = perf_counter()
        dc = HiFiDecode.cancelDC_trim(audio, audio_process_params.pre_trim)
        if measure_perf:
            perf_measurements["end_dc_trim"] = perf_counter()

        # mute audio when carrier loss occurs
        if measure_perf:
            perf_measurements["start_mute"] = perf_counter()
        if audio_process_params.muting_enabled:
            HiFiDecode.mute(audio, audio_process_params)
        if measure_perf:
            perf_measurements["end_mute"] = perf_counter()

        # do head switching noise cancellation if enabled
        if measure_perf:
            perf_measurements["start_headswitch"] = perf_counter()
        if audio_process_params.headswitch_interpolation_enabled:
            audio = HiFiDecode.headswitch_remove_noise(audio, audio_process_params)
        if measure_perf:
            perf_measurements["end_headswitch"] = perf_counter()

        # resample audio sample rate to final audio sample rate
        if measure_perf:
            perf_measurements["start_audio_final_resample"] = perf_counter()
        if audio_process_params.audio_rate != audio_process_params.audio_final_rate:
            audio: np.array = audio_final_resampler.resample_chunk(audio, True)
            audio_final_resampler.clear()
        if measure_perf:
            perf_measurements["end_audio_final_resample"] = perf_counter()

        return audio, dc, perf_measurements

    def block_decode(
        self,
        rf_data: np.array,
        measure_perf: bool = False,
    ) -> Tuple[int, np.array, np.array]:
        # Do a bandpass filter to remove any the video components from the signal.
        if measure_perf:
            start_bandpassRF = perf_counter()

        rf_data = self.bandpassRF.work(rf_data)
        if measure_perf:
            end_bandpassRF = perf_counter()

        # resample from input sample rate to if sample rate
        if measure_perf:
            start_if_resampler = perf_counter()

        if self.options["demod_type"] == DEMOD_HILBERT:
            rf_data = rf_data.astype(np.float32, copy=False)
            rf_data_resampled = self.if_resampler.resample_chunk(rf_data, True)
            self.if_resampler.clear()
        else:
            rf_data_resampled = rf_data

        if measure_perf:
            end_if_resampler = perf_counter()

        # low pass filter to remove any remaining high frequency noise
        # disabled since it interferes with head switching noise detection
        # preL = self.preAudioResampleL.lfilt(preL)
        # preR = self.preAudioResampleR.lfilt(preR)
        # preL = preL.astype(REAL_DTYPE, copy=False)
        # preR = preR.astype(REAL_DTYPE, copy=False)

        # with ProcessPoolExecutor(2) as stereo_executor:
        #     audioL_future = stereo_executor.submit(HiFiDecode.audio_process, preL, self.audio_process_params)
        #     audioR_future = stereo_executor.submit(HiFiDecode.audio_process, preR, self.audio_process_params)
        #     preL, dcL = audioL_future.result()
        #     preR, dcR = audioR_future.result()

        if measure_perf:
            start_carrier_filter = perf_counter()
        if self.audio_process_params.decode_mode != 'r': filterL = self.afeL.work(rf_data_resampled)
        if self.audio_process_params.decode_mode != 'l': filterR = self.afeR.work(rf_data_resampled)
        if measure_perf:
            end_carrier_filter = perf_counter()

        if self.options["grc"] and ZMQ_AVAILABLE:
            self.grc.send(filterL + filterR)

        if self.audio_process_params.decode_mode != 'r': 
            preL, dcL, perf_measurements_l = HiFiDecode.demod_process_audio(
                filterL, self.fmL, self.audio_process_params, self.audio_resampler_l, self.audio_final_resampler_l, measure_perf
            )
        else:
            preL = None
            dcL = 0
            perf_measurements_l = 0
        if self.audio_process_params.decode_mode != 'l': 
            preR, dcR, perf_measurements_r = HiFiDecode.demod_process_audio(
                filterR, self.fmR, self.audio_process_params, self.audio_resampler_r, self.audio_final_resampler_r, measure_perf
            )
        else:
            preR = None
            dcR = 0
            perf_measurements_r = 0

        # fine tune carrier frequency
        if measure_perf:
            start_auto_fine_tune = perf_counter()
        if self.options["auto_fine_tune"]:
            self.auto_fine_tune(dcL, dcR)
            self.log_bias()
        if measure_perf:
            end_auto_fine_tune = perf_counter()

        # mix for various stereo modes
        if measure_perf:
            start_stereo_mix = perf_counter()
        preL, preR = HiFiDecode.mix_for_mode_stereo(
            preL, preR, self.audio_process_params.decode_mode
        )
        if measure_perf:
            end_stereo_mix = perf_counter()

        if measure_perf:
            start_adjust_gain = perf_counter()
        if self.audio_process_params.gain != 1:
            HiFiDecode.adjust_gain(preL, self.audio_process_params.gain)
            HiFiDecode.adjust_gain(preR, self.audio_process_params.gain)
        if measure_perf:
            end_adjust_gain = perf_counter()

        assert (
            preL.dtype == REAL_DTYPE
        ), f"Audio data must be in {REAL_DTYPE} format, instead got {preL.dtype}"
        assert (
            preR.dtype == REAL_DTYPE
        ), f"Audio data must be in {REAL_DTYPE} format, instead got {preR.dtype}"

        if measure_perf:
            duration_bandpassRF = end_bandpassRF - start_bandpassRF
            duration_if_resampler = end_if_resampler - start_if_resampler
            duration_carrier_filter = end_carrier_filter - start_carrier_filter

            duration_demod_l = (
                perf_measurements_l["end_demod"] - perf_measurements_l["start_demod"]
            )
            duration_audio_resample_l = (
                perf_measurements_l["end_audio_resample"]
                - perf_measurements_l["start_audio_resample"]
            )
            duration_dc_trim_l = (
                perf_measurements_l["end_dc_trim"]
                - perf_measurements_l["start_dc_trim"]
            )
            duration_mute_l = (
                perf_measurements_l["end_mute"] - perf_measurements_l["start_mute"]
            )
            duration_headswitch_l = (
                perf_measurements_l["end_headswitch"]
                - perf_measurements_l["start_headswitch"]
            )
            duration_audio_final_resample_l = (
                perf_measurements_l["end_audio_final_resample"]
                - perf_measurements_l["start_audio_final_resample"]
            )

            duration_demod_r = (
                perf_measurements_r["end_demod"] - perf_measurements_r["start_demod"]
            )
            duration_audio_resample_r = (
                perf_measurements_r["end_audio_resample"]
                - perf_measurements_r["start_audio_resample"]
            )
            duration_dc_trim_r = (
                perf_measurements_r["end_dc_trim"]
                - perf_measurements_r["start_dc_trim"]
            )
            duration_mute_r = (
                perf_measurements_r["end_mute"] - perf_measurements_r["start_mute"]
            )
            duration_headswitch_r = (
                perf_measurements_r["end_headswitch"]
                - perf_measurements_r["start_headswitch"]
            )
            duration_audio_final_resample_r = (
                perf_measurements_r["end_audio_final_resample"]
                - perf_measurements_r["start_audio_final_resample"]
            )

            duration_auto_fine_tune = end_auto_fine_tune - start_auto_fine_tune
            duration_stereo_mix = end_stereo_mix - start_stereo_mix
            duration_adjust_gain = end_adjust_gain - start_adjust_gain
            durations = [
                ("duration_bandpassRF", duration_bandpassRF),
                ("duration_if_resampler", duration_if_resampler),
                ("duration_carrier_filter", duration_carrier_filter),
                ("duration_demod_l", duration_demod_l),
                ("duration_audio_resample_l", duration_audio_resample_l),
                ("duration_dc_trim_l", duration_dc_trim_l),
                ("duration_mute_l", duration_mute_l),
                ("duration_headswitch_l", duration_headswitch_l),
                ("duration_audio_final_resample_l", duration_audio_final_resample_l),
                ("duration_demod_r", duration_demod_r),
                ("duration_audio_resample_r", duration_audio_resample_r),
                ("duration_dc_trim_r", duration_dc_trim_r),
                ("duration_mute_r", duration_mute_r),
                ("duration_headswitch_r", duration_headswitch_r),
                ("duration_audio_final_resample_r", duration_audio_final_resample_r),
                ("duration_auto_fine_tune", duration_auto_fine_tune),
                ("duration_stereo_mix", duration_stereo_mix),
                ("duration_adjust_gain", duration_adjust_gain),
            ]
            durations.sort(reverse=True, key=lambda x: x[1])
            print("decode performance", durations)

        return preL, preR

    @staticmethod
    def hifi_decode_worker(
        decoder_in_queue, decoder_out_queue, decode_options, standard
    ):
        setproctitle(current_process().name)
        measure_perf = False
        decoder = HiFiDecode(decode_options, is_main_process=False)
        decoder.standard = standard

        # @profile
        def decode_next_block():
            while True:
                try:
                    decoder_state = decoder_in_queue.get()
                    break
                except InterruptedError:
                    pass
                except EOFError:
                    return

            buffer = DecoderSharedMemory(decoder_state)
            if decoder_state.is_last_block:
                raw_data = buffer.get_last_block()
            else:
                raw_data = buffer.get_block()

            audioL, audioR = decoder.block_decode(
                raw_data,
                measure_perf,
            )

            if measure_perf:
                start_final_audio_copy = perf_counter()
            # copy the audio data into the shared buffer
            l_out = buffer.get_pre_left()
            r_out = buffer.get_pre_right()

            # shift the audio left to remove the block overlap
            audio_len = len(audioL)
            expected_len = decoder_state.block_audio_final_len
            overlap_to_trim = max(0, round((audio_len - expected_len) / 2))

            DecoderSharedMemory.copy_data_src_offset_float32(
                audioL, l_out, overlap_to_trim, audio_len
            )
            DecoderSharedMemory.copy_data_src_offset_float32(
                audioR, r_out, overlap_to_trim, audio_len
            )
            if measure_perf:
                end_final_audio_copy = perf_counter()

            if measure_perf:
                final_audio_copy_duration = (
                    end_final_audio_copy - start_final_audio_copy
                )
                print("final_audio_copy_duration:", final_audio_copy_duration)
                print()

            buffer.close()
            decoder_out_queue.put(decoder_state)

        while True:
            decode_next_block()

    @staticmethod
    def debug_peak_interpolation(
        audio,
        filtered_signal,
        filtered_signal_abs,
        peaks,
        interpolation_boundaries,
        interpolated,
        headswitch_signal_rate,
    ):
        fs = headswitch_signal_rate
        t = np.arange(0, len(audio)) / fs
        fft_signal = np.fft.fft(audio)
        fft_freqs = np.fft.fftfreq(len(t), 1 / fs)

        # Only keep the positive half of the frequency spectrum
        positive_freqs = fft_freqs[: len(t) // 2]
        positive_fft_signal = np.abs(fft_signal[: len(t) // 2])

        # Perform the FFT on the filtered signal
        fft_filtered_signal = np.fft.fft(filtered_signal)
        positive_fft_filtered_signal = np.abs(fft_filtered_signal[: len(t) // 2])

        plt.figure(figsize=(10, 6))
        plt.plot(positive_freqs, positive_fft_signal, label="Original Signal Spectrum")
        plt.plot(
            positive_freqs,
            positive_fft_filtered_signal,
            label="Filtered Signal Spectrum",
            color="orange",
        )
        plt.title("Frequency Spectrum")
        plt.xlabel("Frequency [Hz]")
        plt.ylabel("Magnitude")
        plt.legend()

        plt.figure(figsize=(10, 6))

        plt.subplot(4, 1, 1)
        plt.plot(t, filtered_signal, label="Filtered Signal", color="green")
        plt.title("Filtered Signal")
        plt.xlabel("Time [s]")
        plt.ylabel("Amplitude")
        plt.legend()

        peak_centers = [round(x[0]) for x in peaks]
        peak_starts = [round(x[1]) for x in peaks]
        peak_ends = [round(x[2]) for x in peaks]
        peak_prominences = [x[3] for x in peaks]

        interpolation_starts = [
            max(0, start) for start, end in interpolation_boundaries
        ]
        interpolation_ends = [
            min(end, len(audio) - 1) for start, end in interpolation_boundaries
        ]

        plt.subplot(4, 1, 2)
        plt.plot(
            t,
            filtered_signal_abs,
            label="Filtered Signal Absolute Value",
            color="black",
        )
        plt.plot(
            t[interpolation_starts],
            filtered_signal_abs[interpolation_starts],
            "r+",
            label="Interpolation Start",
        )
        plt.plot(t[peak_starts], filtered_signal_abs[peak_starts], "b+", label="Start")
        plt.plot(t[peak_centers], peak_prominences, "gx", label="Prominence")
        plt.plot(
            t[peak_centers], filtered_signal_abs[peak_centers], "go", label="Center"
        )
        plt.plot(t[peak_ends], filtered_signal_abs[peak_ends], "bx", label="End")
        plt.plot(
            t[interpolation_ends],
            filtered_signal_abs[interpolation_ends],
            "rx",
            label="Interpolation End",
        )
        plt.title("Filtered Signal with head switch points")
        plt.xlabel("Time [s]")
        plt.ylabel("Amplitude")
        plt.legend()

        plt.subplot(4, 1, 3)
        plt.plot(t, interpolated, label="Interpolated audio", color="green")
        plt.title("Interpolated Audio")
        plt.xlabel("Time [s]")
        plt.ylabel("Amplitude")
        plt.legend()

        plt.subplot(4, 1, 4)
        plt.plot(t, audio, label="Original Signal")
        plt.title("Original Signal")
        plt.xlabel("Time [s]")
        plt.ylabel("Amplitude")
        plt.legend()
