"""Unit tests for the raster geometry in lddecode.params.

Everything downstream -- line lengths, output sample counts, IRE conversion,
the CVBS lattice -- is derived from these tables.  A typo in one constant does
not crash anything; it quietly shifts every line in every decode.

The expected values here are computed with ``fractions.Fraction`` from the
broadcast standards, not copied out of the module, so the test is an
independent check of the arithmetic rather than a restatement of it.  Where the
module stores a float, the comparison allows double-precision round-off only
(``rel=1e-15``, a couple of ULP); where it stores an integer sample count, the
comparison is exact.
"""

from fractions import Fraction

import numpy as np
import pytest

from lddecode.params import (
    CVBSParams_NTSC,
    CVBSParams_PAL,
    SysParams_NTSC,
    SysParams_PAL,
    calclinelen,
)

pytestmark = [pytest.mark.unit, pytest.mark.format]

# NTSC colour subcarrier: 315/88 MHz exactly (SMPTE 170M).
NTSC_FSC_MHZ = Fraction(315, 88)
# 227.5 subcarrier cycles per line.
NTSC_LINE_PERIOD_US = Fraction(455, 2) / NTSC_FSC_MHZ

# PAL colour subcarrier: 283.75 * fH + 25 Hz, fH = 15625 Hz (EBU Tech 3280).
PAL_FSC_HZ = Fraction(28375, 100) * 15625 + 25
PAL_FSC_MHZ = PAL_FSC_HZ / 10**6
PAL_LINE_PERIOD_US = Fraction(64)


# --- exact line and frame geometry ----------------------------------------


def test_ntsc_subcarrier_and_line_period():
    assert SysParams_NTSC["fsc_mhz"] == pytest.approx(float(NTSC_FSC_MHZ), rel=1e-15)
    # 4004/63 us = 63.5555... us, the colour-NTSC line.
    assert NTSC_LINE_PERIOD_US == Fraction(4004, 63)
    assert SysParams_NTSC["line_period"] == pytest.approx(
        float(NTSC_LINE_PERIOD_US), rel=1e-15
    )


def test_pal_subcarrier_and_line_period():
    # 4.43361875 MHz exactly.
    assert PAL_FSC_HZ == Fraction(443_361_875, 100)
    assert PAL_FSC_MHZ == Fraction(443_361_875, 10**8)
    assert SysParams_PAL["fsc_mhz"] == pytest.approx(float(PAL_FSC_MHZ), rel=1e-15)
    # PAL's line period is exactly 64 us and is stored as an integer.
    assert SysParams_PAL["line_period"] == 64


def test_ntsc_frame_rate_is_thirty_over_one_point_zero_zero_one():
    # 1e6 us/s / (525 lines * line period) = 30000/1001 = 29.97002997...
    expected = Fraction(10**6) / (525 * NTSC_LINE_PERIOD_US)
    assert expected == Fraction(30000, 1001)
    assert SysParams_NTSC["FPS"] == pytest.approx(float(expected), rel=1e-15)


def test_pal_frame_rate_is_exactly_twenty_five():
    assert SysParams_PAL["FPS"] == 25


@pytest.mark.parametrize(
    "sysparams, line_period_us, fsc_mhz, expected",
    [
        (SysParams_NTSC, NTSC_LINE_PERIOD_US, NTSC_FSC_MHZ, 910),
        (SysParams_PAL, PAL_LINE_PERIOD_US, PAL_FSC_MHZ, 1135),
    ],
    ids=["NTSC", "PAL"],
)
def test_output_line_length_is_four_fsc(sysparams, line_period_us, fsc_mhz, expected):
    # 4fsc sampling: 910 samples/line for NTSC (line-locked, exact) and a
    # nominal 1135 for PAL (which is *not* line-locked -- the true figure is
    # 1135.0064, and the lattice slip that implies is tested in
    # test_cvbs_lattice.py).
    exact = line_period_us * fsc_mhz * 4
    assert round(exact) == expected
    assert sysparams["outlinelen"] == expected


def test_pal_pilot_line_length_is_exact():
    # The PAL pilot burst is at 3.75 MHz, which is line-locked: 64 us * 3.75
    # MHz * 4 = 960 samples with no rounding at all.
    assert PAL_LINE_PERIOD_US * Fraction(15, 4) * 4 == 960
    assert SysParams_PAL["outlinelen_pilot"] == 960


