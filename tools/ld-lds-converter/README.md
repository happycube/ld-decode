# ld-lds-converter

**10-bit to 16-bit Sample Converter**

## Overview

ld-lds-converter converts between 10-bit and 16-bit LaserDisc sample formats. It can unpack 10-bit packed data into 16-bit samples for processing, or pack 16-bit samples back into 10-bit format for storage efficiency. It also supports creating RIFF WAV headers for specific use cases like FlaCCL compression.

## Features

### Conversion Modes
- **Unpack (default)**: Convert 10-bit packed to 16-bit samples
- **Pack**: Convert 16-bit samples to 10-bit packed
- **RIFF Mode**: Unpack with RIFF WAV headers for FlaCCL

### Capabilities
- **Bidirectional**: Pack and unpack conversions
- **Streaming**: Process via stdin/stdout
- **File I/O**: Read from and write to files
- **Format Compatibility**: Works with standard LaserDisc capture formats

## Usage

### Basic Syntax
```bash
ld-lds-converter [options]
```

## Options

#### Common Options
- `-h, --help`: Display help on command-line options
- `-v, --version`: Display version information
- `-d, --debug`: Show debug information
- `-q, --quiet`: Suppress info and warning messages

#### Input/Output
- `-i, --input <file>`: Specify input laserdisc sample file (default is stdin)
- `-o, --output <file>`: Specify output laserdisc sample file (default is stdout)

#### Conversion Mode
- `-u, --unpack`: Unpack 10-bit data into 16-bit (default)
- `-p, --pack`: Pack 16-bit data into 10-bit
- `-r, --riff`: Unpack 10-bit data into 16-bit with RIFF WAV headers (use this ONLY for FlaCCL)

#### Verbosity
- `-q, --quiet`: Suppress info and warning messages
- `-d, --debug`: Show debug

### Examples

#### Unpack 10-bit to 16-bit
```bash
ld-lds-converter -i input_10bit.lds -o output_16bit.lds
```

#### Pack 16-bit to 10-bit
```bash
ld-lds-converter -p -i input_16bit.lds -o output_10bit.lds
```

#### Unpack with RIFF Headers (for FlaCCL)
```bash
ld-lds-converter -r -i input_10bit.lds -o output.wav
```

#### Using stdin/stdout
```bash
# Unpack from stdin to stdout
cat input.lds | ld-lds-converter > output.lds

# Pack with pipe
cat input_16bit.lds | ld-lds-converter -p > output_10bit.lds
```

## Technical Details

### 10-bit Packing

10-bit samples are packed efficiently to save storage space:
- **10-bit**: 4 samples = 40 bits = 5 bytes
- **16-bit**: 4 samples = 64 bits = 8 bytes
- **Savings**: ~37.5% storage reduction

### Sample Format

#### 10-bit Packed
- Packed efficiently, 4 samples per 5 bytes
- Custom bit packing format
- Smaller file sizes

#### 16-bit Unpacked
- Standard 16-bit signed samples
- Little-endian byte order
- Compatible with most tools

#### RIFF WAV
- 16-bit samples with RIFF WAV header
- Specifically for FlaCCL compression
- Standard WAV file format

### Performance
- **Speed**: Very fast (simple bit manipulation)
- **Memory**: Minimal (streaming)
- **Efficiency**: Processes large files quickly

## Integration Examples

### Unpack for Processing
```bash
# Unpack 10-bit capture
ld-lds-converter -u -i capture_10bit.lds -o capture_16bit.lds

# Decode
ld-decode capture_16bit.lds output.tbc

# Pack result for archival
ld-lds-converter -p -i capture_16bit.lds -o capture_archive.lds
```

### FlaCCL Workflow
```bash
# Convert to WAV with RIFF headers
ld-lds-converter -r -i input_10bit.lds -o temp.wav

# Compress with FlaCCL
flaccl -8 temp.wav -o compressed.flac
```

### Batch Processing
```bash
# Unpack all 10-bit files
for file in *_10bit.lds; do
    output="${file%_10bit.lds}_16bit.lds"
    ld-lds-converter -u -i "$file" -o "$output"
done
```

## Sample Rate Reference

### Common Rates
- **40 MHz**: NTSC (DomesDay Duplicator, modern)
- **28 MHz**: PAL (some setups)
- **20 MHz**: NTSC (older captures)
- **14 MHz**: PAL (older captures)
- **Custom**: Tool-dependent rates

### Standard Associations
- **NTSC**: Typically 40 MHz or 20 MHz
- **PAL**: Typically 28 MHz or 14 MHz
- **PAL-M**: Typically 40 MHz or 20 MHz

## Metadata Best Practices

### Essential Fields
1. **Sample Rate**: Always required for raw→LDS
2. **Standard**: PAL/NTSC/PAL-M identification
3. **Device**: Capture device used
4. **Date**: When captured

### Recommended Fields
- **Side**: Disc side (1 or 2)
- **Title**: Disc title
- **Notes**: Quality notes, issues, settings
- **Serial**: Disc serial/catalog number

### Metadata Format

Use with:
```bash
ld-lds-converter --raw-to-lds \
    input.raw output.lds
```

## Troubleshooting

### Issues

**Invalid LDS file:**
- Check magic number/version
- Verify file isn't corrupted
- Ensure complete file (not truncated)

**Missing metadata:**
- Required for raw→LDS: sample rate
- Use --set-metadata to add
- Or provide --metadata-file

**Wrong sample rate:**
- Specify correct rate with --sample-rate
- Check with original capture documentation
- Standard rates: 40 MHz (NTSC), 28 MHz (PAL)

**Conversion errors:**
- Verify input file format is correct
- Check sufficient disk space
- Ensure write permissions

**Metadata encoding issues:**
- Use UTF-8 encoding for metadata files
- Use `ld-export-metadata` to verify metadata format
- Ensure SQLite metadata database is not corrupted

## Format Comparison

| Feature | LDS | LDF | Raw |
|---------|-----|-----|-----|
| Metadata | Yes | Yes | No |
| Compression | No | Yes (FLAC) | No |
| Size | Large | Medium | Large |
| Interchange | Good | ld-decode specific | Universal |
| Complexity | Low | Medium | Minimal |


## Input/Output