"""
Unit tests for the chroma differential-gain servo and correction.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The FM channel scales recovered chrominance by the luminance it rides on
(differential gain) while leaving the luminance staircase itself linear,
so the correction is a luma-controlled chroma gain applied to the
composite output: measured from the ITS modulated staircase, nulled at
CVBS write time, anchored at the 50 IRE calibration pedestal.  These
tests cover the correction's arithmetic, the staircase measurement, and
the servo that connects them.
"""

import logging
import types

import numpy as np
import pytest

from lddecode import utils_logging as logs
from lddecode.decoder import LDdecode, measure_vits_dg_staircase
from lddecode.field import CHROMA_DG_ANCHOR_IRE, apply_chroma_dg_correction

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def quiet_logger(monkeypatch):
    monkeypatch.setattr(logs, "logger", logging.getLogger("test-dg"))


# ---------------------------------------------------------------------------
# The correction
# ---------------------------------------------------------------------------

IRE0 = 7100000.0
HZ_IRE = 8000.0
OUTFREQ = 17.734475   # PAL 4fsc, MHz
LINELEN = 1135

#: The slope the worst measured capture needs (BBC Domesday DD86-DS2
#: NationalA at inner radius reads 0.0038; CommunityNorth 0.0034).
DOMESDAY_SLOPE = 0.0034


def rf_stub():
    return types.SimpleNamespace(
        system="PAL",
        SysParams={"outfreq": OUTFREQ},
        DecoderParams={"ire0": IRE0, "hz_ire": HZ_IRE},
    )


def composite_hz(levels_ire, zone_len, chroma_peak_of):
    """A synthetic 4fsc composite: pedestals with subcarrier riding them."""
    parts = []
    offset = 0
    for level in levels_ire:
        n = np.arange(offset, offset + zone_len)
        tone = chroma_peak_of(level) * np.cos(0.5 * np.pi * n + 0.3)
        parts.append(level + tone)
        offset += zone_len
    ire = np.concatenate(parts)
    return ire * HZ_IRE + IRE0


