# Decode throughput — re-examination after the working-set phases

This document re-examines [`plans/decode-working-set-plan.md`](decode-working-set-plan.md) on the
evidence of its Phases 0–2, and replaces its remaining phases. It is the "take stock and replan"
that plan scheduled as Phase 4, brought forward because Phase 2 falsified the premise the later
phases rest on.

**Verdict in one paragraph.** The working-set plan's mechanism — one decoder's ~12 MiB hot set,
three of which overflow the 32 MiB L3, so shrinking it raises every concurrency ceiling at once —
is wrong. Phase 2 removed a third of the hot set and lost 1–3% everywhere; the whole of its gain
was 96 ms/frame of transform taken off the output thread. Re-measured, there are three separate
ceilings, none of them cache capacity: **(A)** the parent process's per-frame work, which caps
`-t N` at 6.4 fps for PAL CVBS whatever N is; **(B)** the per-field cost of a worker once four or
more of them share the box, which is why PAL `--tbc` and NTSC peak at `-t 4` and fall by `-t 8`;
and **(C)** the machine's DRAM path, 20 GB/s for one core or sixteen, which N independent decoders
reach at N ≈ 4 because a decode streams about 1.3 GB of arrays per PAL frame through caches it
cannot keep them in. The quantity that matters is **bytes streamed per frame**, not bytes resident,
and the biggest streams are whole-field transforms and copies, not the filter bank. The plan below
attacks A first (it is the only thing in the way of PAL CVBS), then B and C together (the same
lever serves both), and only then asks whether the concurrency architecture is the limit.

Sources: §5.1 of the working-set plan (the Phase 2 attribution and counters); the measurements in
§2 below, all made on the Phase 2 tree on the reference box (Ryzen 7 5800X, 8 cores / 16 threads,
32 MiB L3, dual-channel DDR4), PAL `Domesday_DD86-DS2_NationalA` and NTSC `Bambi` at `-s 5000`;
working files under `docs-planning/decode-throughput-replan/` (local, untracked).

---

## 1. What Phases 0–2 established

| Phase | Change | Measured | Mechanism |
|---|---|---|---|
| 1 | hold `MTF ** mtf_level` per adopted level | NTSC CVBS `-t 1` 3.01 → 4.83; PAL +2–9% | 2.29 ms of complex `pow` per block, cycles |
| 1 | `cache=True` on `scale_positions` | 1.8 s off every process start | JIT |
| 2 | chroma-DG transform at `next_fast_len` with a periodic guard | PAL CVBS +19% (`-t 1`) to +44% (`-t 4`, N=4) | 105.6 → 9.1 ms per field of transform, on the output thread |
| 2 | 65536-phase nearest LUT → 256-phase interpolated, 4 MiB → 16 KiB | **−1.7% to −3.1% in every cell**, N=4 included | the 4 MiB was L3-resident and its misses latency-hidden; the blend is real arithmetic |

Both gains were cycles removed from a thread on the critical path. The one pure footprint change
lost. §5.1 of the working-set plan has the full attribution; the point carried forward is that
**a footprint estimate predicts nothing here**, and the remaining phases of that plan — `complex64`
filters (its Phase 3), half-rate video (Phase 6), one picture per field (Phase 5) — were all
justified as footprint.

## 2. The premise, re-measured

### 2.1 The DRAM path is 20 GB/s, and one core saturates it

The analysis's STREAM probe reported 9.8 GB/s flat from 1 to 16 workers and concluded "a cache
question, not a bandwidth one". That probe allocated a fresh temporary every iteration
(`a[:] = b + 3.0 * c`), so it measured page-fault zeroing as much as DRAM. With preallocated
buffers, in-place `np.add(a, b, out=c)` over 256 MiB arrays, and a barrier so every process's
window overlaps:

| processes | 1 | 2 | 4 | 8 | 16 |
|---|---:|---:|---:|---:|---:|
| aggregate GB/s (2 reads + 1 write counted) | 20.0 | 20.5 | 20.1 | 19.8 | 19.7 |

So the box's memory ceiling is ~20 GB/s of streamed traffic, it is flat in core count, and
**a single core can consume all of it**. Every whole-array numpy pass in the decoder is a stream of
this kind. What this changes: the analysis's "nothing that must reach DRAM gains from more cores"
stands, but the reason a decoder reaches DRAM is not that its resident set is evicted — it is that
it streams arrays far larger than any cache, and eight decoders streaming at once divide 20 GB/s
between them.

### 2.2 Where a decode's memory traffic comes from

`perf record` on one serial PAL CVBS decoder (80 frames, DG servo engaged), sampling the two fill
counters and attributing them to native symbols:

| Fills from **L3** (973 MiB/frame solo) | share | Fills from **DRAM** (313 MiB/frame solo) | share |
|---|---:|---|---:|
| scipy pocketfft, real `double` transforms | 44% | numpy copies and casts (`strided_to_contig`, `cast_double_to_*`) | 38% |
| pocketfft, complex `double` transforms | 18% | pocketfft (all) | 20% |
| pocketfft, other (generic radix, c2r/r2c glue) | 3% | numba-compiled kernels (resample, unwrap, dropout, EFM) | 17% |
| CPython interpreter | 13% | `memmove` (block concatenation, transport, ring buffer) | 16% |
| numpy ufuncs (`CDOUBLE_multiply`, casts, `DOUBLE_add`) | 9% | CPython | 6% |
| libc `memmove` | 5% | | |

