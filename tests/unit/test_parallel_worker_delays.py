"""Unit tests for worker processes adopting the parent's RF delays.

RFDecode.computedelays() measures the delays on a synthetic signal built from
the AGC-adjustable levels.  The parent measures them once, at construction,
and never again; a worker spawned after an AGC adjustment recomputed them from
the adjusted snapshot, moving video_rot by a few samples and with it every
dropout a worker flags, against the serial decode.
"""

import pytest

from lddecode import parallel, rfdecode

pytestmark = [pytest.mark.unit, pytest.mark.parallel]


class _FakeRF:
    def __init__(self, **_opts):
        self.DecoderParams = {}
        self.delays = None

    def computefilters(self):
        # What a worker would measure from a post-AGC snapshot
        self.delays = {"video_sync": 1.0, "video_white": 2.0, "video_rot": 9}


@pytest.fixture
def worker_env(monkeypatch):
    """Run the pool initializer in-process with nothing real behind it."""
    monkeypatch.setattr(parallel.signal, "signal", lambda *args: None)
    monkeypatch.setattr(
        parallel.threading, "Thread", lambda **kwargs: type("T", (), {"start": lambda self: None})()
    )
    monkeypatch.setattr(rfdecode, "RFDecode", _FakeRF)
    for name in ("_worker_rf", "_worker_cfg", "_worker_shared",
                 "_worker_video_slot", "_worker_mtf_slot"):
        monkeypatch.setattr(parallel, name, getattr(parallel, name))


def test_worker_adopts_the_parents_delays(worker_env):
    parent = {"video_sync": 1.5, "video_white": 2.5, "video_rot": 6}

    parallel._demod_worker_init({}, {"hz_ire": 1.0}, delays=parent)

    assert parallel._worker_rf.delays == parent
    assert parallel._worker_rf.delays is not parent


def test_worker_without_parent_delays_keeps_its_own(worker_env):
    parallel._demod_worker_init({}, {"hz_ire": 1.0})

    assert parallel._worker_rf.delays["video_rot"] == 9
