"""Unit tests for lddecode.efm_score -- EFM T-value frame-sync scoring.

The scorer is the oracle every EFM demodulation change is judged by (see
docs-planning and analysis/efm_quality.py), so its own behaviour has to
be pinned exactly: a perfect stream must score 1.0/1.0, and each class
of injected damage -- a +/-1 T misquantisation, a corrupted sync pair, a
split or merged run -- must move exactly the metric it is supposed to
move and nothing else.

All streams are synthesised here from the frame structure itself
(IEC 60908 Clause 15: 588 channel bits per frame, sync = two 11T runs),
so every expected number is arithmetic, not measurement.
"""

import numpy as np
import pytest

from lddecode.efm_score import (
    FRAME_CHANNEL_BITS,
    frame_gaps,
    frame_length_error_counts,
    pack_t_conf,
    score_t_values,
    summarise_confidence,
    symbol_separation,
    unpack_t_conf,
    sync_pair_positions,
)

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

# One intact frame in T-values: the sync pair then filler runs (the
# merging bits guarantee even the run ending the sync pattern is >= 3T,
# so a legal frame never carries a run below 3).  11+11+3 + 56*10 + 3 = 588.
FRAME = [11, 11, 3] + [10] * 56 + [3]
assert sum(FRAME) == FRAME_CHANNEL_BITS


def perfect_stream(n_frames):
    """``n_frames`` intact frames as an int8 T-value array."""
    return np.array(FRAME * n_frames, dtype=np.int8)


# --- sync_pair_positions ----------------------------------------------------


def test_sync_pairs_found_at_every_frame_start():
    t = perfect_stream(20)

    positions = sync_pair_positions(t)

    assert np.array_equal(positions, np.arange(20) * len(FRAME))


def test_sync_pairs_three_elevens_count_once():
    # Three consecutive 11s contain two overlapping pairs but only one
    # sync: the greedy de-overlap must not double-count.
    t = np.array([3, 11, 11, 11, 3], dtype=np.int8)

    assert np.array_equal(sync_pair_positions(t), [1])


def test_sync_pairs_four_elevens_count_twice():
    # Two back-to-back syncs are two pairs; the de-overlap must not
    # swallow the second one.
    t = np.array([3, 11, 11, 11, 11, 3], dtype=np.int8)

    assert np.array_equal(sync_pair_positions(t), [1, 3])


def test_sync_pairs_none_in_a_pairless_stream():
    t = np.array([11, 3, 11, 4, 11], dtype=np.int8)

    assert sync_pair_positions(t).size == 0


def test_sync_pairs_empty_and_single_input():
    assert sync_pair_positions(np.zeros(0, dtype=np.int8)).size == 0
    assert sync_pair_positions(np.array([11], dtype=np.int8)).size == 0


# --- frame_gaps -------------------------------------------------------------


def test_frame_gaps_match_direct_summation():
    rng = np.random.default_rng(12345)
    t = rng.integers(3, 12, 500).astype(np.int8)
    positions = np.array([7, 100, 233, 499])

    gaps = frame_gaps(t, positions)

    expected = [int(t[a:b].sum()) for a, b in zip(positions[:-1], positions[1:])]
    assert np.array_equal(gaps, expected)


def test_frame_gaps_of_a_perfect_stream_are_all_588():
    t = perfect_stream(30)

    gaps = frame_gaps(t, sync_pair_positions(t))

    assert gaps.size == 29
    assert np.all(gaps == FRAME_CHANNEL_BITS)


def test_frame_gaps_with_fewer_than_two_positions():
    t = perfect_stream(1)
    assert frame_gaps(t, np.array([0])).size == 0
    assert frame_gaps(t, np.zeros(0, dtype=np.int64)).size == 0


# --- score_t_values: the perfect stream -------------------------------------


def test_perfect_stream_scores_one_point_zero():
    score = score_t_values(perfect_stream(50))

    # Exact by construction: 50 frames of 588 bits carry 50 syncs and
    # 49 gaps of exactly 588.  These are equalities, not tolerances.
    assert score.sync_rate == 1.0
    assert score.frame_588_fraction == 1.0
    assert score.invalid_t_fraction == 0.0
    assert score.n_sync_pairs == 50
    assert score.n_gaps == 49
    assert score.channel_bits == 50 * FRAME_CHANNEL_BITS
    assert score.expected_frames == 50.0


