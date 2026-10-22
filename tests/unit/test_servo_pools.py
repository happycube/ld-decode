"""Unit tests for decoder.pool_reading, the servos' shared sample pool.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The committed decode goes back over every field the calibration pass read,
and a redo brings a field back again; either way a field's reading must
replace the one it already has, wherever that sits in the pool, or the
opening fields count twice once writing begins.
"""

import pytest

from lddecode.decoder import pool_reading

pytestmark = [pytest.mark.unit, pytest.mark.decode]


def test_a_new_field_is_appended():
    pool = pool_reading([(10, "a"), (20, "b")], (30, "c"), keep=8)
    assert pool == [(10, "a"), (20, "b"), (30, "c")]


def test_the_last_field_again_replaces_its_reading():
    pool = pool_reading([(10, "a"), (20, "b")], (20, "B"), keep=8)
    assert pool == [(10, "a"), (20, "B")]


def test_an_earlier_field_again_replaces_its_reading_where_it_stands():
    """The committed decode revisiting the calibration pass's fields."""
    pool = [(10, "a"), (20, "b"), (30, "c")]
    for loc, reading in ((10, "A"), (20, "B"), (30, "C")):
        pool = pool_reading(pool, (loc, reading), keep=8)
    assert pool == [(10, "A"), (20, "B"), (30, "C")]


def test_the_pool_keeps_its_newest_entries():
    pool = []
    for loc in range(5):
        pool = pool_reading(pool, (loc, loc), keep=3)
    assert pool == [(2, 2), (3, 3), (4, 4)]
