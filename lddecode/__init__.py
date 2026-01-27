#!/usr/bin/python3
# Initialisation for the lddecode package.

from importlib import resources as _resources

try:
    _version_path = _resources.files(__package__) / "version"
    __version__ = _version_path.read_text().strip()
except AttributeError:
    # Python <3.9 lacks resources.files; fall back to read_text
    __version__ = _resources.read_text(__package__, "version").strip()
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
