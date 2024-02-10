@echo off
title Compressing : %~n1
"ld-lds-converter.exe" -u -i "%~1" | ffmpeg -f s16le -ar 40k -ac 1 -i - -acodec flac -compression_level 11 -f ogg "%~dp1%~n1.ldf"
echo Done. 
PAUSE