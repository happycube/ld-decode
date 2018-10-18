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
parser.add_argument('-S', '--seek', metavar='seek', type=int, default=-1, help='rough jump to frame n of capture')
parser.add_argument('-l', '--length', metavar='length', type=int, help='limit length to n frames')
parser.add_argument('-p', '--pal', dest='pal', action='store_true', help='source is in PAL format')
args = parser.parse_args()
filename = args.infile
outname = args.outfile
firstframe = args.start
req_frames = args.length
vid_standard = 'PAL' if args.pal else 'NTSC'

rfn = RFDecode(system=vid_standard)

samples_per_frame = int(rfn.freq_hz / rfn.SysParams['FPS']) + 1
bytes_per_frame = samples_per_frame * 5 // 4  # for 10-bit packed files

# make sure we have at least two frames' worth of data (so we can be sure we will get at least one full frame)
infile_size = os.path.getsize(filename)
if (infile_size // bytes_per_frame - firstframe) < 2: 
	print('Error: start frame is past end of file')
	exit(1)
num_frames = req_frames if req_frames is not None else infile_size // bytes_per_frame - firstframe

def findframe(infile, rf, target, nextsample = 0):
    framer = Framer(rf, full_decode = False)
    samples_per_frame = int(rf.freq_hz / rf.SysParams['FPS'])
    framer.vbi = {'framenr': None}
    
    iscav = False
    
    retry = 5
    while framer.vbi['framenr'] is None and retry:
        rv = framer.readframe(infile, nextsample, CAV=False)
        print(rv, framer.vbi)

        # because of 29.97fps, there may be missing frames
        if framer.vbi['isclv']:
            tolerance = 1
        else:
            tolerance = 0
            iscav = True
            
        # This jumps forward 10 seconds on failure
        nextsample = rv[2] + (samples_per_frame * 300)
        retry -= 1
        
    if retry == 0 and framer.vbi['framenr'] is None:
        print("Unable to find first frame")
        return None

    retry = 5
    while np.abs(target - framer.vbi['framenr']) > tolerance and retry:
        offset = (samples_per_frame * (target - 1 - framer.vbi['framenr'])) 
        nextsample = rv[2] + offset
        rv = framer.readframe(infile, nextsample, CAV=iscav)
        print(framer.vbi)
        retry -= 1

    if np.abs(target - framer.vbi['framenr']) > tolerance:
        print("WARNING: seeked to frame ", framer.vbi['framenr'])
        
    return nextsample

fd = open(filename, 'rb')
lddecode_core.loader = load_packed_data_4_40

if args.seek >= 0:
    nextsample = findframe(fd, rfn, args.seek, firstframe * samples_per_frame)
else:
    nextsample = firstframe * samples_per_frame

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
