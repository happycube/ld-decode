:: Create FLAC file from 40msps 16-bit Signed .s16 file.
pushd %~dp0
echo Encoding Unsinged 16-bit to FLAC Compressed ... 
flac.exe -f "%~1" --threads 64 --best --sample-rate=40000 --sign=signed --channels=1 --endian=little --bps=16 "%~n1.flac"
echo Done. 
PAUSE