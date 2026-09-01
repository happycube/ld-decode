"""
test_vits_measure - VITS element measurement primitives

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Every case here is driven by a field synthesised from the vits_reference
nominals (see tests/vits_synth.py), so a primitive is checked against a value
that was deliberately put there.  The fault-injection cases inject what the
conformance layer above this exists to catch: a flat gain error, a gain error
confined to one band, a pedestal shift and a high-frequency loss.

No capture file is read.
"""

import inspect

import numpy as np
import pytest

import vits_geometry as vg
import vits_measure as vm
import vits_reference as vr
import vits_synth as vs

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

#: Origins to sweep: the row boundary itself, and the two a real decode was
#: measured at (NTSC +1.95 samples, PAL -0.98 samples).
ORIGINS = (0.0, 1.95, -0.98)

#: Definitions with something to measure.  The blanked PAL lines carry no
#: content, which is exactly why identification skips them.
MEASURABLE = tuple(
    entry for entry in vr.VITS_DEFINITIONS
    if not all(element.kind == "blanked" for element in entry.elements)
)
MEASURABLE_IDS = [entry.id for entry in MEASURABLE]


def rendered(entry, origin_samples=0.0, **kwargs):
    """(field, geometry) with one definition drawn on its own line."""
    field = vs.make_field(entry.system, is_first_field=(entry.field == 1),
                          origin_samples=origin_samples)
    vs.render_definition(field, entry, **kwargs)
    return field, vg.FieldGeometry(field, origin_samples=origin_samples)


# ---------------------------------------------------------------------------
# The loader is CVBS only
# ---------------------------------------------------------------------------

def test_a_tbc_path_is_refused_by_name():
    with pytest.raises(ValueError, match=r"\.tbc"):
        vm.load("somewhere/capture.tbc")


def test_the_module_reaches_no_tbc_loader():
    # The acceptance for this phase: load_cvbs is the only loader here, so a
    # .tbc can never be measured through a second path.
    assert not hasattr(vm, "load_tbc")
    assert not hasattr(vm, "load_video")
    assert "load_tbc" not in inspect.getsource(vm)


# ---------------------------------------------------------------------------
# Primitives against the nominals
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("entry", MEASURABLE, ids=MEASURABLE_IDS)
@pytest.mark.parametrize("origin", ORIGINS)
def test_every_element_recovers_its_nominal(entry, origin):
    field, geom = rendered(entry, origin)
    measurements = vm.measure_definition(field, entry, geom=geom)

    for element in entry.elements:
        if element.nominal is None or element.kind == "blanked":
            continue
        assert element.id in measurements, element.id
        measurement = measurements[element.id]
        # 1 IRE is the tightest band any of these standards states (IEC
        # 60856-1986 9.1.3: +/-1% of the 0.70 V reference bar), so a
        # primitive that cannot recover a nominal to better than that cannot
        # be used to judge conformance against it.
        assert measurement.deviation == pytest.approx(0.0, abs=1.0), (
            f"{entry.id}/{element.id}")


@pytest.mark.parametrize("entry", MEASURABLE, ids=MEASURABLE_IDS)
def test_a_conformant_rendering_measures_inside_its_own_tolerance(entry):
    field, geom = rendered(entry)
    measurements = vm.measure_definition(field, entry, geom=geom)
    for element in entry.elements:
        if element.tolerance is None or element.id not in measurements:
            continue
        allowed = vr.to_ire(element.tolerance, entry.system)
        assert abs(measurements[element.id].deviation) <= allowed, (
            f"{entry.id}/{element.id}")


def test_a_flat_level_reports_its_ripple_and_a_quality():
    entry = vr.definition("ntsc-ntc7-composite")
    field, geom = rendered(entry)
    measurement = vm.measure_level(geom, 20, 14.0, 28.0)
    assert measurement.value == pytest.approx(100.0, abs=0.5)
    assert measurement.detail["ripple_ire"] < 1.0
    assert measurement.quality > 0.9


def test_level_quality_falls_with_noise(seeded_rng):
    entry = vr.definition("ntsc-ntc7-composite")
    field, geom = rendered(entry)
    clean = vm.measure_level(geom, 20, 14.0, 28.0).quality
    vs.add_noise(field, seeded_rng, 3.0)
    noisy = vm.measure_level(geom, 20, 14.0, 28.0).quality
    assert noisy < clean
    assert 0.0 <= noisy <= 1.0


