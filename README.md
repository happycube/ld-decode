![vhs-decode logo](docs/vhs-decode_logo_256px.png)

# VHS-Decode

A fork of [LD-Decode](https://github.com/happycube/ld-decode), the decoding software powering the Domesday86 project.  
This version has been modified to work with the differences found in RF drum head signals taken directly from videotapes
(not to be confused with the antenna connector on the back of the VCR!).

![vhs-decode thumbnail](https://cdn.lbryplayer.xyz/api/v4/streams/free/vhs-decode-thumbnail/0cfb657312d9a725c20ecce33f1a06bd4895fe40/4b3544)

Currently, only (S-)VHS and U-Matic format tapes are supported;
of those, only NTSC, PAL and PAL-M variants are supported, with plans and/or ongoing work to support more formats and systems.

# Hardware used

The current main options for capturing the rf signal that are supported are the [Domesday Duplicator](https://github.com/happycube/ld-decode/wiki/Domesday-Duplicator) and video capture cards based on Conexant CX23880/1/2/3 chipset using the [CXADC](https://github.com/happycube/cxadc-linux3) kernel module (including variants with PCI-Express x1 bridge). A limitation currently is that both these methods can only capture one signal at a time, so there is no straight forward way of capturing both video and audio at the same time.

## Domesday Duplicator
The domesday duplicator is a custom made solution, originally geared towards capturing RF from laserdiscs players, it does however also work well for digitizing VHS RF data. It consists of a custom analog to digital board, a DE0-NANO FPGA development board, and a Cypress SuperSpeed Explorer development board. More in-depth information about it can be found in the [Domesday86](https://www.domesday86.com/?page_id=2233) project wiki. A major downside of this approach is that the custom board requires prining the PCB and assembling the components yourself (unless you can find someone that have ready-made ones for sale.), and the cost can be a bit high.

## CX Card
The budget approach is using a video capture card based on a Conexant CX23880/1/2/3 chipset. With a modded driver, these cards can be made to capture raw data instead of decoding video normally as they otherwise would. The original cards with this chipset were cards that plugged into the PCI slot (the chip is an all-in-one chip that handles both video decoding and pci interface.) However, there are also newly-made chinese variants that can be found on aliexpress and similar that are made to work in pci-express slots. An advandage of this approach is that the cards (both old PCI ones and new PCIE ones) can be very cheap. The cards may however be a bit more subject to noise compared to the domesday duplicator, though we have not done extensive testing on how they stack up. Capture is done using the custom ```cxadc``` driver (currently linux only). See the [CXADC](https://github.com/happycube/cxadc-linux3) website/repository for more details.

# Dependencies

VHS-Decode, as with LD-Decode, has been developed and tested on machines running the latest version of Ubuntu and Linux Mint.
Other distributions might have outdated (or even newer) versions of certain Python libraries or other dependencies, breaking compatibility. It has been confirmed to work via WSL2. It also partially runs on Windows natively.

Other dependencies include Python 3.5+, Qt5, Qmake, and FFmpeg.

## CVBS-Decode

The repository also contains an experimental CVBS decoder, ```cvbs-decode```, which shares code with ld-decode and vhs-decode. Capable of decoding basic raw digitized NTSC and PAL composite video, including color if the source is somwhat stable. Samples can be captured using cxadc, however this is somewhat buggy as the cx chip can decide resample or do other things if it detects a valid video signal. Test samples can also be generated using [HackTV](https://github.com/fsphil/hacktv).

# Installation and running the software on Ubuntu/Debian

Install all dependencies required by LD-Decode and VHS-Decode:

    sudo apt install build-essential git ffmpeg flac libavcodec-dev libavformat-dev libqwt-qt5-dev qt5-qmake qtbase5-dev python3 python3-pip python3-distutils libfftw3-dev openssl
    sudo pip3 install numba pandas matplotlib scipy numpy==1.20.3 samplerate pyhht
    
(An older numpy version is needed currently due to some compatability [issues](https://github.com/numba/numba/issues/7176) with numba)

Download VHS-Decode:

    git clone https://github.com/oyvindln/vhs-decode.git vhs-decode

Compile and install Domesday tools:

    cd vhs-decode && make -j8 && sudo make install && make clean
    
# Usage

## Cx card capture
See live preview of tape signal being received by CXADC card from video heads (PAL framing for 35.8 MHz/8-bit mode):

    ffplay -hide_banner -async 1 -f rawvideo -pix_fmt gray8 -video_size 2291x625 -i /dev/cxadc0 -vf scale=1135x625,eq=gamma=0.5:contrast=1.5
    
Or (NTSC framing for 35.8 MHz/8-bit mode):

    ffplay -hide_banner -async 1 -f rawvideo -pix_fmt gray8 -video_size 2275x525 -i /dev/cxadc0 -vf scale=910x525,eq=gamma=0.5:contrast=1.5
    
Capture 30 seconds of tape signal using CXADC driver in 8-bit mode and asynchronous audio from line input.
It is recommended to use fast storage:

    timeout 30s cat /dev/cxadc0 > <capture>.r8 | ffmpeg -f alsa -i default -compression_level 12 -y <capture>.flac

## Decoding 

Decode your captured tape by using:

    vhs-decode [arguments] <capture file> <output name>
    
Use analyse tool to inspect decoded tape:

    ld-analyse <output name>.tbc
    
Reduce size of captured CXADC 8-bit data (by 50-60%):

    flac --best --sample-rate=48000 --sign=unsigned --channels=1 --endian=little --bps=8 -f <capture>.r8 -o <capture>.vhs

## Generating video files

VHS-Decode produces timebase corrected 16-bit headerless video signal in .tbc format plus .json and .log files, usable with the LD-Decode family of tools (ld-analyse, ld-process-vbi, and ld-process-vits), VBI data recovery software like [VHS-Teletext](https://github.com/ali1234/vhs-teletext/) or other utilities allowing to recover closed captions and tape-based [arcade games](https://vhs.thenvm.org/resources-research/).
To generate .mkv files viewable in most media players, simply use the scripts installed:

    gen_chroma_vid.sh -v <pal/ntsc> -s <skip n frames> -l <n frames long> -i <.tbc filename without .tbc extension>
    
    # the -a option can embed an audio file.
    gen_chroma_vid.sh -v <pal/ntsc> -s <skip n frames> -l <n frames long> -a <capture>.flac -i <.tbc filename without .tbc extension>

This will use decoded .tbc files, generate a lossless, interlaced and high-bitrate (roughly 100-150 Mb/s) video which,
although ideal for archival and reducing further loss in quality, may be unsuitable for sharing online.
An additional processing mode is included in the script files, but commented out.

## Terminal arguments

VHS-Decode supports various arguments to process differently captured tape recordings and different tape formats/systems.
These tend to change frequently as new features are added or superseded.

```--cxadc, --10cxadc, --cxadc3, --10cxadc3, -f```: 

Changes the sample rate and bit depth for the decoder.
By default, this is set to 40 MHz (the sample rate used by the Domesday Duplicator) at 16 bits.
These flags change this to 28.6 MHz/8-bit, 14.3 MHz/10-bit, 35.8 MHz/8-bit and 17.9 MHz/10-bit, respectively.
See the readme file for [CXADC](https://github.com/happycube/cxadc-linux3#readme) for more information on what each mode and capture rate means.
```-f``` sets the frequency to a custom, user-defined one (expressed as an integer, ie ```-f 40000000``` for 40 MHz input).

```-n, -p, -pm, --NTSCJ```: 

Changes the color system to NTSC, PAL, PAL-M, or NTSC-J, respectively.
Please note that, as of writing, support for PAL-M is **experimental**.

```-s, --start_fileloc, -l```: 

Used for jumping ahead in a file or defining limit.
Useful for recovering decoding after a crash, or by limiting process time by producing shorter samples.
```-s``` jumps ahead to any given frame in the capture,
```--start_fileloc``` jumps ahead to any given *sample* in the capture
(note: upon crashing, vhs-decode automatically dumps the last known sample location in the terminal output) and
```-l``` limits decode length to *n* frames.

```-t```: defines the number of processing threads to use during demodulation.
By default, the main VHS-Decode script allocates only one thread, though the gen_chroma_vid scripts allocate two.
The ```make``` rule of thumb of "number of logical processors, plus one" generally applies here,
though it mainly depends on the amount of memory available to the decoder.

## Debug features

See [Advanced Flags](advanced_flags.md) for more information.

# Supported formats

Tapes:

(S-)VHS 625-line and 525-line, PAL, PAL-M and NTSC.
U-Matic 625-line and 525-line Low Band, PAL and NTSC.

Input file formats:

.ldf/.lds (Domesday Duplicator FLAC-compressed and uncompressed data).

.r8/.u8 (CXADC 8-bit raw data).

.r16/.u16 (CXADC 16-bit raw data).

.flac/.vhs/.svhs/.cvbs (FLAC-compressed captures, can be either 8-bit or 16-bit).

Output file formats:

Unlike LD-Decode, VHS-Decode does not output its timebase-corrected frames as single .tbc file - instead,
it splits both the luminance and chrominance data separate files, first .tbc is comprising luminance data, second chrominance data as chroma.tbc.
Additionaly useful for troubleshooting .log and .json frame descriptor table files are created.

# Join us

[Discord](https://discord.gg/pVVrrxd)

[VideoHelp Forum](https://forum.videohelp.com/threads/394168-Current-status-of-ld-decode-vhs-decode-(true-backup-of-RF-signals)#post2558660)

[Facebook](https://www.facebook.com/groups/2070493199906024)

# Documentation
Some documentation is available via the GitHub wiki. This includes installation and usage instructions. Start with the wiki if you have any questions.

[LD-decode Wiki](https://github.com/happycube/ld-decode/wiki)

## *If in doubt - Feel free to ask!*
