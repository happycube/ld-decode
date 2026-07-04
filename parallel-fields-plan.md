# Parallel field decoding for ld-decode

Repo: `/home/cpage/ld-decode/chad-cutdown`, branch `chad-2026.06.13-cutdown`.
Goal: decode several fields concurrently through an orchestrator that spawns a
high-level per-field routine, reorders results as they complete, and commits
them in sequence — with clean redo semantics for fields that need MTF/AGC
recalibration. Parallelism does not start until the decode is "locked in"
(the first fields are decoded serially and are expected to be redone).

## 0. The core premise: fields decode independently

A field has a well-defined beginning (VSYNC). Given an *estimated* start
location, a window that begins a bit before it, and the field's own sync
structure, a field decodes with **no dependency on its predecessor**. This is
already true in the code: `getLine0` (`field.py:629`) treats the previous
field as just one of three voters — `line0loc_local` (this field's own vblank
analysis), `line0loc_next` (back-projection from the *next* vsync in the same
buffer), and `line0loc_prev` — and returns a confident local answer on its
own (`field.py:691-693`). Every decode already runs its first field, and
every post-skip re-acquisition, with `prevfield=None`.

The previous-field inputs are therefore **fallbacks for damaged fields, not
requirements**:

| Prev-field input | Site | Role | Independent-decode handling |
|---|---|---|---|
| end-position → line0 vote, search limit | `field.py:636,665-672` | rescue when local vsync is damaged | commit-time **repair redo** with a real anchor (§3) |
| `fieldPhaseID + 1` fallback | `field.py:1573-1580,1608,1617` | used only when line-6/burst measurement is ambiguous | worker flags "fallback used"; committer rewrites from the committed chain |
| PAL `phase_adjust` seeds (4 floats), NTSC `phase_adjust_median` | `field.py:1631-1638,1753-1756` | numerical seed for burst zero-crossing search | fixed seed (0 — what field 1 uses today); validated on test discs |
| `fields_written > 0` retry gate | `field.py:715,793` | first-field special case | constant True after warm-up |

