"""
Unit tests for the MTF servo's staircase (FM channel linearity) reference.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Under the staircase reference the MTF level servo holds the raw
differential gain of the ITS modulated staircase at zero: an FM channel
whose pre-demodulation response is affine demodulates without
differential gain, without the rising-edge ring, and with a flat linear
response, so the level that nulls the staircase's slope is the level at
which the channel is linear.  These tests pin the arithmetic of that loop
which reference each system runs, and the staircase reading itself
(metrics.staircase_linearity).
"""

import types

import numpy as np
import pytest

from lddecode import decoder as D
from lddecode.decoder import LDdecode
from lddecode.metrics import staircase_linearity

pytestmark = [pytest.mark.unit]

GAIN = 1.0 / LDdecode.MTF_LINEARITY_SLOPE_PER_LEVEL


def staircase_stub(samples=(), level=0.0, pulse=()):
    stub = types.SimpleNamespace(
        mtf_2t_servo=True,
        mtf_servo_reference="staircase",
        mtf_servo_min_samples=LDdecode.MTF_LINEARITY_MIN_SAMPLES,
        mtf_servo_gain=GAIN,
        mtf_servo_scatter=LDdecode.MTF_LINEARITY_SCATTER,
        mtf_servo_clip=(-1.0, 1.0),
        mtf_servo_deadband=0.10,
        mtf_level=level,
        MTF_SERVO_KEEP=LDdecode.MTF_SERVO_KEEP,
        MTF_SERVO_MAX_AGE_FIELDS=LDdecode.MTF_SERVO_MAX_AGE_FIELDS,
        MTF_SERVO_SETTLE_SAMPLES=LDdecode.MTF_SERVO_SETTLE_SAMPLES,
        _servo_samples=list(samples),
        _servo_samples_2t=list(pulse),
        MTF_SERVO_MIN_SAMPLES=LDdecode.MTF_SERVO_MIN_SAMPLES,
        MTF_2T_GAIN_PAL=LDdecode.MTF_2T_GAIN_PAL,
        MTF_2T_SCATTER_PAL=LDdecode.MTF_2T_SCATTER_PAL,
        MTF_LINEARITY_HANDBACK=LDdecode.MTF_LINEARITY_HANDBACK,
        _servo_handed_over=False,
        _servo_engaged=False,
        _servo_pos=0,
        bytes_per_field=1,
        rf=types.SimpleNamespace(DecoderParams={}),
    )
    stub._mtf_servo_target = lambda: 1.0
    stub._vits_measurement = lambda field, measure: None   # no 2T pulse
    stub._mtf_servo_pooled = (
        lambda s, **kw: LDdecode._mtf_servo_pooled(stub, s, **kw))
    stub._mtf_servo_choose = (
        lambda *a: LDdecode._mtf_servo_choose(stub, *a))
    return stub


def pulses_at(level, estimate, n, start=1000):
    """n 2T readings at level that each ask for `estimate` (PAL gain 6)."""
    ratio = 1.0 + (estimate - level) / LDdecode.MTF_2T_GAIN_PAL
    return [(start + i, level, ratio, bool(i % 2)) for i in range(n)]


def slopes_at(level, slope, n, start=0):
    """n second-field readings of `slope` (fraction per IRE) at level."""
    return [(start + i, level, slope, False) for i in range(n)]


def test_the_2t_pulse_is_the_default_and_pal_may_ask_for_the_staircase():
    assert LDdecode.mtf_servo_reference_for("PAL") == "2t"
    assert LDdecode.mtf_servo_reference_for("PAL", "staircase") == "staircase"
    assert LDdecode.mtf_servo_reference_for("PAL", "2t") == "2t"
    assert LDdecode.mtf_servo_reference_for("NTSC") == "2t"
    assert LDdecode.mtf_servo_reference_for("NTSC", "staircase") == "2t"


def test_an_unknown_reference_is_refused():
    with pytest.raises(ValueError):
        LDdecode.mtf_servo_reference_for("PAL", "multiburst")


def test_a_linear_channel_asks_for_no_change():
    stub = staircase_stub(slopes_at(0.3, 0.0, 8))
    estimate, scatter = LDdecode._mtf_servo_pooled(stub, stub._servo_samples)
    assert estimate == pytest.approx(0.3)
    assert scatter == pytest.approx(0.0)


def test_chroma_that_rises_with_luminance_raises_the_level():
    """DD86-DS2 middle at -1.0: +1.0e-3 per IRE.  Raising the level lowers
    the slope by about MTF_LINEARITY_SLOPE_PER_LEVEL a unit."""
    stub = staircase_stub(slopes_at(-1.0, 1.0e-3, 8))
    estimate, _ = LDdecode._mtf_servo_pooled(stub, stub._servo_samples)
    assert estimate == pytest.approx(-1.0 + 1.0e-3 * GAIN)
    assert estimate > -1.0


