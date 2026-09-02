"""
Unit tests for the chroma differential-gain servo and correction.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The FM channel scales and rotates recovered chrominance by the luminance
it rides on (differential gain and differential phase) while leaving the
luminance staircase itself linear, so the correction is a luma-controlled
complex chroma gain applied to the composite outputs: measured from the
ITS modulated staircase, nulled at write time on both the TBC and CVBS
paths, gain anchored at the 50 IRE calibration pedestal and phase at
blanking (the burst's level, so the hue reference never rotates).  These
tests cover the correction's arithmetic, the staircase measurement, and
the servo that connects them.
"""

import logging
import types

import numpy as np
import pytest

from lddecode import utils_logging as logs
from lddecode.decoder import LDdecode, measure_vits_dg_staircase
from lddecode.field import (CHROMA_DG_ANCHOR_IRE, apply_chroma_dg_correction,
                            apply_chroma_dg_correction_output)

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


def composite_hz(levels_ire, zone_len, chroma_peak_of,
                 chroma_phase_of=lambda level: 0.0):
    """A synthetic 4fsc composite: pedestals with subcarrier riding them."""
    parts = []
    offset = 0
    for level in levels_ire:
        n = np.arange(offset, offset + zone_len)
        tone = chroma_peak_of(level) * np.cos(
            0.5 * np.pi * n + 0.3 + chroma_phase_of(level))
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


def zone_phase(hz, index, zone_len):
    """Quadrature phase of one zone in degrees, on the shared lattice."""
    ire = (np.asarray(hz, dtype=np.float64) - IRE0) / HZ_IRE
    lo = index * zone_len + 24
    hi = (index + 1) * zone_len - 24
    hi = lo + ((hi - lo) // 4) * 4
    seg = ire[lo:hi]
    n = np.arange(lo, hi)
    return np.angle(np.mean((seg - np.mean(seg))
                            * np.exp(-0.5j * np.pi * n)), deg=True)


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
def its_line_ire(chroma_peak_of, tread_levels=(20, 40, 60, 80, 100),
                 chroma_phase_of=lambda level: 0.0):
    fs = OUTFREQ
    y = np.zeros(LINELEN)
    edges_us = [(30.0, 40.0, 0.0)]
    starts = (40.0, 44.0, 48.0, 52.0, 56.0)
    ends = (44.0, 48.0, 52.0, 56.0, 62.0)
    for s_us, e_us, lvl in edges_us + [
            (a, b, l) for a, b, l in zip(starts, ends, tread_levels)]:
        a, b = int(s_us * fs), int(e_us * fs)
        n = np.arange(a, b)
        y[a:b] = lvl + chroma_peak_of(lvl) * np.cos(
            0.5 * np.pi * n + 1.1 + chroma_phase_of(lvl))
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
    slope, phase, line = measured
    assert line == 19
    assert slope == pytest.approx(DOMESDAY_SLOPE, rel=0.10)
    assert abs(phase) < 0.005


def test_a_flat_staircase_reads_no_slope():
    f = field_stub(its_line_ire(lambda l: 18.0))
    slope, _, _ = measure_vits_dg_staircase(f)
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
               fields_written=0, phases=None, current_phase=0.0):
    if phases is None:
        phases = [0.0] * len(slopes)
    it = types.SimpleNamespace(
        chroma_dg_servo=enabled,
        _dg_samples=[(index, s, ph)
                     for index, (s, ph) in enumerate(zip(slopes, phases))],
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
        DG_PHASE_DEADBAND=LDdecode.DG_PHASE_DEADBAND,
        DG_PHASE_CLAMP=LDdecode.DG_PHASE_CLAMP,
        DG_PHASE_ENGAGE=LDdecode.DG_PHASE_ENGAGE,
        DG_PHASE_MIN_SAMPLES=LDdecode.DG_PHASE_MIN_SAMPLES,
        DG_PHASE_RELEASE=LDdecode.DG_PHASE_RELEASE,
        rf=types.SimpleNamespace(
            DecoderParams={"chroma_dg_slope": current,
                           "chroma_dg_phase": current_phase}),
    )
    return it


