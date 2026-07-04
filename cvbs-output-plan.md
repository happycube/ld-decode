# Add a spec-compliant CVBS output mode to ld-decode

Repo: `/home/cpage/ld-decode/chad-cutdown`, branch `chad-2026.06.13-cutdown`. Spec: `cvbs-file-format-specification/docs/` (index.md, video-standard-presets.md, sample-encoding-presets.md, signal-state-presets.md). This plan is self-contained.

## Context

ld-decode's `.tbc` output is a per-field, line-orthogonal raster. The CVBS file format defines a standards-based interchange format (`.composite` + `.meta`) built on true 4×fsc digital composite (SMPTE 244M for NTSC, EBU Tech 3280 for PAL). For **NTSC this is nearly the same raster** (4fsc is line-locked: exactly 910 samples/line, 477,750 samples/frame). For **PAL it is fundamentally different**: PAL 4fsc is **not line-locked** — fsc = (1135/4 + 1/625)·fH, so a line is 1135.0064 samples, the sampling lattice slips **+0.0064 samples/line (4 samples/frame)**, is **non-orthogonal**, repeats at *frame* rate, and the only normative sample count is the **frame total: 709,379 samples**. The current PAL TBC (every line scaled to exactly 1135 samples) cannot be repackaged into this; PAL needs a new continuous-frame-time resampling path.

Scoping decisions (user-confirmed):
- **v1 declares `STANDARD_TBC_UNLOCKED`** for both systems (lattice placed from sync/pilot timing; subcarrier phase is whatever the source's Sc/H gives). Burst-anchoring the lattice (`STANDARD_TBC_LOCKED`) is a v2 follow-up.
- **`--cvbs` replaces the `.tbc` video output** (PCM/EFM/log side outputs continue; `.tbc.json`/`.tbc.db` video metadata replaced by `.meta`).
- **Audio ships in v1** as spec WAV (`<base>_audio_00.wav`) with an honest `audio_locked` flag.

## Normative requirements (from the spec)

| Item | NTSC | PAL |
|---|---|---|
| Sample rate | 4×fsc = 14,318,181.81… Hz | 4×fsc = **17,734,475 Hz exact** |
| Line structure | 910 samples/line, orthogonal; sync edge midpoint between samples 784/785; active = samples 0–767 | **1135.0064 avg**, non-orthogonal; frame 1 line 1 sync edge midway between samples **957/958**, advancing 0.361 ns (0.0064 samples)/line |
| Frame size (normative w/ TBC) | 525×910 = **477,750** samples | **709,379** samples (frame-level only) |
| File layout | sequential **frames** (2 fields each), no headers/markers | same |
| 10-bit levels (`CVBS_U16_4FSC` = value<<6) | sync 16, blanking 240, black 282 (+7.5 setup; 240 for NTSC-J via `black_level` override), white 800, peak 1019 | sync 4, blanking=black 256, white 844, peak 1019 |
| Protected values | 10-bit 0–3 and 1020–1023 must never appear → clamp to [4, 1019] | same |
| Colour sequence | 2 frames (A/B); ld-decode convention: file starts frame A | 4 frames; ld-decode convention: starts at *midpoint* of frame 1 (documented in spec as informational) |
| Metadata | `.meta` SQLite, `PRAGMA user_version = 8`, single `cvbs_file` table | same |
| Audio | stereo PCM WAV s16le; locked = 44,100,000/1001 Hz (1470/frame, header says 44056) | locked = 44100 Hz (1764/frame) |

Existing internals that line up (verified):
- ld-decode's 16-bit levels already ARE the 10-bit tables ×64: `Field.output_black=0x0400` (=16<<6, NTSC sync tip), `output_white=0xC800` (=800<<6); `FieldPAL` overrides `0x0100` (=4<<6, PAL sync tip) and `0xD300` (=844<<6). So `CVBS_U16_4FSC` is the natural encoding; the work is verification + clamping, not remapping. (Verify blanking lands exactly at 240<<6 / 256<<6 — the metrics db showed `blanking_16b=15091` vs expected 15360; determine whether that's a metadata value vs actual signal placement and correct the mapping if the signal itself is off.)
- NTSC TBC raster is already 910×(263+262) = the CVBS frame, byte-identical layout apart from level clamping and frame pairing.
- `--ntsc_audio_rate` already implements the NTSC locked audio rate (1470 samples/frame); PAL audio is already frame-locked at 44100 (1764/frame).
- `SysParams_PAL["outlinelen_pilot"]` is precedent for an alternate PAL output timing mode.

