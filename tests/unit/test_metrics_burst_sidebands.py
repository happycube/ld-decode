"""Unit tests for the per-field FM sideband readings (metrics).

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

burst_sideband_ratio pools the colour burst's two first FM sidebands over
the field's lines; their ratio is the channel's either side of the
blanking carrier, the readout model's cutoff measurement.
pilot_sideband_ratio does the same with PAL's 3.75 MHz pilot burst on the
sync tip.
"""

import types

import numpy as np
import pytest
from scipy.special import jv

from lddecode import metrics

pytestmark = [pytest.mark.unit]

FS = 40e6
FSC = 315e6 / 88
BLANK = 8.1e6
LINELEN = 2542


PAL_TIP = 7.1e6 - 0.3 * 0.8e6 / 0.7
PILOT = 3.75e6


def capture(lower_gain, upper_gain, noise=6.0, seed=1, system="NTSC",
            carrier=BLANK, tone=FSC, beta=0.17):
    """A field's raw RF carrying a tone-modulated carrier everywhere (any
    window reads it), its first sidebands scaled by the channel's gains;
    beta 0.17 by default (NTSC's 20 IRE burst through pre-emphasis)."""
    rng = np.random.default_rng(seed)
    t = np.arange(263 * LINELEN + 4000) / FS
    x = (jv(0, beta) * np.cos(2 * np.pi * carrier * t)
         + lower_gain * jv(1, beta) * np.cos(2 * np.pi * (carrier - tone) * t + 1.0)
         + upper_gain * jv(1, beta) * np.cos(2 * np.pi * (carrier + tone) * t + 2.0))
    raw = 1000 * x + rng.normal(0, noise, len(t))
    rf = types.SimpleNamespace(
        system=system,
        SysParams={"colorBurstUS": (5.3, 7.8), "fsc_mhz": FSC / 1e6,
                   "pilot_mhz": PILOT / 1e6},
        DecoderParams={"ire0": 7.1e6 if system == "PAL" else BLANK,
                       "vsync_ire": -300 / 7},
        iretohz=lambda ire: 7.1e6 + ire * 8000.0,
        delays={"video_sync": 12}, freq_hz=FS)
    linelocs = np.arange(263) * LINELEN + 2000.0

    def lineslice(line, begin, length):
        start = linelocs[line] + begin * FS / 1e6
        return slice(int(start), int(start + length * FS / 1e6) + 1)

    field = types.SimpleNamespace(rawdata=raw, linelocs=linelocs,
                                  lineoffset=0, lineslice=lineslice)
    return rf, field


def test_the_field_reads_the_channel_ratio_across_the_carrier():
    rf, field = capture(1.6, 0.2)
    assert metrics.burst_sideband_ratio(rf, field) == pytest.approx(8.0, rel=0.05)


def test_no_reading_while_the_upper_sideband_is_in_the_noise():
    """The innermost PAL radii, or an NTSC disc whose cutoff sits near
    blanking + fsc: no ratio, rather than noise read as a sideband."""
    rf, field = capture(1.6, 0.0)
    assert metrics.burst_sideband_ratio(rf, field) is None


def test_the_pal_pilot_reads_the_channel_across_the_sync_tip():
    """The pilot rides the sync tip: its sidebands sit 3.75 MHz either
    side of 6.76 MHz, read whatever the pilot's recorded amplitude."""
    for beta in (0.3, 0.45):
        rf, field = capture(5.0, 0.25, system="PAL", carrier=PAL_TIP,
                            tone=PILOT, beta=beta)
        assert metrics.pilot_sideband_ratio(rf, field) == pytest.approx(20.0, rel=0.08)


def test_no_pilot_reading_on_ntsc_or_without_a_pilot():
    rf, field = capture(5.0, 0.25, carrier=PAL_TIP, tone=PILOT, beta=0.3)
    assert metrics.pilot_sideband_ratio(rf, field) is None
    rf, field = capture(0.0, 0.0, system="PAL", carrier=PAL_TIP, tone=PILOT)
    assert metrics.pilot_sideband_ratio(rf, field) is None
