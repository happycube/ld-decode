# ld-decode-tools
ld-decode-tools is a suite of applications for processing the .tbc output from ld-decode.  The tools enable various processing of the LaserDisc including VBI, 40-bit FM code, White-Flag, dropout detection/correction and comb filtering.  The ld-decode-tools use a JSON based metadata file to store and communicate information about the .tbc.  Details of the JSON format can be found on the ld-decode wiki pages.


# Installation

Clone the ld-decode git repo.

From the tools directory type 'qmake' followed by 'make all'.  Once all of the applications are compiled use 'sudo make install' to install and 'sudo make uninstall' to remove.

Note: The ld-decode-tools.pro qmake project file is designed only for command line compilation with Ubuntu.  The individual application .pro files can be used within the Qt Creator IDE (you should build ld-decode-shared first in order to make a local copy of the required shared libraries).

The suggested tool order is ld-decodeshim (as ld-decode doesn't currently produce the required JSON metadata files), then ld-process-vbi and ld-dropoutdetect in order to fill out the metadata.  ld-analyse can then be used to examine the result.

So if, for example, your .tbc output file is test_video.tbc (and is NTSC):

```
ld-process-vbi test_video.tbc (add in the VBI data and determine the field order)

ld-process-ntsc test_video.tbc (add in white flag detection and 40-bit FM decode)

ld-dropout-detect test_video.tbc (perform drop-out detection)

ld-dropout-correct test_video.tbc test_video_doc.tbc (correct the dropouts and create a new .tbc)

ld-analyse test_video_doc.tbc & (view the corrected .tbc)

ld-comb-ntsc test_video_doc.tbc test_video_doc.rgb (convert the .tbc to RGB 16-16-16 frames)
```

For a PAL .tbc output file a typical sequence would be:
```
ld-process-vbi test_video.tbc (add in the VBI data and determine the field order)

ld-dropout-detect test_video.tbc (perform drop-out detection)

ld-dropout-correct test_video.tbc test_video_doc.tbc (correct the dropouts and create a new .tbc)

ld-analyse test_video_doc.tbc & (view the corrected .tbc)

ld-comb-pal test_video_doc.tbc test_video_doc.rgb (convert the .tbc to RGB 16-16-16 frames)
```

Note that the drop-out detection and correction is optional.  Both ld-analyse and the comb filters require field order determination, so the ld-process-vbi must be run before the tools can operate correctly.


## ld-process-vbi
This application examines the input TBC file and determines the available VBI data for each available frame.  The VBI data is stored as both the raw data value for the 3 VBI lines as well as a full decode of the VBI according to the IEC specifications.  The resulting information is written back into the JSON metadata file for the TBC output.

Syntax:

ld-process-vbi \<options> \<input file name>
  
Available options are:

  --debug - Show full debug output
    
  --help - show help text
  
  --version - show version text
  

## ld-dropout-detect
This application examines the input TBC file and performs drop-out detection on each of the available frames.  The detected drop-outs are written into the JSON metadata file for the TBC output.  Note: This application does not perform dropout correction and no change is made to the input TBC video.

Syntax:

ld-dropout-detect \<options> \<input file name>
  
Available options are:

  --debug - Show full debug output
    
  --help - show help text
  
  --version - show version text
  

## ld-dropout-correct
This application uses the drop-out information in the JSON metadata file to perform dropout correction on the input TBC file and produces a new output file.

Syntax:

ld-dropout-correct \<options> \<input file name> \<output file name>
  
Available options are:

  --debug - Show full debug output
    
  --help - show help text
  
  --version - show version text


## ld-comb-pal
This application takes the PAL TBC input video and colourises it.  Output is a sequence of RGB 16-16-16 video frames.

Syntax:

ld-comb-pal \<options> \<input file name> \<output file name>
  
Available options are:

  --debug - Show full debug output

  --start - Specify the start frame

  --length - Specify the maximum number of frames to process

  --crop - Crop the video output to match the output of a VP415 LaserDisc player
    
  --help - show help text
  
  --version - show version text

  
## ld-analyse
This GUI application provides a range of features for examining TBC output including drop-out detection, video extent, line scope and VBI data.  The application works with NTSC and PAL TBC output files.

Note: The input file name is optional (you can either specify it from the command line or using the GUI once the application is running).

Syntax:

ld-analyse \<options> \<input file name>
  
Available options are:

  --debug - Show full debug output
    
  --help - show help text
  
  --version - show version text


## ld-process-ntsc
This application processes items from the IEC NTSC specification that are specific to NTSC LaserDiscs such as 40-bit FM codes, white flags, etc.

Syntax:

ld-process-ntsc \<options> \<input file name>
  
Available options are:

  --debug - Show full debug output
    
  --help - show help text
  
  --version - show version text


## ld-comb-ntsc
This application takes the NTSC TBC input video and colourises it.  Output is a sequence of RGB 16-16-16 video frames.

Syntax:

ld-comb-ntsc \<options> \<input file name> \<output file name>
  
Available options are:

  --debug - Show full debug output

  --filterdepth \<1 to 3> - 1D, 2D or 3D filtering

  --blackandwhite - Output video frames in black and white

  --noadaptive2d - Do not use adaptive 2D processing with 3D filter depth

  --noopticalflow - Do not use optical flow detection with 3D filter depth

  --crop - Crop the output video to a typical LaserDisc player output

  --debugline \<line number 1 to 525> - Provide additional debug for the specified frame line number

  --start - Specify the start frame

  --length - Specify the maximum number of frames to process
    
  --help - show help text
  
  --version - show version text


## Software License (GPLv3)

    ld-decode-tools is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    ld-decode-tools is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

