# ld-decode Tools

This directory contains the complete suite of tools for processing LaserDisc captures and TBC (Time Base Corrected) files. The ld-decode project provides professional-grade tools for digitizing, processing, and analyzing analog video sources with exceptional quality and accuracy.

## Tool Categories

### Core Processing Tools
- **ld-decode** - Primary decoder for raw RF captures to TBC format
- **ld-process-vbi** - Decode Vertical Blanking Interval data
- **ld-process-vits** - Process Vertical Interval Test Signals
- **ld-process-ac3** - Extract Dolby Digital AC3 audio tracks

### EFM Decoder Suite
*Replaces deprecated ld-process-efm with staged decoding and stacking capabilities*
- **efm-decoder-f2** - Convert EFM T-values to F2 sections
- **efm-decoder-d24** - Convert F2 sections to Data24 format
- **efm-decoder-audio** - Convert EFM Data24 sections to 16-bit stereo PCM audio
- **efm-decoder-data** - Convert EFM Data24 sections to ECMA-130 binary data
- **efm-stacker-f2** - Combine multiple F2 captures for improved quality

### Analysis and Quality Tools
- **ld-analyse** - GUI tool for TBC file analysis and visualization
- **ld-discmap** - TBC and VBI alignment and correction tool
- **ld-dropout-correct** - Advanced dropout detection and correction
- **ld-chroma-decoder** - Color decoder for TBC LaserDisc video to RGB/YUV conversion
- **ld-disc-stacker** - Combine multiple TBC captures for improved quality

### Export and Conversion Tools
- **ld-export-metadata** - Export TBC metadata to external formats
- **ld-lds-converter** - Convert between 10-bit and 16-bit LaserDisc sample formats
- **ld-json-converter** - Convert between old internal JSON and new internal SQLite metadata formats

### Utility Scripts
- **ld-compress** - Compress TBC files for storage (in scripts/)
- **filtermaker** - Create custom filtering profiles (in scripts/)
- **tbc-video-export-legacy** - Legacy TBC to video conversion (archived)

## Getting Started

1. **Capture Processing**: Start with `ld-decode` to convert raw RF captures to TBC format
2. **Quality Analysis**: Use `ld-analyse` to assess capture quality and identify issues
3. **Correction**: Apply `ld-dropout-correct` for dropout repair if needed
4. **Chroma Decoding**: Process composite sources with `ld-chroma-decoder`
5. **Export**: Convert to final formats using `tbc-video-export`

## Important Notes

- **SQLite Format**: All tools now use SQLite format for metadata storage instead of JSON
- **File Extensions**: TBC files use `.tbc` extension, metadata uses `.tbc.db` (SQLite format)
- **Dependencies**: Most tools require FFmpeg and other multimedia libraries
- **Performance**: Many tools support multi-threading for faster processing

> [!WARNING]  
> The SQLite metadata format is **internal to ld-decode tools only** and subject to change without notice. External tools and scripts should **not** access this database directly. Instead, use `ld-export-metadata` or similar tools to export metadata in stable, documented formats.

## Documentation

Each tool directory contains detailed README.md files with:
- Comprehensive usage instructions
- Complete option references
- Practical examples
- Input/output format specifications
- Troubleshooting guides

See individual tool directories for specific documentation.

