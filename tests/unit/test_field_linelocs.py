"""Unit tests for line-location assembly and repair.

Sync pulses come out of findpulses() as a list of positions; turning that into
one line location per output line -- filling the gaps a dropout left, throwing
out the pulses that landed in the wrong place, and refining what survives
against the 0.5 MHz demodulated sync -- is what decides where every sample of
the output frame comes from.  A one-sample error here is a visible horizontal
shift, so the tests below assert exact positions rather than tolerances
wherever the maths is exact.

The kernel and the refinement are njit'd and take plain arrays, so they are
driven directly.  computeLineLen and fix_badlines are Field methods, driven
from a minimally-constructed Field (see tests/synthetic_field.py).
"""

import numpy as np
import pytest

from lddecode.dsp import compute_linelocs_kernel, refine_hsync_zcs
from lddecode.pulses import Pulse
from synthetic_field import make_field, make_rf, nominal_linelocs

pytestmark = [pytest.mark.unit, pytest.mark.decode]

# A field's worth of geometry, in the units the kernel works in.  line0loc is
# deliberately not 0: the kernel uses "> 0" as its "this line was found"
# sentinel, so a line at the very start of the buffer would read as missing.
LINE0 = 5000.0
MEANLINELEN = 2542.0
INLINELEN = 2542.0
LINECOUNT = 263
PROCLINES = 273
OUTLINECOUNT = 263
TOLERANCE = 0.4

HSYNC, EQPL1, VSYNC, EQPL2 = range(4)


def kernel(
    p_start,
    p_type=None,
    p_valid=None,
    line0loc=LINE0,
    lastlineloc=LINE0 + LINECOUNT * MEANLINELEN,
    skipdetected=False,
    meanlinelen=MEANLINELEN,
):
    """compute_linelocs_kernel with the scalars fixed to one field's geometry."""
    p_start = np.asarray(p_start, dtype=np.float64)
    if p_type is None:
        p_type = np.zeros(len(p_start), dtype=np.int64)
    if p_valid is None:
        p_valid = np.ones(len(p_start), dtype=np.bool_)

    return compute_linelocs_kernel(
        p_start,
        np.asarray(p_type, dtype=np.int64),
        np.asarray(p_valid, dtype=np.bool_),
        float(line0loc),
        float(lastlineloc),
        float(meanlinelen),
        LINECOUNT,
        PROCLINES,
        bool(skipdetected),
        TOLERANCE,
        OUTLINECOUNT,
        INLINELEN,
    )


def perfect_pulses(count=PROCLINES):
    """One hsync per output line, exactly meanlinelen apart."""
    return LINE0 + np.arange(count, dtype=np.float64) * MEANLINELEN


# --- compute_linelocs_kernel: the clean case ----------------------------


def test_a_clean_field_is_returned_unchanged():
    status, linelocs0, filled, err = kernel(perfect_pulses())

    assert status == 0
    assert np.array_equal(linelocs0, perfect_pulses())
    assert np.array_equal(filled, perfect_pulses())
    assert not err.any()


def test_pulses_beyond_the_processed_lines_are_ignored():
    """The read window runs past the end of the field; pulses from the next
    one must not be written into this field's array."""
    extra = np.concatenate(
        [perfect_pulses(), LINE0 + np.arange(PROCLINES, PROCLINES + 20) * MEANLINELEN]
    )
    status, _, filled, err = kernel(extra)

    assert status == 0
    assert len(filled) == PROCLINES
    assert np.array_equal(filled, perfect_pulses())


def test_pulses_before_line_zero_are_ignored():
    early = np.concatenate([[LINE0 - 3 * MEANLINELEN], perfect_pulses()])
    status, _, filled, _ = kernel(early)

    assert status == 0
    assert np.array_equal(filled, perfect_pulses())


# --- compute_linelocs_kernel: gaps --------------------------------------


