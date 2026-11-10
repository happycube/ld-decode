"""Unit tests for the AC-3 symbol DPLL fed blocks shorter than a symbol.

reclock_symbols keeps the last symbol_distance I/Q samples, to form the
differential symbol for the first samples of the next block.  It kept them
as input[n - sd:], which for a block of n < sd samples is a short (or, for
n == 0, the whole empty) array; the next call then read prev_i[i] past its
end, with Numba bounds checking off.  The tail is now always exactly
symbol_distance long, so how the input is split into blocks cannot change
the symbols.
"""

import numpy as np
import pytest

from lddecode.ac3rf import AC3_DPLL, SYMBOL_RATE

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

FS = SYMBOL_RATE * 6          # six samples per symbol


def qpsk_iq(n_symbols, rng):
    """Differentially encoded QPSK at FS, one phase step per symbol."""
    steps = rng.integers(0, 4, n_symbols) * (np.pi / 2)
    phase = np.repeat(np.cumsum(steps), int(FS / SYMBOL_RATE))
    noise = 0.05 * rng.normal(size=(2, len(phase)))
    return ((np.cos(phase) + noise[0]).astype(np.float32),
            (np.sin(phase) + noise[1]).astype(np.float32))


def reclock(blocks):
    dpll = AC3_DPLL(FS)
    out = [dpll.reclock_symbols(i, q) for i, q in blocks]
    return np.concatenate(out), dpll


def split(i, q, sizes):
    blocks, start = [], 0
    for size in sizes:
        blocks.append((i[start:start + size], q[start:start + size]))
        start += size
    blocks.append((i[start:], q[start:]))
    return blocks


def test_short_and_empty_blocks_give_the_same_symbols_as_one_block():
    rng = np.random.default_rng(12345)
    i, q = qpsk_iq(400, rng)
    whole, _ = reclock([(i, q)])

    sizes = [100, 0, 1, 2, 3, 0, 5, 250, 4, 1, 0, 700]
    pieces, dpll = reclock(split(i, q, sizes))

    np.testing.assert_array_equal(pieces, whole)
    assert len(dpll.prev_i) == dpll.symbol_distance


@pytest.mark.parametrize("n", [0, 1, 5])
def test_the_tail_stays_a_whole_symbol_long(n):
    rng = np.random.default_rng(7)
    i, q = qpsk_iq(20, rng)
    dpll = AC3_DPLL(FS)
    dpll.reclock_symbols(i, q)
    before = dpll.prev_i.copy()

    dpll.reclock_symbols(i[:n], q[:n])

    sd = dpll.symbol_distance
    assert len(dpll.prev_i) == sd and len(dpll.prev_q) == sd
    np.testing.assert_array_equal(dpll.prev_i[: sd - n], before[n:])
    np.testing.assert_array_equal(dpll.prev_i[sd - n:], i[:n])
