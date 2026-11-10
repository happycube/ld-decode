"""Unit tests for what a dropped CVBS frame leaves in the sidecars.

CVBSWriter._write_frame drops a frame whose sample count is not the
system's frame length, without counting it.  _emit_frame used to collect the
frame's dropouts, EFM and audio regardless, under frame_id = frames_written:
the next frame then reused that id, so .efm.meta took two rows with one
(cvbs_file_id, frame_id) primary key and close() died before writing .meta,
and the audio ran a frame ahead of the video.  A dropped frame now
contributes nothing.  The file-touching parts are stubbed out.
"""

from unittest.mock import Mock

import numpy as np
import pytest

from lddecode.cvbs import CVBSParams_PAL, CVBSWriter

pytestmark = [pytest.mark.unit, pytest.mark.format]


def make_writer():
    w = CVBSWriter.__new__(CVBSWriter)
    w.system = "PAL"
    w.params = CVBSParams_PAL
    w.logger = None
    w.frames_written = 0
    w._seq_broken = False
    w.clamped_samples = 0
    w.sample_encoding = "CVBS_U16_4FSC"
    w.has_nonstandard_values = False
    w.f_video = Mock()
    w._pal_shift = 0.0
    w.legacy_origin = True
    w._lock_initialised = True
    w._lock_residuals = []
    w._resample_executor = None
    w._to_spec_levels = lambda x, f: x.astype(np.float64)
    w._pal_phase_error = Mock(return_value=None)
    w._resampler = Mock()
    w._resampler.return_value.submit = lambda fn, *args: Mock(
        result=Mock(return_value=fn(*args)))
    w._collect_dropouts = Mock()
    w._collect_efm = Mock()
    w.push_audio = Mock()
    return w


def emit(w, frame_samples):
    a_len = frame_samples // 2
    fields = []
    for n in (a_len, frame_samples - a_len):
        f = Mock()
        f.downscale_cvbs = Mock(return_value=np.full(n, 20000.0))
        fields.append(f)
    w._emit_frame((fields[0], {}, None, b"a", b"A"),
                  (fields[1], {}, None, b"b", b"B"))


def test_a_written_frame_reports_its_sidecars_under_its_own_id():
    w = make_writer()
    fs = CVBSParams_PAL["frame_samples"]

    emit(w, fs)
    emit(w, fs)

    assert [c.args[0] for c in w._collect_efm.call_args_list] == [0, 1]
    assert [c.args[0] for c in w._collect_dropouts.call_args_list] == [0, 1]
    assert w.push_audio.call_count == 4


def test_a_dropped_frame_leaves_no_rows_and_no_audio():
    w = make_writer()
    fs = CVBSParams_PAL["frame_samples"]

    emit(w, fs)
    emit(w, fs - 1)          # dropped: one sample short
    emit(w, fs)

    assert w.frames_written == 2
    assert w._seq_broken
    # frame ids stay unique and match the frames in the file
    assert [c.args[0] for c in w._collect_efm.call_args_list] == [0, 1]
    assert [c.args[0] for c in w._collect_dropouts.call_args_list] == [0, 1]
    assert w.push_audio.call_count == 4


def test_write_frame_says_whether_it_wrote():
    w = make_writer()
    fs = CVBSParams_PAL["frame_samples"]

    assert w._write_frame(np.full(fs, 20000.0)) is True
    assert w._write_frame(np.full(fs + 1, 20000.0)) is False
    assert w.f_video.write.call_count == 1
