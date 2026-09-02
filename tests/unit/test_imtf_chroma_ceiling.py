"""
Unit tests for the multiburst constraint on the inverse-MTF chroma servo.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The inverse MTF gives back what the disc's response took away, and its
strength was set from burst amplitude alone.  Burst amplitude is as much the
level the burst was recorded at as it is the channel's gain, so on discs that
record a low burst the servo wound up and lifted the whole composite.  These
tests cover the measurement that now bounds it and the bound itself.
"""

import logging
import types

import numpy as np
import pytest

from lddecode import utils_logging as logs
from lddecode.decoder import LDdecode

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def quiet_logger(monkeypatch):
    """The ceiling logs when it applies; no decode has set the logger up."""
    monkeypatch.setattr(logs, "logger", logging.getLogger("test-imtf"))

#: What a BBC AIV pressing reads against the 21.4 IRE the servo expects,
#: on both a damaged (DD86-DS1) and an undamaged (DD86-DS2) copy.
AIV_BURST_IRE = 14.6


#: dB the inverse-MTF filter adds per unit strength in these tests.
DB_PER_STRENGTH = 2.0


def stub(samples, system="PAL", min_samples=6):
    it = types.SimpleNamespace(
        _veq_samples=samples,
        VEQ_MIN_SAMPLES=min_samples,
        CHROMA_BAND_PROBE_HZ=LDdecode.CHROMA_BAND_PROBE_HZ,
        rf=types.SimpleNamespace(
            system=system,
            inverse_mtf_log_db=lambda freq_hz: DB_PER_STRENGTH),
    )
    it._imtf_strength_for_flat_band = (
        lambda first=False: LDdecode._imtf_strength_for_flat_band(it, first))
    # checkVideoEQ publishes this at an adoption; the ceiling reads it.
    it._imtf_flat_band = it._imtf_strength_for_flat_band()
    return it


def samples(devs, count=8, applied_eq=(), strength=0.0):
    """`count` pool entries all carrying the same per-packet deviations."""
    return [(index, tuple(applied_eq), dict(devs), strength)
            for index in range(count)]


# ---------------------------------------------------------------------------
# Measuring the chroma band
# ---------------------------------------------------------------------------

def test_a_band_reading_hot_wants_a_strength_below_what_was_applied():
    """PAL: 4.0 and 4.8 MHz around a 4.43 MHz subcarrier."""
    flat = LDdecode._imtf_strength_for_flat_band(
        stub(samples({4.0e6: 2.0, 4.75e6: 2.0})))
    assert flat == pytest.approx(-2.0 / DB_PER_STRENGTH)


def test_packets_outside_the_chroma_band_do_not_speak_for_it():
    """A flat 2 MHz packet must not dilute a hot subcarrier band."""
    flat = LDdecode._imtf_strength_for_flat_band(
        stub(samples({1.0e6: 0.0, 2.0e6: 0.0, 4.0e6: 3.0, 4.75e6: 3.0})))
    assert flat == pytest.approx(-3.0 / DB_PER_STRENGTH)


def test_a_disc_with_no_multiburst_yields_no_measurement():
    assert LDdecode._imtf_strength_for_flat_band(stub([])) is None


def test_too_few_pooled_fields_yield_no_measurement():
    assert LDdecode._imtf_strength_for_flat_band(
        stub(samples({4.0e6: 2.0}, count=3))) is None


def test_the_ntsc_band_covers_its_own_subcarrier():
    flat = LDdecode._imtf_strength_for_flat_band(
        stub(samples({3.0e6: 2.0, 4.0e6: 2.0}), system="NTSC"))
    assert flat == pytest.approx(-1.0)


# ---------------------------------------------------------------------------
# Absolute bookkeeping: the answer may not depend on what was applied
# ---------------------------------------------------------------------------

