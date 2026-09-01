"""Unit tests for lddecode.efm_pll -- EFM channel-clock recovery.

``EFM_PLL`` turns a demodulated EFM waveform into the run-length (T) values the
``.efm`` output carries, and ``computeefmfilter`` builds the equaliser applied
to that waveform first.  Neither had direct coverage, and both are pure enough
to drive here: the PLL takes an int16 array and returns an int8 array, and the
filter takes two numbers and returns an array.

The test signal is a synthesised NRZI waveform: a piecewise-linear trapezoid
whose zero crossings sit at exact multiples of the nominal channel bit period,
so the T sequence the PLL is *supposed* to recover is the one the signal was
built from.  The ramp either side of each crossing is two samples wide, which
means the two samples the PLL interpolates between always lie on the same
straight line through zero and the recovered crossing is exact to within int16
rounding (about 3e-5 of a sample at the amplitude used here).

These run compiled -- EFM_PLL is a Numba jitclass, so a typing regression in it
fails here rather than part-way through a decode.
"""

import numpy as np
import pytest

from lddecode.efm_pll import EFM_PLL, computeefmfilter

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

# The EFM channel bit period at the decoder's 40 MHz sample rate:
# 40 MHz / 4.3218 MHz = 9.2554... samples per T.
BASE_PERIOD = 40000000.0 / 4321800.0

# Well clear of int16 saturation, and steep enough through the crossing that
# quantisation is negligible.
AMPLITUDE = 16000

# Legal EFM run lengths: 3T to 11T inclusive (EFM's (2,10) run-length limit).
MIN_T, MAX_T = 3, 11


def nrzi_signal(tvals, period=BASE_PERIOD, amplitude=AMPLITUDE, ramp=1.0):
    """A synthesised NRZI waveform with runs of the given T lengths.

    Polarity alternates at each of the crossings ``cumsum(tvals) * period``.
    Within a run the waveform sits at +/-amplitude, ramping linearly through
    zero over +/-``ramp`` samples either side of each crossing.  The shortest
    run is 3T (about 27.8 samples), so the ramps never meet.
    """
    times = np.cumsum([0.0] + [t * period for t in tvals])
    length = int(times[-1])
    out = np.zeros(length)

    polarity = 1.0
    for k in range(len(times) - 1):
        low, high = times[k], times[k + 1]
        n = np.arange(int(np.ceil(low)), int(np.ceil(high)))
        n = n[(n >= 0) & (n < length)]
        # Distance to whichever crossing is nearer, clipped at the flat top.
        shape = np.minimum(np.minimum((n - low) / ramp, (high - n) / ramp), 1.0)
        out[n] = polarity * amplitude * shape
        polarity = -polarity

    return np.round(out).astype(np.int16)


@pytest.fixture(scope="module")
def tvals():
    """A seeded run-length sequence covering every legal T value."""
    rng = np.random.default_rng(12345)
    return rng.integers(MIN_T, MAX_T + 1, 2000).tolist()


@pytest.fixture(scope="module")
def clean_signal(tvals):
    return nrzi_signal(tvals)


# --- EFM_PLL: run-length recovery -----------------------------------------


def test_pll_recovers_the_run_lengths(tvals, clean_signal):
    result = EFM_PLL().process(clean_signal)

    # The first run is measured from the loop's cold-start phase rather than
    # from a preceding edge, so it is not recoverable and is excluded; the
    # final run is still open when the buffer ends and is never emitted.
    # Everything between is exact -- these are integers, not measurements.
    assert len(result) == len(tvals) - 1
    assert np.array_equal(result[1:], np.array(tvals[1 : len(result)], dtype=np.int8))


def test_pll_emits_only_legal_run_lengths(clean_signal):
    result = EFM_PLL().process(clean_signal)

    # The edge-push (T < 3) and edge-pull (T > 11) logic exists to guarantee
    # this: the EFM decoder downstream has no representation for an illegal
    # run length, so one escaping here would corrupt the frame it lands in.
    assert result.min() >= MIN_T
    assert result.max() <= MAX_T


def test_pll_emits_only_legal_run_lengths_on_noise(seeded_rng):
    noise = seeded_rng.integers(-20000, 20000, 200000).astype(np.int16)

    result = EFM_PLL().process(noise)

    # Same invariant with no signal at all.  A capture with a dead EFM channel
    # must produce garbage T values, not out-of-range ones.
    assert len(result) > 0
    assert result.min() >= MIN_T
    assert result.max() <= MAX_T


def test_pll_caps_a_long_dropout_at_eleven_t():
    # A stretch with no zero crossings at all: the loop keeps counting cells
    # and pulls each one out at the 11T limit rather than emitting a single
    # enormous value.
    silence = np.concatenate(
        [
            np.zeros(1, dtype=np.int16),
            np.full(50000, 12000, dtype=np.int16),
            np.full(10, -12000, dtype=np.int16),
        ]
    )

    result = EFM_PLL().process(silence)

    assert len(result) > 0
    assert np.all(result == MAX_T)


