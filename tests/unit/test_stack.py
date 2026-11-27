"""
Unit tests for the multi-source RF stacking.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The stack combines several captures of the same disc into one RF stream,
before demodulation.  These tests build a synthetic disc in memory (a
carrier in the video band, some video-band content and a line structure
with a known frame code), capture it a few times with different noise,
different offsets and a dropout, and check the pairing, the weighting, the
dropout fallback and the sub-sample accuracy of the reads.

Everything here is hermetic: the captures are numpy arrays built in the
test, the line locator is replaced by a seam (lddecode.stack.locate_fields)
that returns the synthetic disc's known line positions, and no file, no
clock and no subprocess is touched.

All signals are synthetic.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np
import pytest

from lddecode import stack
from lddecode.stack import (
    PAIR_LOOKAHEAD,
    QN_CARRIER,
    QN_LOCK,
    StackedSource,
    StackInput,
    amp_weight,
    build_timeline,
    carrier_lag,
    carrier_measure,
    noise_floor,
    phase_lock,
    sinc_lut,
    video_band_lut,
)

pytestmark = [pytest.mark.unit, pytest.mark.decode]

# --------------------------------------------------------------------------
# The synthetic disc
# --------------------------------------------------------------------------

#: The capture's sample rate (Hz).
FS = 75.0e6
#: NTSC's line length (samples): 63.5555... us at 75 MHz.
LINELEN = FS * (227.5e6 * 88.0 / 315.0e6) / 1e6
#: The first line's position (samples).
FIRST_LINE = 2000.0
#: The lines per field, and the fields per capture.
LINES_PER_FIELD = 4
FIELD_COUNT = 2
#: The frame code every field of the synthetic disc carries (a CLV time code:
#: the top nibble is 0xF).
FRAME_CODE = 0xF12345
#: The video band's carrier (Hz): inside the analytic video band.
CARRIER_HZ = 8.0e6
#: The carrier's amplitude.
CARRIER_AMP = 1000.0
#: The video band's content: tones (Hz) and their amplitudes, spread over
#: the video band so that a sub-sample misalignment shows.
CONTENT_TONES = (3.5e6, 5.0e6, 6.5e6, 9.0e6, 11.0e6, 13.0e6)
CONTENT_AMP = 300.0
#: The band the noise is measured in (Hz): below the video band, where the
#: synthetic disc carries nothing.
NOISE_BAND = (0.4e6, 1.6e6)
#: The capture's length (samples).
CAPTURE_LENGTH = int(FIRST_LINE + FIELD_COUNT * LINES_PER_FIELD * LINELEN + 4000)


@dataclass
class _Record:
    """A pass-0 field record.

    It follows the protocol of lddecode.rf_sync.FieldRecord: the lines'
    absolute positions, the frame code words and the parity.
    """

    first: bool
    code: list | None
    lines: list


def _tone(freq: float, t: np.ndarray, phase: float = 0.0) -> np.ndarray:
    """A tone at ``freq`` (Hz) over the times ``t`` (samples, at ``FS``).

    The phase is reduced to a cycle first: numpy's vectorised cosine loses
    its argument reduction over the large arguments this reaches.
    """
    cycles = np.remainder(freq * t / FS, 1.0)
    return np.cos(2.0 * np.pi * cycles + phase)


def _disc_content(t: np.ndarray) -> np.ndarray:
    """The synthetic disc's signal at the times ``t`` (samples of the disc)."""
    out = CARRIER_AMP * _tone(CARRIER_HZ, t)
    for k, f in enumerate(CONTENT_TONES):
        out = out + CONTENT_AMP * _tone(f, t, 0.7 * (k + 1))
    return out


def _capture(delta: float, rng: np.random.Generator, sigma: float, dropout=None) -> StackInput:
    """A capture of the synthetic disc.

    The capture plays the disc ``delta`` samples late (so its lines sit
    ``delta`` samples further into the file), with white noise of the
    standard deviation ``sigma``; ``dropout`` is a ``(start, end)`` stretch
    of samples where the disc's signal is lost.
    """
    n = CAPTURE_LENGTH
    t = np.arange(n, dtype=np.float64) - delta
    samples = _disc_content(t) + rng.standard_normal(n) * sigma
    if dropout is not None:
        lo, hi = dropout
        samples[lo:hi] = rng.standard_normal(hi - lo) * sigma
    samples = samples.astype(np.float64)

    def read_fn(start: int, count: int) -> np.ndarray:
        out = np.zeros(count, dtype=np.float64)
        lo = max(0, int(start))
        hi = min(n, int(start) + count)
        if hi > lo:
            out[lo - int(start) : hi - int(start)] = samples[lo:hi]
        return out

    return StackInput(path=f"capture{delta:+.2f}", read_fn=read_fn, length=n)


def _records(delta: float) -> list[_Record]:
    """The pass-0 records of a capture of the synthetic disc."""
    records = []
    for f in range(FIELD_COUNT):
        lines = [
            FIRST_LINE + (f * LINES_PER_FIELD + k) * LINELEN + delta for k in range(LINES_PER_FIELD)
        ]
        records.append(_Record(first=(f % 2 == 0), code=[FRAME_CODE], lines=lines))
    return records


def _reader_key(read_fn) -> tuple:
    """A key that identifies the capture a reader reads."""
    return tuple(np.asarray(read_fn(0, 4), dtype=np.float64).tolist())


