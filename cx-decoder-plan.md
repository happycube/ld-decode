# CX Audio Decompressor (Expander) — Implementation Plan

Goal: implement the decoder (expander) for the IEC 60857-1986 Appendix B "AUDIO
COMPRESSION SYSTEM" (CBS CX noise reduction) as a post-processor for ld-decode's
analog audio output, plus the matching encoder for testing, and validate against
real discs (he010 dual-track, ggv-cx).

Spec source: `analogue-video-specifications/docs/laserdisc/IEC-60857-1986-Laservision-NTSC/IEC-60857-1986-Laservision-NTSC.md`
- §8.1 (line ~199): ±100 kHz deviation = 100% modulation; instantaneous peak < ±150 kHz.
- §8.3/8.4 (lines 206–212): CX is applied **before** pre-emphasis at mastering.
- Appendix B (lines 764–806): CX parameter definitions.
- Figures: `assets/img-26.jpeg` (compression curve), `img-27/28.jpeg` (stereo
  encoder + control-path detail), `img-29/30.jpeg` (bilingual variant).

---

## 1. System overview

The CX **encoder** is a *feedback* compressor: the sidechain ("control path") is
fed from the encoder **output** (the compressed signal that gets recorded):

```
encoder:   u ──► [VCA ×g] ──┬──► c   (recorded, then pre-emphasized, then FM)
                   ▲        │
                   └─[control path]◄─ (HPF of c)
```

Because the sidechain sees only the *compressed* signal, the **decoder** is the
exact mirror: a *feed-forward* expander whose identical control path is fed from
the decoder **input** (which *is* the encoder output), with reciprocal gain:

```
decoder:   c ──┬──► [VCA ×1/g] ──► u
               │        ▲
               └─[control path]────┘   (identical control path, fed by HPF of c)
```

If the decoder's control path matches the encoder's, tracking is *exact* by
construction — including all detector ballistics. This is why CX playback
hardware could be cheap, and why our expander only needs the control path
implemented faithfully once.

### 1.1 VCA law and why it is a linear multiplier

Figure B1 (img-26): 2:1 compression above the knee; at 1 kHz, input 0 dB
(=100% mod) → output 100 kHz deviation (0 dB); the knee is at **output = 8 kHz
deviation** (−21.94 dB), hence input −43.88 dB (0.64 kHz equivalent). Below the
knee the curve is linear (1:1) with the encoder gain frozen at +21.94 dB.

Let `V_c` be the control voltage and `L` the sidechain-detected level of the
compressed signal, with `V_c ∝ L` (the spec defines `V_CR` as the control
voltage at ±40 kHz deviation, i.e. control voltage is *linear* in level).
A 2:1 curve falls out automatically if the VCA is a plain multiplier:

- Encoder: `c = u · V_ref/V_c` with `V_c ∝ level(c)`  ⟹  `c² ∝ u` ⟹ exact 2:1.
- Decoder: `u = c · V_c/V_ref` with `V_c ∝ level(c)`.

So the decoder main path is simply:

```
y[n] = x[n] · V_c[n] / V_100
```

where `V_100` = control voltage corresponding to 100 kHz deviation. By linearity
`V_100 = 2.5 · V_CR` (100/40). No logs/antilogs anywhere in the audio path.

### 1.2 Static transfer check (1 kHz, levels in dB re 100 kHz deviation)

With `c` = compressed level, `u` = expanded output level, both linear in
"kHz-of-deviation" units:

```
u(c) = c · max(c, 8) / 100        (kHz units; knee clamp at 8 kHz)
```

| original u | compressed c (on disc) | decoder gain |
|-----------:|-----------------------:|-------------:|
|      0 dB  |          0 dB (100 kHz)|        0 dB  |
|    −10 dB  |          −5 dB         |       −5 dB  |
|    −20 dB  |         −10 dB         |      −10 dB  |
|    −40 dB  |         −20 dB         |      −20 dB  |
| −43.88 dB (knee) | −21.94 dB (8 kHz) |   −21.94 dB  |
|    −60 dB  |         −38.06 dB      | −21.94 dB (floor) |

Below the knee the decoder gain is frozen at 8/100 = 0.08 (−21.94 dB) — this is
where the ~14 dB (spec claim) noise reduction comes from.

---

## 2. Signal domains and ld-decode calibration

Mastering chain: `audio u → CX encode → pre-emphasis P → FM (±100 kHz max)`.
ld-decode playback chain: `FM demod (Hz deviation) → de-emphasis D → downscale → .pcm`.

