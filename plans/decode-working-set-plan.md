# Decode working-set reduction — implementation plan

Goal: raise the decoder's concurrency ceiling by shrinking what one decoder keeps hot in cache and
removing per-block work that recomputes constants, measured at every step on one committed harness.
The concurrency architecture is not touched until the working set is small enough that the ceiling
is again set by core count; a dedicated take-stock phase decides whether that point has been reached
before any further work is committed.

The guiding decision: **fix single-decoder efficiency first, then expand threads.** Phase 0 of
[`plans/batch-parallel-decode-plan.md`](batch-parallel-decode-plan.md) established that on an
8-core box PAL CVBS throughput plateaus at two workers however the concurrency is arranged — eight
independent serial processes and one process with eight workers land on the same figure — because
two decoders' working sets fill the 32 MiB shared L3 and a third evicts them. §1.1 measures the
same ceiling from the other side: independent decoders stop adding throughput between two and four.
Every byte removed from one decoder therefore raises the ceiling for `-t N` as it stands, for any
future batch design, and for a single pipeline alike, which is why this work comes before any of
them.

Sources:
- Measurements this plan rests on:
  [`plans/decode-memory-profile-analysis.md`](decode-memory-profile-analysis.md), and
  `docs-planning/decode-throughput-hotspot-analysis.md` (local, untracked). Every figure the plan
  depends on is restated in §1.
- The stopped plan and its Phase 0 results:
  [`plans/batch-parallel-decode-plan.md`](batch-parallel-decode-plan.md) §5.3.
- Identity and threading rules: `AGENTS.md` §4.4, §5.3.3. Test lanes: `TESTING.md` "What the
  functional lane covers"; conformance:
  [`docs/technical/vits-conformance.md`](../docs/technical/vits-conformance.md).
- Resample kernels: `lddecode/dsp.py` (`scale_field`, `scale_positions`); block demodulator:
  `lddecode/rfdecode.py` (`demodblock`); output lattices: `lddecode/cvbs.py`, `lddecode/field.py`.

---

## 1. What was measured

Ryzen 7 5800X: 8 physical cores, 16 SMT threads, 32 KiB L1d and 512 KiB L2 per core, **32 MiB L3
shared**, dual-channel DDR4. PAL material `Domesday_DD86-DS2_NationalA` at `-s 5000`; NTSC `Bambi`.
Post-setup fps as the decoder reports it.

| Mode | 1 serial | 8 concurrent serial | `-t 8` | `-t 6` |
|---|---:|---:|---:|---:|
| PAL CVBS | 2.65 | 5.05 | 5.02 | 5.16 |
| PAL `--tbc` | 2.68 | 8.72 | 7.17 | 7.83 |
| NTSC CVBS | 2.98 | 12.48 | 10.84 | 10.80 |

PAL CVBS `-t` sweep, same span, three run lengths — the plateau starts at `t=2` at every length:

| `-l` | t1 | t2 | t3 | t4 | t6 | t8 | t10 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 150 | 2.57 | 3.85 | 3.89 | 3.86 | 3.77 | 3.84 | 3.83 |
| 1000 | 2.77 | 4.77 | 4.75 | 4.61 | 4.72 | 4.59 | 4.74 |
| 2000 | 2.65 | — | — | — | 5.16 | 5.02 | — |

N independent serial PAL CVBS decoders, 150 frames each — the second costs 10%, the third and
fourth a third, and past four the aggregate is flat and then falls:

| N | 1 | 2 | 4 | 6 | 8 | 12 | 16 |
|---|---:|---:|---:|---:|---:|---:|---:|
| aggregate fps | 2.53 | 4.56 | 6.90 | 6.78 | 6.49 | 6.60 | 5.81 |
| per-process efficiency | 100% | 90% | 68% | 45% | 32% | 22% | 14% |

What is not the cause: SMT (pinning one process per physical core is worse, 4.75 vs 5.17 fps);
storage (NFS delivers 934 MB/s to eight readers against ~30 MB/s demand); raw DRAM bandwidth alone
(flat at 9.8 → 8.4 GB/s from 1 to 16 workers — one thread saturates it, so nothing that must reach
DRAM gains from more cores).

What is the cause — one decoder's hot working set, ~12 MiB:

| Component | Size | Access pattern |
|---|---:|---|
| Filter bank, mostly `complex128`, 32768-point (`rfdecode.py`) | 11.0 MiB PAL / 10.0 MiB NTSC resident; **2.53 MiB read per 32 KiB block**, both systems | sequential, once per block |
| Sinc resample LUT `downscale_sinc_lut`, 65537 × 16 `float32` | **4.00 MiB** | one 64-byte row per output sample, ~1 MiB stride: one cache miss per output sample, ~43 MiB/frame PAL TBC, ~86 MiB/frame PAL CVBS |
| Live temporaries in `demodblock` (no loop fusion) | **5.00 MiB PAL / 4.62 MiB NTSC** peak live | one full-blocklen array per multiply |

