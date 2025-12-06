# ld-chroma-decoder

**Color Decoder for Time Base Corrected LaserDisc Video**

## Overview

ld-chroma-decoder decodes color (chroma) information from Time Base Corrected (TBC) LaserDisc video files, converting them into standard RGB video suitable for playback and editing. It supports multiple decoding algorithms optimized for PAL and NTSC video systems.

## Usage

### Basic Syntax
```bash
ld-chroma-decoder [options] <input.tbc> <output.rgb>
```

## Options

#### Common Options
- `-h, --help`: Display help on command-line options
- `-v, --version`: Display version information
- `-d, --debug`: Show debug information
- `-q, --quiet`: Suppress info and warning messages

#### Input/Output
- `--input-metadata <filename>`: Specify the input metadata file (default input.db)
- `-s, --start <number>`: Specify the start frame number
- `-l, --length <number>`: Specify the length (number of frames to process)
- `-t, --threads <number>`: Specify the number of concurrent threads (default number of logical CPUs)

#### Decoder Selection
- `-f, --decoder <decoder>`: Decoder to use (pal2d, transform2d, transform3d, ntsc1d, ntsc2d, ntsc3d, ntsc3dnoadapt, mono; default automatic)

#### Output Control
- `-p, --output-format <format>`: Output format (rgb, yuv, y4m; default rgb); RGB48, YUV444P16, GRAY16 pixel formats are supported
- `-r, --reverse`: Reverse the field order to second/first (default first/second)
- `-b, --blackandwhite`: Output in black and white
- `--pad, --output-padding <number>`: Pad the output frame to a multiple of this many pixels on both axes (1 means no padding, maximum is 32)

#### Color Adjustment
- `--chroma-gain <number>`: Gain factor applied to chroma components (default 1.0)
- `--chroma-phase <number>`: Phase rotation applied to chroma components (degrees; default 0.0)

#### Video Area Control
- `--ffll, --first_active_field_line <number>`: The first visible line of a field. Range 1-259 for NTSC (default: 20), 2-308 for PAL (default: 22)
- `--lfll, --last_active_field_line <number>`: The last visible line of a field. Range 1-259 for NTSC (default: 259), 2-308 for PAL (default: 308)
- `--ffrl, --first_active_frame_line <number>`: The first visible line of a frame. Range 1-525 for NTSC (default: 40), 1-620 for PAL (default: 44)
- `--lfrl, --last_active_frame_line <number>`: The last visible line of a frame. Range 1-525 for NTSC (default: 525), 1-620 for PAL (default: 620)

#### NTSC-Specific Options
- `-o, --oftest`: NTSC: Overlay the adaptive filter map (only used for testing)
- `--chroma-nr <number>`: NTSC: Chroma noise reduction level in dB (default 0.0)
- `--luma-nr <number>`: Luma noise reduction level in dB (default 0.0)
- `--ntsc-phase-comp`: NTSC: Adjust phase per-line using burst phase

#### Transform Decoder Options
- `--simple-pal`: Transform: Use 1D UV filter (default 2D)
- `--transform-threshold <number>`: Transform: Uniform similarity threshold (default 0.4)
- `--transform-thresholds <file>`: Transform: File containing per-bin similarity thresholds
- `--show-ffts`: Transform: Overlay the input and output FFTs
- `--input-metadata <filename>`: Specify the input metadata file (default input.db)

#### Active Area Selection
- `--ffll, --first_active_field_line <number>`: The first visible line of a field
- `--lfll, --last_active_field_line <number>`: The last visible line of a field  
- `--ffrl, --first_active_frame_line <number>`: The first visible line of a frame
- `--lfrl, --last_active_frame_line <number>`: The last visible line of a frame

#### Chroma Processing
- `--chroma-gain <number>`: Gain factor applied to chroma components (default 1.0)
- `--chroma-phase <number>`: Phase rotation applied to chroma components
- `--chroma-nr <number>`: NTSC: Chroma noise reduction
- `--luma-nr <number>`: Luma noise reduction level in dB

#### NTSC Specific
- `-o, --oftest`: NTSC: Overlay the adaptive filter
- `--ntsc-phase-comp`: NTSC: Adjust phase per-line using pilot burst

#### Transform Decoder
- `--simple-pal`: Transform: Use 1D UV filter  
- `--transform-threshold <number>`: Transform: Uniform similarity threshold
- `--transform-thresholds <file>`: Transform: File containing per-line thresholds
- `--show-ffts`: Transform: Overlay the input and output spectra

#### Standard Options
- `-d, --debug`: Show debug messages
- `-q, --quiet`: Suppress info and warning messages

## Examples

```bash
# PAL LaserDisc (Transform Decoder)
ld-chroma-decoder -p transform input.tbc output.rgb

# NTSC LaserDisc (3D Decoder)
ld-chroma-decoder -n 3D input.tbc output.rgb

# Grayscale Output
ld-chroma-decoder -p mono input.tbc output.rgb

# Process Specific Range
ld-chroma-decoder -p transform -s 1000 -l 500 input.tbc output.rgb

# With Chroma Adjustments
ld-chroma-decoder -p transform --chroma-gain 1.2 --chroma-phase -2.0 input.tbc output.rgb
```

## Input/Output

### Input Format
- TBC files: 16-bit unsigned composite video
- Metadata: SQLite format
- Standards: PAL (625-line), NTSC (525-line), PAL-M (525-line PAL)

### Output Format
- RGB: 16-bit per channel, interlaced or progressive
- Dimensions: Automatically determined from TBC metadata
- Frame rate: Original field rate (50/60 Hz) or frame rate (25/30 Hz)

## Troubleshooting

### Color Issues
- **Wrong colors**: Check chroma phase setting
- **Weak saturation**: Increase chroma gain
- **Color noise**: Try different decoder (Transform recommended for PAL)
- **Vertical color smearing**: Use 3D or Transform decoder

### Performance Issues
- **Slow processing**: Reduce thread count or use simpler decoder
- **High memory usage**: Process in smaller batches with -l option