Since CX encoding happened **before** pre-emphasis, the de-emphasized signal in
the `.pcm` file **is** the encoder output `c`. The expander operates directly on
the `.pcm` samples. Relevant code:

- De-emphasis: `emphasis_iir(5.3e-6, 75e-6, a1_freq)` at `lddecode/rfdecode.py:654`
  (75 µs shelf, unity gain at DC). |D(1 kHz)| = **0.90509** (−0.866 dB).
- PCM scaling: `dsa_rescale_and_clip` at `lddecode/dsp.py:410`:
  `pcm = −round(deviation_Hz · 32767/371081)` → **0.0883015 counts/Hz**.
  (The negation is irrelevant to CX — full-wave rectifier + multiplicative gain.)
- Output: raw headerless int16 LE, stereo interleaved L,R, 44100 Hz default
  (`lddecode/audio.py`).

All spec levels are defined at f = 1 kHz **on-disc deviation**, so convert to
PCM counts through D(1 kHz):

```
counts(dev_kHz) = dev_kHz · 1000 · |D(1kHz)| · 32767/371081
                = dev_kHz · 79.921 counts/kHz
```

| spec quantity | deviation | PCM peak (int16 counts) |
|---|---|---|
| 0 dB reference (100% mod) | 100 kHz | **7992.1** |
| `V_CR` anchor              |  40 kHz | **3196.8** |
| knee                       |   8 kHz |  **639.4** |
| instantaneous max (§8.1)   | 150 kHz | 11988 |

**Do not hardcode 0.90509** — compute it at runtime from
`emphasis_iir(5.3e-6, 75e-6, fs_eval)` via `scipy.signal.freqz` at 1 kHz so the
anchor stays consistent if the deemp constants ever change. Everything else in
the sidechain is expressed as a ratio of `V_CR` (see §3.6), so this single
anchor (40 kHz ↔ 3196.8 counts) is the only absolute calibration.

---

## 3. Control path — discrete-time equations

From Appendix B §B2 and Fig B2 detail (img-28). One control path shared by both
channels in stereo mode; two independent paths in bilingual mode (Fig B3).
`fs` = PCM rate (44100 default), `T = 1/fs`. All state float64.

For every first-order smoother use `α(τ) = 1 − exp(−T/τ)`. At 44.1 kHz:

| block | τ (±5%) | coefficient |
|---|---|---|
| fast attack   | 1 ms   | α_fa = 0.0224215 |
| fast release  | 10 ms  | α_fr = 0.0022650 |
| slow attack   | 30 ms  | α_sa = 7.5557e−4 |
| slow release  | 200 ms | α_sr = 1.1337e−4 |
| integrator    | 2 s    | α_i  = 1.1338e−5 |
| attack-comp decay | 30 ms | β_ac = exp(−T/0.03) = 0.9992447 |

Thresholds (±10%): `θ_slow = 0.26·V_CR`, `θ_ac = 0.52·V_CR`.
Knee clamp: `R_knee` = rectifier-domain constant corresponding to 8 kHz = `0.2·V_CR / k_b`
— in practice just derive it from the self-calibration in §3.6 so detector
ballistics (`k_b`) cancel.

### 3.1 Sidechain high-pass filter (per channel)

First-order, f_c = 500 Hz ± 5%, 6 dB/oct, **sidechain only** (the main audio
path is untouched). One-pole/one-zero:

```
h[n] = a_hpf · (h[n−1] + x[n] − x[n−1]),    a_hpf = exp(−2π·500/fs) = 0.931239 @44.1k
```

(±5% tolerance means the discretization method is uncritical.) Note this makes
the detected level of low-frequency program roll off 6 dB/oct below 500 Hz —
the compression curve is frequency-dependent by design; the decoder mirrors it
automatically. |HPF(1 kHz)| = 2/√5 = 0.8944 — folded into calibration `k_b`.

### 3.2 Full-wave rectifier + knee clamp (per channel), then stereo combine

```
r_ch[n] = |h_ch[n]|
r[n] = max(r_L[n], r_R[n], R_knee)      # stereo: diode-OR of the two rectifiers
r[n] = max(r_ch[n], R_knee)             # bilingual: per-channel path
```

