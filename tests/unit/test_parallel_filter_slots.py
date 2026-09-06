"""Per-job filter slots: the publisher's discipline and the worker's use.

Two filters a field job reads are neither invariant nor per-block - the
video output stack and the MTF response - so they cannot go in the
segment's read-only half.  They live in slots the parent rewrites, and
the whole of the correctness argument is that a slot is never rewritten
while a job that names it can still be reading it, and that a worker
handed a stale id rebuilds instead of reading on.

The tests drive the real publisher (FilterSlots, through an injected
writer) and the real worker path (_sync_worker_video, _sync_worker_mtf,
against module globals a fixture installs), so no process is spawned and
no shared memory is mapped.
"""

import threading
import time
from concurrent.futures import Future

import numpy as np
import pytest
from numpy.testing import assert_array_equal

from lddecode import parallel
from lddecode import shared_filter_bank as sfb
from lddecode.parallel import FieldJobEngine, FilterSlots
from lddecode.rfdecode import RFDecode

pytestmark = [pytest.mark.unit, pytest.mark.parallel]


class RecordingWriter:
    """Stands in for shared_filter_bank.write_slot."""

    def __init__(self):
        self.writes = []

    def __call__(self, descriptor, family, index, arrays, pubid):
        self.writes.append((family, index, arrays, pubid))


def make_slots(depth=2, families=("video", "mtf")):
    writer = RecordingWriter()
    return FilterSlots({"name": "test"}, families, depth=depth,
                       writer=writer), writer


# --- the publisher's discipline ------------------------------------------


def test_a_published_key_becomes_live_and_acquirable():
    slots, writer = make_slots()

    assert slots.publish("video", ("k", None), {"a": 1}) is True
    assert slots.live("video", ("k", None))
    assert writer.writes == [("video", 0, {"a": 1}, 1)]

    tokens = slots.acquire({"video": ("k", None)})
    assert tokens == {"video": (0, 1)}


def test_publishing_a_live_key_again_writes_nothing():
    slots, writer = make_slots()
    slots.publish("mtf", 0.5, {"a": 1})

    assert slots.publish("mtf", 0.5, {"a": 2}) is True
    assert len(writer.writes) == 1


def test_a_second_key_takes_the_other_slot():
    slots, writer = make_slots()
    slots.publish("mtf", 0.5, {"a": 1})
    slots.publish("mtf", 0.6, {"a": 2})

    assert [w[1] for w in writer.writes] == [0, 1]
    assert slots.acquire({"mtf": 0.5}) == {"mtf": (0, 1)}
    assert slots.acquire({"mtf": 0.6}) == {"mtf": (1, 2)}


def test_a_slot_a_job_still_names_is_not_reused():
    """The point of the whole arrangement: a worker running a job holds
    the slot's arrays, so the slot cannot be rewritten under it."""
    slots, writer = make_slots(depth=2)
    slots.publish("mtf", 0.5, {"a": 1})
    slots.publish("mtf", 0.6, {"a": 2})
    slots.acquire({"mtf": 0.5})
    slots.acquire({"mtf": 0.6})

    assert slots.publish("mtf", 0.7, {"a": 3}) is False
    assert len(writer.writes) == 2
    assert not slots.live("mtf", 0.7)


def test_a_slot_is_reused_once_the_jobs_naming_it_have_finished():
    slots, writer = make_slots(depth=2)
    slots.publish("mtf", 0.5, {"a": 1})
    slots.publish("mtf", 0.6, {"a": 2})
    held = slots.acquire({"mtf": 0.5})
    slots.acquire({"mtf": 0.6})
    assert slots.publish("mtf", 0.7, {"a": 3}) is False

    slots.release(held)

    assert slots.publish("mtf", 0.7, {"a": 3}) is True
    # The reused slot answers to a new id, so a job still carrying the
    # old one falls back rather than reading the new value.
    assert writer.writes[-1] == ("mtf", 0, {"a": 3}, 3)
    assert not slots.live("mtf", 0.5)


