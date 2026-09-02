"""
test_vits_conformance - level and differential-level verdicts

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Every case renders a definition from the vits_reference nominals (see
tests/vits_synth.py), optionally with a fault injected, and asserts which
checks notice.  The one that matters most is the differential-level pair: a
field whose chrominance band alone is mis-scaled must pass every absolute
luminance check and fail the gain ratio, because that is the fault this
whole layer exists to catch and the one a luminance-only check cannot see.

No capture file is read.
"""

import json

import numpy as np
import pytest

import vits_conformance as vc
import vits_geometry as vg
import vits_measure as vm
import vits_reference as vr
import vits_synth as vs

pytestmark = [pytest.mark.unit, pytest.mark.dsp, pytest.mark.vits]

#: Definitions with something to judge.
MEASURABLE = tuple(
    entry for entry in vr.VITS_DEFINITIONS
    if not all(element.kind == "blanked" for element in entry.elements)
)
MEASURABLE_IDS = [entry.id for entry in MEASURABLE]


def judged(entry, line=None, **kwargs):
    """(checks, measurements) for one definition rendered on its own line."""
    field = vs.make_field(entry.system, is_first_field=(entry.field == 1))
    line = vs.render_definition(field, entry, line=line, **kwargs)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    measurements = vm.measure_definition(field, entry, line, geom)
    checks = (vc.check_levels(entry, measurements, line, "first")
              + vc.check_ceilings(entry, measurements, line, "first")
              + vc.check_saturation(entry, measurements, line, "first")
              + vc.check_staircases(entry, measurements, line, "first")
              + vc.check_differential(entry, measurements, line, "first")
              + vc.check_chroma_nonlinearity(entry, measurements, line,
                                             "first"))
    return checks, measurements


def verdicts(checks):
    return {check.id: check.verdict for check in checks}


def by_id(checks, suffix):
    for check in checks:
        if check.id.endswith(suffix):
            return check
    raise AssertionError(f"no check ending {suffix!r} in "
                         f"{[c.id for c in checks]}")


# ---------------------------------------------------------------------------
# The tolerance budget
# ---------------------------------------------------------------------------

def test_every_allowance_states_where_its_number_came_from():
    # AGENTS.md section 15: widening one of these later needs the same
    # justification again, which is only possible if it is written down.
    for kind, entry in vr.DECODER_ALLOWANCES.items():
        assert entry.rationale, kind
        assert entry.source, kind
        assert entry.absolute >= 0.0, kind
        assert entry.relative >= 0.0, kind
        assert entry.unit in ("IRE", "fraction", "degrees", "ratio", "dB"), (
            kind)
        # Phase 6 task 6: a number derived from one capture is a number
        # derived from one radius, so every allowance also names the
        # baseline that says what it had to hold across a whole side.
        assert vr._BASELINE_SOURCE in entry.source, kind


def test_an_allowance_grows_with_the_level_it_judges():
    level = vr.allowance("luma_level")
    assert level.band(100.0) > level.band(20.0) > level.band(0.0)
    assert level.band(0.0) == vr.MEASUREMENT_FLOOR_IRE


def test_a_distortion_allowance_does_not_depend_on_a_nominal():
    for kind in ("differential_gain", "differential_phase",
                 "step_inequality", "chroma_nonlinearity"):
        assert vr.allowance(kind).relative == 0.0, kind
        assert vr.allowance(kind).band(50.0) == vr.allowance(kind).band()


def test_an_unknown_check_kind_has_no_silent_zero_band():
    with pytest.raises(KeyError, match="chrominance_wibble"):
        vr.allowance("chrominance_wibble")


def test_chrominance_is_allowed_more_than_luminance_and_says_why():
    # The asymmetry is deliberate: luminance is measured against the same
    # line's own blanking and white, chrominance carries a gain chain.
    luma = vr.allowance("luma_level")
    chroma = vr.allowance("chroma_level")
    assert chroma.relative > luma.relative
    assert chroma.relative == vr.CHAIN_NONLINEARITY
    assert luma.relative == vr.SERVO_RESIDUAL


