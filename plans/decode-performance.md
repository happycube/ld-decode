# Decode performance: what was measured, what changed, and what is left

A record of the throughput work carried out on the decoder between the `05d60fd9` tree and the
current one. It is not a plan — everything described here is either landed, reverted with its
reason, or declined with the figure that decided it. It replaces four working documents that
tracked the work as it went (§11).

**Result in one paragraph.** On the reference box the decoder is **2.0× faster on PAL CVBS, 1.6× on
PAL `--tbc` and 1.4× on NTSC CVBS** at their best thread counts, and 1.5–1.8× serially — in less
resident memory in every cell of the grid, with no conformance band widened and `-t 1`/`-t N`
byte-identity intact throughout. None of it came from the change everyone expected — shrinking the
decoder's cache footprint, which was measured to *cost* 1–3% — and none of it came from rearranging
the concurrency. Every gain was **work deleted from a hot path**: a filter response held instead of
recomputed per block, transforms at fast lengths instead of prime ones, a corrector rebuilt to
one pass at single precision, an EFM transform halved, the video product stack narrowed to the
precision it was always stored at, and a reader buffer that had been re-seating a 64 MB allocation
on every extend. Where the decoder now stands, the field-job pool at its knee (`-t 4`) extracts as
much from the box as four wholly independent decoders do, so the concurrency architecture is not
the limit; what binds is DRAM traffic manufactured by concurrency itself, and the remaining lever
is bytes streamed per frame inside the demodulator.

---

## 1. Headline figures

Reference box: AMD Ryzen 7 5800X, 8 physical cores / 16 SMT threads, 32 KiB L1d and 512 KiB L2 per
core, **32 MiB L3 shared**, 62 GiB dual-channel DDR4. PAL material
`Domesday_DD86-DS2_NationalA_PP_20191014_CAV_PAL_00001-54000.ldf`, NTSC `Bambi`, both at `-s 5000`,
`-l 1000`. Post-setup fps as the decoder reports it; RSS is the peak across the whole process tree.
All rows from [`scripts/bench_decode_throughput.py`](../scripts/bench_decode_throughput.py).

| Cell | `-t 1` | `-t 2` | `-t 4` | `-t 6` | `-t 8` |
|---|---:|---:|---:|---:|---:|
| PAL CVBS, before | 2.71 | 4.67 | 4.66 | 4.79 | **4.81** |
| PAL CVBS, **after** | 4.00 | 8.09 | 9.72 | **9.79** | 9.64 |
| PAL CVBS, peak tree RSS (MB), before → after | 1015 → 727 | 1860 → 1400 | 2503 → 2129 | 3071 → 2762 | 3591 → 3439 |
| PAL `--tbc`, before | 2.82 | 5.43 | **7.38** | 6.99 | 6.69 |
| PAL `--tbc`, **after** | 4.33 | 8.25 | **11.77** | 11.07 | 10.03 |
| PAL `--tbc`, peak tree RSS (MB) | 760 → 698 | 1635 → 1386 | 2357 → 2040 | 2973 → 2651 | 3836 → 3323 |
| NTSC CVBS, before | 3.01 | 5.56 | 9.15 | 10.01 | **10.50** |
| NTSC CVBS, **after** | 5.47 | 9.54 | **14.62** | 14.53 | 13.29 |
| NTSC CVBS, peak tree RSS (MB) | 751 → 618 | 1353 → 1179 | 1847 → 1710 | 2452 → 2240 | 2958 → 2775 |

Best cell to best cell: PAL CVBS **+104%**, PAL `--tbc` **+59%**, NTSC CVBS **+39%**. Serially:
+48%, +54%, +82%.

Two shape changes matter as much as the levels:

- **PAL CVBS is no longer flat from `-t 2`.** It used to sit at 4.67–4.81 across `-t 2`…`-t 8` —
  the signature that was read, correctly at the time, as a parent-process ceiling. It now doubles
  from `-t 2` to `-t 4` before flattening, which is the same shape as the other two cells.
- **NTSC CVBS stopped scaling to `-t 8`.** It used to reach 3.5× its serial rate at `-t 8`; it now
  peaks at `-t 4` and loses 9% by `-t 8`. Nothing about NTSC got worse — its serial rate rose 82%,
  so four workers now stream what eight used to, and the knee moved down to meet them. **The knee
  is a property of the box divided by the cost of a field**, and this work halved the divisor.

N independent serial PAL CVBS decoders over adjacent 1000-frame spans — the same box spending its
cores the simplest possible way:

| N | 1 | 2 | 4 | 8 |
|---|---:|---:|---:|---:|
| aggregate fps, before | 2.81 | 4.79 | 5.96 | 5.90 |
| aggregate fps, **after** | 4.01 | 7.45 | **11.74** | 11.29 |
| per-process efficiency, after | 100% | 93% | 73% | 35% |
| peak tree RSS (MB), before → after | 957 → 723 | 1910 → 1431 | 3771 → 2842 | 7579 → 5582 |

The plateau nearly doubled (5.96 → 11.74) and the second decoder now costs 7% where it cost 15%,
but the knee is still between 2 and 4 and the aggregate still turns over after it. §7 is about why.

## 2. How things were measured, and the rules that came out of it

Two committed harnesses carry every claim:
[`scripts/bench_decode_throughput.py`](../scripts/bench_decode_throughput.py) (one
`(system, mode, -t, -s, -l, capture)` cell, the decoder's own post-setup fps, peak tree RSS, one
JSON row per cell) and [`scripts/report_working_set.py`](../scripts/report_working_set.py)
(resident filter bytes by array, the resample LUT, the bytes `demodblock` actually indexes per
block, and the block's peak live temporaries under `tracemalloc`). A third,
[`scripts/report_decode_traffic.py`](../scripts/report_decode_traffic.py), attributes hardware
counters per named decoder stage.

Four rules were arrived at the hard way, and each one exists because a measurement taken the other
way produced a wrong verdict:

- **Count fills, not bytes.** A memory claim states DRAM fills per frame
  (`ls_any_fills_from_sys.mem_io_local`, solo and among eight) before the change and after it.
  Resident size is reported but never argued from. See §3.
- **Measure one thing at a time, on an idle box.** A row taken while another cell was running is
  discarded, not corrected.
- **Compare interleaved, and plain.** Back to back a cell repeats to ±0.3%, but the same tree
  measured an hour apart in a long session drifts by 5%, and the `/proc` sampling wrapper costs
  more at higher `-t` than at lower. So a before/after claim runs both trees alternately in one
  script without the wrapper, and **a difference under ~5% taken any other way is not a
  difference**. Two wrong verdicts were nearly recorded on rows compared across sessions.
- **A microbenchmark prices arithmetic, not traffic.** The block demodulator measured in isolation
  over 400 back-to-back calls keeps its filter bank in L3; inside a decode it does not, and that
  single difference accounted for a 3× error in where a frame's memory traffic was thought to go
  (§7.2).

Byte-identity between `-t 1` and `-t N` (`compare-*-parallel-*`) held throughout, and the VITS
conformance lanes gated every change that moves output bytes, with
`analysis/vits_known_deviations.toml` untouched from first commit to last. Final gates: **96/96
CTest**, unit suite **1754 passed, 3 skipped**.

## 3. The premise that was wrong, and what replaced it

The work began from a clear and plausible mechanism: one decoder keeps about 11.5 MiB hot (an
11 MiB `complex128` filter bank of which 2.53 MiB is read per block, a 4 MiB sinc resample LUT
read once per output sample, and ~5 MiB of live block temporaries). Two of those fit a 32 MiB L3
and three do not, which is exactly where the concurrent-serial curve turned over. Shrink the hot
set, the reasoning went, and every concurrency ceiling rises at once — `-t N`, independent
decoders and any future design alike.

**It was tested directly and it is false.** Rebuilding the sinc LUT at 256 phases with
interpolation took it from 4.00 MiB to 16 KiB and the hot set from 11.53 to 7.55 MiB — L3 would
now hold 4.2 decoders where it held 2.8 — and throughput went **down 1–3% in every cell measured,
including at four concurrent decoders, where the whole argument was supposed to apply.** The
counters say why:

| per PAL frame, one decoder | before | after LUT | before, among 8 | after, among 8 |
|---|---:|---:|---:|---:|
| L2 misses | 1.47e7 | **1.36e7** | 2.98e7 | 2.91e7 |
| fills from L3 | 1.59e7 (973 MiB) | **1.48e7** | 2.46e7 | 2.43e7 |
| fills from DRAM | 5.14e6 (313 MiB) | 4.87e6 | 2.38e7 | 2.35e7 |
| post-setup fps | 3.61 | 3.55 | 1.21 | 1.21 |

The 1.1e6 line fetches per frame vanished exactly as designed — and they were being subtracted from
**L3, not DRAM**. The table lived in L3, its loads were independent across output samples, and the
out-of-order window had already hidden their latency. Nothing was waiting on them. Against that,
the interpolation the small table needs is real arithmetic that nothing hides.

**A change that removes cache lines pays only if those lines were on a stalled path** — and the
counters can say whether they are *before* the change is made. That single result redirected
everything after it: the remaining footprint proposals (a `complex64` filter bank, half-rate video,
one picture per field) were all justified as footprint, and none of them was implemented on that
basis. What replaced the premise is **bytes streamed per frame**, which is a different quantity
from bytes resident and behaves differently under contention.

The LUT change was kept, on its own merits rather than for throughput: both resample kernels now
read the table identically where they previously did not, the shipped table is *more* accurate than
the nearest-neighbour lookup it replaced (7.8e-7 rms against a 3.05e-5 16-bit LSB), and 4 MiB per
worker process stops being allocated. Its build also turned out to have a latent bug — the guard
row was a copy of its neighbour rather than the phase-1.0 filter, invisible at 65536 phases and
twenty times worse than the table it replaced at 256.

## 4. What landed

In the order it was done. Every row is measured on the harness against the tree immediately before
it, interleaved and plain.

| # | Change | Where | Measured |
|---|---|---|---|
| 1 | `cache=True` on `scale_positions`, matching `scale_field` | `dsp.py` | 1.99 s JIT compile becomes a 4 ms cache load — **1.83 s off every process that resamples** |
| 2 | Hold `Filters["MTF"] ** mtf_level` per adopted level instead of raising it per block | `rfdecode.py` (`mtf_response()`) | block 3.017 → 2.721 ms PAL (−9.8%); NTSC's `MTF` is `complex128` so its `pow` is 2.29 of 5.18 ms — block −46%, **NTSC CVBS `-t 1` 3.01 → 4.83 fps (+60%)** |
| 3 | Two further block hoists: the PAL carrier notch applied in place; the video and audio channels cast on assignment instead of into copies `np.rec.array` copies again | `rfdecode.py` | 0.020 → 0.017 ms and 0.087 → 0.057 ms per block, three 512 KiB temporaries deleted |
| 4 | Chroma-DG correction transformed at `next_fast_len`, padded by tiling the field's own periodic continuation | `field.py` (`_chroma_dg_plan`, `_chroma_dg_pad`) | PAL CVBS field B (354,689 — prime) **105.6 → 9.1 ms**; PAL CVBS **+18.7% (`-t 1`) to +43.5% (N=4)** |
| 5 | 256-phase interpolated sinc LUT | `dsp.py`, `sinc_lut.npz` | 4.00 MiB → 16 KiB; **−1% to −3%** throughput (§3) |
| 6 | Chroma-DG corrector rebuilt: single precision through the filtering, the analytic chroma as a band and its quadrature via two *real* transforms, and one fused `njit` elementwise pass with no temporaries | `field.py`, `dsp.py` (`select_band`, `equalise_chroma_gain*`) | per field **21.6 → 6.1 ms** (gain) and 27.2 → 8.9 (gain and phase); contended at `-t 6`, 42.9 → 16.3 ms. **PAL +10–19%, NTSC +2%** |
| 7 | PAL CVBS burst lock damped to `g = 0.75` | `cvbs.py` (`PAL_LOCK_GAIN`) | quality, not throughput: residual rms falls 8–11% on all ten PAL radius cuts and on the reference capture |
| 8 | EFM output as one real inverse transform of the folded half spectrum, not a complex one whose imaginary half is discarded | `rfdecode.py` (`computeefmhalffilter`) | per block **0.314 → 0.166 ms**, 9428 → 8043 L2 misses; **bit-identical** output over 2.6M samples |
| 9 | Video product stack filtered in float32, with blanking subtracted before the cast and each channel's DC gain restoring it | `rfdecode.py` (`build_video_rfft_stack`) | per block **0.583 → 0.451 ms**, L2 misses 4.93e4 → 2.86e4; worst error 0.5 Hz = 0.00006 IRE, one storage step. **PAL `--tbc` `-t 6` +12.4%** |
| 10 | `fileio.SampleRing`: one fixed allocation with a write and a read cursor, replacing a `bytearray` that re-seated its 64 MB buffer on nearly every extend | `fileio.py` | reader thread **56.6 → 32.6 ms/frame**; **PAL CVBS +8.8% (`-t 1`), +7.4% (`-t 6`), PAL `--tbc` +5.2%**; bit-identical, 91 lines |

Three of these deserve their own note.

**The chroma-DG transform length (#4)** was the whole of one round's gain, and its cause is
mundane: PAL CVBS field B is 354,689 samples, which is prime, so scipy fell back to a generic
radix. Padding to `next_fast_len` (354,816) is worth 11×. What made it safe rather than merely fast
is the padding: the transform convolves circularly, so each end of the field already had the other
as its neighbour, and *tiling the field's own periodic continuation* preserves that where zero
padding would introduce an edge. A 2048-sample guard, where the windows' impulse tails are under
1e-7, holds the padded array's own wrap clear of every sample kept. Worst deviation from the
unpadded correction is 5.1e-6 IRE against the 0.0021 IRE the 16-bit output quantises to.

**The corrector rewrite (#6)** began from a premise that had to be abandoned: a time-domain FIR was
supposed to be the cheaper form. It is not — the two windows' transitions are 0.3 and 0.4 MHz
against a 17.73 MHz lattice, and holding every truncated tap below 1e-4 of the peak takes 437 and
491 taps, tens of milliseconds a field against the 21.6 ms the transform corrector already cost.
The FIR design was abandoned rather than built. The cost was never in the filters; it was in eight
whole-field `float64` temporaries streamed through DRAM for one field's arithmetic, and that is
what the rewrite deleted.

**The float32 video stack (#9)** was written expecting to lose solo and win under contention. It
wins in both places, and the interesting part is the precision argument. float32 carries 24 bits,
so at the 8.5 MHz demod carrier its quantum is about 1 Hz — and *that is already the quantum these
channels are stored at*, because the record array they go into is float32 and always has been.
Filtering at that magnitude spends about five of those quanta, because every intermediate carries
the carrier as magnitude. The video band is only ±0.7 MHz wide, so centring the block on blanking
before the cast costs 0.044 ms of the 0.176 it protects and buys a factor of five: 0.5 Hz, one
storage step. The two constants are derived beside the stack they belong to, so a filter rebuild
cannot leave the block subtracting one centre and adding a different one back.

Two test consequences are recorded because they are the kind that get papered over. `demodblock_sync`
is held to *bit* equality with `demodblock`'s sync channel; rather than loosening that assertion it
was moved to the same precision and the same stack row, so it still passes on `assert_array_equal`.
And `tests/unit/test_demod_fft.py` compared the pipeline with the exact double-precision answer at
`rtol=1e-6`, which no longer describes what the pipeline promises; rather than widen it, the
assertion was restated in the units that matter — within four float32 steps of each channel's peak,
which is the error growth a 32768-point transform pair is entitled to. It fails on a regression
instead of absorbing one.

## 5. What was built, measured and reverted

Three changes were implemented in full, proved correct, measured, and taken back out. Together they
are the most transferable result in this document.

**The EFM demodulator on its own output lane.** `efm_demod.process` is ~28 ms/frame on the busiest
parent thread and runs without the GIL, so it was given its own ordered lane. It is correct
(`compare-{ntsc,pal,jason-pll}-parallel-efm` all pass) and it did what it was meant to do:
`ld-output` fell from 79.2 to 68.5 ms/frame. It buys nothing, because **the parent was already
thread-saturated and the new thread made every other thread in the process about 30% more
expensive** — the correction 17.2 → 23.6 ms/frame, the resample thread 43.2 → 56.6, the
demodulation itself 28.2 → 36.0, the pool's result reader 25.3 → 34.5. Parent CPU went from 176% of
a core to 209%: 55 ms/frame of new work to move 28 ms off one thread.

**The PAL 4fsc resample in the workers.** The dispatcher stamps each job with the burst-lock shift
and the chroma-DG estimate, the worker resamples under that shift and rides the result with the key
it was made under, and the writer either writes what it was sent or resamples itself. Correct at
zero tolerance (`compare-pal-cvbs-parallel-cvbs` with `--exact-speculation`). The parent shed what
it was meant to shed — 178% of a core → 123% at `-t 4` — but **the workers gained far more than the
parent lost**: 333% → 371% at `-t 4` and 333% → **511%** at `-t 6`, an extra 178% of a core for a
resample that costs 85 ms/frame when the parent does it. **A millisecond of work costs about three
times as much in a contended worker as in the parent.**

That experiment also exposed something worth more than the change: **the PAL burst lock was chasing
its own measurement noise.** At a tolerance below the burst measurement's noise, 99.5% of shipped
resamples were redone. Over 120 frames the residual has a mean of 0.01° against an rms of 1.65, and
the shift's movement over eight frames (0.019 samples rms) is the same as over one (0.018) — a
bounded random walk, not a drift. Applying the whole of each frame's residual writes the previous
frame's noise into the next frame's lattice. Damping the loop (#7 above) shipped as a quality
change and is the one output change this work made.

**The VITS measurements moved into the workers.** All three (`measure_its_2t_ratio`,
`measure_vits_dg_staircase`, `measure_vits_multiburst`, 7.8 ms/frame together) run on the parent's
main thread. They are pure functions of the field's TBC picture and the AGC's vsync level, so they
moved under the established `precomputed_*` pattern, bit-identically. They are also **−2.0% on the
binding cell** — 7 ms came off a parent lane that is not the parent's *binding* one (the main
thread is 27.9 ms/frame against `ld-output`'s 82.7) and landed on six workers that are already
contending.

**The rule.** All three *moved* work rather than removing it, and all three cost more than they
saved:

> Work is not movable between these ceilings at par. The only changes that have paid are the ones
> that **delete** work. Moving it — to another parent thread, or into the workers — costs about 3×
> what it saves.

The cleanest single data point is the pair in §4 #10 and the VITS revert. Both are parent-side items
of the same kind and the same order of size — 24 and 7 milliseconds of parent CPU per frame — both
are bit-identical decodes, and both were measured interleaved in the same session on the same box.
The one that *deleted* the work paid **+7.4%**; the one that *moved* it cost **−2.0%**.

## 6. What was priced and declined

Each of these was measured far enough to decide, and the figure is recorded so the question does
not have to be reopened from scratch.

| Candidate | Figure | Why not |
|---|---|---|
| Shorter demod block (16384, 8192) | every cell within the harness spread at all three lengths, including N=4 | at 8192 the block does 12% more work for the same throughput, so the per-sample cost of an L2-resident chain *is* lower — by exactly the overlap it costs. The block length stays at 32768 |
| Holding the product of the three video filters | 0.064 → 0.025 ms/block, 2.3 ms/frame ≈ 0.75% | `(X·A)·B·C` and `X·(A·B·C)` differ in the last ulp, so every video byte in the corpus would need re-recording. 0.75% does not buy that |
| Demodulating blocks straight into a preallocated field buffer (`concatenate_blocks`) | 6.5 ms, 101 MiB of arrays, 2.5e5 L2 misses per frame — **2.6%** of the traffic | costs threading a destination through the block cache, the field-job transport and the redo path |
| De-interleaving the five-channel record array | everything below `concatenate_blocks` in the stage table is together under 8% of the frame's L2-miss traffic | touches the field, the transport and every consumer, for a share that is not there |
| Half-rate video products | the video products *are* the top stream, which is the condition this was made conditional on | the float32 halving (#9) takes the same bytes for a precision cost of one storage step, where this would change every geometry constant downstream and could not be undone in a hot fix. Deferred behind that, not refused |
| Shared-memory result transport | payload 6.0 MB/field; **49 ms/frame of CPU across both ends** to move 12 MB/frame, 8.7% of the tree's CPU | it is a deletion, so the §5 rule does not rule it out. What does: nothing in the parent is saturated (busiest lane 71% duty, GIL 58–60%), shared memory would delete the byte copies but not the object reconstruction, so the honest prediction is a few per cent — at the noise floor — for the change with the worst failure mode available (arrays live until the ordered lane has written the field, and on PAL across two frames, so a block recycled early is silent picture corruption) |
| Batch-parallel decode: replace the pool with N independent serial decoders over disjoint ranges | see §7.3 | its throughput premise is measured false on this box |

Two cheaper deletions inside the transport payload were looked for and are not there:
`transport_demod` is 949,811 samples against a PAL field's 800,000, so trimming it to the span
`downscale_cvbs` indexes would save 9.8% — but every position in `locs` is an absolute index into
it. And `efmout` cannot be decimated in the worker for the same reason the 4fsc resample cannot:
the EFM decimator carries filter state across the whole capture, in commit order.

## 7. Where the decoder stands now

### 7.1 The three ceilings, restated

| | Ceiling | Binds | Status |
|---|---|---|---|
| A | the parent process's per-frame work | PAL CVBS at any `-t` | halved and bounded: 216 ms/frame across five threads, GIL 58%, and the residue is worth at most 17% (§7.3) |
| B | the per-field cost of a worker once several share the box | PAL `--tbc` and NTSC past `-t 4` | measured properly: the same instructions per frame cost 1.7–1.9× the cycles and 3.8–4.3× the DRAM fills at `-t 4` |
| C | the memory path | N independent decoders past N ≈ 4 | **restated** — see below |

Utilisation, per-thread busy fraction of the parent and its children over the second half of a
300-frame run (attribution only — the sampling wrapper costs more at higher `-t`, so these are
never read as a delta):

| cell | fps | parent Σ | busiest parent thread | children Σ | duty each |
|---|---:|---:|---:|---:|---:|
| PAL CVBS `-t 4` | 8.76 | 1.91 | 75% | 3.69 | 74% (max 94%) |
| PAL CVBS `-t 6` | 8.40 | 1.94 | 76% | 3.76 | 54% |
| PAL CVBS `-t 8` | 8.50 | 1.97 | 76% | 3.89 | 43% |
| PAL `--tbc` `-t 4` | 10.22 | 1.03 | 32% | 3.87 | 77% (max 98%) |
| PAL `--tbc` `-t 8` | 8.72 | 1.66 | 48% | 7.74 | 86% |
| NTSC CVBS `-t 4` | 12.04 | 0.86 | 40% | 3.92 | 78% |
| NTSC CVBS `-t 8` | 11.93 | 1.42 | 72% | 7.69 | 85% |

`--tbc` and NTSC past `-t 4`: the workers stay near saturation, the tree consumes 7–9 cores, and
throughput *falls*. Cores are available; each field simply costs more. PAL CVBS: its children are
pinned at 3.7–3.9 cores whatever `-t` is and only their duty dilutes — but nothing in its parent is
saturated either, so the residue is a dependency chain through the parent rather than a full lane.

### 7.2 Where a frame's memory traffic actually goes

`scripts/report_decode_traffic.py` wraps named stages in a per-thread `perf_event_open` group, so
each stage is charged the traffic it caused *minus* the traffic of the wrapped stages it called.
95% of the measured L2-miss traffic is named. Cross-checked against the same decode uninstrumented
under `perf stat`, differencing a 60-frame run against a 20-frame one: the wrappers cost 6% of the
L2 misses and 3.6% of the cycles.

The result overturned the earlier `perf record` symbol attribution by a factor of three. It had put
three quarters of a decode's traffic at field level and a quarter in the block demodulator; measured
in situ it is the other way round — **the block chain is 81% of a PAL CVBS frame's L2-miss traffic
and the transforms alone are 56%** (45% after §4 #8 and #9). The earlier figure was not wrong about
the block *in isolation*; it priced a microbenchmark in which the filter bank stays in L3 across 400
back-to-back calls, which it does not do inside a decode.

Under contention (whole process tree, steady state, a 140-frame run minus a 40-frame one):

| cell | fps | Gcycles/frame | Ginstructions/frame | IPC | DRAM fills/frame |
|---|---:|---:|---:|---:|---:|
| PAL CVBS `-t 1` | 3.43 | 1.472 | 4.509 | 3.06 | 3.83e6 (234 MiB) |
| PAL CVBS `-t 4` | 6.16 | 2.753 | 4.720 | 1.71 | 1.64e7 (1000 MiB) |
| PAL `--tbc` `-t 1` | 3.60 | 1.311 | 3.959 | 3.02 | 3.61e6 (221 MiB) |
| PAL `--tbc` `-t 4` | 7.16 | 2.246 | 4.173 | 1.86 | 1.36e7 (832 MiB) |

Solo, 41% of the L2 misses reach DRAM; at `-t 4`, 83% do. The stages that inflate most under
contention are the ones that stream a whole field once (`dropout_detect_demod` 1.95×,
`concatenate_blocks` 1.95×, `refine_linelocs_pilot` 2.64×) rather than the ones that work block by
block — a block's chain still has some cache to work in when eight processes share the L3; a
field-length pass has none.

One finding the instrument was not looking for, recorded and not acted on: each `decodefield` reads
`readlen // blocksize + 2` blocks, so adjacent fields' windows overlap by two blocks and **15.4% of
all block demodulation is done twice** (1796 demodulations of 1519 distinct blocks over 40
steady-state frames). At `-t 1` there is no block cache at all; at `-t N` each field job is a
separate process, so the overlap cannot be shared without shipping blocks between them.

### 7.3 Ceiling C is not a bandwidth wall, and the architecture is not the limit

The memory path itself was measured with preallocated buffers, in-place `np.add(a, b, out=c)` over
256 MiB arrays and a barrier so every process's window overlaps: **20.0, 20.5, 20.1, 19.8, 19.7
GB/s** at 1, 2, 4, 8 and 16 processes. The box's ceiling is ~20 GB/s of streamed traffic, it is flat
in core count, and a single core can consume all of it. (An earlier probe reporting 9.8 GB/s
allocated a fresh temporary every iteration and was measuring page-fault zeroing as much as DRAM.)

The plateau was originally derived from that ceiling. It does not close. Fills over the whole tree,
N independent serial PAL CVBS decoders:

| N | 1 | 2 | 4 | 8 |
|---|---:|---:|---:|---:|
| aggregate fps | 3.96 | 7.38 | **11.99** | 11.20 |
| DRAM fills per frame (MiB) | 266 | 368 | 608 | 1017 |
| DRAM fills (GB/s) | 1.11 | 2.85 | **7.64** | 11.94 |
| cycles per frame | 1.68e9 | 1.71e9 | 2.04e9 | 4.10e9 |
| instructions per frame | 4.98e9 | 4.85e9 | 4.86e9 | 4.82e9 |

and at the `-t 4` knee, 882 MiB/frame and 7.47 GB/s for PAL CVBS, 677 MiB/frame and 6.64 GB/s for
PAL `--tbc`. The counter counts fills, not writebacks, so every figure is a floor on real traffic.
Even so: **at the knee the box is moving 7.6 GB/s against a 20 GB/s path, and the curve is already
flat there.** Bandwidth cannot be what stops it at N = 4. What does is in the last two rows — the
same instructions per frame to within 4% across the whole curve, for 1.22× the cycles at N = 4 and
2.44× at N = 8, with fills per frame rising 3.8×.

> **Ceiling C, restated.** Not "20 GB/s of DRAM, reached at N ≈ 4", but: **past N ≈ 4 an added
> decoder raises DRAM traffic per frame faster than it converts cores into frames**, and it does so
> at a bandwidth well short of the path's capacity. Concurrency past the knee does not divide the
> work differently, it *manufactures traffic*: at N = 8 the eight 5.60 MiB hot sets are 45 MiB
> against 32 MiB of L3, each decoder's streams evict the others', and the extra fills buy stall
> rather than throughput. The lever is still bytes streamed per frame, but the target it must beat
> is L3 capacity per concurrent decoder, not the bus.

**The concurrency architecture is not the limit.** `-t N` does not scale to the physical core
count — every cell peaks at `-t 4` of 8 — but the pool is no longer what stops it:

- PAL `--tbc` at `-t 4` delivers **11.77 fps** and four *independent* serial decoders deliver
  **11.74**. Those are the two best PAL figures the box produces by any arrangement, and they agree
  to within 0.3%. The field-job architecture at its knee already extracts everything a perfect
  partitioning would.
- There is nothing above it to extract. Eight independent decoders return **11.29 fps, less than
  four do**, at the same instructions per frame for 2.4× the cycles.

That is what settles the batch-parallel design (§6, last row). Its throughput case rested entirely
on "roughly one serial decode per core" — ≈ 8 × 4.0 = 32 fps here — and its own best case, with no
orchestrator, no overlap and no seams, is 11.2. **The prize is at most the 17% PAL CVBS is short
of the independent-decoder curve, on one mode, on this box** — not the 2–3× the design assumed —
and that 17% is available from parent-side items already priced in §6. The design's *simplification*
case is a separate argument and is unaffected: it would retire the `FieldJobEngine`, the speculation
model, the stage-2 pool, the output pool, the block-cache prefetch, the `keep_demod` transport and
the view/key plumbing — roughly all of `parallel.py` except the ordered lane — in exchange for a
batch runner, an orchestrator, a segment format and a seam resolver, and would give up causal servo
semantics at seams. Nothing here argues for or against that on its own terms; it argues only that
it should not be undertaken expecting throughput.

Finally, the per-decoder hot set is now **5.60 MiB** against 11.5 (resident filters 11.17 MiB, LUT
0.02, 1.91 MiB read per block, 3.68 MiB of block temporaries), so 32 MiB of L3 holds 5.7 hot sets
where it held 2.8 — and the plateau is still at 4. That is the §3 lesson stated one last time from
the other end: the footprint halved and the knee did not move.

## 8. What is left, in order of what the evidence supports

1. **The `-t` auto default is above the measured optimum.** [`lddecode/main.py:504`](../lddecode/main.py#L504)
   computes `min(max(physical_cpu_count() - 2, 1), 10)`, which is 6 on the reference box; the
   optimum measured here is 4 in every cell. At `-t 6` PAL CVBS and NTSC are unchanged within the
   run-to-run spread (9.79 against 9.72; 14.53 against 14.62) but **PAL `--tbc` loses 6.3%** (11.07
   against 11.77) and the default costs **630 MB of peak tree RSS** (2762 against 2129). This is the
   one decoder change the final measurements directly support. It wants re-deriving from the knee
   and the per-process RSS, with a unit test over injected core and memory counts, and the knee
   stated as a property of the box rather than assumed to transfer.
2. **Bytes per frame inside the demodulator.** This is the remaining lever and it is a separate
   piece of work. The block chain is 81% of a frame's L2-miss traffic (§7.2) and is where the 608
   MiB/frame at the knee comes from. Half-rate video products (§6) are the largest single candidate
   and the highest-risk one — timing is the TBC's whole job, and that change halves the rate line
   locations are found at, so it needs a lineloc-delta distribution against the full-rate decode on
   the radius set before anything is committed.
3. **The 17% gap on PAL CVBS,** which reaches 9.72 fps at `-t 4` where four independent decoders
   reach 11.74. It is parent-visible: 216 ms/frame across five threads, the GIL held 58% of a
   frame, workers starving rather than saturating, and the busiest lane (`ld-output`, 83.5
   ms/frame) made of EFM `process` 29.5 + `downscale_cvbs` 21.3 + the DG band 8.9 + chroma-vs-luma
   7.8 + encode 5.5. That 17% is also the bound on the declined transport rewrite: it is the most
   a *perfect* parent could be worth on this cell.
4. **The 2T pulse crest measurement.** A 2T pulse is three and a half samples wide at 4fsc and
   `analysis/vits_measure.py` takes its crest by `argmax` plus a parabolic interpolation, which does
   not recover the true crest. That is what blocks taking the burst lock below `g ≈ 0.6`: one cut's
   reading steps bimodally from 90.60 to 86.51 IRE with where the lattice settles, while the decode
   underneath gets *better*. Once that measurement is phase-independent, `g = 0.5` is worth another
   8% of residual rms — and a rate term (a type-2 loop) would be worth more again, for the one disc
   in the corpus whose time base genuinely ramps.
5. **15.4% of block demodulation is done twice** (§7.2). The fix costs a transport and buys 15% of
   one stage; recorded so the size is known.

**The box.** Every figure here is one 5800X with one L3 size and one DRAM speed. The knees are
stated, not assumed to transfer: a part with more or less L3 per core moves them, and the harness
records the box.

## 9. Reproduction

All from the dev shell (`nix develop` — the `nix develop "path:$PWD"` form in `AGENTS.md` §7 fails
on this flake, because a `path:` source carries no git metadata):

```bash
# resident filters, the resample LUT, the bytes demodblock reads per block, temporaries
nix develop --command python3 scripts/report_working_set.py --json working_set.json

# one cell of the -t sweep, then N concurrent serial decoders over adjacent spans
nix develop --command python3 scripts/bench_decode_throughput.py \
  --capture <capture> --system pal --mode cvbs --threads 4 \
  --seek 5000 --length 1000 --out rows.jsonl
nix develop --command python3 scripts/bench_decode_throughput.py \
  --capture <capture> --system pal --mode cvbs --threads 1 --concurrency 8 \
  --seek 5000 --length 1000 --out rows.jsonl

# per-stage traffic attribution for one serial decode
nix develop --command python3 scripts/report_decode_traffic.py \
  --system pal --output cvbs -s 5000 -l 60 --warmup 20 <capture> /tmp/traffic

# fills per frame, solo or across a tree (user-space counters; paranoid=2 is enough)
nix shell nixpkgs#linuxPackages_latest.perf --command perf stat \
  -e cycles:u,instructions:u,ls_any_fills_from_sys.mem_io_local:u \
  -- python3 -m lddecode.main --pal -t 4 -s 5000 -l 150 <capture> /tmp/perf
```

Per-thread attribution needs `py-spy record --threads --subprocesses` (and `--gil` for GIL-held
share): `/proc` reports every Python thread as `python3`, so thread names are not available from it.
Note that `--subprocesses` sampling perturbs cells whose workers sit near saturation — a PAL `--tbc`
`-t 4` run measured 4.08 fps under the sampler against 10.22 unsampled — so those rows are for
attribution only, never for a delta.

## 10. The FFT round

§8 item 2 — bytes per frame inside the demodulator — was carried out, together with the
precondition it set. It is recorded separately in [`fft-optimisation.md`](fft-optimisation.md):
the half-rate FM discriminator, block reuse across adjacent field jobs, and the shared filter
segment. In one line: serial decoding **+7.7% PAL CVBS, +13.5% PAL `--tbc`, +14.8% NTSC**, and the
PAL hot set per block **7.36 → 5.74 MiB**, which is worth −11.1% of DRAM fills per frame among
four decoders and nothing at all to a decoder running alone.

## 11. Provenance

This document replaces four working documents, removed alongside it and recoverable from git
history:

| Document | What it was | Where its content went |
|---|---|---|
| `decode-memory-profile-analysis.md` | the first analysis: why concurrency stopped paying at three decoders, and the L3 hypothesis | §3 (the hypothesis and its refutation), §7.3 (the corrected 20 GB/s probe) |
| `decode-working-set-plan.md` | the plan built on that hypothesis; its first three phases landed, the rest were retired | §4 rows 1–5, §3 |
| `decode-throughput-plan.md` | the re-examination after the premise was falsified, and the four phases that followed it | §4 rows 6–10, §5, §6, §7 |
| `batch-parallel-decode-plan.md` | a design to replace the field-job pool with independent per-range decoders; never implemented | §6 (last row), §7.3 |

The measurements were taken across seven working sessions; the raw harness rows, counter logs and
the diffs of the three reverted changes are under `docs-planning/` (local, untracked).