def test_several_jobs_can_name_one_slot_at_once():
    slots, _ = make_slots(depth=2)
    slots.publish("mtf", 0.5, {"a": 1})
    slots.publish("mtf", 0.6, {"a": 2})
    first = slots.acquire({"mtf": 0.5})
    second = slots.acquire({"mtf": 0.5})
    slots.acquire({"mtf": 0.6})

    slots.release(first)
    assert slots.publish("mtf", 0.7, {"a": 3}) is False

    slots.release(second)
    assert slots.publish("mtf", 0.7, {"a": 3}) is True


def test_acquiring_a_key_no_slot_holds_yields_no_token():
    slots, _ = make_slots()
    slots.publish("mtf", 0.5, {"a": 1})

    assert slots.acquire({"mtf": 0.9}) is None
    assert slots.acquire({"video": ("k", None), "mtf": 0.5}) == {"mtf": (0, 1)}


def test_releasing_more_than_was_acquired_does_not_underflow():
    slots, _ = make_slots()
    slots.publish("mtf", 0.5, {"a": 1})
    tokens = slots.acquire({"mtf": 0.5})

    slots.release(tokens)
    slots.release(tokens)
    slots.release(None)

    assert slots.publish("mtf", 0.7, {"a": 3}) is True


def test_a_family_with_no_slots_is_simply_skipped():
    slots, writer = make_slots(families=("mtf",))

    assert slots.publish("video", ("k", None), {"a": 1}) is False
    assert slots.acquire({"video": ("k", None)}) is None
    assert writer.writes == []


def test_publications_never_reuse_an_id():
    slots, writer = make_slots(depth=2)
    for level in (0.1, 0.2):
        slots.publish("mtf", level, {"a": level})
    for level in (0.3, 0.4):
        slots.publish("mtf", level, {"a": level})

    assert [w[3] for w in writer.writes] == [1, 2, 3, 4]


# --- the worker's use ----------------------------------------------------


class FakeSegment:
    _store = {}
    _serial = 0

    def __init__(self, name=None, size=0):
        if name is None:
            FakeSegment._serial += 1
            name = "slots-%d" % FakeSegment._serial
            self._store[name] = bytearray(size)
        self.name = name
        self.buf = memoryview(self._store[name])


@pytest.fixture
def banks(monkeypatch):
    """A parent bank, a worker bank, and a segment between them.

    Both are real RFDecodes so that "the worker rebuilds it privately"
    and "the worker reads the parent's slot" can be compared as arrays
    rather than as call counts.
    """
    sfb._published.clear()
    sfb._attached.clear()
    parent = RFDecode(inputfreq=40, system="PAL")
    worker = RFDecode(inputfreq=40, system="PAL")

    spec = parent.shared_filter_spec()
    descriptor = sfb.publish(spec["arrays"], slots=spec["slots"],
                             segment_factory=FakeSegment)
    views = sfb.attach(descriptor, segment_factory=FakeSegment)
    worker.adopt_shared_filters(views.arrays)

    monkeypatch.setattr(parallel, "_worker_rf", worker)
    monkeypatch.setattr(parallel, "_worker_shared", views)
    monkeypatch.setattr(parallel, "_worker_video_slot", False)
    monkeypatch.setattr(parallel, "_worker_mtf_slot", False)
    yield parent, worker, descriptor
    sfb._published.clear()
    sfb._attached.clear()
    FakeSegment._store = {}


def publish_video(parent, descriptor, strength, pubid, index=0):
    parent.DecoderParams["inverse_mtf_strength"] = strength
    parent.recompute_fvideo()
    arrays = parent.slot_filter_arrays("video", (strength, None))
    sfb.write_slot(descriptor, "video", index, arrays, pubid)
    return arrays


