"""Unit tests for the VITS measurement maths.

These are the numbers that end up in the .tbc.json and that the AGC and the
auto-calibration servos steer on, so an error here is not cosmetic: it moves
the decode.  Every signal below is synthesised at a level the test states in
IRE, and the expected answer is the closed-form one for that level.

detect_levels is included even though it reaches into a field's demodulated
data, because what it does -- median the sync tip and the back porch of every
usable line, and the VITS white bars -- is per-field measurement with no
history, and a synthetic field pins it exactly.
"""

import numpy as np
import pytest

from lddecode.metrics import (
    UNIFIED_WEIGHTING_TAU,
    calcpsnr,
    calcpsnr_weighted,
    calcsnr,
    detect_levels,
    weighted_noise_rms,
)
from synthetic_field import make_field, make_rf

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

SYSTEMS = ["NTSC", "PAL"]


@pytest.fixture(scope="module")
def rfs():
    return {system: make_rf(system) for system in SYSTEMS}


@pytest.fixture
def rf(rfs, request):
    return rfs[request.param]


parametrize_system = pytest.mark.parametrize("rf", SYSTEMS, indirect=True)


def picture_field(rf, ire, length=20000):
    """A field whose output picture sits at a constant IRE level."""
    field = make_field(rf)
    code = float(field.hz_to_output(rf.iretohz(0.0)))
    picture = np.full(length, code + np.asarray(ire) * field.out_scale)
    field.dspicture = np.round(picture).astype(np.uint16)
    return field


# --- calcsnr / calcpsnr -------------------------------------------------


@parametrize_system
@pytest.mark.parametrize("level, noise_ire", [(50.0, 1.0), (100.0, 0.5), (20.0, 2.0)])
def test_calcsnr_recovers_the_synthesised_ratio(rf, level, noise_ire, seeded_rng):
    """Signal is the mean level, noise the standard deviation, both in IRE."""
    field = picture_field(rf, level)
    noise = seeded_rng.normal(0.0, noise_ire * field.out_scale, len(field.dspicture))
    field.dspicture = np.round(field.dspicture + noise).astype(np.uint16)

    expected = 20 * np.log10(level / noise_ire)
    assert calcsnr(field, slice(None)) == pytest.approx(expected, abs=0.5)


@parametrize_system
def test_calcpsnr_measures_against_a_fixed_100_ire_reference(rf, seeded_rng):
    """PSNR does not depend on the level of the line it is measured on, which
    is why it is the number reported for the black VITS reference lines."""
    noise_ire = 0.75
    expected = 20 * np.log10(100.0 / noise_ire)

    for level in (0.0, 50.0):
        field = picture_field(rf, level)
        noise = seeded_rng.normal(0.0, noise_ire * field.out_scale, len(field.dspicture))
        field.dspicture = np.round(
            np.clip(field.dspicture + noise, 0, 65535)
        ).astype(np.uint16)

        assert calcpsnr(field, slice(None)) == pytest.approx(expected, abs=0.5)


@parametrize_system
def test_calcsnr_converts_to_float_before_subtracting(rf, seeded_rng):
    """dspicture is uint16 and output_to_ire subtracts outputZero from it, so
    a sample below the sync tip wraps to about +140 IRE unless the cast
    happens first.  A dropout floors the output at 0, so such samples are
    exactly what a damaged line contains -- and they would land in the noise
    term as a swing thirty times the real one.
    """
    field = picture_field(rf, 50.0)
    field.dspicture[::500] = 0                     # dropout-floored samples
    assert field.dspicture.min() < rf.SysParams["outputZero"]

    as_float = make_field(rf)
    as_float.dspicture = field.dspicture.astype(float)

    assert calcsnr(field, slice(None)) == calcsnr(as_float, slice(None))
    assert calcpsnr(field, slice(None)) == calcpsnr(as_float, slice(None))


