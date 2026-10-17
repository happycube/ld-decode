"""Unit tests for the chroma gain recorded in the metadata.

The decoded samples carry whatever burst the fixed filter chain gives them, so the
metadata says what gain would bring it to its nominal level; a chroma decoder can then
apply it.  The gain is a median over the fields, so a few fields with no burst, or with
a burst that is a measurement fault, do not move it.
"""

import numpy as np
import pytest

from lddecode.metrics import MIN_USABLE_BURST_IRE, chroma_gain_to_nominal

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

NOMINAL = 20.0


def test_a_burst_at_nominal_needs_no_gain():
    assert chroma_gain_to_nominal([20.0] * 5, NOMINAL) == pytest.approx(1.0, abs=1e-12)


def test_a_low_burst_needs_the_ratio_of_nominal_to_the_burst():
    assert chroma_gain_to_nominal([15.0, 15.0, 15.0], NOMINAL) == pytest.approx(20.0 / 15.0)


def test_the_gain_follows_the_median_not_the_mean():
    levels = [15.0, 15.0, 15.0, 15.0, 60.0]

    assert chroma_gain_to_nominal(levels, NOMINAL) == pytest.approx(20.0 / 15.0)


@pytest.mark.parametrize("unusable", [None, float("nan"), float("inf"), 0.0, MIN_USABLE_BURST_IRE])
def test_a_field_without_a_usable_burst_is_ignored(unusable):
    levels = [16.0, unusable, 16.0]

    assert chroma_gain_to_nominal(levels, NOMINAL) == pytest.approx(20.0 / 16.0)


def test_no_usable_burst_gives_no_gain():
    assert chroma_gain_to_nominal([], NOMINAL) is None
    assert chroma_gain_to_nominal([None, float("nan"), 1.0], NOMINAL) is None


def test_the_nominal_level_is_the_systems_own():
    ntsc = chroma_gain_to_nominal([15.0], 20.0)
    pal = chroma_gain_to_nominal([15.0], 21.5)

    assert pal / ntsc == pytest.approx(21.5 / 20.0)


def test_an_array_of_levels_is_accepted_and_left_alone():
    levels = np.array([15.0, np.nan, 15.0])

    assert chroma_gain_to_nominal(levels, NOMINAL) == pytest.approx(20.0 / 15.0)
    assert np.isnan(levels[1])
