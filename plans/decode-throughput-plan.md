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

**Superseded in part by Phase 4 Task 1 (§6).** The split above is a `perf record` symbol
attribution plus an estimate of what is field-level; measured per named stage *in situ*, it is the
other way round — the block chain is 81% of a PAL CVBS frame's L2-miss traffic and every
field-level pass together is under 19%. The block microbenchmark quoted here (350 MiB/frame)
prices the block's arithmetic rather than its traffic: across 400 back-to-back calls the filter
bank stays in L3, which it does not do inside a decode.

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

**Superseded by Phase 6 Task 4 (§8).** The bandwidth arithmetic no longer closes. Measured on the
Phase 5 tree, four independent decoders plateau at 12.0 fps while moving 7.6 GB/s of DRAM fills,
and eight move 11.9 GB/s for *less* throughput — so the plateau is reached at a third of the path's
capacity, not at it. What binds past the knee is that traffic per frame rises 3.8× from N = 1 to
N = 8 at constant instructions per frame: the added decoders manufacture fills rather than
converting cores into frames. Ceiling C is restated there.

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

  *This table is pre-Phase-3; §7 Task 1 re-measures it and §8 Task 3 re-takes the whole of it.* The two output threads are now 126.5
  ms/frame rather than 175, the FLAC reader 32.6 rather than 55, and the GIL is held 60% of a
  frame with no parent thread above 71% duty.
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

**The 2.5× is superseded by Phase 4 Task 1 (§6).** Counted from the whole process tree's
counters rather than inferred from duty cycles: the same instructions per frame (within 5%) cost
1.71× the cycles at `-t 4` on `--tbc` and 1.87× on CVBS, with DRAM fills 3.77× and 4.27×. The
conclusion's shape is unchanged and so is the lever; the factor is smaller than the duty-cycle
estimate, and the DRAM one is much larger.

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

**Ceiling C's statement in that table is superseded by §8 Task 4**: the plateau is not the 20 GB/s
path, which the tree reaches only half of at its knee, but the point past which an added decoder
raises DRAM traffic per frame faster than it converts cores into frames — N ≈ 4 on this box, set by
L3 capacity per concurrent hot set rather than by the bus.

B and C are now measured rather than estimated (§6 Task 1): at `-t 4` a PAL decode executes the
same instructions per frame as at `-t 1` for 1.7–1.9× the cycles and 3.8–4.3× the DRAM fills, and
81% of a frame's L2-miss traffic is inside the block demodulator, not the field-level passes §2.2
put it in.

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

**Phase 5 measured the two kinds against each other at the same size.** Its two implemented changes
each account for about the same parent milliseconds per frame — 24 for the reader's buffer, 7 for
the VITS measurements — and they went opposite ways: deleting the reader's copies paid **+7.4%** at
`-t 6`, and moving the VITS measurements from the parent's main thread into the workers cost
**−2.0%** at the same `-t` and was reverted (§7 Tasks 2 and 3). Both are bit-identical decodes, both
were measured interleaved on the same box in the same session. That is the rule's third and
cleanest data point, and it is why §7 Task 5 declines a transport rewrite whose prize is a few per
cent: the question to ask of a parent-side item is not how many milliseconds it is, but whether
those milliseconds stop being spent at all.

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

**Outcome.** The inventory the phase opens with (Task 1) moved its target. §2.2 had put three
quarters of a decode's traffic at field level and a quarter in the block demodulator; measured with
a per-stage counter instrument, it is the other way round — the block chain is **81%** of a PAL
CVBS frame's L2-miss traffic and the transforms alone are 56%. So the phase's two landed changes
are both in the block: the EFM output stopped being a complex transform whose imaginary half was
thrown away (Task 3), and the video products are filtered at the precision they have always been
*stored* at (Task 4). Both delete bytes rather than move them, which §3 says is the only kind of
change that has paid here. The copies (Task 5) and the block length (Task 2) are answered with
figures and not taken; half-rate video (Task 6) is deferred behind Task 7's numbers.

Measured end to end (Task 7): **PAL CVBS +7.4% at `-t 1` and +9.2% at `-t 6`, PAL `--tbc` +14.4% at
`-t 6`, NTSC CVBS +13.1% at `-t 6`**, with instructions per frame down 7% and DRAM fills among eight
decoders down 18%. The phase's stated target — a third off the fills among eight, and the N-serial
knee at N ≥ 6 — is **not** reached: the fills fell 18%, and eight decoders still deliver only 2.84×
one decoder. Ceiling C has moved up, not away. Conformance is 96/96 with no deviation widened.

**Task 1 — the traffic inventory. Done, and it moved the phase's target.**

The instrument is `scripts/report_decode_traffic.py`. It runs a serial decode in its own process
with a named set of stages wrapped by a counter-reading decorator: each wrapper reads a per-thread
`perf_event_open` group on entry and exit, so a stage is charged the traffic it caused *minus* the
traffic of the wrapped stages it called, and sums the `nbytes` of the arrays passed in and returned
alongside. Threads are attributed separately, and each thread's own counters over the counting
window are the denominator — so "how much of this thread has a stage name" is measured, not
asserted. Warm-up (filter construction, numba compilation, the first FFT plans) is discarded at a
stated field count, because at ten seconds it would otherwise dominate a short run.

*Cross-check.* The same decode uninstrumented under `perf stat`, differencing a 60-frame run
against a 20-frame one so setup cancels: 9.02e6 L2 misses, 1.472e9 cycles and 3.83e6 DRAM fills per
frame, against the instrument's 9.59e6, 1.525e9 and 4.03e6. The wrappers cost 6% of the L2 misses
and 3.6% of the cycles, and every figure below sits inside that.

*Where one PAL CVBS frame's traffic goes at `-t 1`* (per frame, exclusive, warm-up discarded;
`traffic_pal_cvbs.log`). By thread first, which is also the coverage statement:

| thread | Gcycles | L2 misses | L3 fills | DRAM MiB | has a stage name |
|---|---:|---:|---:|---:|---:|
| decode thread | 1.288 | 8.64e6 | 9.80e6 | 224.6 | 99% |
| `cvbs-resample_0` | 0.113 | 5.79e5 | 7.43e5 | 13.5 | 100% |
| FLAC reader | 0.125 | 3.80e5 | 3.13e5 | 7.8 | 0% |
| **whole process** | **1.525** | **9.59e6** | **1.09e7** | **245.9** | **95%** |

