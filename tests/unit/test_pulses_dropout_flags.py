"""Unit tests for dropout_flags, the one-pass dropout test behind
Field.dropout_detect_demod.

It replaced a sequence of whole-field passes: two range checks on the
demodulated video, a sync-region relaxation of those flags, an RF
high-pass test delayed by the rot delay, an absurd-excursion test, and a
crop to the field.  The reference below is that sequence, built from the
helpers it used; dropout_flags must agree with it sample for sample.
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


def reference(rfhpf, rfstd, rot_delay, video, regions, keep):
    """The sequence of passes dropout_flags replaced."""
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
    for start, end in regions:
        _dropout_unflag_sync(iserr, video["demod"], video["demod_05"], start, end,
                             lim["sync_min"], lim["normal_max"],
                             lim["sync_min_05"], lim["normal_max_05"])
    iserr |= iserr_rf
    n_orgt(iserr, video["demod_raw"], lim["absurd_hz"])
    iserr[:keep[0]] = False
    iserr[keep[1]:] = False
    return iserr


def fused(rfhpf, rfstd, rot_delay, video, regions, keep):
    n = len(rfhpf)
    iserr = np.empty(n, dtype=np.bool_)
    lim = LIMITS
    starts = np.array([r[0] for r in regions], dtype=np.int64)
    ends = np.array([r[1] for r in regions], dtype=np.int64)
    dropout_flags(
        iserr, rfhpf,
        float(np.float32(-rfstd * 3)), float(np.float32(rfstd * 3)), rot_delay,
        video["demod"], video["demod_05"], video["demod_raw"],
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
