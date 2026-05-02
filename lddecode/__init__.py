#!/usr/bin/python3
# Initialisation for the lddecode package.

import os
import sys
from pathlib import Path

# Read PEP-440 compliant version from version file
# Format: base_version[+local.identifiers]
# Examples: 7.2.0, 7.2.0+git.abc123, 7.2.0+branch.main.abc123.dirty
def _candidate_version_files() -> list[Path]:
    package_dir = Path(__file__).resolve().parent
    candidates = [package_dir / "version"]

    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        meipass_path = Path(meipass)
        candidates.append(meipass_path / "lddecode" / "version")
        candidates.append(meipass_path / "Resources" / "lddecode" / "version")

    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).resolve()
        candidates.append(exe_path.parent / "lddecode" / "version")
        candidates.append(exe_path.parent.parent / "Resources" / "lddecode" / "version")
        candidates.append(exe_path.parent.parent.parent / "Resources" / "lddecode" / "version")

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _read_version_file() -> str:
    for version_file in _candidate_version_files():
        try:
            if version_file.is_file():
                version_text = version_file.read_text(encoding="utf-8").strip()
                if version_text:
                    return version_text
        except Exception:
            continue
    return ""


def _fallback_version() -> str:
    env_version = os.environ.get("VERSION", "").strip()
    if env_version:
        return env_version
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


__version__ = _read_version_file() or _fallback_version()

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