def test_a_missing_line_is_interpolated_from_its_neighbours():
    pulses = np.delete(perfect_pulses(), 50)
    status, linelocs0, filled, err = kernel(pulses)

    assert status == 0
    assert linelocs0[50] == -1.0           # linelocs0 records what was found
    assert filled[50] == LINE0 + 50 * MEANLINELEN
    assert err[50] and err.sum() == 1


def test_a_run_of_missing_lines_is_interpolated_across_the_whole_gap():
    """The gap is spanned by one average line length taken across it, not by
    repeated extrapolation, so an error does not accumulate along the run."""
    missing = list(range(100, 110))
    pulses = np.delete(perfect_pulses(), missing)
    _, _, filled, err = kernel(pulses)

    assert np.allclose(filled, perfect_pulses())
    assert list(np.where(err)[0]) == missing


def test_a_gap_is_spanned_at_the_measured_rate_not_the_nominal_one():
    """When the disc is running slow the surviving pulses either side set the
    spacing; falling back to inlinelen would drag the repaired lines off."""
    stretched = LINE0 + np.arange(PROCLINES, dtype=np.float64) * (MEANLINELEN + 3)
    pulses = np.delete(stretched, [60, 61])
    _, _, filled, _ = kernel(pulses)

    assert filled[60] == pytest.approx(stretched[60])
    assert filled[61] == pytest.approx(stretched[61])


def test_a_gap_running_to_the_end_extrapolates_at_the_nominal_length():
    """Past the last pulse there is nothing to interpolate between, so the
    nominal line length is the only estimate available."""
    pulses = perfect_pulses()[:200]
    _, _, filled, err = kernel(pulses)

    assert filled[199] == LINE0 + 199 * MEANLINELEN
    assert filled[210] == pytest.approx(filled[199] + 11 * INLINELEN)
    assert err[200:].all()


def test_a_missing_line_zero_is_extrapolated_backwards():
    pulses = perfect_pulses()[3:]
    status, linelocs0, filled, err = kernel(pulses)

    assert status == 0
    assert linelocs0[0] == -1.0
    assert filled[0] == pytest.approx(LINE0)
    # Line 0 is reconstructed but not flagged: rv_err is only written from
    # line 1 on, so the caller's error map does not mark it.
    assert not err[0]


def test_extrapolating_line_zero_off_the_front_of_the_buffer_fails():
    """Backwards extrapolation that lands inside the first line means the
    field started before the data did; status 1 asks the caller to reseek."""
    status, _, _, _ = kernel(perfect_pulses()[3:], line0loc=INLINELEN)

    assert status == 1


def test_a_field_with_no_usable_pulses_fails():
    far_away = LINE0 + np.arange(5) * MEANLINELEN + PROCLINES * MEANLINELEN
    status, _, _, _ = kernel(far_away)

    assert status == 1


# --- compute_linelocs_kernel: rejection ---------------------------------


def test_a_pulse_too_far_from_its_line_is_rejected():
    """Beyond hsync_tolerance of a line boundary a pulse is more likely to be
    equalisation or noise than that line's sync."""
    pulses = perfect_pulses()
    pulses[50] += 0.45 * MEANLINELEN          # 0.45 lines out, tolerance 0.4
    _, linelocs0, filled, err = kernel(pulses)

    assert linelocs0[50] == -1.0
    assert err[50]
    assert filled[50] == pytest.approx(LINE0 + 50 * MEANLINELEN)


def test_a_pulse_just_inside_the_tolerance_is_kept():
    pulses = perfect_pulses()
    pulses[50] += 0.35 * MEANLINELEN
    _, linelocs0, _, err = kernel(pulses)

    assert linelocs0[50] == pulses[50]
    assert not err[50]


