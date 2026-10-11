"""Unit tests for the whole-field burst loops behind FieldNTSC's burst
refinement and Field.calc_burstmedian.

ntsc_line_bursts and burst_levels run compute_line_bursts and
get_burstlevel over every line of a field in one compiled loop.  Both
per-line methods are still on Field, so they are the reference here: on
synthetic fields with wow, jitter and the awkward lines a real field has
(off either end of the buffer, rejected bursts, crossed line locations),
the loops must agree with them exactly.  refine_linelocs_burst is checked
the same way against the per-line loop it replaced.
"""

import numpy as np
import pytest

from lddecode.filters import inrange
from lddecode.pulses import burst_levels, ntsc_line_bursts
from synthetic_field import make_field, make_rf

pytestmark = [pytest.mark.unit, pytest.mark.decode]

NLINES = 266


@pytest.fixture(scope="module")
def rfs():
    return {system: make_rf(system) for system in ("NTSC", "PAL")}


def burst_field(rf, seed, first=3000.0, count=280, tail=3000, **kwargs):
    """A field of blanking-level lines carrying a colour burst, with wow
    and jitter on the line locations and noise on the signal."""
    rng = np.random.default_rng(seed)
    linelen = rf.linelen * (1 + 2e-4 * rng.standard_normal())
    lines = np.arange(count, dtype=np.float64)
    linelocs = (first + lines * linelen + 6.0 * np.sin(lines / 30.0)
                + rng.normal(0.0, 0.3, count))

    n = int(linelocs[-1]) + tail
    fsc = rf.SysParams["fsc_mhz"]
    hz_ire = rf.DecoderParams["hz_ire"]
    t = np.arange(n, dtype=np.float64)
    phase = 2 * np.pi * fsc * t / rf.freq
    signal = np.full(n, rf.iretohz(0), dtype=np.float64)
    for line, loc in enumerate(linelocs):
        b0, b1 = int(loc + 5.0 * rf.freq), int(loc + 8.6 * rf.freq)
        if 0 <= b0 < n:
            # NTSC's burst inverts on alternate lines
            signal[b0:b1] += 20 * hz_ire * np.sin(
                phase[b0:b1] + np.pi * (line % 2) + rng.normal(0, 0.05))
    signal += rng.normal(0.0, 0.5 * hz_ire, n)

    names = ["demod", "demod_raw", "demod_05", "demod_burst"]
    video = np.recarray(n, dtype=[(name, np.float32) for name in names])
    for name in names:
        video[name] = signal
    field = make_field(rf, linelocs=linelocs, **kwargs)
    # a record array, as demodblock lays it out, so each channel is a
    # strided view
    field.data["video"] = video
    field.anchor = None
    return field


def per_line(field, linelocs, prev):
    """compute_line_bursts for every line, as arrays."""
    measured = np.zeros(NLINES, dtype=bool)
    rising = np.zeros(NLINES, dtype=bool)
    phase = np.zeros(NLINES)
    for line in range(NLINES):
        r, p = field.compute_line_bursts(linelocs, line, prev)
        if r is not None:
            measured[line], rising[line], phase[line] = True, r, p
    return measured, rising, phase


def compiled(field, linelocs, prev):
    rf = field.rf
    return ntsc_line_bursts(
        field.data["video"]["demod_burst"], field.data["video"]["demod"],
        np.asarray(linelocs, dtype=np.float64), field.linelocs, NLINES,
        field.lineoffset, field.linecount + field.lineoffset, rf.linelen,
        rf.samplesperline, rf.SysParams["fsc_mhz"],
        30 * rf.DecoderParams["hz_ire"], float(prev),
    )


def assert_same_bursts(got, want):
    for g, w in zip(got, want):
        np.testing.assert_array_equal(np.asarray(g), np.asarray(w))
    # bit for bit, signed zeros aside
    np.testing.assert_array_equal(got[2] + 0.0, want[2] + 0.0)


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("prev", [0, 0.37, -1.25])
def test_line_bursts_match_compute_line_bursts(rfs, seed, prev):
    field = burst_field(rfs["NTSC"], seed)
    want = per_line(field, field.linelocs, prev)
    assert want[0].sum() > 250

    assert_same_bursts(compiled(field, field.linelocs, prev), want)