def run(it, field=None):
    LDdecode.checkChromaDG(it, field or types.SimpleNamespace(readloc=0))


def slope_of(it):
    return it.rf.DecoderParams["chroma_dg_slope"]


def phase_of(it):
    return it.rf.DecoderParams["chroma_dg_phase"]


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

# ---------------------------------------------------------------------------
# Differential phase
# ---------------------------------------------------------------------------

#: The worst measured phase tilt (BBC Domesday DD86-DS2 NationalA reads
#: +0.058 deg/IRE - a true differential phase of 5-6 degrees).
DOMESDAY_PHASE = 0.058


def test_a_phase_tilted_staircase_is_flattened():
    hz = composite_hz(LEVELS, ZONE, lambda l: 20.0,
                      lambda l: np.deg2rad(DOMESDAY_PHASE * l))
    out = apply_chroma_dg_correction(hz, rf_stub(), 0.0, DOMESDAY_PHASE)
    reference = zone_phase(out, 0, ZONE)
    for i in range(1, len(LEVELS)):
        assert zone_phase(out, i, ZONE) == pytest.approx(reference, abs=0.4)


def test_phase_correction_never_rotates_blanking_level_chroma():
    """Burst sits at blanking, and the hue reference must not move."""
    hz = composite_hz((0.0,), ZONE * 4, lambda l: 20.0)
    out = apply_chroma_dg_correction(hz, rf_stub(), 0.0, DOMESDAY_PHASE)
    assert zone_phase(out, 0, ZONE * 4) == pytest.approx(
        zone_phase(hz, 0, ZONE * 4), abs=0.05)


def test_phase_correction_preserves_amplitude_and_luma():
    hz = composite_hz(LEVELS, ZONE, lambda l: 20.0,
                      lambda l: np.deg2rad(DOMESDAY_PHASE * l))
    out = apply_chroma_dg_correction(hz, rf_stub(), 0.0, DOMESDAY_PHASE)
    for i, level in enumerate(LEVELS):
        assert zone_amp(out, i, ZONE) == pytest.approx(20.0, rel=0.02)
        assert zone_luma(out, i, ZONE) == pytest.approx(level, abs=0.05)


def test_gain_and_phase_correct_together():
    hz = composite_hz(LEVELS, ZONE,
                      lambda l: 20.0 * (1 + DOMESDAY_SLOPE * l),
                      lambda l: np.deg2rad(DOMESDAY_PHASE * l))
    out = apply_chroma_dg_correction(hz, rf_stub(), DOMESDAY_SLOPE,
                                     DOMESDAY_PHASE)
    want = 20.0 * (1 + DOMESDAY_SLOPE * CHROMA_DG_ANCHOR_IRE)
    reference = zone_phase(out, 0, ZONE)
    for i in range(len(LEVELS)):
        assert zone_amp(out, i, ZONE) == pytest.approx(want, rel=0.02)
        assert zone_phase(out, i, ZONE) == pytest.approx(reference, abs=0.4)


def test_a_zero_phase_keeps_the_pure_gain_path_exact():
    """phase=0 must reproduce the gain-only corrector bit for bit: the
    engaged-gain, no-phase case is the one already-verified decodes
    exercise."""
    hz = composite_hz(LEVELS, ZONE,
                      lambda l: 20.0 * (1 + DOMESDAY_SLOPE * l))
    gain_only = apply_chroma_dg_correction(hz, rf_stub(), DOMESDAY_SLOPE)
    with_phase_arg = apply_chroma_dg_correction(hz, rf_stub(),
                                                DOMESDAY_SLOPE, 0.0)
    assert np.array_equal(gain_only, with_phase_arg)