def test_the_closest_of_two_candidates_for_a_line_wins():
    """Two pulses can round to the same line (a dropout splitting one sync,
    or a spurious pulse next to a real one); the nearer is the sync."""
    near = LINE0 + 50 * MEANLINELEN + 0.05 * MEANLINELEN
    far = LINE0 + 50 * MEANLINELEN + 0.30 * MEANLINELEN

    # Fed in each order: the winner must be the nearer pulse, not the first
    # or last one the kernel happens to visit.
    for order in ([near, far], [far, near]):
        pulses = np.concatenate([np.delete(perfect_pulses(), 50), order])
        _, linelocs0, _, _ = kernel(pulses)

        assert linelocs0[50] == near


@pytest.mark.parametrize(
    "line, pulse_type, kept",
    [
        (5, HSYNC, False),      # unverified hsync inside the vblank: rejected
        (50, HSYNC, True),      # unverified hsync in the picture: kept
        (50, EQPL1, False),     # unverified equalisation pulse: never kept
        (50, VSYNC, False),
    ],
)
def test_unverified_pulses_are_kept_only_where_an_hsync_is_expected(
    line, pulse_type, kept
):
    """refinepulses() marks a pulse valid when it matched the expected sync
    pattern.  An unverified one is trusted only as an hsync, and only past
    the vblank where the pattern is unambiguous."""
    pulses = perfect_pulses()
    p_type = np.zeros(len(pulses), dtype=np.int64)
    p_valid = np.ones(len(pulses), dtype=np.bool_)
    p_type[line] = pulse_type
    p_valid[line] = False

    _, linelocs0, _, _ = kernel(pulses, p_type=p_type, p_valid=p_valid)

    assert bool(linelocs0[line] == pulses[line]) is kept


def test_line_zero_is_accepted_even_unverified():
    """Line 0 is the anchor the rest of the field is measured from, and
    getLine0 has already established it."""
    pulses = perfect_pulses()
    p_valid = np.ones(len(pulses), dtype=np.bool_)
    p_valid[0] = False

    _, linelocs0, _, _ = kernel(pulses, p_valid=p_valid)

    assert linelocs0[0] == pulses[0]


# --- compute_linelocs_kernel: skip detection ----------------------------


def test_a_detected_skip_measures_late_lines_from_the_end_of_the_field():
    """When lines are missing the start anchor drifts, but the end of the
    field is still where the next vsync says it is.  With skipdetected the
    kernel prefers whichever anchor puts the pulse closer to a line."""
    # end anchor 0.3 lines further out, so lineloc_end = lineloc - 0.3
    lastlineloc = LINE0 + (LINECOUNT + 0.3) * MEANLINELEN
    pulses = perfect_pulses()
    pulses[50] += 0.45 * MEANLINELEN

    _, without, _, _ = kernel(pulses, lastlineloc=lastlineloc, skipdetected=False)
    _, with_skip, _, _ = kernel(pulses, lastlineloc=lastlineloc, skipdetected=True)

    assert without[50] == -1.0              # 0.45 out, beyond the tolerance
    assert with_skip[50] == pulses[50]      # 0.15 out from the end anchor


def test_the_end_anchor_is_not_used_inside_the_vblank():
    """Lines up to 23 are the vertical interval, whose pulse pattern the
    start anchor was derived from; re-measuring them from the end would
    undo that."""
    lastlineloc = LINE0 + (LINECOUNT + 0.3) * MEANLINELEN
    pulses = perfect_pulses()
    pulses[20] += 0.45 * MEANLINELEN

    _, linelocs0, _, _ = kernel(pulses, lastlineloc=lastlineloc, skipdetected=True)

    assert linelocs0[20] == -1.0


# --- refine_hsync_zcs ---------------------------------------------------

RAMP_US = 0.2       # sync edge transition time; real captures are ~0.14 us
SYNC_US = 4.7


@pytest.fixture(scope="module")
def rfs():
    return {system: make_rf(system) for system in ("NTSC", "PAL")}


