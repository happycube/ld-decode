"""Unit tests for lddecode.pulses -- sync, dropout and burst detection.

Sync pulse detection is the entry point for every timing decision in a decode:
if a pulse is found one sample late, every line location derived from it is one
sample late.  The signals here are synthesised from the pulse widths in
params.py at a stated sample rate, so the expected start and length of each
pulse is known exactly and the assertions can be exact integers rather than
tolerances.

The threshold-crossing conventions these functions use are easy to get wrong by
one sample in either direction, so each is pinned explicitly.
"""

import numpy as np
import pytest

from lddecode.params import SysParams_NTSC, SysParams_PAL
from lddecode.pulses import (
    Pulse,
    _dropout_unflag_sync,
    clb_findbursts,
    findareas,
    findpulses,
    findpulses_numba_raw,
)

pytestmark = [pytest.mark.unit, pytest.mark.decode]

# The decoder's RF sample rate.  At 40 MHz an NTSC hsync (4.7 us) is 188
# samples and an equalisation pulse (2.3 us) is 92, both exact integers, so the
# synthesised pulses have no rounding of their own to confuse the assertions.
FREQ_MHZ = 40.0

# Sync reference levels: the detectors compare against a single threshold, so
# any two levels either side of it will do.  These are shaped like a demodulated
# sync reference (blanking high, sync tip low).
BLANKING = 10.0
SYNC_TIP = 0.0
THRESHOLD = 5.0


def sync_reference(length, pulses):
    """A blanking-level buffer with sync tips at the given (start, width)s."""
    buf = np.full(length, BLANKING)
    for start, width in pulses:
        buf[start : start + width] = SYNC_TIP
    return buf


def pulse_width(sysparams, key):
    """Pulse width in samples at FREQ_MHZ, as an exact integer."""
    samples = sysparams[key] * FREQ_MHZ
    assert samples == int(samples), f"{key} is not a whole number of samples"
    return int(samples)


# --- findareas ------------------------------------------------------------


def test_findareas_brackets_each_region_below_the_threshold():
    # Samples 2..4 and 7..8 are below the crossing level.
    data = np.array([5.0, 5.0, 1.0, 1.0, 1.0, 5.0, 5.0, 0.0, 0.0, 5.0, 5.0])

    areas = findareas(data, 3.0)

    # The convention is (last sample at or above, last sample below, length):
    # the region below is the half-open interval (begin, end].  Downstream code
    # slices with these, so the off-by-one is the thing being pinned.
    assert areas == [(1, 4, 3), (6, 8, 2)]


def test_findareas_with_no_crossings():
    assert findareas(np.full(10, 5.0), 3.0) == []
    assert findareas(np.zeros(10), 3.0) == []


def test_findareas_with_empty_input():
    assert findareas(np.array([]), 3.0) == []


def test_findareas_discards_a_region_open_at_the_start():
    # Starts below the threshold: there is no rising edge to open the first
    # region, so it is dropped rather than reported with a made-up beginning.
    data = np.array([0.0, 0.0, 5.0, 5.0, 0.0, 0.0, 5.0])

    assert findareas(data, 3.0) == [(3, 5, 2)]


def test_findareas_discards_a_region_open_at_the_end():
    # Ends below the threshold: the last region never closes.
    data = np.array([5.0, 0.0, 0.0, 5.0, 5.0, 0.0, 0.0])

    assert findareas(data, 3.0) == [(0, 2, 2)]


def test_findareas_with_a_single_sample_region():
    data = np.array([5.0, 0.0, 5.0])

    assert findareas(data, 3.0) == [(0, 1, 1)]


# --- findpulses -----------------------------------------------------------