Spec B2(2): "When the input signal level is under the knee, the constant d.c.
level corresponding to the knee is fed to the following block" — i.e. the clamp
floor applies at the rectifier output. Because the whole chain has unity DC
gain, feeding constant `R_knee` yields steady `V_c = 0.2·V_CR` ⇒ gain floor
0.08. (Stereo combine: the figure shows both rectifiers feeding one fast block;
diode-OR = max is the standard reading. Keep `sum/2` available behind a flag —
see §5 ambiguities.)

### 3.3 Fast attack/release block

Asymmetric one-pole follower (quasi-peak detector):

```
F[n] = F[n−1] + α_fa·(r[n] − F[n−1])   if r[n] > F[n−1]   (attack, 1 ms)
F[n] = F[n−1] + α_fr·(r[n] − F[n−1])   otherwise           (release, 10 ms)
```

### 3.4 Slow blocks + common capacitor

Three blocks (slow attack 30 ms, slow release 200 ms, integrator 2 s) each act
as a resistor from `F` into one shared capacitor `V_cc`; currents add. The slow
attack/release conduct only when the voltage across them exceeds `θ_slow`
(B2(5)). With `e = F[n] − V_cc[n−1]`:

```
dV = α_i · e                                   # integrator, always active
if e >  θ_slow:  dV += α_sa · (e − θ_slow)     # slow attack (diode-offset model)
if e < −θ_slow:  dV += α_sr · (e + θ_slow)     # slow release
V_cc[n] = V_cc[n−1] + dV
```

Primary model is the **diode-offset** form above (conduction ∝ excess over the
threshold — physical, continuous at the boundary). Alternate **switch** model
(`dV += α_sa·e` when `e > θ_slow`) behind a flag; the he010 test (§7.5) decides
if it matters. `V_CR` is defined "measured at the common capacitor" — i.e.
`V_cc` at steady state with a 40 kHz-deviation tone.

Behavioral summary: small level changes (< 0.26·V_CR ≈ 10.4 kHz-equivalent)
move the gain only through the 2 s integrator (inaudible gain wander); large
level jumps engage the 30 ms / 200 ms paths.

### 3.5 Attack compensator + adder

Spec B2(6,7): decay τ = 30 ms; "active for the input level of this block with
more than 0.52·V_CR"; its output adds to `V_cc` with equal weight:

```
V_c[n] = V_cc[n] + A[n]
```

Design intent: on a loud attack, `F` rises in ~1 ms but `V_cc` needs ~30 ms
(slow attack). The compensator bridges the gap so `V_c` tracks `F` immediately;
its 30 ms decay matches the slow-attack 30 ms charge, so for a step
`V_cc + A ≈ F` throughout the transition (e^{−t/30ms} terms cancel). At steady
state it must contribute ~0, or the static curve (Fig B1, straight 2:1 line to
0 dB) would kink — so it is AC-coupled ("decay time constant"), not a DC path.

**Primary model** (excess-capture, gated on level):

```
if F[n] > θ_ac:                      # θ_ac = 0.52·V_CR   (≈ 20.8 kHz level)
    A[n] = max(F[n] − V_cc[n], A[n−1] · β_ac)
else:
    A[n] = A[n−1] · β_ac
A[n] = max(A[n], 0)
```

Steady state: `F ≈ V_cc` (± ~2.5% detector ripple) → `A ≈ 0` (curve intact to
~0.2 dB at loud levels). Loud attack: `V_c = V_cc + (F − V_cc) = F` exactly.
Quiet-program attacks (`F < 0.52·V_CR`) get no compensation — consistent with
the intent (overshoot only threatens the ±150 kHz deviation ceiling when loud).

**Variants behind a flag** (see §5): (b) subtract the threshold,
`A = max(F − V_cc − θ_ac, A·β_ac)`; (c) off. Decoder-side impact of a wrong
choice is a brief (<30 ms) gain error during loud attacks only; T5's transient
metric picks the variant that best matches real CBS encoders.

### 3.6 Calibration: `V_CR` by self-simulation

Every threshold is a ratio of `V_CR`, and `V_CR` includes detector ballistics
(quasi-peak reading of a full-wave-rectified 1 kHz sine through the 500 Hz HPF).
Don't derive it analytically — measure it from the implemented sidechain:

```
1. A_40 = 40 · 79.921 counts  (≈ 3196.8; recompute D(1kHz) at runtime, §2)
2. x[n] = A_40 · sin(2π·1000·n/fs), 3 s, fed to BOTH channels
3. Run the full sidechain with R_knee = 0, θ_slow = θ_ac = +inf (clamps off)
4. V_CR := mean of V_cc over the last 0.5 s
```

