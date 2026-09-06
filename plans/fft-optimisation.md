# Optimising the FFT implementation: what changed, why, and what it bought

A record of the round of work that moved the demodulator's FFT path onto a half-rate analytic
signal, cut the filter bank down, and shared what was left between workers. It is not a plan —
everything here is landed, reverted with its reason, or declined with the figure that decided it.
It replaces the working documents that tracked the work as it went (§9).

**Result in one paragraph.** Serial decoding is **7.7% faster on PAL CVBS, 13.5% on PAL `--tbc`
and 14.8% on NTSC CVBS**, and the demodulator's hot working set per block falls from 7.36 to
**5.74 MiB** on PAL, so 5.6 decoders' hot sets fit this box's 32 MiB of L3 where 4.3 did. That
footprint is worth nothing to a decoder running alone and **10 to 11% of every frame's DRAM fills
among four or eight of them**. One phase changes output bytes; it is the half-rate discriminator,
and the change is confined to one disc where it moved a pre-existing calibration bug into view.
That bug was then diagnosed to its root and fixed, and the VITS radius lane now has **no real
failures on any cut** — better than the tree this work started from.

---

## 1. Why the work was done

The decode-performance record (`plans/decode-performance.md` §8) left "bytes per frame inside the
demodulator" as the next item the evidence supported, with a precondition attached: a
lineloc-delta distribution against the full-rate decode on the radius set, measured before anything
was committed. That precondition is now met and the item is closed.

The premise is one the earlier throughput work established and this round confirms from the other
direction: **on this decoder, footprint claims have to be measured among N concurrent decoders, and
resident size predicts nothing.** A change that removes megabytes from a worker's hot set buys
nothing solo, because L3 was already absorbing it, and buys double digits once the cache is
genuinely contended.

## 2. What landed

Five changes, each gated on the unit suite and then on a 42-output identity recipe before the next
was started.

| # | Change | Where | Measured |
|---|---|---|---|
| 1 | Developer controls — `LDDECODE_BLOCKLEN`, `LDDECODE_BLOCK_LRU_STATS`, `LDDECODE_SHARED_FILTER_STATS`, `LDDECODE_NO_SHARED_FILTERS` — and per-block accounting in the working-set reporter | `params.py`, `parallel.py`, `scripts/report_working_set.py` | no decode path touched; every measurement below exists because these do |
| 2 | Byte-identical deletions in the block chain: filtering against half-spectra, the audio slice taken by conjugate symmetry, thread-local scratch, five construction-only filters retired | `rfdecode.py`, `filters.py` | PAL hot set per block 7.36 → 7.24 MiB, resident bank 12.28 → 9.28 MiB; **all 42 identity outputs unchanged** |
| 3 | FM discriminator on the half-rate analytic signal, with the rate correction `exp(+i·pi·f·T)/cos(pi·f·T)` | `rfdecode.py` | PAL hot set **7.24 → 5.74 MiB**, NTSC 6.86 → 5.49; L3 holds **5.6 decoders against 4.3**; `-t 1` **+7.7% PAL CVBS, +13.5% PAL `--tbc`, +14.8% NTSC**; **fills/frame −11.1% among four decoders, −9.8% among eight** |
| 4 | Block reuse across adjacent field jobs, pairs of jobs pinned to one worker | `parallel.py` (`AffinityPool`, `WorkerBlockLRU`) | block demodulations per distinct block **1.1829 → 1.0922** (−7.7%); costs 6.51 MiB/worker on PAL; **byte-identical** |
| 5 | Shared-memory filter segment: one mapping per decode instead of one bank per worker | `shared_filter_bank.py`, `parallel.py`, `rfdecode.py` | 3.47 MiB saved PAL, 3.97 NTSC; **fills/frame −3.3%** at `-t 4` and `-t 6`; throughput unchanged; **byte-identical** |

### 2.1 The half-rate discriminator, which is the round's result

