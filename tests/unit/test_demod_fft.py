import threading

import numpy as np
import scipy.fft as npfft

from lddecode.core import RFDecode
from lddecode.utils import unwrap_hilbert

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.dsp]


# The reference chain here is the full-rate one: it demodulates at the input
# rate and filters over the whole spectrum, which is what demodblock did before
# the RF path was halved.  The decoders below are built with
# full_rate_demod=True for that reason - these tests are about the
# half-*spectrum* RF path, and holding it against a reference written in the
# same rate is what makes the comparison exact rather than approximate.  The
# half-*rate* discriminator is held against this same full-rate chain in
# test_demod_half_rate.py.


def _legacy_outputs(rf, signal):
    indata_fft = npfft.fft(signal)
    hilbert = npfft.ifft(indata_fft * rf.Filters["RFVideo"])
    demod = unwrap_hilbert(hilbert, rf.freq_hz)
    demod_fft = npfft.fft(np.clip(demod, 1500000, rf.freq_hz * 0.75))

    # FVideo05 and FVideoBurst carry their delay compensation as a phase ramp
    # baked in by computevideofilters, so there is no np.roll to undo here.
    video = [
        npfft.ifft(demod_fft * rf.Filters["FVideo"]).real,
        npfft.ifft(demod_fft * rf.Filters["FVideo05"]).real,
        npfft.ifft(demod_fft * rf.Filters["FVideoBurst"]).real,
    ]
    if rf.system == "PAL":
        video.append(npfft.ifft(demod_fft * rf.Filters["FVideoPilot"]).real)

    rfhpf = npfft.ifft(indata_fft * rf.Filters["Frfhpf"]).real
    return demod, video, rfhpf


def _check_outputs(system):
    rf = RFDecode(system=system, full_rate_demod=True)
    rng = np.random.default_rng(12345)
    signal = rng.integers(0, 16384, rf.blocklen).astype(np.float64)

    demod, expected_video, expected_rfhpf = _legacy_outputs(rf, signal)
    actual = rf.demodblock(data=signal)

    names = ["demod", "demod_05", "demod_burst"]
    if system == "PAL":
        names.append("demod_pilot")

    # demod_raw is the unfiltered demod, cast on storage exactly as before.
    np.testing.assert_allclose(actual["video"]["demod_raw"], demod, rtol=1e-6)

    # The filtered channels are computed in single precision (demodblock
    # centres the block on blanking before the cast), and stored in a
    # float32 record array.  The reference is still the exact double
    # precision answer; what is asserted is that filtering at the storage
    # precision rounds within a few units in the last place of the storage
    # itself - the error growth a 32768-point transform pair is entitled
    # to, sqrt(log2 N) ~ 4 eps, and no more.
    #
    # The signal here is white noise, which is the worst case for it: the
    # demod then spans the whole clip range rather than the +/-0.7 MHz
    # around blanking a real one occupies.  Measured, the channels land at
    # 1.4 to 3.0 steps on this input and at half a step on a real demod, so
    # a bound of four steps fails on a precision regression instead of
    # absorbing one.
    for name, expected in zip(names, expected_video):
        step = np.spacing(np.float32(np.abs(expected).max()))
        np.testing.assert_allclose(actual["video"][name], expected,
                                   rtol=0, atol=4 * step)

    rotdelay = rf.delays.get("video_rot", 0)
    expected_rfhpf = expected_rfhpf[
        rf.blockcut - rotdelay : -rf.blockcut_end - rotdelay
    ]
    np.testing.assert_allclose(actual["rfhpf"], expected_rfhpf, rtol=1e-6)


def test_ntsc_outputs_match_full_fft():
    _check_outputs("NTSC")


def test_pal_outputs_match_full_fft():
    _check_outputs("PAL")


def _check_efm(system):
    """The EFM samples from the folded half-spectrum transform are the
    samples the full complex transform produced.

    Fefm is one-sided, so ifft(X * Fefm) is analytic and only its real
    part is kept; computeefmhalffilter folds that into a filter for a
    real inverse transform.  The two are the same real signal, and after
    the int16 clip they are the same bytes - which is what lets this
    change land without re-recording an EFM output.
    """
    rf = RFDecode(system=system, decode_digital_audio=True)
    rng = np.random.default_rng(2718)
    signal = rng.integers(0, 16384, rf.blocklen).astype(np.float64)

    legacy = npfft.ifft(npfft.fft(signal) * rf.Filters["Fefm"]).real
    expected = np.int16(np.clip(legacy, -32768, 32767))

    np.testing.assert_array_equal(rf.demodblock(data=signal)["efm"], expected)


def test_pal_efm_matches_the_full_complex_transform():
    _check_efm("PAL")


def test_ntsc_efm_matches_the_full_complex_transform():
    _check_efm("NTSC")


