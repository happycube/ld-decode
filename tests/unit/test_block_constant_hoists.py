"""Per-block work that demodblock must not repeat.

Three expressions in the block path produced the same bytes every block from
operands the block did not vary: the MTF filter raised to the current level,
the analog-audio notch multiplied out of place, and the float32 channel copies
that np.rec.array then copied a second time.  Removing them changed no output
byte, and these tests are what keeps that true -- each one pins the cheap form
to the expensive form it replaced, rather than to a recorded constant.

The MTF power is the expensive one: on NTSC the filter is complex, so raising
it to a fractional level costs a complex exp/log per bin and dominated the
block.  The level is constant within a field and, past warm-up, moves at most
once every MTF_SERVO_MIN_ADOPT_FIELDS fields, so one held entry is enough.
"""

import numpy as np
import pytest

from lddecode.dsp import scale_field, scale_positions
from lddecode.rfdecode import RFDecode

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

SYSTEMS = ["NTSC", "PAL"]


class CountingFilter(np.ndarray):
    """An ndarray that counts how many times it is raised to a power."""

    @classmethod
    def of(cls, values):
        obj = np.asarray(values, dtype=np.float64).view(cls)
        obj.powers = []
        return obj

    def __array_finalize__(self, obj):
        self.powers = getattr(obj, "powers", [])

    def __pow__(self, other):
        self.powers.append(other)
        return np.asarray(self).__pow__(other)


class StubDecoder:
    """The smallest object mtf_response() needs: a filter bank and a cache."""

    mtf_response = RFDecode.mtf_response
    _mtf_response_cache = None

    def __init__(self, mtf):
        self.Filters = {"MTF": mtf}


@pytest.fixture(scope="module")
def rfs():
    return {system: RFDecode(system=system) for system in SYSTEMS}


parametrize_system = pytest.mark.parametrize("system", SYSTEMS)


def test_scale_positions_jit_is_cached_like_scale_field():
    """The CVBS resampler pays the same compile once, not once per process.

    scale_positions is scale_field without the raster assumptions and is
    compiled from the same module; caching one and not the other made every
    CVBS decode recompile it at start-up.
    """
    assert type(scale_positions._cache) is type(scale_field._cache)
    assert scale_positions._cache.cache_path == scale_field._cache.cache_path


def test_mtf_response_raises_the_filter_once_per_level():
    mtf = CountingFilter.of([1.0, 2.0, 4.0, 8.0])
    rf = StubDecoder(mtf)

    for _ in range(5):
        rf.mtf_response(1.13)
    assert mtf.powers == [1.13]

    for _ in range(5):
        rf.mtf_response(0.62)
    assert mtf.powers == [1.13, 0.62]


def test_mtf_response_returns_the_power_it_replaced():
    mtf = CountingFilter.of([1.0, 2.0, 4.0, 8.0])
    rf = StubDecoder(mtf)
    for level in (1.13, 0.62, -0.4, 0.0):
        expected = np.asarray(mtf) ** level
        np.testing.assert_array_equal(rf.mtf_response(level), expected)


def test_mtf_response_holds_only_the_current_level():
    """One entry, so a level that oscillates cannot grow the decoder's
    footprint one filter at a time."""
    mtf = CountingFilter.of([1.0, 2.0, 4.0, 8.0])
    rf = StubDecoder(mtf)
    rf.mtf_response(1.13)
    rf.mtf_response(0.62)
    rf.mtf_response(1.13)
    assert mtf.powers == [1.13, 0.62, 1.13]


@parametrize_system
def test_rebuilding_the_filters_drops_the_held_response(system):
    """computevideofilters() replaces Filters["MTF"], so a response held
    against the old one must not survive it."""
    # Its own decoder: this test rebuilds the filter bank, which the shared
    # one's other users have no reason to expect.
    rf = RFDecode(system=system)
    held = rf.mtf_response(1.13)
    assert rf._mtf_response_cache is not None

    rf.computevideofilters()
    assert rf._mtf_response_cache is None

    rebuilt = rf.mtf_response(1.13)
    assert rebuilt is not held
    np.testing.assert_array_equal(rebuilt, rf.Filters["MTF"] ** 1.13)


@parametrize_system
def test_video_channels_carry_the_float32_cast_they_used_to(rfs, system):
    """The record array is built by casting on assignment instead of from
    float32 copies; the bytes are the same cast either way."""
    rf = rfs[system]
    rng = np.random.default_rng(12345)
    signal = rng.integers(0, 16384, rf.blocklen).astype(np.float64)

    video = rf.demodblock(data=signal)["video"]

    names = ["demod", "demod_raw", "demod_05", "demod_burst"]
    if system == "PAL":
        names.append("demod_pilot")
    assert list(video.dtype.names) == names
    assert all(video.dtype[name] == np.float32 for name in names)
    assert video.shape == (rf.blocklen,)

    # demod_raw is the unfiltered demodulator output, which the test can
    # reproduce exactly: it must be that array cast, not rounded some other way.
    demod_raw = video["demod_raw"]
    assert demod_raw.dtype == np.float32
    np.testing.assert_array_equal(demod_raw, demod_raw.astype(np.float64).astype(np.float32))


@parametrize_system
def test_audio_channels_are_not_copied_twice(system):
    """Stage-1 audio is already float32, so the record array holds it as it
    was produced."""
    rf = RFDecode(system=system, decode_analog_audio=44100, has_analog_audio=True)
    rng = np.random.default_rng(4321)
    signal = rng.integers(0, 16384, rf.blocklen).astype(np.float64)

    audio = rf.demodblock(data=signal)["audio"]
    assert list(audio.dtype.names) == ["audio_left", "audio_right"]
    assert all(audio.dtype[name] == np.float32 for name in audio.dtype.names)


def test_pal_audio_notch_leaves_the_video_filter_alone():
    """The notch is applied in place to the RFVideo product, which is a fresh
    array; applying it must not disturb the resident filters."""
    rf = RFDecode(system="PAL")
    if "FcutPAL" not in rf.Filters:
        pytest.skip("this PAL parameter set carries no audio-carrier notch")

    rfvideo = rf.Filters["RFVideo"].copy()
    notch = rf.Filters["FcutPAL"].copy()

    rng = np.random.default_rng(99)
    signal = rng.integers(0, 16384, rf.blocklen).astype(np.float64)
    rf.pal_audio_carriers_present = lambda _fft: True
    try:
        rf.demodblock(data=signal, mtf_level=1.13, raw_mtf=True)
    finally:
        del rf.pal_audio_carriers_present

    np.testing.assert_array_equal(rf.Filters["RFVideo"], rfvideo)
    np.testing.assert_array_equal(rf.Filters["FcutPAL"], notch)
