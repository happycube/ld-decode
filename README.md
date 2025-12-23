# Documentation

> [!Important]
> If in doubt read the comprehensive [documentation web-site](https://happycube.github.io/ld-decode-docs/)!

You can find the documentation here: [ld-decode documentation](https://happycube.github.io/ld-decode-docs/)

Check the documentation first, the [discord server](https://discord.com/invite/pVVrrxd) second and then raise issues.

# What is ld-decode?

**ld-decode** is a software-defined decoder for LaserDisc RF captures made using modified LaserDisc players and capture devices such as the [DomesdayDuplicator](https://github.com/simoninns/DomesdayDuplicator)

ld-decode recovers video, analog audio, digital audio and metadata content from raw RF samples captured directly from LaserDisc players, bypassing the analog signal chain to achieve preservation-quality digital transfers.

Although ld-decode was originally dedicated to LaserDiscs it has become part of a larger ecosystem including:

- **[vhs-decode](https://github.com/oyvindln/vhs-decode/wiki)** (for videotape formats)
- **[cvbs-decode](https://github.com/oyvindln/vhs-decode/wiki/CVBS-Composite-Decode)** (for composite video)
- **[hifi-decode](https://github.com/oyvindln/vhs-decode/wiki/hifi-decode)** (for audio processing)

All sub-projects share common tools and techniques by being active forks of this repository.

ld-decode is a GPL3 open-source project run entirely by volunteers and provided for free (as in freedom).


# Installation & Downloads 

Note that the main repo is under constant development and, while we strive to keep it stable, it is a part of the active development cycle.  Contributors maintain ready-made binary builds which are far more suitable for end-users and are available for platforms such as Windows and Apple MacOS.  The main ld-decode repo targets only Ubuntu (generally the current LTS version - although it's possible to compile the project on most Linux flavors).

If you'd like to download binaries or compile the project from source please see the [ld-decode documentation](https://happycube.github.io/ld-decode-docs/) for detailed instructions.

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
> The decoders and tools are primarily command line based, only the ld-analyse tool provides a GUI (Graphical User Interface)

# Want to get involved?

The documentation includes details of the ld-decode community's Discord / IRC Bridge and the now legacy Facebook group.  

If you are interested in contributing or have general questions please join the [Domesday86 Discord server](https://discord.gg/pVVrrxd) which has the entire family of decode projects developers on it (or IRC if you must) as the Facebook group is mostly inactive.

For detailed information on how to contribute code, report bugs, or suggest enhancements, please see **[CONTRIBUTING.md](CONTRIBUTING.md)**.

You can also contribute to the project documentation, see the [ld-decode documentation github](https://github.com/happycube/ld-decode-docs) for details.

There is also a VHS specific subreddit [r/vhs-decode](https://new.reddit.com/r/vhsdecode/) that is fairly active. 


# Source code structure

The source is split roughly into three sections:

- ld-decode - The main Python application responsible for decoding lds/ldf LaserDisc RF samples into tbc files (time-base corrected framed video) and generating the initial metadata
- ld-decode-tools (under the tools/ directory) - The Qt based tool-chain for processing tbc files and associated metadata in various ways
- scripts (under the scripts/ directory) - Various scripts to assist with development and decoding
- prototypes (under the prototypes/ directory) - Tools under development that are not yet suitable for inclusion in the main tools build environment
