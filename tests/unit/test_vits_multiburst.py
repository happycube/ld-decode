"""
test_vits_multiburst - multiburst frequency-response conformance

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Every case renders a multiburst from the vits_reference nominals (see
tests/vits_synth.py) and asserts which checks notice which fault.  The pair
that matters is the separation the layer exists for: a response tilt must
fail flatness while every frequency check still passes, and a time-base
error must fail frequency while flatness still passes.  A report that
confuses the two sends the reader to the wrong subsystem.

No capture file is read.
"""

import numpy as np
import pytest

import vits_conformance as vc
import vits_geometry as vg
import vits_measure as vm
import vits_multiburst as mb
import vits_reference as vr
import vits_synth as vs

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

#: Every definition carrying a multiburst, and the set each should match.
MULTIBURST_IDS = ("pal-multiburst-field1", "ntsc-fcc-multiburst",
                  "ntsc-ntc7-combination")
EXPECTED_SETS = {"pal-multiburst-field1": "IEC",
                 "ntsc-fcc-multiburst": "FCC",
                 "ntsc-ntc7-combination": "NTC7"}

#: Fields the NTC-7 combination needs before its amplitude may be judged;
#: anything else is admissible from one field.
AVERAGED = mb.NTC7_MIN_AVERAGE_FIELDS


def measured(vits_id, **kwargs):
    """(entry, measurements, line) for one multiburst rendered on its line."""
    entry = vr.definition(vits_id)
    field = vs.make_field(entry.system, is_first_field=(entry.field == 1))
    line = vs.render_definition(field, entry, **kwargs)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    return entry, vm.measure_definition(field, entry, line, geom), line


def rows_of(vits_id, **kwargs):
    entry, measurements, _ = measured(vits_id, **kwargs)
    return mb.multiburst_response(entry, measurements, entry.system)


def checks_of(vits_id, fields_averaged=AVERAGED, **kwargs):
    entry, measurements, line = measured(vits_id, **kwargs)
    checks, _ = vc.check_multiburst(entry, measurements, line, "first",
                                    fields_averaged)
    return checks


def suffixed(checks, suffix):
    return [check for check in checks if check.id.endswith(suffix)]


def verdicts(checks, suffix):
    return {check.verdict for check in suffixed(checks, suffix)}


# ---------------------------------------------------------------------------
# The response table
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("vits_id", MULTIBURST_IDS)
def test_a_rendered_multiburst_matches_the_set_it_was_drawn_from(vits_id):
    set_name, score, rows = rows_of(vits_id)
    assert set_name == EXPECTED_SETS[vits_id]
    assert score > 0.9
    assert len(rows) == 6


@pytest.mark.parametrize("vits_id", MULTIBURST_IDS)
def test_every_packet_reports_the_frequency_it_was_drawn_at(vits_id):
    _, _, rows = rows_of(vits_id)
    for row in rows:
        assert row.freq_mhz == pytest.approx(row.nominal_freq_mhz, abs=0.05)


@pytest.mark.parametrize("vits_id", MULTIBURST_IDS)
def test_the_reference_packet_is_the_one_nearest_one_megahertz(vits_id):
    _, _, rows = rows_of(vits_id)
    reference = [row for row in rows if row.is_reference]
    assert len(reference) == 1
    assert (mb.REFERENCE_BAND_MHZ[0] <= reference[0].freq_mhz
            <= mb.REFERENCE_BAND_MHZ[1])
    assert reference[0].relative_db == pytest.approx(0.0)


@pytest.mark.parametrize("vits_id", MULTIBURST_IDS)
def test_a_flat_multiburst_reports_a_flat_response(vits_id):
    _, _, rows = rows_of(vits_id)
    # Every packet is drawn at the same nominal, so the whole train should
    # read within a fraction of a dB of the reference.
    for row in rows:
        assert abs(row.relative_db) < 0.5, row.element_id


def test_a_definition_with_no_multiburst_reports_no_response():
    entry = vr.definition("pal-its-field1")
    field = vs.make_field("PAL")
    line = vs.render_definition(field, entry)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    measurements = vm.measure_definition(field, entry, line, geom)
    assert mb.multiburst_response(entry, measurements) == (None, 0.0, [])