def _install_locator(monkeypatch, captures, deltas) -> None:
    """Replace the line locator by one that knows the synthetic disc's lines.

    The source hands the locator a reader of its own (one that reads short
    at the end of the capture), so the capture is recognised by its first
    samples.
    """
    keys = {_reader_key(cap.read_fn): delta for cap, delta in zip(captures, deltas)}

    def locate(read_fn, fs, ntsc, stop=None, length=None):
        # The capture's length is passed on, so the scan ends even when the
        # reader pads past the end of the capture.
        assert length is not None
        return _records(keys[_reader_key(read_fn)])

    monkeypatch.setattr(stack, "locate_fields", locate)


def _source(monkeypatch, captures, deltas, **kwargs) -> StackedSource:
    """A stacked source over the synthetic captures."""
    _install_locator(monkeypatch, captures, deltas)
    options = dict(
        ntsc=True,
        stack_weight="adaptive",
        cancel_xtalk=False,
        cancel_xtal=False,
        cancel_leak=False,
    )
    options.update(kwargs)
    return StackedSource(captures, FS, **options)


def _band_snr(samples: np.ndarray, fs: float = FS, signal_hz: float = CARRIER_HZ) -> float:
    """The SNR of a stream: the carrier's power over the mean noise power (dB).

    The noise is measured in the low band (below the video band), where the
    synthetic disc carries nothing.
    """
    x = samples.astype(np.float64)
    n = x.shape[0]
    spectrum = np.abs(np.fft.rfft(x)) ** 2
    freqs = np.arange(spectrum.shape[0], dtype=np.float64) * fs / n
    signal = spectrum[np.abs(freqs - signal_hz) <= fs / n].sum()
    band = (freqs >= NOISE_BAND[0]) & (freqs <= NOISE_BAND[1])
    noise = spectrum[band].mean()
    return 10.0 * np.log10(signal / noise)


# --------------------------------------------------------------------------
# The pairing and the timeline
# --------------------------------------------------------------------------


def _line_positions(records) -> list[float]:
    return [line for rec in records for line in rec.lines]


def test_the_timeline_pairs_the_fields_of_the_same_frame():
    """Two captures of the same disc pair their fields, and their lines follow."""
    delta = 0.37
    primary = _records(0.0)
    secondary = _records(delta)
    timeline = build_timeline([primary, secondary], LINELEN, CAPTURE_LENGTH)

    # The lead-in anchor, then one anchor per line of the primary.
    assert timeline.t[0] == 0.0
    assert timeline.pos[0][0] == 0.0
    assert not np.isfinite(timeline.pos[1][0])  # the secondary is not there yet
    assert timeline.t.shape[0] == 2 + len(_line_positions(primary))
    # Every line of the primary is paired with the same line of the secondary,
    # at its own (offset) position.  The last anchor is the tail, where the
    # primary is alone again.
    np.testing.assert_allclose(
        timeline.pos[1][1:-1],
        np.asarray(_line_positions(secondary)),
        rtol=0.0,
        atol=1e-9,
    )
    np.testing.assert_allclose(
        timeline.pos[0][1:-1], np.asarray(_line_positions(primary)), rtol=0.0, atol=1e-9
    )
    assert not np.isfinite(timeline.pos[1][-1])


def test_the_timeline_keeps_each_line_once():
    """Fields overlap by a few lines: a line within a quarter line is kept once."""
    primary = [
        _Record(
            first=True,
            code=[FRAME_CODE],
            lines=[FIRST_LINE + k * LINELEN for k in range(4)],
        )
    ]
    # The next field starts before the first one ends: its first line is
    # within a quarter line of the one already laid down, so it is skipped.
    primary.append(
        _Record(
            first=False,
            code=[FRAME_CODE],
            lines=[FIRST_LINE + 3.1 * LINELEN, FIRST_LINE + 4 * LINELEN],
        )
    )
    timeline = build_timeline([primary], LINELEN, CAPTURE_LENGTH)
    # Five lines were offered, one of them within a quarter line of the
    # previous one: four line anchors, plus the lead-in and the tail.
    assert timeline.t.shape[0] == 7


def test_the_timeline_advances_in_half_line_steps():
    """The ideal time of an anchor keeps the half-line resolution."""
    primary = [
        _Record(
            first=True,
            code=[FRAME_CODE],
            lines=[FIRST_LINE, FIRST_LINE + LINELEN * 0.5, FIRST_LINE + LINELEN * 1.5],
        )
    ]
    timeline = build_timeline([primary], LINELEN, CAPTURE_LENGTH)
    # The three line anchors (the tail anchor is not one of them).
    steps = np.diff(timeline.t[1:4])
    np.testing.assert_allclose(steps, LINELEN * np.array([0.5, 1.0]), rtol=1e-9, atol=1e-6)


def test_the_timeline_rounds_the_half_line_away_from_zero():
    """The reference rounds the half-line count half away from zero.

    A line and a quarter between two anchors is 2.5 half-lines: the
    reference rounds it to 3 (a line and a half), the rounding to even would
    give 2 (a line).
    """
    primary = [
        _Record(
            first=True,
            code=[FRAME_CODE],
            lines=[FIRST_LINE, FIRST_LINE + LINELEN * 1.25],
        )
    ]
    timeline = build_timeline([primary], LINELEN, CAPTURE_LENGTH)
    # The two line anchors and the tail anchor.
    step = timeline.t[2] - timeline.t[1]
    np.testing.assert_allclose(step, LINELEN * 1.5, rtol=1e-9, atol=1e-6)