def test_the_strength_a_field_was_decoded_under_is_divided_out():
    """A pool decoded at strength 1.0 must read the same as one at 0."""
    at_zero = LDdecode._imtf_strength_for_flat_band(
        stub(samples({4.0e6: 0.0, 4.75e6: 0.0}, strength=0.0)))
    # The same disc decoded at strength 1.0 reads DB_PER_STRENGTH hotter.
    at_one = LDdecode._imtf_strength_for_flat_band(
        stub(samples({4.0e6: DB_PER_STRENGTH, 4.75e6: DB_PER_STRENGTH},
                     strength=1.0)))
    assert at_zero == pytest.approx(at_one)


def test_the_applied_video_eq_is_divided_out():
    """A pool decoded under an EQ boost must read the same as one without."""
    plain = LDdecode._imtf_strength_for_flat_band(
        stub(samples({4.0e6: 0.0})))
    boosted = LDdecode._imtf_strength_for_flat_band(
        stub(samples({4.0e6: 1.5}, applied_eq=((4.0e6, 1.5),))))
    assert plain == pytest.approx(boosted)


def test_a_pool_spanning_a_trim_still_reads_one_answer():
    """The case that broke serial/threaded bit-identity.

    Half the pool decoded before an inverse-MTF trim and half after must
    give the answer the whole pool would have given under either.
    """
    before = samples({4.0e6: DB_PER_STRENGTH}, count=6, strength=1.0)
    after = samples({4.0e6: 0.0}, count=6, strength=0.0)
    mixed = [(index, eq, devs, st) for index, (_, eq, devs, st)
             in enumerate(before + after)]
    assert LDdecode._imtf_strength_for_flat_band(
        stub(mixed)) == pytest.approx(
            LDdecode._imtf_strength_for_flat_band(stub(after)))


# ---------------------------------------------------------------------------
# The bound it places on the servo
# ---------------------------------------------------------------------------

def test_a_hot_chroma_band_caps_the_strength():
    """A band 2 dB hot at strength 1.2 caps one dB-per-strength lower."""
    excess_db = 2.0
    ceiling = LDdecode._imtf_ceiling(
        stub(samples({4.0e6: excess_db, 4.75e6: excess_db}, strength=1.2)),
        current=1.2)
    assert ceiling == pytest.approx(1.2 - excess_db / DB_PER_STRENGTH)


def test_a_channel_measuring_low_is_still_corrected_up_to_flat():
    """The bound never takes away a correction the channel justifies."""
    ceiling = LDdecode._imtf_ceiling(
        stub(samples({4.0e6: -3.0, 4.75e6: -3.0})), current=0.5)
    assert ceiling == pytest.approx(3.0 / DB_PER_STRENGTH)
    assert ceiling > 0.5


def test_a_flat_chroma_band_at_zero_strength_caps_at_zero():
    assert LDdecode._imtf_ceiling(
        stub(samples({4.0e6: 0.0, 4.75e6: 0.0})), current=1.0) == 0.0


def test_a_disc_without_a_multiburst_is_left_to_the_burst_servo():
    assert LDdecode._imtf_ceiling(stub([]), current=1.2) is None


def test_the_cap_never_goes_negative():
    ceiling = LDdecode._imtf_ceiling(
        stub(samples({4.0e6: 40.0, 4.75e6: 40.0})), current=0.3)
    assert ceiling == 0.0


def test_a_wind_up_the_size_aiv_discs_provoke_is_pulled_back():
    """The measured case: burst 14.6 IRE against 21.4 winds to ~1.2.

    With the chroma band measuring +2.5 dB hot, the servo must not hold
    a strength that large.
    """
    assert AIV_BURST_IRE < 21.4
    ceiling = LDdecode._imtf_ceiling(
        stub(samples({4.0e6: 2.5, 4.75e6: 2.5}, strength=1.245)),
        current=1.245)
    assert ceiling < 1.245
    assert ceiling >= 0.0


# ---------------------------------------------------------------------------
# When the ceiling reaches the servo
# ---------------------------------------------------------------------------

