"""The commit stage's repair of a field's colour-sequence position.

A field that cannot measure its fieldPhaseID from its own bursts falls
back at decode time to its anchor's position plus one (PAL; 1 without an
anchor, and always 1 on NTSC); commit_field then continues the committed
sequence instead.  An
anchor taken before its own field committed - in the worker that decoded
it, or a pipeline step ahead - still carries that field's pre-commit
position, so a threaded decode numbered the next fallback field off it
and broke the sequence where the serial decode, anchoring to the
committed field, did not.
"""

import types

import pytest

from lddecode.decoder import LDdecode
from lddecode.field import FieldAnchor

pytestmark = [pytest.mark.unit, pytest.mark.decode]


def anchor(startloc, phase):
    return FieldAnchor(startloc=startloc, end_lineloc=0.0, valid=True,
                       sync_confidence=100, skip_score=0.0,
                       is_first_field=False, field_phase_id=phase)


def commit(field, committed, phases=8):
    """commit_field up to its metadata, after the committed fields
    `committed` [(fileLoc, fieldPhaseID), ...]."""
    it = types.SimpleNamespace(
        fname_out="out", lastvalidfield={True: None, False: None},
        fieldinfo=[{"fileLoc": loc, "fieldPhaseID": p} for loc, p in committed],
        rf=types.SimpleNamespace(SysParams={"fieldPhases": phases}),
        # a filler request returns before anything is written
        buildmetadata=lambda f: ({}, True),
    )
    LDdecode.commit_field(it, field, None, None, audio_ready=True)
    return field.fieldPhaseID


def field(phase, fallback, anchor_=None):
    return types.SimpleNamespace(
        isFirstField=True, readloc=3000.0, fieldPhaseID=phase,
        phase_id_fallback=fallback, anchor=anchor_)


def test_without_an_anchor_a_fallback_continues_the_committed_sequence():
    assert commit(field(1, True), [(1000, 4), (2000, 5)]) == 6


def test_an_anchor_snapshotted_before_its_field_committed_is_corrected():
    """Field 2000 was numbered 1 in its worker and committed as 5."""
    f = field(2, True, anchor(2000.0, 1))
    assert commit(f, [(1000, 4), (2000, 5)]) == 6


def test_the_sequence_wraps_after_the_eighth_field():
    f = field(2, True, anchor(2000.0, 1))
    assert commit(f, [(2000, 8)]) == 1


def test_an_ntsc_fallback_continues_the_sequence_from_its_anchor():
    """NTSC's decode-time fallback ignores the anchor and says 1."""
    f = field(1, True, anchor(2000.0, 2))
    assert commit(f, [(1000, 1), (2000, 2)], phases=4) == 3
    f = field(1, True, anchor(2000.0, 4))
    assert commit(f, [(2000, 4)], phases=4) == 1


def test_an_anchor_that_is_not_the_field_committed_last_is_left_alone():
    """(a field skipped between them, say): the decode-time value stands."""
    f = field(3, True, anchor(1500.0, 2))
    assert commit(f, [(1000, 4), (2000, 5)]) == 3


def test_a_measured_position_is_never_rewritten():
    f = field(7, False, anchor(2000.0, 1))
    assert commit(f, [(2000, 5)]) == 7
    assert commit(field(7, False), [(2000, 5)]) == 7


def test_the_first_committed_field_keeps_its_own_fallback():
    assert commit(field(1, True, anchor(2000.0, 4)), []) == 1