Hot set per decoder: **11.5 MiB PAL, 11.2 MiB NTSC**. Every full-blocklen `complex128` array is
512 KiB — sixteen L1d's and exactly one L2 — so no stage's operands fit in private cache. Two
decoders (23 MiB) fit L3; three (35 MiB) do not, which is where the plateau at `t=2` comes from.

Costs found that are avoidable without changing what the decoder computes:

| Finding | Where | Measured |
|---|---|---|
| Sinc LUT 256× too large: 256 phases *with* interpolation is 16 KiB and indistinguishable | `dsp.py:105-217`, `sinc_lut.npz` | 105.8 dB below signal for both 65536-nearest and 256-interpolated; 57.7 dB for 256-nearest |
| `scale_positions` has no `cache=True`; JIT-compiled in every process, every run | `dsp.py:169` | **done (§4)**: 1.99 s compile becomes a 4 ms cache load; 1.83 s off every process that resamples |
| `Filters["MTF"] ** mtf_level` recomputed per block; a 32768-point complex `pow` and a 512 KiB temporary, for a value constant over ≥100 fields | `rfdecode.py:1423` | 0.308 of 2.516 ms per block: **12.3% of `demodblock`**. **Done (§4)**, and the estimate understated NTSC: its `MTF` is `complex128`, so the `pow` is **2.29 of 5.18 ms**, and holding it takes NTSC CVBS `-t 1` from 3.01 to 4.83 fps |
| Chroma-DG correction transforms whole fields at hostile lengths: CVBS field B 354,689 is prime, field A carries a factor 563; `next_fast_len` is 354,816 | `field.py:164` | CVBS ~103 ms/frame and TBC ~62 ms/frame in four transforms; ~12 ms padded (2.15/3.77 ms per `rfft`/`ifft` at 354,816) |
| Filter bank stored `complex128` for 16-bit-in / `float32`-out data | `rfdecode.py` filter setup | resident 11.0 → 5.5 MiB, but read per block only 2.53 → 1.27 MiB and hot set 11.5 → 10.3 MiB; no gain in isolation (scipy's `complex64` `ifft` is slower, 0.352 vs 0.293 ms) — the value is footprint under contention only |
| PAL CVBS resamples every field twice: the TBC picture is computed (`decode_stage2`) then discarded; NTSC reuses it because its 4fsc is line-locked (910.0000/line) | `decoder.py:2644`, `cvbs.py:_emit_frame` | `field.py:downscale` is 3.0% of serial time; the cost is footprint, not cycles |
| Post-demod video carried at 40 MSPS for a 6.3 MHz (PAL) / 4.5 MHz (NTSC) band; EFM as `int16` at 40 MSPS for a 4.3218 Mbit/s channel; the audio path already decimates by spectrum slicing | `rfdecode.py:demodblock`, `filters.py:188` | 3.17× / 4.44× the LPF Nyquist |

### 1.1 The Phase 0 baseline

Recorded by [`scripts/bench_decode_throughput.py`](../scripts/bench_decode_throughput.py) on the
box above, PAL `Domesday_DD86-DS2_NationalA` and NTSC `Bambi`, `-s 5000 -l 1000`, one cell at a
time with nothing else running. Post-setup fps as the decoder reports it; RSS is the peak over the
whole process tree, sampled twice a second. Every later phase compares against these rows.

Run-to-run spread, three repeats of PAL CVBS `-t 6`: 4.57, 4.73, 4.68 fps — **3.4%** between the
slowest and the fastest. A phase that moves a cell by less than that has not moved it.

| Cell | `-t 1` | `-t 2` | `-t 4` | `-t 6` | `-t 8` |
|---|---:|---:|---:|---:|---:|
| PAL CVBS, fps | 2.71 | 4.67 | 4.66 | 4.79 | 4.81 |
| PAL CVBS, peak tree RSS (MB) | 1015 | 1860 | 2503 | 3071 | 3591 |
| PAL `--tbc`, fps | 2.82 | 5.43 | **7.38** | 6.99 | 6.69 |
| PAL `--tbc`, peak tree RSS (MB) | 760 | 1635 | 2357 | 2973 | 3836 |
| NTSC CVBS, fps | 3.01 | 5.56 | 9.15 | 10.01 | **10.50** |
| NTSC CVBS, peak tree RSS (MB) | 751 | 1353 | 1847 | 2452 | 2958 |

N independent serial PAL CVBS decoders over adjacent 1000-frame spans:

| N | 1 | 2 | 4 | 8 |
|---|---:|---:|---:|---:|
| aggregate post-setup fps | 2.81 | 4.79 | 5.96 | 5.90 |
| per-process efficiency | 100% | 85% | 53% | 26% |
| peak tree RSS (MB) | 957 | 1910 | 3771 | 7579 |

The `-t` sweep at `-l 1000` reproduces §1's rows within 4.6% (`-t 8`, the one cell outside the 3.4%
spread; every other cell is within 2.2%). Two things in it are sharper than §1 states, and both
matter to what the later phases are for:

