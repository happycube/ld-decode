# ld-decode command

ld-decode's execution is largely controlled by a number of command line switches:

```
ld-decode [-h] [--start file-location] [--length frames] [--seek frame] [--PAL] [--NTSC] [--NTSCJ] [-m mtf]
                 [--MTF_offset mtf_offset] [--noAGC] [--noDOD] [--noEFM] [--preEFM] [--tbc_efm] [--efm_demod {pll,timing}] [--efm_conf {auto,on,off}] [--efm_eq_taps N] [--disable_analog_audio] [--AC3]
                 [--start_fileloc start_fileloc] [--ignoreleadout] [--verboseVITS] [--RF_TBC] [--lowband]
                 [--NTSC_color_notch_filter] [--audio_carrier_cancel] [--V4300D_notch_filter] [--V4300D_coherent_subtract] [--V4300D_no_defer]
                 [--deemp_low deemp_low] [--deemp_high deemp_high]
                 [--deemp_strength deemp_str] [--no_auto_chroma] [--vits_white_level] [--no_mtf_servo] [--calibration_frames frames] [-t threads] [-f FREQ] [--analog_audio_frequency AFREQ]
                 [--video_bpf_low FREQ] [--video_bpf_high FREQ] [--video_lpf FREQ] [--video_lpf_order VLPF_ORDER]
                 [--audio_filterwidth FREQ] [--use_profiler] [--write-test-ldf output.ldf]
                 infile outfile
```

## Synopsis

```bash
ld-decode [OPTIONS] infile outfile
```

## Positional Arguments

### infile
**Required.** Path to the source file containing the raw RF capture data.

### outfile
**Required.** Base name for destination files. The tool will create multiple output files with this base name and appropriate extensions (e.g., `.tbc`, `.tbc.json`, `.efm`, `.pcm`).

## Options

### Version Information

#### `--version`, `-v`
Display the version number of ld-decode and exit. Does not require positional arguments.

**Example:**
```bash
ld-decode --version
```

### Basic Decoding Options

#### `--start file-location`, `-s file-location`
Jump roughly to frame n of the capture before starting decoding.
- **Type:** Float
- **Default:** 0
- **Range:** Any non-negative number
- **Note:** This performs a rough seek; use `--seek` for precise frame seeking

**Example:**
```bash
ld-decode --start 1000 input.ldf output
```

#### `--length frames`, `-l frames`
Limit the number of frames to decode.
- **Type:** Integer
- **Default:** 110000
- **Range:** Any positive integer
- **Note:** Specifies the maximum number of video frames to process

**Example:**
```bash
ld-decode --length 5000 input.ldf output
```

#### `--seek frame`, `-S frame`
Seek to a precise frame number in the capture before starting decoding.
- **Type:** Integer
- **Default:** -1 (disabled)
- **Range:** Any non-negative integer
- **Note:** More precise than `--start`; requires valid frame synchronization data

**Example:**
```bash
ld-decode --seek 2500 input.ldf output
```

#### `--start_fileloc start_fileloc`
Jump to a precise sample number in the file.
- **Type:** Float
- **Default:** -1 (disabled)
- **Range:** Any non-negative number
- **Note:** Specifies the exact sample position in the RF capture file; overrides `--start`

**Example:**
```bash
ld-decode --start_fileloc 10000000 input.ldf output
```

### Video Standard Options

**Note:** Only one video standard can be selected. Selecting both PAL and NTSC (or NTSCJ) will result in an error.

#### `--PAL`, `-p`, `--pal`
Decode the source as PAL format.
- **Default:** If neither PAL nor NTSC is specified, NTSC is assumed
- **Incompatible with:** `--NTSC`, `--NTSCJ`

**Example:**
```bash
ld-decode --PAL input.ldf output
```

#### `--NTSC`, `-n`, `--ntsc`
Decode the source as NTSC format.
- **Default:** NTSC is the default if no standard is specified
- **Incompatible with:** `--PAL`
- **Note:** Uses IRE 7.5 black level (standard NTSC)

**Example:**
```bash
ld-decode --NTSC input.ldf output
```

#### `--NTSCJ`, `-j`
Decode the source as NTSC-J (Japanese NTSC) format.
- **Default:** Disabled
- **Incompatible with:** `--PAL`
- **Note:** Uses IRE 0 black level (Japanese standard) instead of IRE 7.5

