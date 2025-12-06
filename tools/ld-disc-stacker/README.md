# ld-disc-stacker

**Multi-Source TBC Stacking and Combination**

## Overview

ld-disc-stacker combines multiple TBC captures of the same LaserDisc to produce a superior output. By analyzing corresponding fields from multiple sources, it selects the best data for each field, effectively reducing dropouts and improving overall signal quality.

## Usage

### Basic Syntax
```bash
ld-disc-stacker [options] <source1.tbc> <source2.tbc> [...] <output.tbc>
```

## Options

#### Common Options
- `-h, --help`: Display help on command-line options
- `-v, --version`: Display version information
- `-d, --debug`: Show debug information
- `-q, --quiet`: Suppress info and warning messages
- `--help-mode`: Show info about stacking mode
- `-V, --verbose`: Show more info during stacking

#### Input Sources
- `inputs`: Input TBC files - first can be `-` for piped input (required, 2+ sources)
- `output`: Combined output TBC (omit or `-` for piped output) (required)

#### Metadata
- `--input-metadata <filename>`: Specify the input metadata file for the first input file (default input.db)
- `--output-metadata <filename>`: Specify the output metadata file (default output.db)

#### Processing Options
- `-r, --reverse`: Reverse the field order to second/first (default first/second)
- `-t, --threads <number>`: Specify the number of concurrent threads (default is the number of logical CPUs)

#### Stacking Mode
- `-m, --mode <number>`: Specify the stacking mode to use (default is Auto)
  - -1 = Auto
  - 0 = Mean
  - 1 = Median
  - 2 = Smart mean
  - 3 = Smart neighbor
  - 4 = Neighbor
- `--st, --smart-threshold <number>`: Range of value in 8 bit (0~128) for smart mode selection (default is 15)

#### Advanced Options
- `--no-diffdod`: Do not use differential dropout detection on low source pixels
- `--no-map`: Disable mapping requirement
- `--passthrough`: Pass-through dropouts present on every source
- `--it, --integrity`: Check if frames contain skip or sample drop and discard bad source for specific frame
  - 2 = Smart mean
  - 3 = Smart neighbor
  - 4 = Neighbor
- `--help-mode`: Show info about stacking mode
- `--st, --smart-threshold <number>`: Range of value in 8-bit (0~128) for smart mean (default 15)

#### Processing Options
- `-r, --reverse`: Reverse the field order to second/first (default first/second)
- `--no-diffdod`: Do not use differential dropout detection on low source pixels
- `--no-map`: Disable mapping requirement
- `--passthrough`: Pass-through dropouts present on every source
- `--it, --integrity`: Check if frames contain skip or sample drop and discard bad source for specific frame

#### Threading
- `-t, --threads <number>`: Specify the number of concurrent threads (default is the number of logical CPUs)

#### Verbosity
- `-q, --quiet`: Suppress info and warning messages
- `-d, --debug`: Show debug
- `-V, --verbose`: Show more info during stacking

## Examples

```bash
# Basic Two-Source Stack
ld-disc-stacker capture1.tbc capture2.tbc combined.tbc

# Use median mode
ld-disc-stacker -m 1 capture1.tbc capture2.tbc capture3.tbc combined.tbc

# Use smart mean with custom threshold
ld-disc-stacker -m 2 --st 20 capture1.tbc capture2.tbc combined.tbc

# With Integrity Checking
ld-disc-stacker --it capture1.tbc capture2.tbc capture3.tbc combined.tbc
```

## Input/Output

### Input Requirements
- **Same Disc**: All sources must be from same physical disc
- **VBI Data**: Sources need ld-process-vbi run first
- **Same Standard**: PAL sources with PAL, NTSC with NTSC
- **Quality Metadata**: Requires SNR and dropout data

### Output
- **Best-Of TBC**: Combined output with best fields
- **Source Map**: Track which source used per field
- **Statistics**: Quality improvement metrics
- **Metadata**: Complete combined metadata

## Troubleshooting

### Alignment Issues
- Ensure all sources are from same physical disc
- Check that ld-process-vbi was run on all sources
- Verify VBI frame numbers are present in metadata

### Quality Issues
- Use `--verbose` to see selection decisions
- Try different stacking modes (-m option)
- Check individual source quality with ld-analyse

### Performance Issues
- Reduce thread count if memory usage is high
- Process sources in smaller batches for large files
- **SourceUsed**: Which source (1-based index)
- **SNR**: SNR value from selected source
- **DropoutCount**: Dropout count from selected source
- **Reason**: Why this source was selected

