"""Unit tests for the CVBS 4fsc lattice math and position resampler."""

from fractions import Fraction

import numpy as np
import pytest

from lddecode.cvbs import (
    PAL_FRAME_SAMPLES, PAL_FRAME_LINES, PAL_SAMPLES_PER_LINE,
    pal_line_lattice, pal_lattice_positions,
)


def test_pal_frame_sample_count_exact():
    lat = pal_line_lattice()
    assert len(lat) == PAL_FRAME_LINES
    assert sum(n for _, n, _ in lat) == PAL_FRAME_SAMPLES
    # contiguous coverage
    for k in range(1, PAL_FRAME_LINES):
        assert lat[k][0] == lat[k - 1][0] + lat[k - 1][1]


def test_pal_line_counts_1135_or_1136():
    lat = pal_line_lattice()
    counts = [n for _, n, _ in lat]
    assert set(counts) == {1135, 1136}
    # exactly 4 long lines per frame: 625*1135 + 4 = 709379
    assert counts.count(1136) == 4


def test_pal_phase_slip_is_4_per_frame():
    """The lattice phase advances by exactly 4/625 sample per line and
    returns to zero after each frame (the spec's 0.0064 samples/line /
    4 samples/frame slip)."""
    spl = PAL_SAMPLES_PER_LINE
    lat = pal_line_lattice(2 * PAL_FRAME_LINES)  # two frames
    for k, (j0, n, phase) in enumerate(lat):
        exact = (Fraction(j0) - k * spl)  # in [0,1)
        assert 0 <= exact < 1
        assert phase == pytest.approx(float(exact), abs=1e-12)
        # phase progression: -4/625 per line, mod 1
        if k:
            prev = Fraction(lat[k - 1][0]) - (k - 1) * spl
            assert (exact - prev) % 1 == Fraction(-4, 625) % 1
    # frame boundary: sample index at line 625 is exactly PAL_FRAME_SAMPLES,
    # phase identical to line 0 (lattice repeats at frame rate)
    assert lat[PAL_FRAME_LINES][0] == PAL_FRAME_SAMPLES
    assert lat[PAL_FRAME_LINES][2] == lat[0][2] == 0.0


def test_pal_lattice_positions_uniform_step():
    pos = pal_lattice_positions(PAL_FRAME_SAMPLES + 1)
    # spans exactly 625 lines over one frame
    assert pos[0] == 0.0
    assert pos[-1] == pytest.approx(625.0, abs=1e-9)
    # per-line 0H drift: position index nearest each integer line time
    # advances by 1135.0064 samples/line on average
    steps = np.diff(pos)
    # float64 rounding on values up to 625 bounds the step jitter; the
    # integer-exact math lives in pal_line_lattice, tested above
    assert np.allclose(steps, 625.0 / 709379.0, rtol=0, atol=1e-10)


def test_scale_positions_reconstructs_sinusoid():
    from importlib.resources import files
    from lddecode.dsp import scale_positions

    lut = np.load(files("lddecode") / "sinc_lut.npz")["downscale_sinc_lut"]

    n_in = 4096
    freq = 0.037  # cycles/sample, well within band
    t_in = np.arange(n_in)
    buf = np.sin(2 * np.pi * freq * t_in).astype(np.float32)

    # resample onto an irrational-ish non-integer step, away from edges
    step = 1135.0064 / 1135.0  # the PAL slip ratio itself
    locs = (100.0 + np.arange(3500) * step).astype(np.float64)
    out = np.zeros(len(locs), dtype=np.float32)
    wow = np.ones(len(locs), dtype=np.float64)

    scale_positions(buf, out, locs, wow, lut, 1135.0)

    expected = np.sin(2 * np.pi * freq * locs)
    err = np.abs(out - expected)
    assert np.max(err) < 5e-3
