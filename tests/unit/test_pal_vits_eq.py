"""Unit tests for the write-side residual video EQ (--pal_vits_eq).

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

lddecode.vits_eq fits one causal FIR to a pool of per-field VITS
readings - the ITS line (bar steps and 2T pulse), the multiburst packets
and the blank line - and the decoder applies it to the written picture
only.  These tests drive the fit with synthetic PAL lines through known
channels.

All signals are synthetic.
"""

import numpy as np
import pytest
from scipy.signal import lfilter

from lddecode import vits_eq

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

FS = 4 * 4.43361875e6
W = 1135
MB_F = (0.5e6, 1.0e6, 2.0e6, 4.0e6, 4.8e6, 5.8e6)


def _its_line():
    """A PAL ITS-like line in IRE: blanking, a 100 IRE bar over samples
    200-420 with sin^2 edges, and a 2T pulse (T = 100 ns) 4 us after
    the bar."""
    n = np.arange(W, dtype=np.float64)
    x = np.zeros(W)
    edge = 0.2e-6 * FS

    def ramp(t):
        return np.sin(np.clip(t / edge, 0, 1) * np.pi / 2) ** 2
    x += 100 * ramp(n - 200) * (1 - ramp(n - 420))
    t0 = 420 + 4.0e-6 * FS
    t = (n - t0) / FS
    x += np.where(np.abs(t) < 200e-9, 100 * np.cos(np.pi * t / 400e-9) ** 2, 0)
    return x


def _smear(x, c, tau):
    """The disc's tail: the inverse of vits_eq's tail inverse."""
    a = np.exp(-1.0 / tau)
    return lfilter([1 - c * a, -(1 - c) * a], [1.0, -a], x - x[0]) + x[0]


def _lowpass(x, db_at_4mhz):
    """A zero-phase Gaussian loss, db_at_4mhz down at 4 MHz."""
    f = np.fft.rfftfreq(len(x), 1 / FS)
    k = -np.log(10 ** (db_at_4mhz / 20)) / (4e6) ** 2
    return np.fft.irfft(np.fft.rfft(x) * np.exp(-k * f ** 2), len(x))


def _gauss_gain(f, db_at_4mhz):
    k = -np.log(10 ** (db_at_4mhz / 20)) / (4e6) ** 2
    return np.exp(-k * np.asarray(f) ** 2)


def _readings(its, packets, rng, n=20, noise=0.3):
    out = []
    for _ in range(n):
        x = its + rng.normal(0, noise, W)
        blank = rng.normal(0, 1.0, 850)
        out.append((x.astype(np.float32), packets, blank.astype(np.float32)))
    return out


def _packets(gain):
    return tuple((f, 60.0 * g) for f, g in zip(MB_F, gain))


def test_a_flat_channel_stands_down():
    rng = np.random.default_rng(1)
    its = _lowpass(_its_line(), -0.01)
    taps, rep = vits_eq.fit(_readings(its, _packets([1.0] * 6), rng), FS)
    assert taps is None
    assert rep["stand_down"]


def test_the_tail_is_found_and_undone():
    rng = np.random.default_rng(2)
    its = _smear(_its_line(), 0.18, 7.0)
    taps, rep = vits_eq.fit(_readings(its, _packets([1.0] * 6), rng), FS)
    assert taps is not None
    assert rep["c"] == pytest.approx(0.18, abs=0.03)
    assert rep["tau"] == pytest.approx(7.0, abs=1.5)
    # the bar top after the EQ: the smear's shortfall 0.3-2.3 us after
    # the rising edge is gone
    y = vits_eq.causal_filter(its, taps)[0]
    win = slice(int(205 + 0.3e-6 * FS), int(205 + 2.3e-6 * FS))
    before = np.sqrt(np.mean((100 - its[win]) ** 2))
    after = np.sqrt(np.mean((100 - y[win]) ** 2))
    assert before > 0.5
    assert after < 0.25 * before


def test_no_reliable_tail_gives_no_tail_inverse():
    rng = np.random.default_rng(3)
    its = _lowpass(_its_line(), -1.5)
    gain = _gauss_gain(MB_F, -1.5)
    taps, rep = vits_eq.fit(_readings(its, _packets(gain), rng), FS)
    assert rep["c"] == 0.0


