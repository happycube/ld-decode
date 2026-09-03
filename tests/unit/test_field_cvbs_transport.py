"""Unit tests for shipping a field's demodulated video through worker
transport for the PAL CVBS writer (lddecode.field).

A field decoded in a worker process comes back stripped of its sample
buffers (Field.prepare_transport).  The PAL CVBS writer, though, resamples
each field onto the 4fsc frame lattice at write time under a burst-lock
shift that only exists in commit order, so the worker must keep the demod
alive for it: prepare_transport(keep_demod=True) retains a contiguous
float32 copy as transport_demod and downscale_cvbs reads from it once
data is gone.  The tests build a synthetic PAL field (a straight ramp with
a small wow) and check the retained copy, that the transported resample is
the same computation as the inline one, and that a field transported
without the demod fails loudly rather than resampling nothing.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from lddecode.dsp import sinc_phase_count, sinc_tap_count
from lddecode.field import FieldPAL
from lddecode.params import SysParams_PAL

pytestmark = [pytest.mark.unit, pytest.mark.decode, pytest.mark.parallel]

#: Lines of demod the synthetic field carries: a first field's lattice
#: portion spans frame times [0, 312.5) lines from lineoffset + 1, plus
#: the resampler's 16-tap reach.
DEMOD_LINES = 320


def linear_lut():
    """Two-tap table that makes scale_positions linearly interpolate
    (see tests/unit/test_dsp_scaling.py)."""
    lut = np.zeros((sinc_phase_count + 1, sinc_tap_count), dtype=np.float32)
    phase = np.arange(sinc_phase_count + 1) / sinc_phase_count
    lut[:, (sinc_tap_count // 2) - 1] = 1.0 - phase
    lut[:, sinc_tap_count // 2] = phase
    return lut


def make_rf():
    linelen = int(round(40e6 * SysParams_PAL["line_period"] / 1e6))
    return SimpleNamespace(
        linelen=linelen,
        SysParams=SysParams_PAL,
        DecoderParams={
            "ire0": 7_100_000.0,
            "hz_ire": 8_000.0,
            "vsync_ire": -43.0,
            "chroma_dg_slope": 0.0,
            "chroma_dg_phase": 0.0,
        },
        downscale_sinc_lut=linear_lut(),
    )


def make_field(rf, rng):
    """A first-field FieldPAL with just the state downscale_cvbs and
    prepare_transport read, bypassing the decode in __init__."""
    f = FieldPAL.__new__(FieldPAL)
    f.rf = rf
    f.isFirstField = True
    f.lineoffset = 2
    f.inlinelen = rf.linelen
    f.linecount = DEMOD_LINES - 4
    f.wow_interpolation_method = "linear"
    f.wow_level_adjust_smoothing = 0
    f.out_scale = 1.0 / rf.DecoderParams["hz_ire"]
    f.valid = True
    f.sync_confidence = 100
    f.fieldPhaseID = 1
    # line starts with a gentle wow so the resample positions are not
    # integral; the demod is a ramp in Hz across the whole buffer
    n = DEMOD_LINES * rf.linelen
    f.linelocs = (
        np.arange(DEMOD_LINES + 1, dtype=np.float64) * rf.linelen
        + rng.uniform(-0.5, 0.5, DEMOD_LINES + 1).cumsum() * 0.01
    )
    demod = np.linspace(7.0e6, 7.9e6, n, dtype=np.float32)
    video = np.zeros(n, dtype=[("demod", np.float32), ("demod_05", np.float32)])
    video["demod"] = demod
    video["demod_05"] = demod
    f.data = {"video": video, "startloc": 0, "input": None}
    f.rawdata = None
    f.transport_demod = None
    f.anchor = None
    f.skip_check = lambda: 0.0
    return f


@pytest.fixture
def field():
    return make_field(make_rf(), np.random.default_rng(12345))


def test_transport_keeps_a_contiguous_float32_copy_of_the_demod(field):
    expected = field.data["video"]["demod"].copy()
    field.prepare_transport(keep_demod=True)
    assert field.data is None
    assert field.transport_demod.dtype == np.float32
    assert field.transport_demod.flags.c_contiguous
    np.testing.assert_array_equal(field.transport_demod, expected)


def test_transport_drops_the_demod_unless_asked(field):
    field.prepare_transport()
    assert field.data is None
    assert field.transport_demod is None


def test_transported_resample_is_the_inline_computation(field):
    rf = field.rf
    inline = field.downscale_cvbs(0.25)

    field.prepare_transport(keep_demod=True)
    field.rf = rf  # the receiver rebinds rf, as the committer does
    transported = field.downscale_cvbs(0.25)

    # same resampler over the same float32 samples and positions: the
    # outputs are the same bits, not merely close
    np.testing.assert_array_equal(transported, inline)
    assert len(transported) == 354690  # first-field share of the PAL frame


def test_resample_without_the_demod_fails_loudly(field):
    rf = field.rf
    field.prepare_transport()
    field.rf = rf
    with pytest.raises(ValueError, match="keep_demod"):
        field.downscale_cvbs(0.0)
