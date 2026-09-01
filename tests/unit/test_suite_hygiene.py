"""Guards the unit/functional boundary.

TESTING.md states the rule as a review failure: a file under ``tests/unit/``
must not reach for the filesystem, a subprocess, the network, or the
``testdata/`` submodule.  Review catches that unreliably, so it is asserted
here instead.

This module is a meta-test: it reads the test sources themselves.  The rule it
enforces is about the *dependencies a unit test pulls in* -- a test must not
depend on a capture file, an external tool or a network service to pass -- and
reading sibling sources creates no such dependency.  It is therefore excluded
from its own scan, along with the token list below, which necessarily spells
out the very strings it looks for.
"""

import pathlib

import pytest

pytestmark = [pytest.mark.unit]

UNIT_DIR = pathlib.Path(__file__).resolve().parent

#: Tokens that mean a suite has left the hermetic lane.  Each maps to the
#: replacement TESTING.md prescribes.
FORBIDDEN = {
    "open(": "build the input in the test, or use io.BytesIO for a byte stream",
    "subprocess": "inject a runner, or move the suite to tests/functional/",
    "tmp_path": "hold the data in memory; a unit test writes nothing",
    "requests": "a unit test makes no network calls",
    "testdata": "a suite needing real captures belongs in tests/functional/",
}

SELF = pathlib.Path(__file__).name


def unit_sources():
    """Every unit suite except this one."""
    return sorted(p for p in UNIT_DIR.rglob("test_*.py") if p.name != SELF)


@pytest.mark.parametrize("token", sorted(FORBIDDEN))
def test_unit_suites_are_hermetic(token):
    hits = []
    for source in unit_sources():
        # read_text rather than open() so the guard does not trip itself.
        if token in source.read_text(encoding="utf-8"):
            hits.append(source.relative_to(UNIT_DIR).as_posix())
    assert not hits, (
        f"{token!r} found in tests/unit/: {', '.join(hits)}. "
        f"{FORBIDDEN[token]}."
    )
