all: cx tbc-pal tbc-ntsc ntsc4 audiog2 comb-ntsc comb-pal 

CFLAGS=-O3 
CFLAGS=-g -O2 -fno-omit-frame-pointer -march=native

OPENCV_LIBS=-lopencv_core -lopencv_highgui -lopencv_imgproc -lopencv_video

clean:
	rm -f cx tbc-pal tbc-ntsc ntsc4 audiog2 comb-ntsc comb-pal

cx: cx-expander.cxx deemp.h
	clang++ -std=c++11  -Wall $(CFLAGS) -o cx cx-expander.cxx

audiog2: audio-g2.cxx deemp.h
	clang++ -std=c++11  -Wall $(CFLAGS) -o audiog2 audio-g2.cxx

deemp.h: filtermaker.py
	python3.4 filtermaker.py > deemp.h

ntsc4: tbc-ntscx.cxx ld-decoder.h deemp.h
	#clang++ -std=c++11  -Wall $(CFLAGS) -DFSC4 -o ntsc4 tbc-ntsc.cxx
	clang++ -std=c++11  -Wall -g -DFSC4 -o ntsc4 tbc-ntscx.cxx

ntsc10: tbc-ntsc.cxx ld-decoder.h deemp.h
	clang++ -std=c++11  -Wall $(CFLAGS) -DFSC10 -o ntsc10 tbc-ntsc.cxx

tbc-pal: tbc-pal.cxx ld-decoder.h deemp.h
	clang++ -std=c++11  -g -Wall $(CFLAGS) -o tbc-pal tbc-pal.cxx

tbc-ntsc: tbc-ntsc.cxx ld-decoder.h deemp.h
	clang++ -std=c++11  -g -Wall $(CFLAGS) -o tbc-ntsc tbc-ntsc.cxx
#	cp tbc-ntsc ntsc
#	clang++ -std=c++11  -g -Wall -o ntsc tbc-ntsc.cxx

tbc-ntscx: tbc-ntscx.cxx ld-decoder.h deemp.h
	clang++ -std=c++11  -g -Wall $(CFLAGS) -o tbc-ntscx tbc-ntscx.cxx
#	clang++ -std=c++11  -g -Wall -o tbc-ntscx tbc-ntscx.cxx
	cp tbc-ntsc ntsc

tbc-ntsc-airspy: tbc-ntsc-airspy.cxx ld-decoder.h deemp.h
	clang++ -std=c++11  -g -Wall $(CFLAGS) -o tbc-ntsc-airspy tbc-ntsc-airspy.cxx
#	clang++ -std=c++11  -g -Wall -o tbc-ntscx tbc-ntscx.cxx

ntsc: tbc-ntscx

comb-ntsc: comb-ntsc.cxx deemp.h
	clang++ -lfann -std=c++11  -Wall $(CFLAGS) $(OPENCV_LIBS) -o comb-ntsc comb-ntsc.cxx
	cp comb-ntsc comb

comb-pal: comb-pal.cxx deemp.h
	clang++ -lfann -std=c++11  -Wall $(CFLAGS) $(OPENCV_LIBS) -o comb-pal comb-pal.cxx

comb-paln: comb-paln.cxx deemp.h
	clang++ -lfann -std=c++11  -Wall $(CFLAGS) $(OPENCV_LIBS) -o comb-paln comb-paln.cxx

comb: comb-ntsc

test:
	./ldd snw.raw | ./ntsc - | ./comb - > snw.rgb
	convert -size 1488x480 -depth 8 rgb:snw.rgb -resize 640x480\! snw.png

