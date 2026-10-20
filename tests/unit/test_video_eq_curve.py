"""Unit tests for the video EQ curve and the EQ servo's reading of it.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

dsp.video_eq_db is the one place the multiburst EQ's curve is built: the
filter (RFDecode.build_video_eq) is 10 ** (dB / 20) of it over the FFT
bins, and the servo's bookkeeping (decoder.applied_eq_db) reads what a
pooled field was decoded under from it at each packet's frequency - not
from the anchor list, which says nothing about a packet between anchors.
"""

import numpy as np
import pytest

from lddecode.decoder import applied_eq_db
from lddecode.dsp import video_eq_db

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

ANCHORS = ((1.25e6, 0.0), (2.0e6, 0.6), (2.75e6, -0.4))
TOP = 20e6


def test_the_curve_passes_through_its_anchors_and_is_zero_past_the_release():
    for f, db in ANCHORS:
        assert video_eq_db(ANCHORS, f, TOP) == pytest.approx(db)
    assert video_eq_db(ANCHORS, 0.0, TOP) == 0.0
    assert np.all(video_eq_db(ANCHORS, np.array([3.25e6, 4e6, 19e6]), TOP) == 0.0)


def test_no_anchors_is_flat():
    np.testing.assert_array_equal(video_eq_db((), np.array([1e6, 5e6]), TOP), 0.0)


def test_a_packet_between_anchors_reads_the_curve_not_zero():
    """The 3.0 MHz packet past a 2.75 MHz last anchor: the curve is still
    releasing there, which a lookup in the anchor list read as 0."""
    at_3 = applied_eq_db(ANCHORS, 3.0e6)
    assert at_3 != 0.0
    assert at_3 == pytest.approx(float(video_eq_db(ANCHORS, 3.0e6, TOP)))


def test_the_bookkeeping_curve_does_not_depend_on_the_top_frequency():
    for f in (1.6e6, 2.4e6, 3.0e6, 3.2e6, 5e6):
        assert applied_eq_db(ANCHORS, f) == pytest.approx(
            float(video_eq_db(ANCHORS, f, TOP)), abs=1e-12)
    assert applied_eq_db((), 2e6) == 0.0