def test_the_measured_phase_correction_closes_the_loop():
    """Measure a tilted staircase with the servo's instrument, correct
    with the measured figure, re-measure: the tilt must be gone.  This
    pins the sign convention between measurement and corrector."""
    line = its_line_ire(lambda l: 18.0,
                        chroma_phase_of=lambda l: np.deg2rad(
                            DOMESDAY_PHASE * l))
    f = field_stub(line)
    _, phase, _ = measure_vits_dg_staircase(f)
    assert phase == pytest.approx(DOMESDAY_PHASE, rel=0.10)

    hz = f.dspicture * HZ_IRE + IRE0
    corrected = (apply_chroma_dg_correction(hz, rf_stub(), 0.0, phase)
                 .astype(np.float64) - IRE0) / HZ_IRE
    f2 = field_stub(corrected[LINELEN * 18:LINELEN * 19])
    _, residual, _ = measure_vits_dg_staircase(f2)
    assert abs(residual) < 0.1 * DOMESDAY_PHASE


def test_a_wild_phase_tilt_is_rejected_by_the_measurement():
    line = its_line_ire(lambda l: 18.0,
                        chroma_phase_of=lambda l: np.deg2rad(0.8 * l))
    assert measure_vits_dg_staircase(field_stub(line)) is None


# ---------------------------------------------------------------------------
# The TBC write-time path
# ---------------------------------------------------------------------------

OUTPUT_ZERO = 1024
OUT_SCALE = 350.0
VSYNC_IRE = -40.0


def output_field_stub(ire_samples):
    picture = np.clip((ire_samples - VSYNC_IRE) * OUT_SCALE
                      + OUTPUT_ZERO + 0.5, 0, 65535).astype(np.uint16)
    field = types.SimpleNamespace(
        out_scale=OUT_SCALE,
        rf=types.SimpleNamespace(
            SysParams={"outfreq": OUTFREQ, "outputZero": OUTPUT_ZERO},
            DecoderParams={"vsync_ire": VSYNC_IRE}),
    )
    field.output_to_ire = (
        lambda x: (x - OUTPUT_ZERO) / OUT_SCALE + VSYNC_IRE)
    return picture, field


def test_the_output_unit_wrapper_matches_the_hz_corrector():
    hz = composite_hz(LEVELS, ZONE,
                      lambda l: 20.0 * (1 + DOMESDAY_SLOPE * l),
                      lambda l: np.deg2rad(DOMESDAY_PHASE * l))
    ire = (hz - IRE0) / HZ_IRE
    picture, field = output_field_stub(ire)
    out = apply_chroma_dg_correction_output(picture, field,
                                            DOMESDAY_SLOPE, DOMESDAY_PHASE)
    assert out.dtype == np.uint16
    back = field.output_to_ire(out.astype(np.float64))
    hz_back = back * HZ_IRE + IRE0
    want = 20.0 * (1 + DOMESDAY_SLOPE * CHROMA_DG_ANCHOR_IRE)
    reference = zone_phase(hz_back, 0, ZONE)
    for i, level in enumerate(LEVELS):
        assert zone_amp(hz_back, i, ZONE) == pytest.approx(want, rel=0.02)
        assert zone_phase(hz_back, i, ZONE) == pytest.approx(reference,
                                                            abs=0.5)
        assert zone_luma(hz_back, i, ZONE) == pytest.approx(level, abs=0.1)


def test_the_output_unit_wrapper_accepts_bytes():
    ire = (composite_hz(LEVELS, ZONE, lambda l: 20.0) - IRE0) / HZ_IRE
    picture, field = output_field_stub(ire)
    from_bytes = apply_chroma_dg_correction_output(
        picture.tobytes(), field, DOMESDAY_SLOPE)
    from_array = apply_chroma_dg_correction_output(
        picture, field, DOMESDAY_SLOPE)
    assert np.array_equal(from_bytes, from_array)


# ---------------------------------------------------------------------------
# The phase servo
# ---------------------------------------------------------------------------

