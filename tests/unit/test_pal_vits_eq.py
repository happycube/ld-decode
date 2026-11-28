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


# ---------------------------------------------------------------------------
# The decoder's EQ over time (LDdecode.checkVitsEQ): steady across decode
# filter moves and refits, within the same guards.

import logging  # noqa: E402
import types  # noqa: E402

from lddecode import decoder as decoder_module  # noqa: E402
from lddecode import utils_logging as logs  # noqa: E402
from lddecode.decoder import LDdecode  # noqa: E402


def _eq_decoder(monkeypatch, servo_room=False):
    """An LDdecode carrying only what checkVitsEQ reads.  Each field
    stub brings its own reading (field.reading) and decode filters
    (field.decoded_mtf_level)."""
    monkeypatch.setattr(logs, "logger", logging.getLogger("test-vits-eq"))
    it = LDdecode.__new__(LDdecode)
    it.pal_vits_eq = True
    it.rf = types.SimpleNamespace(
        SysParams={"outfreq": FS / 1e6, "FPS": 25}, DecoderParams={},
        freq_hz_half=20e6)
    it._vitseq_samples = []
    it._vitseq_decided = False
    it._vitseq_since_fit = 0
    it._vitseq_fit_key = None
    it._vitseq_stale = False
    it._vitseq_seen_key = None
    it._vitseq_delta = None
    it._vitseq_mtf_moved = False
    it._vitseq_max_boost = vits_eq.MAX_BOOST
    it._vitseq_log = None
    it._vitseq_target = None
    it._vitseq_target_taps = None
    it._vitseq_fit_readings = []
    it._vitseq_ramp = None
    it._vitseq_hold = 1.0
    it._vitseq_applied = None
    it._vits_measurement = lambda field, fn: None
    it._vitseq_servo_has_room = lambda: servo_room
    monkeypatch.setattr(decoder_module.vits_eq, "field_reading",
                        lambda field, its_line, mb: field.reading)
    return it


class _Feed:
    """Commits one field after another to the decoder stub."""

    def __init__(self, it):
        self.it, self.n = it, 0
        self.params = types.SimpleNamespace(DecoderParams={"vsync_ire": -40})

    def __call__(self, reading, level=0.0, veq=None, imtf=0.0):
        f = types.SimpleNamespace(
            dspicture=np.zeros(1), readloc=self.n, reading=reading,
            decoded_mtf_level=level, decoded_imtf_strength=imtf,
            decoded_video_eq=veq, rf=self.params)
        self.n += 1
        LDdecode.checkVitsEQ(self.it, f)
        return self.it.rf.DecoderParams.get("vits_eq_taps")


def _channel(db, c=0.15, tau=6.0, seed=0, n=1):
    """n readings of a disc channel: a Gaussian loss db at 4 MHz and a
    one-pole tail (c, tau)."""
    rng = np.random.default_rng(seed)
    its = _smear(_lowpass(_its_line(), db), c, tau)
    return _readings(its, _packets(_gauss_gain(MB_F, db)), rng, n=n,
                     noise=0.05)


def _t2_after(taps, reading):
    its = np.asarray(reading[0], np.float64)
    st = vits_eq._bar_steps(its)
    y = its if taps is None else vits_eq.causal_filter(its, taps)[0]
    return vits_eq.conformance_2t(y, FS, st[2])


def test_a_filter_move_keeps_the_boost(monkeypatch):
    it = _eq_decoder(monkeypatch)
    feed = _Feed(it)
    for r in _channel(-3.0, n=vits_eq.MIN_FIELDS):
        taps = feed(r)
    assert taps is not None
    boost = vits_eq.gain_db(taps, FS, np.array([3e6]))[0]
    assert boost > 0.5
    # the decode filters move; the channel the readings show does not
    for r in _channel(-3.0, seed=1, n=vits_eq.MIN_FIELDS + 4):
        held = feed(r, level=-0.5)
        assert held is not None
        db = vits_eq.gain_db(held, FS, np.array([3e6]))[0]
        assert db > boost - 0.3
        assert _t2_after(held, r) <= vits_eq.T2_CAP + 0.01


def test_a_filter_move_to_a_sharper_channel_scales_the_boost_down(
        monkeypatch):
    it = _eq_decoder(monkeypatch)
    feed = _Feed(it)
    for r in _channel(-3.0, n=vits_eq.MIN_FIELDS):
        taps = feed(r)
    sharp = _channel(-1.0, c=0.05, seed=2, n=6)
    st = vits_eq._bar_steps(np.asarray(sharp[0][0], np.float64))
    # the fit's response would overshoot the new channel's 2T ...
    assert _t2_after(taps, sharp[0]) > vits_eq.T2_CAP
    held = []
    for r in sharp:
        held.append(feed(r, level=-0.5))
    # ... so once MIN_GUARD_LINES ITS lines are read under the new
    # filters, the response in force is cut back to the 2T cap, and the
    # scale only falls while the readings are stale
    med = np.median([np.asarray(r[0], np.float64) for r in sharp], 0)
    for h in held[vits_eq.MIN_GUARD_LINES - 1:]:
        assert h is not None
        y = vits_eq.causal_filter(med, h)[0]
        assert vits_eq.conformance_2t(y, FS, st[2]) <= vits_eq.T2_CAP + 0.01
    g = [vits_eq.gain_db(h, FS, np.array([3e6]))[0] for h in held]
    assert all(b <= a + 1e-9 for a, b in zip(g, g[1:]))


