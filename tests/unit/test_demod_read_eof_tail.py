"""Tests for the last field of an input whose read window overhangs EOF.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

decodefield() reads a whole readlen plus two blocks from the field's start,
which runs well past the field itself.  Near the end of the input that
window can cross EOF while the field and the vertical sync after it are
still all in the file; demod_read() used to return None for any window that
crossed EOF, so every decode lost its last field (and with it the last CVBS
frame, whose first field was left unpaired).

demod_read() now hands back the blocks before EOF, flagged truncated, when
they can hold a field, and decodefield() takes a field from such a window
only if it is valid: Field.compute_linelocs rejects a field whose pulses do
not reach through the following vertical sync, and pulses exist only where
there is data.  An invalid field in a truncated window is end of input, not
a bad field to skip past.

Stub objects stand in for `self` (see test_decodefield_errors.py), reading
an in-memory "file" through freader.
"""

import threading
import types

import numpy as np
import pytest

from lddecode.core import LDdecode

pytestmark = [pytest.mark.unit, pytest.mark.decode]

BLOCKLEN = 64
CUT = 8
BLOCKSIZE = BLOCKLEN - 2 * CUT      # demod_blocksize: what a block keeps
LINELEN = 10
OUTPUT_LINES = 8                    # a field needs 80 samples: two blocks


def _demod(rawinput, mtf_level):
    """A stand-in demodulator: the block's kept samples, as video."""
    return {"video": rawinput[CUT:-CUT].astype(np.float64)}


def _stub(file_len, block_cache=None):
    data = np.arange(file_len, dtype=np.int16)

    def freader(infile, start, length):
        if start >= file_len:
            return None
        return data[start:start + length]

    stub = types.SimpleNamespace(
        rf=types.SimpleNamespace(blocklen=BLOCKLEN, blockcut=CUT,
                                 blockcut_end=CUT, linelen=LINELEN,
                                 DecoderParams={}),
        demod_blocksize=BLOCKSIZE,
        output_lines=OUTPUT_LINES,
        infile=None,
        freader=freader,
        block_cache=block_cache,
        pipeline_warm=True,
        _job_engine=None,
    )
    stub._read_raw_block = types.MethodType(LDdecode._read_raw_block, stub)
    stub._demod_raw_block = lambda raw, mtf: _demod(raw, mtf)
    stub._demod_read_tail = types.MethodType(LDdecode._demod_read_tail, stub)
    return stub


def _blocks_readable(file_len):
    """How many whole blocks a file of file_len samples can feed."""
    return (file_len - BLOCKLEN) // BLOCKSIZE + 1


def test_a_window_inside_the_file_is_not_truncated():
    stub = _stub(10_000)
    rv = LDdecode.demod_read(stub, 0, 4 * BLOCKSIZE)

    assert rv["truncated"] is False
    assert len(rv["video"]) == 5 * BLOCKSIZE


def test_a_window_over_eof_keeps_the_blocks_before_it():
    """Five blocks asked for, three in the file: the three come back,
    flagged, rather than nothing."""
    file_len = 2 * BLOCKSIZE + BLOCKLEN + 5
    assert _blocks_readable(file_len) == 3
    stub = _stub(file_len)

    rv = LDdecode.demod_read(stub, 0, 4 * BLOCKSIZE)

    assert rv["truncated"] is True
    assert len(rv["video"]) == 3 * BLOCKSIZE
    np.testing.assert_array_equal(
        rv["video"], np.arange(CUT, CUT + 3 * BLOCKSIZE, dtype=np.float64))


def test_no_window_when_the_blocks_before_eof_cannot_hold_a_field():
    """One block (48 samples) is less than a field (80): end of input."""
    stub = _stub(BLOCKLEN + 5)

    assert LDdecode.demod_read(stub, 0, 4 * BLOCKSIZE) is None


class _EofCache:
    """A block cache that, like DemodBlockCache.get_span, returns None
    when EOF falls inside the span."""

    def __init__(self):
        self.read_lock = threading.Lock()

    def get_span(self, brange, mtf_level, imtf_strength=None, veq=None):
        return None


def test_a_threaded_decode_reads_the_same_tail_as_a_serial_one():
    """-t N --exact-speculation must be bit-identical to serial, so the
    block cache's EOF gives the same truncated window."""
    file_len = 2 * BLOCKSIZE + BLOCKLEN + 5
    serial = LDdecode.demod_read(_stub(file_len), 0, 4 * BLOCKSIZE)
    threaded = LDdecode.demod_read(_stub(file_len, _EofCache()), 0,
                                   4 * BLOCKSIZE)

    assert threaded["truncated"] is True
    np.testing.assert_array_equal(threaded["video"], serial["video"])


def _decodefield_stub(rawdecode, valid):
    class _Field:
        def __init__(self, *args, **kwargs):
            self.valid = valid
            self.nextfieldoffset = 5000

        def process(self):
            pass

    return types.SimpleNamespace(
        rf=types.SimpleNamespace(blockcut=0),
        blocksize=32768,
        readlen=65536,
        readlen_first=65536,
        demod_read=lambda *a, **kw: rawdecode,
        FieldClass=_Field,
        fields_written=0,
        wow_level_adjust_smoothing=None,
        wow_interpolation_method=None,
        curfield=None,
        use_profiler=False,
        system="NTSC",
    )


def test_an_invalid_field_in_a_truncated_window_is_end_of_input():
    stub = _decodefield_stub({"startloc": 0, "truncated": True}, valid=False)

    assert LDdecode.decodefield(stub, 0, 0) == (None, None)


def test_an_invalid_field_in_a_whole_window_is_still_skipped_past():
    stub = _decodefield_stub({"startloc": 0, "truncated": False}, valid=False)

    f, offset = LDdecode.decodefield(stub, 0, 0)

    assert f is not None and not f.valid
    assert offset == 5000


def test_a_valid_field_in_a_truncated_window_is_kept():
    stub = _decodefield_stub({"startloc": 0, "truncated": True}, valid=True)

    f, offset = LDdecode.decodefield(stub, 0, 0)

    assert f is not None and f.valid
