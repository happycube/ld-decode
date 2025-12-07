# What is ld-decode?

**ld-decode** is a software-defined decoder for LaserDisc RF captures made using modified LaserDisc players and capture devices such as the [DomesdayDuplicator](https://github.com/simoninns/DomesdayDuplicator)

ld-decode recovers video, analog audio, digital audio and metadata content from raw RF samples captured directly from LaserDisc players, bypassing the analog signal chain to achieve preservation-quality digital transfers.

Although ld-decode was originally dedicated to LaserDiscs it has become part of a larger ecosystem including:

- **[vhs-decode](https://github.com/oyvindln/vhs-decode)** (for videotape formats)
- **[cvbs-decode](https://github.com/oyvindln/cvbs-decode)** (for composite video)
- **[hifi-decode](https://github.com/oyvindln/hifi-decode)** (for audio processing)

All sub-projects share common tools and techniques by being active forks of this repository.

ld-decode is a GPL3 open-source project run entirely by volunteers and provided for free (as in freedom).


# Installation & Downloads 

Note that the main repo is under constant development and, while we strive to keep it stable, it is a part of the active development cycle.  Contributors maintain read-made binary builds which are far more suitable for end-users and are available for platforms such as Windows and Apple MacOS.  The main repo targets only Ubuntu (generally the current LTS version).

If you'd like to download binaries or compile the project from source please see the project's wiki for detailed instructions.


# Documentation

> [!Important]
> If in doubt read the wiki!

You can find the wiki here: [ld-decode Wiki](https://github.com/happycube/ld-decode/wiki)


# The decoding tool-chain

> [!IMPORTANT]  
> The decoders and tools are primarily command line based, only the ld-analyse tool provides a GUI (Graphical User Interface)

# Want to get involved?

The wiki includes details of the ld-decode community's Discord / IRC Bridge and the now legacy Facebook group.  

If you are interested in contributing or have general questions please join the [Discord server](https://discord.gg/pVVrrxd) which has the entire family of decode projects developers on it (or IRC if you must) as the Facebook group is mostly inactive.

There is also a VHS specific subreddit [r/vhs-decode](https://new.reddit.com/r/vhsdecode/) that is fairly active. 


# Source code structure

The source is split roughly into three sections:

- ld-decode - The main Python application responsible for decoding lds/ldf LaserDisc RF samples into tbc files (time-base corrected framed video) and generating the initial metadata
- ld-decode-tools (under the tools/ directory) - The Qt based tool-chain for processing tbc files and associated metadata in various ways
- scripts (under the scripts/ directory) - Various scripts to assist with development and decoding
