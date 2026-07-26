"""Tests that a failed field decode is not mistaken for end-of-input.

Upstream (pre-split) decodefield() ran on a worker thread and communicated
through a shared dict pre-populated with field/offset None sentinels -- the
same values a genuine EOF returns.  A decode-time exception only unwound the
worker thread, so readfield() read the untouched sentinels back as EOF: the
decode stopped early but exited 0 and wrote metadata describing the truncated
output as complete.  Upstream fixed this by handing the exception back on the
shared dict (merge of PR #1052).

This tree decodes stage 1 on the main thread (readfield -> _advance_chain ->
decodefield), stage 2 through futures whose .result() re-raises, and worker
-process field jobs through an explicit {"error": ...} result that falls back
to an inline decode -- so an exception can no longer be silently read as EOF.
These tests pin that contract at the decodefield and readfield levels: a
failing field.process() must raise through to the caller, and only a failed
demod read (real EOF) may return the None sentinels.

This is not specific to any exception type; the tests use a meaningless
exception class, with the ZeroDivisionError from the original report kept as a
single named case.  Stub objects stand in for `self`: constructing a real
LDdecode requires an RF source, which is far more scaffolding than the
exception/EOF contract under test needs.
"""

import types
from collections import deque

import pytest

from lddecode.core import LDdecode


class _DecodeBoom(Exception):
    """An arbitrary decode-time failure.

    Deliberately not a builtin: the old sentinel/EOF collision swallowed *any*
    exception raised during a field decode, so the tests use an exception with
    no meaning of its own.  The ZeroDivisionError that surfaced this in the
    field is covered separately below, as one instance of the general case.
    """


class _BoomField:
    """Stands in for FieldClass; blows up in process() like a real bad field."""

    def __init__(self, *args, **kwargs):
        self.valid = False

    def process(self):
        raise _DecodeBoom("field failed to process")


def _decodefield_stub(rawdecode, exc=None):
    """Minimal `self` carrying only what decodefield() touches.

    `rawdecode` is what demod_read() returns (None = EOF).  A _BoomField
    raising `exc` (default _DecodeBoom) is decoded from it.
    """

    class _Boom(_BoomField):
        def process(self):
            raise (exc if exc is not None else _DecodeBoom("field failed to process"))

    return types.SimpleNamespace(
        rf=types.SimpleNamespace(blockcut=0),
        blocksize=32768,
        readlen=65536,
        readlen_first=65536,
        demod_read=lambda *a, **kw: rawdecode,
        FieldClass=_Boom,
        fields_written=0,
        wow_level_adjust_smoothing=None,
        wow_interpolation_method=None,
        curfield=None,
        use_profiler=False,
        system="NTSC",
    )


def _readfield_stub(rawdecode, exc=None):
    """Minimal `self` for readfield() driving the real stage-1 chain code.

    readfield() and _advance_chain() are the real (unbound) methods; only
    decodefield's inputs are stubbed, so the test exercises the actual
    exception/EOF path from readfield down to field.process().
    """
    stub = _decodefield_stub(rawdecode, exc)
    stub.second_decode = None
    stub.fieldstack = []
    stub.fdoffset = 0
    stub.mtf_level = 0
    stub._job_engine = None
    stub._job_eof = False
    stub._pipeline = deque()
    stub._pipeline_depth = 1
    stub._chain_eof = False
    stub._chain_prev = None
    stub.pipeline_warm = False
    stub._stage2_pool = None
    stub.decodefield = types.MethodType(LDdecode.decodefield, stub)
    stub._advance_chain = types.MethodType(LDdecode._advance_chain, stub)
    return stub


def test_decodefield_raises_a_failed_field_process():
    """A field that fails to process raises through to the caller."""
    stub = _decodefield_stub({"startloc": 0})

    with pytest.raises(_DecodeBoom):
        LDdecode.decodefield(stub, 0, 0)


def test_decodefield_returns_sentinels_at_eof():
    """A real EOF (no rawdecode) returns the bare (None, None) sentinels."""
    stub = _decodefield_stub(None)

    assert LDdecode.decodefield(stub, 0, 0) == (None, None)


def test_readfield_raises_a_failed_field_decode():
    """The failure surfaces from readfield() instead of reading as EOF."""
    stub = _readfield_stub({"startloc": 0})

    with pytest.raises(_DecodeBoom):
        LDdecode.readfield(stub)


def test_readfield_raises_the_reported_zerodivisionerror():
    """The specific failure this was found through, as one case of the general one.

    A ZeroDivisionError out of a field's process() is what truncated a real
    capture at 43% while exiting 0 upstream. It gets its own test only so the
    report has a regression test that names it -- nothing here is specific to
    the exception type.
    """
    stub = _readfield_stub({"startloc": 0}, exc=ZeroDivisionError("float division by zero"))

    with pytest.raises(ZeroDivisionError):
        LDdecode.readfield(stub)


def test_readfield_still_reports_eof_as_eof():
    """A clean (None, None) from decodefield must keep meaning end-of-input."""
    stub = _readfield_stub(None)

    assert LDdecode.readfield(stub) is None
    # EOF pushes the None terminator onto the fieldstack.
    assert stub.fieldstack == [None]