- **The plateau is PAL CVBS's, not the decoder's.** PAL CVBS is flat from `-t 2` (4.67 → 4.81
  across `-t 2`…`-t 8`, all within the run-to-run spread). PAL `--tbc` scales to `-t 4` and then
  *falls* — 7.38 at `-t 4`, 6.69 at `-t 8`. NTSC CVBS scales all the way to `-t 8`, at 3.5x its
  serial rate. So the ceiling moves with how much a decoder keeps hot, which is what this plan
  changes, rather than sitting at a fixed thread count.
- **The concurrent-serial knee is between 2 and 4**, not at 2: the second decoder costs 15% and the
  fourth is where the aggregate stops rising. That is the 11.5 MiB hot set against a 32 MiB L3 —
  two fit, three do not — measured from the other side.

## 2. Rules for every phase

- **Measure on the harness, not by hand.** Every task that claims a throughput or footprint change
  lands with a before/after row from Phase 0 Task 1's harness, on the same captures and spans.
- **Separate what changes bytes from what does not.** A task that alters output (Phases 2, 3, 6)
  re-records its byte baselines in a commit containing nothing else, after the conformance lanes
  have passed on the change. A task that must not alter output (Phases 1, 5) is gated on
  byte-identity with the previous baseline.
- **`-t 1` and `-t N` stay bit-identical throughout** (`AGENTS.md` §4.4). Nothing here touches
  the speculation model, so the `compare-*-parallel-*` lanes are a regression gate, not a target.
- **Conformance is the quality gate.** `conformance-*-vits` verdicts and quality tables stay within
  their bands, with no widening of `analysis/vits_known_deviations.toml`.
- **Name things by what they are.** New modules and options describe the decoder's behaviour, never
  the phase that introduced them.

## 3. Phase 0 — baseline and instruments

No decoder changes. Puts the measurements on a footing every later phase can be compared against.

**Task 1 — commit the throughput harness.** A script under `scripts/` (beside `bench_rf.py`) that
runs one `(system, mode, -t, -s, -l, capture)` cell a stated number of times through
`lddecode.main`, reads the decoder's own post-setup fps line, samples the process tree's RSS, and
writes one JSON row per cell. It shells out with an argument list (`shell=False`) and touches no
decoder code.
*Acceptance:* three repeats of the PAL CVBS `-t 6 -l 1000` cell agree within a stated
run-to-run spread; the §1 tables reproduce within that spread; the script's docstring states the
box, the captures and the spans it expects.
*Done:* [`scripts/bench_decode_throughput.py`](../scripts/bench_decode_throughput.py). Three
repeats gave 4.57 / 4.73 / 4.68 fps, a 3.4% spread, which is the threshold every later phase is
read against. The §1 `-t` sweep reproduces within 4.6%: only `-t 8` falls outside the 3.4% spread.

**Task 2 — commit the working-set inventory.** A script that constructs an `RFDecode` per system and
reports resident filter bytes by array, the LUT size, and the bytes `demodblock` reads per block,
so later phases report footprint numerically.
*Acceptance:* on current code it prints 11.0 MiB / 10.0 MiB resident, 4.00 MiB LUT and ~4.3 MiB per
block for PAL; the per-block figure is derived from the arrays `demodblock` actually indexes, not
hand-listed.
*Done:* [`scripts/report_working_set.py`](../scripts/report_working_set.py), which substitutes a
recording mapping for the filter bank and recording proxies for the audio filters, demodulates one
block with the MTF path and the PAL carrier notch engaged, and sums what was indexed; it also
measures the block's temporaries as peak live allocation under `tracemalloc`. Resident (11.03 MiB
PAL / 10.03 MiB NTSC) and LUT (4.00 MiB) are as expected. **The per-block figure is 2.53 MiB, not
~4.3 MiB** — the estimate assumed every array was a full-blocklen `complex128`, where PAL's
`RFVideo`, `MTF` and `FcutPAL` are real `float64` at half the size and `Frfhpf_half` is a half
spectrum, and it counted the resident audio filters rather than the two 16 KiB stage-1 filters the
block reads. With the measured temporaries (5.00 MiB PAL, 4.62 MiB NTSC) the hot set is 11.5 MiB
PAL and 11.2 MiB NTSC, which is what §1 now states and what the L3 arithmetic already assumed;
the derived figure supersedes the estimate everywhere it appeared. Its consequence is for Phase 3,
recorded there: a narrower dtype moves the hot set by 10%, not by half.

