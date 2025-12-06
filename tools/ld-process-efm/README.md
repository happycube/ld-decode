# ld-process-efm (DEPRECATED)

**⚠️ DEPRECATED: This single tool has been deprecated and replaced by a suite of specialized tools in `tools/efm-decoder/`. Use `efm-decoder-audio` for standard audio decoding, or other efm-decoder tools for specific use cases.**

**Eight-to-Fourteen Modulation (EFM) Digital Audio Decoder**

## Overview

**Note:** This tool is deprecated. Please use the efm-decoder suite of tools located in `tools/efm-decoder/` for EFM decoding. The functionality of this single tool has been split into multiple specialized tools for better flexibility and control.

ld-process-efm decodes digital audio data from LaserDisc captures. It processes Eight-to-Fourteen Modulation (EFM) encoded PCM audio data embedded in the RF signal, producing raw audio streams or WAV files.

## Features

### EFM Decoding
- **Full EFM Decoder**: Complete digital audio extraction
- **Error Correction**: Reed-Solomon error correction (CIRC)
- **Sync Detection**: Robust frame synchronization
- **Parity Checking**: Data integrity validation

### Audio Processing
- **Sample Rates**: 44.1 kHz (CD quality)
- **Bit Depth**: 16-bit linear PCM
- **Channels**: Stereo (2 channel)
- **Byte Order**: Configurable endianness

### Quality Features
- **Error Concealment**: Interpolation of uncorrectable errors
- **Dropout Handling**: Graceful degradation on signal loss
- **Statistics Reporting**: Detailed error and quality metrics
- **Validation**: Audio stream integrity checking

### Output Formats
- **Raw PCM**: Uncompressed audio stream
- **WAV**: Standard WAV file format
- **Metadata**: Error statistics and quality reports

## Usage

### Basic Syntax
```bash
ld-process-efm [options] <input.efm> [output.pcm]
```

Or when integrated with ld-decode:
```bash
ld-decode --digital-efm input.ldf output.tbc output.efm
ld-process-efm output.efm output.pcm
```

## Options

#### Common Options
- `-h, --help`: Display help on command-line options
- `-v, --version`: Display version information
- `-d, --debug`: Show debug information
- `-q, --quiet`: Suppress info and warning messages

#### Audio Output
- `-c, --conceal`: Conceal corrupt audio data (default)
- `-s, --silence`: Silence corrupt audio data
- `-g, --pass-through`: Pass-through corrupt audio data
- `-p, --pad`: Pad start of audio from 00:00 to match initial disc time

#### Decoder Mode
- `-b, --data`: Decode F1 frames as data instead of audio
- `-D, --dts`: Audio is DTS rather than PCM (allow non-standard F3 syncs)
- `-t, --time`: Non-standard audio decode (no time-stamp information)

#### Debug Options
- `--debug-efmtof3frames`: Show EFM To F3 frame decode detailed debug
- `--debug-syncf3frames`: Show F3 frame synchronisation detailed debug
- `--debug-f3tof2frames`: Show F3 To F2 frame decode detailed debug
- `--debug-f2tof1frame`: Show F2 to F1 frame detailed debug

#### Arguments
- `input`: Input EFM file (required)
- `output`: Output audio file (required)

#### Verbosity
- `-q, --quiet`: Suppress info and warning messages
- `-d, --debug`: Show debug

### Examples

#### Basic EFM to PCM
```bash
ld-process-efm input.efm output.pcm
```

#### Silence Corrupt Audio
```bash
ld-process-efm -s input.efm output.pcm
```

#### Pad Audio to Match Disc Time
```bash
ld-process-efm -p input.efm output.pcm
```

#### Decode as Data
```bash
ld-process-efm -b input.efm output.dat
```

#### DTS Audio
```bash
ld-process-efm -D input.efm output.pcm
```

#### Full Pipeline from RF
```bash
# Decode RF with digital audio
ld-decode --digital-efm disc.ldf video.tbc audio.efm

# Process EFM to WAV
ld-process-efm --audio-format wav audio.efm audio.wav
```

## EFM Technical Details

