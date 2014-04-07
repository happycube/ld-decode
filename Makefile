all: ldd ldd10 ntsc ntsc10 comb audio

clean:
	rm -f ldd ntsc comb audio

audio: audio-decoder.cxx
	clang++ -std=c++11  -Wall -DNOSNAP -O3 -g -o audio audio-decoder.cxx

ldd: ld-decoder.cxx
	clang++ -std=c++11  -mavx -march=corei7-avx -Wall -DNOSNAP -O3 -g -o ldd ld-decoder.cxx

ldd10: ld-decoder-10.cxx
	clang++ -std=c++11  -mavx -march=corei7-avx -Wall -DNOSNAP -O3 -g -o ldd10 ld-decoder-10.cxx

ntsc10: ntsc.cxx
	clang++ -std=c++11  -Wall -D_NOSNAP -O3 -g -DDOWNSCALE -o ntsc10 ntsc.cxx

ntsc: ntsc.cxx
	clang++ -std=c++11  -Wall -D_NOSNAP -O3 -g -o ntsc ntsc.cxx

ntsc4: ntsc-4fsc.cxx
	clang++ -std=c++11  -Wall -D_NOSNAP -O3 -g -o ntsc4 ntsc-4fsc.cxx

comb4: comb-4fsc.cxx
	clang++ -std=c++11  -Wall -D_NOSNAP -O3 -g -o comb4 comb-4fsc.cxx

test:
	./ldd snw.raw | ./ntsc - | ./comb - > snw.rgb
	convert -size 1488x480 -depth 8 rgb:snw.rgb -resize 640x480\! snw.png