def test_perfect_stream_t_histogram():
    score = score_t_values(perfect_stream(10))

    # Per frame: two 3s, fifty-six 10s, two 11s; nothing else.
    assert score.t_counts[3] == 20
    assert score.t_counts[10] == 560
    assert score.t_counts[11] == 20
    assert score.t_counts.sum() == score.n_t_values
    assert score.n_t_out_of_histogram == 0


# --- score_t_values: injected damage ----------------------------------------


def test_one_t_error_fails_exactly_one_frame():
    t = perfect_stream(50)
    # A +1 misquantisation in the middle of frame 10 (on a filler run,
    # away from any sync pair): that frame's gap becomes 589.
    victim = 10 * len(FRAME) + 30
    t[victim] += 1

    score = score_t_values(t)

    assert score.n_sync_pairs == 50
    assert score.n_frames_588 == 48
    assert score.frame_588_fraction == pytest.approx(48 / 49)
    errors, counts = frame_length_error_counts(score.gap_bits)
    assert dict(zip(errors.tolist(), counts.tolist())) == {0: 48, 1: 1}


def test_minus_one_t_error_shows_as_a_short_frame():
    t = perfect_stream(50)
    t[20 * len(FRAME) + 30] -= 1

    score = score_t_values(t)

    errors, counts = frame_length_error_counts(score.gap_bits)
    assert dict(zip(errors.tolist(), counts.tolist())) == {-1: 1, 0: 48}


def test_corrupted_sync_merges_two_gaps():
    t = perfect_stream(50)
    # Damage the first 11 of frame 25's sync pair: that sync vanishes,
    # and the gaps either side of it merge into one of 2*588 - 1 bits
    # (the stream also lost one channel bit to the damage itself).
    t[25 * len(FRAME)] = 10

    score = score_t_values(t)

    assert score.n_sync_pairs == 49
    assert score.n_gaps == 48
    errors, counts = frame_length_error_counts(score.gap_bits)
    assert dict(zip(errors.tolist(), counts.tolist())) == {
        0: 47,
        FRAME_CHANNEL_BITS - 1: 1,
    }
    # 49 syncs against 49.99.. expected frames (one bit short of 50 full
    # frames' worth of channel bits).
    assert score.sync_rate == pytest.approx(
        49 / ((50 * FRAME_CHANNEL_BITS - 1) / FRAME_CHANNEL_BITS)
    )


def test_split_run_preserves_framing():
    # A 10 split into 5+5 keeps the channel-bit count, so framing is
    # untouched -- exactly the property museld-style legalisation relies
    # on.  Only the T histogram may change.
    t = perfect_stream(30).tolist()
    victim = 15 * len(FRAME) + 30
    assert t[victim] == 10
    t = t[:victim] + [5, 5] + t[victim + 1 :]

    score = score_t_values(np.array(t, dtype=np.int8))

    assert score.sync_rate == 1.0
    assert score.frame_588_fraction == 1.0
    assert score.t_counts[5] == 2
    assert score.t_counts[10] == 30 * 56 - 1


def test_merged_runs_that_lose_bits_shorten_the_frame():
    # Two 10s replaced by one 11 loses 9 channel bits: the frame length
    # error must say -9 (and the extra 11 must not fake a sync, since it
    # is not adjacent to another 11).
    t = perfect_stream(30).tolist()
    victim = 8 * len(FRAME) + 30
    t = t[:victim] + [11] + t[victim + 2 :]

    score = score_t_values(np.array(t, dtype=np.int8))

    assert score.n_sync_pairs == 30
    errors, counts = frame_length_error_counts(score.gap_bits)
    assert dict(zip(errors.tolist(), counts.tolist())) == {-9: 1, 0: 28}


def test_invalid_t_values_are_counted_but_still_summed():
    # A 2 (below T3) and a 13 (above T11) among legal runs: both count
    # into invalid_t_fraction, both still contribute channel bits.
    t = np.array([4, 2, 13, 5], dtype=np.int8)

    score = score_t_values(t)

    assert score.invalid_t_fraction == pytest.approx(2 / 4)
    assert score.channel_bits == 24
    assert score.t_counts[2] == 1
    assert score.t_counts[13] == 1