@pytest.mark.parametrize(
    "sysparams", [SysParams_NTSC, SysParams_PAL], ids=["NTSC", "PAL"]
)
def test_hsync_pulses_are_found_at_their_exact_positions(sysparams):
    hsync = pulse_width(sysparams, "hsyncPulseUS")
    line = int(round(sysparams["line_period"] * FREQ_MHZ))
    starts = [line, 2 * line, 3 * line]

    buf = sync_reference(5 * line, [(s, hsync) for s in starts])
    pulses = findpulses(buf, None, THRESHOLD)

    # Exact: a synthesised pulse has a hard edge, so there is nothing to
    # approximate.  The length is measured from the first sample at or below
    # the threshold to the first sample above it.
    assert pulses == [Pulse(s, hsync) for s in starts]


def test_pulses_of_each_kind_are_measured_correctly():
    eq = pulse_width(SysParams_NTSC, "eqPulseUS")
    hsync = pulse_width(SysParams_NTSC, "hsyncPulseUS")
    vsync = pulse_width(SysParams_NTSC, "vsyncPulseUS")

    buf = sync_reference(8000, [(1000, eq), (2000, hsync), (3000, vsync)])
    pulses = findpulses(buf, None, THRESHOLD)

    # 2.3 us, 4.7 us and 27.1 us at 40 MHz.  The vertical interval is
    # classified by these widths, so a systematic error would turn equalisation
    # pulses into hsyncs.
    assert [p.len for p in pulses] == [92, 188, 1084]
    assert [p.start for p in pulses] == [1000, 2000, 3000]


def test_a_pulse_starting_at_sample_zero_is_discarded():
    # A buffer that begins mid-pulse cannot have a trustworthy start, so it is
    # dropped rather than reported with a truncated length.  Block-at-a-time
    # demodulation makes this common at every block boundary.
    hsync = pulse_width(SysParams_NTSC, "hsyncPulseUS")
    buf = sync_reference(2000, [(0, hsync), (500, hsync)])

    assert findpulses(buf, None, THRESHOLD) == [Pulse(500, hsync)]


def test_a_pulse_running_off_the_end_is_discarded():
    # Likewise for a pulse still open when the buffer ends: its length is
    # unknown, so it is not reported.
    hsync = pulse_width(SysParams_NTSC, "hsyncPulseUS")
    buf = sync_reference(2000, [(500, hsync), (1900, 100)])

    assert findpulses(buf, None, THRESHOLD) == [Pulse(500, hsync)]


def test_findpulses_with_no_pulses():
    assert findpulses(np.full(1000, BLANKING), None, THRESHOLD) == []


def test_raw_detector_rejects_pulses_outside_the_length_window():
    buf = sync_reference(500, [(20, 10), (100, 3), (200, 50)])

    starts, lengths = findpulses_numba_raw(buf, THRESHOLD, 4, 40)

    # min_synclen and max_synclen bracket what counts as a sync pulse; the
    # 3-sample and 50-sample excursions are noise and a dropout respectively.
    assert np.array_equal(starts, [20])
    assert np.array_equal(lengths, [10])


def test_raw_detector_length_window_is_inclusive():
    buf = sync_reference(500, [(20, 10), (100, 40)])

    starts, _ = findpulses_numba_raw(buf, THRESHOLD, 10, 40)

    # inrange() is inclusive at both ends, so a pulse exactly at either limit
    # is kept.  Worth pinning: the sync classifier's limits are derived from
    # the nominal widths and would otherwise reject a perfect pulse.
    assert np.array_equal(starts, [20, 100])


def test_raw_detector_returns_empty_arrays_when_nothing_matches():
    starts, lengths = findpulses_numba_raw(np.full(500, BLANKING), THRESHOLD)

    assert len(starts) == 0 and len(lengths) == 0


# --- _dropout_unflag_sync -------------------------------------------------


def test_dropout_unflag_clears_only_in_range_samples_inside_the_window():
    iserr = np.ones(12, dtype=bool)
    demod = np.arange(12.0)

    _dropout_unflag_sync(iserr, demod, demod.copy(), 2, 9, 3.0, 7.0, 3.0, 7.0)

    # Samples 3..7 are inside both the window and the level range; 2 and 8 are
    # in the window but outside the range, and 0..1 and 9..11 are outside the
    # window entirely.
    expected = np.ones(12, dtype=bool)
    expected[3:8] = False
    assert np.array_equal(iserr, expected)


