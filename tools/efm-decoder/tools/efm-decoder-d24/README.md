# efm-decoder-d24

**EFM F2 Section to Data24 Section Decoder**

## Overview

efm-decoder-d24 takes F2 sections as input (from efm-decoder-f2) and decodes them into Data24 sections. This tool performs the critical CIRC error correction (C1 and C2) and unscrambling according to ECMA-130 specifications.

Data24 sections are an intermediate format that can be interpreted as either audio data (IEC 60908) or sector-based data (ECMA-130).

## Usage

```bash
efm-decoder-d24 [options] <input.f2> <output.d24>
```

## Options

- `-h, --help` - Display help information
- `-v, --version` - Display version information
- `-d, --debug` - Show debug output
- `-q, --quiet` - Suppress info and warning messages
- `--show-f1` - Show F1 frame data
- `--show-data24` - Show Data24 frame data
- `--show-f2-debug` - Show F2 to F1 decoding debug
- `--show-f1-debug` - Show F1 to Data24 decoding debug
- `--show-all-debug` - Show all debug options

### Arguments

- `input` - Input F2 section file (from efm-decoder-f2)
- `output` - Output Data24 section file

## Processing Pipeline

The decoding sequence performed by efm-decoder-d24:

1. **F2 Sections** → Input from efm-decoder-f2 (or stdin via Unix pipes)
2. **F1 Sections** → CIRC error correction applied
3. **Data24 Sections** → Byte order corrected, ready for final decoding

**Unix Pipelining**: efm-decoder-d24 supports stdin/stdout using `-`, allowing seamless integration in EFM processing pipelines.

## Technical Details

### CIRC Error Correction
The tool implements Cross-Interleaved Reed-Solomon Code (CIRC) error correction:
- **C1 Correction**: First level error correction
- **C2 Correction**: Second level error correction  
- **Unscrambling**: Data de-interleaving according to ECMA-130

### Data24 Format
Data24 sections consist of:
- 98 frames per section (representing 1/75th second)
- 24 bytes per frame (2352 bytes total per section)
- Corrected byte order (unlike F1 frames which have reversed byte order)
- Preserved section metadata from F2 input

### Error Handling
The CIRC system can:
- **Detect** up to 4 symbol errors per codeword
- **Correct** up to 2 symbol errors per codeword
- **Flag** uncorrectable errors for concealment by downstream tools

## Output Format

Data24 sections can be processed by either:
- `efm-decoder-audio` - For audio decoding (CD audio, LaserDisc digital audio)
- `efm-decoder-data` - For data decoding (Domesday LaserDiscs, CD-ROM data)

## Performance Notes

- CIRC correction is computationally intensive
- Error correction effectiveness depends on input quality
- Heavily damaged sections may require multiple source stacking (efm-stacker-f2)



