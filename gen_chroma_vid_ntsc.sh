#!/bin/sh

rm -f $1.avi
rm -f $1chroma.avi
rm -f $1_doc.tbc
rm -f $1_doc.tbc.json
rm -f $1_doc.tbcc
rm -f $1_doc.tbcc.json
ld-dropout-correct $1.tbc $1_doc.tbc
ld-dropout-correct -i $1.tbcc $1_doc.tbcc
ld-chroma-decoder -f mono $1_doc.tbc $1.rgb
ld-chroma-decoder -f ntsc2d $1_doc.tbcc $1chroma.rgb

ffmpeg -f rawvideo -r 25 -pix_fmt rgb48 -s 760x488 -i $1chroma.rgb -r 25 -pix_fmt rgb48 -s 760x488 -i $1.rgb -filter_complex "[0:v]format=yuv444p[0v];[1:v]format=yuv444p[1v];[0v][1v]mergeplanes=0x100102:yuv444p[v]" -map "[v]" -c:v ffv1 -pix_fmt yuv444p -an $1.avi

#ffmpeg -f rawvideo -r 25 -pix_fmt rgb48 -s 760x488 -i $1.rgb -c:v huffyuv -pix_fmt yuv422p -an $1.avi
#ffmpeg -f rawvideo -r 25 -pix_fmt rgb48 -s 760x488 -i $1chroma.rgb -c:v huffyuv -an -pix_fmt yuv422p $1chroma.avi
