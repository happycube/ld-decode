# Documentation

> [!Important]
> If in doubt read the comprehensive [documentation web-site](https://happycube.github.io/ld-decode/)!

You can find the documentation here: [ld-decode documentation](https://happycube.github.io/ld-decode/)

Check the documentation first, the [discord server](https://discord.com/invite/pVVrrxd) second and then raise issues.

# What is ld-decode?

**ld-decode** is a software-defined decoder for LaserDisc RF captures made using modified LaserDisc players and capture devices such as the [DomesdayDuplicator](https://github.com/simoninns/DomesdayDuplicator)

ld-decode recovers video, analog audio, digital audio and metadata content from RAW PCM format (or FLAC compressed) RF samples captured directly from LaserDisc players, bypassing the analog signal chain to achieve preservation-quality digital transfers.

Although ld-decode was originally dedicated to LaserDiscs it has become part of a larger ecosystem including:

- **[vhs-decode](https://github.com/oyvindln/vhs-decode/wiki)** (for videotape formats)
- **[cvbs-decode](https://github.com/oyvindln/vhs-decode/wiki/CVBS-Composite-Decode)** (for composite video)
- **[hifi-decode](https://github.com/oyvindln/vhs-decode/wiki/hifi-decode)** (for audio processing)

All sub-projects share common tools and techniques by being active forks of this repository.

ld-decode is a GPL3 open-source project run entirely by volunteers and provided for free (as in freedom).


# Installation & Downloads 

Note that the main repo is under constant development and, while we strive to keep it stable, it is a part of the active development cycle.  You will find [ready-made binary builds](https://github.com/happycube/ld-decode) in the releases section of this repository.  The main ld-decode repo targets the nix development environment (suitable for a wide-range of Linux distributions and Mac OS)

If you would like installation instructions or details on how to compile the project from source please see the [ld-decode documentation](https://happycube.github.io/ld-decode/) for detailed instructions.

## Building from Source

For detailed build instructions, see **[BUILD.md](BUILD.md)** which includes:
- Quick start guide
- Step-by-step build process
- Building individual tools
- Build options (Debug, Release, Qt debug symbols, etc.)
- Troubleshooting

## Installation

For installation instructions after building, see **[INSTALL.md](INSTALL.md)** which covers:
- Installation directories and targets
- System-wide vs. staging directory installation
- Custom installation prefixes
- Python module installation
- Verification and troubleshooting


# The decoding tool-chain

> [!IMPORTANT]  
> ld-decode is the front-end RF decoder for LaserDisc sources.  Once you have a decoded TBC file you will need Decode-Orc in order to process this and turn it back into video, sound, etc.
>
> Please see [Decode-Orc](https://github.com/simoninns/decode-orc) for details of how to obtain and install the Decode-Orc tools

## Threaded decoding

`ld-decode -t N ...` decodes with N workers (`-t 0` picks a sensible
count automatically; the default `-t 1` is plain serial decode).  RF
block demodulation — the bulk of decode time — runs in prefetching
worker *processes* (so it stays off the Python GIL entirely), and each
field's downscale/metrics work fans out to threads while the sync chain
advances up to a few fields ahead; fields are committed and written
strictly in order.

Parallel decoding only engages after a short warm-up (the first ~20
fields decode serially while the MTF/AGC/de-emphasis calibration loops
settle; the worker processes are then built from the calibrated
parameters), and a field decoded under parameters that calibration
later adjusts is automatically re-decoded, along with anything decoded
ahead of it.  **Output is bit-identical for any `-t` value** — this is
asserted by the test suite — so there is no quality trade-off, only
memory (demod buffers plus ~150 MB per worker process).  Typical
steady-state speedup is ~3.5–4× (`-t 8` through `-t 16`); the remaining
ceiling is the in-order sync/commit chain on the main thread.
`--demod-threads-only` keeps demodulation in threads instead of
processes (slower, but lighter on memory).

## CVBS output mode

`ld-decode --cvbs ...` writes spec-compliant CVBS output instead of the
`.tbc` video output (see `cvbs-file-format-specification/`):

- `<out>.composite` — `CVBS_U16_4FSC` sample data in whole frames
  (NTSC: 477,750 samples/frame; PAL: 709,379), ld-decode line convention
  (the layout decode-orc's `cvbs_source` reader expects)
- `<out>.meta` — the spec's SQLite metadata; the signal state is measured
  and declared honestly (`STANDARD_TBC_LOCKED` when the burst-vs-lattice
  phase is stable within 3°, else `STANDARD_TBC_UNLOCKED`)
- `<out>_audio_00.wav` — spec WAV analog audio, frame-aligned with the
  written frames, with an honest `audio_locked` flag (PAL is frame-locked
  at 44100 Hz; NTSC is locked only with `--ntsc_audio_rate`)
- `<out>.dropouts.meta` — the dropout extension sidecar (dropout runs in
  CVBS frame-sample coordinates)
- `<out>.efm` + `<out>.efm.meta` — the EFM extension (t-values with a
  per-frame index) when digital audio is decoded

Note that **PAL 4fsc is not line-locked**: a line is 1135.0064 samples
and the sampling lattice slips 4 samples per frame, so the PAL
`.composite` is produced by a separate non-orthogonal resampler and its
timing differs fundamentally from the line-locked `.tbc` raster.  PAL
output is burst-anchored: the lattice constraint (sampling at 45° steps
to +U) is defined mod 90°, and 90° of subcarrier is exactly one lattice
sample, so the anchor is a global sub-sample time shift that tracks the
disc's Sc/H drift.  The file starts on NTSC colour frame A / PAL
sequence frame 1 (fieldPhaseID 1).
`scripts/cvbs_verify.py <out>.composite` checks an output file against
the specification (frame sizing, protected values, the 0H sync lattice
including the PAL slip, burst lock, extension sidecars, metadata, and
audio).

# Want to get involved?

The documentation includes details of the ld-decode community's Discord / IRC Bridge and the now legacy Facebook group.  

If you are interested in contributing or have general questions please join the [Domesday86 Discord server](https://discord.gg/pVVrrxd) which has the entire family of decode projects developers on it (or IRC if you must) as the Facebook group is mostly inactive.

For detailed information on how to contribute code, report bugs, or suggest enhancements, please see **[CONTRIBUTING.md](CONTRIBUTING.md)**.

You can also contribute to the project documentation, see the [docs/ directory in this repository](https://github.com/happycube/ld-decode/tree/main/docs) for details.

# Source code structure

The source is split roughly into two sections:

- ld-decode - The main Python application responsible for decoding lds/ldf LaserDisc RF samples into tbc files (time-base corrected framed video) and generating the initial metadata
- scripts (under the scripts/ directory) - Various scripts to assist with development and decoding