def zone_amp(hz, index, zone_len):
    """Quadrature amplitude of one zone, trimmed of filter edges."""
    ire = (np.asarray(hz, dtype=np.float64) - IRE0) / HZ_IRE
    lo = index * zone_len + 24
    hi = (index + 1) * zone_len - 24
    hi = lo + ((hi - lo) // 4) * 4
    seg = ire[lo:hi]
    n = np.arange(lo, hi)
    return 2.0 * abs(np.mean((seg - np.mean(seg))
                             * np.exp(-0.5j * np.pi * n)))


def zone_luma(hz, index, zone_len):
    ire = (np.asarray(hz, dtype=np.float64) - IRE0) / HZ_IRE
    lo = index * zone_len + 24
    seg = ire[lo:(index + 1) * zone_len - 24]
    return float(np.mean(seg))


LEVELS = (0.0, 20.0, 40.0, 60.0, 80.0, 100.0)
ZONE = 400


def test_a_sloped_staircase_is_equalised_at_the_anchor():
    """The Domesday case: chroma gain rising with luminance."""
    hz = composite_hz(LEVELS, ZONE,
                      lambda l: 20.0 * (1 + DOMESDAY_SLOPE * l))
    out = apply_chroma_dg_correction(hz, rf_stub(), DOMESDAY_SLOPE)
    want = 20.0 * (1 + DOMESDAY_SLOPE * CHROMA_DG_ANCHOR_IRE)
    for i in range(len(LEVELS)):
        assert zone_amp(out, i, ZONE) == pytest.approx(want, rel=0.02)


def test_luminance_levels_are_untouched():
    hz = composite_hz(LEVELS, ZONE,
                      lambda l: 20.0 * (1 + DOMESDAY_SLOPE * l))
    out = apply_chroma_dg_correction(hz, rf_stub(), DOMESDAY_SLOPE)
    for i, level in enumerate(LEVELS):
        assert zone_luma(out, i, ZONE) == pytest.approx(level, abs=0.05)


def test_chroma_at_the_anchor_level_keeps_its_gain():
    """G(50 IRE) = 1: the level the multiburst servos calibrate at."""
    hz = composite_hz((50.0,), ZONE * 4, lambda l: 20.0)
    out = apply_chroma_dg_correction(hz, rf_stub(), DOMESDAY_SLOPE)
    assert zone_amp(out, 0, ZONE * 4) == pytest.approx(20.0, rel=0.01)


def test_blanking_level_chroma_gains_the_anchor_factor():
    """Burst and blanking-level subcarrier get the calibrated gain."""
    hz = composite_hz((0.0,), ZONE * 4, lambda l: 20.0)
    out = apply_chroma_dg_correction(hz, rf_stub(), DOMESDAY_SLOPE)
    factor = 1.0 + DOMESDAY_SLOPE * CHROMA_DG_ANCHOR_IRE
    assert zone_amp(out, 0, ZONE * 4) == pytest.approx(20.0 * factor,
                                                       rel=0.01)


def test_sync_below_blanking_is_not_scaled():
    """G is clamped at blanking so sync depth cannot change."""
    ire = np.full(ZONE * 4, -40.0)
    hz = ire * HZ_IRE + IRE0
    out = apply_chroma_dg_correction(hz, rf_stub(), DOMESDAY_SLOPE)
    back = (np.asarray(out, dtype=np.float64) - IRE0) / HZ_IRE
    assert np.max(np.abs(back[48:-48] - (-40.0))) < 0.05


def test_a_negative_slope_corrects_the_other_way():
    slope = -0.0015
    hz = composite_hz(LEVELS, ZONE, lambda l: 20.0 * (1 + slope * l))
    out = apply_chroma_dg_correction(hz, rf_stub(), slope)
    want = 20.0 * (1 + slope * CHROMA_DG_ANCHOR_IRE)
    for i in range(len(LEVELS)):
        assert zone_amp(out, i, ZONE) == pytest.approx(want, rel=0.02)


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------

#: Field-line waveform builder mirroring the ITS layout the measurement
#: reads (blanking-level subcarrier from 30 us, treads from 40 us).
def its_line_ire(chroma_peak_of, tread_levels=(20, 40, 60, 80, 100)):
    fs = OUTFREQ
    y = np.zeros(LINELEN)
    edges_us = [(30.0, 40.0, 0.0)]
    starts = (40.0, 44.0, 48.0, 52.0, 56.0)
    ends = (44.0, 48.0, 52.0, 56.0, 62.0)
    for s_us, e_us, lvl in edges_us + [
            (a, b, l) for a, b, l in zip(starts, ends, tread_levels)]:
        a, b = int(s_us * fs), int(e_us * fs)
        n = np.arange(a, b)
        y[a:b] = lvl + chroma_peak_of(lvl) * np.cos(0.5 * np.pi * n + 1.1)
    return y


def field_stub(line19_ire, is_first=False):
    dspicture = np.zeros(LINELEN * 25)
    dspicture[LINELEN * 18:LINELEN * 19] = line19_ire

    it = types.SimpleNamespace(
        isFirstField=is_first,
        dspicture=dspicture,
        rf=types.SimpleNamespace(
            system="PAL",
            SysParams={"outfreq": OUTFREQ, "outlinelen": LINELEN}),
    )

    def lineslice_tbc(line, begin, length, keepphase=False):
        start = LINELEN * (line - 1)
        off = int(np.floor(begin * OUTFREQ))
        if keepphase:
            off = (off // 4) * 4
        return slice(start + off, start + off + int(np.floor(length * OUTFREQ)))

    it.lineslice_tbc = lineslice_tbc
    it.output_to_ire = lambda x: x
    return it


def test_the_domesday_slope_is_recovered():
    f = field_stub(its_line_ire(lambda l: 18.0 * (1 + DOMESDAY_SLOPE * l)))
    measured = measure_vits_dg_staircase(f)
    assert measured is not None
    slope, line = measured
    assert line == 19
    assert slope == pytest.approx(DOMESDAY_SLOPE, rel=0.10)


def test_a_flat_staircase_reads_no_slope():
    f = field_stub(its_line_ire(lambda l: 18.0))
    slope, _ = measure_vits_dg_staircase(f)
    assert abs(slope) < 3e-4


def test_first_fields_are_not_measured():
    """PAL carries the luma-only staircase there."""
    f = field_stub(its_line_ire(lambda l: 18.0), is_first=True)
    assert measure_vits_dg_staircase(f) is None


def test_a_luma_only_staircase_is_rejected():
    f = field_stub(its_line_ire(lambda l: 0.0))
    assert measure_vits_dg_staircase(f) is None


def test_picture_content_is_rejected():
    rng = np.random.default_rng(7)
    f = field_stub(rng.uniform(0, 100, LINELEN))
    assert measure_vits_dg_staircase(f) is None


def test_a_disc_with_no_dspicture_yields_nothing():
    f = field_stub(its_line_ire(lambda l: 18.0))
    f.dspicture = None
    assert measure_vits_dg_staircase(f) is None


# ---------------------------------------------------------------------------
# The servo
# ---------------------------------------------------------------------------

def servo_stub(slopes, calibrated=False, current=0.0, enabled=True,
               fields_written=0):
    it = types.SimpleNamespace(
        chroma_dg_servo=enabled,
        _dg_samples=[(index, s) for index, s in enumerate(slopes)],
        _dg_last_adopt=None,
        dg_calibrated=calibrated,
        fdoffset=len(slopes),
        bytes_per_field=1,
        fields_written=fields_written,
        DG_KEEP=LDdecode.DG_KEEP,
        DG_MAX_AGE_FIELDS=LDdecode.DG_MAX_AGE_FIELDS,
        DG_MIN_SAMPLES=LDdecode.DG_MIN_SAMPLES,
        DG_SLOPE_DEADBAND=LDdecode.DG_SLOPE_DEADBAND,
        DG_SLOPE_CLAMP_NEG=LDdecode.DG_SLOPE_CLAMP_NEG,
        DG_SLOPE_CLAMP_POS=LDdecode.DG_SLOPE_CLAMP_POS,
        DG_MIN_ADOPT_FIELDS=LDdecode.DG_MIN_ADOPT_FIELDS,
        DG_SLOPE_ENGAGE=LDdecode.DG_SLOPE_ENGAGE,
        rf=types.SimpleNamespace(
            DecoderParams={"chroma_dg_slope": current}),
    )
    return it


def run(it, field=None):
    LDdecode.checkChromaDG(it, field or types.SimpleNamespace(readloc=0))


def slope_of(it):
    return it.rf.DecoderParams["chroma_dg_slope"]


@pytest.fixture(autouse=True)
def no_new_measurement(monkeypatch):
    """The servo tests exercise the pool, not the measurement."""
    import lddecode.decoder as dec
    monkeypatch.setattr(dec, "measure_vits_dg_staircase", lambda f: None)


def test_a_first_adoption_takes_three_samples():
    it = servo_stub([0.0034, 0.0031, 0.0036])
    run(it)
    assert slope_of(it) == pytest.approx(0.0034)
    assert it.dg_calibrated


def test_two_samples_are_not_enough():
    it = servo_stub([0.0034, 0.0031])
    run(it)
    assert slope_of(it) == 0.0


def test_the_dead_band_holds_a_settled_slope():
    it = servo_stub([0.0034] * 8, calibrated=True, current=0.0036)
    run(it)
    assert slope_of(it) == pytest.approx(0.0036)


def test_the_slope_is_clamped():
    it = servo_stub([0.02, 0.02, 0.02])
    run(it)
    assert slope_of(it) == pytest.approx(LDdecode.DG_SLOPE_CLAMP_POS)


def test_the_negative_clamp_is_tighter():
    """1/(1 + 100*slope) runs away below -0.004: boosting bright-area
    chroma by more than a third is never a correction."""
    it = servo_stub([-0.02, -0.02, -0.02])
    run(it)
    assert slope_of(it) == pytest.approx(LDdecode.DG_SLOPE_CLAMP_NEG)
    gain = (1 + slope_of(it) * 50.0) / (1 + slope_of(it) * 100.0)
    assert gain < 1.34


def test_the_rate_limit_holds_adoptions_once_frames_are_written():
    it = servo_stub([0.0034] * 8, calibrated=True, fields_written=5)
    it._dg_last_adopt = it.fdoffset - 1
    run(it)
    assert slope_of(it) == 0.0


def test_a_disabled_servo_does_nothing():
    it = servo_stub([0.0034] * 8, enabled=False)
    run(it)
    assert slope_of(it) == 0.0


def test_a_slope_inside_the_spec_band_is_not_corrected():
    """GGV1011's bar capture measures -0.0010 against a -0.0003 truth;
    engaging there put differential gain IN (0.033 to 0.085).  Below the
    engagement threshold the servo holds zero."""
    it = servo_stub([-0.0010, -0.0009, -0.0011])
    run(it)
    assert slope_of(it) == 0.0


def test_an_engaged_slope_that_falls_back_inside_releases_to_zero():
    """CAV radius drift can carry a disc back into spec mid-decode."""
    it = servo_stub([0.0005] * 8, calibrated=True, current=0.0034)
    run(it)
    assert slope_of(it) == 0.0


def test_the_domesday_slope_is_well_above_the_threshold():
    assert 0.0034 > 2 * LDdecode.DG_SLOPE_ENGAGE


def test_a_clean_disc_never_calibrates():
    """No staircase measured, pool empty: the slope stays exactly 0."""
    it = servo_stub([])
    run(it)
    assert slope_of(it) == 0.0
    assert not it.dg_calibrated
