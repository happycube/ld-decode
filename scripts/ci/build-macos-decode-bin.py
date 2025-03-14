import PyInstaller.__main__
import PyInstaller.utils.osx as osxutils
import plistlib
from pathlib import Path
from shutil import move

print("Building macOS binary version")

PyInstaller.__main__.run(
    [
        "decode.py",
        "--collect-submodules",
        "application",
        "--collect-all",
        "rocket_fft",
        "--add-data",
        "vhsdecode/format_defs:vhsdecode/format_defs",
        "--icon",
        "assets/icons/vhs-decode.icns",
        "--onefile",
        "--windowed",
        "--name",
        "vhs-decode",
    ]
)

move(r"dist/vhs-decode.app/Contents/MacOS/vhs-decode", r"dist/vhs-decode.app/Contents/MacOS/decode")

with Path("dist/vhs-decode.app/Contents/Info.plist").open(mode="rb+") as file:
    plist = plistlib.load(file)

    # update binary location
    plist["CFBundleExecutable"] = "decode"
    #plist["CFBundleShortVersionString"] = version
    file.seek(0)
    file.write(plistlib.dumps(plist))
    file.truncate()

# re-sign
osxutils.sign_binary("dist/vhs-decode.app", deep=True)