# ---------------------------------------------------------------------------
# A conformant rendering passes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("entry", MEASURABLE, ids=MEASURABLE_IDS)
def test_a_conformant_rendering_passes_every_check(entry):
    checks, _ = judged(entry)
    failed = [check.id for check in checks if check.verdict == "FAIL"]
    assert failed == []
    assert any(check.verdict == "PASS" for check in checks)


@pytest.mark.parametrize("entry", MEASURABLE, ids=MEASURABLE_IDS)
def test_every_check_names_the_clause_it_enforces(entry):
    checks, _ = judged(entry)
    for check in checks:
        assert check.clause, check.id
        assert check.verdict in ("PASS", "FAIL", "SKIP"), check.id


def test_an_unmeasurable_element_is_declined_rather_than_failed():
    # The NTC-7 combination packets: too short to measure amplitude from at
    # NTSC 4fsc, so a verdict on them would report the sampling as a fault.
    entry = vr.definition("ntsc-ntc7-combination")
    checks, _ = judged(entry)
    for element in entry.elements:
        if element.kind != "burst_packet":
            continue
        assert not element.amplitude_measurable
        assert verdicts(checks)[f"{entry.id}/{element.id}"] == "SKIP"


def test_a_composite_pulses_chrominance_is_declined():
    entry = vr.definition("pal-its-field1")
    checks, _ = judged(entry)
    check = by_id(checks, "pulse_20t_chroma")
    assert check.verdict == "SKIP"
    assert "composite pulse" in check.reason


# ---------------------------------------------------------------------------
# Absolute levels
# ---------------------------------------------------------------------------

def test_a_luma_gain_error_fails_the_bar_that_carries_the_level():
    """A flat gain error is one fault and is reported once.

    IEC 60856-1986 Figure 7 states every element of the line as a tolerance
    about B2, the white reference bar beside it, so a line uniformly low is
    the bar's failure.  Reporting it again at every element measured against
    an absolute nominal the bar itself does not reach says the 2T pulse and
    the staircase are wrong when only the level is, and sends triage to the
    high-frequency path for a gain fault.
    """
    entry = vr.definition("pal-its-field1")
    checks, _ = judged(entry, luma_gain=0.90)
    assert by_id(checks, "white_reference_bar").verdict == "FAIL"
    for element_id in ("/staircase", "pulse_2t"):
        check = by_id(checks, element_id)
        assert check.verdict == "PASS", check.id
        assert check.detail["relative_to"] == "white_reference_bar"


def test_an_element_wrong_against_its_own_bar_still_fails():
    """The differential fault the relative comparison exists to catch."""
    entry = vr.definition("pal-its-field1")
    checks, _ = judged(entry, luma_gain=0.90,
                       element_gain={"pulse_2t": 0.90})
    assert by_id(checks, "pulse_2t").verdict == "FAIL"
    assert by_id(checks, "/staircase").verdict == "PASS"


def test_the_bar_itself_is_never_judged_against_itself():
    entry = vr.definition("pal-its-field1")
    checks, _ = judged(entry, luma_gain=0.90)
    check = by_id(checks, "white_reference_bar")
    assert check.detail["relative_to"] is None
    assert check.nominal == pytest.approx(check.detail["absolute_nominal"])


def test_an_ntsc_element_is_judged_against_its_absolute_nominal():
    """No NTSC source this project holds states a tolerance about the bar.

    The NTC-7 composite YAML gives the bar and the 2T pulse 100 IRE each and
    no relation between them, so both are judged absolutely; measured, the
    NTSC bars sit within 1.6 IRE of nominal on every radius cut, so nothing
    material rides on the difference there.
    """
    entry = vr.definition("ntsc-ntc7-composite")
    for element in entry.elements:
        assert element.relative_to is None, element.id


def test_a_luma_gain_error_inside_the_band_passes():
    entry = vr.definition("pal-its-field1")
    checks, _ = judged(entry, luma_gain=0.99)
    assert by_id(checks, "white_reference_bar").verdict == "PASS"


def test_a_pedestal_offset_fails_the_levels_it_shifts():
    entry = vr.definition("ntsc-ntc7-combination")
    checks, _ = judged(entry, level_offset_ire=6.0)
    assert by_id(checks, "grey_pedestal").verdict == "FAIL"


