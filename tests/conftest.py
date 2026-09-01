"""Shared fixtures and the unit/functional lane split.

Two lanes live under this directory:

``tests/unit/``
    Hermetic suites.  No filesystem, no network, no subprocess, no clock.
    Every input is synthesised in the test and every generator is seeded, so a
    run is deterministic and needs nothing checked out beyond the source tree.

``tests/functional/``
    Suites that need real capture data from the ``testdata/`` submodule, an
    external tool, or a full decode run.  These skip rather than fail when what
    they need is absent.

See TESTING.md for the full rules.  This file enforces the one rule that cannot
be left to review alone: a test collected from ``tests/unit/`` must carry the
``unit`` marker.
"""

import copy
import pathlib

import numpy as np
import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

#: The ld-decode-testdata submodule.  Functional suites that read real captures
#: locate them from here; nothing under tests/unit/ may refer to it.
TESTDATA = REPO_ROOT / "testdata"

UNIT_DIR = pathlib.Path(__file__).resolve().parent / "unit"

#: The seed used by every unit test that needs pseudo-random input.  A single
#: shared value keeps failures reproducible across suites and makes it obvious
#: in a diff when a test has reached for bare np.random instead.
DEFAULT_SEED = 12345


def pytest_collection_modifyitems(config, items):
    """Fail the run if anything under tests/unit/ is missing the unit marker.

    An unmarked test still executes, so without this check ``-m unit`` would
    quietly skip it and the fast lane would rot.  Raising at collection time
    reports every offender at once rather than one per run.

    The marker is looked up with iter_markers rather than ``item.keywords``:
    keywords also carries the names of the parent collectors, and the parent
    directory here is itself called "unit", so every test would look marked.
    """
    offenders = [
        item.nodeid
        for item in items
        if UNIT_DIR in item.path.parents and not any(item.iter_markers(name="unit"))
    ]
    if offenders:
        raise pytest.UsageError(
            "tests under tests/unit/ must be marked with pytest.mark.unit; "
            "add `pytestmark = [pytest.mark.unit, pytest.mark.<family>]` to:\n  "
            + "\n  ".join(offenders)
        )


@pytest.fixture
def testdata():
    """Path to the testdata submodule, skipping when it is not checked out.

    Functional use only.  A missing submodule is a setup state, not a failure,
    so the tests that need real captures skip instead of going red.
    """
    if not (TESTDATA / "ntsc").is_dir():
        pytest.skip("testdata submodule not checked out")
    return TESTDATA


@pytest.fixture
def seeded_rng():
    """A seeded NumPy generator.

    TESTING.md forbids bare ``np.random.*`` in tests: a run that is not
    reproducible cannot distinguish a real regression from a bad draw.
    """
    return np.random.default_rng(DEFAULT_SEED)


@pytest.fixture
def sysparams_ntsc():
    """A fresh copy of SysParams_NTSC.

    params.py mutates its tables in place at import time, and the decoder
    mutates them further per run, so tests get a deep copy rather than the
    module-level dict; otherwise one test's parameter tweak leaks into the next.
    """
    from lddecode.params import SysParams_NTSC

    return copy.deepcopy(SysParams_NTSC)


@pytest.fixture
def sysparams_pal():
    """A fresh copy of SysParams_PAL.  See sysparams_ntsc for why it is copied."""
    from lddecode.params import SysParams_PAL

    return copy.deepcopy(SysParams_PAL)