**Example:**
```bash
ld-decode --NTSCJ input.ldf output
```

### Video Processing Options

#### `-m mtf`, `--MTF mtf`
MTF (Modulation Transfer Function) compensation multiplier.
- **Type:** Float
- **Default:** 1.0
- **Range:** Typically 0.5 to 2.0
- **Note:** Adjusts the compensation for frequency-dependent signal loss; values > 1.0 increase high-frequency boost

**Example:**
```bash
ld-decode -m 1.5 input.ldf output
```

#### `--MTF_offset mtf_offset`
MTF compensation offset.
- **Type:** Float
- **Default:** 0
- **Range:** Any float value
- **Note:** Additional offset applied to MTF compensation

**Example:**
```bash
ld-decode --MTF_offset 0.1 input.ldf output
```

#### `--noAGC`
Disable Automatic Gain Control.
- **Default:** AGC is enabled
- **Note:** AGC normalizes signal levels; disabling may be useful for analyzing the raw signal

**Example:**
```bash
ld-decode --noAGC input.ldf output
```

#### `--noDOD`
Disable the dropout detector.
- **Default:** Dropout detection is enabled
- **Note:** Dropouts are signal losses; disabling detection means they won't be flagged in the output

**Example:**
```bash
ld-decode --noDOD input.ldf output
```

#### `--lowband`
Use more restricted RF settings optimized for noisier disks.
- **Default:** Disabled
- **Note:** Applies more conservative filtering suitable for degraded or noisy source material

**Example:**
```bash
ld-decode --lowband input.ldf output
```

### Video Filter Options

#### `--video_bpf_low FREQ`
Video band-pass filter low-end frequency.
- **Type:** FREQ (see Frequency Format section)
- **Default:** System-dependent (varies by PAL/NTSC)
- **Note:** Sets the lower cutoff frequency for the video band-pass filter

**Example:**
```bash
ld-decode --video_bpf_low 2.5MHz input.ldf output
```

#### `--video_bpf_high FREQ`
Video band-pass filter high-end frequency.
- **Type:** FREQ (see Frequency Format section)
- **Default:** System-dependent (varies by PAL/NTSC)
- **Note:** Sets the upper cutoff frequency for the video band-pass filter

**Example:**
```bash
ld-decode --video_bpf_high 13MHz input.ldf output
```

#### `--video_lpf FREQ`
Video low-pass filter frequency.
- **Type:** FREQ (see Frequency Format section)
- **Default:** System-dependent (varies by PAL/NTSC)
- **Note:** Sets the cutoff frequency for the video low-pass filter

**Example:**
```bash
ld-decode --video_lpf 5.0MHz input.ldf output
```

#### `--video_lpf_order VLPF_ORDER`
Video low-pass filter order.
- **Type:** Integer
- **Default:** -1 (use system default)
- **Range:** Positive integers (typically 1-10)
- **Note:** Higher orders provide sharper cutoff but more processing

**Example:**
```bash
ld-decode --video_lpf_order 8 input.ldf output
```

### NTSC-Specific Video Options

#### `--NTSC_color_notch_filter`, `-N`
Mitigate interference from analog audio in red colors in NTSC captures.
- **Default:** Disabled
- **Note:** Only effective with NTSC video standard; addresses crosstalk from audio carriers

**Example:**
```bash
ld-decode --NTSC --NTSC_color_notch_filter input.ldf output
```

