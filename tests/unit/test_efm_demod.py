"""Unit tests for lddecode.efm_demod -- symbol-rate EFM timing recovery.

The demodulator is exercised end to end on synthesised EFM waveforms: legal
T sequences (588-channel-bit frames opening with the T11-T11 sync pair) are
NRZI-coded at the channel bit rate, sampled at 40 MHz and band-limited to
1.75 MHz -- the shape the real equaliser hands the demodulator.  Because the
generator knows the T sequence, recovery can be asserted exactly, and the
Phase 1 scorer (lddecode.efm_score) doubles as the acceptance oracle.

The decimation and conditioning stages are also tested in isolation: filter
response and alias rejection against their stated tolerances, and exact
chunking invariance, which is what lets decoder.py feed the demodulator one
field at a time.

These run compiled -- _TimingCore is a Numba jitclass, so a typing
regression fails here rather than part-way through a decode.
"""

import numpy as np
import pytest

from lddecode.efm_demod import (
    CONF_LEGALISED,
    CONF_LOWCAP,
    CONF_RESTORED,
    EFM_BIT_RATE_HZ,
    EFMTimingDemod,
    StreamingConditioner,
    StreamingDecimator,
    decimation_stages,
    halfband_taps,
)
from lddecode.efm_pll import EFM_PLL
from lddecode.efm_score import pack_t_conf, score_t_values

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

FS = 40e6

# One legal 588-channel-bit EFM frame opening with the T11-T11 sync pair.
FRAME = [11, 11, 3] + [10] * 56 + [3]
assert sum(FRAME) == 588


def efm_waveform(
    tvals,
    fs=FS,
    bit_rate=EFM_BIT_RATE_HZ,
    cutoff=1.75e6,
    amplitude=12000.0,
    rate_scale=1.0,
    wow_amp=0.0,
    wow_hz=0.0,
    noise_rms=0.0,
    seed=1,
):
    """A band-limited NRZI waveform carrying the given T sequence.

    ``rate_scale`` applies a static channel-rate offset; ``wow_amp``/
    ``wow_hz`` a sinusoidal rate modulation (disc wow).  Noise is seeded and
    additive.  Returns int16 samples, the dtype decoder.py delivers.
    """
    edges_bits = np.cumsum(np.asarray(tvals, dtype=np.float64))
    rate = bit_rate * rate_scale
    n_samp = int(edges_bits[-1] / rate * fs) + 100
    t = np.arange(n_samp) / fs
    if wow_amp > 0:
        phase = rate * (
            t - (wow_amp / (2 * np.pi * wow_hz)) * (np.cos(2 * np.pi * wow_hz * t) - 1.0)
        )
    else:
        phase = rate * t
    level = np.where(np.searchsorted(edges_bits, phase, side="right") % 2 == 0, 1.0, -1.0)
    x = level * amplitude
    spectrum = np.fft.rfft(x)
    spectrum[np.fft.rfftfreq(len(x), 1 / fs) > cutoff] = 0
    x = np.fft.irfft(spectrum, len(x))
    if noise_rms > 0:
        x = x + np.random.default_rng(seed).normal(0, noise_rms, len(x))
    return np.clip(x, -32767, 32767).astype(np.int16)


def demod(signal, chunk=None, **kwargs):
    """Run a fresh demodulator over the signal; returns (t_values, conf)."""
    d = EFMTimingDemod(FS, **kwargs)
    if chunk is None:
        return d.process(signal).copy(), d.conf_view().copy()
    ts, cs = [], []
    for start in range(0, len(signal), chunk):
        ts.append(d.process(signal[start : start + chunk]).copy())
        cs.append(d.conf_view().copy())
    return np.concatenate(ts), np.concatenate(cs)


@pytest.fixture(scope="module")
def clean_signal():
    return efm_waveform(FRAME * 60)


@pytest.fixture(scope="module")
def clean_result(clean_signal):
    return demod(clean_signal)


# --- Task 2.1: half-band decimation ----------------------------------------


