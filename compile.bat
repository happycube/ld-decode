@echo off
mkdir build
cd build
cmake -G "MinGW Makefiles" ../  -DCMAKE_BUILD_TYPE=Release
make -j 3
move /y E:\Dev\git\ld-disc-stacker_enhance\ld-decode\build\tools\ld-disc-stacker\ld-disc-stacker.exe E:\Dev\git\ld-decode-tools-build-template\ld-disc-stacker.exe
pause