#### `--audio_carrier_cancel`
Prototype. Subtract the analog audio carriers' intermodulation lines from
NTSC video. The audio FM carriers mix with the video carrier on the disc, and
the demodulated video carries faint lines at the carriers' own frequencies
(2.30 and 2.81 MHz), in the luminance band. Each block's line is fitted to the
carrier's own phase, taken from the RF, and subtracted; a carrier that is not
on the disc (and AC3's right channel) is left alone.
- **Default:** Disabled
- **Note:** NTSC only. The lines are strongest towards the outer radius of
  some discs, where removing them lowers the weighted luminance noise by up to
  about 1.3 dB; on most captures the gain is 0.1-0.5 dB.

**Example:**
```bash
ld-decode --NTSC --audio_carrier_cancel input.ldf output
```

### PAL-Specific Video Options

Pioneer LD-V4300D players leak their digital-audio master clock
(192 x 44.1 kHz = 8.4672 MHz, with weaker satellites at ±88.2 kHz
multiples) into the RF output when playing PAL discs with digital audio.
The tone beats against the video FM carrier and shows up as a fine wavy
pattern rolling through solid picture areas.

#### `--V4300D_coherent_subtract`
Remove the LD-V4300D spur by estimating the clock line (and its
satellites) coherently and subtracting the fitted tones from the
spectrum, without cutting holes in the video sidebands. Self-disabling
on captures without the spur, and inactive on blocks with no video
carrier, so it is safe from the first block and keeps the parallel
(multi-threaded) decode path available.
- **Default:** Disabled
- **Note:** Only effective with PAL video standard

**Example:**
```bash
ld-decode --PAL --V4300D_coherent_subtract input.ldf output
```

#### `--V4300D_notch_filter`, `-V`
Legacy alias for `--V4300D_coherent_subtract` (which supersedes the
original FFT-bin notch: it also removes the spur's leakage skirts and
its satellites). Kept so existing command lines continue to work.

#### `--V4300D_no_defer`
Obsolete; accepted for compatibility and ignored. The spur filter no
longer defers until sync acquisition and never forces a serial decode.

### Deemphasis Options

Video signals are typically pre-emphasized during recording and must be de-emphasized during playback.

#### `--deemp_low deemp_low`
Deemphasis low frequency in MHz.
- **Type:** Float
- **Default:** System-dependent
  - NTSC: 3.125MHz
  - PAL: 2.5MHz
- **Range:** Any positive float
- **Note:** Specifies the frequency for low-frequency deemphasis

**Example:**
```bash
ld-decode --deemp_low 3.125 input.ldf output
```

#### `--deemp_high deemp_high`
Deemphasis high frequency in MHz.
- **Type:** Float
- **Default:** System-dependent
  - NTSC: 8.33MHz
  - PAL: 10MHz
- **Range:** Any positive float
- **Note:** Specifies the frequency for high-frequency deemphasis

**Example:**
```bash
ld-decode --deemp_high 10.0 input.ldf output
```

#### `--deemp_strength deemp_str`
Strength of deemphasis filter.
- **Type:** Float
- **Default:** NTSC 0.96, PAL 1.0
- **Range:** Typically 0.0 to 2.0
- **Note:** Multiplier for deemphasis effect; 1.0 is standard, <1.0 reduces effect, >1.0 increases effect.  Giving a value also stops the colour burst from setting the automatic chroma correction's strength (see `--no_auto_chroma`)

**Example:**
```bash
ld-decode --deemp_strength 0.8 input.ldf output
```

#### `--no_auto_chroma`
Disable the automatic chroma level correction.
- **Default:** Enabled
- **Note:** By default the decoder restores the chroma the disc's optics and the
  RF filters took away with an inverse-MTF filter on the demodulated video,
  limited to the chroma band.  The colour burst sets its strength, so the burst
  is brought to its nominal level (20 IRE NTSC, 21.4 IRE PAL), and the VITS
  multiburst, where a disc carries one, bounds it.  The correction is written
  into the `.tbc` and `.cvbs` samples.  With this switch the chroma is written
  as the filter chain demodulates it, so a disc mastered with a low chroma level
  keeps it.  Either way the output's capture notes (`capture.capture_notes` in
  the `.tbc.db`, `cvbs_file.capture_notes` in the `.cvbs.meta`) record the
  correction's strength, the median burst level as written and as it read
  before the correction, and the gain that would bring the burst to nominal
  (`chroma_gain_to_nominal`), for a later decoder to apply or take out.

**Example:**
```bash
ld-decode --no_auto_chroma input.ldf output
```

