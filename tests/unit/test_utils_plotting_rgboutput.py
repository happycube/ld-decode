"""Unit tests for the notebook helper that renders a .tbc through ld-chroma-decoder.

RGBoutput built "ld-chroma-decoder {0}.tbc {0}.rgb" from the name and ran it
with shell=True, so a name holding shell metacharacters ran as a command
(AGENTS.md 3), and its error path then crashed on bytes.split and on a None
match.  It now passes an argument list and raises RuntimeError with what the
tool said.  The runner is a stand-in, passed in.
"""

from types import SimpleNamespace

import pytest

utils_plotting = pytest.importorskip("lddecode.utils_plotting")

pytestmark = [pytest.mark.unit]


def fake_run(returncode, stderr, calls):
    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(returncode=returncode, stderr=stderr)
    return run


def test_the_name_is_passed_as_an_argument_not_through_a_shell():
    calls = []

    with pytest.raises(RuntimeError):
        utils_plotting.RGBoutput("out; touch pwned", run=fake_run(1, b"", calls))

    cmd, kwargs = calls[0]
    assert cmd == ["ld-chroma-decoder", "out; touch pwned.tbc", "out; touch pwned.rgb"]
    assert not kwargs.get("shell")


def test_a_failed_decode_raises_with_what_the_tool_said():
    with pytest.raises(RuntimeError, match="status 2:\ncannot open input"):
        utils_plotting.RGBoutput("out", run=fake_run(2, b"cannot open input\n", []))


def test_output_without_a_picture_size_raises():
    with pytest.raises(RuntimeError, match="did not report a picture size"):
        utils_plotting.RGBoutput("out", run=fake_run(0, b"done\n", []))


def test_a_missing_tool_raises():
    def run(cmd, **kwargs):
        raise FileNotFoundError("ld-chroma-decoder")

    with pytest.raises(RuntimeError, match="could not run ld-chroma-decoder"):
        utils_plotting.RGBoutput("out", run=run)