@parametrize_system
def test_a_noiseless_line_reports_an_infinite_ratio(rf):
    """Zero measured noise is not a real measurement; it means the slice was
    flat (a clipped or synthetic signal), and the caller has to treat the
    infinity as "no reading" rather than as a very good one."""
    field = picture_field(rf, 50.0)

    with np.errstate(divide="ignore"):
        assert np.isinf(calcsnr(field, slice(None)))
        assert np.isinf(calcpsnr(field, slice(None)))


@parametrize_system
def test_a_slice_of_pure_noise_reports_around_zero_db(rf, seeded_rng):
    """Mean and standard deviation of the same order: the signal is gone."""
    field = picture_field(rf, 50.0)
    noise = seeded_rng.normal(0.0, 50.0 * field.out_scale, len(field.dspicture))
    field.dspicture = np.round(
        np.clip(field.dspicture + noise, 0, 65535)
    ).astype(np.uint16)

    assert abs(calcsnr(field, slice(None))) < 3.0


# --- weighted_noise_rms -------------------------------------------------

FS_HZ = 14.318181818e6
LPF_HZ = 4.2e6
N = 4096


def weighting(freq_hz):
    """CCIR Rec. 567 unified weighting, as an amplitude factor."""
    return 1.0 / np.sqrt(1.0 + (2 * np.pi * freq_hz * UNIFIED_WEIGHTING_TAU) ** 2)


def tone(freq_hz, amplitude=1.0, n=N, fs=FS_HZ, phase=0.0):
    """A sinusoid on an exact FFT bin, so its energy does not leak."""
    bin_index = round(freq_hz * n / fs)
    t = np.arange(n)
    return amplitude * np.sin(2 * np.pi * bin_index * t / n + phase), bin_index * fs / n


@pytest.mark.parametrize("freq_hz", [50e3, 200e3, 650e3, 1e6, 2e6, 4e6])
def test_an_in_band_tone_is_scaled_by_the_weighting_curve(freq_hz):
    """A sinusoid of amplitude A has RMS A/sqrt(2); weighting multiplies it by
    the network's response at that frequency."""
    signal, exact_hz = tone(freq_hz, amplitude=3.0)
    expected = (3.0 / np.sqrt(2)) * weighting(exact_hz)

    assert weighted_noise_rms(signal, FS_HZ, LPF_HZ) == pytest.approx(expected, rel=1e-9)


def test_the_weighting_is_minus_three_db_at_its_corner():
    """tau0 = 245 ns puts the half-power point at about 650 kHz; the constant
    is the specification's, so this checks it has not been transcribed as a
    frequency or as a different time constant."""
    corner_hz = 1.0 / (2 * np.pi * UNIFIED_WEIGHTING_TAU)

    assert corner_hz == pytest.approx(649.6e3, rel=1e-3)
    assert 20 * np.log10(weighting(corner_hz)) == pytest.approx(-3.0103, abs=1e-4)


@pytest.mark.parametrize("freq_hz", [4.5e6, 5e6, 6e6])
def test_noise_above_the_measurement_bandwidth_is_discarded(freq_hz):
    """The reading is specified over the video band; energy above it is not
    part of the measurement."""
    signal, _ = tone(freq_hz, amplitude=10.0)

    assert weighted_noise_rms(signal, FS_HZ, LPF_HZ) == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize("freq_hz", [3.5e3, 7e3])
def test_low_frequency_content_is_discarded(freq_hz):
    """Below 10 kHz is field- and line-rate tilt, not noise; a noise meter
    high-passes it away rather than reporting it as grain."""
    signal, _ = tone(freq_hz, amplitude=10.0)

    assert weighted_noise_rms(signal, FS_HZ, LPF_HZ) == pytest.approx(0.0, abs=1e-12)


def test_a_dc_offset_is_not_discarded():
    """Bin 0 is deliberately left in the passband, so the caller has to remove
    the offset itself -- calcpsnr_weighted detrends with a linear fit first.
    A slice handed straight in would read its own DC as noise."""
    assert weighted_noise_rms(np.full(N, 2.5), FS_HZ, LPF_HZ) == pytest.approx(2.5)


