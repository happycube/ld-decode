"""Unit tests for the per-worker block cache and the affinity pool.

Two pieces that only pay off together: WorkerBlockLRU holds the tail of
a field job's demodulated window inside the worker process, and
AffinityPool puts the job that overlaps that tail on the same worker.
Both are pure reuse - a hit returns the block a recomputation would
have produced - so the tests here are about how often the demodulation
runs, never about what it produces.

Everything is driven through injected stand-ins (a counting demod, an
in-process executor), so no worker process is spawned.
"""

import threading
import time
from concurrent.futures import Future

import pytest

from lddecode import parallel
from lddecode.parallel import (AffinityPool, FieldJobEngine, WorkerBlockLRU,
                               _worker_demod_block)

pytestmark = [pytest.mark.unit, pytest.mark.parallel]


# --- the per-worker block cache ------------------------------------------


class CountingRF:
    """Stands in for the worker's RFDecode: records every demodulation
    and returns a value that identifies the block and level."""

    def __init__(self):
        self.calls = []

    def demodblock(self, data=None, mtf_level=0, cut=False):
        assert cut is True
        self.calls.append((data, mtf_level))
        return {"video": (data, mtf_level)}


@pytest.fixture
def worker_rf(monkeypatch):
    """Install a counting RFDecode and an empty cache in the module
    globals the worker path reads."""
    rf = CountingRF()
    monkeypatch.setattr(parallel, "_worker_rf", rf)
    monkeypatch.setattr(parallel, "_worker_block_lru", WorkerBlockLRU())
    return rf


def demod_window(blocks, mtf=0.0, imtf=0.0, veq=None):
    """One field job's per-block loop, as _decode_field_worker runs it."""
    return [_worker_demod_block(b, b * 10, mtf, imtf, veq) for b in blocks]


def test_overlapping_windows_demodulate_each_shared_block_once(worker_rf):
    first = demod_window(range(0, 30))
    assert len(worker_rf.calls) == 30

    second = demod_window(range(25, 55))
    # Only the five blocks the second window adds beyond the first.
    assert len(worker_rf.calls) == 30 + 30 - 5

    # And the shared blocks are the objects the first window got.
    for a, b in zip(first[25:], second[:5]):
        assert a is b


def test_a_changed_mtf_level_demodulates_the_block_again(worker_rf):
    demod_window(range(0, 4), mtf=0.0)
    demod_window(range(0, 4), mtf=0.7)
    assert len(worker_rf.calls) == 8
    assert [c[1] for c in worker_rf.calls] == [0.0] * 4 + [0.7] * 4


def test_a_changed_imtf_strength_demodulates_the_block_again(worker_rf):
    demod_window(range(0, 4), imtf=0.0)
    demod_window(range(0, 4), imtf=0.3)
    assert len(worker_rf.calls) == 8


def test_a_changed_video_eq_demodulates_the_block_again(worker_rf):
    demod_window(range(0, 4), veq=None)
    demod_window(range(0, 4), veq=(2.0e6, 0.4))
    assert len(worker_rf.calls) == 8


def test_an_equal_video_eq_in_a_list_is_the_same_key(worker_rf):
    """The worker normalizes veq to a tuple before it syncs the filters
    (see _sync_worker_veq), so the key must normalize the same way or a
    list would demodulate a block the filters already match."""
    demod_window(range(0, 4), veq=(2.0e6, 0.4))
    demod_window(range(0, 4), veq=[2.0e6, 0.4])
    assert len(worker_rf.calls) == 4


def test_capacity_bounds_what_is_held(worker_rf):
    lru = parallel._worker_block_lru
    demod_window(range(0, 30))
    assert len(lru) == lru.capacity

    # The tail is held, the head is gone.
    demod_window(range(22, 30))
    assert len(worker_rf.calls) == 30
    demod_window(range(0, 8))
    assert len(worker_rf.calls) == 38


def test_a_hit_keeps_the_least_recently_used_entry_out():
    lru = WorkerBlockLRU(capacity=3)
    computed = []

    def make(k):
        return lambda: computed.append(k) or k

    for k in "abc":
        lru.get(k, make(k))
    lru.get("a", make("a"))          # refreshes a, so b is now oldest
    lru.get("d", make("d"))          # evicts b
    assert lru.get("a", make("a")) == "a"
    assert computed == ["a", "b", "c", "d"]
    assert lru.hits == 2
    assert lru.misses == 4