def test_a_matching_token_reads_the_video_slot(banks):
    parent, worker, descriptor = banks
    expected = publish_video(parent, descriptor, 0.4, pubid=1)

    parallel._sync_worker_video(0.4, None, slot=(0, 1))

    assert_array_equal(worker.Filters["FVideo_rfft32"],
                       expected["FVideo_rfft32"])
    assert_array_equal(worker.Filters["FVideo_rfft_dc"],
                       expected["FVideo_rfft_dc"])
    assert not worker.Filters["FVideo_rfft32"].flags.writeable


def test_without_a_token_the_worker_rebuilds_what_the_slot_holds(banks):
    parent, worker, descriptor = banks
    expected = publish_video(parent, descriptor, 0.4, pubid=1)

    parallel._sync_worker_video(0.4, None, slot=None)

    assert worker.Filters["FVideo_rfft32"].flags.writeable
    assert_array_equal(worker.Filters["FVideo_rfft32"],
                       expected["FVideo_rfft32"])
    assert_array_equal(worker.Filters["FVideo_rfft_dc"],
                       expected["FVideo_rfft_dc"])


def test_a_stale_token_makes_the_worker_rebuild(banks):
    parent, worker, descriptor = banks
    publish_video(parent, descriptor, 0.4, pubid=1)

    # The parent reused the slot for a different strength, so the id the
    # job carries no longer stands.
    expected = publish_video(parent, descriptor, 0.6, pubid=2)
    parallel._sync_worker_video(0.4, None, slot=(0, 1))

    assert worker.Filters["FVideo_rfft32"].flags.writeable
    rebuilt = worker.Filters["FVideo_rfft32"]
    assert not np.array_equal(rebuilt, expected["FVideo_rfft32"])
    parent.DecoderParams["inverse_mtf_strength"] = 0.4
    parent.recompute_fvideo()
    assert_array_equal(rebuilt, parent.Filters["FVideo_rfft32"])


def test_a_bank_left_on_a_slot_rebuilds_when_the_next_job_has_none(banks):
    """A slot view outlives the job that named it only in this worker's
    bank; the parent is free to rewrite it as soon as that job is done,
    so the next job without a matching id must not read on."""
    parent, worker, descriptor = banks
    publish_video(parent, descriptor, 0.4, pubid=1)
    parallel._sync_worker_video(0.4, None, slot=(0, 1))
    assert not worker.Filters["FVideo_rfft32"].flags.writeable

    # Same parameters, no token: the parameters alone would say there is
    # nothing to do.
    parallel._sync_worker_video(0.4, None, slot=None)

    assert worker.Filters["FVideo_rfft32"].flags.writeable
    assert_array_equal(worker.Filters["FVideo_rfft32"],
                       parent.Filters["FVideo_rfft32"])


def test_a_matching_token_primes_the_held_mtf_response(banks):
    parent, worker, descriptor = banks
    arrays = parent.slot_filter_arrays("mtf", 0.7)
    sfb.write_slot(descriptor, "mtf", 0, arrays, 5)

    parallel._sync_worker_mtf(0.7, slot=(0, 5))

    held = worker.mtf_response(0.7)
    assert not held.flags.writeable
    assert_array_equal(held, parent.mtf_response(0.7))


def test_without_a_token_the_worker_raises_the_power_itself(banks):
    parent, worker, descriptor = banks

    parallel._sync_worker_mtf(0.7, slot=None)

    held = worker.mtf_response(0.7)
    assert held.flags.writeable
    assert_array_equal(held, parent.mtf_response(0.7))


def test_a_held_response_from_a_slot_is_dropped_when_the_token_goes(banks):
    parent, worker, descriptor = banks
    sfb.write_slot(descriptor, "mtf", 0,
                   parent.slot_filter_arrays("mtf", 0.7), 5)
    parallel._sync_worker_mtf(0.7, slot=(0, 5))
    assert worker._mtf_response_cache is not None

    parallel._sync_worker_mtf(0.7, slot=None)

    assert worker._mtf_response_cache is None
    assert worker.mtf_response(0.7).flags.writeable


# --- the engine hands tokens to the job and drops them after it ----------