def test_dropout_unflag_requires_both_demod_paths_to_agree():
    iserr = np.ones(12, dtype=bool)
    demod = np.arange(12.0)
    demod_05 = demod.copy()
    demod_05[5] = 99.0

    _dropout_unflag_sync(iserr, demod, demod_05, 0, 12, 3.0, 7.0, 3.0, 7.0)

    # Sample 5 is in range on the full-bandwidth demod but not on the 0.5 MHz
    # one, so it stays flagged.  Requiring both is what stops a dropout that
    # happens to land at sync level from being unflagged.
    expected = np.ones(12, dtype=bool)
    expected[3:8] = False
    expected[5] = True
    assert np.array_equal(iserr, expected)


def test_dropout_unflag_clamps_the_window_to_the_array():
    iserr = np.ones(12, dtype=bool)
    demod = np.arange(12.0)

    # A dropout overlapping the start or end of the field gives out-of-range
    # indices; they must be clamped rather than wrapping or raising.
    _dropout_unflag_sync(iserr, demod, demod.copy(), -5, 100, 3.0, 7.0, 3.0, 7.0)

    expected = np.ones(12, dtype=bool)
    expected[3:8] = False
    assert np.array_equal(iserr, expected)


def test_dropout_unflag_with_an_empty_window():
    iserr = np.ones(12, dtype=bool)
    demod = np.arange(12.0)

    _dropout_unflag_sync(iserr, demod, demod.copy(), 6, 6, 3.0, 7.0, 3.0, 7.0)

    assert np.all(iserr)


def test_dropout_unflag_is_idempotent():
    # An overlapping pair of dropouts unflags the same sample twice; the second
    # pass must not re-flag anything.
    iserr = np.ones(12, dtype=bool)
    demod = np.arange(12.0)

    _dropout_unflag_sync(iserr, demod, demod.copy(), 2, 9, 3.0, 7.0, 3.0, 7.0)
    first = iserr.copy()
    _dropout_unflag_sync(iserr, demod, demod.copy(), 4, 11, 3.0, 7.0, 3.0, 7.0)

    assert np.array_equal(iserr, first)


# --- clb_findbursts -------------------------------------------------------

# An 8-sample subcarrier period, so zero crossings fall every 4 samples and the
# analytic answer is an integer.  zcburstdiv is the half period: one unit of
# "burst cycle" per crossing.
BURST_PERIOD = 8.0
BURST_HALF_PERIOD = BURST_PERIOD / 2


def burst(length, shift=0.0):
    n = np.arange(float(length))
    return np.sin(2 * np.pi * (n - shift) / BURST_PERIOD)


def test_burst_zero_crossings_are_found_at_the_analytic_positions():
    burstarea = burst(64)
    count = 14
    isrising = np.zeros(count, dtype=bool)
    zcs = np.zeros(count)

    zc_count, phase_adjust, _ = clb_findbursts(
        isrising, zcs, burstarea, 1, 60, 0.1, 0.0, 0.0, BURST_HALF_PERIOD, 0.0
    )

    assert zc_count == count
    # A sine sampled 8x per cycle crosses zero exactly on samples 4, 8, 12...
    # and linear interpolation between the bracketing samples is exact there by
    # symmetry, so this is tighter than the 0.01 samples a general crossing
    # would warrant.
    assert np.abs(zcs - np.arange(4.0, 4 * count + 1, 4.0)).max() < 1e-9
    assert phase_adjust == pytest.approx(0.0, abs=1e-12)


