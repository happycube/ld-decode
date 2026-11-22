"""Unit tests for the decoder at an input rate other than 40 MHz.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The capture loaders resample the RF to 40 MHz, so the decoder long ran at
that rate alone, and three places held it as a constant: the EFM PLL's
channel bit period, the EFM band-pass's Nyquist frequency, and the block's
end cut (which must divide by the analog audio's decimation).  The
read-time TBC hands the decoder the captures' own rate (75 MHz on a
Domesday Duplicator capture taken at that rate), where all three were
wrong.  At 40 MHz every one of them must stay what it was, bit for bit.

All signals are synthetic.
"""

import numpy as np
import pytest

from lddecode.efm_pll import EFM_PLL
from lddecode.filters import block_cut_end
from lddecode.rfdecode import RFDecode

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

#: The EFM channel bit rate (Hz).
EFM_BIT_RATE_HZ = 4321800.0


def test_the_efm_pll_keeps_its_40_mhz_periods_bit_for_bit():
    """At the default rate the periods are the original constants."""
    base = 40000000.0 / 4321800.0
    pll = EFM_PLL()
    assert pll.basePeriod == base
    assert pll.minimumPeriod == base * 0.90
    assert pll.maximumPeriod == base * 1.10
    assert pll.periodAdjustBase == base * 0.0001
    assert pll.currentPeriod == base
    assert EFM_PLL(40000000.0).basePeriod == base


def test_the_efm_pll_period_follows_the_input_rate():
    """At 75 MHz a channel bit is 17.35 samples, not 9.26."""
    pll = EFM_PLL(75.0e6)
    assert pll.basePeriod == pytest.approx(75.0e6 / EFM_BIT_RATE_HZ, rel=1e-12)
    assert pll.minimumPeriod == pytest.approx(pll.basePeriod * 0.90, rel=1e-12)
    assert pll.maximumPeriod == pytest.approx(pll.basePeriod * 1.10, rel=1e-12)


@pytest.mark.parametrize(
    "fir_delay, fdiv, expected",
    [(32, 32, 32), (32, 64, 64), (33, 32, 64), (1, 1, 1), (32, 0, 32)],
)
def test_the_block_end_cut_is_a_whole_number_of_audio_samples(fir_delay, fdiv, expected):
    """The cut is the FIR delay, rounded up to the audio decimation."""
    assert block_cut_end(fir_delay, fdiv) == expected


@pytest.mark.parametrize("inputfreq", [40.0, 75.0])
def test_a_demodulated_block_holds_whole_audio_samples(inputfreq):
    """The audio blocks tile at the video block stride: 991 audio samples a
    block at 40 MHz (unchanged), 495 at 75 MHz (495.5 before, a drift of
    half an audio sample per block)."""
    rf = RFDecode(inputfreq=inputfreq, system="NTSC", decode_analog_audio=44100)
    fdiv = rf.Filters["audio_fdiv"]
    blocksize = rf.blocklen - rf.blockcut - rf.blockcut_end
    assert blocksize % fdiv == 0
    assert rf.blockcut_end >= rf.Filters["F05_offset"]
    if inputfreq == 40.0:
        assert rf.blockcut_end == 32


@pytest.mark.parametrize("inputfreq", [40.0, 75.0])
def test_the_efm_band_pass_sits_at_the_same_frequencies_at_any_rate(inputfreq):
    """The EFM band (20 kHz to 1.6 MHz on NTSC) is where it is in Hz: with
    the Nyquist frequency held at 20 MHz, at 75 MHz the band stretched up to
    3 MHz and let the analog audio carriers into the EFM."""
    rf = RFDecode(inputfreq=inputfreq, system="NTSC", decode_digital_audio=True)
    fefm = np.abs(rf.Filters["Fefm"])
    freqs = np.arange(fefm.shape[0]) * rf.freq_hz / rf.blocklen

    def level(hz):
        return fefm[int(np.argmin(np.abs(freqs - hz)))]

    peak = fefm[: fefm.shape[0] // 2].max()
    # The audio carrier at 2.3 MHz is far below the band's level.
    assert level(2.3e6) < 1e-3 * peak
    assert level(1.0e6) > 0.1 * peak