So the hot path is: **estimate where field N starts → demod a window starting
slightly before → find VSYNC → decode**. Anchored decode (a `FieldAnchor`
carrying the predecessor's end position, parity, phaseID, seeds) exists only
as the repair path, and for warm-up/serial compatibility.

## 1. Measured baseline (what we're parallelizing)

Warm-cache profile, NTSC ve-snw-cut.ldf, 19 fields decoded (36-core machine,
Python 3.13 GIL build), ~0.96 s/field total:

| Stage | per field | share | inter-field dependency |
|---|---|---|---|
| `demod_read` → `rf.demodblock` (scipy FFT, ~28 × 32k blocks) | ~700 ms | ~73% | none (raw bytes + mtf_level + params) |
| `Field.process` (pulses, linelocs, burst refine, phase ID) | ~35 ms | ~4% | none on the hot path (§0) |
| `downscale` (video + audio + efm slice, njit) | ~150–200 ms | ~18% | none (audio needs the absolute field number) |
| metrics + dropout detect | ~15 ms | ~2% | 3D metric compares against field N−3 (line slices) |
| `writeout` (EFM PLL + sqlite + file writes) | ~85 ms | ~9% | strictly serial |

With fields fully independent, the serial critical path is only the commit
residue (~15 ms/field once the EFM PLL is off it) → ceiling well above the
worker-side arithmetic; in practice throughput scales with worker count until
the reader/committer saturates.

## 2. Goals and non-goals

Goals:
- **G1** Per-field worker jobs; orchestrator dispatches ahead, reorder buffer
  commits strictly in field order.
- **G2** Redo semantics preserved: fields decoded under stale MTF/AGC/deemp
  parameters are re-decoded, as `readfield()`'s one-redo loop does today; add
  the repair redo for damaged fields.
- **G3** Deterministic: identical output for any worker count, run-to-run
  (`md5(-t 8) == md5(-t 1)` is a test assertion).
- **G4** Serial mode (`-t 1`) remains the default until the parallel path has
  soaked; the pre-refactor default path stays bit-identical through the
  refactor commits (md5 baselines), with the intentional behavior changes
  isolated in one commit (§6 step 3).
- **G5** ONE decode code path: serial mode = same worker routine + same
  committer under a trivial scheduler. No `if parallel:` forks in decode logic.

Non-goals (v1):
- `--RF-TBC`, `--AC3`, `pipe_RF_TBC` (need raw field data at the writer;
  these force serial mode with a warning).
- Parallelizing `seek()` / VBI frame-number search (runs before the main loop).
- Free-threaded Python; intra-field block parallelism (noted in §9).

## 3. Architecture

```
                 ┌───────────────────────────────────────────────────┐
                 │ Orchestrator (main)                               │
                 │                                                   │
 raw file ──►  Reader ──► block cache ──► Dispatcher ──► job queue ──┼──► Worker 1..N
                 │            ▲                ▲ (seq, window,       │      │ per field:
                 │            │                │  mtf, params-epoch, │      │  demod window
                 │        retain until         │  abs field number)  │      │  find vsync, process
                 │        committed            │                     │      │  downscale, metrics
                 │                             │ redo / repair /     │      │  → FieldResult
                 │        Calibrator ◄─── Reorder buffer ◄───────────┼──────┘
                 │        (MTF/AGC/deemp)      │  commit in seq order│
                 │            │                ▼                     │
                 │            └──────────► Committer ── validate,    │
                 │                             │        buildmetadata│
                 │                             ▼        writeout     │
                 │                       EFM PLL lane (own thread)   │
                 └───────────────────────────────────────────────────┘
```

No worker-to-worker communication. Every job is a pure function of its inputs.

### The per-field worker routine (the "highish level routine")

`decode_one(job) -> FieldResult`:

1. **Demod** the job's raw window (`demod_read` body): ~28 blocks × FFT,
   from `(window_blocks, mtf_level, params_epoch)`.
2. **`Field(...).process()`** unanchored (or with the job's `FieldAnchor` on a
   repair redo): find vsync/line0 from the field's own structure, linelocs,
   parity, phaseID (+ "phaseID was fallback" flag), burstmedian, actual line0
   absolute position, `nextfieldoffset`.
3. **Downscale** video, audio (using the job's absolute field number), efm
   slice; per-field metrics; `dropout_detect`; `detectLevels` measurements;
   extract the VITS line slices the N−3 3D metric needs.
4. Return `FieldResult` (or an invalid-marker result with the suggested skip).

### Window estimation ("decode a bit before that")

- The dispatcher predicts field N's line0 as
  `truth(N−W).line0 + Σ mean_field_len(parity)` over the gap, where **W is a
  fixed pipeline depth** (default 32, independent of `-t`; see §5) and
  `truth(N−W)` is that committed field's actual position. Per-parity mean
  field lengths are locked during warm-up and slowly updated from committed
  fields (deterministically, at fixed intervals).
- The window is placed so the estimated line0 sits ~30 lines in (matching
  what the anchored path guarantees today), block-quantized exactly like
  `demod_read` (`readloc_block = readloc // blocksize`), length `readlen`
  (340/300 lines ≈ 25–35 lines of slack). Wow-accumulated prediction error
  over 32 fields is a couple of lines — far inside the slack.
- The field's *own* vsync search inside that window establishes the true
  position; the estimate never enters the output, only the window placement.

### Data structures

```python
@dataclass
class FieldAnchor:            # repair-path + warm-up input (lossless vs prevfield)
    end_loc: float            # absolute position of prev linelocs[linecount]
    valid: bool
    sync_confidence: float
    skip_score: float
    is_first_field: bool
    field_phase_id: int
    phase_adjust: dict | None      # PAL lines 7/11/15/19
    phase_adjust_median: float     # NTSC

@dataclass
class FieldJob:
    seq: int                  # monotonic field index (== eventual write order)
    window_blocks: range      # block-quantized read window
    est_line0: int            # predicted absolute line0 (window placement only)
    mtf_level: float
    params_epoch: int         # AGC/deemp generation
    abs_field_number: int     # audio clock
    anchor: FieldAnchor|None  # None on the hot path; set on repair/warm-up
    is_recovery: bool         # unanchored wide window (readlen_first)

@dataclass
class FieldResult:
    seq, valid, line0_abs, next_start, readloc, sync_confidence
    parity, field_phase_id, phase_id_was_fallback
    picture, audio, efm             # downscaled outputs
    fi_fields                       # syncConf, burstmedian, dropouts, linecode…
    metrics, vits_slices            # per-field metrics + N−3 3D-metric inputs
    level_measurements              # detectLevels medians (AGC inputs)
    anchor_out: FieldAnchor         # for repair jobs of seq+1 and warm-up
    used: (mtf_level, params_epoch, est_line0)
    demod_video: optional           # PAL CVBS mode only (committer resamples)
```

### Committer (strict order)

Pops `seq == next_commit` from the reorder buffer, then:

1. **Chain validation** (replaces decode-time prev-field coupling):
   - position continuity: `|result.line0_abs − expected_from(committed N−1)|`
     within tolerance (~2 lines);
   - parity alternates vs committed N−1;
   - `sync_confidence` above threshold;
   - phaseID: if `phase_id_was_fallback`, rewrite as committed chain + 1
     (exactly what the decode-time fallback computes, now with the *real*
     predecessor); if measured, check sequence as `buildmetadata` does.
   Any hard failure → **repair redo**: re-dispatch seq with
   `anchor = anchor_out(committed N−1)` — full today's-robustness decode.
   Still failing → serial-equivalent skip/filler handling.
2. **Calibration check** (was `readfield:877-898`):
   - MTF: fold `blackToWhiteRFRatio` into `bw_ratios`; if
     `|estimate − result.used.mtf_level| ≥ 0.05` → redo this field with the
     new value (one redo, as today).
   - AGC: apply `_adjust_agc` decision from `level_measurements`; on a level
     rewrite → `params_epoch++`, redo this field, flush all in-flight.
   - deemp: locked before parallelism starts (§4); asserted, not handled.
3. `buildmetadata` equivalent: stuck-parity fixup, `needFiller`/filler
   writeout, frame-number decode, 3D metric from the stored N−3 `vits_slices`.
4. Hand EFM to the **EFM PLL lane** (dedicated thread, ordered queue — keeps
   the ~40+ ms PLL off the commit critical path, preserves stream order).
5. Write sqlite/CVBS/tbc/pcm as today; release the field's raw blocks and
   bulky arrays; retain a 3-deep `vits_slices`/anchor tail.

### Redo / flush rules

| Trigger | Detected | Action |
|---|---|---|
| chain validation failure (position/parity/low confidence) | commit-time | **repair redo** with real anchor from committed N−1; successors' windows still valid unless position moved > slack (then re-window from truth) |
| MTF drift ≥ 0.05 | commit-time | redo that field only (estimate is a 30-field rolling mean — moves ≤ 1/30 per field, no cascades) |
| AGC level rewrite | commit-time, first fields | epoch++: redo field, flush + redispatch all in-flight |
| deemp recalibration | warm-up only | n/a after lock-in (asserted) |
| invalid field from worker | worker | repair redo first; if the repair is also invalid → **recovery job** (`readlen_first` ≈ 2 fields, unanchored) at the skip offset, successors flushed — mirrors serial `prevfield=None; continue` |
| parity stuck / `needFiller` | commit-time | as serial (filler writeout, syncConf=10); flush successors only if `abs_field_number` predictions moved |
| EOF | reader | drain; trailing unpaired handling as today |

All decisions are functions of committed results and fixed rules — never of
completion timing → deterministic.

## 4. Warm-up ("don't start parallelism until locked in")

Run the serial scheduler (same `decode_one` + committer, anchored jobs — the
`-t 1` code path) until **all** of:

- `deemp_calibrated` (needs ≥3 valid fields — it recomputes video filters, so
  it must never fire mid-pipeline);
- AGC passed its last first-field check with no rewrite (post-warm tolerance 2 IRE);
- `len(bw_ratios) ≥ 10` and the MTF estimate moved < 0.05 over the last 5 fields;
- no redo in the last 5 committed fields;
- ≥ 1 full frame written (past `fields_written == 0` special cases);
- per-parity mean field lengths measured (for window prediction).

Typically ~10–20 fields (< 0.5 s of video). Then snapshot params, start the
pool, and switch schedulers. Per the premise: the first decoded field *will*
be redone (AGC first-field tolerance is 0.5 IRE) — that all happens here.

## 5. Determinism and bit-exactness

- **Windows are deterministic**: predictions derive from `truth(N−W)` with W
  a fixed constant (not a function of `-t`), and mean-length updates happen
  at fixed committed-field intervals. Same input → same windows → same block
  sets, every run, any worker count.
- **Phase seeds are fixed** (0, the field-1 value) instead of "whatever was
  committed at dispatch time" — dispatch-time state is timing-dependent and
  would break run-to-run equality. Seeds only pre-shift a zero-crossing
  search; validate convergence on the CI discs + he010/pal discs in step 3.
- **MTF dead-band (intentional change, both modes):** today `checkMTF`
  rewrites `mtf_level` every field even under the 0.05 redo threshold
  (`decoder.py:450`), so each field sees a slightly different value — not
  reproducible in any pipeline. `Calibrator` holds `mtf_level` constant until
  drift ≥ 0.05, then adopts + redoes (the tolerance the redo logic already
  accepts). Hysteresis: don't re-adopt within 0.02 of the last adopted value.
- **Serial mode uses the same independent-decode jobs** (anchored only in
  warm-up and repair, same rules) — so `-t 1` and `-t N` produce identical
  bytes, asserted by md5 in ctest.
- Output will differ slightly from *today's* decoder (no prev vote in
  `getLine0`'s median on healthy fields, sync_confidence caps at 90, fixed
  phase seeds, MTF dead-band). On healthy fields the prev vote almost never
  decides the median, so differences are sub-sample; step 3 re-baselines and
  the quality tables must be unchanged within noise.
- Payoff: any race/scheduling bug breaks md5 equality loudly in tests instead
  of wobbling output silently.

## 6. Execution substrate

**Stage A — synchronous executor (validation).** Orchestrator with an inline
executor. Proves scheduling/validation/redo logic with zero concurrency risk;
output must equal the step-3 serial baseline byte-for-byte.

**Stage B — thread pool (first real speedup, low risk).** The heavy code
already cooperates: scipy FFT releases the GIL; every hot njit in `dsp.py` is
`nogil=True`; downscale/metrics are njit. Shared memory means no pickling,
committer receives full `Field` objects, and PAL CVBS (`downscale_cvbs` needs
demod data + the serial `_pal_shift` feedback) works unchanged at the
committer. Expected ~3–5× (GIL-bound Python glue is ~20–25% of worker time).
Requirements:
- Params mutate only at flush barriers (no jobs in flight) — the epoch
  mechanism provides this.
- Shared-scratch audit: `self.curfield` (`decoder.py:773`) moves out of the
  worker path; verify `demodblock`/`Field` never write `rf.*`.
- De-risk first: micro-benchmark `demodblock` at 2/4/8 threads; if < 2.5× at
  4 threads, go straight to Stage C.

**Stage C — process pool (the 10×+ target).** `multiprocessing` (spawn) +
`shared_memory`:
- Raw block ring in SHM (reader writes, workers attach; ~128 KB/block, a
  512-block ring ≈ 64 MB, refcounted by in-flight jobs). Workers never touch
  the input file — stdin/ffmpeg-pipe inputs keep working.
- Workers build their own `RFDecode` from `rf_opts` at startup (~1–2 s once;
  numba `cache=True` gives warm JIT from disk).
- Results return as slim picklable `FieldResult`s (~2–3 MB/field is fine
  through a queue at 20+ fields/s); PAL-CVBS demod arrays return via SHM
  slots, and `downscale_cvbs` is refactored to a free function over
  `(demod, linelocs, …, shift)` so the committer can run it from shipped arrays.
- Param updates ride the job payload on epoch change (level scalars are cheap;
  `recompute_fvideo` never fires post-warm-up).

The orchestrator is substrate-agnostic (executor interface): A→B→C are
scheduler swaps, not rewrites.

## 7. File changes

| File | Change |
|---|---|
| `lddecode/field.py` | `FieldAnchor`; `Field` takes `anchor=None` instead of a `prevfield` object (getLine0 vote/limit, phaseID fallback, phase seeds all read the anchor); `make_anchor()`; report `phase_id_was_fallback`; fixed default phase seeds; audio downscale takes an explicit absolute field number; delete vestigial `needrerun` (`field.py:74`, never set) |
| `lddecode/parallel.py` (new) | `FieldJob`/`FieldResult`, `Orchestrator` (reader, block cache, dispatcher with fixed-depth window prediction, reorder buffer, committer driver), `Calibrator` (MTF dead-band + AGC + deemp, extracted from `checkMTF`/`checkAutoDeemp`/`_adjust_agc`), chain validator, executors (sync/thread/process) (~500 lines) |
| `lddecode/decoder.py` | `readfield` decomposed into `decode_one(job)` and `commit(result)`; serial loop rebuilt on those; EFM PLL behind an ordered lane; `curfield` debug hook relocated |
| `lddecode/main.py` | `-t/--threads N` (default 1; `0` = auto ≈ min(cores−4, 12)); force serial + warn for `--RF-TBC`/`--AC3`/`pipe_RF_TBC` |
| `lddecode/cvbs.py` | (Stage C) `downscale_cvbs` as a free function |
| `cmake_modules/LdDecodeTests.cmake` | parallel decode + md5-equality tests |
| `tests/test_parallel_orchestrator.py` (new) | scripted-worker unit tests of every redo/flush rule |

## 8. Commit sequence (each step: pytest + full ctest green)

1. **Anchor refactor.** `FieldAnchor`; `Field` consumes it; serial path builds
   it from the real prevfield. Bit-identical to today by construction —
   assert with existing md5 baselines.
2. **Loop decomposition.** `decode_one` / `Calibrator` / `commit` extracted;
   `readfield` reassembled; EFM PLL behind an ordered queue (single-threaded
   here); `needrerun` removed. Bit-identical.
3. **Semantic changes, isolated:** independent decode as the hot path
   (anchored only for warm-up/repair), fixed phase seeds, MTF dead-band,
   explicit audio field number. Re-baseline md5s; run
   `differential_phase.py` quality tables on both CI discs + he010 + a PAL
   disc — must match previous tables within noise; eyeball a
   damaged-field-heavy decode to confirm repair-redo parity with today.
4. **Orchestrator + sync executor** (`-t 1` runs through it). Unit tests
   drive a scripted worker through every row of §3's redo table (chain
   failure→repair, MTF drift, AGC epoch, invalid→recovery, needFiller, EOF).
   Output md5 == step 3.