def test_tones_at_different_frequencies_add_in_power():
    """Parseval: the weighted RMS of a sum of tones on distinct bins is the
    root sum of squares of each tone's own reading."""
    parts = [tone(f, amplitude=a)[0] for f, a in ((300e3, 1.0), (1.5e6, 2.0), (3.7e6, 0.5))]
    singles = [weighted_noise_rms(p, FS_HZ, LPF_HZ) for p in parts]

    total = weighted_noise_rms(sum(parts), FS_HZ, LPF_HZ)
    assert total == pytest.approx(np.sqrt(np.sum(np.square(singles))), rel=1e-9)


def test_the_reading_does_not_depend_on_phase():
    """A noise measurement is a magnitude; where in the slice the waveform
    happens to start must not change it."""
    readings = [
        weighted_noise_rms(tone(1e6, phase=p)[0], FS_HZ, LPF_HZ)
        for p in (0.0, 0.7, np.pi / 2, 2.9)
    ]

    assert np.allclose(readings, readings[0], rtol=1e-9)


def test_a_wider_measurement_bandwidth_admits_more_noise(seeded_rng):
    """625-line practice measures to 5 MHz, 525-line to 4.2; the wider band
    can only report at least as much noise, never less."""
    noise = seeded_rng.normal(0.0, 1.0, N)

    assert weighted_noise_rms(noise, FS_HZ, 5.0e6) > weighted_noise_rms(noise, FS_HZ, LPF_HZ)


# --- calcpsnr_weighted --------------------------------------------------


@parametrize_system
def test_weighted_psnr_matches_the_weighted_rms_of_the_noise(rf, seeded_rng):
    field = picture_field(rf, 50.0, length=2048)
    fs_hz = rf.SysParams["outfreq"] * 1e6
    lpf_hz = 4.2e6 if rf.system == "NTSC" else 5.0e6

    noise_ire = seeded_rng.normal(0.0, 1.0, len(field.dspicture))
    field.dspicture = np.round(
        field.dspicture + noise_ire * field.out_scale
    ).astype(np.uint16)
    field.rf = rf

    expected = 20 * np.log10(100.0 / weighted_noise_rms(noise_ire, fs_hz, lpf_hz))
    assert calcpsnr_weighted(field, slice(None)) == pytest.approx(expected, abs=0.3)


@parametrize_system
def test_weighted_psnr_ignores_a_linear_tilt(rf, seeded_rng):
    """The tilt null: line-rate droop is not noise, so a ramp across the slice
    must not change the reading."""
    field = picture_field(rf, 50.0, length=2048)
    noise = seeded_rng.normal(0.0, 1.0, len(field.dspicture)) * field.out_scale
    flat = np.round(field.dspicture + noise).astype(np.uint16)

    tilt = np.linspace(-5.0, 5.0, len(flat)) * field.out_scale
    tilted = np.round(field.dspicture + noise + tilt).astype(np.uint16)

    field.dspicture = flat
    without = calcpsnr_weighted(field, slice(None))
    field.dspicture = tilted
    with_tilt = calcpsnr_weighted(field, slice(None))

    assert with_tilt == pytest.approx(without, abs=0.2)


@parametrize_system
def test_weighted_psnr_declines_a_slice_that_is_too_short(rf):
    """Under 32 samples the FFT has no useful resolution over the band, so
    there is no reading to give."""
    field = picture_field(rf, 50.0, length=2048)

    assert calcpsnr_weighted(field, slice(0, 31)) is None
    assert calcpsnr_weighted(field, slice(0, 64)) is not None


@parametrize_system
def test_a_flat_slice_reads_as_an_implausible_psnr(rf):
    """The rms <= 0 guard only catches an exact zero, and the linear detrend
    leaves float residue behind instead, so a perfectly flat slice comes back
    as a few hundred dB rather than as None.  Callers therefore cannot use
    None alone to spot a slice with nothing in it."""
    field = picture_field(rf, 50.0, length=2048)

    assert calcpsnr_weighted(field, slice(None)) > 200.0


