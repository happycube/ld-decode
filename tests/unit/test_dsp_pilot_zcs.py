"""Unit tests for the PAL pilot zero-crossing finder in lddecode.dsp.

FieldPAL.refine_linelocs_pilot moves each line location onto the phase of
the LaserDisc's 3.75 MHz pilot, which is line-locked (240 cycles a line).
refine_pilot_zcs measures where a pilot zero crossing falls after each
line location, in half pilot periods, scaling the period by the line's
length so the reading does not move with the disc's speed.  A CAV disc's
once-per-revolution wow runs one way across the first field and the other
way across the second, so a speed-dependent reading leaned the two fields'
pictures differently.
"""

import numpy as np
import pytest

from lddecode.dsp import refine_pilot_zcs

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

FREQ = 40.0  # MHz sample rate
PILOT_MHZ = 3.75
LINELEN = 2560.0  # samples per nominal PAL line at 40 Msps
PILOT_CYCLES_PER_LINE = 240
LENGTH_PX = 6 * FREQ  # the 6 us window FieldPAL searches


def _line_locked_pilot(speed, phase0=0.3):
    """A pilot that is exactly line-locked across lines of the given
    relative lengths, and the true line locations."""
    lengths = LINELEN * np.asarray(speed)
    linelocs = np.concatenate([[100.0], 100.0 + np.cumsum(lengths)])
    t = np.arange(int(linelocs[-1]) + 1, dtype=np.float64)
    line = np.searchsorted(linelocs, t, side="right") - 1
    line = np.clip(line, 0, len(lengths) - 1)
    frac = (t - linelocs[line]) / lengths[line]
    pilot = np.sin(2 * np.pi * (PILOT_CYCLES_PER_LINE * (line + frac) + phase0))
    return pilot, linelocs


def _circular_spread(zcs):
    """Largest distance of a fractional phase from their circular mean."""
    frac = zcs - np.floor(zcs)
    mean = np.angle(np.mean(np.exp(2j * np.pi * frac))) / (2 * np.pi)
    d = (frac - mean + 0.5) % 1.0 - 0.5
    return np.max(np.abs(d))


def test_zero_crossing_phase_does_not_move_with_disc_speed():
    # +-0.2 % speed swing across the field, four times a real CAV disc's
    # once-per-revolution wow, so a speed-scaled error stands well clear
    n = 64
    speed = 1.0 + np.linspace(-2e-3, 2e-3, n + 1)
    pilot, linelocs = _line_locked_pilot(speed)

    zcs, plen = refine_pilot_zcs(pilot, linelocs, n, LENGTH_PX, FREQ,
                                 LINELEN, PILOT_MHZ)

    # Lines 0 and 1 have no previous line to scale by.  Every other line's
    # crossing sits at the same pilot phase from its line start; scaling
    # the period the wrong way puts up to 2 * 0.2 % * 6 us (~0.18 half
    # periods) between them.
    assert _circular_spread(zcs[2:]) < 0.005


def test_half_period_follows_the_line_length():
    n = 8
    speed = np.full(n + 1, 1.001)  # every line 0.1 % long: a slow disc
    pilot, linelocs = _line_locked_pilot(speed)

    _, plen = refine_pilot_zcs(pilot, linelocs, n, LENGTH_PX, FREQ,
                               LINELEN, PILOT_MHZ)

    nominal = FREQ / PILOT_MHZ / 2
    np.testing.assert_allclose(plen[2:], nominal * 1.001, rtol=1e-9)
    np.testing.assert_allclose(plen[:2], nominal, rtol=1e-9)