and then by stage, the top of a 46-row table:

| stage | thread | calls | ms | Gcycles | L2 misses | DRAM MiB | arrays in+out MiB |
|---|---|---:|---:|---:|---:|---:|---:|
| `fft.irfft` (rfhpf + the video stack) | decode | 120.9 | 43.9 | 0.161 | 2.63e6 | 10.0 | 154.6 |
| `fft.ifft` (hilbert + EFM + audio) | decode | 241.0 | 39.1 | 0.176 | 1.85e6 | 6.3 | 126.2 |
| `demodblock` itself (multiplies, mirror, clip, the record-array cast) | decode | 59.3 | 163.6 | 0.135 | 1.63e6 | 15.0 | 50.8 |
| `fft.rfft` (input + demod) | decode | 119.5 | 20.7 | 0.085 | 8.69e5 | 4.2 | 50.9 |
| the CVBS lattice resample, all of it | resample | — | 38 | 0.113 | 5.79e5 | 13.5 | — |
| `decodefield` itself | decode | 2.0 | 202.0 | 0.032 | 2.60e5 | 20.2 | 0 |
| `concatenate_blocks` | decode | 9.9 | 6.5 | 0.031 | 2.48e5 | 40.3 | 101.3 |
| `measure_vits_multiburst` | decode | 2.0 | 6.5 | 0.031 | 2.04e5 | 0.2 | 0 |

**The transforms are 56% of the frame's L2-miss traffic and the block chain 81%**, against §2.2's
estimate of a quarter. §2.2 was not wrong about the block *in isolation* — it measured the block
microbenchmark, where the filter bank stays in L3 across 400 back-to-back calls. In a decode it
does not, and the difference is the whole discrepancy. This is the same lesson as the LUT and the
block length, one level up: **a microbenchmark prices arithmetic, not traffic.**

*What contention does to it.* The counters for the whole process tree, steady state (a 140-frame
run minus a 40-frame one, so worker start-up cancels too):

| cell | fps | Gcycles | Ginstructions | IPC | L2 misses | DRAM fills |
|---|---:|---:|---:|---:|---:|---:|
| PAL CVBS `-t 1` | 3.43 | 1.472 | 4.509 | 3.06 | 9.02e6 | 3.83e6 (234 MiB) |
| PAL CVBS `-t 4` | 6.16 | 2.753 | 4.720 | 1.71 | 1.79e7 | 1.64e7 (1000 MiB) |
| PAL `--tbc` `-t 1` | 3.60 | 1.311 | 3.959 | 3.02 | 8.83e6 | 3.61e6 (221 MiB) |
| PAL `--tbc` `-t 4` | 7.16 | 2.246 | 4.173 | 1.86 | 1.64e7 | 1.36e7 (832 MiB) |

**The same work — instructions per frame agree to 5% — costs 1.7–1.9× the cycles and 3.8–4.3× the
DRAM fills at `-t 4`.** Solo, 41% of the L2 misses reach DRAM; at `-t 4`, 83% do. That is ceiling B
stated properly, and it says the lever is exactly what §3 claimed: bytes that reach DRAM. It also
retires §2.3's "2.5×", which was inferred from duty cycles rather than counted.

*Per stage, under contention* (`py-spy --subprocesses`, PAL `--tbc`, ms of CPU per frame; the four
worker processes at `-t 4` against the single process at `-t 1`). py-spy under-samples the `-t 4`
tree by about 15% — its total is 4.1 cores where the counters say ~5 — so the ratios are the
figure, not the absolute ms:

| stage | `-t 1` | `-t 4` workers | factor |
|---|---:|---:|---:|
| `demodblock`, inside the transforms | 73.2 | 105.4 | 1.44 |
| `demodblock`, its own arithmetic | 48.3 | 89.8 | 1.86 |
| `downscale` | 17.5 | 20.9 | 1.19 |
| `computewow_scaled` | 15.9 | 16.8 | 1.06 |
| `dropout_detect_demod` | 9.7 | 18.9 | 1.95 |
| `concatenate_blocks` | 7.3 | 14.2 | 1.95 |
| chroma DG transforms | 9.9 | 12.3 | 1.24 |
| `refine_linelocs_pilot` | 3.9 | 10.3 | 2.64 |
| `refine_linelocs_hsync` | 2.8 | 6.0 | 2.14 |

The stages that inflate most are the ones that stream a whole field once (`dropout_detect_demod`,
`concatenate_blocks`, the line refinements) rather than the ones that work block by block — a
block's chain still has some cache to work in when eight processes share the L3; a field-length
pass has none.

*One finding this instrument was not looking for.* Each `decodefield` reads
`readlen // blocksize + 2` blocks, so adjacent fields' windows overlap by two blocks and **15.4% of
all block demodulation is done twice** (measured directly: 1796 demodulations of 1519 distinct
blocks over 40 steady-state frames, `count_decodes.py`). At `-t 1` there is no block cache at all
(it is gated on `numthreads > 1`); at `-t N` each field job is a separate process, so the overlap
cannot be shared without shipping blocks between them. Recorded, not acted on: the fix costs a
transport and buys 15% of one stage.

*Acceptance:* met — 95% of the measured L2-miss traffic is named against a bar of 80%, the top five
stages are named with their bytes per frame, and the per-stage contention factors at `-t 4` are
stated above.

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

**Task 3 — one multiply where there are three. Split: one taken, one measured and declined.**

*Taken: the EFM output is one real transform, not one complex one.* `Fefm` is built one-sided —
both front ends fill only positive-frequency bins — so `ifft(indata_fft * Fefm)` is an analytic
signal of which `demodblock` keeps `.real` and discards the rest. For a spectrum with no
negative-frequency content that real part is exactly the inverse *real* transform of the positive
half with every bin but DC and Nyquist halved, and `computeefmhalffilter` folds the halving into
the filter once, at filter-build time. Per block, same counters, 200 reps on an idle box
(`bench_block.py`):

