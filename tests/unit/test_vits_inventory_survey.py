"""
test_vits_inventory_survey - the pure half of the VITS radius survey

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The survey's value is that it is repeatable: a row that disagrees with the
capture it came from sends test selection at the wrong disc.  These cases
pin the parts that turn a decode into a row - the frame arithmetic, the log
parsing that finds the spin-up offset, the profile merge across radii, and
the row rendering - and pin the two shell-outs by injecting the runner
rather than by running anything.

No capture file is read and no subprocess is started.
"""

import pytest

import vits_inventory as vi
from vits_identify import Identification

pytestmark = [pytest.mark.unit]


def identified(vits_id, field_line, score=1.0):
    return Identification(field_line=field_line, vits_id=vits_id, score=score,
                          on_expected_line=True)


class FakeCompleted:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


class RecordingRunner:
    """Stands in for subprocess.run, keeping the argv it was handed."""

    def __init__(self, result=None):
        self.result = result or FakeCompleted()
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return self.result


# ---------------------------------------------------------------------------
# Naming and frame arithmetic
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, expected", [
    ("GGV1011_CAV_PAL_side1_DD1_2019-06-12.ldf", "PAL"),
    ("Pioneer GGV1069_CAV_NTSC_side1_dup1.ldf", "NTSC"),
    ("Domesday_DD86-DS1_NationalB_PP_CLV_PAL_00-60.ldf", "PAL"),
    ("Grosse Pointe Blank_side1_2025-11-19.ldf", None),
])
def test_the_system_is_read_from_the_file_name_or_refused(name, expected):
    assert vi.system_from_name(name) == expected


def test_a_name_claiming_both_systems_is_refused_rather_than_guessed():
    assert vi.system_from_name("dual_PAL_and_NTSC_transfer.ldf") is None


def test_the_frame_count_comes_from_the_sample_count_not_the_container():
    # GGV1011 side 1: 38788923392 samples at 40 MSPS, 25 Hz frames.
    assert vi.capture_frames(38788923392, "PAL") == 24243
    # One NTSC frame is 40e6 * 1001 / 30000 samples; ten whole ones, and
    # one sample short of ten, which is nine whole frames and not ten.
    assert vi.capture_frames(round(10 * 40e6 * 1001 / 30000), "NTSC") == 10
    assert vi.capture_frames(round(10 * 40e6 * 1001 / 30000) - 1, "NTSC") == 9


@pytest.mark.parametrize("samples", [None, 0, -1])
def test_an_unreadable_sample_count_yields_no_frame_count(samples):
    assert vi.capture_frames(samples, "PAL") is None


def test_probe_points_are_percentages_along_the_whole_file():
    assert vi.probe_frames(24243, (5.0, 50.0, 95.0)) == [1212, 12121, 23030]


def test_cuts_are_placed_along_the_recorded_band_not_along_the_file():
    # GGV1011 side 1: 24243 frames, 229 of them spin-up before disc frame 1.
    assert vi.recorded_band_frames(24243, 229) == [1429, 12236, 23042]


def test_a_capture_with_no_measurable_spin_up_uses_the_whole_file():
    # CLV carries no absolute disc frame number to measure the offset from.
    assert vi.recorded_band_frames(24243, None) == vi.probe_frames(24243)


# ---------------------------------------------------------------------------
# Reading the decoder's own frame report
# ---------------------------------------------------------------------------

CAV_LOG = """\
Frame 1/12: File Frame 1212: CAV Frame #983 
Frame 2/12: File Frame 1213: CAV Frame #984 
"""

CLV_LOG = "File Frame 90: CLV Timecode 00:01:12 \n"


def test_a_cav_frame_report_yields_the_disc_frame_number():
    assert vi.parse_frame_log(CAV_LOG) == [
        {"file_frame": 1212, "disc_format": "CAV", "disc_frame": 983},
        {"file_frame": 1213, "disc_format": "CAV", "disc_frame": 984},
    ]


def test_a_clv_frame_report_yields_a_timecode_and_no_frame_number():
    assert vi.parse_frame_log(CLV_LOG) == [
        {"file_frame": 90, "disc_format": "CLV", "timecode": "00:01:12"},
    ]


def test_log_lines_that_are_not_frame_reports_are_ignored():
    noise = "INFO - CVBS: wrote 12 frames CVBS_U10_4FSC\nLead In\n"
    assert vi.parse_frame_log(noise + CAV_LOG) == vi.parse_frame_log(CAV_LOG)


