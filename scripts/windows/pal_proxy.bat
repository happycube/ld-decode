:: Create Progressive MP4 AVC Proxy file for web usage. 
pushd %~dp0
echo Encoding Input to AVC Proxy... 
ffmpeg.exe -i "%~1" -c:a aac -b:a 320k -c:v libx264 -b:v 10M -maxrate 20M -bufsize 2M -vf bwdif=1:-1:0,format=yuv420p,scale=720:576 -tune grain -aspect 4:3 -color_range tv -color_primaries bt470bg -colorspace bt470bg -color_trc bt709 "%~n1.mp4"
echo Done. 
PAUSE