**Task 3 — record the baseline.** Run the harness over PAL CVBS, PAL `--tbc` and NTSC CVBS at
`-t` 1, 2, 4, 6, 8 with `-l 1000`, plus 1, 2, 4, 8 concurrent serial decoders, and record it as the
table every later phase compares against.
*Acceptance:* the table is in this plan beneath §1; per-process peak RSS is recorded beside it.
*Done:* §1.1, with peak tree RSS beside every cell. Twenty-two rows, all `rc=0`; the raw JSON, the
inventory output and the driver are under `docs-planning/decode-working-set-baseline/` (local,
untracked). Two refinements to §1 came out of it: the plateau is PAL CVBS's alone — PAL `--tbc`
scales to `-t 4` and NTSC CVBS to `-t 8` — and the concurrent-serial knee is between 2 and 4
decoders rather than at 2.

## 4. Phase 1 — remove work that changes no output byte

Each task is gated on byte-identity with Phase 0's baseline; none may move a conformance figure.

**Task 1 — cache the JIT for `scale_positions`.** Add `cache=True` to its `@njit` decorator to match
`scale_field` (`dsp.py:105`).
*Acceptance:* `compare-pal-cvbs-parallel-*` byte-identical; time to first committed frame of a PAL
CVBS decode drops, stated before/after from the harness; second and later runs no longer show
numba compiling the kernel under `NUMBA_DEBUG_CACHE=1`.
*Done:* [`dsp.py:169`](../lddecode/dsp.py#L169). Compiling the kernel takes 1.99 s; loading it from
the cache takes 4 ms. A six-frame PAL CVBS decode went 13.75 s to 11.92 s wall (mean of three each,
cache file deleted before each cold run) — **1.83 s off every process that resamples**. The compile
lands after the setup line, on the first written frame, so it was being charged to the frame rate:
post-setup fps on that decode went 1.87 to 4.13. A decode instrumented with the dispatcher's own
counters reports `cache_hits={...: 1}, cache_misses={}` where it previously compiled. On the
`-l 1000` grid rows the effect is below the noise, as 1.8 s over 1000 frames should be. All fifteen
`compare-*-parallel-*` lanes pass, and PAL CVBS `-t 1` and `-t 4` write byte-identical output.

**Task 2 — stop raising the MTF filter to a power every block.** Cache
`Filters["MTF"] ** mtf_level` against `mtf_level` and invalidate it wherever the MTF filter itself
is rebuilt. `mtf_level` is constant within a field and changes at most once per
`MTF_SERVO_MIN_ADOPT_FIELDS` past warm-up, so the cache is hit on every block but the first after
an adoption.
*Acceptance:* byte-identical across all `compare-*` lanes (the cached product is the same array the
per-block expression produced); a unit test with an injected `RFDecode` asserts one `pow` per
distinct `mtf_level`; the per-block microbenchmark shows the `pow` gone; `-t 1` fps before/after.
*Done:* `RFDecode.mtf_response()`, invalidated in `computevideofilters()` — the only place that
builds `Filters["MTF"]`. One entry, so a level that oscillates cannot grow the footprint one filter
at a time. **This is the large one, and much larger on NTSC than the analysis expected.** On PAL
`MTF` is a real `float64` magnitude and the power costs 0.308 ms of a 3.017 ms block; on NTSC it is
`complex128` and the power is `exp(level * log z)` per bin, costing **2.29 ms of a 5.18 ms block**.
Per-block time falls 3.017 to 2.721 ms on PAL (-9.8%) and 5.180 to 2.786 ms on NTSC (**-46%**).
Whole-decode: NTSC CVBS `-t 1` goes 3.01 to 4.83 fps, **+60%**. Tests in
[`tests/unit/test_block_constant_hoists.py`](../tests/unit/test_block_constant_hoists.py) count the
powers against an injected filter, check the held array is what the expression produced, and check
a filter rebuild drops it.

**Task 3 — audit `demodblock` for other per-block constants.** Walk the block path for any further
expression whose operands do not depend on the block's data (filter products, mirrored spectra,
repeated `astype` copies) and either hoist it or record why it must stay.
*Acceptance:* a list in the commit message of each candidate with its per-block cost, and for each
either a hoist gated on byte-identity or a one-line reason.
*Done:* §4.1 below. Two more hoists (the PAL notch applied in place; the video and audio record
arrays cast on assignment instead of from float32 copies np.rec.array then copies again), and six
candidates recorded with the reason they stay. The one worth naming is the fused
`RFVideo * FcutPAL`: both are resident constants, so folding them would take a whole 256 KiB filter
out of the per-block read set — 10% of it — but floating-point multiply is not associative, so it
changes output bytes and cannot be done under this phase's gate.

