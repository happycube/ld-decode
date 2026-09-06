"""
Unit tests for the MTF 2T servo's signal gate and its fallback behaviour.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The servo reads the insertion test signal's 2T pulse-to-bar ratio and drives
the MTF level from it.  Two things are covered here: which lines
measure_its_2t_ratio() will accept as an ITS, and what checkMTF() does when
the servo's pool of samples momentarily stops being usable.
"""

import logging
import types

import numpy as np
import pytest

from lddecode import utils_logging as logs
from lddecode.decoder import (
    ITS_FLATNESS_FRACTION, LDdecode, measure_its_2t_ratio,
)

pytestmark = [pytest.mark.unit]

PAL_OUTFREQ = 17.734475
PAL_OUTLINELEN = 1135

#: The gate this file exists to pin.  BBC Domesday DD86-DS1 carries 6-10 IRE
#: of noise on every line against 2-4 IRE on a Pioneer calibration disc, and
#: an absolute 4 IRE flatness gate rejected its perfectly good ITS outright.
NOISY_PRESSING_IRE = 8.0
OLD_ABSOLUTE_GATE_IRE = 4.0


def fake_field(system="PAL", lines=32):
    rf = types.SimpleNamespace(
        system=system,
        SysParams={"outfreq": PAL_OUTFREQ, "outlinelen": PAL_OUTLINELEN},
    )

    class FakeField:
        def __init__(self):
            self.rf = rf
            self.dspicture = np.zeros(PAL_OUTLINELEN * lines)

        def usectooutpx(self, us):
            return int(us * rf.SysParams["outfreq"])

        def lineslice_tbc(self, line, begin=None, length=None):
            start = PAL_OUTLINELEN * (line - 1)
            start += self.usectooutpx(begin) if begin is not None else 0
            count = (self.usectooutpx(length) if length is not None
                     else PAL_OUTLINELEN)
            return slice(start, start + count)

        def output_to_ire(self, output):
            return output          # dspicture is written in IRE directly

    return FakeField()


def draw_its(field, line=19, bar_ire=100.0, pulse_ire=100.0, had_us=0.2,
             pulse_centre_us=26.0, rng=None, noise_ire=0.0):
    """A PAL insertion test signal: white bar, then a 2T sine-squared pulse."""
    base = PAL_OUTLINELEN * (line - 1)
    t_us = np.arange(PAL_OUTLINELEN) / PAL_OUTFREQ
    row = np.zeros(PAL_OUTLINELEN)
    row[(t_us >= 12.0) & (t_us < 22.0)] = bar_ire
    offset = t_us - pulse_centre_us
    inside = np.abs(offset) <= had_us
    row[inside] += pulse_ire * np.cos(
        np.pi * offset[inside] / (2.0 * had_us)) ** 2
    if noise_ire and rng is not None:
        row = row + rng.normal(0.0, noise_ire, PAL_OUTLINELEN)
    field.dspicture[base:base + PAL_OUTLINELEN] = row
    return field


# ---------------------------------------------------------------------------
# Which lines are taken for an insertion test signal
# ---------------------------------------------------------------------------

def test_a_clean_its_is_measured_at_unity_pulse_to_bar():
    field = draw_its(fake_field())
    result = measure_its_2t_ratio(field)
    assert result is not None
    ratio, line = result
    assert line == 19
    assert ratio == pytest.approx(1.0, abs=0.02)


def test_a_noisy_pressing_still_presents_a_usable_its(seeded_rng):
    """The regression: an absolute 4 IRE gate rejected this outright.

    The line is a textbook ITS carrying a noise level a damaged pressing
    really shows, and rejecting it left the 2T servo disengaged on exactly
    the discs whose HF response most needed correcting.
    """
    assert NOISY_PRESSING_IRE > OLD_ABSOLUTE_GATE_IRE
    field = draw_its(fake_field(), rng=seeded_rng,
                     noise_ire=NOISY_PRESSING_IRE)
    result = measure_its_2t_ratio(field)
    assert result is not None
    ratio, line = result
    assert line == 19
    assert ratio == pytest.approx(1.0, abs=0.15)


def test_the_flatness_gate_scales_with_the_bar_it_is_judging():
    """Ripple is judged as a fraction of the line's own bar, not in IRE."""
    rng = np.random.default_rng(20260902)
    inside = draw_its(fake_field(), rng=rng,
                      noise_ire=0.4 * ITS_FLATNESS_FRACTION * 100.0)
    assert measure_its_2t_ratio(inside) is not None

    rng = np.random.default_rng(20260902)
    outside = draw_its(fake_field(), rng=rng,
                       noise_ire=3.0 * ITS_FLATNESS_FRACTION * 100.0)
    assert measure_its_2t_ratio(outside) is None


