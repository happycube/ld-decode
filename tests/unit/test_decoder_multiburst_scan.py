"""Unit tests for the multiburst window scan behind the video EQ servo.

measure_vits_multiburst() slides a 44-sample window along a VBI line and
keeps the windows that hold one clean tone.  It did that one window at a
time - about 65 std/rfft pairs per line, every field, on the decode's main
thread - and now scans every window as one array.  The servo's decisions
depend on these candidates, so the batched scan must return exactly what
the per-window loop returned, not merely something close.
"""

import numpy as np
import pytest

from lddecode.decoder import _multiburst_window_scan

pytestmark = [pytest.mark.unit, pytest.mark.decode]

FS_MHZ = 17.734475  # PAL 4fsc output rate, as SysParams["outfreq"] gives it
W, STEP = 44, 6


def _per_window_scan(y, fs_mhz):
    """The loop the batched scan replaced, verbatim."""
    win = np.hanning(W)
    cands = []
    for i in range((len(y) - W) // STEP):
        w = y[i * STEP:i * STEP + W]
        wd = w - w.mean()
        pp = float(2.0 * np.sqrt(2.0) * np.std(wd))
        if pp < 12.0:
            continue
        spec = np.abs(np.fft.rfft(wd * win))
        k = int(np.argmax(spec[1:])) + 1
        if k >= len(spec) - 1:
            continue
        e_pk = spec[k - 1] ** 2 + spec[k] ** 2 + spec[k + 1] ** 2
        if e_pk < 0.8 * float(np.sum(spec ** 2)):
            continue
        a, b, c = spec[k - 1], spec[k], spec[k + 1]
        denom = a - 2 * b + c
        if abs(denom) > 1e-12:
            k = k + 0.5 * (a - c) / denom
        cands.append((k * fs_mhz / W * 1e6, pp, i * STEP))
    return cands


def _multiburst_line(rng, noise_ire):
    """A 30 us multiburst line in IRE: a pedestal, six packets, noise."""
    n = int(30e-6 * FS_MHZ * 1e6)
    t = np.arange(n) / (FS_MHZ * 1e6)
    y = np.full(n, 50.0)
    edges = np.linspace(0, n, 7).astype(int)
    for (lo, hi), f in zip(zip(edges[:-1], edges[1:]), [0.5, 1.0, 2.0, 4.0, 4.8, 5.8]):
        y[lo:hi] += 30.0 * np.sin(2 * np.pi * f * 1e6 * t[lo:hi])
    return y + rng.normal(0.0, noise_ire, n)


@pytest.mark.parametrize("noise_ire", [0.0, 2.0, 8.0])
def test_batched_scan_returns_exactly_the_per_window_candidates(noise_ire):
    rng = np.random.default_rng(12345)
    y = _multiburst_line(rng, noise_ire)

    expected = _per_window_scan(y, FS_MHZ)

    assert len(expected) > 20  # the line really does carry packets
    assert _multiburst_window_scan(y, FS_MHZ, W, STEP) == expected


def test_flat_and_short_lines_have_no_candidates():
    rng = np.random.default_rng(54321)

    assert _multiburst_window_scan(np.full(500, 50.0), FS_MHZ, W, STEP) == []
    assert _multiburst_window_scan(rng.normal(50.0, 1.0, 500), FS_MHZ, W, STEP) == []
    assert _multiburst_window_scan(np.zeros(W), FS_MHZ, W, STEP) == []
