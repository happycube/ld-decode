# ld-dropout-correct

**Dropout Detection and Concealment for TBC Files**

## Overview

ld-dropout-correct detects and conceals dropouts (signal loss) in Time Base Corrected (TBC) LaserDisc video files. It uses multiple strategies to replace missing or corrupted video data with reconstructed information from adjacent fields or lines.

## Usage

### Basic Syntax
```bash
ld-dropout-correct [options] inputs output
```

## Options

#### Common Options
- `-h, --help`: Display help on command-line options
- `-v, --version`: Display version information
- `-d, --debug`: Show debug information
- `-q, --quiet`: Suppress info and warning messages

#### Source Files
- `inputs`: Input TBC files (multiple files supported; use '-' as first source for piped input)
- `output`: Output corrected TBC file (omit or '-' for piped output)
- `--input-metadata <filename>`: Specify the input metadata file for the first input file (default input.db)
- `--output-metadata <filename>`: Specify the output metadata file (default output.db)

#### Processing Mode
- `-i, --intra`: Force intrafield correction (default interfield)
- `-r, --reverse`: Reverse the field order to second/first (default first/second)
- `-o, --overcorrect`: Over correct mode (use on heavily damaged single sources)
- `-t, --threads <number>`: Specify the number of concurrent threads (default is the number of logical CPUs)
- `-l, --length <frames>`: Process only specified number of frames

#### Additional Sources
- `--source <file.tbc>`: Additional source file for comparison
- Multiple `--source` options can be used

#### Dropout Detection
- `--input-dropouts <file>`: Use external dropout data
- `--output-dropouts <file>`: Save detected dropouts to file

#### Verbosity
- `-q, --quiet`: Suppress informational messages
- `-d, --debug`: Enable debug output

## Examples

```bash
# Basic Dropout Correction
ld-dropout-correct input.tbc output.tbc

# Using Additional Sources
ld-dropout-correct input.tbc output.tbc \
    --source capture2.tbc \
    --source capture3.tbc

# Intra-Field Correction
ld-dropout-correct --intra input.tbc output.tbc

# Reverse Processing
ld-dropout-correct --reverse input.tbc output.tbc

# Overcorrection Mode
ld-dropout-correct --overcorrect input.tbc output.tbc
```

## Input/Output

### Input Format
- TBC files with embedded dropout flags
- Associated SQLite metadata
- Supports all video standards (PAL/NTSC/PAL-M)

### Output Format
- Corrected TBC file (same format as input)
- Updated metadata with correction statistics
- Optional dropout mask output

## Troubleshooting

### Residual dropouts visible
- Try adding more source files
- Use --overcorrect mode
- Check that VBI processing was run first

### Motion artifacts
- Try --intra mode for high-motion scenes
- Consider manual editing of problem areas

### No dropouts corrected
- Verify metadata contains dropout information
- Check input file is actually a TBC file
- Ensure file permissions allow writing

### Overcorrection artifacts
- Reduce --overcorrect aggressiveness
- Use fewer or better-aligned source files