@pytest.mark.parametrize(
    "sysparams, fsc_mhz", [(SysParams_NTSC, NTSC_FSC_MHZ), (SysParams_PAL, PAL_FSC_MHZ)],
    ids=["NTSC", "PAL"],
)
def test_output_frequency_is_four_times_the_subcarrier(sysparams, fsc_mhz):
    assert sysparams["outfreq"] == pytest.approx(float(4 * fsc_mhz), rel=1e-15)


# --- calclinelen ----------------------------------------------------------


def test_calclinelen_accepts_a_key_or_a_number():
    # The mhz argument is either a literal frequency or the name of a SysParams
    # entry holding one; both paths have to give the same answer.
    by_name = calclinelen(SysParams_NTSC, 4, "fsc_mhz")
    by_value = calclinelen(SysParams_NTSC, 4, SysParams_NTSC["fsc_mhz"])
    assert by_name == by_value == 910


def test_calclinelen_scales_with_the_multiplier():
    assert calclinelen(SysParams_NTSC, 2, "fsc_mhz") == 455
    assert calclinelen(SysParams_NTSC, 8, "fsc_mhz") == 1820


def test_calclinelen_at_one_fsc_rounds_down_from_the_half():
    # 227.5 cycles per line, so 1fsc sampling is the one multiplier that lands
    # exactly on a rounding boundary.  It does not stay there: line_period is
    # derived as 1/(fsc/227.5) in double precision and comes back as
    # 227.49999999999997, so the answer is 227 rather than the 228 that
    # round-half-to-even would give on the exact value.  Pinned because it is
    # the sort of thing that would flip if the derivation were rearranged.
    assert SysParams_NTSC["line_period"] * SysParams_NTSC["fsc_mhz"] < 227.5
    assert calclinelen(SysParams_NTSC, 1, "fsc_mhz") == 227


def test_calclinelen_returns_an_int():
    # Callers index arrays with this; a float would work until it did not.
    assert isinstance(calclinelen(SysParams_PAL, 4, "fsc_mhz"), int)


# --- IRE reference levels -------------------------------------------------


def test_ntsc_ire_scale_is_one_point_seven_megahertz_per_hundred_ire():
    # SMPTE: NTSC LD carries 0 IRE at 8.1 MHz and 100 IRE at 9.8 MHz.
    assert SysParams_NTSC["ire0"] == 8_100_000
    assert SysParams_NTSC["hz_ire"] == pytest.approx(
        float(Fraction(1_700_000, 140)), rel=1e-15
    )
    span = SysParams_NTSC["hz_ire"] * 140
    assert span == pytest.approx(1_700_000.0, rel=1e-15)
    # Sync tip is 40 IRE below blanking.
    assert SysParams_NTSC["vsync_ire"] == -40


def test_pal_ire_scale_is_point_eight_megahertz_per_hundred_ire():
    # IEC 60856: PAL LD carries 0 IRE at 7.1 MHz and 100 IRE at 7.9 MHz.
    assert SysParams_PAL["ire0"] == 7_100_000
    assert SysParams_PAL["hz_ire"] == pytest.approx(8000.0, rel=1e-15)
    assert SysParams_PAL["hz_ire"] * 100 == pytest.approx(800_000.0, rel=1e-15)
    # PAL sync is 0.3 V below blanking on a 0.7 V white level, so -300/7 IRE.
    assert SysParams_PAL["vsync_ire"] == pytest.approx(
        float(Fraction(-300, 7)), rel=1e-15
    )


def test_burst_amplitudes():
    # NTSC burst is 40 IRE peak to peak, i.e. +/-20; PAL burst is 300 mV
    # peak to peak on a 700 mV white level, i.e. +/-150/7 IRE.
    assert SysParams_NTSC["burst_ire"] == 20.0
    assert SysParams_PAL["burst_ire"] == pytest.approx(
        float(Fraction(150, 7)), rel=1e-15
    )


# --- cross-table consistency ----------------------------------------------


def test_the_two_tables_carry_the_same_keys():
    # A field added to one system and forgotten in the other is the classic way
    # a PAL-only or NTSC-only crash gets introduced.  The two entries below are
    # genuinely system-specific and are listed so that anything *else* diverging
    # fails here rather than at decode time.
    system_specific = {
        "audio_rfreq_AC3",  # NTSC only: AC3 replaces the right audio carrier
        "outlinelen_pilot",  # PAL only: NTSC LD has no pilot signal
    }
    difference = set(SysParams_NTSC) ^ set(SysParams_PAL)
    assert difference == system_specific


