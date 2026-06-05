"""Tests for NTSC-locked analog audio output (--ntsc_audio_rate).

The flag maps to a negative output frequency, which downscale_audio
interprets as a multiple of the horizontal line frequency. -2.8 must
produce exactly 2.8 audio samples per line (1470 per 525-line NTSC
frame), keeping the audio perfectly aligned to the video with no drift.
"""

import numpy as np

from lddecode.core import _downscale_audio_compute_locs_and_swow, SysParams_NTSC

NTSC_LINE_PERIOD = SysParams_NTSC["line_period"]  # microseconds
NTSC_FRAME_LINES = 525


def _even_lineinfo(linecount, linelen):
    """Evenly spaced line locations (no wow), with a few lines of padding."""
    return np.arange(0, (linecount + 4) * linelen, linelen, dtype=np.double)


def _output_sample_count(freq, linecount=NTSC_FRAME_LINES, linelen=910, scale=32):
    """Run the locs/wow computation and return (n_output_samples, swow)."""
    lineinfo = _even_lineinfo(linecount, linelen)
    _, swow, arange, _ = _downscale_audio_compute_locs_and_swow(
        lineinfo,
        NTSC_LINE_PERIOD,
        linelen,
        linecount,
        0.0,  # timeoffset (ignored for negative freq)
        freq,
        scale,
    )
    # arange carries one extra interpolation tick, so samples = len - 1.
    return len(arange) - 1, swow


def test_ntsc_locked_rate_is_exactly_2_8_samples_per_line():
    """freq=-2.8 yields exactly 1470 samples for a full 525-line frame."""
    n_samples, swow = _output_sample_count(-2.8)

    assert n_samples == 1470  # == 525 * 2.8, integer => no drift
    # Evenly spaced lines means unity wow throughout.
    np.testing.assert_allclose(swow, 1.0, atol=1e-9)


def test_negative_freq_resolves_to_ntsc_locked_hz():
    """-2.8 corresponds to ~44055.944 Hz (2.8 x the NTSC line frequency)."""
    line_freq = 1_000_000 / NTSC_LINE_PERIOD
    assert line_freq * 2.8 == 44055.944055944055


def test_default_44100_does_not_frame_lock():
    """The default 44100 Hz rate is a non-integer 1471.47 samples/frame."""
    n_samples, _ = _output_sample_count(44100)

    # 44100 / (30000/1001) ~= 1471.47, so it cannot equal the locked 1470.
    assert n_samples != 1470
    assert n_samples == 1471