# --- detect_levels ------------------------------------------------------


def levels_field(rf, sync_ire=None, ire0=0.0, white_ire=100.0, linelen=None,
                 lines=280):
    """A field whose demodulated data sits at stated levels.

    demod_05 carries one sync pulse per line against a back porch at `ire0`
    (the two things detect_levels medians); demod is held at `white_ire`,
    which is where the VITS white bars are read from.
    """
    if sync_ire is None:
        sync_ire = rf.DecoderParams["vsync_ire"]
    if linelen is None:
        linelen = rf.linelen

    linelocs = np.arange(lines, dtype=np.float64) * linelen
    length = int(linelocs[-1] + 2 * linelen)

    field = make_field(rf, linelocs=linelocs,
                       video={"demod": np.full(length, rf.iretohz(white_ire)),
                              "demod_05": np.full(length, rf.iretohz(ire0))})

    hsync_us = rf.SysParams["hsyncPulseUS"]
    for i, loc in enumerate(linelocs[:-1]):
        width = field.usectoinpx(hsync_us, i)
        field.data["video"]["demod_05"][int(loc): int(loc + width)] = rf.iretohz(sync_ire)

    return field


@parametrize_system
def test_detect_levels_recovers_the_synthesised_levels(rf):
    field = levels_field(rf)
    sync_hz, ire0_hz, ire100_hz = detect_levels(rf, field, 200)

    assert sync_hz == pytest.approx(rf.iretohz(rf.DecoderParams["vsync_ire"]))
    assert ire0_hz == pytest.approx(rf.iretohz(0.0))
    assert ire100_hz == pytest.approx(rf.iretohz(100.0))


@parametrize_system
def test_detect_levels_tracks_a_mistuned_disc(rf):
    """The AGC exists because the levels drift; the measurement has to follow
    them rather than return the nominal values."""
    field = levels_field(rf, sync_ire=-35.0, ire0=3.0, white_ire=104.0)
    sync_hz, ire0_hz, ire100_hz = detect_levels(rf, field, 200)

    assert sync_hz == pytest.approx(rf.iretohz(-35.0))
    assert ire0_hz == pytest.approx(rf.iretohz(3.0))
    assert ire100_hz == pytest.approx(rf.iretohz(104.0))


@parametrize_system
def test_detect_levels_undoes_wow_before_medianing(rf):
    """A line 1% long was played 1% slow, so its demodulated frequencies are
    1% low; the measurement divides that back out before pooling lines."""
    field = levels_field(rf, linelen=rf.linelen * 1.01)
    sync_hz, ire0_hz, _ = detect_levels(rf, field, 200)

    assert sync_hz == pytest.approx(
        rf.iretohz(rf.DecoderParams["vsync_ire"]) * 1.01, rel=1e-6
    )
    assert ire0_hz == pytest.approx(rf.iretohz(0.0) * 1.01, rel=1e-6)


@parametrize_system
def test_lines_too_far_from_the_nominal_length_are_not_measured(rf):
    """Beyond +/-2% the line loc is more likely wrong than the disc slow, and
    the wow correction would inject a bogus level."""
    field = levels_field(rf, linelen=rf.linelen * 1.10)
    sync_hz, ire0_hz, _ = detect_levels(rf, field, 200)

    assert sync_hz == rf.iretohz(rf.DecoderParams["vsync_ire"])
    assert ire0_hz == rf.iretohz(0.0)


@parametrize_system
def test_a_white_bar_outside_spec_falls_back_to_the_nominal_level(rf):
    """The VITS white bar is only usable if it reads near 100 IRE; a disc
    without one (or a field that lost it) must not drag the reference down."""
    field = levels_field(rf, white_ire=60.0)
    _, _, ire100_hz = detect_levels(rf, field, 200)

    assert ire100_hz == rf.iretohz(100.0)
