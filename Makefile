all: cx ldd ntsc ntsc4 audiog2 comb 

clean:
	rm -f ldd ntsc comb audio

cx: cx-expander.cxx deemp.h
	clang++ -std=c++11  -Wall -DNOSNAP -O3 -g -o cx cx-expander.cxx

audiog2: audio-g2.cxx deemp.h
	clang++ -std=c++11  -Wall -DNOSNAP -O3 -g -o audiog2 audio-g2.cxx

ldcur: ld-decoder-cur.cxx
	clang++ -std=c++11  -mavx -march=corei7-avx -Wall -DNOSNAP -O3 -g -o ldcur ld-decoder-cur.cxx

ldd: ld-decoder.cxx deemp.h ld-decoder.h
	clang++ -std=c++11  -mavx -march=corei7-avx -Wall -DNOSNAP -O3 -g -o ldd ld-decoder.cxx

deemp.h: filtermaker.py
	python3.4 filtermaker.py > deemp.h

ldd10: ld-decoder-10.cxx
	clang++ -std=c++11  -mavx -march=corei7-avx -Wall -DNOSNAP -O3 -g -o ldd10 ld-decoder-10.cxx

ntsc4: ntscg2.cxx ld-decoder.h deemp.h
	clang++ -std=c++11  -Wall -D_NOSNAP -DFSC4 -O3 -g -o ntsc4 ntscg2.cxx

ntsc10: ntscg2.cxx ld-decoder.h deemp.h
	clang++ -std=c++11  -Wall -D_NOSNAP -DFSC10 -O3 -g -o ntsc10 ntscg2.cxx

ntsc: ntscg2.cxx ld-decoder.h deemp.h
	clang++ -std=c++11  -Wall -march=corei7-avx -O3 -mavx -D_NOSNAP -fno-omit-frame-pointer -g -o ntsc ntscg2.cxx

comb: combg2.cxx deemp.h
	clang++ -std=c++11  -Wall -D_NOSNAP -O3 -g -o comb combg2.cxx

test:
	./ldd snw.raw | ./ntsc - | ./comb - > snw.rgb
	convert -size 1488x480 -depth 8 rgb:snw.rgb -resize 640x480\! snw.png