def test_line_bursts_off_either_end_of_the_buffer(rfs):
    """A first line located before sample 0 slices from the end of the
    buffer, Python-style, and lines past the end slice nothing."""
    field = burst_field(rfs["NTSC"], 4, first=-200.0, tail=-60000)
    want = per_line(field, field.linelocs, 0.2)
    assert not want[0][-10:].any()

    assert_same_bursts(compiled(field, field.linelocs, 0.2), want)


def test_line_bursts_reject_a_swinging_burst_area(rfs):
    field = burst_field(rfs["NTSC"], 5)
    hz_ire = field.rf.DecoderParams["hz_ire"]
    for line in (20, 21, 140):
        at = int(field.linelocs[line] + 6.5 * field.rf.freq)
        field.data["video"]["demod"][at] += 80 * hz_ire
    want = per_line(field, field.linelocs, 0)
    assert not want[0][[20, 21, 140]].any()

    assert_same_bursts(compiled(field, field.linelocs, 0), want)


def test_line_bursts_with_crossed_line_locations(rfs):
    """Lines whose neighbours cross measure at the nominal line length."""
    field = burst_field(rfs["NTSC"], 6)
    field.linelocs[50], field.linelocs[52] = field.linelocs[52], field.linelocs[50]
    burst_locs = field.linelocs.copy()

    assert_same_bursts(compiled(field, burst_locs, 0),
                       per_line(field, burst_locs, 0))


def test_line_bursts_on_too_few_line_locations_go_line_by_line(rfs):
    """The last lines measure from the line before alone, so a field one
    location short of the compiled loop's range still measures."""
    field = burst_field(rfs["NTSC"], 7, count=NLINES)
    want = per_line(field, field.linelocs, 0)

    assert_same_bursts(field.line_bursts(field.linelocs, NLINES, 0), want)


# --- refine_linelocs_burst ----------------------------------------------