def test_a_level_window_holding_no_samples_is_refused():
    entry = vr.definition("ntsc-ntc7-composite")
    _, geom = rendered(entry)
    with pytest.raises(ValueError):
        vm.measure_level_over(geom, 20, [])


def test_the_subcarrier_null_removes_a_superimposed_carrier():
    # A four-tap boxcar at 4fsc: the carrier goes, the level does not.
    carrier = 40.0 * np.cos(np.arange(64) * np.pi / 2)
    filtered = vm._suppress_subcarrier(50.0 + carrier)
    assert np.allclose(filtered, 50.0, atol=1e-9)


def test_a_pedestal_is_measured_clear_of_what_sits_on_it():
    # The FCC pedestal runs the length of the line with a white bar and six
    # packets on it; averaging the stated window whole would report neither.
    entry = vr.definition("ntsc-fcc-multiburst")
    field, geom = rendered(entry)
    pedestal = vm.measure_definition(field, entry, geom=geom)["grey_pedestal"]
    assert pedestal.value == pytest.approx(40.0, abs=0.5)
    assert len(pedestal.detail["windows_us"]) > 1


def test_uncovered_windows_leave_an_unobstructed_element_alone():
    entry = vr.definition("ntsc-virs-field1")
    element = entry.element("black_reference")
    assert vm._uncovered_windows(entry, element) == (element.window_us,)


def test_a_staircase_reports_treads_risers_and_step_inequality():
    entry = vr.definition("pal-its-field1")
    field, geom = rendered(entry)
    measurement = vm.measure_definition(field, entry, geom=geom)["staircase"]
    treads = measurement.detail["treads_ire"]
    assert len(treads) == len(entry.element("staircase").steps)
    assert treads == pytest.approx([20.0, 40.0, 60.0, 80.0, 100.0], abs=0.5)
    # IEC 60856-1986 9.1.3 Figure 7 d): six levels including black and white.
    assert (len(measurement.detail["risers_ire"]) + 1
            == vr.PAL_STAIRCASE_LEVEL_COUNT)
    assert measurement.detail["monotonic"] is True
    assert measurement.detail["step_inequality"] < vr.PAL_STAIRCASE_STEP_INEQUALITY


def test_step_inequality_rises_when_one_riser_is_wrong():
    entry = vr.definition("pal-its-field1")
    field, geom = rendered(entry)
    good = vm.measure_definition(field, entry, geom=geom)["staircase"]

    # Lift the middle tread by 5 IRE: the total amplitude is unchanged, so
    # only a step-by-step check can see it.
    field, geom = rendered(entry)
    vs.draw_bar(field, 19, 48.0, 52.0, 65.0)
    bad = vm.measure_definition(field, entry, geom=geom)["staircase"]

    assert bad.value == pytest.approx(good.value, abs=0.5)
    assert bad.detail["step_inequality"] > vr.PAL_STAIRCASE_STEP_INEQUALITY
    assert bad.detail["step_inequality"] > 10 * good.detail["step_inequality"]


def test_a_staircase_with_a_falling_tread_scores_zero_quality():
    entry = vr.definition("pal-its-field1")
    field, geom = rendered(entry)
    vs.draw_bar(field, 19, 48.0, 52.0, 10.0)
    measurement = vm.measure_definition(field, entry, geom=geom)["staircase"]
    assert measurement.detail["monotonic"] is False
    assert measurement.quality == 0.0


def test_the_treads_of_an_uneven_staircase_follow_the_definition():
    # The PAL treads run 4, 4, 4, 4 then 6 us; dividing the window equally
    # would put the last two measurements on the wrong side of a riser.
    element = vr.definition("pal-its-field1").element("staircase")
    assert vm._tread_windows(element) == element.step_windows_us
    assert element.step_windows_us[-1] == (56.0, 62.0)


def test_an_evenly_stepped_staircase_divides_its_window():
    element = vr.definition("ntsc-ntc7-composite").element("staircase")
    assert not element.step_windows_us
    windows = vm._tread_windows(element)
    assert len(windows) == len(element.steps)
    assert windows[0][0] == element.start_us
    assert windows[-1][1] == pytest.approx(element.end_us)


@pytest.mark.parametrize("vits_id", ["pal-multiburst-field1",
                                     "ntsc-fcc-multiburst"])
