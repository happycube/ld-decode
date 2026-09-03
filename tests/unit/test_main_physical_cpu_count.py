"""Unit tests for the auto thread count's core detection in lddecode.main.

SMT siblings share a core, and the FFT-bound workers gain nothing from
being scheduled on both siblings, so the auto count is derived from
physical cores: the distinct thread_siblings_list entries of the Linux
CPU topology.
"""

import pytest

from lddecode.main import count_cores, physical_cpu_count

pytestmark = [pytest.mark.unit, pytest.mark.parallel]


def test_smt_siblings_count_as_one_core():
    # an 8-core / 16-thread part: cpu k pairs with cpu k+8
    lists = [f"{k % 8},{k % 8 + 8}" for k in range(16)]
    assert count_cores(lists) == 8


def test_cores_without_smt_count_one_each():
    assert count_cores([str(k) for k in range(6)]) == 6


def test_ranges_and_blank_entries_are_understood():
    assert count_cores(["0-3", "4-7", "", "0-3\n"]) == 2


def test_missing_topology_falls_back_to_the_logical_count(monkeypatch):
    import os
    monkeypatch.setattr(os, "cpu_count", lambda: 12)
    assert physical_cpu_count(sysfs="/nonexistent/sysfs") == 12
