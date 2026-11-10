"""Unit tests for the sync probe's raw reads taking the reader lock.

All raw reads in a threaded decode go through the block cache's single
reader lock (AGENTS.md 5.3.3): demod_read takes it, and the field-job
dispatcher reads its spans under it.  LDdecode.read_sync, behind the public
has_sync probe, read its blocks without it.  Its only caller today forces a
serial decode, so nothing raced, but the probe is public.  Stub objects
stand in for the decoder.
"""

import threading
import types

import numpy as np
import pytest

from lddecode.decoder import LDdecode

pytestmark = [pytest.mark.unit, pytest.mark.parallel]

BLOCKSIZE = 1000


class RecordingLock:
    """A lock that notes whether it was held at each read."""

    def __init__(self):
        self._lock = threading.Lock()
        self.held = False

    def __enter__(self):
        self._lock.acquire()
        self.held = True

    def __exit__(self, *exc):
        self.held = False
        self._lock.release()


def stub(block_cache):
    held_at_read = []
    s = types.SimpleNamespace(
        demod_blocksize=BLOCKSIZE,
        block_cache=block_cache,
        rf=types.SimpleNamespace(
            demodblock_sync=lambda data, cut: np.zeros(10)),
    )

    def read_raw_block(b):
        held_at_read.append(block_cache.read_lock.held if block_cache else None)
        return np.zeros(BLOCKSIZE, dtype=np.int16)

    s._read_raw_block = read_raw_block
    return s, held_at_read


def test_every_raw_read_holds_the_block_caches_reader_lock():
    cache = types.SimpleNamespace(read_lock=RecordingLock())
    s, held_at_read = stub(cache)

    LDdecode.read_sync(s, 0, 3 * BLOCKSIZE)

    assert held_at_read and all(held_at_read)
    assert not cache.read_lock.held


def test_a_serial_decode_reads_without_a_lock():
    s, held_at_read = stub(None)

    result = LDdecode.read_sync(s, 0, 3 * BLOCKSIZE)

    assert len(held_at_read) == 4
    assert result["startloc"] == 0
