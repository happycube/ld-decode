"""Unit tests for the partial NTSC comb filter used by the metrics.

CombNTSC is not the decoder's chroma path -- ld-decode writes composite and
leaves separation to ld-chroma-decoder -- but it is what the line 19 VITS
colour-burst reading is measured through, and that reading drives the
inverse-MTF auto-calibration.  So its behaviour has to be pinned even though
none of it reaches the .tbc.

Everything below is synthesised at 4x fSC, which is what the output sample
rate is: one subcarrier cycle is exactly four samples, so chroma is a
period-4 sequence and the two-samples-either-side comb is exact rather than
approximate.
"""

import numpy as np
import pytest

from lddecode.metrics import CombNTSC
from synthetic_field import make_field, make_rf

pytestmark = [pytest.mark.unit, pytest.mark.decode]


@pytest.fixture(scope="module")
def rf():
    return make_rf("NTSC")


def comb_field(rf, picture, is_first_field=True, field_phase_id=1):
    return make_field(
        rf,
        dspicture=np.asarray(picture, dtype=np.float64),
        is_first_field=is_first_field,
        field_phase_id=field_phase_id,
    )


def subcarrier(n, amplitude=1.0, phase=0.0, start=0):
    """A subcarrier-rate sequence: four samples to the cycle."""
    t = np.arange(start, start + n)
    return amplitude * np.cos(2 * np.pi * t / 4 + phase)


# --- buildCBuffer -------------------------------------------------------


def test_a_flat_line_combs_to_nothing(rf):
    comb = CombNTSC(comb_field(rf, np.full(64, 12345.0)))

    assert np.array_equal(comb.cbuffer[0], np.zeros(64, dtype=np.float32))


def test_a_luma_ramp_combs_to_nothing(rf):
    """The comb is (neighbours' average - this sample), which is exactly zero
    for anything linear -- so a luma gradient leaves no residue in chroma."""
    comb = CombNTSC(comb_field(rf, np.arange(64.0) * 37.0 + 900.0))

    assert np.allclose(comb.cbuffer[0][2:-2], 0.0, atol=1e-3)


def test_subcarrier_survives_the_comb_at_double_amplitude(rf):
    """Two samples away is half a subcarrier cycle, so the neighbours' average
    is the negated sample; subtracting it doubles chroma and inverts it.  The
    gain is what the line 19 amplitude reading is divided back out of."""
    chroma = subcarrier(64, amplitude=250.0, phase=0.6)
    comb = CombNTSC(comb_field(rf, chroma + 20000.0))

    assert np.allclose(comb.cbuffer[0][2:-2], -2.0 * chroma[2:-2], atol=1e-2)


def test_the_ends_of_the_buffer_are_left_at_zero(rf):
    """The comb needs two samples either side, so the first and last two have
    no reading; they are zero rather than an extrapolation."""
    comb = CombNTSC(comb_field(rf, subcarrier(64, amplitude=100.0) + 5000.0))
    cbuffer = comb.cbuffer[0]

    assert np.array_equal(cbuffer[:2], np.zeros(2, dtype=np.float32))
    assert np.array_equal(cbuffer[-2:], np.zeros(2, dtype=np.float32))


def test_the_comb_is_computed_in_single_precision(rf):
    """dspicture is uint16 in a real decode; the comb promotes to float32,
    which is what every downstream amplitude is measured in."""
    comb = CombNTSC(comb_field(rf, np.arange(64.0)))

    assert comb.cbuffer[0].dtype == np.float32


def test_a_subset_combs_only_what_it_selects(rf):
    field = comb_field(rf, subcarrier(200, amplitude=100.0) + 5000.0)
    comb = CombNTSC(field)

    subset = comb.buildCBuffer(field, subset=slice(50, 150))

    assert len(subset) == 100
    assert np.allclose(subset[2:-2], comb.cbuffer[0][52:148], atol=1e-2)


