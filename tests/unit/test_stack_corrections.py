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

from lddecode import stack_corrections, stack_kernels

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
    end: the reader is asked for them there first (the check of the lines
    found reads the capture again afterwards)."""
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

    found = asked[: stack_corrections.XTAL_SEGMENTS]
    # The first stretch starts at the given position, the last one at the end
    # of the capture.
    assert found[0] == start
    assert found[-1] == XN - stack_corrections.XTAL_FFT
    assert found == sorted(found)
    # Nothing is read before the first located line.
    assert min(asked) >= start


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
    192nd, and the drift of that 192nd is followed.  Those in the EFM's own
    band are left: the disc's EFM is a continuous signal there."""
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
    assert min(lines.ks) * lines.f0 > 2.0e6

    cleaned = lines.clean(capture[: 1 << 16], 0)
    for m in (50, 100):
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


def test_the_batched_phasors_are_the_ones_of_each_block(small_xtal):
    """The lines' phasors are measured over all the blocks of a super-block
    at once: the result is the one of each block taken on its own."""
    rng = np.random.default_rng(208)
    raw = rng.normal(size=stack_corrections.XTAL_SUPER)
    lines = stack_corrections.CrystalLines(
        read_fn=_reader(raw),
        fs=XFS,
        f0=stack_corrections.EFM_XTAL_HZ / stack_corrections.XTAL_DIV,
        ks=[1, 2, 3],
        reference=2,
        others=[3.1e6],
        length=stack_corrections.XTAL_SUPER,
    )
    nb = stack_corrections.XTAL_SUPER // stack_corrections.XTAL_BLOCK

    for f in [m * lines.f0 for m in lines.ks] + list(lines.others):
        one_by_one = np.array(
            [lines._at(raw, f, b * stack_corrections.XTAL_BLOCK) for b in range(nb)]
        )
        batched = lines._ats(raw, [f])[0]

        assert batched.shape == (nb,)
        np.testing.assert_allclose(batched, one_by_one, rtol=1e-12, atol=1e-12)

    # The measurement of a whole super-block follows: the crystal's drift
    # comes from the reference line's phase advance from block to block.
    phasors = np.array(
        [
            lines._at(raw, lines.reference * lines.f0, b * stack_corrections.XTAL_BLOCK)
            for b in range(nb)
        ]
    )
    advance = np.diff(np.angle(phasors))
    advance -= TAU * np.round(advance / TAU)
    drift = (
        float(advance.sum())
        / (nb - 1)
        / (TAU * stack_corrections.XTAL_BLOCK / XFS)
        / (lines.reference * lines.f0)
    )

    measured = lines._measure(raw)
    assert measured.f0 == pytest.approx(lines.f0 * (1.0 + drift), rel=1e-12)
    assert len(measured.amps) == len(lines.ks) + len(lines.others)
    for amps in measured.amps:
        assert np.isfinite(amps).all()


def test_the_peak_keeps_the_last_of_the_equal_maxima():
    """The reference keeps the last of the equal maxima of the window.

    The tie-break shows in which bin the peak is read: the reference scans
    the window and keeps the last of the equal maxima.
    """
    p = np.array([1.0, 2.0, 5.0, 5.0, 5.0, 1.0, 1.0])
    k, _off = stack_corrections._peak(p, 3, 3)
    # The window is 0..=5 (the last bin of the spectrum is left out), and the
    # three equal maxima are at 2, 3 and 4: the last one is kept.
    assert k == 4
    # With a single maximum, it is the one found.
    q = np.array([1.0, 2.0, 9.0, 5.0, 5.0, 1.0, 1.0])
    assert stack_corrections._peak(q, 3, 3)[0] == 2


def test_the_parabolic_offset_of_the_first_bin():
    """The reference reads the peak's own bin when it is the first one."""
    p = np.array([4.0, 2.0, 1.0])
    assert stack_corrections._parabolic_offset(p, 0) != 0.0
    # At the last bin there is no bin after it: no offset.
    assert stack_corrections._parabolic_offset(p, 2) == 0.0


