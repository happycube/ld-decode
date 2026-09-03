"""Unit tests for the LD-V4300D coherent spur subtraction in rfdecode.

All blocks are synthetic: white noise sets the window's median amplitude,
optional line-rate comb lines model legitimate FM sidebands of static
video, and injected tones model the player's 8.4672 MHz digital-audio
master clock and its +-88.2 kHz satellites.
"""

import numpy as np
import pytest
import scipy.fft as npfft

from lddecode.rfdecode import RFDecode

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

FS = 40e6
BLOCKLEN = 32 * 1024
LINE_RATE = 15625.0  # EBU Tech 3280-E: 64 us PAL line

# With rectangular-window FFT of N samples: unit-amplitude tone peak is
# N/2; white noise sigma=1 gives a Rayleigh |X| with median
# sigma * sqrt(N/2) * sqrt(ln 4).  Used to place tones at a chosen
# multiple of the window's median amplitude.
NOISE_MEDIAN = np.sqrt(BLOCKLEN / 2) * np.sqrt(np.log(4))
TONE_GAIN = BLOCKLEN / 2


@pytest.fixture(scope="module")
def rf():
    return RFDecode(
        system="PAL",
        decode_digital_audio=False,
        has_analog_audio=False,
        extra_options={"PAL_V4300D_CoherentSubtract": True},
    )


def tone(freq_hz, med_ratio, phase=0.0):
    """A real tone whose FFT peak is med_ratio x the noise median amplitude."""
    n = np.arange(BLOCKLEN)
    amp = med_ratio * NOISE_MEDIAN / TONE_GAIN
    return amp * np.cos(2 * np.pi * freq_hz / FS * n + phase)


def noise_block(rng):
    """Noise plus a video-FM-carrier stand-in at 7.4 MHz: the filter's
    no-video guard requires a carrier band peak well over the spur window
    median (real captures measure 58-2850x; dead regions 11-21x)."""
    return rng.normal(0.0, 1.0, BLOCKLEN) + tone(7.4e6, 400.0)


def dead_block(rng):
    """Noise only - a capture region with no video carrier."""
    return rng.normal(0.0, 1.0, BLOCKLEN)


def comb(f_start, f_stop, med_ratio, rng):
    """Line-rate comb of equal-amplitude tones with random phases,
    modelling legitimate FM sidebands of static video content."""
    x = np.zeros(BLOCKLEN)
    f = f_start
    while f < f_stop:
        x += tone(f, med_ratio, phase=rng.uniform(0, 2 * np.pi))
        f += LINE_RATE
    return x


def residual_amplitude(x, freq_hz):
    """Amplitude of the tone at freq_hz remaining in the real signal x."""
    n = np.arange(BLOCKLEN)
    e = np.exp(-2j * np.pi * freq_hz / FS * n)
    return 2 * np.abs(np.dot(x, e)) / BLOCKLEN


def run(rf, x):
    return npfft.ifft(rf.v4300d_coherent_subtract(npfft.fft(x))).real


def test_clock_spur_removed_including_off_bin_leakage(rf):
    rng = np.random.default_rng(12345)
    # 400 Hz off the clock nominal: off-bin (bin width ~1221 Hz), inside
    # the +-3 kHz anchor search
    f_spur = rf.V4300D_CLOCK_HZ + 400.0
    x = noise_block(rng) + tone(f_spur, 20.0)
    out = run(rf, x)
    before = residual_amplitude(x, f_spur)
    after = residual_amplitude(out, f_spur)
    assert after < 0.1 * before


def test_spur_below_legacy_gate_still_removed(rf):
    # 15x median is far below the generic 40x gate that the old detector
    # needed; program-content blocks measure 14-53x on real captures.
    rng = np.random.default_rng(12346)
    f_spur = rf.V4300D_CLOCK_HZ - 800.0
    x = noise_block(rng) + tone(f_spur, 15.0)
    out = run(rf, x)
    assert residual_amplitude(out, f_spur) < 0.1 * residual_amplitude(x, f_spur)


def test_satellites_removed_once_main_confirmed(rf):
    rng = np.random.default_rng(12347)
    f_main = rf.V4300D_CLOCK_HZ + 200.0
    f_sat = f_main + rf.V4300D_SATELLITE_HZ
    # note: a strong tone's own leakage skirts inflate the window median,
    # so the realised gate ratios sit below the nominal med_ratio inputs
    x = noise_block(rng) + tone(f_main, 25.0) + tone(f_sat, 12.0)
    out = run(rf, x)
    assert residual_amplitude(out, f_main) < 0.1 * residual_amplitude(x, f_main)
    assert residual_amplitude(out, f_sat) < 0.35 * residual_amplitude(x, f_sat)


