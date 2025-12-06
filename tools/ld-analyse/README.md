# ld-analyse

**TBC File Analysis and Visualization GUI**

## Overview

ld-analyse is a graphical user interface (GUI) tool for analyzing and visualizing Time Base Corrected (TBC) LaserDisc video files produced by ld-decode. It provides comprehensive analysis tools for signal quality assessment, dropout detection, VBI metadata viewing, and real-time video preview.

## Usage

### Command Line
```bash
ld-analyse [options] <input.tbc>
```

### GUI Operation

1. **Open File**: File → Open TBC file, or specify on command line
2. **Navigate**: Use media controls to move between frames/fields
   - Previous/Next buttons
   - Slider for quick navigation
   - Frame number entry
   - Start/End buttons to jump to beginning/end
3. **View Options**: Click buttons to toggle
   - Video: Enable/disable video display
   - Aspect: Toggle aspect ratio correction
   - Dropouts: Highlight dropout regions
   - Sources: Compare multiple sources (when available)
   - View: Switch between frame/field/split modes
   - Field Order: Toggle first/second field first
4. **Analysis Tools**: Tools menu
   - Line Scope: Waveform oscilloscope
   - Vectorscope: Color analysis
   - VBI: Metadata display
   - Dropout Analysis: Statistical dropout information
   - SNR Analysis: Signal-to-noise measurements
5. **Save**: File → Save frame as PNG

## Options

#### Common Options
- `-h, --help`: Display help on command-line options
- `-v, --version`: Display version information
- `-d, --debug`: Show debug information
- `-q, --quiet`: Suppress info and warning messages

#### Display Options
- `--force-dark-theme`: Force dark theme regardless of system settings

#### Arguments
- `input`: Input TBC file to analyze (required)
- `-v, --version`: Display version information

## Examples

```bash
# Open TBC file for analysis
ld-analyse capture.tbc
```

## Input/Output

### Input
- `.tbc` files with associated `.tbc.db` metadata
- Supports PAL (625-line, 50 Hz), NTSC (525-line, 60 Hz), and PAL-M (525-line PAL variant)

### Output
- PNG images (frame export)
- Analysis reports and statistics

## Troubleshooting

### Performance Issues
- Toggle chroma decoder off during seeking for faster navigation
- Reduce zoom level if display is slow
- Check that Qt5 GPU acceleration is available

### Analysis Issues
- Use the oscilloscope to verify signal levels and timing
- Check the vectorscope to ensure correct color burst phase
- Monitor dropout analysis to identify disc damage patterns
- Compare SNR across the disc to find optimal playback regions
- Use VBI data to verify frame numbers and chapter markers