After the one-sided RF filter a block's spectrum is non-zero only over 0–20 MHz, and a complex
signal at 20 MSPS spans exactly that band. The `blocklen // 2`-point inverse of the positive bins
is therefore twice the even samples of the analytic signal with nothing lost, and the
discriminator, the clip, the centring and the video transform can all run there. The batched
`irfft(..., n=N)` that already turned the filtered stack back into samples doubles as the
resampler, so the record array, `blockcut`, `F05_offset` and every downstream consumer stay at the
input rate. The one bin that cannot come along is `blocklen / 2` — at 20 MSPS that frequency is DC,
where the RF band-pass is 60 dB down.

**The rate correction has three factors, not the two the design named.** The interpolation scaling
(every bin doubles except the top one, which the Hermitian extension already counts twice); the
boxcar tilt, since a conjugate-product discriminator reports the phase advance across one of its
own sample intervals and the ratio of the two boxcars has the closed form
`sinc(f·T)/sinc(f·2T) = 1/cos(pi·f·T)`; **and the half-sample advance that boxcar also carries**. A
boxcar of width `T` is `sinc(f·T)·exp(−i·pi·f·T)`, centred half a window back, so running it at
50 ns delays the products by a further 12.5 ns as well as tilting them. Without the phase term the
amplitude test still passes and every channel lands half an input sample late — 20 degrees on the
4.43 MHz burst.

Half-rate against full-rate on a synthetic multiburst:

| burst | uncorrected | corrected |
|---:|---:|---:|
| 0.5 MHz | −0.007 dB | 0.000 dB |
| 3.0 MHz | −0.244 dB | 0.000 dB |
| 5.0 MHz | −0.694 dB | −0.006 dB |
| 5.5 MHz | −0.837 dB | 0.000 dB |

Both columns are asserted in `tests/unit/test_demod_half_rate.py` — the corrected one within
0.05 dB and the uncorrected one at its measured value — so the correction cannot silently rot and
the first test has teeth. `computedelays` agrees with the pre-round tree to 2e-5 of a sample on
`video_sync` and `video_white` on both systems.

The `full_rate_demod` constructor keyword stays. Retiring it was on the plan and should not happen:
it is the control arm that `test_demod_half_rate.py` and three tests in `test_demod_fft.py` are
held against, so retiring it deletes the executable proof that the two chains agree. It is a
constructor keyword and deliberately not plumbed to workers, so no decode can end up with a mix.

### 2.2 Block reuse, and the group size

Adjacent field jobs overlap in the RF blocks they need. Pinning pairs of consecutive jobs to one
worker and giving each worker a small block LRU removes 7.7% of block demodulations
(1.1829 → 1.0922 per distinct block) for 6.51 MiB per worker on PAL. A job either finds a cached
block or does not, and the bytes out are the same either way.

Longer groups were left as an open parameter and are now measured:

| | demods per distinct block | `-t 4` fps | `-t 6` fps |
|---|---:|---:|---:|
| pairs (shipped) | 1.0922 | 4.25 | 4.18 |
| groups of 4 | 1.0512 | 4.17 (−1.9%) | 3.81 (**−8.8%**) |

Groups of four deliver the extra block-demodulation saving they promised and lose 8.8% of
throughput at `-t 6` to the queueing that buys it: four consecutive jobs behind one worker leaves
six workers waiting on group boundaries. **`group_size` keeps its default of 2**, now with a
measured answer beside it rather than an open question.

### 2.3 The shared filter segment

Every worker used to build and hold its own copy of the filter bank. The invariant part —
`RFVideo_half`, `Frfhpf_half`, `Fefm_half`, PAL's `FcutPAL_half`, the MTF base and the two audio
stage-1 filters — plus two slots per family for the filters a job decides now live in one segment
that every worker maps read-only. `FVideo_rfft32` and its `FVideo_rfft_dc` share one slot, because
a worker that read the stack from a slot and rebuilt the DC gains privately would demodulate
against two different parameter sets.

