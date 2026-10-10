"""Unit tests for the compiled wow-spline evaluator in lddecode.dsp.

Field.downscale and the CVBS resampler evaluate the expected-to-actual
line location spline, and its slope, at every output sample of every field.
scipy's BSpline did that by de Boor recursion, twice, at about 5 % of a
decode; interp_spline_with_slope() converts the same spline to one
polynomial per knot interval and evaluates both in one compiled pass.  It
must agree with the BSpline to rounding, inside the data and in the
extrapolated margins the field's first and last lines reach into.
"""

import numpy as np
import pytest
from scipy.interpolate import make_interp_spline

from lddecode.dsp import interp_spline_with_slope

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

INLINELEN = 2546.0  # roughly one NTSC line at 40 Msps, in samples


def _linelocs(rng, n=264):
    """Expected and actual line locations with a random-walk wow."""
    expected = np.arange(n, dtype=np.float64) * INLINELEN
    actual = expected + 50.0 + np.cumsum(rng.normal(0.0, 0.3, n))
    return expected, actual


@pytest.mark.parametrize("k, bc_type", [(1, None), (2, None), (3, "natural")])
def test_matches_the_bspline_inside_and_beyond_the_data(k, bc_type):
    rng = np.random.default_rng(12345)
    x, y = _linelocs(rng)
    # Output pixels from a line before the first to a line past the last
    xq = np.arange(-INLINELEN, x[-1] + INLINELEN, INLINELEN / 910.0)
    spl = make_interp_spline(x, y, k=k, bc_type=bc_type)

    values, slopes = interp_spline_with_slope(x, y, xq, k=k, bc_type=bc_type)

    # Positions are ~7e5 samples: 1e-8 is a few ulp of headroom, and far
    # below anything the sinc resampler can resolve.
    np.testing.assert_allclose(values, spl(xq), rtol=0, atol=1e-8)
    np.testing.assert_allclose(slopes, spl(xq, 1), rtol=0, atol=1e-10)


def test_linear_slope_is_each_intervals_gradient():
    x = np.array([0.0, 10.0, 20.0, 40.0])
    y = np.array([0.0, 10.0, 30.0, 30.0])
    xq = np.array([-5.0, 0.0, 5.0, 10.0, 15.0, 39.0, 40.0, 45.0])

    values, slopes = interp_spline_with_slope(x, y, xq, k=1)

    # A knot belongs to the interval it opens, as in BSpline; the ends
    # extrapolate their own interval.
    np.testing.assert_allclose(values, [-5.0, 0.0, 5.0, 10.0, 20.0, 30.0, 30.0, 30.0])
    np.testing.assert_allclose(slopes, [1.0, 1.0, 1.0, 2.0, 2.0, 0.0, 0.0, 0.0])


def test_unsorted_and_two_dimensional_queries():
    rng = np.random.default_rng(54321)
    x, y = _linelocs(rng, n=40)
    xq = rng.uniform(-INLINELEN, x[-1] + INLINELEN, size=(50, 7))
    spl = make_interp_spline(x, y, k=3, bc_type="natural")

    values, slopes = interp_spline_with_slope(x, y, xq, k=3, bc_type="natural")

    assert values.shape == xq.shape and slopes.shape == xq.shape
    np.testing.assert_allclose(values, spl(xq), rtol=0, atol=1e-8)
    np.testing.assert_allclose(slopes, spl(xq, 1), rtol=0, atol=1e-10)
