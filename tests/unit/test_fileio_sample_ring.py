"""Unit tests for lddecode.fileio.SampleRing and the LDF reader's use of it.

The ring is the buffer between the FLAC decode thread and the reader that
takes fields out of it.  Its contract is narrow and entirely about cursors:
the producer may never overwrite a byte the reader has not taken or may
still seek back over, the reader gets bytes in stream order, and a backward
seek within the retained history is a cursor move rather than a reseek.
These tests drive it directly, with no PyAV and no decoder.
"""

import threading

import numpy as np
import pytest

from lddecode.fileio import LoadLDF, SampleRing

pytestmark = [pytest.mark.unit]


def take(ring, n):
    out = bytearray(n)
    got = ring.read_into(out)
    return bytes(out[:got])


# --- cursors and capacity ------------------------------------------------


def test_capacity_is_readahead_plus_history():
    ring = SampleRing(readahead=64, history=16)
    assert ring.capacity == 80
    assert (ring.available, ring.writable, ring.rewindable) == (0, 64, 0)


def test_bytes_come_back_in_the_order_they_were_written():
    ring = SampleRing(readahead=64, history=16)
    ring.write(b"abcd")
    ring.write(b"efgh")
    assert take(ring, 6) == b"abcdef"
    assert take(ring, 6) == b"gh"


def test_the_producer_may_not_run_further_ahead_than_the_readahead():
    ring = SampleRing(readahead=8, history=4)
    ring.write(b"12345678")
    assert ring.writable == 0
    with pytest.raises(ValueError):
        ring.write(b"9")
    take(ring, 3)
    assert ring.writable == 3


def test_a_write_that_wraps_the_end_reads_back_whole():
    ring = SampleRing(readahead=8, history=4)   # capacity 12
    ring.write(bytes(range(8)))
    take(ring, 8)                                # cursors now at 8
    ring.write(bytes(range(100, 108)))           # wraps at 12
    assert take(ring, 8) == bytes(range(100, 108))


def test_a_read_that_wraps_the_end_comes_back_whole():
    ring = SampleRing(readahead=10, history=4)   # capacity 14
    ring.write(bytes(range(10)))
    take(ring, 10)
    ring.write(bytes(range(50, 60)))             # occupies 10..13 then 0..5
    assert take(ring, 10) == bytes(range(50, 60))


def test_a_short_ring_is_short_not_wrong():
    ring = SampleRing(readahead=16, history=4)
    ring.write(b"abc")
    assert take(ring, 10) == b"abc"
    assert ring.available == 0


# --- history and rewinding ----------------------------------------------


def test_history_behind_the_read_cursor_stays_readable():
    ring = SampleRing(readahead=16, history=8)
    ring.write(bytes(range(16)))
    take(ring, 16)
    assert ring.rewind(8) == 8
    assert take(ring, 8) == bytes(range(8, 16))


def test_a_rewind_past_the_history_is_short_and_says_so():
    ring = SampleRing(readahead=16, history=8)
    ring.write(bytes(range(16)))
    take(ring, 16)
    # capacity is 24 and nothing is unread, so 16 written bytes are all intact
    assert ring.rewind(20) == 16
    assert ring.rpos == 0


def test_unread_bytes_reduce_what_can_be_rewound_over():
    ring = SampleRing(readahead=16, history=8)   # capacity 24
    ring.write(bytes(range(16)))
    take(ring, 16)
    ring.write(bytes(range(100, 116)))           # 16 unread
    assert ring.rewindable == 24 - 16
    assert ring.rewind(16) == 8


def test_the_promised_history_survives_a_full_readahead():
    """With the producer at its limit the reader can still seek back over
    `history` bytes -- that is what the extra capacity is for."""
    ring = SampleRing(readahead=16, history=8)
    for _ in range(4):
        ring.write(bytes(16))
        take(ring, 16)
        ring.write(bytes(16))                    # producer at the readahead cap
        assert ring.rewindable == 8
        take(ring, 16)


