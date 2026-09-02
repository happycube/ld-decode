"""
test_vits_reference - the normative VITS reference data is self-consistent

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

vits_reference is pure data transcribed from IEC 60856-1986, IEC 60857-1986
and the definitions the latter defers to.  A transcription error there is
invisible until a conformance check fails against a good decode, so this suite
pins the structure, the unit conversions, the frame/field line arithmetic and
the numbers the specifications state in more than one place.

No file is opened and nothing from lddecode is imported.
"""

import types

import pytest

import vits_reference as vr
from video_common import NTC7_MULTIBURST_FREQS

pytestmark = [pytest.mark.unit, pytest.mark.format, pytest.mark.vits]

ALL = vr.VITS_DEFINITIONS


# --- layering -------------------------------------------------------------


def test_the_module_pulls_in_no_decoder_or_io_dependency():
    # It is the lowest layer of the measurement stack: pure numbers, so it
    # stays unit-testable and cannot drag a decoder import into a data module.
    # Read from the imported module's own namespace rather than its source, so
    # this test opens no file either.
    imported = {
        value.__name__
        for value in vars(vr).values()
        if isinstance(value, types.ModuleType)
    }
    assert not [name for name in imported if name.split(".")[0] == "lddecode"]
    for forbidden in ("numpy", "sqlite3", "mmap", "os"):
        assert forbidden not in imported


# --- structure ------------------------------------------------------------


def test_every_definition_has_a_unique_id():
    ids = [d.id for d in ALL]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("entry", ALL, ids=lambda d: d.id)
def test_definition_fields_are_well_formed(entry):
    assert entry.system in vr.SYSTEMS
    assert entry.status in vr.STATUSES
    assert entry.field in (1, 2)
    assert entry.frame_line > 0
    assert entry.field_line > 0
    assert entry.source, f"{entry.id} cites no source"
    assert entry.elements, f"{entry.id} has no elements"


@pytest.mark.parametrize("entry", ALL, ids=lambda d: d.id)
def test_element_fields_are_well_formed(entry):
    for elem in entry.elements:
        assert elem.kind in vr.ELEMENT_KINDS, f"{entry.id}/{elem.id}: {elem.kind}"
        assert elem.channel in vr.CHANNELS
        assert elem.source, f"{entry.id}/{elem.id} cites no source"
        assert elem.label


@pytest.mark.parametrize("entry", ALL, ids=lambda d: d.id)
def test_element_ids_are_unique_within_a_definition(entry):
    ids = [e.id for e in entry.elements]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("entry", ALL, ids=lambda d: d.id)
def test_element_lookup_finds_every_element(entry):
    for elem in entry.elements:
        assert entry.element(elem.id) is elem
    assert entry.element("no-such-element") is None


# --- windows --------------------------------------------------------------


@pytest.mark.parametrize("entry", ALL, ids=lambda d: d.id)
def test_element_windows_are_monotonic(entry):
    for elem in entry.elements:
        start, end = elem.window_us
        assert end > start, f"{entry.id}/{elem.id}: window {elem.window_us}"
        assert elem.duration_us == pytest.approx(end - start)


@pytest.mark.parametrize("entry", ALL, ids=lambda d: d.id)
def test_element_windows_fall_inside_one_line(entry):
    # Windows are measured from the leading edge of horizontal sync, so one
    # running past the line period would read into the next line.
    period = vr.LINE_PERIOD_US[entry.system]
    for elem in entry.elements:
        assert elem.start_us >= 0.0, f"{entry.id}/{elem.id}"
        assert elem.end_us <= period, (
            f"{entry.id}/{elem.id}: ends at {elem.end_us} us, "
            f"line is {period} us"
        )


@pytest.mark.parametrize("entry", ALL, ids=lambda d: d.id)
def test_windows_on_one_channel_do_not_overlap_unless_superimposed(entry):
    # Two elements may share a window only when one rides on the other; an
    # unflagged overlap means a measurement would read two signals as one.
    for channel in vr.CHANNELS:
        plain = [
            e for e in entry.elements
            if e.channel == channel and not e.superimposed
        ]
        plain.sort(key=lambda e: e.start_us)
        for earlier, later in zip(plain, plain[1:]):
            assert later.start_us >= earlier.end_us, (
                f"{entry.id}: {earlier.id} and {later.id} overlap on "
                f"{channel} but neither is marked superimposed"
            )