def sync_waveform(rf, linelocs, ire0=0.0):
    """A 0.5 MHz-demodulated field: blanking with one sync pulse per line.

    The falling edge is a linear ramp centred on the line location, so the
    half-amplitude crossing refine_hsync_zcs looks for is at the line
    location exactly and the recovered value can be asserted to float
    precision rather than to a tolerance.
    """
    blank = rf.iretohz(ire0)
    sync = rf.iretohz(rf.DecoderParams["vsync_ire"])

    length = int(linelocs[-1] + 10 * rf.linelen)
    data = np.full(length, blank, dtype=np.float64)

    ramp = RAMP_US * rf.freq
    width = SYNC_US * rf.freq
    n = np.arange(length, dtype=np.float64)
    for loc in linelocs:
        fall = np.clip(0.5 - (n - loc) / ramp, 0.0, 1.0)
        rise = np.clip(0.5 + (n - (loc + width)) / ramp, 0.0, 1.0)
        level = np.maximum(fall, rise)
        inside = (n > loc - ramp) & (n < loc + width + ramp)
        data[inside] = (blank * level + sync * (1 - level))[inside]

    return data


def refine(rf, data, linelocs1, linebad=None):
    linelocs1 = np.asarray(linelocs1, dtype=np.float64)
    if linebad is None:
        linebad = np.zeros(len(linelocs1), dtype=np.bool_)
    out = refine_hsync_zcs(
        np.ascontiguousarray(data),
        linelocs1,
        linebad,
        len(linelocs1),
        rf.system == "PAL",
        float(rf.freq),
        float(rf.iretohz(rf.DecoderParams["vsync_ire"] / 2)),
        float(rf.iretohz(-55)),
        float(rf.iretohz(30)),
    )
    return out, linebad


@pytest.mark.parametrize("system", ["NTSC", "PAL"])
@pytest.mark.parametrize("offset", [-8.0, -0.5, 0.0, 0.5, 8.0])
def test_refinement_pulls_a_line_onto_the_sync_edge(rfs, system, offset):
    """The incoming line locs are whole-sample pulse starts; refinement
    replaces them with the sub-sample position of the half-sync crossing."""
    rf = rfs[system]
    truth = nominal_linelocs(rf, 40, first=10 * rf.linelen)
    data = sync_waveform(rf, truth)

    refined, linebad = refine(rf, data, truth + offset)

    good = [i for i in range(10, 40)]
    assert np.allclose(refined[good], truth[good], atol=1e-6)
    assert not linebad[good].any()


@pytest.mark.parametrize("system, expected", [("NTSC", [3, 4, 5, 6]),
                                              ("PAL", [1, 2, 3, 4, 5, 6])])
def test_the_vsync_lines_are_never_refined(rfs, system, expected):
    """Lines 3-6 are inside the vertical sync block (PAL's field parity adds
    1-2), where there is no hsync edge to measure against; they keep the
    position the kernel gave them and are marked bad."""
    rf = rfs[system]
    truth = nominal_linelocs(rf, 40, first=10 * rf.linelen)
    data = sync_waveform(rf, truth)

    refined, linebad = refine(rf, data, truth + 5.0)

    assert list(np.where(linebad)[0]) == expected
    assert np.array_equal(refined[expected], (truth + 5.0)[expected])


def test_a_line_with_signal_in_the_sync_area_is_rejected(rfs):
    """Video where sync should be means the edge was not sync at all; the
    line reverts to its unrefined position rather than locking onto noise."""
    rf = rfs["NTSC"]
    truth = nominal_linelocs(rf, 40, first=10 * rf.linelen)
    data = sync_waveform(rf, truth)
    # A spike well above 30 IRE just after line 20's sync
    start = int(truth[20] + 2 * rf.freq)
    data[start: start + 10] = rf.iretohz(80)

    refined, linebad = refine(rf, data, truth + 3.0)

    assert linebad[20]
    assert refined[20] == truth[20] + 3.0
    assert refined[21] == pytest.approx(truth[21], abs=1e-6)


