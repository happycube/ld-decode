"""Unit tests for the decoder's audio crosstalk cancellation (resample path).

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

RFDecode.measure_crosstalk measures the analog audio carriers' coupling into
the video carrier's phase over a stretch of blocks; RFDecode's demodblock
then turns each block's analytic video band back by the phase that coupling
makes of the block's own carriers (rf_crosstalk_cancel), before the
discriminator.  All signals are synthetic.
"""

import math

import numpy as np
import pytest

from lddecode.rfdecode import RFDecode

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

TAU = 2.0 * math.pi
F_VIDEO = 8.5e6
GAMMA = 0.01


def _rf(on=True):
    return RFDecode(inputfreq=40.0, system="NTSC",
                    extra_options={"AudioCarrierCancel": on})


def _block(rf, seed, gamma=GAMMA):
    """A block whose video carrier's phase follows the first audio carrier.

    Its picture (a random slow FM) differs from seed to seed, as a capture's
    blocks do; the carriers keep their phase across blocks."""
    rng = np.random.default_rng(seed)
    n = rf.blocklen
    t = (np.arange(n) + seed * n) / rf.freq_hz
    fa, fb = rf.SysParams["audio_lfreq"], rf.SysParams["audio_rfreq"]
    theta = gamma * np.sin(TAU * fa * t + 0.7)
    psi = np.cumsum(rng.normal(size=n)) * 2e-3
    rf_block = np.cos(TAU * F_VIDEO * t + psi + theta)
    rf_block += 0.3 * np.cos(TAU * fa * t + 0.3) + 0.3 * np.cos(TAU * fb * t + 0.6)
    return rf_block.astype(np.float64)


def _tone(rf, demod, f_hz):
    """The amplitude (Hz) of a tone at `f_hz` in a block's demodulated video."""
    seg = np.asarray(demod[rf.blockcut : -rf.blockcut_end], dtype=np.float64)
    seg = seg - seg.mean()
    k = np.arange(seg.shape[0]) + rf.blockcut
    w = TAU * f_hz / rf.freq_hz
    return 2.0 * abs(np.dot(seg, np.exp(-1j * w * k))) / seg.shape[0]


def test_nothing_is_cancelled_until_the_coupling_is_measured():
    rf = _rf()
    block = _block(rf, 3)
    plain = _rf(False).demodblock(data=block)["video"]["demod"]
    np.testing.assert_array_equal(rf.demodblock(data=block)["video"]["demod"], plain)


def test_the_measured_coupling_takes_the_carriers_line_out_of_the_video():
    rf = _rf()
    fa = rf.SysParams["audio_lfreq"]
    gains = rf.measure_crosstalk(_block(rf, s) for s in range(8))
    assert gains is not None
    assert rf.DecoderParams["audio_xtalk_gains"]

    block = _block(rf, 11)
    before = _tone(rf, _rf(False).demodblock(data=block)["video"]["demod"], fa)
    after = _tone(rf, rf.demodblock(data=block)["video"]["demod"], fa)
    # The crosstalk's line is GAMMA * fa Hz deep in the demodulated video.
    # (less the video filter's de-emphasis at fa)
    assert before > 0.2 * GAMMA * fa
    assert after < before / 10.0


def test_a_disc_without_crosstalk_measures_next_to_no_coupling():
    rf = _rf()
    rf.measure_crosstalk(_block(rf, s, gamma=0.0) for s in range(8))
    block = _block(rf, 11, gamma=0.0)
    plain = _rf(False).demodblock(data=block)["video"]["demod"]
    out = rf.demodblock(data=block)["video"]["demod"]
    assert np.std(out - plain) < 1e-2 * GAMMA * rf.SysParams["audio_lfreq"]


def test_without_the_option_nothing_is_measured():
    rf = _rf(False)
    assert rf.measure_crosstalk(_block(rf, s) for s in range(2)) is None
    assert "audio_xtalk_gains" not in rf.DecoderParams
