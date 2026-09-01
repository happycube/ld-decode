"""Unit tests for the sub-sample zero-crossing finders in lddecode.filters.

calczc() is the measurement every timing decision downstream is built on: sync
edge positions, burst zero crossings, pilot phase.  A half-sample error here is
a half-sample error in every line location, so the tests below pin both the
integer search (which sample pair brackets the crossing) and the fractional
interpolation between them.

The signals are ramps and sines built in the test, so the exact answer is known
analytically rather than being whatever the code happened to return.
"""

import numpy as np
import pytest

from lddecode.filters import calczc, calczc_do, calczc_findfirst

pytestmark = [pytest.mark.unit, pytest.mark.dsp]


# 1 MHz sampled at 40 MHz: 40 samples per cycle.  Fast enough that linear
# interpolation across a zero crossing is accurate to well under 0.01 samples,
# and close to the real burst/pilot geometry the function is used on.
SINE_FS = 40e6
SINE_HZ = 1e6
SINE_PERIOD = SINE_FS / SINE_HZ


def sine(length, shift=0.0):
    """sin(2*pi*(n - shift)/period): zero crossings at shift + period/2 * k."""
    n = np.arange(float(length))
    return np.sin(2 * np.pi * (n - shift) / SINE_PERIOD)


def test_findfirst_returns_the_sample_after_the_crossing():
    ramp = np.arange(0.0, 10.0)

    # data[3] = 3.0 < 3.5 <= 4.0 = data[4], so the first bracketing index is 4.
    assert calczc_findfirst(ramp, 3.5, True) == 4
    # A rising ramp never falls through the target.
    assert calczc_findfirst(ramp, 3.5, False) is None


def test_findfirst_target_landing_exactly_on_a_sample():
    ramp = np.arange(0.0, 10.0)

    # The comparison is `>= target`, so a target sitting exactly on a sample is
    # reported at that sample, not at the one after it.
    assert calczc_findfirst(ramp, 4.0, True) == 4


def test_ramp_crossing_is_exact():
    ramp = np.arange(0.0, 10.0)

    # A unit-slope ramp is exactly linear, so the linear interpolation calczc_do
    # performs between the bracketing samples is exact to double precision.
    assert calczc_do(ramp, 0, 3.5) == pytest.approx(3.5, abs=1e-12)


def test_falling_ramp_crossing_is_exact():
    falling = 10.0 - np.arange(0.0, 10.0)

    assert calczc_do(falling, 0, 3.5) == pytest.approx(6.5, abs=1e-12)


def test_edge_direction_selects_which_crossing_is_found():
    # Half a cycle of sine either side of the start point: there is a falling
    # crossing at 20.3 and a rising one at 40.3.
    data = sine(80, shift=0.3)

    # edge=0 takes the direction from the sample at the start offset, which is
    # positive here, so it looks for the falling crossing.
    assert calczc(data, 1, 0.0, count=60) == pytest.approx(20.3, abs=0.01)
    assert calczc(data, 1, 0.0, edge=-1, count=60) == pytest.approx(20.3, abs=0.01)
    assert calczc(data, 1, 0.0, edge=1, count=60) == pytest.approx(40.3, abs=0.01)


@pytest.mark.parametrize("shift", [0.0, 0.1, 0.3, 0.5, 0.7, 0.9])
def test_subsample_position_matches_the_analytic_crossing(shift):
    data = sine(80, shift=shift)

    # The falling crossing sits half a period after the rising one at `shift`.
    expected = shift + SINE_PERIOD / 2
    found = calczc(data, 1, 0.0, count=60)

    # Chord-vs-arc error for a sine sampled 40x per cycle: the interpolation is
    # linear, the signal is not, and the residual is under 0.001 samples.  0.01
    # samples is a quarter of a nanosecond at 40 MHz -- far below the timing
    # resolution anything downstream claims.
    assert found == pytest.approx(expected, abs=0.01)


def test_no_crossing_returns_none():
    ramp = np.arange(0.0, 10.0)

    assert calczc_do(ramp, 0, 100.0) is None
    assert calczc(ramp, 0, 100.0) is None


def test_crossing_beyond_the_search_window_returns_none():
    ramp = np.arange(0.0, 20.0)

    # count bounds the search to data[start:start + count + 1].
    assert calczc_do(ramp, 0, 8.5, 0, 4) is None
    assert calczc_do(ramp, 0, 8.5, 0, 16) == pytest.approx(8.5, abs=1e-12)


def test_crossing_in_the_first_sample_pair():
    ramp = np.arange(0.0, 10.0)

    # The search starts at index 1, so the earliest crossing that can be
    # reported lies between samples 0 and 1.
    assert calczc_do(ramp, 0, 0.5) == pytest.approx(0.5, abs=1e-12)


def test_crossing_in_the_last_sample_pair():
    ramp = np.arange(0.0, 10.0)

    # Crossing between samples 8 and 9, the last pair in the buffer.  The
    # window is clamped by the slice, so this must not read past the end.
    assert calczc_do(ramp, 8, 8.5, count=1) == pytest.approx(8.5, abs=1e-12)


def test_reverse_search_finds_the_crossing_before_the_start_offset():
    ramp = np.arange(0.0, 10.0)

    # Searching backwards from sample 9 finds the same crossing as searching
    # forwards from 0, reported in the same coordinates.
    assert calczc(ramp, 9, 3.5, reverse=True) == pytest.approx(3.5, abs=1e-12)


def test_reverse_search_with_no_crossing_returns_none():
    ramp = np.arange(0.0, 10.0)

    assert calczc(ramp, 9, 100.0, reverse=True) is None