def test_packet_frequencies_are_measured_not_assumed(vits_id):
    entry = vr.definition(vits_id)
    field, geom = rendered(entry)
    measurements = vm.measure_definition(field, entry, geom=geom)
    for element in entry.elements:
        if element.kind != "burst_packet":
            continue
        detail = measurements[element.id].detail
        assert detail["freq_mhz"] == pytest.approx(element.freq_mhz, abs=0.05)
        assert detail["coherence"] > 0.9


def test_a_packet_at_the_wrong_frequency_is_reported_there():
    entry = vr.definition("ntsc-fcc-multiburst")
    field = vs.make_field("NTSC")
    vs.render_definition(field, entry)
    # Overwrite the 2 MHz packet with a 2.6 MHz one.
    element = entry.element("packet_3")
    vs.draw_bar(field, 22, element.start_us, element.end_us, 40.0)
    vs.draw_burst(field, 22, element.start_us, element.end_us, 30.0, 2.6)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    measurement = vm.measure_burst_packet(geom, 22, element)
    assert measurement.detail["freq_mhz"] == pytest.approx(2.6, abs=0.06)
    assert measurement.detail["freq_error_mhz"] == pytest.approx(0.6, abs=0.06)


def test_a_packet_window_with_no_tone_reports_no_frequency():
    entry = vr.definition("ntsc-fcc-multiburst")
    field = vs.make_field("NTSC")
    vs.draw_bar(field, 22, 9.2, 62.0, 40.0)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    measurement = vm.measure_burst_packet(geom, 22, entry.element("packet_3"))
    assert measurement.value == 0.0
    assert measurement.quality == 0.0
    assert "reason" in measurement.detail


def test_chroma_is_measured_against_the_lines_own_burst():
    entry = vr.definition("ntsc-virs-field1")
    field, geom = rendered(entry)
    measurement = vm.measure_definition(
        field, entry, geom=geom)["chroma_reference"]
    assert measurement.value == pytest.approx(20.0, abs=0.5)
    assert measurement.detail["burst_amp_ire"] == pytest.approx(20.0, abs=1.0)
    # Both drawn at 0 degrees, so the element is in phase with the burst.
    assert measurement.detail["burst_relative_phase_deg"] == pytest.approx(
        0.0, abs=2.0)


def test_a_chroma_phase_shift_is_reported_against_the_burst():
    entry = vr.definition("ntsc-virs-field1")
    field = vs.make_field("NTSC")
    vs.draw_colour_burst(field, 19)
    vs.draw_bar(field, 19, 12.0, 36.0, 70.0)
    vs.draw_burst(field, 19, 13.0, 34.5, 20.0, 3.579545, phase_deg=30.0)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    measurement = vm.measure_chroma(geom, 19, entry.element("chroma_reference"))
    assert measurement.detail["burst_relative_phase_deg"] == pytest.approx(
        30.0, abs=2.0)


def test_a_chroma_element_over_a_staircase_is_measured_per_tread():
    # The zones are the differential gain table: one chrominance amplitude
    # per luminance pedestal.
    entry = vr.definition("ntsc-ntc7-composite")
    field, geom = rendered(entry)
    measurement = vm.measure_definition(
        field, entry, geom=geom)["chroma_reference"]
    zones = measurement.detail["zones"]
    assert len(zones) >= 5
    lumas = [zone["luma_ire"] for zone in zones]
    assert lumas == sorted(lumas)
    assert measurement.value == pytest.approx(20.0, abs=0.5)


def test_splitting_a_chroma_window_does_not_move_a_flat_answer():
    entry = vr.definition("pal-multiburst-field2")
    element = entry.element("chroma_reference")
    field, geom = rendered(entry)
    whole = vm.measure_chroma(geom, 20, element, "PAL")
    split = vm.measure_chroma(geom, 20, element, "PAL", windows=[
        (34.0, 47.0), (47.0, 60.0)])
    assert split.value == pytest.approx(whole.value, abs=0.2)


def test_a_pulse_reports_its_width_and_ratio_against_the_bar():
    entry = vr.definition("pal-its-field1")
    field, geom = rendered(entry)
    measurement = vm.measure_definition(field, entry, geom=geom)["pulse_2t"]
    # ITU-T J.63 Annex I section 2: 2T half-duration 0.200 us.
    assert measurement.detail["had_ns"] == pytest.approx(200.0, abs=15.0)
    assert measurement.detail["pulse_to_bar"] == pytest.approx(1.0, abs=0.01)


