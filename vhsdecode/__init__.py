#!/usr/bin/python3
# Initialisation for the vhsdecode package.

import sys
import os

try:
    from llvmlite.binding import load_library_permanently
except Exception:
    load_library_permanently = None

# load intel intrinsics library for numba
ON_LINUX = sys.platform.startswith("linux")
ON_DARWIN = sys.platform.startswith("darwin")
ON_WINDOWS = sys.platform.startswith("win")

os_lib_dir = os.path.join(sys.prefix, *(["Library", "bin"] if ON_WINDOWS else ["lib"]))

try:
    if (
        load_library_permanently is not None
        and not getattr(sys, "frozen", False)
        and 32 << bool(sys.maxsize >> 32) == 64
    ):
        _nb_svml_dir = os.environ.get("NB_SVML_LIBS_DIR") or os_lib_dir
        _nb_loader = lambda so: load_library_permanently(os.path.join(_nb_svml_dir, so))

        if ON_LINUX:
            _nb_loader("libintlc.so.5")
            _nb_loader("libsvml.so")
        elif ON_DARWIN:
            _nb_loader("libintlc.dylib")
            _nb_loader("libsvml.dylib")
        elif ON_WINDOWS:
            _nb_loader("svml_dispmd")
except:
    pass
