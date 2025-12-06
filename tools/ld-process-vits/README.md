# ld-process-vits

**Vertical Interval Test Signal (VITS) Processing and Analysis**

## Overview

ld-process-vits analyzes Vertical Interval Test Signals embedded in TBC files. VITS lines contain calibration and test patterns used to assess video signal quality, including multiburst patterns, modulated staircase, and other test waveforms.

## Features

### VITS Signal Analysis
- **Multiburst Detection**: Analyze frequency response test patterns
- **White Flag**: Detect white flag sync reference
- **Signal Metrics**: Measure amplitude, frequency response
- **Quality Assessment**: Evaluate signal integrity

### Measurements
- **Frequency Response**: Analyze multiburst pattern response
- **Amplitude**: Measure white flag and reference levels
- **SNR Contribution**: VITS-based signal quality metrics
- **Linearity**: Assess signal linearity from test patterns

### Processing Options
- **Line Selection**: Process specific VITS lines
- **Range Processing**: Analyze specific frame ranges
- **Statistical Analysis**: Aggregate measurements
- **Export**: Save measurements to file

## Usage

### Basic Syntax
```bash
ld-process-vits [options] <input.tbc>
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

#### Basic VITS Processing
```bash
ld-process-vits input.tbc
```

#### Process with Multiple Threads
```bash
ld-process-vits -t 8 input.tbc
```

#### Don't Create Backup
```bash
ld-process-vits -n input.tbc
```

#### Debug Mode
```bash
ld-process-vits -d input.tbc
```

## VITS Line Locations

### PAL
- **Line 17**: Multiburst, white flag (common)
- **Line 18**: Modulated staircase (some discs)
- **Line 330**: Field 2 test signals (occasional)

### NTSC
- **Line 17-18**: Multiburst, composite test signals
- **Line 280**: Field 2 VITS lines

### Standards
Different LaserDisc standards and manufacturers use different VITS line configurations. ld-process-vits auto-detects common patterns.

## VITS Signal Types

### Multiburst Pattern
- **Purpose**: Frequency response testing
- **Components**: Multiple frequency bursts (0.5-5.8 MHz typical)
- **Analysis**: Amplitude vs frequency
- **Use**: Assess bandwidth and high-frequency response

### White Flag
- **Purpose**: Reference level and sync
- **Components**: White (100 IRE) pulse
- **Analysis**: Amplitude, position, duration
- **Use**: Calibration reference

### Modulated Staircase
- **Purpose**: Linearity and gray scale testing
- **Components**: Step pattern with varying levels
- **Analysis**: Step heights, non-linearity
- **Use**: Assess signal linearity

## Output Format

### Text Summary
```
VITS Analysis Results
=====================
Line: 17
Frames analyzed: 1000

Multiburst Analysis:
  0.5 MHz: 95.2 IRE (100%)
  1.0 MHz: 94.8 IRE (99.6%)
  2.0 MHz: 92.1 IRE (96.7%)
  3.0 MHz: 87.3 IRE (91.7%)
  4.2 MHz: 78.6 IRE (82.5%)
  5.8 MHz: 65.2 IRE (68.4%)

White Flag:
  Average amplitude: 100.2 IRE
  Std deviation: 1.2 IRE
```

### CSV Format
```csv
Frame,Line,Freq_MHz,Amplitude_IRE,Normalized
1,17,0.5,95.2,1.000
1,17,1.0,94.8,0.996
1,17,2.0,92.1,0.967
...
```

## Technical Details

### Input Format
- TBC files with VITS lines preserved
- Associated SQLite metadata
- Supports PAL, NTSC standards

### Processing Algorithm
1. Identify VITS line locations from standard/metadata
2. Extract VITS line data from each field
3. Analyze specific test patterns (multiburst, white flag, etc.)
4. Calculate measurements and statistics
5. Output results in requested format

### Performance
- **Speed**: 200-400 fps (depending on analysis depth)
- **Memory**: Approximately 50MB + frame cache
- **Threading**: Single-threaded

### Measurement Accuracy
- **Frequency**: ±0.01 MHz
- **Amplitude**: ±0.5 IRE
- **Resolution**: Limited by TBC sample rate and quantization

## Quality Interpretation

### Multiburst Response
- **Good**: >90% at 4.2 MHz, >65% at 5.8 MHz
- **Acceptable**: >85% at 4.2 MHz, >55% at 5.8 MHz
- **Poor**: <80% at 4.2 MHz, <45% at 5.8 MHz

### White Flag Stability
- **Excellent**: Std dev <1 IRE
- **Good**: Std dev 1-2 IRE
- **Poor**: Std dev >3 IRE

## Integration Examples

### Python Analysis
```python
import pandas as pd
import matplotlib.pyplot as plt

# Load VITS measurements
with open('vits.sqlite', 'r') as f:
    data = pd.read_csv(f)

# Plot frequency response
freqs = [b['frequency'] for b in data['multiburst']]
amps = [b['normalized'] * 100 for b in data['multiburst']]

plt.plot(freqs, amps, 'o-')
plt.xlabel('Frequency (MHz)')
plt.ylabel('Response (%)')
plt.title('Frequency Response from VITS')
plt.grid(True)
plt.savefig('frequency_response.png')
```

### Compare Multiple Captures
```bash
# Analyze capture 1
ld-process-vits --multiburst --output cap1.csv --format csv capture1.tbc

# Analyze capture 2
ld-process-vits --multiburst --output cap2.csv --format csv capture2.tbc

# Compare in spreadsheet or with tools
```

## Limitations

- **Line Availability**: Not all discs have VITS lines
- **Variation**: VITS format varies by disc manufacturer
- **Analog Only**: Digital video signals don't have VITS
- **Degradation**: Worn discs may have damaged VITS data

## Troubleshooting

### Issues

**No VITS detected:**
- Not all LaserDiscs include VITS lines
- Try different line numbers with --vits-lines
- Inspect TBC visually with ld-analyse
- Check disc documentation for VITS presence

**Inconsistent measurements:**
- Normal for varying signal quality across disc
- Use --statistics to see trends
- Consider analyzing larger frame ranges

**Invalid/missing data:**
- VITS lines may be damaged on worn discs
- RF signal quality may be insufficient
- Try recapturing with better equipment/settings

**Unexpected results:**
- Different disc manufacturers use different VITS formats
- Some patterns may not be recognized
- May need manual analysis of VITS lines