def test_a_line_already_marked_bad_is_left_alone(rfs):
    """linebad carries forward from the kernel's error map; a line it could
    not place is not going to be refined into place either."""
    rf = rfs["NTSC"]
    truth = nominal_linelocs(rf, 40, first=10 * rf.linelen)
    data = sync_waveform(rf, truth)

    linebad = np.zeros(40, dtype=np.bool_)
    linebad[20] = True
    refined, _ = refine(rf, data, truth + 3.0, linebad)

    assert refined[20] == truth[20] + 3.0


def test_refinement_is_independent_of_the_blanking_level(rfs):
    """The second pass measures the porch and the sync tip and crosses at
    their midpoint, so a field sitting at a different black level refines to
    the same place."""
    rf = rfs["NTSC"]
    truth = nominal_linelocs(rf, 40, first=10 * rf.linelen)

    at_zero, _ = refine(rf, sync_waveform(rf, truth), truth + 4.0)
    lifted, _ = refine(rf, sync_waveform(rf, truth, ire0=10.0), truth + 4.0)

    assert np.allclose(at_zero[10:], lifted[10:], atol=1e-6)


# --- computeLineLen -----------------------------------------------------


def validpulses(types, spacing, start=LINE0):
    """(type, Pulse, valid) triples, `spacing` samples apart in turn."""
    out = []
    pos = start
    for i, t in enumerate(types):
        out.append((t, Pulse(pos, 100), True))
        pos += spacing[i] if i < len(spacing) else 0
    return out


@pytest.fixture(scope="module")
def ntsc_field(rfs):
    return make_field(rfs["NTSC"])


def test_line_length_is_the_mean_over_the_longest_run_of_hsyncs(ntsc_field):
    linelen = ntsc_field.inlinelen
    pulses = validpulses([HSYNC] * 12, [linelen + 4] * 11)

    assert ntsc_field.computeLineLen(pulses) == pytest.approx(linelen + 4)


def test_the_vblank_pulses_are_not_measured(ntsc_field):
    """Equalisation and vsync pulses come twice a line; averaging them in
    would halve the estimate.  The longest run of plain hsyncs wins."""
    linelen = ntsc_field.inlinelen
    types = [EQPL1] * 6 + [VSYNC] * 6 + [EQPL2] * 6 + [HSYNC] * 12
    spacing = [linelen / 2] * 17 + [linelen] * 11

    assert ntsc_field.computeLineLen(validpulses(types, spacing)) == pytest.approx(linelen)


def test_a_gap_that_is_not_a_line_is_excluded(ntsc_field):
    """A dropout swallows a sync, leaving a double-length gap; including it
    would bias the mean upwards for the whole field."""
    linelen = ntsc_field.inlinelen
    spacing = [linelen] * 5 + [2 * linelen] + [linelen] * 6
    result = ntsc_field.computeLineLen(validpulses([HSYNC] * 13, spacing))

    assert result == pytest.approx(linelen)


def test_the_final_gap_of_a_run_is_not_measured(ntsc_field):
    """A quirk of the run bookkeeping: a run of n hsyncs contributes n-2
    gaps, not n-1.  Harmless to the mean, but pinned so that tightening the
    loop does not silently change the estimate on short runs."""
    linelen = ntsc_field.inlinelen
    spacing = [linelen] * 9 + [linelen * 1.04]
    result = ntsc_field.computeLineLen(validpulses([HSYNC] * 11, spacing))

    assert result == pytest.approx(linelen)


def test_no_measurable_run_falls_back_to_the_nominal_length(ntsc_field):
    assert ntsc_field.computeLineLen([]) == ntsc_field.inlinelen

    only_vblank = validpulses([EQPL1] * 8, [ntsc_field.inlinelen / 2] * 7)
    assert ntsc_field.computeLineLen(only_vblank) == ntsc_field.inlinelen


# --- compute_deriv_error and fix_badlines -------------------------------