def test_efm_hardware_front_end_folds_the_same_way(monkeypatch):
    """The alternative front end is one-sided too, so the fold holds for
    it as well (it is env-selected, and nothing else exercises it)."""
    monkeypatch.setenv("LDDECODE_EFM_FRONTEND", "hardware")
    _check_efm("PAL")


def test_the_folded_filter_halves_everything_but_dc_and_nyquist():
    rf = RFDecode(system="PAL", decode_digital_audio=True)
    full, half = rf.Filters["Fefm"], rf.Filters["Fefm_half"]
    assert half.shape[0] == rf.blocklen // 2 + 1
    np.testing.assert_array_equal(half[1:-1], full[1:rf.blocklen // 2] * 0.5)
    assert half[0] == full[0].real and half[-1] == full[rf.blocklen // 2].real


def test_the_centring_offset_is_transparent():
    """Subtracting blanking before the single-precision cast, and adding
    each channel's DC gain back afterwards, cancel exactly.

    The two constants are derived together in build_video_rfft_stack so
    that a filter rebuild cannot leave demodblock subtracting one centre
    and restoring another.  This is the assertion that would fail if it
    ever did: the same block decoded with the centring switched off must
    give the same channels, because all the centring changes is where
    float32 spends its mantissa.
    """
    rf = RFDecode(system="PAL")
    rng = np.random.default_rng(4)
    signal = rng.integers(0, 16384, rf.blocklen).astype(np.float64)

    centred = rf.demodblock(data=signal)["video"].copy()

    rf.Filters["FVideo_rfft_centre"] = 0.0
    rf.Filters["FVideo_rfft_dc"] = np.zeros_like(rf.Filters["FVideo_rfft_dc"])
    plain = rf.demodblock(data=signal)["video"]

    for name in ("demod", "demod_05", "demod_burst", "demod_pilot"):
        # Each is within four float32 steps of the exact answer (see
        # _check_outputs), so the two are within eight of each other.
        step = np.spacing(np.float32(np.abs(centred[name]).max()))
        np.testing.assert_allclose(centred[name], plain[name],
                                   rtol=0, atol=8 * step)


# --- the half-spectrum RF path -------------------------------------------
#
# RFVideo carries the Hilbert transform, so its negative half is zero and the
# whole-spectrum product demodblock used to build had a zero upper half.  The
# block path now filters the rfft of the block against half-length filters and
# zeroes that upper half itself.  These tests hold the new buffer to the old
# one, and the inverse of one to the inverse of the other.


def _rf_block(rf, rng, audio_carriers):
    """A block of RF, optionally carrying the two analog audio FM carriers
    strongly enough for pal_audio_carriers_present to see them."""
    signal = rng.integers(0, 16384, rf.blocklen).astype(np.float64)
    if audio_carriers:
        n = np.arange(rf.blocklen)
        for freq in (rf.SysParams["audio_lfreq"], rf.SysParams["audio_rfreq"]):
            signal += 3000.0 * np.cos(2 * np.pi * freq / rf.freq_hz * n)
    return signal


# Both helpers below multiply in place, because demodblock does.  That is not
# a stylistic detail: for complex128, `x *= y` and `x = x * y` are different
# numpy inner loops and round differently (measured here: ~33% of bins differ
# by one ulp on a 32768-point block).  A reference written in the other form
# fails against a correct implementation, so the reference has to be the same
# shape as the code it stands in for.


def _legacy_inverse_input(rf, signal, mtf_level, notch):
    """What demodblock used to hand the complex inverse: the whole spectrum
    multiplied by the whole-length filters."""
    filt = npfft.fft(signal) * rf.Filters["RFVideo"]
    if notch:
        filt *= rf.Filters["FcutPAL"]
    if mtf_level:
        filt *= rf.Filters["MTF"] ** mtf_level
    return filt


def _half_inverse_input(rf, signal, mtf_level, notch):
    """What it hands the inverse now: the positive half filtered by the
    half-length filters, written into a zeroed whole-length block."""
    filt = npfft.rfft(signal) * rf.Filters["RFVideo_half"]
    if notch:
        filt *= rf.Filters["FcutPAL_half"]
    if mtf_level:
        filt *= rf.mtf_response(mtf_level)
    block = np.zeros(rf.blocklen, dtype=filt.dtype)
    block[: rf.blocklen // 2 + 1] = filt
    return block


def _check_half_spectrum_path(system, mtf_level, notch):
    rf = RFDecode(system=system, full_rate_demod=True)
    rng = np.random.default_rng(4242)
    signal = _rf_block(rf, rng, audio_carriers=notch)

    # The notch is per block on PAL, so pin which arm of demodblock this case
    # actually exercises rather than assuming it.
    assert rf.pal_audio_carriers_present(npfft.rfft(signal)) is notch

    legacy = _legacy_inverse_input(rf, signal, mtf_level, notch)
    half = _half_inverse_input(rf, signal, mtf_level, notch)

    assert legacy.shape == half.shape == (rf.blocklen,)
    np.testing.assert_array_equal(half, legacy)

    # assert_array_equal compares with ==, which does not separate -0.0 from
    # 0.0, and the old upper half held whichever sign the input bins gave it.
    # The inverse is where that would show, so compare that too.
    np.testing.assert_array_equal(npfft.ifft(half), npfft.ifft(legacy))

    # ...and the block demodblock itself demodulated, so the test is pinned to
    # the production path and not just to a reimplementation of it.
    demod = unwrap_hilbert(npfft.ifft(legacy), rf.freq_hz)
    actual = rf.demodblock(data=signal, mtf_level=mtf_level, raw_mtf=True)
    np.testing.assert_array_equal(actual["video"]["demod_raw"], np.float32(demod))


def test_pal_half_spectrum_matches_with_the_carrier_notch_engaged():
    _check_half_spectrum_path("PAL", mtf_level=0, notch=True)


def test_pal_half_spectrum_matches_on_a_disc_without_analog_audio():
    _check_half_spectrum_path("PAL", mtf_level=0, notch=False)


def test_ntsc_half_spectrum_matches_at_a_non_zero_mtf_level():
    _check_half_spectrum_path("NTSC", mtf_level=1.37, notch=False)


def test_pal_half_spectrum_matches_at_a_non_zero_mtf_level_with_the_notch():
    _check_half_spectrum_path("PAL", mtf_level=0.62, notch=True)


@pytest.mark.parametrize("system", ["PAL", "NTSC"])
def test_the_half_filters_are_the_first_half_of_the_filters_they_came_from(system):
    rf = RFDecode(system=system)
    nrf = rf.blocklen // 2 + 1

    np.testing.assert_array_equal(rf.Filters["RFVideo_half"], rf.Filters["RFVideo"][:nrf])
    np.testing.assert_array_equal(rf.Filters["MTF_half"], rf.Filters["MTF"][:nrf])
    if "FcutPAL" in rf.Filters:
        np.testing.assert_array_equal(rf.Filters["FcutPAL_half"], rf.Filters["FcutPAL"][:nrf])

    # Views of the arrays they were cut from: the halves are what the block
    # path reads, so they must not be a second copy resident per worker.
    for name in ("RFVideo", "MTF"):
        assert rf.Filters[name + "_half"].base is rf.Filters[name]


@pytest.mark.parametrize("system", ["PAL", "NTSC"])
def test_the_rf_filter_kills_the_negative_half_outright(system):
    """The premise of the whole path: nothing above Nyquist survives RFVideo,
    so the buffer's upper half is zero however the block varies."""
    rf = RFDecode(system=system)
    np.testing.assert_array_equal(rf.Filters["RFVideo"][rf.blocklen // 2 + 1 :], 0)


@pytest.mark.parametrize("system", ["PAL", "NTSC"])
def test_the_mirrored_spectrum_is_the_whole_transform(system):
    """mirror_spectrum is what the consumers that still index a negative bin
    are fed; it has to be the full transform bit for bit."""
    rf = RFDecode(system=system)
    rng = np.random.default_rng(99)
    signal = _rf_block(rf, rng, audio_carriers=False)

    np.testing.assert_array_equal(rf.mirror_spectrum(npfft.rfft(signal)), npfft.fft(signal))


# --- the per-thread block scratch ------------------------------------------
#
# The block chain's intermediates are the same shape on every block, so they
# are allocated once per thread rather than once per block.  The parent
# demodulates from a thread pool through one RFDecode, so "per thread" is the
# load-bearing half of that sentence.


SCRATCH_BUFFERS = (
    "half_product",
    "inverse_in",
    "centred",
    "video_stack",
)


def _scratch_buffers(scratch):
    """The allocated buffers.  inverse_in is None on the half-rate chain,
    which has no zero-padded inverse to feed."""
    buffers = [getattr(scratch, name) for name in SCRATCH_BUFFERS]
    return [buffer for buffer in buffers if buffer is not None]


def _scratch_arrays(rf):
    return _scratch_buffers(rf._block_scratch(np.dtype(np.complex128)))


@pytest.mark.parametrize("system", ["PAL", "NTSC"])
def test_no_output_aliases_a_scratch_buffer(system):
    """Every array demodblock returns outlives the call, so none of them may
    be a view of a buffer the next block overwrites."""
    rf = RFDecode(system=system, decode_digital_audio=True, decode_analog_audio=44100)
    rng = np.random.default_rng(808)
    signal = _rf_block(rf, rng, audio_carriers=False)

    rv = rf.demodblock(data=signal, mtf_level=0.9, raw_mtf=True, cut=True)

    buffers = _scratch_arrays(rf)
    assert len(buffers) == 3
    returned = [rv[key] for key in ("rfhpf", "video", "efm", "audio") if key in rv]
    assert len(returned) == 4
    for array in returned:
        for buffer in buffers:
            assert not np.shares_memory(array, buffer)


@pytest.mark.parametrize("system", ["PAL", "NTSC"])
def test_the_scratch_is_allocated_once_and_reused(system):
    rf = RFDecode(system=system)
    rng = np.random.default_rng(809)
    signal = _rf_block(rf, rng, audio_carriers=False)

    rf.demodblock(data=signal, mtf_level=0.9, raw_mtf=True)
    first = rf._block_scratch(np.dtype(np.complex128))
    rf.demodblock(data=signal, mtf_level=0.9, raw_mtf=True)

    assert rf._block_scratch(np.dtype(np.complex128)) is first


@pytest.mark.parametrize("system", ["PAL", "NTSC"])
def test_the_inverse_input_upper_half_is_never_written(system):
    """It is zeroed once, at allocation, and the block path writes only the
    positive half.  If anything ever wrote above Nyquist, the next block would
    silently inherit it.

    Full-rate chain only: the half-rate one inverts the positive bins directly
    at their own length, so there is no padded buffer to keep clean - which is
    asserted below.
    """
    rf = RFDecode(system=system, full_rate_demod=True)
    rng = np.random.default_rng(810)
    nrf = rf.blocklen // 2 + 1

    for _ in range(3):
        rf.demodblock(data=_rf_block(rf, rng, audio_carriers=False), mtf_level=1.1, raw_mtf=True)
        scratch = rf._block_scratch(np.dtype(np.complex128))
        np.testing.assert_array_equal(scratch.inverse_in[nrf:], 0)


@pytest.mark.parametrize("system", ["PAL", "NTSC"])
def test_the_half_rate_chain_has_no_zero_padded_inverse_buffer(system):
    """The 512 KiB zeroed block the full-rate inverse needs is not allocated
    at all when the discriminator runs at half rate."""
    rf = RFDecode(system=system)
    rng = np.random.default_rng(811)

    rf.demodblock(data=_rf_block(rf, rng, audio_carriers=False))

    scratch = rf._block_scratch(np.dtype(np.complex128))
    assert scratch.inverse_in is None
    assert scratch.centred.shape == (rf.blocklen // 2,)
    assert scratch.video_stack.shape[1] == rf.blocklen // 4 + 1


def test_each_thread_gets_its_own_scratch():
    rf = RFDecode(system="PAL")
    seen = []
    lock = threading.Lock()

    def grab():
        scratch = rf._block_scratch(np.dtype(np.complex128))
        with lock:
            seen.append(scratch)

    threads = [threading.Thread(target=grab) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(seen) == 4
    assert len({id(scratch) for scratch in seen}) == 4


@pytest.mark.parametrize("system", ["PAL", "NTSC"])
def test_interleaved_threads_demodulate_as_one(system):
    """Two threads through one RFDecode, stepped into the block chain together
    by a barrier, produce what the serial calls produced.

    This is the arrangement parallel.DemodBlockCache actually runs (a thread
    pool over one decoder), and it is what a scratch buffer shared between
    threads would break - silently, and only under load.
    """
    rf = RFDecode(system=system, decode_digital_audio=True, decode_analog_audio=44100)
    rng = np.random.default_rng(4711)
    blocks = [_rf_block(rf, rng, audio_carriers=False) for _ in range(6)]

    expected = [
        rf.demodblock(data=block, mtf_level=0.9, raw_mtf=True, cut=True) for block in blocks
    ]

    actual = [None] * len(blocks)
    barrier = threading.Barrier(2)
    failures = []

    def work(indices):
        try:
            for index in indices:
                barrier.wait()
                actual[index] = rf.demodblock(
                    data=blocks[index], mtf_level=0.9, raw_mtf=True, cut=True
                )
        except Exception as error:  # pragma: no cover - reported below
            barrier.abort()
            failures.append(error)

    threads = [
        threading.Thread(target=work, args=(list(range(0, 6, 2)),)),
        threading.Thread(target=work, args=(list(range(1, 6, 2)),)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not failures
    for want, got in zip(expected, actual):
        assert got is not None
        for key in ("rfhpf", "efm"):
            np.testing.assert_array_equal(got[key], want[key])
        for name in want["video"].dtype.names:
            np.testing.assert_array_equal(got["video"][name], want["video"][name])
        for name in want["audio"].dtype.names:
            np.testing.assert_array_equal(got["audio"][name], want["audio"][name])
