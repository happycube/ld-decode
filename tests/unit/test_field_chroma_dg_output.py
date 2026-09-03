"""Unit tests for the write-time chroma DG decision in lddecode.field
(chroma_dg_output_picture) and for the (slope, phase) pair riding field
jobs in lddecode.parallel.FieldJobEngine.

The TBC output's differential gain/phase correction is a pure function
of the picture and the servo's estimate, so a worker process applies it
and stamps the field with the key it used.  The writer must then use
that copy only while the key is current, and fall back to correcting the
raw dspicture itself - the serial computation - the moment the servo has
moved on.  These tests pin that decision table with stub fields and a
recording corrector, and check the engine hands each job the pair it
was last given.
"""

import threading
import types
from concurrent.futures import Future

import numpy as np
import pytest

from lddecode import field as F
from lddecode.parallel import FieldJobEngine

pytestmark = [pytest.mark.unit, pytest.mark.decode, pytest.mark.parallel]

VSYNC_IRE = -40.0


def stub_field(vsync_ire=VSYNC_IRE, applied=None):
    f = types.SimpleNamespace(
        rf=types.SimpleNamespace(DecoderParams={"vsync_ire": vsync_ire}),
        dspicture=np.arange(8, dtype=np.uint16),
    )
    if applied is not None:
        f.chroma_dg_applied = applied
    return f


@pytest.fixture
def corrector(monkeypatch):
    """Replace the FFT corrector with a recorder that tags its input."""
    calls = []

    def fake(picture, field, slope, phase):
        calls.append((picture, slope, phase))
        return np.asarray(picture) + 1000

    monkeypatch.setattr(F, "apply_chroma_dg_correction_output", fake)
    return calls


def test_key_is_slope_phase_and_the_agc_vsync_level():
    rf = types.SimpleNamespace(DecoderParams={"vsync_ire": -43.0})
    assert F.chroma_dg_output_key(rf, 0.002, 0.04) == (0.002, 0.04, -43.0)


def test_no_correction_needed_returns_the_picture_itself(corrector):
    f = stub_field()
    picture = np.arange(8, dtype=np.uint16)
    assert F.chroma_dg_output_picture(picture, f, 0.0, 0.0) is picture
    assert corrector == []


def test_inline_field_is_corrected_at_write_time(corrector):
    f = stub_field()
    out = F.chroma_dg_output_picture(f.dspicture, f, 0.002, 0.0)
    assert len(corrector) == 1
    assert corrector[0][0] is f.dspicture and corrector[0][1:] == (0.002, 0.0)
    np.testing.assert_array_equal(out, f.dspicture + 1000)


def test_worker_correction_under_the_current_key_is_kept(corrector):
    f = stub_field(applied=(0.002, 0.04, VSYNC_IRE))
    corrected = np.full(8, 7, dtype=np.uint16)
    assert F.chroma_dg_output_picture(corrected, f, 0.002, 0.04) is corrected
    assert corrector == []


@pytest.mark.parametrize(
    "stale",
    [
        (0.001, 0.04, VSYNC_IRE),   # servo adopted a new slope
        (0.002, 0.00, VSYNC_IRE),   # servo adopted a phase
        (0.002, 0.04, -43.0),       # AGC moved the vsync level
    ],
)
def test_stale_worker_correction_is_redone_from_the_raw_picture(corrector, stale):
    f = stub_field(applied=stale)
    corrected = np.full(8, 7, dtype=np.uint16)
    out = F.chroma_dg_output_picture(corrected, f, 0.002, 0.04)
    assert len(corrector) == 1
    assert corrector[0][0] is f.dspicture  # never re-corrects a corrected copy
    np.testing.assert_array_equal(out, f.dspicture + 1000)


TOL = (0.0008, 0.01)


def test_tolerant_mode_keeps_a_correction_within_the_allowance(corrector):
    f = stub_field(applied=(0.0020, 0.04, VSYNC_IRE))
    corrected = np.full(8, 7, dtype=np.uint16)
    out = F.chroma_dg_output_picture(corrected, f, 0.0025, 0.045, tolerance=TOL)
    assert out is corrected
    assert corrector == []


@pytest.mark.parametrize(
    "applied",
    [
        (0.0030, 0.040, VSYNC_IRE),  # slope moved by more than the allowance
        (0.0020, 0.000, VSYNC_IRE),  # the phase term engaged
        (0.0020, 0.040, -43.0),      # a level change is never tolerated
    ],
)
def test_tolerant_mode_still_redoes_a_correction_outside_it(corrector, applied):
    f = stub_field(applied=applied)
    corrected = np.full(8, 7, dtype=np.uint16)
    out = F.chroma_dg_output_picture(corrected, f, 0.0020, 0.040, tolerance=TOL)
    assert len(corrector) == 1 and corrector[0][0] is f.dspicture
    np.testing.assert_array_equal(out, f.dspicture + 1000)


