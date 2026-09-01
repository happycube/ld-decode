"""Unit tests for the coordinate maths on Field.

Every conversion between microseconds, input samples, output samples, Hz and
IRE lives on Field, and everything downstream -- VITS measurement, dropout
extents, the TBC output itself -- is expressed in terms of them.  They are
pure functions of SysParams/DecoderParams plus the field's line locations, so
they are driven here from a minimally-constructed Field (see
tests/synthetic_field.py) rather than a decoded one.

Two families of unit exist and must not be confused: *input* pixels are RF
samples, whose spacing follows the disc's actual line length and therefore
wow; *output* pixels are TBC samples at a fixed 4x fSC and never move.  The
tests below assert that split holds -- usectoinpx() tracks a stretched line
and usectooutpx() does not.
"""

import numpy as np
import pytest

from synthetic_field import make_field, make_rf, nominal_linelocs

pytestmark = [pytest.mark.unit, pytest.mark.decode]

SYSTEMS = ["NTSC", "PAL"]


@pytest.fixture(scope="module")
def rfs():
    return {system: make_rf(system) for system in SYSTEMS}


@pytest.fixture
def rf(rfs, request):
    return rfs[request.param]


@pytest.fixture
def field(rf):
    return make_field(rf)


parametrize_system = pytest.mark.parametrize("rf", SYSTEMS, indirect=True)


def field_offset(rf):
    """The lineoffset make_field() picks for a first field of this system."""
    return 0 if rf.system == "NTSC" else 2


# --- microseconds <-> input samples -------------------------------------


@parametrize_system
def test_usectoinpx_is_the_sample_rate_when_there_is_no_wow(field, rf):
    """With evenly spaced lines a microsecond is exactly `freq` samples."""
    assert field.usectoinpx(1.0, 10) == rf.freq
    assert field.usectoinpx(4.7, 10) == 4.7 * rf.freq


@parametrize_system
def test_usectoinpx_and_inpxtousec_are_inverses(field):
    for x in (0.0, 0.1, 4.7, 63.555, 1000.0):
        assert field.inpxtousec(field.usectoinpx(x, 10), 10) == pytest.approx(x)


@parametrize_system
def test_a_line_period_is_one_line_of_input_samples(field, rf):
    """rf.linelen is the same quantity rounded to a whole sample."""
    period = rf.SysParams["line_period"]
    assert abs(field.usectoinpx(period, 10) - rf.linelen) < 0.5


@parametrize_system
def test_usectoinpx_tracks_a_stretched_line(rf):
    """Wow: a line 1% longer holds 1% more samples per microsecond.

    This is the whole reason the conversion takes a line number.  Reading a
    fixed number of samples per microsecond off a wowed line would walk the
    measurement slices out of the features they are aimed at.
    """
    stretched = make_field(
        rf, linelocs=nominal_linelocs(rf, 320, linelen=rf.linelen * 1.01)
    )
    assert stretched.usectoinpx(1.0, 10) == pytest.approx(rf.freq * 1.01)


@parametrize_system
def test_get_linelen_uses_the_neighbours_of_an_interior_line(rf):
    """An interior line's length is the half-distance across its neighbours,
    so a single misplaced line loc only half-affects the line either side."""
    linelocs = nominal_linelocs(rf, 320)
    linelocs[10] += 100.0  # displace one line, leaving 9 and 11 alone
    field = make_field(rf, linelocs=linelocs)

    assert field.get_linelen(10) == rf.linelen        # neighbours unaffected
    assert field.get_linelen(9) == rf.linelen + 50.0
    assert field.get_linelen(11) == rf.linelen - 50.0