def test_halfband_taps_are_halfband():
    taps = halfband_taps()
    mid = len(taps) // 2
    offsets = np.arange(len(taps)) - mid

    # The defining property: every even offset except the centre is zero,
    # and the DC gain is exactly one (so cascading stages cannot drift the
    # signal level).
    assert np.all(taps[(offsets % 2 == 0) & (offsets != 0)] == 0.0)
    assert taps.sum() == pytest.approx(1.0, abs=1e-15)
    np.testing.assert_allclose(taps, taps[::-1], atol=0)  # linear phase


def test_halfband_passband_is_flat_over_the_efm_band():
    response = np.abs(np.fft.rfft(halfband_taps(), 8192))
    freqs = np.linspace(0.0, 0.5, len(response))

    # Stated tolerance: +/-0.011 dB up to 0.10 fs.  The EFM band's 1.9 MHz
    # edge is 0.095 fs at the tightest stage of a >= 8 MHz cascade (the
    # 20 MHz -> 10 MHz stage), so flatness there means the cascade never
    # tilts the band the equaliser just shaped.
    passband_db = 20 * np.log10(response[freqs <= 0.10])
    assert passband_db.max() < 0.011
    assert passband_db.min() > -0.011


def test_halfband_stopband_rejects_the_alias_band():
    response = np.abs(np.fft.rfft(halfband_taps(), 8192))
    freqs = np.linspace(0.0, 0.5, len(response))

    # Frequencies at/above 0.40 fs fold onto the 0-0.10 fs EFM band after
    # the decimation by two.  Stated rejection: at least 80 dB there.
    stopband_db = 20 * np.log10(response[freqs >= 0.40])
    assert stopband_db.max() < -80.0


@pytest.mark.parametrize("fs_in,stages", [(40e6, 2), (35e6, 2), (30e6, 1), (8e6, 0)])
def test_decimation_keeps_the_rate_at_or_above_eight_megahertz(fs_in, stages):
    # The rule from the design: halve while the result stays >= 8 MHz, so
    # the 0-1.9 MHz band plus its transition edges keep clear headroom.
    assert decimation_stages(fs_in) == stages
    out_rate = fs_in / 2 ** decimation_stages(fs_in)
    assert out_rate >= 8e6


def test_decimator_passes_an_in_band_tone():
    dec = StreamingDecimator(FS)
    n = np.arange(200000)
    tone = np.sin(2 * np.pi * 1.5e6 / FS * n)

    out = dec.process(tone)

    assert dec.output_rate_hz == 10e6
    assert len(out) == len(tone) // 4
    # Amplitude preserved within 1% once the filter delay has passed.
    assert np.abs(out[100:]).max() == pytest.approx(1.0, rel=0.01)


def test_decimator_rejects_an_alias_band_tone():
    dec = StreamingDecimator(FS)
    n = np.arange(200000)
    tone = np.sin(2 * np.pi * 9e6 / FS * n)

    out = dec.process(tone)

    # 9 MHz would fold to 1 MHz -- into the middle of the EFM band -- at the
    # 10 MHz output rate; the stated 80 dB stopband keeps the residual four
    # orders of magnitude down.
    assert np.abs(out[100:]).max() < 1e-3


def test_decimator_is_unaffected_by_how_the_input_is_chunked():
    rng = np.random.default_rng(12345)
    signal = rng.normal(0, 1000, 100001)

    whole = StreamingDecimator(FS).process(signal)
    chunked_dec = StreamingDecimator(FS)
    pieces = [
        chunked_dec.process(signal[start : start + 997]) for start in range(0, len(signal), 997)
    ]

    # Odd chunk sizes exercise the carried decimation phase: with 997-sample
    # chunks the keep-every-second-sample parity flips on every call.
    assert np.array_equal(np.concatenate(pieces), whole)


# --- Task 2.1: DC block and AGC ---------------------------------------------


def test_conditioner_removes_a_dc_offset():
    cond = StreamingConditioner(10e6)
    rng = np.random.default_rng(12345)
    signal = 5000.0 + 3000.0 * rng.normal(size=100000)

    out = cond.process(signal)

    # After the DC blocker settles the mean must be far below the (unit
    # RMS) signal level; the raw input's mean is 5000.
    assert abs(out[20000:].mean()) < 0.02


