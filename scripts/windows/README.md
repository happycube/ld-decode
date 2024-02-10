# Windows Scripts 


This is a collection of basic "drag 'n drop" style bash scripts used for the windows bundled releases for layman users or just pure time saving basic examples for others to make there own scripts.


## Whats Included 


- lds-compress.bat - CPU Based FLAC Compression via ld-lds-converter + FFmpeg 
- lds-compress-nvidia-gpu.bat - GPU Based FLAC Compression via ld-lds-converter + [FLACCL](http://cue.tools/wiki/FLACCL#Download)
- lds-unpack.bat - Simple script to use ld-lds-converter to unpack an 10-bit packed .lds to .s16 raw data.
- s16-to-flac.bat - Simple FLAC script for compressing raw 16-bit files.
- tbc-dropout-correct.bat - Creates a intendent drop out corrected TBC (normally handled via the tbc-video-export tool on export to video)
- tbc-process-vbi.bat - Simple script to run ld-process-vbi and update the json.


## Dependency's


These are currently only tested on Windows 10 (Version 10.0.19045 Build 19045) but should also work on Windows 11.

- ld-tools-suite
- FLAC
- FFmpeg
- CUETools.FLACCL.cmd.exe
- CUETools.Codecs.Flake.dll
- CUETools.Codecs.FLACCL.dll
- CUETools.Codecs.dll
- libFLAC.dll
- libFLAC++.dll
- metaflac.exe
- Newtonsoft.Json.dll
- OpenCLNet.dll


Created/Maintained by [Harry Munday](https://github.com/harrypm/) (harry@opcomedia.com)