def test_a_pulse_shifted_within_its_search_margin_is_still_measured():
    # Real discs move these: GGV PAL carries its whole line 19 signal 0.85 us
    # early.  The peak search has to reach it.
    entry = vr.definition("pal-its-field1")
    field = vs.make_field("PAL")
    vs.draw_bar(field, 19, 12.0, 22.0, 100.0)
    vs.draw_pulse(field, 19, 26.0 - 0.8, 0.2, 100.0)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    measurement = vm.measure_pulse(geom, 19, entry.element("pulse_2t"),
                                   bar_ire=100.0)
    assert measurement.value == pytest.approx(100.0, abs=2.0)
    assert measurement.detail["centre_us"] == pytest.approx(25.2, abs=0.1)


def test_a_pulse_that_lost_height_reports_a_low_ratio():
    entry = vr.definition("pal-its-field1")
    field = vs.make_field("PAL")
    vs.draw_bar(field, 19, 12.0, 22.0, 100.0)
    vs.draw_pulse(field, 19, 26.0, 0.2, 90.0)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    measurement = vm.measure_pulse(geom, 19, entry.element("pulse_2t"),
                                   bar_ire=100.0)
    assert measurement.detail["pulse_to_bar"] == pytest.approx(0.90, abs=0.02)


def test_the_blanking_reference_comes_from_the_back_porch():
    entry = vr.definition("pal-its-field1")
    field, geom = rendered(entry)
    assert vm.measure_line_blanking(geom, 19) == pytest.approx(0.0, abs=0.2)


def test_a_pedestal_offset_shows_as_an_offset_not_a_step_error():
    entry = vr.definition("pal-its-field1")
    field = vs.make_field("PAL")
    vs.render_definition(field, entry, level_offset_ire=5.0)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    measurement = vm.measure_definition(field, entry, geom=geom)["staircase"]
    assert measurement.value == pytest.approx(105.0, abs=0.5)
    # The risers between treads are untouched, so only the first one moves.
    assert measurement.detail["risers_ire"][1:] == pytest.approx(
        [20.0] * 4, abs=0.5)


# ---------------------------------------------------------------------------
# Fault injection: what the conformance layer above this has to see
# ---------------------------------------------------------------------------

def test_a_flat_luma_gain_error_moves_every_luma_level():
    entry = vr.definition("pal-its-field1")
    field = vs.make_field("PAL")
    vs.render_definition(field, entry, luma_gain=0.9)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    measurements = vm.measure_definition(field, entry, geom=geom)
    assert measurements["white_reference_bar"].value == pytest.approx(90.0, abs=0.5)
    assert measurements["staircase"].value == pytest.approx(90.0, abs=0.5)


def test_a_chroma_only_gain_error_leaves_every_luma_level_alone():
    # The differential-level fault: luma and chroma scaled independently.
    entry = vr.definition("pal-multiburst-field2")
    field = vs.make_field("PAL", is_first_field=False)
    vs.render_definition(field, entry, chroma_gain=0.8)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    measurements = vm.measure_definition(field, entry, geom=geom)
    assert measurements["grey_pedestal"].value == pytest.approx(50.0, abs=0.5)
    for element_id, nominal in (("chroma_bar_20", 10.0),
                                ("chroma_bar_60", 30.0),
                                ("chroma_bar_100", 50.0)):
        assert measurements[element_id].value == pytest.approx(
            0.8 * nominal, abs=0.5), element_id


def test_a_high_frequency_loss_shows_only_in_the_upper_packets():
    entry = vr.definition("ntsc-fcc-multiburst")
    field = vs.make_field("NTSC")
    vs.render_definition(field, entry)
    # Halve the top two packets, as a decode losing HF response would.
    for element_id in ("packet_5", "packet_6"):
        element = entry.element(element_id)
        vs.draw_bar(field, 22, element.start_us, element.end_us, 40.0)
        vs.draw_burst(field, 22, element.start_us, element.end_us,
                      15.0, element.freq_mhz)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    measurements = vm.measure_definition(field, entry, geom=geom)
    for element_id in ("packet_1", "packet_2", "packet_3", "packet_4"):
        assert measurements[element_id].value == pytest.approx(30.0, abs=1.0)
    for element_id in ("packet_5", "packet_6"):
        assert measurements[element_id].value == pytest.approx(15.0, abs=1.0)


