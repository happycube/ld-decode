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

import copy
import multiprocessing
import threading
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor

import numpy as np

# Worker-process state: one RFDecode per process, built by the pool
# initializer to reproduce the parent's post-calibration filter state.
_worker_rf = None
_worker_cfg = None


def _demod_worker_init(rf_opts, decoder_params, field_cfg=None):
    global _worker_rf, _worker_cfg
    from .rfdecode import RFDecode

    _worker_rf = RFDecode(**rf_opts)
    # RFDecode's filters are a pure function of (constructor options,
    # DecoderParams): adopting the parent's snapshot and recomputing
    # reproduces its state exactly - including auto-deemp / AGC results
    # calibrated during warm-up.
    _worker_rf.DecoderParams = copy.deepcopy(decoder_params)
    _worker_rf.computefilters()
    _worker_cfg = field_cfg


def _demod_worker_block(rawinput, mtf_level):
    import scipy.fft as npfft

    return _worker_rf.demodblock(
        data=rawinput,
        fftdata=npfft.fft(rawinput),
        mtf_level=mtf_level,
        cut=True,
    )


def _decode_field_worker(seq, start, raw_span, span_begin, mtf_level,
                         audio_field_number):
    """Decode one complete field in this worker process.

    Replicates decodefield()'s window math and demod_read()'s per-block
    assembly exactly, so the result is bit-identical to an inline decode
    from the same `start`.  The parent accepts the result only when its
    block-quantized window matches the one the true chain start would
    produce (plus parameter/validation checks) - see FieldJobEngine.

    Returns a dict; on success it carries the Field stripped of its
    sample buffers (prepare_transport) plus the downscaled outputs.
    """
    import numpy as np
    import scipy.fft as npfft

    from .field import FieldNTSC, FieldPAL
    from .metrics import computeMetrics, detect_levels

    try:
        rf = _worker_rf
        cfg = _worker_cfg

        # decodefield()'s window math, verbatim
        blocksize = rf.blocklen
        dbs = blocksize - rf.blockcut - rf.blockcut_end  # demod_blocksize
        readloc = int(start - rf.blockcut)
        if readloc < 0:
            readloc = 0
        readloc_block = readloc // blocksize
        numblocks = (cfg["readlen"] // blocksize) + 2
        begin = readloc_block * blocksize
        length = numblocks * blocksize

        # demod_read()'s per-block assembly, verbatim
        t = {"input": [], "video": [], "audio": [], "efm": [], "rfhpf": []}
        for b in range(begin // dbs, ((begin + length) // dbs) + 1):
            off = b * dbs - span_begin
            rawinput = raw_span[off : off + rf.blocklen]
            if off < 0 or len(rawinput) < rf.blocklen:
                return {"seq": seq, "eof": True}

            demod = rf.demodblock(
                data=rawinput, fftdata=npfft.fft(rawinput),
                mtf_level=mtf_level, cut=True,
            )
            t["input"].append(rawinput[rf.blockcut : -rf.blockcut_end])
            for k in ("video", "audio", "efm", "rfhpf"):
                if k in demod:
                    t[k].append(demod[k])

        rv = {}
        for k in t.keys():
            rv[k] = np.concatenate(t[k]) if len(t[k]) else None
        if rv["audio"] is not None:
            rv["audio_phase1"] = rv["audio"]
            rv["audio"] = rf.audio_phase2(rv["audio"])
        rv["startloc"] = (begin // dbs) * dbs

        FieldClass = FieldPAL if rf.system == "PAL" else FieldNTSC
        f = FieldClass(
            rf,
            rv,
            anchor=None,
            initphase=False,
            trust_window=True,
            fields_written=1,   # gates first-field-only retries (truthiness)
            readloc=rv["startloc"],
            wow_level_adjust_smoothing=cfg["wow_level_adjust_smoothing"],
            wow_interpolation_method=cfg["wow_interpolation_method"],
        )
        f.process()

        if not f.valid:
            return {"seq": seq, "valid": False}

        picture, _, efm = f.downscale(linesout=cfg["output_lines"], final=True)

        metrics = computeMetrics(rf, f, None, verbose=True)
        f.precomputed_metrics = metrics

        if cfg["doDOD"]:
            f.precomputed_dropouts = f.dropout_detect()

        if cfg["useAGC"] and f.isFirstField and f.sync_confidence > 80:
            f.precomputed_levels = detect_levels(rf, f, cfg["output_lines"])

        audio = f.downscale_audio_out(
            cfg["analog_audio"], field_number=audio_field_number
        )

        nextfieldoffset = float(f.nextfieldoffset)
        f.prepare_transport()

        return {
            "seq": seq,
            "valid": True,
            "field": f,
            "picture": picture,
            "efm": efm,
            "audio": audio,
            "metrics": metrics,
            "nextfieldoffset": nextfieldoffset,
            "readloc_block": readloc_block,
            "mtf_level": mtf_level,
        }
    except Exception:
        import traceback

        return {"seq": seq, "error": traceback.format_exc()}


class FieldJobEngine:
    """Speculative whole-field decode jobs on the worker-process pool.

    A dispatcher thread reads raw windows at *predicted* start offsets
    (the true offset of field N+1 is only known after field N decodes)
    and submits complete per-field decode jobs.  Because a field's
    decode depends on its start only through the block-quantized demod
    window, a job whose window matches the one the true chain start
    produces is bit-identical to an inline decode - the decoder checks
    exactly that (plus parameter and chain validation) before accepting
    a result, and decodes inline from truth otherwise.

    Predictions chain from the last known point: each completed job
    posts its own next-start estimate (within a sample of truth), so
    blind extrapolation only ever spans the in-flight depth.  All of
    this is best-effort - prediction quality affects only the discard
    rate, never the output.
    """

    def __init__(self, executor, read_fn, read_lock, cfg, workers):
        self.executor = executor
        self.read_fn = read_fn          # (sample, length) -> raw or None
        self.read_lock = read_lock      # shared with the block cache
        self.cfg = cfg
        self.depth = workers + 4

        self._cond = threading.Condition()
        self._futures = {}              # seq -> Future (current generation)
        self._est_start = {}            # seq -> refined start estimate
        self._parity_len = dict(cfg["parity_len"])
        self._active = False
        self._stopped = False
        self._eof_seq = None
        self._next_dispatch = 0
        self._next_take = 0
        self._gen = 0
        self._cur_start = None
        self._cur_parity = True
        self._lfw = None
        self._mtf = 0.0

        self._thread = threading.Thread(
            target=self._dispatch_loop, daemon=True, name="fieldjobs"
        )
        self._thread.start()

    def reset(self, start, next_is_first, lastfieldwritten, mtf_level):
        """(Re)start speculation from known chain state."""
        with self._cond:
            self._gen += 1
            self._futures.clear()
            self._est_start.clear()
            self._next_dispatch = 0
            self._next_take = 0
            self._eof_seq = None
            self._cur_start = float(start)
            self._cur_parity = bool(next_is_first)
            self._lfw = lastfieldwritten
            self._mtf = mtf_level
            self._active = True
            self._cond.notify_all()

    def pause(self):
        """Stop dispatching and discard everything in flight (results of
        the old generation are ignored)."""
        with self._cond:
            self._gen += 1
            self._active = False
            self._futures.clear()
            self._est_start.clear()

    def stop(self):
        with self._cond:
            self._stopped = True
            self._active = False
            self._cond.notify_all()
        self._thread.join(timeout=5)

    def next_result(self):
        """The next field result in chain order ({"eof": True} when the
        dispatcher ran out of input).  Blocks until available."""
        with self._cond:
            seq = self._next_take
            self._next_take += 1
            self._cond.notify_all()
            while True:
                if self._eof_seq is not None and seq >= self._eof_seq:
                    return {"eof": True}
                fut = self._futures.pop(seq, None)
                if fut is not None:
                    break
                self._cond.wait()

        res = fut.result()
        if res.get("eof"):
            with self._cond:
                if self._eof_seq is None or seq < self._eof_seq:
                    self._eof_seq = seq
            return {"eof": True}
        return res

    # -- dispatcher internals

    def _window(self, start):
        """decodefield()'s block-quantized read window for a start."""
        c = self.cfg
        readloc = int(start - c["blockcut"])
        if readloc < 0:
            readloc = 0
        begin = (readloc // c["blocklen"]) * c["blocklen"]
        length = ((c["readlen"] // c["blocklen"]) + 2) * c["blocklen"]
        dbs = c["demod_blocksize"]
        b0 = begin // dbs
        b1 = (begin + length) // dbs
        span_begin = b0 * dbs
        span_len = (b1 - b0) * dbs + c["blocklen"]
        return begin, span_begin, span_len

    def _predict_field_number(self, start):
        """The audio-clock field number this job will be written as -
        the same rounding the field itself performs, evaluated on the
        predicted position.  Verified against truth at acceptance."""
        c = self.cfg
        if not self._lfw or c["analog_audio"] < 16000:
            return None
        begin, span_begin, _ = self._window(start)
        startloc = (begin // c["demod_blocksize"]) * c["demod_blocksize"]
        gap = (startloc - self._lfw[1]) / c["samples_per_field"]
        return int(np.round(self._lfw[0] + gap))

    def _dispatch_loop(self):
        while True:
            with self._cond:
                while not self._stopped and (
                    not self._active
                    or self._eof_seq is not None
                    or (self._next_dispatch - self._next_take) >= self.depth
                ):
                    self._cond.wait()
                if self._stopped:
                    return

                gen = self._gen
                seq = self._next_dispatch
                start = self._est_start.pop(seq, None)
                if start is None:
                    start = self._cur_start
                mtf = self._mtf
                parity = self._cur_parity
                fn = self._predict_field_number(start)

            begin, span_begin, span_len = self._window(start)
            with self.read_lock:
                raw = self.read_fn(span_begin, span_len)

            with self._cond:
                if self._gen != gen or not self._active:
                    continue
                if raw is None or len(raw) < span_len:
                    self._eof_seq = seq
                    self._cond.notify_all()
                    continue

                fut = self.executor.submit(
                    _decode_field_worker, seq, start, raw, span_begin, mtf, fn
                )
                self._futures[seq] = fut
                self._next_dispatch = seq + 1
                self._cur_start = start + self._parity_len[parity]
                self._cur_parity = not parity
                self._cond.notify_all()

            fut.add_done_callback(
                lambda ft, s=seq, st=start, g=gen: self._refine(s, st, g, ft)
            )

    def _refine(self, seq, start, gen, fut):
        """A finished job's own next-start estimate replaces the blind
        extrapolation for its successor (if not yet dispatched)."""
        try:
            res = fut.result()
        except Exception:
            return
        if not res.get("valid"):
            return

        f = res["field"]
        readloc = int(start - self.cfg["blockcut"])
        if readloc < 0:
            readloc = 0
        nxt = start + res["nextfieldoffset"] - (readloc - f.readloc)

        with self._cond:
            if self._gen != gen:
                return
            self._est_start[seq + 1] = nxt
            self._parity_len[f.isFirstField] = nxt - start
            self._cond.notify_all()


class DemodBlockCache:
    """Thread-pooled, prefetching cache of demodulated input blocks.

    read_fn(block_idx) returns the block's raw samples, or None at EOF.
    demod_fn(raw, mtf_level) demodulates one block.
    Cached values are (raw, demod) tuples; None marks EOF.
    """

    def __init__(self, read_fn, demod_fn, nthreads, ahead=96, keep_behind=8):
        self.read_fn = read_fn
        self.demod_fn = demod_fn
        self.ahead = ahead
        self.keep_behind = keep_behind

        self._nthreads = nthreads
        self._pool = ThreadPoolExecutor(
            max_workers=nthreads, thread_name_prefix="demod"
        )
        self._procs = None
        self._lock = threading.Lock()       # protects _cache/_eof_block
        self._read_lock = threading.Lock()  # serializes the raw reader
        self._cache = {}                    # (block, mtf) -> Future
        self._eof_block = None

    def enable_processes(self, rf_opts, decoder_params, nprocs=None,
                         field_cfg=None):
        """Move block demodulation into worker processes.

        The demod threads become lightweight feeders: they still read
        raw blocks under the read lock, but hand the FFT/demod compute
        to a process pool and sleep on the result - taking the ~75% of
        decode CPU that block demod represents off the GIL entirely.

        Call once decoder parameters are final (post warm-up): each
        worker builds its RFDecode from the snapshot taken here.  The
        per-block computation is unchanged, so output stays
        bit-identical to threaded and serial decode.

        field_cfg, when given, additionally equips the workers to run
        whole-field decode jobs (FieldJobEngine) on the same pool.
        """
        rf_opts = dict(rf_opts)
        # drop values demod does not need and that may not pickle
        rf_opts["extra_options"] = {
            k: v
            for k, v in rf_opts.get("extra_options", {}).items()
            if k not in ("pipe_RF_TBC",)
        }

        self._procs = ProcessPoolExecutor(
            max_workers=nprocs or self._nthreads,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_demod_worker_init,
            initargs=(rf_opts, copy.deepcopy(decoder_params), field_cfg),
        )
        procs = self._procs

        def demod_in_process(rawinput, mtf_level):
            return procs.submit(_demod_worker_block, rawinput, mtf_level).result()

        self.demod_fn = demod_in_process

    @property
    def process_executor(self):
        return self._procs

    @property
    def read_lock(self):
        return self._read_lock

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
        if self._procs is not None:
            self._procs.shutdown(wait=False, cancel_futures=True)
            self._procs = None

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
