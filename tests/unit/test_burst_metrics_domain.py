"""
test_burst_metrics_domain - burst measurements are independent of sample domain

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

burst_metrics.py reads both .cvbs (normative 10-bit samples) and legacy .tbc
(16-bit samples) through video_common.load_video.  The two domains differ by
roughly a factor of 64, so every measurement it reports has to be a ratio
against the capture's own out_scale; anything left in raw sample units would
read 64x wrong on one of the two inputs.

Fields are synthesised here, so no capture file is needed.
"""

import numpy as np
import pytest

from burst_metrics import (
    BURST_DURATION_US,
    BURST_LINE,
    BURST_START_US,
    measure_burst,
    measure_burst_3d,
)
from video_common import CaptureParams, VideoField

pytestmark = [pytest.mark.unit, pytest.mark.decode]

RECORD = {"field_phase_id": 1, "is_first_field": True, "field_id": 0}


def synthetic_field(system, blanking, white, burst_ire, seed=12345):
    """A field whose line 19 burst window holds a subcarrier of a known size.

    blanking/white set the sample domain: pass the 10-bit presets for a .cvbs
    and 16-bit values for a .tbc.  The waveform is identical in IRE either
    way, so a domain-independent measurement returns the same number for both.
    """
    params = CaptureParams.for_cvbs(system)
    params.blanking_16b_ire = blanking
    params.white_16b_ire = white
    params.black_16b_ire = blanking
    params.out_scale = (white - blanking) / 100.0

    field = VideoField(
        np.zeros(params.field_samples, dtype=np.float64), 0, params, RECORD)

    # fs/4 subcarrier of burst_ire amplitude on the blanking pedestal, with a
    # seeded noise floor so the RMS is not a degenerate exact value.
    rng = np.random.default_rng(seed)
    n = params.field_width
    phase = np.arange(n) * (np.pi / 2)
    line = (blanking
            + burst_ire * params.out_scale * np.sin(phase)
            + rng.normal(0.0, 0.01 * params.out_scale, n))

    start = (BURST_LINE - 1) * params.field_width
    field.dspicture[start:start + n] = line
    return field


def domain_pair(system, burst_ire, seed=12345):
    """The same waveform as a 10-bit .cvbs field and a 16-bit .tbc field."""
    ten_bit = CaptureParams.for_cvbs(system)
    cvbs = synthetic_field(
        system, ten_bit.blanking_16b_ire, ten_bit.white_16b_ire, burst_ire, seed)
    tbc = synthetic_field(
        system, ten_bit.blanking_16b_ire * 64, ten_bit.white_16b_ire * 64,
        burst_ire, seed)
    return cvbs, tbc


@pytest.mark.parametrize("system", ["NTSC", "PAL"])
@pytest.mark.parametrize("burst_ire", [10.0, 20.0, 40.0])
def test_burst_rms_is_the_same_in_both_sample_domains(system, burst_ire):
    cvbs, tbc = domain_pair(system, burst_ire)
    np.testing.assert_allclose(
        measure_burst(cvbs), measure_burst(tbc), rtol=1e-9)


@pytest.mark.parametrize("system", ["NTSC", "PAL"])
def test_burst_3d_residue_is_the_same_in_both_sample_domains(system):
    # Different seeds so the difference is a real residue, not exactly zero.
    cvbs_a, tbc_a = domain_pair(system, 20.0, seed=1)
    cvbs_b, tbc_b = domain_pair(system, 20.0, seed=2)
    np.testing.assert_allclose(
        measure_burst_3d(cvbs_a, cvbs_b),
        measure_burst_3d(tbc_a, tbc_b),
        rtol=1e-9,
    )


def test_burst_3d_cancels_two_identical_fields():
    # Inter-frame differencing removes anything common to both fields, so an
    # unchanged burst leaves nothing behind.
    a = synthetic_field("NTSC", 240, 800, 20.0)
    b = synthetic_field("NTSC", 240, 800, 20.0)
    assert measure_burst_3d(a, b) == pytest.approx(0.0, abs=1e-9)


def test_burst_window_lies_inside_the_measured_line():
    # A window running past the end of the line would silently shorten the
    # RMS on one system and not the other.
    for system in ("NTSC", "PAL"):
        params = CaptureParams.for_cvbs(system)
        end_samples = (BURST_START_US + BURST_DURATION_US) * params.sample_rate_mhz
        assert end_samples < params.field_width


def test_a_larger_burst_measures_larger():
    # Guards against a measurement that has become insensitive to its input.
    small = measure_burst(synthetic_field("NTSC", 240, 800, 10.0))
    large = measure_burst(synthetic_field("NTSC", 240, 800, 40.0))
    assert large > small
