These scripts assume a working installation and are for building release binaries via PyInstaller or python-appimage.  
They are hardcoded to run from the project root, eg. `scripts/ci/*`.
**These do not build vhs-decode.**

## Local pre-GitHub validation
Run unit tests plus the real-data HiFi threading regression check before opening/updating a PR:

    VHSDECODE_HIFI_RF_SAMPLE=/path/to/real/sample.flac python3 scripts/ci/local-validate-tests.py --require-hifi-real-data

Optional knobs:

    python3 scripts/ci/local-validate-tests.py --help
**These do not build vhs-decode.**