"""Unit tests for --verboseVITS reaching the per-field vitsMetrics.

Every decode path precomputes a field's metrics in stage 2 (with every key)
and finishes them at commit with computeMetricsFP, which always cut the dict
down to DEFAULT_OUTPUT_KEYS.  The computeMetrics fallback that honoured
verboseVITS was never reached, so --verboseVITS had no effect on the output.
"""

from types import SimpleNamespace

import pytest

from lddecode.metrics import DEFAULT_OUTPUT_KEYS, computeMetricsFP

pytestmark = [pytest.mark.unit, pytest.mark.decode]

BASE = {"wSNR": 42.1, "bPSNR": 45.0, "greyIRE": 50.2, "whiteIRE": 99.8}


def _pal_field():
    return SimpleNamespace(rf=SimpleNamespace(system="PAL"))


def test_default_output_keeps_only_the_default_keys():
    out = computeMetricsFP(None, _pal_field(), None, BASE)

    assert out == {"wSNR": 42.1, "bPSNR": 45.0}
    assert set(out) <= set(DEFAULT_OUTPUT_KEYS)


def test_verbose_output_keeps_every_precomputed_key():
    out = computeMetricsFP(None, _pal_field(), None, BASE, verbose=True)

    assert out == BASE