def test_a_train_with_no_packet_near_one_megahertz_has_no_reference():
    # The relative response is meaningless without the packet the servo
    # convention reads everything against, so it is refused rather than
    # referred to whichever packet came first.
    entry = vr.definition("ntsc-fcc-multiburst")
    field = vs.make_field("NTSC")
    line = vs.render_definition(field, entry)
    # Erase the 1.25 MHz packet back to the pedestal it rides on.
    packet = entry.element("packet_2")
    vs.draw_bar(field, line, packet.start_us, packet.end_us, 40.0)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    measurements = vm.measure_definition(field, entry, line, geom)
    _, _, rows = mb.multiburst_response(entry, measurements)
    assert not any(row.is_reference for row in rows)
    judge, reason = mb.flatness_judgement(entry, rows[2], None, AVERAGED,
                                          "NTSC")
    assert judge is False
    assert "reference packet" in reason


# ---------------------------------------------------------------------------
# A conformant rendering, and the two faults kept apart
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("vits_id", MULTIBURST_IDS)
def test_a_conformant_multiburst_passes_every_judged_check(vits_id):
    checks = checks_of(vits_id)
    assert verdicts(checks, "/frequency") <= {"PASS", "SKIP"}
    assert verdicts(checks, "/response") <= {"PASS", "SKIP"}
    assert "PASS" in verdicts(checks, "/frequency")


def test_a_one_decibel_high_frequency_tilt_fails_flatness_alone():
    # The fault this check exists for: the response droops or lifts across
    # the band the equaliser is supposed to hold flat, with every packet
    # still at the frequency it should be.
    def tilt(freq_mhz):
        return 10.0 ** (1.0 / 20.0) if freq_mhz >= 2.0 else 1.0

    checks = checks_of("ntsc-fcc-multiburst", packet_gain=tilt)
    assert "FAIL" in verdicts(checks, "/response")
    assert "FAIL" not in verdicts(checks, "/frequency")


def test_a_three_per_cent_frequency_error_fails_frequency_alone():
    # A time-base fault: every packet at the right level, all of them at the
    # wrong rate.  The 2 MHz packet of a PAL multiburst is not judged on
    # this - a 4 us window resolves 2 MHz to about 1.25%, which with the
    # +/-2% the figure allows does not separate a 3% error - so the
    # assertion is that the check fails somewhere, not everywhere.
    checks = checks_of("pal-multiburst-field1", packet_freq_scale=1.03)
    assert "FAIL" in verdicts(checks, "/frequency")
    assert "FAIL" not in verdicts(checks, "/response")


def test_a_frequency_error_and_a_tilt_are_reported_separately():
    def tilt(freq_mhz):
        return 10.0 ** (1.0 / 20.0) if freq_mhz >= 2.0 else 1.0

    checks = checks_of("pal-multiburst-field1", packet_gain=tilt,
                       packet_freq_scale=1.03)
    assert "FAIL" in verdicts(checks, "/frequency")
    assert "FAIL" in verdicts(checks, "/response")
    # And they are different checks, so triage can tell which subsystem.
    failed = {check.id for check in checks if check.verdict == "FAIL"}
    assert any(name.endswith("/frequency") for name in failed)
    assert any(name.endswith("/response") for name in failed)


# ---------------------------------------------------------------------------
# What is judged, and what is only reported
# ---------------------------------------------------------------------------

def test_the_band_the_equaliser_anchors_comes_from_the_decoder():
    # lddecode/decoder.py sets veq_max_freq to 3.6 MHz for PAL and 2.8 for
    # NTSC and skips anchors below 0.7 MHz; the check must not claim
    # flatness anywhere the decoder does not act.
    assert mb.servo_band_mhz("PAL") == (0.7, 3.6)
    assert mb.servo_band_mhz("NTSC") == (0.7, 2.8)
    with pytest.raises(KeyError, match="SECAM"):
        mb.servo_band_mhz("SECAM")


def test_a_packet_above_the_equalisers_reach_is_reported_not_judged():
    checks = checks_of("pal-multiburst-field1")
    # 4.2, 4.8 and 5.8 MHz all sit above the 3.6 MHz PAL anchor limit.
    for element_id in ("packet_4", "packet_5", "packet_6"):
        check = suffixed(checks, f"{element_id}/response")[0]
        assert check.verdict == "SKIP"
        assert np.isfinite(check.measured)


