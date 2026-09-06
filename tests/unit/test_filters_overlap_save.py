"""Unit tests for the block-slicing helpers in lddecode.filters.

Two related jobs live here:

``fft_determine_slices`` / ``fft_do_slice`` / ``fft_do_slice_half``
    Pick a narrow band out of a wide FFT so the audio demodulators can work at
    a fraction of the RF rate.  The arithmetic is integer bin indexing, so it
    is asserted exactly.  The block path holds only the positive half of a
    real block's spectrum, so the ``_half`` form takes the same band from that
    by conjugate symmetry, and is held to the whole-spectrum form's bytes.

``overlap_save_fft`` / ``overlap_save_ifft``
    Split a signal into overlapping FFT blocks and put it back together.  The
    contract is that filtering the blocks and reassembling gives the same
    answer as filtering the whole array in one go -- that is the whole point of
    discarding ``blockcut_begin`` samples from each block, and it is what the
    decoder's block-at-a-time demodulation depends on.

The test blocks are deliberately small (64-256 samples rather than the 32,768
the decoder uses) so several blocks fit in a short signal and the boundaries
actually get exercised.
"""

import numpy as np
import pytest
import scipy.signal as sps

import scipy.fft as npfft

from lddecode.filters import (
    fft_determine_slices,
    fft_do_slice,
    fft_do_slice_half,
    overlap_save_fft,
    overlap_save_ifft,
)

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

FREQ_HZ = 40e6


# --- fft_determine_slices --------------------------------------------------


def test_slice_indices_are_exact():
    # The NTSC left analog audio carrier is near 2.8 MHz; 200 kHz of bandwidth
    # is what the audio filters need either side of it.
    lowbin, nbins, cut_freq = fft_determine_slices(2.8e6, 200e3, FREQ_HZ, 32768)

    # bin width = 40 MHz / 32768 = 1220.703125 Hz
    #   centre bin  = round(2.8e6 / 1220.703125)  = 2294
    #   wanted bins = round(200e3 / 1220.703125)  = 164
    #   nbins       = 2 * 2**ceil(log2(328))      = 1024
    #   lowbin      = 2294 - 1024//4              = 2038
    assert (lowbin, nbins) == (2038, 1024)
    assert cut_freq == pytest.approx(1_250_000.0, abs=1e-9)


def test_slice_width_is_a_power_of_two():
    _, nbins, _ = fft_determine_slices(2.8e6, 200e3, FREQ_HZ, 32768)

    # The sliced band is inverse-transformed, so its length has to stay
    # FFT-friendly however awkward the requested bandwidth is.
    assert nbins & (nbins - 1) == 0


