"""Unit tests for the small numeric helpers in lddecode.dsp.

These are the jitted reducers and phase-arithmetic routines the hot loops call,
plus the two plain-Python bookkeeping helpers (the LRU list and the strided
block collector).  Individually they are a few lines each; collectively they
decide sync timing, burst phase and block alignment, and a change in any of
them is invisible until a decode comes out subtly wrong.

These run compiled: NUMBA_DISABLE_JIT is not set, so the assertions exercise
the jitted code paths and a Numba typing regression fails here rather than in a
functional decode.  Set NUMBA_DISABLE_JIT=1 locally when a readable traceback
matters more than that.
"""

import numpy as np
import pytest

from lddecode.dsp import (
    LRUupdate,
    StridedCollector,
    angular_mean_helper,
    n_ornotrange,
    n_ornotrange_scalar,
    n_orgt,
    nb_abs,
    nb_absmax,
    nb_max,
    nb_mean,
    nb_median,
    nb_min,
    nb_mul,
    nb_round,
    nb_std,
    phase_distance,
)

pytestmark = [pytest.mark.unit, pytest.mark.dsp]


@pytest.fixture
def sample(seeded_rng):
    """A seeded array with an even length, a negative range and no symmetry."""
    return seeded_rng.normal(3.0, 7.0, 200)


# --- nb_* reducers --------------------------------------------------------


@pytest.mark.parametrize(
    "jitted, reference",
    [
        (nb_median, np.median),
        (nb_mean, np.mean),
        (nb_min, np.min),
        (nb_max, np.max),
        (nb_std, np.std),
    ],
    ids=["median", "mean", "min", "max", "std"],
)
def test_reducers_agree_with_numpy(sample, jitted, reference):
    # These exist purely so the caller can stay inside nopython mode; if one
    # ever stops matching its NumPy equivalent it is a bug in the wrapper, not
    # a design choice.  Tolerance is double-precision reassociation in the
    # jitted reduction, a few ULP on values of order 10.
    assert jitted(sample) == pytest.approx(reference(sample), rel=1e-12)


def test_absmax_is_the_largest_magnitude(sample):
    assert nb_absmax(sample) == pytest.approx(np.abs(sample).max(), rel=1e-12)
    # Distinct from nb_max whenever the largest excursion is negative.
    assert nb_absmax(np.array([-9.0, 2.0])) == 9.0
    assert nb_max(np.array([-9.0, 2.0])) == 2.0


def test_elementwise_helpers(sample):
    assert np.array_equal(nb_abs(sample), np.abs(sample))
    assert np.array_equal(nb_mul(sample, 2.5), sample * 2.5)


def test_reducers_on_a_single_sample():
    one = np.array([4.0])

    assert nb_median(one) == 4.0
    assert nb_mean(one) == 4.0
    assert nb_min(one) == nb_max(one) == 4.0
    assert nb_std(one) == 0.0


def test_median_of_an_even_count_is_the_midpoint():
    # Pinned because half the sync-timing code takes a median of an even number
    # of pulses, and "middle of the two middles" versus "lower middle" is a
    # half-sample difference in the answer.
    assert nb_median(np.array([1.0, 2.0, 3.0, 4.0])) == 2.5


# --- nb_round -------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        (2.4, 2),
        (2.6, 3),
        (-2.4, -2),
        (-2.6, -3),
        # Ties go to even, following np.round: this is what calclinelen inherits.
        (0.5, 0),
        (1.5, 2),
        (2.5, 2),
        (-0.5, 0),
        (-1.5, -2),
    ],
)
def test_round_uses_round_half_to_even(value, expected):
    result = nb_round(value)

    assert result == expected
    # calclinelen and fft_determine_slices index arrays with this.
    assert isinstance(result, int)


# --- in-place boolean accumulators ----------------------------------------


