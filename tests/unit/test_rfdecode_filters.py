"""Unit tests for the filter set RFDecode builds.

RFDecode's constructor turns the parameter tables into about twenty FFT-domain
filters, and every sample of every decode passes through them.  The tests here
assert *properties* of those filters -- band edges, flatness, all-pass-ness,
which paths a correction is applied to -- and never their taps: the tap values
are an implementation detail that legitimately changes when a filter is
retuned, whereas "the group delay equaliser must not change amplitude" is a
contract that must not.

RFDecode needs no capture file (only its own packaged sinc table) and builds
in about 50 ms, so the real object is constructed rather than mocked.
"""

import numpy as np
import pytest
import scipy.signal as sps

from lddecode.filters import filtfft
from lddecode.rfdecode import RFDecode

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

SYSTEMS = ["NTSC", "PAL"]

#: IEC 60856 9.1.6 (PAL) / 60857 9.1.7 (NTSC) playback group delay, relative
#: to 0.5 MHz.  Restated from the specifications rather than imported, so that
#: an edit to the table in rfdecode.py has to be made deliberately in both
#: places.
IEC_GROUP_DELAY = {
    "PAL": (
        [0.0, 0.5e6, 2.0e6, 3.0e6, 4.0e6, 4.4336e6, 4.8e6, 5.5e6],
        [0.0, 0.0, 10e-9, 35e-9, 85e-9, 135e-9, 200e-9, 200e-9],
    ),
    "NTSC": (
        [0.0, 0.5e6, 2.0e6, 3.0e6, 3.58e6, 4.0e6, 4.2e6, 4.8e6],
        [0.0, 0.0, 15e-9, 45e-9, 80e-9, 135e-9, 200e-9, 200e-9],
    ),
}

#: Top of the band the equaliser is asked to correct, per system.
CHROMA_TOP = {"NTSC": 4.0e6, "PAL": 4.4336e6}


@pytest.fixture(scope="module")
def rfs():
    return {system: RFDecode(system=system) for system in SYSTEMS}


@pytest.fixture
def rf(rfs, request):
    return rfs[request.param]


parametrize_system = pytest.mark.parametrize("rf", SYSTEMS, indirect=True)


def binfreqs(rf):
    """Frequency of each FFT bin, folded to positive."""
    return np.abs(np.fft.fftfreq(rf.blocklen, 1.0 / rf.freq_hz))


def bin_at(rf, hz):
    return int(round(hz * rf.blocklen / rf.freq_hz))


def db(x):
    return 20 * np.log10(np.maximum(np.abs(x), np.finfo(float).tiny))


def group_delay(rf, response):
    """Group delay of an FFT-domain filter, in seconds per bin step."""
    phase = np.unwrap(np.angle(response))
    return -np.gradient(phase) / (2 * np.pi * (rf.freq_hz / rf.blocklen))


# --- construction -------------------------------------------------------


@parametrize_system
def test_the_decoder_builds_without_reading_a_capture(rf):
    """Nothing in the filter set depends on the input, which is what lets a
    worker process rebuild it from parameters alone."""
    expected = {
        "RFVideo", "MTF", "hilbert", "Frfhpf", "Frfhpf_half",
        "Fvideo_lpf", "Fdeemp", "Femp", "FVideo", "FVideo05", "FVideoBurst",
        "FVideoGD", "FVideo_rfft", "Fburst", "Finverse_mtf_base",
        "Fvideo_eq", "Fvideo_eq_auto",
    }

    assert expected <= set(rf.Filters)

    # Everything but the batched stack and the half-spectrum copy spans the
    # whole transform, so they can be multiplied together bin for bin.
    whole = expected - {"FVideo_rfft", "Frfhpf_half"}
    assert all(len(rf.Filters[k]) == rf.blocklen for k in whole)
    assert len(rf.Filters["Frfhpf_half"]) == rf.blocklen // 2 + 1


@parametrize_system
def test_the_line_length_is_the_sample_rate_times_the_line_period(rf):
    period_us = rf.SysParams["line_period"]

    assert rf.linelen == round(rf.freq_hz / (1e6 / period_us))
    assert rf.samplesperline == rf.freq / rf.linelen


@parametrize_system
def test_the_usable_block_is_trimmed_by_the_sync_filter_delay(rf):
    """The 0.5 MHz FIR is rolled back to align with the data, which leaves its
    delay's worth of samples unusable at the end of every block."""
    assert rf.blockcut_end == rf.Filters["F05_offset"]
    assert rf.blockcut == 1024


