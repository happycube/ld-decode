# efm-decoder-f2

**EFM T-values to F2 Section Decoder**

## Overview

efm-decoder-f2 takes T-values as input (supplied by a tool such as ld-decode) and decodes them into F2 sections. Each section contains 98 F2 frames representing 1/75th of a second of data.

The tool handles the initial stages of EFM decoding, converting raw T-values through channel frames and F3 frames to produce F2 sections with basic error correction.

## Usage

```bash
efm-decoder-f2 [options] <input.efm> <output.f2>
```

## Options

- `-h, --help` - Display help information
- `-v, --version` - Display version information  
- `-d, --debug` - Show debug output
- `-q, --quiet` - Suppress info and warning messages
- `--show-f3` - Show F3 frame data
- `--show-f2` - Show F2 frame data
- `--show-tvalues-debug` - Show T-values to channel decoding debug
- `--show-channel-debug` - Show channel to F3 decoding debug
- `--show-f3-debug` - Show F3 to F2 section decoding debug  
- `--show-f2-correct-debug` - Show F2 section correction debug
- `--show-all-debug` - Show all debug output
- `--no-timecodes` - Process input EFM data with no timecodes (may increase error rates)
- `--show-channel-debug` - Show channel to F3 decoding debug
- `--show-f3-debug` - Show F3 to F2 section decoding debug
- `--show-f2-correct-debug` - Show F2 section correction debug

### Arguments

- `input` - Input EFM file containing T-values
- `output` - Output F2 section file

## Processing Pipeline

The decoding sequence performed by efm-decoder-f2:

1. **T-values** → Channel bit stream conversion (from EFM file or stdin)
2. **Channel frames** → 588-bit frames with sync patterns
3. **F3 Frames** → 33 symbols of 8-bits each (264 bits total)
4. **F2 Sections** → Groups of 98 F2 frames with CIRC parity
5. **F2 Section Correction** → Basic error detection and correction

**Unix Pipelining**: efm-decoder-f2 supports stdin/stdout using `-`, making it the starting point for EFM processing pipelines.

## Technical Details

### T-Values
T-values range from T3 to T11, representing different EFM event periods:
- T3 = 100 (shortest event)
- T4 = 1000
- T5 = 10000
- ...
- T11 = 10000000000 (longest event)

### Channel Frames
Each 588-bit channel frame contains:
- Sync Header: 24 channel bits
- Merging bits: 3 channel bits  
- Control byte: 14 channel bits
- Merging bits: 3 channel bits
- Data bytes 1-32: 32 × (14+3) = 544 channel bits

### F2 Sections
Each F2 section represents 1/75th of a second and contains:
- 98 F2 frames of corrected data
- Associated subcode metadata
- CIRC parity for error detection/correction

## Output Format

The output F2 section file contains binary data that can be processed by:
- `efm-decoder-d24` - For further decoding to Data24 format
- `efm-stacker-f2` - For multi-source error correction



