"""Parallel field decoding support.

RF demodulation - about three quarters of decode time - runs on a fixed
grid of overlapping input blocks: demod_read consumes blocks spaced
demod_blocksize apart, each blocklen samples long, and concatenates the
cut middles.  Each block's demodulation is a pure function of
(block index, mtf_level) given the decoder's filter state, which makes
it cacheable and safe to compute out of order.

DemodBlockCache runs those per-block demodulations on a thread pool and
prefetches sequentially ahead of the (strictly in-order) decode loop.
scipy's FFT releases the GIL, so plain threads parallelize the bulk of
the work while the decode loop continues on the main thread.

Correctness invariants:

- All raw reads happen under one lock: the reader is a single seekable
  handle (or an internally-buffered pipe), exactly as the serial path
  uses it.
- The cache is only consulted once ``LDdecode.pipeline_warm`` is set.
  Before that, decoder parameters (AGC levels, auto-deemp filters) are
  still being recalibrated mid-stream and could change under a
  prefetched block.
- ``mtf_level`` is part of the cache key, and any post-warm-up
  parameter change happens via a field redo, which flushes the cache.
- The assembled output is the same per-block concatenation the serial
  path produces, so decode results are bit-identical for any thread
  count.
"""

import threading
from concurrent.futures import Future, ThreadPoolExecutor


class DemodBlockCache:
    """Thread-pooled, prefetching cache of demodulated input blocks.

    read_fn(block_idx) returns the block's raw samples, or None at EOF.
    demod_fn(raw, mtf_level) demodulates one block.
    Cached values are (raw, demod) tuples; None marks EOF.
    """

    def __init__(self, read_fn, demod_fn, nthreads, ahead=64, keep_behind=8):
        self.read_fn = read_fn
        self.demod_fn = demod_fn
        self.ahead = ahead
        self.keep_behind = keep_behind

        self._pool = ThreadPoolExecutor(
            max_workers=nthreads, thread_name_prefix="demod"
        )
        self._lock = threading.Lock()       # protects _cache/_eof_block
        self._read_lock = threading.Lock()  # serializes the raw reader
        self._cache = {}                    # (block, mtf) -> Future
        self._eof_block = None

    def get_span(self, brange, mtf_level):
        """Demodulated blocks for brange (list of (raw, demod)), or None
        if EOF falls inside the span.  Schedules a sequential prefetch
        beyond the span at the same mtf_level."""
        with self._lock:
            futures = [self._ensure(b, mtf_level) for b in brange]

            for b in range(brange.stop, brange.stop + self.ahead):
                if self._eof_block is not None and b >= self._eof_block:
                    break
                self._ensure(b, mtf_level)

            self._evict(brange.start, mtf_level)

        out = []
        for fut in futures:
            r = fut.result()
            if r is None:
                return None
            out.append(r)

        return out

    def flush(self):
        """Drop all cached and pending work (decoder parameters changed).
        EOF knowledge is parameter-independent and survives."""
        with self._lock:
            for fut in self._cache.values():
                fut.cancel()
            self._cache.clear()

    def close(self):
        self.flush()
        self._pool.shutdown(wait=False, cancel_futures=True)

    # internal - callers hold self._lock

    def _ensure(self, b, mtf_level):
        key = (b, mtf_level)
        fut = self._cache.get(key)

        if fut is None:
            if self._eof_block is not None and b >= self._eof_block:
                fut = Future()
                fut.set_result(None)
            else:
                fut = self._pool.submit(self._compute, b, mtf_level)
            self._cache[key] = fut

        return fut

    def _evict(self, current_start, mtf_level):
        cutoff = current_start - self.keep_behind
        stale = [
            key for key in self._cache
            if key[0] < cutoff or key[1] != mtf_level
        ]
        for key in stale:
            self._cache.pop(key).cancel()

    def _compute(self, b, mtf_level):
        with self._read_lock:
            raw = self.read_fn(b)

        if raw is None:
            with self._lock:
                if self._eof_block is None or b < self._eof_block:
                    self._eof_block = b
            return None

        return raw, self.demod_fn(raw, mtf_level)
