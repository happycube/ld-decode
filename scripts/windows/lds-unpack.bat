:: Unpack 10-bit DdD Capture .lds to 16-bit Singed .s16 file.
echo Unpacking 10-bit Packed Capture...
"ld-lds-converter.exe" --debug --unpack --input "%~1" --output "%~n1.s16"
echo Done.
PAUSE

