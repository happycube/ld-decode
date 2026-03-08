import os
import PyInstaller.__main__
from pyinstaller_versionfile import create_versionfile

print("Building Windows binary")

# Make sure build directory exists since we place versionfile.txt there.
build_path = ".\\build"
if not os.path.isdir(build_path):
    os.makedirs(build_path)

create_versionfile(
    output_file="build\\versionfile.txt",
    product_name="vhs-decode",
    original_filename="decode.exe",
    file_description="Software defined VHS decoder",
    # version=version,
)

PyInstaller.__main__.run(
    [
        "decode.py",
        "--collect-all",
        "vhsd_rust",
        "--add-data",
        "vhsdecode/format_defs;vhsdecode/format_defs",
        "--collect-all",
        "PyQt6",
        "--collect-all",
        "numba",
        "--collect-all",
        "llvmlite",
        "--hidden-import",
        "vhsdecode.decode_launcher",
        "--hidden-import",
        "vhsdecode.main",
        "--hidden-import",
        "cvbsdecode.main",
        "--hidden-import",
        "lddecode.main",
        "--hidden-import",
        "vhsdecode.hifi.main",
        "--hidden-import",
        "filter_tune.filter_tune",
        "--hidden-import",
        "numba._dispatcher",
        "--hidden-import",
        "numba.core.runtime._nrt_python",
        "--icon",
        "assets\\icons\\vhs-decode.ico",
        "--version-file",
        "build\\versionfile.txt",
        "--onefile",
        "--name",
        "decode",
    ]
)
