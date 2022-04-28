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
QMAKE ?= qmake -qt5

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

### Generated files, not updated automatically ###

tools/library/filter/deemp.h: scripts/filtermaker
	$(PYTHON3) scripts/filtermaker >$@