def test_a_missing_element_is_reported_as_unmeasured_not_as_zero():
    entry = vr.definition("ntsc-fcc-multiburst")
    field = vs.make_field("NTSC")
    vs.render_definition(field, entry)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    measurements = vm.measure_definition(field, entry, entry.field_line, geom)
    measurements.pop("packet_3")
    checks = vc.check_levels(entry, measurements, entry.field_line, "first")
    check = by_id(checks, "packet_3")
    assert check.verdict == "SKIP"
    assert np.isnan(check.measured)
    assert "not measurable" in check.reason


def test_the_luminance_ceiling_is_on_luminance_alone():
    # The PAL modulated staircase reaches a nominal 120 IRE composite where
    # its subcarrier rides the 100% tread, and is conformant: IEC 60856-1986
    # 9.1.5 caps luminance and chrominance separately for exactly that
    # reason.
    entry = vr.definition("pal-its-field2")
    checks, measurements = judged(entry)
    ceiling = by_id(checks, "ceiling/luminance")
    assert ceiling.verdict == "PASS"
    assert ceiling.measured == pytest.approx(100.0, abs=1.5)

    zones = measurements["staircase_subcarrier"].detail["zones"]
    composite = max(zone["luma_ire"] + zone["amp_ire"] for zone in zones)
    assert composite > vr.MAX_LUMINANCE_IRE


def test_an_over_white_signal_fails_the_luminance_ceiling():
    entry = vr.definition("pal-its-field1")
    checks, _ = judged(entry, luma_gain=1.15)
    assert by_id(checks, "ceiling/luminance").verdict == "FAIL"


def test_over_saturated_chrominance_fails_the_saturation_ceiling():
    entry = vr.definition("pal-multiburst-field2")
    conformant, _ = judged(entry)
    assert by_id(conformant, "ceiling/saturation").verdict == "PASS"
    hot, _ = judged(entry, chroma_gain=1.30)
    assert by_id(hot, "ceiling/saturation").verdict == "FAIL"


# ---------------------------------------------------------------------------
# The differential-level fault
# ---------------------------------------------------------------------------

def pal_gain_ratio_field(chroma_gain=1.0, luma_gain=1.0):
    """A PAL second field carrying both halves of the gain-ratio pair."""
    field = vs.make_field("PAL", is_first_field=False)
    bundle = {}
    for vits_id in ("pal-its-field2", "pal-multiburst-field2"):
        entry = vr.definition(vits_id)
        line = vs.render_definition(field, entry, chroma_gain=chroma_gain,
                                    luma_gain=luma_gain)
        geom = vg.FieldGeometry(field, origin_samples=0.0)
        bundle[vits_id] = vm.measure_definition(field, entry, line, geom)
    return field, bundle


def test_a_chroma_only_gain_error_fails_the_ratio_and_no_luma_check():
    """The acceptance this phase turns on."""
    field, bundle = pal_gain_ratio_field(chroma_gain=0.90)

    ratio = vc.check_luma_chroma_ratio(bundle, "second", "PAL")[0]
    assert ratio.verdict == "FAIL"
    assert ratio.detail["relative_deviation"] == pytest.approx(-0.10, abs=0.02)

    # Every luminance level on the same field is still right.
    for vits_id in ("pal-its-field2", "pal-multiburst-field2"):
        entry = vr.definition(vits_id)
        checks = vc.check_levels(entry, bundle[vits_id], entry.field_line,
                                 "second")
        for check in checks:
            element = entry.element(check.id.split("/")[-1])
            if element is None or element.channel != "luma":
                continue
            assert check.verdict == "PASS", check.id


def test_a_conformant_field_passes_the_ratio():
    _, bundle = pal_gain_ratio_field()
    ratio = vc.check_luma_chroma_ratio(bundle, "second", "PAL")[0]
    assert ratio.verdict == "PASS"
    assert ratio.measured == pytest.approx(ratio.nominal, rel=0.02)


def test_the_ratio_is_blind_to_a_gain_error_that_moves_both_bands():
    # A decode whose luminance and chrominance are equally wrong keeps the
    # ratio: that is what makes this a *differential* check, and why the
    # absolute level checks are still needed beside it.
    _, bundle = pal_gain_ratio_field(chroma_gain=0.90, luma_gain=0.90)
    ratio = vc.check_luma_chroma_ratio(bundle, "second", "PAL")[0]
    assert ratio.verdict == "PASS"


