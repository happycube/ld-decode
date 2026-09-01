"""Unit tests for the resamplers and level conversions in lddecode.dsp.

These are the functions that turn demodulated RF into output samples: the cubic
line scaler, the sinc-LUT field resamplers that undo wow, the Hz-to-16-bit
conversion, and the analog-audio rescale.  An error in any of them shifts or
tilts the whole picture, so the tests pin the anchor points exactly and the
interpolated values against an analytically known answer.

The sinc lookup table the resamplers take is *injected*, which is what makes
them testable here: the production table is a windowed-sinc kernel loaded from
a file, but the functions themselves only require "a table of tap weights".
The tests hand them a two-tap linear-interpolation table instead, so the
expected output is a straight line evaluation that can be written down rather
than a second implementation of the same convolution.
"""

import numpy as np
import pytest

from lddecode.dsp import (
    dsa_rescale_and_clip,
    hz_to_output_array,
    scale,
    scale_field,
    scale_positions,
    sinc_phase_count,
    sinc_tap_count,
)
from lddecode.params import SysParams_NTSC, SysParams_PAL

pytestmark = [pytest.mark.unit, pytest.mark.dsp]


@pytest.fixture(scope="module")
def linear_lut():
    """A tap table that makes the sinc resamplers do linear interpolation.

    scale_field/scale_positions read taps for samples ``coord_int - 7`` through
    ``coord_int + 8``, so putting ``1 - phase`` on tap 7 and ``phase`` on tap 8
    weights exactly the two samples bracketing the requested position.  The
    resampler's output is then a value we can state in closed form.
    """
    lut = np.zeros((sinc_phase_count + 1, sinc_tap_count), dtype=np.float32)
    phase = np.arange(sinc_phase_count + 1) / sinc_phase_count
    lut[:, (sinc_tap_count // 2) - 1] = 1.0 - phase
    lut[:, sinc_tap_count // 2] = phase
    return lut


# --- scale (cubic line scaler) --------------------------------------------


def test_scale_at_the_source_rate_is_a_verbatim_copy(seeded_rng):
    buf = seeded_rng.normal(0.0, 1.0, 50)

    # When tgtlen equals the source span, every output coordinate lands exactly
    # on a source sample, the cubic's fractional term is zero, and the result is
    # the middle tap unchanged.  Exact equality, not a tolerance: no arithmetic
    # happens beyond a multiply by 1.0.
    assert np.array_equal(scale(buf, 10, 20, 10), buf[10:20])


def test_scale_reproduces_a_straight_line():
    # Catmull-Rom interpolation is exact for polynomials up to cubic, so a ramp
    # resampled at 2x is still a ramp -- at half-sample steps this time.
    buf = np.arange(0.0, 50.0)
    out = scale(buf, 10, 20, 20)

    expected = 10.0 + np.arange(20) * 0.5
    # Pure double-precision arithmetic on small integers; the residual is a few
    # ULP, so 1e-12 is generous and still far tighter than the 1/65536 of full
    # scale that would be visible in the output.
    assert np.abs(out - expected).max() < 1e-12


def test_scale_downsamples_a_straight_line():
    buf = np.arange(0.0, 50.0)
    out = scale(buf, 10, 20, 5)

    expected = 10.0 + np.arange(5) * 2.0
    assert np.abs(out - expected).max() < 1e-12


def test_scale_applies_the_multiplier():
    buf = np.arange(0.0, 50.0)

    plain = scale(buf, 10, 20, 10)
    scaled = scale(buf, 10, 20, 10, mult=3)

    assert np.abs(scaled - 3.0 * plain).max() < 1e-12


def test_scale_returns_the_requested_length():
    buf = np.arange(0.0, 50.0)

    for tgtlen in (1, 7, 10, 33):
        assert len(scale(buf, 10, 20, tgtlen)) == tgtlen


def test_scale_preserves_a_constant_level():
    # A flat line must come back flat at any output rate.  If the cubic's
    # weights did not sum to one this is where it would show, as brightness
    # ripple across a resampled line.
    buf = np.full(50, 42.0)
    out = scale(buf, 10, 20, 37)

    assert np.abs(out - 42.0).max() < 1e-12


# --- scale_field / scale_positions ----------------------------------------


def test_scale_field_resamples_at_the_requested_positions(linear_lut):
    # A ramp, so the resampled value at position p is 3p + 7 exactly.
    buf = np.arange(400.0) * 3.0 + 7.0
    outwidth, lineoffset = 10, 1
    out_len = 20

    start = outwidth * (lineoffset + 1)
    positions = np.linspace(100.0, 119.5, out_len)
    pixel_locs = np.zeros(start + out_len)
    pixel_locs[start:] = positions
    wowfactors = np.full(start + out_len, 2.0)

    dsout = np.zeros(out_len)
    scale_field(buf, dsout, pixel_locs, wowfactors, linear_lut, lineoffset, outwidth)

    expected = 2.0 * (positions * 3.0 + 7.0)
    # scale_field narrows the coordinate to float32 and picks the nearest of
    # 65536 tabulated phases, so the position it actually interpolates at is
    # within about 1e-5 samples of the one asked for.  On a slope of 3 units
    # per sample that is well under 1e-3 units of output, i.e. far below one
    # LSB of the 16-bit sample this feeds.
    assert np.abs(dsout - expected).max() < 1e-3


def test_scale_field_starts_at_the_line_offset(linear_lut):
    # dsout[0] corresponds to pixel_locs[outwidth * (lineoffset + 1)]: the
    # first lineoffset + 1 lines of the location array are skipped.  Getting
    # this wrong shifts the picture by a whole line.
    buf = np.arange(400.0)
    outwidth, lineoffset = 8, 2
    start = outwidth * (lineoffset + 1)

    pixel_locs = np.zeros(start + 4)
    pixel_locs[start:] = [200.0, 201.0, 202.0, 203.0]
    # Fill the skipped region with positions that would give obviously wrong
    # answers if they were read.
    pixel_locs[:start] = 300.0
    wowfactors = np.ones(start + 4)

    dsout = np.zeros(4)
    scale_field(buf, dsout, pixel_locs, wowfactors, linear_lut, lineoffset, outwidth)

    assert np.abs(dsout - np.array([200.0, 201.0, 202.0, 203.0])).max() < 1e-3


def test_scale_positions_resamples_at_the_requested_positions(linear_lut):
    buf = np.arange(400.0) * 3.0 + 7.0
    positions = np.linspace(100.0, 119.5, 20)

    dsout = np.zeros(20)
    scale_positions(
        buf, dsout, positions, np.full(20, 2.0), linear_lut, SysParams_NTSC["outlinelen"]
    )

    expected = 2.0 * (positions * 3.0 + 7.0)
    # scale_positions interpolates between adjacent LUT phases rather than
    # rounding to the nearest, so it is a little tighter than scale_field; the
    # float32 coordinate is still the limit.
    assert np.abs(dsout - expected).max() < 1e-3


def test_scale_positions_is_indexed_one_to_one(linear_lut):
    # Unlike scale_field there is no raster offset here: dsout[i] comes from
    # pixel_locs[i].  This is the property the CVBS lattice depends on, since
    # PAL 4fsc lines are not a fixed number of samples wide.
    buf = np.arange(400.0)
    positions = np.array([100.0, 250.5, 150.25, 300.75])

    dsout = np.zeros(4)
    scale_positions(buf, dsout, positions, np.ones(4), linear_lut, 1135)

    assert np.abs(dsout - positions).max() < 1e-3


def test_wow_outlier_is_replaced_by_the_median(linear_lut):
    # A single bad line location produces a wildly wrong wow factor, which
    # would otherwise show up as one bright or dark line.  Anything more than
    # 15 median absolute deviations from the median falls back to the median.
    buf = np.ones(400)
    positions = np.arange(100.0, 120.0)

    rng = np.random.default_rng(12345)
    wowfactors = 1.0 + rng.normal(0.0, 0.001, 20)
    wowfactors[7] = 1.5

    median = np.median(wowfactors)
    mad = np.median(np.abs(wowfactors - median))
    expected = np.where(np.abs(wowfactors - median) > 15 * mad, median, wowfactors)

    dsout = np.zeros(20)
    scale_positions(buf, dsout, positions, wowfactors.copy(), linear_lut, 1135)

    # buf is all ones, so the output is the level adjustment itself.
    assert np.abs(dsout - expected).max() < 1e-6
    assert dsout[7] == pytest.approx(median, abs=1e-6)


def test_wow_with_no_variance_uses_the_fallback_threshold(linear_lut):
    # When every wow factor is identical the median absolute deviation is zero,
    # so 15 * mad would reject nothing -- or everything, depending on how the
    # comparison is written.  The code substitutes a fixed 0.001 threshold;
    # this pins that an outlier is still caught in that case.
    buf = np.ones(400)
    positions = np.arange(100.0, 120.0)

    wowfactors = np.ones(20)
    wowfactors[5] = 5.0

    dsout = np.zeros(20)
    scale_positions(buf, dsout, positions, wowfactors, linear_lut, 1135)

    assert np.abs(dsout - 1.0).max() < 1e-6


def test_wow_smoothing_is_a_one_pole_filter(linear_lut):
    # With smoothing enabled the level adjustment is low-passed along the
    # field, so a step in wow is approached exponentially instead of applied at
    # once.  Reproducing the recurrence in the test is the only way to state
    # what "smoothed" means numerically.
    buf = np.ones(400)
    positions = np.arange(100.0, 140.0)
    samples_per_line = 1135
    smoothing = 0.001

    wowfactors = np.concatenate([np.full(20, 1.0), np.full(20, 1.02)])

    alpha = 1 / (smoothing * samples_per_line)
    expected = wowfactors.astype(float).copy()
    # The median/MAD clamp runs first; here the two halves are 0.02 apart with
    # a MAD of 0.01, so 15 * mad leaves both alone.
    for i in range(1, len(expected)):
        expected[i] = alpha * expected[i] + (1 - alpha) * expected[i - 1]

    dsout = np.zeros(40)
    scale_positions(
        buf, dsout, positions, wowfactors.copy(), linear_lut, samples_per_line,
        wow_level_adjust_smoothing=smoothing,
    )

    assert np.abs(dsout - expected).max() < 1e-6


# --- hz_to_output_array ---------------------------------------------------

# Field.out_scale is (output_white - output_black) / (100 - vsync_ire); the
# 16-bit output range is set by FieldNTSC/FieldPAL in field.py.  Restated here
# rather than imported, so this stays a test of the layer-0 conversion maths
# and does not drag a layer-3 module into the unit lane.
NTSC_OUTPUT_RANGE = (0x0400, 0xC800)
PAL_OUTPUT_RANGE = (0x0100, 0xD300)


def out_scale_for(sysparams, output_range):
    black, white = output_range
    return np.double(white - black) / (100 - sysparams["vsync_ire"])


def hz_for_ire(sysparams, ire):
    return sysparams["ire0"] + ire * sysparams["hz_ire"]


@pytest.mark.parametrize(
    "sysparams, output_range, expected",
    [
        (SysParams_NTSC, NTSC_OUTPUT_RANGE, (1024, 15360, 51200)),
        (SysParams_PAL, PAL_OUTPUT_RANGE, (256, 16384, 54016)),
    ],
    ids=["NTSC", "PAL"],
)
def test_output_anchor_levels_are_exact(sysparams, output_range, expected):
    out_scale = out_scale_for(sysparams, output_range)
    levels = np.array(
        [
            hz_for_ire(sysparams, sysparams["vsync_ire"]),
            hz_for_ire(sysparams, 0),
            hz_for_ire(sysparams, 100),
        ]
    )

    out = hz_to_output_array(
        levels,
        sysparams["ire0"],
        sysparams["hz_ire"],
        sysparams["outputZero"],
        sysparams["vsync_ire"],
        out_scale,
    )

    # Sync tip, blanking and peak white are the three levels every downstream
    # consumer of a .tbc keys off.  Integer output, so assert them exactly.
    assert tuple(int(v) for v in out) == expected
    assert out.dtype == np.uint16


@pytest.mark.parametrize(
    "sysparams, output_range",
    [(SysParams_NTSC, NTSC_OUTPUT_RANGE), (SysParams_PAL, PAL_OUTPUT_RANGE)],
    ids=["NTSC", "PAL"],
)
def test_output_is_invertible(sysparams, output_range):
    out_scale = out_scale_for(sysparams, output_range)
    ires = np.linspace(sysparams["vsync_ire"], 100.0, 57)
    levels = hz_for_ire(sysparams, ires)

    out = hz_to_output_array(
        levels,
        sysparams["ire0"],
        sysparams["hz_ire"],
        sysparams["outputZero"],
        sysparams["vsync_ire"],
        out_scale,
    )
    # Field.output_to_ire is the documented inverse.
    recovered = (
        (out.astype(np.double) - sysparams["outputZero"]) / out_scale
    ) + sysparams["vsync_ire"]

    # Round trip through a 16-bit integer: the error is bounded by half an
    # output code, which is 1/(2 * out_scale) IRE -- under 0.0015 IRE for both
    # systems.  0.002 IRE is the tolerance that statement implies.
    assert np.abs(recovered - ires).max() < 0.002


def test_output_clips_at_both_rails():
    sysparams = SysParams_NTSC
    out_scale = out_scale_for(sysparams, NTSC_OUTPUT_RANGE)

    levels = np.array([hz_for_ire(sysparams, -1e6), hz_for_ire(sysparams, 1e6)])
    out = hz_to_output_array(
        levels,
        sysparams["ire0"],
        sysparams["hz_ire"],
        sysparams["outputZero"],
        sysparams["vsync_ire"],
        out_scale,
    )

    # Wrapping instead of clipping would turn a dropout into a bright flash.
    assert tuple(int(v) for v in out) == (0, 65535)


def test_output_rounds_to_nearest_rather_than_truncating():
    # scale = 1, offset = 0: the input is the output, so the rounding is the
    # only thing under test.  Without the +0.5 the conversion truncates and
    # every pixel is biased half a code low.
    values = np.array([0.0, 0.4, 0.5, 1.6, 2.5, 100.49, 100.51])
    out = hz_to_output_array(values, 0.0, 1.0, 0.0, 0.0, 1.0)

    assert tuple(int(v) for v in out) == (0, 0, 1, 2, 3, 100, 101)


def test_output_of_empty_input_is_empty():
    out = hz_to_output_array(np.array([]), 8100000.0, 12142.857, 1024, -40, 358.4)

    assert len(out) == 0
    assert out.dtype == np.uint16


def test_output_of_a_single_sample():
    sysparams = SysParams_NTSC
    out_scale = out_scale_for(sysparams, NTSC_OUTPUT_RANGE)

    out = hz_to_output_array(
        np.array([float(sysparams["ire0"])]),
        sysparams["ire0"],
        sysparams["hz_ire"],
        sysparams["outputZero"],
        sysparams["vsync_ire"],
        out_scale,
    )

    assert len(out) == 1
    assert int(out[0]) == 15360


# --- dsa_rescale_and_clip -------------------------------------------------


def test_audio_rescale_anchor_points():
    # 371081.0 Hz of deviation is the analog audio full-scale figure the
    # decoder normalises against; it maps to full scale in the output word.
    assert dsa_rescale_and_clip(0.0) == 0
    assert dsa_rescale_and_clip(371081.0 / 2) == 16384
    assert dsa_rescale_and_clip(-371081.0 / 2) == -16384


def test_audio_rescale_leaves_one_code_of_headroom():
    # Historical behaviour: the 16-bit path clips at +/-32766, one code inside
    # the representable range, and the 24-bit path scales that rule up.
    assert dsa_rescale_and_clip(371081.0) == 32766
    assert dsa_rescale_and_clip(-371081.0) == -32766
    assert dsa_rescale_and_clip(1e9) == 32766
    assert dsa_rescale_and_clip(-1e9) == -32766


def test_audio_rescale_at_twenty_four_bits():
    full_scale = 8388607.0

    assert dsa_rescale_and_clip(371081.0, full_scale) == 8388606
    assert dsa_rescale_and_clip(-371081.0, full_scale) == -8388606
    assert dsa_rescale_and_clip(0.0, full_scale) == 0


def test_audio_rescale_returns_an_int():
    # This value is packed straight into a PCM sample; a float here would be
    # silently truncated somewhere further down instead.
    assert isinstance(dsa_rescale_and_clip(12345.0), int)