**Task 4 — measure.** Harness rows for the Phase 1 result against Phase 0's baseline.
*Acceptance:* the table is recorded beneath Phase 0's; footprint inventory unchanged (Phase 1 adds
one cached 512 KiB array and removes a 512 KiB temporary per block).
*Done:* §4.2 below.

### 4.1 The block-path audit

Every expression `demodblock` evaluates per block, priced on the reference box at blocklen 32768
with digital and analog audio on. "Constant" means the operands do not depend on the block's data.

| Expression | Constant? | Cost per block | Disposition |
|---|---|---|---|
| `Filters["MTF"] ** mtf_level` | yes | 0.308 ms PAL, **2.29 ms NTSC**; a fresh 256/512 KiB array | **hoisted** into `mtf_response()` |
| `indata_fft_filt * Filters["FcutPAL"]` (PAL) | no, but allocates | 0.020 ms, 512 KiB temporary | **hoisted**: applied in place, 0.017 ms and no temporary |
| the video channels' `.astype(np.float32)` copies, which `np.rec.array` then copies again (and the same for the two audio channels) | no, but doubled | 0.087 ms PAL / 0.069 ms NTSC, 640/512 KiB thrown away, plus two audio copies | **hoisted**: cast on assignment, 0.057 / 0.042 ms |
| `Filters["RFVideo"] * Filters["FcutPAL"]` fused into one filter | yes | would save 0.017 ms and 256 KiB of the 2.53 MiB read per PAL block | **kept**: float multiply is not associative, so a fused filter changes output bytes. Belongs with a phase that re-records baselines |
| `Filters["MTF"]` folded in as well | yes within a field | as above | **kept**: same reason, and the level moves, so the fold would be rebuilt per adoption |
| carrier-bin arithmetic in `pal_audio_carriers_present` | indices yes, power sums no | 0.015 ms for the whole call | **kept**: scalar index arithmetic, below the measurement floor |
| window slices in `v4300d_coherent_subtract` | yes | only when the workaround is enabled; slice arithmetic | **kept**: same |
| `np.clip(demod, 1500000, self.freq_hz * 0.75)` | upper bound yes | scalar | **kept** |
| `Filters["FVideo05"][:n]` in `demodblock_sync` | yes | a view, no copy | **kept** |
| mirroring the `rfft` half-spectrum back to full | no | 0.016 ms | data dependent |

All three hoists are byte-identical by construction: holding the raised filter evaluates the same
expression once instead of per block; an in-place `*=` on a freshly allocated array performs the
same multiply as the out-of-place one; and assigning a `float64` array into a `float32` record field
runs the same cast `.astype(np.float32)` does. That was checked rather than assumed — see §4.2.

### 4.2 The Phase 1 result

Same harness, same captures, same spans and the same order as §1.1, one cell at a time. Repeats of
the PAL CVBS `-t 6` cell gave 4.77 / 4.98 / 4.96 fps, a **4.4%** spread on this run against 3.4% on
Phase 0's, so read a single cell against 4.4%.

| Cell | `-t 1` | `-t 2` | `-t 4` | `-t 6` | `-t 8` |
|---|---:|---:|---:|---:|---:|
| PAL CVBS, fps (Phase 0 → Phase 1) | 2.71 → 2.87 | 4.67 → 4.99 | 4.66 → 4.96 | 4.79 → 5.02 | 4.81 → 4.94 |
| PAL `--tbc`, fps | 2.82 → 2.93 | 5.43 → 5.72 | 7.38 → **7.94** | 6.99 → 7.60 | 6.69 → 6.91 |
| NTSC CVBS, fps | 3.01 → **4.83** | 5.56 → **9.07** | 9.15 → **12.45** | 10.01 → 12.17 | 10.50 → 11.21 |

N independent serial PAL CVBS decoders, aggregate post-setup fps: 2.81 → 2.87 (N=1), 4.79 → 4.83,
5.96 → 6.02, 5.90 → 5.98 (N=8). Peak tree RSS is unchanged or slightly lower in every cell (PAL
CVBS `-t 4` 2503 → 2357 MB, N=8 7579 → 6816 MB); nothing here grew the decoder.