def test_evenly_spaced_lines_have_no_derivative_error(ntsc_field, rfs):
    linelocs = nominal_linelocs(rfs["NTSC"], 100)
    base = np.zeros(100, dtype=bool)

    assert not ntsc_field.compute_deriv_error(linelocs, base).any()


def test_a_step_in_line_length_flags_the_lines_around_it(ntsc_field, rfs):
    """One displaced line makes three consecutive second differences nonzero,
    and each is reported against two lines (derr1 and derr2 are the same test
    read one line apart), so the flag spreads a line either side.  The repair
    then interpolates across the whole group rather than trusting a line whose
    position was only measured relative to a bad one."""
    linelocs = nominal_linelocs(rfs["NTSC"], 100)
    linelocs[50] += 20.0
    base = np.zeros(100, dtype=bool)

    assert list(np.where(ntsc_field.compute_deriv_error(linelocs, base))[0]) == [
        49, 50, 51, 52
    ]


def test_the_derivative_error_is_added_to_what_is_already_known(ntsc_field, rfs):
    linelocs = nominal_linelocs(rfs["NTSC"], 100)
    base = np.zeros(100, dtype=bool)
    base[10] = True

    assert ntsc_field.compute_deriv_error(linelocs, base)[10]


def test_fix_badlines_leaves_a_clean_field_alone(rfs):
    field = make_field(rfs["NTSC"])
    linelocs = nominal_linelocs(rfs["NTSC"], 100)
    field.linebad = np.zeros(100, dtype=bool)

    assert np.array_equal(field.fix_badlines(linelocs), linelocs)


def test_fix_badlines_interpolates_a_marked_line(rfs):
    field = make_field(rfs["NTSC"])
    linelocs = nominal_linelocs(rfs["NTSC"], 100)
    truth = linelocs.copy()
    linelocs[50] += 500.0            # far enough out to be visibly wrong
    field.linebad = np.zeros(100, dtype=bool)
    field.linebad[50] = True

    fixed = field.fix_badlines(linelocs)

    assert fixed[50] == pytest.approx(truth[50])
    assert np.array_equal(fixed[:50], truth[:50])


def test_fix_badlines_spans_a_run_of_marked_lines(rfs):
    field = make_field(rfs["NTSC"])
    linelocs = nominal_linelocs(rfs["NTSC"], 100)
    truth = linelocs.copy()
    linelocs[40:45] += 300.0
    field.linebad = np.zeros(100, dtype=bool)
    field.linebad[40:45] = True

    fixed = field.fix_badlines(linelocs)

    assert np.allclose(fixed[40:45], truth[40:45])


def test_fix_badlines_falls_back_to_the_backup_for_a_nan(rfs):
    """refine_linelocs_burst can leave a NaN where a line had no burst; the
    previous refinement stage's value stands in before interpolation."""
    field = make_field(rfs["NTSC"])
    backup = nominal_linelocs(rfs["NTSC"], 100)
    linelocs = backup.copy()
    linelocs[60] = np.nan
    field.linebad = np.zeros(100, dtype=bool)

    fixed = field.fix_badlines(linelocs, backup)

    assert fixed[60] == backup[60]


@pytest.mark.parametrize("system, fixed_expected", [("NTSC", False), ("PAL", True)])
def test_line_one_is_repairable_only_on_pal(rfs, system, fixed_expected):
    """NTSC's line 0 is a vsync line whose position is not a line length from
    line 1, so it is not a usable anchor; PAL's field offset means line 0 is
    an ordinary line and can be interpolated from."""
    field = make_field(rfs[system])
    linelocs = nominal_linelocs(rfs[system], 100)
    truth = linelocs.copy()
    linelocs[1] += 400.0
    field.linebad = np.zeros(100, dtype=bool)
    field.linebad[1] = True

    fixed = field.fix_badlines(linelocs)

    assert bool(fixed[1] == pytest.approx(truth[1])) is fixed_expected
