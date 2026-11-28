"""Captures read at positions: the readers the read-time TBC and the
resample cleaning read every capture through (fileio.open_capture).

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

They write small captures to a temporary directory and read them back:
a packed .lds through PackedCapture, a FLAC through CompressedCapture.
"""

import numpy as np
import pytest

from lddecode.fileio import load_packed_data_4_40, open_capture

pytestmark = [pytest.mark.functional]


def _pack(samples):
    """Four 10-bit samples into the five bytes the DdD writes, group by group."""
    out = bytearray()
    for i in range(0, len(samples), 4):
        a, b, c, d = (int(v) for v in samples[i : i + 4])
        out += bytes([
            a >> 2,
            ((a & 0x03) << 6) | (b >> 4),
            ((b & 0x0F) << 4) | (c >> 6),
            ((c & 0x3F) << 2) | (d >> 8),
            d & 0xFF,
        ])
    return bytes(out)


def test_a_packed_capture_reads_at_positions_what_its_loader_reads(tmp_path):
    """PackedCapture reads an .lds at any position, zero outside it, the
    samples load_packed_data_4_40 gives the decoder."""
    samples = np.random.default_rng(2).integers(0, 1024, size=4 * 64)
    path = tmp_path / "capture.lds"
    path.write_bytes(_pack(samples))
    capture = open_capture(str(path))
    try:
        assert capture.length == len(samples)
        with open(path, "rb") as f:
            want = load_packed_data_4_40(f, 0, len(samples))
        np.testing.assert_array_equal(capture.read(0, len(samples)), want)
        np.testing.assert_array_equal(capture.read(37, 50), want[37:87])
        tail = capture.read(len(samples) - 3, 8)
        np.testing.assert_array_equal(tail[:3], want[-3:])
        assert not tail[3:].any()
        head = capture.read(-2, 4)
        assert not head[:2].any()
        np.testing.assert_array_equal(head[2:], want[:2])
    finally:
        capture.close()


# The reader goes by the name, the container by its content: every name
# the decoder hands LoadLDF must open here too, ".raw.oga" (ld-compress
# --oga) among them, whose suffix has two dots.
@pytest.mark.parametrize("name", ["capture.flac", "capture.ldf", "capture.raw.oga"])
def test_a_compressed_capture_reads_at_positions(tmp_path, name):
    """CompressedCapture reads a FLAC capture at any position, through the
    decoder's FLAC reader, and knows its length from the container."""
    av = pytest.importorskip("av", reason="PyAV is required for the FLAC reader")
    samples = np.random.default_rng(3).integers(-20000, 20000, size=40000).astype(np.int16)
    path = tmp_path / name
    with av.open(str(path), "w", format="flac") as out:
        stream = out.add_stream("flac", rate=40000, layout="mono")
        frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = 40000
        for packet in stream.encode(frame):
            out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    capture = open_capture(str(path))
    try:
        assert capture.length == samples.size
        np.testing.assert_array_equal(capture.read(0, 1000), samples[:1000])
        np.testing.assert_array_equal(capture.read(30000, 500), samples[30000:30500])
        np.testing.assert_array_equal(capture.read(100, 50), samples[100:150])
        assert not capture.read(samples.size, 10).any()
    finally:
        capture.close()


def _write_flac(path, samples):
    av = pytest.importorskip("av", reason="PyAV is required for the FLAC reader")
    with av.open(str(path), "w", format="flac") as out:
        stream = out.add_stream("flac", rate=40000, layout="mono")
        frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = 40000
        for packet in stream.encode(frame):
            out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)


def _set_header_count(path, count):
    """Write `count` into the FLAC header's total samples (STREAMINFO: the
    low 36 bits of its bytes 10 to 17, after "fLaC" and the block header)."""
    data = bytearray(path.read_bytes())
    at = 8 + 10
    field = int.from_bytes(data[at : at + 8], "big")
    field = (field & ~((1 << 36) - 1)) | (count & ((1 << 36) - 1))
    data[at : at + 8] = field.to_bytes(8, "big")
    path.write_bytes(bytes(data))


@pytest.mark.parametrize("header", [None, 1000, 0, 5_000_000])
def test_a_compressed_captures_length_is_the_streams_not_its_headers(tmp_path, header):
    """A FLAC's header can carry a count that is not the stream's (a file
    encoded through a pipe): the length is where the stream ends, as the
    decoder finds it reading, whatever the header says (right, too small,
    unknown, too large)."""
    from lddecode.fileio import compressed_length

    samples = np.random.default_rng(4).integers(-2000, 2000, size=300_001).astype(np.int16)
    path = tmp_path / "capture.flac"
    _write_flac(path, samples)
    if header is not None:
        _set_header_count(path, header)

    assert compressed_length(str(path)) == samples.size
    capture = open_capture(str(path))
    try:
        assert capture.length == samples.size
        np.testing.assert_array_equal(capture.read(samples.size - 500, 500), samples[-500:])
    finally:
        capture.close()