def test_the_boost_stops_at_a_2t_of_one():
    rng = np.random.default_rng(4)
    its = _lowpass(_its_line(), -3.0)
    gain = _gauss_gain(MB_F, -3.0)
    readings = _readings(its, _packets(gain), rng, noise=0.05)
    taps, rep = vits_eq.fit(readings, FS)
    assert taps is not None
    assert rep["t2"] < vits_eq.T2_BOOST_BELOW
    st = vits_eq._bar_steps(its)
    t2_after = vits_eq.conformance_2t(
        vits_eq.causal_filter(its, taps)[0], FS, st[2])
    assert rep["t2"] < t2_after <= vits_eq.T2_CAP + 0.005
    # never more than MAX_BOOST, and back to unity above the band edge
    db = vits_eq.gain_db(taps, FS, np.array([2e6, 4e6, 6.2e6]))
    assert np.all(db <= 20 * np.log10(vits_eq.MAX_BOOST) + 0.05)
    assert abs(db[2]) < 0.1


def test_a_hot_band_with_no_tail_is_left_alone():
    rng = np.random.default_rng(5)
    gain = [1.0, 1.0, 1.05, 1.15, 1.2, 1.0]   # no deficit anywhere
    taps, rep = vits_eq.fit(_readings(_its_line(), _packets(gain), rng), FS)
    assert taps is None
    assert rep["stand_down"]


def test_a_sharp_2t_allows_no_boost():
    rng = np.random.default_rng(9)
    its = _smear(_its_line(), 0.15, 6.0)
    gain = _gauss_gain(MB_F, -1.0)
    taps, rep = vits_eq.fit(_readings(its, _packets(gain), rng), FS)
    if rep["t2"] >= vits_eq.T2_BOOST_BELOW:
        db = vits_eq.gain_db(taps, FS, np.linspace(0.1e6, 6e6, 60))
        assert np.all(db <= 0.02)


def test_the_boost_is_held_to_the_noise_rise():
    rng = np.random.default_rng(6)
    its = _lowpass(_its_line(), -3.0)
    gain = _gauss_gain(MB_F, -3.0)
    readings = _readings(its, _packets(gain), rng, noise=0.05)
    taps, rep = vits_eq.fit(readings, FS)
    assert rep["noise_out"] <= rep["noise_in"] + vits_eq.NOISE_RISE_IRE + 1e-6


def test_the_stream_filter_is_continuous_across_blocks():
    rng = np.random.default_rng(7)
    x = rng.normal(0, 10, 20000) + 50
    taps = vits_eq.tail_impulse(0.2, 6.0)
    taps = np.convolve(taps, [0.1, 0.8, 0.1])
    whole = vits_eq.StreamEQ().process(x, taps)
    s = vits_eq.StreamEQ()
    parts = np.concatenate([s.process(x[a:b], taps)
                            for a, b in ((0, 3000), (3000, 3001),
                                         (3001, 12000), (12000, 20000))])
    np.testing.assert_allclose(parts, whole, atol=1e-9)


def test_no_taps_writes_the_input_unchanged():
    x = np.arange(100, dtype=np.float64)
    s = vits_eq.StreamEQ()
    assert s.process(x, None) is x or np.array_equal(s.process(x, None), x)


def test_the_output_is_held_at_the_decoders_floor():
    x = np.r_[np.full(50, 10.0), np.full(50, 100.0), np.full(50, 10.0)]
    taps = np.array([1.6, -0.6])          # overshooting edges
    y = vits_eq.StreamEQ().process(x, taps, floor=10.0)
    assert y.min() >= 10.0
    assert y.max() > 100.0


def test_the_filter_has_unit_dc_gain_and_is_causal():
    rng = np.random.default_rng(8)
    its = _smear(_lowpass(_its_line(), -3.0), 0.15, 6.0)
    gain = _gauss_gain(MB_F, -3.0)
    taps, _ = vits_eq.fit(_readings(its, _packets(gain), rng), FS)
    assert taps.sum() == pytest.approx(1.0)
    # minimum phase: the energy is at the front
    e = np.cumsum(taps ** 2) / np.sum(taps ** 2)
    assert e[8] > 0.9


def test_no_boost_while_the_2t_servo_can_still_act():
    rng = np.random.default_rng(10)
    its = _lowpass(_its_line(), -3.0)
    gain = _gauss_gain(MB_F, -3.0)
    taps, rep = vits_eq.fit(_readings(its, _packets(gain), rng, noise=0.05),
                            FS, allow_boost=False)
    db = vits_eq.gain_db(taps, FS, np.linspace(0.1e6, 6e6, 60))
    assert np.all(db <= 0.02)
