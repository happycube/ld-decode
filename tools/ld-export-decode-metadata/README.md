# ld-export-decode-metadata

**SQLite to JSON Metadata Converter**

## Overview

`ld-export-decode-metadata` exports internal TBC SQLite metadata information into a JSON file for external tools.

**⚠️ Important**: The SQLite metadata format is **internal to ld-decode tools only** and subject to change without notice. External tools and scripts should **not** access this database directly.
Instead, use this tool to export metadata in a (mostly) stable, documented format.
Because ld-decode, vhs-decode, or ld-tools may evolve in backward-incompatible ways, the export metadata format may have to change as well and therefore includes a version field.

## Usage

### Basic Syntax
```bash
ld-export-decode-metadata [options]
```

## Options

#### Common Options
- `-h, --help`: Display help on command-line options
- `-v, --version`: Display version information
- `-d, --debug`: Show debug information
- `-q, --quiet`: Suppress info and warning messages

#### Input/Output
- `--input-sqlite <filename>`: Specify the input SQLite file
- `--output-json <filename>`: Specify the output JSON file (default same as input but with -export.json extension))

#### Standard Options
- `-d, --debug`: Show debug messages
- `-q, --quiet`: Suppress info and warning messages
- `-h, --help`: Display help information
- `-v, --version`: Display version information

## Input/Output

### Input Format
- TBC SQLite database metadata files (`.tbc.db`)

### Output Format  
- Export JSON files (`.json`)

# Export JSON Format

The export JSON metadata format is based on the JSON format used by the ld-decode tools before the transition to SQLite. It consists of a root object containing four main sections: `exportMetadata`, `videoParameters`, `pcmAudioParameters` (optional), and `fields` (array). This format is used to store comprehensive metadata about decoded LaserDisc captures and other analog video sources for use in external tools.

## Export JSON Format version history

### 1.0
- Identical to previous internal JSON format, with the exception of the added `exportMetadata` object.

## Root Object Structure

```
json
{
  "exportMetadata": { ... },
  "videoParameters": { ... },
  "pcmAudioParameters": { ... },
  "fields": [ ... ]
}
```

## exportMetadata Object

Contains information about the exported metadata file:

| Field | Type | Description |
|-------|------|-------------|
| `majorVersion` | Integer | Major version of the metadata file format |
| `minorVersion` | Integer | Minor version of the metadata file format |

`minorVersion` will be increased if the change to the format is fully backwards compatible (for example new fields).
Existing tools do not need any modification if they don't plan to use any features provided by the new format version.

`majorVersion` will be increased if the change to the format is not fully backwards compatible (for example removal of non-optional fields).
Existing tools should check if they are affected by the change and may have to be updated for the new format version.
`majorVersion` will only be increased if absolutly neccessary.

## videoParameters Object

Contains capture-level metadata and video system information:

| Field | Type | Description |
|-------|------|-------------|
| `numberOfSequentialFields` | Integer | Total number of fields decoded |
| `system` | String | Video system: "PAL", "NTSC", or "PAL_M" |
| `activeVideoStart` | Integer | Start position (pixels) of active video line |
| `activeVideoEnd` | Integer | End position (pixels) of active video line |
| `colourBurstStart` | Integer | Start position (pixels) of colour burst |
| `colourBurstEnd` | Integer | End position (pixels) of colour burst |
| `white16bIre` | Integer | White level IRE in 16-bit scale |
| `black16bIre` | Integer | Black level IRE in 16-bit scale |
| `fieldWidth` | Integer | Width of each field in pixels |
| `fieldHeight` | Integer | Height of each field in field-lines |
| `sampleRate` | Double | Sample rate in Hz |
| `isMapped` | Boolean | True if video mapped by ld-discmap (optional) |
| `isSubcarrierLocked` | Boolean | True if samples are subcarrier-locked (optional) |
| `isWidescreen` | Boolean | True if 16:9 anamorphic, false if 4:3 (optional) |
| `gitBranch` | String | Git branch of ld-decode used (optional) |
| `gitCommit` | String | Git commit of ld-decode used (optional) |
| `tapeFormat` | String | Tape format description (optional) |

## pcmAudioParameters Object (Optional)

PCM audio configuration when audio data is present:

| Field | Type | Description |
|-------|------|-------------|
| `sampleRate` | Double | Audio sample rate in Hz |
| `isLittleEndian` | Boolean | True for little endian, false for big endian |
| `isSigned` | Boolean | True for signed samples, false for unsigned |
| `bits` | Integer | Bits per sample (e.g., 16) |

## fields Array

Array of field objects, one per video field:

### Field Object

| Field | Type | Description |
|-------|------|-------------|
| `seqNo` | Integer | Unique sequential field number |
| `isFirstField` | Boolean | True for first field, false for second field |
| `syncConf` | Integer | Sync confidence (0=poor, 100=perfect) |
| `medianBurstIRE` | Double | Median colour burst level in IRE (optional) |
| `fieldPhaseID` | Integer | Position in 4-field (NTSC) or 8-field (PAL) sequence |
| `audioSamples` | Integer | Number of audio samples for this field (optional) |
| `diskLoc` | Double | Location in file (fields) (optional) |
| `fileLoc` | Integer | Sample number in file (optional) |
| `decodeFaults` | Integer | Decode fault flags (optional) |
| `efmTValues` | Integer | EFM T-Values in bytes (optional) |
| `pad` | Boolean | True if field is padded (no valid video) (optional) |

### Nested Objects in Fields

#### vitsMetrics Object (Optional)
Vertical Interval Test Signal metrics:

| Field | Type | Description |
|-------|------|-------------|
| `wSNR` | Double | White Signal-to-Noise ratio |
| `bPSNR` | Double | Black line PSNR |

#### vbi Object (Optional) 
Vertical Blanking Interval data:

| Field | Type | Description |
|-------|------|-------------|
| `vbiData` | Integer Array | Raw VBI data from lines 16, 17, 18 (3 elements) |

#### ntsc Object (Optional)
NTSC-specific metadata:

| Field | Type | Description |
|-------|------|-------------|
| `isFmCodeDataValid` | Boolean | True if FM code data is valid |
| `fmCodeData` | Integer | 20-bit FM code data payload |
| `fieldFlag` | Boolean | True for first video field |
| `isVideoIdDataValid` | Boolean | True if VIDEO ID data is valid |
| `videoIdData` | Integer | 14-bit VIDEO ID code data payload |
| `whiteFlag` | Boolean | True if white flag present |

#### vitc Object (Optional)
Vertical Interval Timecode:

| Field | Type | Description |
|-------|------|-------------|
| `vitcData` | Integer Array | 8 values of VITC raw data without framing bits or CRC |

#### cc Object (Optional)
Closed Caption data:

| Field | Type | Description |
|-------|------|-------------|
| `data0` | Integer | First closed caption byte (-1 if invalid) |
| `data1` | Integer | Second closed caption byte (-1 if invalid) |

#### dropOuts Object (Optional)
RF dropout detection data:

| Field | Type | Description |
|-------|------|-------------|
| `startx` | Integer Array | Start pixel positions of dropouts |
| `endx` | Integer Array | End pixel positions of dropouts |
| `fieldLine` | Integer Array | Field lines containing dropouts |

