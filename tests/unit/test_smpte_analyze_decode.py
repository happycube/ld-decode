"""Unit tests for smpte_analyze --decode asking ld-decode for a TBC.

The analyser reads .tbc/.tbc.db, but ld-decode writes CVBS by default, so
decode_lds ran a full decode and then raised FileNotFoundError for a .tbc
that was never going to appear.  It now passes --tbc.  The runner (passed
in) and the existence check are stand-ins.
"""

from types import SimpleNamespace

import pytest

import smpte_analyze

pytestmark = [pytest.mark.unit]


def test_the_decode_asks_for_tbc_output(monkeypatch):
    commands = []

    def run(cmd, **kwargs):
        commands.append(cmd)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(smpte_analyze.os.path, "exists",
                        lambda path: bool(commands) and path == "/out/bars.tbc")

    assert smpte_analyze.decode_lds("bars.lds", "/out/bars", "PAL",
                                    run=run) == "/out/bars.tbc"
    assert "--tbc" in commands[0]
    assert "--PAL" in commands[0]
