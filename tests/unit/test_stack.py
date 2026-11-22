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

from dataclasses import dataclass

import numpy as np
import pytest

from lddecode import stack
from lddecode.stack import (
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
    full, _band, _covered = stack._read_input(span, sinc, video_band_lut(FS, (2.5e6, 3.6e6)))
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
    # Past the end of the stream: zeros, but still the samples asked for.
    got = source.read(source.length, 100)
    assert got.shape == (100,)
    assert not got.any()


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
