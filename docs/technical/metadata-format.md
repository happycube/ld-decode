# SQLite Metadata Format

In order for all tools in the ld-decode tool-chain to communicate metadata about video and non-video capture content, the tools use an SQLite database to store and process information.

Please note that this metadata format is *internal* to the ld-decode project and should not be used by external tools (as the metadata format is subject to change without notice).

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
    blanking_16b_ire INTEGER,

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

## Field Descriptions

This section provides detailed descriptions of each field in the SQLite schema tables.

### Table: capture

Contains capture-level metadata (one record per capture/JSON file).

| Field | Type | Description |
|-------|------|-------------|
| `capture_id` | INTEGER | Primary key identifier for the capture |
| `system` | TEXT | Video system in use: `"PAL"`, `"NTSC"`, or `"PAL_M"`. PAL is standard 625-line PAL, NTSC is standard 525-line NTSC (as used on LaserDisc), and PAL_M is the 525-line PAL system used in Brazil |
| `decoder` | TEXT | The decoder used: `"ld-decode"` or `"vhs-decode"` |
| `git_branch` | TEXT | The git branch ID of the decoder used to decode the TBC (optional) |
| `git_commit` | TEXT | The git commit ID of the decoder used to decode the TBC (optional) |
| `video_sample_rate` | REAL | The sample rate in Hz (usually 4 × fSC for ld-decode) |
| `active_video_start` | INTEGER | Position (in pixels) of the start of the active video line |
| `active_video_end` | INTEGER | Position (in pixels) of the end of the active video line |
| `field_width` | INTEGER | The width of each field in pixels |
| `field_height` | INTEGER | The height of each field in field-lines (represents the taller of the two video fields; the shorter field is padded to match) |
| `number_of_sequential_fields` | INTEGER | The total number of fields decoded |
| `colour_burst_start` | INTEGER | Position (in pixels) of the colour-burst start |
| `colour_burst_end` | INTEGER | Position (in pixels) of the colour-burst end |
| `is_mapped` | INTEGER | Boolean: 1 if the video has been mapped by ld-discmap, 0 otherwise |
| `is_subcarrier_locked` | INTEGER | Boolean: 1 if samples are subcarrier-locked (aligned to colour subcarrier rather than line-locked), 0 otherwise |
| `is_widescreen` | INTEGER | Boolean: 1 if the video is 16:9 anamorphic, 0 if 4:3 |
| `white_16b_ire` | INTEGER | The white level IRE in a 16-bit scale |
| `black_16b_ire` | INTEGER | The black level IRE in a 16-bit scale |
| `blanking_16b_ire` | INTEGER | The blanking level IRE in a 16-bit scale |
| `capture_notes` | TEXT | Notes about the capture (was JSON `tapeFormat` field describing tape media format like VHS, Betamax, Video8) |

### Table: pcm_audio_parameters

PCM audio configuration when audio data is present (one record per capture).

| Field | Type | Description |
|-------|------|-------------|
| `capture_id` | INTEGER | Foreign key referencing `capture.capture_id` |
| `bits` | INTEGER | The number of bits used per sample (e.g., 16) |
| `is_signed` | INTEGER | Boolean: 1 if sample data is signed, 0 if unsigned |
| `is_little_endian` | INTEGER | Boolean: 1 if sample is little endian, 0 if big endian |
| `sample_rate` | REAL | The audio sample rate in Hz |

### Table: field_record

Field-level metadata (one record per video field).

