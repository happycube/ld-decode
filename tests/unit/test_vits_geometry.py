"""
test_vits_geometry - microsecond to sample mapping inside a CVBS field

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The two coordinate problems the module exists to solve, checked separately:
the non-line-locked PAL row lattice, and the position of 0H inside a row.
Every field is synthesised (see tests/vits_synth.py), so a conversion is
checked against a marker deliberately placed at a known time rather than
against a previous run of itself.
"""

import numpy as np
import pytest

import vits_geometry as vg
import vits_synth as vs
from video_common import CaptureParams, VideoField

pytestmark = [pytest.mark.unit, pytest.mark.dsp, pytest.mark.vits]

SYSTEMS = ("NTSC", "PAL")

#: Origins to sweep: the row boundary itself, and the two a real decode was
#: measured at (NTSC +1.95 samples, PAL -0.98 samples).
ORIGINS = (0.0, 1.95, -0.98)


# ---------------------------------------------------------------------------
# The PAL lattice
# ---------------------------------------------------------------------------

def test_ntsc_rows_sit_exactly_on_the_line_grid():
    field = vs.make_field("NTSC")
    for line in range(1, field.params.field_height + 1):
        assert vg.row_lattice_offset(field, line) == 0.0


@pytest.mark.parametrize("is_first_field", [True, False])
def test_pal_row_offsets_stay_inside_one_sample(is_first_field):
    field = vs.make_field("PAL", is_first_field=is_first_field)
    offsets = [vg.row_lattice_offset(field, line)
               for line in range(1, field.params.field_height + 1)]
    assert all(0.0 <= offset < 1.0 for offset in offsets)
    # Not line locked: 709379/625 leaves a different remainder on most rows.
    assert len(set(round(offset, 6) for offset in offsets)) > 100


def test_pal_row_offsets_are_not_a_multiple_of_the_row_width():
    # The failure this phase exists to prevent: resolving a window from
    # line * 1135 instead of from the row's own lattice start.  The two
    # agree only on the first row and part company from the second.
    field = vs.make_field("PAL")
    naive = np.arange(field.params.field_height) * 1135
    drift = np.asarray(field.cvbs_row_starts) - naive
    assert drift[0] == 0
    assert drift[1] == 1
    assert drift[-1] == 2
    # Two whole samples over a field: a 0.4 us pulse is only seven samples
    # wide, so this is not a rounding detail.
    assert drift.max() * 2 > 0.4 * field.params.sample_rate_mhz / 2


def test_a_field_without_row_starts_is_refused():
    params = CaptureParams.for_cvbs("PAL")
    field = VideoField(np.zeros(params.field_samples), 0, params,
                       {"field_id": 0, "is_first_field": True,
                        "field_phase_id": 1})
    with pytest.raises(ValueError, match="cvbs_row_starts"):
        vg.row_lattice_offset(field, 19)


def test_a_line_outside_the_field_is_refused():
    field = vs.make_field("PAL")
    with pytest.raises(ValueError, match="outside"):
        vg.row_lattice_offset(field, field.params.field_height + 1)


@pytest.mark.parametrize("system", SYSTEMS)
@pytest.mark.parametrize("line", [1, 19, 20, 313])
@pytest.mark.parametrize("marker_us", [12.0, 30.5, 47.25])
def test_a_marker_is_recovered_within_half_a_sample(system, line, marker_us):
    """The phase's stated acceptance for the lattice arithmetic."""
    field = vs.make_field(system)
    if line > field.params.field_height:
        pytest.skip(f"{system} fields have {field.params.field_height} lines")

    # A single-sample spike at a known time, placed through the synth's own
    # geometry, which is written out independently of FieldGeometry.
    index = int(round(vs.sample_of(field, line, marker_us)))
    field.dspicture[(line - 1) * field.params.field_width + index] += 500.0

    geom = vg.FieldGeometry(field, origin_samples=0.0)
    assert abs(geom.sample(line, marker_us) - index) <= 0.5


def test_windows_move_with_the_row_across_a_pal_field():
    # Over 313 rows the lattice slips two whole samples, so a window that
    # ignored the offset would drift off a 0.4 us pulse entirely.
    field = vs.make_field("PAL")
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    drift = [geom.sample(line, 26.0) - (26.0 * geom.fs_mhz)
             for line in (1, 100, 200, 313)]
    assert min(drift) < -0.5 < 0.0
    assert max(drift) <= 0.0


# ---------------------------------------------------------------------------
# Where 0H is
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("system", SYSTEMS)
@pytest.mark.parametrize("origin", ORIGINS + (3.0,))
def test_the_sync_origin_is_recovered_from_the_capture(system, origin):
    field = vs.make_field(system, origin_samples=origin)
    found = vg.measure_sync_origin(field)
    assert found is not None
    measured, scatter = found
    assert measured == pytest.approx(origin, abs=0.05)
    assert scatter < 0.2


def test_a_field_with_no_sync_reports_no_origin():
    field = vs.make_field("PAL", with_sync=False)
    assert vg.measure_sync_origin(field) is None


def test_a_geometry_falls_back_to_the_row_boundary_and_says_so():
    field = vs.make_field("NTSC", with_sync=False)
    geom = vg.FieldGeometry(field)
    assert geom.origin_measured is False
    assert geom.origin_samples == 0.0


def test_a_geometry_reports_a_measured_origin():
    field = vs.make_field("NTSC", origin_samples=1.95)
    geom = vg.FieldGeometry(field)
    assert geom.origin_measured is True
    assert geom.origin_samples == pytest.approx(1.95, abs=0.05)


def test_a_window_off_the_end_of_a_row_is_refused():
    field = vs.make_field("NTSC")
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    with pytest.raises(ValueError, match="outside"):
        geom.bounds(19, 200.0, 210.0)


def test_a_row_slice_ignores_the_alignment():
    # The back porch is defined by sample index, so it must not move when a
    # definition is slid onto a disc that inserted it off the stated timing.
    field = vs.make_field("NTSC", origin_samples=0.0)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    plain = geom.row_slice(19, 120, 130)
    slid = geom.aligned(-2.0).row_slice(19, 120, 130)
    assert np.array_equal(plain, slid)