def test_the_spin_up_offset_is_the_gap_to_disc_frame_one():
    assert vi.spin_up_offset(vi.parse_frame_log(CAV_LOG)) == 229


def test_a_clv_capture_has_no_measurable_spin_up_offset():
    # Only an absolute disc frame number can measure it, and CLV has none.
    assert vi.spin_up_offset(vi.parse_frame_log(CLV_LOG)) is None
    assert vi.spin_up_offset([]) is None


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

def test_a_profile_records_every_line_and_parity_a_vits_was_seen_on():
    profile = vi.vits_profile([
        (1, {19: identified("pal-its-field1", 19)}),
        (2, {19: identified("pal-its-field2", 19)}),
        (1, {19: identified("pal-its-field1", 19, score=0.9)}),
    ])
    assert profile["pal-its-field1"] == {
        "field_lines": [19], "parities": [1], "fields": 2, "best_score": 1.0}
    assert profile["pal-its-field2"]["parities"] == [2]


def test_a_vits_moved_to_its_alternate_line_is_reported_on_the_line_found():
    # The PAL multiburst sits on frame line 13 or 20 depending on the
    # pressing, so the survey has to report where it was, not where the
    # definition puts it.
    profile = vi.vits_profile([(1, {13: identified("pal-multiburst-field1",
                                                   13)})])
    assert profile["pal-multiburst-field1"]["field_lines"] == [13]


def test_a_line_a_signal_was_seen_on_once_is_not_one_of_its_lines():
    # Domesday DS1 reads the second-field multiburst on line 23 in one field
    # of thirteen and on line 20 in all of them; the row must say line 20.
    fields = [(2, {20: identified("pal-multiburst-field2", 20)})
              for _ in range(6)]
    fields[3][1][23] = identified("pal-multiburst-field2", 23)
    profile = vi.vits_profile(fields)
    assert profile["pal-multiburst-field2"]["field_lines"] == [20]


def test_a_signal_the_disc_repeats_on_several_lines_keeps_all_of_them():
    # GGV1069 carries the FCC multiburst on field lines 22, 23 and 24 of
    # every field, which a rule counting occurrences rather than fields
    # would throw away as a third each.
    fields = [(parity, {line: identified("ntsc-fcc-multiburst", line)
                        for line in (22, 23, 24)})
              for parity in (1, 2, 1, 2)]
    profile = vi.vits_profile(fields)
    assert profile["ntsc-fcc-multiburst"]["field_lines"] == [22, 23, 24]
    assert profile["ntsc-fcc-multiburst"]["parities"] == [1, 2]


def test_a_signal_on_one_parity_is_not_diluted_by_the_other():
    # Half the fields of a capture can never carry a first-field VITS, so
    # the denominator has to be the parity's own fields.
    fields = ([(1, {19: identified("pal-its-field1", 19)}) for _ in range(5)]
              + [(2, {}) for _ in range(5)])
    assert vi.vits_profile(fields)["pal-its-field1"]["field_lines"] == [19]


def test_a_weak_identification_is_not_recorded_as_carried():
    weak = vi.INVENTORY_MIN_SCORE - 0.01
    profile = vi.vits_profile([(1, {19: identified("pal-its-field1", 19,
                                                   score=weak)})])
    assert profile == {}


class BlankCheck:
    """A vits_conformance.check_blanked_lines Check, as far as this needs."""

    def __init__(self, mean_ire, verdict):
        self.detail = {"mean_ire": mean_ire}
        self.verdict = verdict


def test_a_line_with_a_pedestal_offset_is_still_a_blanked_line():
    # GGV1011 reads +1.09 IRE on field line 22, which fails the blanking
    # allowance of 1.0 IRE.  The disc still carries a blanked line 22, and a
    # survey that used the verdict would say it does not.
    assert vi.is_line_blank(BlankCheck(1.088, "FAIL"))
    assert vi.is_line_blank(BlankCheck(-1.088, "FAIL"))


def test_a_line_carrying_picture_content_is_not_a_blanked_line():
    over = vi.INVENTORY_BLANK_TOLERANCE_IRE + 1.0
    assert not vi.is_line_blank(BlankCheck(over, "FAIL"))
    assert not vi.is_line_blank(BlankCheck(-over, "FAIL"))