Three readings, and the last two are the ones that matter to the rest of the plan:

- **NTSC gains hugely, PAL modestly.** NTSC CVBS is +60% serial and +36% at `-t 4`, all of it the
  complex `pow`. Every one of the fourteen PAL cells improved too, by +2.1% to +8.7%, mean about
  +5%; individually several sit inside the 4.4% spread, but fourteen same-signed cells are not
  noise, and the block microbenchmark independently shows -9.8%.
- **Making the block cheaper moved NTSC's ceiling forward, it did not raise it much.** NTSC CVBS
  now peaks at `-t 4` (12.45) and *falls* to 11.21 by `-t 8`, where before it climbed all the way
  to `-t 8`. Its plateau is 2.6x its serial rate where it used to be 3.5x. Taking work out of the
  block did not buy proportional throughput: it moved the decoder onto the contention limit sooner.
  That is the plan's premise, measured from the inside.
- **The concurrent-serial curve barely moves at all** (+0.8% to +1.4% across N = 1, 2, 4, 8). With
  N whole decoders competing, per-block arithmetic is not what is scarce. Nothing short of the
  footprint work in Phases 2, 3 and 6 will move that curve.

The footprint inventory is unchanged where it counts: per-block reads stay at 2.53 MiB on both
systems and the hot set at 11.53 MiB PAL / 11.16 MiB NTSC, because the held response is read in
place of the filter it was raised from and is the same size. Resident grows by exactly that array —
11.03 → 11.28 MiB PAL, 10.03 → 10.53 MiB NTSC. The plan expected the block's peak transient to fall
by 512 KiB; it does not measurably, because the temporaries removed are not the ones live at the
peak (the transforms are). [`scripts/report_working_set.py`](../scripts/report_working_set.py) now
reports the held response, both as resident and as the block's read, so that stays visible.

**Byte-identity.** Six decode configurations — PAL CVBS `-t 1` and `-t 4`, PAL `--tbc`, NTSC
`--tbc`, NTSC CVBS `-t 4`, and a PAL decode with EFM and analog audio — were run on this branch and
on a pristine copy of the previous commit. Every signal artefact (`.cvbs`, `.efm`, `.wav`) and every
metadata table is identical; the only difference anywhere is the branch-name field, which records
`unknown` for the copy because it is not a git checkout. Separately, all fifteen
`compare-*-parallel-*` lanes pass, and a block-level digest over both systems at three `mtf_level`
values with the PAL notch engaged matches the previous commit exactly.

## 5. Phase 2 — the resample LUT

Changes output by ~5e-6 rms on a unit signal — below 16-bit quantisation, but not byte-identical.

**Task 1 — regenerate the LUT at 256 phases and interpolate in both kernels.** Rebuild
`sinc_lut.npz` with `build_kaiser_lut` at the same `kaiser_beta` and `sinc_tap_count`, 256 phases;
make `scale_field` interpolate between adjacent phases exactly as `scale_positions` does, so the two
kernels read the table identically. The LUT is 16 KiB and lives in L1d.
*Acceptance:* a hermetic unit test builds a 65536-phase nearest-lookup reference and a 256-phase
interpolated table in-test and asserts the interpolated result is within 1e-5 rms of the reference
on a seeded DC–6.3 MHz band-limited signal at 10⁴ random fractional positions (the measured figure
is 5.1e-6; the tolerance is twice it and stays two decades under a 16-bit LSB); the shipped
`.npz` is ≤ 64 KiB; `scale_field` and `scale_positions` produce identical samples at identical
positions.

**Task 2 — re-record baselines and gate on conformance.** Run the full conformance and identity
lanes on the change, then re-record every byte baseline the change moves in one commit containing
nothing else.
*Acceptance:* `conformance-*-vits` within bands, no widening of `vits_known_deviations.toml`;
`compare-*-parallel-*` identity holds on the new baselines; the re-record commit touches only
baseline files.

**Task 3 — measure the footprint moving out of L3.** Harness rows, inventory, and the `perf`
fill-source measurement of the analysis's §3.4 repeated on one decoder among eight.
*Acceptance:* DRAM fills per frame drop by an amount consistent with ~700k fewer line fetches per
PAL frame; the PAL CVBS `-t` sweep's plateau moves, and its new onset is stated.

