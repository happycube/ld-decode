# ld-process-vbi

**VBI Data Extraction and Decoding**

## Overview

ld-process-vbi extracts and decodes Vertical Blanking Interval (VBI) data from TBC files. It reads embedded metadata such as frame numbers, time codes, chapter marks, user codes, and closed captions, updating the TBC metadata for use by other tools.

## Features

### VBI Data Types

#### Frame Numbering
- **CAV Frame Numbers**: Picture numbers from CLV/CAV discs
- **Frame Identification**: Unique frame identifiers
- **Frame Mapping**: Correlates disc frames to capture fields

#### Chapter Information
- **Chapter Marks**: Chapter stop codes
- **Chapter Numbers**: Sequential chapter identification
- **Program Markers**: Program/title boundaries

#### Time Codes
- **IEC Time Code**: Standard time code format (HH:MM:SS:FF)
- **Vertical Interval Time Code (VITC)**: Where available

#### User Data
- **User Codes**: Custom data embedded by disc manufacturer
- **Program Status**: Lead-in, lead-out, disc side
- **Picture Stop**: Still frame markers

#### NTSC Specific
- **Closed Captions**: Line 21 CC data (CEA-608)
- **Video ID**: White flag, chapter/frame codes
- **AmigaVision**: Amiga metadata (if present)

### Processing Options
- **Line Selection**: Process specific VBI lines
- **Format Override**: Force specific VBI format
- **Range Processing**: Process specific frame ranges
- **Validation**: Verify VBI data integrity

## Usage

### Basic Syntax
```bash
ld-process-vbi [options] <input.tbc>
```

## Options

#### Common Options
- `-h, --help`: Display help on command-line options
- `-v, --version`: Display version information
- `-d, --debug`: Show debug information
- `-q, --quiet`: Suppress info and warning messages

#### Processing Control
- `--input-metadata <filename>`: Specify the input metadata file (default input.db)
- `--output-metadata <filename>`: Specify the output metadata file (default same as input)
- `-n, --nobackup`: Do not create a backup of the input metadata
- `-t, --threads <number>`: Specify the number of concurrent threads (default is the number of logical CPUs)

#### Arguments
- `input`: Input TBC file (required)

### Examples

#### Basic VBI Processing
```bash
ld-process-vbi input.tbc
```

#### Process with Multiple Threads
```bash
ld-process-vbi -t 8 input.tbc
```

#### Don't Create Backup
```bash
ld-process-vbi -n input.tbc
```

#### Debug Mode
```bash
ld-process-vbi -d input.tbc
```

## VBI Line Locations

### PAL
- **Line 16**: Frame number (most common)
- **Line 17**: IEC time code, chapter marks
- **Line 18**: User code, program status
- **Line 19**: Additional metadata (some discs)

### NTSC
- **Line 10-11**: Frame number (field 1)
- **Line 12-13**: IEC time code (field 1)
- **Line 14**: Chapter, user codes (field 1)
- **Line 21**: Closed captions (both fields)
- **Line 273-274**: Frame number (field 2)

## Output Information

After processing, metadata is updated with:

### VBI Data Structure

### Closed Caption Data

## Data Validation

ld-process-vbi validates:
- **Checksum**: Hamming codes, parity bits
- **Continuity**: Frame number sequences
- **Format**: Proper VBI format structure
- **Range**: Values within expected bounds

Invalid data is:
- Flagged in debug output
- Not written to metadata (preserved as null)
- Reported in statistics (if enabled)

## Technical Details

### Input Format
- TBC files with VBI lines intact
- Associated SQLite metadata
- Supports PAL, NTSC, PAL-M standards

### Processing Algorithm
1. Load TBC metadata
2. For each field:
   - Extract VBI lines from TBC data
   - Decode according to standard (PAL/NTSC)
   - Validate checksums and format
   - Update metadata with decoded information
3. Write updated metadata

### Performance
- **Speed**: 200-500 fps (I/O bound)
- **Memory**: Approximately 50MB + field cache
- **Threading**: Single-threaded

### VBI Decoding Standards
- **IEC 60857**: PAL VBI standard (White Book)
- **EIA-J**: NTSC LaserDisc standard
- **CEA-608**: Closed captioning standard
- **SMPTE RP-157**: AmigaVision metadata

## Quality Considerations

### Best Practices
1. **Run Early**: Process VBI before dropout correction
2. **Check Statistics**: Use --statistics to verify decode success
3. **Validate**: Inspect results with ld-analyse VBI dialog
4. **Line Selection**: Use correct lines for your disc type

### Common Issues
- **Poor RF Quality**: Results in failed VBI decodes
- **Non-Standard Discs**: May use different line locations
- **Worn Discs**: VBI may be damaged/inconsistent

## Pipeline Usage

Typical position in processing pipeline:

```bash
# Standard LaserDisc workflow
ld-decode input.ldf capture.tbc
ld-process-vbi capture.tbc              # Run before dropout correction
ld-dropout-correct capture.tbc corrected.tbc
ld-chroma-decoder corrected.tbc output.rgb
```

## Troubleshooting

### Issues

**No VBI data extracted:**
- Verify disc contains VBI data (not all discs do)
- Try different --vbi-lines range
- Check --statistics for decode errors
- Inspect with ld-analyse to verify VBI lines are visible

**Incorrect frame numbers:**
- May be non-standard disc (use --force-standard)
- Check for multi-format discs (PAL/NTSC hybrid)
- Verify proper field order in metadata

**Closed captions not extracted:**
- NTSC only feature (not available on PAL)
- Use --closed-captions option explicitly
- Check line 21 quality in ld-analyse

**Inconsistent chapter marks:**
- Normal for some discs (chapters may be sparse)
- Validate with physical disc documentation


## Input/Output