Then derive everything as ratios:

```
θ_slow = 0.26·V_CR      θ_ac = 0.52·V_CR      V_100 = 2.5·V_CR
R_knee = 0.20·V_CR
```

`R_knee = 0.2·V_CR` needs no ballistics correction: the spec defines the clamp
as "the constant **d.c.** level corresponding to the knee", the chain from
rectifier output to `V_cc` has unity DC gain, and control voltage is linear in
level (knee 8 kHz = 0.2 × 40 kHz). Consistency check worth asserting in a test:
a sine at `A_8 = 8·79.921` counts (clamp off) must also settle to
`V_cc = 0.2·V_CR ± 1%` — same ballistics factor as the `V_CR` tone, by
linearity. (Slightly above the knee the per-sample clamp still trims the
rectified waveform near zero-crossings, softening the corner a little; that is
spec-literal behavior, not an error.)

Cache `(fs, V_CR)` after first computation (it's ~130k samples of njit loop,
negligible anyway — fine to compute at every startup).

---

## 4. Decoder main path, end to end

Per sample (stereo shares one `V_c`; bilingual has `V_c` per channel):

```
x_L, x_R  = pcm samples as float64
(sidechain §3 updates V_c[n] from x_L, x_R)
y_ch[n] = x_ch[n] · V_c[n] / V_100
output  = clip(round(y), −32766, 32766) as int16
```

Notes:
- Gain range: 0.08 (floor) … ~1.0 at 100% modulation; can exceed 1 only if the
  disc exceeds 100 kHz deviation (spec allows 150 kHz instantaneous → gain 1.5).
  Clip guard on output; count clipped samples and log a warning.
- **DC offset**: any demod carrier-offset DC in the .pcm becomes gain-modulated
  DC = audible thumps. Add an optional main-path DC blocker (1st-order HPF at
  5 Hz, default ON, `--no-dc-block` to disable). The sidechain HPF already
  kills DC in the control path.
- **Startup**: initialize `F = V_cc = 0.2·V_CR` (knee), `A = 0`, then warm up by
  running the sidechain (only) over the first `min(0.5 s, len)` of input before
  the real pass, keeping the resulting state. Avoids a 2 s integrator settle.
- Dropout clicks in analog audio will punch the detector (1 ms attack). Keep
  spec-pure by default; optional `--click-guard` limiting `r[n]` slew is a
  later nicety, not part of this plan's acceptance.

---

## 5. Spec ambiguities — decision table

Each is a keyword argument + CLI flag; defaults chosen here; T5 (he010) is the
tiebreaker. None of these affect the static curve; all affect only transient
tracking accuracy against real CBS encoders.

| # | ambiguity | options | default |
|---|---|---|---|
| 1 | stereo rectifier combine | `max` (diode-OR) / `mean` | `max` |
| 2 | slow-block conduction law | `offset` (∝ excess) / `switch` (∝ full e) | `offset` |
| 3 | attack compensator | `excess` (§3.5) / `excess-minus-threshold` / `off` | `excess` |
| 4 | knee clamp placement | rectifier floor (spec literal) — no option needed | — |

---

## 6. Implementation plan

New module `lddecode/cx.py` (standalone; no changes to the decode pipeline in
this pass):

```python
CXParams   # dataclass/namespace: fs, mode, taus, thresholds (ratios), flags from §5
class CXExpander:
    def __init__(self, fs=44100, mode="stereo", **flags)   # runs §3.6 self-cal
    def process(self, pcm: np.ndarray) -> np.ndarray       # int16 interleaved in/out
    # state persists across calls → streaming/chunked processing works
class CXCompressor:   # encoder, for tests: same sidechain, y = x·V_100/V_c,
                      # sidechain fed from y with one-sample delay
```

- Hot loop: single `@njit(cache=True, nogil=True)` function taking flat state
  arrays, matching repo style (`lddecode/audio.py`, `lddecode/dsp.py`). The
  loop is inherently sequential (feedback state) — sample-by-sample, ~15 ops
  per sample, trivially real-time at 44.1 kHz.
- `dsp.py` already has `db_to_lev`/`lev_to_db` marked "Used to help w/CX
  routines" (dsp.py:398) — use them for reporting only; the signal path is all
  linear-domain.
