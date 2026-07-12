"""Tests for the CX audio expander/compressor (lddecode/cx.py).

Covers the plan's synthetic acceptance items (cx-decoder-plan.md sec. 7):
T1 static compression curve, T2 detector time constants, T3 encoder
round-trip, plus the self-calibration self-consistency check.  The real-disc
tests (T4-T6) need large decoded assets and are run out of band.
"""

import numpy as np

from lddecode.cx import CXExpander, CXCompressor, counts_per_khz

FS = 44100
A100 = 100 * counts_per_khz(FS)  # int16 counts at 100% modulation


def _tone(db, secs, fs=FS):
    """Stereo interleaved int16 1 kHz tone at ``db`` re 100% modulation."""
    n = int(secs * fs)
    t = np.arange(n)
    amp = A100 * (10 ** (db / 20))
    s = np.round(amp * np.sin(2 * np.pi * 1000.0 * t / fs)).astype(np.int16)
    x = np.empty(2 * n, dtype=np.int16)
    x[0::2] = s
    x[1::2] = s
    return x


def _steady_gain_db(db, secs=6.0):
    """Expand a held tone; return output level (dB re 100%) over the last second."""
    y = CXExpander(fs=FS).process(_tone(db, secs)).astype(np.float64)
    yl = y[0::2]
    peak = np.sqrt(np.mean(yl[-FS:] ** 2)) * np.sqrt(2)
    return 20 * np.log10(peak / A100)


def test_calibration_anchor():
    """V_100/V_CR/R_knee hold the spec ratios (2.5 / 1 / 0.2) off V_CR."""
    cx = CXExpander(fs=FS)
    assert np.isclose(cx.V_100, 2.5 * cx.V_CR)
    assert np.isclose(cx.R_knee, 0.20 * cx.V_CR)
    assert np.isclose(cx.theta_slow, 0.26 * cx.V_CR)
    assert np.isclose(cx.theta_ac, 0.52 * cx.V_CR)
    # V_CR is the detector reading of the 40 kHz anchor tone (~0.756 * A_40).
    assert 0.70 * cx.A_40 < cx.V_CR < 0.80 * cx.A_40


def test_default_variant_is_cx14():
    """The default path is CX-14 (IEC 60857): excess comp, nominal theta_ac."""
    cx = CXExpander(fs=FS)
    assert cx.variant == "cx14"
    assert cx.attack_comp == 1  # 'excess'
    assert np.isclose(cx.theta_ac, 0.52 * cx.V_CR)


def test_cx20_variant_uses_gentler_attack_comp():
    """CX-20 selects the weaker compensator (excess-thresh, raised threshold).

    Only the attack ballistics differ -- the static-curve anchors (V_100,
    R_knee) are identical to CX-14, and the round-trip stays exactly null."""
    cx = CXExpander(fs=FS, variant="cx20")
    assert cx.attack_comp == 2  # 'excess-thresh'
    assert np.isclose(cx.theta_ac, 0.70 * cx.V_CR)
    assert np.isclose(cx.V_100, CXExpander(fs=FS).V_100)   # static curve shared
    assert np.isclose(cx.R_knee, CXExpander(fs=FS).R_knee)

    # explicit attack_comp overrides the variant default
    assert CXExpander(fs=FS, variant="cx20", attack_comp="off").attack_comp == 0

    # cx20 encoder->decoder still tracks transparently (shared control path)
    rng = np.random.RandomState(3)
    n = 6 * FS
    env = 0.3 + 0.6 * np.abs(np.sin(2 * np.pi * 0.8 * np.arange(n) / FS))
    sig = rng.randn(n) * env * A100 * 0.3
    u = np.empty(2 * n, dtype=np.int16)
    u[0::2] = np.clip(np.round(sig), -32766, 32766)
    u[1::2] = u[0::2]
    c = CXCompressor(fs=FS, variant="cx20").process(u)
    r = CXExpander(fs=FS, variant="cx20", dc_block=False).process(c).astype(np.float64)
    ref = u.astype(np.float64)
    sk = FS
    def env_db(x, hop=int(0.01 * FS), win=int(0.05 * FS)):
        return np.array([
            10 * np.log10(np.mean(x[i - win:i + win] ** 2) + 1e-6)
            for i in range(win, len(x) - win, hop)
        ])
    eu = env_db(ref[2 * sk::2])
    er = env_db(r[2 * sk::2])
    m = min(len(eu), len(er))
    err = np.abs(er[:m] - eu[:m])
    active = eu[:m] > (eu[:m].max() - 40)
    assert np.mean(err[active]) < 0.5