def test_the_ntsc_ratio_pair_lives_on_one_line():
    entry = vr.definition("ntsc-ntc7-composite")
    field = vs.make_field("NTSC")
    line = vs.render_definition(field, entry, chroma_gain=0.85)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    bundle = {entry.id: vm.measure_definition(field, entry, line, geom)}
    ratio = vc.check_luma_chroma_ratio(bundle, "first", "NTSC")[0]
    assert ratio.verdict == "FAIL"
    assert ratio.detail["relative_deviation"] == pytest.approx(-0.15, abs=0.03)


def test_the_ratio_is_skipped_when_half_the_pair_is_absent():
    entry = vr.definition("pal-its-field2")
    field = vs.make_field("PAL", is_first_field=False)
    line = vs.render_definition(field, entry)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    bundle = {entry.id: vm.measure_definition(field, entry, line, geom)}
    assert vc.check_luma_chroma_ratio(bundle, "second", "PAL") == []


# ---------------------------------------------------------------------------
# Differential gain and phase
# ---------------------------------------------------------------------------

def modulated_staircase_field(gains=None, phases_deg=None):
    """A PAL modulated staircase whose subcarrier varies with the tread.

    gains and phases_deg give one entry per zone, blanking level first.
    """
    entry = vr.definition("pal-its-field2")
    field = vs.make_field("PAL", is_first_field=False)
    line = entry.field_line
    vs.draw_colour_burst(field, line)

    element = entry.element("staircase")
    treads = [(0.0, (30.0, 40.0))] + list(
        zip(element.steps, element.step_windows_us))
    for tread, window in treads[1:]:
        vs.draw_bar(field, line, window[0], window[1],
                    vr.to_ire(tread, "PAL"))

    subcarrier = entry.element("staircase_subcarrier")
    nominal = vr.to_ire(subcarrier.nominal, "PAL")
    for index, (_, window) in enumerate(treads):
        gain = 1.0 if gains is None else gains[index]
        phase = 0.0 if phases_deg is None else phases_deg[index]
        vs.draw_burst(field, line, window[0], window[1],
                      nominal * gain, subcarrier.freq_mhz, phase_deg=phase)

    geom = vg.FieldGeometry(field, origin_samples=0.0)
    measurements = vm.measure_definition(field, entry, line, geom)
    return vc.check_differential(entry, measurements, line, "second")


def test_a_flat_modulated_staircase_passes_both_differential_checks():
    checks = modulated_staircase_field()
    assert by_id(checks, "differential_gain").verdict == "PASS"
    assert by_id(checks, "differential_phase").verdict == "PASS"


def test_chroma_amplitude_rising_with_luma_fails_differential_gain():
    checks = modulated_staircase_field(
        gains=[1.0, 1.05, 1.10, 1.15, 1.20, 1.25])
    gain = by_id(checks, "differential_gain")
    assert gain.verdict == "FAIL"
    assert gain.measured == pytest.approx(0.25, abs=0.03)
    # Phase was left alone, so only one of the pair moves.
    assert by_id(checks, "differential_phase").verdict == "PASS"


def test_chroma_phase_turning_with_luma_fails_differential_phase():
    checks = modulated_staircase_field(
        phases_deg=[0.0, 2.0, 4.0, 6.0, 8.0, 10.0])
    phase = by_id(checks, "differential_phase")
    assert phase.verdict == "FAIL"
    assert phase.measured == pytest.approx(10.0, abs=1.5)
    assert by_id(checks, "differential_gain").verdict == "PASS"


def test_the_differential_checks_are_referred_to_the_blanking_tread():
    # ITU-R BT.1439-1 3.3.1.3 refers both measures to the subcarrier at
    # blanking level, so a fault confined to the reference itself shows as
    # a deviation of every other tread.
    checks = modulated_staircase_field(
        gains=[0.80, 1.0, 1.0, 1.0, 1.0, 1.0])
    gain = by_id(checks, "differential_gain")
    assert gain.measured == pytest.approx(0.25, abs=0.03)


