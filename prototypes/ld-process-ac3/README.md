# ld-process-ac3/ld-ac3-*

**AC3 Audio Decoder for LaserDisc RF Signals**

## Overview

ld-process-ac3/ld-ac3-* tools decode AC3 Audio.

## Building

```
mkdir build
cd build
cmake ..
make all
```

## Usage

### Basic Syntax
```bash
ld-ac3-demodulate [options] source_file output_file [log_file]
ld-ac3-decode [options] source_file output_file [log_file]
```

## Options

### ld-ac3-demodulate
This tool does not support `--help`

#### Arguments
- `source_file`: Input RF signal file (use '-' for stdin)
- `output_file`: Output QPSK symbols file (use '-' for stdout)
- `log_file`: Optional log file (defaults to stderr)

### ld-ac3-decode
#### Options
- `-v <int>`: Set the logging level (0-3: DEBUG, INFO, WARN, ERR)
- `-h`: Print help information

#### Arguments
- `source_file`: Input QPSK symbols file (use '-' for stdin)
- `output_file`: Output AC3 audio file (use '-' for stdout)  
- `log_file`: Optional log file (defaults to stderr)