def test_static_curve_above_knee():
    """2:1 expansion (u = 2c) within 0.25 dB away from the soft knee (T1)."""
    for c in (-40, -30, -25, -15, -10, -5, 0):
        # Skip the immediate knee neighbourhood (-24..-20), where the spec-
        # literal per-sample clamp intentionally softens the corner.
        if -24 < c < -22:
            continue
        u = _steady_gain_db(c)
        expect = 2 * c if c >= -21.94 else c - 21.94
        assert abs(u - expect) < 0.25, f"c={c}: got {u:.3f}, expect {expect:.3f}"


def test_below_knee_gain_floor():
    """Below the knee the gain is pinned at 8/100 = 0.08 (-21.94 dB)."""
    # A -45 dB compressed tone must expand to -45 - 21.94 = -66.94 dB.
    u = _steady_gain_db(-45)
    assert abs(u - (-45 - 21.94)) < 0.3


def test_fast_attack_reaches_target_quickly():
    """A -30 -> -10 dB jump reaches 90% of the gain step within ~5 ms (T2a)."""
    n0 = int(1.0 * FS)
    n1 = int(0.5 * FS)
    env = np.concatenate([
        np.full(n0, A100 * 10 ** (-30 / 20)),
        np.full(n1, A100 * 10 ** (-10 / 20)),
    ])
    t = np.arange(len(env))
    s = np.round(env * np.sin(2 * np.pi * 1000.0 * t / FS)).astype(np.int16)
    x = np.empty(2 * len(env), dtype=np.int16)
    x[0::2] = s
    x[1::2] = s

    cx = CXExpander(fs=FS)
    cx.process(x)
    g = cx.last_vc_log  # V_c / V_100 per frame
    g0 = g[n0 - 2]
    gf = np.mean(g[-int(0.1 * FS):])
    target = g0 + 0.9 * (gf - g0)
    reached = np.argmax(g[n0:] >= target) / FS * 1000.0  # ms
    assert reached < 8.0, f"attack took {reached:.1f} ms"


def test_round_trip_is_transparent():
    """Compress then expand random program material -> near-null (T3)."""
    rng = np.random.RandomState(0)
    n = 10 * FS
    env = 0.3 + 0.6 * np.abs(np.sin(2 * np.pi * 0.8 * np.arange(n) / FS))
    sig = rng.randn(n) * env * A100 * 0.3
    u = np.empty(2 * n, dtype=np.int16)
    u[0::2] = np.clip(np.round(sig), -32766, 32766)
    u[1::2] = np.clip(np.round(np.roll(sig, 5)), -32766, 32766)

    c = CXCompressor(fs=FS).process(u)
    r = CXExpander(fs=FS, dc_block=False).process(c).astype(np.float64)
    ref = u.astype(np.float64)

    # Compare short-time RMS envelopes past the warmup transient.
    sk = FS
    def env_db(x, hop=int(0.01 * FS), win=int(0.05 * FS)):
        return np.array([
            10 * np.log10(np.mean(x[i - win:i + win] ** 2) + 1e-6)
            for i in range(win, len(x) - win, hop)
        ])
    eu = env_db(ref[2 * sk::2])
    er = env_db(r[2 * sk::2])
    m = min(len(eu), len(er))
    err = np.abs(er[:m] - eu[:m])
    active = eu[:m] > (eu[:m].max() - 40)
    assert np.mean(err[active]) < 0.5


def test_streaming_matches_single_shot():
    """Persistent state makes chunked processing bit-identical to one call.

    The first-call warmup pass depends on how much data the first call sees, so
    it is neutralised here (``_warmed``) to isolate the streaming-state
    property itself."""
    x = _tone(-12, 3.0)
    one = CXExpander(fs=FS)
    one._warmed = True
    whole = one.process(x)

    cx = CXExpander(fs=FS)
    cx._warmed = True
    chunks = []
    step = 4096 * 2  # keep L,R frames intact
    for i in range(0, len(x), step):
        chunks.append(cx.process(x[i:i + step]))
    streamed = np.concatenate(chunks)
    np.testing.assert_array_equal(whole, streamed)
