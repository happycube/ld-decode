"""Unit tests for lddecode.parallel.OrderedOutputLane, the thread the
output stage runs on when fields decode in parallel.

The lane's contract is what keeps a threaded decode's output identical
to the serial one: submitted callables run one at a time, in
submission order, and a failure surfaces on the submitting thread
rather than being lost on the lane's thread.
"""

import threading

import pytest

from lddecode.parallel import OrderedOutputLane

pytestmark = [pytest.mark.unit, pytest.mark.parallel]


def test_callables_run_in_submission_order_on_the_lane_thread():
    lane = OrderedOutputLane(depth=4)
    seen = []
    try:
        for i in range(10):
            lane.submit(lambda n: seen.append((n, threading.get_ident())), i)
    finally:
        lane.close()
    assert [n for n, _ in seen] == list(range(10))
    threads = {t for _, t in seen}
    assert len(threads) == 1 and threading.get_ident() not in threads


def test_close_waits_for_the_queued_work():
    lane = OrderedOutputLane(depth=2)
    gate = threading.Event()
    done = []
    lane.submit(gate.wait, 5.0)
    lane.submit(done.append, "after")
    gate.set()
    lane.close()
    assert done == ["after"]


def test_a_failure_surfaces_at_the_next_submit_and_drops_later_work():
    lane = OrderedOutputLane(depth=4)
    ran = []
    failed = threading.Event()

    def boom():
        failed.set()
        raise IOError("disk full")

    lane.submit(boom)
    assert failed.wait(5.0)
    # give the lane's thread the moment it needs to record the failure
    lane._thread.join(0.5) if False else None
    for _ in range(50):
        if lane.failed:
            break
        threading.Event().wait(0.01)
    assert lane.failed

    with pytest.raises(IOError, match="disk full"):
        lane.submit(ran.append, "never")
    lane.close()
    assert ran == []


def test_a_failure_not_yet_seen_surfaces_at_close():
    lane = OrderedOutputLane(depth=4)

    def boom():
        raise ValueError("last field")

    lane.submit(boom)
    with pytest.raises(ValueError, match="last field"):
        lane.close()


def test_submit_after_close_is_refused():
    lane = OrderedOutputLane(depth=1)
    lane.close()
    with pytest.raises(RuntimeError):
        lane.submit(print)