def test_t_values_outside_the_histogram_are_reported():
    t = np.array([4, 100, 5, -3], dtype=np.int16)

    score = score_t_values(t)

    assert score.n_t_out_of_histogram == 2
    assert score.t_counts.sum() == 2
    # Out-of-histogram values are necessarily invalid runs too.
    assert score.invalid_t_fraction == pytest.approx(2 / 4)


def test_empty_stream_scores_zero_without_dividing():
    score = score_t_values(np.zeros(0, dtype=np.int8))

    assert score.n_t_values == 0
    assert score.sync_rate == 0.0
    assert score.frame_588_fraction == 0.0
    assert score.invalid_t_fraction == 0.0


def test_syncless_stream_scores_zero_sync_rate():
    rng = np.random.default_rng(54321)
    # Runs of 3..10 only: plenty of channel bits, no 11 pairs.
    t = rng.integers(3, 11, 2000).astype(np.int8)

    score = score_t_values(t)

    assert score.n_sync_pairs == 0
    assert score.sync_rate == 0.0
    assert score.frame_588_fraction == 0.0
    assert score.expected_frames > 0


def test_score_does_not_mutate_its_input():
    t = perfect_stream(5)
    before = t.copy()

    score_t_values(t)

    assert np.array_equal(t, before)


# --- frame_length_error_counts ----------------------------------------------


def test_error_counts_of_no_gaps_are_empty():
    errors, counts = frame_length_error_counts(np.zeros(0, dtype=np.int64))
    assert errors.size == 0
    assert counts.size == 0


# --- summarise_confidence ---------------------------------------------------


def test_confidence_summary_statistics():
    conf = np.array([255, 255, 0, 100], dtype=np.uint8)

    summary = summarise_confidence(conf, low_threshold=128)

    assert summary.n_values == 4
    assert summary.mean == pytest.approx((255 + 255 + 0 + 100) / 4)
    assert summary.fraction_low == pytest.approx(2 / 4)


def test_confidence_summary_threshold_is_exclusive():
    conf = np.array([128, 127], dtype=np.uint8)

    summary = summarise_confidence(conf, low_threshold=128)

    assert summary.fraction_low == pytest.approx(1 / 2)


def test_confidence_summary_of_empty_stream():
    summary = summarise_confidence(np.zeros(0, dtype=np.uint8))

    assert summary.n_values == 0
    assert summary.mean == 0.0
    assert summary.fraction_low == 0.0


# --- symbol_separation ------------------------------------------------------


def nrzi_waveform(tvals, period, amplitude=10000.0, jitter=None, rng=None):
    """NRZI waveform whose crossings sit at cumsum(tvals) * period samples.

    Linear two-sample ramps through each crossing, so the interpolated
    crossing positions recover the construction exactly; ``jitter`` (in
    samples, per crossing) displaces them.
    """
    times = np.cumsum(np.asarray(tvals, dtype=np.float64)) * period
    if jitter is not None:
        times = times + rng.normal(0.0, jitter, times.size)
    length = int(times[-1]) + 2
    out = np.empty(length)
    polarity = 1.0
    prev = 0.0
    for cross in times:
        lo, hi = int(np.ceil(prev)), int(np.ceil(cross))
        n = np.arange(lo, min(hi, length))
        ramp = np.minimum(np.minimum(n - prev, cross - n), 1.0)
        out[n] = polarity * amplitude * np.clip(ramp, -1.0, 1.0)
        polarity, prev = -polarity, cross
    out[int(np.ceil(prev)) :] = polarity * amplitude
    return out


def test_symbol_separation_of_an_on_grid_waveform_is_zero():
    rng = np.random.default_rng(12345)
    tvals = rng.integers(3, 12, 3000)

    sep = symbol_separation(nrzi_waveform(tvals, period=9.2554), 40e6)

    # Crossings on the exact grid: interpolation error only (the ramps are
    # linear through zero, so recovered positions are float-exact).
    assert sep.n_intervals == tvals.size - 1
    assert sep.rms_bits < 1e-3
    assert sep.bit_period == pytest.approx(9.2554, rel=1e-4)


