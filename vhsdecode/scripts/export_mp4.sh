#!/bin/bash

ffmpeg -i $1.mkv \
  -vf scale=in_color_matrix=bt601:out_color_matrix=bt709:648x488,bwdif=1:0:0 \
  -c:v libx264 -preset veryslow -crf 15 \
  -pixel_format yuv420p -color_primaries bt709 -color_trc bt709 -colorspace bt709 \
  -aspect 4:3 -c:a libopus -b:a 192k -strict -2 -movflags +faststart -y $1_lossy.mp4