# --- getlinephase -------------------------------------------------------


@pytest.mark.parametrize("field_phase_id", [1, 2, 3, 4])
@pytest.mark.parametrize("line", [0, 1, 18, 19])
def test_line_phase_alternates_with_the_line_and_the_field(rf, field_phase_id, line):
    """The subcarrier inverts line to line and the four-field sequence shifts
    where that inversion starts; phase IDs 1 and 4 are in phase on even lines,
    2 and 3 on odd ones."""
    comb = CombNTSC(comb_field(rf, np.zeros(64), field_phase_id=field_phase_id))

    expected = field_phase_id in ((1, 4) if line % 2 == 0 else (2, 3))
    assert bool(comb.getlinephase(0, line)) is expected


def test_line_phase_inverts_between_adjacent_lines(rf):
    comb = CombNTSC(comb_field(rf, np.zeros(64), field_phase_id=1))

    for line in range(0, 20):
        assert comb.getlinephase(0, line) != comb.getlinephase(0, line + 1)


# --- splitIQ_line -------------------------------------------------------


def test_split_takes_alternate_samples_into_the_two_axes(rf):
    """At 4x fSC the two colour-difference axes are simply the even and odd
    samples; the sign flips put successive cycles the same way up."""
    values = np.arange(1.0, 17.0)
    field = comb_field(rf, np.zeros(64), field_phase_id=1)
    comb = CombNTSC(field)
    comb.cbuffer[0] = values.astype(np.float32)

    si, sq = comb.splitIQ_line(0, slice(0, 16))

    assert np.array_equal(np.abs(sq), values[0::2])
    assert np.array_equal(np.abs(si), values[1::2])


@pytest.mark.parametrize("line, signs_i, signs_q", [
    (0, [1, -1], [-1, 1]),      # linephase true for phase ID 1 on even lines
    (1, [-1, 1], [1, -1]),
])
def test_the_sign_pattern_follows_the_line_phase(rf, line, signs_i, signs_q):
    """Which of the two interleaves gets negated is the whole content of
    getlinephase: get it backwards and hue inverts every other line."""
    values = np.ones(16)
    field = comb_field(rf, np.zeros(64), field_phase_id=1)
    comb = CombNTSC(field)
    comb.cbuffer[0] = values.astype(np.float32)

    si, sq = comb.splitIQ_line(line, slice(0, 16))

    assert list(si[:2]) == signs_i
    assert list(sq[:2]) == signs_q


def test_a_stationary_subcarrier_demodulates_to_a_constant(rf):
    """A single unchanging colour across the line must give constant I and Q;
    any ripple would be the split putting samples on the wrong axis."""
    chroma = subcarrier(400, amplitude=200.0, phase=0.4)
    comb = CombNTSC(comb_field(rf, chroma + 20000.0, field_phase_id=1))

    si, sq = comb.splitIQ_line(0, slice(4, 396))

    assert np.allclose(si, si[0], atol=1e-2)
    assert np.allclose(sq, sq[0], atol=1e-2)


def test_the_split_does_not_alias_luma_into_chroma(rf):
    chroma = subcarrier(400, amplitude=200.0, phase=0.4)
    ramp = np.linspace(15000.0, 25000.0, 400)
    plain = CombNTSC(comb_field(rf, chroma + 20000.0, field_phase_id=1))
    tilted = CombNTSC(comb_field(rf, chroma + ramp, field_phase_id=1))

    for a, b in zip(plain.splitIQ_line(0, slice(4, 396)),
                    tilted.splitIQ_line(0, slice(4, 396))):
        assert np.allclose(a, b, atol=1e-2)


# --- 3D availability ----------------------------------------------------


def test_a_single_field_has_no_third_dimension(rf):
    assert not CombNTSC(comb_field(rf, np.zeros(64))).has_3d


