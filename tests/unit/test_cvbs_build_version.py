"""Unit tests for the git branch and commit the metadata records.

The CVBS specification defines .meta's git_commit as the commit hash
(cvbs-file-format-specification/docs/index.md, cvbs_file.git_commit).  The
writer split the version string on ":" alone, so a CMake build's
"8.0.0dev:8.0.0pre1+git.16dc70f0:dirty" recorded git_commit as
"8.0.0pre1+git.16dc70f0:dirty", and a Nix build's "8.0.0pre1+git.16dc70f0"
recorded the whole version as git_branch.  The .tbc.db had the first of
these too.  Both now read the version through parse_build_version.
"""

import pytest

from lddecode.cvbs import parse_build_version

pytestmark = [pytest.mark.unit, pytest.mark.format]


@pytest.mark.parametrize("version, expected", [
    # CMake configure: branch:base+git.<shortrev>[:dirty]
    ("8.0.0dev:8.0.0pre1+git.16dc70f0:dirty", ("8.0.0dev", "16dc70f0")),
    ("8.0.0dev:8.0.0pre1+git.16dc70f0", ("8.0.0dev", "16dc70f0")),
    ("release:8.0.0pre1+git.16dc70f0", ("release", "16dc70f0")),
    ("release:unknown+git.unknown", ("release", None)),
    # Nix: base+git.<shortrev>[.dirty], no branch
    ("8.0.0pre1+git.16dc70f0", (None, "16dc70f0")),
    ("8.0.0pre1+git.16dc70f0.dirty", (None, "16dc70f0")),
    # older builds: branch/commit
    ("main/16dc70f0", ("main", "16dc70f0")),
    # nothing recorded
    ("unknown", (None, None)),
    ("", (None, None)),
    (None, (None, None)),
])
def test_the_version_string_gives_the_branch_and_commit_hash(version, expected):
    assert parse_build_version(version) == expected


def test_a_trailing_newline_is_not_part_of_the_commit():
    assert parse_build_version("8.0.0dev:8.0.0pre1+git.16dc70f0\n") == (
        "8.0.0dev", "16dc70f0")
