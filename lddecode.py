#!/usr/bin/python3
from base64 import b64encode
import copy
from datetime import datetime
import getopt
import io
from io import BytesIO
import os
import sys

from lddutils import *
import lddecode_core
from lddecode_core import *

if len(sys.argv) != 5:
    print("lddecode.py [input file] [output file] [start] [end]")
    sys.exit(0)
    
filename = sys.argv[1]
outname = sys.argv[2]
firstframe = int(sys.argv[3])
num_frames = int(sys.argv[4])

rfn = RFDecode(system='NTSC')

bytes_per_frame = int(rfn.freq_hz / rfn.SysParams['FPS']) + 1

fd = open(filename, 'rb')
lddecode_core.loader = load_packed_data_4_40

nextsample = firstframe * bytes_per_frame

outfile = open(outname + '.tbc', 'wb')
outfile_audio = open(outname + '.pcm', 'wb')

framer_ntsc = Framer(rfn)
ca = []
for f in range(0, num_frames):
    combined, audio, nextsample = framer_ntsc.readframe(fd, nextsample, f == 0)
    
    print('frame ', framer_ntsc.vbi['framenr'])
    
    ca.append(audio)
    
    outfile.write(combined)
    print(len(audio)//2)
    outfile_audio.write(audio)

#draw_raw_bwimage(combined, outwidth, 610, hscale=2, vscale=2)

outfile.close()
outfile_audio.close()