5. **Thread executor** (`-t N`). Assertions: `md5(-t 4) == md5(-t 1)`;
   repeated `-t 4` runs identical; ctest `decode-{ntsc,pal}-parallel` feeding
   the existing verify/analyze fixtures. Record measured FPS here.
6. **Soak**: a few thousand fields (he010) at `-t 8` vs `-t 1`: md5 + metrics
   table + `.efm` md5 equality.
7. **(If Stage B measures short) process executor**: SHM ring, slim results,
   worker-side RFDecode, CVBS-PAL committer resampling; same assertions.
8. Docs: README section; serial-forced modes noted.

## 9. Risks / watch items

- **Hidden shared state on `rf`** (thread stage): one scratch array = corrupted
  fields. The md5-equality tests are maximally sensitive to this — any race
  breaks them loudly.
- **Vsync-window ambiguity without the prev limit**: `getLine0`'s
  `limit=100` guard (`field.py:636`) exists to reject a *next* vsync when the
  window is long. Independent windows are placed so line0 sits ~30 lines in;
  pass an equivalent limit derived from `est_line0` so the local search stays
  disciplined without needing the prev field.
- **Fixed phase seeds**: if some disc genuinely needs chained seeds to
  converge (large phase adjust), fall back per-disc via repair redo (which
  carries real seeds) — validation in step 3 decides if more is needed.
