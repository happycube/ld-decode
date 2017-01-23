all: cx tbc-pal tbc-ntsc ntsc4 comb-ntsc comb-pal 

CFLAGS=-g -O2 -fno-omit-frame-pointer -march=native
OPENCV_LIBS=-lopencv_core -lopencv_highgui -lopencv_imgproc -lopencv_video

clean:
	rm -f cx tbc-pal tbc-ntsc ntsc4 comb-ntsc comb-pal

cx: cx-expander.cxx deemp.h
	clang++ -std=c++11  -Wall $(CFLAGS) -o cx cx-expander.cxx

deemp.h: filtermaker.py
	python3 filtermaker.py > deemp.h

ntsc4: tbc-ntsc.cxx ld-decoder.h deemp.h
	clang++ -std=c++11  -Wall -g -DFSC4 -o ntsc4 tbc-ntsc.cxx

ntsc10: tbc-ntsc.cxx ld-decoder.h deemp.h
	clang++ -std=c++11  -Wall $(CFLAGS) -DFSC10 -o ntsc10 tbc-ntsc.cxx

tbc-pal: tbc-pal.cxx ld-decoder.h deemp.h
	clang++ -std=c++11  -g -Wall $(CFLAGS) -o tbc-pal tbc-pal.cxx

tbc-ntsc: tbc-ntsc.cxx ld-decoder.h deemp.h
	clang++ -std=c++11  -g -Wall $(CFLAGS) -o tbc-ntsc tbc-ntsc.cxx
#	cp tbc-ntsc ntsc
#	clang++ -std=c++11  -g -Wall -o ntsc tbc-ntsc.cxx

ntsc: tbc-ntsc

comb-ntsc: comb-ntsc.cxx deemp.h
	clang++ -lfann -std=c++11  -Wall $(CFLAGS) $(OPENCV_LIBS) -o comb-ntsc comb-ntsc.cxx
	cp comb-ntsc comb

comb-ntsc-eigen: comb-ntsc-eigen.cxx deemp.h
	clang++ -Ieigen -lfann -std=c++11  -Wall $(CFLAGS) $(OPENCV_LIBS) -o comb-ntsc-eigen comb-ntsc-eigen.cxx
#	cp comb-ntsc-euler comb

comb-pal: comb-pal.cxx deemp.h
	clang++ -lfann -std=c++11  -Wall $(CFLAGS) $(OPENCV_LIBS) -o comb-pal comb-pal.cxx

comb-paln: comb-paln.cxx deemp.h
	clang++ -lfann -std=c++11  -Wall $(CFLAGS) $(OPENCV_LIBS) -o comb-paln comb-paln.cxx

comb: comb-ntsc

test:
	./ldd snw.raw | ./ntsc - | ./comb - > snw.rgb
	convert -size 1488x480 -depth 8 rgb:snw.rgb -resize 640x480\! snw.png

