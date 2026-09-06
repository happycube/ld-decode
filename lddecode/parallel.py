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
- ``mtf_level`` and ``inverse_mtf_strength`` are part of the cache
  key, and any post-warm-up
  parameter change happens via a field redo, which flushes the cache.
- The assembled output is the same per-block concatenation the serial
  path produces, so decode results are bit-identical for any thread
  count.
- Worker processes cache the blocks they demodulate under the same key
  (WorkerBlockLRU), and consecutive field jobs are pinned to one worker
  so that cache sees the overlap between their windows (AffinityPool).
  Both are pure reuse of an identical computation: they change how
  often a block is demodulated, never what it demodulates to.
- The filters every worker reads are published once into a shared
  segment and adopted read-only (shared_filter_bank, FilterSlots), so
  the pool holds one copy instead of one per process.  A worker only
  reads a rewritable slot while it holds the publication id its job
  carries, and the parent only rewrites a slot no job in flight names;
  otherwise the worker rebuilds the filter privately, which is what it
  did before the segment existed.  Either way it demodulates against
  the same numbers.
"""

import copy
import multiprocessing
import signal
import threading
from collections import OrderedDict
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures import wait as futures_wait

import numpy as np

from . import shared_filter_bank
from .dsp import concatenate_blocks


class WorkerBlockLRU:
    """Per-process cache of demodulated input blocks for field jobs.

    A field's read window spans about thirty demod blocks and advances
    by about twenty-five, so the last handful of blocks one job
    demodulates are the first its successor needs.  Nothing shares them
    today: the block cache's own cache lives in the parent, and a field
    job demodulates its whole window inside the worker.  Holding the
    tail of a job's window until the next one arrives turns that
    overlap into hits, provided consecutive jobs reach the same process
    (see AffinityPool).

    Capacity is in blocks and only has to cover the overlap, which
    measures 4-6 blocks on PAL and 5-7 on NTSC; more than that holds
    demodulated blocks no reachable job can ask for.  It is resident
    memory the worker did not hold before - a cached block is 834 KiB
    on PAL and 706 KiB on NTSC, so a full cache is 6.5 / 5.5 MiB per
    worker process.

    Thread-safety: an instance belongs to one worker process, which
    runs one work item at a time, so no lock is taken.  The parent
    never touches it.
    """

    def __init__(self, capacity=8):
        self.capacity = capacity
        self.hits = 0
        self.misses = 0
        self._entries = OrderedDict()

    def get(self, key, compute):
        """The cached value for key, or compute() stored under it."""
        # Membership, not a sentinel default: whether a value is worth
        # caching is the caller's business, and a cache that silently
        # recomputes one particular value is a trap to debug.
        if key in self._entries:
            self._entries.move_to_end(key)
            self.hits += 1
            return self._entries[key]

        self.misses += 1
        entry = compute()
        self._entries[key] = entry
        while len(self._entries) > self.capacity:
            self._entries.popitem(last=False)
        return entry

    def clear(self):
        self._entries.clear()
        self.hits = 0
        self.misses = 0

    def __len__(self):
        return len(self._entries)


# Worker-process state: one RFDecode per process, built by the pool
# initializer to reproduce the parent's post-calibration filter state.
_worker_rf = None
_worker_cfg = None
_worker_block_lru = WorkerBlockLRU()
# The shared segment's views, and whether what the bank currently holds
# for each slot family came out of it (see _sync_worker_video).
_worker_shared = None
_worker_video_slot = False
_worker_mtf_slot = False
# Developer control (LDDECODE_SHARED_FILTER_STATS=1): how many jobs read
# each slot family out of the segment rather than rebuilding it.
_worker_slot_stats = {"video": [0, 0], "mtf": [0, 0]}


def _demod_worker_init(rf_opts, decoder_params, field_cfg=None,
                       shared_filters=None):
    global _worker_rf, _worker_cfg, _worker_shared
    global _worker_video_slot, _worker_mtf_slot
    import logging
    import os
    import time as _time

    # A terminal Ctrl-C delivers SIGINT to the whole foreground process
    # group, workers included.  A KeyboardInterrupt raised inside a
    # worker's compiled demod - or while it holds a multiprocessing queue
    # lock - wedges the worker (futex_wait) and the parent then hangs
    # joining it at exit.  Ignore SIGINT here so only the main process
    # handles the interrupt; it tears the pool down (see DemodBlockCache).
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    from . import utils_logging as logs
    from .rfdecode import RFDecode

    def _exit_with_parent(ppid=os.getppid()):
        # A SIGKILLed parent can't shut the pool down; without this,
        # workers outlive it holding ~200 MB each.
        while os.getppid() == ppid:
            _time.sleep(5)
        os._exit(0)

    threading.Thread(target=_exit_with_parent, daemon=True).start()

    if logs.logger is None:
        # Field code logs decode conditions (bad windows, dropped
        # fields).  In a worker those are speculative: the parent
        # re-decodes inline and logs the authoritative message, so
        # worker logging stays quiet rather than duplicating it.
        logger = logging.getLogger("lddecode.fieldworker")
        logger.addHandler(logging.NullHandler())
        logs.logger = logger

    _worker_rf = RFDecode(**rf_opts)
    # RFDecode's filters are a pure function of (constructor options,
    # DecoderParams): adopting the parent's snapshot and recomputing
    # reproduces its state exactly - including auto-deemp / AGC results
    # calibrated during warm-up.
    _worker_rf.DecoderParams = copy.deepcopy(decoder_params)
    _worker_rf.computefilters()
    if shared_filters is not None:
        # The bank this worker just built duplicates, bin for bin, the
        # one the parent published; swap the invariant half of it for
        # read-only views and let the private copies go.
        _worker_shared = shared_filter_bank.attach(shared_filters)
        _worker_rf.adopt_shared_filters(_worker_shared.arrays)
    _worker_cfg = field_cfg
    _worker_video_slot = False
    _worker_mtf_slot = False
    _worker_block_lru.clear()


def _sync_worker_video(imtf_strength, veq, slot=None):
    """Bring this worker's video output filters to a job's parameters.

    The inverse-MTF strength and the dynamic EQ propagate per job (like
    mtf_level) rather than by respawning the pool, and between them they
    decide FVideo_rfft32 and FVideo_rfft_dc.  Three ways to arrive at
    those, in order of preference:

    - a slot in the shared segment the parent filled for exactly this
      key, identified by the publication id the job carries;
    - the bank as it stands, when the parameters have not moved and what
      it holds is this worker's own;
    - a private rebuild, which is what every worker did before the
      segment existed.

    The middle case is why the slot source is tracked.  A slot view is
    the parent's to rewrite once no job naming it is in flight, so a
    bank still pointing at one when a job arrives without a matching id
    has to rebuild rather than read on, even though its parameters are
    unchanged.

    Thread-safety: this and the module state it keeps belong to one
    worker process, which runs one work item at a time; nothing here is
    reachable from the parent, and no lock is taken.  The same holds for
    _sync_worker_mtf.
    """
    global _worker_video_slot

    veq = tuple(veq) if veq else None
    params = _worker_rf.DecoderParams
    moved = (params.get("inverse_mtf_strength", 0.0) != imtf_strength
             or params.get("video_eq_auto") != veq)
    params["inverse_mtf_strength"] = imtf_strength
    params["video_eq_auto"] = veq

    arrays = None
    if slot is not None and _worker_shared is not None:
        arrays = _worker_shared.slot("video", slot[0], slot[1])

    if arrays is not None:
        for name, view in arrays.items():
            _worker_rf.Filters[name] = view
        _worker_video_slot = True
        _worker_slot_stats["video"][0] += 1
        return

    _worker_slot_stats["video"][1] += 1
    if moved or _worker_video_slot:
        _worker_rf.recompute_fvideo()
        _worker_video_slot = False


def _sync_worker_mtf(mtf_level, slot=None):
    """Prime mtf_response()'s held value from the shared segment.

    mtf_response() already keeps the last exponent it was asked for, so
    a slot is adopted by writing that cache: every block of the job then
    reads the parent's array instead of raising MTF_half to the power
    itself.  With no matching slot, a cache that came from one is
    dropped - the parent may since have rewritten it - and the bank
    rebuilds the response on the first block, as it always did.
    """
    global _worker_mtf_slot

    arrays = None
    if slot is not None and _worker_shared is not None:
        arrays = _worker_shared.slot("mtf", slot[0], slot[1])

    if arrays is not None:
        _worker_rf._mtf_response_cache = (mtf_level, arrays["MTF_response"])
        _worker_mtf_slot = True
        _worker_slot_stats["mtf"][0] += 1
        return

    _worker_slot_stats["mtf"][1] += 1
    if _worker_mtf_slot:
        _worker_rf._mtf_response_cache = None
        _worker_mtf_slot = False


def _worker_demod_block(b, rawinput, mtf_level, imtf_strength, veq):
    """One demodulated block of a field job, from this process's cache
    when an earlier job on this worker already produced it.

    The key carries every filter state a job can arrive with - the
    absolute block index plus the three parameters the worker is
    synced to before it decodes - so a hit is the same block the
    recomputation would produce and nothing needs invalidating.  A
    parameter change that is not in the key (an AGC readjustment)
    respawns the pool, which discards the cache with the process.

    The cached dict is handed to more than one job.  Every array in it
    is freshly allocated by demodblock and is only ever read here
    (concatenate_blocks copies), so the sharing is safe.
    """
    return _worker_block_lru.get(
        (b, mtf_level, imtf_strength, tuple(veq) if veq else None),
        lambda: _worker_rf.demodblock(
            data=rawinput, mtf_level=mtf_level, cut=True
        ),
    )


def _demod_worker_block(rawinput, mtf_level, imtf_strength=None, veq=None):
    if imtf_strength is not None:
        _sync_worker_video(imtf_strength, veq)
    # No slot: these carry no job key, so any slot the bank is still
    # pointing at has to go before the block is demodulated.
    _sync_worker_mtf(mtf_level)
    return _worker_rf.demodblock(
        data=rawinput,
        mtf_level=mtf_level,
        cut=True,
    )


def _decode_field_worker(seq, start, raw_span, span_begin, mtf_level,
                         imtf_strength, veq, audio_field_number,
                         chroma_dg=None, slots=None):
    """Decode one complete field in this worker process.

    Replicates decodefield()'s window math and demod_read()'s per-block
    assembly exactly, so the result is bit-identical to an inline decode
    from the same `start`.  The parent accepts the result only when its
    block-quantized window matches the one the true chain start would
    produce (plus parameter/validation checks) - see FieldJobEngine.

    Returns a dict; on success it carries the Field stripped of its
    sample buffers (prepare_transport) plus the downscaled outputs.
    """
    import os
    import sys

    import numpy as np

    from .field import (FieldNTSC, FieldPAL, apply_chroma_dg_correction_output,
                        chroma_dg_output_key)
    from .metrics import computeMetrics, detect_levels

    try:
        _sync_worker_video(imtf_strength, veq,
                           slots.get("video") if slots else None)
        _sync_worker_mtf(mtf_level, slots.get("mtf") if slots else None)
        rf = _worker_rf
        cfg = _worker_cfg
        stats = os.environ.get("LDDECODE_BLOCK_LRU_STATS") == "1"
        if os.environ.get("LDDECODE_SHARED_FILTER_STATS") == "1":
            # Developer control: whether the parent's slots are actually
            # reaching the jobs, which depends on the publication landing
            # before the job that carries its key (see FilterSlots).
            # One line per job, cumulative for the process.
            print(
                "[shared-slots] pid %d seq %d shared %s mtf_level %.4f "
                "video %d/%d mtf %d/%d"
                % (os.getpid(), seq, _worker_shared is not None, mtf_level,
                   _worker_slot_stats["video"][0],
                   sum(_worker_slot_stats["video"]),
                   _worker_slot_stats["mtf"][0],
                   sum(_worker_slot_stats["mtf"])),
                file=sys.stderr,
            )

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
        brange = range(begin // dbs, ((begin + length) // dbs) + 1)
        for b in brange:
            off = b * dbs - span_begin
            rawinput = raw_span[off : off + rf.blocklen]
            if off < 0 or len(rawinput) < rf.blocklen:
                return {"seq": seq, "eof": True}

            demod = _worker_demod_block(
                b, rawinput, mtf_level, imtf_strength, veq
            )
            t["input"].append(rawinput[rf.blockcut : -rf.blockcut_end])
            for k in ("video", "audio", "efm", "rfhpf"):
                if k in demod:
                    t[k].append(demod[k])

        if stats:
            # Developer control: how much of the window overlap this
            # worker's cache is actually catching, which depends on the
            # job-to-worker mapping holding (see AffinityPool).  One
            # line per job, cumulative for the process.
            lru = _worker_block_lru
            print(
                "[block-lru] pid %d seq %d blocks %d %d hits %d misses %d"
                % (os.getpid(), seq, brange.start, brange.stop,
                   lru.hits, lru.misses),
                file=sys.stderr,
            )

        rv = {}
        for k in t.keys():
            rv[k] = concatenate_blocks(t[k]) if len(t[k]) else None
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
        # the 2T MTF servo needs to know what parameters each field was
        # demodulated under (measurements are closed-loop)
        f.decoded_mtf_level = mtf_level
        f.decoded_imtf_strength = imtf_strength
        f.decoded_video_eq = tuple(veq) if veq else None
        f.process()

        if not f.valid:
            return {"seq": seq, "valid": False}

        picture, _, efm = f.downscale(linesout=cfg["output_lines"], final=True)

        # The TBC output's chroma differential gain/phase correction is
        # a pure function of the picture and the servo's (slope, phase),
        # so it runs here on a copy - f.dspicture stays raw for the
        # servos - and rides the result with the key it was computed
        # under; the writer keeps it only while that key is current
        # (see field.chroma_dg_output_picture).
        f.chroma_dg_applied = None
        if chroma_dg is not None and any(chroma_dg):
            slope, phase = chroma_dg
            picture = apply_chroma_dg_correction_output(picture, f, slope, phase)
            f.chroma_dg_applied = chroma_dg_output_key(rf, slope, phase)

        metrics = computeMetrics(rf, f, None, verbose=True)
        f.precomputed_metrics = metrics

        if cfg["doDOD"]:
            f.precomputed_dropouts = f.dropout_detect()

        if cfg["useAGC"] and f.isFirstField and f.sync_confidence > 80:
            f.precomputed_levels = detect_levels(rf, f, cfg["output_lines"])

        audio = f.downscale_audio_out(
            cfg["analog_audio"], field_number=audio_field_number,
            audio_bits=cfg.get("audio_bits", 16)
        )

        nextfieldoffset = float(f.nextfieldoffset)
        f.prepare_transport(keep_demod=cfg.get("keep_demod", False))

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
            "imtf_strength": imtf_strength,
        }
    except Exception:
        import traceback

        return {"seq": seq, "error": traceback.format_exc()}


class FilterSlots:
    """The publisher's half of the shared segment's per-job filter slots.

    Two of the filters a field job demodulates against are neither
    invariant nor per-block: the video output stack moves when the
    inverse-MTF strength or the dynamic EQ does, and the MTF response
    moves with the level.  Both move rarely, because every adoption that
    drives them is dead-banded, but when one does every worker rebuilds
    it and then holds its own copy for as long as the value stands.
    Publishing the parent's copy into a slot leaves one copy for the
    pool and saves each worker the rebuild.

    A slot cannot simply be overwritten: a job already running in a
    worker may be reading it.  Each family therefore gets `depth` slots
    - two is enough, one live and one free - and each slot a reference
    count, raised when a job naming it is submitted and dropped when
    that job finishes.  A slot with references outstanding is never
    chosen.  The count, and not the engine's generation counter, is what
    guards this: pause() abandons futures whose workers are still
    running, so a new generation is no promise that the readers of the
    old one have gone.

    When no slot is free the publication is simply skipped, and the
    workers rebuild privately as they did before slots existed.

    Thread-safety: publish() runs on the decode thread, acquire() on the
    dispatcher thread, and release() on whichever thread completes a
    future.  One lock covers all three.  The window in which a slot is
    being written is covered by a reference of its own, so nothing can
    select a half-written slot.
    """

    def __init__(self, descriptor, families, depth=2, writer=None):
        self.descriptor = descriptor
        self._writer = writer or shared_filter_bank.write_slot
        self._lock = threading.Lock()
        self._next_pubid = 0
        # family -> [[key, pubid, refcount], ...]
        self._slots = {
            family: [[None, 0, 0] for _ in range(depth)]
            for family in families
        }

    def live(self, family, key):
        """Whether `key` is already published in a slot of `family`."""
        with self._lock:
            return any(slot[1] and slot[0] == key
                       for slot in self._slots.get(family, ()))

    def publish(self, family, key, arrays):
        """Write `arrays` into a free slot of `family` under `key`.

        Returns whether the key is live in a slot afterwards, which
        includes it having been there already.
        """
        slots = self._slots.get(family)
        if slots is None:
            return False

        with self._lock:
            for slot in slots:
                if slot[1] and slot[0] == key:
                    return True
            # Of the slots no job is naming, take one that holds nothing
            # first and otherwise the oldest publication: what the other
            # slot holds is most likely the value still being dispatched,
            # and overwriting that would cost every job in flight its
            # read.
            free = [(slot[1], i) for i, slot in enumerate(slots)
                    if slot[2] == 0]
            if not free:
                return False
            index = min(free)[1]
            slot = slots[index]
            # Unpublished and referenced for the duration of the write:
            # no job can name it and no other publication can take it.
            slot[0] = None
            slot[1] = 0
            slot[2] = 1
            self._next_pubid += 1
            pubid = self._next_pubid

        self._writer(self.descriptor, family, index, arrays, pubid)

        with self._lock:
            slot[0] = key
            slot[1] = pubid
            slot[2] = 0
        return True

    def acquire(self, keys):
        """Slot tokens for a job about to be submitted.

        {family: (index, pubid)} for every family whose live slot holds
        the key this job carries, with a reference held on each until
        release().  None when nothing matched, which is what a job with
        no shared filters to read is given.
        """
        tokens = {}
        with self._lock:
            for family, key in keys.items():
                for index, slot in enumerate(self._slots.get(family, ())):
                    if slot[1] and slot[0] == key:
                        slot[2] += 1
                        tokens[family] = (index, slot[1])
                        break
        return tokens or None

    def release(self, tokens):
        """Drop the references a finished job held."""
        if not tokens:
            return
        with self._lock:
            for family, (index, _pubid) in tokens.items():
                slot = self._slots[family][index]
                if slot[2] > 0:
                    slot[2] -= 1


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

    def __init__(self, executor, read_fn, read_lock, cfg, workers,
                 filter_slots=None, slot_source=None):
        self.executor = executor
        self.read_fn = read_fn          # (sample, length) -> raw or None
        self.read_lock = read_lock      # shared with the block cache
        self.cfg = cfg
        self.filter_slots = filter_slots    # FilterSlots or None
        self.slot_source = slot_source      # (family, key) -> arrays or None
        # Twice the worker count: with similar job durations a shallow
        # window makes all workers start and finish in lockstep, idling
        # while the dispatcher serially reads the next wave's raw spans
        # (bursty output, lost throughput).  Enough queued jobs behind
        # the running ones keeps every finishing worker busy and lets
        # the read run ahead continuously.
        self.depth = workers * 2 + 4

        self._cond = threading.Condition()
        self._futures = {}              # seq -> Future (current generation)
        self._est_start = {}            # seq -> refined start estimate
        self._nxt_by_seq = {}           # seq -> (refined next-start, parity)
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
        self._imtf = 0.0
        self._veq = None
        self._chroma_dg = None
        self._rebase_seq = 0

        self._thread = threading.Thread(
            target=self._dispatch_loop, daemon=True, name="fieldjobs"
        )
        self._thread.start()

    def reset(self, start, next_is_first, lastfieldwritten, mtf_level,
              imtf_strength=0.0, veq=None, chroma_dg=None):
        """(Re)start speculation from known chain state."""
        with self._cond:
            self._gen += 1
            self._futures.clear()
            self._est_start.clear()
            self._nxt_by_seq.clear()
            self._next_dispatch = 0
            self._next_take = 0
            self._eof_seq = None
            self._cur_start = float(start)
            self._cur_parity = bool(next_is_first)
            self._lfw = lastfieldwritten
            self._mtf = mtf_level
            self._imtf = imtf_strength
            self._veq = tuple(veq) if veq else None
            self._chroma_dg = tuple(chroma_dg) if chroma_dg else None
            self._rebase_seq = 0
            self._active = True
            self._cond.notify_all()
        self.publish_slots()

    def pause(self):
        """Stop dispatching and discard everything in flight (results of
        the old generation are ignored)."""
        with self._cond:
            self._gen += 1
            self._active = False
            self._futures.clear()
            self._est_start.clear()
            self._nxt_by_seq.clear()

    def set_mtf(self, mtf_level):
        """Adopt a new MTF level for future dispatches without touching
        what is in flight - the decoder tolerates the old level on
        already-dispatched jobs (tolerant parameter mode)."""
        with self._cond:
            self._mtf = mtf_level
        self.publish_slots()

    def set_imtf(self, imtf_strength):
        """Adopt a new inverse-MTF strength for future dispatches (the
        workers rebuild FVideo per job; see _sync_worker_video)."""
        with self._cond:
            self._imtf = imtf_strength
        self.publish_slots()

    def set_veq(self, veq):
        """Adopt a new dynamic video EQ for future dispatches."""
        with self._cond:
            self._veq = tuple(veq) if veq else None
        self.publish_slots()

    def publish_slots(self):
        """Offer the current parameters to the shared segment's slots.

        Called from the decode thread whenever one of them moves, and on
        every reset, because the values a stretch of decoding starts on
        are the ones most of its jobs will carry.  Every step is
        best-effort: a source that declines (the parent's bank is
        between the parameter write and the rebuild that follows it) or
        a family with no free slot leaves the workers rebuilding
        privately, which is correct and merely slower.
        """
        if self.filter_slots is None or self.slot_source is None:
            return
        with self._cond:
            keys = {"video": (self._imtf, self._veq), "mtf": self._mtf}
        for family, key in keys.items():
            # Asked before the source is: building the value to publish
            # costs a transcendental per bin, and the common case is
            # that it is already there.
            if self.filter_slots.live(family, key):
                continue
            arrays = self.slot_source(family, key)
            if arrays is not None:
                self.filter_slots.publish(family, key, arrays)

    def set_chroma_dg(self, chroma_dg):
        """Adopt a new chroma DG (slope, phase) for future dispatches.
        Jobs in flight keep the old pair; the writer re-corrects those
        from the raw picture, so nothing needs discarding."""
        with self._cond:
            self._chroma_dg = tuple(chroma_dg) if chroma_dg else None

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
                imtf = self._imtf
                veq = self._veq
                chroma_dg = self._chroma_dg
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

                # Tokens name the slots holding this job's filters, and
                # hold a reference on each until it finishes; the parent
                # cannot rewrite a slot while one is outstanding (see
                # FilterSlots).
                slots = (
                    self.filter_slots.acquire(
                        {"video": (imtf, veq), "mtf": mtf}
                    )
                    if self.filter_slots is not None
                    else None
                )
                # The key pins consecutive pairs to one worker so the
                # blocks their windows share are demodulated once (see
                # AffinityPool and WorkerBlockLRU).
                fut = self.executor.submit(
                    _decode_field_worker, seq, start, raw, span_begin, mtf,
                    imtf, veq, fn, chroma_dg, slots, key=seq
                )
                self._futures[seq] = fut
                self._next_dispatch = seq + 1
                self._cur_start = start + self._parity_len[parity]
                self._cur_parity = not parity
                self._cond.notify_all()

            if slots:
                fut.add_done_callback(
                    lambda ft, t=slots: self.filter_slots.release(t)
                )
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
        # Anchored to the decoded buffer, so accurate to ~a sample even
        # when `start` itself was mispredicted.
        nxt = start + res["nextfieldoffset"] - (readloc - f.readloc)

        with self._cond:
            if self._gen != gen:
                return
            self._est_start[seq + 1] = nxt

            # Field-length observations must come from two *refined*
            # estimates - measuring against the predicted start would
            # feed each job's prediction error back into parity_len and
            # let errors compound.  EWMA smooths per-field wow jitter.
            self._nxt_by_seq[seq] = (nxt, f.isFirstField)
            prev = self._nxt_by_seq.get(seq - 1)
            if prev is not None:
                length = nxt - prev[0]
                old = self._parity_len[f.isFirstField]
                self._parity_len[f.isFirstField] = 0.75 * old + 0.25 * length
            self._nxt_by_seq.pop(seq - 32, None)

            # Re-anchor the blind chain: at steady flow the dispatcher
            # runs a full pipeline depth ahead of completions, so
            # est_start is never available at dispatch time and
            # _cur_start would otherwise extrapolate from itself
            # indefinitely, accumulating systematic wow drift until a
            # window boundary is crossed.  Extrapolating this fresh
            # estimate out to the dispatch point caps the blind span at
            # the in-flight depth.
            if seq >= self._rebase_seq:
                steps = self._next_dispatch - (seq + 1)
                if steps >= 0:
                    base = nxt
                    parity = not f.isFirstField
                    pair = self._parity_len[True] + self._parity_len[False]
                    base += (steps // 2) * pair
                    if steps % 2:
                        base += self._parity_len[parity]
                    self._cur_start = base
                    self._rebase_seq = seq

            self._cond.notify_all()


class AffinityPool:
    """N single-worker process pools with a stable job-to-worker map.

    A ProcessPoolExecutor hands each queued item to whichever worker is
    free, so consecutive field jobs land in different processes and the
    per-worker block cache never sees the overlap between them (see
    WorkerBlockLRU).  Splitting the pool into N executors of one worker
    each makes the assignment a function of the key instead: jobs 2k
    and 2k+1 go to the same process, which is the one holding the
    blocks they share.

    Work with no key - block-level demodulation, which the parent's own
    cache has already deduplicated - is spread round-robin.

    Pairing recovers half the overlap and no more: every group boundary
    still hands a fresh worker a window that overlaps its
    predecessor's, so a PAL run goes from 1.18 demodulations per
    distinct block to 1.09 rather than to 1.00.  Longer groups recover
    more (1.05 at four) at the cost of queueing more jobs behind one
    worker, which has not been measured; group_size is here so it can
    be, and nothing sets it.

    Thread-safety: submit() is called from the dispatcher thread and
    from the block-cache feeder threads.  The round-robin counter is
    taken under a lock, the in-flight set is a set of futures mutated
    under the same lock, and the executors are themselves thread-safe.
    """

    def __init__(self, max_workers, mp_context=None, initializer=None,
                 initargs=(), executor_factory=None, group_size=2):
        if executor_factory is None:
            def executor_factory():
                return ProcessPoolExecutor(
                    max_workers=1,
                    mp_context=mp_context,
                    initializer=initializer,
                    initargs=initargs,
                )

        self._executors = [executor_factory() for _ in range(max_workers)]
        self.group_size = group_size
        self._lock = threading.Lock()
        self._rr = 0
        self._inflight = set()

    def __len__(self):
        return len(self._executors)

    def index_for(self, key):
        """Which executor a key goes to.  None means round-robin."""
        n = len(self._executors)
        if key is None:
            with self._lock:
                i = self._rr % n
                self._rr += 1
            return i
        return (key // self.group_size) % n

    def submit(self, fn, *args, key=None):
        ex = self._executors[self.index_for(key)]
        fut = ex.submit(fn, *args)
        # Tracked so close() can drain the pool before touching the
        # worker processes; see close().
        with self._lock:
            self._inflight.add(fut)
        fut.add_done_callback(self._done)
        return fut

    def _done(self, fut):
        with self._lock:
            self._inflight.discard(fut)

    def processes(self):
        """The underlying worker processes, if the executors have any
        (an injected stand-in need not)."""
        out = []
        for ex in self._executors:
            out.extend(getattr(ex, "_processes", {}).values())
        return out

    def shutdown(self):
        """Cancel queued work and refuse new submissions, without
        waiting: what is already running in a worker keeps going and
        the executors join it on their own threads.  This is the
        teardown a pool restart wants - nothing is terminated, so
        nothing can be interrupted mid-result."""
        for ex in self._executors:
            ex.shutdown(wait=False, cancel_futures=True)

    def close(self, drain_timeout=10):
        self.shutdown()

        # Let those in-flight items drain before touching the worker
        # processes.  terminate()ing a worker mid-result-write leaves the
        # executor's manager thread blocked forever on a truncated pickle,
        # the .result() waiters never wake, and the interpreter then hangs
        # joining them at exit: the decode prints its summary and never
        # exits (hit reliably by decode-pal-cvbs on a starved 4-vCPU CI
        # runner, where prefetch is still busy at close time).  One item
        # is a few seconds at worst, so the drain is short whenever the
        # pool is healthy.
        with self._lock:
            pending = list(self._inflight)
        futures_wait(pending, timeout=drain_timeout)

        # Anything still running now is genuinely wedged (e.g. a worker
        # stuck in futex_wait after a group SIGINT, the case the Ctrl-C
        # fix targets).  Its result is no longer needed, and the
        # interpreter's atexit join would block on it: terminate for a
        # prompt exit.  An idle worker is not mid-write, so this cannot
        # truncate a result.
        if any(not f.done() for f in pending):
            for p in self.processes():
                try:
                    p.terminate()
                except Exception:
                    pass


class DemodBlockCache:
    """Thread-pooled, prefetching cache of demodulated input blocks.

    read_fn(block_idx) returns the block's raw samples, or None at EOF.
    demod_fn(raw, mtf_level, imtf_strength) demodulates one block.
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
        self._shared = None                 # published filter descriptor
        self.filter_slots = None            # FilterSlots over that segment
        self._lock = threading.Lock()       # protects _cache/_eof_block
        self._read_lock = threading.Lock()  # serializes the raw reader
        self._cache = {}                    # (block, mtf, imtf) -> Future
        self._eof_block = None

    def enable_processes(self, rf_opts, decoder_params, nprocs=None,
                         field_cfg=None, shared_filters=None):
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

        shared_filters, when given (RFDecode.shared_filter_spec()), is
        published into one shared-memory segment that every worker maps
        instead of keeping its own copy of those filters; the segment's
        rewritable slots are then driven by the returned FilterSlots.
        """
        rf_opts = dict(rf_opts)
        # Drop values demod does not need and that may not pickle.
        rf_opts["extra_options"] = {
            k: v
            for k, v in rf_opts.get("extra_options", {}).items()
            if k not in ("pipe_RF_TBC",)
        }

        # Idempotent: a second enable without a restart would otherwise
        # leave the first segment with nothing left to unlink it.
        self._release_shared()

        if shared_filters and shared_filters.get("arrays"):
            self._shared = shared_filter_bank.publish(
                shared_filters["arrays"],
                slots=shared_filters.get("slots"),
            )
            if self._shared["slots"]:
                self.filter_slots = FilterSlots(
                    self._shared, tuple(self._shared["slots"])
                )

        self._procs = AffinityPool(
            max_workers=nprocs or self._nthreads,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_demod_worker_init,
            initargs=(rf_opts, copy.deepcopy(decoder_params), field_cfg,
                      self._shared),
        )
        procs = self._procs

        def demod_in_process(rawinput, mtf_level, imtf_strength=None,
                             veq=None):
            # No key: these are already deduplicated by this cache, so
            # there is nothing for a worker to reuse and spreading them
            # round-robin keeps every worker fed.
            return procs.submit(_demod_worker_block, rawinput, mtf_level,
                                imtf_strength, veq).result()

        self.demod_fn = demod_in_process

    def restart_processes(self, rf_opts, decoder_params, nprocs=None,
                          field_cfg=None, shared_filters=None):
        """Tear down and respawn the worker processes with a fresh
        parameter snapshot (needed after a post-warm-up AGC adjustment:
        workers hold DecoderParams frozen from their spawn)."""
        if self._procs is not None:
            # Not close(): a restart terminates nothing, so there is
            # nothing to drain first (see AffinityPool.shutdown).
            self._procs.shutdown()
            self._procs = None
        # The filters go with the parameters that built them.  Unlinking
        # only removes the name: a worker still finishing a job keeps the
        # mapping it attached to until it exits.
        self._release_shared()
        self.enable_processes(rf_opts, decoder_params, nprocs=nprocs,
                              field_cfg=field_cfg,
                              shared_filters=shared_filters)

    @property
    def process_executor(self):
        return self._procs

    @property
    def read_lock(self):
        return self._read_lock

    def get_span(self, brange, mtf_level, imtf_strength=None, veq=None):
        """Demodulated blocks for brange (list of (raw, demod)), or None
        if EOF falls inside the span.  Schedules a sequential prefetch
        beyond the span at the same parameters."""
        with self._lock:
            veq = tuple(veq) if veq else None
            futures = [self._ensure(b, mtf_level, imtf_strength, veq)
                       for b in brange]

            for b in range(brange.stop, brange.stop + self.ahead):
                if self._eof_block is not None and b >= self._eof_block:
                    break
                self._ensure(b, mtf_level, imtf_strength, veq)

            self._evict(brange.start, mtf_level, imtf_strength, veq)

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
            # Drains what is running before terminating whatever is
            # wedged; see AffinityPool.close.
            self._procs.close()
            self._procs = None
        self._release_shared()

    def _release_shared(self):
        """Drop the published filter segment, if there is one."""
        self.filter_slots = None
        if self._shared is not None:
            shared_filter_bank.unlink(self._shared)
            self._shared = None

    # internal - callers hold self._lock

    def _ensure(self, b, mtf_level, imtf_strength=None, veq=None):
        key = (b, mtf_level, imtf_strength, veq)
        fut = self._cache.get(key)

        if fut is None:
            if self._eof_block is not None and b >= self._eof_block:
                fut = Future()
                fut.set_result(None)
            else:
                fut = self._pool.submit(self._compute, b, mtf_level,
                                        imtf_strength, veq)
            self._cache[key] = fut

        return fut

    def _evict(self, current_start, mtf_level, imtf_strength=None, veq=None):
        cutoff = current_start - self.keep_behind
        stale = [
            key for key in self._cache
            if (key[0] < cutoff or key[1] != mtf_level
                or key[2] != imtf_strength or key[3] != veq)
        ]
        for key in stale:
            self._cache.pop(key).cancel()

    def _compute(self, b, mtf_level, imtf_strength=None, veq=None):
        with self._read_lock:
            raw = self.read_fn(b)

        if raw is None:
            with self._lock:
                if self._eof_block is None or b < self._eof_block:
                    self._eof_block = b
            return None

        return raw, self.demod_fn(raw, mtf_level, imtf_strength, veq)


class OrderedOutputLane:
    """Run the per-field output work on one background thread, in order.

    Everything that happens to a field after it is committed - the EFM
    demodulation, the metadata database row, the CVBS frame assembly
    and the file writes - is a function of that field and of state only
    the output stage touches, so it can trail the commit loop by a few
    fields without changing a byte: the callables run one at a time, in
    submission order, exactly as the serial decode would have run them
    inline.  The commit thread only blocks when the lane's bounded
    look-ahead is full.

    A failure in the lane (a full disk, say) is re-raised on the
    submitting thread at its next submit() or at close(); the work
    queued behind the failed callable is dropped.
    """

    def __init__(self, depth=16, name="ld-output"):
        import queue

        self._queue = queue.Queue(maxsize=depth)
        self._error = None
        self._closed = False
        self._thread = threading.Thread(
            target=self._run, name=name, daemon=True)
        self._thread.start()

    def submit(self, fn, *args):
        """Queue fn(*args) behind everything submitted before it."""
        self._raise_error()
        if self._closed:
            raise RuntimeError("output lane is closed")
        self._queue.put((fn, args))

    def _run(self):
        while True:
            item = self._queue.get()
            if item is None:
                break
            if self._error is not None:
                continue  # drop what was queued behind the failure
            fn, args = item
            try:
                fn(*args)
            except BaseException as exc:  # surfaced on the submitting thread
                self._error = exc

    def _raise_error(self):
        if self._error is not None:
            exc, self._error = self._error, None
            raise exc

    @property
    def failed(self):
        return self._error is not None

    def close(self):
        """Finish the queued work and stop the thread; re-raises a
        failure that has not been surfaced yet."""
        if not self._closed:
            self._closed = True
            self._queue.put(None)
        self._thread.join()
        self._raise_error()
