"""Command-line tests for ld-cut's refusal to write over its own input.

The guard's logic is unit tested in tests/unit/test_cut_input_guard.py; this
runs the real CLI on real files, because what is under test is that the
capture on disk survives: every ld-cut writer truncates its destination when
it opens it.
"""

import os
import subprocess
import sys

import pytest

pytestmark = [pytest.mark.functional, pytest.mark.format]

CAPTURE = bytes(range(256)) * 64


def _run_cut(*cli_args):
    return subprocess.run(
        [sys.executable, "-m", "lddecode.cut", *cli_args],
        capture_output=True,
    )


@pytest.mark.parametrize("name", ["capture.s16", "capture.lds", "capture.ldf"])
def test_cutting_a_capture_onto_itself_leaves_it_intact(tmp_path, name):
    capture = tmp_path / name
    capture.write_bytes(CAPTURE)

    result = _run_cut(str(capture), str(capture))

    assert result.returncode == 1
    assert b"is the input file" in result.stderr
    assert capture.read_bytes() == CAPTURE


def test_cutting_onto_a_link_to_the_capture_leaves_it_intact(tmp_path):
    capture = tmp_path / "capture.s16"
    capture.write_bytes(CAPTURE)
    link = tmp_path / "link.s16"
    os.symlink(capture, link)

    result = _run_cut(str(capture), str(link))

    assert result.returncode == 1
    assert capture.read_bytes() == CAPTURE
