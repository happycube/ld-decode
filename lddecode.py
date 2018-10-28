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
parser.add_argument('-s', '--start', metavar='start', type=int, default=0, help='rough jump to frame n of capture (default is 0)')
parser.add_argument('-S', '--seek', metavar='seek', type=int, default=-1, help='seek to frame n of capture')
parser.add_argument('-E', '--end', metavar='end', type=int, default=-1, help='cutting: last frame')
parser.add_argument('-l', '--length', metavar='length', type=int, help='limit length to n frames')
parser.add_argument('-p', '--pal', dest='pal', action='store_true', help='source is in PAL format')
parser.add_argument('-n', '--ntsc', dest='ntsc', action='store_true', help='source is in NTSC format')
parser.add_argument('-c', '--cut', dest='cut', action='store_true', help='cut (to r16) instead of decode')
parser.add_argument('-m', '--MTF', metavar='mtf', type=float, default=1.0, help='mtf compensation adjustment')

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

rfn = RFDecode(system=vid_standard, mtf_adjustment = args.MTF)

samples_per_frame = int(rfn.freq_hz / rfn.SysParams['FPS']) + 1
bytes_per_frame = samples_per_frame * 5 // 4  # for 10-bit packed files

# make sure we have at least two frames' worth of data (so we can be sure we will get at least one full frame)
infile_size = os.path.getsize(filename)
if (infile_size // bytes_per_frame - firstframe) < 2: 
	print('Error: start frame is past end of file')
	exit(1)
num_frames = req_frames if req_frames is not None else infile_size // bytes_per_frame - firstframe

fd = open(filename, 'rb')

if filename[-3:] == 'lds':
    lddecode_core.loader = load_packed_data_4_40
elif filename[-3:] == 'r30':
    lddecode_core.loader = load_packed_data_3_32
elif filename[-3:] == 'r16':
    lddecode_core.loader = load_unpacked_data_s16

if args.seek >= 0:
    nextsample = findframe(fd, rfn, args.seek, firstframe * samples_per_frame)
else:
    nextsample = firstframe * samples_per_frame

if args.cut:
    print(args.seek, args.end)
    outfile = open(outname + '.r16', 'wb')
    
    lastsample = findframe(fd, rfn, args.end, nextsample)
    lastsample += int(samples_per_frame * .25)
    
    for i in range(nextsample, lastsample, 16384):
        l = lastsample - i
        if l > 16384:
            l = 16384
            
        data = lddecode_core.loader(fd, i, l)
        dataout = np.array(data, dtype=np.int16)
        outfile.write(dataout)
        
    exit(0)
    
outfile = open(outname + '.tbc', 'wb')
outfile_audio = open(outname + '.pcm', 'wb')

framer_ntsc = Framer(rfn)
ca = []
for f in range(0, num_frames):
	if fd.tell() + bytes_per_frame * 1.05 <= infile_size:  # 1.05 gives us a little slack in case the frame is long
	    combined, audio, nextsample, fields = framer_ntsc.readframe(fd, nextsample, f == 0)
	    
	    print('frame ', framer_ntsc.vbi['framenr'])
	    
	    ca.append(audio)
	    
	    outfile.write(combined)
	    #print(len(audio)//2)
	    outfile_audio.write(audio)
	else:
		if req_frames is not None:
			print('Warning: end of file reached before requested number of frames were decoded')
		break

#draw_raw_bwimage(combined, outwidth, 610, hscale=2, vscale=2)

outfile.close()
outfile_audio.close()