def test_a_filter_move_while_the_servo_can_act_is_cut_only(monkeypatch):
    it = _eq_decoder(monkeypatch)
    feed = _Feed(it)
    for r in _channel(-3.0, n=vits_eq.MIN_FIELDS):
        feed(r)
    it._vitseq_servo_has_room = lambda: True
    held = feed(_channel(-3.0, seed=3)[0], level=-0.5)
    db = vits_eq.gain_db(held, FS, np.linspace(0.1e6, 6e6, 60))
    assert np.all(db <= 0.02)


def test_a_refit_is_reached_gradually(monkeypatch):
    it = _eq_decoder(monkeypatch)
    feed = _Feed(it)
    grid = np.linspace(0.5e6, 5e6, 19)
    for r in _channel(-1.5, c=0.10, n=vits_eq.MIN_FIELDS):
        feed(r)
    start = vits_eq.gain_db(it.rf.DecoderParams.get("vits_eq_taps"), FS,
                            grid)
    # the channel changes under the same decode filters: the refit at
    # REFIT_FIELDS adopts a larger response, reached over RAMP_FIELDS
    later = _channel(-3.0, c=0.18, seed=4,
                     n=vits_eq.REFIT_FIELDS + vits_eq.RAMP_FIELDS + 5)
    trace = [vits_eq.gain_db(feed(r), FS, grid) for r in later]
    final = trace[-1]
    assert np.max(np.abs(final - start)) > 2 * vits_eq.ADOPT_DB - 0.1
    steps = np.max(np.abs(np.diff(np.array([start] + trace), axis=0)), 1)
    total = np.max(np.abs(final - start))
    # the ramp's steps, and at most a small cut where a step met a guard
    assert steps.max() <= 2.0 * total / vits_eq.RAMP_FIELDS + 0.05
    assert np.median(steps[steps > 0]) <= 1.2 * total / vits_eq.RAMP_FIELDS
    # it arrives at the refit's response (less any guard scale)
    assert it._vitseq_ramp is None
    target = vits_eq.gain_db(it._vitseq_target_taps, FS, grid)
    assert np.max(np.abs(final - target)) <= 0.1


def test_an_identity_fit_stays_identity(monkeypatch):
    it = _eq_decoder(monkeypatch)
    feed = _Feed(it)
    flat = _readings(_lowpass(_its_line(), -0.01), _packets([1.0] * 6),
                     np.random.default_rng(5), n=40)
    for i, r in enumerate(flat):
        assert feed(r, level=0.0 if i < 25 else -0.5) is None
    assert it._vitseq_decided


def test_a_video_eq_move_is_followed(monkeypatch):
    it = _eq_decoder(monkeypatch)
    feed = _Feed(it)
    for r in _channel(-3.0, n=vits_eq.MIN_FIELDS):
        taps = feed(r)
    grid = np.array([1e6, 2e6, 3e6])
    before = vits_eq.gain_db(taps, FS, grid)
    # the multiburst video EQ (a known zero-phase filter in the decode)
    # lifts 2 MHz by 0.5 dB: the EQ gives exactly that back at once, so
    # the written picture's response is the one the fit guarded
    veq = ((1e6, 0.0), (2e6, 0.5))
    for i, r in enumerate(_channel(-3.0, seed=6, n=vits_eq.MIN_FIELDS - 1)):
        held = feed(r, veq=veq)
        after = vits_eq.gain_db(held, FS, grid)
        np.testing.assert_allclose(after - before, [0.0, -0.5, 0.0],
                                   atol=0.03)
    assert it._vitseq_hold == 1.0


def test_follow_filters_keeps_the_fits_limits():
    fq = np.fft.rfftfreq(vits_eq.NFFT, 1 / FS)
    lg = np.full(len(fq), np.log(1.1)) * vits_eq.band_taper(fq)
    # the filters lost 3 dB: the EQ may give back only up to max_boost
    out = vits_eq.follow_filters(lg, np.full(len(fq), -3 * np.log(10) / 20),
                                 FS, max_boost=vits_eq.MAX_BOOST)
    assert out.max() == pytest.approx(np.log(vits_eq.MAX_BOOST))
    # a cut-only fit stays cut-only
    out = vits_eq.follow_filters(-lg, np.full(len(fq), -0.2), FS,
                                 max_boost=1.0)
    assert out.max() <= 0.0
    # nothing moves above the picture band
    assert np.all(out[fq > vits_eq.TAPER_HI_HZ] == 0.0)


def test_an_eq_coming_in_after_identity_is_set_at_once(monkeypatch):
    it = _eq_decoder(monkeypatch)
    feed = _Feed(it)
    flat = _readings(_lowpass(_its_line(), -0.01), _packets([1.0] * 6),
                     np.random.default_rng(7), n=vits_eq.MIN_FIELDS)
    for r in flat:
        assert feed(r) is None
    # the channel softens under the same filters: the refit's EQ is in
    # force at once, as a first fit is (nothing to ramp from)
    for r in _channel(-3.0, seed=8, n=vits_eq.REFIT_FIELDS):
        taps = feed(r)
    assert taps is not None
    np.testing.assert_array_equal(
        taps, tuple(float(t) for t in it._vitseq_target_taps))