#: What _veq_estimate() adopts a *first* video EQ on, against
#: VEQ_MIN_SAMPLES for every adoption after it.  The flat-band measurement
#: reads the same pool at the same moment for the same decision, so it must
#: take the same number; requiring more silently withheld the ceiling from
#: every first adoption holding 3 to 5 samples.
VEQ_FIRST_ADOPT_SAMPLES = 3


def eq_stub(samples_, strength, flat_band=None, job_engine=None):
    """Enough of an LDdecode for the ceiling's publish-and-apply path."""
    it = types.SimpleNamespace(
        _veq_samples=samples_,
        VEQ_MIN_SAMPLES=6,
        CHROMA_BAND_PROBE_HZ=LDdecode.CHROMA_BAND_PROBE_HZ,
        _imtf_flat_band=flat_band,
        _deemp_burst_samples=[1.0, 2.0],
        _deemp_burst_offset=7,
        _job_engine=job_engine,
        rf=types.SimpleNamespace(
            system="PAL",
            DecoderParams={"inverse_mtf_strength": strength},
            inverse_mtf_log_db=lambda freq_hz: DB_PER_STRENGTH),
    )
    it._imtf_ceiling = lambda current: LDdecode._imtf_ceiling(it, current)
    it._imtf_strength_for_flat_band = (
        lambda first=False: LDdecode._imtf_strength_for_flat_band(it, first))
    return it


def test_a_first_adoption_measures_the_band_on_what_it_adopted_on():
    """The threshold gap that made the ceiling a coin toss.

    Measured on BBC Domesday DD86-DS1 outer: the only video EQ adoption of
    the decode holds five samples, every one of them carrying the chroma
    band packets.  _veq_estimate() adopts on three; the flat-band
    measurement demanded six, so no ceiling was published, and the
    correction the multiburst says is unjustified stayed on for the whole
    decode - about 20% hot chrominance.
    """
    pool = samples({4.0e6: 2.0, 4.75e6: 2.0},
                   count=VEQ_FIRST_ADOPT_SAMPLES + 2)
    it = eq_stub(pool, strength=0.5)
    assert it._imtf_strength_for_flat_band(first=False) is None
    assert it._imtf_strength_for_flat_band(first=True) is not None


def test_a_pool_below_even_the_first_adoption_threshold_says_nothing():
    it = eq_stub(samples({4.0e6: 2.0}, count=VEQ_FIRST_ADOPT_SAMPLES - 1),
                 strength=0.5)
    assert it._imtf_strength_for_flat_band(first=True) is None


def test_a_ceiling_published_after_the_servo_settled_is_still_applied():
    """_deemp_calibrate() only consults the ceiling while it is adopting.

    Its dead-band returns early once the burst servo has converged, so a
    ceiling published after that was never applied at all - measured over
    a 150-frame decode of DD86-DS1 outer, where the burst servo settles at
    0.456 and no further adoption ever happens.
    """
    it = eq_stub([], strength=0.456, flat_band=0.0)
    assert LDdecode._apply_imtf_ceiling(it) is True
    assert it.rf.DecoderParams["inverse_mtf_strength"] == pytest.approx(0.0)


def test_applying_the_ceiling_discards_a_pool_measured_under_the_old_value():
    it = eq_stub([], strength=0.456, flat_band=0.0)
    LDdecode._apply_imtf_ceiling(it)
    assert it._deemp_burst_samples == []
    assert it._deemp_burst_offset is None


def test_applying_the_ceiling_tells_the_job_engine():
    engine = types.SimpleNamespace(sent=[])
    engine.set_imtf = engine.sent.append
    it = eq_stub([], strength=0.456, flat_band=0.0, job_engine=engine)
    LDdecode._apply_imtf_ceiling(it)
    assert engine.sent == [pytest.approx(0.0)]