# --- the RF front end ---------------------------------------------------


@parametrize_system
def test_the_rf_bandpass_is_half_power_at_its_stated_edges(rf):
    """Butterworth edges, measured against the passband: the analytic signal
    doubles the positive frequencies, so full scale here is 2, not 1."""
    response = np.abs(rf.Filters["RFVideo"])

    for edge in ("video_bpf_low", "video_bpf_high"):
        at_edge = response[bin_at(rf, rf.DecoderParams[edge])]
        assert at_edge / 2.0 == pytest.approx(1 / np.sqrt(2), abs=0.02)


@parametrize_system
def test_the_rf_bandpass_rejects_out_of_band_energy(rf):
    low = rf.DecoderParams["video_bpf_low"]
    high = rf.DecoderParams["video_bpf_high"]
    # relative to the analytic signal's passband gain of 2
    response = np.abs(rf.Filters["RFVideo"]) / 2.0

    assert db(response[bin_at(rf, low / 3)]) < -18
    assert db(response[bin_at(rf, min(high * 1.4, rf.freq_hz_half * 0.98))]) < -18


@parametrize_system
def test_the_rf_path_is_analytic(rf):
    """The Hilbert transform is folded into RFVideo so the demodulator gets an
    analytic signal from one inverse transform; the negative half must be
    exactly zero, not merely small."""
    negative = rf.Filters["RFVideo"][rf.blocklen // 2 + 1:]

    assert np.array_equal(negative, np.zeros_like(negative))


@parametrize_system
def test_the_dropout_high_pass_half_spectrum_matches_the_full_one(rf):
    """demodblock uses the half spectrum to halve the transform cost; it has
    to be the same filter, or dropout detection quietly changes."""
    assert np.array_equal(
        rf.Filters["Frfhpf_half"], rf.Filters["Frfhpf"][: rf.blocklen // 2 + 1]
    )


# --- audio carrier notches ----------------------------------------------


@parametrize_system
def test_the_audio_carriers_are_notched_out(rf):
    for key, carrier in (("Fcutl", "audio_lfreq"), ("Fcutr", "audio_rfreq")):
        depth = db(rf.Filters[key][bin_at(rf, rf.SysParams[carrier])])
        assert depth < -30


def test_ntsc_folds_the_notches_into_the_rf_filter(rfs):
    """On NTSC the carriers sit outside the video sideband, so the notch is
    always safe to apply and is folded in once."""
    rf = rfs["NTSC"]
    assert "FcutPAL" not in rf.Filters
    assert db(np.abs(rf.Filters["RFVideo"])[bin_at(rf, rf.SysParams["audio_lfreq"])]) < -20


def test_pal_keeps_the_notch_separate(rfs):
    """On PAL the carriers are inside the video FM lower sideband, so an
    EFM-only disc would lose real signal; the notch is applied per block only
    when the carriers are actually there."""
    rf = rfs["PAL"]
    assert "FcutPAL" in rf.Filters
    carrier = bin_at(rf, rf.SysParams["audio_lfreq"])

    assert db(np.abs(rf.Filters["FcutPAL"])[carrier]) < -30
    assert db(np.abs(rf.Filters["RFVideo"])[carrier]) > -20


@pytest.mark.parametrize("system", SYSTEMS)
def test_a_disc_without_analogue_audio_gets_no_notch(system):
    rf = RFDecode(system=system, has_analog_audio=False)

    assert "Fcutl" not in rf.Filters
    assert "Fcutr" not in rf.Filters
    assert "FcutPAL" not in rf.Filters


def test_ac3_replaces_the_right_audio_carrier():
    """An AC3 disc carries the digital surround stream where the right analogue
    channel would be, so the notch has to move with it."""
    plain = RFDecode(system="NTSC")
    ac3 = RFDecode(system="NTSC", extra_options={"AC3": True})

    assert ac3.SysParams["audio_rfreq"] == plain.SysParams["audio_rfreq_AC3"]
    assert ac3.SysParams["audio_rfreq"] != plain.SysParams["audio_rfreq"]
    assert db(np.abs(ac3.Filters["Fcutr"])[bin_at(ac3, ac3.SysParams["audio_rfreq"])]) < -30


# --- the post-demodulation video path -----------------------------------


@parametrize_system
def test_the_video_low_pass_is_flat_across_the_passband(rf):
    cutoff = rf.DecoderParams["video_lpf_freq"]
    passband = np.abs(rf.Filters["Fvideo_lpf"])[: bin_at(rf, cutoff * 0.7) + 1]

    assert db(passband).min() > -0.5
    assert db(passband).max() < 1e-9        # a low-pass never has gain


@parametrize_system
def test_the_video_low_pass_is_half_power_at_its_cutoff(rf):
    cutoff = rf.DecoderParams["video_lpf_freq"]

    assert db(rf.Filters["Fvideo_lpf"][bin_at(rf, cutoff)]) == pytest.approx(-3.01, abs=0.05)


@parametrize_system
def test_the_video_low_pass_cutoff_follows_its_parameter(rf):
    """--vlpf has to actually move the filter; the override reaches the
    builder through DecoderParams."""
    moved = RFDecode(system=rf.system, decoder_params_override={"video_lpf_freq": 3.0e6})

    assert db(moved.Filters["Fvideo_lpf"][bin_at(moved, 3.0e6)]) == pytest.approx(
        -3.01, abs=0.05
    )


@parametrize_system
def test_de_emphasis_is_unity_at_dc_and_falls_with_frequency(rf):
    """The disc is recorded pre-emphasised; playback de-emphasis undoes it,
    which means unity at DC and monotonic attenuation above."""
    response = np.abs(rf.Filters["Fdeemp"])[: bin_at(rf, rf.DecoderParams["video_lpf_freq"])]

    assert response[0] == pytest.approx(1.0)
    assert np.all(np.diff(response) <= 1e-12)
    assert db(response[-1]) < -5


@parametrize_system
def test_pre_emphasis_is_exactly_the_inverse_of_de_emphasis(rf):
    """Femp exists to generate test signals that the de-emphasis will undo, so
    the product has to be one at every bin, not just in the passband."""
    assert np.abs(rf.Filters["Femp"] * rf.Filters["Fdeemp"] - 1.0).max() < 1e-12


@parametrize_system
def test_the_group_delay_equaliser_is_all_pass(rf):
    """Its whole purpose is to move phase without touching amplitude; any
    magnitude ripple here would show up as a luma response error."""
    assert np.abs(np.abs(rf.Filters["FVideoGD"]) - 1.0).max() < 1e-12
    assert rf.Filters["FVideoGD"][0] == 1.0


@parametrize_system
def test_the_group_delay_equaliser_has_a_real_impulse_response(rf):
    """Conjugate symmetry: an asymmetric spectrum would give the equaliser an
    imaginary part, which the real-valued output path would silently drop."""
    impulse = np.fft.ifft(rf.Filters["FVideoGD"])

    assert np.abs(impulse.imag).max() < 1e-12


@parametrize_system
def test_the_equalised_video_path_meets_the_iec_group_delay_curve(rf):
    """This is the contract the equaliser exists for: low-pass plus equaliser
    reproduces the group delay the disc was pre-distorted against, so the
    chroma sidebands arrive level with luma."""
    freqs, delays = IEC_GROUP_DELAY[rf.system]
    binf = binfreqs(rf)
    combined = rf.Filters["Fvideo_lpf"] * rf.Filters["FVideoGD"]

    measured = group_delay(rf, combined)
    measured -= measured[np.argmin(np.abs(binf - 0.5e6))]
    target = np.interp(binf, freqs, delays)

    band = (binf >= 0.5e6) & (binf <= CHROMA_TOP[rf.system])
    assert np.abs(measured[band] - target[band]).max() < 1e-9      # 1 ns


@parametrize_system
def test_the_equaliser_leaves_the_low_frequencies_alone(rf):
    """Below 0.4 MHz the residual is forced to zero: there is nothing to
    correct there, and integrating noise into the phase would tilt the
    whole line."""
    binf = binfreqs(rf)
    low = rf.Filters["FVideoGD"][binf < 0.4e6]

    assert np.allclose(low, 1.0)


@parametrize_system
def test_the_output_video_filter_is_the_low_pass_and_de_emphasis(rf):
    """FVideo = lpf * deemp**strength * groupdelay, and the group delay term
    is all-pass, so the amplitude response is the first two alone."""
    strength = rf.DecoderParams["video_deemp_strength"]
    expected = np.abs(rf.Filters["Fvideo_lpf"] * rf.Filters["Fdeemp"] ** strength)

    assert np.abs(np.abs(rf.Filters["FVideo"]) - expected).max() < 1e-12


# --- delay compensation -------------------------------------------------


@parametrize_system
def test_the_sync_filter_delay_is_compensated_in_the_frequency_domain(rf):
    """A circular shift folded into the filter, instead of an np.roll that
    would copy the whole block.  The FIR's own delay is its half-length."""
    taps = sps.firwin(65, [0.5 / rf.freq_half], pass_zero=True)
    plain = filtfft((taps, [1.0]), rf.blocklen)
    shift = np.exp(1j * 2 * np.pi * 32 * np.arange(rf.blocklen) / rf.blocklen)

    assert int(np.argmax(np.abs(np.fft.ifft(plain).real))) == 32
    assert int(np.argmax(np.abs(np.fft.ifft(plain * shift).real))) == 0
    assert rf.Filters["F05_offset"] == 32


@parametrize_system
def test_the_burst_filter_delay_is_compensated_too(rf):
    taps = sps.firwin(81, rf.notchrange(rf.SysParams["fsc_mhz"], 0.2), pass_zero=False)
    plain = filtfft((taps, [1.0]), rf.blocklen)
    shift = np.exp(1j * 2 * np.pi * 40 * np.arange(rf.blocklen) / rf.blocklen)

    assert int(np.argmax(np.abs(np.fft.ifft(plain).real))) == 40
    assert int(np.argmax(np.abs(np.fft.ifft(plain * shift).real))) == 0
    assert rf.Filters["FVideoBurst_offset"] == 40


# --- inverse MTF and the dynamic EQ -------------------------------------


@parametrize_system
def test_the_inverse_mtf_base_is_a_real_boost_above_the_crossover(rf):
    """Real-valued by construction, so raising it to a strength can lift
    chroma amplitude without contributing any differential phase."""
    base = rf.Filters["Finverse_mtf_base"]
    binf = binfreqs(rf)

    assert not np.iscomplexobj(base)
    assert np.all(base[binf < 2.0e6] == 1.0)
    assert np.all(base >= 1.0)
    assert base.max() == pytest.approx(20.0)       # the 0.05 clip on the MTF


@parametrize_system
def test_the_2t_gain_is_unity_at_zero_strength(rf):
    """The servo divides its pulse-to-bar reading by this; at neutral it must
    be exactly one, or the two control loops start from a biased measurement."""
    assert rf.inverse_mtf_2t_peak_gain(0) == 1.0
    assert rf.inverse_mtf_2t_peak_gain(0.0) == 1.0


@parametrize_system
def test_the_2t_gain_rises_with_the_inverse_mtf_strength(rf):
    gains = [rf.inverse_mtf_2t_peak_gain(s) for s in (0.0, 0.25, 0.5, 1.0, 2.0)]

    assert gains == sorted(gains)
    assert gains[-1] > gains[0]


@parametrize_system
def test_the_2t_gain_is_cached_per_strength(rf):
    """It costs a full-block FFT, and the servo asks for it every field."""
    first = rf.inverse_mtf_2t_peak_gain(0.375)

    assert rf.inverse_mtf_2t_peak_gain(0.375) is first
    assert round(0.375, 6) in rf._imtf_2t_gain_cache


@parametrize_system
def test_the_eq_2t_gain_is_unity_with_no_anchors(rf):
    assert rf.video_eq_2t_peak_gain(None) == 1.0
    assert rf.video_eq_2t_peak_gain([]) == 1.0


@parametrize_system
def test_the_eq_2t_gain_follows_the_sign_of_the_anchors(rf):
    """A boost in the band the 2T pulse occupies raises it, a cut lowers it;
    getting the sign wrong would drive the MTF servo the wrong way."""
    assert rf.video_eq_2t_peak_gain([(3.0e6, 3.0)]) > 1.0
    assert rf.video_eq_2t_peak_gain([(3.0e6, -3.0)]) < 1.0


@parametrize_system
def test_the_video_eq_hits_its_anchor_gains(rf):
    points = [(1.0e6, 2.0), (3.0e6, -4.0)]
    eq = rf.build_video_eq(points)

    for freq_hz, gain_db in points:
        assert db(eq[bin_at(rf, freq_hz)]) == pytest.approx(gain_db, abs=1e-3)


@parametrize_system
def test_the_video_eq_is_pinned_to_unity_outside_its_anchors(rf):
    """Held at 0 dB at DC and from half a megahertz past the last anchor, so
    a per-disc EQ measured over the multiburst band cannot disturb sync or
    the chroma band above it."""
    eq = rf.build_video_eq([(1.0e6, 2.0), (3.0e6, -4.0)])

    assert eq[0] == pytest.approx(1.0)
    assert eq[bin_at(rf, 3.6e6)] == pytest.approx(1.0)
    assert eq[bin_at(rf, 6.0e6)] == pytest.approx(1.0)


@parametrize_system
def test_the_video_eq_is_zero_phase(rf):
    """Returned as a real array, so applying it cannot move phase -- which is
    what makes it safe to use on a signal whose differential phase matters."""
    eq = rf.build_video_eq([(1.0e6, 2.0), (3.0e6, -4.0)])
    half = rf.blocklen // 2

    assert not np.iscomplexobj(eq)
    assert np.array_equal(eq[1:half], eq[:half:-1])


@parametrize_system
def test_no_anchors_gives_a_flat_eq(rf):
    assert np.array_equal(rf.build_video_eq(None), np.ones(rf.blocklen))
    assert np.array_equal(rf.build_video_eq([]), np.ones(rf.blocklen))


# --- worker parity ------------------------------------------------------


@pytest.mark.parametrize("system", SYSTEMS)
@pytest.mark.parametrize("change", [
    {"inverse_mtf_strength": 0.7},
    {"video_eq_auto": [(2.0e6, 1.5)]},
    {"inverse_mtf_strength": 0.4, "video_eq_auto": [(2.5e6, -2.0)]},
])
def test_the_cheap_rebuild_matches_a_full_one(system, change):
    """recompute_fvideo() skips the audio, EFM and delay work when only the
    video output filter has changed.  Worker processes rebuild through
    computefilters() instead, so any divergence between the two would make a
    parallel decode differ from a serial one -- which is exactly what the
    bit-identity contract forbids.
    """
    full = RFDecode(system=system)
    full.DecoderParams.update(change)
    full.computefilters()

    cheap = RFDecode(system=system)
    cheap.DecoderParams.update(change)
    cheap.recompute_fvideo()

    assert np.array_equal(full.Filters["FVideo"], cheap.Filters["FVideo"])
    assert np.array_equal(full.Filters["FVideo_rfft"], cheap.Filters["FVideo_rfft"])


@parametrize_system
def test_the_stacked_output_filters_are_the_ones_demodblock_uses(rf):
    """demodblock does one batched inverse transform over FVideo_rfft; the
    stack has to stay in step with the individual filters after any rebuild."""
    half = rf.blocklen // 2 + 1
    expected = [rf.Filters[k][:half] for k in ("FVideo", "FVideo05", "FVideoBurst")]
    if rf.system == "PAL":
        expected.append(rf.Filters["FVideoPilot"][:half])

    assert np.array_equal(rf.Filters["FVideo_rfft"], np.asarray(expected))


# --- the EFM equaliser --------------------------------------------------


@pytest.mark.parametrize("system", SYSTEMS)
def test_the_efm_filter_is_built_only_for_a_digital_audio_decode(system):
    assert "Fefm" not in RFDecode(system=system).Filters
    assert "Fefm" in RFDecode(system=system, decode_digital_audio=True).Filters


@pytest.mark.parametrize("system, upper_hz", [("NTSC", 1.6e6), ("PAL", 1.75e6)])
def test_the_efm_filter_passes_only_the_efm_band(system, upper_hz):
    """The super-Gaussian band-pass sets the edges; above it there is nothing
    but video sideband, and the PLL would lock to that instead."""
    rf = RFDecode(system=system, decode_digital_audio=True)
    response = np.abs(rf.Filters["Fefm"])

    assert response[bin_at(rf, upper_hz)] > 0.0
    assert response[bin_at(rf, upper_hz * 1.5)] == pytest.approx(0.0, abs=1e-9)
    assert response[0] == pytest.approx(0.0, abs=1e-9)
    assert response[bin_at(rf, 0.8e6)] > 1.0


def test_the_two_systems_use_different_efm_equalisation():
    """PAL's curve was retuned against Domesday captures; NTSC keeps the
    legacy one.  Pinned so that a change to one is not silently applied to
    both."""
    ntsc = RFDecode(system="NTSC", decode_digital_audio=True)
    pal = RFDecode(system="PAL", decode_digital_audio=True)
    peak = 0.8e6

    assert not np.array_equal(ntsc.Filters["Fefm"], pal.Filters["Fefm"])
    assert np.abs(pal.Filters["Fefm"][bin_at(pal, peak)]) > np.abs(
        ntsc.Filters["Fefm"][bin_at(ntsc, peak)]
    )