# ---------------------------------------------------------------------------
# Locating a definition that a disc placed off the stated timing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("shift_us", [-0.85, 0.0, 0.6])
def test_a_shifted_definition_is_located_and_measured(shift_us):
    entry = vr.definition("pal-its-field1")
    # Drawing at a shifted origin moves the whole line, sync included, so
    # the sync origin is measured and the shift has to be found separately.
    field = vs.make_field("PAL")
    for element in entry.elements:
        if element.channel == "chroma" or element.nominal is None:
            continue
        if element.kind == "staircase":
            for tread, window in zip(element.steps,
                                     element.step_windows_us):
                vs.draw_bar(field, 19, window[0] + shift_us,
                            window[1] + shift_us, vr.to_ire(tread, "PAL"))
        elif element.kind == "pulse":
            centre = (element.start_us + element.end_us) / 2.0 + shift_us
            half = (element.end_us - element.start_us) / 2.0
            vs.draw_pulse(field, 19, centre, half,
                          vr.to_ire(element.nominal, "PAL"))
        else:
            vs.draw_bar(field, 19, element.start_us + shift_us,
                        element.end_us + shift_us,
                        vr.to_ire(element.nominal, "PAL"))

    geom = vg.FieldGeometry(field, origin_samples=0.0)
    offset_us, correlation = vm.measure_time_offset(geom, 19, entry)
    assert offset_us == pytest.approx(shift_us, abs=0.1)
    assert correlation > 0.9

    measurements = vm.measure_definition(field, entry, 19, geom)
    assert measurements["white_reference_bar"].value == pytest.approx(
        100.0, abs=1.0)
    assert measurements["pulse_2t"].value == pytest.approx(100.0, abs=2.0)


def test_a_definition_at_its_stated_time_needs_no_alignment():
    entry = vr.definition("ntsc-ntc7-composite")
    _, geom = rendered(entry)
    offset_us, correlation = vm.measure_time_offset(geom, 20, entry)
    assert offset_us == pytest.approx(0.0, abs=0.1)
    assert correlation > 0.95


def test_a_line_that_matches_nothing_is_not_slid_onto_noise(seeded_rng):
    entry = vr.definition("ntsc-ntc7-composite")
    field = vs.make_field("NTSC")
    vs.add_noise(field, seeded_rng, 20.0)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    aligned, offset_us, correlation = vm.align_geometry(geom, 20, entry)
    assert correlation < vm.TIME_ALIGN_MIN_CORRELATION
    assert offset_us == 0.0
    assert aligned.alignment_us == 0.0


def test_a_definition_with_no_luma_structure_reports_no_offset():
    # A blanked line is flat by definition: there is nothing to correlate,
    # and the correlator says so rather than sliding onto noise.
    entry = vr.definition("pal-blanked-field1")
    field = vs.make_field("PAL")
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    assert vm.measure_time_offset(geom, 22, entry) == (0.0, 0.0)


def test_a_flat_pedestal_is_still_located_by_its_own_edges():
    # The PAL chrominance bar line carries no luminance structure but its
    # pedestal, which is enough: the pedestal's ends are edges.
    entry = vr.definition("pal-multiburst-field2")
    _, geom = rendered(entry)
    offset_us, correlation = vm.measure_time_offset(geom, 20, entry)
    assert offset_us == pytest.approx(0.0, abs=0.1)
    assert correlation > vm.TIME_ALIGN_MIN_CORRELATION


def test_the_template_follows_the_definition():
    entry = vr.definition("pal-its-field1")
    times = np.array([13.0, 24.0, 26.0, 41.0, 57.0])
    template = vm.luma_template(entry, times)
    assert template[0] == pytest.approx(100.0)   # white bar
    assert template[1] == pytest.approx(0.0)     # between elements
    assert template[2] == pytest.approx(100.0)   # 2T crest
    assert template[3] == pytest.approx(20.0)    # first tread
    assert template[4] == pytest.approx(100.0)   # last tread


# ---------------------------------------------------------------------------
# Coherent averaging
# ---------------------------------------------------------------------------

def noisy_copies(entry, count, rng, sigma_ire=4.0):
    """`count` renderings of one definition, each with its own noise."""
    fields = []
    for index in range(count):
        field = vs.make_field(
            entry.system, is_first_field=(entry.field == 1),
            field_phase_id=1 + (index % 8 if entry.system == "PAL"
                                else index % 4))
        vs.render_definition(field, entry)
        vs.add_noise(field, rng, sigma_ire)
        field.field_index = index
        fields.append(field)
    return fields


