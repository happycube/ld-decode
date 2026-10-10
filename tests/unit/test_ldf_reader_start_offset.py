"""Unit tests for ld-ldf-reader-py reaching its requested start offset.

When container.seek() failed the reader zeroed start_offset, which also turned
off the pts check that skips frames before the requested sample.  On a pipe a
failed seek has already consumed data, so the output began at whatever sample
the stream had reached -- neither the start nor the requested offset -- and the
reader still reported success.
"""

import io
from fractions import Fraction
from types import SimpleNamespace

import numpy as np
import pytest

from lddecode import ldf_reader

pytestmark = [pytest.mark.unit, pytest.mark.format]

RATE = 40000
FRAME = 4096


class _PassThroughResampler:
    def __init__(self, **_kwargs):
        pass

    def resample(self, frame):
        return [frame]


def _frame(first_sample, pts=True):
    # Each sample holds its own index (mod 2**15) so the output shows where it began
    data = (np.arange(first_sample, first_sample + FRAME) % 32768).astype("<i2")
    return SimpleNamespace(
        pts=first_sample if pts else None,
        samples=FRAME,
        planes=[data.tobytes()],
    )


def _reader(start_offset, frames, monkeypatch):
    monkeypatch.setattr(ldf_reader.av.audio.resampler, "AudioResampler", _PassThroughResampler)
    out = io.BytesIO()
    monkeypatch.setattr(ldf_reader.sys, "stdout", SimpleNamespace(buffer=out))
    reader = ldf_reader.LdfReader("unused.ldf", start_offset=start_offset, debug=False)
    reader.audio_stream = SimpleNamespace(time_base=Fraction(1, RATE), sample_rate=RATE)
    reader.container = SimpleNamespace(decode=lambda audio: iter(frames))
    return reader, out


def test_output_starts_at_the_requested_sample(monkeypatch):
    frames = [_frame(n * FRAME) for n in range(4)]
    reader, out = _reader(5000, frames, monkeypatch)

    assert reader._decode_packets()

    samples = np.frombuffer(out.getvalue(), dtype="<i2")
    assert samples[0] == 5000
    assert len(samples) == 4 * FRAME - 5000


def test_stream_already_past_the_start_is_an_error(monkeypatch):
    # What a failed seek on a pipe leaves behind: decoding resumes mid-stream
    frames = [_frame(n * FRAME) for n in range(30, 33)]
    reader, out = _reader(5000, frames, monkeypatch)

    assert not reader._decode_packets()
    assert out.getvalue() == b""


def test_frames_without_pts_count_skipped_samples(monkeypatch):
    frames = [_frame(n * FRAME, pts=False) for n in range(4)]
    reader, out = _reader(5000, frames, monkeypatch)

    assert reader._decode_packets()

    samples = np.frombuffer(out.getvalue(), dtype="<i2")
    assert samples[0] == 5000
