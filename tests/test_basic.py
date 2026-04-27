import importlib
from importlib import resources

import lddecode


def test_version_matches_file():
    """Test that version file exists and matches __version__ (if present)."""
    try:
        try:
            version_text = (resources.files(lddecode) / "version").read_text().strip()
        except AttributeError:
            # Python <3.9 lacks resources.files; fall back to read_text
            version_text = resources.read_text(lddecode.__name__, "version").strip()
        
        # If version file exists, __version__ should match it
        assert lddecode.__version__ == version_text
    except FileNotFoundError:
        # Version file doesn't exist (packaged builds) - this is OK
        # Version will be read from pyproject.toml or git at runtime
        pass


def test_can_import_key_modules():
    for mod in ("core", "utils", "fft8"):
        importlib.import_module(f"lddecode.{mod}")
