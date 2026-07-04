"""CVBS 4fsc output (see cvbs-file-format-specification/).

Lattice math for the spec's Video Standard Presets.  The writer that uses
these lives in CVBSWriter (added with the output mode).

The PAL 4fsc lattice is NOT line-locked: fsc = (1135/4 + 1/625) * fH, so a
line averages 1135.0064 samples, the sampling structure slips 4 samples per
625-line frame, and the normative sample count exists only at frame level
(709,379 samples).  All lattice arithmetic here is integer-exact — no float
accumulation across lines or frames.
"""

from fractions import Fraction

from .params import CVBSParams_NTSC, CVBSParams_PAL

PAL_FRAME_SAMPLES = CVBSParams_PAL["frame_samples"]      # 709379
PAL_FRAME_LINES = CVBSParams_PAL["frame_lines"]          # 625
PAL_SAMPLES_PER_LINE = Fraction(*CVBSParams_PAL["samples_per_line"])

NTSC_FRAME_SAMPLES = CVBSParams_NTSC["frame_samples"]    # 477750
NTSC_FRAME_LINES = CVBSParams_NTSC["frame_lines"]        # 525
NTSC_SAMPLES_PER_LINE = CVBSParams_NTSC["samples_per_line"]  # 910


def _ceil_frac(f):
    return -(-f.numerator // f.denominator)


def pal_line_lattice(nlines=PAL_FRAME_LINES):
    """Per-line lattice structure of one PAL 4fsc frame.

    Returns a list of (first_sample_index, sample_count, start_phase) per
    line, where start_phase is the fractional lattice offset of the line's
    first sample past the line's start time, in lattice-sample units [0, 1).
    Integer-exact: sample counts are 1135 or 1136 and sum to exactly
    PAL_FRAME_SAMPLES over a full frame (four lines per frame carry the
    extra sample).
    """
    out = []
    spl = PAL_SAMPLES_PER_LINE
    for k in range(nlines):
        t0 = k * spl
        t1 = (k + 1) * spl
        j0 = _ceil_frac(t0)
        j1 = _ceil_frac(t1)
        out.append((j0, j1 - j0, float(j0 - t0)))
    return out


def pal_lattice_positions(n_samples, origin_lines=Fraction(0)):
    """Positions of PAL lattice samples in *line-time* units.

    Sample j of the frame lattice sits at time (origin_lines + j/spl)
    lines, where spl = 709379/625.  Returned as a float64 numpy array for
    feeding a field's expected-time -> input-position spline.  The uniform
    step is 625/709379 lines — the non-orthogonality is entirely captured
    by that ratio not being 1/1135.
    """
    import numpy as np

    step = 625.0 / 709379.0
    return float(origin_lines) + np.arange(n_samples, dtype=np.float64) * step