def test_a_repeated_frame_code_leaves_the_input_unpaired():
    """A frame code that repeats in a capture is ambiguous: it is left out."""
    primary = [
        _Record(first=True, code=[FRAME_CODE], lines=[FIRST_LINE + k * LINELEN for k in range(4)]),
        _Record(
            first=False,
            code=[FRAME_CODE + 1],
            lines=[FIRST_LINE + (4 + k) * LINELEN for k in range(4)],
        ),
    ]
    # The secondary repeats the first field's code: the key is ambiguous, so
    # the primary's first field is left unpaired rather than mispaired.
    secondary = [
        _Record(first=True, code=[FRAME_CODE], lines=[FIRST_LINE + k * LINELEN for k in range(4)]),
        _Record(
            first=True, code=[FRAME_CODE], lines=[FIRST_LINE + (4 + k) * LINELEN for k in range(4)]
        ),
        _Record(
            first=False,
            code=[FRAME_CODE + 1],
            lines=[FIRST_LINE + (8 + k) * LINELEN for k in range(4)],
        ),
    ]
    timeline = build_timeline([primary, secondary], LINELEN, CAPTURE_LENGTH)
    # The first four anchors are the primary's first field: the secondary is
    # not paired with it (its key repeats).
    assert not np.isfinite(timeline.pos[1][1:5]).any()
    # The second field's key is not repeated, so it is paired.
    assert np.isfinite(timeline.pos[1][5:9]).all()


def test_a_line_length_off_by_more_than_two_percent_leaves_the_input_out():
    """A capture whose lines are 3% longer is left out of that segment."""
    primary = [
        _Record(first=True, code=[FRAME_CODE], lines=[FIRST_LINE + k * LINELEN for k in range(4)])
    ]
    secondary = [
        _Record(
            first=True,
            code=[FRAME_CODE],
            lines=[FIRST_LINE + k * LINELEN * 1.03 for k in range(4)],
        )
    ]
    timeline = build_timeline([primary, secondary], LINELEN, CAPTURE_LENGTH)
    # The line lengths differ by 3%: the secondary does not cover the
    # segment, so its position there is not covered.
    for k in range(1, len(timeline.t) - 1):
        assert np.isnan(timeline.position(1, k, timeline.t[k]))
    # The primary's own positions are untouched.
    assert np.isfinite(timeline.position(0, 1, timeline.t[1]))


def test_a_capture_without_a_frame_code_is_not_paired():
    """A field with no frame code cannot be paired with anything."""
    primary = [
        _Record(first=True, code=[FRAME_CODE], lines=[FIRST_LINE + k * LINELEN for k in range(4)])
    ]
    secondary = [_Record(first=True, code=None, lines=[FIRST_LINE + k * LINELEN for k in range(4)])]
    timeline = build_timeline([primary, secondary], LINELEN, CAPTURE_LENGTH)
    assert not np.isfinite(timeline.pos[1][1:]).any()


def test_a_primary_without_lines_is_refused():
    """A primary with no usable line is an error, not an empty stream."""
    with pytest.raises(ValueError, match="no usable lines"):
        build_timeline([[_Record(first=True, code=[FRAME_CODE], lines=[])]], LINELEN, 1000)


# --------------------------------------------------------------------------
# The carrier measure, the weights and the lock
# --------------------------------------------------------------------------


@pytest.mark.dsp
def test_the_carrier_measure_reads_no_carrier_on_noise():
    """Noise alone reads no carrier, whatever its level."""
    rng = np.random.default_rng(1234)
    n = 512
    lag = carrier_lag(FS)
    noise = rng.standard_normal(n) + 1j * rng.standard_normal(n)
    rl = np.sum(noise[lag:] * np.conj(noise[:-lag]))
    e = float(np.sum(np.abs(noise) ** 2))
    power, frac = carrier_measure(rl, e, n, QN_LOCK)
    assert float(power) == 0.0
    assert float(frac) == 0.0

    # A loud noise reads no carrier either: the measure is blind to the
    # noise's level.
    rl = np.sum((noise[lag:] * 1000.0) * np.conj(noise[:-lag] * 1000.0))
    e = float(np.sum(np.abs(noise * 1000.0) ** 2))
    power, frac = carrier_measure(rl, e, n, QN_LOCK)
    assert float(power) == 0.0


@pytest.mark.dsp
def test_the_carrier_measure_reads_a_carrier():
    """A tone in the video band reads a high carrier fraction."""
    n = 512
    lag = carrier_lag(FS)
    t = np.arange(n)
    tone = np.exp(2j * np.pi * 0.3 * t)
    rl = np.sum(tone[lag:] * np.conj(tone[:-lag]))
    e = float(np.sum(np.abs(tone) ** 2))
    power, frac = carrier_measure(rl, e, n, QN_LOCK)
    assert float(frac) > 0.9
    assert float(power) == pytest.approx(1.0, rel=0.05)


@pytest.mark.dsp
def test_the_carrier_lag_follows_the_sample_rate():
    """The lag is the sample rate over the video band's width, at least one."""
    assert carrier_lag(75.0e6) == 5
    assert carrier_lag(40.0e6) == 3
    assert carrier_lag(1.0e6) == 1


def test_the_carrier_lag_is_rounded_half_away_from_zero():
    """The reference rounds the lag half away from zero, not to even.

    At 37.5 MHz the rate over the band's width is 2.5 samples: the reference
    takes 3, the rounding to even would take 2.
    """
    assert carrier_lag(37.5e6) == 3
    assert carrier_lag(67.5e6) == 5
    # A rate below the band's width still gives one sample.
    assert carrier_lag(10.0e6) == 1


