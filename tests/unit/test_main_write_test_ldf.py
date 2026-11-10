"""Unit tests for --write-test-ldf telling a good bug-report capture from a bad one.

write_input_ldf_file broke off on a short read, never looked at ffmpeg's exit
status, and then printed "Successfully wrote" - so a failed encode left a file
that looked like a valid bug-report capture.  It now encodes under a .part
name and moves it into place only once the read and the encode both
finished cleanly; a read cut short by the end of the input (the window runs
past the last decoded field) keeps what there is and says so.  The loader,
the encoder pipe and the filesystem calls are stand-ins.
"""

import io
from types import SimpleNamespace

import numpy as np
import pytest

from lddecode import main as ldmain

pytestmark = [pytest.mark.unit, pytest.mark.format]


class FakePipe:
    def __init__(self):
        self.written = 0

    def write(self, data):
        self.written += len(data)

    def close(self):
        pass


@pytest.fixture
def harness(monkeypatch):
    state = SimpleNamespace(status=0, file_len=10**9, failed=None,
                            pipe=FakePipe(), replaced=[], unlinked=[], piped=[])

    class Loader:
        def __call__(self, infile, sample, length):
            if sample + length > state.file_len:
                return None
            return np.zeros(length, dtype=np.int16)

        @property
        def failed(self):
            return state.failed

    def ldf_pipe(name, compression_level=6):
        state.piped.append(name)
        return SimpleNamespace(wait=lambda: state.status), state.pipe

    monkeypatch.setattr(ldmain, "make_loader", lambda name, freq=None: Loader())
    monkeypatch.setattr(ldmain, "ldf_pipe", ldf_pipe)
    monkeypatch.setattr(ldmain, "open", lambda name, mode: io.BytesIO(), raising=False)
    monkeypatch.setattr(ldmain.os, "replace", lambda a, b: state.replaced.append((a, b)))
    monkeypatch.setattr(ldmain.os, "unlink", lambda a: state.unlinked.append(a))
    return state


def write(start=0, end=100_000):
    return ldmain.write_input_ldf_file(None, "bug.ldf", start, end, "capture.ldf")


def test_a_clean_write_is_encoded_aside_then_moved_into_place(harness, capsys):
    assert write() is True

    assert harness.piped == ["bug.ldf.part"]
    assert harness.replaced == [("bug.ldf.part", "bug.ldf")]
    assert harness.pipe.written == 100_000          # samples
    assert "Successfully wrote bug.ldf" in capsys.readouterr().err


def test_an_encoder_failure_leaves_no_file_and_no_claim_of_success(harness, capsys):
    harness.status = 1

    assert write() is False

    err = capsys.readouterr().err
    assert harness.replaced == []
    assert harness.unlinked == ["bug.ldf.part"]
    assert "ffmpeg exited with status 1" in err
    assert "Successfully" not in err


def test_an_input_that_failed_to_decode_leaves_no_file(harness, capsys):
    harness.file_len = 50_000
    harness.failed = "FLAC decode failed: bad frame"

    assert write() is False

    assert harness.replaced == []
    assert "FLAC decode failed" in capsys.readouterr().err


def test_the_end_of_the_input_keeps_what_there_is_and_says_so(harness, capsys):
    harness.file_len = 50_000

    assert write() is True

    err = capsys.readouterr().err
    assert harness.replaced == [("bug.ldf.part", "bug.ldf")]
    assert "the input ends at sample 49152" in err
    assert "Successfully" not in err
