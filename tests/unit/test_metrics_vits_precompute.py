"""Unit tests for metrics.precompute_vits, which takes the VITS
measurements the decoder's 2T and video-EQ servos pool while the field is
still in stage 2 (or in its worker process).

The measurements read the picture in IRE through the live vsync level,
which the AGC can move before the servo sees the result, so each result
must travel with the level it was read under.
"""

import types

import pytest

from lddecode import metrics as M

pytestmark = [pytest.mark.unit, pytest.mark.decode]


def stub_field(vsync_ire=-40.0):
    return types.SimpleNamespace(
        rf=types.SimpleNamespace(DecoderParams={"vsync_ire": vsync_ire}))


@pytest.fixture
def measures(monkeypatch):
    calls = []

    def two_t(field):
        calls.append("2t")
        return (1.01, 19)

    def multiburst(field):
        calls.append("mb")
        return ([(1e6, 60.0)], 13)

    monkeypatch.setattr(M, "VITS_SERVO_MEASURES", {
        "measure_its_2t_ratio": two_t, "measure_vits_multiburst": multiburst})
    return calls


def test_each_measurement_is_kept_with_the_level_it_read(measures):
    got = M.precompute_vits(stub_field(-43.0),
                            ["measure_its_2t_ratio", "measure_vits_multiburst"])

    assert got == {"measure_its_2t_ratio": (-43.0, (1.01, 19)),
                   "measure_vits_multiburst": (-43.0, ([(1e6, 60.0)], 13))}


def test_only_the_named_measurements_run(measures):
    got = M.precompute_vits(stub_field(), ["measure_vits_multiburst"])

    assert measures == ["mb"] and list(got) == ["measure_vits_multiburst"]
    assert M.precompute_vits(stub_field(), []) == {}


def test_a_level_that_moves_mid_measurement_keeps_nothing(monkeypatch):
    field = stub_field(-40.0)

    def moving(f):
        f.rf.DecoderParams["vsync_ire"] = -41.0
        return (1.0, 19)

    monkeypatch.setattr(M, "VITS_SERVO_MEASURES", {"measure_its_2t_ratio": moving})
    assert M.precompute_vits(field, ["measure_its_2t_ratio"]) == {}


def test_none_is_a_result_like_any_other(monkeypatch):
    """A field with no ITS still measured; its None must not send the
    servo off to measure it again."""
    monkeypatch.setattr(M, "VITS_SERVO_MEASURES",
                        {"measure_its_2t_ratio": lambda f: None})
    assert M.precompute_vits(stub_field(-40.0), ["measure_its_2t_ratio"]) == {
        "measure_its_2t_ratio": (-40.0, None)}


def test_the_servo_measurements_are_the_decoders():
    from lddecode import decoder as D

    assert M.VITS_SERVO_MEASURES == {
        "measure_its_2t_ratio": D.measure_its_2t_ratio,
        "measure_vits_multiburst": D.measure_vits_multiburst,
    }
