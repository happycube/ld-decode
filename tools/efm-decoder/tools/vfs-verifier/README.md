# vfs-verifier

**Virtual File System Data Verifier**

## Overview

vfs-verifier validates and analyzes data recovered from Domesday LaserDiscs and other VFS-containing optical media. It verifies file system integrity, extracts metadata, and provides detailed analysis of data recovery quality and completeness.

## Usage

```bash
vfs-verifier [options] <input.bin> [output_report.txt]
```

## Options

- `-h, --help` - Display help information
- `-v, --version` - Display version information
- `-d, --debug` - Show debug output
- `-q, --quiet` - Suppress info and warning messages
- `--vfs-type TYPE` - Specify VFS type (domesday, acorn, generic)
- `--output-metadata FILE` - Generate detailed metadata report
- `--verify-checksums` - Perform checksum verification where available
- `--extract-files` - Extract individual files from the VFS
- `--output-dir DIR` - Directory for extracted files (default: vfs_extracted)
- `--summary-only` - Generate summary report only

### Arguments

- `input.bin` - Input binary data file from efm-decoder-data
- `output_report.txt` - Optional output verification report

## VFS Type Support

### Domesday LaserDisc VFS
- **Purpose**: BBC Domesday Project data verification
- **Structure**: Acorn DFS with custom extensions
- **Features**: Geographic data, text, images, software
- **Validation**: CRC checks, file table verification, geographic data integrity

### Acorn DFS
- **Purpose**: General Acorn Disk Filing System verification  
- **Structure**: Standard Acorn DFS layout
- **Features**: File allocation, directory structures
- **Validation**: Catalog integrity, file size verification

### Generic VFS
- **Purpose**: Unknown or custom file systems
- **Structure**: Basic structural analysis
- **Features**: Pattern recognition, data classification
- **Validation**: Structural consistency checks

## Verification Process

### File System Analysis
1. **Header Validation**: Check VFS header and magic numbers
2. **Directory Structure**: Verify directory entries and allocation
3. **File Table**: Validate file allocation table consistency  
4. **Cross-References**: Check file size vs. allocated sectors
5. **Metadata**: Extract and verify embedded metadata

### Data Integrity Checks
- **Checksums**: Verify embedded checksums where available
- **Consistency**: Cross-check redundant information
- **Completeness**: Identify missing or corrupted sectors
- **Geographic Data**: Validate coordinate systems and data ranges (Domesday)

## Pipeline Integration

### Input Requirements
- Binary data file from efm-decoder-data
- Preferably error-corrected and verified data
- Complete file system image (partial images supported but limited)

### Standard Workflow

#### Domesday Data Recovery
```bash
# Complete pipeline from EFM to verified VFS
efm-decoder-f2 domesday.efm domesday.f2
efm-decoder-d24 domesday.f2 domesday.d24
efm-decoder-data domesday.d24 domesday.bin --output-metadata domesday_meta.txt

# Verify and extract VFS
vfs-verifier domesday.bin domesday_report.txt \
  --vfs-type domesday \
  --verify-checksums \
  --extract-files \
  --output-dir domesday_extracted \
  --output-metadata domesday_vfs_meta.txt
```

#### Quality Assessment Workflow
```bash
# Multi-source stacked recovery with verification
efm-stacker-f2 dom1.f2 dom2.f2 dom3.f2 stacked.f2
efm-decoder-d24 stacked.f2 stacked.d24  
efm-decoder-data stacked.d24 final.bin

# Comprehensive verification
vfs-verifier final.bin quality_report.txt \
  --vfs-type domesday \
  --verify-checksums \
  --debug \
  --output-metadata complete_analysis.txt
```

## Output Reports

### Summary Report
Basic verification results:
- VFS type identification
- Total files found/expected  
- File system integrity status
- Overall data recovery percentage
- Critical errors and warnings

### Detailed Metadata Report
Comprehensive analysis including:
- Complete file listing with sizes and checksums
- Directory structure map
- Sector allocation analysis
- Geographic coordinate verification (Domesday)
- Data classification and content analysis
- Corruption pattern analysis

### Extracted Files
When `--extract-files` is used:
- Individual files extracted to specified directory
- Original file names and metadata preserved
- Corrupted files marked with .partial extension
- Index file listing all extractions

## Quality Metrics

### File System Level
- **Completeness**: Percentage of expected files successfully recovered
- **Integrity**: File system structure consistency
- **Accessibility**: Files that can be fully extracted vs. partially recovered

### Data Level  
- **Checksum Verification**: Files passing embedded checksum tests
- **Geographic Accuracy**: Coordinate system validation (Domesday specific)
- **Content Classification**: Data type identification and validation

## Error Detection and Reporting

### File System Errors
- Missing or corrupted directory entries
- Invalid file allocation table entries
- Inconsistent file sizes
- Broken cross-references

### Data Corruption Patterns
- Systematic vs. random errors
- Sector-level corruption clustering
- EFM-to-data error propagation analysis
- Recovery success correlation with input quality

## Technical Details

### VFS Structure Analysis
- **Sector Size**: Typically 1024 bytes (Domesday), 256 bytes (Acorn DFS)
- **Directory Format**: Acorn DFS catalog format with extensions
- **File Allocation**: Track allocation table consistency
- **Metadata**: Extract creation dates, file attributes, checksums

### Domesday-Specific Features
- **Geographic Data**: Validate OS Grid References and coordinate systems
- **Image Data**: Verify embedded image formats and compression
- **Text Data**: Check character encoding and text structure
- **Software**: Validate executable file integrity

## Integration with Other Tools

### Error Correction Pipeline
vfs-verifier provides feedback for:
- efm-decoder-data parameter tuning
- Multi-source stacking quality assessment  
- Optimal recovery strategy selection

### Archive Workflows
Results can be used for:
- Digital preservation documentation
- Research data validation
- Historical accuracy verification
- Long-term storage planning