def test_two_fields_of_opposite_parity_are_not_a_frame_apart(rf):
    """Subtracting the other parity's field would subtract a different set of
    picture lines, not the same ones one frame earlier."""
    fields = [comb_field(rf, np.zeros(64), is_first_field=p) for p in (True, False)]

    assert not CombNTSC(fields).has_3d


def test_two_fields_of_the_same_parity_are_a_frame_apart(rf):
    fields = [comb_field(rf, np.zeros(64), is_first_field=True) for _ in range(2)]

    assert CombNTSC(fields).has_3d


def test_four_fields_are_always_a_frame_apart(rf):
    fields = [comb_field(rf, np.zeros(64), is_first_field=bool(i % 2)) for i in range(4)]
    comb = CombNTSC(fields)

    assert comb.has_3d
    assert comb._ref_idx == 1          # the same parity as fields[3]


def test_the_reference_field_is_one_frame_back(rf):
    for count, expected in ((1, 0), (2, 0), (3, 0), (4, 1), (5, 2)):
        fields = [comb_field(rf, np.zeros(64)) for _ in range(count)]
        assert CombNTSC(fields)._ref_idx == expected


def test_the_metrics_field_is_always_the_last_one(rf):
    fields = [comb_field(rf, np.full(64, float(i))) for i in range(4)]

    assert CombNTSC(fields).field is fields[-1]


def test_a_bare_field_is_accepted_without_a_list(rf):
    field = comb_field(rf, np.zeros(64))

    assert CombNTSC(field).fields == [field]


# --- 3D subtraction -----------------------------------------------------


def test_an_unchanging_picture_subtracts_to_nothing_in_3d(rf):
    """Two identical frames means no chroma difference; the 3D path is an
    inter-frame subtraction with no motion correction, so a still picture is
    exactly what it cancels."""
    chroma = subcarrier(400, amplitude=200.0, phase=0.4) + 20000.0
    fields = [comb_field(rf, chroma, is_first_field=True) for _ in range(2)]

    si, sq = CombNTSC(fields).splitIQ_line(0, slice(4, 396))

    assert np.allclose(si, 0.0, atol=1e-3)
    assert np.allclose(sq, 0.0, atol=1e-3)


def test_the_3d_subtraction_halves_rather_than_doubling(rf):
    """C = (current - previous) / 2, so an inverted subcarrier one frame back
    -- which is what the four-field sequence gives -- comes back at the same
    amplitude as the 2D path, not twice it."""
    chroma = subcarrier(400, amplitude=200.0, phase=0.4)
    current = comb_field(rf, chroma + 20000.0, is_first_field=True)
    previous = comb_field(rf, -chroma + 20000.0, is_first_field=True)

    flat = CombNTSC(current).splitIQ_line(0, slice(4, 396))
    with_3d = CombNTSC([previous, current]).splitIQ_line(0, slice(4, 396))

    for a, b in zip(flat, with_3d):
        assert np.allclose(a, b, atol=1e-2)


# --- calcLine19Info -----------------------------------------------------

LINE19_LUMA_IRE = 70.0


