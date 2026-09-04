# Batch-parallel decode — implementation plan

Goal: remove the throughput ceilings that `-t N` cannot pass by dividing a capture into large
batches and running the *existing serial decoder* over each batch in its own process. The
components ld-decode has (`RFDecode`, `Field`, the `LDdecode` calibrate/commit loop, `CVBSWriter`,
the EFM demodulators, the loaders) are kept; what changes is where they run and what they are
allowed to depend on.

The guiding decision: **inside a batch there is no parallelism**. A batch runs the `-t 1` reference
path — inline writeout, no lanes, no pools, no speculation. Parallelism comes from the number of
batches in flight, and every one of today's layered mechanisms (§1) is either retired or confined
to the orchestrator. Many processes each doing sequential work beat one process distributing work
through five levels of queues, because the sequential dependencies that make the current design
hard (burst lock, EFM PLL, servo adoption order) stop being cross-process dependencies when each
batch owns its own copy of them.

Sources:
- Throughput measurements quoted below: `docs-planning/decode-throughput-hotspot-analysis.md`
  (local, untracked). Every figure this plan depends on is restated inline, so the plan stands
  without it.
- Prior parallel work, as built: [`plans/parallel-fields-plan.md`](parallel-fields-plan.md) §11.
- Threading and determinism rules this plan changes: `AGENTS.md` §4.4, §5.3.3.
- CVBS format constraints on the writer split: `cvbs-file-format-specification/` (submodule).

---

## 1. What's actually parallel today, and what isn't

Past `pipeline_warm` (`decoder.py:3082`), a `-t N` decode is running **seven** concurrent
mechanisms, layered:

| Mechanism | Where | Threads/processes | Scales with `-t N`? |
|---|---|---|---|
| FLAC reader (`_reader_loop`, `fileio.py:447`) | parent | 1 thread | no |
| `DemodBlockCache` prefetch (`parallel.py:540`) | parent | `N` threads, idle once field jobs start (`ahead = 0`, `decoder.py:3115`) | yes, but unused post-warm-up |
| `FieldJobEngine` dispatcher (`parallel.py:259`) + worker pool | parent thread + `N` processes | `N` | yes, up to physical cores |
| stage-2 pool (`decoder.py:828`) | parent | up to 4 threads, only on the non-job path | no |
| `OrderedOutputLane` (`parallel.py:737`) | parent | exactly 1 thread (`decoder.py:842`) | no |
| output pool for stale TBC DG re-correction (`decoder.py:844`) | parent | 2 threads | no |
| PAL CVBS field-B resample executor (`cvbs.py:402-406`) | parent | 1 thread, hard-coded | no |

The workers decode fields with `anchor=None` (`parallel.py:191`) - after warm-up a field's decode
already has **no dependency on its predecessor's decode**; the chain survives only as (a) the start
position the dispatcher predicts (`_window`, `parity_len`, `_refine`, `parallel.py:405-538`),
(b) the
block-quantised identity check and chain validation at acceptance (`_accept_job`,
`decoder.py:3243`), and (c) the in-order calibrate/commit loop on the main thread.

Two ceilings sit in the parent process, and both are architecture rather than tuning:

- **The finishing stage.** Everything after a field is accepted - EFM demod, PAL CVBS resample +
  DG/phase correction, the `.tbc.db` row, the file writes - runs on the fixed threads in the table.
  Measured on PAL CVBS (`-t 6`): the output lane and the resample thread sum to ~104% of wall-clock
  while six worker processes average 22% duty each (throughput analysis §3.2).
- **The commit loop itself.** Even in `--tbc` mode, where no resample exists, the main thread cycles
  at ~0.12 s/frame post-warm-up (IPC unpickling ~15 ms, FLAC ring-buffer copies ~12 ms, EFM
  ~15 ms per field; measured on the same box during the output-lane work, not in the hotspot doc).
  That is an ~8 fps ceiling independent of worker count; the hotspot doc's PAL `--tbc` figure at
  `-t 6` (5.31 fps) is already two-thirds of the way to it, and `-t 14` measured no better than
  `-t 10`. Adding workers past this point cannot help any mode.

The dispatcher's 16-field look-ahead (`depth = workers*2+4`, `parallel.py:289`) is **not** a
bottleneck: NTSC workers run ~82% busy once warm (throughput analysis §3.3). Deeper look-ahead is
not what
batching is for.

## 2. Why the file isn't already chopped into N independent chunks

The obstacles, corrected against the code as it stands:

1. **Field boundaries aren't at known byte offsets** - but a batch does not need them. The cold
   start path already exists and is exercised on every decode: `decodefield(..., wide=True)` reads
   `readlen_first` (a whole frame, `decoder.py:619/624`) and finds the first vsync inside it
   (`_advance_chain` with `prevfield=None`, `decoder.py:2897`). A batch can begin at an arbitrary
   sample offset exactly the way `--start` does today. There is no need for a separate whole-file
   boundary index; the only question a seam has to answer is *which* field is the first one the
   batch owns, and that is settled by agreement between neighbouring chains (§3.4), not by
   pre-computed positions.
