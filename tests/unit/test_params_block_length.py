"""Unit tests for the demodulation block-length override.

``params.resolve_block_length`` is the one place the block length can be moved
away from ``BLOCKSIZE``.  It exists for the block-length sweep, and the sweep's
whole value is that a measured cell is at the length it says it is, so a
malformed override has to raise rather than fall back to the default quietly.

Hermetic: the environment is injected as a plain dict; ``os.environ`` is never
read or written.
"""

import pytest

from lddecode.params import (
    BLOCK_LENGTH_ENV,
    BLOCK_LENGTH_MAX,
    BLOCK_LENGTH_MIN,
    BLOCKSIZE,
    resolve_block_length,
)

pytestmark = [pytest.mark.unit, pytest.mark.dsp]


def test_an_absent_override_gives_the_shipped_block_length():
    assert resolve_block_length({}) == BLOCKSIZE


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_an_empty_override_gives_the_shipped_block_length(blank):
    assert resolve_block_length({BLOCK_LENGTH_ENV: blank}) == BLOCKSIZE


@pytest.mark.parametrize("length", [4096, 8192, 16384, 32768, 65536, 131072])
def test_a_power_of_two_in_range_is_taken(length):
    assert resolve_block_length({BLOCK_LENGTH_ENV: str(length)}) == length


def test_surrounding_whitespace_is_tolerated():
    assert resolve_block_length({BLOCK_LENGTH_ENV: " 16384\n"}) == 16384


@pytest.mark.parametrize("text", ["12288", "40000", "32767"])
def test_a_length_that_is_not_a_power_of_two_is_refused(text):
    with pytest.raises(ValueError, match="power of two"):
        resolve_block_length({BLOCK_LENGTH_ENV: text})


@pytest.mark.parametrize("length", [BLOCK_LENGTH_MIN // 2, BLOCK_LENGTH_MAX * 2])
def test_a_power_of_two_outside_the_range_is_refused(length):
    with pytest.raises(ValueError, match="between"):
        resolve_block_length({BLOCK_LENGTH_ENV: str(length)})


@pytest.mark.parametrize("text", ["32k", "-16384", "32768.0", "0x8000", "auto"])
def test_a_value_that_is_not_a_positive_integer_is_refused(text):
    with pytest.raises(ValueError, match="positive integer"):
        resolve_block_length({BLOCK_LENGTH_ENV: text})


def test_zero_is_refused_rather_than_treated_as_absent():
    # "0" parses as an integer and is not caught by the power-of-two test
    # (0 & -1 == 0), so the range check is what has to refuse it.
    with pytest.raises(ValueError):
        resolve_block_length({BLOCK_LENGTH_ENV: "0"})


def test_the_shipped_length_is_itself_inside_the_accepted_range():
    assert BLOCK_LENGTH_MIN <= BLOCKSIZE <= BLOCK_LENGTH_MAX
    assert BLOCKSIZE & (BLOCKSIZE - 1) == 0