@pytest.mark.parametrize(
    "sysparams", [SysParams_NTSC, SysParams_PAL], ids=["NTSC", "PAL"]
)
def test_pulse_widths_fit_inside_a_line(sysparams):
    # Equalisation pulses are roughly half an hsync; the vsync (broad) pulse
    # runs most of a half-line.  Any ordering violation here would make the
    # synthesised pulse geometry in the sync detector nonsensical.
    assert 0 < sysparams["eqPulseUS"] < sysparams["hsyncPulseUS"]
    assert sysparams["hsyncPulseUS"] < sysparams["vsyncPulseUS"]
    assert sysparams["vsyncPulseUS"] < sysparams["line_period"] / 2


@pytest.mark.parametrize(
    "sysparams", [SysParams_NTSC, SysParams_PAL], ids=["NTSC", "PAL"]
)
def test_field_line_counts_sum_to_the_frame(sysparams):
    assert sum(sysparams["field_lines"]) == sysparams["frame_lines"]


@pytest.mark.parametrize(
    "sysparams", [SysParams_NTSC, SysParams_PAL], ids=["NTSC", "PAL"]
)
def test_active_video_and_burst_windows_lie_inside_the_line(sysparams):
    burst_start, burst_end = sysparams["colorBurstUS"]
    active_start, active_end = sysparams["activeVideoUS"]

    assert sysparams["hsyncPulseUS"] < burst_start < burst_end
    # The burst sits in the back porch, before active video starts.
    assert burst_end <= active_start < active_end
    assert active_end < sysparams["line_period"]


# --- CVBS output constants ------------------------------------------------


def test_ntsc_cvbs_lattice_is_line_locked():
    p = CVBSParams_NTSC
    # 4fsc NTSC is orthogonal: every line is exactly 910 samples.
    assert p["frame_lines"] * p["samples_per_line"] == p["frame_samples"] == 477_750
    assert p["fs_hz"] == pytest.approx(float(4 * NTSC_FSC_MHZ * 10**6), rel=1e-15)


def test_pal_cvbs_lattice_is_not_line_locked():
    p = CVBSParams_PAL
    numerator, denominator = p["samples_per_line"]
    # The only normative count is the frame total; per-line it is 1135.0064.
    assert (numerator, denominator) == (p["frame_samples"], p["frame_lines"])
    assert p["frame_samples"] == 625 * 1135 + 4
    # 17,734,475 Hz is an exact integer rate, so this is not an approximation.
    assert p["fs_hz"] == float(4 * PAL_FSC_MHZ * 10**6) == 17_734_475.0


@pytest.mark.parametrize(
    "cvbsparams", [CVBSParams_NTSC, CVBSParams_PAL], ids=["NTSC", "PAL"]
)
def test_cvbs_levels_are_ordered_and_within_ten_bits(cvbsparams):
    levels = cvbsparams["levels"]

    assert levels["sync"] < levels["blanking"] <= levels["black"]
    assert levels["black"] < levels["white"] < levels["peak"]
    assert 0 <= levels["sync"] and levels["peak"] <= 1023
    assert all(isinstance(v, int) for v in levels.values())


def test_pal_cvbs_has_no_setup():
    # EBU: PAL black sits at blanking.  NTSC has 7.5 IRE of setup, so its black
    # is above blanking; asserting both directions catches a copy-paste between
    # the two tables.
    assert CVBSParams_PAL["levels"]["black"] == CVBSParams_PAL["levels"]["blanking"]
    assert CVBSParams_NTSC["levels"]["black"] > CVBSParams_NTSC["levels"]["blanking"]


@pytest.mark.parametrize(
    "cvbsparams, sysparams",
    [(CVBSParams_NTSC, SysParams_NTSC), (CVBSParams_PAL, SysParams_PAL)],
    ids=["NTSC", "PAL"],
)
def test_cvbs_sample_rate_matches_the_tbc_output_rate(cvbsparams, sysparams):
    # Both tables carry the 4fsc rate, derived independently.  They have to
    # agree, or a .cvbs and a .tbc of the same disc would be at different
    # rates.  SysParams stores MHz, CVBSParams stores Hz.
    assert cvbsparams["fs_hz"] == pytest.approx(
        sysparams["outfreq"] * 1e6, rel=1e-12
    )
    assert cvbsparams["frame_lines"] == sysparams["frame_lines"]


def test_the_module_tables_are_plain_python_numbers_where_it_matters():
    # Sample counts get used as array lengths and written into metadata; a
    # numpy scalar that sneaks in here serialises as something JSON cannot
    # represent.
    for params in (CVBSParams_NTSC, CVBSParams_PAL):
        assert isinstance(params["frame_samples"], int)
        assert isinstance(params["frame_lines"], int)
        assert not isinstance(params["frame_samples"], np.generic)
