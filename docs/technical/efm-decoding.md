# EFM Decoding

ld-decode extracts the disc's EFM stream — CD-format digital audio on
LaserDiscs with digital sound, or the data content of an LV-ROM disc such as
the BBC Domesday set — whenever digital audio is enabled (the default; disable
with `--noEFM`). The output is a `.efm` file of T-values that downstream tools
(`ld-process-efm`, decode-orc) turn into audio samples or data sectors.

The RF → `.efm` path is:

1. **Equalisation** — `lddecode/rfdecode.py` `computeefmfilter()`: a fixed
   11-anchor frequency-domain equaliser (0–2 MHz, cubic-interpolated amplitude
   and phase) applied during demodulation, producing an int16 EFM waveform at
   the input sample rate.
2. **Bit-clock recovery** — one of two selectable demodulators
   (`--efm_demod`):
    - `timing` (default) — `lddecode/efm_demod.py` `EFMTimingDemod`: a
      symbol-rate timing-recovery demodulator (decimation, AGC, a
      per-channel-bit Mueller & Müller timing loop, and bit-domain frame
      sync); see its own section below.
    - `pll` — `lddecode/efm_pll.py` `EFM_PLL`: interpolated zero-crossing
      detection feeding a run-length PLL that emits one T-value per
      recovered run, clamped into the EFM-legal range 3–11. The default
      before the timing demodulator; selecting it reproduces the previous
      `.efm` output byte for byte.
3. **Output** — `lddecode/decoder.py` `_process_efm()`: serial and stateful,
   one field's EFM slice at a time.

The demodulator is the part that decides how many frames survive on a
marginal disc.

## Output files

| File | Contents |
|------|----------|
| `.efm` | One signed byte per T-value (values 3–11), in disc order. Written in both TBC and CVBS output modes; in CVBS mode a `.efm.meta` SQLite sidecar additionally indexes the stream by frame (see the CVBS EFM extension format). |
| `.efm` (confidence-packed) | With confidence output enabled (`--efm_conf`; the default for CVBS output), each `.efm` byte instead carries the T-value in its low nibble and a 4-bit doubt (0 = trusted) in its high nibble (`T_VALUE_CONF_U8` in the CVBS EFM extension format — see below). Same file, same length; consumers separate the fields with a mask and a shift. |
| `.prefm` | The filtered EFM waveform before the PLL (int16 samples), written with `--preEFM`; for debugging and cross-capture waveform research. |

## Defaults (no flags needed)

The **timing-recovery demodulator** is the default. Decode as usual:

```bash
ld-decode --PAL capture.ldf out
ld-process-efm -b out.efm out.bin     # data disc (omit -b for audio)
```

To reproduce the previous demodulator's output (the run-length PLL) byte for
byte, e.g. for an A/B comparison:

```bash
ld-decode --efm_demod pll --PAL capture.ldf out
```

With `--efm_demod pll`, the PLL uses a **gear-shift / fast-reacquire** loop
by default. While locked it is bit-for-bit identical to the original
fixed-gain loop, so clean captures are byte-for-byte unchanged; it boosts
its phase and frequency gains only *while unlocked* — on cold start, after a
dropout, and through low-SNR regions — which is where the fixed-gain loop
used to lose framing. `LDDECODE_EFM_GEARSHIFT=0` restores the original
fixed-gain loop.

## Tuning a stubborn disc (advanced)

Individual PLL acquisition parameters (`--efm_demod pll` only) can be
overridden via the environment; leave them unset to use the tuned defaults.
The timing demodulator's own hooks are in its section below.

| Variable | Default | Effect |
|----------|---------|--------|
| `LDDECODE_EFM_GEARSHIFT` | `1` | `0` restores the original fixed-gain loop |
| `LDDECODE_EFM_PHASEGAIN_ACQ` | `0.05` | Phase gain while acquiring (higher = faster, jumpier pull-in) |
| `LDDECODE_EFM_FREQSTEPMUL` | `20` | Frequency-step multiplier while acquiring |
| `LDDECODE_EFM_LOCKERRFRAC` | `0.125` | \|phase error\| < frac·period counts as "in lock" |
| `LDDECODE_EFM_LOCKTHRESH` | `24` | Consecutive in-lock edges before declaring lock |
| `LDDECODE_EFM_EMITCONF` | unset | `1`/`0` forces confidence-packed `.efm` output on/off (same as `--efm_conf on`/`off`) |
| `LDDECODE_TBC_EFM` | unset | `1` enables EFM time-base correction (same as `--tbc_efm`) |