@pytest.mark.parametrize("entry", ALL, ids=lambda d: d.id)
def test_burst_packets_are_ordered_and_disjoint(entry):
    packets = [e for e in entry.elements if e.kind == "burst_packet"]
    if not packets:
        return
    for earlier, later in zip(packets, packets[1:]):
        assert later.start_us >= earlier.end_us, f"{entry.id}: packets overlap"
        assert later.freq_mhz > earlier.freq_mhz, (
            f"{entry.id}: packet frequencies must climb"
        )


# --- unit conversions -----------------------------------------------------


def test_pal_white_reference_is_one_hundred_on_the_measurement_scale():
    # 0.70 V p-p is PAL's blanking-to-white reference, so it is 100 on the
    # scale VideoField.output_to_ire() produces.
    assert vr.to_ire(1.00, "PAL") == pytest.approx(100.0, abs=1e-9)
    assert vr.to_percent(1.00, "PAL") == pytest.approx(100.0, abs=1e-9)


def test_ntsc_white_reference_is_one_hundred_on_the_measurement_scale():
    assert vr.to_ire(100.0, "NTSC") == pytest.approx(100.0, abs=1e-9)
    assert vr.to_percent(100.0, "NTSC") == pytest.approx(100.0, abs=1e-9)


def test_blanking_is_zero_on_the_measurement_scale():
    for system, nominal in (("PAL", 0.0), ("NTSC", 0.0)):
        assert vr.to_ire(nominal, system) == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize(
    "system, nominal, expected_ire",
    [
        ("PAL", 0.80, 80.0),    # IEC 60856 Figure 8 a) white reference bar
        ("PAL", 0.20, 20.0),    # IEC 60856 Figure 8 b) black reference bar
        ("PAL", 0.60, 60.0),    # IEC 60856 Figure 7 d) staircase third tread
        ("NTSC", 68.0, 68.0),   # VIRS first zone
        ("NTSC", 46.0, 46.0),   # VIRS second zone
    ],
)
def test_stated_nominals_convert_to_the_documented_measurement_value(
    system, nominal, expected_ire
):
    assert vr.to_ire(nominal, system) == pytest.approx(expected_ire, abs=1e-9)


def test_pal_millivolts_follow_the_seven_hundred_millivolt_reference():
    assert vr.to_millivolts(1.00, "PAL") == pytest.approx(700.0, abs=1e-9)
    assert vr.to_millivolts(0.80, "PAL") == pytest.approx(560.0, abs=1e-9)
    assert vr.to_millivolts(0.20, "PAL") == pytest.approx(140.0, abs=1e-9)


def test_ntsc_millivolts_follow_the_seven_hundred_fourteen_reference():
    # The one place the two systems genuinely differ: 100 on the measurement
    # scale is 700 mV on 625-line and 714.3 mV on 525-line.
    assert vr.to_millivolts(100.0, "NTSC") == pytest.approx(714.3, abs=1e-9)
    assert vr.to_millivolts(50.0, "NTSC") == pytest.approx(357.15, abs=1e-9)


@pytest.mark.parametrize("entry", ALL, ids=lambda d: d.id)
def test_every_nominal_converts_and_stays_within_the_recorded_ceiling(entry):
    for elem in entry.elements:
        if elem.nominal is None:
            continue
        ire = vr.to_ire(elem.nominal, entry.system)
        assert ire == pytest.approx(
            vr.to_percent(elem.nominal, entry.system), abs=1e-9)
        # IEC 60856-1986 9.1.5 / IEC 60857-1986 9.1.6.
        assert -1e-9 <= ire <= vr.MAX_LUMINANCE_IRE, f"{entry.id}/{elem.id}"


def test_an_unknown_system_is_refused_by_name():
    for call in (vr.to_ire, vr.to_percent, vr.to_millivolts):
        with pytest.raises(ValueError, match="SECAM"):
            call(1.0, "SECAM")


# --- sample scaling -------------------------------------------------------


@pytest.mark.parametrize(
    "blanking, white",
    [(240, 800), (256, 844), (15117, 51200), (15248, 54016)],
)
def test_sample_scaling_puts_blanking_at_zero_and_white_at_one_hundred(
    blanking, white
):
    # Mirrors VideoField.output_to_ire(): the sample domain cancels, so the
    # 10-bit CVBS presets and the 16-bit .tbc levels give the same answer.
    assert vr.sample_to_ire(blanking, blanking, white) == pytest.approx(0.0, abs=1e-9)
    assert vr.sample_to_ire(white, blanking, white) == pytest.approx(100.0, abs=1e-9)


