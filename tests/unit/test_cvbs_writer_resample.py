"""Unit tests for the PAL frame assembly in lddecode.cvbs.CVBSWriter.

A PAL frame resamples both of its fields onto the 4fsc lattice under one
burst-lock shift, and only field A's result feeds the lock.  Once the lock
is anchored the writer therefore hands field B's resample to an executor
and runs field A's itself; the tests inject a recording executor and
check the two calls use the same shift, that the first (anchoring) frame
stays synchronous, and that the lock shift for the next frame comes from
field A alone - the invariants that make the concurrent version the same
computation as the serial one.
"""

from unittest.mock import Mock

import numpy as np
import pytest

from lddecode.cvbs import CVBSWriter, CVBSParams_PAL

pytestmark = [pytest.mark.unit, pytest.mark.format, pytest.mark.parallel]


class RecordingExecutor:
    """Runs submissions inline, remembering what was submitted."""

    def __init__(self):
        self.calls = []

    def submit(self, fn, *args):
        self.calls.append((fn, args))
        fut = Mock()
        fut.result.return_value = fn(*args)
        return fut


def make_writer(executor):
    """A PAL writer with the file-touching parts stubbed out."""
    w = CVBSWriter.__new__(CVBSWriter)
    w.system = "PAL"
    w.params = CVBSParams_PAL
    w.logger = None
    w.frames_written = 0
    w._pal_shift = 0.0
    w._lock_initialised = False
    w._lock_residuals = []
    w._resample_executor = executor
    w._owns_resample_executor = False
    w._to_spec_levels = lambda x, f: x.astype(np.float64)
    w._pal_phase_error = Mock(return_value=None)
    w._write_frame = Mock()
    w._collect_dropouts = Mock()
    w._collect_efm = Mock()
    w.push_audio = Mock()
    return w


def make_field(n):
    f = Mock()
    f.downscale_cvbs = Mock(
        side_effect=lambda shift: np.full(n, shift, dtype=np.float32))
    return f


def emit(w):
    f_a, f_b = make_field(354690), make_field(354689)
    w._emit_frame((f_a, {}, None, None, None), (f_b, {}, None, None, None))
    return f_a, f_b


def test_first_frame_anchors_the_lock_before_field_b_resamples():
    ex = RecordingExecutor()
    w = make_writer(ex)
    w._pal_phase_error = Mock(return_value=9.0)  # 9 deg -> 0.1 sample
    f_a, f_b = emit(w)

    # field A twice (measure, then re-resample at the anchored shift),
    # field B once at the anchored shift, all inline
    assert [c.args[0] for c in f_a.downscale_cvbs.call_args_list] == [0.0, 0.1]
    assert [c.args[0] for c in f_b.downscale_cvbs.call_args_list] == [0.1]
    assert ex.calls == []
    assert w._lock_initialised


def test_field_b_resamples_on_the_executor_at_field_a_shift():
    ex = RecordingExecutor()
    w = make_writer(ex)
    w._lock_initialised = True
    w._pal_shift = 0.25
    f_a, f_b = emit(w)

    assert f_a.downscale_cvbs.call_args_list[0].args == (0.25,)
    assert len(ex.calls) == 1
    fn, args = ex.calls[0]
    assert fn is f_b.downscale_cvbs and args == (0.25,)
    frame = w._write_frame.call_args.args[0]
    assert len(frame) == CVBSParams_PAL["frame_samples"]


def test_lock_tracks_from_field_a_only_and_is_clamped():
    ex = RecordingExecutor()
    w = make_writer(ex)
    w._lock_initialised = True
    # -20 deg is -0.222 sample of error; three quarters of that is still
    # past the per-frame clamp, so a large error slews at the clamp as it
    # did before the loop was damped
    w._pal_phase_error = Mock(return_value=-20.0)
    emit(w)

    w._pal_phase_error.assert_called_once()
    called_with = w._pal_phase_error.call_args.args[0]
    assert len(called_with) == 354690  # field A's lattice share
    assert w._pal_shift == pytest.approx(-0.05)  # clamped per-frame step
    assert w._lock_residuals == [-20.0]


def test_a_small_residual_moves_the_lock_by_a_fraction_of_it():
    """The residual is mostly measurement noise (see PAL_LOCK_GAIN), so the
    loop applies three quarters of it and leaves the rest to be re-measured
    rather than writing this frame's noise into the next frame's
    lattice."""
    ex = RecordingExecutor()
    w = make_writer(ex)
    w._lock_initialised = True
    w._pal_phase_error = Mock(return_value=1.8)   # 0.02 sample of error

    emit(w)

    assert w._pal_shift == pytest.approx(0.75 * 1.8 / 90.0)
    assert w.PAL_LOCK_GAIN == 0.75


def test_the_anchor_frame_takes_the_whole_measured_error():
    """Acquisition is not damped: the first frame moves the lattice by all
    of what it measures, so the loop starts from the right place instead of
    walking there a fraction at a time."""
    ex = RecordingExecutor()
    w = make_writer(ex)
    # 9 deg of error to anchor out, then 4 deg read back off the anchored
    # field (inside the per-frame clamp, so the gain is what shows)
    w._pal_phase_error = Mock(side_effect=[9.0, 4.0])

    f_a, _ = emit(w)

    assert [c.args[0] for c in f_a.downscale_cvbs.call_args_list] == [0.0, 0.1]
    assert w._pal_shift == pytest.approx(0.1 + 0.75 * 4.0 / 90.0)


def test_close_leaves_an_injected_executor_alone():
    ex = Mock()
    w = make_writer(ex)
    w.f_video = Mock()
    w.f_wav = None
    w.f_efm = None
    w.dropout_rows = []
    w._lock_state = Mock(return_value="STANDARD_STABLE_LOCKED")
    w._sequence_continuous = Mock(return_value=1)
    w._write_meta = Mock()
    w.close()
    ex.shutdown.assert_not_called()
