"""Unit tests for the per-field VBI codes written to the .tbc.db.

vbi0/vbi1/vbi2 are lines 16/17/18.  The list used to drop lines with no code,
so on the common CAV layout (nothing on line 16, the picture number on 17 and
18) the picture number landed in vbi0 and vbi2 was zero.
"""

import pytest

from lddecode.decoder import vbi_line_codes

pytestmark = [pytest.mark.unit, pytest.mark.decode]


def test_a_missing_line_16_keeps_the_others_in_place():
    assert vbi_line_codes([None, 0xF01234, 0xF01234]) == [0, 0xF01234, 0xF01234]


def test_every_line_present_is_passed_through():
    assert vbi_line_codes([0x8BA000, 0xF01234, 0xF01234]) == [0x8BA000, 0xF01234, 0xF01234]


def test_no_codes_gives_an_all_zero_row():
    codes = vbi_line_codes([None, None, None])

    assert codes == [0, 0, 0]
    assert not any(codes)  # _write_field_db writes no vbi row for it
