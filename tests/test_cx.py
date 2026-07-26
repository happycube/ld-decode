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
A40 = 40 * counts_per_khz(FS)    # int16 counts at the rated 40 kHz / 40% mod

# Variant knee ratios (expander floor = knee_ratio * V_CR); see cx.py _VARIANT.
_KNEE = {"cx14": 0.20, "cx20": 0.10}


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


def _steady_gain_db(db, secs=6.0, variant="cx14"):
    """Expand a held tone; return output level (dB re 100%) over the last second."""
    y = CXExpander(fs=FS, variant=variant).process(_tone(db, secs)).astype(np.float64)
    yl = y[0::2]
    peak = np.sqrt(np.mean(yl[-FS:] ** 2)) * np.sqrt(2)
    return 20 * np.log10(peak / A100)


def _expect_static_db(db, variant="cx14"):
    """Expected steady expander output (dB re 100% mod) for a held tone at ``db``.

    Rated unity gain is at 40 kHz / 40% mod (V_CR); gain is V_c/V_CR, linear in
    level = 2.5*10^(db/20), floored at knee_ratio.  So above the knee the curve
    is 2:1 (output = 2*db + 20log10(2.5)) and below it is a flat floor
    (output = db + 20log10(knee_ratio))."""
    kr = _KNEE[variant]
    gain = 2.5 * 10 ** (db / 20)
    if gain < kr:
        gain = kr
    return db + 20 * np.log10(gain)


def test_calibration_anchor():
    """V_rated/V_100/V_CR/R_knee hold the spec ratios off V_CR (CX-14)."""
    cx = CXExpander(fs=FS)
    # The rated unity-gain anchor is V_CR (40 kHz / 40% mod), not V_100.
    assert np.isclose(cx.V_rated, cx.V_CR)
    assert np.isclose(cx.V_100, 2.5 * cx.V_CR)
    assert np.isclose(cx.R_knee, 0.20 * cx.V_CR)   # CX-14 knee = 8 kHz
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

    CX-20 shares the rated unity-gain anchor (V_rated = V_CR) with CX-14 but has
    a deeper knee (0.10*V_CR = 4 kHz, 20 dB NR vs CX-14's 8 kHz / 14 dB) and a
    faster integrator; the round-trip still stays exactly null."""
    cx = CXExpander(fs=FS, variant="cx20")
    cx14 = CXExpander(fs=FS)
    assert cx.attack_comp == 2  # 'excess-thresh'
    assert np.isclose(cx.theta_ac, 0.70 * cx.V_CR)
    assert np.isclose(cx.V_rated, cx14.V_rated)            # rated anchor shared
    assert np.isclose(cx.R_knee, 0.10 * cx.V_CR)           # deeper CX-20 knee
    assert not np.isclose(cx.R_knee, cx14.R_knee)          # differs from CX-14
    assert cx.a_i > cx14.a_i                               # faster integrator

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
    """2:1 expansion about the rated 40% anchor, within 0.25 dB (T1).

    Rated unity gain is at -7.96 dB re 100% mod (40 kHz); the expander gain is
    V_c/V_CR, so output = 2*db + 20log10(2.5) above the knee (see
    _expect_static_db).  Verified for both variants (the knee differs)."""
    for variant, knee_db in (("cx14", -21.94), ("cx20", -27.96)):
        for c in (-40, -30, -25, -15, -10, -5, 0):
            # Skip the knee neighbourhood, where the spec-literal per-sample
            # clamp softens the corner for a few dB above the knee.
            if knee_db - 2 < c < knee_db + 4:
                continue
            u = _steady_gain_db(c, variant=variant)
            expect = _expect_static_db(c, variant=variant)
            assert abs(u - expect) < 0.25, \
                f"{variant} c={c}: got {u:.3f}, expect {expect:.3f}"


def test_below_knee_gain_floor():
    """Below the knee the gain is pinned at the variant's noise-reduction floor.

    CX-14 floor = 0.20 (-13.98 dB, 14 dB NR); CX-20 floor = 0.10 (-20 dB NR)."""
    for variant in ("cx14", "cx20"):
        floor_db = 20 * np.log10(_KNEE[variant])
        # A tone well below the knee must expand to db + floor_db.
        u = _steady_gain_db(-45, variant=variant)
        assert abs(u - (-45 + floor_db)) < 0.3, \
            f"{variant}: got {u:.3f}, expect {-45 + floor_db:.3f}"


def test_ggv_spec_absolute_levels():
    """ggv1001 CX-20 source spec as absolute ground truth (plan sec. 8d).

    The spec (testdata/cx/ggv1001-cx.png) states: Level A = 0 dB = 40% mod,
    Level B = -20 dB = 4% RMS on the *master*; on the compressed disc, A = 40%
    and B = 12.6%.  So the compressor must map the rated 40%-mod master to 40%
    on disc (gain 1) and the 4% master to 12.6% on disc (2:1 compression), and
    the expander must recover 40% / 4%.  This pins the absolute anchor without
    depending on the (uncommitted) ggv-cx.pcm asset."""
    def held(mod_pct, secs=8.0):
        n = int(secs * FS)
        t = np.arange(n)
        amp = A100 * mod_pct / 100.0
        s = np.round(amp * np.sin(2 * np.pi * 1000.0 * t / FS)).astype(np.int16)
        x = np.empty(2 * n, dtype=np.int16)
        x[0::2] = s
        x[1::2] = s
        return x

    def steady_mod(pcm):
        yl = pcm[0::2].astype(np.float64)
        return np.sqrt(np.mean(yl[-2 * FS:] ** 2)) * np.sqrt(2) / A100 * 100.0

    for variant in ("cx14", "cx20"):
        comp = CXCompressor(fs=FS, variant=variant)
        # Level A: 40% master -> 40% disc (rated, gain 1).
        discA = steady_mod(comp.process(held(40.0)))
        assert abs(discA - 40.0) < 2.0, f"{variant} disc A {discA:.1f}% != 40%"
        # Level B: 4% master -> 12.6% disc (2:1 about the 40% anchor).
        comp_b = CXCompressor(fs=FS, variant=variant)
        discB = steady_mod(comp_b.process(held(4.0)))
        assert abs(discB - 12.6) < 1.5, f"{variant} disc B {discB:.1f}% != 12.6%"

        # Round-trip recovers the master levels (40% / 4%).
        exp = CXExpander(fs=FS, variant=variant, dc_block=False)
        recA = steady_mod(exp.process(comp.process(held(40.0))))
        exp_b = CXExpander(fs=FS, variant=variant, dc_block=False)
        recB = steady_mod(exp_b.process(comp_b.process(held(4.0))))
        assert abs(20 * np.log10(recA / 40.0)) < 0.5, f"{variant} rec A {recA:.2f}%"
        assert abs(20 * np.log10(recB / 4.0)) < 0.6, f"{variant} rec B {recB:.2f}%"


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