def test_skipping_advances_without_copying_but_keeps_the_history():
    ring = SampleRing(readahead=16, history=8)
    ring.write(bytes(range(16)))
    assert ring.skip(10) == 10
    assert take(ring, 6) == bytes(range(10, 16))
    assert ring.rewind(6) == 6
    assert take(ring, 6) == bytes(range(10, 16))


def test_skipping_past_the_end_stops_at_what_was_written():
    ring = SampleRing(readahead=16, history=8)
    ring.write(b"abcd")
    assert ring.skip(10) == 4
    assert ring.available == 0


# --- the reader's use of it ---------------------------------------------


class FakeLDF(LoadLDF):
    """LoadLDF with the FLAC decoder replaced by a byte generator, so the
    buffering can be exercised without PyAV or a capture file."""

    def __init__(self, data, readahead=256, history=64):
        self.data = data
        self.position = 0
        self.rewind_size = history
        self.seek_threshold = 1 << 30
        self._readahead = readahead
        self._container = None
        self._ring = None
        self._cv = threading.Condition()
        self._eof = False
        self._reader_thread = None
        self._stop_event = None
        self.starts = 0

    def _start_decoder(self, sample):
        self._stop_decoder()
        self.starts += 1
        ring = SampleRing(self._readahead, self.rewind_size)
        stop_event = threading.Event()
        with self._cv:
            self._ring = ring
            self._eof = False
        self._stop_event = stop_event
        self._container = object()
        self.position = sample * 2
        self._reader_thread = threading.Thread(
            target=self._feed, args=(stop_event, ring, sample * 2), daemon=True)
        self._reader_thread.start()

    def _feed(self, stop_event, ring, offset):
        pos = offset
        try:
            while pos < len(self.data):
                chunk = self.data[pos:pos + 8]
                with self._cv:
                    while ring.writable < len(chunk) and not stop_event.is_set():
                        self._cv.wait()
                    if stop_event.is_set():
                        return
                    ring.write(chunk)
                    self._cv.notify_all()
                pos += len(chunk)
        finally:
            with self._cv:
                if self._ring is ring:
                    self._eof = True
                self._cv.notify_all()


@pytest.fixture
def samples():
    return np.arange(4096, dtype="<i2")


@pytest.fixture
def reader(samples):
    r = FakeLDF(samples.tobytes())
    yield r
    r._close()


def test_a_forward_read_returns_the_requested_samples(reader, samples):
    np.testing.assert_array_equal(reader.read(None, 0, 100), samples[:100])
    np.testing.assert_array_equal(reader.read(None, 100, 100), samples[100:200])


def test_a_gap_is_skipped_without_a_reseek(reader, samples):
    """A forward seek shorter than seek_threshold decodes and discards; it
    must not restart the container."""
    reader.read(None, 0, 10)
    starts = reader.starts
    np.testing.assert_array_equal(reader.read(None, 500, 50), samples[500:550])
    assert reader.starts == starts


def test_a_backward_seek_within_the_history_does_not_reseek(reader, samples):
    reader.read(None, 0, 16)
    starts = reader.starts
    np.testing.assert_array_equal(reader.read(None, 8, 8), samples[8:16])
    assert reader.starts == starts


def test_a_backward_seek_past_the_history_reseeks(reader, samples):
    reader.read(None, 0, 16)
    reader.read(None, 1000, 16)          # 1968 samples past the ring
    starts = reader.starts
    np.testing.assert_array_equal(reader.read(None, 4, 8), samples[4:12])
    assert reader.starts == starts + 1


def test_a_read_running_off_the_end_returns_none(reader):
    assert reader.read(None, 4090, 100) is None


def test_a_read_larger_than_the_readahead_is_served(samples):
    """The producer is held to `readahead` bytes ahead of the reader, so a
    read larger than that has to raise the bound rather than deadlock."""
    r = FakeLDF(samples.tobytes(), readahead=256, history=64)
    try:
        np.testing.assert_array_equal(r.read(None, 0, 1000), samples[:1000])
        assert r._readahead >= 2000
    finally:
        r._close()


def test_the_returned_array_is_the_callers_to_write(reader):
    out = reader.read(None, 0, 8)
    out[0] = 999
    assert out[0] == 999