#### `--vits_white_level`
Scale the luminance so that the disc's VITS white bar reads 100 IRE.
- **Default:** Disabled
- **Note:** Discs are mastered a percent or so either side of nominal level
  (the NTSC captures tested read their white bar at 98.8-101.7 IRE).  With this
  switch the decoder reads the white bar of the insertion test signal (PAL's
  ITS, NTSC's NTC-7 composite) over the first few fields and scales the
  luminance above blanking by the factor that brings it to 100 IRE.  Sync,
  burst and chroma are left as they are; the chroma's level is set from the
  burst (see `--no_auto_chroma`).  The correction is written into the `.tbc`
  and `.cvbs` samples, and the first few fields, written before the reading
  settles, are not corrected.  A disc without that test signal is left alone.

**Example:**
```bash
ld-decode --vits_white_level input.ldf output
```

#### `--no_mtf_servo`
Do not adapt the MTF level from the 2T pulse of the vertical-blanking test signal.
- **Default:** The servo runs when the disc carries the pulse, and the RF black-to-white ratio gives the level otherwise
- **Note:** The servo is already off when `-m` is not 1.0 or `--MTF_offset` is not 0; this flag turns it off without changing the level.  It only acts under the pole-pair MTF model (PAL); NTSC's readout MTF model takes its level from the RF and never runs the servo

**Example:**
```bash
ld-decode --no_mtf_servo input.ldf output
```

#### `--calibration_frames frames`
Run a calibration pass: decode at least this many frames ahead, before the first frame is written, to settle the servos that calibrate the decode from the disc: the AGC, MTF level, inverse-MTF chroma strength, multiburst video EQ and chroma differential-gain corrector. 10 is a good choice.
- **Type:** Integer
- **Default:** 0 (no pass)
- **Note:** Without a pass the decoder writes as soon as its servos are stable, and the slower ones (the 2T servo, the chroma differential-phase decision) can still adopt after writing has begun, so the opening frames of a decode may carry a different calibration from the rest. The pass runs at least this long and then until no servo has moved for 6 fields, within a further 60 fields. On a disc with a test staircase it also waits, up to 25 frames, for the chroma differential-phase decision. It decodes ahead and starts over, so nothing is skipped; the cost is decoding those frames twice at the start, about 3 seconds. A decode of a few frames from a long capture therefore takes noticeably longer (`-l 3`: 4.8 s to 8.1 s); a capture shorter than the pass costs nothing extra, as the pass stops at the end of the input. With a shorter pass the slower servos can still adopt after writing has begun, and a short decode then carries two calibrations. `0`, the default, writes once the servos have been stable for two fields, the video EQ has adopted or held, the 2T servo's level reads back as itself and the chroma differential-gain decision is taken - usually 4-8 frames ahead - and leaves the differential-phase decision until after writing begins.
- **Log:** a pass reports itself on the console when it starts; either way the decoder logs a line when calibration ends (`Calibrating... settled after 5.5 frames - ...` without a pass), with why it stopped (settled, end of input, field limit) and the MTF level, chroma strength, video EQ and chroma DG it settled on.

**Example:**
```bash
ld-decode --calibration_frames 10 input.ldf output
```

### Audio Decoding Options

#### `--disable_analog_audio`, `--disable_analogue_audio`, `--daa`
Disable analog audio decoding.
- **Default:** Analog audio is enabled at 44100Hz
- **Note:** Useful when only video is needed or when processing digital-only sources

**Example:**
```bash
ld-decode --disable_analog_audio input.ldf output
```

#### `--analog_audio_frequency AFREQ`
Set the analog audio output sampling frequency.
- **Type:** Integer (Hz)
- **Default:** 44100
- **Range:** Typically 44100 or 48000
- **Note:** Output sample rate for analog audio tracks

**Example:**
```bash
ld-decode --analog_audio_frequency 48000 input.ldf output
```

#### `--ntsc_audio_rate`
Output analog audio locked to NTSC line timing instead of the default 44100Hz.
- **Default:** Off (analog audio is output at 44100Hz)
- **Effect:** Produces exactly 2.8 samples per line (1470 samples/frame, 735 per field), giving a sample rate of ~44055.944Hz that stays perfectly aligned to the NTSC video timing with no drift. The default 44100Hz rate corresponds to a non-integer 1471.47 samples/frame, which slowly drifts against the video.
- **Metadata:** The `.tbc.json` reports the resolved `sampleRate` as `44055.944055944055`.
- **Note:** NTSC only. The flag is ignored (with a warning) for PAL, which is already frame-locked at 44100Hz (1764 samples/frame). Overrides `--analog_audio_frequency`.

**Example:**
```bash
ld-decode --ntsc_audio_rate input.ldf output
```

#### `--audio_filterwidth FREQ`
Set the analog audio filter width.
- **Type:** FREQ (see Frequency Format section)
- **Default:** System-dependent
- **Note:** Bandwidth of the analog audio channel filters

**Example:**
```bash
ld-decode --audio_filterwidth 150kHz input.ldf output
```

#### `--noEFM`
Disable EFM (Eight-to-Fourteen Modulation) front end for digital audio.
- **Default:** EFM decoding is enabled
- **Note:** EFM is used for digital audio (CD audio) on laserdiscs and for LV-ROM data; disabling skips digital audio extraction. See [EFM decoding](../technical/efm-decoding.md) for the EFM path, its tuning environment variables, and the `.efm` output format (including confidence-packed output).

**Example:**
```bash
ld-decode --noEFM input.ldf output
```

#### `--preEFM`
Write filtered but otherwise pre-processed EFM data.
- **Default:** Disabled
- **Note:** Outputs intermediate EFM data before full decoding; useful for debugging or custom processing

**Example:**
```bash
ld-decode --preEFM input.ldf output
```

#### `--tbc_efm`
Time-base-correct the EFM waveform onto the video line time-base before the EFM PLL.
- **Default:** Disabled (also enabled by `LDDECODE_TBC_EFM=1`)
- **Note:** Experimental; does not improve a single-capture decode. It aligns the pre-PLL EFM of multiple captures of the same disc onto a common disc-position time-base for cross-capture stacking and waveform research — see [EFM decoding](../technical/efm-decoding.md).

**Example:**
```bash
ld-decode --tbc_efm input.ldf output
```

#### `--efm_demod`
Select the EFM demodulator that turns the equalised EFM waveform into `.efm` T-values.
- **Default:** `timing`
- **Choices:** `timing` (symbol-rate timing-recovery demodulator: per-channel-bit Mueller & Müller loop with bit-domain frame sync, sync restoration and legalised T emission), `pll` (the previous zero-crossing run-length PLL)
- **Note:** `timing` recovers noticeably more valid frames on noisy or marginal captures — it met or beat the PLL on every validation capture — and derives per-T-value confidence from its framing state. Use `pll` to reproduce pre-switch `.efm` output byte for byte. See [EFM decoding](../technical/efm-decoding.md) for the architecture and its tuning environment variables.

**Example:**
```bash
ld-decode --efm_demod pll input.ldf output
```

#### `--efm_conf`
Confidence-packed `.efm` output for `--tbc` mode: each byte carries the T-value in its low nibble and a 4-bit demodulator doubt in its high nibble (the byte layout of the CVBS EFM extension format; consumers separate them as `t = byte & 0x0F`, `doubt = byte >> 4` — 0 = full trust, so trusted bytes stay plain T-values). CVBS output always writes this layout — the extension format defines it — so this option only affects `--tbc` output.
- **Default:** `auto` — **off** for `--tbc` output so the plain `.efm` keeps working with legacy tools
- **Choices:** `auto`, `on`, `off` (`LDDECODE_EFM_EMITCONF=1`/`0` is the environment equivalent of on/off)
- **Note:** a packed stream cannot be distinguished from a plain one by inspection, so only force `on` for `--tbc` output when the consumer knows it is getting packed data. See [EFM decoding](../technical/efm-decoding.md).

**Example:**
```bash
ld-decode --tbc --efm_conf on input.ldf output
```

#### `--AC3`
Enable AC3-RF audio demodulation (NTSC only).  On AC3 LaserDiscs the
analog right audio channel carries a QPSK signal at 2.88 MHz with Dolby
Digital data at 288 kbaud.  With this option, ld-decode demodulates that
signal (see `lddecode/ac3rf.py`) and writes the raw QPSK symbols to
`output.ac3sym` (one symbol per byte, values 0-3); the number of symbols
demodulated during each field is recorded in the field metadata
(`ac3Symbols`, analogous to `efmTValues`).

The `.ac3sym` file is not playable audio by itself: framing, Reed-Solomon
error correction and AC3 frame assembly are performed downstream by
[decode-orc](https://github.com/simoninns/decode-orc)'s *AC3 RF Sink*
stage, which reads the `.tbc`, its metadata, and the `.ac3sym` file and
writes the final playable `.ac3` file.

- **Default:** Disabled
- **Note:** Only compatible with NTSC; attempting to use with PAL will result in an error
- **Incompatible with:** `--PAL`

**Example:**
```bash
ld-decode --NTSC --AC3 input.ldf output
```

The demodulator has a self-contained unit test (synthetic QPSK loopback,
no capture files needed), runnable from the repository root:
```bash
python3 -m tests.test_ac3rf
```
A quick sanity check on real output: `output.ac3sym` should grow by
about 288,000 symbols (bytes) per second of decoded video.

### RF Sampling Options

#### `-f FREQ`, `--frequency FREQ`
RF sampling frequency of the source file.
- **Type:** FREQ (see Frequency Format section)
- **Default:** 40MHz
- **Note:** If the source file has a different sample rate, specify it here; the decoder will resample to 40MHz internally

**Example:**
```bash
ld-decode -f 28.636363MHz input.ldf output
ld-decode -f 8fsc input.ldf output
```

### Processing Options

#### `-t threads`, `--threads threads`
Number of worker processes to decode fields with.
- **Type:** Integer
- **Default:** 0 (auto): the machine's physical cores minus 2, capped at 10
- **Range:** 1 (serial decode) to number of CPU cores
- **Note:** The workers are FFT-bound, so counting SMT (hyper-threading) siblings as cores oversubscribes the machine; an 8-core/16-thread CPU decodes faster with 6 workers than with 10. Output is bit-identical for any thread count.

**Example:**
```bash
ld-decode -t 8 input.ldf output
```

### Output Options

#### `--RF_TBC`
Create a `.tbc.ldf` file containing time-base corrected RF data.
- **Default:** Disabled
- **Note:** Outputs the RF signal after time-base correction; useful for archival or analysis

**Example:**
```bash
ld-decode --RF_TBC input.ldf output
```

#### `--cvbs-legacy-origin`, `--cvbs-spec-origin`
Where each `.cvbs` frame starts relative to 0H.  The legacy origin keeps the decoder's own line origin, as written before frames were 0H-aligned (NTSC 0H 0.3-1.9 samples after sample 0, PAL -0.1 to -1.04), for readers built to that layout.  `--cvbs-spec-origin` moves the frame origin by whole samples so 0H falls in the sample before sample 0, as the CVBS specification requires.
- **Default:** legacy origin, for now
- **Note:** a legacy-origin file is not spec compliant (a spec reader can take NTSC colour frame A for B) and says so in the `.meta` `capture_notes`; `analysis/cvbs_verify.py` fails an NTSC one on its origin check

**Example:**
```bash
ld-decode --cvbs-spec-origin input.ldf output
```

#### `--ignoreleadout`
Continue decoding after detecting the lead-out section.
- **Default:** Disabled (stop at lead-out)
- **Note:** Lead-out marks the end of the disc content; this option processes beyond that marker

**Example:**
```bash
ld-decode --ignoreleadout input.ldf output
```

#### `--verboseVITS`
Enable additional fields in the JSON metadata output.
- **Default:** Disabled
- **Note:** VITS (Vertical Interval Test Signals) contain technical information; this outputs more detailed data

**Example:**
```bash
ld-decode --verboseVITS input.ldf output
```

### Debugging and Development Options

#### `--write-test-ldf output.ldf`
Write the input portion being decoded to a `.ldf` file for bug reporting.
- **Type:** String (filename)
- **Default:** Disabled
- **Note:** Creates a reproducible test case containing the input samples that were decoded; useful for submitting bug reports. The output file cannot be the same as the input file.

**Example:**
```bash
ld-decode --write-test-ldf test-case.ldf input.ldf output
```

#### `--use_profiler`
Enable line_profiler on select functions for performance analysis.
- **Default:** Disabled
- **Note:** Development tool for identifying performance bottlenecks; requires line_profiler to be installed

**Example:**
```bash
ld-decode --use_profiler input.ldf output
```

## Frequency Format

Many options accept frequency values with the `FREQ` type. These can be specified in several formats:

### Bare Number
A number without a suffix is interpreted as **MHz**.
```bash
--frequency 40      # 40 MHz
```

### With Suffix (case-insensitive)
- **Hz**: Hertz
  ```bash
  --frequency 40000000Hz
  ```
- **kHz**: Kilohertz (10³ Hz)
  ```bash
  --frequency 40000kHz
  ```
- **MHz**: Megahertz (10⁶ Hz)
  ```bash
  --frequency 40MHz
  ```
- **GHz**: Gigahertz (10⁹ Hz)
  ```bash
  --frequency 0.04GHz
  ```
- **fSC**: NTSC color subcarrier frequency (315/88 MHz ≈ 3.579545 MHz)
  ```bash
  --frequency 8fsc    # 8× NTSC subcarrier ≈ 28.636 MHz
  ```
- **fSCPAL**: PAL color subcarrier frequency (283.75 × 15625 + 25 Hz ≈ 4.43361875 MHz)
  ```bash
  --frequency 8fscpal # 8× PAL subcarrier ≈ 35.469 MHz
  ```

## Common Usage Examples

### Basic PAL Decode
```bash
ld-decode --PAL input.ldf output
```

### NTSC Decode with Custom Length
```bash
ld-decode --NTSC --length 30000 input.ldf output
```

### High-Quality PAL Decode with Custom Settings
```bash
ld-decode --PAL -m 1.2 --lowband -t 8 input.ldf output
```

### NTSC with AC3 Audio
```bash
ld-decode --NTSC --AC3 input.ldf output
```

### Decode Specific Frame Range
```bash
ld-decode --PAL --start 1000 --length 5000 input.ldf output
```

### Custom Sample Rate Input
```bash
ld-decode --PAL -f 28.636363MHz input.ldf output
```

### NTSC with Color Notch Filter
```bash
ld-decode --NTSC --NTSC_color_notch_filter input.ldf output
```

### PAL V4300D Capture
```bash
ld-decode --PAL --V4300D_coherent_subtract input.ldf output
```

### Video Only (No Audio)
```bash
ld-decode --PAL --disable_analog_audio --noEFM input.ldf output
```

### Create Test Case for Bug Report
```bash
ld-decode --PAL --start 5000 --length 10 --write-test-ldf bug-report.ldf input.ldf output
```

## Output Files

Based on the base name provided as `outfile`, ld-decode creates several output files:

- **`outfile.tbc`**: Time-base corrected video data
- **`outfile.tbc.json`**: Frame metadata in JSON format
- **`outfile.pcm`**: Analog audio (if enabled, one file per audio channel)
- **`outfile.efm`**: Digital audio EFM data (if enabled)
- **`outfile.log`**: Detailed log file
- **`outfile.tbc.ldf`**: TBC'd RF data (if `--RF_TBC` is used)

## Exit Behavior

The decoder will stop processing when:
1. The requested number of frames (`--length`) has been decoded
2. Lead-out is detected (unless `--ignoreleadout` is specified)
3. End of file is reached
4. An error occurs
5. User interrupts with Ctrl+C (SIGINT)

## Error Conditions

### PAL/NTSC Conflict
```
ERROR: Can only be PAL or NTSC
```
Occurs when multiple video standards are specified.

### AC3 with PAL
```
ERROR: AC3 audio decoding is only supported for NTSC
```
AC3 audio is only available on NTSC laserdiscs.

### Write Test LDF Collision
```
ERROR: --write-test-ldf output file cannot be the same as input file
```
The test output file must be different from the input file.

### Seek Failure
```
ERROR: Seeking failed
```
Unable to seek to the requested frame; may indicate corrupted data or invalid frame number.

## Notes

- **Default Video Standard**: If neither `--PAL` nor `--NTSC` is specified, NTSC is assumed.
- **Thread Count**: The default of 4 threads is suitable for most systems; adjust based on your CPU core count.
- **Sample Rate**: The decoder internally works at 40MHz; all other sample rates are resampled.
- **Frame Counting**: Frames are counted as complete video frames; internally, the decoder processes fields (2 fields = 1 frame).
- **Lead-out**: The lead-out section marks the end of valid disc content; decoding typically stops here unless `--ignoreleadout` is used.

## Version Information

To check the installed version:
```bash
ld-decode --version
```

or

```bash
ld-decode -v
```
