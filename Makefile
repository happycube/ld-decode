### Top-level Makefile for ld-decode ###

# Prefix into which ld-decode will be installed.
# This must be set both at build and install time. If you're using a
# non-default directory here, make sure that Python knows to look in there for
# modules (e.g. by setting PYTHONPATH in your environment).
prefix ?= /usr/local

# Staging dir for building distribution packages.
# If you're building packages, it may make more sense to build the Python and
# Qt parts using your distribution's tools, rather than using this Makefile
# (but don't forget the helpers!).
DESTDIR =

# Tools you might want to override
PYTHON3 ?= python3
QMAKE ?= qmake

### Get the current git commit information ###
BRANCH = $(shell git rev-parse --abbrev-ref HEAD)
COMMIT = $(shell git rev-parse --short HEAD)

### Targets for users to invoke ###

all: build-helpers build-python build-tools
install: install-helpers install-python install-tools
clean: clean-helpers clean-python clean-tools

.PHONY: all build-helpers build-python build-tools
.PHONY: install install-helpers install-python install-tools
.PHONY: clean clean-helpers clean-python clean-tools

### Helper programs used by ld-decode ###

helpers = ld-ldf-reader

build-helpers: $(helpers)

ld-ldf-reader: ld-ldf-reader.c
	$(CC) -O2 -Wno-deprecated-declarations -o $@ $< -lavcodec -lavutil -lavformat

install-helpers:
	install -d "$(DESTDIR)$(prefix)/bin"
	install -m755 $(helpers) "$(DESTDIR)$(prefix)/bin"

clean-helpers:
	rm -f $(helpers)

### Python modules and scripts ###

build-python:
	$(PYTHON3) setup.py build

install-python:
	if [ -z "$(DESTDIR)" ]; then \
		$(PYTHON3) setup.py install --prefix="$(prefix)"; \
	else \
		$(PYTHON3) setup.py install --root="$(DESTDIR)" --prefix="$(prefix)"; \
	fi

clean-python:
	$(PYTHON3) setup.py clean -a

### Qt-based tools ###

build-tools:
	cd tools && $(QMAKE) -recursive PREFIX="$(prefix)" BRANCH="$(BRANCH)" COMMIT="$(COMMIT)"
	$(MAKE) -C tools

install-tools:
	$(MAKE) -C tools install INSTALL_ROOT="$(DESTDIR)"

clean-tools:
	$(MAKE) -C tools clean

### Tests ###

# To run the test suite, clone the ld-decode-testdata repo as "testdata",
# and do "make check".

TESTCASES = \
	check-library-filter \
	check-library-metadata \
	check-library-vbidecoder \
	check-ld-cut-ntsc \
	check-ld-cut-pal \
	check-decode-ntsc-cav \
	check-decode-ntsc-clv \
	check-decode-pal-cav \
	check-decode-pal-clv

check: $(TESTCASES)
.PHONY: check $(TESTCASES)

TESTING = printf '\n\#\# Testing %s\n\n'

check-library-filter:
	@$(TESTING) "library: filter"
	@tools/library/filter/testfilter/testfilter

check-library-metadata:
	@$(TESTING) "library: metadata"
	@tools/library/tbc/testmetadata/testmetadata

check-library-vbidecoder:
	@$(TESTING) "library: vbidecoder"
	@tools/library/tbc/testvbidecoder/testvbidecoder

check-ld-cut-ntsc:
	@$(TESTING) "ld-cut (NTSC)"
	@scripts/test-decode \
		--cut-seek 30255 \
		--cut-length 4 \
		--expect-frames 4 \
		--expect-vbi 9151563,15925845,15925845 \
		testdata/ve-snw-cut.lds

check-ld-cut-pal:
	@$(TESTING) "ld-cut (PAL)"
	@scripts/test-decode \
		--pal \
		--cut-seek 760 \
		--cut-length 4 \
		--expect-frames 4 \
		--expect-vbi 9152512,15730528,15730528 \
		testdata/pal/ggv-mb-1khz.ldf

check-decode-ntsc-cav:
	@$(TESTING) "full decode (NTSC CAV)"
	@scripts/test-decode \
		--decoder mono --decoder ntsc2d --decoder ntsc3d \
		--expect-frames 29 \
		--expect-bpsnr 43.3 \
		--expect-vbi 9151563,15925840,15925840 \
		--expect-efm-samples 40572 \
		testdata/ve-snw-cut.lds

check-decode-ntsc-clv:
	@$(TESTING) "full decode (NTSC CLV)"
	@scripts/test-decode \
		--expect-frames 4 \
		--expect-bpsnr 37.6 \
		--expect-vbi 9167913,15785241,15785241 \
		testdata/issues/176/issue176.lds

check-decode-pal-cav:
	@$(TESTING) "full decode (PAL CAV)"
	@scripts/test-decode --pal \
		--decoder mono --decoder pal2d --decoder transform2d --decoder transform3d \
		--expect-frames 4 \
		--expect-bpsnr 38.4 \
		--expect-vbi 9151527,16065688,16065688 \
		--expect-efm-samples 5292 \
		testdata/pal/jason-testpattern.lds

check-decode-pal-clv:
	@$(TESTING) "full decode (PAL CLV)"
	@scripts/test-decode --pal --no-efm \
		--expect-frames 9 \
		--expect-bpsnr 30.3 \
		--expect-vbi 0,8449774,8449774 \
		testdata/pal/kagemusha-leadout-cbar.ldf

### Generated files, not updated automatically ###

tools/library/filter/deemp.h: scripts/filtermaker
	$(PYTHON3) scripts/filtermaker >$@
