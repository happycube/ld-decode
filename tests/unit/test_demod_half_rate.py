"""The FM discriminator runs at half the input rate.

After the one-sided RF filter the block's spectrum is non-zero only over
0-20 MHz, and a complex signal sampled at 20 MSPS spans exactly that band, so
the ``blocklen // 2``-point inverse of the positive bins is twice the even
samples of the analytic signal with nothing lost.  ``demodblock`` demodulates
there and interpolates the video products back onto the input lattice with the
zero-padded inverse it was already doing, so nothing outside the block chain
changes rate.

Two things do change, and both are corrected where the video stack is built
(``RFDecode.discriminator_rate_correction``): the conjugate-product
discriminator averages the instantaneous frequency over one of its own sample
intervals, so at 50 ns it both tilts the response and delays it by a further
12.5 ns.  These tests hold the corrected chain against the full-rate one, which
is still reachable through ``full_rate_demod=True`` and is byte-for-byte the
chain that shipped before this change.

Hermetic: every block is synthesised here; nothing reads a capture.
"""

import numpy as np
import scipy.fft as npfft

import pytest

from lddecode.core import RFDecode
from lddecode.filters import emphasis_iir, filtfft
from lddecode.dsp import genwave

pytestmark = [pytest.mark.unit, pytest.mark.dsp]


SYSTEMS = ["PAL", "NTSC"]

#: Both chains are circular over the block, and ``unwrap_hilbert`` writes a
#: zero as its first sample, which is a full-amplitude impulse in the demod.
#: The leading ``blockcut`` throws away where it lands; the 32-sample trailing
#: cut does not reach where the circular convolution wraps it to.  That tail is
#: a property of a synthetic block that a real overlap-save decode does not
#: have (its blocks are contiguous), and it exists identically in both chains,
#: so the comparisons below are made over the interior.
EDGE = 2000


def bin_snap(rf, hz):
    """``hz`` moved to the nearest bin, so a tone is periodic over the block.

    A tone that is not periodic makes the block's own wrap a discontinuity,
    which then dominates every difference measured near the edges.
    """
    return round(hz * rf.blocklen / rf.freq_hz) * rf.freq_hz / rf.blocklen


def fm_carrier(rf, ire):
    """An unmodulated FM carrier at one video level."""
    hz = bin_snap(rf, rf.iretohz(ire))
    return genwave(np.full(rf.blocklen, hz), rf.freq_hz / 2) * 4096 + 8192


def fm_tones(rf, tones_mhz, ire=50, amp_ire=20, per_segment=False):
    """A pre-emphasised, FM-modulated block carrying ``tones_mhz``.

    With ``per_segment``, each tone gets its own stretch of the block rather
    than being summed onto the whole of it, which is what a multiburst is.
    Returns the block and, for the segmented case, the segment length.
    """
    video = np.full(rf.blocklen, float(rf.iretohz(ire)))
    n = np.arange(rf.blocklen)
    step = rf.blocklen // (len(tones_mhz) + 2)
    for index, mhz in enumerate(tones_mhz):
        hz = bin_snap(rf, mhz * 1e6)
        tone = amp_ire * rf.DecoderParams["hz_ire"] * np.cos(2 * np.pi * hz * n / rf.freq_hz)
        if per_segment:
            lo = step * (index + 1)
            video[lo : lo + step] += tone[lo : lo + step]
        else:
            video += tone

    # Pre-emphasis, so the block is what a disc carries rather than a bare
    # tone: computevideofilters retired Femp, so it is rebuilt here from the
    # de-emphasis coefficients it is the inverse of.
    deemp1, deemp2 = rf.DecoderParams["video_deemp"]
    femp = filtfft(emphasis_iir(deemp2, deemp1, rf.freq_hz), rf.blocklen)
    emphasised = npfft.ifft(npfft.fft(video) * femp).real

    return genwave(emphasised, rf.freq_hz / 2) * 4096 + 8192, step


def both_chains(system, **kwargs):
    """The half-rate decoder under test and the full-rate one it answers to."""
    return (
        RFDecode(system=system, **kwargs),
        RFDecode(system=system, full_rate_demod=True, **kwargs),
    )


def video_channels(rf):
    names = ["demod", "demod_05", "demod_burst"]
    if rf.system == "PAL":
        names.append("demod_pilot")
    return names


# --- the tilt correction ----------------------------------------------------


#: The plan's multiburst.  5.5 MHz is above both systems' video low-pass
#: corner, which is the point: it is where the uncorrected tilt is worst.
MULTIBURST_MHZ = [0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 5.5]


