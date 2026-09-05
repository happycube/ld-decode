"""
test_vits_identify - recognising a VITS by what it measures

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Identification must never rest on a line number, because real discs move
these signals, and must not be defeated by a decode fault, because a fault
that hides the signal also hides itself.  Both properties are checked here
against fields synthesised from the vits_reference nominals.
"""

import numpy as np
import pytest

import vits_geometry as vg
import vits_identify as vi
import vits_reference as vr
import vits_synth as vs
from vits_measure import guarded_window, measure_definition

pytestmark = [pytest.mark.unit, pytest.mark.dsp, pytest.mark.vits]

SYSTEMS = ("NTSC", "PAL")

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
# Identification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("entry", MEASURABLE, ids=MEASURABLE_IDS)
def test_each_definition_is_identified_where_it_was_drawn(entry):
    field, geom = rendered(entry)
    found = vi.identify_vits(field, geom=geom)
    assert entry.field_line in found, entry.id
    identified = found[entry.field_line]
    assert identified.vits_id == entry.id
    assert identified.score >= vi.IDENTIFY_MIN_SCORE
    assert identified.on_expected_line is True


def test_a_definition_on_its_alternate_line_is_still_on_an_expected_line():
    # IEC 60856-1986 9.1.3 Amendment 2 permits frame line 13; GGV uses it.
    entry = vr.definition("pal-multiburst-field1")
    field = vs.make_field("PAL")
    vs.render_definition(field, entry, line=13)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    found = vi.identify_vits(field, geom=geom)
    assert found[13].vits_id == entry.id
    assert found[13].on_expected_line is True


def test_a_definition_on_an_unexpected_line_is_found_and_flagged():
    entry = vr.definition("ntsc-fcc-multiburst")
    field = vs.make_field("NTSC")
    vs.render_definition(field, entry, line=16)
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    found = vi.identify_vits(field, geom=geom)
    assert found[16].vits_id == entry.id
    assert found[16].on_expected_line is False


def test_an_empty_vbi_identifies_nothing():
    for system in SYSTEMS:
        field = vs.make_field(system)
        assert vi.identify_vits(field) == {}


def test_a_line_of_low_frequency_data_is_not_taken_for_a_multiburst(
        seeded_rng):
    # What a PAL VBI biphase data line looked like before the per-feature
    # floor: six "packets" all near 0.5 MHz, matching no published set, but
    # carried over the threshold by its levels and its chroma presence.
    field = vs.make_field("PAL")
    vs.draw_bar(field, 16, 12.0, 62.0, 40.0)
    for start in np.arange(14.0, 60.0, 4.0):
        vs.draw_burst(field, 16, start, start + 2.0, 30.0, 0.5)
    found = vi.identify_vits(field, lines=[16])
    assert found == {}


def test_the_multiburst_set_actually_present_is_the_one_reported():
    # Real PAL discs carry the ITU set, not the IEC set the definition uses.
    entry = vr.definition("pal-multiburst-field1")
    field = vs.make_field("PAL")
    vs.render_definition(field, entry)
    for element, freq_mhz in zip(
            [e for e in entry.elements if e.kind == "burst_packet"],
            vr.PAL_MULTIBURST_ITU):
        vs.draw_bar(field, 20, element.start_us, element.end_us, 50.0)
        vs.draw_burst(field, 20, element.start_us, element.end_us, 30.0,
                      freq_mhz)
    found = vi.identify_vits(field, lines=[20])
    assert found[20].vits_id == entry.id
    assert found[20].features["multiburst_set"] == "ITU"


@pytest.mark.parametrize("system, expected", [
    ("PAL", "IEC"), ("NTSC", "FCC")])
def test_the_definitions_own_set_matches_itself(system, expected):
    name, _, score = vi.identify_multiburst_set(
        vr.MULTIBURST_SETS[system][expected], system)
    assert name == expected
    assert score == pytest.approx(1.0)


def test_an_incomplete_packet_train_scores_below_a_complete_one():
    full = vi.identify_multiburst_set(vr.NTSC_MULTIBURST_FCC, "NTSC")[2]
    partial = vi.identify_multiburst_set(
        vr.NTSC_MULTIBURST_FCC[:3], "NTSC")[2]
    assert partial < full


def test_no_frequencies_match_no_set():
    assert vi.identify_multiburst_set([], "PAL") == (None, (), 0.0)


def test_a_blanked_definition_is_never_identified_by_content():
    entry = vr.definition("pal-blanked-field1")
    field = vs.make_field("PAL")
    geom = vg.FieldGeometry(field, origin_samples=0.0)
    score, features = vi.score_definition(geom, 22, entry)
    assert score is None
    assert "reason" in features


