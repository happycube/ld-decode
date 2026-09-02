"""
efm_score - frame-sync quality scoring for EFM T-value streams

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Pure, I/O-free scoring of the run-length (T) values ld-decode writes to
``.efm``: locates T11-T11 frame-sync pairs, measures the channel-bit
distance between them, and summarises how much of the stream frames up
correctly.  Consumed by ``analysis/efm_quality.py`` (the CTest oracle)
and usable directly against any int T-value array.

Every function here takes NumPy arrays and returns NumPy arrays or plain
numbers; none of them reads a file, and none of them mutates its input.
All returned arrays are freshly allocated copies.

Background (why the stream is scoreable without a downstream decoder):

- IEC 60908 Clause 15 / IEC 60857 Section 10: EFM channel data is
  run-length limited to runs of 3 to 11 channel bits (T3-T11).
- IEC 60908 Clause 15: every EFM frame is exactly 588 channel bits.
- IEC 60908 Figure 15: the frame sync pattern is 100000000001000000000010,
  two successive 11T runs (followed by a 2T ending the pattern) - a
  sequence the (2,10) RLL code guarantees cannot occur anywhere else in
  an undamaged frame.

So in a perfect T stream every frame starts with an 11,11 pair and
successive pair starts are exactly 588 channel bits apart.  Deviations
measure demodulation damage directly: a +/-1 T misquantisation shifts a
frame length off 588, a missed sync doubles a gap, an invalid run (<3 or
>11) marks a decision the demodulator had to clamp or got wrong.

Note for gapped discs (BBC Domesday / AIV): those discs interleave EFM
sections with analogue-audio-only or silent sections, and ld-decode
emits (garbage) T-values for the gaps too, so a whole-capture sync rate
is bounded below 1.0 by the disc layout, not by the demodulator.  Scores
on such captures are comparable against a baseline of the same capture,
not against 1.0.
"""

from dataclasses import dataclass

import numpy as np

# IEC 60908 Clause 15: 588 channel bits per EFM frame.
FRAME_CHANNEL_BITS = 588

# IEC 60908 Clause 15: run-length limits of the (2,10) RLL channel code.
T_MIN = 3
T_MAX = 11

# IEC 60908 Figure 15: the frame sync pattern starts with two 11T runs.
SYNC_RUN_LENGTH = 11

# T histogram width: bins 0..15 cover everything an int8 T stream from
# the current or any planned demodulator can carry (legal 3..11 plus
# margin to see illegal values); values outside are counted separately.
T_HISTOGRAM_BINS = 16


@dataclass(frozen=True)
class EFMScore:
    """Frame-sync quality summary of one T-value stream.

    All counts are in T-values or channel bits as named; rates are
    dimensionless fractions.  ``gap_bits`` is one entry per pair of
    successive syncs (the channel-bit distance between their starts;
    588 when the frame between them is intact).
    """

    n_t_values: int  # T-values scored
    channel_bits: int  # sum of all T-values (channel bits)
    expected_frames: float  # channel_bits / 588
    n_sync_pairs: int  # T11-T11 pairs found
    sync_rate: float  # n_sync_pairs / expected_frames (0.0 if no bits)
    n_gaps: int  # successive-sync gaps measured
    n_frames_588: int  # gaps of exactly 588 channel bits
    frame_588_fraction: float  # n_frames_588 / n_gaps (0.0 if no gaps)
    invalid_t_fraction: float  # fraction of T-values outside 3..11
    gap_bits: np.ndarray  # int64, channel bits between successive syncs
    t_counts: np.ndarray  # int64[16], count of each T-value 0..15
    n_t_out_of_histogram: int  # T-values outside 0..15 (all invalid)


@dataclass(frozen=True)
class ConfidenceSummary:
    """Summary of a per-T-value confidence stream (``.efmc`` payload).

    Confidence is uint8, 255 = full trust (see ``efm_pll.EFM_PLL``).
    """

    n_values: int
    mean: float  # arithmetic mean, 0..255
    fraction_low: float  # fraction strictly below the threshold


def sync_pair_positions(t_values):
    """Indices where a T11-T11 frame-sync pair starts.

    ``t_values`` is a 1-D integer array (any int dtype).  Returns a fresh
    int64 array of the indices ``i`` with ``t[i] == t[i+1] == 11``,
    counting overlapping pairs greedily left to right: a run of three
    11s yields one pair, four 11s (two back-to-back syncs) yield two.
    """
    t = np.asarray(t_values)
    if t.size < 2:
        return np.zeros(0, dtype=np.int64)

    pair = (t[:-1] == SYNC_RUN_LENGTH) & (t[1:] == SYNC_RUN_LENGTH)
    idx = np.nonzero(pair)[0].astype(np.int64)
    if idx.size == 0:
        return idx

    # Greedy de-overlap: drop a pair start that reuses the second 11 of
    # the pair just kept.  Runs of adjacent starts are rare (three or
    # more consecutive 11s are illegal channel data), so the loop is
    # over a handful of entries even in a badly damaged stream.
    keep = np.ones(idx.size, dtype=bool)
    last_kept = idx[0]
    for k in range(1, idx.size):
        if idx[k] == last_kept + 1:
            keep[k] = False
        else:
            last_kept = idx[k]
    return idx[keep]