The equalisation front end has sweep hooks of its own (used for filter-tuning
experiments; leave unset for normal decodes):

| Variable | Default | Effect |
|----------|---------|--------|
| `LDDECODE_EFM_AMP` | built-in table | Override the equaliser's 11 amplitude anchors (comma-separated values over 0–1.9 MHz) |
| `LDDECODE_EFM_SGORDER` | `60` | Super-gaussian band-pass roll-off order (60 ≈ brick-wall; lower = gentler, less ringing) |
| `LDDECODE_EFM_SGHIGH` | PAL `1750000`, NTSC `1600000` | Band-pass upper edge in Hz (the PAL 1.75 MHz edge is the IEC 60856 value) |
| `LDDECODE_EFM_SGLOW` | `20000` | Band-pass lower edge in Hz |
| `LDDECODE_EFM_FRONTEND` | unset | `hardware` substitutes the player-derived RF EQ + elliptic LPF front end (comparison experiments; see the front-end comparison section) |

**Ensemble tip:** different settings lock *different* marginal frames. Decoding
a hard disc several times with varied settings and merging the resulting
sectors recovers more than any single setting alone — see the ensemble
workflow below.

## The timing-recovery demodulator (`--efm_demod timing`)

`--efm_demod timing` selects `lddecode/efm_demod.py` `EFMTimingDemod` in
place of the PLL. Where the PLL times zero crossings against a free-running
clock — so a single ±1 T misquantisation shifts every following bit in the
frame — this demodulator recovers the 4.3218 Mbit/s channel clock itself and
takes one soft decision per channel bit:

1. **Decimation** — cascaded half-band FIR stages halve the sample rate
   while it stays ≥ 8 MHz (40 MHz → 10 MHz), leaving the 0–1.9 MHz EFM band
   untouched (passband flat within ±0.011 dB, alias rejection ≥ 80 dB).
2. **Conditioning** — a one-pole DC blocker and a running-power AGC
   normalise the waveform to unit RMS, so loop gains are level-independent.
3. **Timing recovery** — a cubic-interpolating fractional resampler emits
   one soft sample per channel bit; a Mueller & Müller timing-error detector
   updates a second-order PI loop *every channel bit* (natural frequency
   1.2 kHz, damping 0.6, corrections clamped to 2 %/4 % of the bit period).
   While the timing error is large (cold start, frequency offset, after a
   dropout) an acquisition gear boosts the loop bandwidth ×6 for fast
   pull-in — a ±2 % channel-rate offset is acquired in a few frames.
