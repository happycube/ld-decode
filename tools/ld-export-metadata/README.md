# ld-export-metadata

**TBC Metadata Export and Conversion Tool**

## Overview

ld-export-metadata exports and converts metadata from TBC files into various human-readable and machine-readable formats. It provides access to detailed field-level information, VBI data, dropout statistics, and quality metrics.

**Note**: This is the **recommended tool for external scripts and applications** to access ld-decode metadata. The internal SQLite metadata format is subject to change without notice and should not be accessed directly by external tools.

## Features

### Export Formats
- `--vits-csv <file>`: Write VITS information as CSV
- `--vbi-csv <file>`: Write VBI information as CSV  
- `--audacity-labels <file>`: Write navigation information as Audacity labels
- `--ffmetadata <file>`: Write navigation information as FFMETADATA1
- `--closed-captions <file>`: Write closed captions as Scenarist SCC V1.0 format

### Data Categories
- **Field Information**: Sequence numbers, field order, timestamps
- **VBI Metadata**: Frame numbers, time codes, chapter marks
- **Video Parameters**: System type, dimensions, sample rate
- **Dropout Data**: Location, length, and statistics
- **Quality Metrics**: SNR, VITS measurements
- **NTSC Specific**: Closed captions, Video ID
- **Audio Information**: PCM parameters, EFM status

### Analysis Features
- **Field Range Selection**: Export specific frame ranges
- **Filtering Options**: Include/exclude specific data types
- **Statistical Summary**: Aggregate information across fields
- **Frame Number Mapping**: Convert between field/frame numbering

## Usage

### Basic Syntax
```bash
ld-export-metadata [options] <input.tbc>
```

## Options

#### Common Options
- `-h, --help`: Display help on command-line options
- `-v, --version`: Display version information
- `-d, --debug`: Show debug information
- `-q, --quiet`: Suppress info and warning messages

#### Export Formats
- `--vits-csv <file>`: Write VITS information as CSV
- `--vbi-csv <file>`: Write VBI information as CSV
- `--audacity-labels <file>`: Write navigation information as Audacity labels
- `--ffmetadata <file>`: Write navigation information as FFMETADATA1
- `--closed-captions <file>`: Write closed captions as Scenarist SCC V1.0 format

#### Arguments
- `input`: Input metadata file (required)

### Examples

#### Export VBI Data as CSV
```bash
ld-export-metadata --vbi-csv vbi.csv input.tbc.sqlite
```

#### Export VITS Data as CSV
```bash
ld-export-metadata --vits-csv vits.csv input.tbc.sqlite
```

#### Export FFmpeg Metadata for Chapter Marks
```bash
ld-export-metadata --ffmetadata chapters.txt input.tbc.sqlite
```

#### Export Closed Captions
```bash
ld-export-metadata --closed-captions captions.scc input.tbc.sqlite
```

#### Export Audacity Labels
```bash
ld-export-metadata --audacity-labels labels.txt input.tbc.sqlite
```

## Export Format Details

### CSV Format

#### Field Information
```csv
Field,IsFirstField,FieldPhaseID,SyncConf,MedianBurstIRE,DropoutCount,SNR
1,true,0,95,40.2,0,42.5
2,false,1,96,40.1,2,41.8
...
```

#### VBI Data
```csv
Field,DiscType,FrameNumber,ChapterNumber,TimeCode,UserCode
1,CAV,12345,5,,CUSTOM
2,CAV,12345,5,,CUSTOM
...
```

#### Dropout Data
```csv
Field,Line,StartX,EndX,Length
150,23,450,478,28
150,24,455,492,37
...
```


### FFmpeg Metadata Format

```ini
;FFMETADATA1
title=LaserDisc Capture
encoder=ld-decode

[CHAPTER]
TIMEBASE=1/25
START=0
END=100
title=Chapter 1

[CHAPTER]
TIMEBASE=1/25
START=100
END=250
title=Chapter 2
```

## Technical Details

### Input Format
- TBC metadata (SQLite format)
- Associated TBC file (for validation)
- All video standards supported (PAL/NTSC/PAL-M)

### Data Accuracy
- Exports exactly what is stored in metadata
- No interpretation or correction applied
- Timestamps calculated from field numbers and standard

### Performance
- **Speed**: Very fast (metadata-only operation)
- **Memory**: Minimal (streaming export)
- **File Size**: Depends on field count and data density

## Integration Examples

### Python Analysis
```python
import pandas as pd
import pandas as pd

# Load metadata
with open('metadata.sqlite', 'r') as f:
    data = pd.read_csv(f)

# Analyze dropout distribution
dropouts = []
for field in data['fields']:
    dropouts.extend(field.get('dropOuts', []))

df = pd.DataFrame(dropouts)
print(f"Total dropouts: {len(df)}")
print(f"Average length: {df['length'].mean():.1f} samples")
```

### Shell Script Processing
```bash
# Export VBI data and extract frame numbers
ld-export-metadata --vbi-csv vbi_data.csv input.tbc
awk -F',' 'NR>1 {print $1}' vbi_data.csv | sort -u > frames_with_vbi.txt
```

### FFmpeg Chapter Integration
```bash
# Export chapters
ld-export-metadata --ffmetadata chapters.txt input.tbc

# Add to final video
ffmpeg -i video.mkv -i chapters.txt -map_metadata 1 -codec copy output.mkv
```



