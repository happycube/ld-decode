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

    def submit(self, fn, *args, **kwargs):
        self.calls.append((fn, args))
        fut = Future()
        fut.set_result(fn(*args, **kwargs))
        return fut


def stub_field(vsync_ire=-40.0, first=True):
    rf = types.SimpleNamespace(DecoderParams={
        "vsync_ire": vsync_ire, "chroma_dg_slope": 0.002, "chroma_dg_phase": 0.0})
    return types.SimpleNamespace(rf=rf, isFirstField=first,
                                 dspicture=np.arange(8, dtype=np.uint16))


def stub_decoder(lane=None, pool=None, cvbs=None, dbconn=None):
    it = types.SimpleNamespace(
        fieldinfo=[], _burst_levels=[], fields_written=3, cvbs_writer=cvbs, dbconn=dbconn,
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


def test_commit_half_keeps_every_fields_burst_level_for_the_chroma_gain(corrector):
    """FieldInfo only holds the last few fields; the gain is over all of them."""
    it = stub_decoder(lane=RecordingLane(), cvbs=object())
    f = stub_field()

    for level in (15.0, 15.5, 16.0, 15.25, None):
        job = dataset(f)
        job[1]["medianBurstIRE"] = level
        it.writeout(job)

    assert it._burst_levels == [15.0, 15.5, 16.0, 15.25, None]


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


def test_cvbs_output_does_not_send_the_correction_to_the_field_jobs():
    """The other half of the same rule: with the CVBS writer on, the field
    jobs are told no chroma DG at all, so a worker leaves the TBC picture it
    downscales uncorrected and the correction happens once, on the 4fsc
    lattice the decode is actually writing (downscale_cvbs)."""
    it = types.SimpleNamespace(
        output_cvbs=True,
        rf=types.SimpleNamespace(DecoderParams={
            "chroma_dg_slope": 0.002, "chroma_dg_phase": 0.04}),
    )

    assert LDdecode._engine_chroma_dg(it) is None

    it.output_cvbs = False
    assert LDdecode._engine_chroma_dg(it) == (0.002, 0.04)


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


class StubEFMDemod:
    """Front end and timing loop that record the order they were fed."""

    def __init__(self):
        self.fronts = []
        self.backs = []

    def front_end(self, efm):
        self.fronts.append(int(efm[0]))
        return efm * 10

    def back_end(self, front):
        self.backs.append(int(front[0]))
        return front.astype(np.int8)


def efm_decoder(lane=None, front_pool=None):
    it = stub_decoder(lane=lane, cvbs=object())
    it.digital_audio = True
    it._efm_front_pool = front_pool
    it.efm_pll = StubEFMDemod()
    it.efm_conf_packed = False
    it.outfile_efm = None
    it.outfile_pre_efm = None
    it.outfile_ac3sym = None
    it._efm_front_end = lambda e: LDdecode._efm_front_end(it, e)
    it._efm_back_end = lambda e: LDdecode._efm_back_end(it, e)
    it._process_efm = lambda e: LDdecode._process_efm(it, e)
    it._write_field = lambda job: LDdecode._write_field(it, job)
    it._writeout_data = lambda fi, pic, aud, f, efm_out: it.written.append(efm_out)
    return it


def test_the_efm_front_end_starts_at_commit_on_its_pool(corrector):
    lane = RecordingLane()
    pool = ImmediateExecutor()
    it = efm_decoder(lane=lane, front_pool=pool)

    for n in (1, 2, 3):
        it.writeout(dataset(stub_field(), efm=np.full(4, n, dtype=np.int16)))

    # all three slices went through the front end at commit, in order,
    # before the lane demodulated any of them
    assert it.efm_pll.fronts == [1, 2, 3] and it.efm_pll.backs == []
    efms = [args[0][4] for _, args in lane.jobs]
    assert all(isinstance(e, Future) for e in efms)

    for fn, args in lane.jobs:
        fn(*args)
    assert it.efm_pll.backs == [10, 20, 30]
    assert [int(e[0]) for e in it.written] == [10, 20, 30]
    assert [fi["efmTValues"] for fi in it.fieldinfo] == [4, 4, 4]


def test_without_a_front_end_pool_the_efm_is_demodulated_on_the_lane(corrector):
    lane = RecordingLane()
    it = efm_decoder(lane=lane)

    it.writeout(dataset(stub_field(), efm=np.full(4, 7, dtype=np.int16)))
    assert it.efm_pll.fronts == []
    fn, args = lane.jobs[0]
    fn(*args)
    assert it.efm_pll.fronts == [7] and it.efm_pll.backs == [70]


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


# --- the previous-frame VITS metrics ------------------------------------


def metrics_decoder(pool=None):
    it = stub_decoder(pool=pool)
    it.fieldinfo = []
    it.bytes_per_field = 1000.0
    it.doDOD = False
    it.verboseVITS = False
    it.rf = types.SimpleNamespace(DecoderParams={"vsync_ire": -40.0},
                                  SysParams={"fieldPhases": 4})
    return it


def metrics_field(it, n):
    f = types.SimpleNamespace(
        rf=it.rf, isFirstField=True, readloc=1000.0 * n, burstmedian=20.0,
        fieldPhaseID=1, linecode=[None, None, None],
        precomputed_metrics={"wSNR": 40.0 + n},
        compute_syncconf=lambda: 100)
    return f


@pytest.fixture
def fp_metrics(monkeypatch):
    calls = []

    def fake(rf, f, fp, base, verbose=False):
        calls.append((f, fp, dict(f.rf.DecoderParams)))
        return dict(base, fp=fp is not None)

    from lddecode import metrics
    monkeypatch.setattr(metrics, "computeMetricsFP", fake)
    return calls


def test_previous_frame_metrics_go_to_the_output_pool_at_commit_levels(fp_metrics):
    pool = ImmediateExecutor()
    it = metrics_decoder(pool=pool)
    fields = [metrics_field(it, n) for n in range(3)]
    it.fieldstack = [fields[2], fields[1], fields[0]]
    it.fieldinfo = [{"fieldPhaseID": 4, "isFirstField": False, "diskLoc": 0.0}] * 3

    fi, filler = LDdecode.buildmetadata(it, fields[2], check_phase=False)
    # the live level moves on after the commit
    it.rf.DecoderParams["vsync_ire"] = -45.0

    assert not filler and isinstance(fi["vitsMetrics"], Future)
    assert fi["vitsMetrics"].result() == {"wSNR": 42.0, "fp": True}
    (f, fp, params), = fp_metrics
    # views of the field and its previous frame, bound to the commit's
    # levels, not the fields themselves
    assert f is not fields[2] and f.readloc == fields[2].readloc
    assert fp is not fields[0] and fp.readloc == fields[0].readloc
    assert params == {"vsync_ire": -40.0}
    # the key keeps its place in the row
    assert list(fi).index("vitsMetrics") < list(fi).index("vbi")


def test_previous_frame_metrics_are_computed_inline_without_a_pool(fp_metrics):
    it = metrics_decoder()
    f = metrics_field(it, 0)
    it.fieldstack = [f]

    fi, _ = LDdecode.buildmetadata(it, f, check_phase=False)

    assert fi["vitsMetrics"] == {"wSNR": 40.0, "fp": False}
    assert fp_metrics[0][0] is f


def test_the_output_stage_collects_the_metrics_before_the_row(corrector):
    it = efm_decoder()
    it.digital_audio = False
    it.dbconn = object()
    rows = []
    it._write_field_db = lambda fi, f_id, n: rows.append(fi["vitsMetrics"])
    fut = Future()
    fut.set_result({"wSNR": 41.0})
    fi = {"vitsMetrics": fut}

    LDdecode._write_field(it, (stub_field(), fi, None, None, None, 0, 1))

    assert rows == [{"wSNR": 41.0}] and fi["vitsMetrics"] == {"wSNR": 41.0}