@pytest.mark.parametrize("system", SYSTEMS)
def test_the_multiburst_amplitudes_survive_the_rate_change(system):
    """Per-burst amplitude within 0.05 dB of the full-rate chain's.

    The uncorrected tilt is -0.84 dB at 5.5 MHz (asserted below), so this
    fails if the correction is missing, and fails the other way if it is
    applied twice.
    """
    half, full = both_chains(system)
    signal, step = fm_tones(full, MULTIBURST_MHZ, per_segment=True)

    got = half.demodblock(data=signal)["video"]["demod"]
    want = full.demodblock(data=signal)["video"]["demod"]

    for index, mhz in enumerate(MULTIBURST_MHZ):
        # Well inside the segment: the transitions between bursts are steps,
        # and a step's ringing is not what this measures.
        lo = step * (index + 1) + 400
        hi = step * (index + 2) - 400
        db = 20 * np.log10(np.std(got[lo:hi]) / np.std(want[lo:hi]))
        assert abs(db) < 0.05, (mhz, db)


@pytest.mark.parametrize("system", SYSTEMS)
def test_the_uncorrected_tilt_is_what_the_correction_removes(system):
    """The tilt is real and this size, so the test above has teeth.

    Runs the same multiburst through a decoder whose stack has been stripped
    back to the plain interpolation scaling - no ``1 / cos`` and no half-sample
    advance - and measures the sinc ratio the discriminator's 50 ns window
    imposes: about -0.24 dB at 3 MHz and -0.84 dB at 5.5 MHz.
    """
    half, full = both_chains(system)

    flat = np.full(half.blocklen // 4 + 1, 2.0 + 0j)
    flat[-1] = 1.0
    half.Filters["FVideo_rfft32"] = (
        half.Filters["FVideo_rfft32"] / half.discriminator_rate_correction() * flat
    ).astype(np.complex64)

    signal, step = fm_tones(full, MULTIBURST_MHZ, per_segment=True)
    got = half.demodblock(data=signal)["video"]["demod"]
    want = full.demodblock(data=signal)["video"]["demod"]

    measured = {}
    for index, mhz in enumerate(MULTIBURST_MHZ):
        lo = step * (index + 1) + 400
        hi = step * (index + 2) - 400
        measured[mhz] = 20 * np.log10(np.std(got[lo:hi]) / np.std(want[lo:hi]))

    assert measured[0.5] == pytest.approx(-0.007, abs=0.01)
    assert measured[3.0] == pytest.approx(-0.244, abs=0.02)
    assert measured[5.5] == pytest.approx(-0.837, abs=0.02)


@pytest.mark.parametrize("system", SYSTEMS)
def test_the_rate_correction_is_the_sinc_ratio_of_the_two_windows(system):
    """``1 / cos(pi*k/N)`` is the closed form of ``sinc(f*T) / sinc(f*2T)``.

    Held against the ratio written out longhand, so the identity the
    implementation leans on cannot quietly stop being true.
    """
    rf = RFDecode(system=system)
    k = np.arange(rf.blocklen // 4 + 1)
    freq = k * rf.freq_hz / rf.blocklen

    longhand = np.sinc(freq / rf.freq_hz) / np.sinc(freq / (rf.freq_hz / 2))
    advance = np.exp(1j * np.pi * freq / rf.freq_hz)
    interpolation = np.full(k.shape, 2.0)
    interpolation[-1] = 1.0

    np.testing.assert_allclose(
        rf.discriminator_rate_correction(),
        longhand * advance * interpolation,
        rtol=1e-12,
    )

    # And it is exactly 1 at DC, which is what lets the channels' DC gains be
    # taken from the uncorrected stack.
    assert rf.discriminator_rate_correction()[0] == 2.0


@pytest.mark.parametrize("system", SYSTEMS)
def test_the_absurd_demod_bound_follows_the_discriminator_rate(system):
    """The input-rate chain keeps the bound it shipped with; the half-rate one
    takes three-quarters of the way to its own phase wrap, which is also where
    demodblock clips."""
    half, full = both_chains(system)

    assert full.demod_absurd_hz == full.freq_hz_half
    assert half.demod_absurd_hz == pytest.approx(0.75 * half.freq_hz_demod)
    assert half.demod_absurd_hz < half.freq_hz_demod


@pytest.mark.parametrize("system", SYSTEMS)
def test_the_video_band_above_the_half_rate_nyquist_is_empty(system):
    """The premise of cutting the stack at ``blocklen // 4``.

    The half-rate demod's transform stops at 10 MHz, so the video filters'
    response between there and 20 MHz is dropped outright.  Measured, the
    largest magnitude any of the four channels has up there is -98 dB (PAL)
    and -60 dB (NTSC) of its passband: the post-demod low-pass corner is
    around 5 MHz and its skirt has long since run out.
    """
    full = RFDecode(system=system, full_rate_demod=True)
    stack = full.Filters["FVideo_rfft32"]
    discarded = np.abs(stack[:, full.blocklen // 4 + 1 :]).max()
    passband = np.abs(stack[:, :4]).max()

    assert 20 * np.log10(discarded / passband) < -55


# --- the products themselves ------------------------------------------------


#: The two chains do not agree bit for bit and cannot: the discriminator's
#: output above 10 MHz folds at 20 MSPS, which is the deliberate, measured
#: cost of the rate change.  On an unmodulated carrier there is nothing above
#: 10 MHz to fold, so what is left is arithmetic, and it is stated in IRE
#: rather than in the channels' float32 steps because the burst and pilot
#: channels of an unmodulated block hold numerical residue whose "peak" is not
#: a scale.  Measured worst case: 0.00025 IRE (NTSC demod), 0.00006 IRE (PAL).
#: A 16-bit TBC sample is about 0.0027 IRE, so this is a tenth of one.
CARRIER_TOLERANCE_IRE = 0.001


@pytest.mark.parametrize("system", SYSTEMS)
@pytest.mark.parametrize("ire", [0, 50, 100])
def test_an_unmodulated_carrier_demodulates_the_same_on_both_chains(system, ire):
    half, full = both_chains(system)
    signal = fm_carrier(full, ire)

    got = half.demodblock(data=signal)["video"]
    want = full.demodblock(data=signal)["video"]
    hz_ire = full.DecoderParams["hz_ire"]

    for name in video_channels(full):
        difference = np.abs(got[name] - want[name])[EDGE:-EDGE].max() / hz_ire
        assert difference < CARRIER_TOLERANCE_IRE, (name, difference)


@pytest.mark.parametrize("system", SYSTEMS)
def test_the_burst_and_pilot_channels_track_the_full_rate_chain(system):
    """The channels the unmodulated block cannot exercise, on a block that can.

    Their content is a tone at the subcarrier (and, on PAL, at the pilot), so
    here the channel's own peak is a scale and the difference can be stated
    against it.
    """
    half, full = both_chains(system)
    tones = [full.SysParams["fsc_mhz"]]
    if system == "PAL":
        tones.append(full.SysParams["pilot_mhz"])
    signal, _ = fm_tones(full, tones)

    got = half.demodblock(data=signal)["video"]
    want = full.demodblock(data=signal)["video"]

    for name in ("demod_burst", "demod_pilot") if system == "PAL" else ("demod_burst",):
        peak = np.abs(want[name][EDGE:-EDGE]).max()
        difference = np.abs(got[name] - want[name])[EDGE:-EDGE].max()
        # Measured: 0.15 % of peak on PAL burst, 0.02 % on PAL pilot, 0.005 %
        # on NTSC burst.  This is the fold, not rounding, so the bound is in
        # the channel's own amplitude rather than in its last places.
        assert difference < 0.005 * peak, (name, difference / peak)
        assert peak > 10 * full.DecoderParams["hz_ire"], (name, peak)


@pytest.mark.parametrize("system", SYSTEMS)
def test_the_products_are_still_written_at_the_input_rate(system):
    """The record array, and everything downstream that indexes it, keep the
    block's own length: the zero-padded inverse is where the rate comes back."""
    half, _ = both_chains(system)
    signal, _ = fm_tones(half, [half.SysParams["fsc_mhz"]])

    video = half.demodblock(data=signal)["video"]
    assert video.shape == (half.blocklen,)

    cut = half.demodblock(data=signal, cut=True)["video"]
    assert cut.shape == (half.blocklen - half.blockcut - half.blockcut_end,)


# --- the unfiltered channel -------------------------------------------------


@pytest.mark.parametrize("system", SYSTEMS)
def test_demod_raw_is_constant_over_the_sample_pairs_it_was_formed_from(system):
    """``demod[m]`` is the phase advance from analytic sample 2m-2 to 2m, so it
    is written at 2m-1 and 2m: pairs starting at odd indices, not even ones."""
    half, _ = both_chains(system)
    signal, _ = fm_tones(half, [half.SysParams["fsc_mhz"]])

    raw = half.demodblock(data=signal)["video"]["demod_raw"]

    np.testing.assert_array_equal(raw[1:-1:2], raw[2::2])
    # ...and it is genuinely a decimated signal, not accidentally constant.
    assert np.count_nonzero(raw[2:-1:2] != raw[3::2]) > raw.shape[0] // 4


@pytest.mark.parametrize("system", SYSTEMS)
def test_demod_raw_carries_the_full_rate_pair_average(system):
    """Each half-rate estimate is the mean of the two full-rate estimates it
    spans, so the expanded channel is that mean at both of their positions."""
    half, full = both_chains(system)
    signal = fm_carrier(full, 50)

    got = half.demodblock(data=signal)["video"]["demod_raw"]
    want = full.demodblock(data=signal)["video"]["demod_raw"]

    # want[2m-1] and want[2m] are the two increments demod[m] spans.
    pairs = want[1:-1].reshape(-1, 2).mean(axis=1)
    hz_ire = full.DecoderParams["hz_ire"]
    difference = np.abs(got[2:-1:2] - pairs) / hz_ire
    assert difference[EDGE:-EDGE].max() < CARRIER_TOLERANCE_IRE


@pytest.mark.parametrize("system", SYSTEMS)
def test_an_rf_dropout_is_bracketed_on_both_chains(system):
    """``field.dropout_detect_demod``'s last test, on both chains.

    What is asserted is that the flagged region brackets the damage on both,
    not that it is the same set of samples: the half-rate estimate is the mean
    of a pair, so an isolated full-rate excursion is averaged back towards the
    carrier and the interior of a long dropout is flagged more sparsely.
    """
    half, full = both_chains(system)
    signal, _ = fm_tones(full, [full.SysParams["fsc_mhz"]])
    start, width = 16000, 200
    signal[start : start + width] = 8192.0

    for name, rf in (("half", half), ("full", full)):
        raw = rf.demodblock(data=signal)["video"]["demod_raw"]
        flagged = np.flatnonzero(raw > rf.demod_absurd_hz)
        near = flagged[(flagged > start - 500) & (flagged < start + width + 500)]
        assert near.size, name
        # Inside the damage, and reaching both ends of it.
        assert start - 8 <= near[0] <= start + 40, (name, int(near[0]))
        assert start + width - 40 <= near[-1] <= start + width + 8, (name, int(near[-1]))
        # ...and nothing flagged away from it.
        assert np.array_equal(flagged, near), name


@pytest.mark.parametrize("system", SYSTEMS)
def test_a_clean_block_flags_nothing_on_either_chain(system):
    """The threshold has to stay above what an undamaged carrier reaches, or
    the rate change would turn the detector into a source of dropouts.

    The half-rate bound is the one that had to be chosen rather than carried
    over (see rfdecode.demod_absurd_hz); this is the margin it leaves on a
    synthetic block, and the measured margin on real captures is recorded
    there.
    """
    half, full = both_chains(system)
    signal, _ = fm_tones(full, [full.SysParams["fsc_mhz"]])

    for rf in (half, full):
        raw = rf.demodblock(data=signal, cut=True)["video"]["demod_raw"]
        assert not np.any(raw > rf.demod_absurd_hz)
        assert raw.max() < 0.85 * rf.demod_absurd_hz, (rf.full_rate_demod, raw.max())


# --- the calibrated delays --------------------------------------------------


#: ``computedelays`` demodulates a synthetic line and measures where the
#: products land.  These are the values the tree produced before the rate
#: change (checked against the reference tree, not merely against this one),
#: and the plan's gate is that the half-rate chain stays within one sample.
FULL_RATE_DELAYS = {
    "PAL": {"video_sync": 20.140279769, "video_white": 20.166305181, "video_rot": 9},
    "NTSC": {"video_sync": 13.561008729, "video_white": 13.528512437, "video_rot": 5},
}


@pytest.mark.parametrize("system", SYSTEMS)
def test_the_full_rate_delays_are_unchanged(system):
    delays = RFDecode(system=system, full_rate_demod=True).delays
    for name, expected in FULL_RATE_DELAYS[system].items():
        assert delays[name] == pytest.approx(expected, abs=1e-8), name


@pytest.mark.parametrize("system", SYSTEMS)
def test_the_half_rate_delays_land_within_one_sample(system):
    """The half-sample advance in the rate correction is what holds the two
    together; without it these move by half a sample each.

    ``video_rot`` is the onset of a rot glitch found by a 20 %-of-peak
    threshold, and the discriminator's 50 ns window spreads the glitch over a
    further sample, so on NTSC the onset is found one sample later.  That is
    inside the few samples of movement computedelays' own comment records
    across parameter sweeps.
    """
    delays = RFDecode(system=system).delays
    for name, expected in FULL_RATE_DELAYS[system].items():
        assert abs(delays[name] - expected) <= 1, (name, delays[name], expected)

    for name in ("video_sync", "video_white"):
        assert delays[name] == pytest.approx(FULL_RATE_DELAYS[system][name], abs=1e-3)
