"""Unit tests for scale_spline, the downscaler that evaluates the wow
spline as it goes.

Field.downscale and the CVBS lattice used to evaluate the spline at every
output sample into two whole-field arrays (interp_spline_with_slope) and
hand them to scale_field / scale_positions, which then sorted one of them
twice for the wow outlier medians.  scale_spline does the same work a
chunk at a time and takes a linear spline's medians from one value per
interval.  None of that may change a bit of the output.
"""

import numpy as np
import pytest

from lddecode.dsp import (
    _counted_median,
    _wow_median_mad,
    interp_spline_with_slope,
    scale_field,
    scale_positions,
    scale_spline,
    spline_pieces,
)
from lddecode.rfdecode import RFDecode

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

INLINELEN = 2542.0
OUTLINELEN = 910
METHODS = [(1, None), (2, None), (3, "natural")]


@pytest.fixture(scope="module")
def lut():
    return RFDecode(inputfreq=40, system="NTSC").downscale_sinc_lut


def field(seed, lines=40, outlier=True):
    """A buffer and line locations with wow, jitter and one bad hsync."""
    rng = np.random.default_rng(seed)
    expected = np.arange(lines, dtype=np.float64) * INLINELEN
    wow = 30.0 * np.sin(np.arange(lines) / 6.0)
    actual = expected + 4000.0 + wow + rng.normal(0.0, 0.4, lines)
    if outlier:
        actual[17] += 9.0
    buf = (8.1e6 + 1e5 * rng.standard_normal(int(actual[-1]) + 8000)).astype(np.float32)
    return buf, expected, actual


@pytest.mark.parametrize("k, bc_type", METHODS)
@pytest.mark.parametrize("smoothing", [0, 1.5])
def test_matches_the_raster_path_bit_for_bit(lut, k, bc_type, smoothing):
    buf, expected, actual = field(1)
    lineoffset, outlines = 2, 34
    xq = np.arange((outlines + lineoffset + 1) * OUTLINELEN) * (INLINELEN / OUTLINELEN)

    locs, wow = interp_spline_with_slope(expected, actual, xq, k=k, bc_type=bc_type)
    want = np.zeros(outlines * OUTLINELEN, np.float32)
    scale_field(buf, want, locs, wow, lut, lineoffset, OUTLINELEN,
                wow_level_adjust_smoothing=smoothing)

    breaks, coeffs = spline_pieces(expected, actual, k=k, bc_type=bc_type)
    got = np.zeros_like(want)
    scale_spline(buf, got, OUTLINELEN * (lineoffset + 1), xq, breaks, coeffs,
                 lut, OUTLINELEN, wow_level_adjust_smoothing=smoothing)

    np.testing.assert_array_equal(got.view(np.uint32), want.view(np.uint32))


@pytest.mark.parametrize("k, bc_type", METHODS)
def test_matches_the_lattice_path_bit_for_bit(lut, k, bc_type):
    buf, expected, actual = field(2)
    # Not line-locked: a uniform step that is not a whole fraction of a line
    pos = (np.arange(25000) * (625.0 / 709379) + 3.37) * INLINELEN

    locs, wow = interp_spline_with_slope(expected, actual, pos, k=k, bc_type=bc_type)
    want = np.zeros(len(pos), np.float32)
    scale_positions(buf, want, locs, wow, lut, 709379 / 625.0)

    breaks, coeffs = spline_pieces(expected, actual, k=k, bc_type=bc_type)
    got = np.zeros_like(want)
    scale_spline(buf, got, 0, pos, breaks, coeffs, lut, 709379 / 625.0)

    np.testing.assert_array_equal(got.view(np.uint32), want.view(np.uint32))


@pytest.mark.parametrize("counts", [
    [1], [2], [3, 1], [1, 1, 1, 1], [5, 2, 7], [4, 4], [910] * 7, [910] * 8,
])
def test_counted_median_is_the_median_of_the_expanded_array(counts):
    rng = np.random.default_rng(len(counts))
    values = rng.normal(1.0, 1e-3, len(counts))
    counts = np.array(counts, dtype=np.int64)

    expanded = np.repeat(values, counts)
    assert _counted_median(values, counts, counts.sum()) == np.median(expanded)


def test_counted_median_with_tied_values():
    values = np.array([2.0, 1.0, 2.0, 3.0])
    counts = np.array([1, 2, 1, 1], dtype=np.int64)
    assert _counted_median(values, counts, 5) == np.median([2, 1, 1, 2, 3])


@pytest.mark.parametrize("k, bc_type", METHODS)
def test_wow_medians_match_the_per_sample_medians(k, bc_type):
    _, expected, actual = field(3)
    # A query on every breakpoint, where the interval a point is counted
    # in has to be the one its slope is evaluated in
    xq = np.sort(np.concatenate([
        np.arange(-INLINELEN, expected[-1] + INLINELEN, INLINELEN / OUTLINELEN),
        expected,
    ]))
    _, slopes = interp_spline_with_slope(expected, actual, xq, k=k, bc_type=bc_type)
    median = np.median(slopes)
    mad = np.median(np.abs(slopes - median))

    breaks, coeffs = spline_pieces(expected, actual, k=k, bc_type=bc_type)
    assert _wow_median_mad(breaks, coeffs, xq) == (median, mad)