def test_burst_crossing_directions_alternate():
    burstarea = burst(64)
    count = 14
    isrising = np.zeros(count, dtype=bool)
    zcs = np.zeros(count)

    clb_findbursts(
        isrising, zcs, burstarea, 1, 60, 0.1, 0.0, 0.0, BURST_HALF_PERIOD, 0.0
    )

    # sin() first crosses zero going down, then alternates.  Burst phase
    # detection counts rising crossings against expected parity, so a direction
    # that did not alternate would corrupt the phase estimate.
    expected = np.arange(count) % 2 == 1
    assert np.array_equal(isrising, expected)


def test_burst_phase_adjust_absorbs_a_fractional_offset():
    # The burst is half a sample late, so each crossing sits at n.5 and the
    # cycle numbering is 0.125 out (half a sample over a 4-sample half period).
    burstarea = burst(64, shift=0.5)
    count = 14
    isrising = np.zeros(count, dtype=bool)
    zcs = np.zeros(count)

    _, phase_adjust, _ = clb_findbursts(
        isrising, zcs, burstarea, 1, 60, 0.1, 0.0, 0.0, BURST_HALF_PERIOD, 0.0
    )

    assert np.abs(zcs - np.arange(4.5, 4 * count + 1, 4.0)).max() < 1e-9
    assert phase_adjust == pytest.approx(-0.125, abs=1e-9)


def test_burst_phase_adjust_makes_the_cycle_numbering_integral():
    burstarea = burst(64, shift=0.5)
    count = 14
    isrising = np.zeros(count, dtype=bool)
    zcs = np.zeros(count)

    _, phase_adjust, _ = clb_findbursts(
        isrising, zcs, burstarea, 1, 60, 0.1, 0.0, 0.0, BURST_HALF_PERIOD, 0.0
    )

    # That is what phase_adjust is for: applying it lines the measured
    # crossings up with whole subcarrier half-cycles, which is how the phase of
    # the burst relative to the line is established.
    cycles = zcs / BURST_HALF_PERIOD + phase_adjust
    assert np.abs(cycles - np.round(cycles)).max() < 1e-9


def test_burst_below_the_threshold_finds_nothing():
    burstarea = 0.01 * burst(64)
    isrising = np.zeros(14, dtype=bool)
    zcs = np.zeros(14)

    zc_count, phase_adjust, rising_count = clb_findbursts(
        isrising, zcs, burstarea, 1, 60, 0.5, 0.0, 0.0, BURST_HALF_PERIOD, 0.25
    )

    # A line with no burst (or one buried in noise) must report nothing rather
    # than a phase derived from noise, and must leave the running phase
    # estimate alone.
    assert zc_count == 0
    assert rising_count == 0
    assert phase_adjust == 0.25


def test_burst_search_stops_when_the_output_arrays_are_full():
    burstarea = burst(64)
    isrising = np.zeros(3, dtype=bool)
    zcs = np.zeros(3)

    zc_count, _, _ = clb_findbursts(
        isrising, zcs, burstarea, 1, 60, 0.1, 0.0, 0.0, BURST_HALF_PERIOD, 0.0
    )

    # The caller sizes the arrays for the expected burst length; overrunning
    # them in a jitted function would corrupt memory rather than raise.
    assert zc_count == 3
    assert np.abs(zcs - np.array([4.0, 8.0, 12.0])).max() < 1e-9


def test_burst_search_respects_the_end_of_the_burst_area():
    burstarea = burst(64)
    isrising = np.zeros(14, dtype=bool)
    zcs = np.zeros(14)

    zc_count, _, _ = clb_findbursts(
        isrising, zcs, burstarea, 1, 20, 0.1, 0.0, 0.0, BURST_HALF_PERIOD, 0.0
    )

    # endburstarea bounds where the scan may *start* looking, not where a
    # crossing may fall: the last search position inside the window is sample
    # 17, and the crossing it brackets is at 20.0, just past the bound.  So the
    # window keeps active video out of the burst measurement, but the final
    # crossing can sit up to half a subcarrier cycle beyond it.
    assert zc_count == 5
    assert np.abs(zcs[:5] - np.array([4.0, 8.0, 12.0, 16.0, 20.0])).max() < 1e-9
