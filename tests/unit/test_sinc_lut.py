"""The resample look-up table, and the interpolation that lets it be small.

The table is read one row per *output* sample, so it stays hot for the whole of
every field and its size is charged against the same cache as the signal being
resampled.  At 65536 phases it was 4 MiB and could not stay resident; at 256 it
is 16 KiB and sits in L1d.  The phase resolution that costs is bought back by
interpolating between the two rows either side of a position instead of taking
the nearest one, in both kernels.

These tests build the tables in-process, so the coarse interpolated table is
measured against a fine one directly rather than against a recorded number, and
the shipped file is pinned to the same builder.
"""

from importlib.resources import files

import numpy as np
import pytest

from lddecode.dsp import (
    build_kaiser_lut, kaiser_beta, scale_field, scale_positions,
    sinc_phase_count, sinc_tap_count,
)

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

#: The phase count the coarse table is measured against.  Its rows are a strict
#: subsample of it, so it is the same filter family at a resolution fine enough
#: that its own quantisation is not what the comparison sees.
REFERENCE_PHASE_COUNT = 65536

#: (sample rate, bandwidth) pairs the table is measured on.  The resamplers
#: read the demodulated video at the input rate and write the 4fsc lattice, so
#: the first row is the case that actually occurs; the second puts the same
#: band that much closer to Nyquist, where interpolating a coarse table is
#: hardest, and is the regime the design measurement was taken in.
BANDS = [
    (40e6, 6.3e6),     # PAL input rate, past the luma band
    (17.734475e6, 6.3e6),  # PAL 4fsc, band at 0.36 of the rate
]

#: Above the largest measured error with margin (7.8e-7 at the input rate,
#: 3.2e-6 at 4fsc) and still a decade and a half under a 16-bit LSB (3.05e-5
#: on a unit signal), so the table cannot drift into visible territory without
#: this failing first.
RMS_TOLERANCE = 1e-5


@pytest.fixture(scope="module")
def coarse():
    return build_kaiser_lut(kaiser_beta, sinc_tap_count, sinc_phase_count)


@pytest.fixture(scope="module")
def fine():
    return build_kaiser_lut(kaiser_beta, sinc_tap_count, REFERENCE_PHASE_COUNT)


SIGNAL_LENGTH = 4096


def band_limited_signal(sample_rate, bandwidth):
    """A seeded noise signal with no energy above `bandwidth`, unit rms.

    Band-limited because a resampler is only asked to reconstruct what the
    input filters passed; broadband noise would measure aliasing, not the
    table.
    """
    rng = np.random.default_rng(20260904)
    bins = SIGNAL_LENGTH // 2 + 1
    top = int(bandwidth / sample_rate * SIGNAL_LENGTH)
    spectrum = np.zeros(bins, dtype=np.complex128)
    spectrum[: top + 1] = rng.normal(size=top + 1) + 1j * rng.normal(size=top + 1)
    signal = np.fft.irfft(spectrum, SIGNAL_LENGTH)
    return signal / np.sqrt(np.mean(signal**2))


@pytest.fixture(scope="module")
def positions():
    """10**4 positions with arbitrary fractional parts, clear of the taps."""
    rng = np.random.default_rng(987654321)
    margin = sinc_tap_count
    return rng.uniform(margin, SIGNAL_LENGTH - margin, 10000)


