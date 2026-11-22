"""Unit tests for the stacked-RF signal corrections.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

`lddecode.stack_corrections` holds three corrections the stacking pipeline
applies to the RF it reads:

- `cancel_crosstalk` takes out of the demodulated video the part that
  follows the two analog audio carriers (they leak into the video carrier's
  phase on the disc).
- `cancel_chroma_leak` takes out the composite chroma that leaks into the
  RF baseband around the colour subcarrier.
- `CrystalLines` finds the narrow clock lines a capture carries and
  subtracts them from the samples as they are read.

Every signal here is synthetic and every generator is seeded; no test
touches the filesystem, the network, a subprocess or the clock.
"""

import math

import numpy as np
import pytest

from lddecode import stack_corrections

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

TAU = 2.0 * math.pi


# --- helpers -------------------------------------------------------------


def _band_noise(rng, n, fs, lo_hz, hi_hz):
    """White noise band-limited to `lo_hz`-`hi_hz`, with unit RMS."""
    spec = rng.normal(size=n // 2 + 1) + 1j * rng.normal(size=n // 2 + 1)
    freq = np.fft.rfftfreq(n, 1.0 / fs)
    spec[(freq < lo_hz) | (freq > hi_hz)] = 0.0
    x = np.fft.irfft(spec, n)
    return x / np.std(x)


def _tone_amplitude(x, fs, f_hz, start, count):
    """The amplitude of a tone at `f_hz` over `count` samples from `start`."""
    seg = np.asarray(x[start : start + count], dtype=np.float64)
    w = TAU * f_hz / fs
    return 2.0 * abs(np.dot(seg, np.exp(-1j * w * np.arange(seg.shape[0])))) / seg.shape[0]


def _correlation(a, b):
    """The correlation of two signals, with their means removed."""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    a = a - a.mean()
    b = b - b.mean()
    return float(np.dot(a, b) / np.sqrt(np.dot(a, a) * np.dot(b, b)))


# --- cancel_crosstalk ----------------------------------------------------

#: The NTSC analog audio carriers (Hz).
CARRIERS = (2.301136e6, 2.8125e6)
#: The NTSC video band starts above this (Hz); the correction is kept there.
KEEP = (3.0e6, 3.6e6)
#: The sample rate (Hz) and the chunk's length (samples).
FS = 40e6
N = 65536
#: The video carrier's frequency (Hz): its crosstalk sidebands (the carrier
#: plus and minus the audio carriers) then all sit above the keep band.
F_VIDEO = 6.8e6


def _crosstalk_chunk(gamma_rad):
    """A chunk with a video carrier whose phase follows an audio carrier.

    `gamma_rad` is the amplitude of the phase error the crosstalk puts on
    the video carrier (radians); the picture's own FM (a slow tone) is
    there too, so the fit has something it must not follow.
    """
    t = np.arange(N) / FS
    theta = gamma_rad * np.sin(TAU * CARRIERS[0] * t + 0.7)
    psi = 0.05 * np.sin(TAU * 50e3 * t)
    video_band = np.exp(1j * (TAU * F_VIDEO * t + psi + theta))
    carriers = sum(0.3 * np.cos(TAU * f * t + 0.3 * (i + 1)) for i, f in enumerate(CARRIERS))
    clean = np.cos(TAU * F_VIDEO * t + psi) + carriers
    rf = np.cos(TAU * F_VIDEO * t + psi + theta) + carriers
    return rf, clean, video_band


def test_crosstalk_cancellation_reduces_the_phase_error():
    """A chunk whose video phase follows an audio carrier comes back with
    most of that error taken out."""
    rf, clean, video_band = _crosstalk_chunk(0.02)

    out = stack_corrections.cancel_crosstalk(rf, video_band, FS, CARRIERS, KEEP)

    before = np.std(rf - clean)
    after = np.std(out - clean)
    assert before > 1e-3
    assert after < before / 3.0


def test_crosstalk_cancellation_leaves_a_clean_chunk_alone():
    """Without crosstalk there is nothing to take out: the picture's own
    frequency does not follow the carriers, so no gain is fitted."""
    rf, clean, video_band = _crosstalk_chunk(0.0)

    out = stack_corrections.cancel_crosstalk(rf, video_band, FS, CARRIERS, KEEP)

    assert np.std(out - rf) < 1e-6 * np.std(rf)


def test_crosstalk_correction_is_kept_above_the_keep_band_only():
    """The correction is a high-pass: it must not move what lands on the
    audio carriers (or the EFM) below the keep band."""
    rf, clean, video_band = _crosstalk_chunk(0.02)

    out = stack_corrections.cancel_crosstalk(rf, video_band, FS, CARRIERS, KEEP)

    correction = out - rf
    for f in CARRIERS:
        # at least 60 dB below the correction itself
        assert _tone_amplitude(correction, FS, f, 4096, N - 8192) < 1e-3 * np.std(correction)


def test_crosstalk_cancellation_does_not_change_its_inputs():
    rf, clean, video_band = _crosstalk_chunk(0.02)
    rf_copy = rf.copy()
    band_copy = video_band.copy()

    out = stack_corrections.cancel_crosstalk(rf, video_band, FS, CARRIERS, KEEP)

    np.testing.assert_array_equal(rf, rf_copy)
    np.testing.assert_array_equal(video_band, band_copy)
    assert out is not rf


# --- cancel_chroma_leak --------------------------------------------------

#: The NTSC chroma band: the rising and falling raised-cosine edges (Hz).
LEAK_BAND = ((2.9e6, 3.1e6), (4.1e6, 4.3e6))
#: The chroma's own band, inside the pass band (Hz).
CHROMA_LO, CHROMA_HI = 3.15e6, 4.05e6


def _chroma_chunk(rng, leak_taps=None, noise_rms=0.02, leak_scale=1.0):
    """A chunk with a known chroma leak in the RF baseband.

    The video band's instantaneous frequency carries a band-limited noise
    (the chroma); the RF's same band carries that chroma delayed by the
    fit's lags, which is the leak the cancellation has to find.

    Returns the RF, the leak and the video band.
    """
    t = np.arange(N) / FS
    chroma = _band_noise(rng, N, FS, CHROMA_LO, CHROMA_HI) * 1.0e5
    chroma -= chroma.mean()
    # The video band: its instantaneous frequency is the chroma, so the
    # phase is the chroma's integral.
    phase = TAU * 8.0e6 * t + TAU * np.cumsum(chroma) / FS
    video_band = np.exp(1j * phase)

    half = stack_corrections.LEAK_TAPS // 2 * stack_corrections.LEAK_STEP
    lags = np.arange(stack_corrections.LEAK_TAPS) * stack_corrections.LEAK_STEP - half
    if leak_taps is None:
        leak_taps = {6: 1.0, 5: 0.3, 7: -0.2}
    leak = np.zeros(N)
    for k, gain in leak_taps.items():
        leak += gain * np.roll(chroma, -lags[k])
    leak *= leak_scale
    rf = leak + rng.normal(size=N) * noise_rms
    return rf, leak, video_band


def test_chroma_leak_is_taken_out_of_the_rf():
    """A chunk with a known chroma leak comes back with the leak gone."""
    rng = np.random.default_rng(101)
    rf, leak, video_band = _chroma_chunk(rng)

    out = stack_corrections.cancel_chroma_leak(rf, video_band, FS, LEAK_BAND)

    mid = slice(2000, N - 2000)
    assert _correlation(rf[mid], leak[mid]) > 0.99
    assert abs(_correlation(out[mid], leak[mid])) < 0.05
    # what is left of the RF is the noise it had under the leak
    assert np.std(out[mid] - (rf[mid] - leak[mid])) < np.std(leak[mid]) / 10.0


def test_chroma_leak_leaves_a_chunk_without_leak_unchanged():
    """A chunk whose RF band explains less than the minimum share of the
    chroma is left exactly as it was."""
    rng = np.random.default_rng(102)
    rf, leak, video_band = _chroma_chunk(rng, leak_taps={}, noise_rms=1.0)

    out = stack_corrections.cancel_chroma_leak(rf, video_band, FS, LEAK_BAND)

    np.testing.assert_array_equal(out, rf)


def test_chroma_leak_below_the_minimum_share_is_left_unchanged():
    """A little leak, swamped by the RF's own noise in the band, is not
    worth correcting: the share of the band it explains is under 5 %."""
    rng = np.random.default_rng(103)
    rf, leak, video_band = _chroma_chunk(rng, leak_taps={6: 1.0}, noise_rms=1.0e5, leak_scale=0.01)

    out = stack_corrections.cancel_chroma_leak(rf, video_band, FS, LEAK_BAND)

    np.testing.assert_array_equal(out, rf)


def test_ntsc_chroma_leak_band_edges_are_the_specified_ones():
    """The NTSC leak band: the chroma is 3.58 MHz +- 0.6, so the pass band
    runs from 3.1 to 4.1 MHz."""
    assert stack_corrections.LEAK_BAND_HZ == ((2.9e6, 3.1e6), (4.1e6, 4.3e6))
    rise, fall = stack_corrections.LEAK_BAND_HZ
    assert (rise[1], fall[0]) == (3.1e6, 4.1e6)
    assert (rise[0] + rise[1]) / 2 == pytest.approx(3.0e6)
    assert (fall[0] + fall[1]) / 2 == pytest.approx(4.2e6)


# --- CrystalLines --------------------------------------------------------

#: The sample rate (Hz) and the capture's length (samples).
XFS = 20e6
XN = 1 << 20
#: A clock line at a frequency that is a bin of both the detection FFT and
#: the block DFT, so its amplitude is measured exactly.
XLINE_HZ = 18000 * (XFS / (1 << 16))


@pytest.fixture
def small_xtal(monkeypatch):
    """The detection and measurement constants, small enough for a test."""
    monkeypatch.setattr(stack_corrections, "XTAL_FFT", 1 << 16)
    monkeypatch.setattr(stack_corrections, "XTAL_SUPER", 1 << 18)
    monkeypatch.setattr(stack_corrections, "XTAL_BLOCK", 1 << 14)
    monkeypatch.setattr(stack_corrections, "XTAL_SEED", 256)


def _reader(samples):
    """A reader over an array of samples, as the stacking pipeline's is."""

    def read_fn(start, count):
        start = max(0, start)
        if start >= samples.shape[0]:
            return np.zeros(0, dtype=np.float32)
        return samples[start : start + count]

    return read_fn


def _capture(rng, lines_hz, amplitude=0.5):
    """A capture with a line at each of `lines_hz`, and noise."""
    t = np.arange(XN) / XFS
    x = 0.01 * rng.normal(size=XN)
    for f in lines_hz:
        x += amplitude * np.cos(TAU * f * t)
    return x


def test_a_clock_line_is_found_and_removed(small_xtal):
    """A capture carrying a clock line has it found, and the line is taken
    out of the samples."""
    rng = np.random.default_rng(201)
    capture = _capture(rng, [XLINE_HZ])

    lines = stack_corrections.CrystalLines.detect(
        _reader(capture), XFS, ntsc=True, line_hz=stack_corrections.NTSC_LINE_HZ
    )

    assert lines.has_lines
    assert len(lines.others) == 1
    assert lines.others[0] == pytest.approx(XLINE_HZ, rel=1e-4)

    cleaned = lines.clean(capture[: 1 << 16], 0)
    before = _tone_amplitude(capture, XFS, XLINE_HZ, 1 << 15, 1 << 14)
    after = _tone_amplitude(cleaned, XFS, XLINE_HZ, 1 << 15, 1 << 14)
    assert 20 * math.log10(before / after) > 20.0


def test_the_detection_starts_where_the_caller_says(small_xtal):
    """The stretches are spread from the capture's first located line to its
    end: the reader is asked for them there, and nowhere else."""
    rng = np.random.default_rng(206)
    capture = _capture(rng, [XLINE_HZ])
    asked: list[int] = []

    def reader(start, count):
        asked.append(int(start))
        return _reader(capture)(start, count)

    start = XN // 4
    stack_corrections.CrystalLines.detect(
        reader,
        XFS,
        ntsc=True,
        line_hz=stack_corrections.NTSC_LINE_HZ,
        length=XN,
        start=start,
    )

    assert len(asked) == stack_corrections.XTAL_SEGMENTS
    # The first stretch starts at the given position, the last one at the end
    # of the capture.
    assert asked[0] == start
    assert asked[-1] == XN - stack_corrections.XTAL_FFT
    assert asked == sorted(asked)


def test_the_detection_reads_no_further_than_the_captures_length(small_xtal):
    """A reader that pads past the end of the capture needs the length.

    Without it the capture's length is probed, and a reader that never
    reports the end of the capture sends the stretches past it.
    """
    rng = np.random.default_rng(207)
    capture = _capture(rng, [XLINE_HZ])

    def padding_reader(start, count):
        # Always the whole count: the end of the capture is not reported.
        out = np.zeros(count, dtype=np.float64)
        lo = max(0, start)
        hi = min(capture.shape[0], start + count)
        if hi > lo:
            out[lo - start : hi - start] = capture[lo:hi]
        return out

    lines = stack_corrections.CrystalLines.detect(
        padding_reader,
        XFS,
        ntsc=True,
        line_hz=stack_corrections.NTSC_LINE_HZ,
        length=capture.shape[0],
    )

    assert lines.has_lines
    assert len(lines.others) == 1
    assert lines.others[0] == pytest.approx(XLINE_HZ, rel=1e-4)


def test_a_comb_at_the_line_frequency_is_not_taken_for_a_clock_line(small_xtal):
    """A still picture's RF is a comb of lines a line frequency apart; it
    must not be taken for a clock line and subtracted."""
    rng = np.random.default_rng(202)
    line_hz = stack_corrections.NTSC_LINE_HZ
    comb = _capture(rng, [XLINE_HZ + k * line_hz for k in (-2, -1, 0, 1, 2)])

    lines = stack_corrections.CrystalLines.detect(_reader(comb), XFS, ntsc=True, line_hz=line_hz)

    assert not lines.has_lines
    cleaned = lines.clean(comb[: 1 << 16], 0)
    np.testing.assert_array_equal(cleaned, comb[: 1 << 16])


def test_cleaning_does_not_depend_on_the_chunking(small_xtal):
    """A sample gets the same value whatever read it is in: the phasor is
    exact at every seed of the super-block."""
    rng = np.random.default_rng(203)
    capture = _capture(rng, [XLINE_HZ])
    lines = stack_corrections.CrystalLines.detect(
        _reader(capture), XFS, ntsc=True, line_hz=stack_corrections.NTSC_LINE_HZ
    )

    small = lines.clean(capture[: 1 << 16], 0)
    large = lines.clean(capture[: 1 << 18], 0)

    np.testing.assert_array_equal(small, large[: 1 << 16])


def test_the_efm_decoder_crystal_is_found_and_its_lines_removed(small_xtal, monkeypatch):
    """The player's EFM decoder crystal: its lines are the multiples of its
    192nd, and the drift of that 192nd is followed."""
    monkeypatch.setattr(stack_corrections, "XTAL_TOP_HZ", 14.5e6)
    monkeypatch.setattr(stack_corrections, "XTAL_SUPER", 1 << 16)
    rng = np.random.default_rng(204)
    fs = 40e6
    n = 1 << 18
    # The crystal itself, on a bin of the detection FFT.
    bin_hz = fs / stack_corrections.XTAL_FFT
    crystal_hz = round(16.9344e6 / bin_hz) * bin_hz
    f0 = crystal_hz / stack_corrections.XTAL_DIV
    t = np.arange(n) / fs
    capture = 0.01 * rng.normal(size=n)
    for m in range(1, 193):
        capture += 0.2 * np.cos(TAU * m * f0 * t)

    def read_fn(start, count):
        start = max(0, start)
        if start >= n:
            return np.zeros(0, dtype=np.float32)
        return capture[start : start + count]

    lines = stack_corrections.CrystalLines.detect(
        read_fn, fs, ntsc=True, line_hz=stack_corrections.NTSC_LINE_HZ
    )

    assert lines.f0 == pytest.approx(f0, rel=1e-3)
    assert len(lines.ks) > 100
    assert not lines.others

    cleaned = lines.clean(capture[: 1 << 16], 0)
    for m in (10, 100):
        f = m * f0
        before = _tone_amplitude(capture, fs, f, 1 << 15, 1 << 14)
        after = _tone_amplitude(cleaned, fs, f, 1 << 15, 1 << 14)
        assert 20 * math.log10(before / after) > 20.0


def test_a_capture_without_lines_is_left_alone(small_xtal):
    """Noise alone has no line to find, so nothing is subtracted."""
    rng = np.random.default_rng(205)
    capture = 0.01 * rng.normal(size=XN)

    lines = stack_corrections.CrystalLines.detect(
        _reader(capture), XFS, ntsc=True, line_hz=stack_corrections.NTSC_LINE_HZ
    )

    assert not lines.has_lines
    cleaned = lines.clean(capture[: 1 << 16], 0)
    np.testing.assert_array_equal(cleaned, capture[: 1 << 16])
