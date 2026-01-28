#!/usr/bin/python3
# Initialisation for the lddecode package.

from importlib import resources as _resources

try:
    _version_path = _resources.files(__package__) / "version"
    __version__ = _version_path.read_text().strip()
except (AttributeError, FileNotFoundError):
    # Python <3.9 lacks resources.files or version file doesn't exist
    try:
        __version__ = _resources.read_text(__package__, "version").strip()
    except FileNotFoundError:
        # Version file not present (packaged builds); will be read from pyproject.toml by utils module
        __version__ = "unknown"
except Exception:
    # Ensure attribute exists even if the version file cannot be read
    __version__ = "unknown"

__all__ = [
    "audio",
    "commpy_filters",
    "core",
    "efm_pll",
    "fdls",
    "fft8",
    "utils",
    "utils_logging",
    "utils_plotting",
    "__version__",
]
