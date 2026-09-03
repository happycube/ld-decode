# Decode memory profile: why concurrency stops paying at three decoders

Companion to `docs-planning/decode-throughput-hotspot-analysis.md` (local, untracked),
measured on `05d60fd9` (`prev-8-sdi-dev`). That document asked where CPU time goes and concluded
that PAL CVBS is held flat from `-t 2` by a two-worker resample ceiling. This one asks a different
question — why does adding decoders stop helping, whatever shape the concurrency takes — and reaches
a different answer: the binding constraint is the **shared L3 cache**, and the thing that fills it
is
the decoder's own filter bank.

Nothing here changes behaviour. It records measurements taken for Phase 0 of
[`plans/batch-parallel-decode-plan.md`](batch-parallel-decode-plan.md), whose premise —
that N independent serial decoders beat one distributed decoder — these numbers refute.

Machine: AMD Ryzen 7 5800X, 8 physical cores / 16 SMT threads, 32 MiB L3 (one instance, shared),
512 KiB L2 per core, 32 KiB L1d per core, 62 GiB dual-channel DDR4. Captures on an NFS mount
(10.0.1.4) that sustains 618 MB/s single-stream and 934 MB/s across eight concurrent readers,
against a decode demand of roughly 30 MB/s — storage is not a constraint anywhere in this document.

---

## 1. The observation

Three ways of spending eight cores on the same 2000 frames of
`Domesday_DD86-DS2_NationalA_PP_20191014_CAV_PAL_00001-54000.ldf` (`-s 5000`), post-setup fps as
reported by the decoder itself:

| Mode | 1 serial decode | 8 concurrent serial decodes | `-t 8` | `-t 6` |
|---|---:|---:|---:|---:|
| PAL CVBS | 2.65 | 5.05 | 5.02 | 5.16 |
| PAL `--tbc` | 2.68 | 8.72 | 7.17 | 7.83 |
| NTSC CVBS | 2.98 | 12.48 | 10.84 | 10.80 |

Eight fully independent processes — no shared queues, no IPC, no lanes, nothing in common but the
hardware — reach 5.05 fps on PAL CVBS where one reaches 2.65. That is **1.9x for 8x the cores**, and
it is no better than the existing threaded decoder at `-t 6`. The same shape appears whether the
concurrency is eight processes or one process with eight workers, which already rules out anything
in `parallel.py`: two completely different concurrency architectures hit the same wall at the same
place.

Per-process efficiency under 8-way concurrency, against the same decode run alone:

| Mode | solo fps | per-process fps at N=8 | efficiency |
|---|---:|---:|---:|
| PAL CVBS | 2.65 | 0.63 | 24% |
| PAL `--tbc` | 2.68 | 1.09 | 41% |
| NTSC CVBS | 2.98 | 1.56 | 52% |

Each process still gets its core — `ps` shows ~112% CPU per process and the box reports idle
capacity — so this is not scheduling starvation. The processes are running; they are just doing
much less work per cycle.

## 2. What it is not

**Not SMT contention.** Pinning one decoder per physical core (`taskset -c 0..7`, siblings are `k`
and `k+8` on this part) is slightly *worse* than letting the scheduler use all sixteen logical CPUs:

| 8 concurrent serial decodes | post-setup aggregate fps |
|---|---:|
| pinned one per physical core | 4.75 |
| unpinned | 5.17 |

**Not storage.** See the NFS figures above; decode demand is ~30 MB/s against ~900 MB/s available.

**Not raw memory bandwidth alone, though the memory system is saturated.** A STREAM-style triad over
buffers far larger than L3, run at increasing concurrency:

| Concurrent workers | 1 | 2 | 4 | 6 | 8 | 12 | 16 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Aggregate GB/s | 9.8 | 8.6 | 9.5 | 9.4 | 9.1 | 8.4 | 8.4 |

