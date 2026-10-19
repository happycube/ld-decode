"""
Unit tests for the VITS white-level servo and its correction.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Discs are mastered a percent or so either side of nominal level.  With
--vits_white_level the decoder reads the insertion test signal's white bar
(metrics.measure_its_white_level), pools it (LDdecode.checkLumaLevel) and
scales the luminance above blanking at write time so that the bar reads
100 IRE - riding the chroma DG corrector's luma/chroma split, so sync,
burst and chrominance stay where they are.  These tests cover the scaling
kernel, the correction, the measurement and the servo's pool.
"""

import logging
import types

import numpy as np
import pytest

from lddecode import utils_logging as logs
from lddecode.decoder import LDdecode
from lddecode.dsp import scale_luma_above_blanking
from lddecode.field import apply_chroma_dg_correction
from lddecode.metrics import ITS_WHITE_NOMINAL_IRE, measure_its_white_level

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def quiet_logger(monkeypatch):
    monkeypatch.setattr(logs, "logger", logging.getLogger("test-white-level"))


# ---------------------------------------------------------------------------
# The kernel
# ---------------------------------------------------------------------------

def test_the_kernel_scales_only_the_non_chroma_part_above_blanking():
    ire = np.array([-40.0, 0.0, 50.0, 100.0, 60.0])
    chroma = np.array([0.0, 0.0, 0.0, 0.0, 10.0])
    out = ire.copy()
    scale_luma_above_blanking(out, ire, chroma, 0.99)
    np.testing.assert_allclose(out, [-40.0, 0.0, 49.5, 99.0, 59.5])


# ---------------------------------------------------------------------------
# The correction
# ---------------------------------------------------------------------------

IRE0 = 8100000.0
HZ_IRE = 1700000.0 / 140.0
OUTFREQ = 14.318182   # NTSC 4fsc, MHz
ZONE = 400
LEVELS = (0.0, 20.0, 50.0, 80.0, 101.0)


def rf_stub():
    return types.SimpleNamespace(
        system="NTSC",
        SysParams={"outfreq": OUTFREQ},
        DecoderParams={"ire0": IRE0, "hz_ire": HZ_IRE},
    )


def composite_hz(levels, chroma_peak=20.0, prefix_sync=False):
    """Pedestals with subcarrier riding them, optionally after sync."""
    parts, offset = [], 0
    if prefix_sync:
        parts.append(np.full(ZONE, -40.0))
        offset = ZONE
    for level in levels:
        n = np.arange(offset, offset + ZONE)
        parts.append(level + chroma_peak * np.cos(0.5 * np.pi * n + 0.3))
        offset += ZONE
    return np.concatenate(parts) * HZ_IRE + IRE0