def test_the_solver_keeps_the_last_of_the_equal_pivots():
    """The reference keeps the last of the equal maxima of the pivot column.

    Two rows with the same pivot: the reference swaps in the second one.
    """
    a = np.array(
        [
            [2.0, 1.0, 0.0],
            [2.0, 3.0, 1.0],
            [1.0, 0.0, 2.0],
        ]
    )
    b = np.array([4.0, 5.0, 2.0])
    x = stack_corrections._solve_linear(a, b)
    assert x is not None
    np.testing.assert_allclose(a @ x, b, rtol=1e-12, atol=1e-12)


def test_the_chroma_leak_is_taken_out_in_double_precision():
    """The leak is subtracted in double precision and rounded once.

    The reference rounds the result of the subtraction, not the leak itself:
    rounding the leak first would round it twice, and the two differ by an
    ulp on the samples where it shows.
    """
    # Values whose leak is not representable in single precision, so that the
    # two orders of the rounding differ.
    rf = np.array(
        [-0.001501439, -327.75882, -1.0866956, 424171.75, 0.8127859, 716.6634],
        dtype=np.float32,
    )
    leak = np.array(
        [
            -1.575681409082927e-07,
            -0.028335570730240244,
            -0.00012999772692694572,
            79.015626980576,
            -6.935000589315558e-05,
            0.10537719724930929,
        ],
        dtype=np.float64,
    )
    out = rf.copy()

    stack_corrections._subtract_leak(out, leak)

    expected = (rf.astype(np.float64) - leak).astype(np.float32)
    np.testing.assert_array_equal(out, expected)
    # The other order (the leak rounded first) is not the same.
    other = (rf.astype(np.float32) - leak.astype(np.float32)).astype(np.float32)
    assert not np.array_equal(out, other)


def test_the_cleaning_kernel_matches_the_reference(small_xtal):
    """The compiled subtraction gives the vectorised reference's samples,
    from a start that is not on a seed and across a super-block."""
    rng = np.random.default_rng(205)
    capture = _capture(rng, [XLINE_HZ])
    lines = stack_corrections.CrystalLines.detect(
        _reader(capture), XFS, ntsc=True, line_hz=stack_corrections.NTSC_LINE_HZ
    )
    assert lines.has_lines
    start = 777
    span = capture[start : start + (1 << 17)]
    np.testing.assert_allclose(
        lines.clean(span, start), lines.clean_reference(span, start), rtol=0, atol=1e-7
    )


def test_the_narrow_band_kernel_matches_the_reference():
    """The compiled mixing down gives the vectorised reference's narrow band,
    span edges and chunk ends included."""
    rng = np.random.default_rng(206)
    out = rng.standard_normal(70001) * 1000.0
    w = -stack_corrections.TAU * 2.301136e6 / FS
    want = stack_corrections._carrier_narrow_band(out, w, 16, 320, 1024)
    got = np.empty(want.shape[0], dtype=np.complex128)
    stack_kernels.narrow_band_kernel(out, w, 16, 320, 1024, got)
    np.testing.assert_allclose(got, want, rtol=1e-9, atol=1e-9)


