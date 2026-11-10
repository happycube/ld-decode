import importlib

import lddecode

import pytest

pytestmark = [pytest.mark.unit]


def test_can_import_key_modules():
    for mod in ("core", "utils", "fft8"):
        importlib.import_module(f"lddecode.{mod}")


def test_star_import_needs_no_notebook_dependencies():
    """utils_plotting needs IPython, which is not a package dependency."""
    assert "utils_plotting" not in lddecode.__all__