def resample_nearest(buf, locs, lut, phases):
    """What the kernels used to do: the nearest tabulated phase, no blend."""
    ints = locs.astype(np.int64)
    frac = locs - ints
    rows = lut[(frac * phases + 0.5).astype(np.int64)]
    starts = ints - (sinc_tap_count // 2 - 1)
    taps = buf[starts[:, None] + np.arange(sinc_tap_count)[None, :]]
    return np.einsum("ij,ij->i", taps, rows.astype(np.float64))


def test_shipped_table_is_what_the_parameters_build(coarse):
    """The .npz is generated, so it can fall out of step with dsp.py; this is
    what catches a parameter change that was never regenerated."""
    shipped = np.load(files("lddecode") / "sinc_lut.npz")["downscale_sinc_lut"]
    assert shipped.shape == coarse.shape
    assert shipped.dtype == coarse.dtype
    np.testing.assert_array_equal(shipped, coarse)


def test_shipped_table_stays_small_enough_to_cache():
    path = files("lddecode") / "sinc_lut.npz"
    assert path.stat().st_size <= 64 * 1024
    lut = np.load(path)["downscale_sinc_lut"]
    assert lut.nbytes <= 64 * 1024


def test_every_row_has_unit_gain_at_dc(coarse):
    """Rows are normalised, so a blend of two adjacent rows is normalised too
    and the resampler cannot introduce a level shift that varies with phase."""
    np.testing.assert_allclose(coarse.sum(axis=1), 1.0, rtol=0, atol=2e-7)


def test_the_guard_row_is_the_whole_sample_delay(coarse):
    """The last row is the phase-1.0 filter, which is the phase-0 filter moved
    on by one tap -- not a copy of its neighbour.  The top phase bucket
    interpolates towards it, so a copy there would bias every position in it."""
    assert not np.array_equal(coarse[sinc_phase_count], coarse[sinc_phase_count - 1])
    np.testing.assert_array_equal(coarse[sinc_phase_count][1:], coarse[0][:-1])


def test_the_coarse_table_is_a_subsample_of_the_fine_one(coarse, fine):
    """Nothing about the filter changed with the phase count; only how finely
    it is tabulated.  This is what makes the comparison below a measure of the
    interpolation alone."""
    np.testing.assert_array_equal(fine[:: REFERENCE_PHASE_COUNT // sinc_phase_count], coarse)


@pytest.mark.parametrize("sample_rate,bandwidth", BANDS)
def test_interpolating_a_coarse_table_matches_a_fine_one(
    coarse, fine, positions, sample_rate, bandwidth
):
    signal = band_limited_signal(sample_rate, bandwidth)
    reference = resample_nearest(signal, positions, fine, REFERENCE_PHASE_COUNT)

    out = np.zeros(len(positions), dtype=np.float64)
    wow = np.ones(len(positions), dtype=np.float64)
    scale_positions(signal, out, positions, wow, coarse, 1.0)

    error = out - reference
    rms = np.sqrt(np.mean(error**2))
    assert rms < RMS_TOLERANCE, "rms %.3e, peak %.3e" % (rms, np.abs(error).max())


def test_both_kernels_resample_a_position_the_same_way(coarse, positions):
    """scale_field lays its output out as a raster and scale_positions does
    not, but the sample each produces for a given position is the same one."""
    signal = band_limited_signal(*BANDS[0])
    width = 128
    locs = positions[: 4 * width]
    wow = np.ones(len(locs), dtype=np.float64)

    # scale_field starts one line in and indexes locs by absolute position, so
    # it resamples locs[width:], which is the slice given to scale_positions.
    raster = np.zeros(len(locs) - width, dtype=np.float64)
    scale_field(signal, raster, locs, wow, coarse, 0, width)

    flat = np.zeros(len(locs) - width, dtype=np.float64)
    scale_positions(
        signal, flat, locs[width:], wow[width:], coarse, float(width)
    )

    np.testing.assert_array_equal(raster, flat)


def test_a_position_resamples_the_same_wherever_it_sits_in_the_buffer(coarse):
    """The sample a position resolves to must not depend on how far into the
    field that position is.

    A field's demod buffer runs to about 8e5 samples, which is past the point
    where a float32 can hold a sample position to better than 1/16 of a
    sample.  Narrowing the coordinate before splitting off its fractional part
    therefore snapped the lower half of every field onto a coarse grid and
    threw away the resolution the table is interpolated for.  Tiling a
    periodic signal puts identical waveform under both bases, so anything the
    two resamples disagree about came from the coordinate.
    """
    period = SIGNAL_LENGTH
    signal = np.tile(band_limited_signal(*BANDS[0]), (1 << 20) // period + 2)

    # A step that is not a whole number of samples, so the fractional part
    # sweeps the table rather than sitting on phase zero.
    offsets = np.arange(2048) * (period / 2049.0)
    near, far = float(period), float(1 << 20)

    def resample(base):
        out = np.zeros(len(offsets), dtype=np.float64)
        wow = np.ones(len(offsets), dtype=np.float64)
        scale_positions(signal, out, base + offsets, wow, coarse, 1.0)
        return out

    np.testing.assert_allclose(resample(far), resample(near), rtol=0, atol=1e-6)