def test_a_blanking_check_with_no_measurement_is_not_a_blanked_line():
    assert not vi.is_line_blank(BlankCheck(None, "SKIP"))


def test_a_blanked_line_is_recorded_although_it_cannot_be_identified():
    # Being blank is the whole of its content, so it arrives from the
    # conformance check rather than from the identifier.
    profile = vi.vits_profile(
        [], blanked=[(1, 22, "pal-blanked-field1", True),
                     (2, 22, "pal-blanked-field2", False)])
    assert profile["pal-blanked-field1"]["field_lines"] == [22]
    assert "pal-blanked-field2" not in profile


def test_merging_marks_what_every_radius_carried():
    at_all = {"field_lines": [19], "parities": [1], "fields": 9,
              "best_score": 1.0}
    merged = vi.merge_profiles([
        {"pal-its-field1": at_all},
        {"pal-its-field1": at_all},
        {"pal-its-field1": at_all},
    ])
    assert merged["pal-its-field1"]["at_every_radius"] is True
    assert merged["pal-its-field1"]["carried"] is True
    assert merged["pal-its-field1"]["fields"] == 27
    assert merged["pal-its-field1"]["probes"] == [0, 1, 2]


def test_a_vits_seen_at_one_radius_only_is_reported_but_not_called_carried():
    inner = {"field_lines": [22], "parities": [1], "fields": 3,
             "best_score": 0.9}
    merged = vi.merge_profiles([{"ntsc-fcc-multiburst": inner}, {}, {}])
    assert merged["ntsc-fcc-multiburst"]["probes"] == [0]
    assert merged["ntsc-fcc-multiburst"]["at_every_radius"] is False
    assert merged["ntsc-fcc-multiburst"]["carried"] is False


def test_merging_nothing_yields_nothing():
    assert vi.merge_profiles([]) == {}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

RECORD = {
    "label": "Calibration/GGV1011 side 1", "system": "PAL",
    "disc_format": "CAV", "frames": 24243, "spin_up": 229,
    "vits": {
        "pal-its-field1": {"field_lines": [19], "parities": [1],
                           "probes": [0, 1, 2], "at_every_radius": True,
                           "carried": True},
        "pal-multiburst-field1": {"field_lines": [13], "parities": [1, 2],
                                  "probes": [0], "at_every_radius": False,
                                  "carried": False},
    },
}


def test_a_row_names_the_lines_and_parities_a_capture_carries():
    row = vi.markdown_row(RECORD)
    assert row.startswith("| `Calibration/GGV1011 side 1` | PAL | CAV "
                          "| ~24243 | 229 |")
    assert "`pal-its-field1` line 19 F1" in row


def test_a_vits_found_at_one_radius_only_is_still_named_in_the_row():
    # GGV1069 carries the FCC multiburst at the inner radius alone; a row
    # that dropped it would say the disc does not carry it.
    row = vi.markdown_row(RECORD)
    assert "`pal-multiburst-field1` line 13 F1F2 (1 of the probes)" in row


def test_a_cut_reports_where_in_the_disc_it_came_from_not_a_spin_up():
    # A cut starts inside the disc, so file frame 0 is some disc frame well
    # past 1 and the offset comes out negative.  "Spin-up -754" is nonsense.
    cut = dict(RECORD, spin_up=-754)
    assert "| from disc frame 754 |" in vi.markdown_row(cut)


def test_a_row_survives_a_capture_whose_length_could_not_be_read():
    unknown = dict(RECORD, frames=None, spin_up=None, disc_format=None)
    assert "| ? | ? | ? |" in vi.markdown_row(unknown)


def test_a_probe_that_decoded_nothing_carries_nothing():
    # The lead-out of a disc decodes to an empty file.  A survey tool that
    # died there could not report on a capture that reaches it.
    assert vi.vits_profile([]) == {}


def test_a_capture_carrying_nothing_says_so_rather_than_leaving_a_blank():
    assert "none identified" in vi.markdown_row(dict(RECORD, vits={}))


def test_a_vits_present_at_some_radii_only_is_flagged_where_it_is_carried():
    partial = dict(RECORD, vits={
        "ntsc-fcc-multiburst": {"field_lines": [22], "parities": [1],
                                "probes": [0, 1], "at_every_radius": False,
                                "carried": True}})
    assert "(2 of the probes)" in vi.markdown_row(partial)


