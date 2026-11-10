"""lddecode - software-defined decoding of LaserDisc RF captures.

Reads __version__ from the generated version file and names the package's
modules in __all__.  utils_plotting, the notebook helpers, needs IPython and
PIL, which are not dependencies of the package, so it is left out of __all__
to keep "from lddecode import *" working in a normal install; import it by
name.
"""

import os

# Read PEP-440 compliant version from version file
# Format: base_version[+local.identifiers]
# Examples: 7.2.0, 7.2.0+git.abc123, 7.2.0+branch.main.abc123.dirty
try:
    _version_file = os.path.join(os.path.dirname(__file__), "version")
    if os.path.exists(_version_file):
        with open(_version_file, 'r') as f:
            __version__ = f.read().strip()
    else:
        __version__ = "unknown"
except Exception:
    __version__ = "unknown"

__all__ = [
    "audio",
    "commpy_filters",
    "core",
    "decoder",
    "dsp",
    "efm_demod",
    "efm_pll",
    "efm_score",
    "fdls",
    "field",
    "fft8",
    "fileio",
    "filters",
    "params",
    "profiling",
    "pulses",
    "rfdecode",
    "utils",
    "utils_logging",
    "__version__",
]