@parametrize_system
def test_get_linelen_at_the_first_and_last_line(rf):
    """The ends have no pair of neighbours, so they use the one gap they have."""
    linelocs = nominal_linelocs(rf, 320)
    linelocs[1] += 30.0
    last = 262 if rf.system == "NTSC" else 315
    linelocs[last] += 70.0
    field = make_field(rf, linelocs=linelocs, linecount=last - field_offset(rf))

    assert field.get_linelen(0) == rf.linelen + 30.0
    assert field.get_linelen(last) == rf.linelen + 70.0



@parametrize_system
def test_non_monotonic_linelocs_fall_back_to_the_nominal_length(rf):
    """A TBC failure can leave line locs out of order; a negative length
    would otherwise turn into a negative sample rate."""
    linelocs = nominal_linelocs(rf, 320)
    linelocs[11] = linelocs[9] - 1.0
    field = make_field(rf, linelocs=linelocs)

    assert field.get_linelen(10) == rf.linelen
    assert field.usectoinpx(1.0, 10) == rf.freq


@parametrize_system
def test_get_linelen_without_a_line_number_is_the_nominal_length(field, rf):
    assert field.get_linelen() == rf.linelen
    assert field.get_linefreq() == pytest.approx(rf.freq)


# --- microseconds <-> output samples ------------------------------------


@parametrize_system
def test_usectooutpx_is_the_output_sample_rate(field, rf):
    assert field.usectooutpx(1.0) == rf.SysParams["outfreq"]
    assert field.outpxtousec(field.usectooutpx(12.5)) == pytest.approx(12.5)


@parametrize_system
def test_a_line_period_is_one_line_of_output_samples(field, rf):
    """outlinelen is fixed by the standard, so this is a consistency check on
    the SysParams table rather than on the conversion."""
    period = rf.SysParams["line_period"]
    assert field.usectooutpx(period) == pytest.approx(rf.SysParams["outlinelen"], abs=0.01)


@parametrize_system
def test_output_pixels_do_not_move_with_wow(rf):
    """The output time base is the point of time-base correction: unlike
    usectoinpx(), this conversion must ignore the line locs entirely."""
    stretched = make_field(
        rf, linelocs=nominal_linelocs(rf, 320, linelen=rf.linelen * 1.01)
    )
    assert stretched.usectooutpx(1.0) == rf.SysParams["outfreq"]


# --- lineslice (pre-TBC) ------------------------------------------------


@parametrize_system
def test_lineslice_starts_at_the_line_loc(field):
    for line in (0, 1, 100):
        assert field.lineslice(line).start == int(field.linelocs[line + field.lineoffset])


@parametrize_system
def test_lineslice_defaults_to_a_whole_line(field, rf):
    """The default length is one line period, and the stop is one sample past
    it -- the slice is inclusive of the sample at `begin + length`."""
    sl = field.lineslice(10)
    assert sl.stop - sl.start == int(rf.SysParams["line_period"] * rf.freq) + 1


@parametrize_system
def test_lineslice_offsets_by_microseconds(field, rf):
    """5.5 us in, 2.4 us long: the burst window get_burstlevel() uses."""
    sl = field.lineslice(10, 5.5, 2.4)
    base = field.linelocs[10 + field.lineoffset]

    assert sl.start == int(base + 5.5 * rf.freq)
    assert sl.stop == int(base + 5.5 * rf.freq + 2.4 * rf.freq + 1)


@parametrize_system
def test_lineslice_begin_offset_shifts_both_ends(field):
    plain = field.lineslice(10, 5.5, 2.4)
    shifted = field.lineslice(10, 5.5, 2.4, begin_offset=17)

    assert shifted.start == plain.start + 17
    assert shifted.stop == plain.stop + 17


@parametrize_system
def test_lineslice_honours_lineoffset(rf):
    """PAL's two field parities put field line 0 at a different sync pulse;
    lineoffset is what keeps `line` meaning the same picture line in both."""
    linelocs = nominal_linelocs(rf, 320)
    first = make_field(rf, linelocs=linelocs, lineoffset=2)
    second = make_field(rf, linelocs=linelocs, lineoffset=3)

    assert second.lineslice(10).start - first.lineslice(10).start == int(rf.linelen)


