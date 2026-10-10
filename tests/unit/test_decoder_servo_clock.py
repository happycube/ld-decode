"""The calibration servos' clock in LDdecode._commit_entry.

The servos age their sample pools and rate-limit their adoptions by
position in the capture.  On a serial decode that position was fdoffset,
which at calibration time stands just past the field being calibrated;
the stage-2 pipeline, though, advances the chain up to its depth ahead of
the field it commits.  _commit_entry therefore sets the servos' own
position from the entry being committed, so a pipelined decode measures
ages and rate limits exactly as the serial one does.
"""

import types

import pytest

from lddecode.decoder import LDdecode

pytestmark = [pytest.mark.unit, pytest.mark.decode]

FIELD_LEN = 500.0


def stub_field():
    return types.SimpleNamespace(
        linelocs=[0.0] * 400, inlinelen=1.0, sync_confidence=100, valid=True)


def stub_decoder(redo_first=False):
    seen = []
    it = types.SimpleNamespace(
        fields_written=10, deemp_calibrated=True, pipeline_warm=True,
        output_lines=263, fieldstack=[None] * 4, _fields_since_redo=0,
        second_decode=1.0, _agc_adjusted_last=False, _job_engine=None,
        # the chain has run three fields past the entry being committed
        fdoffset=1000.0 + 4 * FIELD_LEN, _servo_pos=0,
        mtf_level=0.0, seen=seen,
    )

    def calibrate(f, metrics, redos):
        seen.append(it._servo_pos)
        return redo_first and redos == 0

    it.calibrate = calibrate
    it._flush_pipeline = lambda: None
    it.decodefield = lambda *a, **k: (stub_field(), FIELD_LEN + 20.0)
    it.decode_stage2 = lambda f: (None, None, {})
    it.commit_field = lambda *a, **k: "committed"
    return it


def entry():
    return {"f": stub_field(), "result": (None, None, {}), "start": 1000.0,
            "offset": FIELD_LEN, "independent": True, "initphase": False}


def test_servos_measure_from_the_field_being_committed():
    it = stub_decoder()
    assert LDdecode._commit_entry(it, entry()) == "committed"
    assert it.seen == [1000.0 + FIELD_LEN]


def test_a_redo_moves_the_servo_clock_with_the_field():
    it = stub_decoder(redo_first=True)
    LDdecode._commit_entry(it, entry())
    # the re-decoded field is 20 samples longer
    assert it.seen == [1000.0 + FIELD_LEN, 1000.0 + FIELD_LEN + 20.0]
    assert it._servo_pos == it.fdoffset