def test_sample_scaling_is_the_same_in_the_ten_bit_and_sixteen_bit_domains():
    ten_bit = vr.sample_to_ire(500, 240, 800)
    sixteen_bit = vr.sample_to_ire(500 * 64, 240 * 64, 800 * 64)
    assert ten_bit == pytest.approx(sixteen_bit, abs=1e-9)


@pytest.mark.parametrize("system", ["NTSC", "PAL"])
def test_sample_scaling_agrees_with_the_loader_it_mirrors(system):
    # The point of sample_to_ire(): a nominal converted with to_ire() and a
    # sample converted by VideoField.output_to_ire() have to land on one
    # scale, or every conformance comparison is off by a constant.
    import numpy as np
    from video_common import CaptureParams, VideoField

    params = CaptureParams.for_cvbs(system)
    field = VideoField(
        np.zeros(params.field_samples, dtype=np.int32), 0, params,
        {"field_phase_id": 1, "is_first_field": True, "field_id": 0},
    )
    samples = np.array(
        [params.blanking_16b_ire, params.black_16b_ire, params.white_16b_ire, 512])
    from_loader = field.output_to_ire(samples)
    from_reference = [
        vr.sample_to_ire(s, params.blanking_16b_ire, params.white_16b_ire)
        for s in samples
    ]
    np.testing.assert_allclose(from_loader, from_reference, rtol=0, atol=1e-9)


@pytest.mark.parametrize(
    "system, nominal",
    [("PAL", 1.00), ("PAL", 0.50), ("NTSC", 100.0), ("NTSC", 50.0)],
)
def test_a_nominal_and_its_ideal_sample_agree_on_the_measurement_scale(
    system, nominal
):
    # Construct the sample an ideal decode would write for this nominal, then
    # read it back through the loader's scale; it must return the nominal.
    from video_common import CaptureParams

    params = CaptureParams.for_cvbs(system)
    expected_ire = vr.to_ire(nominal, system)
    sample = params.blanking_16b_ire + expected_ire * params.out_scale
    measured = vr.sample_to_ire(
        sample, params.blanking_16b_ire, params.white_16b_ire)
    assert measured == pytest.approx(expected_ire, abs=1e-9)


def test_a_degenerate_scale_is_refused():
    with pytest.raises(ValueError, match="undefined"):
        vr.sample_to_ire(100, 240, 240)


# --- frame line to field line --------------------------------------------


@pytest.mark.parametrize(
    "system, first, second",
    [
        # IEC 60856-1986 9.1.3, including the Amendment 2 alternatives.
        ("PAL", 19, 332),
        ("PAL", 20, 333),
        ("PAL", 13, 326),
        ("PAL", 22, 335),
        # IEC 60857-1986 9.1.3 (VIRS) and 9.1.4 (ITS).
        ("NTSC", 19, 282),
        ("NTSC", 20, 283),
    ],
)
def test_each_iec_pair_is_one_field_line_in_both_parities(system, first, second):
    field_a, line_a = vr.frame_line_to_field(system, first)
    field_b, line_b = vr.frame_line_to_field(system, second)
    assert (field_a, field_b) == (1, 2)
    assert line_a == line_b, (
        f"{system} frame lines {first}/{second} should be one field line"
    )


@pytest.mark.parametrize("system", ["PAL", "NTSC"])
def test_frame_and_field_line_conversions_are_inverse(system):
    offset = vr.FIELD_TWO_FRAME_LINE_OFFSET[system]
    for frame_line in range(1, 2 * offset):
        field, field_line = vr.frame_line_to_field(system, frame_line)
        assert vr.field_to_frame_line(system, field, field_line) == frame_line


def test_the_field_offsets_are_the_standards_values():
    # PAL 625/2 puts field 2 line 1 at frame line 314, NTSC 525 at 264, so
    # the offsets are the frame lines before each field's first.
    assert vr.FIELD_TWO_FRAME_LINE_OFFSET["PAL"] == 313
    assert vr.FIELD_TWO_FRAME_LINE_OFFSET["NTSC"] == 263


