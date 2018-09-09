# Makefile for the Software Decode of Laserdiscs project

# Note: Targets do not include auto-generated .h files, which means
#       that make clean will not remove them.
TARGETS=cx comb-ntsc comb-pal ddpack ddunpack #tbc

CFLAGS=-g -O2 -fno-omit-frame-pointer -march=native
OPENCV_LIBS=-lopencv_core -lopencv_highgui -lopencv_imgproc -lopencv_video

# Define the directory for the TBC Qt app (relative to this makefile)
TBCAPP=./app/tbc/

all: $(TARGETS)

clean:
	rm -f $(TARGETS)
#	$(MAKE) -C $(TBCAPP) clean

ddpack: ddpack.c
	gcc -std=c99 -O2 -o ddpack ddpack.c

ddunpack: ddunpack.c
	gcc -std=c99 -O2 -o ddunpack ddunpack.c

cx: cx-expander.cxx deemp.h
	clang++ -std=c++11  -Wall $(CFLAGS) -o cx cx-expander.cxx

deemp.h: filtermaker.py
	python3 filtermaker.py > deemp.h

comb-ntsc: comb-ntsc.cxx deemp.h
	clang++ -lfann -std=c++11  -Wall $(CFLAGS) $(OPENCV_LIBS) -o comb-ntsc comb-ntsc.cxx
	cp comb-ntsc comb

comb-pal: comb-pal.cxx deemp.h
	clang++ -lfann -std=c++11  -Wall $(CFLAGS) $(OPENCV_LIBS) -o comb-pal comb-pal.cxx

comb: comb-ntsc

