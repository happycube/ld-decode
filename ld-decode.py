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

parser = argparse.ArgumentParser(description='Extracts audio and video from raw RF laserdisc captures')
parser.add_argument('infile', metavar='infile', type=str, help='source file')
parser.add_argument('outfile', metavar='outfile', type=str, help='base name for destination files')
parser.add_argument('-s', '--start', metavar='start', type=int, default=0, help='rough jump to frame n of capture (default is 0)')
parser.add_argument('-S', '--seek', metavar='seek', type=int, default=-1, help='seek to frame n of capture')
#parser.add_argument('-E', '--end', metavar='end', type=int, default=-1, help='cutting: last frame')
parser.add_argument('-l', '--length', metavar='length', type=int, default = 110000, help='limit length to n frames')
parser.add_argument('-p', '--pal', dest='pal', action='store_true', help='source is in PAL format')
parser.add_argument('-n', '--ntsc', dest='ntsc', action='store_true', help='source is in NTSC format')
#parser.add_argument('-c', '--cut', dest='cut', action='store_true', help='cut (to r16) instead of decode')
parser.add_argument('-m', '--MTF', metavar='mtf', type=float, default=None, help='mtf compensation multiplier')
parser.add_argument('--MTF_offset', metavar='mtf_offset', type=float, default=None, help='mtf compensation offset')
parser.add_argument('-f', '--frame', dest='frame', action='store_true', help='output frames')
parser.add_argument('--NTSCJ', dest='ntscj', action='store_true', help='source is in NTSC-J (IRE 0 black) format')
parser.add_argument('--noDOD', dest='nodod', action='store_true', default=False, help='enable dropout detector')

parser.add_argument('--noleadout', dest='noleadout', action='store_true', default=False, help='enable dropout detector')


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
    
ldd = LDdecode(filename, outname, loader, frameoutput=foutput, system=system, doDOD = not args.nodod)
ldd.roughseek(firstframe * 2)

if system == 'NTSC' and not args.ntscj:
    ldd.blackIRE = 7.5
    
#print(ldd.blackIRE)

if args.seek != -1:
    ldd.seek(firstframe, args.seek)

if args.MTF is not None:
    ldd.rf.mtf_mult = args.MTF

if args.MTF_offset is not None:
    ldd.rf.mtf_offset = args.MTF_offset

def write_json(ldd, outname):
    jsondict = ldd.build_json(ldd.curfield)
    
    fp = open(outname + '.tbc.json.tmp', 'w')
    json.dump(jsondict, fp, indent=4)
    fp.write('\n')
    fp.close()
    
    os.rename(outname + '.tbc.json.tmp', outname + '.tbc.json')

done = False

while not done and ldd.fields_written < (req_frames * 2):
    try:
        f = ldd.readfield()
    except Exception as err:
        #print("aborted")
        traceback.print_tb(err.__traceback__)
        write_json(ldd, outname)
        exit(1)

    if f is None or (args.noleadout == False and ldd.leadOut == True):
        done = True

#    print(ldd.fields_written)

    if ldd.fields_written < 100 or ((ldd.fields_written % 500) == 0):
        #print('write json')
        write_json(ldd, outname)

print("saving JSON and exiting")    
write_json(ldd, outname)