Aggregate bandwidth is flat from one worker to sixteen: a single thread already saturates this
box's path to DRAM. (The absolute figure understates real traffic — numpy materialises a temporary
for `3.0 * c`, so the triad touches about five arrays rather than the nominal three — but the
flatness is what matters and is unaffected.) So *anything* that has to reach DRAM gains nothing
from more cores. The question is why the decode has to reach DRAM at all, and that is a cache
question, not a bandwidth one.

## 3. Why: the working set

### 3.1 The filter bank

`BLOCKSIZE = 32 * 1024` ([`params.py:17`](../lddecode/params.py#L17)), and every frequency-domain
filter is stored as a full-blocklen `complex128` array — 32768 x 16 bytes = **512 KiB each**.
Summing every array an `RFDecode` holds resident:

| System | `Filters` | audio filters | total per process |
|---|---:|---:|---:|
| PAL | 10240 KiB | 1056 KiB | **11.0 MiB** |
| NTSC | 9216 KiB | 1056 KiB | **10.0 MiB** |

The largest entries are all the same size, because they are all the same shape:
`FVideo_rfft` (4 x 16385, 1024 KiB), then `FVideo`, `FVideo05`, `FVideoBurst`, `FVideoGD`,
`FVideoPilot`, `Fburst`, `Fcutl`, `Fcutr`, `Fdeemp`, `Fefm`, `Femp`, `Frfhpf`, `MTF`, `RFVideo`,
`FcutPAL` … at 512 KiB apiece.

### 3.2 What one block touches

`demodblock` ([`rfdecode.py:1365`](../lddecode/rfdecode.py#L1365)) runs, per 32 KiB block, roughly
nine transforms and eight full-length spectrum multiplies. The filter coefficients it reads:

| Array | Size |
|---|---:|
| `Frfhpf_half` | 256 KiB |
| `RFVideo` | 512 KiB |
| `MTF` (plus the `** mtf_level` temporary) | 1024 KiB |
| `FcutPAL` (PAL, when the audio carriers are present) | 512 KiB |
| `FVideo_rfft` | 1024 KiB |
| `Fefm` (digital audio) | 512 KiB |
| audio stage-1 filters and slicers | ~1056 KiB |
| **filter coefficients read per block** | **~4.3 MiB** |

On top of that sit the temporaries — `indata_fft`, its mirrored full spectrum, `indata_fft_filt`,
the `hilbert` result, `demod`, `demod_fft`, the four-way `video_results` stack, the `float32` copies
and the record-array copy — another ~4 MiB live at once. NumPy has no loop fusion, so each of those
multiplies materialises its own 512 KiB array rather than being folded into its neighbour.

**A decoder's hot working set is therefore ~8-9 MiB, and none of it fits in private cache.** A
single full-blocklen spectrum is 512 KiB: sixteen times L1d, and exactly the size of the whole
per-core L2. No stage of the block has operands that fit in the cache private to the core running
it, so every stage streams its operands in and its result out through L3.

### 3.3 The arithmetic that predicts the cliff

L3 is 32 MiB and shared by all cores. The hot set per decoder is the filter coefficients read every
block (~4.3 MiB, §3.2), the resample LUT (4.0 MiB, §4c), and the live temporaries (~4 MiB) — call it
~12 MiB:

| Concurrent decoders | Working set | Fits in 32 MiB L3? |
|---:|---:|---|
| 1 | ~12 MiB | yes, comfortably |
| 2 | ~25 MiB | marginal |
| 3 | ~37 MiB | **no** |
| 8 | ~98 MiB | no, by 3x |

Below the cliff the filter bank stays resident in L3 and is read from cache on every block. Above
it, the filters are evicted between blocks and re-read from DRAM — and §2 has already established
that DRAM bandwidth does not grow with core count. That is the mechanism, and it predicts the
throughput curve should flatten at three to four concurrent decoders regardless of how the
concurrency is arranged.

Sweeping `-t` on PAL CVBS over the same span at two run lengths, post-setup fps:

| `-l` | t1 | t2 | t3 | t4 | t6 | t8 | t10 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 150 | 2.57 | 3.85 | 3.89 | 3.86 | 3.77 | 3.84 | 3.83 |
| 1000 | 2.77 | 4.77 | 4.75 | 4.61 | 4.72 | 4.59 | 4.74 |
| 2000 | 2.65 | — | — | — | 5.16 | 5.02 | — |

The plateau **begins at `t=2` at every run length**, which is exactly where two working sets
(~25 MiB) reach the 32 MiB L3 and a third cannot fit. Run length moves the *level* of the plateau
(3.85 at `-l 150`, ~4.8-5.2 at `-l 1000`-`2000`, because worker spawn and per-worker numba JIT are
amortised over more frames) but not its onset. So the hotspot analysis's shape — "CVBS gets
essentially all of its speedup by `t=2` … and is flat or slightly declining from `t=2` through
`t=10`" — is real; only its absolute numbers were depressed by short runs. What the shape is *not*
is a property of the CVBS resample: `--tbc` and NTSC carry the same filter bank and the same LUT and
flatten in the same place.

### 3.4 Confirmation: where the contended decoder's fills come from

`perf stat` on one serial PAL CVBS decoder over 60 frames (`-s 40000`): alone; beside one `-t 8`
decode of the same capture; and among seven other serial decoders (user-space counters;
`ls_any_fills_from_sys.*` counts 64-byte cache-line fills by their source):

| per frame | alone | beside `-t 8` | among eight serial |
|---|---:|---:|---:|
| instructions | 6.51e9 | 6.51e9 | 6.51e9 |
| cycles | 2.44e9 | 3.67e9 | 7.89e9 (**3.24×**) |
| IPC | 2.67 | 1.77 | 0.83 |
| L2 misses (`l2_cache_misses_from_dc_misses`) | 1.57e7 | 2.49e7 | 3.77e7 |
| fills from L3 (`int_cache`) | 1.69e7 (1035 MiB) | 2.24e7 (1367 MiB) | 2.94e7 (1793 MiB) |
| fills from DRAM (`mem_io_local`) | 5.43e6 (332 MiB) | 1.66e7 (1012 MiB) | 2.74e7 (1670 MiB, **5.0×**) |
| DRAM share of fills | 24% | 43% | 48% |
| post-setup fps | 3.15 | 2.04 | 0.89 |

The contended decoder executes exactly the same instructions and takes 3.2x the cycles to do so.
Its fills from DRAM rise five-fold, from a third of a gigabyte per frame to 1.6 GB, and DRAM's share
of all fills doubles. That is the L3 eviction §3.3 predicts, measured directly: the lines the
solo decoder finds in L3 are, among eight, no longer there. A `-t 8` decode as the neighbour sits
between the two — three times the DRAM fills of solo — because its eight workers are not all busy
at once (§1 of the hotspot analysis measures them at ~22% duty on PAL CVBS), so it occupies less of
L3 than eight serial decoders do while still evicting a serial neighbour's lines.

Note also the solo figures on their own: a lone decoder already pulls ~1.0 GB per frame from L3
and ~0.33 GB from DRAM — ~4.3 GB/s of L2-miss traffic at 3.15 fps — which is what §3.2's
"nothing fits in private cache" means in practice.

## 4. Avoidable costs found along the way

These are observations from reading the block path, not a plan; each would need its own change and
its own conformance evidence.

**The filters are `complex128` and need not be.** They are frequency responses multiplying data
whose input is 16-bit and whose output is `float32`. Storing them as `complex64` halves the filter
bank from 11.0 MiB to 5.5 MiB per process, which moves the L3 cliff from ~3 decoders to ~6 — the
single largest lever available, and it touches no algorithm.

**`Filters["MTF"] ** mtf_level` is recomputed on every block**
([`rfdecode.py:1423`](../lddecode/rfdecode.py#L1423)). It is a complex `pow` — `exp(r log z)`, two
transcendentals per element — over 32768 elements, producing a fresh 512 KiB temporary each time.
`mtf_level` is constant within a field and, past warm-up, changes at most once per 100 fields
(`MTF_SERVO_MIN_ADOPT_FIELDS`, [`decoder.py:1149`](../lddecode/decoder.py#L1149)). Caching the
raised filter against `mtf_level` removes both the transcendental cost and a 512 KiB allocation per
block.

**The chroma-DG corrector transforms at hostile lengths on the CVBS path.** Already recorded in the
hotspot analysis §3.2; repeated here with the factorisations because it is a working-set cost as
much as a cycle cost. `_correct_chroma_vs_luma` ([`field.py:164`](../lddecode/field.py#L164))
rfft/ifft's a whole field, and runs only when the DG servo is non-zero — that is, on exactly the
Domesday material these sweeps use. The PAL 4fsc frame lattice of 709,379 samples splits into:

| Path | Length | Factorisation |
|---|---:|---|
| CVBS field A | 354,690 | 2 · 3² · 5 · 7 · **563** |
| CVBS field B | 354,689 | **prime** |
| TBC field | 355,255 | 5 · 227 · 313 |
| TBC field | 354,120 | 2³ · 3 · 5 · 13 · 227 |

A prime length forces scipy onto its Bluestein path, and 563 is a large enough factor to hurt on
its own; the TBC lengths factor into small primes. This is a plausible part of why PAL CVBS
(5.16 fps) trails PAL `--tbc` (7.83 fps) under concurrency while being identical to it at `-t 1`
(2.65 vs 2.68) — the penalty is memory traffic, and it only bites once the machine is contended.
Zero-padding to `scipy.fft.next_fast_len` before the transform is local to one function, though the
bandpass and the analytic-signal construction would have to be built on the padded grid, and the
padding discontinuity handled.

## 4c. The resample LUT is 4 MiB and is read once per output sample

`downscale_sinc_lut` ([`rfdecode.py:120`](../lddecode/rfdecode.py#L120)) is **65537 x 16 float32 =
4.00 MiB**, and each row is exactly 64 bytes — one cache line. The resamplers index it by the
fractional sample phase, which advances by ~0.2555 per output sample on the PAL 4fsc lattice, so
consecutive lookups land **16,744 rows (~1 MiB) apart**. There is no reuse and no stride the
prefetcher can follow: it is one cache miss per output sample.

| Path | Output samples/frame | LUT rows read | LUT line fetches |
|---|---:|---:|---:|
| PAL TBC (`scale_field`, nearest phase) | 709,375 | 1 per sample | ~43 MiB/frame |
| PAL CVBS (`scale_positions`, interpolated) | 709,379 | 2 per sample | ~86 MiB/frame |

Eight concurrent decoders hold 32 MiB of LUT between them — the whole L3 — before a single filter
bank is counted. This is the second half of §3.3's working set, and the worse-behaved half.

The table is that large because `scale_field` looks up the **nearest** tabulated phase, and its
comment reasons that at 2**16 phases the nearest one is "accurate far below float32 precision", so
interpolating between adjacent phases "would double LUT reads and add per-tap math in the innermost
loop of the decoder for no change in output". `scale_positions` interpolates anyway.

Measured, against the shipping 65536-phase nearest lookup as reference, resampling a DC-6.3 MHz
band-limited signal at 40,000 random fractional positions:

| Phases | Interpolated | Table | rms difference | dB below signal |
|---:|---|---:|---:|---:|
| 65536 | nearest | 4096 KiB | — reference — | — |
| 65536 | yes | 4096 KiB | 5.11e-06 | 105.8 |
| 4096 | yes | 256 KiB | 5.11e-06 | 105.8 |
| 1024 | yes | 64 KiB | 5.11e-06 | 105.8 |
| **256** | **yes** | **16 KiB** | 5.14e-06 | **105.8** |
| 64 | yes | 4 KiB | 1.13e-05 | 98.9 |
| 1024 | nearest | 64 KiB | 3.24e-04 | 69.8 |
| 256 | nearest | 16 KiB | 1.30e-03 | 57.7 |

The trade is currently made on the wrong side. With interpolation the accuracy floor is the 16-tap
sinc window itself, not the phase quantisation, so the table can shrink by 256x — from 4 MiB to
16 KiB, small enough to sit in L1d — with no measurable change. Without interpolation a small table
is indeed bad (57.7 dB at 256 phases), which is what the comment is really observing.

Two further notes from comparing the kernels:

- The nearest and interpolated lookups differ from each other by 5.11e-06 rms, so **PAL CVBS and
  PAL TBC do not resample identically today**; the interpolated path is the more accurate of the
  two.
- `scale_positions` is declared `@njit(nogil=True, fastmath=True)`
  ([`dsp.py:169`](../lddecode/dsp.py#L169)) — **no `cache=True`**, where `scale_field`
  ([`dsp.py:105`](../lddecode/dsp.py#L105)) has it. The PAL CVBS resampler is therefore JIT-compiled
  from source in every process on every run, including in every `-t N` worker. That is a startup
  cost, and it is part of why short runs measure so much worse than long ones (§1 of the hotspot
  analysis's sweep used short runs).

## 4d. Per-block cost, measured

One 32 KiB PAL block through `demodblock` (digital and analog audio on, `mtf_level` 0.98), 30
repetitions after warm-up, on an otherwise idle machine:

| Stage | ms/block | bytes touched | effective GB/s |
|---|---:|---:|---:|
| **`demodblock` (whole)** | **2.516** | | |
| `rfft(raw)` | 0.128 | 512 KiB | 4.1 |
| mirror rfft → full spectrum | 0.016 | 512 KiB | 33.3 |
| spectrum × filter | 0.021 | 1536 KiB | 74.9 |
| **`MTF ** mtf_level`** | **0.308** | 1024 KiB | 3.4 |
| `ifft` (full complex, for the Hilbert) | 0.291 | 1024 KiB | 3.6 |
| `rfft(demod)` | 0.127 | 512 KiB | 4.1 |
| batched `irfft` (4 × half) | 0.388 | 2048 KiB | 5.4 |

Two readings from this. First, the per-block `MTF ** mtf_level` costs 0.308 ms against 0.022 ms for
the multiply it feeds: **hoisting it out of the block loop removes 12.3% of `demodblock`** for a
value that is constant across ≥ 100 fields. Second, the effective bandwidths sort the stages into
two kinds: the plain multiplies run at 60-75 GB/s (cache-resident in isolation — the operands were
just written), the transforms and the `pow` at 3.4-5.4 GB/s. The transforms are not memory-bound
here; they are the arithmetic. What the contended measurements in §1 add is that the multiplies
stop being cache-resident once other decoders share L3, which is where the 60-75 GB/s goes.

At 31,712 usable samples per block and 1.6 M samples per PAL frame, `demodblock` alone is
126.9 ms/frame — a 7.88 fps ceiling from this stage by itself, against the 2.65 fps a whole serial
decode achieves, so this stage is about a third of a serial frame.

**The filter dtype, in isolation.** `complex128 × complex64` takes the same 0.022 ms as
`complex128 × complex128` (60 vs 73 GB/s over less data — the conversion costs what the bytes
saved), and a full `complex64` multiply takes 0.008 ms. But scipy's single-precision transform is
**slower** on this machine — `ifft` 0.352 ms in `complex64` against 0.293 ms in `complex128` — so a
`complex64` pipeline loses on the transforms what it gains on the multiplies. The dtype change
therefore has no measurable benefit on an idle machine; its whole value is the halved L3 footprint
under contention, and Phase 3 of the working-set plan has to measure it on the throughput harness
at `-t 6` and 8-concurrent, not with this microbenchmark.

**The chroma-DG transform lengths, measured.** `rfft` and `ifft` of one field at each length the
two output paths use, ms per transform:

| Length | | `rfft` | `ifft` |
|---|---:|---:|---:|
| CVBS field A (2·3²·5·7·563) | 354,690 | 12.92 | 32.39 |
| CVBS field B (prime) | 354,689 | 29.94 | 27.77 |
| TBC field (5·227·313) | 355,255 | 12.99 | 29.55 |
| TBC field (2³·3·5·13·227) | 354,120 | 5.84 | 13.90 |
| `next_fast_len(354689)` | 354,816 | **2.15** | **3.77** |

When the DG servo is non-zero, the CVBS path spends **~103 ms per frame** in these four transforms
and the TBC path ~62 ms; padded to 354,816 both would spend ~12 ms. This is the largest single
per-frame cost found in this document, and it applies only on DG-affected discs — which is what the
throughput sweeps were run on: the servo traces put `chroma_dg_slope` at 0.0008–0.0037/IRE across
frames 2,500–7,500 of DS2 NationalA, so the correction was running throughout the sweeps' span. It
sits on the output lane, so at `-t 1` it overlaps nothing and at
`-t N` it is one of the two fixed threads §1 of the hotspot analysis describes.

## 4e. The concurrency curve

N independent serial PAL CVBS decoders, 150 frames each, disjoint spans of DS2 NationalA:

| N | aggregate fps | per-process fps | efficiency vs solo | resident |
|---:|---:|---:|---:|---:|
| 1 | 2.53 | 2.53 | 100% | 1.0 GB |
| 2 | 4.56 | 2.28 | 90% | 1.9 GB |
| 4 | 6.90 | 1.73 | 68% | 3.6 GB |
| 6 | 6.78 | 1.13 | 45% | 5.6 GB |
| 8 | 6.49 | 0.81 | 32% | 7.3 GB |
| 12 | 6.60 | 0.55 | 22% | 10.6 GB |
| 16 | 5.81 | 0.36 | 14% | 14.3 GB |

The second decoder costs 10%; the third and fourth cost a third; past four the aggregate is flat and
then falls. The knee is between two and four decoders, where §3.3's arithmetic puts it, and sixteen
decoders do less total work than four.

## 4a. The chain carries RF bandwidth all the way to the output

The RF input is 40 MSPS because that is what the capture hardware delivers and what FM demodulation
of a 7.1-9.3 MHz carrier needs. Nothing downstream of `unwrap_hilbert` needs it. The demodulated
signal is video baseband, bounded by the video LPF the decoder itself applies:

| | video LPF | Nyquist needs | 4fsc output | input is |
|---|---:|---:|---:|---|
| PAL | 6.30 MHz | 12.60 MSPS | 17.734475 MSPS | **3.17x** the LPF Nyquist, 2.26x the output rate |
| NTSC | 4.50 MHz | 9.00 MSPS | 14.318182 MSPS | **4.44x** the LPF Nyquist, 2.79x the output rate |

Yet the post-demod products are all carried at the full 40 MSPS to the end of the block:
`demodblock` emits `demod`, `demod_raw`, `demod_05`, `demod_burst` and (PAL) `demod_pilot` — four or
five `float32` arrays of the whole blocklen — and the digital-audio path emits EFM as `int16` at
40 MSPS for a signal whose channel rate is 4.3218 Mbit/s. Only then does
`downscale`/`downscale_cvbs`
resample to 4fsc.

The idiom for fixing this is already in the codebase, applied to exactly one of the three outputs.
The **analog audio** path does not carry 40 MSPS: `fft_determine_slices` / `fft_do_slice`
([`filters.py:188`](../lddecode/filters.py#L188)) cut the block spectrum down to a power-of-two bin
count around each audio carrier, and everything after that runs at the reduced rate
(`a1_freq`) with a correspondingly short hilbert transform. The video and EFM paths do the same
kind of work at 40 MSPS throughout.

The natural cut for video is at `demod_fft` ([`rfdecode.py:1436`](../lddecode/rfdecode.py#L1436)),
which already exists: the spectrum of the demodulated baseband is computed there and immediately
multiplied by the `FVideo_rfft` stack. Slicing that spectrum to the video band and inverting at half
the length would produce the video products at ~20 MSPS — still 1.6x the LPF Nyquist and 1.13x the
4fsc output rate — halving four or five full-blocklen arrays per block, halving the `FVideo_rfft`
filter bank, and halving what a `Field` then carries in memory. EFM has far more headroom again.

What that risks, and would have to be shown not to break:

- **Sync and lineloc precision.** Line locations are found on `demod_05` with sub-sample
  interpolation; the interpolation recovers most of what the lower raw rate gives up, but "most" is
  not "all" and the TBC's whole job is timing.
- **Dropout detection stays at full rate regardless** — `dropout_detect_demod`
  ([`field.py:1544`](../lddecode/field.py#L1544)) works on `data["rfhpf"]`, an RF-domain product,
  not on the demodulated video.
- **The 2T pulse and multiburst measurements** feed the MTF and EQ servos. Both live below the
  6.3 MHz LPF, so band-wise they are safe, but they are the measurements the conformance lanes
  judge, so they are where a regression would show first.

## 4b. PAL resamples every field twice; NTSC does not

`decode_stage2` ([`decoder.py:2644`](../lddecode/decoder.py#L2644)) unconditionally computes the
line-locked TBC picture via `f.downscale(final=True)`, in every mode. What happens next depends
entirely on whether the system's 4fsc lattice is line-locked:

| | 4fsc samples/line | TBC line length | frame |
|---|---:|---:|---:|
| NTSC | 910.0000 (exact) | 910 | 477,750 |
| PAL | 1135.0064 | 1135 | CVBS 709,379 vs TBC 709,375 |

Because NTSC's lattice is exactly line-locked, `_emit_frame` reuses the TBC picture directly —
`_to_spec_levels(_as_u16(pic_a), f_a)` — and no second resample exists. PAL's is not, so
`_emit_frame` discards `pic_a`/`pic_b` and calls `downscale_cvbs` on both fields: **the field is
resampled twice, once to a lattice that is then thrown away.**

Deriving the TBC lattice from the CVBS one by dropping samples does not work. The two differ by
exactly 4 samples per frame, a rate ratio of 1.0000056, so dropping four samples per frame gives the
right sample *count* while leaving a sawtooth timing error of up to one lattice sample — 90 degrees
of subcarrier — which is not survivable for chroma.

The reduction available is the other way round. The TBC picture is not kept in CVBS mode for the
output; it is kept because the metrics and servos read `f.dspicture`
([`metrics.py`](../lddecode/metrics.py), ~15 call sites, all VITS-line and SNR slices at
`outlinelen` spacing). Dropout detection does not need it. So in PAL CVBS mode the whole-field TBC
downscale exists to serve measurements on a handful of lines, and could be cut to those lines, or
the measurements re-based onto the CVBS lattice with per-line offsets at 1135.0064 spacing.

Size the prize honestly before doing it: the hotspot analysis measures `field.py:downscale` at 3.0%
of PAL serial main-thread time, and at `-t 1` PAL CVBS and PAL `--tbc` run at the same speed (2.65
vs 2.68 fps). The second resample is nearly free when the machine is idle. It only bites under
concurrency — PAL CVBS 5.16 vs PAL `--tbc` 7.83 at `-t 6` — which is the signature of a working-set
cost, not a cycle cost, and puts it in the same category as everything else in this document.

## 5. What this means for batch-parallel decode

[`plans/batch-parallel-decode-plan.md`](batch-parallel-decode-plan.md) proposes replacing
the threaded decoder with N independent serial decoders over disjoint ranges, on the premise that
"many processes each doing sequential work beat one process distributing work through five levels of
queues". Phase 0 Task 2 tested that premise directly and it does not hold on this hardware: the
independent processes match the threaded decoder, at 2-2.5x the memory (7.5 GB vs 3.0 GB resident
for the same work). They match it because both are limited by the same thing, and that thing is
neither the queues nor the resample — it is that four concurrent copies of an 11 MiB filter bank do
not fit in a 32 MiB cache.

The useful consequence is that the lever is much cheaper than the plan. Halving the filter bank's
dtype moves the cliff from three decoders to six and helps `-t N` and any future batching equally,
without an orchestrator, a segment format, a seam resolver or a merge stage — and without giving up
the causal servo semantics the plan would have had to trade away.

More generally, the ordering the measurements argue for is **shrink the working set first, then
parallelise**. Concurrency here is capped by how many decoder working sets fit in 32 MiB, not by how
many cores exist, so every byte removed from the per-decoder footprint raises the ceiling for
*every*
concurrency scheme at once — the existing `-t N`, a future batch design, or a single pipeline. In
rough order of size:

| Change | Footprint effect | Risk |
|---|---|---|
| 256-phase interpolated sinc LUT (§4c) | 4.00 MiB -> 16 KiB, and ~709k random DRAM fetches per frame become L1 hits | low: measured indistinguishable at 105.8 dB |
| Chroma-DG transforms at `next_fast_len` (§4d) | none resident; ~90 ms/frame (CVBS) and ~50 ms/frame (TBC) off the output lane on DG-affected discs | low: padding-edge handling, DG/DP conformance figures |
| `complex64` filter bank (§4, §4d) | 11.0 -> 5.5 MiB resident; cliff ~3 -> ~6 decoders | medium: no gain in isolation, scipy's `complex64` FFT is slower; must be measured under contention |
| Decimate post-demod video to 20 MSPS (§4a) | halves 4-5 arrays/block and the `FVideo_rfft` bank | highest: lineloc precision, servo measurements |
| `cache=True` on `scale_positions` (§4c) | none resident; removes a per-process JIT compile | none |
| Cache `MTF ** mtf_level` (§4) | removes a 512 KiB temporary and 32768 complex `pow` per block | none |
| Drop the discarded PAL TBC picture (§4b) | removes a whole-field array in CVBS mode | low, but only ~3% of serial time |

A single common intermediate rate serves both systems. The binding constraint is not the video LPF's
cutoff but its transition band: PAL's is order-16 Butterworth at 6.3 MHz, which at a 6.5 MHz Nyquist
(13 MSPS) still passes -5.7 dB, folding energy back into the band. At 20 MSPS (input / 2, Nyquist
10 MHz) it is -64 dB, and NTSC's order-6 at 4.5 MHz is -42 dB. Input / 2 is also an exact halving of
the `demod_fft` spectrum that already exists, so it needs no resampling filter, no per-system
constant and no branch — the same rate is the better choice for each system taken alone, not a
compromise between them.

None of these changes the concurrency architecture, and all of them are testable against the
existing VITS conformance lanes rather than against byte equality. Only once one decoder's working
set is small enough for eight of them to coexist does the shape of the parallelism become the
limiting question again — and at that point the cheap answer (`-t N` as it stands) may well be
sufficient, which is the strongest argument for doing these first.

## 6. Reproduction

All of it runs from the dev shell. Note that the `nix develop "path:$PWD"` form in `AGENTS.md` §7
fails on this flake (`attribute 'shortRev' missing`, `flake.nix:22`) because a `path:` source
carries no git metadata; use plain `nix develop`.

```bash
# per-process filter footprint
nix develop --command python -c "
from lddecode.core import RFDecode
import numpy as np
rf = RFDecode(system='PAL', decode_digital_audio=True,
              decode_analog_audio=44100, has_analog_audio=True)
print(sum(np.asarray(a).nbytes for a in rf.Filters.values()
          if np.asarray(a).dtype != object) / 2**20, 'MiB')"

# one decode alone vs eight concurrent, same total frames
nix develop --command python -m lddecode.main --pal -t 1 -s 5000 -l 250 <capture> /tmp/solo
for k in $(seq 0 7); do
  nix develop --command python -m lddecode.main --pal -t 1 \
    -s $((5000 + k * 250)) -l 250 <capture> /tmp/b$k &
done; wait

# cache fill sources, solo vs contended (user-space counters, paranoid=2 is enough)
nix shell nixpkgs#linuxPackages_latest.perf --command perf stat \
  -e cycles,instructions,ls_any_fills_from_sys.int_cache,ls_any_fills_from_sys.mem_io_local \
  -- python -m lddecode.main --pal -t 1 -s 40000 -l 60 <capture> /tmp/perf
```