def test_picture_content_is_not_taken_for_an_its(seeded_rng):
    field = fake_field()
    base = PAL_OUTLINELEN * 18
    field.dspicture[base:base + PAL_OUTLINELEN] = seeded_rng.uniform(
        0.0, 100.0, PAL_OUTLINELEN)
    assert measure_its_2t_ratio(field) is None


def test_a_line_with_no_bar_is_rejected():
    field = draw_its(fake_field(), bar_ire=20.0)
    assert measure_its_2t_ratio(field) is None


# ---------------------------------------------------------------------------
# What checkMTF does when the servo pool stops being usable
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def quiet_logger(monkeypatch):
    """checkMTF logs its adoptions; no decode has set the logger up here."""
    monkeypatch.setattr(logs, "logger", logging.getLogger("test-servo"))


def servo_stub(estimate, engaged, samples, level=0.0, bw_ratio=1.044,
               flat_band=None, feedforward=0.928):
    """Enough of an LDdecode for checkMTF()'s level-selection branch.

    ``flat_band`` is the multiburst's held chroma-band verdict, which an
    adoption carries across the level change; None is a disc whose
    multiburst has never been measured.
    """
    stub = types.SimpleNamespace(
        autoMTF=True,
        mtf_level=level,
        _imtf_flat_band=flat_band,
        mtf_deemp_feedforward=feedforward,
        mtf_servo_deadband=0.10,
        bw_ratios=[bw_ratio],
        fields_written=0,
        _servo_last_adopt=None,
        _servo_engaged=engaged,
        _servo_samples=samples,
        fdoffset=0,
        bytes_per_field=1,
        MTF_SERVO_MIN_ADOPT_FIELDS=0,
        auto_deemp=False,
        deemp_calibrated=False,
        _job_engine=None,
        rf=types.SimpleNamespace(DecoderParams={}),
    )
    stub._mtf_servo_estimate = lambda field: estimate
    return stub


def test_a_momentary_pool_failure_holds_the_servo_level():
    """The open-loop mapping must not overwrite a measured level.

    Reverting on the field after every adoption made the loop alternate
    (0.000 -> -0.726 -> 0.000 -> -0.809) and the correction never took.
    """
    stub = servo_stub(estimate=None, engaged=True, samples=[("s",)],
                      level=-0.726)
    assert LDdecode.checkMTF(stub, field=None) is True
    assert stub.mtf_level == -0.726


def test_an_empty_pool_falls_through_to_the_open_loop_mapping():
    """No ITS inside the horizon means there is nothing better to hold."""
    stub = servo_stub(estimate=None, engaged=True, samples=[], level=-0.726)
    LDdecode.checkMTF(stub, field=None)
    assert stub.mtf_level != -0.726


def test_a_disc_the_servo_has_never_measured_uses_the_open_loop_mapping():
    stub = servo_stub(estimate=None, engaged=False, samples=[], level=1.0)
    LDdecode.checkMTF(stub, field=None)
    assert stub.mtf_level != 1.0


def test_a_live_servo_estimate_is_adopted_over_the_fallback():
    stub = servo_stub(estimate=-0.8, engaged=True, samples=[("s",)],
                      level=0.0)
    LDdecode.checkMTF(stub, field=None)
    assert stub.mtf_level == pytest.approx(-0.8)




# ---------------------------------------------------------------------------
# Which pulse the loop holds: the one in the output, not the one before
# the inverse-MTF and video EQ filters have acted
# ---------------------------------------------------------------------------

#: A stand-in for the 2T peak gain of the inverse-MTF filter.  The real one
#: integrates a sine-squared pulse through Finverse_mtf_base ** strength;
#: what these tests need is only that it rises with strength, so they state
#: the servo's arithmetic rather than the filter's.
IMTF_GAIN_PER_STRENGTH = 0.25

#: Adopted inverse-MTF strength high enough that the lift it puts on the
#: pulse is far outside the servo's dead-band.  BBC AIV discs drive the
#: burst-amplitude servo past this before the multiburst ceiling caps it
#: (GGV1011 middle reaches 1.067 and is capped to 0.435), which is the trim
#: that exposed the fault these tests pin.
ADOPTED_IMTF_STRENGTH = 1.2

SERVO_GAIN = 6.0                 # PAL


