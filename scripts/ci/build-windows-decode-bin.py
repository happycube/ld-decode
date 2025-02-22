import PyInstaller.__main__
from pyinstaller_versionfile import create_versionfile

print("Building Windows binary")

create_versionfile(
    output_file="build\\versionfile.txt",
    product_name="vhs-decode",
    original_filename="decode.exe",
    file_description="Software defined VHS decoder",
    #version=version,
)

PyInstaller.__main__.run(
    [
        "decode.py",
        "--collect-submodules",
        "application",
        "--collect-all",
        "rocket_fft",
        "--collect-all",
        "icc_rt",
        "--add-data",
        "vhsdecode/format_defs:vhsdecode/format_defs",
        "--icon",
        "assets\\icons\\vhs-decode.ico",
        "--version-file",
        "build\\versionfile.txt",
        "--onefile",
        "--name",
        "decode",
    ]
)