def test_clear_drops_everything(worker_rf):
    demod_window(range(0, 4))
    parallel._worker_block_lru.clear()
    demod_window(range(0, 4))
    assert len(worker_rf.calls) == 8


# --- the affinity pool ---------------------------------------------------


class InlineExecutor:
    """Runs submitted work on the calling thread."""

    def __init__(self):
        self.calls = []
        self.shutdowns = []
        self._processes = {}

    def submit(self, fn, *args):
        self.calls.append(args)
        fut = Future()
        fut.set_result(fn(*args))
        return fut

    def shutdown(self, wait=True, cancel_futures=False):
        self.shutdowns.append((wait, cancel_futures))


class ManualExecutor:
    """Accepts work and never finishes it until the test says so."""

    def __init__(self):
        self.futures = []
        self.shutdowns = []
        self._processes = {}

    def submit(self, fn, *args):
        fut = Future()
        fut.set_running_or_notify_cancel()
        self.futures.append(fut)
        return fut

    def shutdown(self, wait=True, cancel_futures=False):
        self.shutdowns.append((wait, cancel_futures))


def make_pool(n, factory=InlineExecutor, **kw):
    made = []

    def executor_factory():
        made.append(factory())
        return made[-1]

    return AffinityPool(n, executor_factory=executor_factory, **kw), made


@pytest.mark.parametrize("n", [1, 2, 4, 8])
def test_consecutive_pairs_share_an_executor_and_the_load_is_balanced(n):
    pool, made = make_pool(n)
    counts = [0] * n
    for seq in range(40):
        i = pool.index_for(seq)
        counts[i] += 1
        assert pool.index_for(seq) == pool.index_for(seq ^ 1)

    assert sum(counts) == 40
    # 20 pairs over n workers: the remainder is at most one whole pair.
    assert max(counts) - min(counts) <= pool.group_size


def test_keyless_work_goes_round_robin():
    pool, made = make_pool(3)
    assert [pool.index_for(None) for _ in range(7)] == [0, 1, 2, 0, 1, 2, 0]


def test_submit_routes_to_the_keyed_executor():
    pool, made = make_pool(2)
    pool.submit(lambda a: a, "x", key=0)
    pool.submit(lambda a: a, "y", key=1)
    pool.submit(lambda a: a, "z", key=2)
    assert [c[0] for c in made[0].calls] == ["x", "y"]
    assert [c[0] for c in made[1].calls] == ["z"]


def test_close_drains_in_flight_work_from_every_executor():
    pool, made = make_pool(3, ManualExecutor)
    for seq in range(6):
        pool.submit(None, key=seq)
    assert all(len(ex.futures) == 2 for ex in made)

    def finish():
        time.sleep(0.05)
        for ex in made:
            for fut in ex.futures:
                fut.set_result(None)

    finisher = threading.Thread(target=finish)
    finisher.start()
    try:
        pool.close(drain_timeout=10)
    finally:
        finisher.join()

    # It waited rather than timing out, and every executor was told to
    # stop taking new work first.
    assert all(fut.done() for ex in made for fut in ex.futures)
    assert all(ex.shutdowns == [(False, True)] for ex in made)
    assert pool._inflight == set()


def test_shutdown_does_not_wait_and_terminates_nothing():
    """What a pool restart uses: it must not block on in-flight jobs
    and must leave the workers to finish and join themselves."""
    class FakeProc:
        terminated = 0

        def terminate(self):
            FakeProc.terminated += 1

    pool, made = make_pool(2, ManualExecutor)
    for ex in made:
        ex._processes = {0: FakeProc()}
    pool.submit(None, key=0)
    pool.submit(None, key=2)

    pool.shutdown()
    assert all(ex.shutdowns == [(False, True)] for ex in made)
    assert not any(fut.done() for ex in made for fut in ex.futures)
    assert FakeProc.terminated == 0


def test_close_terminates_workers_that_never_drain():
    class FakeProc:
        def __init__(self):
            self.terminated = 0

        def terminate(self):
            self.terminated += 1

    pool, made = make_pool(2, ManualExecutor)
    procs = []
    for ex in made:
        proc = FakeProc()
        procs.append(proc)
        ex._processes = {0: proc}
    pool.submit(None, key=0)
    pool.submit(None, key=2)

    pool.close(drain_timeout=0.05)
    assert [p.terminated for p in procs] == [1, 1]