The saving in resident bytes is exact and small: 3.47 MiB on PAL, 3.97 on NTSC. That is below what
a live decode can be sampled at (peak pool `Pss` reads 1,291.8 MiB against 1,291.3 MiB). The reason
to want it is L3, and that is measurable: with the segment switched off via
`LDDECODE_NO_SHARED_FILTERS=1`, same tree and same bytes out, DRAM fills per frame rise **3.3%** at
both `-t 4` and `-t 6`, with the two arms' ranges disjoint at `-t 6`. Cycles and wall time both sit
inside a percent, which is exactly what a change that only relocates where numbers live should do.

This is the only shared mutable state across processes anywhere in the decoder, and it is the
largest and riskiest diff in the round for the smallest measured return. It is kept because it is
byte-identical, heavily tested, and the only mechanism that stops every worker holding its own copy
of the bank as core counts grow — but the case for the other decision is real and worth recording:
3.3% of one resource and 4 MiB of memory is a thin return for a cross-process publication protocol
and slot lifecycle in a decoder maintained by very few people.

## 3. What it bought

Pre-round tree against the finished one, on the measurements that judge it:

| | before | after |
|---|---:|---:|
| PAL hot set per block | 7.36 MiB | **5.74 MiB** |
| NTSC hot set per block | 7.11 MiB | **5.49 MiB** |
| PAL decoders whose hot set fits 32 MiB of L3 | 4.3 | **5.6** |
| DRAM fills per frame, one decoder | 4,947,230 | 4,958,100 (+0.2%) |
| DRAM fills per frame, four decoders | 10,937,300 | **9,717,970 (−11.1%)** |
| DRAM fills per frame, eight decoders | 17,201,600 | **15,522,800 (−9.8%)** |
| NTSC CVBS `-t 1` / `-t 4` / `-t 6` | 5.45 / 9.03 / 9.16 fps | **6.25 / 10.62 / 10.61 (+14.8 / +17.7 / +15.8%)** |
| PAL CVBS `-t 1` | 4.13 fps | **4.46 (+7.7%)** |
| PAL `--tbc` `-t 1` | 4.33 fps | **4.91 (+13.5%)** |
| PAL CVBS / `--tbc` at `-t 4`, `-t 6` | — | no difference (see §7) |
| block demodulations per distinct block | 1.1829 | **1.0922** |
| cycles per frame, one decoder | 2.373e9 | **2.226e9 (−6.2%)** |

**The fills result is the one to carry forward.** Solo, the smaller hot set is worth +0.2% of DRAM
fills — nothing. Among four and eight decoders it is worth 10 to 11%. That is the same shape the
earlier resample-LUT work found, now confirmed on a change moving in the other direction.

## 4. The defect this work found, and fixed

The half-rate tree put two VITS radius lanes red on one disc, and the cause is not the
demodulator. `lddecode/decoder.py` differed from the pre-round tree by 23 lines, none of them in
the calibration loop. What differs is that the 2T servo's consistency gate,
`np.std(ests) > mtf_servo_scatter` with the gate at 0.350000, is straddled by both trees on
`domesday-ds2-community-north`:

| | evaluations | min scatter | margin | adopts |
|---|---:|---:|---:|---:|
| pre-round tree | 64 | 0.361798 | +3.37% | no |
| half-rate tree | 67 | 0.340984 | −2.58% | twice |

`_servo_engaged` latches on the first acceptance, so two evaluations of a noise statistic 2.6%
under a fixed threshold change every frame of the decode. On the `-outer` cut **the roles reverse**
— the pre-round tree adopts −0.724 and the half-rate tree adopts nothing.

### 4.1 The root cause

Engagement is not the fault; acting on a stale bound is.

The multiburst's chroma-band verdict (`_imtf_flat_band`) is a *strength*: the inverse-MTF strength
at which the decoded chroma band would measure flat. It bounds the burst servo, which otherwise
reads a disc-mastering choice as channel loss and winds about 1.2 strength units chasing it.
`_imtf_strength_for_flat_band()` takes each pooled sample back to what it would have read with no
video EQ and no inverse MTF, using the EQ and the strength that field was decoded under — so a pool
spanning a trim of either still yields an absolute answer. **`mtf_level` is the one term it does
not correct for, and `mtf_level` is a pre-demod HF boost: it moves the very band the verdict
describes.**