def test_averaging_reduces_the_scatter_of_a_packet_measurement(seeded_rng):
    """The phase's stated acceptance, on synthesised fields."""
    entry = vr.definition("ntsc-fcc-multiburst")
    element = entry.element("packet_3")

    singles = []
    averages = []
    for _ in range(8):
        fields = noisy_copies(entry, 10, seeded_rng)
        geom = vg.FieldGeometry(fields[0], origin_samples=0.0)
        singles.append(vm.measure_burst_packet(geom, 22, element).value)

        averaged, used = vm.average_fields(fields, 10, phase_locked=False)
        assert used == 10
        geom = vg.FieldGeometry(averaged, origin_samples=0.0)
        averages.append(vm.measure_burst_packet(geom, 22, element).value)

    assert np.std(singles) > 2.0 * np.std(averages)


def test_an_average_keeps_the_lattice_of_the_fields_it_came_from(seeded_rng):
    entry = vr.definition("pal-multiburst-field1")
    fields = noisy_copies(entry, 8, seeded_rng)
    averaged, _ = vm.average_fields(fields, 8, phase_locked=False)
    assert np.array_equal(averaged.cvbs_row_starts, fields[0].cvbs_row_starts)
    assert averaged.params is fields[0].params
    assert averaged.dspicture.dtype == np.float64


def test_phase_locked_averaging_groups_by_subcarrier_position(seeded_rng):
    entry = vr.definition("pal-multiburst-field1")
    fields = noisy_copies(entry, 16, seeded_rng)
    averaged, used = vm.average_fields(fields, 10, phase_locked=True)
    # 16 fields across the 8-field PAL sequence leave 2 per phase.
    assert used == 2
    assert averaged.phase_locked is True


def test_parity_averaging_reaches_the_count_from_fewer_fields(seeded_rng):
    entry = vr.definition("pal-multiburst-field1")
    fields = noisy_copies(entry, 16, seeded_rng)
    _, used = vm.average_fields(fields, 10, phase_locked=False)
    assert used == 10


def test_chroma_from_an_average_that_ignored_phase_is_marked_untrusted(
        seeded_rng):
    entry = vr.definition("pal-multiburst-field2")
    fields = noisy_copies(entry, 8, seeded_rng)
    averaged, _ = vm.average_fields(fields, 8, phase_locked=False)
    geom = vg.FieldGeometry(averaged, origin_samples=0.0)
    measurement = vm.measure_chroma(
        geom, 20, entry.element("chroma_reference"), "PAL")
    assert measurement.quality == 0.0
    assert measurement.detail["phase_locked"] is False


def test_a_single_field_counts_as_phase_locked(seeded_rng):
    entry = vr.definition("pal-multiburst-field2")
    fields = noisy_copies(entry, 1, seeded_rng)
    averaged, used = vm.average_fields(fields, 1, phase_locked=False)
    assert used == 1
    assert averaged.phase_locked is True


def test_averaging_refuses_a_count_below_one():
    entry = vr.definition("ntsc-virs-field1")
    field, _ = rendered(entry)
    with pytest.raises(ValueError, match="at least 1"):
        vm.average_fields([field], 0)


def test_averaging_refuses_a_parity_that_is_not_there():
    entry = vr.definition("ntsc-virs-field1")
    field, _ = rendered(entry)
    with pytest.raises(ValueError, match="parity"):
        vm.average_fields([field], 4, parity=False)


# ---------------------------------------------------------------------------
# Result plumbing
# ---------------------------------------------------------------------------

def test_a_measurement_without_a_nominal_has_no_deviation():
    measurement = vm.Measurement(
        element_id="x", kind="bar", channel="luma", value=10.0, quality=1.0)
    assert measurement.deviation is None


def test_every_measurement_reports_the_alignment_it_was_made_under():
    entry = vr.definition("pal-its-field1")
    field, geom = rendered(entry)
    for measurement in vm.measure_definition(field, entry, geom=geom).values():
        assert "alignment_us" in measurement.detail
        assert "alignment_correlation" in measurement.detail


def test_measuring_unaligned_is_available():
    entry = vr.definition("pal-its-field1")
    field, geom = rendered(entry)
    measurements = vm.measure_definition(field, entry, geom=geom, align=False)
    assert measurements["white_reference_bar"].detail["alignment_us"] == 0.0
