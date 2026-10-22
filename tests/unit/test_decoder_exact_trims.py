"""Tracking trims under --exact-speculation.

A dead-band-sized servo trim (video EQ, inverse-MTF strength, the
multiburst ceiling) applies from the next field on: the field being
calibrated keeps the parameters it was decoded under.  The default decode
tolerates what was already decoded ahead under the old parameters; an
exact decode discards it once the calibrated field has committed.  Exact
mode used to redo the calibrated field too, so the flag changed a serial
decode's output and -t N --exact-speculation matched only
-t 1 --exact-speculation, not plain -t 1.
"""

import logging
import types

import pytest

from lddecode import utils_logging as logs
from lddecode.decoder import LDdecode

pytestmark = [pytest.mark.unit, pytest.mark.decode, pytest.mark.parallel]

FIELD_LEN = 500.0

APPLIED_EQ = ((1.0e6, 0.0), (2.0e6, 0.0))
#: a full dB from what is applied at 2 MHz: past the EQ's dead-band
TRIMMED_EQ = ((1.0e6, 0.0), (2.0e6, 1.0))


@pytest.fixture(autouse=True)
def quiet_logger(monkeypatch):
    """An adoption logs; no decode has set the logger up."""
    monkeypatch.setattr(logs, "logger", logging.getLogger("test-exact-trims"))


class RecordingEngine:
    def __init__(self):
        self.handed = []

    def set_veq(self, veq):
        self.handed.append(("veq", veq))


def adopter(exact, engine=None):
    return types.SimpleNamespace(exact_speculation=exact, _job_engine=engine,
                                 _discard_ahead=False)


def test_a_default_decode_hands_the_trim_to_the_jobs_not_yet_dispatched():
    engine = RecordingEngine()
    it = adopter(False, engine)

    LDdecode._adopt_from_next_field(it, lambda e: e.handed.append("veq"))

    assert engine.handed == ["veq"] and not it._discard_ahead


def test_a_default_decode_without_an_engine_has_nothing_to_hand_over():
    it = adopter(False)
    LDdecode._adopt_from_next_field(it, lambda e: pytest.fail("no engine"))
    assert not it._discard_ahead


def test_an_exact_decode_discards_ahead_instead():
    engine = RecordingEngine()
    it = adopter(True, engine)

    LDdecode._adopt_from_next_field(it, lambda e: e.handed.append("veq"))

    assert it._discard_ahead and engine.handed == []


# --- the video EQ trim ---------------------------------------------------


def veq_stub(exact, fields_written, engine=None):
    """Enough of an LDdecode for checkVideoEQ to reach a tracking trim:
    the EQ has locked, and its servo now reports TRIMMED_EQ.  The
    multiburst ceiling has its own tests (test_imtf_chroma_ceiling) and
    is held still here."""
    it = types.SimpleNamespace(
        exact_speculation=exact, _job_engine=engine, _discard_ahead=False,
        veq_calibrated=True, fields_written=fields_written,
        VEQ_DEADBAND_DB=LDdecode.VEQ_DEADBAND_DB,
        VEQ_MIN_ADOPT_FIELDS=LDdecode.VEQ_MIN_ADOPT_FIELDS,
        _veq_last_adopt=None, _servo_pos=0, bytes_per_field=1,
        rf=types.SimpleNamespace(
            DecoderParams={"video_eq_auto": APPLIED_EQ},
            recompute_fvideo=lambda: None),
    )
    it._veq_estimate = lambda field: TRIMMED_EQ
    it._publish_imtf_flat_band = lambda first: False
    it._apply_imtf_ceiling = lambda: False
    it._adopt_from_next_field = (
        lambda hand_over: LDdecode._adopt_from_next_field(it, hand_over))
    return it


@pytest.mark.parametrize("exact", [False, True])
def test_a_video_eq_trim_is_no_redo_in_either_mode(exact):
    """The domesday-ds2 inner field: exact mode redid the field this trim
    was measured on, where a serial decode keeps it."""
    engine = RecordingEngine()
    it = veq_stub(exact, fields_written=10, engine=engine)

    assert LDdecode.checkVideoEQ(it, field=None) is True

    assert it.rf.DecoderParams["video_eq_auto"] == TRIMMED_EQ
    assert it._discard_ahead is exact
    assert engine.handed == ([] if exact else [("veq", TRIMMED_EQ)])


