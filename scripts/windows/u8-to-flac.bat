:: Create FLAC file from 40msps 8-bit Unsigned .u8 file.
pushd %~dp0
echo Encoding Unsinged 16-bit to FLAC Compressed ... 
flac.exe -f "%~1" --threads 64 --best --sample-rate=40000 --sign=unsigned --channels=1 --endian=little --bps=8 "%~n1.flac"
echo Done. 
PAUSE