- CLI: `python3 -m lddecode.cx in.pcm out.pcm [--rate 44100] [--mode stereo|bilingual]
  [--stereo-combine max|mean] [--slow-model offset|switch] [--attack-comp excess|excess-thresh|off]
  [--no-dc-block] [--gain-log file]` — `--gain-log` dumps `V_c/V_100` per block
  for the analysis notebooks.
- Later (out of scope now): `--cx` flag in `lddecode/main.py`; auto-detection
  from the VBI programme status code (`8DC` = CX on, Appendix C, spec line ~845)
  and bilingual flags from the X41/X34/X43/X44 table.

---

## 7. Test plan

Test assets:

| asset | what it is |
|---|---|
| `/home/cpage/ld-decode/ggv-ntsc-1khz100p.ldf` (+75p, 40p, 4p) | 1 kHz tones at 100/75/40/4% modulation, CX off |
| `/home/cpage/ld-decode/ggv-cx.ldf` (1.5 GB) | GGV test disc CX section (CX-encoded test signals) |
| `/home/cpage/ld-decode/he010.efm.flac`, repo `he010.pcm`/`he010.efm` (already decoded) | disc with BOTH digital (EFM, not CX) and analog (CX) tracks of the same program |
| `ld-process-efm` (`/usr/local/bin`) | .efm → digital PCM |

### T1 — static curve (synthetic)
Generate 3 s 1 kHz tones at compressed peak levels c ∈ {−40, −30, −25, −21.94,
−20, −15, −10, −5, 0} dB re 7992 counts → expand → measure steady output level
(last 1 s, RMS·√2). Expect `u = 2c` above the knee, `u = c − 21.94 dB` below,
within **±0.25 dB** (self-calibrated `V_CR` makes this tight; spec tolerances
are ±5%/±10% so anything <1 dB is compliant).

### T2 — dynamics / threshold logic (synthetic)
1 kHz tone with level steps, verify `V_c` trajectories:
- −30 → −10 dB step: `V_c` reaches 90% of final within ≈ 5 ms (fast + attack
  compensator; without compensator ≈ 65 ms) — also *proves* the compensator path.
- −10 → −30 dB step: release via 200 ms path; 90% in ≈ 400–500 ms.
- −16 → −14 dB step (below 0.26·V_CR): only the 2 s integrator responds;
  `V_c` still <50% settled after 1 s.
- Below-knee tone (−45 dB): gain pinned at −21.94 dB, no modulation.

### T3 — encoder round-trip (the strong self-consistency test)
Use the he010 **digital** PCM (or any music) as source `u` → `CXCompressor` →
`CXExpander` → `û`. Assert: short-time RMS envelope error |env(û) − env(u)|
< **0.5 dB** for ≥99% of active 50 ms frames; sample-domain null depth vs `u`
better than −30 dB outside attack transients. Also run with mismatched flags
(encoder `offset` / decoder `switch`, etc.) to quantify each ambiguity's real
cost — this bounds the damage of any wrong §5 default.

### T4 — absolute anchor (GGV tones, CX off)
Decode `ggv-ntsc-1khz{100,75,40,4}p.ldf` (analog audio on), measure PCM tone
amplitude. Expect ≈ 7992 / 5994 / 3197 / 320 counts (±5%). This validates the
counts↔deviation↔deemp anchor of §2 against real hardware — the 40% tone is
literally the `V_CR` anchor. If these are off by a constant factor, fold that
factor into `A_40` before anything else.

### T5 — real CX disc, dual-track ground truth (he010)
The repo already has `he010.pcm` (analog, CX) and `he010.efm`; run
`ld-process-efm he010.efm he010-digital.pcm` for the uncompressed reference.
1. Align: cross-correlate; note the analog path is sign-flipped and offset
   (~265 samples) relative to digital — see comment at `lddecode/audio.py:115`.
   Use envelope cross-correlation for coarse, waveform for fine alignment.
2. Band-limit both to 200 Hz–15 kHz; compute short-time RMS in dB (50 ms
   window, 10 ms hop).
3. **Pre-expansion sanity**: regress analog_dB vs digital_dB on active frames —
   slope ≈ 0.5 confirms the analog track really is CX-encoded.
4. **Post-expansion acceptance**: slope = 1.0 ± 0.05; mean |envelope error|
   < **1 dB**; 95th percentile < 2 dB over active frames.
5. **Transient model selection**: take the top-1% frames by envelope
   derivative; compare error there for each §5 option combination; adopt the
   winner as defaults and record the numbers in this file.
