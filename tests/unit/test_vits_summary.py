"""
test_vits_summary - the CI table a conformance run is read through

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The summary is what a red CI run is judged by before anyone downloads an
artefact, so the two claims that matter are that a failing check reaches the
table with its measurement intact, and that a capture whose checks were all
skipped is never rendered as a pass - the case the manifest exists to make
visible.

No file is read: every case is a payload of the shape
vits_conformance.json_payload builds.
"""

import pytest

import vits_summary as vs

pytestmark = [pytest.mark.unit, pytest.mark.vits]


def payload(name, system="PAL", fields=50, checks=(), **summary):
    """A report of the shape vits_conformance.json_payload writes."""
    counts = {"passed": 0, "failed": 0, "known": 0, "skipped": 0}
    counts.update(summary)
    return {
        "context": {"path": f"/build/testout/{name}.cvbs", "system": system,
                    "fields": fields},
        "checks": list(checks),
        "summary": counts,
    }


def check(vits_id="pal-its-field1/pulse_2t", verdict="FAIL", measured=106.422,
          unit="IRE", **extra):
    entry = {"id": vits_id, "verdict": verdict, "measured": measured,
             "unit": unit, "clause": "IEC 60856-1986 9.1.3",
             "field_line": 19, "reason": ""}
    entry.update(extra)
    return entry


def test_a_capture_is_named_as_the_manifest_labels_it():
    rows = vs.capture_rows([payload("ggv1011-side1-inner", passed=45)])
    assert rows[0][0] == "ggv1011-side1-inner"


def test_a_capture_with_a_failure_is_a_fail():
    rows = vs.capture_rows([payload("x", passed=45, failed=5, skipped=4)])
    assert rows[0][-1] == "FAIL"


def test_a_capture_that_judged_nothing_is_not_reported_as_a_pass():
    # Every check skipped means the manifest says the disc carries none of
    # the signals.  Nothing was proved, and a "PASS" here would read as a
    # clean bill on checks that were never attempted.
    rows = vs.capture_rows([payload("x", skipped=49)])
    assert rows[0][-1] == "SKIPPED"


def test_a_capture_carrying_only_known_deviations_still_passes():
    # Nothing failed and nothing was proved clean either, but the checks were
    # made and the build agreed to carry their faults, which is a pass.
    rows = vs.capture_rows([payload("x", known=16, skipped=4)])
    assert rows[0][-1] == "PASS"


def test_known_deviations_are_counted_apart_from_the_passes():
    rows = vs.capture_rows([payload("x", passed=34, known=16, skipped=4)])
    assert rows[0][3:7] == (34, 0, 16, 4)


def test_only_failing_checks_reach_the_detail_table():
    reports = [payload("x", checks=[check(), check(verdict="PASS"),
                                    check(verdict="SKIP")])]
    assert len(vs.failure_rows(reports)) == 1


def test_a_failure_carries_its_measurement_and_the_band_it_missed():
    rows = vs.failure_rows([payload("x", checks=[
        check(nominal=100.735, band=2.5)])])
    _, _, _, measured, against, used, _ = rows[0]
    assert measured == "106.422 IRE"
    assert against == "100.735 +/-2.500"
    assert used == "2.27x"


def test_a_ceiling_is_scored_against_its_limit_not_a_band():
    # A ceiling has no nominal to deviate from, so "band used" has to come
    # from the limit or the column would be blank exactly where the worst
    # readings are.
    rows = vs.failure_rows([payload("x", checks=[
        check(vits_id="pal-multiburst-field2/ceiling/saturation",
              measured=123.862, unit="percent", limit=101.0)])])
    assert rows[0][4] == "limit 101.000"
    assert rows[0][5] == "1.23x"


def test_a_check_with_no_number_reports_its_reason_instead():
    rows = vs.failure_rows([payload("x", checks=[
        check(measured=float("nan"),
              reason="the manifest records this capture carries "
                     "pal-its-field1, and this decode does not")])])
    assert rows[0][3].startswith("the manifest records")


def test_the_headline_counts_captures_not_checks():
    reports = [payload("a", passed=50),
               payload("b", passed=45, failed=5, checks=[check(), check()])]
    text = vs.render_summary(reports)
    assert "2 checks failed across 1 of 2 captures" in text


def test_a_clean_run_says_so_and_lists_no_failures():
    text = vs.render_summary([payload("a", passed=50), payload("b", passed=49)])
    assert "2 captures, no failing checks" in text
    assert "Failing checks" not in text


def test_every_capture_row_reaches_the_table():
    text = vs.render_summary([payload("a", passed=1), payload("b", passed=1)])
    assert text.count("| a |") == 1
    assert text.count("| b |") == 1
