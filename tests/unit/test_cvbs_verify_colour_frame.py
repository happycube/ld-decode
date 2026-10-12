"""Unit tests for cvbs_verify's 0H-origin and colour-sequence checks.

The spec stores frames 0H-aligned (0H in the sample before sample 0) and
leaves each frame's colour-sequence position to be read from its burst.  A
burst-locked decoder puts 0H wherever the disc's SC/H does, so the verifier
reads the position against the frame's own 0H: NTSC colour frame A within
90 degrees of 0 deg SC/H and B within 90 of 180, PAL frames 1-4 by the
V-switch and the +U phase at 0H (BT.470 note 21).  The frames here are
built from those definitions directly.
"""

import numpy as np
import pytest

import cvbs_verify as cv

pytestmark = [pytest.mark.unit, pytest.mark.format]

NTSC, PAL = cv.PRESETS["NTSC"], cv.PRESETS["PAL"]


def frame(preset, h0, burst_phase, porch=None, seed=0):
    """A frame whose line syncs fall (half amplitude) at h0 samples from
    each line's lattice position, with a two-sample edge, and whose burst
    on line l reads burst_phase(l) as the phase of cos(90 (n - h0) + phase)
    over the frame's sample index n."""
    rng = np.random.default_rng(seed)
    lv = preset["levels"]
    porch = lv["blanking"] if porch is None else porch
    n = np.arange(preset["frame_samples"], dtype=np.float64)
    pitch = preset["frame_samples"] / preset["frame_lines"]
    line = np.floor(n / pitch + 0.5).astype(int)
    t = n - line * pitch - h0
    low = np.clip((t + 1.0) / 2.0, 0.0, 1.0) * np.clip((66.0 - t) / 2.0, 0.0, 1.0)
    x = porch - (porch - lv["sync"]) * low
    b0, b1 = preset["burst"]
    phases = np.array([burst_phase(l) for l in range(preset["frame_lines"] + 1)])
    in_burst = (t >= b0 + 2) & (t < b1 - 2)
    x += in_burst * 40.0 * np.cos(np.radians(90.0 * (n - h0) + phases[line]))
    return np.round(x + rng.normal(0.0, 1.0, len(x))).astype(np.int32)


def ntsc_frame(sch, h0=-0.5, **kw):
    """Colour frame A at sch degrees of SC/H (B is A at sch + 180)."""
    return frame(NTSC, h0, lambda l: cv.NTSC_FRAME_A_BURST + sch, **kw)


def pal_frame(number, sch, h0=-0.5):
    """PAL sequence frame 1-4 at sch degrees of Sc-H: +U at 270 (k - 1)
    degrees at 0H of line 0, the +135 burst on even stored lines of
    frames 1 and 3 and on odd ones of 2 and 4."""
    u = (270.0 * (number - 1) + sch) % 360
    plus_on_even = number in (1, 3)

    def burst(l):
        plus = (l % 2 == 0) == plus_on_even
        return u + (45.0 if plus else 135.0)
    return frame(PAL, h0, burst)


@pytest.mark.parametrize("preset, h0", [(NTSC, -0.5), (NTSC, -0.05), (PAL, -0.9)])
def test_the_origin_is_where_the_sync_edge_crosses_half_amplitude(preset, h0):
    x = frame(preset, h0, lambda l: 0.0)
    assert cv.frame_origin(x, preset) == pytest.approx(h0, abs=0.05)


def test_the_origin_is_measured_against_the_disc_s_own_porch():
    """ggv1016-side1's dark picture content pulls the histogram's blanking
    peak to 260; the porch it is measured against reads 240."""
    x = ntsc_frame(0.0, h0=-0.5, porch=260)
    assert cv.frame_origin(x, NTSC) == pytest.approx(-0.5, abs=0.05)


def read(x, preset_name, preset):
    return cv.colour_phase(x, preset_name, preset, cv.frame_origin(x, preset))


@pytest.mark.parametrize("sch", [0.0, 45.0, -60.0])
def test_ntsc_colour_frames_are_read_against_0h(sch):
    a, b = ntsc_frame(sch), ntsc_frame(sch + 180.0)
    assert cv.colour_frame(read(a, "NTSC", NTSC), "NTSC") == "A"
    assert cv.colour_frame(read(b, "NTSC", NTSC), "NTSC") == "B"


def test_the_colour_frame_does_not_depend_on_where_0h_falls_in_its_sample():
    """Frame A with 0H 0.7 samples further in: its burst moves 63 degrees
    against the sample index, but not against 0H."""
    for h0 in (-0.2, -0.9):
        assert cv.colour_frame(read(ntsc_frame(30.0, h0=h0), "NTSC", NTSC), "NTSC") == "A"


def test_an_ntsc_frame_near_90_degrees_of_sch_has_no_colour_frame():
    assert cv.colour_frame(read(ntsc_frame(88.0), "NTSC", NTSC), "NTSC") == "?"


@pytest.mark.parametrize("sch", [0.0, 40.0, -40.0])
def test_pal_frames_are_read_by_v_switch_and_u_phase(sch):
    for number in (1, 2, 3, 4):
        reading = read(pal_frame(number, sch), "PAL", PAL)
        assert cv.colour_frame(reading, "PAL") == number


def test_a_continuous_sequence_steps_one_position_per_frame():
    ntsc = [read(ntsc_frame(20.0 + 180.0 * i), "NTSC", NTSC) for i in range(3)]
    pal = [read(pal_frame(k, 20.0), "PAL", PAL) for k in (3, 4, 1, 2)]
    assert cv.sequence_steps_ok(ntsc, "NTSC")
    assert cv.sequence_steps_ok(pal, "PAL")
    # a repeated frame breaks it
    assert not cv.sequence_steps_ok([ntsc[0], ntsc[0]], "NTSC")
    assert not cv.sequence_steps_ok([pal[0], pal[0]], "PAL")