@parametrize_system
def test_lineslice_takes_explicit_linelocs(field, rf):
    """refine_linelocs_* passes a candidate array in before committing it."""
    candidate = nominal_linelocs(rf, 320) + 500.0
    assert field.lineslice(10, linelocs=candidate).start == int(candidate[10 + field.lineoffset])


@parametrize_system
def test_lineslice_widens_on_a_stretched_line(rf):
    """The slice is in microseconds, so on a longer line it covers more
    samples -- and still lands on the same part of the picture."""
    stretched = make_field(
        rf, linelocs=nominal_linelocs(rf, 320, linelen=rf.linelen * 1.01)
    )
    nominal = make_field(rf)

    width = lambda f: f.lineslice(10, 5.5, 2.4).stop - f.lineslice(10, 5.5, 2.4).start
    assert width(stretched) == pytest.approx(width(nominal) * 1.01, abs=1)


# --- lineslice_tbc (post-TBC) -------------------------------------------


@parametrize_system
def test_lineslice_tbc_counts_lines_from_one(field, rf):
    """Line 1 is the start of the buffer; every line is outlinelen apart."""
    outlinelen = rf.SysParams["outlinelen"]

    assert field.lineslice_tbc(1).start == 0
    assert field.lineslice_tbc(1).stop == outlinelen
    assert field.lineslice_tbc(19).start == outlinelen * 18


@parametrize_system
def test_lineslice_tbc_is_independent_of_the_line_locs(rf):
    """Post-TBC the wow is gone by construction, so nothing here may consult
    linelocs -- otherwise a measurement slice would move with the input."""
    stretched = make_field(
        rf, linelocs=nominal_linelocs(rf, 320, linelen=rf.linelen * 1.01)
    )
    nominal = make_field(rf)

    assert stretched.lineslice_tbc(19, 14, 18) == nominal.lineslice_tbc(19, 14, 18)


@parametrize_system
def test_lineslice_tbc_offsets_by_microseconds(field, rf):
    outlinelen = rf.SysParams["outlinelen"]
    outfreq = rf.SysParams["outfreq"]
    sl = field.lineslice_tbc(19, 14, 18)

    assert sl.start == round(outlinelen * 18 + 14 * outfreq)
    assert sl.stop == round(outlinelen * 18 + 14 * outfreq + 18 * outfreq)