def test_an_unmodulated_chroma_element_is_not_a_differential_measurement():
    # The chrominance reference on the PAL bar line sits on one flat
    # pedestal, so there is no luminance variation to measure against.
    entry = vr.definition("pal-multiburst-field2")
    checks, _ = judged(entry)
    assert not [c for c in checks if "differential" in c.id]


# ---------------------------------------------------------------------------
# Non-linearity
# ---------------------------------------------------------------------------

def test_an_even_staircase_passes_the_non_linearity_check():
    entry = vr.definition("pal-its-field1")
    checks, _ = judged(entry)
    check = by_id(checks, "/nonlinearity")
    assert check.verdict == "PASS"
    assert check.measured < 0.01


def test_a_bowed_staircase_fails_the_non_linearity_check():
    entry = vr.definition("pal-its-field1")
    field = vs.make_field("PAL")
    line = vs.render_definition(field, entry)
    # Lift one tread: the top and the bar are untouched, so only a
    # riser-by-riser check can see it.
    vs.draw_bar(field, line, 48.0, 52.0, 68.0)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    measurements = vm.measure_definition(field, entry, line, geom)
    checks = (vc.check_levels(entry, measurements, line, "first")
              + vc.check_staircases(entry, measurements, line, "first"))
    assert by_id(checks, "/nonlinearity").verdict == "FAIL"
    assert by_id(checks, "white_reference_bar").verdict == "PASS"
    assert by_id(checks, "/staircase").verdict == "PASS"


def test_a_falling_staircase_is_declined_rather_than_failed():
    entry = vr.definition("pal-its-field1")
    field = vs.make_field("PAL")
    line = vs.render_definition(field, entry)
    vs.draw_bar(field, line, 48.0, 52.0, 5.0)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    measurements = vm.measure_definition(field, entry, line, geom)
    check = vc.check_staircases(entry, measurements, line, "first")[0]
    assert check.verdict == "SKIP"
    assert "monotonic" in check.reason


def test_a_curved_chroma_bar_fails_chrominance_non_linearity():
    entry = vr.definition("pal-multiburst-field2")
    field = vs.make_field("PAL", is_first_field=False)
    line = vs.render_definition(field, entry)
    # Lift only the middle step: the ratios between the three break.
    element = entry.element("chroma_bar_60")
    vs.draw_burst(field, line, element.start_us, element.end_us,
                  vr.to_ire(element.nominal, "PAL") * 1.30, element.freq_mhz)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    measurements = vm.measure_definition(field, entry, line, geom)
    check = vc.check_chroma_nonlinearity(entry, measurements, line,
                                         "second")[0]
    assert check.verdict == "FAIL"


def test_chrominance_non_linearity_ignores_a_flat_chroma_gain_error():
    # The counterpart of the ratio check: this one sees curvature only, so
    # between them the two cover both halves of a chrominance gain fault.
    entry = vr.definition("pal-multiburst-field2")
    checks, _ = judged(entry, chroma_gain=0.85)
    assert by_id(checks, "chroma_nonlinearity").verdict == "PASS"


# ---------------------------------------------------------------------------
# Blanked lines
# ---------------------------------------------------------------------------

def test_a_blanked_pal_line_passes():
    field = vs.make_field("PAL")
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    checks = vc.check_blanked_lines(geom, "first")
    assert [check.verdict for check in checks] == ["PASS"]
    assert checks[0].field_line == 22


def test_a_pal_line_carrying_signal_fails_the_blanking_requirement():
    field = vs.make_field("PAL")
    vs.draw_bar(field, 22, 12.0, 62.0, 8.0)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    check = vc.check_blanked_lines(geom, "first")[0]
    assert check.verdict == "FAIL"
    assert check.measured == pytest.approx(8.0, abs=0.5)


def test_noise_on_a_blanked_line_is_reported_not_judged(seeded_rng):
    # IEC 60856-1986 9.1.3 blanks these lines to *enable* a noise
    # measurement, so noise on them is the point, not a fault.
    field = vs.make_field("PAL")
    vs.add_noise(field, seeded_rng, 3.0)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    check = vc.check_blanked_lines(geom, "first")[0]
    assert check.verdict == "PASS"
    assert check.detail["noise_rms_ire"] > 2.0
    assert check.detail["absolute_max_ire"] > check.measured


