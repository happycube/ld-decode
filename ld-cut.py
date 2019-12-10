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
import subprocess

from lddutils import *
import lddecode_core
from lddecode_core import *

parser = argparse.ArgumentParser(description='Extracts a sample area from raw RF laserdisc captures')
parser.add_argument('infile', metavar='infile', type=str, help='source file')
parser.add_argument('outfile', metavar='outfile', type=str, help='destination file')

parser.add_argument('-s', '--start', metavar='start', type=float, default=0, help='rough jump to frame n of capture (default is 0)')
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

try:
    loader = make_loader(filename, None)
except ValueError as e:
    print(e)
    exit(1)

makelds = True if outname[-3:] == 'lds' else False
    
system = 'PAL' if args.pal else 'NTSC'
    
ldd = LDdecode(filename, None, loader, system=system, doDOD = False)

if args.MTF is not None:
    ldd.rf.mtf_mult = args.MTF

if args.MTF_offset is not None:
    ldd.rf.mtf_offset = args.MTF_offset

if args.seek != -1:
    startloc = ldd.seek(args.start, args.seek) 
    if startloc > 1:
        startloc -= 1
else:
    startloc = args.start * 2

if args.end != -1:
    endloc = ldd.seek(startloc, args.end)
elif args.length != -1:
    endloc = startloc + (args.length * 2)
else:
    print('ERROR: Must specify -l or -E option')
    exit(-1)

ldd.roughseek(startloc)
startidx = int(ldd.fdoffset)

ldd.roughseek(endloc)
endidx = int(ldd.fdoffset)

if makelds:
    process = subprocess.Popen(['ld-lds-converter', '-o', outname, '-p'], stdin=subprocess.PIPE)
    fd = process.stdin
else:
    fd = open(args.outfile, 'wb')

#print(startloc, endloc, startidx, endidx)

for i in range(startidx, endidx + 16384, 16384):
    l = endidx - i

    if l > 16384:
        l = 16384
    else:
        break
    #l = 16384 if (l > 16384) else l

    data = ldd.freader(ldd.infile, i, l)
    dataout = np.array(data, dtype=np.int16)

    fd.write(dataout)

fd.close()

if makelds:
    # allow ld-lds-converter to finish after EOFing it's input
    process.wait()
    
#exit(0)