def frame_gaps(t_values, positions):
    """Channel-bit distance between successive sync-pair starts.

    ``positions`` are indices into ``t_values`` (as returned by
    ``sync_pair_positions``, in ascending order).  Returns a fresh int64
    array of ``len(positions) - 1`` sums: entry ``k`` is the total
    channel bits of ``t_values[positions[k] : positions[k+1]]`` - 588
    for an intact frame.
    """
    t = np.asarray(t_values, dtype=np.int64)
    pos = np.asarray(positions, dtype=np.int64)
    if pos.size < 2:
        return np.zeros(0, dtype=np.int64)

    cumulative = np.concatenate((np.zeros(1, dtype=np.int64), np.cumsum(t)))
    return np.diff(cumulative[pos])


def frame_length_error_counts(gap_bits):
    """Histogram of frame-length errors in channel bits.

    Returns ``(errors, counts)``: the distinct values of
    ``gap_bits - 588`` in ascending order and how often each occurs,
    both fresh int64 arrays.  A perfect stream yields ``([0], [n])``.
    """
    gaps = np.asarray(gap_bits, dtype=np.int64)
    if gaps.size == 0:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    errors, counts = np.unique(gaps - FRAME_CHANNEL_BITS, return_counts=True)
    return errors.astype(np.int64), counts.astype(np.int64)


def score_t_values(t_values):
    """Score one T-value stream; returns an :class:`EFMScore`.

    ``t_values`` is a 1-D integer array of run lengths (nominally int8,
    legal values 3..11).  ``sync_rate`` is the fraction of the frame
    positions the stream's total channel-bit count implies that actually
    carry a T11-T11 pair; it can exceed 1.0 if corruption fakes extra
    pairs.  ``frame_588_fraction`` is the fraction of successive-sync
    gaps that are exactly 588 channel bits.  Both are 0.0 (not NaN) when
    the stream is too short to measure them.
    """
    t = np.asarray(t_values)
    n = int(t.size)
    if n == 0:
        empty = np.zeros(0, dtype=np.int64)
        return EFMScore(
            n_t_values=0,
            channel_bits=0,
            expected_frames=0.0,
            n_sync_pairs=0,
            sync_rate=0.0,
            n_gaps=0,
            n_frames_588=0,
            frame_588_fraction=0.0,
            invalid_t_fraction=0.0,
            gap_bits=empty,
            t_counts=np.zeros(T_HISTOGRAM_BINS, dtype=np.int64),
            n_t_out_of_histogram=0,
        )

    t64 = t.astype(np.int64)
    channel_bits = int(t64.sum())
    expected_frames = channel_bits / FRAME_CHANNEL_BITS

    positions = sync_pair_positions(t)
    gaps = frame_gaps(t, positions)
    n_frames_588 = int(np.count_nonzero(gaps == FRAME_CHANNEL_BITS))

    in_histogram = (t64 >= 0) & (t64 < T_HISTOGRAM_BINS)
    t_counts = np.bincount(t64[in_histogram], minlength=T_HISTOGRAM_BINS)
    n_out = n - int(np.count_nonzero(in_histogram))
    n_invalid = n - int(np.count_nonzero((t64 >= T_MIN) & (t64 <= T_MAX)))

    return EFMScore(
        n_t_values=n,
        channel_bits=channel_bits,
        expected_frames=expected_frames,
        n_sync_pairs=int(positions.size),
        sync_rate=(positions.size / expected_frames) if channel_bits else 0.0,
        n_gaps=int(gaps.size),
        n_frames_588=n_frames_588,
        frame_588_fraction=(n_frames_588 / gaps.size) if gaps.size else 0.0,
        invalid_t_fraction=n_invalid / n,
        gap_bits=gaps,
        t_counts=t_counts.astype(np.int64),
        n_t_out_of_histogram=n_out,
    )


def summarise_confidence(confidence, low_threshold=128):
    """Summarise a per-T-value confidence stream (``.efmc`` payload).

    ``confidence`` is a 1-D uint8-valued array, 255 = full trust;
    ``low_threshold`` is the exclusive lower bound of "trusted" - values
    strictly below it count into ``fraction_low``.  Returns a
    :class:`ConfidenceSummary`; an empty stream summarises to zeros.
    """
    conf = np.asarray(confidence)
    if conf.size == 0:
        return ConfidenceSummary(n_values=0, mean=0.0, fraction_low=0.0)
    conf64 = conf.astype(np.float64)
    return ConfidenceSummary(
        n_values=int(conf.size),
        mean=float(conf64.mean()),
        fraction_low=float(np.count_nonzero(conf64 < low_threshold) / conf.size),
    )
