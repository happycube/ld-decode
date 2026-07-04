"""Unit tests for lddecode.parallel.DemodBlockCache.

Uses synthetic read/demod functions so the scheduling, caching, EOF,
keying and eviction behavior can be tested exactly and quickly.
"""

import threading

import numpy as np
import pytest

from lddecode.parallel import DemodBlockCache


EOF_AT = 40


def make_fns(read_log=None):
    """Deterministic block source: block b is [b*100 .. b*100+9];
    'demod' multiplies by (1 + mtf).  EOF at block EOF_AT."""

    def read_fn(b):
        if read_log is not None:
            read_log.append(b)
        if b >= EOF_AT:
            return None
        return np.arange(b * 100, b * 100 + 10, dtype=np.float64)

    def demod_fn(raw, mtf):
        return raw * (1.0 + mtf)

    return read_fn, demod_fn


def serial_reference(brange, mtf):
    read_fn, demod_fn = make_fns()
    out = []
    for b in brange:
        raw = read_fn(b)
        if raw is None:
            return None
        out.append((raw, demod_fn(raw, mtf)))
    return out


@pytest.mark.parametrize("nthreads", [1, 4])
def test_get_span_matches_serial(nthreads):
    read_fn, demod_fn = make_fns()
    cache = DemodBlockCache(read_fn, demod_fn, nthreads=nthreads, ahead=4)
    try:
        for start in (0, 3, 10):
            span = range(start, start + 6)
            got = cache.get_span(span, 0.5)
            ref = serial_reference(span, 0.5)
            assert len(got) == len(ref)
            for (graw, gdem), (rraw, rdem) in zip(got, ref):
                np.testing.assert_array_equal(graw, rraw)
                np.testing.assert_array_equal(gdem, rdem)
    finally:
        cache.close()


def test_eof_inside_span_returns_none():
    read_fn, demod_fn = make_fns()
    cache = DemodBlockCache(read_fn, demod_fn, nthreads=2, ahead=4)
    try:
        assert cache.get_span(range(EOF_AT - 2, EOF_AT + 2), 0.0) is None
        # EOF knowledge persists; a later span before EOF still works
        assert cache.get_span(range(EOF_AT - 6, EOF_AT - 2), 0.0) is not None
        # and spans past EOF stay None without further reads
        assert cache.get_span(range(EOF_AT, EOF_AT + 4), 0.0) is None
    finally:
        cache.close()


def test_mtf_is_part_of_the_key():
    read_fn, demod_fn = make_fns()
    cache = DemodBlockCache(read_fn, demod_fn, nthreads=2, ahead=2)
    try:
        a = cache.get_span(range(0, 3), 0.0)
        b = cache.get_span(range(0, 3), 1.0)
        for (_, da), (_, db) in zip(a, b):
            np.testing.assert_array_equal(db, da * 2.0)
    finally:
        cache.close()


def test_prefetch_covers_next_span_without_new_reads():
    read_log = []
    read_fn, demod_fn = make_fns(read_log)
    cache = DemodBlockCache(read_fn, demod_fn, nthreads=2, ahead=8)
    try:
        cache.get_span(range(0, 4), 0.0)
        # wait for prefetch of blocks 4..11 to finish
        with cache._lock:
            futs = list(cache._cache.values())
        for f in futs:
            f.result()

        before = len(read_log)
        cache.get_span(range(4, 8), 0.0)
        assert len(read_log) == before, "next span should be fully prefetched"
    finally:
        cache.close()


def test_flush_forces_recompute():
    read_log = []
    read_fn, demod_fn = make_fns(read_log)
    cache = DemodBlockCache(read_fn, demod_fn, nthreads=2, ahead=0)
    try:
        cache.get_span(range(0, 3), 0.0)
        n = len(read_log)
        cache.flush()
        cache.get_span(range(0, 3), 0.0)
        assert len(read_log) == n + 3
    finally:
        cache.close()


def test_eviction_bounds_cache():
    read_fn, demod_fn = make_fns()
    cache = DemodBlockCache(read_fn, demod_fn, nthreads=2, ahead=4,
                            keep_behind=2)
    try:
        for start in range(0, 30, 3):
            cache.get_span(range(start, start + 4), 0.0)
        with cache._lock:
            assert len(cache._cache) <= 4 + 4 + 2 + 2
            assert all(k[0] >= 30 - 3 - 2 for k in cache._cache)
    finally:
        cache.close()


def test_concurrent_spans_are_consistent():
    """Same results regardless of interleaved access from two threads
    (the decode loop never does this, but the cache must not corrupt)."""
    read_fn, demod_fn = make_fns()
    cache = DemodBlockCache(read_fn, demod_fn, nthreads=4, ahead=4)
    results = {}

    def worker(name, start):
        results[name] = cache.get_span(range(start, start + 5), 0.25)

    try:
        threads = [
            threading.Thread(target=worker, args=(f"t{i}", 2)) for i in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        ref = serial_reference(range(2, 7), 0.25)
        for name, got in results.items():
            for (_, gdem), (_, rdem) in zip(got, ref):
                np.testing.assert_array_equal(gdem, rdem)
    finally:
        cache.close()
