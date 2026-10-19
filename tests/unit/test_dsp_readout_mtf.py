"""Unit tests for the disc readout MTF model in lddecode.dsp.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The readout passes spatial frequency through the overlap of the zero and
first diffracted orders in the objective's pupil - the autocorrelation of
the pupil amplitude - with IEC 60857's reference readout filling the pupil
with a Gaussian 23 % (intensity) at the rim.  The compensation equalises
the channel to a straight line rather than to flat, because a zero-phase
response affine in frequency leaves an FM signal's phase alone.
"""

import numpy as np
import pytest

from lddecode import dsp

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

FS = 40e6


def test_a_uniform_pupil_gives_the_textbook_arccos_mtf():
    s, otf = dsp.readout_otf_table(1.0)
    x = np.linspace(0.0, 1.0, 21)
    arccos = 2 / np.pi * (np.arccos(x) - x * np.sqrt(1 - x * x))
    assert np.interp(x, s, otf) == pytest.approx(arccos, abs=1e-3)


def test_the_iec_gaussian_fill_falls_faster_than_a_uniform_pupil():
    """23 % at the rim weights the pupil's centre: two shifted pupils
    overlap there at low frequency, little of it is left near the
    cutoff, where the Gaussian fill passes less than a uniform one."""
    low, high = np.array([2e6, 4e6]), np.array([11e6, 12.5e6])
    assert np.all(dsp.readout_otf(low, 13.6e6)
                  > dsp.readout_otf(low, 13.6e6, rim_intensity=1.0))
    assert np.all(dsp.readout_otf(high, 13.6e6)
                  < dsp.readout_otf(high, 13.6e6, rim_intensity=1.0))
    assert np.all(np.diff(dsp.readout_otf(np.linspace(0, 13e6, 30),
                                          13.6e6)) < 0)
    assert dsp.readout_otf(13.6e6, 13.6e6) == 0.0


@pytest.mark.parametrize("cutoff", [13.6e6, 18.1e6, 30.8e6])
def test_the_cutoff_is_recovered_from_the_carrier_tilt(cutoff):
    lo, hi = 8.1e6, 9.3e6
    ratio = dsp.readout_otf(lo, cutoff) / dsp.readout_otf(hi, cutoff)
    assert dsp.readout_cutoff_from_tilt(ratio, lo, hi) == pytest.approx(
        cutoff, rel=1e-6)


@pytest.mark.parametrize("ratio", [1.0, 0.98, float("nan")])
def test_no_tilt_gives_no_cutoff(ratio):
    assert dsp.readout_cutoff_from_tilt(ratio, 8.1e6, 9.3e6) is None


def test_the_compensated_channel_is_a_straight_line_to_zero():
    """compensation x readout: unity at the blanking carrier, falling
    linearly to zero at 0.95 x cutoff, wherever the readout still has
    something to equalise."""
    cutoff, ref = 13.6e6, 8.1e6
    f = np.linspace(3e6, 11.5e6, 50)
    comp = dsp.readout_compensation(f, cutoff, ref)
    channel = dsp.readout_otf(f, cutoff) / dsp.readout_otf(ref, cutoff)
    line = (0.95 * cutoff - f) / (0.95 * cutoff - ref)
    assert comp * channel == pytest.approx(line, abs=0.01)
    assert dsp.readout_compensation(ref, cutoff, ref) == pytest.approx(1.0)
    assert np.all(dsp.readout_compensation(
        np.array([13.0e6, 14e6]), cutoff, ref) == 0.0)


def test_the_zero_is_never_put_below_its_floor():
    """At a cutoff low enough that 0.90 x cutoff falls under peak white's
    upper chroma sideband, the line runs to the floor instead and that
    sideband is still carried on it (the line is checked where the
    readout has something left to equalise, as above)."""
    cutoff, ref, floor = 13.6e6, 8.1e6, 13.0e6
    f = np.linspace(3e6, 11.5e6, 50)
    comp = dsp.readout_compensation(f, cutoff, ref, zero_fraction=0.90,
                                    zero_min_hz=floor)
    channel = dsp.readout_otf(f, cutoff) / dsp.readout_otf(ref, cutoff)
    line = (floor - f) / (floor - ref)
    assert comp * channel == pytest.approx(line, abs=0.01)
    assert dsp.readout_compensation(12.9e6, cutoff, ref, zero_fraction=0.90,
                                    zero_min_hz=floor) > 0.0
    # a cutoff whose own zero is above the floor is left as it was
    np.testing.assert_array_equal(
        dsp.readout_compensation(f, 16e6, ref, zero_fraction=0.90, zero_min_hz=floor),
        dsp.readout_compensation(f, 16e6, ref, zero_fraction=0.90))


