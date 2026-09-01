"""
test_vits_distortion_maths - the ITU-R BT.1439-1 insertion-signal measures

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

These live in analysis/video_common.py because two callers need them -
analysis/differential_phase.py's report and the VITS conformance checks - and
AGENTS.md section 4.5 puts shared measurement maths there and tests it there.
Each is a pure function of the numbers a measurement produced, so every case
here is a hand-written sequence whose answer follows from the definition in
the standard rather than from a previous run.
"""

import numpy as np
import pytest

from video_common import (
    CHROMA_BAR_STEP_RATIOS,
    chrominance_gain_nonlinearity,
    differential_gain,
    differential_phase,
    luminance_nonlinearity,
    unwrap_about,
)

pytestmark = [pytest.mark.unit, pytest.mark.dsp]


# ---------------------------------------------------------------------------
# Phase unwrapping
# ---------------------------------------------------------------------------

def test_phases_that_straddle_the_wrap_keep_their_true_spread():
    # Two degrees apart, but read modulo 360 as 359 and 1.
    unwrapped = unwrap_about([359.0, 1.0], 359.0)
    assert unwrapped == pytest.approx([359.0, 361.0])
    assert np.ptp(unwrapped) == pytest.approx(2.0)


def test_unwrapping_leaves_a_sequence_that_does_not_wrap_alone():
    phases = [10.0, 12.0, 14.0, 11.0]
    assert unwrap_about(phases, phases[0]) == pytest.approx(phases)


def test_the_reference_is_returned_unchanged():
    assert unwrap_about([42.0], 42.0) == pytest.approx([42.0])


# ---------------------------------------------------------------------------
# Differential gain
# ---------------------------------------------------------------------------

def test_a_flat_subcarrier_has_no_differential_gain():
    peak_to_peak, positive, negative = differential_gain([20.0] * 6)
    assert (peak_to_peak, positive, negative) == (0.0, 0.0, 0.0)


def test_differential_gain_is_referred_to_the_blanking_tread():
    # ITU-R BT.1439-1 3.3.1.3: x = |A_max/A_0 - 1|, y = |A_min/A_0 - 1|,
    # peak-to-peak = |A_max - A_min| / A_0, with A_0 the blanking tread.
    peak_to_peak, positive, negative = differential_gain(
        [20.0, 22.0, 24.0, 25.0, 23.0, 21.0])
    assert positive == pytest.approx(0.25)      # 25/20 - 1
    assert negative == pytest.approx(0.0)       # the minimum is A_0 itself
    assert peak_to_peak == pytest.approx(0.25)  # (25 - 20) / 20


def test_a_monotonic_fall_puts_the_whole_deviation_on_the_negative_side():
    peak_to_peak, positive, negative = differential_gain([20.0, 18.0, 16.0])
    assert positive == pytest.approx(0.0)
    assert negative == pytest.approx(0.2)
    assert peak_to_peak == pytest.approx(0.2)


def test_differential_gain_is_a_ratio_and_not_a_level():
    scaled = differential_gain([40.0, 44.0, 48.0, 50.0, 46.0, 42.0])
    plain = differential_gain([20.0, 22.0, 24.0, 25.0, 23.0, 21.0])
    assert scaled == pytest.approx(plain)


def test_a_reference_index_other_than_the_first_is_honoured():
    peak_to_peak, _, _ = differential_gain([25.0, 20.0], reference_index=1)
    assert peak_to_peak == pytest.approx(0.25)


def test_a_zero_reference_amplitude_is_refused_rather_than_divided_by():
    with pytest.raises(ValueError, match="blanking level is zero"):
        differential_gain([0.0, 20.0, 21.0])


def test_one_tread_is_not_a_differential_measurement():
    with pytest.raises(ValueError, match="at least two treads"):
        differential_gain([20.0])


# ---------------------------------------------------------------------------
# Differential phase
# ---------------------------------------------------------------------------

def test_a_steady_subcarrier_phase_has_no_differential_phase():
    assert differential_phase([12.0] * 6) == (0.0, 0.0, 0.0)


def test_differential_phase_is_referred_to_the_blanking_tread():
    peak_to_peak, positive, negative = differential_phase(
        [0.0, 1.0, 2.0, 3.0, -1.0, 0.5])
    assert positive == pytest.approx(3.0)
    assert negative == pytest.approx(1.0)
    assert peak_to_peak == pytest.approx(4.0)


