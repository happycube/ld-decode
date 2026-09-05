"""Unit tests for the pure parts of ``scripts/report_decode_traffic.py``.

The traffic report is what Phase 4 of the throughput plan argued from, so
the parts of it that can be wrong *quietly* are covered here: the
resolution of a dotted stage path to the attribute it has to replace, the
array-byte tally, and above all the exclusive attribution - a stage is
charged what it caused minus what the wrapped stages it called caused,
and getting that arithmetic wrong would silently move traffic from one
named stage to another.

Hermetic: no decoder is run and no PMU counter is opened.  The counter
group is replaced by a list of readings, which is the seam the
attribution logic was written to have.
"""

import collections
import threading

import numpy as np
import pytest

from report_decode_traffic import Instrument, Tally, _array_bytes, _resolve

pytestmark = [pytest.mark.unit, pytest.mark.parallel]


class FakeCounters:
    """Returns the next reading each time it is read."""

    def __init__(self, readings):
        self.readings = list(readings)
        self.n = 0

    def read(self):
        r = self.readings[self.n]
        self.n += 1
        return list(r)


def instrument(readings, n_events=1):
    """An Instrument wired to a fake counter group, no PMU involved."""
    inst = Instrument.__new__(Instrument)
    inst.events = [("l2_miss", 0, 0)][:n_events]
    inst.n = n_events
    inst._lock = threading.Lock()
    inst.tallies = collections.defaultdict(lambda: Tally(n_events))
    inst.patched = []
    inst.threads = []
    inst.warmup_fields = 0
    inst.fields = 0
    inst.counting_from = 0.0
    counters = FakeCounters(readings)
    stack = []
    inst._state = lambda: (counters, stack, "T")
    return inst


# --- resolving a stage path ---------------------------------------------


def test_a_dotted_path_resolves_to_the_owner_and_the_attribute():
    owner, name, target = _resolve("lddecode.rfdecode.RFDecode.demodblock")
    from lddecode.rfdecode import RFDecode

    assert owner is RFDecode and name == "demodblock"
    assert target is RFDecode.demodblock


def test_a_module_level_function_resolves_to_its_module():
    import lddecode.dsp as dsp

    owner, name, target = _resolve("lddecode.dsp.concatenate_blocks")
    assert owner is dsp and name == "concatenate_blocks"


def test_an_unknown_attribute_is_an_error_rather_than_a_silent_miss():
    with pytest.raises(ValueError):
        _resolve("lddecode.dsp.no_such_function")


# --- what a call moved ---------------------------------------------------


def test_array_bytes_counts_arrays_one_level_into_containers():
    a = np.zeros(10, dtype=np.float64)     # 80 bytes
    b = np.zeros(4, dtype=np.int16)        # 8 bytes
    assert _array_bytes(a) == 80
    assert _array_bytes((a, b)) == 88
    assert _array_bytes({"x": a, "y": [b]}) == 88
    assert _array_bytes(b"1234") == 4
    assert _array_bytes(3.0) == 0


# --- the exclusive attribution ------------------------------------------


def test_a_stage_is_charged_what_it_caused_less_what_its_children_did():
    # outer runs from 0 to 100; inner runs from 10 to 40 inside it.
    inst = instrument([[0], [10], [40], [100]])

    def inner():
        return np.zeros(2, dtype=np.int8)

    wrapped_inner = inst.wrap("inner", inner)

    def outer():
        return wrapped_inner()

    inst.wrap("outer", outer)()

    assert inst.tallies[("T", "inner")].excl == [30]
    assert inst.tallies[("T", "inner")].incl == [30]
    assert inst.tallies[("T", "outer")].excl == [70]
    assert inst.tallies[("T", "outer")].incl == [100]


def test_two_children_are_both_taken_off_their_parent():
    inst = instrument([[0], [5], [15], [20], [50], [100]])
    child = inst.wrap("child", lambda: None)
    inst.wrap("parent", lambda: (child(), child()))()

    assert inst.tallies[("T", "child")].calls == 2
    assert inst.tallies[("T", "child")].excl == [40]   # 10 + 30
    assert inst.tallies[("T", "parent")].excl == [60]  # 100 - 40


def test_a_stage_that_raises_is_still_charged_and_still_unwinds():
    inst = instrument([[0], [7], [30], [40]])

    def boom():
        raise ValueError("no")

    child = inst.wrap("child", boom)

    def parent():
        try:
            child()
        except ValueError:
            pass

    inst.wrap("parent", parent)()

    assert inst.tallies[("T", "child")].excl == [23]
    assert inst.tallies[("T", "parent")].excl == [17]


def test_the_bytes_of_the_arguments_and_the_result_are_recorded():
    inst = instrument([[0], [1]])
    arg = np.zeros(8, dtype=np.float32)          # 32 bytes
    out = np.zeros(3, dtype=np.float64)          # 24 bytes
    inst.wrap("stage", lambda a: out)(arg)

    t = inst.tallies[("T", "stage")]
    assert t.bytes_in == 32 and t.bytes_out == 24


def test_the_warm_up_discard_clears_everything_counted_so_far():
    inst = instrument([[0], [10], [10], [20], [20], [33]])
    inst.warmup_fields = 2
    stage = inst.wrap("stage", lambda: None)
    writeout = inst.wrap("writeout", lambda: None)

    stage()          # warm-up traffic
    writeout()       # field 1
    writeout()       # field 2 - the discard happens here
    assert ("T", "stage") not in dict(inst.tallies)
    assert inst.tallies[("T", "writeout")].calls == 1