@pytest.mark.dsp
def test_the_phase_lock_recovers_a_known_rotation():
    """The lock's rotation is the phase difference between the two bands."""
    n = 128
    phi = 0.3
    r = complex(np.cos(phi), np.sin(phi)) * n
    rot, guard = phase_lock(r, float(n), float(n), float(n), 0.99, 0.99, 1.0)
    assert abs(np.angle(rot) - phi) < 1e-3
    assert float(guard) == pytest.approx(1.0)


@pytest.mark.dsp
def test_the_alignment_guard_leaves_a_misaligned_input_out():
    """A low coherence (as a misalignment gives) leaves the input out."""
    n = 128
    r = complex(0.2 * n, 0.0)
    rot, guard = phase_lock(r, float(n), float(n), float(n), 0.99, 0.99, 1.0)
    assert float(guard) == pytest.approx(0.0)


@pytest.mark.dsp
def test_the_alignment_guard_needs_the_primarys_own_carrier():
    """At the edge of the primary's dropout the guard does not apply."""
    n = 128
    r = complex(0.2 * n, 0.0)
    _, guard = phase_lock(r, float(n), float(n), float(n), 0.99, 0.99, 0.0)
    assert float(guard) == pytest.approx(1.0)


@pytest.mark.dsp
def test_the_amplitude_weight_is_floored():
    """An input with no carrier weighs its floor, not nothing."""
    assert float(amp_weight(0.0, 0.05, 2.0)) == pytest.approx(0.1)
    assert float(amp_weight(4.0, 0.05, 2.0)) == pytest.approx(4.0)


@pytest.mark.dsp
def test_the_noise_floor_of_a_white_noise_capture():
    """The noise floor of a white capture is its variance."""
    rng = np.random.default_rng(99)
    n = 1 << 17
    sigma = 0.25
    samples = rng.standard_normal(n) * sigma

    def read_fn(start, count):
        return samples[start : start + count]

    estimate = noise_floor(read_fn, 0, FS)
    assert estimate == pytest.approx(sigma**2, rel=0.1)


@pytest.mark.dsp
def test_the_sinc_table_is_normalised():
    """Every phase of the sinc table sums to one."""
    lut = sinc_lut()
    assert lut.shape == (1025, 32)
    np.testing.assert_allclose(lut.sum(axis=1), 1.0, rtol=0.0, atol=1e-12)


def test_the_fractional_phase_is_rounded_half_away_from_zero():
    """The reference rounds the sinc's phase half away from zero.

    At half a phase (1/2048 of a sample), the reference takes the phase
    above (1), the rounding to even would take the phase below (0).
    """
    # A ramp: the filter's output tells which phase it used.
    raw = np.arange(4096, dtype=np.float64)
    sinc = sinc_lut()
    # Half a phase above the sample 100.
    span = stack._InputSpan(raw=raw, start=0, positions=np.array([100.0 + 1.0 / 2048.0]))
    hi = video_band_lut(FS, (2.5e6, 3.6e6))
    parts = (np.ascontiguousarray(hi.real), np.ascontiguousarray(hi.imag))
    full, _band, _covered = stack._read_input(span, sinc, parts)
    above = np.dot(sinc[1, :], raw[100 - 15 : 100 - 15 + 32])
    below = np.dot(sinc[0, :], raw[100 - 15 : 100 - 15 + 32])
    np.testing.assert_allclose(full[0], above, rtol=1e-12, atol=1e-9)
    # The two phases differ enough on a ramp for the choice to be visible.
    assert abs(above - below) > 1e-4


