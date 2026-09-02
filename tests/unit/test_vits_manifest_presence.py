"""
test_vits_manifest_presence - naming what a capture does not carry

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

A conformance run against a capture carrying no FCC multiburst makes no FCC
checks and prints PASS, which reads the same as a clean bill.  These cases
pin the manifest that closes it: which record answers to which name, which
VITS a record says are carried, and the three verdicts that follow.

No manifest file is read - every record here is built in the test.
"""

import pytest

import vits_conformance as vc
import vits_manifest as vmf
import vits_reference as vr

pytestmark = [pytest.mark.unit, pytest.mark.vits]


def record(label, carried, capture=None):
    return {
        "label": label,
        "capture": capture or f"/library/{label}.ldf",
        "system": "NTSC",
        "vits": {vits_id: {"carried": is_carried, "field_lines": [20],
                           "parities": [1]}
                 for vits_id, is_carried in carried.items()},
    }


#: The NTSC CI capture: VIRS and the NTC-7 pair, and no FCC multiburst.
CI_NTSC = record("ve-snw-cut", {
    "ntsc-virs-field1": True, "ntsc-virs-field2": True,
    "ntsc-ntc7-composite": True, "ntsc-ntc7-combination": True,
    "ntsc-fcc-multiburst": False,
})


# ---------------------------------------------------------------------------
# Finding the record
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "ve-snw-cut",
    "ve-snw-cut.ldf",
    "/library/ve-snw-cut.ldf",
    "/build/testout/ve-snw-cut.cvbs",
])
def test_a_record_answers_to_every_name_its_capture_goes_by(name):
    # The decoder writes no reference to its input into the CVBS metadata,
    # so a decode and the capture it came from are tied together by name.
    assert vmf.manifest_entry([CI_NTSC], name) is CI_NTSC


def test_a_capture_nobody_surveyed_has_no_record():
    assert vmf.manifest_entry([CI_NTSC], "some-other-disc.ldf") is None
    assert vmf.manifest_entry([], "ve-snw-cut") is None


def test_only_the_carried_entries_count_as_carried():
    assert vmf.carried_vits(CI_NTSC) == {
        "ntsc-virs-field1", "ntsc-virs-field2",
        "ntsc-ntc7-composite", "ntsc-ntc7-combination"}


def test_a_record_with_no_vits_key_carries_nothing():
    assert vmf.carried_vits({"label": "empty"}) == set()


# ---------------------------------------------------------------------------
# The three verdicts
# ---------------------------------------------------------------------------

def verdicts_for(entry, found_ids, system="NTSC"):
    return {vits_id: (verdict, reason) for vits_id, verdict, reason
            in vmf.presence_verdicts(vr.definitions_for(system), entry,
                                     found_ids)}


def test_a_vits_the_capture_does_not_carry_is_skipped_by_name():
    verdicts = verdicts_for(CI_NTSC, {"ntsc-virs-field1"})
    verdict, reason = verdicts["ntsc-fcc-multiburst"]
    assert verdict == "SKIP"
    assert reason == "capture carries no ntsc-fcc-multiburst"


def test_a_vits_the_capture_carries_and_the_decode_found_passes():
    found = {"ntsc-virs-field1", "ntsc-virs-field2",
             "ntsc-ntc7-composite", "ntsc-ntc7-combination"}
    verdict, reason = verdicts_for(CI_NTSC, found)["ntsc-virs-field1"]
    assert verdict == "PASS"
    assert reason == "found where the manifest records it"


def test_a_vits_the_capture_carries_and_the_decode_lost_fails():
    verdict, reason = verdicts_for(CI_NTSC, set())["ntsc-ntc7-combination"]
    assert verdict == "FAIL"
    assert "the manifest records this capture carries" in reason


def test_a_blanked_line_is_left_to_its_own_unconditional_check():
    # Being blank is the whole of its content, so presence is not a
    # question the identifier can answer; check_blanked_lines judges it
    # directly whether the manifest mentions it or not.
    pal = record("ggv1011", {"pal-its-field1": True})
    judged = verdicts_for(pal, set(), system="PAL")
    assert "pal-blanked-field1" not in judged
    assert "pal-blanked-field2" not in judged
    assert "pal-multiburst-field1" in judged


def test_every_definition_of_the_system_gets_a_verdict():
    judged = verdicts_for(CI_NTSC, set())
    assert set(judged) == {definition.id
                           for definition in vr.definitions_for("NTSC")}


# ---------------------------------------------------------------------------
# As the runner reports them
# ---------------------------------------------------------------------------

def test_the_runner_turns_a_verdict_into_a_check_naming_its_clause():
    checks = vc.check_carried("NTSC", CI_NTSC, {"ntsc-virs-field1"}, "first")
    by_id = {check.id: check for check in checks}
    absent = by_id["ntsc-fcc-multiburst/carried"]
    assert absent.verdict == "SKIP"
    assert absent.reason == "capture carries no ntsc-fcc-multiburst"
    assert absent.clause == vr.definition("ntsc-fcc-multiburst").source
    assert absent.field_line == vr.definition("ntsc-fcc-multiburst").field_line
    assert absent.parity == "first"
    assert absent.detail["manifest"] == "ve-snw-cut"


def test_only_this_parity_s_definitions_are_asked_after():
    # A first-field VITS is not on a second field to be found, so asking
    # after it while judging the second field would fail every one of them.
    checks = vc.check_carried("NTSC", CI_NTSC, {"ntsc-virs-field2",
                                                "ntsc-ntc7-combination"},
                              "second")
    assert {check.id for check in checks} == {
        "ntsc-virs-field2/carried", "ntsc-ntc7-combination/carried"}
    assert all(check.verdict == "PASS" for check in checks)


def test_a_carried_check_reports_its_reason_because_it_has_no_number():
    # There is no measurement to print, so a formatter with nothing but the
    # number would render every one of these as "nan".
    checks = vc.check_carried("NTSC", CI_NTSC, {"ntsc-virs-field1"}, "first")
    assert all(check.reason for check in checks)
    for check in checks:
        assert "nan" not in vc._format_check(check)
        assert check.reason in vc._format_check(check)


def test_the_runner_makes_no_carried_checks_without_a_manifest():
    # The default path has to stay exactly as it was, or every existing CI
    # contract moves the day this lands.
    assert vc.run_conformance.__defaults__[-1] is None
