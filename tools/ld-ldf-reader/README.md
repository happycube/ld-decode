# ld-ldf-reader

**LaserDisc LDF Format Reader and Extractor**

## Overview

ld-ldf-reader extracts 16-bit data from .ldf (.oga compressed) files. LDF is a compressed container format used by ld-decode for storing raw LaserDisc RF data efficiently using OGG/Vorbis compression. This tool streams the decompressed data to standard output.

## Features

### Format Support
- **LDF Reading**: Native ld-decode RF format (.ldf files)
- **OGA Decompression**: Decompress .oga compressed RF data
- **Streaming Output**: Direct to stdout for piping
- **Seek Support**: Optional seek to specific location in file

## Usage

### Basic Syntax
```bash
ld-ldf-reader [filename] [seek location]
```

Output is streamed to standard output.

## Options

This tool does not use standard command-line options. It has a simplified interface:

#### Arguments
- `filename`: LDF file to read (required)
- `seek location`: Optional sample position to seek to before reading

### Examples

#### Extract Entire File
```bash
ld-ldf-reader capture.ldf > output.raw
```

#### Seek to Position
```bash
# Seek to sample 1000000 before reading
ld-ldf-reader capture.ldf 1000000 > segment.raw
```

#### Pipe to ld-decode
```bash
ld-ldf-reader capture.ldf | ld-decode - output.tbc
```

#### Extract Segment
```bash
# Extract from specific position
ld-ldf-reader capture.ldf 50000000 | head -c 10000000 > segment.raw
```

## LDF Format Details

### Structure
LDF files use OGG/Vorbis (.oga) compression to store RF sample data efficiently. The tool decompresses and outputs raw 16-bit signed samples.

### Output Format
- **16-bit Signed**: Little-endian sample data
- **Raw Stream**: No header, pure sample data
- **Stdout**: Direct streaming for piping to other tools

## Technical Details

### Performance
- **Speed**: Limited by decompression and I/O
- **Memory**: Minimal buffering
- **Streaming**: Processes continuously without loading entire file

### Sample Format
- **Bit Depth**: 16-bit signed
- **Byte Order**: Little-endian
- **Channels**: Single channel (RF signal)

## Integration Examples

### Stream to ld-decode
```bash
# Decompress and decode in one pipeline
ld-ldf-reader capture.ldf | ld-decode - output.tbc
```

### Extract and Save
```bash
# Convert LDF to raw file
ld-ldf-reader capture.ldf > capture.raw
```

### Segment Extraction
```bash
# Extract from specific position
ld-ldf-reader capture.ldf 1000000 | head -c 50000000 > segment.raw
```

## Sample Rate Information

### Common Sample Rates
- **40 MHz**: NTSC captures (typical DomesDay Duplicator)
- **28 MHz**: PAL captures (some setups)
- **20 MHz**: NTSC captures (older setups)
- **14 MHz**: PAL captures (older setups)

### Duration Calculation
```
Duration (seconds) = Total Samples / Sample Rate

Example (NTSC):
  21,600,000,000 samples / 40,000,000 Hz = 540 seconds = 9 minutes
```

## File Size Expectations

### Uncompressed
- **Formula**: `Size = Samples × 2 bytes`
- **NTSC**: ~288 GB per hour (40 MHz)
- **PAL**: ~201 GB per hour (28 MHz)

### LDF Compressed
- **NTSC**: ~150-160 GB per hour
- **PAL**: ~100-120 GB per hour
- **Savings**: ~45-50% compression

## Troubleshooting

### Issues

**Cannot read file:**
- Verify file is actually LDF format
- Check file isn't corrupted (--verify)
- Ensure ld-decode tools are updated

**Decompression errors:**
- File may be damaged
- Incomplete download/transfer
- Disk corruption (run filesystem check)

**Wrong output format:**
- LDF reader always outputs 16-bit signed LE
- Use conversion tools if different format needed

**Performance issues:**
- Ensure adequate CPU for decompression
- Check disk I/O speed (use fast storage)
- Consider extracting ranges for large files

**Incomplete extraction:**
- Verify start/length parameters
- Check available disk space
- Ensure file permissions

## Conversion from Other Formats

### Create LDF from Raw
LDF files are typically created by ld-decode during capture. To create from raw RF:

```bash
# Use ld-decode to process and create LDF
ld-decode input.raw output.tbc

# Or use custom tools that support LDF writing
```

Note: ld-ldf-reader is read-only. For writing LDF files, use ld-decode or other compatible tools.


## Input/Output