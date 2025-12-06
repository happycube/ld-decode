# ld-json-converter

**JSON to SQLite Metadata Converter**

## Overview

ld-json-converter converts TBC JSON metadata files into a relational SQLite database for easier querying and analysis.

**⚠️ Important**: The SQLite metadata format is **internal to ld-decode tools only** and subject to change without notice. External tools and scripts should **not** access this database directly. Instead, use `ld-export-metadata` or similar tools to export metadata in stable, documented formats.

## Usage

### Basic Syntax
```bash
ld-json-converter [options]
```

## Options

#### Common Options
- `-h, --help`: Display help on command-line options
- `-v, --version`: Display version information
- `-d, --debug`: Show debug information
- `-q, --quiet`: Suppress info and warning messages

#### Input/Output
- `--input-json <filename>`: Specify the input JSON file
- `--output-sqlite <filename>`: Specify the output SQLite file (default same as input but with .db extension)

#### Standard Options
- `-d, --debug`: Show debug messages
- `-q, --quiet`: Suppress info and warning messages
- `-h, --help`: Display help information
- `-v, --version`: Display version information

## Input/Output

### Input Format
- TBC JSON metadata files (`.tbc.json`)

### Output Format  
- SQLite database files (`.tbc.db`)

## SQLite Schema

```sql
------------------------------------------------------------------
-- Schema Versioning
------------------------------------------------------------------
PRAGMA user_version = 1;

------------------------------------------------------------------
-- 1. Capture-level metadata (one per JSON file)
------------------------------------------------------------------
CREATE TABLE capture (
    capture_id INTEGER PRIMARY KEY,
    system TEXT NOT NULL
        CHECK (system IN ('NTSC','PAL','PAL_M')),
    decoder TEXT NOT NULL
        CHECK (decoder IN ('ld-decode','vhs-decode')),
    git_branch TEXT,
    git_commit TEXT,

    video_sample_rate REAL,
    active_video_start INTEGER,
    active_video_end INTEGER,
    field_width INTEGER,
    field_height INTEGER,
    number_of_sequential_fields INTEGER,

    colour_burst_start INTEGER,
    colour_burst_end INTEGER,
    is_mapped INTEGER
        CHECK (is_mapped IN (0,1)),
    is_subcarrier_locked INTEGER
        CHECK (is_subcarrier_locked IN (0,1)),
    is_widescreen INTEGER
        CHECK (is_widescreen IN (0,1)),
    white_16b_ire INTEGER,
    black_16b_ire INTEGER,

    capture_notes TEXT -- was JSON tape_format
);

------------------------------------------------------------------
-- 2. PCM Audio Parameters (one per capture)
------------------------------------------------------------------
CREATE TABLE pcm_audio_parameters (
    capture_id INTEGER PRIMARY KEY
        REFERENCES capture(capture_id) ON DELETE CASCADE,
    bits INTEGER,
    is_signed INTEGER
        CHECK (is_signed IN (0,1)),
    is_little_endian INTEGER
        CHECK (is_little_endian IN (0,1)),
    sample_rate REAL
);

------------------------------------------------------------------
-- 3. Field metadata
------------------------------------------------------------------
CREATE TABLE field_record (
    capture_id INTEGER NOT NULL
        REFERENCES capture(capture_id) ON DELETE CASCADE,
    -- Note: Original JSON seqNo was indexed from 1, the field_id
    -- will be the original seqNo - 1 to zero-index the ID
    field_id INTEGER NOT NULL,
    audio_samples INTEGER,
    decode_faults INTEGER,
    disk_loc REAL,
    efm_t_values INTEGER,
    field_phase_id INTEGER,
    file_loc INTEGER,
    is_first_field INTEGER
        CHECK (is_first_field IN (0,1)),
    median_burst_ire REAL,
    pad INTEGER
        CHECK (pad IN (0,1)),
    sync_conf INTEGER,

    -- NTSC specific fields (NULL for other formats)
    ntsc_is_fm_code_data_valid INTEGER
        CHECK (ntsc_is_fm_code_data_valid IN (0,1)),
    ntsc_fm_code_data INTEGER,
    ntsc_field_flag INTEGER
        CHECK (ntsc_field_flag IN (0,1)),
    ntsc_is_video_id_data_valid INTEGER
        CHECK (ntsc_is_video_id_data_valid IN (0,1)),
    ntsc_video_id_data INTEGER,
    ntsc_white_flag INTEGER
        CHECK (ntsc_white_flag IN (0,1)),

    PRIMARY KEY (capture_id, field_id)
);

------------------------------------------------------------------
-- 4. VITS metrics (optional) - one per field
------------------------------------------------------------------
CREATE TABLE vits_metrics (
    capture_id INTEGER NOT NULL,
    field_id INTEGER NOT NULL,
    b_psnr REAL,
    w_snr REAL,
    FOREIGN KEY (capture_id, field_id)
        REFERENCES field_record(capture_id, field_id)
        ON DELETE CASCADE,
    PRIMARY KEY (capture_id, field_id)
);

------------------------------------------------------------------
-- 5. VBI data (optional) - stores 3 VBI data values per field
------------------------------------------------------------------
CREATE TABLE vbi (
    capture_id INTEGER NOT NULL,
    field_id INTEGER NOT NULL,
    vbi0 INTEGER NOT NULL, -- VBI line 16 data
    vbi1 INTEGER NOT NULL, -- VBI line 17 data  
    vbi2 INTEGER NOT NULL, -- VBI line 18 data
    FOREIGN KEY (capture_id, field_id)
        REFERENCES field_record(capture_id, field_id)
        ON DELETE CASCADE,
    PRIMARY KEY (capture_id, field_id)
);

------------------------------------------------------------------
-- 6. Drop-out elements (optional)
------------------------------------------------------------------
CREATE TABLE drop_outs (
    capture_id INTEGER NOT NULL,
    field_id INTEGER NOT NULL, 
    field_line INTEGER NOT NULL,
    startx INTEGER NOT NULL,
    endx INTEGER NOT NULL,
    PRIMARY KEY (capture_id, field_id, field_line, startx, endx),
    FOREIGN KEY (capture_id, field_id)
        REFERENCES field_record(capture_id, field_id)
        ON DELETE CASCADE
);

------------------------------------------------------------------
-- 7. VITC data (optional) - stores 8 VITC data values per field
------------------------------------------------------------------
CREATE TABLE vitc (
    capture_id INTEGER NOT NULL,
    field_id INTEGER NOT NULL,
    vitc0 INTEGER NOT NULL, -- VITC data element 0
    vitc1 INTEGER NOT NULL, -- VITC data element 1
    vitc2 INTEGER NOT NULL, -- VITC data element 2
    vitc3 INTEGER NOT NULL, -- VITC data element 3
    vitc4 INTEGER NOT NULL, -- VITC data element 4
    vitc5 INTEGER NOT NULL, -- VITC data element 5
    vitc6 INTEGER NOT NULL, -- VITC data element 6
    vitc7 INTEGER NOT NULL, -- VITC data element 7
    FOREIGN KEY (capture_id, field_id)
        REFERENCES field_record(capture_id, field_id)
        ON DELETE CASCADE,
    PRIMARY KEY (capture_id, field_id)
);

------------------------------------------------------------------
-- 8. Closed Caption data (optional) - one per field
------------------------------------------------------------------
CREATE TABLE closed_caption (
    capture_id INTEGER NOT NULL,
    field_id INTEGER NOT NULL,
    data0 INTEGER, -- First closed caption byte (-1 if invalid)
    data1 INTEGER, -- Second closed caption byte (-1 if invalid)
    FOREIGN KEY (capture_id, field_id)
        REFERENCES field_record(capture_id, field_id)
        ON DELETE CASCADE,
    PRIMARY KEY (capture_id, field_id)
);
```

