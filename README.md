# ld-decode


This is the GitHub repo for ld-decode.  This is the (hopefully stable) merged development branch.


# Documentation


Documentation is available via the GitHub wiki.  This includes installation and usage instructions.  Start with the wiki if you have any questions.  

The wiki also includes details of the project's IRC channel and Facebook group.  

If you intend on contributing or have general questions please join the Discord server which has the entire family of decode projects developers on it (or IRC if you must) as the Facebook group is mostly inactive.

https://github.com/happycube/ld-decode/wiki

https://discord.gg/pVVrrxd


## *If in doubt - Read the Wiki!*


# Source code locations


The source is split roughly into three parts:

- ld-decode - The main python application responsible for decoding lds/ldf LaserDisc RF samples into tbc files (time-base corrected framed video)
- ld-decode-tools (under the tools/ directory) - The tool-chain for processing tbc files in various ways
- scripts (under the scripts/ directory) - Various scripts to assist with dev and decoding


## Self-contained builds 


You will find Windows/MacOS/Linux self-contained binaries for the entire decode family workflow here:

- [vhs-decode repository](https://github.com/oyvindln/vhs-decode/releases/) - VHS and many other tape formats are supported by the FM RF archival method today. 
- [tbc-video-export repository](https://github.com/JuniorIsAJitterbug/tbc-video-export/releases) - More fluid and simple export workflow tool for CVBS/S-Video type TBC files.
