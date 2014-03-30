all: ldd ntsc comb audio

clean:
	rm -f ldd ntsc comb audio

audio: audio-decoder.cxx
	clang++ -std=c++11  -Wall -DNOSNAP -O3 -g -o audio audio-decoder.cxx

ldd: ld-decoder.cxx
	clang++ -std=c++11  -mavx -march=corei7-avx -Wall -DNOSNAP -O3 -g -o ldd ld-decoder.cxx

ntsc: ntsc.cxx
	clang++ -std=c++11  -Wall -D_NOSNAP -O3 -g -o ntsc ntsc.cxx

comb: comb.cxx
	clang++ -std=c++11  -Wall -D_NOSNAP -O3 -g -o comb comb.cxx

