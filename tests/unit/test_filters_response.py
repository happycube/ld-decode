"""Unit tests for the filter designers in lddecode.filters.

These assert filter *properties* -- passband gain, band-edge attenuation,
stopband floor, the analytic-signal identity -- rather than taps or a golden
array.  A golden array tells you a coefficient changed; it does not tell you
whether the filter still does its job, and it goes stale the moment SciPy
changes a rounding detail.

Everything here is frequency-domain maths on synthesised signals, so no data
and no I/O is involved.
"""

import numpy as np
import pytest
import scipy.signal as sps

from lddecode.filters import build_hilbert, emphasis_iir, filtfft, gen_bpf_supergauss

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

# A 40 MHz RF sample rate and a 1024-bin block: small enough to be quick, and
# the bin spacing (39.0625 kHz) divides the band edges used below exactly, so
# the response can be sampled at the edge rather than near it.
FREQ_HZ = 40e6
BLOCK_LEN = 1024
BIN_HZ = FREQ_HZ / BLOCK_LEN


def db(x):
    """Magnitude in dB, with a floor so a response that underflows to exactly
    zero reads as -inf-ish rather than raising a divide-by-zero warning.  The
    high-order super-Gaussians really do reach 0.0 in double precision."""
    return 20 * np.log10(np.maximum(np.abs(x), np.finfo(float).tiny))


# --- gen_bpf_supergauss ----------------------------------------------------