Two thirds of what a solo decoder pulls from L3 is inside FFT kernels, and its DRAM fills are
dominated by copies, casts and the spectrum-times-filter multiplies — i.e. the filter bank is
*already* not staying in L3 for one decoder, because the field-level streams churn it out. The
block demodulator alone, measured in isolation with `perf stat` over 400 blocks: 88k L2 misses
(5.5 MiB), 112k L3 fills (7.0 MiB) and ~450 DRAM fills per PAL block, 36 M instructions. At 50.5
blocks per PAL frame that is ~350 MiB/frame — **about a quarter of the decode's 1.29 GB/frame of
L2-miss traffic**. The other three quarters are field-level: the whole-field chroma-DG transforms,
`concatenate_blocks`, the `keep_demod` transport copy, the record-array extraction, the two
resamples, dropout detection and EFM, each a pass over 2–20 MB arrays.

The chroma DG correction alone, `--no_chroma_dg` against the default on the same 80 frames, one
serial decoder on an idle box:

| PAL, `-t 1`, per frame | fps | cycles | L2 misses | fills from L3 | fills from DRAM |
|---|---:|---:|---:|---:|---:|
| CVBS | 3.29 | 2.21e9 | 1.38e7 | 1.52e7 | 6.26e6 (382 MiB) |
| CVBS, no DG | 3.56 | 2.03e9 | 1.20e7 | 1.32e7 | 4.76e6 (290 MiB) |
| `--tbc` | 3.53 | 2.01e9 | 1.38e7 | 1.52e7 | 4.90e6 (299 MiB) |
| `--tbc`, no DG | 3.90 | 1.88e9 | 1.20e7 | 1.31e7 | 4.28e6 (261 MiB) |

The padded transforms cost 8% of a serial decode's cycles but **a quarter of its DRAM fills**
(1.5e6 per frame on CVBS): four 2.8 MB transforms per field, each several radix passes over an
array no cache keeps, are exactly the kind of stream §2.1 says the box has 20 GB/s for. That is
why the correction doubles in cost under `-t 6` (§2.3) and why Phase 3 Task 1 replaces it with a
pass that never leaves L1d.

Under eight-way contention every one of those passes goes to DRAM (§5.1: DRAM fills per frame
5.1e6 → 2.3e7, 1.43 GB), and 8 × 1.21 fps × 1.43 GB ≈ 14 GB/s of reads plus writebacks is the
20 GB/s ceiling of §2.1. **That is the N-serial plateau at 7.9–8.5 fps**, and it moves only with
bytes streamed per frame.

### 2.3 The parent process is the `-t N` ceiling

Per-thread busy fraction of the parent and its workers, sampled from `/proc` over the second half of
a 300-frame run, Phase 2 tree:

| cell | fps | worker duty each | workers Σ | parent Σ | busiest parent thread |
|---|---:|---:|---:|---:|---:|
| PAL CVBS `-t 4` | 6.35 | 72% | 2.9 cores | 1.84 | 68% |
| PAL CVBS `-t 6` | 6.37 | 45% | 2.7 | 1.84 | 67% |
| PAL CVBS `-t 8` | 6.42 | 35% | 2.8 | 1.84 | 69% |
| PAL `--tbc` `-t 4` | 7.20 | **95%** | 3.8 | 1.03 | 42% |
| PAL `--tbc` `-t 8` | 6.02 | 92% | 7.4 | 1.68 | 56% |
| NTSC CVBS `-t 4` | 10.59 | 94% | 3.8 | 0.80 | 37% |
| NTSC CVBS `-t 8` | 9.69 | 90% | 7.2 | 1.39 | 56% |

Two different shapes:

- **PAL CVBS is parent-bound.** Throughput and the parent's load are identical at `-t 4/6/8`; the
  workers' aggregate is pinned at 2.8 cores and their duty just dilutes. `py-spy` on the parent at
  `-t 6` (400 frames) puts the two output-stage threads at **105 ms + 70 ms of CPU per frame**:

  | thread | ms/frame | of which |
  |---|---:|---|
  | `ld-output` | 105 | `_correct_chroma_vs_luma` 42, `efm_demod.process` 28, `downscale_cvbs` 23, encode 3 |
  | `cvbs-resample_0` | 70 | `_correct_chroma_vs_luma` 41, `downscale_cvbs` 25 |
  | `Thread-2 (_reader_loop)` (FLAC) | 55 | PyAV decode 28, `bytearray.extend` copies 25 |
  | main thread | 29 | inline `demodblock` 7.5, `measure_vits_multiburst` 6 |
  | `Thread-3` (pool result unpickling) | 27 | `multiprocessing.connection.recv` |

  NTSC CVBS at `-t 6` under the same sampler: `_reader_loop` 56 ms/frame, `ld-output` 51
  (`efm_demod.process` 33.5, `encode_cvbs_frame` 9), main thread 29 (`demodblock` 7, VITS 5.5),
  unpickling 10, dispatcher reads 9, job pickling 7 — 1.4 cores of parent at 9.3 fps, so the
  reader alone binds NTSC at ~18 fps and the output lane at ~20.

  The two output threads sum to 175 ms/frame ≈ 1/6.2 fps: they share one GIL and one L3 and behave
  as one core. The GIL itself is held 56% of the time (`py-spy --gil`), so it is not saturated; the
  work is. **Chroma DG is still 83 ms of a 160 ms PAL CVBS frame** — the field transforms are
  cheap in isolation (9 ms per field) but not with six workers streaming through the same L3.
