# ld-process-ac3

**AC3 Audio Decoder for LaserDisc RF Signals**

## Overview

ld-process-ac3 decodes AC3 Audio from RF signals captured by ld-decode. The first executable, ld-ac3-demodulate, takes a stream of unsigned 8-bit samples at 46.08MHz to produce a stream of QPSK symbols. The second executable, ld-ac3-decode, decodes the stream of symbols into playable AC3 audio frames while producing Reed-solomon, CRC and other statistics.

## Usage

### Basic Syntax
```bash
ld-ac3-demodulate [options] source_file output_file [log_file]
ld-ac3-decode [options] source_file output_file [log_file]
```

## Options

### ld-ac3-demodulate
This tool does not support `--help` but uses a simplified interface.

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

## Examples

### Complete Processing Pipeline
```bash
# Format, resample and filter the source signal
ffmpeg -hide_banner -y -i "$path" -f s16le -c:a pcm_s16le TP0
sox -r 40000000 -b 16 -c 1 -e signed -t raw TP0 -b 8 -r 46080000 -e unsigned -c 1 -t raw TP1 sinc -n 500 2600000-3160000

# Demodulate and decode AC3 audio
ld-ac3-demodulate TP1 TP2 demodulate_log
ld-ac3-decode TP2 "$outpath" decode_log
```

The TP0, TP1 and TP2 files are intermediate files used for caching and are not needed when piping directly between commands.

## Input/Output

