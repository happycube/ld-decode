"""Guards the unit/functional boundary.

TESTING.md states the rule as a review failure: a file under ``tests/unit/``
must not reach for the filesystem, a subprocess, the network, or the
``testdata/`` submodule.  Review catches that unreliably, so it is asserted
here instead.

Only executable code is scanned.  Comments and docstrings are stripped first,
because a prose reference to a capture file -- citing which spec sheet a
constant came from, say -- documents where a number originated; it creates no
dependency, and rewording documentation to satisfy a grep would be the wrong
direction of travel.

This module is a meta-test: it reads the test sources themselves.  The rule it
enforces is about the *dependencies a unit test pulls in* -- a test must not
need a capture file, an external tool or a network service to pass -- and
reading sibling sources creates no such dependency.  It is excluded from its
own scan, since the token table below necessarily spells out, as live code, the
very strings it looks for.
"""

import ast
import io
import pathlib
import tokenize

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


def code_only(source):
    """Return source with comments and docstrings blanked out.

    Blanks in place rather than deleting, so that a token spanning what is
    removed cannot be spliced together with its neighbour into a match that
    was never in the file.
    """
    lines = source.splitlines()

    def blank(start, end):
        (srow, scol), (erow, ecol) = start, end
        for row in range(srow, erow + 1):
            line = lines[row - 1]
            first = scol if row == srow else 0
            last = ecol if row == erow else len(line)
            lines[row - 1] = line[:first] + " " * (last - first) + line[last:]

    # A leading bare string is a docstring on a module, class or function.  The
    # same shape inside an if/for body is dead code, and treating it as prose
    # too costs nothing.
    docstrings = set()
    for node in ast.walk(ast.parse(source)):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            docstrings.add((first.value.lineno, first.value.col_offset))

    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT or (
            tok.type == tokenize.STRING and tok.start in docstrings
        ):
            blank(tok.start, tok.end)

    return "\n".join(lines)


@pytest.mark.parametrize("token", sorted(FORBIDDEN))
def test_unit_suites_are_hermetic(token):
    hits = []
    for source in unit_sources():
        # read_text rather than open() so the guard does not trip itself.
        if token in code_only(source.read_text(encoding="utf-8")):
            hits.append(source.relative_to(UNIT_DIR).as_posix())
    assert not hits, (
        f"{token!r} found in tests/unit/: {', '.join(hits)}. " f"{FORBIDDEN[token]}."
    )