def test_the_boost_is_bounded_where_the_readout_has_nothing_left():
    f = np.linspace(1e6, 20e6, 400)
    comp = dsp.readout_compensation(f, 13.6e6, 8.1e6, zero_fraction=1.2,
                                    max_boost_db=20.0)
    assert 20 * np.log10(comp.max()) < 20.0


def test_an_affine_channel_leaves_fm_phase_alone():
    """The premise of the compensation's target: an analytic FM signal
    through a zero-phase response a + b f comes out multiplied by the real
    envelope a + b f_inst, its phase untouched however deep the
    modulation, while a curved response bends the phase."""
    n = 1 << 14
    t = np.arange(n) / FS
    # a carrier swinging 7.6-9.3 MHz under a 1 MHz tone
    f_inst = 8.45e6 + 0.85e6 * np.sin(2 * np.pi * 1.0e6 * t)
    phase = 2 * np.pi * np.cumsum(f_inst) / FS
    x = np.exp(1j * phase)
    freqs = np.fft.fftfreq(n, 1 / FS)
    X = np.fft.fft(x)

    def through(response):
        return np.fft.ifft(X * response)

    def phase_error(y):
        core = slice(n // 8, -n // 8)
        err = np.angle(y[core] * np.conj(x[core]))
        return np.max(np.abs(err))

    affine = np.clip((13.0e6 - np.abs(freqs)) / 4.9e6, 0, None)
    curved = affine ** 2
    assert phase_error(through(affine)) < 1e-3
    assert phase_error(through(curved)) > 0.02


def test_the_carrier_amplitude_is_read_through_noise():
    rng = np.random.default_rng(20261018)
    t = np.arange(800) / FS
    # in-band SNR from 13 dB down to 0 dB (the discs run 20-30)
    for amp, noise, tol in ((1.0, 0.3, 0.02), (0.5, 0.3, 0.04), (1.0, 1.0, 0.08)):
        seg = amp * np.cos(2 * np.pi * 8.1e6 * t) + rng.normal(0, noise, 800)
        assert dsp.carrier_amplitude(seg, FS) == pytest.approx(amp, rel=tol)
    assert dsp.carrier_amplitude(np.zeros(32), FS) is None


def _fm_burst_lines(n_lines, n, carrier, tone, beta, gains, noise, rng):
    """Raw-RF stretches of a carrier sinusoidally modulated by a tone, each
    line of its Bessel spectrum scaled by gains[k] (the channel at
    carrier + k tone), random phase per stretch, white noise added."""
    from scipy.special import jv
    t = np.arange(n) / FS
    out = np.empty((n_lines, n))
    for i in range(n_lines):
        pc, pt = rng.uniform(0, 2 * np.pi, 2)
        x = np.zeros(n)
        for k, g in gains.items():
            x += g * jv(k, beta) * np.cos(2 * np.pi * (carrier + k * tone) * t + pc + k * pt)
        out[i] = 1000 * x + rng.normal(0, noise, n)
    return out


def test_the_burst_sidebands_read_the_channel_whatever_the_burst_level():
    """|J_-1| = |J_1|: the first sidebands stand in the channel's ratio
    for any modulation depth, the noise under them taken out."""
    rng = np.random.default_rng(20261018)
    fsc = 315e6 / 88
    gains = {-2: 2.5, -1: 1.6, 0: 1.0, 1: 0.2, 2: 0.0}
    for beta in (0.12, 0.25):
        segs = _fm_burst_lines(200, 80, 8.1e6, fsc, beta, gains, 6.0, rng)
        lower, upper, _, upper_noise = dsp.tone_sideband_powers(segs, FS, 8.1e6, fsc)
        assert np.sqrt(lower / upper) == pytest.approx(1.6 / 0.2, rel=0.08)
        assert upper > upper_noise


def test_a_lost_upper_sideband_reads_as_noise():
    rng = np.random.default_rng(7)
    fsc = 4.43361875e6
    segs = _fm_burst_lines(200, 72, 7.1e6, fsc, 0.15, {-1: 2.0, 0: 1.0, 1: 0.0}, 6.0, rng)
    lower, upper, lower_noise, upper_noise = dsp.tone_sideband_powers(segs, FS, 7.1e6, fsc)
    assert lower > 10 * lower_noise
    assert abs(upper) < 0.3 * upper_noise
    assert dsp.tone_sideband_powers(np.zeros((0, 80)), FS, 7.1e6, fsc) is None


@pytest.mark.parametrize("cutoff", [13.6e6, 19.9e6, 30.8e6])
def test_the_cutoff_is_recovered_from_the_burst_sidebands(cutoff):
    fsc = 315e6 / 88
    lo, hi = 8.1e6 - fsc, 8.1e6 + fsc
    ratio = dsp.readout_otf(lo, cutoff) / dsp.readout_otf(hi, cutoff)
    assert dsp.readout_cutoff_from_tilt(ratio, lo, hi) == pytest.approx(cutoff, rel=1e-6)