- **PAL `--tbc` and NTSC are worker-bound at `-t 4` and contention-bound past it.** Four workers
  run at 94–95% each; eight workers at 90–92% each produce *less*. Cores are available (16 SMT
  threads) — each field just costs more once eight FFT-bound processes share eight FPUs and one
  DRAM path. The `--tbc` parent is at 1.0 cores at 7.2 fps, of which the FLAC reader is 0.41 and
  the EFM demodulator 0.25: the reader alone caps `--tbc` at ~15 fps, the EFM lane at ~22 fps.

  How much a worker's field costs under contention is the number that sizes ceiling B. Serially
  (`-t 1`, PAL CVBS, `py-spy`, 400 frames) the stages a worker runs cost about 200 ms per frame:

  | main thread, `-t 1` | ms/frame | | ms/frame |
  |---|---:|---|---:|
  | `demodblock` | 120 | `dropout_detect_demod` | 9 |
  | `downscale` (TBC picture) | 15.5 | `concatenate_blocks` | 7 |
  | `computewow_scaled` | 15.5 | burst / pilot / hsync refinement | 12 |
  | audio phase 2, VITS, pulses | 10 | *(parent-side, not worker: DG 40, `downscale_cvbs` 33, EFM 21)* | |

  At `-t 4` (`--tbc`) four workers at 95% deliver 7.2 fps: **528 ms of worker CPU per frame, 2.5×
  the serial cost of the same stages.** The same factor appears in §5.1's counters for one
  decoder among eight (cycles per frame 2.25e9 → 5.6e9 at the same instruction count). Four
  independent serial decoders pay only 1.56× (8.48 fps against 4 × 3.30), so a `-t 4` process
  contends with itself harder than four separate processes do: its parent adds ~1.8 cores of
  streaming (DG, resample, FLAC) and the field transport pickles 4 MB per field each way. Halving
  that factor is worth more than any other single item in this document.

### 2.4 What the LUT result now means

The 4 MiB table's misses were L3 hits and independent across output samples, so the out-of-order
window hid them; removing them removed no stall. Nothing about the small table is wrong — both
kernels now resample identically and more accurately, 4 MiB per process is not allocated — but as
a throughput measure it is a 1–3% loss and it stays only on the balance the user set. The lesson
is general: **a change that removes cache lines pays only if those lines were on a stalled path**,
which the counters can say before the change is made (fills from DRAM, not footprint).

### 2.5 The chroma DG correction is PAL-only, by decision

Every NTSC measurement in this document ran without a chroma DG correction, and it is worth
being exact about why, because the first reading of the code was wrong. The correction's servo,
`checkChromaDG`, measures the modulated staircase of the PAL insertion test signal only —
`measure_vits_dg_staircase` returns `None` for any field whose system is not PAL
(`decoder.py:170`) — so on NTSC the estimate never leaves 0.0 and neither output mode applies
anything. The routing observation (the CVBS writer only applies the correction on PAL's resample
path, `field.py:2071`, and the TBC-picture correction is skipped whenever a CVBS writer exists,
`decoder.py:2167-2171`) is true but moot while there is no NTSC estimate.