**Task 4 — transform the chroma-DG correction at a fast length.** In `_correct_chroma_vs_luma`
(`field.py:164`), pad the field to `scipy.fft.next_fast_len` before the transform, build the
subcarrier bandpass and the analytic-signal construction on the padded grid, and truncate after.
Both output paths benefit (CVBS ~103 → ~12 ms/frame, TBC ~62 → ~12 ms/frame on DG-affected
material); the padding discontinuity must be handled so the correction at the field's ends is
unchanged.
*Acceptance:* a hermetic unit test asserts the padded correction matches the unpadded one within a
stated tolerance on a synthetic staircase-plus-subcarrier field, including the first and last
lines; `conformance-*-vits` differential-gain and differential-phase figures within bands on the
radius set; harness rows for PAL CVBS and PAL `--tbc` on DS2 NationalA before/after; re-record
commit separate.

## 6. Phase 3 — the filter bank's dtype

**Task 1 — measure the dtype options under contention.** In isolation the dtype change buys
nothing: `complex128 × complex64` takes the same 0.022 ms/block as `complex128 × complex128`, and
scipy's `complex64` `ifft` is slower (0.352 vs 0.293 ms), so a `complex64` pipeline loses on the
transforms what it gains on the multiplies. Its only value is the halved L3 footprint when other
decoders share the cache, and Phase 0 Task 2 measured that as smaller than the resident figure
suggests: the block reads 2.53 MiB of coefficients, so narrowing every one of them moves the hot
set from 11.5 MiB to 10.3 MiB — 10%, not a halving, because the temporaries and the LUT dominate.
Three of PAL's six per-block filters are already real `float64`, so PAL gains least. Measure before
implementing: prototype "`complex64` filters only" and "`complex64` block pipeline" on a branch and
run both through the harness at `-t 6` and as eight concurrent serial decoders.
*Acceptance:* harness rows for both options against Phase 2's result at `-t 6` and N = 8; a stated
choice with the reason, or a stated decision to skip this phase if neither option moves the
contended figure by more than the harness's run-to-run spread.

**Task 2 — implement the chosen option.** Build the filter bank in the chosen dtype at
construction; if the pipeline option is chosen, carry the block spectrum in `complex64` from the
input transform to the video/EFM/audio products.
*Acceptance:* `conformance-*-vits` within bands; every `.tbc.db` metric the VITS lanes read stays
within its tolerance; the inventory reports the filter bank at ≤ 5.5 MiB PAL; re-record commit
separate, as in Phase 2 Task 2.

**Task 3 — measure.** Harness rows against Phase 2's result.
*Acceptance:* recorded table; the concurrent-serial curve's knee is stated.

## 7. Phase 4 — take stock and replan

No decoder changes. Decides whether the remaining phases are needed at all.

**Task 1 — re-measure the ceiling.** Re-run the `-t` sweep and the N = 1…16 concurrent-serial curve
from Phase 0 on the Phase 3 code; re-run the inventory.
*Acceptance:* the knee of both curves and the per-decoder hot set are stated beside Phase 0's.

**Task 2 — decide.** If the plateau's onset is at or beyond the box's physical core count, Phases
5–7 are not needed for throughput and this plan closes with Phase 5 Task 1 as an optional
simplification. If it is still below core count, record the remaining footprint by component and
proceed.
*Acceptance:* the decision and the measurement it rests on are recorded in this section; §1 is not
rewritten — the new figures sit beside the old.

**Task 3 — re-derive the `-t` auto default.** `main.physical_cpu_count` minus a margin was tuned to
the old knee; re-derive it from the new one and the per-process RSS.
*Acceptance:* unit test for the arithmetic with injected core and memory counts; the default lands
at
or below the measured optimum on the reference box.

## 8. Phase 5 — one resampler, one picture per field

**Task 1 — one position-based kernel.** Express `scale_field`'s raster case as a position generator
feeding `scale_positions` (after Phase 2 both interpolate on the same table), and retire the
duplicated inner loop.
*Acceptance:* `.tbc` and `.cvbs` outputs byte-identical to Phase 2's baselines; `python-unit-tests`
cover the raster and non-raster position generators against hand-computed positions for PAL
(1135.0064 samples/line, 4 slipped samples per frame) and NTSC (910 exactly).

**Task 2 — stop discarding the PAL TBC picture.** In PAL CVBS mode, produce only what the metrics
and servos read from `dspicture` — the VITS-line and SNR slices — rather than the whole line-locked
field, or re-base those measurements onto the CVBS lattice with per-line offsets. Dropout detection
is unaffected (it reads `data["rfhpf"]`).
*Acceptance:* every metric in the `.tbc.db` and every servo trajectory (`mtf_level`,
`inverse_mtf_strength`, `video_eq_auto`, `chroma_dg_slope/phase`) identical to the previous baseline
on the CI captures and the radius set; `.cvbs` bytes identical; inventory shows one fewer
whole-field array live per field in CVBS mode.

