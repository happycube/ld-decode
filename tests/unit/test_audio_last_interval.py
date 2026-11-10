"""Unit tests for the last output audio sample of a field's buffer.

_downscale_audio_to_output averages audio_left[start:end] into each output
sample, and treated an interval ending exactly at the end of the buffer
(end == len, a valid exclusive bound) as out of range: the sample was muted
and the field reported as having failed samples.
"""

import numpy as np
import pytest

from lddecode.audio import _downscale_audio_to_output

pytestmark = [pytest.mark.unit, pytest.mark.dsp]


LFREQ, RFREQ = 2.3e6, 2.8e6       # carrier frequencies, Hz


def downscale(locs, n):
    # 20 and 30 kHz of deviation: well inside full scale, far from zero
    left = np.full(n, LFREQ + 20e3)
    right = np.full(n, RFREQ + 30e3)
    return _downscale_audio_to_output(
        np.arange(len(locs), dtype=np.float64), np.asarray(locs, dtype=np.float64),
        np.ones(len(locs)), left, right, LFREQ, RFREQ, 32767)


def test_an_interval_reaching_the_end_of_the_buffer_is_kept():
    output, failed = downscale([0.0, 5.0, 10.0], 10)

    assert not failed
    assert np.all(output != 0)
    np.testing.assert_array_equal(output[2:], output[:2])


def test_an_interval_past_the_end_is_still_muted():
    output, failed = downscale([0.0, 5.0, 11.0], 10)

    assert failed
    np.testing.assert_array_equal(output[2:], [0, 0])