# JSON Format

The ld-decode JSON metadata format consists of a root object containing three main sections: `videoParameters`, `pcmAudioParameters` (optional), and `fields` (array). This format is used to store comprehensive metadata about decoded LaserDisc captures and other analog video sources.

Note: This analysis is based on examining the code (as the documentation on the wiki has not been kept up to date).

## Root Object Structure

```
json
{
  "videoParameters": { ... },
  "pcmAudioParameters": { ... },
  "fields": [ ... ]
}
```

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
| `isMapped` | Boolean | True if video mapped by ld-discmap |
| `isSubcarrierLocked` | Boolean | True if samples are subcarrier-locked |
| `isWidescreen` | Boolean | True if 16:9 anamorphic, false if 4:3 |
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
| `medianBurstIRE` | Double | Median colour burst level in IRE |
| `fieldPhaseID` | Integer | Position in 4-field (NTSC) or 8-field (PAL) sequence |
| `audioSamples` | Integer | Number of audio samples for this field (optional) |
| `diskLoc` | Double | Location in file (fields) (optional) |
| `fileLoc` | Integer | Sample number in file (optional) |
| `decodeFaults` | Integer | Decode fault flags (optional) |
| `efmTValues` | Integer | EFM T-Values in bytes (optional) |
| `pad` | Boolean | True if field is padded (no valid video) |

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

