"""Unit tests for converting loader output to signed 16-bit samples.

The .u8 and .u16 loaders hand back unsigned samples centred on 128 and 32768.
ld-cut and ld-decode --write-test-ldf cast them straight to int16 before
encoding, which wrapped every u16 sample above 32767 (folding the waveform) and
left u8 data as an 8-bit signal in the bottom of the range, which .lds packing
then reduced to its top two bits.
"""

import numpy as np
import pytest

from lddecode.fileio import samples_to_s16

pytestmark = [pytest.mark.unit, pytest.mark.format]


def test_u16_is_recentred_rather_than_wrapped():
    raw = np.array([0, 32767, 32768, 40000, 65535], dtype=np.uint16)

    out = samples_to_s16(raw)

    assert out.dtype == np.int16
    np.testing.assert_array_equal(out, [-32768, -1, 0, 7232, 32767])


def test_u8_is_recentred_and_scaled_to_the_16_bit_range():
    # As ffmpeg's u8 -> pcm_s16le conversion: (x - 128) << 8
    raw = np.array([0, 127, 128, 129, 255], dtype=np.uint8)

    out = samples_to_s16(raw)

    assert out.dtype == np.int16
    np.testing.assert_array_equal(out, [-32768, -256, 0, 256, 32512])


def test_signed_input_is_cast_unchanged():
    raw = np.array([-32768, -1, 0, 1, 32767], dtype=np.int16)

    out = samples_to_s16(raw)

    np.testing.assert_array_equal(out, raw)
    assert out is not raw