| the EFM output, per block | ms | L2 misses | L3 fills |
|---|---:|---:|---:|
| `ifft(full spectrum).real` — today | 0.314 | 9428 | 1.07e4 |
| **`irfft(folded half)`** | **0.166** | **8043** | **9586** |
| `irfft(folded half)`, multiplying only the 1477 non-zero bins | 0.172 | 8654 | 1.02e4 |

Narrowing the multiply to the filter's 1477 non-zero bins does *not* pay: the zeroed half-length
buffer it needs costs more than the multiply it saves. The plain fold does, and it is **the same
bytes out** — 2.6M samples across PAL and NTSC and both front ends (anchor and hardware) are
bit-identical, because the two transforms differ in the last ulp and the `int16` truncation is
thirty orders away from it. So this one lands without re-recording an EFM output.
`tests/unit/test_demod_fft.py` holds the two to `assert_array_equal`.

*Declined: holding the product of the video filters.* `indata_fft_filt` is formed by up to three
successive full-spectrum multiplies (RFVideo, the PAL audio-carrier notch when the carriers are
present, the held MTF response). Holding their product per adopted MTF level costs one multiply
instead of three: 0.064 ms → 0.025 ms and 1905 → 800 L2 misses per block, which is 2.3 ms/frame at
`-t 1`, about 0.75%. But `(X·A)·B·C` and `X·(A·B·C)` differ in the last ulp, so every video byte in
the corpus changes for it. **Not taken**: 0.75% does not buy a re-record. The figures are here so
the question does not have to be asked again.

*Also measured, also declined:* dropping the rfft-to-full mirror at the block input would save
0.017 ms/block (0.140 → 0.123), but the hilbert transform, the audio slicers and the symmetric
V4300D notch all want the full spectrum, so only EFM could have been moved off it — and it now is.

**Task 4 — the narrower pipeline, justified as traffic. Done; the premise was wrong in our favour.**

The task was written expecting scipy's single-precision transform to be slower solo, so that the
change would pay only among eight. On this box it is faster in both places: the batched video
`irfft` (four channels of blocklen) measured alone goes 0.372 ms → 0.222 ms per block, its L2
misses 3.56e4 → 1.84e4.

The real question is precision, and it is not where it looks. float32 carries 24 bits, so at the
8.5 MHz demod carrier its quantum is about 1 Hz — and that is *already* the quantum these channels
are stored at, because the record array they go into is float32 and always has been. Filtering at
that magnitude in float32 spends about five of those quanta, since every intermediate carries the
carrier as magnitude. The video band is only ±0.7 MHz wide, so `demodblock` now subtracts blanking
before the cast and each channel's own DC gain puts the offset back as it is copied into the record
array — a pass that already existed, so the restoration is nearly free. Both constants are derived
in `build_video_rfft_stack` beside the stack they belong to, so a filter rebuild can never leave the
block subtracting one centre and adding another back. Per block, on a realistic demod
(`bench_video_offset.py`):

| the video product stack, per block | ms | L2 misses | worst error on `demod` |
|---|---:|---:|---|
| float64 — today | 0.583 | 4.93e4 | — |
| float32 | 0.407 | 2.45e4 | 2.5 Hz = 0.00031 IRE (5 storage steps) |
| **float32, centred before the cast** | **0.451** | **2.86e4** | **0.5 Hz = 0.00006 IRE (1 storage step)** |

Centring costs 0.044 ms/block of the 0.176 it protects, and buys a factor of five in accuracy: the
filtering now rounds no worse than the storage it feeds. The band-pass channels (burst, pilot) come
out at 0.01 Hz, four orders below an IRE.

Two test consequences, recorded because they are the kind that get papered over:

* `demodblock_sync` — the start finder's cheap sync-only path — is held to *bit* equality with
  `demodblock`'s sync channel by `tests/unit/test_start_finder.py`. It moved to the same precision
  rather than having its assertion loosened, and now filters through the same stack row, so the test
  still passes on `assert_array_equal`.
* `tests/unit/test_demod_fft.py` compared the pipeline with the exact double-precision answer at
  `rtol=1e-6`, which no longer describes what the pipeline promises. Rather than widen it, the
  assertion is restated in the units that matter: within four float32 steps of each channel's peak,
  which is the error growth a 32768-point transform pair is entitled to (√log₂N ≈ 4 eps). On
  white-noise RF — the worst case, since the demod then spans the whole clip range instead of
  ±0.7 MHz around blanking — the channels measure 1.4 to 3.0 steps; on a real demod, half a step.
  The bound fails on a regression instead of absorbing one.

*What it is worth on its own* — interleaved plain A/B against the tree with only Task 3's fold in
it, three rounds, `-l 300`:

| cell | Task 3 only | + single precision | |
|---|---|---|---:|
| PAL CVBS `-t 1` | 3.48 3.48 3.54 \| 3.50 | 3.54 3.65 3.63 \| 3.61 | +3.0% |
| PAL CVBS `-t 6` | 7.40 7.55 7.61 \| 7.52 | 7.28 7.90 7.97 \| 7.72 | +2.6% |
| PAL `--tbc` `-t 6` | 8.25 8.09 8.55 \| 8.30 | **9.27 9.30 9.41 \| 9.33** | **+12.4%** |

The single-precision tree's first round is its own warm-up and is left in the table rather than
dropped: a freshly copied tree compiles its numba kernels on the first run, which cost that column
its `-t 1` and `-t 6` CVBS rows (3.54 and 7.28 against 3.65/3.63 and 7.90/7.97 afterwards). On
rounds 2 and 3 alone the two CVBS cells are +3.7% and +4.7%. `--tbc` was unaffected and is
consistent across all three.

`--tbc` at `-t 6` is where this belongs: it is the cell ceiling B binds, six workers each
streaming a block chain through a shared L3, and halving that chain's bytes is worth **12%** there
against 3–5% where the parent is closer to the limit.

*Acceptance:* DRAM fills per frame among eight before and after are in Task 7; the harness rows are
there too; conformance is **96/96 CTest** with `vits_known_deviations.toml` untouched, which
includes the ten-cut VITS radius sweep and the `compare-*-parallel-*` byte-identity checks.
**Go.**

