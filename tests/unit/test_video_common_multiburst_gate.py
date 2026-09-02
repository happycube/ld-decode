"""
test_video_common_multiburst_gate - which measured packets are a multiburst

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

A sliding-window packet finder reports every sustained oscillation on the
line, and on a real disc that is more than the multiburst: National Gallery
of Art reports 6, 7 and 8 packets at different radii on one side.  The cases
here pin what ``match_multiburst_packets`` keeps and what it refuses, and
close with the same instability reproduced hermetically - a rendered NTC-7
combination that ``measure_ntc7_multiburst`` splits into seven, at four
noise levels.

No capture file is read.
"""

import numpy as np
import pytest

import vits_reference as vr
import vits_synth as vs
from video_common import (
    MULTIBURST_MATCH_TOLERANCE_MHZ,
    NTC7_MULTIBURST_FREQS,
    match_multiburst_packets,
    measure_ntc7_multiburst,
)

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

#: The nominal set every case here matches against, and a clean train that
#: matches it: measured frequencies a little off nominal, climbing, evenly
#: spaced along the line, all at the 50 IRE p-p the NTC-7 combination states.
NOMINALS = NTC7_MULTIBURST_FREQS
CLEAN = [(20.7, 0.512, 50.1), (24.8, 1.021, 49.8), (28.8, 2.014, 50.3),
         (32.9, 3.033, 49.6), (36.9, 3.596, 50.2), (40.9, 4.268, 49.4)]

#: The bar-to-pedestal step at the head of the line, as the finder reads it:
#: a half cycle at the low edge of the frequency search, at an amplitude
#: close to the real 0.5 MHz packet's.  Measured on National Gallery of Art.
LEADING_EDGE = (18.0, 0.467, 34.5)

#: The tail of the last packet, likewise: a low-amplitude fragment past the
#: end of the multiburst, at a frequency that varies field to field.
TRAILING_FRAGMENT = (42.9, 4.797, 9.8)


def test_a_clean_train_is_returned_unchanged():
    assert match_multiburst_packets(CLEAN, NOMINALS) == CLEAN


def test_a_leading_edge_peak_is_dropped():
    selected = match_multiburst_packets([LEADING_EDGE] + CLEAN, NOMINALS)
    assert selected == CLEAN


def test_a_trailing_fragment_is_dropped():
    selected = match_multiburst_packets(CLEAN + [TRAILING_FRAGMENT], NOMINALS)
    assert selected == CLEAN


def test_both_line_edge_artefacts_are_dropped_together():
    train = [LEADING_EDGE] + CLEAN + [TRAILING_FRAGMENT]
    assert match_multiburst_packets(train, NOMINALS) == CLEAN


def test_the_closer_of_two_candidates_wins_rather_than_the_first():
    # Both sit within tolerance of the 0.5 MHz nominal; only one is the
    # packet.  Matching greedily left to right would take the edge peak.
    train = [LEADING_EDGE] + CLEAN
    assert match_multiburst_packets(train, NOMINALS)[0] == CLEAN[0]


def test_a_merged_packet_pair_is_refused_rather_than_reported_as_six():
    # The inner-radius NGA fields where 3.0 and 3.58 MHz fuse into one read
    # at 3.77 MHz.  Six packets come back from the finder, so a count test
    # passes them; the fused one matches neither nominal well enough to fill
    # both, so a nominal is left unfilled and the field is refused.
    merged = [CLEAN[0], CLEAN[1], CLEAN[2], (35.0, 3.768, 25.7), CLEAN[5]]
    assert len(merged) < len(NOMINALS)
    assert match_multiburst_packets([LEADING_EDGE] + merged, NOMINALS) == []


def test_a_train_shorter_than_the_nominal_set_is_refused():
    assert match_multiburst_packets(CLEAN[:-1], NOMINALS) == []


def test_an_empty_nominal_set_matches_nothing():
    assert match_multiburst_packets(CLEAN, ()) == []


def test_frequencies_that_climb_but_miss_the_set_are_refused():
    # A PAL VBI data line reads as a climbing train of low frequencies.
    train = [(20.0 + 4.0 * i, 0.4 + 0.25 * i, 40.0) for i in range(6)]
    assert match_multiburst_packets(train, NOMINALS) == []


def test_a_packet_beyond_the_tolerance_refuses_the_whole_train():
    train = list(CLEAN)
    off = MULTIBURST_MATCH_TOLERANCE_MHZ * 1.1
    train[3] = (CLEAN[3][0], NOMINALS[3] + off, CLEAN[3][2])
    assert match_multiburst_packets(train, NOMINALS) == []
    # ... and stays matched just inside it, so the bound is the tolerance
    # and not something narrower.
    train[3] = (CLEAN[3][0], NOMINALS[3] + MULTIBURST_MATCH_TOLERANCE_MHZ * 0.9,
                CLEAN[3][2])
    assert len(match_multiburst_packets(train, NOMINALS)) == len(NOMINALS)


def test_a_train_that_does_not_climb_in_frequency_is_refused():
    # Same six frequencies, two of them swapped in time.  Every packet is
    # within tolerance of some nominal, so only the ordering rejects this.
    train = list(CLEAN)
    train[3], train[4] = ((CLEAN[3][0],) + CLEAN[4][1:],
                          (CLEAN[4][0],) + CLEAN[3][1:])
    assert match_multiburst_packets(train, NOMINALS) == []


def test_the_result_is_a_subsequence_of_the_input_in_order():
    train = [LEADING_EDGE] + CLEAN + [TRAILING_FRAGMENT]
    selected = match_multiburst_packets(train, NOMINALS)
    positions = [train.index(packet) for packet in selected]
    assert positions == sorted(positions)
    assert len(set(positions)) == len(positions)


@pytest.mark.parametrize("sigma_ire", [0.0, 1.0, 2.0, 4.0])
def test_a_rendered_ntc7_combination_gates_to_six_packets_under_noise(
        sigma_ire):
    """The instability, reproduced from synthesised arrays.

    The finder splits the combination's 5 us 0.5 MHz packet in two, so it
    reports seven at every noise level; the gate has to reduce that to the
    six the definition states, at the definition's own frequencies.
    """
    entry = vr.definition("ntsc-ntc7-combination")
    field = vs.make_field(entry.system, is_first_field=(entry.field == 1))
    line = vs.render_definition(field, entry)
    if sigma_ire:
        vs.add_noise(field, np.random.default_rng(12345), sigma_ire)

    found = measure_ntc7_multiburst(field, line=line)
    assert len(found) > len(NOMINALS), "the split this gate exists to absorb"

    selected = match_multiburst_packets(found, NOMINALS)
    assert len(selected) == len(NOMINALS)
    np.testing.assert_allclose([p[1] for p in selected], NOMINALS,
                               rtol=0.0, atol=0.05)
