"""Unit tests for lddecode.field.field_output_view: the commit-time
parameter snapshot a field carries into the output stage.
"""

import types

import numpy as np
import pytest

from lddecode.field import field_output_view

pytestmark = [pytest.mark.unit, pytest.mark.decode, pytest.mark.parallel]


def stub_field():
    rf = types.SimpleNamespace(
        DecoderParams={"vsync_ire": -40.0, "chroma_dg_slope": 0.0},
        SysParams={"outputZero": 1024},
        downscale_sinc_lut=np.zeros(4),
    )
    return types.SimpleNamespace(rf=rf, dspicture=np.arange(8, dtype=np.uint16))


def test_no_field_gives_no_view():
    assert field_output_view(None) is None


def test_view_shares_the_samples_but_owns_a_parameter_snapshot():
    f = stub_field()
    view = field_output_view(f)
    assert view is not f
    assert view.dspicture is f.dspicture
    assert view.rf is not f.rf
    assert view.rf.DecoderParams is not f.rf.DecoderParams
    assert view.rf.DecoderParams == f.rf.DecoderParams
    # constants and tables stay shared
    assert view.rf.SysParams is f.rf.SysParams
    assert view.rf.downscale_sinc_lut is f.rf.downscale_sinc_lut


def test_a_later_servo_adoption_does_not_reach_the_view():
    f = stub_field()
    view = field_output_view(f)
    f.rf.DecoderParams["chroma_dg_slope"] = 0.002
    f.rf.DecoderParams["vsync_ire"] = -43.0
    assert view.rf.DecoderParams["chroma_dg_slope"] == 0.0
    assert view.rf.DecoderParams["vsync_ire"] == -40.0
    # and the field itself stays bound to the live decoder
    assert f.rf.DecoderParams["vsync_ire"] == -43.0