**Task 5 — the copies. Priced, and they are not where §2.2 put them.**

§2.2 attributed 54% of a decode's DRAM fills to copies and casts and listed four candidates. With
the inventory in hand three are answered without being touched:

* the `keep_demod` transport went with Phase 3 Task 3;
* the record-array extraction reads one float32 channel out of a five-channel interleaved record
  array, so it touches five bytes for every one it wants — but the field-level passes that do it are
  small: everything below `concatenate_blocks` in Task 1's table together is under 8% of the frame's
  L2-miss traffic. De-interleaving would touch the field, the transport and every consumer, for a
  share that is not there;
* the FLAC reader's `bytes()` → `bytearray.extend` → `frombuffer` chain is real — the reader thread
  is 4% of the frame's L2 misses and 7.8 MiB/frame of DRAM, and none of it has a stage name because
  none of it is decoder code. It belongs to Phase 5, where it is already listed as a parent-thread
  item.

That leaves `concatenate_blocks`: 9.9 calls, 6.5 ms, 101 MiB of arrays in and out and 2.5e5 L2
misses per frame — 2.6% of the traffic. Demodulating each block straight into a preallocated field
buffer would remove most of it, at the cost of threading a destination through the block cache, the
field-job transport and the redo path. **Not taken**; the figure is recorded so the question is
settled.

**Task 6 — half-rate video products. Deferred, and the reason is now a number.**

The video products *are* the top stream, which is the condition this task was made conditional on.
But Task 4 halves their bytes for a precision cost measured at one storage step, while halving the
sample rate would change every geometry constant downstream and could not be undone in a hot fix.
The right order is to take the halving that is nearly free, measure again, and only then ask whether
the second one is worth the blast radius. **Deferred, with Task 7's figures as the input.**

**Task 7 — measure.**

