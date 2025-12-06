# ld-ldf-reader

**LDF Reader Tool for ld-decode**

## Overview

ld-ldf-reader extracts 16-bit data from .ldf (FLAC compressed) files. LDF is a compressed container format used by ld-decode for storing raw LaserDisc RF data efficiently using FLAC compression in an Ogg container. This tool decompresses and streams the raw 16-bit sample data to standard output.

## Usage

### Basic Syntax
```bash
ld-ldf-reader [options] input
```

Output is streamed to standard output.

## Options

#### Common Options
- `-h, --help`: Display help on command-line options
- `-v, --version`: Display version information
- `-d, --debug`: Show debug information
- `-q, --quiet`: Suppress info and warning messages

#### Input/Output
- `input`: Input LDF file (positional argument, required)
- `-s, --start-offset <samples>`: Start offset in samples (default: 0)

## Examples

### Extract Entire File
```bash
ld-ldf-reader capture.ldf > output.raw
```

### Extract with Start Offset
```bash
# Skip first 1,000,000 samples before reading
ld-ldf-reader --start-offset 1000000 capture.ldf > segment.raw
```

### Pipe to ld-decode
```bash
ld-ldf-reader capture.ldf | ld-decode - output.tbc
```

### Extract Specific Segment
```bash
# Extract 10MB starting from sample 50,000,000
ld-ldf-reader --start-offset 50000000 capture.ldf | head -c 10000000 > segment.raw
```

## Input/Output

### Input Format
- LDF files (FLAC audio in Ogg container, `.ldf` extension)
- Compressed RF sample data

### Output Format
- **16-bit Signed**: Little-endian sample data
- **Raw Stream**: No header, pure sample data
- **Stdout**: Direct streaming for piping to other tools

## LDF Format Details

### Structure
LDF files use FLAC compression in an Ogg container to store RF sample data efficiently. The tool decompresses and outputs raw 16-bit signed samples.

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
# Extract from specific position using offset
ld-ldf-reader --start-offset 1000000 capture.ldf | head -c 50000000 > segment.raw
```


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

### LDF Compressed (FLAC)
- **NTSC**: ~150-160 GB per hour
- **PAL**: ~100-120 GB per hour
- **Compression Ratio**: ~45-50% reduction

## Troubleshooting

### Common Issues

**Cannot read file:**
- Verify file is actually LDF format (use `file` command to check)
- Check file isn't corrupted
- Ensure FFmpeg libraries are properly installed

**Decompression errors:**
- File may be damaged
- Incomplete download/transfer
- Disk corruption (run filesystem check)

**Output issues:**
- LDF reader always outputs 16-bit signed little-endian format
- Use `--quiet` to suppress info messages if piping to another tool
- Redirect stderr to avoid mixing debug output with data stream

**Performance issues:**
- Decompression speed limited by CPU and I/O
- Use `--start-offset` to skip to specific positions efficiently
- Consider extracting specific segments for large files


## Testing

A test suite is included to verify proper operation:

```bash
# Run the ld-ldf-reader test
ctest -R ldf-reader-full
```

The test validates:
- Full file decompression and checksum verification
- Partial extraction with `--start-offset` parameter

