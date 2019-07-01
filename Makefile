# Makefile for the Software Decode of Laserdiscs project

# Note: Targets do not include auto-generated .h files, which means
#       that make clean will not remove them.
TARGETS=cx

CFLAGS=-g -O2 -fno-omit-frame-pointer -march=native -Itools/ld-chroma-decoder

all: $(TARGETS)

clean:
	rm -f $(TARGETS)

cx: cx-expander.cxx deemp.h
	clang++ -std=c++11  -Wall $(CFLAGS) -o cx cx-expander.cxx

deemp.h: filtermaker.py
	python3 filtermaker.py > deemp.h