An adoption therefore leaves the held verdict describing a channel that no longer exists. That
would be survivable if the verdict were re-measured promptly. It is not: republication is rate
limited to `VEQ_MIN_ADOPT_FIELDS` = 100 fields, and a 30-frame radius cut is 60. **On any capture
under 50 frames the first verdict published stands for the whole decode.** Instrumented, the whole
fault is six lines:

```
publish flat_band=0.5349  pool=3  mtf_levels=[0.0]      <- measured once, before the adoption
MTF level 0.000 -> -0.667 (2T servo)
call flat=-0.2210 held=0.5349 mtf=-0.667 -> STOP rate limit
call flat=-0.2406 held=0.5349 mtf=-0.667 -> STOP rate limit
call flat=-0.2574 held=0.5349 mtf=-0.667 -> STOP rate limit
adopt current=0.0000 estimate=0.3187 ceiling=0.5349      <- bounded by the stale verdict
```

The multiburst reads the band as wanting −0.22 and then −0.27 from the field after the adoption
onward. Every reading is discarded, the ceiling stays at the +0.535 measured beforehand, and the
burst servo winds +0.319 onto a band the instrument is concurrently measuring as hot: about 2 dB of
excess chroma, `ceiling/saturation` at 112.4%, seven checks red.

### 4.2 The fix

Carry the verdict across the adoption instead of leaving it behind. The flat band is a strength,
the level change moves the channel's HF by a known amount, and `mtf_deemp_feedforward` is the
conversion the adopted strength is already corrected by a few statements later in the same
function:

```python
if self._imtf_flat_band is not None:
    shifted = self._imtf_flat_band + self.mtf_deemp_feedforward * delta
    if shifted < self._imtf_flat_band:
        self._imtf_flat_band = max(shifted, min(0.0, self._imtf_flat_band))
```

The clamp is not decoration. **A prediction may withdraw a boost and may never open or deepen a
cut** — this filter's standing rule rather than a new one, since `_imtf_ceiling()` already spends
the negative half on the multiburst's measurement alone.

### 4.3 Designs that were measured and rejected

Recorded because each looked right, and the comment in `decoder.py` carries them so they are not
retried:

| design | measured |
|---|---|
| **Do nothing** (the fault) | `-middle`: 7 checks red |
| **Hold the burst servo** until the multiburst republishes | **stalls outright** on `ds1-outer`, whose pool holds 5 samples against the 6 `VEQ_MIN_SAMPLES` wants after calibration, so the verdict never republishes: differential gain 0.067 → 0.117 |
| **Drop the rate limit** so a real measurement lands sooner | `ds1-outer` republishes at −0.525 and applies that cut: differential gain 0.067 → 0.117, nothing else on the cut improves |
| **Shift, unclamped** | the prediction reaches −0.475 and the ceiling engages a cut on a number nothing measured: differential gain 0.067 → **0.157** |
| **Shift, clamped** (adopted) | `-middle` 7 red → **0**; no cut regresses |

A bound that can go unmeasurable has to degrade to a prediction — not to a stall, and not to a free
hand.

One further hypothesis was eliminated early and is recorded so it is not suspected twice: the
feed-forward floor at `min(0.0, current)` accounts for 0.003 of the 0.32 strength at issue, and
removing it leaves the cut failing 7 of 51.

### 4.4 Result

| | before | after |
|---|---|---|
| `domesday-ds2-community-north-middle`, real failures | 7 | **0** |
| whole VITS radius lane, real failures | 2 cuts | **none, on any cut** |
| `gain_ratio/PAL` on that cut | 0.340 (pre-round 0.273, both out of band) | **0.299** against a 0.300 nominal |
| `ceiling/saturation` | 112.4% | **98.9%** |
| `packet_4/response` | +1.70 dB | **+1.07 dB** (band ±1.25) |

The lane is better than the tree this work started from, not merely better than the tree before the
fix: `gain_ratio` was 0.273 before the round and failed low. The now-passing entry for that cut is
deleted from `analysis/vits_known_deviations.toml`, as that file's contract requires.