def test_the_virs_parities_are_told_apart_by_the_fields_own_parity():
    # The two are identical in content, so nothing but parity distinguishes
    # them - and parity is a property of the field, not a line number.
    for is_first, expected in ((True, "ntsc-virs-field1"),
                               (False, "ntsc-virs-field2")):
        field = vs.make_field("NTSC", is_first_field=is_first)
        vs.render_definition(field, vr.definition(expected), line=19)
        assert vi.identify_vits(field, lines=[19])[19].vits_id == expected


def test_a_level_fault_does_not_hide_the_signal():
    # A decode with a real level error still has to be identified, or the
    # conformance layer never gets to report the error.
    entry = vr.definition("pal-its-field1")
    field = vs.make_field("PAL")
    vs.render_definition(field, entry, luma_gain=0.80)
    found = vi.identify_vits(field, lines=[19])
    assert found[19].vits_id == entry.id


# ---------------------------------------------------------------------------
# Chrominance that has no level to be held to
# ---------------------------------------------------------------------------

#: Definitions whose chrominance rides on a sine-squared pulse, and the
#: element that does.  vits_conformance.py refuses to judge these against
#: their nominal - the window carries the pulse's envelope, not an amplitude
#: (EBU Tech. 3209 7.2.4 c) - so identification cannot hold them to a level
#: either.
PULSE_CHROMA = [
    ("pal-its-field1", "pulse_20t_chroma"),
    ("ntsc-ntc7-composite", "pulse_12t5_chroma"),
]


@pytest.mark.parametrize("vits_id, element_id", PULSE_CHROMA)
def test_a_pulses_chrominance_is_not_held_to_a_level(vits_id, element_id):
    """A 20T pulse reading a tenth of its nominal is still identified.

    The reading this element gives is not an amplitude, and across the
    Domesday captures it lands between 4.9 and 11.4 IRE against a 50 IRE
    nominal on discs whose sustained chrominance bars read 41 to 46 - so a
    fixed IRE floor set to reject a blank line also rejects a real signal.
    That is the level fault hiding itself, which this module exists to
    prevent; it cost DD86-DS2 middle its whole ITS line, and with it the 2T
    pulse deviation that line was the only place to see.
    """
    entry = vr.definition(vits_id)
    field = vs.make_field(entry.system, is_first_field=(entry.field == 1))
    vs.render_definition(field, entry, chroma_gain=0.07)
    geom = vg.FieldGeometry(field, origin_samples=0.0)

    measured = measure_definition(
        field, entry, entry.field_line, geom)[element_id].value
    assert measured < vi.IDENTIFY_CHROMA_PRESENT_IRE, (
        "the point of the test is a reading a fixed floor would reject")

    found = vi.identify_vits(field, geom=geom, lines=[entry.field_line])
    assert found[entry.field_line].vits_id == entry.id


@pytest.mark.parametrize("vits_id, element_id", PULSE_CHROMA)
def test_a_pulse_carrying_no_chrominance_at_all_is_still_rejected(
        vits_id, element_id):
    # Loose against the level, not absent: the element still has to stand
    # clear of what the line reads where the definition says there is none.
    entry = vr.definition(vits_id)
    field = vs.make_field(entry.system, is_first_field=(entry.field == 1))
    vs.render_definition(field, entry, chroma_gain=0.0)
    geom = vg.FieldGeometry(field, origin_samples=0.0)

    score, features = vi.score_definition(geom, entry.field_line, entry)
    assert features["chroma_present"] == 0.0
    assert score == 0.0
    assert entry.field_line not in vi.identify_vits(field, geom=geom)


def test_sustained_chrominance_is_still_held_to_its_level():
    """The relaxation reaches the pulse only, which is what keeps the PAL
    ITS pair apart.

    Line 19 and its field 2 counterpart carry the same bar, 2T pulse and
    staircase and differ in chrominance alone - the counterpart's staircase
    has subcarrier superimposed.  That chrominance is a sustained bar, whose
    reading is an amplitude, so it keeps the level floor: a field 1 line,
    where it is genuinely absent, cannot pass for a field 2 one.
    """
    entry = vr.definition("pal-its-field2")
    field = vs.make_field("PAL", is_first_field=False)
    vs.render_definition(field, entry, chroma_gain=0.09)
    geom = vg.FieldGeometry(field, origin_samples=0.0)

    score, features = vi.score_definition(geom, entry.field_line, entry)
    assert features["chroma_present"] == 0.0
    assert score == 0.0


