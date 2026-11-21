"""Tests for seeking in .ldf (FLAC) captures with LoadLDF.

An .ldf stores the 40 MHz RF samples as a 40 kHz FLAC stream, one stream
sample per RF sample.  LoadLDF's seek scaled RF samples to stream units by
1/1000, as if the stream ran 1000x slower than the RF, and passed the result
to container.seek() without a stream, so it was read as AV_TIME_BASE
microseconds.  The seek therefore landed at the start of the file for any
target below ~2e9 samples (correct data, but the reader decoded and threw
away everything before the target: minutes per seek on a real capture), and
far before the target beyond that, where the post-seek realignment (scaled
the other way, x1000) then returned the wrong samples.
"""

import itertools

import numpy as np
import pytest

av = pytest.importorskip("av")

from lddecode.utils import LoadLDF

RATE = 40000
# Long enough that a far read restarts the decoder with a container seek
# (LoadLDF.seek_threshold is 40 MiB, i.e. 20 Mi samples).
NSAMPLES = 30_000_000


def _ramp(start, count):
    return (np.arange(start, start + count) % 65536 - 32768).astype("<i2")


@pytest.fixture(scope="module")
def ramp_ldf(tmp_path_factory):
    """A mono s16 FLAC whose sample n holds (n % 65536) - 32768."""
    path = tmp_path_factory.mktemp("ldf") / "ramp.ldf"
    with av.open(str(path), "w", format="flac") as container:
        stream = container.add_stream("flac", rate=RATE, layout="mono")
        stream.format = "s16"
        step = 1 << 20
        for start in range(0, NSAMPLES, step):
            count = min(step, NSAMPLES - start)
            frame = av.AudioFrame.from_ndarray(
                _ramp(start, count).reshape(1, -1), format="s16", layout="mono"
            )
            frame.sample_rate = RATE
            frame.pts = start
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return str(path)


class _LandingLoader(LoadLDF):
    """LoadLDF that records where each (re)started decoder resumed."""

    def __init__(self, filename):
        super().__init__(filename)
        self.landings = []

    def _reader_loop(self, stop_event, buf, target_sample):
        first = next(self._decode_iter)
        self.landings.append(
            (target_sample, round(float(first.pts * self._stream.time_base) * RATE))
        )
        self._decode_iter = itertools.chain([first], self._decode_iter)
        super()._reader_loop(stop_event, buf, target_sample)


@pytest.mark.parametrize("target", [25_000_000, 29_000_123])
def test_far_read_returns_the_right_samples(ramp_ldf, target):
    loader = LoadLDF(ramp_ldf)
    try:
        assert np.array_equal(loader.read(None, 1000, 4096), _ramp(1000, 4096))
        assert np.array_equal(loader.read(None, target, 4096), _ramp(target, 4096))
    finally:
        loader._close()


def test_far_read_seeks_near_the_target(ramp_ldf):
    """The container seek must land within a second of audio before the target,
    not at the start of the file."""
    target = 25_000_000
    loader = _LandingLoader(ramp_ldf)
    try:
        loader.read(None, 0, 4096)
        assert np.array_equal(loader.read(None, target, 4096), _ramp(target, 4096))
    finally:
        loader._close()

    (seek_target, landed) = loader.landings[-1]
    assert seek_target == target
    assert target - 2 * RATE <= landed <= target
