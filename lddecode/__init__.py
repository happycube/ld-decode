#!/usr/bin/python3
# Initialisation for the lddecode package.

import os

# Read PEP-440 compliant version from version file
# Format: base_version[+local.identifiers]
# Examples: 7.2.0, 7.2.0+git.abc123, 7.2.0+branch.main.abc123.dirty
def _fallback_version() -> str:
    try:
        from vhsdecode._version import __version__ as pkg_version
        from vhsdecode._version import __commit_id__ as commit_id

        if commit_id:
            return f"vhs_decode:{commit_id}"
        if pkg_version:
            return str(pkg_version)
    except Exception:
        pass
    return "unknown"

try:
    _version_file = os.path.join(os.path.dirname(__file__), "version")
    if os.path.exists(_version_file):
        with open(_version_file, 'r') as f:
            __version__ = f.read().strip() or _fallback_version()
    else:
        __version__ = _fallback_version()
except Exception:
    __version__ = _fallback_version()

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