## Differences from old Wiki Documentation

Based on code analysis, the following differences exist between the current implementation and the [wiki documentation](https://github.com/happycube/ld-decode/wiki/JSON-metadata-format):

1. **Closed Caption Object**: The code uses `cc` with `data0`/`data1` fields, while the wiki shows `ccData0`/`ccData1` directly in the field object.

2. **Missing Wiki Fields**: Several fields documented in the wiki are not present in the current code implementation:
   - `blackLevelStart`/`blackLevelEnd` in videoParameters 
   - Extended VITS metrics fields (only basic `wSNR`/`bPSNR` implemented)
   - VBI `vp` array (removed in current version, only `vbiData` remains)

3. **Additional Code Fields**: The code includes some fields not in the wiki:
   - `tapeFormat` in videoParameters (storing format description)
   - Various conditional fields that are only written when valid

4. **Field Numbering**: The code uses 1-based indexing for sequential field numbers as documented.

This JSON format serves as the interchange format between all ld-decode tools and provides comprehensive metadata for video processing workflows.

# JSON to SQLite Schema Mapping

This section documents how JSON metadata elements map to the SQLite database schema.

## Root Level Mapping

| JSON Path | SQLite Table | SQLite Field | Notes |
|-----------|--------------|--------------|--------|
| `videoParameters` | `capture` | Various fields | See videoParameters mapping below |
| `pcmAudioParameters` | `pcm_audio_parameters` | Various fields | See pcmAudioParameters mapping below |
| `fields[]` | `field_record` + related tables | Various fields | See fields mapping below |

## videoParameters Mapping

| JSON Field | SQLite Table | SQLite Field | Transformation |
|------------|--------------|--------------|----------------|
| `numberOfSequentialFields` | `capture` | `number_of_sequential_fields` | Direct copy |
| `system` | `capture` | `system` | Direct copy |
| `activeVideoStart` | `capture` | `active_video_start` | Direct copy |
| `activeVideoEnd` | `capture` | `active_video_end` | Direct copy |
| `colourBurstStart` | `capture` | `colour_burst_start` | Direct copy |
| `colourBurstEnd` | `capture` | `colour_burst_end` | Direct copy |
| `white16bIre` | `capture` | `white_16b_ire` | Direct copy |
| `black16bIre` | `capture` | `black_16b_ire` | Direct copy |
| `fieldWidth` | `capture` | `field_width` | Direct copy |
| `fieldHeight` | `capture` | `field_height` | Direct copy |
| `sampleRate` | `capture` | `video_sample_rate` | Direct copy |
| `isMapped` | `capture` | `is_mapped` | Boolean → Integer (0/1) |
| `isSubcarrierLocked` | `capture` | `is_subcarrier_locked` | Boolean → Integer (0/1) |
| `isWidescreen` | `capture` | `is_widescreen` | Boolean → Integer (0/1) |
| `gitBranch` | `capture` | `git_branch` | Direct copy (optional) |
| `gitCommit` | `capture` | `git_commit` | Direct copy (optional) |
| `tapeFormat` | `capture` | `capture_notes` | Direct copy (optional) |
| N/A | `capture` | `decoder` | **SQL-only field** - set during conversion |

## pcmAudioParameters Mapping

| JSON Field | SQLite Table | SQLite Field | Transformation |
|------------|--------------|--------------|----------------|
| `sampleRate` | `pcm_audio_parameters` | `sample_rate` | Direct copy |
| `isLittleEndian` | `pcm_audio_parameters` | `is_little_endian` | Boolean → Integer (0/1) |
| `isSigned` | `pcm_audio_parameters` | `is_signed` | Boolean → Integer (0/1) |
| `bits` | `pcm_audio_parameters` | `bits` | Direct copy |

## fields[] Array Mapping

### Main Field Record

| JSON Field | SQLite Table | SQLite Field | Transformation |
|------------|--------------|--------------|----------------|
| `seqNo` | `field_record` | `field_id` | field_id will be seqNo - 1 |
| `isFirstField` | `field_record` | `is_first_field` | Boolean → Integer (0/1) |
| `syncConf` | `field_record` | `sync_conf` | Direct copy |
| `medianBurstIRE` | `field_record` | `median_burst_ire` | Direct copy |
| `fieldPhaseID` | `field_record` | `field_phase_id` | Direct copy |
| `audioSamples` | `field_record` | `audio_samples` | Direct copy (optional) |
| `diskLoc` | `field_record` | `disk_loc` | Direct copy (optional) |
| `fileLoc` | `field_record` | `file_loc` | Direct copy (optional) |
| `decodeFaults` | `field_record` | `decode_faults` | Direct copy (optional) |
| `efmTValues` | `field_record` | `efm_t_values` | Direct copy (optional) |
| `pad` | `field_record` | `pad` | Boolean → Integer (0/1) |

### NTSC Object Mapping (fields[].ntsc)

| JSON Field | SQLite Table | SQLite Field | Transformation |
|------------|--------------|--------------|----------------|
| `isFmCodeDataValid` | `field_record` | `ntsc_is_fm_code_data_valid` | Boolean → Integer (0/1) |
| `fmCodeData` | `field_record` | `ntsc_fm_code_data` | Direct copy |
| `fieldFlag` | `field_record` | `ntsc_field_flag` | Boolean → Integer (0/1) |
| `isVideoIdDataValid` | `field_record` | `ntsc_is_video_id_data_valid` | Boolean → Integer (0/1) |
| `videoIdData` | `field_record` | `ntsc_video_id_data` | Direct copy |
| `whiteFlag` | `field_record` | `ntsc_white_flag` | Boolean → Integer (0/1) |

### Nested Object Mappings

#### vitsMetrics Object (fields[].vitsMetrics)

| JSON Field | SQLite Table | SQLite Field | Transformation |
|------------|--------------|--------------|----------------|
| `wSNR` | `vits_metrics` | `w_snr` | Direct copy |
| `bPSNR` | `vits_metrics` | `b_psnr` | Direct copy |

#### VBI Array (fields[].vbi.vbiData[])

| JSON Array Element | SQLite Table | SQLite Field | Transformation |
|-------------------|--------------|--------------|----------------|
| `vbiData[0]` | `vbi` | `vbi0` | Array element → column |
| `vbiData[1]` | `vbi` | `vbi1` | Array element → column |
| `vbiData[2]` | `vbi` | `vbi2` | Array element → column |

#### VITC Array (fields[].vitc.vitcData[])

| JSON Array Element | SQLite Table | SQLite Field | Transformation |
|-------------------|--------------|--------------|----------------|
| `vitcData[0]` | `vitc` | `vitc0` | Array element → column |
| `vitcData[1]` | `vitc` | `vitc1` | Array element → column |
| `vitcData[2]` | `vitc` | `vitc2` | Array element → column |
| `vitcData[3]` | `vitc` | `vitc3` | Array element → column |
| `vitcData[4]` | `vitc` | `vitc4` | Array element → column |
| `vitcData[5]` | `vitc` | `vitc5` | Array element → column |
| `vitcData[6]` | `vitc` | `vitc6` | Array element → column |
| `vitcData[7]` | `vitc` | `vitc7` | Array element → column |

#### Closed Caption Object (fields[].cc)

| JSON Field | SQLite Table | SQLite Field | Transformation |
|------------|--------------|--------------|----------------|
| `data0` | `closed_caption` | `data0` | Direct copy |
| `data1` | `closed_caption` | `data1` | Direct copy |

#### Dropouts Arrays (fields[].dropOuts)

| JSON Array Elements | SQLite Table | SQLite Field | Transformation |
|--------------------|--------------|--------------|----------------|
| `startx[i]`, `endx[i]`, `fieldLine[i]` | `drop_outs` | `startx`, `endx`, `field_line` | Array elements → separate rows with matching indices |

## Key Transformation Notes

1. **Boolean to Integer**: All JSON boolean values are converted to SQLite integers (0 for false, 1 for true)
2. **Array Flattening**: JSON arrays are flattened into separate table rows with index fields, except for VBI and VITC arrays which are stored as separate columns
3. **VBI/VITC Arrays**: VBI and VITC data arrays are stored as individual columns (vbi0-vbi2, vitc0-vitc7) for improved query performance
3. **Optional Fields**: Fields that may not exist in JSON are stored as NULL in SQLite
4. **Primary Keys**: SQLite uses `capture_id` (auto-generated) and `field_id` (from JSON `seqNo`) as primary keys
5. **Foreign Keys**: All field-related tables reference `field_record(capture_id, field_id)`
6. **New Fields**: The `decoder` field is SQL-only and must be set during conversion process
7. **Index from 0**: One will be subtracted from the JSON seqNo to ensure that field_id is zero-indexed


