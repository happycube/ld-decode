"""Unit tests for FieldJobEngine's handling of a failing dispatcher.

The dispatcher thread reads raw windows and submits jobs; if either step
raises, the decode thread blocked in next_result() must see the error
rather than wait forever, and any filter-slot references taken for the
job that never ran must be given back.
"""

import threading

import numpy as np
import pytest

from lddecode.parallel import FieldJobEngine, FilterSlots

pytestmark = [pytest.mark.unit, pytest.mark.parallel]

ENGINE_CFG = {
    "blocklen": 32768,
    "blockcut": 1024,
    "demod_blocksize": 30720,
    "readlen": 32768 * 4,
    "samples_per_field": 32768.0 * 4,
    "analog_audio": 0,
    "parity_len": {True: 32768.0 * 4, False: 32768.0 * 4},
}


class RefusingExecutor:
    """An executor that has been shut down underneath the engine."""

    def submit(self, fn, *args, key=None):
        raise RuntimeError("cannot schedule new futures after shutdown")


def make_engine(executor, read_fn, slots=None, source=None):
    return FieldJobEngine(
        executor=executor,
        read_fn=read_fn,
        read_lock=threading.Lock(),
        cfg=ENGINE_CFG,
        workers=1,
        filter_slots=slots,
        slot_source=source,
    )


def next_result_in_thread(engine):
    """Run next_result() on a helper thread so a regression hangs the
    helper, not the test run."""
    outcome = {}

    def take():
        try:
            outcome["result"] = engine.next_result()
        except BaseException as exc:
            outcome["error"] = exc

    t = threading.Thread(target=take, daemon=True)
    t.start()
    t.join(5.0)
    assert not t.is_alive(), "next_result() blocked after the dispatcher died"
    return outcome


def test_a_read_failure_is_raised_from_next_result():
    def read_fn(sample, length):
        raise IOError("Seeking too far backwards")

    engine = make_engine(RefusingExecutor(), read_fn)
    try:
        engine.reset(start=0.0, next_is_first=True, lastfieldwritten=(0, 0),
                     mtf_level=0.5)
        outcome = next_result_in_thread(engine)
    finally:
        engine.stop()

    assert isinstance(outcome.get("error"), RuntimeError)
    assert isinstance(outcome["error"].__cause__, IOError)


def test_a_submit_failure_is_raised_and_releases_the_slots():
    slots = FilterSlots({"name": "test"}, ("video", "mtf"), depth=1,
                        writer=lambda *args: None)
    engine = make_engine(
        RefusingExecutor(),
        lambda sample, length: np.zeros(length, dtype=np.int16),
        slots,
        lambda family, key: {"a": (family, key)},
    )
    try:
        engine.reset(start=0.0, next_is_first=True, lastfieldwritten=(0, 0),
                     mtf_level=0.5)
        outcome = next_result_in_thread(engine)
    finally:
        engine.stop()

    assert isinstance(outcome.get("error"), RuntimeError)
    # With depth 1 the only mtf slot holds 0.5; it can be rewritten only
    # if the failed job's reference was dropped.
    assert slots.publish("mtf", 0.9, {"a": 1}) is True
