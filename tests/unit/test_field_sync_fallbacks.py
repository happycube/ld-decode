"""Unit tests for the sync-detection fallbacks in Field.

Two paths only run on damaged fields: get_timings() when no pulse has an
hsync-like width, and getpulses()'s level-corrected retry when there are no
equalising pulses around vsync to measure black from.  The first must keep
the pulse windows in samples; the second must not compute a NaN threshold.
"""

import numpy as np
import pytest

from lddecode.pulses import Pulse
from synthetic_field import make_field, make_rf

pytestmark = [pytest.mark.unit, pytest.mark.decode]


@pytest.fixture(scope="module", params=["NTSC", "PAL"])
def rf(request):
    return make_rf(request.param)


def test_timings_without_hsync_pulses_fall_back_to_the_nominal_width(rf):
    field = make_field(rf)
    typical = field.usectoinpx(rf.SysParams["hsyncPulseUS"])
    half_us = field.usectoinpx(0.5)

    field.rawpulses = []  # nothing hsync-shaped: a dropout-wrecked field
    LT = field.get_timings()

    assert LT["hsync_median"] == pytest.approx(typical)
    assert LT["hsync"] == pytest.approx((typical - half_us, typical + half_us))
    # With the nominal width there is no offset to push the eq / vsync
    # windows around.
    assert LT["hsync_offset"] == pytest.approx(0.0)


def test_timings_follow_the_measured_hsync_width(rf):
    field = make_field(rf)
    typical = field.usectoinpx(rf.SysParams["hsyncPulseUS"])
    measured = typical + 10.0

    field.rawpulses = [Pulse(i * 1000, measured) for i in range(5)]
    LT = field.get_timings()

    assert LT["hsync_offset"] == pytest.approx(10.0)


def test_pulse_retry_without_eq_pulses_reports_no_pulses(rf):
    # One broad (vsync) pulse, 10 IRE below the nominal sync level so the
    # level-corrected retry runs, and no equalising pulses either side of it.
    n = 40000
    blank_hz = rf.iretohz(0)
    sync_hz = rf.iretohz(rf.DecoderParams["vsync_ire"] - 10)
    demod_05 = np.full(n, blank_hz, dtype=np.float64)
    start = 10000
    length = int(rf.freq * 30)  # 30 us: comfortably above the 10 us vsync cut
    demod_05[start:start + length] = sync_hz

    field = make_field(rf, video={"demod_05": demod_05})
    field.fields_written = 1

    # No NaN black level (np.median of nothing) may reach the threshold;
    # with no level to retry at, the field reports no pulses so the
    # decoder skips ahead.
    with np.errstate(all="raise"):
        pulses = field.getpulses()

    assert len(pulses) == 0