def warmup_stub(exact):
    """A calibration warm-up whose first lookahead field trims the video
    EQ, with every other loop already settled."""
    it = veq_stub(exact, fields_written=0)
    it.decoded = 0

    def decodefield(pos, mtf_level, prev, initphase):
        it.decoded += 1
        return types.SimpleNamespace(valid=True, burstmedian=20.0), FIELD_LEN

    it.__dict__.update(
        mtf_level=0.0, isCLV=False, bw_ratios=[],
        deemp_calibrated=True, veq_servo=True, mtf_2t_servo=False,
        chroma_dg_servo=False, dg_calibrated=False,
        # --calibration_frames 0, the warm-up as it was before the
        # calibration pass: this is about what a trim does to the stable count
        warmup_min_fields=0,
        WARMUP_STABLE_FIELDS=LDdecode.WARMUP_STABLE_FIELDS,
        WARMUP_MAX_FIELDS=LDdecode.WARMUP_MAX_FIELDS,
        WARMUP_DG_PHASE_FIELDS=LDdecode.WARMUP_DG_PHASE_FIELDS,
        DG_PHASE_MIN_SAMPLES=LDdecode.DG_PHASE_MIN_SAMPLES,
        checkChromaDG=lambda field: None,
        _servo_samples=[], _veq_samples=[], _dg_samples=[],
        _veq_held=False,
        _deemp_burst_samples=[], _deemp_burst_offset=None,
        _agc_adjusted_last=False, _deemp_adjusted_last=False,
        decodefield=decodefield,
        decode_stage2=lambda f: (None, None, {}),
        checkMTF=lambda f, prev: True,
        _adjust_agc=lambda f, wide: False,
        _deemp_calibrate=lambda: False,
        _mtf_servo_settled=lambda: True,
    )
    it.rf.DecoderParams["inverse_mtf_strength"] = 0.0
    it.checkVideoEQ = lambda field: LDdecode.checkVideoEQ(it, field)
    return it


@pytest.mark.parametrize("exact", [False, True])
def test_a_warm_up_trim_does_not_restart_the_warm_up_in_either_mode(exact):
    """Exact mode used to count a trim as a parameter move: the burst pool
    was emptied and the warm-up ran another field before it settled."""
    it = warmup_stub(exact)
    start = {"f": stub_field(), "start": 1000.0, "offset": FIELD_LEN,
             "initphase": False}

    # the EQ moved, so the entry itself is re-decoded under it
    assert LDdecode._calibration_warmup(it, start) is True

    assert it.rf.DecoderParams["video_eq_auto"] == TRIMMED_EQ
    assert it.decoded == 2
    assert it._deemp_burst_samples == [20.0, 20.0]


# --- _commit_entry -------------------------------------------------------


def stub_field():
    return types.SimpleNamespace(
        linelocs=[0.0] * 400, inlinelen=1.0, sync_confidence=100, valid=True)


def stub_decoder(trim=False, exact=True):
    events = []
    it = types.SimpleNamespace(
        fields_written=10, deemp_calibrated=True, pipeline_warm=True,
        output_lines=263, fieldstack=[None] * 4, _fields_since_redo=3,
        second_decode=1.0, _agc_adjusted_last=False, _job_engine=None,
        exact_speculation=exact,
        # the pipeline has decoded three fields past the entry
        fdoffset=1000.0 + 4 * FIELD_LEN, _chain_prev="field decoded ahead",
        _servo_pos=0, mtf_level=0.0, events=events,
    )

    def calibrate(f, metrics, redos):
        events.append(("calibrate", redos))
        if trim:
            LDdecode._adopt_from_next_field(it, lambda e: None)
        return False

    it.calibrate = calibrate
    it._flush_pipeline = lambda: events.append("flush")
    it.decodefield = lambda *a, **k: events.append("redecode") or (stub_field(), FIELD_LEN)
    it.decode_stage2 = lambda f: (None, None, {})
    it.commit_field = lambda f, *a, **k: events.append("commit") or f
    return it


def entry(f):
    return {"f": f, "result": (None, None, {}), "start": 1000.0,
            "offset": FIELD_LEN, "independent": True, "initphase": False}


def test_an_exact_trim_commits_the_field_as_decoded_and_restarts_past_it():
    it = stub_decoder(trim=True)
    f = stub_field()

    assert LDdecode._commit_entry(it, entry(f)) is f

    assert it.events == [("calibrate", 0), "flush", "commit"]
    assert it._chain_prev is f and it.fdoffset == 1000.0 + FIELD_LEN
    assert not it._discard_ahead
    # not a redo, so the pipeline's warm-up count carries on
    assert it._fields_since_redo == 4


@pytest.mark.parametrize("exact", [False, True])
def test_without_a_trim_nothing_ahead_is_discarded(exact):
    it = stub_decoder(trim=False, exact=exact)

    LDdecode._commit_entry(it, entry(stub_field()))

    assert it.events == [("calibrate", 0), "commit"]
    assert it.fdoffset == 1000.0 + 4 * FIELD_LEN