### Eight-to-Fourteen Modulation
- **Encoding**: 8 data bits → 14 channel bits
- **Purpose**: DC-free signal, clock recovery
- **Frame Structure**: 588 channel bits per audio frame
- **Sync Patterns**: 24-bit + 3 merge bits

### Error Correction (CIRC)
- **Method**: Cross-Interleaved Reed-Solomon Code
- **C1 Decoder**: First-level error correction (4 bytes)
- **C2 Decoder**: Second-level error correction (4 bytes)
- **Interleaving**: Delay-based (108 frames)
- **Capability**: Corrects bursts up to ~3900 bits

### Audio Format
- **Sample Rate**: 44,056 Hz or 44,100 Hz (depends on disc)
- **Quantization**: 16-bit linear PCM
- **Channels**: 2 (Left and Right interleaved)
- **Frame Rate**: 7,350 frames/second

## Processing Statistics

When using `--statistics`, ld-process-efm reports:

```
EFM Processing Statistics:
==========================
Total frames processed: 735000
Valid sync patterns: 734980 (99.997%)
C1 errors corrected: 125 (0.017%)
C2 errors corrected: 8 (0.001%)
Uncorrectable errors: 2 (0.0003%)
Concealed samples: 384 (0.00087%)
Output duration: 01:40:00
Average bitrate: 1411.2 kbps
```

### Quality Metrics
- **<0.01% errors**: Excellent quality
- **0.01-0.1% errors**: Good quality, minor issues
- **0.1-1% errors**: Audible artifacts, poor source
- **>1% errors**: Severe problems, check RF capture

## Error Concealment

### Methods
1. **Interpolation**: Linearly interpolate between good samples
2. **Previous Sample Hold**: Repeat last good sample
3. **Muting**: Output silence (if concealment disabled)

### Behavior
- Applied to uncorrectable errors after CIRC decoding
- Conceals up to ~13ms of audio (typical)
- Longer errors result in audible glitches

## Integration Examples

### Convert to WAV and Encode
```bash
# Extract digital audio
ld-process-efm --audio-format wav input.efm raw.wav

# Encode to FLAC (lossless)
flac --best raw.wav -o output.flac

# Or encode to MP3
lame -V 0 raw.wav output.mp3
```

### Process Multiple Sides
```bash
# Process side 1
ld-decode --digital-efm side1.ldf side1.tbc side1.efm
ld-process-efm --audio-format wav side1.efm side1.wav

# Process side 2
ld-decode --digital-efm side2.ldf side2.tbc side2.efm
ld-process-efm --audio-format wav side2.efm side2.wav

# Concatenate
sox side1.wav side2.wav complete.wav
```

### Analyze Quality
```bash
# Process with statistics
ld-process-efm --statistics --output-metadata meta.sqlite input.efm output.wav

# Extract error rate
ld-export-metadata --csv meta.sqlite
```

## Troubleshooting

### Issues

**No audio output:**
- Verify EFM file is not empty (`ls -lh input.efm`)
- Check that ld-decode used `--digital-efm` option
- Ensure disc has digital audio tracks (not all LaserDiscs do)

**High error rates:**
- Improve RF signal quality (better connection, cleaning)
- Check for disc damage (scratches, rot)
- Verify proper tracking during capture
- Try recapturing with different settings

**Sync errors:**
- May indicate wrong sample rate or corrupted EFM file
- Check ld-decode didn't report errors during capture
- Verify file is complete (not truncated)

**Audible glitches:**
- Normal for damaged discs (physical media errors)
- Consider error concealment if disabled
- May need manual audio repair in editing software

**Wrong sample rate:**
- Some discs use 44,056 Hz instead of 44,100 Hz
- Use `--sample-rate` to override if needed
- Check disc specifications

## LaserDisc Digital Audio

### Format Types
- **PCM Audio**: Highest quality, occupies video lines
- **AC-3 (Dolby Digital)**: Compressed surround (use ld-process-ac3)
- **Analog Audio**: Standard LaserDisc audio (decoded separately)

### Availability
- Not all LaserDiscs have digital audio
- Common on later discs (1990s+)
- Music discs typically have PCM
- Movies may have AC-3 instead