def test_chroma_that_falls_with_luminance_lowers_the_level():
    stub = staircase_stub(slopes_at(1.0, -1.08e-3, 8))
    estimate, _ = LDdecode._mtf_servo_pooled(stub, stub._servo_samples)
    assert estimate < 1.0


def test_the_estimate_is_held_inside_the_clip():
    """GGV1011 inner reads +2.2e-3 at level 0: the null is near +2, and the
    ceiling holds the level at +1.0 (a noise bound; see __init__)."""
    stub = staircase_stub(slopes_at(0.0, 2.2e-3, 8))
    estimate, _ = LDdecode._mtf_servo_pooled(stub, stub._servo_samples)
    assert estimate == pytest.approx(1.0)


def test_readings_from_different_levels_agree_on_one_null():
    """Each sample is absolute (level used + slope / Jacobian), so fields
    decoded either side of an adoption pool to the same estimate."""
    null = 0.2
    lo = slopes_at(-0.5, (null + 0.5) / GAIN, 6)
    hi = slopes_at(0.6, (null - 0.6) / GAIN, 6, start=6)
    stub = staircase_stub(lo + hi)
    estimate, scatter = LDdecode._mtf_servo_pooled(stub, stub._servo_samples)
    assert estimate == pytest.approx(null)
    assert scatter == pytest.approx(0.0, abs=1e-9)


def test_a_staircase_field_is_pooled_with_the_level_it_was_decoded_under(monkeypatch):
    monkeypatch.setattr(D, "measure_staircase_linearity",
                        lambda field: (1.5e-3, 7, 19))
    stub = staircase_stub()
    field = types.SimpleNamespace(decoded_mtf_level=-0.4, dspicture=np.zeros(4),
                                  readloc=7, isFirstField=False)
    LDdecode._mtf_servo_estimate(stub, field)
    assert stub._servo_samples == [(7, -0.4, 1.5e-3, False)]


def test_a_field_without_a_staircase_adds_nothing(monkeypatch):
    monkeypatch.setattr(D, "measure_staircase_linearity", lambda field: None)
    stub = staircase_stub()
    field = types.SimpleNamespace(decoded_mtf_level=0.0, dspicture=np.zeros(4),
                                  readloc=1, isFirstField=False)
    assert LDdecode._mtf_servo_estimate(stub, field) is None
    assert stub._servo_samples == []


def test_the_pool_waits_for_six_staircases():
    n = LDdecode.MTF_LINEARITY_MIN_SAMPLES
    assert LDdecode._mtf_servo_estimate(
        staircase_stub(slopes_at(0.0, 0.0, n - 1)), field=None) is None
    assert LDdecode._mtf_servo_estimate(
        staircase_stub(slopes_at(0.0, 0.0, n)), field=None) == pytest.approx(0.0)


def test_a_scattered_pool_is_not_trusted():
    """Per-field readings spread up to about 0.5 level units on DD86 inner;
    a pool spread well past the gate is not a staircase being read."""
    spread = LDdecode.MTF_LINEARITY_SCATTER * 1.5
    samples = [(i, 0.0, (spread if i % 2 else -spread) / GAIN, False)
               for i in range(8)]
    assert LDdecode._mtf_servo_estimate(staircase_stub(samples), field=None) is None


def test_the_staircase_reference_still_reads_the_2t_pulse():
    """It hands over to the pulse when linearity is out of reach."""
    it = types.SimpleNamespace(autoMTF=True, mtf_2t_servo=True, veq_servo=False,
                               mtf_servo_reference="staircase")
    assert LDdecode._vits_servo_measures(it) == ["measure_its_2t_ratio"]


def test_a_null_inside_the_clip_is_the_level_whatever_the_pulse_says():
    """DD86 middle: linear at -0.3, its soft 2T pulse asks for -0.85."""
    stub = staircase_stub(slopes_at(0.0, -0.3 / GAIN, 8),
                          pulse=pulses_at(0.0, -0.85, 8))
    assert LDdecode._mtf_servo_estimate(stub, field=None) == pytest.approx(-0.3)


def test_a_null_out_of_reach_hands_the_level_to_the_pulse():
    """Inner radius: the null is near +1.9, past the clip; the channel is
    single-sideband there and the 2T pulse sets the level instead."""
    stub = staircase_stub(slopes_at(0.0, 1.9 / GAIN, 8),
                          pulse=pulses_at(0.0, 0.6, 8))
    assert LDdecode._mtf_servo_estimate(stub, field=None) == pytest.approx(0.6)


def test_with_no_usable_pulse_an_unreachable_null_is_clipped():
    stub = staircase_stub(slopes_at(0.0, 1.9 / GAIN, 8))
    assert LDdecode._mtf_servo_estimate(stub, field=None) == pytest.approx(1.0)
    scattered = [(1000 + i, 0.0, 1.0 + (0.6 + (1 if i % 2 else -1)) / 6.0,
                  bool(i % 2)) for i in range(8)]
    stub = staircase_stub(slopes_at(0.0, 1.9 / GAIN, 8), pulse=scattered)
    assert LDdecode._mtf_servo_estimate(stub, field=None) == pytest.approx(1.0)


