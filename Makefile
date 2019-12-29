# Makefile for the Software Decode of Laserdiscs project

# Note: Targets do not include auto-generated .h files, which means
#       that make clean will not remove them.
TARGETS=ld-ldf-reader

CFLAGS=-g -O2 -fno-omit-frame-pointer -march=native -Itools/library/filter

all: $(TARGETS)

clean:
	rm -f $(TARGETS)

install:
	cp ld-ldf-reader /usr/local/bin

deemp.h: filtermaker.py
	python3 filtermaker.py > deemp.h

ld-ldf-reader: ld-ldf-reader.c
	clang -o ld-ldf-reader ld-ldf-reader.c -Wno-deprecated-declarations -lavcodec -lavutil -lavformat -O2


