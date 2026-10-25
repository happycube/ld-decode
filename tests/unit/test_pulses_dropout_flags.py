"""Unit tests for dropout_flags, the one-pass dropout test behind
Field.dropout_detect_demod.

It replaced a sequence of whole-field passes: two range checks on the
demodulated video, a sync-region relaxation of those flags, an RF
high-pass test delayed by the rot delay, an absurd-excursion test, and a
crop to the field.  The reference below is that sequence, built from the
helpers it used; dropout_flags must agree with it sample for sample.

The one departure since is the PAL pilot: the sync relaxation now reads
demod less demod_pilot, so the reference takes the pilot out of the demod
it hands _dropout_unflag_sync.
"""

import numpy as np
import pytest

from lddecode.dsp import n_orgt, n_ornotrange_scalar
from lddecode.pulses import _dropout_unflag_sync, dropout_flags

pytestmark = [pytest.mark.unit, pytest.mark.decode]

LIMITS = dict(
    normal_min=7.3e6, normal_max=9.6e6, normal_min_05=7.6e6, normal_max_05=9.3e6,
    sync_min=6.9e6, sync_min_05=7.4e6, absurd_hz=1.3e7,
)


def reference(rfhpf, rfstd, rot_delay, video, regions, keep, pilot=None):
    """The sequence of passes dropout_flags replaced, with the sync
    relaxation reading demod less the pilot."""
    iserr_rf1 = (rfhpf < (-rfstd * 3)) | (rfhpf > (rfstd * 3))
    if rot_delay:
        iserr_rf = np.full_like(iserr_rf1, False)
        iserr_rf[rot_delay:] = iserr_rf1[:-rot_delay]
    else:
        iserr_rf = iserr_rf1.copy()

    lim = LIMITS
    iserr = np.full_like(iserr_rf1, False)
    n_ornotrange_scalar(iserr, video["demod"], lim["normal_min"], lim["normal_max"])
    n_ornotrange_scalar(iserr, video["demod_05"], lim["normal_min_05"], lim["normal_max_05"])
    demod_sync = video["demod"] if pilot is None else video["demod"] - pilot
    for start, end in regions:
        _dropout_unflag_sync(iserr, demod_sync, video["demod_05"], start, end,
                             lim["sync_min"], lim["normal_max"],
                             lim["sync_min_05"], lim["normal_max_05"])
    iserr |= iserr_rf
    n_orgt(iserr, video["demod_raw"], lim["absurd_hz"])
    iserr[:keep[0]] = False
    iserr[keep[1]:] = False
    return iserr


def fused(rfhpf, rfstd, rot_delay, video, regions, keep, pilot=None):
    n = len(rfhpf)
    if pilot is None:
        pilot = np.empty(0, dtype=np.float32)
    iserr = np.empty(n, dtype=np.bool_)
    lim = LIMITS
    starts = np.array([r[0] for r in regions], dtype=np.int64)
    ends = np.array([r[1] for r in regions], dtype=np.int64)
    dropout_flags(
        iserr, rfhpf,
        float(np.float32(-rfstd * 3)), float(np.float32(rfstd * 3)), rot_delay,
        video["demod"], video["demod_05"], video["demod_raw"], pilot,
        lim["normal_min"], lim["normal_max"], lim["normal_min_05"], lim["normal_max_05"],
        lim["sync_min"], lim["sync_min_05"], lim["absurd_hz"],
        starts, ends,
        slice(None, keep[0]).indices(n)[1], slice(keep[1], None).indices(n)[0],
    )
    return iserr


def signals(seed, n=20000):
    """Video wandering over and past every threshold, as a record array
    the way demodblock lays it out, and an RF high-pass with outliers."""
    rng = np.random.default_rng(seed)
    names = ["demod", "demod_raw", "demod_05", "demod_burst"]
    video = np.recarray(n, dtype=[(name, np.float32) for name in names])
    for name in names:
        video[name] = 8.4e6 + 9e5 * rng.standard_normal(n)
    video["demod_raw"][rng.integers(0, n, 40)] = 2e7
    rfhpf = (300 * rng.standard_normal(n)).astype(np.float32)
    rfhpf[rng.integers(0, n, 60)] *= 8
    return rfhpf, float(np.std(rfhpf)), video


REGIONS = [(150, 340), (900, 3200), (3100, 3300), (2000, 2100), (-50, 40),
           (7000, 6000), (19950, 20500), (5000, 5200)]


@pytest.mark.parametrize("rot_delay", [0, 1, 37, 2500])
@pytest.mark.parametrize("keep", [(400, 19000), (0, 20000), (-300, 25000), (19500, 100)])
def test_matches_the_pass_by_pass_test(rot_delay, keep):
    rfhpf, rfstd, video = signals(rot_delay + abs(keep[0]))
    want = reference(rfhpf, rfstd, rot_delay, video, REGIONS, keep)
    got = fused(rfhpf, rfstd, rot_delay, video, REGIONS, keep)
    # a window that ends before it starts keeps nothing at all
    assert not want.all() and want.any() == (keep[1] > keep[0])
    np.testing.assert_array_equal(got, want)


def test_a_rot_delay_longer_than_the_field():
    rfhpf, rfstd, video = signals(5, n=900)
    want = reference(rfhpf, rfstd, 1200, video, [(100, 300)], (0, 900))
    np.testing.assert_array_equal(fused(rfhpf, rfstd, 1200, video, [(100, 300)], (0, 900)), want)


