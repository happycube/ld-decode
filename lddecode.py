#!/usr/bin/env python3
from base64 import b64encode
import copy
from datetime import datetime
import getopt
import io
from io import BytesIO
import os
import sys
import argparse

from lddutils import *
import lddecode_core
from lddecode_core import *

parser = argparse.ArgumentParser(description='Extracts audio and video from raw RF laserdisc captures')
parser.add_argument('infile', metavar='infile', type=str, help='source file')
parser.add_argument('outfile', metavar='outfile', type=str, help='base name for destination files')
parser.add_argument('--start', metavar='start', type=int, default=0, help='start at frame n (default is 0)')
parser.add_argument('--length', metavar='length', type=int, default=100, help='limit length to n frames (default is 100)')
parser.add_argument('--system', metavar='system', type=str, choices=['ntsc','pal'], default='ntsc', help='video system standard (ntsc/pal, default is ntsc)')
args = parser.parse_args()
filename = args.infile
outname = args.outfile
firstframe = args.start
num_frames = args.length
vid_standard = args.system.upper()

rfn = RFDecode(system=vid_standard)

bytes_per_frame = int(rfn.freq_hz / rfn.SysParams['FPS']) + 1

fd = open(filename, 'rb')
lddecode_core.loader = load_packed_data_4_40

nextsample = firstframe * bytes_per_frame

outfile = open(outname + '.tbc', 'wb')
outfile_audio = open(outname + '.pcm', 'wb')

framer_ntsc = Framer(rfn)
ca = []
for f in range(0, num_frames):
    combined, audio, nextsample, fields = framer_ntsc.readframe(fd, nextsample, f == 0)
    
    print('frame ', framer_ntsc.vbi['framenr'])
    
    ca.append(audio)
    
    outfile.write(combined)
    print(len(audio)//2)
    outfile_audio.write(audio)

#draw_raw_bwimage(combined, outwidth, 610, hscale=2, vscale=2)

outfile.close()
outfile_audio.close()
