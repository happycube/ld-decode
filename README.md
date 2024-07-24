# ld-decode


This is the GitHub repo for ld-decode.  This is the (hopefully stable) merged development branch.


# Installation & Downloads 


- [Linux](https://github.com/happycube/ld-decode/wiki/Installation)
- [Windows](https://github.com/oyvindln/vhs-decode/wiki/Windows-Build)
- [MacOS](https://github.com/oyvindln/vhs-decode/wiki/MacOS-Build)

You will find self-contained binary bundled ready-to-use packages of current and future builds of the decoders and ld-x tools in the [vhs-decode repository](https://github.com/oyvindln/vhs-decode/wiki/), combining `ld-decode`, `vhs-decode`, `cvbs-decode` & `hifi-decode` into one package, alongside [tbc-video-export](https://github.com/JuniorIsAJitterbug/tbc-video-export/releases) a more fluid cross format export tool to make CVBS/S-Video type TBC files into video files.


> [!NOTE]  
> vhs-decode is not limited to VHS and supports many tape media formats!

> [!IMPORTANT]  
> The decoders and tools are CLI - Commandline Interface, only ld-analyse & hifi-decode have a GUI - Graphical User Interface.


# Documentation


Documentation is available via the GitHub wiki's.  This includes installation and usage instructions.  

Start with the wiki if you have any questions.

If you only care about Laserdiscs please read

- [LD-Decode Wiki](https://github.com/happycube/ld-decode/wiki)

If you want to learn about FM RF archival overall and other media formats such as tape or RAW Composite/CVBS decoding then please read:

- [VHS-Decode Wiki](https://github.com/oyvindln/vhs-decode/wiki/)


The wiki also includes details of the decode community's Discord / IRC Bridge and the now legacy Facebook group.  

If you intend on contributing or have general questions please join the [Discord server](https://discord.gg/pVVrrxd) which has the entire family of decode projects developers on it (or IRC if you must) as the Facebook group is mostly inactive there is also the [r/vhs-decode](https://new.reddit.com/r/vhsdecode/) subreddit that is fairly active. 


## *If in doubt - Read the Wiki!*


# Source code locations


The source is split roughly into three parts:

- ld-decode - The main Python application responsible for decoding lds/ldf LaserDisc RF samples into tbc files (time-base corrected framed video)
- ld-decode-tools (under the tools/ directory) - The tool-chain for processing tbc files in various ways
- scripts (under the scripts/ directory) - Various scripts to assist with dev and decoding