def test_servo_returning_to_zero_discards_the_worker_correction(corrector):
    f = stub_field(applied=(0.002, 0.0, VSYNC_IRE))
    corrected = np.full(8, 7, dtype=np.uint16)
    assert F.chroma_dg_output_picture(corrected, f, 0.0, 0.0) is f.dspicture
    assert corrector == []


def test_no_field_means_no_correction(corrector):
    picture = np.arange(8, dtype=np.uint16)
    assert F.chroma_dg_output_picture(picture, None, 0.002, 0.0) is picture


# --- exact speculation demands current filter parameters -----------------


def accept_stub(exact, imtf=0.5, veq=((1.0e6, 0.0),)):
    from lddecode.decoder import LDdecode

    it = types.SimpleNamespace(
        exact_speculation=exact,
        mtf_level=0.0,
        mtf_speculation_tolerance=0.1,
        rf=types.SimpleNamespace(
            DecoderParams={"inverse_mtf_strength": imtf, "video_eq_auto": veq}),
        reasons=[],
    )
    it._log_speculation = lambda reason, detail="": it.reasons.append(reason)
    it._accept_job = lambda res: LDdecode._accept_job(it, res)
    return it


def job_result(imtf=0.5, veq=((1.0e6, 0.0),)):
    field = types.SimpleNamespace(decoded_video_eq=tuple(veq) if veq else None)
    return {"valid": True, "mtf_level": 0.0, "imtf_strength": imtf, "field": field}


def test_exact_mode_rejects_a_job_decoded_under_a_stale_inverse_mtf_strength():
    it = accept_stub(exact=True, imtf=0.5)
    assert it._accept_job(job_result(imtf=0.4)) is None
    assert it.reasons == ["stale-imtf"]


def test_exact_mode_rejects_a_job_decoded_under_a_previous_video_eq():
    it = accept_stub(exact=True, veq=((1.0e6, 0.0), (2.0e6, 1.0)))
    assert it._accept_job(job_result(veq=((1.0e6, 0.0),))) is None
    assert it.reasons == ["stale-veq"]


def test_tolerant_mode_lets_a_dead_band_trim_through(monkeypatch):
    """Not rejected for the strength: the check falls through to the
    window/chain validation, which this stub does not model."""
    it = accept_stub(exact=False, imtf=0.5)
    with pytest.raises(AttributeError):
        it._accept_job(job_result(imtf=0.4))
    assert it.reasons == []


# --- the engine hands the pair to each job -------------------------------


class RecordingExecutor:
    def __init__(self):
        self.calls = []
        self.submitted = threading.Event()

    def submit(self, fn, *args):
        self.calls.append(args)
        fut = Future()
        fut.set_result({"seq": args[0], "valid": False})
        self.submitted.set()
        return fut


def make_engine(executor):
    cfg = {
        "blocklen": 32768,
        "blockcut": 1024,
        "demod_blocksize": 30720,
        "readlen": 32768 * 4,
        "samples_per_field": 32768.0 * 4,
        "analog_audio": 0,
        "parity_len": {True: 32768.0 * 4, False: 32768.0 * 4},
    }
    return FieldJobEngine(
        executor=executor,
        read_fn=lambda sample, length: np.zeros(length, dtype=np.int16),
        read_lock=threading.Lock(),
        cfg=cfg,
        workers=1,
    )


def test_engine_dispatches_the_chroma_dg_pair_it_was_reset_with():
    ex = RecordingExecutor()
    engine = make_engine(ex)
    try:
        engine.reset(start=0.0, next_is_first=True, lastfieldwritten=(0, 0),
                     mtf_level=0.0, chroma_dg=(0.002, 0.04))
        assert ex.submitted.wait(5.0)
    finally:
        engine.stop()
    assert ex.calls[0][-1] == (0.002, 0.04)


def test_engine_adopts_a_new_pair_for_later_dispatches():
    ex = RecordingExecutor()
    engine = make_engine(ex)
    try:
        engine.pause()
        engine.set_chroma_dg((0.003, 0.0))
        assert engine._chroma_dg == (0.003, 0.0)
        engine.set_chroma_dg(None)
        assert engine._chroma_dg is None
    finally:
        engine.stop()