@pytest.mark.parametrize("entry", ALL, ids=lambda d: d.id)
def test_each_definition_agrees_with_its_own_line_arithmetic(entry):
    field, field_line = vr.frame_line_to_field(entry.system, entry.frame_line)
    assert (field, field_line) == (entry.field, entry.field_line), (
        f"{entry.id}: frame line {entry.frame_line} resolves to "
        f"field {field} line {field_line}"
    )


def test_bad_line_numbers_are_refused():
    with pytest.raises(ValueError):
        vr.frame_line_to_field("PAL", 0)
    with pytest.raises(ValueError):
        vr.field_to_frame_line("PAL", 3, 19)
    with pytest.raises(ValueError):
        vr.field_to_frame_line("PAL", 1, 0)


# --- multiburst sets ------------------------------------------------------


def test_video_common_uses_the_reference_frequency_set():
    # Task 4 of the phase: one definition, not two that can drift apart.
    assert NTC7_MULTIBURST_FREQS is vr.NTSC_MULTIBURST_NTC7


@pytest.mark.parametrize(
    "name, expected",
    [
        # IEC 60856-1986 9.1.3 Figure 8 c).
        ("PAL_MULTIBURST_IEC", (0.5, 1.3, 2.3, 4.2, 4.8, 5.8)),
        # ITU-T J.63 Annex I section 3 - what real PAL discs carry.
        ("PAL_MULTIBURST_ITU", (0.5, 1.0, 2.0, 4.0, 4.8, 5.8)),
        # FCC Rules Part 73 / EIA RS-498.
        ("NTSC_MULTIBURST_FCC", (0.5, 1.25, 2.0, 3.0, 3.58, 4.1)),
        # ITU-T J.63 Annex II section 3.
        ("NTSC_MULTIBURST_NTC7", (0.5, 1.0, 2.0, 3.0, 3.58, 4.2)),
    ],
)
def test_multiburst_sets_match_their_specifications(name, expected):
    assert getattr(vr, name) == expected


def test_the_pal_sets_really_do_differ():
    # The reason a measurement has to identify the set by frequency rather
    # than assume the IEC one: three of six packets differ.
    differing = sum(
        1 for iec, itu in zip(vr.PAL_MULTIBURST_IEC, vr.PAL_MULTIBURST_ITU)
        if iec != itu
    )
    assert differing == 3


@pytest.mark.parametrize("system", ["PAL", "NTSC"])
def test_every_multiburst_set_climbs_and_has_six_packets(system):
    for name, freqs in vr.MULTIBURST_SETS[system].items():
        assert len(freqs) == 6, f"{system}/{name}"
        assert list(freqs) == sorted(freqs), f"{system}/{name}"


def test_pal_multiburst_packets_carry_the_iec_frequency_tolerance():
    # IEC 60856-1986 9.1.3 Figure 8 c): frequencies +/-2%.
    entry = vr.definition("pal-multiburst-field1")
    packets = [e for e in entry.elements if e.kind == "burst_packet"]
    assert len(packets) == 6
    for elem, nominal in zip(packets, vr.PAL_MULTIBURST_IEC):
        assert elem.freq_mhz == nominal
        assert elem.freq_tolerance_mhz == pytest.approx(nominal * 0.02, rel=1e-12)


# --- staircases -----------------------------------------------------------


@pytest.mark.parametrize("entry", ALL, ids=lambda d: d.id)
def test_staircase_treads_climb_to_the_stated_top(entry):
    for elem in entry.elements:
        if elem.kind != "staircase":
            continue
        assert elem.steps, f"{entry.id}/{elem.id} has no treads"
        assert list(elem.steps) == sorted(elem.steps)
        assert elem.steps[-1] == pytest.approx(elem.nominal)


def test_the_pal_staircase_has_the_six_levels_the_figure_states():
    # IEC 60856-1986 9.1.3 Figure 7 d): "Number of levels = 6 (black and
    # white incl.)" - blanking plus five treads.
    entry = vr.definition("pal-its-field1")
    staircase = entry.element("staircase")
    assert len(staircase.steps) + 1 == vr.PAL_STAIRCASE_LEVEL_COUNT
    assert staircase.steps == (0.20, 0.40, 0.60, 0.80, 1.00)


def test_the_pal_staircase_treads_are_evenly_spaced():
    # Step inequality is a conformance check, so the nominal treads it is
    # measured against have to be exactly even.
    steps = vr.definition("pal-its-field1").element("staircase").steps
    rises = [b - a for a, b in zip((0.0,) + steps, steps)]
    for rise in rises:
        assert rise == pytest.approx(rises[0], abs=1e-12)