@pytest.mark.dsp
def test_the_video_band_filter_has_no_energy_below_the_split():
    """The analytic video band starts at the split (2.5 MHz, NTSC)."""
    fs = 75.0e6
    lut = video_band_lut(fs, (2.5e6, 3.5e6))
    assert lut.shape == (1025, 128)
    # The filter's response at 1 MHz is (near) zero: the low band is the full
    # signal minus this band.
    n = 1 << 14
    impulse = np.zeros(n)
    impulse[n // 2] = 1.0
    taps = lut[0].real
    response = np.abs(np.fft.rfft(taps, n))
    freqs = np.arange(response.shape[0]) * fs / n
    low = response[(freqs > 0.2e6) & (freqs < 1.5e6)].max()
    high = response[(freqs > 6.0e6) & (freqs < 10.0e6)].max()
    # The leakage across the crossover is near -37 dB in the Rust: -40 dB
    # here, measured over the low band.
    assert low < 1e-2 * high


# --------------------------------------------------------------------------
# The stacking, end to end
# --------------------------------------------------------------------------


def test_read_returns_exactly_readlen_samples(monkeypatch):
    """The source serves exactly the number of samples asked for."""
    rng = np.random.default_rng(7)
    capture = _capture(0.0, rng, 5.0)
    source = _source(monkeypatch, [capture], [0.0])
    for readlen in (1, 1000, 12345):
        got = source.read(0, readlen)
        assert got.shape == (readlen,)
        assert got.dtype == np.float64


def test_read_is_short_at_the_end_of_the_stream(monkeypatch):
    """The decoder takes a short read as the end of its input, so the
    stream ends with one: the samples left, then none at all."""
    rng = np.random.default_rng(7)
    capture = _capture(0.0, rng, 5.0)
    source = _source(monkeypatch, [capture], [0.0])
    assert source.read(source.length - 10, 100).shape == (10,)
    assert source.read(source.length, 100).shape == (0,)


def test_read_keeps_values_past_the_int16_range(monkeypatch):
    """An unsigned 16-bit capture reads up to 65535: the stream hands its
    values on unclipped and unrounded, as the reference's f32 source does."""
    n = CAPTURE_LENGTH
    samples = 40000.0 + 0.25 * np.cos(2.0 * np.pi * CARRIER_HZ / FS * np.arange(n))

    def read_fn(start: int, count: int) -> np.ndarray:
        out = np.zeros(count, dtype=np.float64)
        lo, hi = max(0, start), min(n, start + count)
        if hi > lo:
            out[lo - start : hi - start] = samples[lo:hi]
        return out

    capture = StackInput(path="u16", read_fn=read_fn, length=n)
    source = _source(monkeypatch, [capture], [0.0])
    middle = source.read(n // 2, 1000).astype(np.float64)
    np.testing.assert_allclose(middle.mean(), 40000.0, rtol=0, atol=1.0)
    # Not rounded to whole units: the quarter-unit carrier is still there.
    assert np.abs(middle - np.rint(middle)).max() > 0.01


def test_the_read_ahead_keeps_recent_chunks_whatever_their_position():
    """A read behind the last one finds its chunk again: the field jobs of
    a threaded decode read ahead of the decoder's own reads, and a buffer
    that dropped everything behind the newest read would compute the same
    chunks over and over."""
    computed = []

    def compute(index, chunk):
        computed.append(index)
        return np.full(chunk, index, dtype=np.float32)

    cache = stack._ChunkCache(compute, chunk=16, ahead=1, behind=0)
    try:
        for index in (0, 6, 1, 0, 6):
            assert cache.get(index)[0] == index
    finally:
        cache.stop()
    assert computed.count(0) == 1
    assert computed.count(6) == 1


def test_the_stream_length_matches_the_primarys_coverage(monkeypatch):
    """The stream ends where the primary's capture ends."""
    rng = np.random.default_rng(8)
    capture = _capture(0.0, rng, 5.0)
    source = _source(monkeypatch, [capture], [0.0])
    assert source.length == pytest.approx(CAPTURE_LENGTH, abs=2.0)
    # The last samples of the stream are not zero: the tail is the primary
    # alone, read at its own positions.
    tail = source.read(source.length - 1000, 1000)
    assert np.abs(tail).max() > 0.0


def test_the_stacked_stream_beats_the_best_single_input(monkeypatch):
    """Three captures of the same disc stack better than any one of them.

    The metric is the SNR: the carrier's power over the mean noise power of
    the low band, in dB.  Three captures of the same noise stack about
    4.8 dB (10*log10(3)) better than one of them; the test asks for 2 dB.
    """
    rng = np.random.default_rng(11)
    sigma = 40.0
    captures = [_capture(0.0, rng, sigma), _capture(0.37, rng, sigma), _capture(-0.61, rng, sigma)]
    deltas = [0.0, 0.37, -0.61]

    stacked = _source(monkeypatch, captures, deltas)
    stream = stacked.read(0, stacked.length).astype(np.float64)
    stacked_snr = _band_snr(stream)

    singles = []
    for capture, delta in zip(captures, (0.0, 0.37, -0.61)):
        one = _source(monkeypatch, [capture], [delta])
        singles.append(_band_snr(one.read(0, one.length).astype(np.float64)))
    best = max(singles)

    assert (
        stacked_snr > best + 2.0
    ), f"stacked {stacked_snr:.2f} dB, best single {best:.2f} dB, singles {singles}"


def test_a_dropout_input_stops_contributing(monkeypatch):
    """An input in a dropout weighs almost nothing: the others carry on."""
    rng = np.random.default_rng(13)
    sigma = 40.0
    dropout = (int(FIRST_LINE + LINELEN), int(FIRST_LINE + 3 * LINELEN))
    healthy = _capture(0.0, rng, sigma)
    sick = _capture(0.37, rng, sigma, dropout=dropout)
    deltas = [0.0, 0.37]
    source = _source(monkeypatch, [healthy, sick], deltas)
    stream = source.read(0, source.length).astype(np.float64)

    # The dropout falls inside the stream, at the sample the sick capture's
    # signal is lost.
    start = int(dropout[0] - 0.37)
    stop = int(dropout[1] - 0.37)
    in_dropout = _band_snr(stream[start:stop])
    outside = _band_snr(stream[int(FIRST_LINE) : stop])
    # The healthy capture carries the stack through the dropout: the SNR
    # there is close to the SNR outside it (the sick capture adds noise
    # there, but little signal).
    assert in_dropout > outside - 1.5, f"dropout {in_dropout:.2f} dB, outside {outside:.2f} dB"


def test_the_weight_sum_falls_back_to_the_healthy_inputs():
    """The sum of the weights drops to the healthy inputs' when one drops out.

    The combine step is driven directly here, with a carrier in one input's
    video band and noise only in the other's.
    """
    n = 512
    rng = np.random.default_rng(17)
    t = np.arange(n)
    carrier = 100.0 * np.exp(2j * np.pi * 0.3 * t)
    healthy_band = carrier
    sick_band = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) * 0.01
    healthy = (np.real(healthy_band), healthy_band, np.ones(n, dtype=bool))
    sick = (np.real(sick_band), sick_band, np.ones(n, dtype=bool))
    afloor = 0.05
    weight = 1.0
    out, wsum, _ = stack._combine(
        [healthy, sick], [weight, weight], [afloor, afloor], "adaptive", 5, 0
    )
    # The healthy input's weight is its carrier amplitude; the sick input's
    # is its floor.
    assert wsum[int(n / 2)] == pytest.approx(100.0 + afloor, rel=1e-3)
    assert float(out[int(n / 2)]) == pytest.approx(np.real(carrier[int(n / 2)]), rel=1e-3)


def test_the_read_is_sub_sample_accurate(monkeypatch):
    """The served stream is the disc's signal, read at the fractional positions.

    The second capture is 0.37 samples out of step with the primary: read at
    the fractional position, its content adds to the primary's; read at a
    rounded position, it would be decorrelated (the content's tones are up
    to 13 MHz, so half a sample is a third of a cycle).
    """
    rng = np.random.default_rng(19)
    sigma = 2.0
    delta = 0.37
    captures = [_capture(0.0, rng, sigma), _capture(delta, rng, sigma)]
    deltas = [0.0, delta]
    source = _source(monkeypatch, captures, deltas)
    stream = source.read(0, source.length).astype(np.float64)

    # The disc's signal at the virtual positions.
    expected = _disc_content(np.arange(source.length, dtype=np.float64))
    error = stream - expected
    content = np.std(expected)
    rms = float(np.sqrt(np.mean(error**2)))
    # The tolerance is 2% of the content's RMS: the noise alone (the two
    # captures' noise, averaged) is 0.2% of it, while a read at the rounded
    # positions would be decorrelated and give 14%.
    assert rms < 0.02 * content, f"rms {rms:.3f} against a content of {content:.3f}"


def test_the_fixed_mode_weighs_every_input_by_its_noise_weight():
    """In the "fixed" mode every input weighs its 1/sigma^2 weight alone."""
    n = 256
    rng = np.random.default_rng(29)
    t = np.arange(n)
    band_a = 100.0 * np.exp(2j * np.pi * 0.3 * t)
    band_b = 50.0 * np.exp(2j * np.pi * 0.3 * t + 0.2)
    reads = [
        (np.real(band_a), band_a, np.ones(n, dtype=bool)),
        (np.real(band_b), band_b, np.ones(n, dtype=bool)),
    ]
    _, wsum, _ = stack._combine(reads, [3.0, 5.0], [0.05, 0.05], "fixed", 5, 0)
    # The primary's weight is its fixed one too, not its carrier amplitude.
    assert wsum[int(n / 2)] == pytest.approx(8.0)


def test_the_fixed_weight_mode_uses_the_noise_weights(monkeypatch):
    """The "fixed" mode weighs every input by its 1/sigma^2 weight alone."""
    rng = np.random.default_rng(23)
    captures = [_capture(0.0, rng, 40.0), _capture(0.37, rng, 40.0)]
    deltas = [0.0, 0.37]
    adaptive = _source(monkeypatch, captures, deltas)
    fixed = _source(monkeypatch, captures, deltas, stack_weight="fixed")
    assert adaptive.weight == fixed.weight
    assert fixed.stack_weight == "fixed"
    # Both serve the same number of samples.
    assert adaptive.length == fixed.length


# --------------------------------------------------------------------------
# Pass 0, alongside the decode
# --------------------------------------------------------------------------


def _field(index: int, code: int, first: bool) -> _Record:
    """Field ``index`` of a capture with no offset, carrying ``code``."""
    lines = [FIRST_LINE + (index * LINES_PER_FIELD + k) * LINELEN for k in range(LINES_PER_FIELD)]
    return _Record(first=first, code=[code], lines=lines)


def test_a_code_repeated_past_the_lookahead_keeps_its_first_pairing():
    """A secondary field is paired once 16 later fields of its capture are
    known; a repeat of its code further on is seen too late to undo a
    primary field already laid down, as in the reference's live pairing."""
    count = PAIR_LOOKAHEAD + 4
    primary = [_field(k, FRAME_CODE + k, k % 2 == 0) for k in range(count)]
    secondary = [_field(k, FRAME_CODE + k, k % 2 == 0) for k in range(count)]
    # The secondary skips back to its first frame, past the lookahead.
    secondary.append(_field(count, FRAME_CODE, True))
    timeline = build_timeline([primary, secondary], LINELEN, 10**9)
    # The primary's first field (anchors 1 to 4) is paired all the same.
    assert np.isfinite(timeline.pos[1][1 : 1 + LINES_PER_FIELD]).all()


def test_the_timeline_is_served_before_pass_0_has_ended():
    """The live timeline lays down a primary field as soon as every input
    is located for it: a read waits for its anchors, not for the scans."""
    live = stack.LiveTimeline(1, LINELEN, CAPTURE_LENGTH)
    for rec in _records(0.0):
        live.push(0, rec)
    assert live.wait_cover(FIRST_LINE + LINELEN) is None
    part = live.slice(FIRST_LINE, int(LINELEN))
    assert part.t.shape[0] >= 2
    live.finish(0)
    assert live.wait_cover(0.0) == pytest.approx(CAPTURE_LENGTH, abs=2.0)


def test_a_scan_failing_after_the_stop_is_not_an_error():
    """Pass 0 is stopped where the decode stops; a scan ending with an
    error then is that stop, not a failure."""
    live = stack.LiveTimeline(1, LINELEN, CAPTURE_LENGTH)
    for rec in _records(0.0):
        live.push(0, rec)
    live.stop()
    assert live.stopped()
    live.finish(0, RuntimeError("stopped"))
    assert live.wait_done().t.shape[0] >= 2


def test_the_stream_is_read_while_pass_0_still_runs(monkeypatch):
    """The source reads the stream while the scans still run, and close()
    stops them: pass 0 ends where the decode ends."""
    rng = np.random.default_rng(21)
    capture = _capture(0.0, rng, 5.0)
    released = threading.Event()
    stopped = threading.Event()

    # Enough fields for the stream's first chunk (a chunk waits for the
    # anchors to its end); past the capture they read as silence.
    fields = (stack.CHUNK + 4 * stack.LOCK_MARGIN) // int(LINES_PER_FIELD * LINELEN) + 2

    def locate(read_fn, fs, ntsc, stop=None, length=None):
        for k in range(fields):
            yield _field(k, FRAME_CODE, k % 2 == 0)
        # The scan has more to read: it waits, polling its stop.
        while not stop():
            released.wait(0.01)
        stopped.set()

    monkeypatch.setattr(stack, "locate_fields", locate)
    source = StackedSource(
        [capture], FS, ntsc=True, cancel_xtalk=False, cancel_xtal=False, cancel_leak=False
    )
    try:
        got = source.read(0, 1000)
        assert got.shape == (1000,)
        assert not stopped.is_set()
    finally:
        source.close()
    assert stopped.wait(5.0)


def test_the_rf_out_scale_takes_an_unsigned_captures_offset_out():
    """--rf-out is s16: an unsigned capture lands centred on zero, not
    clipped above 32767, as the reference writes it."""
    assert stack.rf_out_scale("uint16") == (1.0, -32768.0)
    assert stack.rf_out_scale("uint8") == (256.0, -32768.0)
    assert stack.rf_out_scale("int16") == (1.0, 0.0)
    assert stack.rf_out_scale("float32") == (1.0, 0.0)


def test_the_rf_out_rounds_half_away_from_zero(monkeypatch):
    """The reference rounds the f32 value half away from zero (Rust's
    round); numpy's rint would round an exact half to even."""
    written = {}

    class _File:
        def seek(self, offset):
            written["offset"] = offset

        def write(self, data):
            written["data"] = np.frombuffer(data, dtype="<i2").copy()

        def close(self):
            pass

    monkeypatch.setattr("builtins.open", lambda path, mode: _File())
    out = stack._RfOut("rf.s16", *stack.rf_out_scale("uint16"))
    out.write(3, np.array([32768.5, 32769.5, 32767.5, 70000.0, 0.0], dtype=np.float32))
    assert written["offset"] == 6
    np.testing.assert_array_equal(written["data"], [1, 2, -1, 32767, -32768])


# --------------------------------------------------------------------------
# The compiled kernels against their vectorised references
# --------------------------------------------------------------------------


def _synthetic_reads(rng, count, length):
    """Reads of ``count`` inputs: a common carrier, per-input noise and
    rotation, coverage holes and a dropout, over ``length`` samples."""
    t = np.arange(length, dtype=np.float64)
    carrier = np.exp(2j * np.pi * 0.11 * t) * 1000.0
    reads = []
    for i in range(count):
        noise = rng.standard_normal(length) + 1j * rng.standard_normal(length)
        band = carrier * np.exp(0.05j * i) + 30.0 * noise
        band[500 + 300 * i : 700 + 300 * i] = 30.0 * noise[500 + 300 * i : 700 + 300 * i]
        full = band.real + rng.standard_normal(length) * 5.0
        covered = np.ones(length, dtype=bool)
        covered[100 * (i + 1) : 100 * (i + 1) + 37] = False
        full[~covered] = 0.0
        band[~covered] = 0.0
        reads.append((full, band, covered))
    return reads


@pytest.mark.parametrize("mode", ["adaptive", "fixed"])
def test_the_combine_kernels_match_the_reference(mode):
    """The compiled combination gives the vectorised reference's samples."""
    rng = np.random.default_rng(31)
    # Past three blocks of the kernels, so their edges are crossed.
    reads = _synthetic_reads(rng, 3, 3 * 8192 + 1000)
    args = ([1.0, 0.7, 1.3], [0.05, 0.04, 0.06], mode, 5, 128)
    got = stack._combine(reads, *args)
    want = stack._combine_reference(reads, *args)
    for g, w in zip(got, want):
        np.testing.assert_allclose(g, w, rtol=1e-12, atol=1e-9)


def test_the_read_kernel_matches_the_reference():
    """The compiled read gives the vectorised reference's samples, the
    uncovered positions and the edges of the span included."""
    rng = np.random.default_rng(32)
    raw = rng.standard_normal(6000) * 1000.0
    positions = 3.0 + np.cumsum(rng.uniform(0.9, 1.1, 5000))
    positions[[0, 17, 400]] = np.nan
    positions[-1] = 5999.9
    span = stack._InputSpan(raw=raw, start=10, positions=positions + 10.0)
    sinc = sinc_lut()
    hi = video_band_lut(FS, (2.5e6, 3.5e6))
    parts = (np.ascontiguousarray(hi.real), np.ascontiguousarray(hi.imag))
    got = stack._read_input(span, sinc, parts)
    want = stack._read_input_reference(span, sinc, hi)
    np.testing.assert_array_equal(got[2], want[2])
    np.testing.assert_allclose(got[0], want[0], rtol=1e-12, atol=1e-9)
    np.testing.assert_allclose(got[1], want[1], rtol=1e-12, atol=1e-9)


# --- the cleaned source (--tbc_mode resample) -----------------------------


def _xtalk_capture(gamma, n=65536, fs=40e6):
    """A video carrier whose phase follows the first NTSC audio carrier, with
    both carriers in the RF; and the same without the crosstalk."""
    t = np.arange(n) / fs
    carriers = sum(0.3 * np.cos(2 * np.pi * f * t + 0.3 * (i + 1))
                   for i, f in enumerate(stack.AUDIO_CARRIERS_HZ))
    psi = 0.05 * np.sin(2 * np.pi * 50e3 * t)
    theta = gamma * np.sin(2 * np.pi * stack.AUDIO_CARRIERS_HZ[0] * t + 0.7)
    rf = 8000.0 * (np.cos(2 * np.pi * 6.8e6 * t + psi + theta) + carriers)
    clean = 8000.0 * (np.cos(2 * np.pi * 6.8e6 * t + psi) + carriers)
    return rf, clean


def _reader(samples):
    def read(start, count):
        out = np.zeros(count)
        lo, hi = max(start, 0), min(start + count, samples.size)
        if hi > lo:
            out[lo - start : hi - start] = samples[lo:hi]
        return out
    return read


def test_the_cleaned_source_with_nothing_to_cancel_is_the_capture():
    """Virtual sample s is capture sample s: with every cancellation off the
    stream is the capture itself, to the last bit, and ends where it ends."""
    rng = np.random.default_rng(4)
    raw = np.round(rng.normal(scale=3000.0, size=70000))
    source = stack.CleanedSource(_reader(raw), raw.size, 40e6, ntsc=True,
                                 cancel_xtalk=False, cancel_xtal=False, cancel_leak=False)
    try:
        assert source.length == raw.size
        np.testing.assert_array_equal(source.read(0, raw.size), raw.astype(np.float32))
        np.testing.assert_array_equal(source.read(1234, 100), raw[1234:1334].astype(np.float32))
        assert source.read(raw.size - 10, 50).shape == (10,)
        assert source.read(raw.size, 10).shape == (0,)
    finally:
        source.close()


def test_a_centred_reader_takes_the_offset_out_inside_the_capture_only():
    """Inside the capture the samples lose its DC offset; outside it they read
    zero as before, the centred signal's level, so the corrections see no
    step at the capture's ends."""
    raw = np.arange(10, dtype=np.float64) + 100.0
    reader = stack._CentredReader(_reader(raw), 104.5, raw.size)
    np.testing.assert_array_equal(reader(0, 10), raw - 104.5)
    np.testing.assert_array_equal(reader(-3, 6), [0.0, 0.0, 0.0, -4.5, -3.5, -2.5])
    np.testing.assert_array_equal(reader(8, 4), [3.5, 4.5, 0.0, 0.0])
    assert stack.capture_dc(_reader(raw), raw.size) == pytest.approx(104.5, abs=1e-12)


@pytest.mark.parametrize("dc", [512.0, -16384.0])
def test_the_cleaning_does_not_depend_on_the_captures_dc_offset(dc):
    """The same RF with a DC offset (an unsigned capture's) is cleaned the
    same, the offset kept: the corrections read zero past the chunk and the
    capture, and an offset left in made a step there that moved their fits."""
    rf, _ = _xtalk_capture(0.02, n=200000)
    rf = np.round(rf)
    outs = []
    for offset in (0.0, dc):
        source = stack.CleanedSource(_reader(rf + offset), rf.size, 40e6, ntsc=True,
                                     cancel_xtalk=True, cancel_xtal=False, cancel_leak=True)
        try:
            outs.append(source.read(0, rf.size).astype(np.float64) - offset)
        finally:
            source.close()
    # float32 chunks: a few ulps at the offset's magnitude.
    np.testing.assert_allclose(outs[1], outs[0], rtol=0, atol=0.02)


def test_the_cleaned_source_takes_the_crosstalk_out():
    """The stacked source's crosstalk cancellation, on the capture read as it
    is: most of the phase error the carrier put on the video goes."""
    rf, clean = _xtalk_capture(0.02)
    source = stack.CleanedSource(_reader(rf), rf.size, 40e6, ntsc=True,
                                 cancel_xtalk=True, cancel_xtal=False, cancel_leak=False)
    try:
        out = source.read(0, rf.size).astype(np.float64)
    finally:
        source.close()
    mid = slice(4096, rf.size - 4096)
    assert np.std(out[mid] - clean[mid]) < np.std(rf[mid] - clean[mid]) / 3.0


def test_the_cleaned_source_detects_the_clock_lines_a_quarter_in(monkeypatch):
    """The clock lines are detected where there is picture, a quarter into the
    capture (CLEAN_PROBE_TAIL from its end at most), and subtracted from the
    samples at their own positions."""
    from lddecode import stack_corrections

    seen = {}

    class _Lines:
        has_lines = True

        def clean(self, raw, start):
            # A line whose phase follows the absolute position.
            t = np.arange(start, start + raw.shape[0])
            return raw - 100.0 * np.cos(2 * np.pi * t / 37.0)

    def detect(read_fn, fs, *, ntsc, line_hz, length, start):
        seen.update(start=start, length=length)
        return _Lines()

    monkeypatch.setattr(stack_corrections.CrystalLines, "detect", staticmethod(detect))

    def line(start, count):
        t = np.arange(start, start + count)
        return 100.0 * np.cos(2 * np.pi * t / 37.0)

    # Long enough for a quarter in to be CLEAN_PROBE_TAIL from the end.
    n = 20_000_000
    source = stack.CleanedSource(line, n, 40e6, ntsc=True,
                                 cancel_xtalk=False, cancel_xtal=True, cancel_leak=False)
    try:
        out = source.read(1000, 80000)
    finally:
        source.close()
    assert seen == {"start": n // 4, "length": n}
    assert np.max(np.abs(out)) < 1e-3

    # A short capture is probed from its start (the reference's
    # min(len / 4, len - 2^22)).
    source = stack.CleanedSource(line, 80000, 40e6, ntsc=True,
                                 cancel_xtalk=False, cancel_xtal=True, cancel_leak=False)
    source.close()
    assert seen["start"] == 0