def refine_by_line(field, linelocs):
    """refine_linelocs_burst as a loop over compute_line_bursts."""
    prev = field.phase_adjust_median
    if prev == 0 and field.anchor is not None:
        prev = field.anchor.phase_adjust_median
    rising_sum, adjs_new = 0, {}
    for line in range(NLINES):
        rising, phase_adjust = field.compute_line_bursts(linelocs, line, prev)
        if rising is not None:
            adjs_new[line] = phase_adjust / 2
            rising_sum += 1 if (line % 2 == 0 and rising) else 0
    field14 = rising_sum > (len(adjs_new) // 4)
    field.phase_adjust_median = (np.median(list(adjs_new.values())) * 2
                                 if adjs_new else prev)

    linelocs_adj = linelocs.copy()
    for line in range(1, NLINES):
        if line not in adjs_new:
            field.linebad[line] = True
    adjs = {}
    for line in range(NLINES):
        if not (np.isnan(linelocs_adj[line]) or field.linebad[line]) and line in adjs_new:
            adjs[line] = (adjs_new[line] * field.get_linefreq(line, linelocs)
                          * (1 / field.rf.SysParams["fsc_mhz"]))
    if not adjs:
        return linelocs_adj, 1, 0
    median = np.median(list(adjs.values()))
    last, outliers = median, 0
    for line in range(NLINES):
        if line in adjs and inrange(adjs[line] - median, -2, 2):
            linelocs_adj[line] += adjs[line]
            last = adjs[line]
        else:
            linelocs_adj[line] += last
            outliers += line in adjs
    return linelocs_adj, {(True, True): 1, (False, False): 2,
                          (True, False): 3, (False, True): 4}[(field.isFirstField, field14)], outliers


@pytest.mark.parametrize("seed, first_field", [(8, True), (9, False)])
def test_refine_linelocs_burst_matches_the_line_by_line_refinement(rfs, seed, first_field):
    field = burst_field(rfs["NTSC"], seed, is_first_field=first_field)
    # lines already known bad, a line with no burst, and a run of lines
    # whose burst is a quarter cycle out, which the outlier test passes over
    field.linebad[[30, 31, 200]] = True
    loc = field.linelocs[90]
    field.data["video"]["demod_burst"][int(loc):int(loc + 9 * field.rf.freq)] = \
        field.rf.iretohz(0)
    shift = int(0.25 * field.rf.freq / field.rf.SysParams["fsc_mhz"])
    for name in ("demod", "demod_burst"):
        seg = field.data["video"][name][int(loc + 4 * field.rf.freq):int(field.linelocs[121])]
        seg[:] = np.roll(seg, shift)
    field.phase_adjust_median = 0.21

    ref = burst_field(rfs["NTSC"], seed, is_first_field=first_field)
    ref.data = field.data
    ref.linebad = field.linebad.copy()
    ref.phase_adjust_median = field.phase_adjust_median
    want, want_id, outliers = refine_by_line(ref, field.linelocs)
    assert outliers > 10

    got = field.refine_linelocs_burst(field.linelocs)

    np.testing.assert_array_equal(got, want)
    np.testing.assert_array_equal(field.linebad, ref.linebad)
    assert field.fieldPhaseID == want_id
    assert field.phase_adjust_median == ref.phase_adjust_median


def test_a_field_without_burst_keeps_its_seed_and_falls_back(rfs):
    field = burst_field(rfs["NTSC"], 10)
    # a picture swinging far past any burst under every burst window
    demod = field.data["video"]["demod"]
    demod[(np.arange(len(demod)) // 50) % 2 == 1] += 80 * field.rf.DecoderParams["hz_ire"]
    field.phase_adjust_median = 0.4

    got = field.refine_linelocs_burst(field.linelocs)

    assert field.fieldPhaseID == 1 and field.phase_id_fallback
    assert field.phase_adjust_median == 0.4
    assert field.linebad[1:NLINES].all()
    np.testing.assert_array_equal(got, field.linelocs)


def test_get_linelens_matches_get_linelen(rfs):
    field = burst_field(rfs["NTSC"], 11)
    field.linelocs[40] = field.linelocs[38]       # crossed: nominal length
    lines = np.arange(len(field.linelocs) - 1)

    want = [field.get_linelen(line, field.linelocs) for line in lines]
    np.testing.assert_array_equal(field.get_linelens(lines, field.linelocs), want)


# --- burst_levels / calc_burstmedian ------------------------------------


def levels(field):
    rf = field.rf
    hz_ire = rf.DecoderParams["hz_ire"]
    limit = np.inf if field.burst_max_ire is None else field.burst_max_ire * hz_ire
    return burst_levels(
        field.data["video"]["demod"], field.linelocs, 0, len(field.linelocs) + 5,
        field.lineoffset, field.linecount + field.lineoffset, rf.linelen,
        rf.samplesperline, 5.5, 2.4, np.float32(limit),
    )


def levels_by_line(field):
    out = [field.get_burstlevel(line) for line in range(len(field.linelocs) + 5)]
    return (np.array([0.0 if v is None else v for v in out]),
            np.array([v is not None for v in out]))


@pytest.mark.parametrize("system", ["NTSC", "PAL"])
def test_burst_levels_match_get_burstlevel(rfs, system):
    """Including the lines past the end of linelocs, where get_burstlevel
    fails to index and returns None."""
    field = burst_field(rfs[system], 12)
    want = levels_by_line(field)
    assert want[1].sum() > 250 and not want[1][-5:].any()

    got = levels(field)
    np.testing.assert_array_equal(got[1], want[1])
    np.testing.assert_array_equal(got[0], want[0])


@pytest.mark.parametrize("system", ["NTSC", "PAL"])
def test_burst_levels_at_the_buffer_edges_and_on_bad_samples(rfs, system):
    """A window before sample 0 wraps, windows past the end are empty, a
    NaN burst gives a NaN level rather than none, and on PAL a burst
    peaking over 30 IRE is not measured."""
    field = burst_field(rfs[system], 13, first=-500.0, tail=-80000)
    demod = field.data["video"]["demod"]
    hz_ire = field.rf.DecoderParams["hz_ire"]
    at = int(field.linelocs[60] + 6.0 * field.rf.freq)
    demod[at] = np.nan
    at = int(field.linelocs[100] + 6.0 * field.rf.freq)
    demod[at] += 35 * hz_ire
    want = levels_by_line(field)
    assert np.isnan(want[0]).any()

    got = levels(field)
    np.testing.assert_array_equal(got[1], want[1])
    np.testing.assert_array_equal(got[0], want[0])


@pytest.mark.parametrize("system", ["NTSC", "PAL"])
def test_calc_burstmedian_is_the_median_of_the_measured_levels(rfs, system):
    field = burst_field(rfs[system], 14)
    lines = range(*field.burst_lines)
    measured = [b for b in (field.get_burstlevel(line) for line in lines) if b is not None]

    assert field.calc_burstmedian() == np.median(measured) / field.rf.DecoderParams["hz_ire"]
    # the 20 IRE burst, as a peak level
    assert field.calc_burstmedian() == pytest.approx(20, rel=0.05)
