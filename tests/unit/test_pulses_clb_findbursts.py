"""Unit tests for clb_findbursts, the burst zero-crossing count behind PAL's
8-field sequence position and NTSC's burst refinement.

The crossings land in a fixed array of slots; a PAL burst fills about 7 of
16, an NTSC one 12-14.  The empty slots used to join the median that sets
the burst's phase and the count of rising crossings, so on PAL they
outvoted the burst: the phase was pinned to the start of the burst window
and the field's position in the sequence flip-flopped by four fields
(industrial-lv-side1, whose CVBS output opened on frame 3).
"""

import numpy as np
import pytest

from lddecode.pulses import clb_findbursts

pytestmark = [pytest.mark.unit, pytest.mark.decode]

PERIOD = 10.0       # samples per subcarrier cycle
FIRST_ZC = 1.5      # first crossing: 0.3 of a half-cycle past the grid


def find(slots, phase_adjust=0.0, end=36):
    """clb_findbursts over a clean burst with `slots` crossing slots."""
    j = np.arange(64, dtype=np.float64)
    burst = np.sin(2 * np.pi * (j - FIRST_ZC) / PERIOD)
    isrising = np.zeros(slots, dtype=np.bool_)
    zcs = np.zeros(slots, dtype=np.float64)
    return clb_findbursts(isrising, zcs, burst, 0, end, 0.5,
                          0.0, 0.0, PERIOD / 2, phase_adjust)


def test_the_phase_comes_from_the_crossings_found_only():
    count, phase_adjust, _ = find(16)

    # 8 crossings, every one 0.3 half-cycles past the grid; the 8 empty
    # slots read as crossings on it and used to drag the median there
    assert count == 8
    assert phase_adjust == pytest.approx(-0.3)


@pytest.mark.parametrize("phase_adjust", [0.0, 0.6])
def test_spare_slots_change_nothing(phase_adjust):
    assert find(16, phase_adjust) == pytest.approx(find(64, phase_adjust))


def test_the_rising_count_counts_crossings_found_only():
    # an incoming phase that rounds the empty slots onto an odd half-cycle,
    # which counted every one of them as a rising crossing; the 8 real
    # crossings all round the other way
    count, _, rising = find(16, phase_adjust=0.6)
    assert (count, rising) == (8, 0)
