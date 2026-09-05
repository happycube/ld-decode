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
import sys

import numpy as np
import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

#: analysis/ holds the measurement oracles.  It is a directory of scripts
#: rather than an installed package, and they import each other by bare module
#: name, so it has to be on sys.path for a test to reach the measurement maths
#: AGENTS.md 4.5 asks to be covered there.  This is an import path only: it
#: opens no file, so a unit suite importing from it stays hermetic.
ANALYSIS_DIR = REPO_ROOT / "analysis"
if str(ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYSIS_DIR))

#: scripts/ holds the developer measurement harnesses.  Like analysis/ it is a
#: directory of scripts rather than a package, so it has to be on sys.path for a
#: test to reach the pure helpers inside one (argv construction, log parsing,
#: the footprint recorders).  Import path only: nothing here opens a file.
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

#: The ld-decode-testdata submodule.  Functional suites that read real captures
#: locate them from here; nothing under tests/unit/ may refer to it.
TESTDATA = REPO_ROOT / "testdata"

UNIT_DIR = pathlib.Path(__file__).resolve().parent / "unit"
FUNCTIONAL_DIR = pathlib.Path(__file__).resolve().parent / "functional"

#: Which marker a test collected from each lane must carry.  TESTING.md states
#: the rule for both lanes, so it is enforced for both: an unmarked functional
#: suite would drop out of "-m functional" exactly as quietly as an unmarked
#: unit one drops out of "-m unit".
LANE_MARKER = {UNIT_DIR: "unit", FUNCTIONAL_DIR: "functional"}

#: The seed used by every unit test that needs pseudo-random input.  A single
#: shared value keeps failures reproducible across suites and makes it obvious
#: in a diff when a test has reached for bare np.random instead.
DEFAULT_SEED = 12345


def pytest_collection_modifyitems(config, items):
    """Fail the run if a test carries the wrong lane marker, or none.

    An unmarked test still executes, so without this check ``-m unit`` or
    ``-m functional`` would quietly skip it and that lane would rot.  Raising
    at collection time reports every offender at once rather than one per run.

    The markers are looked up with iter_markers rather than ``item.keywords``:
    keywords also carries the names of the parent collectors, and the lane
    directories are themselves called "unit" and "functional", so every test
    would look marked.
    """
    missing = []
    crossed = []

    for item in items:
        markers = {marker.name for marker in item.iter_markers()}
        for directory, lane in LANE_MARKER.items():
            if directory not in item.path.parents:
                continue
            if lane not in markers:
                missing.append(f"{item.nodeid}  (needs {lane})")
            # A test claiming both lanes satisfies either filter, so it would
            # run in the fast lane while declaring that it needs real data.
            if markers & ({"unit", "functional"} - {lane}):
                crossed.append(item.nodeid)

    problems = []
    if missing:
        problems.append(
            "these tests are missing their lane marker; add "
            "`pytestmark = [pytest.mark.<lane>, pytest.mark.<family>]` to:\n  "
            + "\n  ".join(missing)
        )
    if crossed:
        problems.append(
            "these tests carry both lane markers, which puts them in both "
            "lanes at once; a test belongs to exactly one:\n  "
            + "\n  ".join(crossed)
        )
    if problems:
        raise pytest.UsageError("\n".join(problems))


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