class RecordingExecutor:
    """Runs nothing; records what the dispatcher submitted."""

    def __init__(self):
        self.calls = []
        self.futures = []
        self.submitted = threading.Event()

    def submit(self, fn, *args, key=None):
        self.calls.append(args)
        fut = Future()
        self.futures.append(fut)
        self.submitted.set()
        return fut


ENGINE_CFG = {
    "blocklen": 32768,
    "blockcut": 1024,
    "demod_blocksize": 30720,
    "readlen": 32768 * 4,
    "samples_per_field": 32768.0 * 4,
    "analog_audio": 0,
    "parity_len": {True: 32768.0 * 4, False: 32768.0 * 4},
}

#: _decode_field_worker(seq, start, raw, span_begin, mtf, imtf, veq,
#: audio_field_number, chroma_dg, slots)
SLOTS_ARG = 9


def make_engine(executor, slots=None, source=None):
    return FieldJobEngine(
        executor=executor,
        read_fn=lambda sample, length: np.zeros(length, dtype=np.int16),
        read_lock=threading.Lock(),
        cfg=ENGINE_CFG,
        workers=1,
        filter_slots=slots,
        slot_source=source,
    )


def test_the_engine_publishes_the_parameters_it_is_reset_with():
    slots, writer = make_slots()
    engine = make_engine(RecordingExecutor(), slots,
                         lambda family, key: {"a": (family, key)})
    try:
        engine.reset(start=0.0, next_is_first=True, lastfieldwritten=(0, 0),
                     mtf_level=0.5, imtf_strength=0.25)
    finally:
        engine.stop()

    assert slots.live("mtf", 0.5)
    assert slots.live("video", (0.25, None))


def test_a_source_that_declines_publishes_nothing():
    slots, writer = make_slots()
    engine = make_engine(RecordingExecutor(), slots, lambda family, key: None)
    try:
        engine.reset(start=0.0, next_is_first=True, lastfieldwritten=(0, 0),
                     mtf_level=0.5)
    finally:
        engine.stop()

    assert writer.writes == []


def test_a_dispatched_job_carries_the_tokens_for_its_parameters():
    slots, _ = make_slots()
    ex = RecordingExecutor()
    engine = make_engine(ex, slots, lambda family, key: {"a": (family, key)})
    try:
        engine.reset(start=0.0, next_is_first=True, lastfieldwritten=(0, 0),
                     mtf_level=0.5, imtf_strength=0.25)
        assert ex.submitted.wait(5.0)
    finally:
        engine.stop()

    assert ex.calls[0][SLOTS_ARG] == {"video": (0, 1), "mtf": (0, 2)}


def test_the_tokens_are_released_when_the_job_finishes():
    slots, _ = make_slots()
    ex = RecordingExecutor()
    engine = make_engine(ex, slots, lambda family, key: {"a": (family, key)})
    try:
        engine.reset(start=0.0, next_is_first=True, lastfieldwritten=(0, 0),
                     mtf_level=0.5, imtf_strength=0.25)
        assert ex.submitted.wait(5.0)
        engine.pause()

        # One slot holds the job's level and the job is in flight; pin
        # the other by hand, and there is nowhere left to publish.
        assert slots.publish("mtf", 0.9, {"a": 1}) is True
        slots.acquire({"mtf": 0.9})
        assert slots.publish("mtf", 1.1, {"a": 1}) is False

        for fut in list(ex.futures):
            fut.set_result({"seq": 0, "valid": False})
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if slots.publish("mtf", 1.1, {"a": 1}):
                break
            time.sleep(0.01)
    finally:
        engine.stop()

    assert slots.live("mtf", 1.1)


def test_an_engine_with_no_slots_dispatches_none():
    ex = RecordingExecutor()
    engine = make_engine(ex)
    try:
        engine.reset(start=0.0, next_is_first=True, lastfieldwritten=(0, 0),
                     mtf_level=0.5)
        assert ex.submitted.wait(5.0)
    finally:
        engine.stop()

    assert ex.calls[0][SLOTS_ARG] is None