FULL = LDdecode.DG_PHASE_MIN_SAMPLES


def test_the_phase_engage_threshold_holds_conforming_captures_at_zero():
    """GGV1011 pools 0.021-0.025 deg/IRE - a true 1.8 degree rise, well
    inside the 5.2 degree conformance limit - and must stay untouched."""
    it = servo_stub([0.0034] * FULL,
                    phases=([0.021, 0.025, 0.023] * FULL)[:FULL])
    run(it)
    assert phase_of(it) == 0.0


def test_a_domesday_phase_tilt_is_adopted():
    it = servo_stub([0.0034] * FULL,
                    phases=([0.058, 0.055, 0.061] * FULL)[:FULL])
    run(it)
    assert phase_of(it) == pytest.approx(0.058)


def test_the_phase_is_clamped():
    it = servo_stub([0.0034] * FULL, phases=[0.4] * FULL)
    run(it)
    assert phase_of(it) == pytest.approx(LDdecode.DG_PHASE_CLAMP)


def test_an_engaged_phase_that_falls_back_inside_releases_to_zero():
    it = servo_stub([0.0034] * FULL, calibrated=True, current=0.0034,
                    phases=[0.01] * FULL, current_phase=0.05)
    run(it)
    assert phase_of(it) == 0.0


def test_a_phase_switching_on_is_not_held_by_the_rate_limit():
    """The pool reaches its depth whenever it does - often just after a
    gain trim on a busy decode - and the engage is a one-time event, so
    it goes out immediately rather than waiting out the trim holdoff."""
    it = servo_stub([0.0034] * FULL, calibrated=True, current=0.0034,
                    phases=[0.058] * FULL, fields_written=5)
    it._dg_last_adopt = it.fdoffset - 1
    run(it)
    assert phase_of(it) == pytest.approx(0.058)


def test_a_phase_trim_is_still_rate_limited():
    it = servo_stub([0.0034] * FULL, calibrated=True, current=0.0034,
                    phases=[0.058] * FULL, current_phase=0.045,
                    fields_written=5)
    it._dg_last_adopt = it.fdoffset - 1
    run(it)
    assert phase_of(it) == pytest.approx(0.045)


def test_the_hysteresis_band_neither_engages_nor_releases():
    """A capture whose tilt sits between the release and engage
    thresholds keeps whatever state it is in - no flapping."""
    it = servo_stub([0.0034] * FULL, phases=[0.028] * FULL)
    run(it)
    assert phase_of(it) == 0.0

    it = servo_stub([0.0034] * FULL, calibrated=True, current=0.0034,
                    phases=[0.028] * FULL, current_phase=0.043)
    run(it)
    assert phase_of(it) == pytest.approx(0.028)


def test_a_phase_change_alone_still_adopts():
    """The gain can be settled while the phase drifts past its dead-band;
    the adoption must not be gated on the gain moving too."""
    it = servo_stub([0.0034] * FULL, calibrated=True, current=0.0034,
                    phases=[0.058] * FULL, current_phase=0.0)
    run(it)
    assert slope_of(it) == pytest.approx(0.0034)
    assert phase_of(it) == pytest.approx(0.058)


def test_a_part_filled_pool_never_takes_the_phase_decision():
    """A 3-sample phase median put GGV1011 over the engage line; until
    the pool fills, the phase holds - a first gain adoption goes out
    alone, and an engaged phase survives a pool shrunk by aging."""
    it = servo_stub([0.0034] * 3, phases=[0.058] * 3)
    run(it)
    assert slope_of(it) == pytest.approx(0.0034)
    assert phase_of(it) == 0.0

    it = servo_stub([0.0034] * 8, calibrated=True, current=0.0034,
                    phases=[0.01] * 8, current_phase=0.05)
    it.DG_PHASE_MIN_SAMPLES = 24
    run(it)
    assert phase_of(it) == 0.05