# ---------------------------------------------------------------------------
# The manifest table that goes beside the captures
# ---------------------------------------------------------------------------

CUT = dict(RECORD, capture="radius/ggv1011-side1-inner.ldf",
           disc="Pioneer GGV1011", side="1",
           source_library="Calibration/GGV1011",
           source_file_frames=[1429, 1458], radius_band="inner",
           band_percentage=5.0)


def test_a_cut_reports_the_disc_frame_its_extract_begins_at():
    # File frame 1429 of a capture whose disc frame 1 is at file frame 229.
    assert vi.disc_frame_at_start(CUT) == 1200


def test_a_full_disc_capture_has_no_disc_frame_to_report():
    # It begins in the lead-in, which is what the spin-up column says.
    assert vi.disc_frame_at_start(RECORD) is None


def test_a_capture_with_no_measurable_spin_up_has_no_disc_frame():
    assert vi.disc_frame_at_start(dict(CUT, spin_up=None)) is None


def test_a_manifest_row_carries_the_provenance_as_well_as_the_vits():
    row = vi.manifest_row(CUT)
    for expected in ("`radius/ggv1011-side1-inner.ldf`", "Pioneer GGV1011",
                     "Calibration/GGV1011", "1429–1458", "1200",
                     "inner (5 %)", "`pal-its-field1` line 19 F1"):
        assert expected in row, expected


def test_a_manifest_row_leaves_provenance_it_does_not_know_blank():
    # The captures already in the repository predate the survey and their
    # provenance is recorded nowhere; blank beats guessed.
    row = vi.manifest_row(RECORD)
    assert row.count("| — |") >= 3


def test_the_manifest_table_header_matches_its_rows():
    table = vi.manifest_table([CUT, RECORD]).splitlines()
    assert len(table) == 4
    columns = table[0].count("|") - 1
    assert table[1] == "|" + "---|" * columns
    for row in table[2:]:
        assert row.count("|") - 1 == columns


def test_the_table_carries_one_header_and_one_row_per_capture():
    table = vi.markdown_table([RECORD, RECORD]).splitlines()
    assert table[0].startswith("| Capture |")
    assert len(table) == 4


# ---------------------------------------------------------------------------
# The two shell-outs, with the runner injected
# ---------------------------------------------------------------------------

def test_the_sample_count_is_read_from_ffprobe_as_an_argument_list():
    runner = RecordingRunner(FakeCompleted(stdout="38788923392\n"))
    assert vi.probe_sample_count("a capture.ldf", runner=runner) == 38788923392
    argv, kwargs = runner.calls[0]
    assert isinstance(argv, list) and argv[0] == "ffprobe"
    assert argv[-1] == "a capture.ldf"
    assert "shell" not in kwargs


@pytest.mark.parametrize("result", [
    FakeCompleted(returncode=1),
    FakeCompleted(stdout=""),
    FakeCompleted(stdout="not a number\n"),
])
def test_an_absent_or_unhelpful_ffprobe_yields_no_sample_count(result):
    assert vi.probe_sample_count("x.ldf", runner=RecordingRunner(result)) is None


def test_an_ffprobe_that_cannot_be_launched_yields_no_sample_count():
    def missing(argv, **kwargs):
        raise OSError("No such file or directory: 'ffprobe'")
    assert vi.probe_sample_count("x.ldf", runner=missing) is None


def test_a_probe_decode_is_serial_so_the_survey_repeats():
    runner = RecordingRunner(FakeCompleted(stdout=CAV_LOG))
    log = vi.decode_sample("in.ldf", "PAL", 1212, 12, "out", runner=runner)
    argv, _ = runner.calls[0]
    assert argv[argv.index("-t") + 1] == "1"
    assert "--PAL" in argv and "--NTSC" not in argv
    assert argv[argv.index("-s") + 1] == "1212"
    assert argv[argv.index("-l") + 1] == "12"
    assert argv[-2:] == ["in.ldf", "out"]
    assert CAV_LOG in log


def test_a_failed_decode_is_raised_rather_than_surveyed_as_empty():
    runner = RecordingRunner(FakeCompleted(returncode=2, stderr="boom"))
    with pytest.raises(RuntimeError, match="frame 1212 failed"):
        vi.decode_sample("in.ldf", "NTSC", 1212, 12, "out", runner=runner)