@parametrize_system
def test_lineslice_tbc_keepphase_quantises_to_a_subcarrier_cycle(field, rf):
    """The output is sampled at 4x fSC, so rounding the offset down to a
    multiple of 4 keeps the slice starting on the same subcarrier phase --
    which is what makes a chroma measurement across lines comparable."""
    outfreq = rf.SysParams["outfreq"]
    for begin in (5.0, 14.0, 23.7):
        plain = field.lineslice_tbc(19, begin, 4).start
        phased = field.lineslice_tbc(19, begin, 4, keepphase=True).start

        offset = int(begin * outfreq)
        assert (phased - field.lineslice_tbc(19).start) % 4 == 0
        assert 0 <= plain - phased <= 4
        assert phased == field.lineslice_tbc(19).start + (offset // 4) * 4


@parametrize_system
def test_lineslice_tbc_rounds_half_to_even(rf):
    """nb_round is np.round, i.e. banker's rounding -- a .5 boundary goes to
    the even sample, not upwards.  Pinned because a switch to int() or to
    round-half-up would silently move every slice that lands on a half."""
    field = make_field(rf)
    outfreq = rf.SysParams["outfreq"]

    # Half an output sample into line 1.  Half-to-even keeps the slice at 0;
    # round-half-up, or C-style truncation of 0.5 + 0.5, would move it to 1.
    assert field.lineslice_tbc(1, 0.5 / outfreq, 1.0).start == 0
    assert field.lineslice_tbc(1, 0.6 / outfreq, 1.0).start == 1


# --- Hz <-> output codes <-> IRE ----------------------------------------


@parametrize_system
def test_hz_to_output_anchors(field, rf):
    """The two ends of the output range are what output_black/output_white
    name: the sync tip (vsync_ire) and 100 IRE."""
    vsync_ire = rf.DecoderParams["vsync_ire"]

    assert field.hz_to_output(rf.iretohz(vsync_ire)) == field.output_black
    assert field.hz_to_output(rf.iretohz(100)) == field.output_white

    # outputZero names the code at vsync_ire, not the code for 0 IRE: it is
    # the offset the scaling is applied from, and equals output_black.
    assert rf.SysParams["outputZero"] == field.output_black
    assert field.hz_to_output(rf.iretohz(0)) == round(
        field.output_black - vsync_ire * field.out_scale
    )


@parametrize_system
def test_out_scale_is_codes_per_ire(field, rf):
    span = field.output_white - field.output_black
    assert field.out_scale == span / (100 - rf.DecoderParams["vsync_ire"])

    # one IRE is one out_scale step
    step = field.hz_to_output(rf.iretohz(51)) - field.hz_to_output(rf.iretohz(50))
    assert step == pytest.approx(field.out_scale, abs=1)


@parametrize_system
def test_out_scale_follows_the_agc(rf):
    """The AGC rewrites vsync_ire between fields, so out_scale is recomputed
    per field rather than fixed at construction."""
    field = make_field(rf)
    before = field.out_scale

    rf.DecoderParams["vsync_ire"] = -30.0
    try:
        assert field.compute_out_scale() != before
        assert field.compute_out_scale() == (
            field.output_white - field.output_black) / 130.0
    finally:
        rf.DecoderParams["vsync_ire"] = rf.SysParams["vsync_ire"]


@parametrize_system
def test_hz_to_output_scalar_and_array_paths_agree(field, rf, seeded_rng):
    """Two implementations of the same map: a scalar branch here and the
    jitted hz_to_output_array in dsp.py.  A divergence would show up as a
    difference between measured levels and written output."""
    hz = rf.iretohz(seeded_rng.uniform(-50, 120, 500))
    scalar = np.array([field.hz_to_output(float(v)) for v in hz])

    assert np.array_equal(field.hz_to_output(hz), scalar)


@parametrize_system
def test_hz_to_output_clips_into_the_16_bit_range(field, rf):
    assert field.hz_to_output(rf.iretohz(-100000)) == 0
    assert field.hz_to_output(rf.iretohz(100000)) == 65535
    assert field.hz_to_output(rf.iretohz(0)).dtype == np.uint16


@parametrize_system
def test_output_to_ire_inverts_hz_to_output(field, rf):
    for ire in (-40.0, -20.0, 0.0, 7.5, 50.0, 100.0):
        out = field.hz_to_output(rf.iretohz(ire))
        assert field.output_to_ire(float(out)) == pytest.approx(ire, abs=0.01)


@parametrize_system
def test_output_to_ire_is_linear_and_exact_at_the_anchors(field, rf):
    assert field.output_to_ire(float(field.output_black)) == pytest.approx(
        rf.DecoderParams["vsync_ire"]
    )
    assert field.output_to_ire(float(field.output_white)) == pytest.approx(100.0)


def test_the_two_systems_use_different_output_ranges(rfs):
    """NTSC and PAL place sync and peak white at different codes; a test that
    passed for one system while asserting the other's constants would be
    silently wrong, so the difference is pinned here."""
    ntsc = make_field(rfs["NTSC"])
    pal = make_field(rfs["PAL"])

    assert (ntsc.output_black, ntsc.output_white) == (0x0400, 0xC800)
    assert (pal.output_black, pal.output_white) == (0x0100, 0xD300)
    assert ntsc.out_scale != pal.out_scale
