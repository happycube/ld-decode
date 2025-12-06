# ld-discmap

**TBC and VBI Alignment and Correction**

## Overview

ld-discmap performs TBC and VBI alignment and correction. It maps frame numbers from VBI data to the actual video fields, corrects field ordering issues, handles pulldown detection, and can delete unmappable frames. This tool is essential for ensuring proper frame synchronization and handling various video format conversions.



## Usage

### Basic Syntax
```bash
ld-discmap [options] <input.tbc> <output.tbc>
```

## Options

#### Common Options
- `-h, --help`: Display help on command-line options
- `-v, --version`: Display version information
- `-d, --debug`: Show debug information
- `-q, --quiet`: Suppress info and warning messages

#### Input/Output
- `input`: Input TBC file (required)
- `output`: Output TBC file (required unless using --maponly)

#### Processing Options
- `-r, --reverse`: Reverse the field order to second/first (default first/second)
- `-m, --maponly`: Only perform mapping - No output TBC file required
- `-s, --nostrict`: No strict checking on pulldown frames
- `-u, --delete-unmappable-frames`: Delete unmappable frames
- `-n, --no-audio`: Do not process analogue audio

#### Verbosity
- `-q, --quiet`: Suppress info and warning messages
- `-d, --debug`: Show debug

## Examples

```bash
# Basic Frame Mapping
ld-discmap input.tbc output.tbc

# Map Only (No Output)
ld-discmap -m input.tbc output.tbc

# Delete Unmappable Frames
ld-discmap -u input.tbc output.tbc

# No Strict Pulldown Checking
ld-discmap -s input.tbc output.tbc

# Reverse Field Order
ld-discmap -r input.tbc output.tbc

# Skip Audio Processing
ld-discmap -n input.tbc output.tbc
```

## Input/Output

### Input Format
- TBC files with VBI metadata processed
- Associated SQLite metadata
- Supports all video standards (PAL, NTSC, PAL-M)

### Output Format
- Corrected TBC with updated metadata
- Frame mapping information in metadata

## Troubleshooting

### VBI mapping errors
- Ensure ld-process-vbi was run first
- Check that VBI data is present in metadata
- Some discs have poor VBI data quality

### Unmappable frames
- Use --delete-unmappable-frames to remove them
- Or keep them and handle in downstream tools
- Check source disc quality

### Field order issues
- Try --reverse option
- Verify metadata has correct field order
- Check with ld-analyse

### Audio sync problems
- Ensure audio processing is enabled (remove -n)
- Check that analogue audio is present
- Verify audio track alignment