def test_the_ntsc_staircase_treads_match_the_ntc7_definition():
    steps = vr.definition("ntsc-ntc7-composite").element("staircase").steps
    assert steps == (18.0, 36.0, 54.0, 72.0, 90.0)


# --- the numbers the specifications state twice ---------------------------


def test_pal_multiburst_reference_bars_match_the_itu_pedestal_arithmetic():
    # IEC 60856 Figure 8 states 80% and 20% of 0.70 V p-p; the ITU geometry
    # states a 350 mV pedestal with +/-210 mV bars.  They must agree, because
    # this module takes timing from one and levels from the other.
    entry = vr.definition("pal-multiburst-field1")
    pedestal = vr.to_millivolts(entry.element("grey_pedestal").nominal, "PAL")
    white = vr.to_millivolts(entry.element("white_reference_bar").nominal, "PAL")
    black = vr.to_millivolts(entry.element("black_reference_bar").nominal, "PAL")
    assert pedestal == pytest.approx(350.0, abs=1e-9)
    assert white - pedestal == pytest.approx(210.0, abs=1e-9)
    assert pedestal - black == pytest.approx(210.0, abs=1e-9)


def test_pal_staircase_subcarrier_matches_the_iec_peak_to_peak_figure():
    # IEC 60856 Figure 9 states 0.28 V p-p; stored as a carrier peak, so
    # twice the stored value in millivolts must be 280 mV.
    elem = vr.definition("pal-its-field2").element("staircase_subcarrier")
    assert 2 * vr.to_millivolts(elem.nominal, "PAL") == pytest.approx(280.0, abs=1e-9)


def test_pal_multiburst_amplitude_matches_the_iec_envelope_figure():
    # IEC 60856 Figure 8 c) states an envelope of 60% of 0.70 V p-p, which is
    # 420 mV peak-to-peak, so the stored carrier peak is 210 mV.
    elem = vr.definition("pal-multiburst-field1").element("packet_1")
    assert 2 * vr.to_millivolts(elem.nominal, "PAL") == pytest.approx(420.0, abs=1e-9)


def test_virs_burst_excursion_matches_the_documented_range():
    # SMPTE RP 168: the burst rides on the 70 IRE zone at +/-20 IRE (40 IRE
    # p-p), so the composite spans 50 to 90 IRE.  The submodule's virs.yaml
    # states the same signal against reference black rather than blanking;
    # see the divergence recorded above _VIRS_ELEMENTS.
    entry = vr.definition("ntsc-virs-field1")
    bar = vr.to_ire(entry.element("first_zone_bar").nominal, "NTSC")
    peak = vr.to_ire(entry.element("chroma_reference").nominal, "NTSC")
    assert bar - peak == pytest.approx(50.0, abs=1e-9)
    assert bar + peak == pytest.approx(90.0, abs=1e-9)


def test_virs_levels_are_the_yaml_levels_referred_to_blanking():
    # Each canonical level is the YAML's own figure converted off the 7.5
    # IRE setup pedestal, which is what makes this a unit correction rather
    # than a different signal.
    entry = vr.definition("ntsc-virs-field1")
    setup = vr.NTSC_SETUP_IRE
    for element_id, yaml_ire in (
        ("first_zone_bar", 68.0),
        ("second_zone_bar", 46.0),
        ("black_reference", 0.0),
    ):
        converted = yaml_ire * (100.0 - setup) / 100.0 + setup
        assert entry.element(element_id).nominal == pytest.approx(
            converted, abs=0.5), element_id
    # An amplitude carries no pedestal, so it scales without the offset.
    assert entry.element("chroma_reference").nominal == pytest.approx(
        22.0 * (100.0 - setup) / 100.0, abs=0.5)


def test_ntc7_combination_chroma_zones_match_the_documented_ranges():
    # NTSC-VITS.md: zones of 20, 40 and 80 IRE p-p on the 50 IRE pedestal,
    # spanning 40-60, 30-70 and 10-90 IRE.
    entry = vr.definition("ntsc-ntc7-combination")
    pedestal = vr.to_ire(entry.element("grey_pedestal").nominal, "NTSC")
    for zone_id, expected in (
        ("chroma_zone_1", (40.0, 60.0)),
        ("chroma_zone_2", (30.0, 70.0)),
        ("chroma_zone_3", (10.0, 90.0)),
    ):
        peak = vr.to_ire(entry.element(zone_id).nominal, "NTSC")
        assert (pedestal - peak, pedestal + peak) == pytest.approx(expected, abs=1e-9)