def line19_info(comb):
    """calcLine19Info with the noiseless case's 1/0 left alone.

    A synthetic burst has an exactly constant envelope, so the SNR division
    is by zero; that is the reading being asked about in one of the tests
    below, not an accident to be avoided.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        return comb.calcLine19Info()


def line19_field(rf, chroma_ire=20.0, phase=0.0, luma_ire=LINE19_LUMA_IRE,
                 noise_ire=0.0, field_phase_id=1, is_first_field=True, rng=None):
    """A field whose line 19 carries a flat 70 IRE bar with a burst on it.

    calcLine19Info only reads line 19, so the rest of the picture is left at
    the same level; the 14-18 us window it sanity-checks has to sit between
    40 and 100 IRE for a reading to be returned at all.
    """
    field = make_field(rf, is_first_field=is_first_field,
                       field_phase_id=field_phase_id)
    outlinelen = rf.SysParams["outlinelen"]
    length = outlinelen * 30

    zero = float(field.hz_to_output(rf.iretohz(0.0)))
    picture = np.full(length, zero + luma_ire * field.out_scale)

    start = outlinelen * 18
    span = slice(start, start + outlinelen)
    picture[span] += subcarrier(outlinelen, chroma_ire * field.out_scale, phase,
                                start=start)
    if noise_ire:
        picture[span] += rng.normal(0.0, noise_ire * field.out_scale, outlinelen)

    field.dspicture = picture
    return field


def test_line_19_reports_the_burst_amplitude_in_ire(rf):
    """The reading is divided by 2 x out_scale, undoing the comb's gain of
    two and converting output codes back to IRE."""
    # The burst has to stay inside the 40-100 IRE window the reading is only
    # taken in, so 25 IRE either side of the 70 IRE bar is the ceiling here.
    for chroma_ire in (5.0, 10.0, 25.0):
        amplitude, _, _ = line19_info(CombNTSC(line19_field(rf, chroma_ire)))

        assert amplitude == pytest.approx(chroma_ire, rel=1e-3)


def test_line_19_phase_tracks_the_burst_phase(rf):
    """A quarter-cycle shift of the input moves the reported phase by 90
    degrees; the sign of that is what tells a decode its colour is inverted."""
    base, step = 0.0, np.pi / 2
    phases = [
        line19_info(CombNTSC(line19_field(rf, phase=base + k * step)))[1]
        for k in range(4)
    ]

    diffs = [(phases[k + 1] - phases[k]) % 360 for k in range(3)]
    assert all(d == pytest.approx(diffs[0], abs=1e-6) for d in diffs)
    assert diffs[0] == pytest.approx(90.0) or diffs[0] == pytest.approx(270.0)


def test_line_19_phase_is_reported_in_zero_to_360(rf):
    for k in range(8):
        _, phase, _ = line19_info(CombNTSC(line19_field(rf, phase=k * np.pi / 4)))
        assert 0.0 <= phase < 360.0


def test_a_noiseless_burst_reports_an_infinite_snr(rf):
    """The SNR is the spread of the burst envelope; with nothing to spread it
    the reading is meaningless rather than perfect."""
    _, _, snr = line19_info(CombNTSC(line19_field(rf)))

    assert np.isinf(snr)


def test_line_19_snr_falls_as_noise_rises(rf, seeded_rng):
    readings = [
        line19_info(
            CombNTSC(line19_field(rf, chroma_ire=10.0, noise_ire=n, rng=seeded_rng))
        )[2]
        for n in (0.25, 1.0, 4.0)
    ]

    assert readings[0] > readings[1] > readings[2]


@pytest.mark.parametrize("luma_ire", [20.0, 39.0, 101.0, 120.0])
def test_a_line_19_outside_the_expected_level_is_declined(rf, luma_ire):
    """Line 19 carries a defined 70 IRE bar.  If what is there is not between
    40 and 100 IRE it is not that bar -- a disc without VITS, or a field that
    lost sync -- and measuring it would feed the servos noise."""
    assert line19_info(CombNTSC(line19_field(rf, luma_ire=luma_ire))) == (
        None, None, None
    )


def test_a_bad_reference_field_declines_the_3d_reading(rf):
    """With 3D the reading depends on the previous frame too, so that frame's
    line 19 has to be usable as well."""
    good = line19_field(rf, chroma_ire=10.0, is_first_field=True)
    # one frame back the subcarrier is inverted, so the 3D subtraction adds
    previous = line19_field(rf, chroma_ire=10.0, phase=np.pi, is_first_field=True)
    bad = line19_field(rf, chroma_ire=10.0, luma_ire=10.0, is_first_field=True)

    assert line19_info(CombNTSC([bad, good])) == (None, None, None)
    assert line19_info(CombNTSC([previous, good]))[0] == pytest.approx(10.0, rel=1e-3)
