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


def test_a_compressed_capture_reads_at_positions(tmp_path):
    """CompressedCapture reads a FLAC capture at any position, through the
    decoder's FLAC reader, and knows its length from the container."""
    av = pytest.importorskip("av", reason="PyAV is required for the FLAC reader")
    samples = np.random.default_rng(3).integers(-20000, 20000, size=40000).astype(np.int16)
    path = tmp_path / "capture.flac"
    with av.open(str(path), "w") as out:
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