def test_a_default_decode_keeps_what_it_decoded_ahead_through_a_trim():
    it = stub_decoder(trim=True, exact=False)

    LDdecode._commit_entry(it, entry(stub_field()))

    assert it.events == [("calibrate", 0), "commit"]
    assert it._chain_prev == "field decoded ahead"


def test_the_warm_up_runs_its_minimum_pass_even_when_settled():
    """--calibration_frames: however early the loops settle, the warm-up
    decodes at least warmup_min_fields ahead before the first commit."""
    it = warmup_stub(False)
    it.warmup_min_fields = 20
    start = {"f": stub_field(), "start": 1000.0, "offset": FIELD_LEN,
             "initphase": False}
    LDdecode._calibration_warmup(it, start)
    assert it.decoded == 20


def test_a_full_pass_waits_for_more_stable_fields_than_the_old_warm_up():
    it = warmup_stub(False)
    it.warmup_min_fields = 2
    start = {"f": stub_field(), "start": 1000.0, "offset": FIELD_LEN,
             "initphase": False}
    LDdecode._calibration_warmup(it, start)
    assert it.decoded == LDdecode.WARMUP_STABLE_FIELDS


def staircase_warmup_stub(clear_every=None):
    """A full pass on a disc whose staircase is on one field in two, with
    the DG corrector's slope already decided; clear_every empties the pool
    as another servo's adoption would."""
    it = warmup_stub(False)
    it.warmup_min_fields = 20
    it.chroma_dg_servo = True
    it.dg_calibrated = True
    calls = []

    def check(field):
        calls.append(field)
        if len(calls) % 2:
            it._dg_samples.append((len(calls), 0.0, 0.0))
        if clear_every and len(calls) % clear_every == 0:
            # the adoption's own field is pooled afresh
            it._dg_samples[:] = [(len(calls), 0.0, 0.0)]

    it.checkChromaDG = check
    return it


def test_the_pass_waits_for_the_phase_pool_to_fill():
    """Ten frames give the phase pool at most ten staircase fields; its
    decision takes DG_PHASE_MIN_SAMPLES, and the first frame should have it."""
    it = staircase_warmup_stub()
    start = {"f": stub_field(), "start": 1000.0, "offset": FIELD_LEN,
             "initphase": False}
    LDdecode._calibration_warmup(it, start)
    assert len(it._dg_samples) >= LDdecode.DG_PHASE_MIN_SAMPLES
    assert 2 * LDdecode.DG_PHASE_MIN_SAMPLES - 2 <= it.decoded \
        < LDdecode.WARMUP_DG_PHASE_FIELDS


def test_the_wait_for_the_phase_pool_is_bounded():
    it = staircase_warmup_stub(clear_every=20)
    start = {"f": stub_field(), "start": 1000.0, "offset": FIELD_LEN,
             "initphase": False}
    LDdecode._calibration_warmup(it, start)
    assert it.decoded == LDdecode.WARMUP_DG_PHASE_FIELDS


def test_without_a_pass_the_first_frame_waits_for_the_dg_slope_only():
    """The default runs no pass, but the staircase is pooled as it warms up,
    so the first frame carries the slope decision (three staircase fields);
    the phase decision is left to the commit path."""
    it = staircase_warmup_stub()
    it.warmup_min_fields = 0
    it.dg_calibrated = False
    pool = it.checkChromaDG

    def check(field):
        pool(field)
        if len(it._dg_samples) >= 3:
            it.dg_calibrated = True

    it.checkChromaDG = check
    start = {"f": stub_field(), "start": 1000.0, "offset": FIELD_LEN,
             "initphase": False}
    LDdecode._calibration_warmup(it, start)
    assert it.dg_calibrated and len(it._dg_samples) == 3
    assert it.decoded < 2 * LDdecode.DG_PHASE_MIN_SAMPLES


def test_an_eq_held_inside_its_dead_band_ends_the_warm_up():
    """A channel the EQ finds flat enough never adopts, so veq_calibrated
    stays unset; the warm-up used to wait out its whole budget for it
    (GGV1069 outer: 20 frames decoded ahead of a settled first frame)."""
    it = warmup_stub(False)
    it.veq_calibrated = False
    it._veq_estimate = lambda field: APPLIED_EQ
    it._veq_samples = [("multiburst seen",)]
    start = {"f": stub_field(), "start": 1000.0, "offset": FIELD_LEN,
             "initphase": False}

    assert LDdecode._calibration_warmup(it, start) is False

    assert it.decoded == 2 and not it.veq_calibrated


def test_the_warm_up_waits_for_the_2t_servo_to_settle():
    it = warmup_stub(False)
    settled_after = 7
    it._mtf_servo_settled = lambda: it.decoded >= settled_after
    start = {"f": stub_field(), "start": 1000.0, "offset": FIELD_LEN,
             "initphase": False}
    LDdecode._calibration_warmup(it, start)
    assert it.decoded == settled_after
