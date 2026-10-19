"""Unit tests for how the decoder sets the readout MTF model's level.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Under the readout model mtf_level is the innermost CAV radius' cutoff over
the disc's, and the disc's cutoff is the one at which the model passes the
burst's lower FM sideband over its upper one as the capture does - or,
while the burst gives no reading, tilts the blanking carrier over the
white carrier as the capture does.
"""

import types

import numpy as np
import pytest

from lddecode import dsp
from lddecode.decoder import LDdecode
from lddecode.params import FilterParams_NTSC, SysParams_NTSC

pytestmark = [pytest.mark.unit]

REF = FilterParams_NTSC["readout_ref_cutoff_hz"]
BLANK, WHITE = 8.1e6, 9.3e6
FSC = SysParams_NTSC["fsc_mhz"] * 1e6
# a PAL-shaped pilot for the selection logic: the tone on the sync tip
TIP, PILOT = 7.614e6, 3.75e6


def stub(tilts=(), bws=(), sides=(), pilots=()):
    dp = {k: FilterParams_NTSC[k] for k in FilterParams_NTSC
          if k.startswith("readout_")}
    dp["ire0"] = BLANK
    dp["vsync_ire"] = -40.0
    it = types.SimpleNamespace(
        tilt_ratios=list(tilts), bw_ratios=list(bws),
        sideband_ratios=list(sides), pilot_ratios=list(pilots),
        READOUT_LEVEL_MAX=LDdecode.READOUT_LEVEL_MAX,
        READOUT_SIDEBAND_MIN=LDdecode.READOUT_SIDEBAND_MIN,
        rf=types.SimpleNamespace(DecoderParams=dp,
                                 SysParams={"fsc_mhz": FSC / 1e6,
                                            "pilot_mhz": PILOT / 1e6},
                                 iretohz=lambda ire: {100.0: WHITE, -40.0: TIP}[ire]))
    it._readout_measurement = types.MethodType(LDdecode._readout_measurement, it)
    return it


def tilt_at(cutoff):
    return dsp.readout_otf(BLANK, cutoff) / dsp.readout_otf(WHITE, cutoff)


def sides_at(cutoff):
    return (dsp.readout_otf(BLANK - FSC, cutoff)
            / dsp.readout_otf(BLANK + FSC, cutoff))


@pytest.mark.parametrize("cutoff", [13.6e6, 18.1e6, 30.8e6])
def test_the_level_names_the_measured_cutoff(cutoff):
    it = stub(tilts=[tilt_at(cutoff)] * 5)
    level = LDdecode._readout_level_estimate(it)
    assert REF / level == pytest.approx(cutoff, rel=1e-6)


def test_the_level_is_the_median_of_the_pool():
    it = stub(tilts=[tilt_at(14e6)] * 5 + [1.9, 1.0])
    assert REF / LDdecode._readout_level_estimate(it) == pytest.approx(14e6, rel=1e-6)


def test_no_tilt_means_no_compensation():
    assert LDdecode._readout_level_estimate(stub(tilts=[0.99] * 5)) == 0.0


def test_the_raw_ratio_stands_in_until_the_carrier_is_measured():
    it = stub(bws=[tilt_at(16e6)] * 3)
    assert REF / LDdecode._readout_level_estimate(it) == pytest.approx(16e6, rel=1e-6)
    assert LDdecode._readout_level_estimate(stub()) is None


def test_a_tilt_steeper_than_any_cutoff_gives_is_held_at_the_bound():
    """Not 'no compensation': the carrier says the disc is past anything
    the model reaches."""
    it = stub(tilts=[1e6] * 5)
    assert LDdecode._readout_level_estimate(it) == LDdecode.READOUT_LEVEL_MAX


@pytest.mark.parametrize("cutoff", [13.6e6, 19.9e6, 30.8e6])
def test_the_burst_sidebands_name_the_cutoff_over_the_tilt(cutoff):
    """The electronics' droop tilts the carrier as if the readout were
    something else (GGV1069 outer reads 57 MHz); the sidebands win."""
    it = stub(tilts=[tilt_at(57e6)] * 8, sides=[sides_at(cutoff)] * 8)
    assert REF / LDdecode._readout_level_estimate(it) == pytest.approx(cutoff, rel=1e-6)
    assert it._readout_measurement()[0].startswith("burst sidebands")


def test_a_sparse_sideband_pool_leaves_the_tilt_in_charge():
    """Fields give no sideband reading while the upper sideband sits in
    the noise; the few that do are the ones whose noise read high."""
    tilt = [tilt_at(14e6)] * 12
    for sides in ([sides_at(20e6)] * 4, [sides_at(20e6)] * 5):
        it = stub(tilts=tilt, sides=sides)
        assert REF / LDdecode._readout_level_estimate(it) == pytest.approx(14e6, rel=1e-6)
    it = stub(tilts=tilt, sides=[sides_at(20e6)] * 6)
    assert REF / LDdecode._readout_level_estimate(it) == pytest.approx(20e6, rel=1e-6)


def pilot_at(cutoff):
    return (dsp.readout_otf(TIP - PILOT, cutoff)
            / dsp.readout_otf(TIP + PILOT, cutoff))


def test_the_pilot_is_read_before_the_burst():
    """Its upper sideband outlasts the colour burst's on inner radii, so
    when both are measured the pilot names the cutoff."""
    it = stub(tilts=[tilt_at(14e6)] * 8, sides=[sides_at(16e6)] * 8,
              pilots=[pilot_at(11.9e6)] * 8)
    assert REF / LDdecode._readout_level_estimate(it) == pytest.approx(11.9e6, rel=1e-6)
    assert it._readout_measurement()[0].startswith("pilot sidebands")
    it = stub(tilts=[tilt_at(14e6)] * 8, sides=[sides_at(16e6)] * 8,
              pilots=[pilot_at(11.9e6)] * 3)
    assert REF / LDdecode._readout_level_estimate(it) == pytest.approx(16e6, rel=1e-6)