def test_ntsc_has_no_blanked_line_requirement():
    field = vs.make_field("NTSC")
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    assert vc.check_blanked_lines(geom, "first") == []


def test_only_the_matching_parity_is_checked():
    for is_first, expected in ((True, "pal-blanked-field1"),
                               (False, "pal-blanked-field2")):
        field = vs.make_field("PAL", is_first_field=is_first)
        geom = vg.FieldGeometry(field, origin_samples=0.0)
        checks = vc.check_blanked_lines(geom, "first")
        assert [c.id for c in checks] == [f"{expected}/blanked"]


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def sample_context():
    return {"path": "synthetic", "system": "PAL", "fields": 2,
            "parities": [{"parity": "first", "fields_averaged": 1,
                          "origin_samples": 0.0, "origin_measured": True,
                          "picture_peak_ire": 101.0, "picture_max_ire": 104.0,
                          "identified": []}]}


def test_a_clean_run_reports_pass(capsys):
    entry = vr.definition("ntsc-virs-field1")
    checks, _ = judged(entry)
    status = vc.report(checks, sample_context())
    assert status == 0
    assert "VITS CONFORMANCE: PASS" in capsys.readouterr().out


def test_a_failing_run_reports_fail_and_a_nonzero_status(capsys):
    entry = vr.definition("pal-its-field1")
    checks, _ = judged(entry, luma_gain=0.80)
    status = vc.report(checks, sample_context())
    out = capsys.readouterr().out
    assert status == 1
    assert "VITS CONFORMANCE: FAIL" in out
    assert "[FAIL]" in out


def test_a_capture_with_no_vits_is_skipped_and_exits_zero(capsys):
    status = vc.report([], sample_context())
    assert status == 0
    assert "VITS CONFORMANCE: SKIPPED (no VITS detected)" in capsys.readouterr().out


def test_a_run_of_nothing_but_declined_checks_is_also_skipped(capsys):
    entry = vr.definition("ntsc-ntc7-combination")
    declined = [c for c in judged(entry)[0] if c.verdict == "SKIP"]
    assert declined
    status = vc.report(declined, sample_context())
    assert status == 0
    assert "SKIPPED" in capsys.readouterr().out


def test_every_reported_line_carries_its_clause(capsys):
    entry = vr.definition("pal-multiburst-field2")
    checks, _ = judged(entry)
    vc.report(checks, sample_context())
    out = capsys.readouterr().out
    for check in checks:
        if check.verdict == "SKIP" and np.isnan(check.measured):
            continue
        assert check.clause in out


def test_the_json_sidecar_round_trips():
    # The payload is built and serialised here rather than written: a unit
    # test touches no filesystem (TESTING.md), and write_json is a two-line
    # wrapper over this.
    entry = vr.definition("ntsc-virs-field1")
    checks, _ = judged(entry)
    payload = json.loads(json.dumps(
        vc.json_payload(checks, sample_context()), default=float))
    assert payload["summary"]["passed"] == sum(
        1 for c in checks if c.verdict == "PASS")
    assert len(payload["checks"]) == len(checks)
    assert payload["context"]["system"] == "PAL"
    for record in payload["checks"]:
        assert record["clause"]
        assert record["verdict"] in ("PASS", "FAIL", "SKIP")


@pytest.mark.parametrize("vits_id", MEASURABLE_IDS)
def test_every_check_that_carries_an_allowance_names_the_budget_it_came_from(
        vits_id):
    """A number with no name cannot be traced back to what justified it.

    The radius baseline groups a run's checks by their budget to show what
    each allowance is actually holding, so a check that carries an allowance
    without naming its kind would drop out of that survey unnoticed.
    """
    known = set(vr.DECODER_ALLOWANCES) | {"multiburst_frequency"}
    entry = vr.definition(vits_id)
    checks, measurements = judged(entry)
    line = entry.field_line
    checks += vc.check_multiburst(entry, measurements, line, "first")[0]
    carrying = [check for check in checks if check.allowance is not None]
    assert carrying, vits_id
    for check in carrying:
        assert check.allowance_kind in known, (vits_id, check.id)