def test_nan_samples_are_not_flagged_by_the_range_tests():
    rfhpf, rfstd, video = signals(6)
    video["demod"][1000:1010] = np.nan
    video["demod_05"][4000:4010] = np.nan
    rfhpf[7000:7010] = np.nan
    want = reference(rfhpf, rfstd, 25, video, REGIONS, (0, 20000))
    np.testing.assert_array_equal(fused(rfhpf, rfstd, 25, video, REGIONS, (0, 20000)), want)


def test_the_rf_bound_is_compared_in_single_precision():
    """The high-pass is float32 and the old bound a Python float, so
    NumPy rounded the bound to float32: a sample between the bound and its
    float32 rounding must come out as the rounded comparison says."""
    rfhpf, _, video = signals(7)
    video["demod"][:] = 8.4e6
    video["demod_05"][:] = 8.4e6
    video["demod_raw"][:] = 8.4e6
    rfstd = 100.00000123   # 3 * rfstd is not a float32
    bound = np.float32(rfstd * 3)
    rfhpf[:] = 0
    rfhpf[10] = bound
    rfhpf[11] = np.nextafter(bound, np.float32(np.inf))
    want = reference(rfhpf, rfstd, 0, video, [], (0, len(rfhpf)))
    assert not want[10] and want[11]
    np.testing.assert_array_equal(fused(rfhpf, rfstd, 0, video, [], (0, len(rfhpf))), want)


# --- the PAL pilot ---------------------------------------------------------

#: A sync tip in the LIMITS frequency domain: demod and demod_05 below
#: their normal floors and inside the relaxed sync ranges.
TIP = 7.1e6
TIP_05 = 7.5e6
PILOT_PEAK = 0.3e6   # takes the troughs to 6.8e6, past sync_min (6.9e6)
SYNC = (1000, 1200)


def pilot_on_sync_tips(n=20000, seed=8):
    """Quiet video at blanking, with a sync tip carrying a 3.75 MHz-like
    pilot at 40 MHz sampling, and the pilot channel that isolates it.  The
    pilot channel is a record-array field, as demodblock lays it out."""
    rng = np.random.default_rng(seed)
    names = ["demod", "demod_raw", "demod_05", "demod_burst", "demod_pilot"]
    video = np.recarray(n, dtype=[(name, np.float32) for name in names])
    video["demod"] = 8.4e6
    video["demod_05"] = 8.4e6
    video["demod_raw"] = 8.4e6
    video["demod_burst"] = 0
    video["demod_pilot"] = 0
    tip = slice(*SYNC)
    t = np.arange(SYNC[1] - SYNC[0])
    pilot = PILOT_PEAK * np.sin(2 * np.pi * 3.75 / 40 * t + 0.3)
    video["demod_pilot"][tip] = pilot
    video["demod"][tip] = TIP + pilot + 1e4 * rng.standard_normal(len(t))
    video["demod_05"][tip] = TIP_05
    rfhpf = np.zeros(n, dtype=np.float32)
    return rfhpf, 100.0, video


@pytest.mark.parametrize("rot_delay", [0, 1500])
def test_the_pilot_troughs_on_a_sync_tip_are_not_dropouts(rot_delay):
    # rot_delay 1500 puts the tip before the RF test starts, through the
    # sample-at-a-time path.
    rfhpf, rfstd, video = pilot_on_sync_tips()
    assert np.any(video["demod"][SYNC[0]:SYNC[1]] < LIMITS["sync_min"])
    without = fused(rfhpf, rfstd, rot_delay, video, [SYNC], (0, len(rfhpf)))
    assert without[SYNC[0]:SYNC[1]].any()
    got = fused(rfhpf, rfstd, rot_delay, video, [SYNC], (0, len(rfhpf)),
                video["demod_pilot"])
    assert not got.any()


def test_a_real_excursion_on_a_sync_tip_is_still_a_dropout():
    rfhpf, rfstd, video = pilot_on_sync_tips()
    video["demod"][1100:1103] = 5.0e6
    got = fused(rfhpf, rfstd, 0, video, [SYNC], (0, len(rfhpf)),
                video["demod_pilot"])
    np.testing.assert_array_equal(np.nonzero(got)[0], [1100, 1101, 1102])


def test_the_pilot_is_not_taken_out_of_the_normal_test():
    # Outside the sync regions demod is tested as it is: a pilot-channel
    # reading there must neither raise nor clear a flag.
    rfhpf, rfstd, video = pilot_on_sync_tips()
    video["demod"][5000:5010] = 7.0e6           # below normal_min
    video["demod_pilot"][5000:5010] = -1.5e6    # would lift it into range
    video["demod_pilot"][6000:6010] = 2.0e6     # would push it out of range
    got = fused(rfhpf, rfstd, 0, video, [SYNC], (0, len(rfhpf)),
                video["demod_pilot"])
    np.testing.assert_array_equal(np.nonzero(got)[0], np.arange(5000, 5010))


@pytest.mark.parametrize("rot_delay", [0, 37, 2500])
def test_matches_the_pass_by_pass_test_with_a_pilot(rot_delay):
    rfhpf, rfstd, video = signals(rot_delay + 11)
    rng = np.random.default_rng(rot_delay)
    pilot = (4e5 * rng.standard_normal(len(rfhpf))).astype(np.float32)
    want = reference(rfhpf, rfstd, rot_delay, video, REGIONS, (400, 19000), pilot)
    got = fused(rfhpf, rfstd, rot_delay, video, REGIONS, (400, 19000), pilot)
    assert want.any()
    np.testing.assert_array_equal(got, want)
