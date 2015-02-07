all: cx ntsc ntsc4 audiog2 comb 

CFLAGS=-O3 
CFLAGS=-O3 -mavx -march=corei7-avx

clean:
	rm -f ldd ntsc ntsc4 ntsc10 audiog2 comb 

cx: cx-expander.cxx deemp.h
	clang++ -std=c++11  -Wall $(CFLAGS) -o cx cx-expander.cxx

audiog2: audio-g2.cxx deemp.h
	clang++ -std=c++11  -Wall $(CFLAGS) -o audiog2 audio-g2.cxx

deemp.h: filtermaker.py
	python3.4 filtermaker.py > deemp.h

ntsc4: ntscg2.cxx ld-decoder.h deemp.h
	#clang++ -std=c++11  -Wall $(CFLAGS) -DFSC4 -o ntsc4 ntscg2.cxx
	clang++ -std=c++11  -Wall -g -DFSC4 -o ntsc4 ntscg2.cxx

ntsc10: ntscg2.cxx ld-decoder.h deemp.h
	clang++ -std=c++11  -Wall $(CFLAGS) -DFSC10 -o ntsc10 ntscg2.cxx

ntsc: ntscg2.cxx ld-decoder.h deemp.h
	clang++ -std=c++11  -g -Wall $(CFLAGS) -o ntsc ntscg2.cxx
#	clang++ -std=c++11  -g -Wall -o ntsc ntscg2.cxx

comb-ntsc: comb-ntsc.cxx deemp.h
	clang++ -std=c++11  -Wall $(CFLAGS) -o comb-ntsc comb-ntsc.cxx

comb: combg2.cxx deemp.h
	clang++ -std=c++11  -Wall $(CFLAGS) -o comb combg2.cxx

test:
	./ldd snw.raw | ./ntsc - | ./comb - > snw.rgb
	convert -size 1488x480 -depth 8 rgb:snw.rgb -resize 640x480\! snw.png

