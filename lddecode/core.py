"""Backward-compatibility shim.

core.py was split into params.py, rfdecode.py, audio.py, field.py and
decoder.py.  This module re-exports the historical public surface so that
`from lddecode.core import X` and `from lddecode.core import *` keep working.
Names are re-exported by reference, so in-place mutation of e.g.
FilterParams_PAL through this module still affects the decoder.
"""

import traceback  # noqa: F401

from . import efm_pll  # noqa: F401
from .profiling import profile  # noqa: F401

from .params import (  # noqa: F401
    BLOCKSIZE, FilterParams_NTSC, FilterParams_NTSC_lowband, FilterParams_PAL,
    FilterParams_PAL_lowband, SysParams_NTSC, SysParams_PAL, calclinelen,
)
from .rfdecode import RFDecode  # noqa: F401
from .audio import (  # noqa: F401
    _downscale_audio_compute_locs_and_swow, _downscale_audio_to_output,
    downscale_audio,
)
from .field import (  # noqa: F401
    EQPL1, EQPL2, Field, FieldAnchor, FieldNTSC, FieldPAL, HSYNC, VSYNC,
)
from .decoder import LDdecode  # noqa: F401

# Historical wildcard surface: core.py used to import these from utils and
# they leaked through `from lddecode.core import *`.
from .utils import (  # noqa: F401
    FieldInfo, Pulse, StridedCollector, _dropout_unflag_sync, ac3_pipe,
    angular_mean_helper, build_hilbert, calczc, clb_findbursts, compute_mtf,
    dsa_rescale_and_clip, emphasis_iir, fft_determine_slices, fft_do_slice,
    filtfft, findpulses, gen_bpf_supergauss, genwave, hz_to_output_array,
    inrange, ldf_pipe, n_orgt, n_ornotrange, n_ornotrange_scalar, nb_abs,
    nb_absmax, nb_max, nb_mean, nb_median, nb_min, nb_round, nb_std,
    phase_distance, polar2z, rms, roundfloat, scale, scale_field, sqsum,
    unwrap_hilbert,
)


def __getattr__(name):
    # `core.logger` used to be a module global rebound by LDdecode.__init__;
    # it now lives in utils_logging.  Forward attribute access for
    # backward compatibility (PEP 562).
    if name == "logger":
        from . import utils_logging as _logs
        return _logs.logger
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
