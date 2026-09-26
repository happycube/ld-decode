"""Unit tests for reading .s8 (signed 8-bit) source files.

make_loader() recognised .s8 only on its resampling path, where a --frequency
is given and ffmpeg does the reading.  Without --frequency the extension fell
through to the bare LoadFFmpeg() fallback, which reads stdin with no format
arguments, so no samples arrived and the decode ended with "Completed without
handling any frames" without having read the file.
"""

import io

import numpy as np
import pytest

from lddecode.fileio import LoadFFmpeg, load_unpacked_data_s8, make_loader

pytestmark = [pytest.mark.unit, pytest.mark.format]


def test_s8_maps_to_its_own_loader_without_a_frequency():
    loader = make_loader("capture.s8")

    assert loader is load_unpacked_data_s8


def test_s8_still_uses_ffmpeg_when_resampling():
    loader = make_loader("capture.s8", inputfreq=62.5)

    assert isinstance(loader, LoadFFmpeg)
    assert loader.input_args == ["-f", "s8"]


def test_s8_samples_are_scaled_to_the_16_bit_range():
    # Matches the ffmpeg path, which converts s8 to pcm_s16le by scaling by
    # 256, so a file decodes identically whichever loader reads it.
    raw = np.array([-128, -1, 0, 1, 127], dtype=np.int8)

    out = load_unpacked_data_s8(io.BytesIO(raw.tobytes()), 0, len(raw))

    assert out.dtype == np.int16
    np.testing.assert_array_equal(out, raw.astype(np.int16) * 256)


def test_s8_sample_offsets_are_one_byte_apart():
    raw = np.arange(-8, 8, dtype=np.int8)

    out = load_unpacked_data_s8(io.BytesIO(raw.tobytes()), 3, 4)

    np.testing.assert_array_equal(out, raw[3:7].astype(np.int16) * 256)


def test_s8_short_read_is_eof():
    raw = np.zeros(4, dtype=np.int8)

    assert load_unpacked_data_s8(io.BytesIO(raw.tobytes()), 0, 64) is None
