all: cx tbc-pal tbc-ntsc ntsc4 audiog2 comb-ntsc 

CFLAGS=-O3 
CFLAGS=-g -O2 -fno-omit-frame-pointer -mavx -march=corei7-avx

OPENCV_LIBS=-lopencv_core -lopencv_highgui -lopencv_imgproc -lopencv_video

clean:
	rm -f ldd ntsc ntsc4 ntsc10 audiog2 comb 

cx: cx-expander.cxx deemp.h
	clang++ -std=c++11  -Wall $(CFLAGS) -o cx cx-expander.cxx

audiog2: audio-g2.cxx deemp.h
	clang++ -std=c++11  -Wall $(CFLAGS) -o audiog2 audio-g2.cxx

deemp.h: filtermaker.py
	python3.4 filtermaker.py > deemp.h

ntsc4: tbc-ntsc.cxx ld-decoder.h deemp.h
	#clang++ -std=c++11  -Wall $(CFLAGS) -DFSC4 -o ntsc4 tbc-ntsc.cxx
	clang++ -std=c++11  -Wall -g -DFSC4 -o ntsc4 tbc-ntsc.cxx

ntsc10: tbc-ntsc.cxx ld-decoder.h deemp.h
	clang++ -std=c++11  -Wall $(CFLAGS) -DFSC10 -o ntsc10 tbc-ntsc.cxx

tbc-pal: tbc-pal.cxx ld-decoder.h deemp.h
	clang++ -std=c++11  -g -Wall $(CFLAGS) -o tbc-pal tbc-pal.cxx

tbc-ntsc: tbc-ntsc.cxx ld-decoder.h deemp.h
	clang++ -std=c++11  -g -Wall $(CFLAGS) -o tbc-ntsc tbc-ntsc.cxx
	cp tbc-ntsc ntsc
#	clang++ -std=c++11  -g -Wall -o ntsc tbc-ntsc.cxx

comb-ntsc: comb-ntsc.cxx deemp.h
	clang++ -lfann -std=c++11  -Wall $(CFLAGS) $(OPENCV_LIBS) -o comb-ntsc comb-ntsc.cxx
	cp comb-ntsc comb

test:
	./ldd snw.raw | ./ntsc - | ./comb - > snw.rgb
	convert -size 1488x480 -depth 8 rgb:snw.rgb -resize 640x480\! snw.png