def test_orgt_accumulates_into_the_flag_array():
    flags = np.zeros(5, dtype=bool)
    values = np.array([1.0, 5.0, 3.0, 9.0, 2.0])

    n_orgt(flags, values, np.full(5, 4.0))
    assert np.array_equal(flags, [False, True, False, True, False])

    # OR, not assignment: a second pass must not clear what the first set.
    n_orgt(flags, values, np.full(5, 8.0))
    assert np.array_equal(flags, [False, True, False, True, False])

    n_orgt(flags, values, np.full(5, 0.0))
    assert np.all(flags)


def test_ornotrange_flags_samples_outside_the_window():
    values = np.array([1.0, 5.0, 3.0, 9.0, 2.0])
    expected = [True, False, False, True, False]

    array_form = np.zeros(5, dtype=bool)
    n_ornotrange(array_form, values, np.full(5, 2.0), np.full(5, 5.0))

    scalar_form = np.zeros(5, dtype=bool)
    n_ornotrange_scalar(scalar_form, values, 2.0, 5.0)

    # The two spellings exist for per-sample and fixed limits respectively;
    # given the same limits they must agree, bounds included.
    assert np.array_equal(array_form, expected)
    assert np.array_equal(scalar_form, expected)


def test_ornotrange_bounds_are_inclusive():
    values = np.array([2.0, 5.0])
    flags = np.zeros(2, dtype=bool)

    n_ornotrange_scalar(flags, values, 2.0, 5.0)

    # A sample sitting exactly on the limit is in range.  Dropout detection
    # uses this, so an off-by-one-code error here flags clean samples as rot.
    assert not flags.any()


# --- phase arithmetic -----------------------------------------------------


@pytest.mark.parametrize(
    "x, expected",
    [
        (0.75, 0.0),  # on the reference phase
        (0.9, 0.15),
        (0.1, 0.35),  # wraps forward through 1.0 rather than going back 0.65
        (0.6, -0.15),
        (1.1, 0.35),  # only the fractional part matters
        (3.9, 0.15),
    ],
)
def test_phase_distance_takes_the_short_way_round(x, expected):
    # Phases live on a circle: the distance from 0.1 to 0.75 is -0.35 of a
    # cycle, not +0.65.  Getting this wrong makes the burst phase tracker chase
    # a full cycle of error.  Tolerance is double-precision subtraction.
    assert phase_distance(x) == pytest.approx(expected, abs=1e-12)


def test_phase_distance_at_the_half_cycle_boundary():
    # Exactly half a cycle away is ambiguous; the implementation resolves it
    # negative (the `< -0.5` test is strict).  Pinned so the choice is
    # deliberate rather than incidental.
    assert phase_distance(0.25) == pytest.approx(-0.5, abs=1e-12)


def test_phase_distance_honours_the_reference_phase():
    assert phase_distance(0.3, c=0.3) == pytest.approx(0.0, abs=1e-12)
    assert phase_distance(0.4, c=0.3) == pytest.approx(0.1, abs=1e-12)


def test_angular_mean_helper_maps_phase_to_the_unit_circle():
    angles = np.array(angular_mean_helper(np.array([0.0, 0.25, 0.5, 0.75])))

    # A phase of 0..1 becomes a full turn: quarter cycles land on 1, i, -1, -i.
    expected = np.array([1 + 0j, 1j, -1 + 0j, -1j])
    assert np.abs(angles - expected).max() < 1e-12


def test_angular_mean_helper_averages_across_the_wrap():
    # The reason this exists: phases of 0.99 and 0.01 are 0.02 apart, but their
    # arithmetic mean is 0.5 -- the opposite side of the circle.  Averaging the
    # unit vectors instead gives a resultant pointing at phase 0.
    angles = np.array(angular_mean_helper(np.array([0.99, 0.01])))
    mean_phase = np.angle(angles.mean()) / (2 * np.pi)

    assert mean_phase == pytest.approx(0.0, abs=1e-12)
    # And the resultant is nearly unit length, i.e. the two agree closely.
    assert np.abs(angles.mean()) > 0.99


def test_angular_mean_helper_honours_the_cycle_length():
    # cycle_len says how many phase units make a full turn, so with cycle_len
    # of 2 a phase of 0.5 is a quarter turn rather than a half one.  x is
    # reduced modulo 1 first, so pass values already inside 0..1.
    angles = np.array(angular_mean_helper(np.array([0.5]), cycle_len=2.0))

    assert angles[0] == pytest.approx(1j, abs=1e-12)


