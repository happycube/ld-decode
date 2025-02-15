:: Create wave file from raw .pcm file from ld-decode (analog audio track)
pushd %~dp0
echo Remuxing PCM to WAV container... 
ffmpeg -f s16le -ac 2 -ar 44100 -i "%~1" "%~n1.wav"
echo Done.
PAUSE