| Field | Type | Description |
|-------|------|-------------|
| `capture_id` | INTEGER | Foreign key referencing `capture.capture_id` |
| `field_id` | INTEGER | Zero-indexed unique sequential field number (original JSON `seqNo` was 1-indexed; this is `seqNo - 1`) |
| `audio_samples` | INTEGER | The number of (stereo, signed 16-bit) audio samples corresponding to the video field |
| `decode_faults` | INTEGER | Bit flags for decode faults: bit 1 = first-field detection failure, bit 2 = field phase ID mismatch, bit 3 = skipped field (likely a player skip) |
| `disk_loc` | REAL | The location in the file (in fields) where the field is located |
| `efm_t_values` | INTEGER | The number of .efm T-Values (in bytes) corresponding to the video field |
| `field_phase_id` | INTEGER | The position of this field in the 4-field (NTSC) or 8-field (PAL) sequence |
| `file_loc` | INTEGER | The sample number in the file where the field is located |
| `is_first_field` | INTEGER | Boolean: 1 if first field, 0 if second field |
| `median_burst_ire` | REAL | The median point of the colour burst (in IRE) |
| `pad` | INTEGER | Boolean: 1 if field is padded (contains no valid video data), 0 if normal field |
| `sync_conf` | INTEGER | Sync confidence: 0 = poor, 100 = perfect (percentage confidence of the sync point determination) |
| `ntsc_is_fm_code_data_valid` | INTEGER | Boolean (NTSC only): 1 if FM code data is valid, 0 if invalid, NULL for non-NTSC |
| `ntsc_fm_code_data` | INTEGER | The 20-bit FM code data payload (X5 to X1) (NTSC only, NULL for non-NTSC) |
| `ntsc_field_flag` | INTEGER | Boolean (NTSC only): 1 if first video field, 0 if not first video field, NULL for non-NTSC |
| `ntsc_is_video_id_data_valid` | INTEGER | Boolean (NTSC only): 1 if VIDEO ID data is valid, 0 if invalid, NULL for non-NTSC |
| `ntsc_video_id_data` | INTEGER | The 14-bit VIDEO ID code data payload (IEC 61880) (NTSC only, NULL for non-NTSC) |
| `ntsc_white_flag` | INTEGER | Boolean (NTSC only): 1 if white flag present, 0 if not present, NULL for non-NTSC |

### Table: vits_metrics

Video Insert Test Signal metrics (optional, one record per field when available).

| Field | Type | Description |
|-------|------|-------------|
| `capture_id` | INTEGER | Foreign key referencing `field_record.capture_id` |
| `field_id` | INTEGER | Foreign key referencing `field_record.field_id` |
| `b_psnr` | REAL | Black line PSNR (not conventional SNR) |
| `w_snr` | REAL | The Signal to Noise ratio of a white (100 IRE) area of the field |

### Table: vbi

Vertical Blanking Interval data (optional, one record per field when available).

| Field | Type | Description |
|-------|------|-------------|
| `capture_id` | INTEGER | Foreign key referencing `field_record.capture_id` |
| `field_id` | INTEGER | Foreign key referencing `field_record.field_id` |
| `vbi0` | INTEGER | VBI line 16 raw data (see IEC 60857-1986 and IEC 60856-1986 for details) |
| `vbi1` | INTEGER | VBI line 17 raw data |
| `vbi2` | INTEGER | VBI line 18 raw data |

### Table: drop_outs

RF dropout detection data (optional, multiple records per field possible).

| Field | Type | Description |
|-------|------|-------------|
| `capture_id` | INTEGER | Foreign key referencing `field_record.capture_id` |
| `field_id` | INTEGER | Foreign key referencing `field_record.field_id` |
| `field_line` | INTEGER | Field line number on which the dropout occurs |
| `startx` | INTEGER | Start pixel position of the detected dropout |
| `endx` | INTEGER | End pixel position of the detected dropout |

### Table: vitc

Vertical Interval Timecode data (optional, one record per field when available).

| Field | Type | Description |
|-------|------|-------------|
| `capture_id` | INTEGER | Foreign key referencing `field_record.capture_id` |
| `field_id` | INTEGER | Foreign key referencing `field_record.field_id` |
| `vitc0` | INTEGER | VITC data element 0 (8 bits of raw VITC data without framing bits or CRC) |
| `vitc1` | INTEGER | VITC data element 1 (8 bits of raw VITC data) |
| `vitc2` | INTEGER | VITC data element 2 (8 bits of raw VITC data) |
| `vitc3` | INTEGER | VITC data element 3 (8 bits of raw VITC data) |
| `vitc4` | INTEGER | VITC data element 4 (8 bits of raw VITC data) |
| `vitc5` | INTEGER | VITC data element 5 (8 bits of raw VITC data) |
| `vitc6` | INTEGER | VITC data element 6 (8 bits of raw VITC data) |
| `vitc7` | INTEGER | VITC data element 7 (8 bits of raw VITC data) |

**Note:** Each value represents 8 bits of the raw VITC data. The LSB of `vitc0` is VITC bit 2 (the LSB of the frame number), and the MSB of `vitc7` is VITC bit 79.

### Table: closed_caption

Closed Caption data (optional, one record per field when available).

| Field | Type | Description |
|-------|------|-------------|
| `capture_id` | INTEGER | Foreign key referencing `field_record.capture_id` |
| `field_id` | INTEGER | Foreign key referencing `field_record.field_id` |
| `data0` | INTEGER | First closed caption byte (-1 if invalid, 0 indicates CC is present but no data is being transferred) |
| `data1` | INTEGER | Second closed caption byte (-1 if invalid, 0 indicates CC is present but no data is being transferred) |

**Note:** See ANSI/CTA-608 for details on closed caption data format.