def test_symbol_separation_grows_with_crossing_jitter():
    rng = np.random.default_rng(12345)
    tvals = rng.integers(3, 12, 3000)
    period = 40e6 / 4321800.0

    small = symbol_separation(
        nrzi_waveform(tvals, period, jitter=0.5, rng=np.random.default_rng(1)), 40e6
    )
    large = symbol_separation(
        nrzi_waveform(tvals, period, jitter=2.0, rng=np.random.default_rng(1)), 40e6
    )

    # Jitter sigma in bit units is sigma/period; sqrt(2) for a difference
    # of two jittered crossings.  The metric must track it and order the
    # two waveforms correctly -- this ordering is the whole use case
    # (ranking front-end filters).
    assert small.rms_bits == pytest.approx(0.5 / period * np.sqrt(2), rel=0.15)
    assert large.rms_bits > 2.5 * small.rms_bits


def test_symbol_separation_ignores_a_disc_speed_offset():
    rng = np.random.default_rng(12345)
    tvals = rng.integers(3, 12, 3000)

    on_speed = symbol_separation(nrzi_waveform(tvals, period=9.2554), 40e6)
    fast = symbol_separation(nrzi_waveform(tvals, period=9.2554 * 0.98), 40e6)

    # A 2% speed offset moves every interval off the nominal grid by up to
    # 0.22 bits, which would swamp the ISI signal the metric exists to
    # see; the refined period estimate must absorb it.
    assert fast.rms_bits < 1e-3
    assert fast.bit_period == pytest.approx(9.2554 * 0.98, rel=1e-4)
    assert abs(fast.rms_bits - on_speed.rms_bits) < 1e-3


def test_symbol_separation_of_a_dead_waveform():
    sep = symbol_separation(np.zeros(1000), 40e6)

    assert sep.n_intervals == 0
    assert np.isnan(sep.rms_bits)


# --- pack_t_conf / unpack_t_conf (T_VALUE_CONF_U8) --------------------------


def test_pack_unpack_roundtrip_preserves_t_and_quantises_confidence():
    rng = np.random.default_rng(12345)
    t = rng.integers(3, 12, 500).astype(np.int8)
    conf = rng.integers(0, 256, 500).astype(np.uint8)

    packed = pack_t_conf(t, conf)
    t_back, conf_back = unpack_t_conf(packed)

    # T-values are exact (they fit the low nibble); confidence keeps its
    # top four bits (stored inverted as doubt), re-expanded so 255 maps
    # back to 255 and thresholds carry over between the 8-bit and packed
    # representations.
    assert packed.dtype == np.uint8
    assert np.array_equal(t_back, t)
    assert np.array_equal(conf_back, (conf >> 4).astype(np.uint8) * 17)


def test_pack_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        pack_t_conf(np.full(5, 7, np.int8), np.zeros(4, np.uint8))


def test_a_plain_stream_unpacks_as_full_confidence():
    t = perfect_stream(3)

    t_back, conf_back = unpack_t_conf(t)

    # The high nibble stores doubt, so a legacy T_VALUE_U8 stream is
    # byte-identical to a packed stream with zero doubt everywhere and
    # unpacks - correctly - as fully trusted.
    assert np.array_equal(t_back, t)
    assert conf_back.min() == 255


def test_fully_confident_packing_is_byte_identical_to_the_plain_stream():
    t = perfect_stream(3)

    packed = pack_t_conf(t, np.full(t.size, 255, np.uint8))

    # The point of the inverted (doubt) sense: a fully-confident packed
    # stream IS the plain stream, so legacy consumers only ever see
    # out-of-range bytes on symbols the demodulator actually doubted.
    assert np.array_equal(packed, t.astype(np.uint8))


def test_packing_does_not_change_the_score():
    t = perfect_stream(20)
    conf = np.full(t.size, 128, np.uint8)

    t_back, _ = unpack_t_conf(pack_t_conf(t, conf))
    packed_score = score_t_values(t_back)
    plain_score = score_t_values(t)

    # The whole point of the low-nibble layout: consumers that mask get
    # exactly the stream they had before.
    assert packed_score.sync_rate == plain_score.sync_rate
    assert packed_score.frame_588_fraction == plain_score.frame_588_fraction