## Design

### CLI and plumbing

- `lddecode/main.py`: add `--cvbs` flag (bool). Passed through `LDdecode.__init__` as `output_cvbs=True`.
- `lddecode/decoder.py` (`LDdecode`): when `output_cvbs`, do not open `.tbc`/create the tbc sqlite video tables; instead instantiate `CVBSWriter` (new module). `writeout()` hands each decoded field (dspicture-equivalent array + field info) to the writer instead of writing bytes directly.

### New module `lddecode/cvbs.py` — `CVBSWriter`

Responsibilities:
1. **Frame pairing.** Buffer fields; emit only complete frames (first+second field). Drop a leading unpaired field so the file starts on the conventional sequence position (NTSC: colour frame A via `fieldPhaseID`; PAL: keep ld-decode's documented half-frame-offset convention). Drop a trailing unpaired field. Track `number_of_sequential_frames`.
2. **Level compliance.** Clamp output to 10-bit [4, 1019] <<6 (u16 [256, 65216]). Count clamped samples; if any legitimate non-standard content is expected (PAL LD pilot burst in blanking!) set `has_nonstandard_values=TRUE` rather than clipping it away — pilot lives within legal amplitude range, so clamping only protects the reserved codes.
3. **`.meta` SQLite** (exact schema from index.md §Metadata, `PRAGMA user_version=8`): one `cvbs_file` row — `preset` NTSC/PAL, `sample_encoding_preset='CVBS_U16_4FSC'`, `signal_state_preset='STANDARD_TBC_UNLOCKED'`, `signal_type='composite'`, `decoder='ld-decode'`, git branch/commit (already available via version machinery), `number_of_sequential_frames` (filled at close), `black_level` (NULL normally; 240 when `--NTSCJ`), `has_nonstandard_values` (TRUE for PAL LD w/ pilot; else NULL), `audio_locked` (below), `capture_notes` (e.g. "LaserDisc PAL pilot burst present in blanking").
4. **Audio WAV.** Take the existing decoded 16-bit stereo analog-audio stream (currently written raw to `.pcm`) and write `<basename>_audio_00.wav` with a proper RIFF header. `audio_locked`: PAL → TRUE (44100, verify 1764/frame exactly over the run); NTSC → TRUE only when `--ntsc_audio_rate` was given (header nSamplesPerSec=44056 per spec), else FALSE (44100). Patch the RIFF sizes at close. EFM/AC3 continue as today (the spec has extension docs for EFM; wiring that sidecar format is out of scope for v1).

### NTSC video path (small)

The existing line-locked downscale already produces the 4fsc orthogonal raster. Work:
- Verify the raster's sync placement matches SMPTE 244M expectations closely enough to document (informational, not normative for UNLOCKED): the spec puts 0H (sync edge midpoint) between samples 784/785, i.e. the digital line starts in *active video*, not at sync. Current TBC lines start near 0H. **Decision: emit with a constant sample rotation per line** so the stored digital line matches the 244M structure (active at samples 0–767, sync edge at 784.5). This is a cheap `np.roll`-equivalent index shift at write time (NTSC is orthogonal, so a per-line constant works); it makes consumers' preset-defined VBI/active windows land correctly.
- Pair fields into 477,750-sample frames; clamp; stream.

### PAL video path (the core work)

**Problem.** True PAL 4fsc output must be a continuous per-frame sample sequence on a lattice defined in *time* (17,734,475 Hz), not per-line rasters. Per EBU 3280: frame line 1's 0H falls at sample 957.5; each subsequent line's 0H falls 1135.0064 samples later; after 625 lines the lattice has slipped exactly 4 samples and the next frame repeats the structure. Half-lines at the field boundaries are part of the continuous sequence — there is no per-line padding.

**Approach: continuous frame-time resampler fed by linelocs.**
The decoder already produces, per field, `linelocs` — input-sample positions of each line's 0H — plus per-line wow (`computewow_scaled`). Frame assembly:

1. For a paired frame, build a 625-entry array of (input_position_of_0H, input_samples_per_line) covering field A's lines then field B's, using the same lineloc data `downscale()` uses today. Field B's entries continue frame line numbering (offset 312.5 lines — the half-line seam falls inside vsync where both fields have decoded data; use field A's trailing lines / field B's leading lines from their `proclines` margins to cover the junction, the same data `rf_tbc()` relies on).
2. Define the output lattice: output sample j of the frame (j = 0 … 709,378) corresponds to frame time t_j = (j + j0)/fs_cvbs, where j0 encodes the fixed origin (0H of frame line 1 at lattice position 957.5). For each output line k (boundaries at k·64 µs exactly), the covered output samples are those with t_j in [k, k+1)·64 µs — **1135 or 1136 samples with a fractional start phase φ_k that accumulates by 0.0064/line and wraps by 4/frame**.
3. Map each output sample to input position `lineloc[k] + frac(t_j within line k) × linelen[k]` and interpolate with the existing cubic `scale()` machinery (`lddecode/dsp.py:scale` takes arbitrary float start/end — call it per line with `start = lineloc[k] + φ_k·step`, `step = linelen[k]/1135.0064`, `count = n_k`). A new njit helper `scale_line_fractional` (or a generalized `scale_field`) keeps this fast; the accumulator arithmetic must be exact-rational (use integers: 0.0064 = 4/625; per-line sample count n_k and phase from `(1135·625 + 4)`-based integer math, never accumulated floats — this is what guarantees **exactly 709,379 samples every frame**).
4. Output rounding/clamping identical to NTSC.

**What this deliberately does NOT do in v1:** rotate the lattice to anchor burst at 45°-to-+U (that's the LOCKED upgrade). The lattice origin is defined purely by the sync-derived linelocs; subcarrier phase relative to the lattice is the source's Sc/H. Declared `STANDARD_TBC_UNLOCKED` accordingly (the spec explicitly lists this decoder behavior as the typical UNLOCKED case).

**Field class touch points** (`lddecode/field.py`): expose per-field lineloc/wow data in a form the frame assembler can consume without re-deriving (`FieldPAL.cvbs_lineinfo()` returning the same arrays `downscale()` uses). The existing per-line `downscale()` raster is *not* produced in CVBS mode (saves the work); dropout/metrics code that reads `dspicture` still needs it — so in CVBS mode keep computing the standard `dspicture` for internal metrics/DOD, but *write* only the CVBS lattice output. (Metrics/VITS/auto-cal all read `dspicture`; keeping it avoids destabilizing calibration. Cost is one extra resample per field for PAL — acceptable.)

### v2 follow-ups (documented, not in scope)

- **Burst-locked mode** (`STANDARD_TBC_LOCKED`): measure per-frame mean burst-vs-lattice phase (PAL: fold V-switch; use `clb_findbursts`), apply a global fractional-sample lattice shift + choose frame parity so the file starts at PAL sequence frame 1 / Sc/H 0°; NTSC analog uses the existing fsc_phase machinery rotated to the 244M canonical (+123° I at line 10 sample 0 of frame A).
- **Dropout extension sidecar** per `docs/extensions/dropout-extension-format.md` (data already exists in the internal dropout lists; coordinates must be re-expressed in CVBS frame-sample space — for PAL that means through the non-orthogonal mapping).
- **EFM extension** per `docs/extensions/efm-extension-format.md`.
- **YC dual-file output** (`signal_type='yc'`): not meaningful for ld-decode composite sources.

## Files

| File | Change |
|---|---|
| `lddecode/cvbs.py` (new) | `CVBSWriter`: frame pairing, PAL frame assembler, clamping, `.meta` writer, WAV writer (~350 lines) |
| `lddecode/dsp.py` | njit `scale_line_fractional` (or generalize `scale_field`) for fractional-phase per-line resampling |
| `lddecode/field.py` | `FieldPAL.cvbs_lineinfo()`; NTSC per-line rotation constant |
| `lddecode/decoder.py` | `output_cvbs` wiring in `__init__`/`writeout`/`close`; skip tbc video file+tables in CVBS mode |
| `lddecode/main.py` | `--cvbs` flag; pass-through; forbid `--cvbs` with incompatible flags (e.g. 10-bit tbc packing options if any) |
| `lddecode/params.py` | exact CVBS constants: `PAL_CVBS_FS = 17734475`, `PAL_CVBS_FRAME = 709379`, level-table constants per system |
| `scripts/cvbs_verify.py` (new) | standalone compliance checker (below) |
| `cmake_modules/LdDecodeTests.cmake` | `decode-ntsc-cvbs`, `decode-pal-cvbs` + verify assertions |

## Verification

**`scripts/cvbs_verify.py`** — reads `.composite` + `.meta` and checks:
1. File size = `number_of_sequential_frames` × frame_bytes (477,750×2 NTSC / 709,379×2 PAL) exactly.
2. No protected sample values (10-bit <4 or >1019 after >>6; and LSBs all zero for U16 preset).
3. Level sanity: sync tip / blanking / white found near preset values (histogram peaks).
4. **Sync lattice check (the PAL-critical one):** locate every 0H (sync edge midpoint) in the frame; NTSC: constant 910-sample spacing, edge at 784.5 ± tolerance; **PAL: spacings average 1135.0064, per-line drift +0.0064 samples accumulating to exactly +4 over each frame, and frame-to-frame 0H positions identical** — this directly proves the non-orthogonal lattice is right.
5. Burst behavior: demod burst at fs/4 on fixed lattice positions; report phase progression (informational under UNLOCKED; becomes an assertion under LOCKED in v2).
6. `.meta` schema/user_version/row sanity; WAV header vs `audio_locked` (PAL: data length = frames×1764×4 bytes when locked).

**Tests:**
- ctest: decode both CI discs with `--cvbs`; run `cvbs_verify.py` with PASS_REGULAR_EXPRESSION on its summary line.
- Cross-decode round trip (manual/optional): feed the NTSC `.composite` to vhs-decode's `cvbsdecode` (present at `~/ld-decode/vhs-decode/cvbsdecode`) and confirm it locks and produces sane output — end-to-end proof the file is real CVBS. Same for PAL, which specifically exercises the non-line-locked timing.
- Regression: normal (non-cvbs) decodes must remain bit-identical (md5 of `.tbc` on both CI discs before/after the series — the CVBS mode must not touch the default path).
- Quality checks on CVBS content: `differential_phase.py` won't read `.composite` directly (different raster) — out of scope; `cvbs_verify.py`'s burst/level checks cover format health.

## Commit sequence

1. `params.py` constants + `dsp.py` fractional-scale helper (+ unit test with a synthetic ramp: resample a known sinusoid onto the PAL lattice, verify sample count 709,379 and phase slip 4/frame analytically).
2. `cvbs.py` writer + NTSC path + decoder/main wiring (NTSC end-to-end working).
3. `scripts/cvbs_verify.py` + NTSC ctest.
4. PAL frame assembler (`field.py` lineinfo + cvbs.py PAL path) + PAL ctest.
5. Audio WAV + `.meta` finalization (+ `--NTSCJ` black_level, PAL pilot capture_notes).
6. Docs: README section describing the mode and the PAL non-orthogonal caveat; note the v2 (burst-lock, dropout/EFM extensions) follow-ups.

Each commit verified: pytest, full ctest (old tests must stay green — default path untouched), and from commit 3 on, `cvbs_verify.py` on fresh decodes.

## Risks / watch items

- **PAL field-boundary half-lines**: the seam between fields inside a frame must come from real decoded samples; use the same margin data `rf_tbc()` uses. If a field's `proclines` margin proves insufficient at the tail, widen the assembler's source window rather than synthesizing blanking. Test with a disc seek/skip in range to ensure a broken pair degrades to a dropped frame, not a mis-sized one (the spec REQUIRES exact frame sizes — on unrecoverable fields, emit a repeated last-good frame or drop the frame entirely; never emit a short frame).
- **Exact integer lattice math**: all per-line counts/phases derived from integers (709379, 625, 4) — no float accumulation across lines/frames.
- **Levels**: confirm 0 IRE lands exactly on 240<<6 (NTSC) / 256<<6 (PAL) in the output signal itself; fix the mapping if the `blanking_16b=15091` discrepancy is real signal placement and not just metadata.
- **PAL pilot burst**: legal amplitude but non-standard content → `has_nonstandard_values=TRUE` + capture_notes, never clipped.
- **Performance**: PAL does one extra full-rate resample per field; if FPS matters, the standard `dspicture` for metrics can later be computed on demand only for the lines metrics actually read.