*Throughput, HEAD against both landed changes.* Interleaved plain A/B, three rounds PAL and two
NTSC, `-l 300`, one cell at a time on an idle box, no sampling wrapper (§4's rule); each column is
the runs and their mean.

| cell | HEAD | Phase 4 | |
|---|---|---|---:|
| PAL CVBS `-t 1` | 3.37 3.44 3.44 \| 3.42 | 3.67 3.67 3.67 \| 3.67 | **+7.4%** |
| PAL CVBS `-t 6` | 7.26 7.24 7.29 \| 7.26 | 7.97 7.93 7.89 \| 7.93 | **+9.2%** |
| PAL `--tbc` `-t 6` | 8.18 8.15 8.08 \| 8.14 | 9.29 9.28 9.35 \| 9.31 | **+14.4%** |
| NTSC CVBS `-t 1` | 4.77 4.77 \| 4.77 | 4.91 4.94 \| 4.93 | +3.2% |
| NTSC CVBS `-t 6` | 10.68 10.77 \| 10.72 | 12.01 12.24 \| 12.12 | **+13.1%** |

*Counters, one PAL CVBS decoder solo and among eight* (`-l 150`, per frame; these are whole-run
totals rather than the differenced steady state used in Task 1, so setup is included in both
columns equally and the instruction counts run higher than Task 1's):

| per frame | solo, HEAD | solo, Phase 4 | among eight, HEAD | among eight, Phase 4 |
|---|---:|---:|---:|---:|
| fps | 3.39 | 3.64 | 1.12 | 1.29 |
| instructions | 5.365e9 | 4.986e9 (−7.1%) | 5.365e9 | 4.986e9 |
| cycles | 1.834e9 | 1.726e9 | 4.861e9 | 4.278e9 |
| L2 misses | 1.130e7 | 9.29e6 (−17.8%) | 2.478e7 | 1.837e7 (−25.9%) |
| **DRAM fills** | 4.60e6 | 4.45e6 (−3.2%) | **2.018e7** | **1.647e7 (−18.4%)** |

Two things to read off it. The changes delete **instructions** as well as bytes — 7% of them — which
is what a half-size transform is. And solo the DRAM fills barely move while the L2 misses fall 18%:
solo, the traffic these changes removed was being served by L3. It is only when eight decoders share
that L3 that the same removal is worth 18% of the DRAM fills, and 15% of the aggregate rate
(8 × 1.12 = 8.99 fps → 8 × 1.29 = 10.32 fps, against §2.2's 7.9–8.5 plateau).

*The inventory re-run on the final tree*, same instrument and span as Task 1:

| per frame, PAL CVBS `-t 1` | before | after |
|---|---:|---:|
| whole process, L2 misses | 9.59e6 | 7.80e6 (−18.7%) |
| decode thread, L2 misses | 8.64e6 | 6.90e6 (−20.1%) |
| `fft.irfft` (now carries EFM too) | 2.63e6, 154.6 MiB | 1.94e6, 125.0 MiB |
| `fft.ifft` | 1.85e6, 126.2 MiB | 9.55e5, 66.9 MiB |
| `fft.rfft` | 8.69e5, 50.9 MiB | 6.07e5, 36.1 MiB |
| `demodblock` itself | 1.63e6 | 1.73e6 |
| all transforms | 5.35e6 (56%) | 3.50e6 (45%) |

`demodblock`'s own arithmetic goes *up* slightly: it now does the centring subtraction and the
restoring add. That is the 0.044 ms/block Task 4 priced, visible from the other side.

*Acceptance: partly met, and the shortfall is stated rather than rounded.* DRAM fills per PAL frame
among eight are **2.018e7 → 1.647e7, −18.4%**, against a target of −35% (to ≤ 1.5e7); the target is
not reached. The N-serial knee cannot be said to have moved: eight decoders deliver 2.84× one
decoder where they delivered 2.65×, so the plateau lifted by 15% but is still a plateau, and this
phase measured only N=1 and N=8. Both knees therefore stand where §2.3 put them, higher by the
figures above. What did land is 7–14% across every cell of the grid, on two systems, with
instructions per frame down 7% and no conformance band widened.

## 7. Phase 5 — the parent's remaining per-frame work

Ceiling A. Only after Phases 3 and 4, and only if Phase 4 Task 7 shows `-t N` flattening below the
worker knee. **It does.** With Phase 4 in, PAL `--tbc` at `-t 6` reaches 9.31 fps while PAL CVBS at
the same `-t` reaches 7.93: the same workers, and the difference between them is the parent's
output stage. Phase 4 also widened the gap rather than closing it (`--tbc` gained 14.4% against
CVBS's 9.2%), because a worker-side saving cannot be spent by a parent-bound cell. This phase is
therefore the binding one for PAL CVBS.

**Outcome.** One of the four candidates landed, and it is the one that turned out to be a deletion:
the FLAC reader's decode buffer was re-seating a 64 MB `bytearray` on nearly every extend, so
36 ms of a PAL `--tbc` frame was spent copying bytes that had already arrived. Replacing it with a
fixed-capacity ring gives **PAL CVBS +8.8% at `-t 1`, +7.4% at `-t 6`, and PAL `--tbc` +5.2% at
`-t 6`**, bit-identical output, at a cost of 91 lines. The other three are answered with figures:
the VITS measurements were moved to the workers, measured at **−2.0%** on the binding cell, and
reverted; the inline `demodblock` is 6.7 ms/frame of which none is a rejected speculation
(`speculation_log` is empty over the spans measured); and the result transport is priced at
49 ms/frame of CPU across both ends but declined, with the condition that would reopen it stated.
Conformance is 96/96 with no deviation widened; the unit suite is 1754 passed, 3 skipped.

**Task 1 — re-measure the parent, because §2.3's table predates Phases 3 and 4.**

`py-spy record --rate 200 --threads --subprocesses`, 400 frames, attributed per parent thread
(`docs-planning/.../phase5/parent_threads.py`). PAL CVBS `-t 6` at HEAD, and the same run sampled
with `--gil` so each thread's *GIL-held* share is separated from its CPU:

| parent thread | ms/frame CPU | of which GIL | what it is |
|---|---:|---:|---|
| `ld-output` | 82.7 | — | EFM `process` 30.3, `downscale_cvbs` 23.3, DG band 9.0, chroma-vs-luma 7.5, encode 4.0 |
| `Thread-2 (_reader_loop)` | 56.6 | — | libav FLAC decode 33.1, **`buf.extend` 25.9** |
| `cvbs-resample_0` | 43.8 | — | `downscale_cvbs` 24.7, DG band 9.2, chroma-vs-luma 6.5 |
| `MainThread` | 27.9 | — | `demodblock` 6.7, `measure_vits_multiburst` 6.5, the rest scattered |
| `Thread-3` (pool results) | 25.2 | — | `_recv` 10.6, `recv` 4.5 |
| **total** | **252** | | 1.8 cores of parent at 7.18 fps under the sampler |

Phase 3 has already halved what §2.3 measured: the two output threads were 175 ms/frame and are now
126.5. The reader is now the second-largest thread and the largest single line in the parent is
inside it.

**Task 2 — the FLAC reader. Landed.**

The 25.9 ms is not the FLAC decode and it is not the `bytes(rf.planes[0])` copy (0.56 ms/frame);
it is `bytearray.extend` on the decode buffer, which is 100× what copying 3.2 MB per frame should
cost. The cause is the buffer's shape, not its size: the reader runs ahead until backpressure, so
the buffer sits at its 64 MB cap, and each extend near the cap re-seats the whole allocation.
Reproduced in isolation — the same producer/consumer pattern at the cap costs 17.3 ms per frame's
worth of bytes, against 1.1 ms when the buffer is kept small and 0.9 ms for a deque of chunks.

What landed is `fileio.SampleRing`: one fixed allocation of `readahead + history` bytes, a write
cursor and a read cursor. A byte is copied in once and out once, and nothing moves as the buffer
fills. Holding the producer to `readahead` bytes ahead of the consumer is the same condition as
keeping the ring from overwriting itself, so the backpressure rule and the safety rule are one
test; the extra `history` is what makes a backward seek a cursor move. That deletes, besides the
extend: the `bytes(buffer[:n])` slice and its `del` (1.7 ms), the separate `rewind_buf` and its
trim (2.2 ms), and the `buf_data + read_data` concatenation (0.6 ms) — the reader now hands back a
`np.empty` the samples were decoded straight into.

*Before and after, same run and sampler* (PAL CVBS `-t 6`):

| parent thread | ms/frame before | after |
|---|---:|---:|
| `Thread-2 (_reader_loop)` | 56.6 | **32.6** |
| parent total | 252 | 237 |

*Harness rows* (interleaved plain A/B, three rounds, `-l 300`, both trees warmed first):

| cell | HEAD | ring reader | |
|---|---:|---:|---:|
| PAL CVBS `-t 1` | 3.61 | 3.93 | **+8.8%** |
| PAL CVBS `-t 6` | 7.81 | 8.39 | **+7.4%** |
| PAL `--tbc` `-t 6` | 9.05 | 9.52 | **+5.2%** |

Per-round spreads are 3.58–3.64 / 3.91–3.95, 7.75–7.84 / 8.25–8.47, 8.90–9.13 / 9.37–9.65: every
round of every cell is on the same side.

*Identity.* The reader returns the same bytes on every path it has — sequential, a forward gap, a
gap past `seek_threshold`, a backward seek inside the history and one past it — checked against
fresh readers on the real capture. Decoded 40 frames PAL CVBS and PAL `--tbc` at `-t 4`: `.tbc`,
`.cvbs`, `.efm`, `.pcm` and the `.wav` byte-identical, and every metadata row identical (80 field
records, 80 `vits_metrics`, 80 VBI, 37 dropouts) but the git version stamp. `tests/unit/
test_fileio_sample_ring.py` pins the ring's cursor arithmetic and the reader's seek paths against
a byte generator, with no PyAV and no capture file.

**Task 3 — VITS on the main thread. Built, measured, reverted.**

The candidate was stated as "the measurements are already made in the worker"; they are not — all
three (`measure_its_2t_ratio`, `measure_vits_dg_staircase`, `measure_vits_multiburst`, 7.8 ms/frame
together) run only on the parent's main thread. They are pure functions of the field's TBC picture
and the AGC's vsync level (`out_scale` is frozen at `process()` time), so the implementation was
the established `precomputed_*` pattern: the worker makes the set the enabled servos will ask for
and stamps it with the level it used, and the parent re-measures the moment the AGC has moved —
the same bookkeeping `chroma_dg_output_key` does, and what keeps `-t 1` and `-t N` identical.

It works and it is bit-identical (40 frames, both output modes, all metadata rows equal). It is
also slower:

| cell | ring reader | + worker-side VITS | |
|---|---:|---:|---:|
| PAL CVBS `-t 1` | 3.97 | 3.96 | −0.3% |
| PAL CVBS `-t 6` | 8.54 | 8.37 | **−2.0%** |
| PAL `--tbc` `-t 6` | 9.67 | 9.63 | −0.4% |

Under the plan's own rule that is not a difference, but all three rounds of the binding cell are on
the same side (8.47/8.59/8.56 against 8.33/8.36/8.42), and the sign is the point. 7 ms/frame came
off a parent lane that is not the parent's binding one — the main thread is 27.9 ms/frame against
`ld-output`'s 82.7 — and landed on six workers that are already contending. **Reverted.** This is
the third measurement of §3's rule and the cleanest: the reader change and this one are the same
size in parent milliseconds, and the one that *deleted* the work paid 7.4% where the one that
*moved* it cost 2.0%.

**Task 4 — inline `demodblock` on the main thread. Not taken; the rejection rate is zero.**

The candidate asked for the rejection rate before deciding. `speculation_log` is empty over every
span measured here (40 frames at `-t 4`, both output modes) — no rejected speculation at all on
this capture, so none of the 6.7 ms/frame is a re-decode. It is, by stack: `_calibration_warmup`
51%, `_advance_chain` 33%, `_commit_entry` 16%. The warmup runs once before the first commit and
is amortised setup, not per-frame work; what is left is ~3 ms/frame of chain advance. Too small to
restructure the commit path for, and the figure that would change that verdict is a capture with a
non-zero rejection rate, which this one does not provide.

**Task 5 — the result transport. Priced at 49 ms/frame, declined.**

The payload is 6.0 MB per field, measured by re-pickling each component of a real job result
(`phase5/payload.py`): `transport_demod` 3.71 MB, `efmout` 1.56 MB, `dspicture` 0.69 MB, everything
else under 15 KB. `picture`, `efm` and `audio` are the same objects as the field's own attributes,
so they cost nothing extra. Both ends of the pipe pay: the worker spends 15.1 ms/frame pickling and
5.1 in `prepare_transport`, the parent's `Thread-3` 28.9 — **49 ms/frame of CPU to move 12 MB per
frame between processes**, 8.7% of the 565 ms/frame the whole process tree uses.

That is a deletion, not a relocation, so §3's rule does not rule it out. What rules it out is the
size of the prize against the risk. The GIL profile says `Thread-3` is the parent's largest single
GIL holder (18.4 of 76 ms/frame) — but the parent holds the GIL only 60% of a frame, nothing in it
is saturated (`ld-output` is the closest at 71% duty), and the whole tree uses 4.5 of the box's 8
cores at `-t 6`. Shared memory would delete the byte copies but not the object reconstruction, so
the honest prediction is a few per cent — at the noise floor this document sets at 5% — for the
change with the worst failure mode in it: the arrays live until the ordered output lane has written
the field, and on PAL they live across two frames because `cvbs.py` holds a first field until its
pair arrives, so a block recycled early is silent corruption of picture data.

Two cheaper deletions inside the payload were looked for and are not there. `transport_demod` is
949,811 samples against a PAL field's 800,000, so trimming it to the span `downscale_cvbs` actually
indexes would save 9.8% of the payload — but every position in `locs` is an absolute index into it
and would need the offset carried, for ~5 ms/frame. `efmout` cannot be decimated in the worker for
the same reason the 4fsc resample cannot: the EFM decimator carries filter state across the whole
capture, in commit order.

*What would reopen this.* `ld-output` at 82.7 ms/frame is the parent's binding lane and 30.3 of it
is `efm_demod.process`. If that lane comes down, the GIL becomes the parent's binding resource
rather than one lane's CPU, and `Thread-3`'s 18.4 ms of it is then the largest thing left to
delete. Measure the GIL occupancy again first: at 60% it is not yet the constraint.

*Acceptance:* met for the item taken — the parent's per-thread ms/frame before (56.6) and after
(32.6), and the harness rows above. Three items priced and not taken, each with the figure that
decided it.

## 8. Phase 6 — take stock: is the concurrency architecture the limit?

No decoder changes; nothing in this section is a proposal, only what the instruments now say.

**Outcome: the architecture is not the limit, and ceiling C is not the wall §2.2 described.** `-t N`
does not scale to the physical core count — every cell peaks at `-t 4` of 8 — but the pool is no
longer what stops it. PAL `--tbc` at `-t 4` delivers 11.77 fps and four *independent* serial
decoders on the same box deliver 11.74: the field-job architecture at its knee now extracts
everything a perfect partitioning would. Nor is there anything above that to extract — eight
independent decoders return **11.29 fps, less than four do**, and a second arm with the counters
attached puts that fall at the same instructions per frame for 2.4× the cycles. So the
batch-parallel plan's premise, "roughly one serial decode per core" (that plan's §4, ≈ 8 × 4.0 =
32 fps here), is refuted on this box by its own best case, and
reopening the concurrency design would buy PAL `--tbc` nothing at all. What remains is one bounded
item — PAL CVBS is 17% below that ceiling and the shortfall is parent-visible — and then bytes
streamed per frame, which is a separate plan.

**Task 1 — the `-t` sweep.** Two rounds, `-l 1000`, round-robin over the cells at each `-t` so
session drift lands on all three equally; both rounds shown, then their mean. Round-to-round spread
is 4.5% at worst (NTSC `-t 6`), under 2.3% in fourteen of fifteen cells and under 1% in nine.

| cell | `-t 1` | `-t 2` | `-t 4` | `-t 6` | `-t 8` |
|---|---:|---:|---:|---:|---:|
| PAL CVBS, fps | 4.00 3.99 \| **4.00** | 8.06 8.12 \| **8.09** | 9.88 9.56 \| **9.72** | 9.84 9.74 \| **9.79** | 9.60 9.69 \| **9.64** |
| PAL CVBS, peak tree RSS (MB) | 727 | 1400 | 2129 | 2762 | 3439 |
| PAL `--tbc`, fps | 4.32 4.34 \| **4.33** | 8.29 8.21 \| **8.25** | 11.75 11.78 \| **11.77** | 10.98 11.16 \| **11.07** | 10.14 9.92 \| **10.03** |
| PAL `--tbc`, peak tree RSS (MB) | 698 | 1386 | 2040 | 2651 | 3323 |
| NTSC CVBS, fps | 5.48 5.47 \| **5.47** | 9.59 9.49 \| **9.54** | 14.66 14.57 \| **14.62** | 14.21 14.85 \| **14.53** | 13.28 13.29 \| **13.29** |
| NTSC CVBS, peak tree RSS (MB) | 618 | 1179 | 1710 | 2240 | 2775 |

Against the working-set plan's Phase 0 baseline (§1.1 there), best cell to best cell: PAL CVBS
4.81 → 9.79 (**+104%**), PAL `--tbc` 7.38 → 11.77 (**+59%**), NTSC CVBS 10.50 → 14.62 (**+39%**).
Serially: PAL CVBS 2.71 → 4.00 (+48%), PAL `--tbc` 2.82 → 4.33 (+54%), NTSC CVBS 3.01 → 5.47
(+82%), each in 8–28% less resident memory.

Two shape changes matter more than the levels:

- **PAL CVBS is no longer flat from `-t 2`.** It was 4.67 → 4.81 across `-t 2`…`-t 8`, the signature
  §2.3 read as a parent ceiling. It now doubles from `-t 2` to `-t 4` and only then flattens, which
  is the same shape as the other two cells rather than a shape of its own.
- **NTSC CVBS stopped scaling to `-t 8`.** It reached 3.5× its serial rate at `-t 8` at baseline;
  it now peaks at `-t 4` and loses 9% by `-t 8`. Nothing about NTSC got worse — its serial rate rose
  82%, so four workers now stream what eight used to, and the knee moved down to meet them. The
  knee is a property of the box divided by the cost of a field, and Phases 1–5 halved the divisor.

**Task 2 — the concurrent-serial curve.** N independent serial PAL CVBS decoders over adjacent
1000-frame spans, Phase 0's arm re-run unchanged:

| N | 1 | 2 | 4 | 8 |
|---|---:|---:|---:|---:|
| aggregate post-setup fps | 4.01 | 7.45 | **11.74** | 11.29 |
| per-process efficiency | 100% | 93% | 73% | 35% |
| peak tree RSS (MB) | 723 | 1431 | 2842 | 5582 |
| *Phase 0: aggregate fps* | *2.81* | *4.79* | *5.96* | *5.90* |

The knee is still between 2 and 4 and the aggregate still turns over after it, but the plateau has
almost doubled (5.96 → 11.74) and the second decoder now costs 7% where it cost 15%. The
per-decoder hot set, re-measured with `scripts/report_working_set.py`, is **5.60 MiB** against
Phase 0's 11.5 MiB (resident filters 11.17 MiB, LUT 0.02, 1.91 MiB read per block, 3.68 MiB of
block temporaries), so 32 MiB of L3 holds 5.7 hot sets where it held 2.8. That is the working-set
plan's Phase 4 Task 1 acceptance — both knees and the hot set, stated beside Phase 0's.

**Task 3 — the utilisation table.** Per-thread busy fraction of the parent and its children over
the second half of a 300-frame run. `n` children is `-t` plus the stage-2 helper; the wrapper costs
more at higher `-t`, so these rows are attribution and never a delta (§4).

| cell | fps | parent Σ | busiest parent thread | children Σ | duty each |
|---|---:|---:|---:|---:|---:|
| PAL CVBS `-t 1` | 3.98 | 1.16 | 96% | — | — |
| PAL CVBS `-t 4` | 8.76 | 1.91 | 75% | 3.69 | 74% (max 94%) |
| PAL CVBS `-t 6` | 8.40 | 1.94 | 76% | 3.76 | 54% (max 67%) |
| PAL CVBS `-t 8` | 8.50 | 1.97 | 76% | 3.89 | 43% (max 51%) |
| PAL `--tbc` `-t 4` | 10.22 | 1.03 | 32% | 3.87 | 77% (max 98%) |
| PAL `--tbc` `-t 6` | 9.62 | 1.30 | 39% | 5.81 | 83% |
| PAL `--tbc` `-t 8` | 8.72 | 1.66 | 48% | 7.74 | 86% |
| NTSC CVBS `-t 4` | 12.04 | 0.86 | 40% | 3.92 | 78% |
| NTSC CVBS `-t 6` | 12.68 | 1.31 | 56% | 5.83 | 83% |
| NTSC CVBS `-t 8` | 11.93 | 1.42 | 72% | 7.69 | 85% |

`--tbc` and NTSC still do what §2.3 recorded: past `-t 4` the workers stay near saturation, the
tree consumes 7–9 cores, and throughput *falls* — cores are available and each field simply costs
more. PAL CVBS still does not: its children are pinned at 3.7–3.9 cores whatever `-t` is, and only
their duty dilutes. That much is unchanged. What has changed is that nothing in its parent is
saturated either — 1.9 cores across five threads with the busiest at 76% — so the residue is a
dependency chain through the parent, not a full lane. `py-spy` on the parent at `-t 4`, 400 frames:

| thread | ms/frame | of which | GIL ms/frame |
|---|---:|---|---:|
| `ld-output` | 83.5 | `efm_demod.process` 29.5, `downscale_cvbs` 21.3, `_chroma_dg_band` 8.9, `_correct_chroma_vs_luma` 7.8, encode 5.5 | 15.7 |
| `cvbs-resample_0` | 44.9 | `downscale_cvbs` 22.9, `_chroma_dg_band` 9.8, `_correct_chroma_vs_luma` 7.7 | 10.2 |
| `Thread-2 (_reader_loop)` (FLAC) | 27.1 | PyAV decode | 7.2 |
| `MainThread` | 25.8 | VITS 6.8, inline `demodblock` 6.1 | 16.9 |
| `Thread-3` (pool result unpickling) | 24.1 | `multiprocessing.connection.recv` | 16.2 |
| *parent total* | *216* | | *70* |

216 ms of parent CPU per frame, with the GIL held 58% of one. That is 1.9 cores of concurrency the
parent must find inside a frame, and the utilisation table above says it finds 1.9 — so the parent
fits, and still binds. Both figures are just under their `-t 6` values from §7 Task 1 (237 ms,
60%): nothing in the parent moved when the knee did.

**Task 4 — what the plateau is made of.** §2.2 derived the N-serial plateau from bandwidth: 1.43
GB/frame at 8 × 1.21 fps ≈ 14 GB/s against §2.1's 20 GB/s. That arithmetic no longer closes, and
the traffic says why. `ls_any_fills_from_sys.mem_io_local` over the whole tree, `-l 150` per
decoder:

| N independent serial PAL CVBS | 1 | 2 | 4 | 8 |
|---|---:|---:|---:|---:|
| aggregate post-setup fps | 3.96 | 7.38 | **11.99** | 11.20 |
| DRAM fills per frame (MiB) | 266 | 368 | 608 | 1017 |
| DRAM fills (GB/s) | 1.11 | 2.85 | 7.64 | 11.94 |
| cycles per frame | 1.68e9 | 1.71e9 | 2.04e9 | 4.10e9 |
| instructions per frame | 4.98e9 | 4.85e9 | 4.86e9 | 4.82e9 |

and at the `-t 4` knee, 882 MiB/frame and 7.47 GB/s for PAL CVBS, 677 MiB/frame and 6.64 GB/s for
PAL `--tbc`.

The counter counts fills, not writebacks, so every figure is a floor on real DRAM traffic. Even so:
**at the knee the box is moving 7.6 GB/s against a 20 GB/s path**, and the curve is already flat
there. Bandwidth cannot be what stops it at N = 4. What does is in the last two rows — the same
instructions per frame to within 4% across the whole curve, for 1.22× the cycles at N = 4 and
2.44× at N = 8, with fills per frame rising 3.8×. Concurrency past the knee does not divide the
work differently, it *manufactures traffic*: at N = 8 the eight hot sets are 45 MiB against 32 MiB
of L3, each decoder's streams evict the others', and the extra fills buy stall rather than
throughput. By N = 8 the 11.9 GB/s of fills plus their writebacks may well reach the 20 GB/s wall,
but the plateau was reached at half that.

*Ceiling C, restated.* Not "20 GB/s of DRAM, reached at N ≈ 4", but: **past N ≈ 4 an added decoder
raises DRAM traffic per frame faster than it converts cores into frames**, and it does so at a
bandwidth well short of the path's capacity. The lever named in §3 is unchanged — bytes streamed
per frame — but the target it must beat is L3 capacity per concurrent decoder, not the bus.

**Task 5 — the decision.** Of §8's three branches, none applies cleanly, so the finding is stated
as measured rather than forced into one:

- *`-t N` does not scale to the physical core count.* It peaks at `-t 4` of 8 in all three cells,
  so the close-and-re-derive branch does not trigger on its own terms.
- *The reason is not visible in the parent for two cells of three.* PAL `--tbc` at `-t 4` equals
  four independent decoders to within 0.3% — the two best PAL figures the box produces by any
  arrangement, and they agree. There is nothing for a different concurrency design to recover
  there, and the batch-parallel plan's §3.6 is therefore **not** reopened: its promised prize is
  the independent-decoder curve, and that curve is already met at N = 4 and falls at N = 8.
- *It is visible in the parent for PAL CVBS,* which reaches 9.72 where the same box gives 11.74
  to four independent decoders — a **17% gap**, against 216 ms/frame of parent CPU, a 58% GIL and
  workers that starve rather than saturate. That is the residue of ceiling A, it is the size §7
  Task 5 priced its declined item against, and it is bounded by a figure that did not exist when
  §7 declined it: the most a perfect parent can be worth on this cell is 17%.
- *The remaining lever is ceiling C's,* restated above, and §8's third branch applies: bytes per
  frame inside the demodulator, in a separate plan. The block chain is 81% of a frame's L2-miss
  traffic (§6 Task 1) and that is where the 608 MiB/frame at the knee comes from.

**The `-t` auto default is now above the measured optimum.** `main.py:504` computes
`min(max(physical - 2, 1), 10)`, which is 6 on the reference box; the optimum measured here is 4 in
every cell. At `-t 6` PAL CVBS and NTSC are unchanged within the spread (9.79 against 9.72, 14.53
against 14.62) but PAL `--tbc` loses 6.3% (11.07 against 11.77), and the default costs 630 MB of
peak tree RSS (2762 against 2129). The working-set plan's Phase 4 Task 3 asks for the default to
land at or below the measured optimum; it does not, and re-deriving it is the one decoder change
this take-stock has evidence for. It is left for a following commit — this phase changes no code.

*Acceptance:* met. The `-t` sweep, the concurrent-serial curve and the utilisation table are
re-run and recorded above beside Phase 0's, both knees and the per-decoder hot set are stated, and
the decision rests on two measurements the earlier phases did not have: that `--tbc` at its knee
equals independent decoders, and that the plateau sits at 7.6 GB/s of a 20 GB/s path.

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
- **Single-precision transforms — closed.** The premise was wrong: scipy's `complex64` transform
  is *faster* per element here, and the video stack's is 40% faster (§6 Task 4). What the task
  actually turned on was precision, and the answer is that filtering the video products in float32
  rounds within one step of the float32 the record array has always stored them at, once the block
  is centred on blanking before the cast. Landed, 96/96 CTest, no deviation widened.
- **Block length and the filters.** Every frequency-domain filter is sampled at `blocklen`; at
  8192 the resolution is 4.9 kHz per bin against 1.2 kHz today, and the emphasis IIRs and the
  notches are the responses most sensitive to that. Conformance gates it, and 16384 is the safer
  step.
- **The box.** As before: one 5800X, one L3 size, one DRAM speed. The knees are stated, not assumed
  to transfer.