def test_a_packet_below_the_equalisers_reach_is_reported_not_judged():
    checks = checks_of("pal-multiburst-field1")
    check = suffixed(checks, "packet_1/response")[0]
    assert check.verdict == "SKIP"
    assert "0.7" in check.reason


def test_the_uncorrectable_band_is_named_with_its_citation():
    # The plan requires the excluded region to be a named constant carrying
    # the measurement it came from, not a magic number inside an if.
    assert mb.UNCORRECTED_BANDS_MHZ["PAL"] == ((4.0, 4.8),)
    entry = vr.definition("pal-multiburst-field1")
    _, _, rows = rows_of("pal-multiburst-field1")
    row = next(r for r in rows if 4.0 <= r.freq_mhz <= 4.8)
    assert row.uncorrected_band == (4.0, 4.8)
    _, reason = mb.flatness_judgement(entry, row, rows[1], AVERAGED, "PAL")
    assert "vits-servos.md" in reason


def test_a_short_window_reports_its_frequency_without_judging_it():
    checks = checks_of("ntsc-ntc7-combination")
    # The NTC-7 packets are about 2 us after guarding, so the low-frequency
    # ones cannot resolve the tolerance they would be judged against.
    check = suffixed(checks, "packet_1/frequency")[0]
    assert check.verdict == "SKIP"
    assert "cycles" in check.reason
    assert check.measured == pytest.approx(0.5, abs=0.05)


def test_the_frequency_band_is_the_figures_tolerance_plus_the_estimators():
    _, _, rows = rows_of("pal-multiburst-field1")
    row = next(r for r in rows if r.nominal_freq_mhz == 2.3)
    spec, allowance = mb.frequency_band_mhz(row, "PAL")
    # IEC 60856-1986 9.1.3 Figure 8 c): +/-2% of the nominal.
    assert spec == pytest.approx(0.02 * 2.3)
    assert allowance == pytest.approx(
        vr.MULTIBURST_FREQ_ALLOWANCE_CYCLES * row.freq_mhz / row.cycles,
        rel=1e-6)


def test_no_ntsc_source_states_a_frequency_tolerance_so_none_is_claimed():
    _, _, rows = rows_of("ntsc-fcc-multiburst")
    spec, allowance = mb.frequency_band_mhz(rows[2], "NTSC")
    assert spec == 0.0
    assert allowance > 0.0


# ---------------------------------------------------------------------------
# The NTC-7 combination restriction
# ---------------------------------------------------------------------------

def test_amplitude_from_a_single_ntc7_field_is_refused_with_a_reason():
    entry = vr.definition("ntsc-ntc7-combination")
    admissible, reason = mb.amplitude_admissible(entry, 1)
    assert admissible is False
    assert str(AVERAGED) in reason
    assert "NTSC_MULTIBURST_NTC7" in reason


def test_amplitude_from_enough_averaged_ntc7_fields_is_admitted():
    entry = vr.definition("ntsc-ntc7-combination")
    assert mb.amplitude_admissible(entry, AVERAGED) == (True, "")


@pytest.mark.parametrize("vits_id", ["pal-multiburst-field1",
                                     "ntsc-fcc-multiburst"])
def test_a_long_packet_multiburst_needs_no_averaging(vits_id):
    entry = vr.definition(vits_id)
    assert mb.amplitude_admissible(entry, 1) == (True, "")


def test_a_single_field_ntc7_response_check_skips_rather_than_passing():
    checks = checks_of("ntsc-ntc7-combination", fields_averaged=1)
    responses = suffixed(checks, "/response")
    assert {check.verdict for check in responses} == {"SKIP"}
    assert all(str(AVERAGED) in check.reason for check in responses)
    # Presence and frequency are unaffected by the restriction.
    assert "PASS" in verdicts(checks, "/frequency")


def test_a_single_field_ntc7_level_check_skips_rather_than_passing():
    entry, measurements, line = measured("ntsc-ntc7-combination")
    single = vc.check_levels(entry, measurements, line, "second", 1)
    averaged = vc.check_levels(entry, measurements, line, "second", AVERAGED)
    packets = [element.id for element in entry.elements
               if element.kind == "burst_packet"]
    single_by_id = {check.id: check for check in single}
    averaged_by_id = {check.id: check for check in averaged}
    for packet in packets:
        name = f"{entry.id}/{packet}"
        assert single_by_id[name].verdict == "SKIP"
        assert str(AVERAGED) in single_by_id[name].reason
        assert averaged_by_id[name].verdict == "PASS"


