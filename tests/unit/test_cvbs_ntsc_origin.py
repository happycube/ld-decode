"""Unit tests for where lddecode.cvbs.CVBSWriter puts an NTSC frame's origin.

The spec's stored frames are 0H-aligned: sample 0 is the first sampling
instant at or after 0H, so 0H falls in the sample before it.  The decoder
rotates each NTSC line to put the burst on the 4fsc lattice, which leaves
0H wherever the disc's SC/H puts it - 0.3 to 1.9 samples into the decoded
line on the test discs.  Copying the decoded lines straight through put
0H up to two samples late, and on the orthogonal NTSC lattice two samples
are 180 degrees of subcarrier: a spec reader took colour frame A for B.
The writer measures 0H on the first frame and starts every frame that many
whole samples into field A; dropout positions move with the samples.
"""

from unittest.mock import Mock

import numpy as np
import pytest

from lddecode.cvbs import CVBSWriter, CVBSParams_NTSC

pytestmark = [pytest.mark.unit, pytest.mark.format]

SPL = 910
FIELD = 263 * SPL           # the decoder writes 263 rows per NTSC field
BLANK = 240 * 64            # the writer's working domain (10-bit * 64)
TIP = 40 * 64               # a shallow sync tip, as discs have


def make_writer():
    w = CVBSWriter.__new__(CVBSWriter)
    w.system = "NTSC"
    w.params = CVBSParams_NTSC
    w.logger = None
    w.frames_written = 0
    w.dropout_rows = []
    w.blank16 = BLANK
    w._ntsc_shift = None
    w._ntsc_prev_tail = None
    w._to_spec_levels = lambda x, f: np.asarray(x, dtype=np.float64)
    w._measure_ntsc_lock = Mock()
    w._write_frame = Mock()
    w._collect_efm = Mock()
    w.push_audio = Mock()
    return w


def synced_field(h0, offset=0.0, seed=0, blank=BLANK):
    """A field whose line syncs fall (half amplitude) at h0 samples into
    each row, with a two-sample edge and a little noise; `offset` marks
    the samples so slices can be traced."""
    rng = np.random.default_rng(seed)
    n = np.arange(FIELD, dtype=np.float64)
    t = (n + SPL / 2) % SPL - SPL / 2           # samples from the row start
    edge = np.clip((t - (h0 - 1.0)) / 2.0, 0.0, 1.0)
    tail = np.clip((h0 + 66.0 - t) / 2.0, 0.0, 1.0)
    x = blank - (blank - TIP) * np.minimum(edge, tail)
    return x + rng.normal(0.0, 8.0, FIELD) + offset


@pytest.mark.parametrize("h0, shift", [(1.91, 2), (0.32, 1), (0.97, 1),
                                       (-0.3, 0), (2.4, 3)])
def test_the_shift_puts_0h_in_the_sample_before_sample_0(h0, shift):
    w = make_writer()
    assert w._ntsc_origin_shift(synced_field(h0)) == shift
    assert shift - 1 < h0 <= shift


def test_0h_is_found_against_the_disc_s_own_blanking_level():
    """ggv1016-side1 sits 20 codes above nominal blanking; halfway to it
    from the tip is a tenth of a sample from halfway to nominal, enough to
    take a 0H just inside a sample for one just past it."""
    w = make_writer()
    assert w._ntsc_origin_shift(synced_field(0.95, blank=260 * 64)) == 1


def emit(w, a, b):
    w._emit_frame((None, {}, a, None, None), (None, {}, b, None, None))
    return w._write_frame.call_args.args[0]


def test_a_frame_starts_the_shift_into_field_a_and_runs_on_into_field_b():
    w = make_writer()
    a = synced_field(1.91)
    b = synced_field(1.91, offset=1e6)

    frame = emit(w, a, b)

    assert w._ntsc_shift == 2
    assert len(frame) == CVBSParams_NTSC["frame_samples"]
    assert frame[0] == a[2]
    # field A's last row finishes on field B's first samples, and field
    # B's last row on its extra row (the next frame's first line)
    assert frame[263 * SPL - 2] == b[0]
    assert frame[-1] == b[262 * SPL + 1]


def test_the_shift_is_taken_once_and_kept():
    w = make_writer()
    emit(w, synced_field(1.91), synced_field(1.91))
    emit(w, synced_field(0.32), synced_field(0.32))
    assert w._ntsc_shift == 2


def test_a_negative_shift_starts_inside_the_previous_frame():
    w = make_writer()
    a1, b1 = synced_field(-1.4), synced_field(-1.4, offset=1e6)
    first = emit(w, a1, b1)
    assert w._ntsc_shift == -1
    # front porch before the first frame, the previous frame after it
    assert first[0] == BLANK and first[1] == a1[0]

    a2 = synced_field(-1.4, offset=2e6)
    second = emit(w, a2, synced_field(-1.4, offset=3e6))
    assert len(second) == CVBSParams_NTSC["frame_samples"]
    assert second[0] == b1[262 * SPL - 1] and second[1] == a2[0]


def dropouts(field_a=None, field_b=None, shift=2):
    w = make_writer()
    w._ntsc_shift = shift
    fi = [None if d is None else {"dropOuts": {
        "fieldLine": [d[0]], "startx": [d[1]], "endx": [d[2]]}}
        for d in (field_a, field_b)]
    w._collect_dropouts(0, *fi)
    return w.dropout_rows


def test_dropouts_move_with_the_samples():
    assert dropouts(field_a=(10, 100, 150)) == [(0, 9 * SPL + 98, 50, 100)]
    assert dropouts(field_b=(1, 50, 60)) == [(0, 263 * SPL + 48, 10, 100)]
    assert dropouts(field_a=(10, 100, 150), shift=-1) == [(0, 9 * SPL + 101, 50, 100)]


def test_a_dropout_from_before_the_first_sample_is_clipped_to_it():
    assert dropouts(field_a=(1, 0, 5)) == [(0, 0, 3, 100)]
    assert dropouts(field_a=(1, 0, 1)) == []
