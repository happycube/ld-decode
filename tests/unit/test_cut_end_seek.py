"""Unit tests for how ld-cut seeks to its end frame.

LDdecode.seek(startframe, target) takes a frame to start probing from, but
ld-cut passed the start *field*, so the first probe for the -E frame landed at
twice the right position -- past EOF for any cut starting beyond the middle of
a capture, after which the seek fell back to the lead-in and failed.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from lddecode import cut

pytestmark = [pytest.mark.unit]


class _FakeLDdecode:
    """Seeks to field 2 * frame, and reads nothing (so no samples are cut)."""

    seeks = []

    def __init__(self, *args, **kwargs):
        self.fdoffset = 0
        self.infile = None

    def seek(self, startframe, target):
        self.seeks.append((startframe, target))
        return target * 2

    def roughseek(self, location):
        self.fdoffset = location * 1000

    def freader(self, infile, sample, length):
        return None


class _FakeWriter:
    def __init__(self, name):
        self.written = []

    def write(self, data):
        self.written.append(np.asarray(data))

    def close(self):
        pass


@pytest.fixture
def fake_cut(monkeypatch):
    _FakeLDdecode.seeks = []
    monkeypatch.setattr(cut, "LDdecode", _FakeLDdecode)
    monkeypatch.setattr(cut, "make_loader", lambda name, freq: None)
    monkeypatch.setattr(cut, "init_logging", lambda name: None)
    monkeypatch.setattr(cut, "LdsWriter", _FakeWriter)
    monkeypatch.setattr(cut.signal, "signal", lambda *args: None)


def test_end_seek_starts_from_the_start_frame_not_field(fake_cut):
    cut.main(["capture.lds", "out.lds", "-S", "40000", "-E", "40010"])

    # The start seek returns field 80000; the cut starts a field earlier,
    # and the end search must probe from frame ~40000, not 79999.
    assert _FakeLDdecode.seeks[0] == (40000, 40000)
    startframe, target = _FakeLDdecode.seeks[1]
    assert target == 40010
    assert startframe == 79999 // 2


def test_end_seek_after_a_rough_start(fake_cut):
    cut.main(["capture.lds", "out.lds", "-s", "300", "-E", "310"])

    assert _FakeLDdecode.seeks == [(300, 310)]
