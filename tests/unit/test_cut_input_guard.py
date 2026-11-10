"""Unit tests for ld-cut refusing arguments that would destroy or misread its input.

Every ld-cut writer opens its destination for writing (ffmpeg with -y), so
`ld-cut capture.lds capture.lds` truncated the capture to nothing before the
first read.  ld-cut now refuses an output that is the input before it opens
anything, and refuses a negative --start or a --length under one frame.  The
path checks are replaced here so no test touches the filesystem.
"""

import os

import pytest

from lddecode import cut

pytestmark = [pytest.mark.unit]


class _Opened(Exception):
    """Raised by the stand-ins for anything that opens the input."""


def _refuse(*args, **kwargs):
    raise _Opened()


@pytest.fixture
def paths(monkeypatch):
    """os.path.exists/samefile/realpath over a table of names instead of disk.

    `aliases` maps a name to the file it is (a link, /dev/stdout redirected);
    `existing` lists the names that exist."""
    state = {"aliases": {}, "existing": set()}

    def ident(name):
        return state["aliases"].get(name, name)

    monkeypatch.setattr(cut.os.path, "exists", lambda name: name in state["existing"])
    monkeypatch.setattr(cut.os.path, "samefile", lambda a, b: ident(a) == ident(b))
    monkeypatch.setattr(cut.os.path, "realpath",
                        lambda name: os.path.normpath(os.path.join("/work", name)))
    return state


@pytest.fixture
def nothing_opens(monkeypatch):
    monkeypatch.setattr(cut, "make_loader", _refuse)
    monkeypatch.setattr(cut, "LDdecode", _refuse)


def test_the_same_name_is_the_same_file(paths):
    assert cut.same_file("capture.lds", "capture.lds")


def test_another_spelling_of_the_same_path_is_the_same_file(paths):
    assert cut.same_file("capture.lds", "./sub/../capture.lds")


def test_a_link_to_the_input_is_the_same_file(paths):
    paths["existing"] |= {"capture.lds", "link.lds"}
    paths["aliases"]["link.lds"] = "capture.lds"

    assert cut.same_file("capture.lds", "link.lds")


def test_stdout_redirected_onto_the_input_is_the_same_file(paths):
    paths["existing"] |= {"capture.raw", "/dev/stdout"}
    paths["aliases"]["/dev/stdout"] = "capture.raw"

    assert cut.same_file("capture.raw", "/dev/stdout")


def test_a_different_output_is_not_the_same_file(paths):
    paths["existing"] |= {"capture.lds", "out.lds"}

    assert not cut.same_file("capture.lds", "out.lds")


def test_stdin_input_is_never_the_output(paths):
    assert not cut.same_file("-", "-")


def test_main_refuses_to_cut_onto_its_input_before_opening_it(paths, nothing_opens, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cut.main(["capture.lds", "capture.lds"])

    assert exit_info.value.code == 1
    assert "is the input file" in capsys.readouterr().err


@pytest.mark.parametrize("cli_args, message", [
    (["-s", "-5"], "--start must not be negative"),
    (["-l", "0"], "--length must be at least 1 frame"),
    (["-l", "-3"], "--length must be at least 1 frame"),
])
def test_main_refuses_a_bad_range_before_opening_the_input(paths, nothing_opens, capsys,
                                                           cli_args, message):
    with pytest.raises(SystemExit) as exit_info:
        cut.main(["capture.lds", "out.lds", *cli_args])

    assert exit_info.value.code == 1
    assert message in capsys.readouterr().err
