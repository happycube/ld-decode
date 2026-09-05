"""Unit tests for the modelled optical MTF and the curve built from it.

The inverse-MTF chroma correction is shaped by the disc's own optical
transfer function, whose cutoff is the readout objective's spatial cutoff
carried past the spot at the track velocity.  A CAV disc turns once per
frame, so that velocity - and the cutoff with it - scales with the frame
rate, and PAL's 25 rev/s is a fifth below NTSC's 29.97.  Modelled at the
wrong rate the curve is not merely mis-scaled: the correction the servos
hold is a *shape*, and every strength unit, dead-band and limit expressed
against it means something different.

These tests pin the rotation rate the curve is built at, per system, and
the property that made it worth pinning - that a correction of a stated
size in dB at the subcarrier stays that size when the curve changes.
"""

import numpy as np
import pytest

from lddecode.dsp import compute_mtf, get_fmax
from lddecode.params import SysParams_NTSC, SysParams_PAL
from lddecode.rfdecode import RFDecode

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

#: Disc revolutions per second on a CAV side, which is the frame rate.
PAL_FPS = 25.0
NTSC_FPS = 30000.0 / 1001.0

#: The 2 MHz point below which the correction curve is held at unity.
CROSSOVER_HZ = 2.0e6

#: The numerical aperture compute_mtf() reads the disc at.  get_fmax()
#: carries a different default (0.5) and is only ever called through
#: compute_mtf, so the tests state which one they mean.
NA = 0.52


def reference_db_per_unit(freq_hz, fps):
    """dB the inverse-MTF curve adds at freq_hz per unit of strength.

    Restated from the curve's definition rather than imported, so a change
    to how rfdecode builds it has to be made deliberately in both places.
    """
    norm = (compute_mtf(freq_hz, fps=fps)
            / compute_mtf(CROSSOVER_HZ, fps=fps))
    return float(-20.0 * np.log10(norm))


# ---------------------------------------------------------------------------
# The cutoff itself
# ---------------------------------------------------------------------------

def test_the_cutoff_scales_with_the_disc_rotation_rate():
    """2*NA/lambda cycles per unit length past the spot at 2*pi*r*fps."""
    inner_radius_m = 0.055
    for fps in (PAL_FPS, NTSC_FPS):
        expected = (2 * NA / 0.780) * (2 * np.pi * fps) * inner_radius_m
        assert get_fmax(na=NA, fps=fps) == pytest.approx(expected)


def test_pal_reads_a_fifth_below_ntsc():
    """The size of the error a PAL decode inherited from NTSC's default."""
    assert get_fmax(na=NA, fps=PAL_FPS) == pytest.approx(11.52, abs=0.01)
    assert get_fmax(na=NA, fps=NTSC_FPS) == pytest.approx(13.81, abs=0.01)
    assert (get_fmax(na=NA, fps=NTSC_FPS) / get_fmax(na=NA, fps=PAL_FPS)
            == pytest.approx(NTSC_FPS / PAL_FPS))


def test_the_cav_frame_count_is_revolutions_and_not_seconds():
    """54000 tracks span the CAV programme radii on both systems.

    It is fps that differs between them, not the number of turns, so the
    modelled radius at a given CAV frame must not move with the rate.
    """
    for fps in (PAL_FPS, NTSC_FPS):
        outer = get_fmax(cavframe=54000, fps=fps)
        inner = get_fmax(cavframe=0, fps=fps)
        assert outer / inner == pytest.approx(0.145 / 0.055)


def test_the_mtf_falls_to_zero_at_the_cutoff_and_is_flat_at_dc():
    fmax_mhz = get_fmax(na=NA, fps=PAL_FPS)
    assert compute_mtf(0.0, fps=PAL_FPS) == pytest.approx(1.0)
    assert compute_mtf(fmax_mhz * 1e6, fps=PAL_FPS) == pytest.approx(0.0)
    assert compute_mtf(2 * fmax_mhz * 1e6, fps=PAL_FPS) == 0


def test_an_array_argument_is_not_modified():
    """The caller's frequency axis is reused; clipping it in place would
    silently flatten every later use of it."""
    freqs = np.array([1.0e6, 5.0e6, 40.0e6])
    before = freqs.copy()
    compute_mtf(freqs, fps=PAL_FPS)
    np.testing.assert_array_equal(freqs, before)


# ---------------------------------------------------------------------------
# The curve rfdecode builds from it
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def decoders():
    return {system: RFDecode(system=system) for system in ("PAL", "NTSC")}


@pytest.mark.parametrize("system, fps", [("PAL", PAL_FPS),
                                         ("NTSC", NTSC_FPS)])
def test_the_curve_is_built_at_the_disc_rotation_rate(decoders, system, fps):
    """Each system's curve, at three frequencies across the video band."""
    rf = decoders[system]
    for freq_hz in (3.0e6, rf.SysParams["fsc_mhz"] * 1e6, 5.0e6):
        assert rf.inverse_mtf_log_db(freq_hz) == pytest.approx(
            reference_db_per_unit(freq_hz, fps), abs=0.01)


def test_pal_is_not_built_at_ntscs_rate(decoders):
    """The regression itself: 3.48 dB per unit at 4.43 MHz, not the
    2.69 the NTSC default modelled."""
    rf = decoders["PAL"]
    fsc_hz = rf.SysParams["fsc_mhz"] * 1e6
    assert rf.inverse_mtf_log_db(fsc_hz) == pytest.approx(3.48, abs=0.01)
    assert rf.inverse_mtf_log_db(fsc_hz) != pytest.approx(
        reference_db_per_unit(fsc_hz, NTSC_FPS), abs=0.5)


def test_the_rotation_rate_comes_from_the_system_parameters():
    """SysParams["FPS"] is the rate the curve is built at, so the two
    cannot drift apart."""
    assert SysParams_PAL["FPS"] == pytest.approx(PAL_FPS)
    assert SysParams_NTSC["FPS"] == pytest.approx(NTSC_FPS)


def test_the_curve_is_unity_below_the_crossover(decoders):
    for rf in decoders.values():
        assert rf.inverse_mtf_log_db(1.0e6) == pytest.approx(0.0)
        assert rf.inverse_mtf_log_db(CROSSOVER_HZ) == pytest.approx(0.0)