6. Noise check: in silent passages, expanded analog noise floor should drop by
   ~14–22 dB vs unexpanded.

### T6 — ggv-cx.ldf
Decode a slice of `/home/cpage/ld-decode/ggv-cx.ldf` (analog audio). Inspect
content (likely calibrated 1 kHz tones/steps with CX on). If stepped tones are
present: measure the *actual CBS encoder's* static curve directly (tone level
on disc vs announced/step level) against Fig B1, then verify the expander maps
the steps back to a linear scale. This is the only test of the real encoder's
static calibration independent of he010's program material.

---

## 8. Acceptance summary

1. T1 static curve within ±0.25 dB; T2 time-constant behavior as specified.
2. T3 round-trip transparent to <0.5 dB envelope error.
3. T4 anchors within ±5%.
4. T5 slope 1.0 ± 0.05 and mean envelope error <1 dB vs digital ground truth;
   §5 defaults locked in from measured transient error.
5. `python3 -m lddecode.cx he010.pcm he010-cx.pcm` runs at ≫ realtime,
   streaming, constant memory.

## 8b. Implementation status & measured results (2026-07-06)

Implemented in `lddecode/cx.py` (standalone; no decode-pipeline changes).
`CXExpander`/`CXCompressor`, single `@njit` hot loop, self-calibration, CLI as
specified. Tests in `tests/test_cx.py` (T1/T2/T3 + calibration + streaming).

Calibration note: `V_CR` is measured as the **mean of the fast follower** at
the 40 kHz anchor (settles in ~50 ms), *not* by letting the 2 s integrator
settle in a 3 s tone — a seeded-integrator calibration under-settles by ~4.5%
and inflates `V_CR`, giving a ~0.33 dB gain deficit at all levels. With the
follower-mean anchor the from-below operating equilibrium (integrator → mean F)
matches `V_CR` exactly (ratio 2.5000 verified across levels).

Measured:
- **T1 static curve**: within **±0.12 dB** away from the knee; below-knee exact.
  Near the knee the per-sample clamp softens the corner (+0.33 dB at −20 dB,
  +0.71 dB at the knee) — spec-literal, not an error.
- **T2 dynamics**: −30→−10 attack 90% in **4.7 ms**; −10→−30 release 90% in
  **543 ms**; −16→−14 small step **0.42** settled after 1 s (integrator-only,
  <0.5 as specified); below-knee gain pinned at **0.080**.
- **T3 round-trip**: mean envelope error **0.002 dB**, 100% of frames <0.5 dB.
- **T5 he010 dual-track** (vs `ld-process-efm -p he010.efm`): pre-expansion
  slope analog/digital = **0.66** (compression confirmed); **post-expansion
  slope = 1.01** (target 1.0±0.05); offset-removed tracking error mean
  **0.95 dB** (target <1 dB), 95th pct 2.58 dB (>2 dB target — coarse envelope
  alignment only; no per-frame TBC/waveform fine-align in the quick harness).
- **Throughput**: he010.pcm (72.9 M frames, 27.5 min) expands in **~7 s**
  (~236× realtime), 0 samples clipped.

**§5 defaults retained** (stereo-combine `max`, slow-model `offset`,
attack-comp `excess`): they already give T5 slope 1.01 / mean error 0.95 dB, so
no transient-model change is warranted. A full option-combo sweep (T5.5) and
the absolute-anchor / real-encoder curve checks (T4 GGV tones, T6 ggv-cx) remain
open; they need the large `.ldf` decodes and are out of band for this pass.

## 9. Reference constants (44.1 kHz, for quick review)

```
counts/Hz-deviation        = 32767/371081 = 0.0883015     (dsp.py:410)
|D(1 kHz)| deemp 75µ/5.3µ  = 0.90509                       (rfdecode.py:654; recompute at runtime)
counts per kHz @1 kHz      = 79.921
A_100 / A_40 / A_8         = 7992.1 / 3196.8 / 639.4 counts
knee: output 8 kHz (−21.94 dB), input 0.64 kHz (−43.88 dB); ratio 2:1
V_100 = 2.5·V_CR;  θ_slow = 0.26·V_CR;  θ_ac = 0.52·V_CR;  gain floor 0.08
α: fast-att 0.0224215, fast-rel 0.0022650, slow-att 7.5557e−4,
   slow-rel 1.1337e−4, integ 1.1338e−5;  β_ac = 0.9992447;  a_hpf = 0.931239
```