def test_the_ceiling_never_winds_the_correction_up():
    it = eq_stub([], strength=0.2, flat_band=0.9)
    assert LDdecode._apply_imtf_ceiling(it) is False
    assert it.rf.DecoderParams["inverse_mtf_strength"] == pytest.approx(0.2)


def test_no_multiburst_leaves_the_strength_alone():
    it = eq_stub([], strength=1.2, flat_band=None)
    assert LDdecode._apply_imtf_ceiling(it) is False
    assert it.rf.DecoderParams["inverse_mtf_strength"] == pytest.approx(1.2)


# ---------------------------------------------------------------------------
# The wiring: checkVideoEQ is where the ceiling is both published and applied
# ---------------------------------------------------------------------------

def adopt_stub(samples_, strength, flat_band=None, calibrated=False):
    """Enough of an LDdecode to run checkVideoEQ() to its adoption."""
    it = types.SimpleNamespace(
        _veq_samples=samples_,
        VEQ_MIN_SAMPLES=6,
        VEQ_DEADBAND_DB=LDdecode.VEQ_DEADBAND_DB,
        VEQ_MIN_ADOPT_FIELDS=LDdecode.VEQ_MIN_ADOPT_FIELDS,
        CHROMA_BAND_PROBE_HZ=LDdecode.CHROMA_BAND_PROBE_HZ,
        _imtf_flat_band=flat_band,
        _deemp_burst_samples=[],
        _deemp_burst_offset=None,
        _job_engine=None,
        _veq_last_adopt=None,
        veq_calibrated=calibrated,
        fields_written=0,
        fdoffset=0,
        bytes_per_field=1,
        exact_speculation=False,
        rf=types.SimpleNamespace(
            system="PAL",
            DecoderParams={"inverse_mtf_strength": strength},
            recompute_fvideo=lambda: None,
            inverse_mtf_log_db=lambda freq_hz: DB_PER_STRENGTH),
    )
    it._veq_estimate = lambda field: ((1.0e6, 0.0), (2.0e6, 1.0))
    it._imtf_ceiling = lambda current: LDdecode._imtf_ceiling(it, current)
    it._imtf_strength_for_flat_band = (
        lambda first=False: LDdecode._imtf_strength_for_flat_band(it, first))
    it._apply_imtf_ceiling = lambda: LDdecode._apply_imtf_ceiling(it)
    return it


def test_adopting_a_video_eq_brings_the_strength_under_the_new_ceiling():
    """Publishing a ceiling and acting on it are the same moment.

    Left to _deemp_calibrate() alone the ceiling reaches the servo only if
    a burst adoption happens to follow, which on a converged servo never
    does; the whole correction the multiburst calls unjustified then stays
    applied for the rest of the decode.
    """
    pool = samples({4.0e6: 2.0, 4.75e6: 2.0}, count=8, strength=1.2)
    it = adopt_stub(pool, strength=1.2)
    LDdecode.checkVideoEQ(it, field=None)
    assert it._imtf_flat_band == pytest.approx(1.2 - 2.0 / DB_PER_STRENGTH)
    assert it.rf.DecoderParams["inverse_mtf_strength"] == pytest.approx(0.2)


def test_a_thinned_pool_does_not_erase_a_ceiling_already_published():
    """The multiburst does not unsay what it said."""
    it = adopt_stub(samples({4.0e6: 2.0}, count=2), strength=1.2,
                    flat_band=0.2, calibrated=True)
    LDdecode.checkVideoEQ(it, field=None)
    assert it._imtf_flat_band == pytest.approx(0.2)
    assert it.rf.DecoderParams["inverse_mtf_strength"] == pytest.approx(0.2)


def test_a_disc_with_no_multiburst_verdict_keeps_its_strength():
    it = adopt_stub([], strength=1.2)
    LDdecode.checkVideoEQ(it, field=None)
    assert it._imtf_flat_band is None
    assert it.rf.DecoderParams["inverse_mtf_strength"] == pytest.approx(1.2)