# ---------------------------------------------------------------------------
# The window-occupancy correction the restriction rests on
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("drawn_us", [4.0, 3.5, 3.0])
def test_a_packet_shorter_than_its_window_is_read_at_its_own_amplitude(
        drawn_us):
    # This is the under-read docs/technical/vits-servos.md records as "up to
    # 2.5 dB with the wrong sign": a fit over a window wider than the packet
    # returns the amplitude averaged over the window.  Dividing by the
    # occupancy the fit's own residual reports recovers the amplitude of the
    # tone where it is present, which is what the nominal states.
    entry = vr.definition("ntsc-fcc-multiburst")
    element = entry.element("packet_4")
    field = vs.make_field("NTSC")
    vs.draw_bar(field, 22, 9.2, 62.0, 40.0)
    vs.draw_burst(field, 22, element.start_us, element.start_us + drawn_us,
                  30.0, element.freq_mhz, rise_us=0.2)
    geom = vg.FieldGeometry(field, origin_samples=0.0)

    guard_start, guard_end = vm.guarded_window(*element.window_us)
    covered = element.start_us + drawn_us - guard_start
    expected_duty = covered / (guard_end - guard_start)
    assert expected_duty > vm.PACKET_MIN_DUTY

    measurement = vm.measure_burst_packet(geom, 22, element)
    assert measurement.detail["duty"] == pytest.approx(expected_duty, abs=0.04)
    assert measurement.value == pytest.approx(30.0, abs=0.5)
    # The uncorrected figure is reported beside it, so the size of the
    # correction is visible rather than implicit.
    assert measurement.detail["fitted_pp_ire"] / 2.0 == pytest.approx(
        30.0 * expected_duty, abs=0.8)


def test_a_window_holding_almost_nothing_is_left_as_fitted():
    entry = vr.definition("ntsc-fcc-multiburst")
    element = entry.element("packet_4")
    field = vs.make_field("NTSC")
    vs.draw_bar(field, 22, 9.2, 62.0, 40.0)
    vs.draw_burst(field, 22, element.start_us, element.start_us + 1.2,
                  30.0, element.freq_mhz, rise_us=0.2)
    geom = vg.FieldGeometry(field, origin_samples=0.0)

    measurement = vm.measure_burst_packet(geom, 22, element)
    assert measurement.detail["duty"] < vm.PACKET_MIN_DUTY
    assert measurement.value == pytest.approx(
        measurement.detail["fitted_pp_ire"] / 2.0)


def test_a_window_too_short_in_cycles_is_left_as_fitted():
    # Below PACKET_DUTY_MIN_CYCLES the frequency refinement's own upward
    # bias dominates, and correcting would double it.
    entry = vr.definition("pal-multiburst-field1")
    element = entry.element("packet_1")
    _, measurements, _ = measured("pal-multiburst-field1")
    detail = measurements[element.id].detail
    assert detail["cycles"] < vm.PACKET_DUTY_MIN_CYCLES
    assert measurements[element.id].value == pytest.approx(
        detail["fitted_pp_ire"] / 2.0)


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def test_every_frequency_check_names_the_set_it_was_judged_against():
    for vits_id in MULTIBURST_IDS:
        for check in suffixed(checks_of(vits_id), "/frequency"):
            assert EXPECTED_SETS[vits_id] in check.clause
            assert "frequency set" in check.clause


def test_every_response_check_cites_where_its_band_came_from():
    for check in suffixed(checks_of("ntsc-fcc-multiburst"), "/response"):
        assert "vits-servos.md" in check.clause
        assert check.allowance == pytest.approx(vr.SERVO_FLATNESS_DB)


def test_the_response_table_carries_every_packet_whether_judged_or_not():
    entry, measurements, line = measured("pal-multiburst-field1")
    _, response = vc.check_multiburst(entry, measurements, line, "first",
                                      AVERAGED)
    assert response["vits_id"] == entry.id
    assert response["set"] == "IEC"
    assert len(response["packets"]) == 6
    for packet in response["packets"]:
        assert packet["freq_mhz"] > 0.0
        assert packet["amplitude_ire"] > 0.0
        assert np.isfinite(packet["relative_db"])