Decision recorded (owner, 2026-09-04): **the correction stays PAL-only**; an NTSC measurement is
not in scope. The rule that *is* in force, and that Phase 3 must preserve, is that the correction
is applied exactly once, on the path being written: in CVBS mode the workers do not correct the
TBC picture (`_engine_chroma_dg` returns `None`) and the commit path does not either — only the
4fsc resample is corrected, inside `downscale_cvbs`; in `--tbc` mode only the TBC picture is. The
two outputs are either/or, never both. (Should NTSC ever be wanted, the NTC-7 composite line's
modulated staircase — first fields, five pedestals — is what `analysis/differential_phase.py`
already reads, and the reference's end-to-end NTSC figures are 3.4% gain and 3.1° phase.)

## 3. Three ceilings, one order

| | Ceiling | Binds | Lever | Phase |
|---|---|---|---|---|
| A | parent per-frame work: 175 ms output stage, 55 ms reader, 27 ms unpickle, 29 ms main | PAL CVBS at any `-t`; every mode above ~12–15 fps | move work out of the parent or make it an order of magnitude cheaper | 3, 5 |
| B | per-field worker cost under contention | PAL `--tbc`, NTSC past `-t 4` | fewer bytes streamed and cycles per field in the worker | 4 |
| C | 20 GB/s DRAM, ~1.3–3 GB streamed per PAL frame | N independent decoders at N ≥ 4; `-t N` once A is lifted | bytes streamed per frame | 4 |

A is attacked first because it is the only thing between PAL CVBS and the `--tbc` curve, and
because everything in it is parent-resident CPU that the counters attribute to named functions. B
and C share a lever and are one phase. The concurrency architecture is not reopened until Phase 6
has re-measured with A and B/C moved.

**Phase 3 priced B, and the price changes the strategy.** Moving one field's 4fsc resample into the
workers cost the pool about three times what the same work costs in the parent (§5 Task 3), and
giving one parent thread's work a thread of its own made every other parent thread ~30% more
expensive (§5 Task 2). Work is not movable between these ceilings at par: the only changes that
have paid are the ones that **delete** work (§1's MTF hold, §1's transform length, §5's corrector).
Phase 4's traffic items are of that kind; the "give it its own thread / its own process" kind is
answered, and needs a new measurement before it is tried again.

## 4. Rules

As the working-set plan §2: harness rows for every claim, on the same captures and spans; byte
changes re-record in their own commit after `conformance-*-vits` passes within bands with no
widening of `vits_known_deviations.toml`; `-t 1` / `-t N` identity holds throughout
(`compare-*-parallel-*`); names describe the decoder, not the phase. Two additions from this
re-examination:

- **Count fills, not bytes.** A task that claims a memory effect states the DRAM fills per frame
  it removes (`ls_any_fills_from_sys.mem_io_local`, solo and among eight) before it is implemented,
  and the harness row afterwards. Resident size is reported but never argued from.
- **Measure one thing at a time.** Counter and utilisation runs are made on an otherwise idle box;
  a row taken while another cell was running is discarded, not corrected.
- **Compare interleaved, and plain.** Back to back the same cell repeats to ±0.3% (7.20, 7.22,
  7.24 fps), but the same tree measured an hour apart in a long session drifts by 5%, and the
  `/proc` sampling wrapper costs more at higher `-t` than at lower. So a before/after claim runs
  both trees alternately in one script, without the wrapper (the wrapper's rows are for
  attribution, never for a delta), and a difference under ~5% taken any other way is not a
  difference. Phase 3 nearly recorded two wrong verdicts on rows that were compared across
  sessions.

## 5. Phase 3 — take the output stage off the critical path

Ceiling A for PAL CVBS. Target: PAL CVBS within 10% of PAL `--tbc` at the same `-t`, and the
parent's output threads under 40% busy at `-t 6`.

**Outcome: one task of the three paid, and the other two priced the ceilings.** Task 1 (the chroma
DG corrector, single precision and one pass) is in: PAL +10–19%, NTSC +2%, and it brought PAL CVBS
to within 10% of `--tbc` at `-t 6` on its own. Tasks 2 and 3 were built, measured and reverted:
neither redistributing the output thread's work inside the parent nor pushing it into the workers
raises throughput, and both cost more total CPU than they save. The phase's second target is
retired with a reason (Task 4).

**Task 1 — the chroma DG corrector at a third of its cost. Done.**

*The time-domain premise this task was written on is wrong, and was dropped.* The two windows'
transitions are 0.3 and 0.4 MHz against a 17.73 MHz lattice — two percent of the sample rate — and
a raised-cosine amplitude taper's impulse response decays slowly, so the "few dozen taps" the task
assumed is out by an order of magnitude. Holding every truncated tap below 1e-4 of the peak takes
437 taps for the luminance low-pass and 491 for the subcarrier prototype (below 1e-5: 897 and
1087). Over a 355k-sample field that is ~140 M multiply-adds even with the 4fsc identity splitting
the bandpass and its quadrature across even and odd taps, tens of milliseconds a field against the
21.6 ms the transform corrector already took. Decimating the luminance path by four still leaves
19 M. A time-domain corrector is not the cheaper form at these transition widths, and the FIR
design was abandoned rather than built.

*Where the cost actually was.* Timed solo on a PAL field, the old corrector took 21.6 ms (gain
only) and 27.2 ms (gain and phase), of which the three transforms were 7.4 ms. The rest was
double-precision elementwise numpy over 355k-sample arrays: the gain divide alone 2.0 ms, the
analytic signal's complex inverse transform 5.9 ms, and eight whole-field temporaries streamed
through DRAM for one field's arithmetic. The filter design was never the cost; the width and the
temporaries were.

*What was done instead* — three changes, none of them to the filters or to what they compute:

- **Single precision through the filtering** (`_chroma_dg_bands`, `field.py`). The transforms are
  half the width and roughly twice the rate. What comes out is only ever multiplied by `(G - 1)`,
  of order a tenth, before it is added back to the composite in double precision, so the correction
  term carries the single-precision error and the composite does not.
- **The analytic chroma as a band and its quadrature** (`select_band`, `dsp.py`): multiplying a
  half spectrum by `-1j` is the Hilbert transform's `-1j*sgn(f)`, so a second *real* inverse
  transform returns the quadrature component, replacing the complex transform across the doubled
  full-length spectrum. The windowing touches only the bins a window can be non-zero over (a sixth
  of the spectrum for the low-pass, a third for the bandpass) and writes into a zeroed buffer.
- **One elementwise pass per field** (`equalise_chroma_gain`, `equalise_chroma_gain_phase`,
  `dsp.py`, `njit(nogil=True)`): the clip, the gain, the rotation and the combination in a single
  loop with no temporaries. The rotation's cosine and sine stay in numpy, which evaluates them in
  SIMD; the same two calls inside the loop cost 5.1 ms a field through libm, as this build of numba
  has no SVML.

*Measured.* Per field, solo and warm: 21.6 → **6.1 ms** gain-only, 27.2 → **8.9 ms** with phase.
Contended at `-t 6` (py-spy, PAL CVBS, both fields' corrections summed): 42.9 → **16.3 ms** per
field. The 3 ms target was not reached and cannot be by this route: 5.6 ms of the 6.1 is the three
transforms themselves.

| cell | before | after | |
|---|---:|---:|---|
| PAL CVBS `-t 4` | 6.38, 6.47 fps | 7.19, 7.23 fps | +12% |
| PAL CVBS `-t 6` | 6.43 fps | 7.07 fps | +10% |
| PAL `--tbc` `-t 4` | 7.41 fps | 8.32 fps | +12% |
| PAL `--tbc` `-t 6` | 6.62 fps | 7.90 fps | +19% |
| NTSC CVBS `-t 4` | 10.65 fps | 10.83 fps | +2% |

(Interleaved A/B, this tree against the same tree with `field.py` and `dsp.py` at HEAD,
alternating cells so the session's own drift cannot land on one side — see §4.)

`--tbc` gains as much as CVBS does even though its correction runs in the workers, which is
ceiling B: the workers are the contended resource, and a correction three times cheaper is worker
capacity returned. Per-thread at `-t 6` under py-spy (ms/frame): `ld-output` 105.1 → 79.2, of which
the correction 43.4 → 17.2; `cvbs-resample_0` 70.1 → 43.2, of which the correction 42.3 → 15.4. In
`--tbc` mode the output pool's re-correction of stale fields fell from 18.3 to 4.0 ms/frame across
its two threads.

*Against the acceptance criteria.* The hermetic comparison against the double-precision transform
corrector is `test_the_corrector_matches_the_double_precision_transform` on the modulated staircase
field, whole field and first and last lines separately: largest deviation 5.9e-5 IRE on the
gain-and-phase path and 5.3e-6 on the gain-only path, against a stated tolerance of 1e-3 IRE — half
the 0.0021 IRE the 16-bit TBC output quantises to, so neither the padding nor the working precision
can move an output sample by an LSB without the test failing first. The plan's 0.01 IRE rms figure
is carried as a second assertion and is three orders above what is measured. The written-path rule
of §2.5 gained its test at the dispatch end
(`test_cvbs_output_does_not_send_the_correction_to_the_field_jobs`): with the CVBS writer on, field
jobs are told no chroma DG at all, so a worker leaves the TBC picture uncorrected and the
correction happens once, on the lattice being written. The commit end already had
`test_cvbs_output_leaves_the_picture_to_the_writer`. Unit suite 1719 passed, 3 skipped; the full
CTest suite passed 96/96, including the VITS radius sweep (`conformance-*-vits` on twelve cuts) and
the `-t 1` / `-t N` byte comparisons for `.tbc`, `.cvbs`, `.pcm`, `.efm` and the metadata.

*What this leaves.* `ld-output` is still the busiest parent thread at `-t 6` (51% of a core, 79
ms/frame), so the task's second target — output threads under 40% — stands open. Its composition is
now the 4fsc resample (Task 3) and the EFM demodulator (Task 2), with the correction third.

**Task 2 — the EFM demodulator on its own lane. Built, measured, reverted.**

`efm_demod.process` is 28 ms/frame on the output thread and runs without the GIL, so it was given
its own ordered lane (`OrderedOutputLane(name="ld-efm")` plus a `submit_result` that hands the
write a Future for the T-values), fed from the same commit sequence. It is correct — serial and
parallel `.efm` bytes stayed identical, `compare-{ntsc,pal,jason-pll}-parallel-efm` all pass — and
it does what it was meant to do: `ld-output` fell from 79.2 to 68.5 ms/frame and the demodulation
moved to a thread of its own.

It buys nothing, because **the parent is already thread-saturated: the new thread made every other
thread in the process about 30% more expensive.** Per-thread, PAL CVBS `-t 6` (ms/frame, before →
after the lane): the correction on `ld-output` 17.2 → 23.6, `cvbs-resample_0` 43.2 → 56.6, the
demodulation itself 28.2 → 36.0, the pool's result reader 25.3 → 34.5. Parent CPU rose from 176% of
a core to 209% — 55 ms/frame of extra parent work to move 28 ms off one thread. Throughput did not
move with it: every cell measured (PAL CVBS `-t 4`/`-t 6`, PAL `--tbc` `-t 4`/`-t 6`, NTSC CVBS
`-t 4`) landed within a few percent of where it started, which is inside this harness's own
session-to-session spread (§4) — the CPU figures, taken in the same run, are what the verdict
rests on.

The change was reverted (the diff is kept at
`docs-planning/decode-throughput-replan/phase3/efm-lane.diff`). **The lesson is the same shape as
Task 1's: redistributing parent work does not raise ceiling A, only removing it does.** Every
remaining idea of the "give it its own thread" kind is answered by this measurement and should not
be tried again without a reason to think the contention is different; Task 3, which moves work out
of the parent process entirely, is the form that can win.

**Task 3 — the PAL 4fsc resample in the workers. Built, measured, reverted.**

Built as the task describes: the dispatcher stamps each job with the burst-lock shift and the
chroma DG estimate (`FieldJobEngine.set_cvbs_resample`, fed by a listener the writer calls each
frame), the worker resamples both of its field's lattices under that shift and rides the result
with the key it was made under (`Field.cvbs_resample_key`: shift, estimate, and the three AGC
levels `hz_to_output` reads), and the writer either writes what it was sent or resamples the field
itself (`Field.cvbs_resample`, counted and logged). Correct: `compare-pal-cvbs-parallel-cvbs`,
which decodes with `--exact-speculation` and compares bytes against the serial decode, passes —
with a zero tolerance every shipped resample is either exactly current or redone here, which is
what "proves the mechanism" meant.

*The burst lock is chasing measurement noise, which the speculation exposed.* At the tolerance the
task asked for — below the burst measurement's own noise — **99.5% of shipped resamples were
redone**. The reason is in the lock itself: over 120 frames of the reference PAL capture the
residual has a mean of 0.01 degrees and a standard deviation of 1.65, and the shift's movement over
eight frames (0.019 samples rms) is the same as over one (0.018) — a bounded random walk, not a
drift. Applying the whole of each frame's residual writes the previous frame's measurement noise
into the next frame's lattice. Four discs from the radius set say the same: per-frame residual
standard deviations of 0.5 to 2.3 degrees, mean movement per frame of 0.0003 lattice samples or
less. Damping the loop to a quarter of the residual (`PAL_LOCK_GAIN`) cut the residual spread on
every one of them (0.80 → 0.63, 1.10 → 0.88, 0.50 → 0.38, 2.27 → 1.62 degrees) and shrank the
four-frame movement to 0.002–0.005 samples, at which point a tolerance of 0.02 samples (1.8 degrees
of subcarrier, at or below the measurement noise on every disc) brought the redo rate down to
18% at `-t 4` and 28% at `-t 6`.

*It still does not pay, and the reason is worth more than the change.* With the resample in the
workers the parent shed what it was meant to shed — parent CPU 178% of a core → 123% at `-t 4`,
180% → 134% at `-t 6` — but the workers gained far more than the parent lost: 333% → 371% at `-t 4`
and **333% → 511% at `-t 6`**, an extra 178% of a core for a resample that costs 85 ms/frame when
the parent does it. Throughput did not improve at any thread count (and `-t 6` was, if anything,
slightly worse). **A millisecond of work costs about three times as much in a contended worker as
it does in the parent** — ceiling B, priced. Moving work from the parent into the workers is not a
free rebalance; it is a purchase at 3x.

The change was reverted (the diff is kept at
`docs-planning/decode-throughput-replan/phase3/cvbs-worker-resample.diff`, the lock residual series
beside it). Two things come out of it that outlive it:

- **The PAL burst lock is damped, as its own change** (`PAL_LOCK_GAIN`, §5.1 below). It is a
  quality change, not a throughput one: it lowers the residual's rms on nine of the ten PAL radius
  cuts and on the 300-frame reference capture, and it costs nothing anywhere else.
- **The 4 MB `keep_demod` transport stays**, because the parent must be able to resample. Removing
  it needs the resample to be reproducible in the parent from something smaller than the demod
  (a fractional-sample delay of the already-resampled field is the obvious candidate, at about a
  fortieth of the cost), which is a Phase 4 traffic question, not this one.

**Task 4 — measure. Done, and it moved the phase's target.**

Where PAL CVBS stands after Task 1, against `--tbc` at the same thread count (interleaved A/B,
plain runs): `-t 4` 7.2 against 8.3, `-t 6` 7.1 against 7.9 — **10% apart at `-t 6`, which is the
phase's target met**, and 13% at `-t 4`. The second target, output threads under 40% busy at
`-t 6`, is not met and is no longer the right target: `ld-output` is 51% of a core, and Tasks 2 and
3 between them show that neither splitting that thread's work across more parent threads nor
pushing it into the workers raises throughput. Nothing in the parent is saturated at `-t 6` —
`ld-output` 51%, the reader thread 36%, the resample thread 28%, the main thread 19%, and the
workers 48% — which is the signature of a **latency** limit rather than a resource one: fields are
delivered in chain order, so the commit loop advances at the pace of the slowest job in the
sequence, and every millisecond added to a worker's field job is paid on that path.

Per-thread at `-t 6` after Task 1 (ms/frame, py-spy): `ld-output` 79.2 (the 4fsc resample 42.1, the
EFM demodulation 28.2, the correction 17.2 inside the resample), the FLAC reader 55.0,
`cvbs-resample_0` 43.2 (the correction 15.4), the main thread 27.1, the pool result reader 25.3.
The busiest thread is still `ld-output`, and its largest single item is now the resample.

### 5.1 The PAL burst lock's loop gain

Phase 3 Task 3 found this and did not need it; it is the one output change the phase made.

The writer's PAL lock resamples each frame under a shift, measures the burst-versus-lattice phase
of the field it just wrote, and moved the shift by the whole of that measurement. But the
measurement carries noise, and on most discs the noise is all there is: across the ten PAL radius
cuts the per-frame residual has a mean of hundredths of a degree against an rms of 0.5 to 3
degrees, and the shift's movement over eight frames is no larger than over one. Applying all of a
noisy measurement writes the previous frame's noise into the next frame's lattice. For a loop
applying a fraction `g` of a measurement whose noise is `sigma`, the written phase error settles at
`sigma*sqrt(g/(2-g))` and the residual read back at `sigma*sqrt(2/(2-g))`; the measured figures
follow that to within a few hundredths of a degree.

| residual rms, deg | g = 1 | g = 0.75 | g = 0.5 | g = 0.25 |
|---|---:|---:|---:|---:|
| ggv1011-side1 inner / middle / outer | 0.79 / 0.64 / 0.48 | 0.73 / 0.57 / 0.47 | 0.67 / 0.52 / 0.50 | 0.62 / 0.49 / **0.70** |
| domesday-ds2-community-north in / mid / out | 3.08 / 1.10 / 2.30 | 2.87 / 1.00 / 2.16 | 2.65 / 0.94 / 2.00 | 2.59 / 0.90 / 1.86 |
| domesday-ds1-community-north-outer | 2.23 | 2.06 | 1.81 | 1.62 |
| industrial-lv-side1 in / mid / out | 0.64 / 0.55 / 0.49 | 0.57 / 0.49 / 0.44 | 0.53 / 0.45 / 0.40 | 0.51 / 0.41 / 0.38 |
| reference PAL capture, 300 frames | 1.65 (max 4.65) | 1.48 (max 4.15) | 1.36 (max 3.76) | — |

**`g = 0.75` shipped**: every cut improves, by 8–11%, and the reference capture by 10% in rms and
11% in its worst frame. Nothing else in the corpus moves — CTest 96/96, no `signal_state_preset`
verdict changed (the three cuts that read `UNLOCKED` still do, on worst frames of 5–7 degrees
against a 3 degree tolerance), and `vits_known_deviations.toml` is untouched.

Two things stop the gain going lower, and **neither of them is the noise**:

- **A disc whose time base really moves.** The standing error on a ramp of `r` samples a frame is
  `90*r/g` degrees. Nine cuts have `r < 0.0003`; `ggv1011-side1-outer` has `r = 0.002`, and at
  `g = 0.25` that costs it half a degree — the one cell in the table that goes the wrong way.
  Following a ramp without that penalty needs a rate term (a type-2 loop), not a smaller gain.
- **The VITS 2T pulse measurement is knife-edge in sampling phase.** A 2T pulse is three and a half
  samples wide at 4fsc, so its sampled crest moves several IRE with where the lattice sits, and
  `analysis/vits_measure.py` takes the crest by `argmax` plus a parabolic interpolation, which does
  not recover that. Below about `g = 0.6` the lattice settles where the crest of
  `domesday-ds1-community-north-outer`'s averaged first fields falls between two samples: its
  reading steps from 90.60 to 86.51 IRE and `conformance-domesday-ds1-community-north-outer-vits`
  fails against the ceiling recorded for its known deviation. The reading is bimodal, not drifting
  — 90.60 at `g` = 1, 0.9 and 0.75, 86.51 at 0.5 and 0.25 — and the decode underneath is better,
  not worse (that cut's residual falls from 2.23 to 1.81 degrees, and its single-field second-field
  2T reading is unchanged at 93.30). So the ceiling was not widened and `g = 0.5` was not taken.

The 2T pulse and the reference it is judged against are already owned by
`docs-planning/vits-conformance-testing-plan.md` Phase 8 task 5. Once that measurement reads a
narrow pulse's crest independently of sampling phase, `g = 0.5` is worth another 8% and this
constant should be revisited; a rate term would be worth more again.

## 6. Phase 4 — bytes streamed per field

Ceilings B and C. Target: DRAM fills per PAL frame among eight decoders down by a third
(2.3e7 → ≤ 1.5e7), and the N-serial knee moved from N ≈ 4 to N ≥ 6.

**Task 1 — the traffic inventory.** Extend `scripts/report_working_set.py` (or add a sibling) to
report, per stage of one field's decode, bytes streamed: for each numpy/scipy pass the array sizes
in and out, and for the numba kernels the arrays read. Cross-check the sum against `perf stat`'s
L2-miss bytes for one serial frame (1.29 GB today).
Alongside the bytes, attribute the 2.5× of §2.3 by stage: `py-spy --subprocesses` on the workers
at `-t 1` (one worker) and `-t 4`, per-stage ms per field side by side, so the phase knows which
stages inflate under contention (the transforms, the copies, or the numba kernels) before it
chooses among Tasks 3–6.
*Acceptance:* a table by stage that accounts for ≥ 80% of the measured L2-miss traffic; the top
five stages named with their bytes per frame; the per-stage contention factor at `-t 4` stated.

**Task 2 — the block length: measured, no effect.** Every full-blocklen `complex128` array is
512 KiB, exactly one L2, which made a shorter block the obvious way to keep the per-block chain in
private cache; the cost is overlap (`blockcut` is 1056 samples regardless: usable samples 96.8% →
93.6% at 16384 → 87.1% at 8192). Measured on the harness, `-l 300`, one cell at a time:

| block length | PAL CVBS `-t 1` | PAL CVBS `-t 4` | PAL CVBS N=4 (Σ) | NTSC CVBS `-t 1` | NTSC CVBS `-t 4` |
|---|---:|---:|---:|---:|---:|
| 32768 (today) | 3.23 | 6.58 | 8.75 | 4.80 | 11.03 |
| 16384 | 3.21 | 6.23 | 8.84 | 4.74 | 11.05 |
| 8192 | 3.31 | 6.21 | 8.76 | 4.73 | 10.97 |

Every cell is within the harness's spread of the current length, including N=4 where L3 sharing
is at its worst. At 8192 the block does 12% more work for the same throughput, so the per-sample
cost of an L2-resident chain *is* lower — by exactly the overlap it costs. This is the block-side
counterpart of the LUT result: the per-block chain is not where the stalls are. **Decision: the
block length stays at 32768**, and nothing in this phase targets the block's cache residency.

**Task 3 — one multiply where there are three.** `indata_fft_filt` is formed by up to three
successive full-spectrum multiplies (`RFVideo`, `FcutPAL`, the held MTF response). Hold the product
per adopted MTF level instead — the same cache Phase 1 built for the MTF response — so the block
does one multiply. Likewise fold the rfft mirroring: consumers that only need the half spectrum
(`rfhpf` already does) should read `half`, and the full-spectrum copy be made once for those that
need it.
This is a cycles saving (two full-spectrum multiplies per block, ~0.05 ms) more than a traffic one,
given Task 2's result; take it if Task 1's inventory still lists the block among the top streams,
otherwise leave it.
*Acceptance:* the block microbenchmark's L2 misses per block stated before and after; output bytes
identical where the arithmetic is only reordered by a held product (check, since floating-point
association changes bytes — if not identical, conformance gates and the re-record is separate).

**Task 4 — the narrower pipeline, justified as traffic.** The working-set plan's Phase 3 is kept in
one form only: carry the block spectrum and video products in `complex64`/`float32` from the input
transform onward, and measure it *among eight* and at `-t 6`, where the FFTs are DRAM-bound and
halving their bytes is what matters (solo, scipy's single-precision transform is slower and the
change loses). The "narrow the filters only" variant is dropped: it halves bytes the counters say
are not the stalled ones.
*Acceptance:* DRAM fills per frame among eight, before and after; harness rows N=8 and `-t 6`;
conformance within bands, with the servo-trajectory identity check of the working-set plan (Phase
5 Task 2's instrument) run on the radius set; a stated go/no-go.

**Task 5 — the copies.** §2.2's DRAM attribution is 54% copies and casts. Candidates, each to be
priced by Task 1 before touching: the record-array extraction (`_aligned_strided_to_contig_size4`
— storing video products as a `float32` recarray and then pulling channels out), `concatenate_blocks`,
the FLAC reader's `bytes(rf.planes[0])` → `bytearray.extend` → `np.frombuffer` → cast chain (three
copies of every input sample), the `keep_demod` transport (gone with Phase 3 Task 3).
*Acceptance:* per candidate, bytes per frame removed and the harness row; identity or conformance
as the change dictates.

**Task 6 — half-rate video, if Task 1 points at it.** The working-set plan's Phase 6 survives only
as a traffic argument: if Task 1's inventory shows the 40 MSPS video products and the passes over
them are still a top-five stream after Tasks 2–5, run that plan's Task 1 prototype and precision
measurement unchanged. Otherwise it is not done.
*Acceptance:* as written there; or a recorded decision not to proceed, with Task 1's figures.

**Task 7 — measure.** The full grid, the N-serial curve, the counters solo and among eight.
*Acceptance:* both knees restated beside §2.3's and the working-set plan's; DRAM fills per frame
among eight restated.

## 7. Phase 5 — the parent's remaining per-frame work

Only after Phases 3 and 4, and only if Phase 4 Task 7 shows `-t N` flattening below the worker
knee. The candidates are known from §2.3, in order of size at `-t 6`:

- **The FLAC reader** (55–70 ms/frame in the parent, holding the GIL for ~a third of it): decode in
  a subprocess writing to shared memory, or hand PyAV a preallocated plane so the `bytes()` and
  `extend` copies go; either way the reader stops being a GIL client of the parent.
- **Result unpickling** (27 ms/frame): ship the worker's field through shared memory rather than a
  pickle over a pipe; the `prepare_transport` payload is already contiguous arrays.
- **VITS measurement on the main thread** (`measure_vits_multiburst`, 6–10 ms/frame): the
  measurements are already made in the worker for the servos; the main-thread call is the
  calibrate-time repeat and can read the worker's figures.
- **Inline `demodblock` on the main thread** (7.5 ms/frame at `-t 6`): rejected speculations and
  the input tail; state the rejection rate before deciding.

*Acceptance:* for each item taken, the parent's per-thread ms/frame before and after, and the
harness row.

## 8. Phase 6 — take stock: is the concurrency architecture the limit?

No decoder changes. Re-run the `-t` sweep, the N-serial curve and the utilisation table. If `-t N`
now scales to the physical core count, close; re-derive the `-t` auto default from the new knee
(working-set plan Phase 4 Task 3, unchanged). If it flattens below it for a reason visible in the
parent, reopen the concurrency design with the batch-parallel plan's §3.6 as input — on the traffic
figures, not a footprint. If it flattens at ceiling C, the remaining lever is bytes per frame in
the demodulator itself, and that is a separate plan.

## 9. Superseded

In [`plans/decode-working-set-plan.md`](decode-working-set-plan.md): Phase 3 (filter dtype) is
replaced by §6 Task 4 here, in its pipeline form only; Phase 4's take-stock is this document;
Phase 5 Task 1 (one resampler) is kept as a simplification with no throughput claim; Phase 5 Task 2
(the discarded PAL TBC picture) is folded into §5 Task 3; Phase 6 (half-rate video) is §6 Task 6,
conditional; Phase 7 is §8.

## 10. Risks and open questions

- **The FIR corrector is not the transform corrector.** A short FIR has a transition band the
  raised-cosine windows do not; the DG/DP conformance figures are the arbiter, and the unit test's
  tolerance is stated, not tuned.
- **The burst-lock shift as a speculation key.** If a disc's lock wanders faster than the
  tolerance, every frame re-resamples in the parent and PAL CVBS is back where it is now — the
  re-resample rate is logged so this is visible, not silent.
- **Single-precision transforms.** scipy's `complex64` FFT is slower per element on this box; Task
  4 of Phase 4 is a measured go/no-go, not a plan to land it.
- **Block length and the filters.** Every frequency-domain filter is sampled at `blocklen`; at
  8192 the resolution is 4.9 kHz per bin against 1.2 kHz today, and the emphasis IIRs and the
  notches are the responses most sensitive to that. Conformance gates it, and 16384 is the safer
  step.
- **The box.** As before: one 5800X, one L3 size, one DRAM speed. The knees are stated, not assumed
  to transfer.
