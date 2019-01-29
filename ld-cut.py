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
import traceback

from lddutils import *
import lddecode_core
from lddecode_core import *

parser = argparse.ArgumentParser(description='Extracts a sample area from raw RF laserdisc captures')
parser.add_argument('infile', metavar='infile', type=str, help='source file')
parser.add_argument('-o', '--outfile', metavar='outfile', type=str, default='-', help='base name for destination files')

parser.add_argument('-s', '--start', metavar='start', type=int, default=0, help='rough jump to frame n of capture (default is 0)')
parser.add_argument('-l', '--length', metavar='length', type=int, default = -1, help='limit length to n frames')

parser.add_argument('-S', '--seek', metavar='seek', type=int, default=-1, help='seek to frame n of capture')
parser.add_argument('-E', '--end', metavar='end', type=int, default=-1, help='cutting: last frame')

parser.add_argument('-p', '--pal', dest='pal', action='store_true', help='source is in PAL format')
parser.add_argument('-n', '--ntsc', dest='ntsc', action='store_true', help='source is in NTSC format')

# included because some marginal CAV disks need -m 0 manually set
parser.add_argument('-m', '--MTF', metavar='mtf', type=float, default=None, help='mtf compensation multiplier')
parser.add_argument('--MTF_offset', metavar='mtf_offset', type=float, default=None, help='mtf compensation offset')

args = parser.parse_args()
#print(args)
filename = args.infile
outname = args.outfile
vid_standard = 'PAL' if args.pal else 'NTSC'

if args.pal and args.ntsc:
    print("ERROR: Can only be PAL or NTSC")
    exit(1)

if args.seek == -1 or args.end == -1:
    print("ERROR: -E and -S options must be supplied")
    exit(1)

if filename[-3:] == 'lds':
    loader = load_packed_data_4_40
elif filename[-3:] == 'r30':
    loader = load_packed_data_3_32
elif filename[-3:] == 'r16':
    loader = load_unpacked_data_s16
    
system = 'PAL' if args.pal else 'NTSC'
    
ldd = LDdecode(filename, None, loader, frameoutput=False, system=system, doDOD = False)

if args.MTF is not None:
    ldd.rf.mtf_mult = args.MTF

if args.MTF_offset is not None:
    ldd.rf.mtf_offset = args.MTF_offset

startloc = args.start * 2

if args.seek != -1:
    startloc = ldd.seek(args.start * 2, args.seek) 
    if startloc > 1:
        startloc -= 1
    
if args.end != -1:
    endloc = ldd.seek(startloc, args.end)
elif args.length != -1:
    endloc = startloc + args.length
else:
    print('ERROR: Must specify -l or -E option')
    exit(-1)

ldd.roughseek(startloc * 2)
startidx = ldd.fdoffset

ldd.roughseek(endloc * 2)
endidx = ldd.fdoffset

if args.outfile == '-':
    fd = sys.stdout
else:
    fd = open(args.outfile, 'wb')

print(startloc, endloc, startidx, endidx)

for i in range(startidx, endidx, 16384):
    l = endidx - i
    l = 16384 if (l > 16384) else l

    data = ldd.freader(ldd.infile, i, l)
    dataout = np.array(data, dtype=np.int16)
    fd.write(dataout)

exit(0)