# --- LRUupdate ------------------------------------------------------------


def test_lru_moves_an_existing_entry_to_the_front():
    entries = [1, 2, 3]

    LRUupdate(entries, 2)

    assert entries == [2, 1, 3]


def test_lru_inserts_an_unseen_entry_at_the_front():
    entries = [1, 2, 3]

    LRUupdate(entries, 9)

    assert entries == [9, 1, 2, 3]


def test_lru_never_duplicates():
    entries = []

    for key in (1, 2, 3, 2, 1, 4, 1):
        LRUupdate(entries, key)

    # Descending order of last use, each key present once.  The block cache
    # evicts from the tail, so a duplicate would mean a live block being
    # dropped while a stale one is kept.
    assert entries == [1, 4, 2, 3]
    assert len(set(entries)) == len(entries)


# --- StridedCollector -----------------------------------------------------


def test_collector_reports_when_a_block_is_available():
    collector = StridedCollector(blocklen=16, cut_begin=4, cut_end=2)
    data = np.arange(40.0)

    assert collector.add(data[:10]) is False
    assert collector.have_block() is False
    assert collector.add(data[10:20]) is True
    assert collector.have_block() is True


def test_collector_blocks_overlap_by_the_stride():
    collector = StridedCollector(blocklen=16, cut_begin=4, cut_end=2)
    data = np.arange(40.0)

    collector.add(data[:20])
    first = collector.get_block()
    collector.add(data[20:26])
    second = collector.get_block()

    # stride = cut_begin + cut_end = 6, so the next block starts 16 - 6 = 10
    # samples on.  Exact array equality: this is index bookkeeping, not maths.
    assert np.array_equal(first, data[0:16])
    assert np.array_equal(second, data[10:26])


def test_collector_cut_regions_tile_the_input_exactly():
    collector = StridedCollector(blocklen=16, cut_begin=4, cut_end=2)
    data = np.arange(40.0)
    collector.add(data)

    kept = []
    while collector.have_block():
        kept.append(collector.cut(collector.get_block()))

    # This is the whole point of the class: the retained middles of successive
    # blocks join up with no gap and no overlap, so the FFT edge effects are
    # discarded without losing or repeating a sample.
    assert np.array_equal(np.concatenate(kept), data[4 : 4 + 10 * len(kept)])


def test_collector_cut_discards_the_configured_edges():
    collector = StridedCollector(blocklen=16, cut_begin=4, cut_end=2)
    block = np.arange(16.0)

    assert np.array_equal(collector.cut(block), np.arange(4.0, 14.0))


def test_collector_with_no_trailing_cut():
    collector = StridedCollector(blocklen=16, cut_begin=4, cut_end=0)
    block = np.arange(16.0)

    # cut_end of zero must keep the block through to its end, not drop
    # everything (which is what a naive `[-0:]` style slice would do).
    assert np.array_equal(collector.cut(block), np.arange(4.0, 16.0))
    assert collector.stride == 4


def test_collector_returns_none_before_the_first_block():
    collector = StridedCollector(blocklen=16, cut_begin=4, cut_end=2)

    assert collector.get_block() is None
    collector.add(np.arange(5.0))
    assert collector.get_block() is None


def test_collector_accepts_data_in_arbitrary_sized_pieces():
    single = StridedCollector(blocklen=16, cut_begin=4, cut_end=2)
    piecemeal = StridedCollector(blocklen=16, cut_begin=4, cut_end=2)
    data = np.arange(40.0)

    single.add(data)
    for start in range(0, 40, 3):
        piecemeal.add(data[start : start + 3])

    # The caller has no control over how the reader chunks its input, so the
    # block boundaries must depend only on the total, not on the arrival
    # pattern.
    assert np.array_equal(single.get_block(), piecemeal.get_block())
    assert np.array_equal(single.get_block(), piecemeal.get_block())