2. **Calibration is not "converge once".** Only auto-deemp and AGC are one-shot warm-up loops
   (`_calibration_warmup`, `decoder.py:2663`). The MTF servo (`checkMTF`, `decoder.py:1877`) tracks
   the 2T response as radius changes; the multiburst video-EQ servo and the inverse-MTF ceiling
   (`checkVideoEQ`, `_apply_imtf_ceiling`, `decoder.py:1717`) and the chroma DG servo
   (`checkChromaDG`, `decoder.py:1498`, 100-field adoption hold-off, 240-field sample age) all keep
   adopting across the whole disc, under dead-bands and rate limits. That is precisely why
   `_flush_pipeline`, tolerant vs `--exact-speculation` acceptance, and `d4703045` ("Fix DG
   non-determinism") exist: the servos are causal, so a field's parameters depend on every field
   before it. Any batch that starts mid-disc cannot reproduce that state without having decoded
   everything before it. §3.3 takes this head-on rather than promising to hand it off.
3. **Cross-field state lives in the finishing stage, not the decode.** After warm-up the decode is
   independent (§1). What still chains field-to-field is: the PAL CVBS burst-lock shift, updated
   from every frame's resampled field A and applied to the next (`_emit_frame`, `cvbs.py:355-390`);
   the EFM demodulator's PLL/timing state, "the one per-field computation that can never fan out"
   (`_process_efm`, `decoder.py:2119`); the AC3 demodulator (`AC3demodulate`, `decoder.py:2099`);
   and the analogue audio clock, which numbers each field from the previous written one
   (`compute_audio_field_number`, `field.py:1297`). Every one of these is a serial stream. Any
   design that keeps one copy of each in the parent and fans the surrounding work out inherits a
   serial dependency per stream; a design that gives every batch its own copy does not.
4. **The parent reads everything.** All raw reads go through one reader and one lock, and the raw
   spans are pickled to workers (`FieldJobEngine._dispatch_loop`, `parallel.py:432`). `LoadLDF`
   already supports seeking (`fileio.py:565`, container seek on far forward jumps), so independent
   readers per batch are possible for files. Pipe input (`LoadFFmpeg` on stdin, `fileio.py:269`)
   cannot seek and cannot be batched - it needs a fallback, or loses `-t`.

None of these rule out batching. They rule out batching *on top of* the current structure. What they
argue for is closer to a video encoder's GOP split: fixed, input-derived partitions, a cold start
with
a short overlap at each seam, and per-partition finishing, with the parent reduced to warm-up,
dispatch and an ordered merge.

## 3. Proposed architecture

### 3.1 The batch: one serial decoder over a sample range

A batch is `LDdecode` running its `-t 1` path over `[start, end)` samples with three additions:

- it is constructed from a **calibration snapshot** (§3.3) instead of cold defaults;
- it decodes an **overlap** of `O` fields before `start` whose outputs are discarded but whose
  servo, burst-lock, EFM/AC3 state are kept (this is `--start`'s cold start plus a warm-up of
  the tracking servos);
- it continues an **overrun** of a few fields past `end` so its successor can find the seam (§3.4);
- it writes to a **segment** (a temp file per output stream plus a per-field record list) rather
  than the final files, and reports its end state.

Everything inside is the reference path: `readfield` with pipeline depth 1, `writeout` inline,
`CVBSWriter` with its own burst lock, its own `EFM_PLL`/`EFMTimingDemod` instance, its own reader
(and therefore its own FLAC decoder thread - the one thread a batch process has besides the main
one). Modes that today cannot use field jobs at all - `--RF-TBC`, `--AC3`, auto echo cancellation
(`use_field_jobs`, `decoder.py:782`) - become parallel for free, because nothing inside a batch
assumes a pure demod or ships a field's raw input anywhere.

### 3.2 Partitioning: fixed by the input, never by `-t N`

Batch length is a function of the decode range only (a fixed number of nominal fields, e.g. ~1000,
as a CLI option so CI can shrink it to a few dozen and exercise seams on the short test captures).
`-t N` sets only how many batches run concurrently. This is what keeps AGENTS.md §4.4's guarantee -
`-t N` bit-identical to `-t 1` - true by construction: `-t 1` runs the same batches one after
another, `-t N` runs them N at a time, and nothing in the output can depend on completion order or
timing. The earlier idea of sizing batches by `-t N` and capture length would have broken exactly
that guarantee and is dropped.

Workers pull batches from an ordered queue (batch `k+1` is taken by whichever process frees up), so
a damaged region that decodes slowly delays its own batch, not the partition.

### 3.3 Calibration: global warm-up, batch-local tracking

The parent runs today's serial warm-up from the decode start until `pipeline_warm` - deemp, AGC and
the first MTF/EQ/DG adoptions, ~20-30 frames - and snapshots `rf.DecoderParams`, `mtf_level`, the
servo pools (`bw_ratios`, `_veq_samples`, `_dg_samples`, `_imtf_flat_band`) and the AGC levels.
Every batch starts from that snapshot; batch 0 starts from the warm-up's true state with no overlap.

The tracking servos then run **inside** each batch from the snapshot, warming over the overlap. This
is a deliberate change of what the output *is*: a batch's servo state at field `n` is a function of
the snapshot and of fields `start - O .. n`, not of the whole disc before it. It cannot be otherwise
without serialising the batches (a handoff of batch `k-1`'s end state to batch `k` is a chain, not a
fan-out). The consequences:

- `-t 1` and `-t N` agree bit-for-bit because they run the same batches with the same snapshot.
- Output differs from today's decoder at and after every seam by whatever the servo would have
  adopted differently. The overlap must be long enough that the tracking servos reach their
  steady-state dead-bands on ordinary material: the MTF pool is a rolling mean of 30 fields on CAV
  but **900 on CLV** (`decoder.py:2685`), the DG servo needs `DG_MIN_SAMPLES` staircase
  measurements (only fields that carry an ITS staircase count) and the EQ servo `VEQ_MIN_SAMPLES`
  multiburst fields. An overlap of ~60 fields (1.2 s of video, 6% of a 1000-field batch) is the
  starting point for CAV; it is a measured quantity, not a constant to guess, and CLV is a
  separate question (§11).
- The write-time servo outputs (DG slope/phase, the burst-lock shift) are re-anchored per batch.
  For the PAL lock this is safe by design: the writer anchors to a target defined mod 90 degrees
  (`_pal_phase_error`, `cvbs.py:459`), so two batches anchoring independently land on the same
  lattice phase within the residual tolerance, and `_lock_state` keeps reporting LOCKED honestly.

This trades "identical to the causal serial decode" for "identical across thread counts, and
non-causal-safe at seams". The precedent is already set: the imtf-ceiling fix changed `-t 1
--exact-speculation` output to match the parallel path, and the VITS conformance lane, not byte
equality with the previous release, is what guards quality.

### 3.4 Seams: agreement between chains, not a pre-computed index

Batch `k` cold-starts at its nominal offset, decodes its overlap, and by `start` has a chain of true
field starts. Batch `k-1` overruns past `end` by a few fields. Both chains cover the same fields
around the seam, and a field decoded from the same block-quantised window is bit-identical
(`_accept_job`'s `readloc_block` test, `decoder.py:3300`; the property `FieldJobEngine` already
relies on). The seam rule: **batch `k` owns fields from the first first-field at or after `start`
whose window block matches batch `k-1`'s chain at that field**; batch `k-1` owns everything before
it. Both sides' overrun/overlap outputs for the other side's fields are discarded.

If no agreement is found within the overrun (heavy dropout or an unlocked region straddling the
seam), batch `k-1` keeps decoding forward through batch `k`'s range until the chains agree, and
batch `k`'s output up to that point is discarded. The rule is a function of the two chains only, so
it is deterministic; the cost of a bad seam is redundant work, never a different output.

Cutting at a first field keeps CVBS frame pairing whole. EFM and AC3 cut at the same field: both
demodulators inside batch `k` have consumed the overlap's slices, so the run open across the seam
field boundary is held in the same state a continuous stream would hold it at that point, given the
overlap is longer than the PLL's acquisition. Only the last batch flushes the EFM tail
(`_close_outputs`, `decoder.py:890`).

### 3.5 What finishes where

Not everything can finish in the batch, because some outputs are numbered by *count*, which only
the merge knows:

| Work | Cost/field | Depends on | Runs in |
|---|---|---|---|
| RF demod, `Field.process`, video downscale, metrics, dropouts | ~0.5-0.9 s (box-dependent) | the field | batch |
| PAL CVBS 4fsc resample + DG/phase correction, burst lock | ~100-200 ms/frame | field, batch-local lock | batch |
| EFM / AC3 demod | ~15-20 ms | batch-local stream state | batch |
| MTF / EQ / DG / imtf servos | small | batch-local pools | batch |
| analogue audio downscale (`downscale_audio_out`, `field.py:1309`) | a few ms | absolute field number from the previous *written* field | merge |
| `.tbc.db` rows, CVBS frame ids, `.efm` frame index, WAV | small | field/frame count | merge |

Batch segments therefore carry: fixed-size video (TBC fields or CVBS frames), the EFM/AC3 output
slices with per-field counts, the per-field audio demod (`audio_phase1`/`audio` arrays, ~0.3 MB per
field) for the merge to downscale, and the `fieldinfo` dicts. The merge is a sequential append of
video (`copy_file_range` where the filesystem allows, a stream copy otherwise), the cheap audio
downscale with the real `lastFieldWritten` chain, and the metadata writers exactly as they run
today. `OrderedOutputLane`'s shape (one thread, in order, bounded look-ahead, errors re-raised on
the submitter) is reused at batch granularity for this.

### 3.6 Unwinding the existing structure

Each current mechanism, and its fate. "Retired" means removed once Phase 4 lands, not
kept as an alternative path.

| Mechanism | Inside a batch | In the orchestrator | Fate |
|---|---|---|---|
| FLAC reader thread | one per batch process (each has its own GIL) | one, for the warm-up only | kept |
| `DemodBlockCache` thread prefetch | off (`block_cache=None`, the `-t 1` path) | optional, warm-up only | retired unless warm-up time matters |
| `FieldJobEngine` + worker pool, speculation, tolerant/exact acceptance | off | - | retired; `--exact-speculation` goes with it (batches are exact by construction) |
| stage-2 pool | off | - | retired |
| `OrderedOutputLane` | off (writeout inline) | reused for the ordered merge | reshaped |
| output pool (stale DG re-correction) | off (no stale fields exist) | - | retired |
| CVBS field-B resample executor | off (frames resample inline, one lock per batch) | - | retired |
| `keep_demod` transport, `field_output_view`, `_pair_cvbs_view`, `chroma_dg_output_picture` speculation keys | unnecessary | - | retired |
| `setswitchinterval` GIL tuning | unnecessary | - | retired |

What that removes is roughly the whole of `parallel.py` except the lane, plus the speculation
bookkeeping in `decoder.py` and the transport/view plumbing in `field.py` and `cvbs.py` - and with
it the class of bug `d4703045` fixed, because there is no longer any in-flight work decoded under
parameters that can change before it commits.

What must be added: a batch runner (construct `LDdecode` from a snapshot, decode a range with
overlap/overrun into a segment, report chain positions and end state), an orchestrator (warm-up,
partition, worker pool of batch processes, seam resolution, merge), and the segment format. The
reader lock rule in AGENTS.md §5.3.3 ("all raw reads go through the single reader lock") becomes
"one reader per process"; the cached-demod purity rule becomes moot.

Pipe input cannot be partitioned. The recommendation is that stdin input decodes serially (`-t` is
ignored with a warning) rather than keeping the field-job machinery alive as a second parallel
path for that one case; if piped parallel decode matters, spooling the pipe to a temp file and
batching it is simpler than maintaining both.

## 4. What this does and doesn't fix

Fixes: the PAL CVBS 2-way ceiling and the single-thread EFM cost (throughput analysis §3.2-3.3),
because
each batch runs its own; the parent-process commit-loop ceiling (§1), because the parent no longer
touches per-field work; the IPC and GIL-convoy costs, because nothing per-field crosses a process
boundary; and the modes excluded from field jobs today.

Does not fix: the per-field RF demod cost (~75% of a field's own decode, numba/scipy-bound). On an
8-physical-core box this means the realistic ceiling is roughly one serial decode per core minus
overlap overhead - about the `--tbc` NTSC scaling already measured (1.66x at `-t 6`), extended to
PAL CVBS and to many-core machines where the parent ceiling currently bites. Expect PAL CVBS to
move from its flat 3.6 fps to the neighbourhood of PAL `--tbc` (5.3 fps at `-t 6`), and everything
to keep scaling past `-t 6` on boxes that have the cores.

**The throughput ceiling above is measured false on the reference box** (`decode-throughput-plan.md`
§8, Phase 6). "Roughly one serial decode per core" was the whole of this design's throughput case,
and it does not hold: on an 8-core 5800X, *eight* independent serial PAL CVBS decoders — the best
case this architecture can reach, with no orchestrator, no overlap and no seams — deliver 11.2 fps,
below the 12.0 that four deliver, at the same instructions per frame for 2.4× the cycles. Past four
concurrent decoders the added copies raise DRAM traffic per frame faster than they convert cores
into frames. Meanwhile the existing field-job pool now reaches that same four-decoder figure on PAL
`--tbc` (11.77 against 11.74) and comes within 17% of it on PAL CVBS. So the prize here is at most
that 17%, on one mode, on this box — not the 2–3× the paragraph above assumed — and it is available
from parent-side items already priced in `decode-throughput-plan.md` §7. This plan is not reopened
on throughput grounds; the simplification case in §3.6 stands on its own merits and is unaffected.

Costs: the overlap (6% at 60/1000), the extra read of each overlap, one `LDdecode` memory footprint
per concurrent batch instead of one plus N slim workers, and N sequential read streams into the
same file (fine on SSD; measure on spinning disks). Short captures gain little: a capture of two
batches is at most 2x, and the CI captures are one batch at the default length.

## 5. Validation material

Disc format is the **decoder's** verdict (`isCLV`, `decoder.py:3523-3543`), taken from a four-frame
probe at file frame 5000, not from the filename or the capture JSON — `isCLV` is what selects the
900-field MTF pool (`decoder.py:2685`), so it is the only reading that matters here. Verification
status is recorded in §5.2.

### 5.1 The material

| Capture | System | Format | Role |
|---|---|---|---|
| `testdata/ntsc/ve-snw-cut.ldf`, `ve-monitor.ldf` | NTSC | CAV | CI identity gates; seam tests at small batch length |
| `testdata/pal/ggv-mb-1khz.ldf`, `jason-testpattern.ldf` | PAL | CAV | CI identity gates |
| `testdata/ntsc/issue176.ldf` | NTSC | CLV | the only CLV capture in CI: exercises the CLV code path, far too short for the 900-field pool |
| `testdata/radius/domesday-ds2-community-north-{inner,middle,outer}.ldf` | PAL | CAV | DG-affected material; the DG servo at seams; `domesday-ds2-community-north-middle` also carries the known `-t 1`/`-t N` divergence |
| `Domesday_DD86-DS2_NationalA_PP_20191014_CAV_PAL_00001-54000.ldf` | PAL | CAV | throughput sweeps (the existing PAL benchmark); PAL CVBS burst lock |
| `Domesday_DD86-DS2_NationalB_PP_20191014_CLV_PAL_00-60.ldf` | PAL | **CLV** | **the primary CLV case**: same disc set and rig as the CAV benchmark, so CAV-vs-CLV servo behaviour is a controlled comparison rather than a cross-disc one; DG-affected; carries EFM |
| `Grosse Pointe Blank_side1_2025-11-19_12-26-27.ldf` | PAL | **CLV** | long CLV soak; recent LD-V4300D capture with capture-side JSON; digital audio |
| `A man a woman and a bank_CLV_PAL_side1_2020-02-15_17-09-55.ldf` | PAL | **CLV** | second CLV opinion, different capture run (2020) |
| `Falklands Task Force South_CLV_PAL_side1_BBC Video_2019-12-23_13-59-42.ldf` | PAL | **CLV** | third CLV opinion |
| `Bambi_CLV_NTSC_side1_JapanImport_LDG_2020-01-22_20-25-19.ldf` | NTSC | **CLV** | NTSC CLV servo behaviour; EFM baseline capture |
| `Cinderella_CLV_NTSC_side1_JapanImport_CC_2020-01-22_18-19-04.ldf` | NTSC | **CLV** | second NTSC CLV opinion; EFM baseline capture |
| `Red Arrows_side1_2025-11-19_14-15-55.ldf` | PAL | CAV | long CAV soak and the N-reader read-pattern test |

Roots: Domesday captures under `/home/sdi/raid/library/BBC_AIV/Domesday/Domesday_DS2/`; the
LD-V4300D captures under `/home/sdi/raid/sftp/simoninns/LDV4300D_1/{PAL,NTSC}/<title>/`. All are on
the raid mount, so every measurement that involves them also measures the raid's read behaviour;
Phase 0 Task 2 separates the two by repeating one case from local storage.

### 5.2 Verification status

Recorded by the probe described in Phase 0 Task 1. `decoder` is the disc type the decoder derived;
`fps` is a four-frame CVBS decode at `-t 1` and is a smoke reading, not a benchmark.

All fourteen captures decode without error, and in every case the decoder's verdict matches what
the filename or capture JSON claimed. Six captures are confirmed CLV by the decoder — four PAL
(one of them Domesday) and two NTSC — so Phase 0 Tasks 3-5 have the CLV material they need.

| Capture | System | Decoder says | Claimed by | Size | Smoke fps |
|---|---|---|---|---|---|
| `testdata/ntsc/ve-snw-cut.ldf` | NTSC | CAV | CAV (README) | 28 MB | n/a |
| `testdata/ntsc/ve-monitor.ldf` | NTSC | CAV | CAV (README) | 81 MB | n/a |
| `testdata/ntsc/issue176.ldf` | NTSC | CLV | CLV (README) | 4 MB | n/a |
| `testdata/pal/ggv-mb-1khz.ldf` | PAL | CAV | CAV (README) | 23 MB | n/a |
| `testdata/pal/jason-testpattern.ldf` | PAL | CAV | CAV (README) | 6 MB | n/a |
| `testdata/radius/domesday-ds2-community-north-middle.ldf` | PAL | CAV | CAV (README) | 34 MB | n/a |
| `DS2 NationalA (benchmark)` | PAL | CAV | CAV (filename) | 54.5 GB | 0.54 |
| `DS2 NationalB` | PAL | **CLV** | CLV (filename) | 77.1 GB | 0.57 |
| `Grosse Pointe Blank side 1` | PAL | **CLV** | CLV (JSON) | 60.5 GB | 0.58 |
| `A man a woman and a bank side 1` | PAL | **CLV** | CLV (filename) | 62.7 GB | 0.55 |
| `Falklands Task Force South side 1` | PAL | **CLV** | CLV (filename) | 66.5 GB | 0.56 |
| `Red Arrows side 1` | PAL | CAV | CAV (JSON) | 30.3 GB | 0.61 |
| `Bambi side 1` | NTSC | **CLV** | CLV (filename) | 49.7 GB | 1.06 |
| `Cinderella side 1` | NTSC | **CLV** | CLV (filename) | 56.1 GB | 0.86 |

Smoke fps is a four-frame `-t 1` CVBS decode seeked to file frame 5000, taken while the capture was
read over the raid mount, and includes numba warm-up. It says the capture decodes; it is not a
throughput figure. CI captures decode from their start and are not timed.

`DS2 NationalB` is the primary CLV case. It is CLV PAL from the same disc set, rig and capture
session as the CAV benchmark `DS2 NationalA`, which makes the CAV-versus-CLV servo comparison in
Phase 0 Task 4 a controlled one rather than a comparison across two unrelated discs. It is also
DG-affected Domesday material and carries EFM, so it exercises the chroma DG servo and the EFM
stream at a seam at the same time.

Reproduce one row with:

```bash
nix develop --command python -m lddecode.main --pal -s 5000 -l 4 <capture>.ldf /tmp/probe
```

and read the disc type off the per-frame `File Frame N: CAV|CLV` log line. Note that
`nix develop "path:$PWD"` fails on this flake (`attribute 'shortRev' missing`, `flake.nix:22`)
because a `path:` source carries no git metadata; use the plain `nix develop`.

### 5.3 Phase 0 Task 2 result: the premise does not hold

Measured on the box in §5.1's roots (Ryzen 7 5800X, 8 physical cores, 32 MiB shared L3), 2000
frames per arm, post-setup fps from the decoder's own report:

| Mode | 1 serial decode | 8 concurrent serial decodes | `-t 8` | `-t 6` |
|---|---:|---:|---:|---:|
| PAL CVBS (DS2 NationalA) | 2.65 | 5.05 | 5.02 | 5.16 |
| PAL `--tbc` (DS2 NationalA) | 2.68 | 8.72 | 7.17 | 7.83 |
| NTSC CVBS (Bambi) | 2.98 | 12.48 | 10.84 | 10.80 |

Eight independent serial decoders match the existing threaded decoder within −2% to +15%, at
2–2.5× its resident memory (7.5 GB against 3.0 GB for PAL CVBS), against a design premise of
"roughly one serial decode per core" (≈21 fps for PAL CVBS). Per-process throughput under 8-way
concurrency falls to 24% (PAL CVBS), 41% (PAL `--tbc`) and 52% (NTSC) of the same decode run alone,
while each process still receives ~1.1 cores. Pinning one process per physical core is slightly
worse (4.75 vs 5.17 fps), and a STREAM-style probe shows aggregate memory bandwidth flat from 1 to
16 workers (9.8 → 8.4 GB/s): a single thread saturates this box's path to DRAM. The concurrency
curve for N independent serial PAL CVBS decoders (150 frames each) is 2.53, 4.56, 6.90, 6.78, 6.49,
6.60, 5.81 aggregate fps at N = 1, 2, 4, 6, 8, 12, 16 — the second decoder costs 10%, the fourth a
third, and sixteen do less total work than four.

The cause is the shared cache, not the concurrency structure. Each decoder's hot working set is
~12 MiB — a 4.3 MiB slice of an 11.0 MiB `complex128` filter bank read every 32 KiB block, a
4.00 MiB sinc resample LUT read at one cache line per output sample with a ~1 MiB stride, and
~4 MiB of live temporaries — so two decoders fill the 32 MiB L3 and a third evicts them. Sweeping
`-t` on PAL CVBS shows the plateau beginning at `t=2` at every run length tested (150, 1000 and
2000 frames); run length moves the plateau's level (3.85 → ~4.8 → 5.16 fps) but not its onset.
Eight processes and one process with eight workers hit the same wall because they carry the same
working set.
`perf` confirms the mechanism: one serial decoder among eight executes the same instructions per
frame as one alone, in 3.2× the cycles (IPC 2.67 → 0.83), with fills from DRAM up five-fold
(0.33 → 1.67 GB per frame).

**Verdict: this plan stops at Phase 0 Task 2**, as Task 2's acceptance criterion requires. What
raises the ceiling is shrinking one decoder's working set, which helps `-t N` and any future
batching alike and needs none of Phases 1–4. That work is
[`plans/decode-working-set-plan.md`](decode-working-set-plan.md). The measurements behind this
section are in [`decode-memory-profile-analysis.md`](decode-memory-profile-analysis.md); every
figure this verdict rests on is restated above.

Two corrections to this plan's premises surfaced on the way and are recorded here so the CLV
question is not carried forward wrongly:

- The `keep = 900 if self.isCLV else 30` pool (`decoder.py:2685`, `:2781`) is `bw_ratios`, the
  **open-loop fallback** the MTF servo uses only when the 2T servo has no usable estimate. The
  primary loop pools `MTF_SERVO_KEEP = 60` samples over `MTF_SERVO_MAX_AGE_FIELDS = 240`, on both
  formats; the EQ and DG pools are 24 samples over 240 fields. A ~240–300-field overlap re-warms
  every servo on any disc whose ITS the 2T servo can measure, and the CLV problem in §11 reduces to
  discs where it cannot.
- Every servo carries a 100-field minimum adoption interval (`MTF_SERVO_MIN_ADOPT_FIELDS`,
  `VEQ_MIN_ADOPT_FIELDS`, `DG_MIN_ADOPT_FIELDS`, `decoder.py:1149-1208`). A servo needing *k*
  adoptions from a cold start needs at least 100*k* fields whatever its pool size, so §3.3's
  60-field overlap starting point is short by construction.

### 5.4 Phase 0 Tasks 3–5 results: servo settle, CLV policy, burst lock

Recorded although the plan stops at Task 2, because the settle figures are what any future seam
design would be sized by. Method: one continuous `--tbc -t 1` decode of 2600 frames from the start
of each capture, four cold starts inside it (`-s` 600, 1000, 1400, 1800 frames, 700 frames each),
and ten 500-frame cold probes spread across each whole side. Every committed field's servo state
was logged; cold trajectories are aligned to the continuous one by sample position. A delta is
"inside" when it is smaller than the servo's own dead-band (`mtf_level` 0.10, `inverse_mtf_strength`
0.05, EQ 0.3 dB, `chroma_dg_slope` 0.0004/IRE, `chroma_dg_phase` 0.005°/IRE), since a smaller
delta cannot change what the servo does.

Cold starts inside the dead-band of the continuous decode, out of 8 (4 CAV on DS2 NationalA,
4 CLV on DS2 NationalB), after:

| Servo | 60 fields | 300 fields | 900 fields |
|---|---:|---:|---:|
| `mtf_level` | 7 | **8** | 8 |
| `video_eq_auto` (2T gain, dB) | 8 | 8 | 8 |
| `chroma_dg_slope` | 7 | 8 | 7 |
| `chroma_dg_phase` | 4 | 3 | 4 |
| `inverse_mtf_strength` | 2 | 1 | **4** |

**Task 3.** The MTF and EQ servos re-warm from cold within 300 fields on both formats; the DG
slope does too. The slow ones are `inverse_mtf_strength` — outside its dead-band at 900 fields in
four of eight runs (deltas 0.07–0.11 against a 0.05 band), driven by the burst-tracking deemp
calibration and the multiburst ceiling under their 100-field adoption interval — and
`chroma_dg_phase`, which hovers at its dead-band (deltas 0.002–0.010 against 0.005) throughout. An
overlap sized for MTF (300 fields) would leave the inverse-MTF strength unsettled at a seam roughly
half the time; sizing for it means well over 900 fields, i.e. most of a 1000-field batch.

**Task 4.** The CLV question is answered by which loop is in charge: the 2T servo was engaged on
100% of committed fields on both discs (`_servo_samples` at its 60-sample cap throughout), so
`mtf_level` was never set by the 900-field `bw_ratios` pool on the CLV disc, and it re-warmed in
≤ 300 fields there exactly as on CAV. Across the whole CLV side `mtf_level` moves 0.13 (1.3
dead-bands); across the CAV side it moves 1.0 (10 dead-bands) — the CAV disc is the harder one. On
DS2 NationalA the 2T servo *disengages* for the outer 40% of the side (engaged fraction 0.92 at
frame 27,500 and 0.00 from 32,500 on), and `mtf_level` sits on the open-loop mapping's floor of
0.0 from there; that is where a CLV-style long pool would matter, and it is a CAV disc. None of the
three §11 options is needed for CLV as such; what a seam design would have to carry is the
inverse-MTF strength, on both formats.

**Task 5.** Two independent burst-lock anchors converge to the same lattice phase on DS2 NationalA
— shift difference ≤ 1.5° mod 90° (mean 0.1–0.4°), inside `LOCK_TOL` 3.0° — but **not on Grosse
Pointe Blank**: 7.9–8.5° maximum, ~5° mean, with each run reporting itself LOCKED (own residuals
≤ 2.1°). Two batches anchoring independently on that disc would carry a ~5° subcarrier phase step
at every seam. §3.3's per-batch re-anchoring therefore fails its acceptance criterion; the lock
would have had to go in the calibration snapshot.

Across the CAV side the servos travel far more than the dead-bands: `inverse_mtf_strength` spans
2.4 (48 dead-bands, −1.7 at the inner probe to +0.66 at the outer), `chroma_dg_phase` 0.10 (21
dead-bands), `chroma_dg_slope` 0.0037 (9 dead-bands). The DG servo was active (slope
0.0008–0.0037/IRE) over frames 2,500–7,500, i.e. throughout the span the throughput sweeps in §5.3
were run on, so the chroma-DG correction's per-frame transforms are included in those figures.

## 6. Phase 0 — measure before building

No decoder changes. Settles the design constants and the premise, so Phases 1-3 implement
decisions rather than experiments.

**Task 1 — verify the validation material.** Probe every capture in §5.1 with a short decode at a
fixed seek offset; record the decoder-derived disc type, exit status and smoke fps.
*Acceptance:* §5.2 filled in for every row; every capture decodes without error; at least two PAL
CLV, two NTSC CLV and two CAV captures confirmed CLV/CAV by the decoder rather than by filename.

**Task 2 — test the premise.** Run `N` independent `-t 1` decodes of disjoint ranges of one capture
concurrently (`-s k*L -l L`, `N` = the box's physical core count) and compare aggregate frames per
second against a single `-t N` decode of the same span. Cover PAL CVBS, PAL `--tbc` and NTSC CVBS.
Record per-process peak RSS (`resource.getrusage(RUSAGE_CHILDREN)`) and repeat one case with the
capture on local storage to separate raid behaviour from decode behaviour.
*Acceptance:* a table of aggregate fps for concurrent-serial vs `-t N` per mode; a per-process RSS
figure; a stated verdict on whether N serial decoders beat one distributed decoder. **If they do
not, this plan stops here.**

**Task 3 — measure servo settle time from cold.** Full serial decode of one CAV capture
(DS2 NationalA) and one CLV capture (DS2 NationalB) logging every servo value per field
(`mtf_level`, `inverse_mtf_strength`, `video_eq_auto`, `chroma_dg_slope`, `chroma_dg_phase`). Repeat
with decodes started cold at several `-s` offsets into the same captures. For each servo, count the
fields a cold start needs before its trajectory enters the continuous decode's dead-band.
*Acceptance:* per-servo, per-format settle-field counts; the overlap default for CAV chosen from
the slowest servo, with margin; the counts recorded in §5.2 beside the material they were measured
on.

**Task 4 — decide the CLV policy.** From Task 3's CLV runs: how far a cold `mtf_level` sits from
the continuous one after 60, 300 and 900 fields, and how much `mtf_level` moves across a whole CLV
side. Compare against the CAV capture from the same disc set and rig.
*Acceptance:* one of the three options in §11 (carry the pool in the snapshot; longer batches on
CLV; sparse pre-pass seeding) chosen with the measurement that justifies it, and §3.3 amended to
state it.

**Task 5 — check PAL burst-lock stationarity.** Log `_pal_shift` and `_lock_residuals`
(`cvbs.py:355-390`) over a continuous CVBS decode of DS2 NationalA and Grosse Pointe Blank, then
from several `-s` starts.
*Acceptance:* the shift two independent anchors converge to agrees within `LOCK_TOL` (3.0 degrees)
on both captures, confirming §3.3's per-batch re-anchoring; or, if it does not, the burst lock is
added to the calibration snapshot and §3.3 amended.

## 7. Phase 1 — the range decoder

`LDdecode` decodes `[start, end)` from an injected calibration snapshot, with overlap and overrun,
into a segment, and reports its end state and chain positions. Output is unchanged: a single
whole-file batch with no snapshot must be byte-identical to today's `-t 1`.

**Task 1 — calibration snapshot.** Factor the constructor so calibration state
(`rf.DecoderParams`, `mtf_level`, `bw_ratios`, `_veq_samples`, `_dg_samples`, `_imtf_flat_band`,
AGC levels, `deemp_calibrated`, `pipeline_warm`) is a dataclass that can be exported from a running
decode and injected into a new one.
*Acceptance:* unit tests for a round trip (export, inject, decode one field, identical result) with
no filesystem access; injecting a snapshot taken at warm-up reproduces the warm decoder's
parameters exactly.

**Task 2 — range bounds and seam bookkeeping.** Add range start/end, overlap and overrun counting,
and a per-committed-field record of true start position and demod window block.
*Acceptance:* unit tests with a scripted decode assert that overlap fields are decoded but not
committed, that overrun fields are committed to the segment but flagged, and that the recorded
window block matches `decodefield`'s own quantisation.

**Task 3 — segment format.** New layer-1 leaf module: per-field records (`fieldinfo`, audio demod
arrays, EFM/AC3 slices with counts), the video segment, and the readers the merge needs.
*Acceptance:* unit tests round-trip records through `io.BytesIO` with no filesystem access and
assert bit-exactness of every array; sizes per field recorded for the memory budget.

**Task 4 — split the writers.** Separate `CVBSWriter` frame assembly (`_emit_frame` through
`_to_spec_levels`) from file and metadata writing; likewise the `.tbc.db` row writer and
`_writeout_data`, so a batch can produce frames and records while the merge writes files.
*Acceptance:* unit tests drive both writer halves from synthetic records; with no segment
configured the existing path is used unchanged.

**Task 5 — identity gate.** A single whole-file batch, no snapshot, over the CI captures.
*Acceptance:* byte-identical to the current `-t 1` output for `.tbc`/`.cvbs`, `.efm`, `.pcm`/WAV
and the `.tbc.db` contents; existing `compare-*` CTest lanes green; `-t N` behaviour untouched.

## 8. Phase 2 — orchestrator with a synchronous executor

Warm-up, snapshot, partition, batches run one after another in the parent, seam resolution, merge.
`-t 1` becomes "batched serial", and this is the phase where the reference output changes.

**Task 1 — warm-up and partitioner.** New layer-4 module: run today's serial loop to
`pipeline_warm`, export the snapshot, and partition the decode range into batches whose geometry is
a function of the range and `--batch-fields` only — never of `-t N`.
*Acceptance:* unit tests assert identical partition geometry across thread counts and across runs;
overlap and overrun are applied at every interior seam and suppressed at the ends.

**Task 2 — seam resolver.** Implement §3.4: batch `k` owns fields from the first first-field at or
after its start whose window block matches its predecessor's chain, with the predecessor decoding
onward when no agreement is found.
*Acceptance:* unit tests drive scripted chains through agree-at-start, agree-late, agree-on-a-later
field and never-agree, asserting the owned range and that the decision is a pure function of the
two chains.

**Task 3 — merge.** Video append (`os.copy_file_range` with a stream-copy fallback), the audio
downscale with the real `lastFieldWritten` chain, the metadata writers, and the EFM tail flush on
the last batch only.
*Acceptance:* unit tests merge synthetic segments and assert output identical to writing the same
records inline; the audio clock matches a continuous decode's field numbering.

**Task 4 — CLI and pipe fallback.** `--batch-fields` and `--batch-overlap` in `main.py` only,
defaulted from Phase 0; pipe input forces the unbatched serial path with a warning.
*Acceptance:* the library is callable without the flags; a piped decode warns once and produces the
same output as today; `docs/user-guide/command.md` updated in the same change.

**Task 5 — seam observability.** Log every seam's agreement offset and every fallback to the decode
log and to a `.tbc.db` table.
*Acceptance:* a seam-heavy decode shows one row per seam with its agreement offset; a forced
never-agree case is visible as such.

**Task 6 — re-baseline and conformance gate.** Seam-heavy runs (`--batch-fields` of a few dozen) on
the CI captures, the radius set, DS2 NationalA and NationalB, and Grosse Pointe Blank.
*Acceptance:* VITS conformance verdicts and quality tables within their known-deviation bands, with
no widening of `analysis/vits_known_deviations.toml`; no servo step at a seam beyond the servo's
dead-band; byte baselines re-recorded in one commit containing nothing else.

## 9. Phase 3 — process executor

**Task 1 — executor.** A spawn-based process pool: each worker builds its own `LDdecode` from
`rf_opts` and the snapshot, opens its own loader, writes its segment to a scratch directory and
returns the segment path with its chain positions. Batches are pulled from an ordered queue.
*Acceptance:* unit tests with an injected fake executor cover ordering, out-of-order completion and
error propagation from a worker; no test starts a real process.

**Task 2 — streaming merge.** The merge consumes segments in batch order as they complete, bounded
so scratch usage stays proportional to the in-flight batch count rather than the capture length.
*Acceptance:* peak scratch usage measured on a full-side decode and stated; a worker failure
surfaces on the merging thread and stops the decode without a partial output file being mistaken
for a complete one.

**Task 3 — thread-count default.** Rederive the `-t` auto default from `main.physical_cpu_count`
and the per-process RSS measured in Phase 0 Task 2.
*Acceptance:* the default lands at or below the measured optimum on the reference box and does not
exceed available memory at that count; unit test for the arithmetic with injected core and memory
counts.

**Task 4 — identity gate.** `md5(-t N) == md5(-t 1)` with the same batch geometry, for
`.tbc`/`.cvbs`, `.efm`, `.pcm`/WAV and the `.tbc.db` contents, over the Phase 2 material.
*Acceptance:* identity holds for `N` in at least {2, 6, physical core count}; repeated `-t N` runs
identical; the identity CTest lanes updated to force a small `--batch-fields`.

**Task 5 — throughput and soak.** Re-run the four `(system, mode)` sweep cells; soak one full CLV
side (DS2 NationalB or Grosse Pointe Blank) and one full CAV side (Red Arrows).
*Acceptance:* PAL CVBS scales past its current flat 3.6 fps and tracks PAL `--tbc`; every mode
keeps scaling to the physical core count; the soak decodes complete with identity holding and
memory within Task 3's budget.

## 10. Phase 4 — retirement and documentation

**Task 1 — remove the retired mechanisms.** Everything marked retired in §3.6: the field-job
engine and its speculation bookkeeping, the block cache's prefetch, the stage-2 pool, the output
pool, the CVBS resample executor, `keep_demod`, `field_output_view`, `_pair_cvbs_view`, the
`chroma_dg_output_picture` speculation key, `--exact-speculation` and the `setswitchinterval` call.
*Acceptance:* `parallel.py` reduced to the ordered lane and the executor; no dead references; unit
and functional lanes green.

**Task 2 — retire the matching tests.** `test_parallel_blockcache`, `test_field_cvbs_transport`,
`test_field_output_view` and the per-field lane cases of `test_decoder_output_stage`;
`test_parallel_output_lane` stays with the lane.
*Acceptance:* no test references a removed symbol; unit lane runtime does not regress.

**Task 3 — rewrite the CTest lanes.** `compare-*-parallel-*` restated on the new invariant with an
explicit small `--batch-fields` so the CI captures contain seams.
*Acceptance:* the lanes fail if batch geometry is made `-t`-dependent, and fail if a seam changes
output.

**Task 4 — documentation.** `docs/user-guide/command.md` for `-t`, the batch options, pipe
behaviour and the removed flag; a `docs/technical/` page on batch decode and what determinism means
now; `AGENTS.md` §5.3.3 restated as "one reader per process" with the cached-demod purity rule
dropped, and §4.4 restated as `-t N` bit-identical to `-t 1` under the same batch geometry.
*Acceptance:* `nix build .#docs` succeeds; no documentation references a removed flag.

## 11. Risks and open questions

- **Overlap sufficiency.** The overlap is the whole determinism-versus-quality trade: too short and
  a seam carries a visible servo step, too long and the redundant decode eats the gain. Phase 0
  Task 3 measures it per servo on clean and DG-affected material; Phase 2 Task 6's seam-heavy runs
  confirm it. A dropout-heavy region landing on a seam is the worst case, because the overlap has
  less real signal to settle on, and needs its own test rather than averaged-case validation.
- **CLV and long-memory servos.** The MTF pool keeps 900 fields on CLV against 30 on CAV
  (`decoder.py:2685`), so an overlap sized for CAV cannot re-warm it: a CLV batch would run on the
  snapshot's pool, gradually replaced by its own samples, making the MTF trajectory across a CLV
  side a sequence of per-batch restarts rather than one continuous track. Three options: carry the
  pool in the snapshot and accept the restart; use longer batches on CLV; or add a sparse pre-pass
  that records the MTF/EQ/DG trajectory every few hundred fields and seeds each batch from it,
  which would also make the servos non-causal and arguably better than today. Phase 0 Task 4
  decides, on DS2 NationalA and NationalB (§5.2); Phase 2 implements the decision.
- **Seam disagreement.** §3.4's fallback of letting the predecessor decode onward is correct but
  can, on very bad material, collapse a batch into serial work. Phase 2 Task 5 makes every seam's
  agreement offset and every fallback visible in the decode log and the `.tbc.db`.
- **Audio at the merge.** Deferring the audio downscale keeps today's clock semantics exactly, at
  the price of carrying per-field audio demod arrays in the segments. Numbering fields from the
  batch's nominal start instead would be fully batch-local but changes the A/V clock's definition;
  it is a fallback if segment size proves a problem, not the default. Phase 1 Task 3 measures the
  per-field record size that decides this.
- **Memory.** N concurrent `LDdecode` instances, each with a reader ring buffer and a field stack,
  instead of one parent plus slim workers. Phase 0 Task 2 measures per-process RSS; Phase 3 Task 3
  folds it into the auto `-t` default.
- **Read pattern.** N seeking readers on one `.ldf`, each also re-reading its overlap. Every
  capture in §5.1 except the CI ones lives on the raid mount, so Phase 0 Task 2 repeats one case
  from local storage to separate the mount's behaviour from the decoder's.
- **Loss of today's causal servo behaviour.** A servo that adopted late in a disc under the causal
  decoder may adopt earlier, or never, under a batch that starts from the snapshot. This is mostly
  an improvement, since batches are closer to non-causal, but it changes what conformance measures,
  so the VITS lanes and the known-deviation list are the gate rather than byte equality with the
  previous release.
- **Short captures and CI.** At any sensible default batch length the CI captures are single
  batches, so the parallel-identity gate only means something with a small `--batch-fields` forced,
  which Phase 4 Task 3 requires. CI has no CLV capture long enough to exercise the 900-field pool;
  that evidence lives in Phase 0's results and the raid captures.
- **Interim alternative, deliberately not taken.** A dead-banded burst lock letting the PAL
  resample ride the field job, plus a dedicated EFM lane, would lift PAL CVBS toward `--tbc`
  throughput without any of this plan. Every line of it lands in Phase 4's removal list and it
  changes CVBS bytes for the serial path too, so it is worth doing only if a release must ship
  before Phase 3.
