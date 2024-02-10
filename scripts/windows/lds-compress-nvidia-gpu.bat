@echo off
title Compressing : %~n1
"ld-lds-converter.exe" -i "%~1" -u -r | C:\ld-tools-suite-windows\CUETools.FLACCL.cmd.exe -11 -o "%~dp1%~n1.ldf" --lax --ignore-chunk-sizes --task-size 16 --fast-gpu -
echo Done. 
PAUSE