def test_pll_confidence_is_high_once_locked(clean_signal):
    pll = EFM_PLL()
    result = pll.process(clean_signal)
    confidence = pll.pllConf[: len(result)]

    # pllConf is the soft-decision the Reed-Solomon stage uses to pick
    # erasures: 255 means the edge landed on the loop's predicted clock grid.
    # On a synthesised, jitter-free signal the loop should be firmly locked
    # well before the end, so the tail is where the claim is testable.
    assert confidence[-200:].min() > 200
    assert confidence.max() <= 255


def test_pll_holds_its_frequency_on_a_nominal_signal(clean_signal):
    pll = EFM_PLL()
    pll.process(clean_signal)

    # The signal is at exactly the nominal bit rate, so the recovered period
    # must stay there.  0.1% is far tighter than the +/-10% the loop allows
    # itself and loose enough for the hysteresis dither.
    assert pll.currentPeriod == pytest.approx(BASE_PERIOD, rel=1e-3)


@pytest.mark.parametrize("rate", [0.92, 1.0, 1.30])
def test_pll_period_stays_within_its_limits(rate, tvals):
    signal = nrzi_signal(tvals, period=BASE_PERIOD * rate)

    pll = EFM_PLL()
    pll.process(signal)

    # The +/-10% clamp is what stops a badly off-rate or noisy capture from
    # walking the loop somewhere it can never recover from.
    assert pll.minimumPeriod <= pll.currentPeriod <= pll.maximumPeriod


def test_pll_period_clamp_binds_under_noise(seeded_rng):
    noise = seeded_rng.integers(-20000, 20000, 200000).astype(np.int16)

    pll = EFM_PLL()
    pll.process(noise)

    # Noise crosses zero far more often than EFM does, so the loop drives the
    # period down until the clamp catches it.  Asserting that it lands exactly
    # on the limit (rather than merely inside it) shows the clamp is doing the
    # work, not just sitting there.
    assert pll.currentPeriod == pll.minimumPeriod


# --- EFM_PLL: streaming contract ------------------------------------------


def test_pll_is_unaffected_by_how_the_input_is_chunked(clean_signal):
    whole = EFM_PLL().process(clean_signal)

    chunked = EFM_PLL()
    pieces = [
        chunked.process(clean_signal[start : start + 997]).copy()
        for start in range(0, len(clean_signal), 997)
    ]

    # The decoder feeds the PLL a block at a time, and the block size depends
    # on the demodulator's geometry rather than on anything the PLL controls.
    # Carrying zcPreviousInput and delta across calls is what makes the output
    # independent of that; a chunk size that is not a multiple of anything is
    # the case most likely to expose a boundary bug.
    assert np.array_equal(np.concatenate(pieces), whole)


def test_pll_result_is_a_view_that_the_next_call_overwrites(clean_signal):
    pll = EFM_PLL()

    first = pll.process(clean_signal[:5000])
    snapshot = first[:5].copy()
    pll.process(clean_signal[5000:10000])

    # process() returns a view into the PLL's own buffer, so a caller that
    # keeps the array across calls silently gets the next block's data.
    # Pinned deliberately: it is the reason decoder.py copies, and a change
    # that started returning a fresh array would make that copy dead weight.
    assert not np.array_equal(first[:5], snapshot)


def test_pll_grows_its_buffer_for_a_long_input(tvals):
    rng = np.random.default_rng(54321)
    long_signal = nrzi_signal(rng.integers(MIN_T, MAX_T + 1, 9000).tolist())
    assert len(long_signal) > 1 << 16, "test needs an input past the initial buffer"

    pll = EFM_PLL()
    assert len(pll.pllResult) == 1 << 16
    result = pll.process(long_signal)

    # The result and confidence buffers are sized for the input, not for the
    # number of edges, so they have to be reallocated together -- letting them
    # get out of step would write confidence values past the end of pllConf.
    assert len(pll.pllResult) == len(long_signal)
    assert len(pll.pllConf) == len(long_signal)
    assert len(result) > 0


def test_pll_with_empty_input():
    assert len(EFM_PLL().process(np.zeros(0, dtype=np.int16))) == 0


def test_pll_with_no_zero_crossings():
    # A constant, non-zero input: nothing to time against, so nothing is
    # emitted rather than a spurious run.
    assert len(EFM_PLL().process(np.full(1000, 5000, dtype=np.int16))) == 0


# --- EFM_PLL: gear shift ---------------------------------------------------


def test_gearshift_leaves_a_clean_signal_bit_identical(clean_signal):
    default = EFM_PLL()
    shifted = EFM_PLL()
    shifted.gearshift = 1

    # This is the claim the gear-shift code makes for itself: it boosts the
    # loop gains only while unlocked, and a clean signal never leaves lock, so
    # enabling it must not change a single T value.  If that stops being true
    # the option has become a decode-changing switch instead of a recovery
    # aid, which is exactly what this test is here to catch.
    assert np.array_equal(default.process(clean_signal), shifted.process(clean_signal))


