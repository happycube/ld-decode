# Scripts

## ld-compress

ld-compress is a script to simplify the compression of .lds (raw LaserDisc RF files) into .ldf images.

ld-decode fully supports FLAC compressed files as input.  Files can be suffixed with .ldf as shown here, or .raw.oga.  ld-decode will automatically uncompress the input file during processing.

To compress a .lds file simply use:

```
ld-compress <filename>.lds
```

This script will write a .ldf compressed version of the .lds file to the directory it's called from.

### Encoding

ld-compress encodes with multithreaded [flac](https://xiph.org/flac/){target="_blank"}, which requires flac 1.5.0 or later.  This is the only external program ld-compress uses, and every ld-decode package ships it alongside the ld-compress command, so there is nothing to install separately.  If you are running from a source checkout instead, put a flac 1.5.0 or later on your PATH.

Uncompression (`-u`) and verification (`-v`) need nothing external at all: they decode with PyAV, the same FFmpeg binding ld-decode itself reads .ldf files with, and pack the result with the same code as `ld-lds-converter-py`.

The `-l` compression level ranges from 1 to 8, defaulting to 8 (best compression).

While it works, ld-compress shows a progress bar with the percentage complete, the amount of the input file read, the throughput and an estimated time remaining:

```
disc01.lds [==============>           ]  59% 17.0GiB/28.6GiB 9.5MiB/s ETA 0:21:04
```

The bar is only drawn when ld-compress is run at a terminal, so redirecting its output to a log file keeps the log clean.  Use `-n` to turn it off at a terminal too, or `-p` to force it on when standard error is not a terminal.

### Windows

ld-compress is an ordinary command on Windows, the same as on Linux and macOS - run `bin\ld-compress.bat` from the portable ZIP.  It finds the `bin\flac.exe` that ships beside it without any PATH setup.

Save a file like this as `.bat` to make a drag and drop compressor:

```
@echo off
title Compressing : %~n1
"C:\path\to\ld-decode\bin\ld-compress.bat" "%~1"

pause
```

If you are still using the legacy ld-tools-suite, its
`C:\ld-tools-suite-windows\ld-lds-converter.exe` produces output byte-identical
to the `ld-lds-converter-py` that ships with ld-decode.

### Command List

The full list of command line options is as follows:

```
usage: ld-compress [-h] [-c | -u | -v] [-l 1-8] [-g] [-p | -n] [--version]
                   file [file ...]

ld-compress - compress and uncompress LaserDisc RF captures

positional arguments:
  file                 file(s) to process

options:
  -h, --help           show this help message and exit
  -c, --compress       compress .lds files to .ldf files in the current
                       directory (default)
  -u, --uncompress     uncompress .ldf/.raw.oga files to .lds files in the
                       current directory
  -v, --verify         print md5 checksums of the given .ldf/.raw.oga files
                       and of the .lds data they contain
  -l 1-8, --level 1-8  compression level 1 - 8 (default 8)
  -g, --oga            use the .raw.oga extension instead of .ldf when
                       compressing
  -p, --progress       always show the progress display, even when stderr is
                       not a terminal
  -n, --no-progress    never show the progress display
  --version            show program's version number and exit
```

A progress bar is shown by default when standard error is a terminal.

## ld-cut

ld-cut is a utility for cutting samples from raw RF LaserDisc captures (useful to create samples of trouble-areas when issue reporting), and can now also be used to compress .lds files.  The utility allows you to seek and specify start and end frames similar to the main ld-decode application.

```
usage: ld-cut [-h] [-s start] [-l length] [-S seek] [-E end] [-p] [-n]
              infile outfile

Extract a sample area from raw RF laserdisc captures. (Similar to ld-decode,
except it outputs samples)

positional arguments:
  infile                source file
  outfile               destination file (recommended to use .lds or .ldf suffixes)

optional arguments:
  -h, --help            show this help message and exit
  -s start, --start start
                        rough jump to frame n of capture (default is 0)
  -l length, --length length
                        limit length to n frames
  -S seek, --seek seek  seek to frame n of capture
  -E end, --end end     cutting: last frame
  -p, --pal             source is in PAL format
  -n, --ntsc            source is in NTSC format
```

Using ld-cut, you can do parallel .ldf encodings (optionally targeting different directories) using shell scripting pretty easily:

```
for i in f1.lds f2.lds f3.lds f4.lds; do (ld-cut $i /someotherdirectory/`basename -s .lds $i`.ldf &); done
```

## Measurement harnesses

These live in `scripts/` and are development tools rather than installed commands; they are run from a source checkout inside the development shell. They exist so that a performance claim about the decoder is made in the same units every time — see `plans/decode-performance.md` for the figures they produced and the rules for reading them.

### bench_decode_throughput.py

Runs one measurement *cell* — a (system, mode, thread count, seek, length, capture) tuple — and writes one JSON row per repeat, carrying each decoder's own post-setup frame rate, the aggregate rate over wall time, and the peak resident set of the whole process tree. `--concurrency N` starts N identical decoders over adjacent spans, which is how the "N independent decoders" arm is measured.

```
python3 scripts/bench_decode_throughput.py --capture disc.ldf \
    --system pal --mode cvbs --threads 4 --seek 5000 --length 1000 \
    --repeats 3 --out results.jsonl
```

Every row records the machine it was measured on, including physical core count, per-core L2 and shared L3 size, so rows from different boxes stay distinguishable. Cache capacity per worker is what sets the point where adding threads stops paying, so rows from an unfamiliar machine should be read with those figures in view.

### report_working_set.py

Reports what one decoder keeps resident and what it touches per RF block: every filter array by name and size, the sinc resample look-up table, the bytes `demodblock` actually indexes, its peak transient allocation, and the pocketfft transform plans it needs. The last three are measured by instrumenting one real block rather than being listed by hand.

```
python3 scripts/report_working_set.py --json working_set.json
```

### report_decode_traffic.py

Attributes hardware performance counters to named decoder stages, per thread, so a change that claims a memory effect can name the stage it takes the traffic out of. It reads the counters through `perf_event_open` directly and its default event encodings are AMD Zen 3; on another CPU pass `--events`.

### Block-length override

The demodulator works on blocks of 32,768 samples. Setting `LDDECODE_BLOCKLEN` to another power of two between 4096 and 131072 overrides that, for sweeping the block length against a machine's cache sizes:

```
LDDECODE_BLOCKLEN=16384 python3 -m lddecode.main --pal disc.ldf out
```

This is a developer control, not a decoding option. The block length is a filter-design parameter — every filter is evaluated across that many frequency bins — so a decode at a different length is not comparable byte for byte with one at the default, and output from a sweep should not be kept as a decode. An unusable value is rejected outright rather than falling back to the default, so a mistyped sweep value cannot be measured as though it were the default.

The block length has been swept on the reference box and 32,768 is the measured optimum: 16,384 is inside the run-to-run spread on both systems (+0.2% NTSC, −0.9% PAL) and 8,192 costs 6.6% on PAL for 89 MB of peak resident set. The default is not expected to hold on a machine with a different cache hierarchy, which is what the override is for.

### Parallel-decode developer controls

Three further environment variables report on, or disable, the worker pool's caching. All are off by default, none changes decoded output, and each exists so that a claim about the pool can be checked rather than argued.

```
LDDECODE_BLOCK_LRU_STATS=1     # one line per field job: worker pid, block span, cumulative hits and misses
LDDECODE_SHARED_FILTER_STATS=1 # one line per field job: whether the parent's filter slots reached it
LDDECODE_NO_SHARED_FILTERS=1   # disable the shared filter segment; every worker builds its own bank
```

`LDDECODE_BLOCK_LRU_STATS` is how the block-reuse figures are produced. Adjacent field jobs overlap by design, and pairing each pair of jobs onto one worker lets the second reuse the first's demodulated blocks; the stats lines give the demodulations per distinct block that measures it (1.09 with the pairing, 1.18 without). The block spans on the same lines give the request count, so one run yields both halves of the ratio.

`LDDECODE_NO_SHARED_FILTERS` is the bisect control for the shared filter segment. Sharing changes where the filter bank lives — one read-only mapping per decode rather than one private copy per worker — and never what it contains, so a decode with the segment off must be byte-identical to one with it on. That is what makes it useful: any difference in output with this set is a bug in the sharing, and any difference in *counters* is what the sharing is worth (measured at 3.3% of DRAM fills per frame at `-t 4` and `-t 6`, and nothing in throughput).

Counters for the last of these need `perf` or `report_decode_traffic.py`; resident size will not show them, because the effect is on cache traffic among concurrent workers rather than on how much memory is held.