def test_supergauss_is_unity_at_the_band_centre():
    lo_bin, hi_bin = 100, 300
    response = gen_bpf_supergauss(
        lo_bin * BIN_HZ, hi_bin * BIN_HZ, 3, FREQ_HZ / 2, BLOCK_LEN
    )

    # The super-Gaussian is exp(0) at its centre by construction, so this is an
    # exact identity, not an approximation: any drift means the centre
    # frequency is no longer where the caller asked for it.
    assert response[(lo_bin + hi_bin) // 2] == pytest.approx(1.0, abs=1e-12)


def test_supergauss_is_six_db_down_at_the_band_edges():
    lo_bin, hi_bin = 100, 300
    response = gen_bpf_supergauss(
        lo_bin * BIN_HZ, hi_bin * BIN_HZ, 3, FREQ_HZ / 2, BLOCK_LEN
    )

    # supergauss() folds a factor of log(2)/2 into its exponent precisely so
    # that the requested freq_low/freq_high land on the half-amplitude points,
    # i.e. the arguments are -6.02 dB corners and not -3 dB ones.  Tolerance is
    # double-precision exp() round-off, so 1e-12 rather than a dB figure.
    assert response[lo_bin] == pytest.approx(0.5, abs=1e-12)
    assert response[hi_bin] == pytest.approx(0.5, abs=1e-12)


@pytest.mark.parametrize("order", [1, 2, 3, 6])
def test_supergauss_stopband_floor(order):
    lo_bin, hi_bin = 200, 300
    response = gen_bpf_supergauss(
        lo_bin * BIN_HZ, hi_bin * BIN_HZ, order, FREQ_HZ / 2, BLOCK_LEN
    )

    # One full bandwidth clear of each edge (100 bins = 3.9 MHz), every order
    # is at least 50 dB down -- order 1, the gentlest skirt the designer will
    # be asked for, reaches -54 dB and the sharper orders run off the bottom of
    # double precision.  That rejection is what the RF bandpass is there for:
    # keep the audio carriers and out-of-band noise out of the FM demodulator.
    guard = hi_bin - lo_bin
    below = response[: lo_bin - guard]
    above = response[hi_bin + guard : BLOCK_LEN // 2]

    assert db(below.max()) < -50.0
    assert db(above.max()) < -50.0


def test_supergauss_upper_half_mirrors_the_lower_half_exactly():
    response = gen_bpf_supergauss(100 * BIN_HZ, 300 * BIN_HZ, 3, FREQ_HZ / 2, BLOCK_LEN)

    assert len(response) == BLOCK_LEN
    # The negative-frequency half is a reversed copy of bins 0..N/2-1, so
    # response[N-1-k] == response[k].  Built by np.flip, so this is exact.
    lower = response[: BLOCK_LEN // 2]
    upper = response[BLOCK_LEN // 2 :]
    assert np.array_equal(upper, lower[::-1])


def test_supergauss_is_real_and_non_negative():
    response = gen_bpf_supergauss(100 * BIN_HZ, 300 * BIN_HZ, 3, FREQ_HZ / 2, BLOCK_LEN)

    # A magnitude-only (zero-phase) filter: adding an imaginary part here would
    # silently introduce group delay into every path that multiplies by it.
    assert response.dtype.kind == "f"
    assert response.min() >= 0.0


# --- build_hilbert ---------------------------------------------------------


def test_hilbert_coefficients_are_exact():
    h = build_hilbert(16)

    # Integer-valued by construction: DC and Nyquist pass at unity, the
    # positive frequencies are doubled, the negative ones are zeroed.
    expected = np.array([1, 2, 2, 2, 2, 2, 2, 2, 1, 0, 0, 0, 0, 0, 0, 0], dtype=float)
    assert np.array_equal(h, expected)


def test_hilbert_rejects_an_odd_block_length():
    # There is no Nyquist bin to halve in an odd-length transform, so the
    # construction is undefined rather than merely inaccurate.
    with pytest.raises(Exception):
        build_hilbert(15)


def test_hilbert_produces_an_analytic_signal():
    n_bins = 1024
    bin_index = 37
    amplitude = 3.0
    phase = 0.4
    n = np.arange(n_bins)
    real_tone = amplitude * np.cos(2 * np.pi * bin_index * n / n_bins + phase)

    analytic = np.fft.ifft(np.fft.fft(real_tone) * build_hilbert(n_bins))

    # The defining properties of the analytic signal of a real tone: the real
    # part is unchanged and the envelope is the tone's amplitude everywhere.
    # This is what the demodulator relies on -- the envelope carries the RF
    # level and the phase derivative carries the FM.  Tolerance is FFT
    # round-off (~1e-13 on an amplitude of 3), not a signal-level allowance.
    assert np.abs(analytic.real - real_tone).max() < 1e-12
    assert np.abs(np.abs(analytic) - amplitude).max() < 1e-12


def test_hilbert_phase_advances_at_the_tone_frequency():
    n_bins = 1024
    bin_index = 37
    n = np.arange(n_bins)
    real_tone = np.cos(2 * np.pi * bin_index * n / n_bins)

    analytic = np.fft.ifft(np.fft.fft(real_tone) * build_hilbert(n_bins))
    increments = np.diff(np.unwrap(np.angle(analytic)))

    # Constant phase increment == flat group delay across the block: an
    # analytic signal built from one bin must not disperse.  Any deviation
    # would appear downstream as an FM demodulation error.
    expected = 2 * np.pi * bin_index / n_bins
    assert np.abs(increments - expected).max() < 1e-12


# --- emphasis_iir ----------------------------------------------------------


def test_deemphasis_is_unity_at_dc():
    # The NTSC video de-emphasis time constants from params.py.
    b, a = emphasis_iir(120e-9, 320e-9, FREQ_HZ)
    response = filtfft((b, a), BLOCK_LEN)

    # The analog prototype is (w2/w1)(s + w1)/(s + w2), which is exactly 1 at
    # s = 0, and the bilinear transform preserves the DC value.  De-emphasis
    # must not shift the black level, so this one is worth pinning tightly.
    assert np.abs(response[0]) == pytest.approx(1.0, abs=1e-12)


def test_deemphasis_asymptote_matches_the_time_constant_ratio():
    t1, t2 = 120e-9, 320e-9
    b, a = emphasis_iir(t1, t2, FREQ_HZ)
    response = filtfft((b, a), BLOCK_LEN)

    # Pre-warped corner frequencies; at Nyquist the bilinear-transformed filter
    # sits exactly on the analog high-frequency asymptote w2/w1.
    w1 = 2 * FREQ_HZ * np.tan((1 / t1) / (2 * FREQ_HZ))
    w2 = 2 * FREQ_HZ * np.tan((1 / t2) / (2 * FREQ_HZ))

    nyquist = np.abs(response[BLOCK_LEN // 2])
    assert nyquist == pytest.approx(w2 / w1, rel=1e-12)
    # 120/320 ns is roughly -8.5 dB of HF cut; assert the sign of the shaping
    # so a swapped argument pair cannot pass.
    assert db(nyquist) < -6.0


def test_preemphasis_is_the_reciprocal_of_deemphasis():
    t1, t2 = 120e-9, 320e-9
    deemph = filtfft(emphasis_iir(t1, t2, FREQ_HZ), BLOCK_LEN)
    preemph = filtfft(emphasis_iir(t2, t1, FREQ_HZ), BLOCK_LEN)

    # Swapping the time constants swaps the zero and the pole, which inverts
    # the transfer function exactly.  This is the property that makes the
    # emphasis/de-emphasis pair transparent end to end, so it is asserted
    # across the whole band rather than at a couple of points.  1e-10 is
    # double-precision round-off through two bilinear transforms and a freqz.
    assert np.abs(deemph * preemph - 1.0).max() < 1e-10


def test_emphasis_is_monotonic_across_the_band():
    b, a = emphasis_iir(120e-9, 320e-9, FREQ_HZ)
    magnitude = np.abs(filtfft((b, a), BLOCK_LEN))[: BLOCK_LEN // 2 + 1]

    # A single-pole/single-zero shelf: the response must fall monotonically
    # from DC to Nyquist.  A ripple here would mean the design had picked up an
    # extra pole pair.
    assert np.all(np.diff(magnitude) <= 1e-15)


# --- filtfft ---------------------------------------------------------------


def test_filtfft_of_a_passthrough_is_all_ones():
    response = filtfft(([1.0], [1.0]), 64)

    assert len(response) == 64
    assert np.abs(response - 1.0).max() < 1e-15


def test_filtfft_of_a_pure_delay_is_a_phase_ramp():
    delay = 2
    taps = np.zeros(delay + 1)
    taps[delay] = 1.0

    response = filtfft((taps, [1.0]), 64)
    k = np.arange(64)

    # A z^-2 delay has unit magnitude and a phase of -2*w.  Asserting the
    # complex value pins the sign convention filtfft hands to every caller that
    # multiplies an FFT block by it; getting it backwards would advance the
    # signal instead of delaying it.
    expected = np.exp(-2j * np.pi * k * delay / 64)
    assert np.abs(response - expected).max() < 1e-12


def test_filtfft_matches_the_frequency_response_of_the_designed_filter():
    b, a = sps.butter(4, 0.25)
    response = filtfft((b, a), 256)

    # filtfft evaluates the whole circle, so bin k and bin N-k are conjugates
    # for a real-coefficient filter.  This is the property callers depend on
    # when they multiply a real signal's FFT by it and take the real part.
    assert np.abs(response[1:128] - np.conj(response[255:128:-1])).max() < 1e-12
