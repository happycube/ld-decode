"""Unit tests for telling a failed compressed input from its end.

A FLAC decode error in LoadLDF, or ffmpeg dying under LoadFFmpeg, ends the
samples the same way the end of the file does: reads past it return None,
which every caller takes as end of input.  ld-decode then said "Completed"
and exited 0 over a silently truncated output.  Both loaders now record how
their input stopped in `failed`, None only for a clean end, so the entry
points can report the output as incomplete.  PyAV and the ffmpeg process are
replaced with in-memory stand-ins.
"""

import io
from types import SimpleNamespace

import av
import pytest

from lddecode.fileio import LoadFFmpeg, LoadLDF

pytestmark = [pytest.mark.unit, pytest.mark.format]


class _CorruptFrame(Exception):
    """What the FLAC decoder raises on a frame it cannot decode."""


class _FakeContainer:
    """A PyAV container whose decode yields nothing, or raises at once."""

    def __init__(self, error=None):
        self.error = error
        stream = SimpleNamespace(thread_type="SLICE",
                                 codec_context=SimpleNamespace(thread_count=1))
        self.streams = SimpleNamespace(audio=[stream])

    def decode(self, audio):
        # Errors come out of the iteration, on the loader's decode thread
        def frames():
            if self.error is not None:
                raise self.error
            yield from ()
        return frames()

    def close(self):
        pass


def _ldf_loader(monkeypatch, error=None):
    monkeypatch.setattr(av, "open", lambda name: _FakeContainer(error))
    return LoadLDF("capture.ldf")


def test_a_clean_end_of_a_flac_capture_is_not_a_failure(monkeypatch, caplog):
    loader = _ldf_loader(monkeypatch)

    assert loader.read(None, 0, 1024) is None
    assert loader.failed is None


def test_a_flac_decode_error_is_recorded_as_a_failure(monkeypatch, caplog):
    loader = _ldf_loader(monkeypatch, _CorruptFrame("bad frame"))

    assert loader.read(None, 0, 1024) is None
    assert "FLAC decode failed" in loader.failed
    assert "bad frame" in loader.failed


class _FakeFFmpeg:
    """An ffmpeg process that has written `output` and exits with `code`."""

    def __init__(self, output, code):
        self.stdout = io.BytesIO(output)
        self.code = code

    def wait(self, timeout=None):
        return self.code

    def kill(self):
        pass


def _ffmpeg_loader(samples, code):
    loader = LoadFFmpeg()
    loader.ffmpeg = _FakeFFmpeg(b"\x01\x00" * samples, code)
    return loader


def test_ffmpeg_reaching_the_end_cleanly_is_not_a_failure():
    loader = _ffmpeg_loader(100, 0)

    assert loader.read(None, 0, 100) is not None
    assert loader.read(None, 100, 100) is None
    assert loader.failed is None


def test_ffmpeg_dying_partway_is_recorded_as_a_failure():
    loader = _ffmpeg_loader(100, 1)

    assert loader.read(None, 0, 200) is None
    assert loader.failed == "ffmpeg exited with status 1"


def test_a_full_read_does_not_wait_for_ffmpeg():
    loader = _ffmpeg_loader(100, None)
    waits = []
    loader.ffmpeg.wait = lambda timeout=None: waits.append(timeout)

    assert loader.read(None, 0, 100) is not None
    assert waits == []
    assert loader.failed is None