def zone(hz, index):
    ire = (np.asarray(hz, dtype=np.float64) - IRE0) / HZ_IRE
    lo = index * ZONE + 24
    hi = lo + ((ZONE - 48) // 4) * 4
    seg = ire[lo:hi]
    n = np.arange(lo, hi)
    amp = 2.0 * abs(np.mean((seg - seg.mean()) * np.exp(-0.5j * np.pi * n)))
    return float(seg.mean()), float(amp)


def test_the_gain_scales_every_luminance_level_about_blanking():
    gain = 100.0 / 101.0
    out = apply_chroma_dg_correction(composite_hz(LEVELS), rf_stub(), 0.0,
                                     luma_gain=gain)
    for i, level in enumerate(LEVELS):
        assert zone(out, i)[0] == pytest.approx(level * gain, abs=0.05)


def test_the_chroma_riding_the_luminance_is_left_alone():
    out = apply_chroma_dg_correction(composite_hz(LEVELS), rf_stub(), 0.0,
                                     luma_gain=0.98)
    for i in range(len(LEVELS)):
        assert zone(out, i)[1] == pytest.approx(20.0, rel=0.005)


def test_sync_and_blanking_do_not_move():
    hz = composite_hz((0.0,), chroma_peak=0.0, prefix_sync=True)
    out = apply_chroma_dg_correction(hz, rf_stub(), 0.0, luma_gain=0.97)
    back = (np.asarray(out, dtype=np.float64) - IRE0) / HZ_IRE
    assert np.max(np.abs(back[48:ZONE - 48] + 40.0)) < 0.05
    assert np.max(np.abs(back[ZONE + 48:-48])) < 0.05


def test_a_unity_gain_is_the_chroma_dg_correction_alone():
    hz = composite_hz(LEVELS)
    np.testing.assert_array_equal(
        apply_chroma_dg_correction(hz, rf_stub(), 0.002, 0.0, luma_gain=1.0),
        apply_chroma_dg_correction(hz, rf_stub(), 0.002, 0.0))


def test_the_gain_and_the_dg_correction_apply_together():
    slope, gain = 0.002, 0.99
    hz = composite_hz(LEVELS)
    with_both = apply_chroma_dg_correction(hz, rf_stub(), slope, 0.0,
                                           luma_gain=gain)
    dg_only = apply_chroma_dg_correction(hz, rf_stub(), slope, 0.0)
    for i, level in enumerate(LEVELS):
        assert zone(with_both, i)[0] == pytest.approx(level * gain, abs=0.05)
        assert zone(with_both, i)[1] == pytest.approx(zone(dg_only, i)[1],
                                                      rel=0.005)


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------

NTSC_LINELEN = 910


def ntsc_field(lines=32):
    rf = types.SimpleNamespace(
        system="NTSC",
        SysParams={"outfreq": OUTFREQ, "outlinelen": NTSC_LINELEN},
    )

    class FakeField:
        def __init__(self):
            self.rf = rf
            self.dspicture = np.zeros(NTSC_LINELEN * lines)

        def lineslice_tbc(self, line, begin=None, length=None):
            start = NTSC_LINELEN * (line - 1) + int(begin * OUTFREQ)
            return slice(start, start + int(length * OUTFREQ))

        def output_to_ire(self, output):
            return output          # dspicture is written in IRE directly

    return FakeField()


def draw_ntc7(field, line, bar_ire=100.0, offset_ire=0.0, pulse=True):
    """NTC-7 composite: the white bar from 12 to 30 us, then the 2T pulse
    at 34 us, the whole line lifted by offset_ire."""
    t_us = np.arange(NTSC_LINELEN) / OUTFREQ
    row = np.zeros(NTSC_LINELEN)
    row[(t_us >= 12.0) & (t_us < 30.0)] = bar_ire
    if pulse:
        d = t_us - 34.0
        inside = np.abs(d) <= 0.25
        row[inside] += bar_ire * np.cos(np.pi * d[inside] / 0.5) ** 2
    base = NTSC_LINELEN * (line - 1)
    field.dspicture[base:base + NTSC_LINELEN] = row + offset_ire
    return field


def test_the_white_bar_is_read_above_its_baseline():
    level, line = measure_its_white_level(draw_ntc7(ntsc_field(), 20, 101.3))
    assert line == 20 and level == pytest.approx(101.3, abs=0.01)


def test_a_blanking_offset_does_not_read_as_a_gain():
    level, _ = measure_its_white_level(
        draw_ntc7(ntsc_field(), 20, 100.0, offset_ire=2.0))
    assert level == pytest.approx(100.0, abs=0.01)


def test_a_bright_line_without_the_2t_pulse_is_not_taken_for_the_bar():
    assert measure_its_white_level(
        draw_ntc7(ntsc_field(), 20, 100.0, pulse=False)) is None


# ---------------------------------------------------------------------------
# The servo
# ---------------------------------------------------------------------------

def servo_stub(levels, calibrated=False, current=1.0, enabled=True,
               fields_written=0):
    return types.SimpleNamespace(
        luma_level_servo=enabled,
        _level_samples=[(index, level) for index, level in enumerate(levels)],
        _level_last_adopt=None,
        level_calibrated=calibrated,
        _servo_pos=len(levels),
        bytes_per_field=1,
        fields_written=fields_written,
        LEVEL_KEEP=LDdecode.LEVEL_KEEP,
        LEVEL_MAX_AGE_FIELDS=LDdecode.LEVEL_MAX_AGE_FIELDS,
        LEVEL_MIN_SAMPLES=LDdecode.LEVEL_MIN_SAMPLES,
        LEVEL_DEADBAND=LDdecode.LEVEL_DEADBAND,
        LEVEL_CLAMP=LDdecode.LEVEL_CLAMP,
        LEVEL_MIN_ADOPT_FIELDS=LDdecode.LEVEL_MIN_ADOPT_FIELDS,
        rf=types.SimpleNamespace(DecoderParams={"luma_level_gain": current}),
    )


def run(it):
    LDdecode.checkLumaLevel(it, types.SimpleNamespace(readloc=0))


def gain_of(it):
    return it.rf.DecoderParams["luma_level_gain"]


@pytest.fixture(autouse=True)
def no_new_measurement(monkeypatch):
    """The servo tests exercise the pool, not the measurement."""
    import lddecode.decoder as dec
    monkeypatch.setattr(dec, "measure_its_white_level", lambda f: None)


def test_a_first_adoption_takes_three_samples():
    it = servo_stub([101.3, 101.0, 101.5])
    run(it)
    assert gain_of(it) == pytest.approx(ITS_WHITE_NOMINAL_IRE / 101.3)
    assert it.level_calibrated


def test_two_samples_are_not_enough():
    it = servo_stub([101.3, 101.0])
    run(it)
    assert gain_of(it) == 1.0


def test_the_dead_band_holds_a_settled_gain():
    it = servo_stub([100.0] * 8, calibrated=True, current=0.9985)
    run(it)
    assert gain_of(it) == 0.9985


def test_the_gain_is_clamped():
    it = servo_stub([80.0] * 3)
    run(it)
    assert gain_of(it) == pytest.approx(1.0 + LDdecode.LEVEL_CLAMP)


def test_the_rate_limit_holds_adoptions_once_frames_are_written():
    it = servo_stub([101.3] * 8, calibrated=True, fields_written=5)
    it._level_last_adopt = it._servo_pos - 1
    run(it)
    assert gain_of(it) == 1.0


def test_a_disabled_servo_does_nothing():
    it = servo_stub([101.3] * 8, enabled=False)
    run(it)
    assert gain_of(it) == 1.0
