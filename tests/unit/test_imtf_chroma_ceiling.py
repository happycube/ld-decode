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
        IMTF_STRENGTH_LIMIT=LDdecode.IMTF_STRENGTH_LIMIT,
        rf=types.SimpleNamespace(
            system=system,
            SysParams={"fsc_mhz": 4.43361875 if system == "PAL" else 3.579545},
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


def test_a_band_hot_at_zero_strength_is_cut_below_zero():
    """The fault this bound exists to reach at the negative end.

    A chroma band that reads hot with nothing applied cannot be brought
    back by the burst servo declining to boost: zero is already what it
    is doing.  Measured on BBC Domesday DD86-DS2 inner, +3.6 dB at
    4.0 MHz and +4.0 at 4.8, which left chrominance 45 percent hot.
    """
    ceiling = LDdecode._imtf_ceiling(
        stub(samples({4.0e6: 3.6, 4.75e6: 4.0})), current=0.0)
    assert ceiling < 0.0
    # Read at fsc between the two packets, not averaged across them.
    at_fsc = 3.6 + (4.43361875 - 4.0) / (4.75 - 4.0) * (4.0 - 3.6)
    assert ceiling == pytest.approx(-at_fsc / DB_PER_STRENGTH)


def test_the_band_is_read_at_the_subcarrier_not_averaged_across_it():
    """The packets disagree, and only one frequency is being corrected.

    The inverse-MTF curve rises more steeply across the probe band than
    the error does, so the packet below fsc asks for a deeper correction
    than the one above it. Averaging the two strengths lands between two
    answers neither of which is about fsc; on DD86-DS2 inner that
    overshoot put chrominance cold.
    """
    hot_below = LDdecode._imtf_strength_for_flat_band(
        stub(samples({4.0e6: 6.0, 4.75e6: 2.0})))
    mean_of_packets = -(6.0 + 2.0) / 2 / DB_PER_STRENGTH
    at_fsc = 6.0 + (4.43361875 - 4.0) / (4.75 - 4.0) * (2.0 - 6.0)
    assert hot_below == pytest.approx(-at_fsc / DB_PER_STRENGTH)
    assert hot_below != pytest.approx(mean_of_packets)


def test_the_cut_is_bounded_at_the_strength_limit():
    ceiling = LDdecode._imtf_ceiling(
        stub(samples({4.0e6: 40.0, 4.75e6: 40.0})), current=0.3)
    assert ceiling == -LDdecode.IMTF_STRENGTH_LIMIT


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
    # The band is hot by almost exactly what the applied strength put
    # there, so the verdict is "apply nothing", not "cut".
    assert ceiling == pytest.approx(0.0, abs=0.05)


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
        IMTF_STRENGTH_LIMIT=LDdecode.IMTF_STRENGTH_LIMIT,
        _imtf_flat_band=flat_band,
        _deemp_burst_samples=[1.0, 2.0],
        _deemp_burst_offset=7,
        _job_engine=job_engine,
        rf=types.SimpleNamespace(
            system="PAL",
            SysParams={"fsc_mhz": 4.43361875},
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

def adopt_stub(samples_, strength, flat_band=None, calibrated=False,
               estimate=((1.0e6, 0.0), (2.0e6, 1.0)), applied_eq=None,
               fields_written=0, last_publish=None):
    """Enough of an LDdecode to run checkVideoEQ() to its adoption.

    `estimate` is what the video EQ servo reports and `applied_eq` what is
    already adopted, so a caller can put the EQ inside its own dead-band
    and still exercise the chroma-band ceiling.
    """
    params = {"inverse_mtf_strength": strength}
    if applied_eq is not None:
        params["video_eq_auto"] = applied_eq
    it = types.SimpleNamespace(
        _veq_samples=samples_,
        VEQ_MIN_SAMPLES=6,
        VEQ_DEADBAND_DB=LDdecode.VEQ_DEADBAND_DB,
        VEQ_MIN_ADOPT_FIELDS=LDdecode.VEQ_MIN_ADOPT_FIELDS,
        IMTF_CEILING_DEADBAND=LDdecode.IMTF_CEILING_DEADBAND,
        CHROMA_BAND_PROBE_HZ=LDdecode.CHROMA_BAND_PROBE_HZ,
        IMTF_STRENGTH_LIMIT=LDdecode.IMTF_STRENGTH_LIMIT,
        _imtf_flat_band=flat_band,
        _imtf_flat_band_last_publish=last_publish,
        _deemp_burst_samples=[],
        _deemp_burst_offset=None,
        _job_engine=None,
        _veq_last_adopt=None,
        veq_calibrated=calibrated,
        fields_written=fields_written,
        fdoffset=0,
        bytes_per_field=1,
        exact_speculation=False,
        rf=types.SimpleNamespace(
            system="PAL",
            SysParams={"fsc_mhz": 4.43361875},
            DecoderParams=params,
            recompute_fvideo=lambda: None,
            inverse_mtf_log_db=lambda freq_hz: DB_PER_STRENGTH),
    )
    it._veq_estimate = lambda field: estimate
    it._imtf_ceiling = lambda current: LDdecode._imtf_ceiling(it, current)
    it._imtf_strength_for_flat_band = (
        lambda first=False: LDdecode._imtf_strength_for_flat_band(it, first))
    it._apply_imtf_ceiling = lambda: LDdecode._apply_imtf_ceiling(it)
    it._publish_imtf_flat_band = (
        lambda first: LDdecode._publish_imtf_flat_band(it, first))
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


# ---------------------------------------------------------------------------
# The ceiling is not the video EQ's decision to make
# ---------------------------------------------------------------------------

#: A video EQ estimate that matches what is already adopted, so
#: checkVideoEQ() declines inside VEQ_DEADBAND_DB without adopting.
FLAT_EQ = ((1.0e6, 0.0), (2.0e6, 0.0))


def test_a_band_the_eq_is_happy_with_still_publishes_its_ceiling():
    """The defect: the ceiling rode on the EQ's adoption, not its own.

    Measured on BBC Domesday DD86-DS1 outer.  The EQ wants +/-0.13 dB at
    2 MHz - well inside its 0.3 dB dead-band - so it never adopts across
    the whole decode, and the chroma-band ceiling was published only at an
    adoption.  The burst servo then ran unbounded to 1.418 chasing a burst
    the disc recorded at 15.7 IRE, and twenty of forty-nine conformance
    checks failed.  A channel flat enough for the EQ to decline is exactly
    the channel the multiburst is most confident about.
    """
    pool = samples({4.0e6: 2.0, 4.75e6: 2.0}, count=8, strength=1.2)
    it = adopt_stub(pool, strength=1.2, estimate=FLAT_EQ,
                    applied_eq=FLAT_EQ, calibrated=True)
    LDdecode.checkVideoEQ(it, field=None)
    assert it.rf.DecoderParams["video_eq_auto"] == FLAT_EQ, "EQ must decline"
    assert it._imtf_flat_band == pytest.approx(1.2 - 2.0 / DB_PER_STRENGTH)
    assert it.rf.DecoderParams["inverse_mtf_strength"] == pytest.approx(0.2)


def test_a_ceiling_that_has_not_moved_is_not_republished():
    """Its own dead-band, on the quantity the burst servo holds inside.

    A ceiling that moves by less than the burst servo's own dead-band
    cannot change what the burst servo does, so republishing it is churn
    on a value that crosses loops.
    """
    pool = samples({4.0e6: 2.0, 4.75e6: 2.0}, count=8, strength=1.2)
    settled = 1.2 - 2.0 / DB_PER_STRENGTH
    it = adopt_stub(pool, strength=0.2, estimate=FLAT_EQ, applied_eq=FLAT_EQ,
                    calibrated=True,
                    flat_band=settled + 0.9 * LDdecode.IMTF_CEILING_DEADBAND)
    before = it._imtf_flat_band
    LDdecode.checkVideoEQ(it, field=None)
    assert it._imtf_flat_band == pytest.approx(before)


def test_a_ceiling_that_has_moved_past_the_dead_band_is_published():
    pool = samples({4.0e6: 2.0, 4.75e6: 2.0}, count=8, strength=1.2)
    settled = 1.2 - 2.0 / DB_PER_STRENGTH
    it = adopt_stub(pool, strength=0.2, estimate=FLAT_EQ, applied_eq=FLAT_EQ,
                    calibrated=True,
                    flat_band=settled + 1.1 * LDdecode.IMTF_CEILING_DEADBAND)
    LDdecode.checkVideoEQ(it, field=None)
    assert it._imtf_flat_band == pytest.approx(settled)


def test_the_rate_limit_holds_a_republish_once_frames_are_written():
    """Warmup is exempt; a committed decode is not.

    The value crosses loops, so how often it may change has to be bounded
    by something the decode schedule cannot influence - the same reason
    the video EQ's own adoptions are rate limited.
    """
    pool = samples({4.0e6: 2.0, 4.75e6: 2.0}, count=8, strength=1.2)
    it = adopt_stub(pool, strength=1.2, estimate=FLAT_EQ, applied_eq=FLAT_EQ,
                    calibrated=True, fields_written=4, last_publish=0)
    it.fdoffset = (LDdecode.VEQ_MIN_ADOPT_FIELDS - 1) * it.bytes_per_field
    LDdecode.checkVideoEQ(it, field=None)
    assert it._imtf_flat_band is None
    assert it.rf.DecoderParams["inverse_mtf_strength"] == pytest.approx(1.2)

    it.fdoffset = LDdecode.VEQ_MIN_ADOPT_FIELDS * it.bytes_per_field
    LDdecode.checkVideoEQ(it, field=None)
    assert it.rf.DecoderParams["inverse_mtf_strength"] == pytest.approx(0.2)


def test_the_first_publication_does_not_wait_for_the_rate_limit():
    """Nothing has been written yet, so there is nothing to be consistent
    with; the burst servo must be bounded before the first frame."""
    pool = samples({4.0e6: 2.0, 4.75e6: 2.0}, count=8, strength=1.2)
    it = adopt_stub(pool, strength=1.2, estimate=FLAT_EQ, applied_eq=FLAT_EQ,
                    calibrated=True, fields_written=0, last_publish=0)
    LDdecode.checkVideoEQ(it, field=None)
    assert it.rf.DecoderParams["inverse_mtf_strength"] == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# The negative half of the range, and who is allowed to spend it
# ---------------------------------------------------------------------------

def test_a_negative_ceiling_carries_the_strength_below_zero():
    """The measured case at BBC Domesday DD86-DS2 inner radius.

    The 2T servo has driven mtf_level negative, the chroma band reads
    about +3.8 dB hot with no correction applied, and nothing the burst
    servo can do reaches it: zero is already where it sits.
    """
    it = eq_stub([], strength=0.0, flat_band=-1.4)
    assert LDdecode._apply_imtf_ceiling(it) is True
    assert it.rf.DecoderParams["inverse_mtf_strength"] == pytest.approx(-1.4)


def deemp_stub(burst_ire, strength, flat_band=None, calibrated=True):
    """Enough of an LDdecode for _deemp_calibrate()."""
    it = types.SimpleNamespace(
        IMTF_STRENGTH_LIMIT=LDdecode.IMTF_STRENGTH_LIMIT,
        _deemp_burst_samples=[burst_ire] * 4,
        _deemp_burst_offset=7,
        _imtf_flat_band=flat_band,
        _job_engine=None,
        deemp_calibrated=calibrated,
        exact_speculation=False,
        rf=types.SimpleNamespace(
            SysParams={"burst_ire": 21.4},
            # 20*log10(e**0.31) ~ 2.7 dB at fsc per strength unit
            inverse_mtf_log_at_fsc=0.31,
            DecoderParams={"inverse_mtf_strength": strength},
            recompute_fvideo=lambda: None),
    )
    it._imtf_ceiling = lambda current: LDdecode._imtf_ceiling(it, current)
    return it


def test_the_burst_servo_alone_never_cuts():
    """A burst read hot is as likely to be the level the disc recorded.

    With no multiburst verdict the servo may decline to boost and no
    more, whatever the burst reads - the same reason the ceiling exists
    in the other direction.
    """
    it = deemp_stub(burst_ire=40.0, strength=0.0, flat_band=None)
    LDdecode._deemp_calibrate(it)
    assert it.rf.DecoderParams["inverse_mtf_strength"] == pytest.approx(0.0)


def test_a_multiburst_verdict_lets_the_same_servo_cut():
    it = deemp_stub(burst_ire=14.6, strength=0.0, flat_band=-1.4)
    LDdecode._deemp_calibrate(it)
    assert it.rf.DecoderParams["inverse_mtf_strength"] == pytest.approx(-1.4)


def test_a_first_calibration_adopts_a_cut():
    """The `first` gate adopted any non-trivial strength upwards only.

    A disc whose very first verdict is a cut would otherwise decline it
    and never look again until the burst drifted.
    """
    it = deemp_stub(burst_ire=14.6, strength=0.0, flat_band=-1.4,
                    calibrated=False)
    assert LDdecode._deemp_calibrate(it) is True
    assert it.rf.DecoderParams["inverse_mtf_strength"] == pytest.approx(-1.4)


def feedforward_stub(strength, delta):
    """The inverse-MTF half of checkMTF()'s adoption, in isolation."""
    it = types.SimpleNamespace(
        IMTF_STRENGTH_LIMIT=LDdecode.IMTF_STRENGTH_LIMIT,
        mtf_deemp_feedforward=1.2,
        _deemp_burst_samples=[1.0],
        _deemp_burst_offset=7,
        _job_engine=None,
        rf=types.SimpleNamespace(
            DecoderParams={"inverse_mtf_strength": strength},
            recompute_fvideo=lambda: None),
    )
    current = it.rf.DecoderParams["inverse_mtf_strength"]
    it.rf.DecoderParams["inverse_mtf_strength"] = float(np.clip(
        current + it.mtf_deemp_feedforward * delta,
        min(0.0, current), it.IMTF_STRENGTH_LIMIT))
    return it.rf.DecoderParams["inverse_mtf_strength"]


def test_the_feed_forward_does_not_open_a_cut_of_its_own():
    """It predicts, it does not measure: only the multiburst may cut."""
    assert feedforward_stub(strength=0.0, delta=-1.0) == pytest.approx(0.0)


def test_the_feed_forward_does_not_close_a_cut_the_multiburst_asked_for():
    """A plain 0.0 floor walked a standing cut back up on the next
    MTF adoption, undoing the verdict a field at a time."""
    assert feedforward_stub(strength=-1.4, delta=-0.5) == pytest.approx(-1.4)


def test_the_feed_forward_still_winds_up_from_a_cut():
    assert feedforward_stub(strength=-1.4, delta=0.5) == pytest.approx(-0.8)
