import importlib
from importlib import resources

import lddecode


def test_version_matches_file():
    try:
        version_text = (resources.files(lddecode) / "version").read_text().strip()
    except AttributeError:
        # Python <3.9 lacks resources.files; fall back to read_text
        version_text = resources.read_text(lddecode.__name__, "version").strip()

    assert lddecode.__version__ == version_text


def test_can_import_key_modules():
    for mod in ("core", "utils", "fft8"):
        importlib.import_module(f"lddecode.{mod}")
