"""Unit tests for the split of LDdecode.writeout into its commit-time
half and the output-stage half (_write_field) that trails it on the
output lane with -t N.

The commit thread must do only what later commits depend on (the
metadata list, the written-field count), hand the field over as a view
frozen at commit-time parameters, and keep the queue in order; the
chroma DG decision for the TBC picture goes to the output pool.  These
tests drive the methods on a stub decoder with recording collaborators.
"""

import types
from concurrent.futures import Future

import numpy as np
import pytest

from lddecode import decoder as D
from lddecode.decoder import LDdecode

pytestmark = [pytest.mark.unit, pytest.mark.decode, pytest.mark.parallel]


class RecordingLane:
    def __init__(self):
        self.jobs = []

    def submit(self, fn, *args):
        self.jobs.append((fn, args))


class ImmediateExecutor:
    """A pool whose work completes at submit time, so the test sees the
    Future the commit thread hands on without another thread."""

    def __init__(self):
        self.calls = []

    def submit(self, fn, *args):
        self.calls.append((fn, args))
        fut = Future()
        fut.set_result(fn(*args))
        return fut


def stub_field(vsync_ire=-40.0, first=True):
    rf = types.SimpleNamespace(DecoderParams={
        "vsync_ire": vsync_ire, "chroma_dg_slope": 0.002, "chroma_dg_phase": 0.0})
    return types.SimpleNamespace(rf=rf, isFirstField=first,
                                 dspicture=np.arange(8, dtype=np.uint16))


def stub_decoder(lane=None, pool=None, cvbs=None, dbconn=None):
    it = types.SimpleNamespace(
        fieldinfo=[], fields_written=3, cvbs_writer=cvbs, dbconn=dbconn,
        _output_lane=lane, _output_pool=pool, dg_speculation_tolerance=None,
        fdoffset=12345.0, capture_id=7, written=[],
    )
    it.writeout = lambda ds: LDdecode.writeout(it, ds)
    it._output_picture = lambda p, v: LDdecode._output_picture(it, p, v)
    it._pair_cvbs_view = lambda v: LDdecode._pair_cvbs_view(it, v)
    it._write_field = lambda job: it.written.append(job)
    it._log_speculation = lambda r, d="": LDdecode._log_speculation(it, r, d)
    it._db_log_speculation = lambda row: LDdecode._db_log_speculation(it, row)
    return it


@pytest.fixture
def corrector(monkeypatch):
    calls = []

    def fake(picture, field, slope, phase, tolerance=None):
        calls.append((picture, field, slope, phase, tolerance))
        return np.asarray(picture) + 1

    monkeypatch.setattr(D, "chroma_dg_output_picture", fake)
    return calls


def dataset(f, picture=None, audio=None, efm=None):
    fi = {"isFirstField": True}
    if picture is None:
        picture = f.dspicture
    return (f, fi, picture, audio, efm)


def test_commit_half_records_the_field_and_queues_the_rest_in_order(corrector):
    lane = RecordingLane()
    it = stub_decoder(lane=lane, cvbs=object())
    f = stub_field()
    audio = np.zeros(20, dtype=np.int16)

    it.writeout(dataset(f, audio=audio))
    it.writeout(dataset(f))

    assert [fi["audioSamples"] for fi in it.fieldinfo] == [10, 0]
    assert it.fields_written == 5
    assert it.written == []  # nothing written on the commit thread
    ids = [args[0][5] for _, args in lane.jobs]
    counts = [args[0][6] for _, args in lane.jobs]
    assert ids == [3, 4] and counts == [1, 2]
    assert all(fn is it._write_field for fn, _ in lane.jobs)


def test_the_queued_field_is_a_view_frozen_at_commit_time_parameters(corrector):
    lane = RecordingLane()
    it = stub_decoder(lane=lane, cvbs=object())
    f = stub_field(vsync_ire=-40.0)
    it.writeout(dataset(f))
    f.rf.DecoderParams["vsync_ire"] = -43.0   # AGC moves after the commit

    view = lane.jobs[0][1][0][0]
    assert view is not f and view.dspicture is f.dspicture
    assert view.rf.DecoderParams["vsync_ire"] == -40.0


def test_without_a_lane_the_field_is_written_inline(corrector):
    it = stub_decoder(cvbs=object())
    it.writeout(dataset(stub_field()))
    assert len(it.written) == 1 and it.fields_written == 4


def test_tbc_picture_decision_uses_commit_time_estimate_on_the_pool(corrector):
    pool = ImmediateExecutor()
    it = stub_decoder(lane=RecordingLane(), pool=pool)
    f = stub_field()
    it.writeout(dataset(f))
    f.rf.DecoderParams["chroma_dg_slope"] = 0.005

    job = it._output_lane.jobs[0][1][0]
    picture = job[2]
    assert isinstance(picture, Future)
    np.testing.assert_array_equal(picture.result(), f.dspicture + 1)
    _, view, slope, phase, tol = corrector[0]
    assert view is job[0] and (slope, phase) == (0.002, 0.0) and tol is None


def test_tbc_picture_is_decided_inline_without_a_pool(corrector):
    it = stub_decoder()
    f = stub_field()
    it.writeout(dataset(f))
    picture = it.written[0][2]
    assert not isinstance(picture, Future)
    np.testing.assert_array_equal(picture, f.dspicture + 1)


def test_cvbs_output_leaves_the_picture_to_the_writer(corrector):
    it = stub_decoder(cvbs=object())
    f = stub_field()
    it.writeout(dataset(f))
    assert it.written[0][2] is f.dspicture
    assert corrector == []


def test_a_cvbs_frame_is_written_under_its_second_fields_parameters(corrector):
    """The writer resamples both fields when the second arrives, so the
    inline write read the second field's commit-time parameters for the
    first field too; the queued views must agree."""
    lane = RecordingLane()
    it = stub_decoder(lane=lane, cvbs=object())
    a = stub_field(first=True)
    it.writeout(dataset(a))
    a.rf.DecoderParams["chroma_dg_phase"] = 0.03   # trim between the fields
    b = stub_field(first=False)
    b.rf.DecoderParams["chroma_dg_phase"] = 0.03
    it.writeout(dataset(b))

    view_a = lane.jobs[0][1][0][0]
    view_b = lane.jobs[1][1][0][0]
    assert view_a.rf is view_b.rf
    assert view_a.rf.DecoderParams["chroma_dg_phase"] == 0.03
    # and the pairing is consumed: a later first field starts afresh
    it.writeout(dataset(stub_field(first=True)))
    assert lane.jobs[2][1][0][0].rf is not view_b.rf


@pytest.fixture
def quiet_log(monkeypatch):
    monkeypatch.setattr(D.logs, "logger", types.SimpleNamespace(
        debug=lambda *a, **k: None))


def test_speculation_log_rows_travel_through_the_lane(quiet_log):
    lane = RecordingLane()
    db = types.SimpleNamespace(rows=[])
    db.execute = lambda sql, params: db.rows.append(params)
    it = stub_decoder(lane=lane, dbconn=db)

    it._log_speculation("stale-imtf", "detail")
    assert db.rows == []  # not on the commit thread
    fn, args = lane.jobs[0]
    fn(*args)
    assert db.rows == [(7, 3, 12345, "stale-imtf", "detail")]


def test_speculation_log_is_immediate_without_a_lane(quiet_log):
    db = types.SimpleNamespace(rows=[])
    db.execute = lambda sql, params: db.rows.append(params)
    it = stub_decoder(dbconn=db)
    it._log_speculation("resync")
    assert db.rows == [(7, 3, 12345, "resync", "")]