**The two `-outer` entries are deleted as well, and that took a measurement to justify.** They pass
because this tree does not engage the 2T servo on that cut, where the pre-round tree does. Deleting
an entry asserts the check must keep passing, so the question was whether that non-engagement is a
property of this tree or a coin flip — the same file already records this servo flipping once
before, when the PAL MTF rotation-rate fix landed. Instrumenting the gate across all 21 radius cuts
settles it: on `-outer` **none of the 63 evaluations falls under the gate**, minimum 0.3594 against
a gate of 0.3500. There is no marginal evaluation there to turn over. The alternative — leaving a
lane permanently red on a contract violation the runner is designed to force — is worse than an
entry that may one day need writing again with a fresh reason, which is what that file is for.

With those two gone the whole VITS radius lane is green: **96 of 96 CTest, 48 of 48 in the lane
itself, and every other one of the 1,323 conformance checks across the 21 cuts reads exactly what
it read before.**

### 4.5 Making the gate itself robust: built, measured, rejected

The remaining complaint about the gate is that engagement latches on a single evaluation, so one
under-gate reading decides every frame that follows. Instrumented across the lane, that is real:
on `domesday-ds1-community-north-outer` only 5 of 96 evaluations fall under the gate, the longest
run is 4, and the servo engages on the first of them. Discs that carry a usable ITS look nothing
like that:

| population | consecutive under-gate runs |
|---|---|
| discs the servo should drive (10 cuts) | 42, 42, 44, 70, 70, 79, 79, 94, 94, 182 |
| the two marginal Domesday cuts | 4 (of 96 evaluations), 11 (of 66) |
| cuts carrying no usable ITS (7) | the gate is never reached |

The populations are four times apart, so requiring *n* consecutive under-gate evaluations before
the first engagement separates them cleanly, with n=16 sitting between them rather than at either
edge. **It was built and measured, and it turns one red lane into eight.** Delaying engagement by
15 fields costs the warmup, which is exactly where the servo has to converge before the adoption
rate limit slows it to one step per 100 fields:

| cut | cost of the delayed engagement |
|---|---|
| `ggv1011-side1-inner` | **6 real failures** — both chroma bars, three multiburst packets, `gain_ratio` |
| `industrial-lv-side1-middle`, `-outer` | `pulse_2t` fails |
| `dolby-surround-side1-inner` | `pulse_2t` fails |
| `domesday-ds2-...-middle` | `gain_ratio` 0.299 → 0.273, undoing §4.2 |
| `domesday-ds1-...-outer` | `gain_ratio` 0.285 → 0.272 |

Engaging early is not incidental to this servo; it is what lets it converge at all. **The latch is
the price of that, and on this evidence it is worth paying** — the one cut where a short run
engages the servo spuriously passes its lane regardless. The gate keeps its shipped form.

## 5. What was built, measured and reverted

**A free-threaded thread engine.** Built in full on a free-threaded CPython 3.14 shell that had to
be constructed from source (eight nixpkgs overrides; nothing free-threaded is cached on any
channel), passing 2,029 unit tests, `ctest -R parallel` 19 of 19, all 42 identity hashes on both
interpreters, and producing decodes byte-identical to the process engine. It measured **11% slower**
(3.83 against 4.31 fps).

The cause is upstream and not fixable here: `rfdecode.py` opens with `import scipy.fft`, and SciPy
1.16.3's `scipy.linalg._fblas` has not declared free-threading safety, so that import re-enables
the GIL and the engine's premise disappears. The process engine is byte-identical and within noise
on 3.14t, so the interpreter itself is free — this can be revisited if SciPy ever declares safety.

## 6. What was priced and declined