@pytest.mark.parametrize("amplitude", [1000.0, 20000.0])
def test_conditioner_normalises_either_capture_level_to_unit_rms(amplitude):
    cond = StreamingConditioner(10e6)
    n = np.arange(100000)
    signal = amplitude * np.sin(2 * np.pi * 0.07 * n)

    out = cond.process(signal)

    # The AGC's whole job: a weak and a strong capture present the timing
    # loop with the same signal level, so its gains need no per-disc tuning.
    rms = np.sqrt(np.mean(out[50000:] ** 2))
    assert rms == pytest.approx(1.0, rel=0.05)


def test_conditioner_is_unaffected_by_how_the_input_is_chunked():
    rng = np.random.default_rng(12345)
    signal = 2000.0 + 4000.0 * rng.normal(size=50001)

    whole = StreamingConditioner(10e6).process(signal)
    chunked_cond = StreamingConditioner(10e6)
    pieces = [
        chunked_cond.process(signal[start : start + 997]) for start in range(0, len(signal), 997)
    ]

    assert np.array_equal(np.concatenate(pieces), whole)


# --- Task 2.2: timing recovery ----------------------------------------------


def test_recovers_the_exact_t_sequence_at_nominal_rate(clean_result):
    t_values, _ = clean_result
    expected = np.array(FRAME * 60, dtype=np.int8)

    # Locate a mid-stream sync pair and demand an exact, long match against
    # the generated sequence -- these are integers, not measurements.
    mid = len(t_values) // 2
    starts = [i for i in range(mid, mid + 200) if t_values[i] == 11 and t_values[i + 1] == 11]
    assert starts, "no sync pair found mid-stream"
    window = t_values[starts[0] : starts[0] + 3 * len(FRAME)]
    matches = [
        j
        for j in range(0, len(expected) - len(window))
        if np.array_equal(expected[j : j + len(window)], window)
    ]
    assert matches, "recovered T values do not match the generated sequence"


def test_clean_stream_scores_perfectly_on_the_phase_1_oracle(clean_result):
    t_values, _ = clean_result
    score = score_t_values(t_values)

    # The acceptance criterion for the whole chain: every inter-sync gap in
    # the recovered stream is exactly 588 channel bits and every T is legal.
    # (sync_rate < 1.0 only by the stream's edges: the tail frame is still
    # pending when the input ends.)
    assert score.frame_588_fraction == 1.0
    assert score.invalid_t_fraction == 0.0
    assert score.sync_rate > 0.97


