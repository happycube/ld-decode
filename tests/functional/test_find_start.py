"""End-to-end coverage for ld-find-start (lddecode.start_finder).

The unit lane (tests/unit/test_start_finder.py) pins the run-detector's
logic on synthetic observations; this suite gates the tool's CLI contract
on real RF: scanning a real capture, decoding real VBI, and reporting a
start position a decode can begin from.

The capture, testdata/ntsc/ggv1016-side1-start.ldf, is a 40-frame cut of a
GGV1016 side 1 (NTSC CAV) capture beginning at the first qualifying VBI run.
The full capture opens 219 file frames earlier, in the lead-in, and
ld-find-start reports --start 219 for it; the cut begins inside that run, so
the finder must lock on the first probe and report a start in the file's
first seconds.

The cut is 40 frames rather than the token few a tool this cheap could use
because a run is only confirmed after REQUIRED_VBI_FRAMES (30) contiguous
advancing frame addresses, and the preamble probe advances in one-second
strides until a field decodes valid, so the capture must begin inside the
run and still hold the whole confirmation window.
"""

import pathlib
import re
import subprocess
import sys

import pytest

# tests/functional/<this file> -> the repo root is two levels up.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE_LDF = REPO_ROOT / "testdata" / "ntsc" / "ggv1016-side1-start.ldf"

pytestmark = [
    pytest.mark.functional,
    pytest.mark.decode,
    pytest.mark.skipif(
        not SOURCE_LDF.exists(), reason="testdata submodule not checked out"
    ),
]


def test_find_start_confirms_the_cav_run_at_the_first_frame():
    result = subprocess.run(
        [sys.executable, "-m", "lddecode.start_finder", str(SOURCE_LDF), "-n"],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr

    # The one thing a consumer parses: the ld-decode --start argument.
    match = re.fullmatch(r"--start (\d+)\n", result.stdout)
    assert match is not None, repr(result.stdout)
    # The cut begins inside the run and the pre-roll replay is bounded by the
    # file start, so the reported start must sit in the file's first seconds.
    assert 0 <= int(match.group(1)) < 10

    # The confirmed-VBI path, not the guarded stable-video fallback (which
    # would exit 2 with a WARNING line instead).
    assert "found CAV run" in result.stderr