def test_the_warm_up_settles_on_a_handed_over_level():
    samples = slopes_at(0.6, 1.3 / GAIN, 6)
    pulse = pulses_at(0.6, 0.62, 6)
    assert LDdecode._mtf_servo_settled(staircase_stub(samples, 0.6, pulse))
    pulse = pulses_at(0.6, 0.9, 6)
    assert not LDdecode._mtf_servo_settled(staircase_stub(samples, 0.6, pulse))


def test_the_warm_up_waits_for_the_level_to_read_back_as_itself():
    settled = staircase_stub(slopes_at(0.0, 0.5e-3, 6)
                             + slopes_at(0.33, 0.0, 4, start=6), level=0.33)
    assert LDdecode._mtf_servo_settled(settled)
    pending = staircase_stub(slopes_at(0.0, 0.9e-3, 6)
                             + slopes_at(0.33, 0.6e-3, 4, start=6), level=0.33)
    assert not LDdecode._mtf_servo_settled(pending)


# --- the staircase reading --------------------------------------------------

FS = 4 * 4.43361875     # PAL 4fsc, MHz
LINE = 1135


def staircase_line(dg_per_ire=0.0, chroma=20.0, start_us=30.0, rng=None,
                   noise_ire=0.0):
    """A CCIR 330-like line: subcarrier over blanking, then five risers to
    100 IRE, 4 us treads; chrominance scaled by (1 + dg * (L - 50))."""
    t = np.arange(LINE) / FS
    luma = np.zeros(LINE)
    levels = [0, 20, 40, 60, 80, 100]
    gate = np.zeros(LINE)
    for i, lv in enumerate(levels):
        a = start_us + 4.0 * i
        on = (t >= a) & (t < a + 4.0)
        luma[on] = lv
        gate[on] = 1.0
    amp = chroma * (1.0 + dg_per_ire * (luma - 50.0))
    x = luma + gate * amp * np.cos(0.5 * np.pi * np.arange(LINE) + 0.3)
    if rng is not None and noise_ire:
        x = x + rng.normal(0.0, noise_ire, LINE)
    return x


def test_a_linear_channel_reads_no_slope():
    got = staircase_linearity(staircase_line(0.0), FS)
    assert got is not None
    slope, treads = got
    assert treads == 6
    assert slope == pytest.approx(0.0, abs=2e-5)


@pytest.mark.parametrize("dg", [1.5e-3, -2.0e-3])
def test_the_slope_is_read_as_a_fraction_of_the_chroma_at_50_ire(dg):
    slope, _ = staircase_linearity(staircase_line(dg), FS)
    assert slope == pytest.approx(dg, rel=0.05)


def test_the_treads_are_found_wherever_the_disc_put_them():
    """A fixed window that catches a riser biases the slope; the treads are
    located by content, so moving the staircase moves nothing."""
    a, _ = staircase_line_at(30.0)
    b, _ = staircase_line_at(33.7)
    assert a == pytest.approx(b, abs=5e-5)


def staircase_line_at(start_us):
    return staircase_linearity(staircase_line(1.0e-3, start_us=start_us), FS)


def test_a_noisy_pressing_still_reads_its_staircase(seeded_rng):
    """DD86 carries several IRE of noise per sample on its VITS lines."""
    got = staircase_linearity(
        staircase_line(1.0e-3, rng=seeded_rng, noise_ire=3.0), FS)
    assert got is not None
    assert got[0] == pytest.approx(1.0e-3, abs=4e-4)


def test_a_luminance_only_staircase_is_not_read():
    assert staircase_linearity(staircase_line(0.0, chroma=0.0), FS) is None


def test_a_flat_line_is_not_read():
    assert staircase_linearity(np.zeros(LINE), FS) is None


def test_a_handed_over_level_is_taken_back_only_well_inside_the_clip():
    """DD86-DS2 inner cycled between the references: read from fields
    decoded at -0.9, its null (really near +1.9) lands at +0.97."""
    stub = staircase_stub(slopes_at(-0.9, 1.87 / GAIN, 8),
                          pulse=pulses_at(-0.9, -0.9, 8))
    stub._servo_handed_over = True
    assert LDdecode._mtf_servo_estimate(stub, field=None) == pytest.approx(-0.9)
    assert stub._servo_handed_over is True
    stub = staircase_stub(slopes_at(-0.9, 1.2 / GAIN, 8),
                          pulse=pulses_at(-0.9, -0.9, 8))
    stub._servo_handed_over = True
    assert LDdecode._mtf_servo_estimate(stub, field=None) == pytest.approx(0.3)
    assert stub._servo_handed_over is False
