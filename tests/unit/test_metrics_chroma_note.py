"""Unit tests for the capture-notes record of the chroma correction.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The inverse-MTF chroma correction is written into the samples, so the
output's capture notes say what it was and what the burst read without
it: chroma_correction_note summarises the per-field record the decoder
keeps as it writes.
"""

import math

import pytest

from lddecode.metrics import chroma_correction_note

pytestmark = [pytest.mark.unit]

DB_PER_UNIT = 1.67   # NTSC's curve at the subcarrier


def fields(burst, strength, n=9):
    return [(burst, strength)] * n


def pairs(note):
    return dict(part.split("=", 1) for part in note.split("; "))


def test_the_correction_and_the_burst_without_it_are_recorded():
    note = pairs(chroma_correction_note(fields(20.0, 0.6), 20.0, DB_PER_UNIT, True))
    gain_db = 0.6 * DB_PER_UNIT

    assert note["chroma_correction"] == "auto"
    assert note["inverse_mtf_strength"] == "0.600 (0.600..0.600)"
    assert float(note["inverse_mtf_gain_at_fsc_db"]) == pytest.approx(gain_db, abs=0.005)
    assert float(note["median_burst_ire"]) == 20.0
    assert float(note["median_burst_ire_uncorrected"]) == pytest.approx(
        20.0 / 10 ** (gain_db / 20), abs=0.005)
    assert float(note["chroma_gain_to_nominal"]) == 1.0


def test_with_the_correction_off_the_burst_is_what_was_written():
    note = pairs(chroma_correction_note(fields(17.66, 0.0), 20.0, DB_PER_UNIT, False))

    assert note["chroma_correction"] == "off"
    assert "inverse_mtf_strength" not in note
    assert "median_burst_ire_uncorrected" not in note
    assert float(note["median_burst_ire"]) == 17.66
    assert float(note["chroma_gain_to_nominal"]) == pytest.approx(20.0 / 17.66, abs=1e-4)


def test_each_field_is_taken_back_under_its_own_strength():
    """The strength tracks the disc; a field decoded before the servo
    locked carries none of the correction."""
    record = [(16.0, 0.0)] * 3 + [(20.0, 1.0)] * 6
    note = pairs(chroma_correction_note(record, 20.0, 6.0206, True))

    assert float(note["median_burst_ire_uncorrected"]) == pytest.approx(10.0, abs=0.01)
    assert note["inverse_mtf_strength"] == "1.000 (0.000..1.000)"


def test_fields_with_no_usable_burst_are_left_out():
    record = fields(20.0, 0.5) + [(None, 0.5), (math.nan, 0.5), (3.0, 0.5)] * 4
    note = pairs(chroma_correction_note(record, 20.0, DB_PER_UNIT, True))
    assert float(note["median_burst_ire"]) == 20.0
    assert chroma_correction_note([(None, 0.0)], 20.0, DB_PER_UNIT, False) == (
        "chroma_correction=off")
