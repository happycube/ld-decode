# efm-decoder-data

**EFM Data24 to Binary Data Decoder**

## Overview

efm-decoder-data converts Data24 sections into ECMA-130 compliant binary data sectors. This tool handles data-mode EFM decoding for applications like Domesday LaserDiscs and CD-ROM data, performing Reed-Solomon Product Code (RSPC) error correction and producing raw binary output.

## Usage

```bash
efm-decoder-data [options] <input.d24> <output.bin>
```

## Options

- `-h, --help` - Display help information
- `-v, --version` - Display version information
- `-d, --debug` - Show debug output
- `-q, --quiet` - Suppress info and warning messages
- `--output-metadata` - Output bad sector map metadata file
- `--show-rawsector` - Show raw sector frame data
- `--show-rawsector-debug` - Show Data24 to raw sector decoding debug
- `--show-sector-debug` - Show raw sector to sector decoding debug
- `--show-sector-correction-debug` - Show sector correction debug
- `--show-all-debug` - Show all decoding debug

### Arguments

- `input` - Input Data24 section file (from efm-decoder-d24)
- `output` - Output binary data file

## Processing Pipeline

The decoding sequence performed by efm-decoder-data:

1. **Data24 Sections** → Input from efm-decoder-d24 (or stdin via Unix pipes, 2352 bytes per section)
2. **Raw Sectors** → Extract 2048-byte data sectors from each section
3. **RSPC Error Correction** → Reed-Solomon Product Code correction
4. **Sector Validation** → Mark sectors as valid or invalid
5. **Binary Output** → Continuous binary data stream

**Unix Pipelining**: efm-decoder-data supports stdin/stdout using `-`, enabling direct data extraction from EFM processing pipelines.

## Technical Details

### Data Format Conversion
- **Input**: Data24 sections (2352 bytes each, representing 1/75 second)
- **Processing**: Strip EFM parity and error correction overhead
- **Output**: Pure data sectors (2048 bytes each)
- **Efficiency**: ~87% data efficiency (2048/2352)

### RSPC Error Correction
Implements Reed-Solomon Product Code correction according to ECMA-130:
- **Q Parity**: Outer code correction
- **P Parity**: Inner code correction  
- **Sector-level**: All-or-nothing correction per 2048-byte sector
- **Unscrambling**: Data de-interleaving for error correction

### Error Handling
Unlike audio decoding, data decoding is binary:
- **Valid sectors**: Fully corrected, guaranteed accuracy
- **Invalid sectors**: Uncorrectable, flagged in metadata
- **No concealment**: Corrupted data is not interpolated

## Metadata Output

### Bad Sector Map
When `--output-metadata` is specified, creates a text file listing invalid sector addresses:

```
28
29
30
31
```

Each number represents a 2048-byte sector that could not be corrected.

### Format
- One sector address per line
- Addresses are sequential (starting from 0)
- Only invalid/uncorrectable sectors are listed
- Can be used by downstream tools for error handling

## Pipeline Integration

### Input Requirements
- Data24 sections from efm-decoder-d24
- CIRC-corrected data (first-stage error correction completed)

### Common Workflows

#### Standard Data Extraction
```bash
# Complete pipeline for data using Unix pipes
efm-decoder-f2 input.efm - | efm-decoder-d24 - - | efm-decoder-data - output.bin --output-metadata

# Alternative: step by step with files
efm-decoder-f2 input.efm temp.f2
efm-decoder-d24 temp.f2 temp.d24  
efm-decoder-data temp.d24 output.bin --output-metadata
```

#### Domesday LaserDisc Workflow
```bash
# Extract data then verify VFS structure
efm-decoder-data domesday.d24 domesday.bin --output-metadata
vfs-verifier domesday.bin domesday_metadata.txt
```

#### Multi-Source Data Recovery
```bash
# Stack sources for better error correction
efm-stacker-f2 disc1.f2 disc2.f2 disc3.f2 stacked.f2
efm-decoder-d24 stacked.f2 stacked.d24
efm-decoder-data stacked.d24 recovered.bin --output-metadata
```

## Output Verification

The extracted binary data can be verified using:
- `vfs-verifier` - For Domesday LaserDisc VFS structures
- Standard file analysis tools
- Checksum verification (if reference data available)



