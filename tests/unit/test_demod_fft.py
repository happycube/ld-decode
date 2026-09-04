import numpy as np
import scipy.fft as npfft

from lddecode.core import RFDecode
from lddecode.utils import unwrap_hilbert

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.dsp]


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
    rf = RFDecode(system=system)
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