| Change | Priced at | Why declined |
|---|---|---|
| Affinity groups of four instead of pairs | block demodulations 1.0922 → 1.0512 (−3.4% more) | costs **8.8% of throughput at `-t 6`** |
| Block length 16384 | +0.2% NTSC, −0.9% PAL; 68 MB less peak RSS | inside the spread both ways; no reason to move |
| Block length 8192 | −3.2% NTSC, **−6.6% PAL**; 89 MB less peak RSS | the only sweep figure outside the threshold, and in the wrong direction |
| Retiring the `full_rate_demod` escape hatch | 11 branches in `rfdecode.py` | it is the control arm the half-rate equivalence tests are held against |
| Requiring *n* consecutive clean evaluations before the 2T servo engages | separates the marginal cuts from the good ones four times over | costs the warmup: 1 red lane becomes **8**, six of them real failures on one cut (§4.5) |

Each block length was also checked with `cvbs_verify`, since block length is a filter-design
parameter and not just a buffer size: all three pass. **The default stays 32768.**

## 7. How it was verified, and what could not be measured

**Identity.** Every phase after the first was held against a 42-output baseline — seven decodes
over three captures, hashing every `.tbc`, `.cvbs`, `.efm`, `.wav`, `.json` and `.meta` output.
Phases 1, 2, 4 and 5 reproduce all 42 exactly. Phase 3 is the only change to output bytes, and
after the servo fix **36 of the 42 are unchanged** against it: every EFM stream, every audio track,
every video and EFM metadata file, and both non-Domesday captures entirely. The six that move are
one Domesday cut's `.cvbs` and `.dropouts.meta` at `-t 1`, `-t 4` and under
`--V4300D_coherent_subtract` — precisely where the servo engages.

**Bit-identity across thread counts.** Every `compare-*-parallel-*` test passes, so the guarantee
in `AGENTS.md` §4.4 — a `-t N` decode is bit-identical to the serial decode — holds throughout.

**Conformance.** The full CTest suite passes, **96 of 96**, with the VITS radius lane green on all
21 cuts. No tolerance was widened and no assertion removed; the three known-deviation entries this
work deletes are deleted because their checks now pass, which is what that file's contract asks
for.

**What could not be measured.** The long reference captures live on a NAS mount that is empty on
this box, and nothing in `testdata/` is more than 90 frames. The PAL cells at `-t 4` and `-t 6` are
therefore 30-frame decodes — about seven seconds — which never reach steady state, and they show no
difference where NTSC, on the only capture long enough, keeps +17.7% and +15.8%. **A long PAL
capture at `-t 4` is the one measurement that would close this round**, and the distinction it
would settle is not small: "the gain is serial-only on PAL" against "the cell was too short to see
it".

## 8. Reproduction

The developer controls added by change 1 are documented in `docs/user-guide/scripts.md`. All are
off by default and none is on a decode path:

```sh
# working set per block, and the resident bank, per system
python3 scripts/report_working_set.py --system pal

# demodulations per distinct block: the figure that judges block reuse
LDDECODE_BLOCK_LRU_STATS=1 ld-decode -t 4 ... 2>&1 | grep block-lru

# the shared filter segment on against off, same tree, same bytes out
LDDECODE_NO_SHARED_FILTERS=1 ld-decode -t 4 ...

# block length sweep
LDDECODE_BLOCKLEN=16384 ld-decode ...
```

DRAM fills per frame, which is the measurement that judges the footprint work, needs `perf` — not
in the dev shell, so it is invoked by absolute store path with the dev shell's own interpreter
pinned:

```sh
perf stat -e cycles:u,instructions:u,ls_any_fills_from_sys.mem_io_local:u ld-decode ...
```

Measurement rules that these figures depend on, and that reproducing them requires: interleave the
two arms inside each round so session drift cannot land on one of them; discard a warm-up round;
run on an otherwise idle box; report post-setup fps, which excludes filter construction and JIT
warm-up; and treat a difference under 5% as no difference.

## 9. Provenance

This document replaces the working documents that tracked the round as it went — the design note,
the phase-by-phase implementation plan, and the measurement records for each phase's conformance,
throughput, fills, block-length and free-threading work. All were local and untracked. Their
figures are reproduced above; the raw harness rows and counter logs were not retained.

The round's own record previously sat as §10 of `plans/decode-performance.md`, which now points
here instead.