def estimate_stub(samples, imtf_strength=0.0, video_eq=None):
    """Enough of an LDdecode for _mtf_servo_estimate()'s pooling branch.

    samples are (readloc, level_used, pre_filter_ratio, is_first_field).
    """
    rf = types.SimpleNamespace(
        DecoderParams={"inverse_mtf_strength": imtf_strength,
                       "video_eq_auto": video_eq},
        inverse_mtf_2t_peak_gain=(
            lambda strength: 1.0 + IMTF_GAIN_PER_STRENGTH * float(strength)),
        video_eq_2t_peak_gain=lambda points: 1.0 if not points else 2.0,
    )
    stub = types.SimpleNamespace(
        mtf_2t_servo=True,
        rf=rf,
        _servo_samples=list(samples),
        _servo_engaged=False,
        fdoffset=0,
        bytes_per_field=1,
        MTF_SERVO_MIN_SAMPLES=LDdecode.MTF_SERVO_MIN_SAMPLES,
        MTF_SERVO_KEEP=LDdecode.MTF_SERVO_KEEP,
        MTF_SERVO_MAX_AGE_FIELDS=LDdecode.MTF_SERVO_MAX_AGE_FIELDS,
        mtf_servo_gain=SERVO_GAIN,
        mtf_servo_scatter=0.35,
        mtf_servo_clip=(-1.0, 1.0),
    )
    stub._mtf_servo_target = lambda: LDdecode._mtf_servo_target(stub)
    return stub


def pool(ratio, level=0.0, n=None):
    """A pool of identical, in-horizon samples, half of each parity."""
    n = n or LDdecode.MTF_SERVO_MIN_SAMPLES
    return [(i, level, ratio, bool(i % 2)) for i in range(n)]


def test_with_no_filter_lifting_the_pulse_the_setpoint_is_unity():
    stub = estimate_stub([])
    assert LDdecode._mtf_servo_target(stub) == pytest.approx(1.0)


def test_the_setpoint_is_the_reciprocal_of_what_the_filters_add():
    stub = estimate_stub([], imtf_strength=ADOPTED_IMTF_STRENGTH)
    gain = 1.0 + IMTF_GAIN_PER_STRENGTH * ADOPTED_IMTF_STRENGTH
    assert LDdecode._mtf_servo_target(stub) == pytest.approx(1.0 / gain)


def test_the_video_eq_enters_the_setpoint_as_well():
    stub = estimate_stub([], video_eq=((1.0e6, 0.5),))
    assert LDdecode._mtf_servo_target(stub) == pytest.approx(0.5)


def test_a_field_whose_output_pulse_is_already_unity_asks_for_no_change():
    """The fault this fixes, stated directly.

    The servo measures the pulse with both filters divided out, so a field
    whose *output* pulse-to-bar is exactly 1.0 reports a pre-filter ratio of
    1/gain.  Held against a setpoint of 1.0 that reads as a large error and
    the loop moves mtf_level for no reason; held against the setpoint the
    filters imply, it correctly asks for nothing.
    """
    gain = 1.0 + IMTF_GAIN_PER_STRENGTH * ADOPTED_IMTF_STRENGTH
    level = 0.4
    stub = estimate_stub(pool(1.0 / gain, level=level),
                         imtf_strength=ADOPTED_IMTF_STRENGTH)
    assert LDdecode._mtf_servo_estimate(stub, field=None) == pytest.approx(
        level)


def test_lowering_the_inverse_mtf_makes_the_servo_lower_the_level():
    """The regression the multiburst ceiling introduced.

    Capping inverse_mtf_strength takes lift off the output pulse.  Nothing
    in the pool changes - the pre-filter chain has not moved - so a servo
    holding the pre-filter ratio leaves mtf_level where it is and the output
    pulse simply drops.  The setpoint has to move with the filter, and
    lowering the filter must lower the level (mtf_level and demodulated HF
    run opposite ways).
    """
    gain = 1.0 + IMTF_GAIN_PER_STRENGTH * ADOPTED_IMTF_STRENGTH
    samples = pool(1.0 / gain, level=0.4)

    before = LDdecode._mtf_servo_estimate(
        estimate_stub(samples, imtf_strength=ADOPTED_IMTF_STRENGTH),
        field=None)
    after = LDdecode._mtf_servo_estimate(
        estimate_stub(samples, imtf_strength=0.5 * ADOPTED_IMTF_STRENGTH),
        field=None)
    assert after < before