**Task 3 — measure.** Harness rows; PAL CVBS against PAL `--tbc` at the same `-t`.
*Acceptance:* the PAL CVBS-versus-`--tbc` gap under concurrency (5.16 vs 7.83 at Phase 0) is
re-stated.

## 9. Phase 6 — carry video at the rate it needs

Gated on Phase 4 Task 2. The highest-risk change in the plan: it moves where timing precision comes
from.

**Task 1 — prototype and measure precision.** On a branch, halve the post-demod video rate at
`demod_fft` (`rfdecode.py:1436`): keep the lower half of the spectrum and invert at half length, so
the video products leave `demodblock` at input/2 (20 MSPS for 40 MSPS input: Nyquist 10 MHz against
PAL's 6.3 MHz order-16 LPF at −64 dB and NTSC's 4.5 MHz order-6 at −42 dB; the same rate for both
systems, no per-system constant). Rescale the lineloc search and the downscale positions to the new
rate. Measure the per-line lineloc difference against the full-rate decode on the CI captures and
the radius set.
*Acceptance:* the distribution of lineloc deltas (in output samples) is stated with its 99th
percentile; `conformance-*-vits` results on the prototype are tabled beside the full-rate ones; a
go/no-go is recorded here with the figures.

**Task 2 — implement.** If Task 1 passes, land the change with the `Field` carrying half-rate video
products, the `FVideo` filter stack built at the new length, and the dropout detector untouched.
*Acceptance:* conformance within bands; the audio and EFM paths byte-identical; re-record commit
separate; inventory shows the video products and `FVideo_rfft` halved.

**Task 3 — decimate the EFM product.** Slice the `Fefm` band as the audio path slices its carriers
and hand `EFM_PLL` the lower-rate stream.
*Acceptance:* the EFM quality lane (`analysis/efm_quality.py` over the EFM-bearing captures) and
`compare-*-parallel-efm` unchanged in verdict; T-value distributions stated before/after.

## 10. Phase 7 — take stock: is the concurrency architecture still the limit?

No decoder changes.

**Task 1 — re-measure.** The `-t` sweep and concurrent-serial curve once more, on the Phase 6 code.
*Acceptance:* knees and hot set stated beside Phases 0 and 4.

**Task 2 — decide what, if anything, is next.** If `-t N` now scales to the physical core count,
close this plan. If it flattens below it for a reason that is now visibly in the parent process
(the commit loop, the output lane, IPC), reopen the concurrency design with the batch-parallel
plan's
§3.6 unwinding table as the input, on a fresh premise test.
*Acceptance:* the decision, its measurement, and the named bottleneck are recorded here.

## 11. Risks and open questions

- **`fastmath` and interpolation.** Both kernels are compiled with `fastmath=True`; making
  `scale_field` interpolate changes its floating-point sequence and so its bytes even before the
  table changes. Phase 2 accepts a byte change and gates on conformance; Phase 5 Task 1 must then
  land byte-identical to Phase 2, which is what makes the two-step order necessary.
- **Mixed-dtype cost.** A `complex64` filter against a `complex128` spectrum halves read traffic but
  adds a conversion per element inside the ufunc; on a machine that is cache-bound this should win
  and on one that is not it may lose. Phase 3 Task 1 measures rather than assumes, and the pipeline
  option exists for the case where the mixed form does not pay.
- **Servo measurements after Phase 3 and Phase 6.** The 2T pulse ratio, the multiburst packets and
  the DG staircase are measured on the decoded picture and feed the MTF, EQ and DG servos. A
  precision loss shows first as a servo adopting differently, then as a conformance figure moving.
  The servo-trajectory identity check in Phase 5 Task 2 is the instrument; Phases 3 and 6 use it
  too.
- **The measurement measures the box.** Every figure here is from one 5800X with its CPU frequency
  scaling active and a 32 MiB L3. A part with a larger L3 per core, or a smaller one, moves the
  knee.
  The harness records the box; the plan's decisions in Phases 4 and 7 are made on the reference box
  and the knee is stated, not assumed to transfer.
- **Decimation and the TBC's purpose.** Timing is the TBC's whole job, and Phase 6 halves the raw
  rate the line locations are found at. Sub-sample interpolation on `demod_05` is what the precision
  actually rests on today, and it survives the change in principle, but that is the claim Phase 6
  Task 1 exists to test on real captures before anything is committed.
- **What this plan does not do.** Nothing here changes the per-field RF demodulation cost, which is
  three quarters of a serial decode. Once the working set fits, the ceiling is `cores × 2.65 fps`
  for PAL and the remaining lever is the demodulator itself, which is out of scope.