- **GIL ceiling** (thread stage): micro-benchmark gates it (§6).
- **Memory**: W in-flight × ~25 MB worker-side demod + reorder-buffer
  results. W fixed at 32 for determinism; workers cap concurrent jobs, and
  results free aggressively at commit.
- **Redo storms** on discs oscillating near the 0.05 MTF boundary: hysteresis
  (§5) — deterministic, both modes.
- **Skips/CLV pulldown discs**: heavier repair/filler traffic degrades
  throughput toward serial; correctness covered by the rules table.
- **`--start`/`--seek`**: run before the main loop; warm-up begins at the
  sought offset (verify).
- **EFM output equality**: PLL lane consumes the identical ordered stream —
  `.efm` md5 asserted in every test above.

## 10. Expected outcome

| Config | est. throughput (NTSC CI disc) |
|---|---|
| today (serial) | ~1.0–1.5 fields/s |
| Stage B, `-t 6` | ~4–6 fields/s |
| Stage C, 12 workers | ~12–25 fields/s (critical path: ~15 ms commit residue; no inter-worker chain) |

Ceiling beyond that: parallelize inside demod (28 independent blocks/field)
or shard the committer — both compatible with this architecture, both out of
scope.

---

## 11. Implementation log (as built, 2026-07-04)

Commits 87be437b → baf9a574 on `chad-2026.07.04-prev8-parallel`.

