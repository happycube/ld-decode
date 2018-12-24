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
import json

from lddutils import *
import lddecode_core
from lddecode_core import *

parser = argparse.ArgumentParser(description='Extracts audio and video from raw RF laserdisc captures')
parser.add_argument('infile', metavar='infile', type=str, help='source file')
parser.add_argument('outfile', metavar='outfile', type=str, help='base name for destination files')
parser.add_argument('-s', '--start', metavar='start', type=int, default=0, help='rough jump to frame n of capture (default is 0)')
parser.add_argument('-S', '--seek', metavar='seek', type=int, default=-1, help='seek to frame n of capture')
#parser.add_argument('-E', '--end', metavar='end', type=int, default=-1, help='cutting: last frame')
parser.add_argument('-l', '--length', metavar='length', type=int, default = 1, help='limit length to n frames')
parser.add_argument('-p', '--pal', dest='pal', action='store_true', help='source is in PAL format')
parser.add_argument('-n', '--ntsc', dest='ntsc', action='store_true', help='source is in NTSC format')
#parser.add_argument('-c', '--cut', dest='cut', action='store_true', help='cut (to r16) instead of decode')
parser.add_argument('-m', '--MTF', metavar='mtf', type=float, default=1.0, help='mtf compensation multiplier')
parser.add_argument('--MTF_offset', metavar='mtf_offset', type=float, default=0.0, help='mtf compensation offset')
parser.add_argument('-f', '--frame', dest='frame', action='store_true', help='output frames')
parser.add_argument('--NTSCJ', dest='ntscj', action='store_true', help='source is in NTSC-J (IRE 0 black) format')

args = parser.parse_args()
print(args)
filename = args.infile
outname = args.outfile
firstframe = args.start
req_frames = args.length
vid_standard = 'PAL' if args.pal else 'NTSC'

if args.pal and args.ntsc:
    print("ERROR: Can only be PAL or NTSC")
    exit(1)

# make sure we have at least two frames' worth of data (so we can be sure we will get at least one full frame)
#infile_size = os.path.getsize(filename)
#if (infile_size // bytes_per_frame - firstframe) < 2: 
	#print('Error: start frame is past end of file')
	#exit(1)
#num_frames = req_frames if req_frames is not None else infile_size // bytes_per_frame - firstframe

#fd = open(filename, 'rb')

if filename[-3:] == 'lds':
    loader = load_packed_data_4_40
elif filename[-3:] == 'r30':
    loader = load_packed_data_3_32
elif filename[-3:] == 'r16':
    loader = load_unpacked_data_s16
    
system = 'PAL' if args.pal else 'NTSC'
foutput = False if not args.frame else True
    
ldd = LDdecode(filename, outname, loader, frameoutput=foutput, system=system)
ldd.roughseek(firstframe * 2)

if system == 'NTSC' and not args.ntscj:
    ldd.blackIRE = 7.5
    
print(ldd.blackIRE)

if args.seek != -1:
    ldd.seek(firstframe, args.seek)

ldd.rf.mtf_mult = args.MTF
ldd.rf.mtf_offset = args.MTF_offset

for i in range(0, req_frames * 2):
    f = ldd.readfield()

    jsondict = ldd.build_json(f)
    
    fp = open(outname + '.tbc.json.tmp', 'w')
    json.dump(jsondict, fp, indent=4)
    fp.write('\n')
    fp.close()
    
    os.rename(outname + '.tbc.json.tmp', outname + '.tbc.json')
