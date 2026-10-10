"""Unit tests for the PAL pilot zero-crossing refinement in lddecode.dsp.

The 3.75 MHz pilot is locked to the line rate, so when a line spans more
samples than nominal (the disc is turning slowly against the sample clock) the
pilot's period in samples stretches by the same factor.  refine_pilot_zcs
divided by that factor instead of multiplying, doubling the period error, and
since each line's phase is counted in half-periods from wherever the zero
crossing falls, that error scattered the per-line phase it reports.
"""

import numpy as np
import pytest

from lddecode.dsp import refine_pilot_zcs

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

FREQ = 40.0  # samples per microsecond
PILOT_MHZ = 3.75
LINELEN = 2560.0  # nominal samples per 64 us line at 40 Msps
LINES = 20
STRETCH = 1.002  # lines 0.2% longer than nominal


def _pilot_capture():
    """A line-locked pilot (240 cycles per line) on lines stretched by STRETCH."""
    linelen = LINELEN * STRETCH
    linelocs = 100.0 + np.arange(LINES + 1) * linelen
    t = np.arange(int(linelocs[-1] + linelen), dtype=np.float64)
    cycles_per_sample = (LINELEN / (FREQ / PILOT_MHZ)) / linelen
    return np.sin(2 * np.pi * cycles_per_sample * t), linelocs


def test_pilot_half_period_stretches_with_the_line():
    pilot, linelocs = _pilot_capture()

    _zcs, plen = refine_pilot_zcs(
        pilot, linelocs, LINES, 6 * FREQ, FREQ, LINELEN, PILOT_MHZ
    )

    nominal = FREQ / PILOT_MHZ / 2
    np.testing.assert_allclose(plen[2:], nominal * STRETCH, rtol=1e-9)


def test_line_locked_pilot_reports_the_same_phase_on_every_line():
    pilot, linelocs = _pilot_capture()

    zcs, _plen = refine_pilot_zcs(
        pilot, linelocs, LINES, 6 * FREQ, FREQ, LINELEN, PILOT_MHZ
    )

    # zcs counts half-periods from either-edge crossings, so field.py takes
    # it modulo 1 (phase_distance); every line starts on the same pilot
    # phase, so the spread is only interpolation error.
    phase = np.unwrap(np.angle(np.exp(2j * np.pi * zcs[2:])))
    spread = np.ptp(phase) / (2 * np.pi)
    assert spread < 0.01