@pytest.mark.parametrize("center", [1e6, 2.8e6, 3.58e6, 4.43e6, 8.1e6, 12e6])
@pytest.mark.parametrize("min_bandwidth", [50e3, 100e3, 200e3, 500e3, 1e6])
@pytest.mark.parametrize("bins_in", [4096, 16384, 32768])
def test_slice_covers_the_requested_band(center, min_bandwidth, bins_in):
    lowbin, nbins, cut_freq = fft_determine_slices(
        center, min_bandwidth, FREQ_HZ, bins_in
    )

    binwidth = FREQ_HZ / bins_in
    low_hz = lowbin * binwidth
    high_hz = (lowbin + nbins // 2) * binwidth

    # The docstring promises centre +/- min_bandwidth, and every caller sizes
    # its filters on that promise.  Rounding the bin count up to a power of two
    # means the real span is wider, never narrower.
    assert low_hz <= center - min_bandwidth
    assert high_hz >= center + min_bandwidth
    assert cut_freq == pytest.approx(binwidth * nbins, rel=1e-12)


def test_do_slice_takes_the_bins_determine_slices_named():
    blocklen = 32768
    # A ramp so each element reports its own index: the assertion then reads as
    # "which bins were taken", not "what were their values".
    fdomain = np.arange(blocklen)
    lowbin, nbins, _ = fft_determine_slices(2.8e6, 200e3, FREQ_HZ, blocklen)

    sliced = fft_do_slice(fdomain, lowbin, nbins, blocklen)

    half = nbins // 2
    expected = np.concatenate(
        [
            np.arange(lowbin, lowbin + half),
            np.arange(blocklen - lowbin - half, blocklen - lowbin),
        ]
    )
    # Exact: this is index arithmetic, and taking the mirror-image negative
    # frequencies from the wrong end would silently conjugate the band.
    assert np.array_equal(sliced, expected)
    assert len(sliced) == nbins


# --- the same slice, taken from a real block's rfft ------------------------
#
# demodblock holds the positive half of the block's spectrum, so the audio
# slicers read their negative-frequency bins off it by conjugate symmetry
# instead of the whole spectrum being mirrored for them.  The bytes have to be
# the ones the mirror produced, so these compare against fft_do_slice itself.

# The two systems' analog audio carriers, and a 200 kHz half-bandwidth, as
# computeaudiofilters asks for them.
AUDIO_CARRIERS_HZ = [2.301136e6, 2.812499e6, 2.30e6, 2.80e6]
AUDIO_BLOCKLEN = 32768


@pytest.mark.parametrize("center", AUDIO_CARRIERS_HZ)
def test_the_half_slice_is_the_whole_slice(center):
    rng = np.random.default_rng(20220)
    block = rng.normal(0.0, 1.0, AUDIO_BLOCKLEN)
    lowbin, nbins, _ = fft_determine_slices(center, 200e3, FREQ_HZ, AUDIO_BLOCKLEN)

    expected = fft_do_slice(npfft.fft(block), lowbin, nbins, AUDIO_BLOCKLEN)
    actual = fft_do_slice_half(npfft.rfft(block), lowbin, nbins, AUDIO_BLOCKLEN)

    assert len(actual) == nbins
    # Exact, not close: this slice feeds a demodulator whose output is written
    # to a .pcm file that a decode is held byte-identical on.
    np.testing.assert_array_equal(actual, expected)


def test_the_half_slice_refuses_a_band_that_runs_past_nyquist():
    """The whole-spectrum version wraps into the mirror and returns a silently
    wrong slice; there is no mirror to wrap into here, so say so instead."""
    blocklen = 1024
    half = npfft.rfft(np.zeros(blocklen))

    with pytest.raises(ValueError, match="outside the positive half"):
        fft_do_slice_half(half, blocklen // 2 - 8, 64, blocklen)


def test_the_half_slice_refuses_a_spectrum_of_the_wrong_length():
    """Handed a whole spectrum by mistake, the conjugate mirror it builds
    would be of the wrong bins entirely."""
    blocklen = 1024
    whole = npfft.fft(np.zeros(blocklen))

    with pytest.raises(ValueError, match="is not the rfft"):
        fft_do_slice_half(whole, 100, 64, blocklen)


def test_the_half_slice_takes_the_band_it_was_asked_for():
    """The conjugate mirror hides a reversed or off-by-one band, so pin the
    bins themselves as the whole-spectrum test above does."""
    blocklen = 1024
    lowbin, nbins = 100, 64
    # A complex ramp: the real part reports the bin index, and conjugating it
    # flips the sign of the imaginary part, so a bin taken from the wrong end
    # or without the conjugate cannot pass.
    half = np.arange(blocklen // 2 + 1) + 1j * np.arange(blocklen // 2 + 1)

    sliced = fft_do_slice_half(half, lowbin, nbins, blocklen)

    mirror = np.arange(lowbin + 1, lowbin + nbins // 2 + 1)[::-1]
    expected = np.concatenate(
        [
            np.arange(lowbin, lowbin + nbins // 2) * (1 + 1j),
            mirror * (1 - 1j),
        ]
    )
    assert np.array_equal(sliced, expected)


# --- overlap_save round trip ----------------------------------------------


BLOCK_LEN = 64
CUT_BEGIN = 8
CUT_END = 4


@pytest.mark.parametrize(
    "length",
    [
        1,  # single sample
        BLOCK_LEN - CUT_BEGIN - CUT_END - 1,  # shorter than one stride
        BLOCK_LEN - CUT_BEGIN - CUT_END,  # exactly one stride
        BLOCK_LEN,  # exactly one block
        BLOCK_LEN + 1,  # one sample past a block
        4 * BLOCK_LEN + 7,  # several blocks, unaligned tail
    ],
)
def test_round_trip_reconstructs_the_input(seeded_rng, length):
    # 16-bit-scale samples, matching what the decoder actually pushes through
    # these functions.
    data = seeded_rng.integers(-30000, 30000, length).astype(np.float64)

    blocks = overlap_save_fft(data, BLOCK_LEN, CUT_BEGIN, CUT_END)
    restored = overlap_save_ifft(blocks, CUT_BEGIN, CUT_END)

    assert len(restored) == length
    # Forward and inverse FFT of 16-bit-scale data: the residual is around
    # 1e-11 absolute, i.e. five orders of magnitude below one LSB of the
    # 16-bit sample it has to reproduce.  1e-6 is a generous ceiling that still
    # catches a real reconstruction error.
    assert np.abs(restored - data).max() < 1e-6


def test_round_trip_carries_the_length_so_padding_is_not_returned():
    data = np.arange(100.0)
    blocks = overlap_save_fft(data, BLOCK_LEN, CUT_BEGIN, CUT_END)

    # The first element is the original length, not an FFT block: the final
    # block is zero-padded and the length is what trims the padding back off.
    assert blocks[0] == 100
    assert all(len(b) == BLOCK_LEN for b in blocks[1:])


def test_block_count_covers_the_input():
    stride = BLOCK_LEN - CUT_BEGIN - CUT_END
    data = np.arange(4.0 * stride)

    blocks = overlap_save_fft(data, BLOCK_LEN, CUT_BEGIN, CUT_END)

    # numblocks = len // stride + 1, so an exactly-aligned input still gets a
    # trailing block.  Reconstruction has to stay correct in that case, which
    # the round-trip test above covers; here just pin the count.
    assert len(blocks) - 1 == 5


# --- overlap_save as a filter ---------------------------------------------


def test_filtering_the_blocks_matches_filtering_the_whole_signal(seeded_rng):
    blocklen, cut_begin, cut_end = 256, 32, 16
    length = 1000

    data = seeded_rng.normal(0.0, 1000.0, length)
    # 17 taps, comfortably shorter than cut_begin: overlap-save is only exact
    # while the filter's impulse response fits inside the discarded region.
    taps = sps.firwin(17, 0.25)
    response = np.fft.fft(taps, blocklen)

    blocks = overlap_save_fft(data, blocklen, cut_begin, cut_end)
    filtered = [blocks[0]] + [block * response for block in blocks[1:]]
    actual = overlap_save_ifft(filtered, cut_begin, cut_end)

    expected = np.convolve(data, taps)[:length]

    # From cut_begin onward the sliced path is the linear convolution.  On a
    # signal with an RMS of 1000 the difference is around 1e-13, so 1e-6 is
    # again far below anything that could matter and still tight enough to
    # catch a block that was stitched at the wrong offset.
    assert np.abs(actual[cut_begin:] - expected[cut_begin:]).max() < 1e-6


def test_the_first_block_head_is_circular_wraparound(seeded_rng):
    blocklen, cut_begin, cut_end = 256, 32, 16
    length = 1000

    data = seeded_rng.normal(0.0, 1000.0, length)
    taps = sps.firwin(17, 0.25)
    response = np.fft.fft(taps, blocklen)

    blocks = overlap_save_fft(data, blocklen, cut_begin, cut_end)
    filtered = [blocks[0]] + [block * response for block in blocks[1:]]
    actual = overlap_save_ifft(filtered, cut_begin, cut_end)
    expected = np.convolve(data, taps)[:length]

    # The head of the first block is not discarded, so it carries the FFT's
    # circular wraparound and is *not* the linear convolution.  Callers have to
    # know that; pinning it here means a change that starts trimming the head
    # shows up as a failing test rather than as a silent shift in every
    # downstream block boundary.
    assert np.abs(actual[:cut_begin] - expected[:cut_begin]).max() > 1.0