# --- the two together ----------------------------------------------------


PAL_CFG = {
    "blocklen": 32768,
    "blockcut": 1024,
    "demod_blocksize": 31712,
    "readlen": 870400,
    "samples_per_field": 800000.0,
    "analog_audio": 0,
    "parity_len": {True: 798720.0, False: 801280.0},
}

NTSC_CFG = dict(
    PAL_CFG,
    readlen=753664,
    samples_per_field=667333.3333333333,
    parity_len={True: 668546.0, False: 666004.0},
)


def field_block_ranges(cfg, fields):
    """The block ranges a run of `fields` sequential jobs demodulates,
    placed by the engine's own window math."""
    engine = FieldJobEngine(
        executor=InlineExecutor(),
        read_fn=lambda sample, length: None,
        read_lock=threading.Lock(),
        cfg=cfg,
        workers=1,
    )
    try:
        dbs = cfg["demod_blocksize"]
        length = ((cfg["readlen"] // cfg["blocklen"]) + 2) * cfg["blocklen"]
        out, start, parity = [], 0.0, True
        for _ in range(fields):
            begin = engine._window(start)[0]
            out.append(range(begin // dbs, ((begin + length) // dbs) + 1))
            start += cfg["parity_len"][parity]
            parity = not parity
        return out
    finally:
        engine.stop()


def reuse_ratio(cfg, workers, fields=40, group_size=2):
    """Demodulations per distinct block over a run of field jobs."""
    pool, _ = make_pool(workers, group_size=group_size)
    lrus = [WorkerBlockLRU() for _ in range(workers)]
    computed = []
    ranges = field_block_ranges(cfg, fields)

    for seq, brange in enumerate(ranges):
        lru = lrus[pool.index_for(seq)]
        for b in brange:
            lru.get(b, lambda b=b: (computed.append(b), b)[1])

    distinct = len({b for r in ranges for b in r})
    return len(computed) / distinct


@pytest.mark.parametrize("workers", [2, 4, 8])
def test_pair_affinity_recovers_half_the_window_overlap(workers):
    """A PAL field's window spans about thirty demod blocks and advances
    by about twenty-five, so an uncached run demodulates 1.18 blocks per
    distinct block.  Pinning pairs recovers the overlap inside a pair
    but not the one across the boundary between pairs, which is half of
    it - and the result does not depend on the worker count."""
    assert reuse_ratio(PAL_CFG, workers) == pytest.approx(1.0879, abs=1e-4)


def test_without_affinity_the_overlap_is_all_lost():
    """Every job on its own worker: the reference the pairing improves
    on (and what a ProcessPoolExecutor's own scheduling approximates)."""
    ranges = field_block_ranges(PAL_CFG, 40)
    distinct = len({b for r in ranges for b in r})
    assert sum(len(r) for r in ranges) / distinct == pytest.approx(
        1.1807, abs=1e-4
    )


def test_one_worker_recovers_all_of_it():
    """The floor pair affinity is working towards: with a single worker
    every job follows its predecessor and the cache catches every
    overlapping block."""
    assert reuse_ratio(PAL_CFG, 1) == pytest.approx(1.0, abs=1e-9)


def test_ntsc_keeps_less_because_its_windows_overlap_more():
    """NTSC reads a shorter window but advances less, so it starts from
    a bigger overlap (1.26) and pairing leaves more of it on the table."""
    assert reuse_ratio(NTSC_CFG, 4) == pytest.approx(1.1311, abs=1e-4)


@pytest.mark.parametrize(
    "cfg, span, overlap", [(PAL_CFG, 29, (4, 6)), (NTSC_CFG, 26, (5, 7))]
)
def test_the_capacity_is_the_largest_overlap_a_job_can_hand_on(
    cfg, span, overlap
):
    """The cache is useful only if it still holds the blocks the second
    job of a pair asks for, and useful only up to that: blocks are
    demodulated in ascending order, so what a job hands on is the tail
    of its window, and holding more than the overlap holds blocks no
    reachable job can ask for.  Both systems fit in 8 with one spare."""
    ranges = field_block_ranges(cfg, 60)
    assert len(ranges[0]) == span
    overlaps = [len(set(a) & set(b)) for a, b in zip(ranges, ranges[1:])]
    assert (min(overlaps), max(overlaps)) == overlap
    assert max(overlaps) < WorkerBlockLRU().capacity
