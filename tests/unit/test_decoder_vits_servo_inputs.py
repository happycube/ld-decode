"""Unit tests for how the 2T and video-EQ servos get their per-field VITS
measurements.

Stage 2 (decode_stage2 here, or the field job in a worker) takes them
with the vsync level they read; calibrate() takes that result only while
the level still stands, and measures the field afresh otherwise - so the
servos see exactly what measuring at calibration time would give, even
when the AGC moves the level inside the field's own calibration.
"""

import types

import pytest

from lddecode import decoder as D
from lddecode.decoder import LDdecode

pytestmark = [pytest.mark.unit, pytest.mark.decode]


def stub_field(vsync_ire=-40.0, precomputed=None, **kwargs):
    f = types.SimpleNamespace(
        rf=types.SimpleNamespace(DecoderParams={"vsync_ire": vsync_ire}), **kwargs)
    if precomputed is not None:
        f.precomputed_vits = precomputed
    return f


def counting(result):
    calls = []

    def measure(field):
        calls.append(field)
        return result
    measure.__name__ = "measure_its_2t_ratio"
    return measure, calls


def test_a_measurement_taken_under_the_standing_level_is_used():
    measure, calls = counting((0.9, 19))
    f = stub_field(-40.0, {"measure_its_2t_ratio": (-40.0, (1.02, 19))})

    assert LDdecode._vits_measurement(None, f, measure) == (1.02, 19)
    assert calls == []


def test_a_stored_none_is_used_too():
    measure, calls = counting((0.9, 19))
    f = stub_field(-40.0, {"measure_its_2t_ratio": (-40.0, None)})

    assert LDdecode._vits_measurement(None, f, measure) is None
    assert calls == []


@pytest.mark.parametrize("precomputed", [
    None,                                              # never taken
    {},                                                # not wanted then
    {"measure_its_2t_ratio": (-40.0, (1.02, 19))},     # level since moved
    {"measure_vits_multiburst": (-38.5, None)},        # another measurement
])
def test_otherwise_the_field_is_measured_afresh(precomputed):
    measure, calls = counting((0.9, 19))
    f = stub_field(-38.5, precomputed)

    assert LDdecode._vits_measurement(None, f, measure) == (0.9, 19)
    assert calls == [f]


@pytest.mark.parametrize("auto_mtf, two_t, veq, want", [
    (True, True, True, ["measure_its_2t_ratio", "measure_vits_multiburst"]),
    (False, True, True, ["measure_vits_multiburst"]),
    (True, False, False, []),
    (True, True, False, ["measure_its_2t_ratio"]),
])
def test_the_measurements_follow_the_servos_that_pool_them(auto_mtf, two_t, veq, want):
    it = types.SimpleNamespace(autoMTF=auto_mtf, mtf_2t_servo=two_t, veq_servo=veq)
    assert LDdecode._vits_servo_measures(it) == want


@pytest.mark.parametrize("mtf_level, want", [
    (0.4, ["measure_its_2t_ratio", "measure_vits_multiburst"]),
    (None, ["measure_vits_multiburst"]),
])
def test_stage_2_takes_them_with_the_rest_of_the_field(monkeypatch, mtf_level, want):
    """The 2T servo only pools a field that knows the mtf_level it was
    decoded under, so stage 2 does not measure one that doesn't."""
    seen = []
    monkeypatch.setattr(D, "precompute_vits",
                        lambda f, names: seen.append(list(names)) or {"x": 1})
    it = types.SimpleNamespace(
        output_lines=263, doDOD=False, useAGC=False,
        computeMetrics=lambda f, fp, verbose=False: {"m": 1},
        _vits_servo_measures=lambda: ["measure_its_2t_ratio", "measure_vits_multiburst"])
    f = stub_field(decoded_mtf_level=mtf_level,
                   downscale=lambda **k: ("picture", None, "efm"))

    assert LDdecode.decode_stage2(it, f) == ("picture", "efm", {"m": 1})
    assert seen == [want] and f.precomputed_vits == {"x": 1}