def test_the_setpoint_is_read_from_adopted_values_not_from_the_pool():
    """Bit-identity: the pool size must not reach the setpoint.

    A live pool median depends on how many fields are in hand, which
    differs between serial and threaded decode; reading one into a servo
    boundary is what broke compare-pal-parallel-tbc when the inverse-MTF
    ceiling was first written.
    """
    small = estimate_stub(pool(0.9, n=LDdecode.MTF_SERVO_MIN_SAMPLES),
                          imtf_strength=ADOPTED_IMTF_STRENGTH)
    large = estimate_stub(pool(0.9, n=4 * LDdecode.MTF_SERVO_MIN_SAMPLES),
                          imtf_strength=ADOPTED_IMTF_STRENGTH)
    assert (LDdecode._mtf_servo_target(small)
            == LDdecode._mtf_servo_target(large))
    assert (LDdecode._mtf_servo_estimate(small, field=None)
            == LDdecode._mtf_servo_estimate(large, field=None))


def test_a_missing_filter_bank_leaves_the_setpoint_at_unity():
    stub = estimate_stub([])
    stub.rf.inverse_mtf_2t_peak_gain = lambda strength: 0.0
    assert LDdecode._mtf_servo_target(stub) == pytest.approx(1.0)


# --- carrying the multiburst's chroma-band verdict across an adoption ----
#
# The verdict is a strength, measured under one mtf_level.  mtf_level is a
# pre-demod HF boost and the one term _imtf_strength_for_flat_band() does
# not take its samples back to bare for, so an adoption leaves the held
# verdict describing a channel the decode has left behind - and the rate
# limit on republishing it is 100 fields, longer than a 30-frame cut, so
# on a short capture it never refreshes at all.


def test_an_adoption_carries_the_chroma_band_verdict_with_it():
    """A level drop withdraws boost from the bound, by the feed-forward.

    Left uncarried on BBC Domesday DD86-DS2 middle, the +0.535 verdict
    measured before the adoption bounded the burst servo for the whole
    decode while the multiburst was concurrently reading -0.22: the
    servo wound +0.319 onto a band the instrument called hot, about 2 dB
    of excess chroma.
    """
    stub = servo_stub(estimate=-0.667, engaged=True, samples=[("s",)],
                      level=0.0, flat_band=0.5349, feedforward=0.928)

    LDdecode.checkMTF(stub, field=None)

    assert stub.mtf_level == pytest.approx(-0.667)
    # 0.5349 + 0.928 * (-0.667) = -0.084, and the clamp below leaves a
    # withdrawal that stops at zero.
    assert stub._imtf_flat_band == pytest.approx(0.0)


def test_the_carried_verdict_may_not_open_a_cut():
    """Only the multiburst may spend the negative half.

    _imtf_ceiling() applies a cut on the multiburst's measurement alone,
    because burst amplitude and a feed-forward both read a mastering
    choice as channel loss.  An unclamped prediction reaches -0.475 on
    BBC Domesday DD86-DS1 outer, engages a cut on a number nothing
    measured, and costs differential gain 0.067 -> 0.157.
    """
    stub = servo_stub(estimate=-1.0, engaged=True, samples=[("s",)],
                      level=0.0, flat_band=0.10, feedforward=0.928)

    LDdecode.checkMTF(stub, field=None)

    # 0.10 + 0.928 * (-1.0) = -0.828, clamped at zero because the held
    # verdict was not itself negative.
    assert stub._imtf_flat_band == pytest.approx(0.0)


def test_the_carried_verdict_may_not_deepen_a_measured_cut():
    """A cut the multiburst measured is a floor the prediction respects."""
    stub = servo_stub(estimate=-1.0, engaged=True, samples=[("s",)],
                      level=0.0, flat_band=-0.30, feedforward=0.928)

    LDdecode.checkMTF(stub, field=None)

    assert stub._imtf_flat_band == pytest.approx(-0.30)


def test_a_rising_level_does_not_raise_the_bound():
    """The prediction may withdraw a boost, never authorise more of one.

    A level *rise* would shift the verdict up, which is the one direction
    that hands the burst servo more room than anything measured.
    """
    stub = servo_stub(estimate=0.5, engaged=True, samples=[("s",)],
                      level=0.0, flat_band=0.20, feedforward=0.928)

    LDdecode.checkMTF(stub, field=None)

    assert stub._imtf_flat_band == pytest.approx(0.20)


def test_a_disc_with_no_measured_multiburst_carries_nothing():
    """None is not a verdict, and must not become one."""
    stub = servo_stub(estimate=-0.667, engaged=True, samples=[("s",)],
                      level=0.0, flat_band=None)

    LDdecode.checkMTF(stub, field=None)

    assert stub._imtf_flat_band is None
