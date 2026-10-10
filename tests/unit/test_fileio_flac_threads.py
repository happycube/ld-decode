"""Unit tests for decoding a compressed capture on more than one thread.

In a threaded decode a single FLAC decode thread is the bound: at -t 8 the
field dispatcher spent most of its time waiting on it for raw samples.
LoadLDF can hand the FLAC decode to libavcodec's frame threading; this
checks that the request reaches the codec, and that the default stays the
single-threaded decode every other caller had.
"""

from types import SimpleNamespace

import av
import pytest

from lddecode.fileio import LoadLDF, make_loader

pytestmark = [pytest.mark.unit, pytest.mark.format]


class _FakeContainer:
    """Just enough of a PyAV container for _start_decoder: no frames."""

    def __init__(self):
        self.stream = SimpleNamespace(
            thread_type="SLICE", codec_context=SimpleNamespace(thread_count=1)
        )
        self.streams = SimpleNamespace(audio=[self.stream])

    def decode(self, audio):
        return iter(())

    def close(self):
        pass


@pytest.fixture
def fake_av(monkeypatch):
    containers = []

    def container_for(name):
        containers.append(_FakeContainer())
        return containers[-1]

    monkeypatch.setattr(av, "open", container_for)
    return containers


def test_make_loader_passes_the_thread_count_through():
    assert make_loader("capture.ldf").decode_threads == 1
    assert make_loader("capture.ldf", decode_threads=4).decode_threads == 4


def test_frame_threading_is_requested_from_the_codec(fake_av):
    loader = LoadLDF("capture.ldf", decode_threads=4)

    loader._start_decoder(0)
    loader._reader_thread.join(timeout=5)

    stream = fake_av[0].stream
    assert stream.thread_type == "FRAME"
    assert stream.codec_context.thread_count == 4


def test_a_single_thread_leaves_the_codec_alone(fake_av):
    loader = LoadLDF("capture.ldf")

    loader._start_decoder(0)
    loader._reader_thread.join(timeout=5)

    stream = fake_av[0].stream
    assert stream.thread_type == "SLICE"
    assert stream.codec_context.thread_count == 1