def test_the_floor_is_the_lines_own_quietest_chrominance_free_window():
    """Not the mean of them, and not the loudest.

    A window a definition states as chrominance-free can still read loud.
    The NTC7 composite's staircase terminus begins where its chrominance
    reference ends and takes 15 IRE of spill from it on every NTSC capture
    in testdata, on a line that is otherwise clean.  Averaging that in, or
    taking it for the floor, would put the threshold above the very signal
    the floor exists to admit.
    """
    entry = vr.definition("ntsc-ntc7-composite")
    pulse = next(e for e in entry.elements if e.id == "pulse_12t5_chroma")
    terminus = next(e for e in entry.elements if e.id == "staircase_terminus")
    field = vs.make_field("NTSC")
    vs.render_definition(field, entry)
    vs.draw_burst(field, entry.field_line, terminus.start_us,
                  terminus.end_us, vr.to_ire(15.0, "NTSC"),
                  field.params.sample_rate_mhz / 4.0)
    geom = vg.FieldGeometry(field, origin_samples=0.0)

    _, loud, _ = geom.demod(entry.field_line,
                            *guarded_window(*terminus.window_us))
    assert loud > vi.IDENTIFY_CHROMA_FLOOR_MIN_IRE, (
        "one window has to be the loud one for this to mean anything")

    # A floor taken from that window would put the threshold above the
    # element's own nominal, so even this conformant rendering would fail it.
    assert (vi.IDENTIFY_PULSE_CHROMA_MARGIN * loud
            > vr.to_ire(pulse.nominal, "NTSC"))
    _, features = vi.score_definition(geom, entry.field_line, entry)
    assert features["chroma_present"] == 1.0


# ---------------------------------------------------------------------------
# A definition whose shape is not there
# ---------------------------------------------------------------------------

def test_a_line_with_plausible_levels_but_the_wrong_shape_is_not_a_match():
    """Levels alone are not identification; the shape has to be there.

    Coherently averaging four fields of moving picture gives a line that is
    flat-ish, carries chrominance everywhere, and averages to a plausible
    level - which matched the PAL chrominance reference at score 1.0 on a
    picture line of a real capture, with an alignment correlation of 0.46
    against 0.98 for the real one on the same field.  Every other feature is
    deliberately loose against levels so a faulty decode is still
    identified; that looseness is paid for by requiring the definition's own
    structure to be locatable.

    The stand-in here is a line split into two levels either side of the
    nominal: its mean is the pedestal the definition states, so the levels
    feature could not reject it, and its shape is not a pedestal at all.
    """
    entry = vr.definition("pal-multiburst-field2")
    line = entry.field_line
    pedestal = vr.to_ire(50.0, "PAL")

    field = vs.make_field(entry.system, is_first_field=False)
    vs.draw_colour_burst(field, line)
    vs.draw_bar(field, line, 12.0, 37.0, vr.to_ire(70.0, "PAL"))
    vs.draw_bar(field, line, 37.0, 62.0, vr.to_ire(30.0, "PAL"))
    vs.draw_burst(field, line, 12.0, 62.0, 7.0,
                  field.params.sample_rate_mhz / 4.0)
    geom = vg.FieldGeometry(field, origin_samples=0.0)

    # The levels feature would have let this through: the line's mean sits
    # on the nominal the definition states.
    mean_ire = float(np.mean(geom.segment(line, 12.0, 62.0))) / \
        field.params.out_scale
    assert abs(mean_ire - pedestal / field.params.out_scale) < \
        vi.IDENTIFY_LEVEL_TOLERANCE_IRE

    score, features = vi.score_definition(geom, line, entry)
    assert features["alignment_correlation"] < vi.TIME_ALIGN_MIN_CORRELATION
    assert score == 0.0
    assert features["reason"] == "definition's shape not found on this line"
    assert line not in vi.identify_vits(field, geom=geom)


def test_the_shape_gate_is_the_threshold_that_already_gates_the_offset():
    # Not a new number: below this correlation vits_measure already refuses
    # to believe the offset it found, so the definition was never located.
    from vits_measure import TIME_ALIGN_MIN_CORRELATION
    assert vi.TIME_ALIGN_MIN_CORRELATION is TIME_ALIGN_MIN_CORRELATION


@pytest.mark.parametrize("entry", MEASURABLE, ids=MEASURABLE_IDS)
def test_a_conformant_rendering_is_located_well_clear_of_the_shape_gate(entry):
    # Real captures correlate 0.77 to 1.00 where the signal is really there;
    # the ghost that prompted the gate reads 0.46.
    _, geom = rendered(entry)
    _, features = vi.score_definition(geom, entry.field_line, entry)
    assert features["alignment_correlation"] > 0.75
