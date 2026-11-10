"""Command-line tests for analysis/cvbs_verify.py on an incomplete capture.

With the .meta missing, the verifier printed "[FAIL] .meta present" and then
called sqlite3.connect() on the name anyway, which created a 0-byte .meta and
died with sqlite3.OperationalError instead of printing the CVBS VERIFY: FAIL
line CTest matches.  It now stops there, and opens the .meta read-only.
"""

import pathlib
import subprocess
import sys

import pytest

pytestmark = [pytest.mark.functional, pytest.mark.format]

VERIFY = pathlib.Path(__file__).resolve().parents[2] / "analysis" / "cvbs_verify.py"


def _verify(path):
    return subprocess.run([sys.executable, str(VERIFY), str(path)],
                          capture_output=True, text=True)


def test_a_capture_without_its_meta_fails_and_creates_nothing(tmp_path):
    capture = tmp_path / "x.cvbs"
    capture.write_bytes(bytes(1024))

    result = _verify(capture)

    assert result.returncode == 1
    assert "CVBS VERIFY: FAIL" in result.stdout
    assert "Traceback" not in result.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.cvbs"]


def test_a_missing_capture_fails_by_name(tmp_path):
    result = _verify(tmp_path / "absent.cvbs")

    assert result.returncode == 1
    assert "[FAIL] absent.cvbs present" in result.stdout
    assert list(tmp_path.iterdir()) == []