def test_the_crosstalk_correction_kernel_matches_the_reference():
    """The compiled correction gives the vectorised reference's, the faded
    edges and both branches of the small-turn series included."""
    rng = np.random.default_rng(207)
    n, dec, taper = 40000, 16, 1024
    narrow = [
        (rng.standard_normal(n // dec + 1) + 1j * rng.standard_normal(n // dec + 1)) * s
        for s in (1.0, 400.0)
    ]
    ws = [-stack_corrections.TAU * f / FS for f in CARRIERS]
    gains = np.array([30000.0 + 2000.0j, -1500.0 + 900.0j])
    band = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) * 3000.0
    t = np.arange(n)
    want = stack_corrections._crosstalk_correction_reference(
        t, narrow, ws, gains, CARRIERS, dec, n, taper, band
    )
    got = np.empty(n, dtype=np.float64)
    stack_kernels.crosstalk_correction_kernel(
        narrow[0], narrow[1], np.asarray(ws), gains, np.asarray(CARRIERS, dtype=np.float64),
        dec, taper, band, got,
    )
    np.testing.assert_allclose(got, want, rtol=1e-9, atol=1e-6)


def test_the_line_phasor_kernel_matches_the_matrix_products(small_xtal):
    """The compiled measure of the lines gives the matrix products'
    phasors, every line on every block."""
    rng = np.random.default_rng(208)
    capture = _capture(rng, [XLINE_HZ])
    lines = stack_corrections.CrystalLines.detect(
        _reader(capture), XFS, ntsc=True, line_hz=stack_corrections.NTSC_LINE_HZ
    )
    raw = capture[: stack_corrections.XTAL_SUPER].astype(np.float64)
    freqs = [XLINE_HZ, 2.0 * XLINE_HZ, 1.234e6]
    got = lines._ats(raw, freqs)
    want = lines._ats_reference(raw, freqs)
    for g, w in zip(got, want):
        np.testing.assert_allclose(g, w, rtol=1e-9, atol=1e-9 * np.abs(w).max())


#: Amplitudes that put each multiple near 6 x the floor at 40 MHz (past the
#: satellites' threshold, short of the ordinary one): a multiple off a bin
#: of the detection FFT loses up to 1.4 dB to its window, so each has its own.
_WEAK_AMPLITUDES = {93: 1.86e-4, 94: 2.6e-4, 95: 1.92e-4, 97: 2.36e-4, 98: 2.94e-4}


def _crystal_capture(rng, strong, weak):
    """The EFM crystal with its multiples ``strong`` well over the floor and
    ``weak`` about 6 times over it."""
    fs = 40e6
    n = 1 << 18
    bin_hz = fs / stack_corrections.XTAL_FFT
    crystal_hz = round(16.9344e6 / bin_hz) * bin_hz
    f0 = crystal_hz / stack_corrections.XTAL_DIV
    t = np.arange(n) / fs
    capture = 0.01 * rng.normal(size=n) + 0.2 * np.cos(TAU * crystal_hz * t)
    for m in strong:
        capture += 0.2 * np.cos(TAU * m * f0 * t)
    for m in weak:
        capture += _WEAK_AMPLITUDES[m] * np.cos(TAU * m * f0 * t)
    return _reader(capture), fs


def test_the_v4300d_clocks_satellites_are_kept_with_it(small_xtal, monkeypatch):
    """The LD-V4300D's master clock is the crystal's 96th multiple; its
    satellites, 88.2 and 176.4 kHz either side, stand only a few times over
    the floor and are kept where the master clock is found."""
    monkeypatch.setattr(stack_corrections, "XTAL_TOP_HZ", 14.5e6)
    read_fn, fs = _crystal_capture(np.random.default_rng(209), [96], [93, 94, 95, 97, 98])
    lines = stack_corrections.CrystalLines.detect(
        read_fn, fs, ntsc=True, line_hz=stack_corrections.NTSC_LINE_HZ
    )
    near = [m for m in lines.ks if 90 <= m <= 100]
    assert near == [94, 95, 96, 97, 98]


def test_without_the_master_clock_weak_multiples_are_left(small_xtal, monkeypatch):
    """The relaxed threshold is the V4300D's alone: without its master
    clock, multiples a few times over the floor are not lines."""
    monkeypatch.setattr(stack_corrections, "XTAL_TOP_HZ", 14.5e6)
    # The same noise and the same weak multiples as with the master clock.
    read_fn, fs = _crystal_capture(np.random.default_rng(209), [72], [93, 94, 95, 97, 98])
    lines = stack_corrections.CrystalLines.detect(
        read_fn, fs, ntsc=True, line_hz=stack_corrections.NTSC_LINE_HZ
    )
    assert not [m for m in lines.ks if 90 <= m <= 100]


# --- the check of the lines found ----------------------------------------

#: A bin of the detection FFT near a frequency, in the small fixture.
def _on_bin(f_hz):
    bin_hz = XFS / (1 << 16)
    return round(f_hz / bin_hz) * bin_hz


def _detect(capture, ntsc=True):
    line_hz = stack_corrections.NTSC_LINE_HZ if ntsc else stack_corrections.PAL_LINE_HZ
    return stack_corrections.CrystalLines.detect(
        _reader(capture), XFS, ntsc=ntsc, line_hz=line_hz, length=capture.shape[0]
    )


#: Long enough for the check's stretch to span several rotations.
XW = 1 << 22


def _disc_capture(rng):
    """A clock at `XLINE_HZ`, and a line the disc carries: its frequency
    follows the spindle's speed, which wanders by about 100 Hz rms below
    30 Hz (made at 1 kHz and held)."""
    import scipy.signal

    t = np.arange(XW) / XFS
    hold = 20000
    slow = scipy.signal.lfilter(*scipy.signal.butter(2, 30 / 500), rng.normal(size=XW // hold + 202))
    slow = 100.0 * slow[200:] / slow[200:].std()
    swing = np.repeat(slow, hold)[:XW]
    disc_hz = _on_bin(6.2e6)
    capture = 0.01 * rng.normal(size=XW) + 0.5 * np.cos(TAU * XLINE_HZ * t)
    capture += 0.5 * np.cos(TAU * disc_hz * t + TAU * np.cumsum(swing) / XFS)
    return capture, disc_hz


@pytest.mark.parametrize("check", [True, False])
def test_a_line_the_disc_carries_is_left_and_a_clock_kept(small_xtal, monkeypatch, check):
    """A line whose frequency follows the disc's speed is as narrow as a
    clock over a short stretch, so it is found; over the long stretches it
    is spread, and only the clock is kept.  Without the long stretches'
    test, both are."""
    if not check:
        monkeypatch.setattr(stack_corrections, "XTAL_SHARP", 0.0)
    capture, disc_hz = _disc_capture(np.random.default_rng(213))

    lines = _detect(capture)

    assert any(abs(f - XLINE_HZ) < 50 for f in lines.others)
    assert any(abs(f - disc_hz) < 1000 for f in lines.others) == (not check)


@pytest.mark.parametrize("bands", [None, ()])
def test_a_line_in_the_efm_band_is_left(small_xtal, monkeypatch, bands):
    """The EFM is a continuous signal of the disc's that the sync does not
    interrupt: a line in its band is left (PAL), and taken without the
    sensitive bands."""
    if bands is not None:
        monkeypatch.setattr(stack_corrections, "PAL_XTAL_SENSITIVE_HZ", bands)
    rng = np.random.default_rng(211)
    t = np.arange(XN) / XFS
    efm_hz = _on_bin(1.5e6)
    capture = 0.01 * rng.normal(size=XN) + 0.5 * np.cos(TAU * efm_hz * t)

    lines = _detect(capture, ntsc=False)

    taken = any(abs(f - efm_hz) < 50 for f in lines.others)
    assert taken == (bands is not None)


def _located_lines(monkeypatch, line_len, n):
    """rf_sync.locate stood in by fields of lines `line_len` apart from the
    start of what it is asked to read."""

    class _Field:
        def __init__(self, lines):
            self.lines = lines

    def locate(read_fn, fs, system, stop=None, length=None):
        positions = np.arange(0.0, n - line_len, line_len)
        for k in range(0, positions.shape[0] - 1, 312):
            yield _Field(positions[k : k + 313])

    from lddecode import rf_sync

    monkeypatch.setattr(rf_sync, "locate", locate)


@pytest.mark.parametrize("judge", [True, False])
def test_a_line_cut_by_the_sync_is_the_videos(small_xtal, monkeypatch, judge):
    """A clock runs through the sync and the blanking; a line the video
    makes is interrupted every line.  Folded on the line's position over the
    located lines, the first is kept and the second left; with the fold's
    verdict turned off, both are kept."""
    # The line comb's neighbours are what the short stretches would reject
    # it on; turned off, the fold is what is tested.
    monkeypatch.setattr(stack_corrections, "_is_comb", lambda *a: False)
    if not judge:
        monkeypatch.setattr(stack_corrections, "XTAL_CUT_SNR", math.inf)
    line_len = XFS / stack_corrections.PAL_LINE_HZ
    _located_lines(monkeypatch, line_len, XN)
    rng = np.random.default_rng(212)
    t = np.arange(XN) / XFS
    video_hz = _on_bin(3.3e6)
    # Off from the start of every line to the end of the back porch.
    on = (np.arange(XN) % line_len) >= 10.5e-6 * XFS
    capture = 0.01 * rng.normal(size=XN) + 0.5 * np.cos(TAU * XLINE_HZ * t)
    capture += 0.5 * on * np.cos(TAU * video_hz * t)

    lines = _detect(capture, ntsc=False)

    assert any(abs(f - XLINE_HZ) < 50 for f in lines.others)
    assert any(abs(f - video_hz) < 50 for f in lines.others) == (not judge)


@pytest.mark.parametrize("with_master", [True, False])
def test_the_v4300d_satellites_go_with_their_master(with_master):
    """The LD-V4300D's satellites are sidebands of one modulated clock, less
    narrow than its master line: they are kept with the master even when
    spread over the long stretches, and left without it."""
    import scipy.signal

    fs, n = 40e6, 1 << 22
    f0 = stack_corrections.EFM_XTAL_HZ / stack_corrections.XTAL_DIV
    rng = np.random.default_rng(214)
    t = np.arange(n) / fs
    hold = 40000
    slow = scipy.signal.lfilter(*scipy.signal.butter(2, 30 / 500), rng.normal(size=n // hold + 202))
    swing = np.repeat(100.0 * slow[200:] / slow[200:].std(), hold)[:n]
    spread = TAU * np.cumsum(swing) / fs
    capture = 0.01 * rng.normal(size=n)
    if with_master:
        capture += 0.5 * np.cos(TAU * 96 * f0 * t)
    for m in (95, 97):
        capture += 0.5 * np.cos(TAU * m * f0 * t + spread)
    ks = [95, 96, 97] if with_master else [95, 97]
    # The detector follows the drift on the strongest line found.
    strongest = 96 if with_master else 95

    kept, _, reference = stack_corrections._check_lines(
        _reader(capture), fs, True, stack_corrections.NTSC_LINE_HZ, n, 0, f0, ks, [], strongest
    )

    assert kept == ([95, 96, 97] if with_master else [])
    assert reference == (96 if with_master else 0)


# --- the disc's own lines (--disc_lines) -----------------------------------

#: The fixture's rate and line length (PAL: 1280 samples a line at 20 MHz).
DFS = 20e6
DLINE = DFS / stack_corrections.PAL_LINE_HZ
DN = 1 << 23


class _Recording:
    """A capture's reader that remembers where it was last asked to read."""

    def __init__(self, samples):
        self.samples = samples
        self.last = 0

    def __call__(self, start, count):
        self.last = int(start)
        start = max(0, int(start))
        return self.samples[start : start + int(count)]


def _mastered_capture(seed, with_clock):
    """A PAL capture whose disc turns unevenly: the disc's time runs about
    1e-4 off the capture's, wandering below 30 Hz.  On the disc: a clock
    leaked at mastering (3.1 MHz, continuous) if asked, and a video line
    (4.4 MHz) that the sync cuts every line.  In the capture: its own clock
    (5.49 MHz).  Returns the reader and the capture position of each line."""
    import scipy.signal

    rng = np.random.default_rng(seed)
    t = np.arange(DN, dtype=np.float64)
    hold = 20000
    slow = scipy.signal.lfilter(*scipy.signal.butter(2, 30 / 500), rng.normal(size=DN // hold + 202))
    speed = 1.0 + 1e-4 * np.repeat(slow[200:] / slow[200:].std(), hold)[:DN]
    disc = np.cumsum(speed) - speed[0]
    lines = np.interp(np.arange(0.0, disc[-1], DLINE), disc, t)
    capture = 0.01 * rng.normal(size=DN) + 0.3 * np.cos(TAU * 5.49e6 * t / DFS)
    if with_clock:
        capture += 0.3 * np.cos(TAU * 3.1e6 * disc / DFS)
    on = (disc % DLINE) >= 10.5e-6 * DFS
    capture += 0.3 * on * np.cos(TAU * 4.4e6 * disc / DFS)
    return _Recording(capture), lines


def _locate_on(monkeypatch, reader, lines):
    """rf_sync.locate stood in by the capture's true lines, from where it is
    asked to read, as field records of 312 lines."""

    class _Field:
        def __init__(self, positions):
            self.lines = positions

    def locate(read_fn, fs, system, stop=None, length=None):
        read_fn(0, 1)
        at = reader.last
        mine = lines[(lines >= at) & (lines < at + (length or DN))] - at
        for k in range(0, mine.shape[0], 312):
            yield _Field(mine[k : k + 313])

    from lddecode import rf_sync

    monkeypatch.setattr(rf_sync, "locate", locate)


@pytest.mark.parametrize("with_clock", [True, False])
def test_a_clock_on_the_disc_is_found_and_nothing_else(monkeypatch, with_clock):
    """A clock leaked on the disc follows the disc's speed: narrow on the
    disc's timeline, spread in the capture's, and continuous through the
    sync.  It is found; the capture's own clock (narrow in both) and the
    video's line (cut by the sync, a comb) are not, and without the clock
    nothing is."""
    reader, lines = _mastered_capture(215, with_clock)
    _locate_on(monkeypatch, reader, lines)

    found = stack_corrections.find_disc_lines(
        reader, DFS, ntsc=False, line_hz=stack_corrections.PAL_LINE_HZ, length=DN
    )

    if with_clock:
        assert len(found) == 1
        assert found[0] == pytest.approx(3.1e6, abs=5.0)
    else:
        assert found == []


def test_the_discs_line_is_taken_out_of_a_chunk():
    """subtract_disc_lines: a line steady on the stream's timeline is taken
    out of a chunk, its phase referenced to the stream's first sample, and
    the rest of the chunk is left."""
    rng = np.random.default_rng(216)
    n, start = 1 << 18, 5 * (1 << 18)
    index = start + np.arange(n)
    rest = rng.normal(size=n)
    chunk = rest + 0.5 * np.cos(TAU * 3.1e6 * index / DFS + 0.7)

    out = stack_corrections.subtract_disc_lines(chunk, start, [3.1e6], DFS)

    assert _tone_amplitude(out, DFS, 3.1e6, 0, n) < 0.5 / 300
    assert np.std(out - rest) < 0.01
    np.testing.assert_array_equal(
        stack_corrections.subtract_disc_lines(chunk, start, [], DFS), chunk)


def test_without_the_comb_test_the_fold_still_leaves_the_video(monkeypatch, caplog):
    """The video's line is a comb, which leaves it first; with that test
    turned off it is a candidate, and the fold, which finds it cut by the
    sync, still leaves it."""
    import logging

    monkeypatch.setattr(stack_corrections, "DISC_COMB_DB", math.inf)
    reader, lines = _mastered_capture(215, True)
    _locate_on(monkeypatch, reader, lines)

    with caplog.at_level(logging.INFO, logger="lddecode.stack_corrections"):
        found = stack_corrections.find_disc_lines(
            reader, DFS, ntsc=False, line_hz=stack_corrections.PAL_LINE_HZ, length=DN
        )

    assert [round(f / 1e3) for f in found] == [3100]
    # The video's comb teeth were candidates, and the fold left every one.
    counts = [r.getMessage() for r in caplog.records if "candidate(s)" in r.getMessage()]
    assert counts and int(counts[-1].split("disc lines: ")[1].split(" ")[0]) > 1
    assert "1 shown continuous" in counts[-1]
