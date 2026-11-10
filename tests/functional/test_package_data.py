"""Checks on the data files the lddecode package ships.

These read files out of the installed package, so they are functional tests
(AGENTS.md 4.1): they moved here from tests/unit/test_sinc_lut.py and
tests/unit/test_basic.py, whose unit lane may not touch the filesystem.

- lddecode/sinc_lut.npz is generated, so it can fall out of step with the
  parameters in dsp.py; the unit tests build the table in memory, and this
  pins the shipped file to the same builder.
- lddecode/version is written by CMake configure (or the Nix build), and
  lddecode.__version__ is read from it.
"""

from importlib import resources

import numpy as np
import pytest

import lddecode
from lddecode.dsp import build_kaiser_lut, kaiser_beta, sinc_phase_count, sinc_tap_count

pytestmark = [pytest.mark.functional, pytest.mark.format]


@pytest.fixture(scope="module")
def coarse():
    return build_kaiser_lut(kaiser_beta, sinc_tap_count, sinc_phase_count)


def test_shipped_table_is_what_the_parameters_build(coarse):
    """What catches a parameter change that was never regenerated."""
    shipped = np.load(resources.files("lddecode") / "sinc_lut.npz")["downscale_sinc_lut"]
    assert shipped.shape == coarse.shape
    assert shipped.dtype == coarse.dtype
    np.testing.assert_array_equal(shipped, coarse)


def test_shipped_table_stays_small_enough_to_cache():
    path = resources.files("lddecode") / "sinc_lut.npz"
    assert path.stat().st_size <= 64 * 1024
    lut = np.load(path)["downscale_sinc_lut"]
    assert lut.nbytes <= 64 * 1024


def test_version_matches_file():
    """The version file, where there is one, is what __version__ reports."""
    try:
        version_text = (resources.files(lddecode) / "version").read_text().strip()
    except FileNotFoundError:
        # Packaged builds may not carry the file
        pytest.skip("no lddecode/version in this build")
    assert lddecode.__version__ == version_text
