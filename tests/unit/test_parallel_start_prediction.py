"""Unit tests for FieldJobEngine's start prediction.

Each job is dispatched with a predicted field start, and its result is
used only if that prediction lands in the same demod window as the
true start; a miss is re-decoded inline on the commit thread.  The
prediction extrapolates per-parity field lengths learned from finished
jobs, re-anchored to the freshest finished estimate.  These tests pin
the two ways that learning used to go stale: one parity's length was
never measured when jobs finished out of order, and a re-anchoring that
landed while the dispatcher was reading a span was overwritten.
"""

import threading
import types
from concurrent.futures import Future

import numpy as np
import pytest

from lddecode.parallel import FieldJobEngine

pytestmark = [pytest.mark.unit, pytest.mark.parallel]

NOMINAL = 32768.0 * 4
BLOCKCUT = 1024

ENGINE_CFG = {
    "blocklen": 32768,
    "blockcut": BLOCKCUT,
    "demod_blocksize": 30720,
    "readlen": 32768 * 4,
    "samples_per_field": NOMINAL,
    "analog_audio": 0,
    "parity_len": {True: NOMINAL, False: NOMINAL},
}


class HeldExecutor:
    """Takes jobs and never runs them; the test finishes them itself."""

    def __init__(self):
        self.jobs = []

    def submit(self, fn, *args, key=None):
        fut = Future()
        self.jobs.append((args, fut))
        return fut


def make_engine(read_fn=None, executor=None):
    return FieldJobEngine(
        executor=executor or HeldExecutor(),
        read_fn=read_fn or (lambda sample, length: None),
        read_lock=threading.Lock(),
        cfg=ENGINE_CFG,
        workers=1,
    )


def finished(start, next_start, first):
    """A completed job whose refined next-start estimate is next_start."""
    readloc = int(start - BLOCKCUT)
    field = types.SimpleNamespace(readloc=readloc, isFirstField=first)
    fut = Future()
    fut.set_result({"valid": True, "field": field,
                    "nextfieldoffset": next_start - start})
    return fut


def test_both_parities_are_learned_when_jobs_finish_out_of_order():
    """Pairs share a worker, so job 2k typically finishes before job
    2k-1; every even field then finishes after its successor's
    predecessor - the case that used to be dropped."""
    engine = make_engine()
    try:
        lengths = {True: NOMINAL - 70.0, False: NOMINAL + 130.0}
        starts = [1000.0]
        for seq in range(60):
            starts.append(starts[-1] + lengths[seq % 2 == 0])

        order = [0]
        for k in range(29):
            order += [2 * k + 2, 2 * k + 1]
        for seq in order:
            engine._refine(seq, starts[seq], 0,
                           finished(starts[seq], starts[seq + 1], seq % 2 == 0))

        for parity, length in lengths.items():
            assert engine._parity_len[parity] == pytest.approx(length, abs=0.5)
    finally:
        engine.stop()


def test_a_reanchoring_during_a_span_read_is_kept():
    """The dispatcher reads a span outside the lock; a job finishing
    meanwhile re-anchors the chain, and the successor must extrapolate
    from that, not from the prediction the read began with."""
    reading = threading.Event()
    release = threading.Event()
    third = threading.Event()
    calls = []

    def read_fn(sample, length):
        calls.append(sample)
        if len(calls) == 2:
            reading.set()
            assert release.wait(5)
        if len(calls) > 2:
            third.set()  # seq 1 is submitted and its successor set
            return None  # end of input: the dispatcher stops here
        return np.zeros(length, dtype=np.int16)

    executor = HeldExecutor()
    engine = make_engine(read_fn, executor)
    try:
        start = 10 * NOMINAL
        engine.reset(start, True, None, 0.0)
        assert reading.wait(5)  # seq 0 is out, seq 1's span is being read

        anchored = start + NOMINAL + 500.0  # seq 1 is really here
        engine._refine(0, start, engine._gen,
                       finished(start, anchored, True))
        release.set()

        assert third.wait(5)
        assert len(executor.jobs) == 2
        assert engine._cur_start == anchored + engine._parity_len[False]
    finally:
        release.set()
        engine.stop()
