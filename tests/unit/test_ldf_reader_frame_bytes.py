"""Unit tests for taking sample bytes out of a decoded PyAV audio frame.

FFmpeg pads each plane's buffer out to its alignment, so bytes(planes[0]) on a
frame whose length is not a multiple of 16 samples carries junk past the last
real sample.  Every .ldf decode path read the whole buffer, so the short final
frame of a capture grew by up to 15 samples: ld-compress -u turned an
8341675-byte .lds into an 8341680-byte one.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from lddecode.ldf_reader import packed_s16_bytes

pytestmark = [pytest.mark.unit, pytest.mark.format]


def _frame(samples, padded_samples):
    """A stand-in for a packed mono s16 frame with an aligned plane buffer."""
    data = np.arange(padded_samples, dtype="<i2")
    data[samples:] = -1  # the alignment padding past the last real sample
    return SimpleNamespace(samples=samples, planes=[data.tobytes()]), data[:samples]


def test_alignment_padding_is_dropped():
    # The last frame of the round-trip capture: 956 samples in a 960 buffer
    frame, expected = _frame(956, 960)

    data = packed_s16_bytes(frame)

    assert len(data) == 956 * 2
    np.testing.assert_array_equal(np.frombuffer(data, dtype="<i2"), expected)


def test_aligned_frame_is_returned_whole():
    frame, expected = _frame(4096, 4096)

    data = packed_s16_bytes(frame)

    np.testing.assert_array_equal(np.frombuffer(data, dtype="<i2"), expected)