def test_gearshift_starts_in_the_locked_state():
    pll = EFM_PLL()

    # lockCounter starts at the threshold so a clean start-up runs through the
    # tracking gains, not the acquisition ones -- which is what makes the
    # bit-identity above hold from the very first edge.
    assert pll.lockCounter == pll.lockThreshold
    assert pll.gearshift == 0


# --- computeefmfilter ------------------------------------------------------

# The equaliser's anchor points, from the module.  Restated here so the test
# checks the interpolation and the scaling rather than re-reading the table it
# is meant to be verifying.
EQ_FREQS_HZ = np.linspace(0.0e6, 2.0e6, num=11)
EQ_AMPLITUDE = np.array(
    [0.0, 0.215, 0.41, 0.73, 0.98, 1.03, 0.99, 0.81, 0.59, 0.42, 0.0]
)
EQ_PHASE = (
    np.array([0.0, -0.92, -1.03, -1.11, -1.2, -1.2, -1.2, -1.2, -1.05, -0.95, -0.8])
    * 1.25
)
EQ_GAIN = 8

# 40 MHz over 4000 bins puts a bin every 10 kHz, so the 200 kHz anchor spacing
# lands exactly on bins 0, 20, 40 ... 200.  The decoder's own 65536-bin block
# does not, which would leave nothing to compare the interpolation against.
FILTER_FREQ_HZ = 40000000
FILTER_BLOCK_LEN = 4000
BINS_PER_ANCHOR = 20


@pytest.fixture(scope="module")
def efm_filter():
    return computeefmfilter(FILTER_FREQ_HZ, FILTER_BLOCK_LEN)


def test_filter_shape(efm_filter):
    assert len(efm_filter) == FILTER_BLOCK_LEN
    assert efm_filter.dtype == np.complex128


def test_filter_passes_through_its_amplitude_anchors(efm_filter):
    knots = efm_filter[np.arange(11) * BINS_PER_ANCHOR]

    # Cubic interpolation is exact at its knots, so this is a check of the
    # x8 scaling and the amp/phase composition, not of SciPy's interpolator.
    # Tolerance is double-precision round-off through cos/sin.
    assert np.abs(np.abs(knots) - EQ_AMPLITUDE * EQ_GAIN).max() < 1e-12


def test_filter_applies_the_phase_anchors_with_a_negative_rotation(efm_filter):
    knots = efm_filter[np.arange(11) * BINS_PER_ANCHOR]

    # The coefficients are amp * (cos(p) - i*sin(p)), i.e. exp(-i*p): the
    # tabulated phase is *removed* from the signal, not added to it.  A sign
    # error here would double the group delay the equaliser exists to correct.
    # Only the anchors with non-zero amplitude carry a defined angle.
    nonzero = EQ_AMPLITUDE > 0
    assert np.abs(np.angle(knots[nonzero]) - (-EQ_PHASE[nonzero])).max() < 1e-12


def test_filter_is_zero_outside_the_equalised_band(efm_filter):
    # Bin 200 is the 2.0 MHz anchor, whose amplitude is zero; everything past
    # it is left untouched at zero.  EFM's channel bit rate is 4.32 Mbit/s, so
    # the equaliser deliberately keeps only the fundamental region.
    assert efm_filter[0] == 0
    assert efm_filter[200] == 0
    assert np.abs(efm_filter[201:]).max() == 0.0


def test_filter_peak_gain(efm_filter):
    # The tallest anchor is 1.03, scaled by 8.  The cubic overshoots it very
    # slightly between knots, which is expected of an interpolating spline; a
    # 0.1% allowance covers that and would still catch a changed scale factor.
    assert np.abs(efm_filter).max() == pytest.approx(
        EQ_AMPLITUDE.max() * EQ_GAIN, rel=1e-3
    )


def test_filter_band_edge_is_a_frequency_not_a_bin_count():
    # The equalised band is 0-2 MHz whatever block length and sample rate it is
    # asked for, so halving both must give the same shape rather than the same
    # number of bins at a different frequency.
    forty = computeefmfilter(40000000, 4000)
    twenty = computeefmfilter(20000000, 2000)

    # Both have a 10 kHz bin spacing, so the two bands cover the same bins.
    assert np.count_nonzero(forty) == np.count_nonzero(twenty)
    assert np.abs(forty[:201] - twenty[:201]).max() < 1e-12


def test_filter_is_finite_everywhere(efm_filter):
    # interp1d will happily produce NaN if asked outside its range; the bin
    # count is computed from the anchor spacing, so an off-by-one there would
    # show up as a NaN rather than as a wrong value.
    assert np.all(np.isfinite(efm_filter))