@pytest.mark.parametrize("rate_scale", [0.98, 1.02])
def test_pulls_in_a_two_percent_frequency_offset(rate_scale):
    signal = efm_waveform(FRAME * 120, rate_scale=rate_scale)

    t_values, _ = demod(signal)

    # The acquisition gear must pull the loop onto a channel clock 2% off
    # nominal; after pull-in the framing must be perfect, so score only the
    # second half (the first half contains the pull-in transient).
    score = score_t_values(t_values[len(t_values) // 2 :])
    assert score.frame_588_fraction == 1.0


def test_tracks_sinusoidal_wow():
    signal = efm_waveform(FRAME * 200, wow_amp=0.01, wow_hz=30.0)

    t_values, _ = demod(signal)
    score = score_t_values(t_values)

    # 1% speed modulation at 30 Hz spans the wow a worn spindle produces;
    # the 1.2 kHz loop must follow it without a single mis-sized frame.
    assert score.frame_588_fraction == 1.0


def test_survives_noise_that_defeats_the_pll():
    # Additive white noise at sigma=4500 against a 12000-amplitude carrier
    # (about 8.5 dB SNR in-band): measured behaviour is EFM_PLL collapsing
    # to under 5% valid frames while the per-bit timing loop stays clean.
    # This is the error class the demodulator exists to remove.
    signal = efm_waveform(FRAME * 120, noise_rms=4500.0, seed=7)

    t_timing, _ = demod(signal)
    pll = EFM_PLL()
    pll.gearshift = 1
    t_pll = pll.process(signal)

    timing_score = score_t_values(t_timing)
    pll_score = score_t_values(np.asarray(t_pll))
    assert pll_score.frame_588_fraction < 0.5
    assert timing_score.frame_588_fraction > 0.99


def test_demod_is_unaffected_by_how_the_input_is_chunked(clean_signal, clean_result):
    whole_t, whole_conf = clean_result

    chunk_t, chunk_conf = demod(clean_signal, chunk=99991)

    # decoder.py feeds one field slice per call; the output must not depend
    # on where those slices fall.
    assert np.array_equal(chunk_t, whole_t)
    assert np.array_equal(chunk_conf, whole_conf)


def test_empty_input_produces_empty_output():
    d = EFMTimingDemod(FS)
    assert len(d.process(np.zeros(0, dtype=np.int16))) == 0
    assert len(d.conf_view()) == 0


def test_result_is_a_view_that_the_next_call_overwrites(clean_signal):
    d = EFMTimingDemod(FS)

    first = d.process(clean_signal[:150000])
    snapshot = first[:5].copy()
    d.process(clean_signal[150000:300000])

    # Same contract as EFM_PLL.process: the caller must copy to keep data.
    assert not np.array_equal(first[:5], snapshot)


def test_flush_drains_the_pending_tail(clean_signal):
    d = EFMTimingDemod(FS)
    streamed = d.process(clean_signal).copy()

    tail = d.flush()
    tail_conf = d.conf_view()

    # The frames still awaiting their closing sync at end of stream (the
    # decoder calls this at close): a non-trivial tail, every value legal,
    # all of it marked unvalidated, and 1:1 with its confidences.  A second
    # flush must return nothing - the tail is written exactly once.
    assert len(tail) > 0
    assert tail.min() >= 3 and tail.max() <= 11
    assert len(tail_conf) == len(tail)
    assert tail_conf.max() <= CONF_LOWCAP
    combined = np.concatenate([streamed, tail])
    assert score_t_values(combined).sync_rate > score_t_values(streamed).sync_rate
    assert len(d.flush()) == 0


# --- Task 2.3: framing, legalisation, confidence ----------------------------


def test_emits_only_legal_run_lengths(clean_result):
    t_values, _ = clean_result
    assert t_values.min() >= 3
    assert t_values.max() <= 11


def test_emits_only_legal_run_lengths_on_pure_noise(seeded_rng):
    noise = seeded_rng.integers(-20000, 20000, 400000).astype(np.int16)

    t_values, conf = demod(noise, chunk=50000)

    # A dead EFM channel must still produce bounded, legal T values (the
    # pending-buffer overflow flush keeps output flowing with no sync), and
    # none of them may claim validated-frame confidence.
    assert len(t_values) > 0
    assert t_values.min() >= 3
    assert t_values.max() <= 11
    assert conf.max() <= CONF_LOWCAP


def test_confidence_is_one_to_one_with_t_values(clean_signal):
    d = EFMTimingDemod(FS)
    for start in range(0, len(clean_signal), 123457):
        t_values = d.process(clean_signal[start : start + 123457])
        assert len(d.conf_view()) == len(t_values)


def test_confidence_is_low_before_lock_and_high_after(clean_result):
    _, conf = clean_result

    # Frames seen before the 7-frame sync hysteresis locks were never
    # validated, so they are erasure candidates; once locked and validated,
    # a clean signal must be trusted.
    assert conf[0] <= CONF_LOWCAP
    assert conf[-200:].min() > 200


def test_legalisation_merges_a_short_run_into_the_following_run():
    frames = [FRAME.copy() for _ in range(40)]
    # A raw T2 (illegal: below the (2,10) run-length limit) followed by a
    # T8 occupies the channel bits of one T10.
    frames[20] = [11, 11, 3] + [10] * 30 + [2, 8] + [10] * 25 + [3]
    assert sum(frames[20]) == 588
    signal = efm_waveform([t for frame in frames for t in frame])

    t_values, _ = demod(signal)
    score = score_t_values(t_values)

    # The T2 must be merged forward into the T8 (emitting a T10), keeping
    # the frame at exactly 588 channel bits -- so the stream still scores
    # perfectly and carries no illegal value.
    assert t_values.min() >= 3
    assert score.frame_588_fraction == 1.0
    assert not np.any(t_values == 2)


def test_legalisation_splits_a_long_run():
    frames = [FRAME.copy() for _ in range(40)]
    # A raw T14 (illegal: above T11) plus a T6 in place of two T10s.
    frames[20] = [11, 11, 3] + [10] * 30 + [14, 6] + [10] * 24 + [3]
    assert sum(frames[20]) == 588
    signal = efm_waveform([t for frame in frames for t in frame])

    t_values, _ = demod(signal)
    score = score_t_values(t_values)

    # The T14 is split (11 emitted, 3 carried into the following run),
    # preserving the total channel-bit count: the frame still sums to 588.
    assert t_values.max() <= 11
    assert score.frame_588_fraction == 1.0


def test_flywheel_restores_a_corrupted_sync_from_the_position_counter():
    frames = [FRAME.copy() for _ in range(60)]
    # Destroy one frame's sync pair without changing its length: T10-T10 in
    # place of T11-T11 leaves 588 channel bits but no 0x801002 pattern.
    frames[30] = [10, 10, 5] + [10] * 56 + [3]
    assert sum(frames[30]) == 588
    signal = efm_waveform([t for frame in frames for t in frame])

    t_values, conf = demod(signal)
    score = score_t_values(t_values)

    # While locked, the 588-bit position counter outranks one marginal
    # read: the flywheel rewrites the pending runs at the expected boundary
    # back to T11-T11 (channel-bit count preserved), so the T stream keeps
    # a valid sync in every frame -- the behaviour of a hardware transport,
    # and what keeps downstream sync-scanning decoders framed.
    assert score.frame_588_fraction == 1.0
    assert 1176 not in score.gap_bits


def test_sync_restoration_can_be_switched_off():
    frames = [FRAME.copy() for _ in range(60)]
    frames[30] = [10, 10, 5] + [10] * 56 + [3]
    signal = efm_waveform([t for frame in frames for t in frame])

    restored = score_t_values(demod(signal)[0])
    honest = score_t_values(demod(signal, restore_sync=False)[0])

    # Repairing a missed sync keeps downstream decoders framed, but it also
    # hands them a frame the channel never showed.  With restoration off the
    # damage stays in the T stream, which is what makes the two policies
    # comparable on real material.
    assert restored.frame_588_fraction == 1.0
    assert honest.frame_588_fraction < 1.0


def test_an_unrestorable_sync_leaves_the_gap_honest():
    frames = [FRAME.copy() for _ in range(60)]
    # Corrupt the boundary so a run straddles the expected frame start by
    # exactly one channel bit: the restoration head would be an illegal
    # 1-bit run, so the rewrite must not fire -- inventing a sync over
    # unaccountable bits is worse than reporting the damage.  (The two
    # frames still total 2 x 588 bits, so framing recovers afterwards.)
    frames[29] = [11, 11, 3] + [10] * 56 + [2]  # 587 bits
    frames[30] = [5, 9, 3] + [10] * 56 + [12]  # 589 bits, no sync pattern
    assert sum(frames[29]) + sum(frames[30]) == 2 * 588
    signal = efm_waveform([t for frame in frames for t in frame])

    t_values, _ = demod(signal)
    score = score_t_values(t_values)

    # The damage stays visible as wrong frame lengths.
    assert score.frame_588_fraction < 1.0


def test_a_frame_that_fails_the_sync_check_gets_low_confidence():
    frames = [FRAME.copy() for _ in range(60)]
    frames[30] = [10, 10, 5] + [10] * 56 + [3]
    signal = efm_waveform([t for frame in frames for t in frame])

    t_values, conf = demod(signal)

    # The corrupted frame's T values are erasure candidates: a contiguous
    # stretch about one frame long (the frame the flywheel had to close
    # without its sync) is capped at the low-confidence ceiling, while the
    # clean frames around it keep full trust.
    frame_len = len(FRAME)
    middle = conf[len(conf) // 3 : 2 * len(conf) // 3]
    capped = int(np.sum(middle <= CONF_LOWCAP))
    assert frame_len - 10 <= capped <= 3 * frame_len
    assert conf[-3 * frame_len :].min() > 200


def test_input_is_not_mutated(clean_signal):
    copy = clean_signal.copy()
    demod(clean_signal)
    assert np.array_equal(clean_signal, copy)


# --- Fabrication and timing confidence --------------------------------------

# The pre-lock frames are capped as unvalidated and the very first transition
# has no predecessor to straddle, so confidence assertions about the body of a
# stream start past the 7-frame lock hysteresis.
LOCKED = 600


def test_a_merged_short_run_is_marked_fabricated():
    frames = [FRAME.copy() for _ in range(40)]
    frames[20] = [11, 11, 3] + [10] * 30 + [2, 8] + [10] * 25 + [3]
    assert sum(frames[20]) == 588
    signal = efm_waveform([t for frame in frames for t in frame])

    t_values, conf = demod(signal)

    # The T10 the legaliser built out of T2+T8 is the only T value in the
    # locked body of the stream the demodulator did not actually read, and
    # it says so: without this the merge is invisible downstream, which is
    # what lets a fabricated symbol reach the CIRC stages as trusted data.
    fabricated = np.flatnonzero(conf[LOCKED:] <= CONF_LEGALISED) + LOCKED
    assert len(fabricated) == 1
    assert t_values[fabricated[0]] == 10


def test_a_split_long_run_marks_both_halves_fabricated():
    frames = [FRAME.copy() for _ in range(40)]
    frames[20] = [11, 11, 3] + [10] * 30 + [14, 6] + [10] * 24 + [3]
    assert sum(frames[20]) == 588
    signal = efm_waveform([t for frame in frames for t in frame])

    t_values, conf = demod(signal)

    # The T14 becomes T11 plus a carried remainder: two adjacent T values,
    # one invented boundary between them, both flagged.
    fabricated = np.flatnonzero(conf[LOCKED:] <= CONF_LEGALISED) + LOCKED
    assert len(fabricated) == 2
    assert fabricated[1] == fabricated[0] + 1
    assert t_values[fabricated[0]] == 11
    assert sum(t_values[fabricated]) == 14


def test_a_clean_stream_flags_nothing_once_locked(clean_result):
    _, conf = clean_result

    # No legalisation, no restoration, no timing margin lost: a clean
    # capture must not spend erasure hints it has no reason to spend.
    assert conf[LOCKED:].min() == 255


def test_a_restored_sync_carries_the_restored_ceiling():
    frames = [FRAME.copy() for _ in range(60)]
    frames[30] = [10, 10, 5] + [10] * 56 + [3]
    signal = efm_waveform([t for frame in frames for t in frame])

    t_values, conf = demod(signal)

    # The runs the flywheel rewrote back to T11-T11 are counter-backed
    # guesses, not reads, and carry the strongest available distrust -
    # distinct from the ordinary cap the rest of that frame gets.
    restored = np.flatnonzero(conf[LOCKED:] == CONF_RESTORED) + LOCKED
    assert len(restored) >= 2
    assert np.all(np.diff(restored) == 1)
    block = t_values[restored]
    assert any(block[i] == 11 and block[i + 1] == 11 for i in range(len(block) - 1))


@pytest.mark.parametrize(
    "displacement, ceiling",
    [(0.5, 32), (0.4, 128), (0.3, 224), (0.2, 256)],
)
def test_an_edge_adrift_loses_confidence_at_full_amplitude(displacement, ceiling):
    frames = [FRAME.copy() for _ in range(40)]
    # Move one NRZI edge off the midpoint between two strobes without
    # touching the level or the frame's channel-bit count.
    frames[20] = (
        [11, 11, 3] + [10] * 30 + [10 + displacement, 10 - displacement] + [10] * 24 + [3]
    )
    assert sum(frames[20]) == 588
    signal = efm_waveform([t for frame in frames for t in frame])

    _, conf = demod(signal)

    # A full-height run whose length was a coin toss is exactly the failure
    # an amplitude-only confidence cannot see: at half a bit the two runs
    # bounding the edge are barely trusted, and the response is graded, so
    # a merely noisy edge is not thrown away with the ambiguous one.
    body = conf[LOCKED:]
    assert body.min() < ceiling
    if displacement > 0.2:
        assert int(np.sum(body < 250)) == 2


def test_confidence_ceilings_pack_to_the_documented_doubt_levels():
    # The .efm high nibble is doubt = 15 - (conf >> 4).  Fabrication must
    # land above a consumer's erasure threshold and whole-frame validation
    # below it, or the hint is spent on the 74 T values of a frame for the
    # sake of the two in it that are wrong.
    doubt = pack_t_conf(
        np.full(3, 10, np.int8),
        np.array([CONF_RESTORED, CONF_LEGALISED, CONF_LOWCAP], np.uint8),
    ) >> 4

    assert list(doubt) == [15, 14, 8]


# --- Task 3.1: sign-sign LMS adaptive equaliser -----------------------------


def test_equaliser_is_off_by_default_and_bypassed(clean_signal):
    default_t, default_conf = demod(clean_signal)
    explicit_t, explicit_conf = demod(clean_signal, eq_taps=0)

    # eq_taps=0 is the default and takes the identical code path: the
    # symbol chain is untouched, keeping the no-equaliser configuration
    # bit-identical to the pre-equaliser demodulator.
    assert np.array_equal(default_t, explicit_t)
    assert np.array_equal(default_conf, explicit_conf)


@pytest.mark.parametrize("taps", [2, 4, 17, -3])
def test_equaliser_rejects_illegal_tap_counts(taps):
    with pytest.raises(ValueError):
        EFMTimingDemod(FS, eq_taps=taps)


def test_equaliser_converges_on_symbol_spaced_isi():
    # Channel model: x[k] = s[k] + 0.4*s[k-1] over antipodal symbols
    # (one-symbol post-cursor ISI), seeded noise at 26 dB SNR.  This is the
    # setting where decision-directed sign-sign LMS provably applies, so
    # here the machinery must actually converge: the slicer error shrinks
    # and the first tap moves negative to cancel the post-cursor.
    rng = np.random.default_rng(12345)
    symbols = np.where(rng.random(60000) < 0.5, 1.0, -1.0)
    received = symbols.copy()
    received[1:] += 0.4 * symbols[:-1]
    received += rng.normal(0, 0.05, len(received))

    core = EFMTimingDemod(FS, eq_taps=3, eq_mu=1e-4).core
    err_first = 0.0
    err_last = 0.0
    n_first = 3000  # covers the adaptation ramp (mu * n ~ the 0.4 cursor)
    n_last = 10000
    for k, x in enumerate(received):
        z = core._equalise(x)
        e = abs(z - (1.0 if z >= 0 else -1.0))
        if k < n_first:
            err_first += e
        elif k >= len(received) - n_last:
            err_last += e

    assert err_last / n_last < 0.7 * (err_first / n_first)
    assert core.eq_w[0] < -0.25  # post-cursor canceller, ideal -0.4
    assert core.eq_w[1] == pytest.approx(1.0, abs=0.25)  # main tap holds


def test_equaliser_taps_stay_inside_their_bound():
    rng = np.random.default_rng(54321)
    core = EFMTimingDemod(FS, eq_taps=5, eq_mu=1e-2, eq_bound=0.3).core

    # An aggressive step on pure noise is the worst case for tap walk;
    # the per-tap bound around the centre-spike initialisation is what
    # guarantees a noisy stretch can never leave the filter unrecoverable.
    for x in rng.normal(0, 1.0, 20000):
        core._equalise(x)

    init = np.zeros(5)
    init[2] = 1.0
    assert np.all(np.abs(np.asarray(core.eq_w) - init) <= 0.3 + 1e-12)


def test_equaliser_enabled_still_frames_a_clean_capture(clean_signal):
    t_values, _ = demod(clean_signal, eq_taps=3)

    # With the equaliser adapting on a clean signal the stream must stay
    # perfectly framed once converged (the equaliser is default-off because
    # it buys nothing, not because it is unsafe on clean material).
    score = score_t_values(t_values[len(t_values) // 2 :])
    assert score.frame_588_fraction == 1.0
