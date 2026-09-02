"""
test_vits_deviations - the list of faults the build agrees to carry

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The list exists so a lane with seventy-six known failures can still go red
for a new one, so the cases that matter are the ones where it must refuse to
stay quiet: a fault that got worse, a fault that was fixed and left listed,
and an entry naming a check nobody makes any more.  A list that cannot be
wrong is a list that hides the next regression.

No file is read: every case is entries and checks as mappings.
"""

import pytest

import vits_deviations as vd

pytestmark = [pytest.mark.unit, pytest.mark.vits]


def check(vits_id="pal-blanked-field1/blanked", verdict="FAIL", measured=1.105,
          **extra):
    record = {"id": vits_id, "verdict": verdict, "measured": measured,
              "unit": "IRE", "field_line": 22, "parity": "first",
              "limit": 1.0}
    record.update(extra)
    return record


def entry(capture="ggv1011-side1-inner",
          vits_id="pal-blanked-field1/blanked", **extra):
    record = {"capture": capture, "check": vits_id, "field_line": 22,
              "parity": "first", "reason": "left on a line that must blank"}
    record.update(extra)
    return record


def test_a_listed_failure_becomes_known():
    verdicts, complaints = vd.reconcile([check()], [entry()],
                                        "ggv1011-side1-inner")
    assert verdicts == [(0, "KNOWN", "left on a line that must blank")]
    assert complaints == []


def test_an_owner_is_carried_into_the_reason():
    verdicts, _ = vd.reconcile([check()], [entry(owner="Phase 8 task 2")],
                               "ggv1011-side1-inner")
    assert "owned by Phase 8 task 2" in verdicts[0][2]


def test_a_fault_worse_than_its_ceiling_is_still_a_failure():
    # 1.105 against a limit of 1.0 spends 1.11 of its band.
    verdicts, _ = vd.reconcile([check()], [entry(band_used=1.05, ceiling=1.08)],
                               "ggv1011-side1-inner")
    index, verdict, reason = verdicts[0]
    assert verdict == "FAIL"
    assert "worse than recorded" in reason


def test_a_fault_within_its_ceiling_stays_known():
    verdicts, _ = vd.reconcile([check()], [entry(band_used=1.11, ceiling=1.22)],
                               "ggv1011-side1-inner")
    assert verdicts[0][1] == "KNOWN"


def test_a_listed_check_that_now_passes_fails_the_build():
    _, complaints = vd.reconcile([check(verdict="PASS", measured=0.4)],
                                 [entry()], "ggv1011-side1-inner")
    assert len(complaints) == 1
    assert "delete the entry" in complaints[0][1]


def test_a_listed_check_the_run_never_made_fails_the_build():
    _, complaints = vd.reconcile([], [entry()], "ggv1011-side1-inner")
    assert len(complaints) == 1
    assert "no such check" in complaints[0][1]


def test_a_listed_check_that_was_skipped_fails_the_build():
    _, complaints = vd.reconcile([check(verdict="SKIP")], [entry()],
                                 "ggv1011-side1-inner")
    assert len(complaints) == 1
    assert "did not judge it" in complaints[0][1]


def test_an_entry_for_another_capture_is_not_consulted():
    verdicts, complaints = vd.reconcile(
        [check()], [entry(capture="ggv1069-side1-outer")],
        "ggv1011-side1-inner")
    assert (verdicts, complaints) == ([], [])


def test_the_same_check_on_another_line_is_another_measurement():
    # ggv1069-side1-inner carries its multiburst on three field lines of both
    # parities, so the identifier alone cannot say which reading is meant.
    verdicts, complaints = vd.reconcile(
        [check(field_line=23)], [entry()], "ggv1011-side1-inner")
    assert verdicts == []
    assert len(complaints) == 1


def test_a_capture_may_be_named_by_its_decoded_path():
    verdicts, _ = vd.reconcile([check()], [entry()],
                               "/build/testout/ggv1011-side1-inner.cvbs")
    assert verdicts[0][1] == "KNOWN"


def test_a_deviation_about_a_nominal_is_scored_against_its_band():
    assert vd.band_used({"measured": 106.422, "nominal": 100.735,
                         "band": 2.5}) == pytest.approx(2.2748, abs=1e-3)


def test_a_ceiling_with_no_nominal_is_scored_against_its_limit():
    assert vd.band_used({"measured": 123.862, "limit": 101.0}) == \
        pytest.approx(1.2264, abs=1e-3)


def test_a_check_with_no_number_has_no_band_figure():
    assert vd.band_used({"measured": float("nan"), "limit": 1.0}) is None
    assert vd.band_used({"measured": 1.0}) is None


def test_one_measurement_listed_twice_fails_the_build():
    _, complaints = vd.reconcile([check()], [entry(), entry()],
                                 "ggv1011-side1-inner")
    assert len(complaints) == 1
    assert "listed 2 times" in complaints[0][1]
