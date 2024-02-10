:: Scan for and index VBI data inside Luma TBC file and update .JSON file.
echo Decoding VBI Data...
"ld-process-vbi.exe" "%~1"
echo Done. 
PAUSE