def test_satellite_without_main_left_alone(rf):
    # A lone line at a satellite frequency with no main clock line is not
    # the V4300D signature; below the generic 40x gate it must survive.
    rng = np.random.default_rng(12348)
    f_sat = rf.V4300D_CLOCK_HZ + rf.V4300D_SATELLITE_HZ
    x = noise_block(rng) + tone(f_sat, 10.0)
    fft_in = npfft.fft(x)
    fft_out = rf.v4300d_coherent_subtract(fft_in)
    assert fft_out is fft_in  # untouched, returned as-is


def test_legitimate_comb_line_at_clock_frequency_protected(rf):
    # Static video content whose sideband comb happens to put a line at
    # the clock frequency: comparable comb neighbours must veto the
    # anchored gate (each line is well below the generic 40x gate too).
    rng = np.random.default_rng(12349)
    f_line = rf.V4300D_CLOCK_HZ + 500.0
    x = noise_block(rng) + comb(f_line - 12 * LINE_RATE, f_line + 12 * LINE_RATE, 15.0, rng)
    fft_in = npfft.fft(x)
    fft_out = rf.v4300d_coherent_subtract(fft_in)
    assert fft_out is fft_in


def test_clock_spur_removed_from_within_comb(rf):
    # The real program-content case: spur standing above a legitimate comb.
    rng = np.random.default_rng(12350)
    f_spur = rf.V4300D_CLOCK_HZ - 300.0
    x = noise_block(rng) + comb(8.37e6, 8.65e6, 4.0, rng) + tone(f_spur, 30.0)
    out = run(rf, x)
    assert residual_amplitude(out, f_spur) < 0.2 * residual_amplitude(x, f_spur)
    # a comb line two pitches away must survive
    f_keep = f_spur + 2 * LINE_RATE
    assert residual_amplitude(out, f_keep) > 0.7 * residual_amplitude(x, f_keep)


def test_generic_lone_tone_still_caught(rf):
    # A strong unexpected tone away from every anchor: the legacy >40x
    # lone-tone gate must still remove it.
    rng = np.random.default_rng(12351)
    # ~44 kHz from the nearest anchor, bin-aligned so scalloping does not
    # eat into the >40x gate margin (skirt-inflated median does a little)
    f_spur = round(8.51e6 / (FS / BLOCKLEN)) * (FS / BLOCKLEN)
    x = noise_block(rng) + tone(f_spur, 100.0)
    out = run(rf, x)
    assert residual_amplitude(out, f_spur) < 0.1 * residual_amplitude(x, f_spur)


def test_pure_noise_is_a_noop(rf):
    rng = np.random.default_rng(12352)
    fft_in = npfft.fft(noise_block(rng))
    fft_out = rf.v4300d_coherent_subtract(fft_in)
    assert fft_out is fft_in


def test_input_fft_never_mutated(rf):
    rng = np.random.default_rng(12353)
    x = noise_block(rng) + tone(rf.V4300D_CLOCK_HZ, 20.0)
    fft_in = npfft.fft(x)
    saved = fft_in.copy()
    rf.v4300d_coherent_subtract(fft_in)
    np.testing.assert_array_equal(fft_in, saved)


def test_deterministic_per_block(rf):
    rng = np.random.default_rng(12354)
    x = noise_block(rng) + tone(rf.V4300D_CLOCK_HZ + 250.0, 20.0)
    fft_in = npfft.fft(x)
    out1 = rf.v4300d_coherent_subtract(fft_in.copy())
    out2 = rf.v4300d_coherent_subtract(fft_in.copy())
    np.testing.assert_array_equal(out1, out2)


def test_no_video_guard_leaves_dead_regions_untouched(rf):
    # A spur with no video carrier present (lead-in noise, dead regions):
    # nothing to protect, nothing to beat against - must be bit-exact
    # untouched so cold-start sync hunting sees the unfiltered signal.
    rng = np.random.default_rng(12355)
    x = dead_block(rng) + tone(rf.V4300D_CLOCK_HZ, 30.0)
    fft_in = npfft.fft(x)
    fft_out = rf.v4300d_coherent_subtract(fft_in)
    assert fft_out is fft_in
