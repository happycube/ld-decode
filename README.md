# Documentation

> [!Important]
> If in doubt read the comprehensive [documentation web-site](https://happycube.github.io/ld-decode-docs/)!

You can find the documentation here: [ld-decode documentation](https://happycube.github.io/ld-decode-docs/)

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

If you would like installation instructions or details on how to compile the project from source please see the [ld-decode documentation](https://happycube.github.io/ld-decode-docs/) for detailed instructions.

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

# Want to get involved?

The documentation includes details of the ld-decode community's Discord / IRC Bridge and the now legacy Facebook group.  

If you are interested in contributing or have general questions please join the [Domesday86 Discord server](https://discord.gg/pVVrrxd) which has the entire family of decode projects developers on it (or IRC if you must) as the Facebook group is mostly inactive.

For detailed information on how to contribute code, report bugs, or suggest enhancements, please see **[CONTRIBUTING.md](CONTRIBUTING.md)**.

You can also contribute to the project documentation, see the [ld-decode documentation github](https://github.com/happycube/ld-decode-docs) for details.

# Source code structure

The source is split roughly into two sections:

- ld-decode - The main Python application responsible for decoding lds/ldf LaserDisc RF samples into tbc files (time-base corrected framed video) and generating the initial metadata
- scripts (under the scripts/ directory) - Various scripts to assist with development and decoding
