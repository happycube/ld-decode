"""Unit tests for compare_efm_data's sector alignment.

The offset between the reference and the stacked image is negative whenever
the reference carries more leading blank sectors than the image.  The old
slice imgs[off:off + n] then counted from the end of the image, which either
crashed on mismatched shapes or compared the wrong sectors.
"""

import numpy as np
import pytest

from lddecode import compare_efm_data

pytestmark = [pytest.mark.unit]

SEC = compare_efm_data.SEC


def _sectors(rng, count):
    return rng.integers(1, 256, size=(count, SEC), dtype=np.uint8)


def _run(image, reference, monkeypatch, capsys):
    files = {"data.bin": image.ravel(), "ref.bin": reference.ravel()}
    monkeypatch.setattr(compare_efm_data.np, "fromfile", lambda name, dtype: files[name])
    compare_efm_data.main(["data.bin", "ref.bin"])
    return capsys.readouterr().out


def test_reference_with_more_leading_blanks_aligns(monkeypatch, capsys):
    rng = np.random.default_rng(12345)
    data = _sectors(rng, 50)
    reference = np.vstack([np.zeros((10, SEC), np.uint8), data])
    image = np.vstack([np.zeros((3, SEC), np.uint8), data])

    out = _run(image, reference, monkeypatch, capsys)

    assert "OFFSET = -7" in out
    assert "reproduced byte-identical: 50 (100.0000%)" in out
    assert "MISSED (blank in image):   0" in out


def test_image_with_more_leading_blanks_aligns(monkeypatch, capsys):
    rng = np.random.default_rng(12345)
    data = _sectors(rng, 50)
    reference = np.vstack([np.zeros((2, SEC), np.uint8), data])
    image = np.vstack([np.zeros((9, SEC), np.uint8), data])

    out = _run(image, reference, monkeypatch, capsys)

    assert "OFFSET = 7" in out
    assert "reproduced byte-identical: 50 (100.0000%)" in out