def test_ntc7_pedestal_peak_to_peak_values_agree_with_video_common():
    from video_common import NTC7_PEDESTAL_PP

    entry = vr.definition("ntsc-ntc7-combination")
    peaks = tuple(
        2 * vr.to_ire(entry.element(z).nominal, "NTSC")
        for z in ("chroma_zone_1", "chroma_zone_2", "chroma_zone_3")
    )
    assert peaks == NTC7_PEDESTAL_PP


def test_the_multiburst_pedestal_boosts_reach_an_apparent_hundred_ire():
    # Both NTSC multibursts state a reference boost that brings the pedestal
    # up to a 100 IRE white reference.
    for vits_id in ("ntsc-fcc-multiburst", "ntsc-ntc7-combination"):
        entry = vr.definition(vits_id)
        boost = entry.element(
            "white_reference_bar") or entry.element("reference_boost")
        assert vr.to_ire(boost.nominal, "NTSC") == pytest.approx(100.0, abs=1e-9)


# --- placement ------------------------------------------------------------


def test_the_only_mandatory_vits_is_the_ntsc_virs():
    # IEC 60857-1986 9.1.3 is the sole "shall" that puts a test signal on an
    # active line; PAL's "shall" is the requirement to blank lines 22/335.
    mandatory = {d.id for d in ALL if d.status == "shall"}
    assert mandatory == {
        "ntsc-virs-field1",
        "ntsc-virs-field2",
        "pal-blanked-field1",
        "pal-blanked-field2",
    }


def test_the_pal_blanked_lines_are_the_noise_floor_reference():
    for vits_id, frame_line in (
        ("pal-blanked-field1", 22), ("pal-blanked-field2", 335)
    ):
        entry = vr.definition(vits_id)
        assert entry.frame_line == frame_line
        assert entry.field_line == 22
        assert [e.kind for e in entry.elements] == ["blanked"]
        assert entry.elements[0].nominal == 0.0


def test_definitions_for_returns_one_system_in_frame_line_order():
    for system in vr.SYSTEMS:
        entries = vr.definitions_for(system)
        assert entries
        assert all(e.system == system for e in entries)
        assert [e.frame_line for e in entries] == sorted(
            e.frame_line for e in entries)
    assert len(vr.definitions_for("PAL")) + len(vr.definitions_for("NTSC")) == len(ALL)


def test_definition_lookup_by_id():
    assert vr.definition("pal-its-field1") is vr.VITS_PAL_LINE19
    assert vr.definition("no-such-vits") is None


def test_a_field_line_can_host_more_than_one_candidate():
    # PAL field line 20 carries the multiburst in field 1 and the chrominance
    # bars in field 2, so a check cannot pick by line number alone.
    on_20 = vr.definitions_on_field_line("PAL", 20)
    assert {e.id for e in on_20} == {
        "pal-multiburst-field1", "pal-multiburst-field2"}


def test_the_amendment_two_alternate_line_is_reachable():
    # IEC 60856-1986 9.1.3 (Amendment 2) permits line 13 or 20; GGV and Roger
    # Rabbit use 13, so a lookup on field line 13 has to find the multiburst.
    on_13 = vr.definitions_on_field_line("PAL", 13)
    assert {e.id for e in on_13} == {
        "pal-multiburst-field1", "pal-multiburst-field2"}


def test_ntsc_definitions_state_no_mastering_tolerance():
    # Neither IEC 60857 nor the NTC-7 definitions state one, and inventing a
    # number here would let a conformance check assert something no standard
    # requires.  The pass band comes from the decoder allowance instead.
    for entry in vr.definitions_for("NTSC"):
        for elem in entry.elements:
            assert elem.tolerance is None, f"{entry.id}/{elem.id}"


def test_pal_definitions_carry_the_iec_mastering_tolerances():
    for vits_id in ("pal-its-field1", "pal-its-field2", "pal-multiburst-field1",
                    "pal-multiburst-field2"):
        entry = vr.definition(vits_id)
        for elem in entry.elements:
            assert elem.tolerance is not None, f"{entry.id}/{elem.id}"
            assert elem.tolerance > 0