**Steps 1–3 landed as planned:**
- 87be437b `FieldAnchor` replaces the prevfield object (bit-identical).
- fbad1d18 readfield decomposed into decode stages + calibrate + commit;
  audio downscale moved to commit time; EFM PLL behind one ordered entry
  point (bit-identical).
- de09b43b independent decode after a one-way warm-up gate, commit-time
  chain validation + anchored repair, phaseID chain rewrite at commit,
  MTF dead-band.  Quality tables within noise on both CI discs; `.efm`
  bit-identical; ~20-field warm-up then 100% independent decodes with
  zero repairs on the CI discs.

**Steps 4–5 deviated from §3/§6 — a simpler construction won:**
instead of window *prediction*, exploit the fact that demodulation
already runs on a block-quantized grid.  `demod_read` consumes
fixed-position 32k blocks whose demodulation is a pure function of
(block index, mtf_level) — so a **DemodBlockCache** (eed69760,
lddecode/parallel.py) demodulates blocks on a thread pool with a
sequential prefetch (block N+1 always follows block N; no prediction,
no rebase machinery), and the field-level offset chain stays exact.
Bit-equality with serial holds **by construction** and is asserted in
ctest (compare-{ntsc,pal}-parallel-*).  readfield then became a small
in-order pipeline driver (baf9a574): stage 1 (sync/lineloc chain) on
the main thread, stage 2 (downscale/metrics/dropouts) fanned out per
field, commits strictly in order with the single-redo rule flushing
everything decoded ahead under old parameters.  `-t 1` is the same
driver at depth 1 — one code path.

**Measured (36-core, NTSC CI disc, steady state post-warm-up):**

| Config | fields/s |
|---|---|
| `-t 1` | 2.36 |
| `-t 8` | 6.39 (2.7×) |

`-t 12` was slightly worse than `-t 8` (GIL contention), matching §6's
prediction that the thread stage saturates around 3–5×.  The remaining
serial residue is stage 1 (~50 ms) + commit (~60 ms: sqlite/EFM
PLL/writes) plus GIL-slowed demod under load.

**Still open (the §6 Stage C path, unchanged in design):** a process
pool fanning out full per-field jobs — the step-3 independence
semantics were built exactly so worker processes need only
(start offset, mtf, params epoch).  EFM lane and commit sharding are
smaller follow-ups.