def test_differential_phase_survives_a_sequence_that_wraps():
    # The same three-degree spread, written either side of zero.
    plain = differential_phase([0.0, 1.5, 3.0])
    wrapped = differential_phase([359.0, 0.5, 2.0])
    assert wrapped == pytest.approx(plain)


def test_one_tread_is_not_a_differential_phase_measurement():
    with pytest.raises(ValueError, match="at least two treads"):
        differential_phase([12.0])


# ---------------------------------------------------------------------------
# Luminance non-linearity
# ---------------------------------------------------------------------------

def test_even_risers_are_perfectly_linear():
    assert luminance_nonlinearity([20.0] * 5) == pytest.approx(0.0)


def test_luminance_non_linearity_is_the_riser_spread_over_the_largest():
    # ITU-R BT.1439-1 3.3.1.1: "the difference between the largest and the
    # smallest amplitude as a percentage of the largest".
    assert luminance_nonlinearity([20.0, 19.0, 18.0, 19.0, 20.0]) == (
        pytest.approx(2.0 / 20.0))


def test_it_is_the_largest_and_not_the_mean_that_normalises():
    # The mean of these is 19.4, which would give 0.103; the definition
    # divides by the largest, giving 0.100.
    assert luminance_nonlinearity([20.0, 18.0, 20.0, 19.0, 20.0]) == (
        pytest.approx(0.10))


def test_a_flat_gain_error_does_not_change_the_non_linearity():
    risers = [20.0, 19.0, 18.0, 19.0, 20.0]
    scaled = [riser * 0.85 for riser in risers]
    assert luminance_nonlinearity(scaled) == pytest.approx(
        luminance_nonlinearity(risers))


def test_a_staircase_that_did_not_rise_is_refused():
    with pytest.raises(ValueError, match="no positive riser"):
        luminance_nonlinearity([0.0, -1.0, -2.0])


def test_one_riser_is_not_a_non_linearity_measurement():
    with pytest.raises(ValueError, match="at least two risers"):
        luminance_nonlinearity([20.0])


# ---------------------------------------------------------------------------
# Chrominance gain non-linearity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("system, amplitudes", [
    # The step ratios BT.1439-1 3.3.1.2 states reproduce this project's own
    # nominals: PAL 20/60/100 % of the reference, NTSC 10/20/40 IRE.
    ("PAL", [10.0, 30.0, 50.0]),
    ("NTSC", [10.0, 20.0, 40.0]),
])
def test_a_correctly_proportioned_bar_has_no_non_linearity(system, amplitudes):
    assert chrominance_gain_nonlinearity(amplitudes, system) == (
        pytest.approx(0.0))


@pytest.mark.parametrize("system", ["PAL", "NTSC"])
def test_a_flat_chroma_gain_error_cancels_out(system):
    nominal = [ratio * 30.0 for ratio in CHROMA_BAR_STEP_RATIOS[system]]
    hot = [value * 1.30 for value in nominal]
    assert chrominance_gain_nonlinearity(hot, system) == pytest.approx(0.0)


def test_a_lifted_outer_step_is_reported_against_its_expected_ratio():
    # PAL k1 = 1/3, so a step 20% above 1/3 of the middle reads 0.20.
    assert chrominance_gain_nonlinearity([12.0, 30.0, 50.0], "PAL") == (
        pytest.approx(0.20))


def test_the_larger_of_the_two_outer_deviations_is_the_answer():
    # k1 step 10% low, k3 step 20% high: the definition takes the larger.
    amplitudes = [9.0, 30.0, 60.0]
    assert chrominance_gain_nonlinearity(amplitudes, "PAL") == (
        pytest.approx(0.20))


def test_lifting_only_the_middle_step_shows_on_both_outer_ratios():
    value = chrominance_gain_nonlinearity([10.0, 39.0, 50.0], "PAL")
    assert value == pytest.approx(1.0 - 10.0 / 13.0, abs=1e-9)


def test_a_bar_without_three_steps_is_refused():
    with pytest.raises(ValueError, match="three steps"):
        chrominance_gain_nonlinearity([10.0, 30.0], "PAL")


def test_a_zero_middle_step_is_refused_rather_than_divided_by():
    with pytest.raises(ValueError, match="zero amplitude"):
        chrominance_gain_nonlinearity([10.0, 0.0, 50.0], "PAL")
