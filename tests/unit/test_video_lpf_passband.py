"""
The video low-pass must contain the multiburst, not end on it.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

A Butterworth's corner frequency is by definition its -3 dB point, so a
passband edge placed *on* a frequency the standard specifies a test signal at
loses 3 dB of that signal.  PAL's corner was set to 5.8 MHz to reach the
5.8 MHz packet of IEC 60856-1986 Figure 8 and cost 3.01 dB of it, and 3.56 dB
on the discs that record the packet at 5.9 MHz.

No capture file is read: this is the filter's own response against the
frequencies the reference data says are there.
"""

import numpy as np
import pytest
import scipy.signal as sps

import vits_reference as vr
from lddecode.filters import filtfft
from lddecode.params import (
    FilterParams_NTSC, FilterParams_PAL, SysParams_PAL,
)

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

#: How much of a multiburst packet the video low-pass may take, in dB.
#:
#: Not the measurement floor: chasing that would mean widening the passband
#: further, and demodulated FM noise density rises as f^2, so the last MHz
#: of passband carries far more noise than signal.  0.5 dB is a budget - it
#: is 40% of vits_reference.OUT_OF_BAND_RESPONSE_DB, the allowance the
#: packet is actually judged against, so the check still measures the
#: channel rather than the filter, and it is met at 1.23x the FM-weighted
#: noise where reaching the measurement floor costs 1.89x.  The trade is
#: tabulated beside video_lpf_freq in lddecode/params.py.
PASSBAND_BUDGET_DB = 0.5

#: The top packet the discs in testdata/ actually record.  IEC 60856-1986
#: Figure 8 c) states 5.8 MHz and GGV1011 records that; BBC Domesday
#: DD86-DS1 records 5.9, and both must be inside the passband.
PAL_TOP_PACKET_MHZ = 5.9

#: Stopband the low-pass must still reach at the 4fsc output Nyquist.  The
#: 5.8 MHz order 7 filter this replaced managed -32.5 dB; a wider passband
#: may not be bought by giving that up.
NYQUIST_FLOOR_DB = -32.5


#: The RF sample rate and block length the decoder builds its filters at.
#: The realised digital response is what the multiburst sees, and the
#: bilinear transform's frequency warping makes it differ from the analogue
#: prototype by tenths of a dB right where these assertions are made - so
#: this builds the filter the way lddecode/rfdecode.py does rather than
#: evaluating a formula.
FREQ_HZ = 40e6
BLOCK_LEN = 32768


def butterworth_db(freq_mhz, corner_hz, order):
    """Realised magnitude of the video low-pass at freq_mhz, in dB."""
    ba = sps.butter(order, corner_hz / (FREQ_HZ / 2.0), "low")
    response = np.abs(filtfft(ba, BLOCK_LEN))
    half = BLOCK_LEN // 2
    binf = np.abs(np.fft.fftfreq(BLOCK_LEN, 1.0 / FREQ_HZ))[:half] / 1e6
    return 20.0 * np.log10(
        max(float(np.interp(freq_mhz, binf, response[:half])), 1e-12))


def test_the_top_pal_packet_is_inside_the_passband():
    loss = butterworth_db(PAL_TOP_PACKET_MHZ,
                          FilterParams_PAL["video_lpf_freq"],
                          FilterParams_PAL["video_lpf_order"])
    assert abs(loss) < PASSBAND_BUDGET_DB, (
        f"the video low-pass takes {loss:.2f} dB out of the "
        f"{PAL_TOP_PACKET_MHZ} MHz multiburst packet")


def test_every_published_pal_packet_is_inside_the_passband():
    for set_name, nominals in vr.MULTIBURST_SETS["PAL"].items():
        for freq_mhz in nominals:
            loss = butterworth_db(freq_mhz,
                                  FilterParams_PAL["video_lpf_freq"],
                                  FilterParams_PAL["video_lpf_order"])
            assert abs(loss) < PASSBAND_BUDGET_DB, (set_name, freq_mhz, loss)


def test_the_corner_is_not_placed_on_a_specified_packet():
    """The defect itself: a -3 dB point sitting on a test frequency."""
    corner_mhz = FilterParams_PAL["video_lpf_freq"] / 1e6
    for nominals in vr.MULTIBURST_SETS["PAL"].values():
        assert corner_mhz not in nominals


def test_the_passband_still_falls_away_before_the_output_nyquist():
    """A wider passband is not an absent one.

    CVBS output is 4fsc; the low-pass is what keeps the demodulated band
    inside it.
    """
    nyquist_mhz = SysParams_PAL["outfreq"] / 2.0
    loss = butterworth_db(nyquist_mhz,
                          FilterParams_PAL["video_lpf_freq"],
                          FilterParams_PAL["video_lpf_order"])
    assert loss < NYQUIST_FLOOR_DB, f"only {loss:.1f} dB at the 4fsc Nyquist"


def test_ntsc_is_left_as_it_measures():
    """NTSC is deliberately not held to the same rule.

    Its corner sits well inside its own top packet, but the NTSC multiburst
    measures flat on every radius cut (-0.28 to +0.01 dB), so the loss is
    cancelling something else in that chain.  Pinning the value here means a
    change to it has to come with the measurement that justifies it.
    """
    assert FilterParams_NTSC["video_lpf_freq"] == 4500000
    assert FilterParams_NTSC["video_lpf_order"] == 6
    loss = butterworth_db(4.2, FilterParams_NTSC["video_lpf_freq"],
                          FilterParams_NTSC["video_lpf_order"])
    assert loss < -1.0