4. **Framing and emission** — NRZI toggles shift into a 24-bit register;
   frame sync is the IEC 60908 T11-T11 pattern (0x801002) confirmed by a
   588-bit position counter with 7-frame lock hysteresis that flywheels
   across corrupted syncs. Emitted runs are legalised (< 3 merged into the
   following run, > 11 split) preserving the total channel-bit count, so
   the `.efm` contract is unchanged. While locked, a sync the pattern
   matcher missed by a marginal edge is *restored* from the position
   counter — the pending runs are rewritten to T11-T11 (channel bits
   preserved, confidence capped low) exactly as a hardware transport
   regenerates sync, which keeps downstream sync-scanning decoders framed;
   damage that cannot be rewritten to legal run lengths is left visible.
   Up to one frame of T-values waits for its closing sync, so the decoder
   drains the demodulator at close (TBC mode; the tail lands after the
   last field's `efmTValues` count and belongs to no field).

On clean captures both demodulators frame essentially perfectly; the timing
demodulator's advantage appears on noisy and marginal material, where per-bit
decisions plus the sync flywheel hold framing long after the run-length PLL
starts misquantising (see the baseline table below). Decode time is a few
percent higher than the PLL path, plus a one-time Numba compilation cost of
a few seconds per run.

Loop constants are exposed for sweeps (leave unset for the tuned defaults):

| Variable | Default | Effect |
|----------|---------|--------|
| `LDDECODE_EFM_TIMING_FN` | `1200` | Timing-loop natural frequency in Hz (higher = faster tracking, more bit-noise) |
| `LDDECODE_EFM_TIMING_ZETA` | `0.6` | Loop damping factor |
| `LDDECODE_EFM_TIMING_TED` | `0.5` | Assumed timing-error-detector gain (calibrates the loop bandwidth) |
| `LDDECODE_EFM_TIMING_ACQBOOST` | `6` | Loop-bandwidth boost while acquiring |
| `LDDECODE_EFM_TIMING_EQTAPS` | `0` | Adaptive-equaliser tap count (same as `--efm_eq_taps`) |

### Adaptive equaliser (`--efm_eq_taps`, experimental, off by default)

The timing demodulator carries an optional decision-directed sign-sign LMS
FIR at symbol rate (centre-tap-initialised, taps leakage-bounded around the
identity, odd tap counts 3–15). It is **off by default** because measurement
says it does not help this pipeline:

- The demodulator's per-bit sign decisions plus the sync flywheel are
  already immune to static linear distortion — synthetic band-limiting down
  to 0.9 MHz and single-bit echoes up to 0.95× amplitude leave
  `frame_588_fraction` at 1.0 with no equaliser at all.
- The remaining failures are noise-dominated, and there the ±1
  slicer-target adaptation is neutral at best and harmful when active
  (ve-snw-cut 0.998171 → 0.989979 with 3 taps; dolby-surround inner
  0.999602 → 0.998010).

The machinery itself is correct — on a true antipodal symbol stream with
symbol-spaced ISI it converges to the channel inverse (unit-tested) — the
EFM soft-sample stream is simply not that signal. The flag remains for
experimentation on badly distorted discs; check the oracle's scores before
trusting its output.

## Confidence-packed `.efm` output (`--efm_conf`)

Legal T-values are 3–11, so they only ever occupy the low nibble of an
`.efm` byte. With confidence output enabled, the high nibble carries the
demodulator's *doubt* about that run:

```
bit  7 6 5 4   3 2 1 0
      doubt     T-value        t = byte & 0x0F;  doubt = byte >> 4
```

Doubt 0 means full trust — so a fully trusted run packs to its plain
T-value — and values approaching 15 mean the run is a likely Reed-Solomon
erasure candidate for the downstream decoder. This is the
`T_VALUE_CONF_U8` encoding of the CVBS EFM extension format.

The default follows the output mode:

- **CVBS output: on.** The `.efm.meta` sidecar declares the encoding in
  its `efm_stream` table (extension schema version 2), so consumers know
  how to read the stream, and `analysis/cvbs_verify.py` checks the
  declaration.
- **TBC output: off**, so the plain `.efm` keeps working byte-for-byte
  with legacy tools (`ld-process-efm` and friends). TBC mode has no
  metadata sidecar to declare the encoding, so forcing it on
  (`--efm_conf on`, or `LDDECODE_EFM_EMITCONF=1`) is for consumers that
  already know they are getting a packed stream. Because the high nibble
  stores doubt, a plain stream is byte-identical to a packed stream with
  zero doubt throughout — a confidence-aware consumer therefore reads a
  legacy plain `.efm` correctly as fully trusted, and a legacy tool fed a
  packed stream only sees out-of-range bytes on the runs the demodulator
  actually doubted. The encodings still cannot be told apart by
  inspection, so packed output must be declared (or known out of band).

What the confidence measures:

- With the **PLL**, how close the run's closing edge fell to the loop's
  predicted clock grid (near half a bit period off → 0).
- With the **timing demodulator**, the weakest soft sample inside the run
  combined with the framing state: T-values inside frames that fail the
  sync/588-bit check — including everything decoded before frame lock —
  are capped low (packed doubt 11), marking whole suspect frames as
  erasure candidates rather than only individually mis-timed edges.

The demodulators produce 8-bit confidences internally; packing inverts
and keeps the top four bits (confidence 255 → doubt 0, and
`(15 - doubt) * 17` restores the 0–255 confidence scale).

## `--tbc_efm` (experimental, off by default)

`--tbc_efm` (or `LDDECODE_TBC_EFM=1`) time-base-corrects the EFM waveform onto
the video line time-base before the PLL. It does not improve a single-capture
decode (the recovered sector set is the same with or without), so it is off by
default; it exists to align the pre-PLL EFM waveforms of *multiple captures of
the same disc* onto a common disc-position time-base for cross-capture
stacking and waveform research.

## Ensemble decoding workflow (LV-ROM / data discs)

For a marginal data disc, decode several times with varied PLL settings,
convert each `.efm` to a data image, then stack:

```bash
for n in 1 2 3; do
    LDDECODE_EFM_LOCKERRFRAC=0.$((n+10)) ld-decode --PAL capture.ldf out$n
    ld-process-efm -b out$n.efm out$n.bin
done
python -m lddecode.stack_efm_data stacked.bin out1.bin out2.bin out3.bin
python -m lddecode.compare_efm_data stacked.bin reference.bin   # optional check
```

`stack_efm_data.py` aligns the captures by robust multi-anchor consensus (no
external reference needed) and takes the per-sector majority;
`compare_efm_data.py` validates a stack against a known-good reference image.

## Measuring T-value quality

Because valid runs are only T3–T11, every EFM frame is exactly 588 channel
bits, and each frame starts with a unique T11-T11 sync pair (IEC 60908;
LaserDisc digital audio carries CD-format EFM per IEC 60857 section 10), a
`.efm` stream is directly scoreable without any downstream decoder.
`analysis/efm_quality.py` (wrapping the pure scoring functions in
`lddecode/efm_score.py`) reports:

- **`sync_rate`** — T11-T11 sync pairs found, per 588 channel bits of stream.
  1.0 means every expected frame position carries a sync; corruption can push
  it slightly above 1.0 by faking pairs.
- **`frame_588_fraction`** — the fraction of gaps between successive syncs
  that are exactly 588 channel bits. A ±1 T misquantisation anywhere in a
  frame moves that frame off 588, so this is the most sensitive single number
  for demodulator quality.
- **`invalid_t_fraction`** — T-values outside 3–11 (the current PLL clamps,
  so this is 0 by construction; a future demodulator must keep it 0).
- **frame-length error and T-value histograms**, and confidence statistics
  when the stream is confidence-packed (`--packed`).

```bash
python analysis/efm_quality.py out.efm \
    --min-sync-rate 0.99 --min-frame-588 0.98 --max-invalid-t 0
# confidence-packed stream (the CVBS-mode default): add --packed
python analysis/efm_quality.py out.efm --packed --min-frame-588 0.98
```

The encoding cannot be detected from the bytes, so pass `--packed` exactly
when the decode wrote packed output (CVBS default, or `--efm_conf on`).

The final line is `EFM QUALITY: PASS (...)` or `EFM QUALITY: FAIL (...)`; with
no threshold flags the run is informational. CTest gates every EFM-bearing
capture in `testdata/` with thresholds set just under the measured baseline
below (`cmake_modules/LdDecodeTests.cmake`), so a demodulation regression
fails CI.

**Gapped discs:** the BBC Domesday / AIV LV-ROM discs interleave EFM data
sections with analogue-audio-only or silent sections, and ld-decode emits
(garbage) T-values across the gaps too, so a whole-capture or gap-spanning
score is bounded below 1.0 by the disc layout rather than the demodulator.
Domesday scores are only comparable against a baseline of the same capture
region — and a cut that lands entirely in a gap (both Domesday *outer* radius
cuts in `testdata/`) scores 0 by nature and is left ungated.

## Baseline measurements

PLL demodulator (gear-shift, `--efm_demod pll`), measured with
`analysis/efm_quality.py`. These were the numbers the original CTest
thresholds derived from; the timing-recovery demodulator's validation
results against them are in the next section.

### `testdata/` captures (CI gates)

| Capture | System | T-values | sync_rate | frame_588_fraction |
|---------|--------|---------:|----------:|-------------------:|
| pal/jason-testpattern (TBC) | PAL | 144,675 | 1.000000 | 1.000000 |
| ntsc/issue176 (TBC) | NTSC | 118,082 | 1.000021 | 1.000000 |
| ntsc/ve-snw-cut (TBC) | NTSC | 868,290 | 0.998021 | 0.996477 |
| ntsc/ve-snw-cut (CVBS, 6 frames) | NTSC | 179,872 | 0.996048 | 0.988372 |
| ntsc/ve-monitor (CVBS) | NTSC | 2,637,423 | 0.999381 | 0.991516 |
| radius/dolby-surround-side1-inner | NTSC | 600,441 | 0.998778 | 0.991223 |
| radius/dolby-surround-side1-middle | NTSC | 570,482 | 0.998712 | 0.991618 |
| radius/dolby-surround-side1-outer | NTSC | 600,980 | 0.997639 | 0.990400 |
| radius/domesday-ds2-community-north-inner | PAL | 900,397 | 0.997257 | 0.992212 |
| radius/domesday-ds2-community-north-middle | PAL | 1,044,537 | 0.997895 | 0.993289 |
| radius/domesday-ds1-community-north-outer | PAL | 1,445,796 | 0.000212 | 0.000000 |
| radius/domesday-ds2-community-north-outer | PAL | 1,448,773 | 0.000000 | 0.000000 |

The two Domesday outer cuts land in an analogue-audio gap between EFM
sections (see above); they are recorded here as layout facts, not decoder
faults. The GGV pressings (`pal/ggv-mb-1khz`, the `ggv1011`/`ggv1069` radius
cuts), `industrial-lv`, `ntsc/ggv-ntsc-mb-v2800` and `pal/kagemusha-leadout`
carry no EFM at all.

### Local captures (500-frame segments from frame 2000, not in CI)

| Capture | System | T-values | sync_rate | frame_588_fraction |
|---------|--------|---------:|----------:|-------------------:|
| Grosse Pointe Blank side 1 (LDV4300D) | PAL | 17,804,419 | 0.999932 | 0.999918 |
| Roger Rabbit Bonus Disc side 1 (LDV4300D) | PAL | 17,764,356 | 0.999986 | 0.999986 |
| Bambi side 1 (Japan, LDG) | NTSC | 14,864,847 | 0.999931 | 0.999910 |
| Cinderella side 1 (Japan, CC) | NTSC | 14,736,454 | 0.999931 | 0.999910 |
| Domesday DS1 Community North | PAL | 17,997,553 | 0.999115 | 0.998761 |
| City Disc Culture1 side 1 | PAL | 24,700,310 | 0.000043 | 0.000000 |

The City Disc segment is another gap example: frames 2000–2500 of that side
carry no EFM section at all, so the score reflects the disc layout. Choose
EFM-active regions (or score per region) when baselining gapped LV-ROM
discs.

### Timing-recovery demodulator validation (the default switch)

The same captures decoded with `--efm_demod timing` (TBC mode; sync
restoration and end-of-stream flush included). `frame_588_fraction` shown
as PLL → timing:

| Capture | System | PLL | timing |
|---------|--------|----:|-------:|
| pal/jason-testpattern | PAL | 1.000000 | 1.000000 |
| ntsc/issue176 | NTSC | 1.000000 | 1.000000 |
| ntsc/ve-snw-cut | NTSC | 0.996477 | 0.998171 |
| ntsc/ve-monitor | NTSC | 0.991516 | 0.999909 |
| radius/dolby-surround-side1-inner | NTSC | 0.991223 | 0.999602 |
| radius/dolby-surround-side1-middle | NTSC | 0.991618 | 0.999801 |
| radius/dolby-surround-side1-outer | NTSC | 0.990400 | 0.999403 |
| radius/domesday-ds2-community-north-inner | PAL | 0.992212 | 0.999654 |
| radius/domesday-ds2-community-north-middle | PAL | 0.993289 | 0.999665 |
| Grosse Pointe Blank side 1 | PAL | 0.999918 | 0.999939 |
| Roger Rabbit Bonus Disc side 1 | PAL | 0.999986 | 1.000000 |
| Bambi side 1 | NTSC | 0.999910 | 0.999976 |
| Cinderella side 1 | NTSC | 0.999910 | 0.999976 |
| Domesday DS1 Community North | PAL | 0.998761 | 0.999490 |

`sync_rate` improves in step on every capture, and `invalid_t_fraction`
stays 0. The timing demodulator meets or beats the PLL on every validation
capture and beats the museld figures below on every capture measured there
(dolby inner 0.999602 vs museld 0.998397; domesday inner 0.999654 vs
0.995224; ve-snw-cut 0.998171 vs 0.997807) — which is why it became the
default. `--efm_demod pll` reproduces the previous output byte for byte.

### Front-end filter comparison (defaults unchanged)

Two front ends were compared on the validation captures, decoding with the
timing demodulator and judging with both the frame oracle and the
**symbol-separation metric** (`lddecode.efm_score.symbol_separation`, after
museld's `eval_efm_fir_filter.m`): the RMS distance of the filtered
waveform's zero-crossing intervals from the legal T3–T11 grid, in
channel-bit units, measured on the `.prefm` output
(`analysis/efm_quality.py --prefm`). Lower is better; the metric needs no
demodulator, so it ranks filters directly.

- **anchor** — the shipped 11-anchor equaliser + super-gaussian band-pass
  (PAL curve tuned 2026, NTSC legacy curve).
- **hardware** — a player-derived alternative
  (`LDDECODE_EFM_FRONTEND=hardware`): the Sony HIL-C1 service-manual
  "RF EQ" biquad (bilinear coefficients via museld) cascaded with an
  elliptic `ellip(4, 3 dB, 40 dB, 1.7 MHz)` low-pass.

| Capture | System | anchor f588 / sep_rms | hardware f588 / sep_rms |
|---------|--------|----------------------:|------------------------:|
| jason-testpattern | PAL | 1.000000 / 0.125 | 1.000000 / 0.177 |
| ve-snw-cut | NTSC | 0.998171 / 0.142 | 0.997747 / 0.182 |
| dolby-surround-side1-inner | NTSC | 0.999602 / 0.127 | 0.998207 / 0.190 |
| domesday-ds2-community-north-inner | PAL | 0.999654 / 0.174 | 0.991763 / 0.212 |

The shipped anchor equaliser wins on every capture on both measures (and
the two measures rank the front ends identically, which is the
cross-validation of the metric), so the defaults are unchanged. The
`LDDECODE_EFM_FRONTEND=hardware` hook remains for experiments.

### museld comparison

[museld](https://github.com/staffanu/museld)'s `ac3rf-efm-decode`
(`--t-values-output-filename`) decodes the same RF with a different
architecture (decimation, fractional-resampling Mueller & Müller timing
recovery, adaptive equalisation) and legalises its T-values the same way, so
its output scores with the same oracle.

Measured with museld master (September 2026), `--efm-rf` defaults, on the
same `testdata/` captures. museld decodes the entire capture from sample 0
while ld-decode starts at the first fielded video, so the T-value counts
differ slightly; the rates remain directly comparable.

| Capture | System | Decoder | sync_rate | frame_588_fraction |
|---------|--------|---------|----------:|-------------------:|
| pal/jason-testpattern | PAL | ld-decode | 1.000000 | 1.000000 |
| pal/jason-testpattern | PAL | museld | 0.999834 | 1.000000 |
| ntsc/ve-snw-cut | NTSC | ld-decode | 0.998021 | 0.996477 |
| ntsc/ve-snw-cut | NTSC | museld | 0.997794 | 0.997807 |
| radius/dolby-surround-side1-inner | NTSC | ld-decode | 0.998778 | 0.991223 |
| radius/dolby-surround-side1-inner | NTSC | museld | 0.998385 | 0.998397 |
| radius/domesday-ds2-community-north-inner | PAL | ld-decode | 0.997257 | 0.992212 |
| radius/domesday-ds2-community-north-inner | PAL | museld | 0.995224 | 0.995224 |

On clean captures the two decoders are equivalent; on the harder captures
museld's symbol-rate timing recovery held a clear `frame_588_fraction`
advantage over the PLL (fewer ±1 T misquantisations). That gap motivated
ld-decode's own timing-recovery demodulator, which now exceeds these museld
figures on every capture measured here (see the validation table above).

## References

- IEC 60908 (CD digital audio): EFM channel code, 588-bit frame, sync pattern.
- IEC 60857 section 10: LaserDisc digital sound carries CD-format EFM.
- [museld](https://github.com/staffanu/museld) (GPLv3): the comparison
  decoder used for the baseline above.
