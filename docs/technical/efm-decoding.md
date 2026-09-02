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
2. **Bit-clock recovery** — `lddecode/efm_pll.py` `EFM_PLL`: interpolated
   zero-crossing detection feeding a run-length PLL that emits one T-value per
   recovered run, clamped into the EFM-legal range 3–11.
3. **Output** — `lddecode/decoder.py` `_process_efm()`: serial and stateful,
   one field's EFM slice at a time.

The PLL is the part that decides how many frames survive on a marginal disc.

## Output files

| File | Contents |
|------|----------|
| `.efm` | One signed byte per T-value (values 3–11), in disc order. Written in both TBC and CVBS output modes; in CVBS mode a `.efm.meta` SQLite sidecar additionally indexes the stream by frame (see the CVBS EFM extension format). |
| `.efmc` | Optional confidence sidecar, one unsigned byte per T-value, byte-for-byte parallel to `.efm` (see below). TBC output mode only; opt-in via `LDDECODE_EFM_EMITCONF=1`. |
| `.prefm` | The filtered EFM waveform before the PLL (int16 samples), written with `--preEFM`; for debugging and cross-capture waveform research. |

## Defaults (no flags needed)

The PLL uses a **gear-shift / fast-reacquire** loop by default. While locked it
is bit-for-bit identical to the original fixed-gain loop, so clean captures are
byte-for-byte unchanged; it boosts its phase and frequency gains only *while
unlocked* — on cold start, after a dropout, and through low-SNR regions — which
is where the fixed-gain loop used to lose framing.

Decode as usual:

```bash
ld-decode --PAL capture.ldf out
ld-process-efm -b out.efm out.bin     # data disc (omit -b for audio)
```

To restore the original fixed-gain loop for an A/B comparison:

```bash
LDDECODE_EFM_GEARSHIFT=0 ld-decode --PAL capture.ldf out
```

## Tuning a stubborn disc (advanced)

Individual acquisition parameters can be overridden via the environment; leave
them unset to use the tuned defaults.

| Variable | Default | Effect |
|----------|---------|--------|
| `LDDECODE_EFM_GEARSHIFT` | `1` | `0` restores the original fixed-gain loop |
| `LDDECODE_EFM_PHASEGAIN_ACQ` | `0.05` | Phase gain while acquiring (higher = faster, jumpier pull-in) |
| `LDDECODE_EFM_FREQSTEPMUL` | `20` | Frequency-step multiplier while acquiring |
| `LDDECODE_EFM_LOCKERRFRAC` | `0.125` | \|phase error\| < frac·period counts as "in lock" |
| `LDDECODE_EFM_LOCKTHRESH` | `24` | Consecutive in-lock edges before declaring lock |
| `LDDECODE_EFM_EMITCONF` | unset | `1` writes the `.efmc` confidence sidecar (TBC mode) |
| `LDDECODE_TBC_EFM` | unset | `1` enables EFM time-base correction (same as `--tbc_efm`) |

The equalisation front end has sweep hooks of its own (used for filter-tuning
experiments; leave unset for normal decodes):

| Variable | Default | Effect |
|----------|---------|--------|
| `LDDECODE_EFM_AMP` | built-in table | Override the equaliser's 11 amplitude anchors (comma-separated values over 0–1.9 MHz) |
| `LDDECODE_EFM_SGORDER` | `60` | Super-gaussian band-pass roll-off order (60 ≈ brick-wall; lower = gentler, less ringing) |
| `LDDECODE_EFM_SGHIGH` | PAL `1750000`, NTSC `1600000` | Band-pass upper edge in Hz (the PAL 1.75 MHz edge is the IEC 60856 value) |
| `LDDECODE_EFM_SGLOW` | `20000` | Band-pass lower edge in Hz |

**Ensemble tip:** different settings lock *different* marginal frames. Decoding
a hard disc several times with varied settings and merging the resulting
sectors recovers more than any single setting alone — see the ensemble
workflow below.

## The `.efmc` confidence sidecar

With `LDDECODE_EFM_EMITCONF=1` (TBC output mode), ld-decode writes
`<out>.efmc`: one uint8 per T-value, exactly parallel to `<out>.efm`. The
value is the PLL's soft decision for that run — how close the run's closing
edge fell to the loop's predicted clock grid. 255 means the edge landed on the
grid (full trust); values approaching 0 mean the edge fell near half a bit
period off (likely mis-timed, a Reed-Solomon erasure candidate for the
downstream decoder). It is opt-in so default decodes are byte-for-byte
unchanged.

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
- **frame-length error and T-value histograms**, and `.efmc` confidence
  statistics when given the sidecar.

```bash
python analysis/efm_quality.py out.efm --efmc out.efmc \
    --min-sync-rate 0.99 --min-frame-588 0.98 --max-invalid-t 0
```

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

Current PLL demodulator (gear-shift default), measured with
`analysis/efm_quality.py`. These are the numbers the CTest thresholds derive
from and that any EFM demodulation change must meet or beat.

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
museld's symbol-rate timing recovery holds a clear `frame_588_fraction`
advantage (fewer ±1 T misquantisations), which is the gap the planned
timing-recovery demodulator exists to close.

## References

- IEC 60908 (CD digital audio): EFM channel code, 588-bit frame, sync pattern.
- IEC 60857 section 10: LaserDisc digital sound carries CD-format EFM.
- [museld](https://github.com/staffanu/museld) (GPLv3): the comparison
  decoder used for the baseline above.
