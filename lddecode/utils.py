"""Backward-compatibility shim.

The helpers formerly here now live in fileio.py, filters.py, pulses.py and
dsp.py.  This module re-exports the full historical public surface so that
`from lddecode.utils import X` and `from lddecode.utils import *` keep working.
"""

import traceback  # noqa: F401  (historically re-exported; core imported it from here)

from .profiling import profile  # noqa: F401

from .fileio import (  # noqa: F401
    LoadFFmpeg, LoadLDF, ac3_pipe, ffmpeg_pipe, ldf_pipe,
    load_packed_data_3_32, load_packed_data_4_40, load_unpacked_data,
    load_unpacked_data_float32, load_unpacked_data_s16, load_unpacked_data_u16,
    load_unpacked_data_u8, make_loader, parse_frequency, unpack_data_4_40,
)
from .filters import (  # noqa: F401
    build_hilbert, calczc, calczc_do, calczc_findfirst, emphasis_iir,
    fft_determine_slices, fft_do_slice, filtfft, gen_bpf_supergauss, inrange,
    overlap_save_fft, overlap_save_ifft, polar2z, sqsum, supergauss,
    unwrap_hilbert,
)
from .pulses import (  # noqa: F401
    Pulse, _dropout_unflag_sync, _to_pulses_list, clb_findbursts, findareas,
    findpulses, findpulses_numba_raw,
)
from .dsp import (  # noqa: F401
    FieldInfo, LRUupdate, StridedCollector, angular_mean_helper, compute_mtf,
    db_to_lev, distance_from_round, dsa_rescale_and_clip, genwave, get_fmax,
    hz_to_output_array, lev_to_db, n_orgt, n_ornotrange, n_ornotrange_scalar,
    nb_abs, nb_absmax, nb_max, nb_mean, nb_median, nb_min, nb_mul, nb_round,
    nb_std, phase_distance, rms, roundfloat, scale, scale_field,
    sinc_phase_count, sinc_tap_count,
)

# Non-callable module-level values that historically leaked through
# `from lddecode.utils import *`; preserved for surface compatibility.
from .fileio import frequency_suffixes  # noqa: F401
