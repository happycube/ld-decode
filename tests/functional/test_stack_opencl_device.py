"""The stacked source's OpenCL kernels on a real device, against the host.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Needs pyopencl and an OpenCL device, so it is functional and skips without
them.  The same plan is read and combined on the host's compiled kernels and
on the device, in double and in single precision, and the two must agree to
the precision's own rounding.

All signals are synthetic.
"""

from __future__ import annotations

import numpy as np
import pytest

from lddecode import stack

pytestmark = [pytest.mark.functional, pytest.mark.decode]

cl = pytest.importorskip("pyopencl")


def _device_or_skip():
    from lddecode.stack_opencl import open_device

    try:
        return open_device(cl)
    except Exception as exc:  # noqa: BLE001 - no device is a skip, not a failure
        pytest.skip(f"no OpenCL device: {exc}")


def _plan(rng, ninputs, length):
    """A plan over synthetic captures, each read at a slightly different rate."""
    n_raw = length + 4096
    t = np.arange(n_raw, dtype=np.float64)
    seg = np.zeros(length, dtype=np.int64)
    seg_t0 = np.array([0.0])
    spans = []
    for i in range(ninputs):
        raw = 2000.0 * np.cos(2 * np.pi * 0.108 * t + i) + rng.standard_normal(n_raw) * 50.0
        spans.append(
            stack._InputSpan(
                raw=raw,
                start=0,
                a0=np.array([300.0 + 0.37 * i]),
                slope=np.array([1.0 + 1e-4 * i]),
                seg=seg,
                seg_t0=seg_t0,
                s0=0.0,
            )
        )
    return stack._Plan(s0=0.0, length=length, seg=seg, seg_t0=seg_t0, inputs=spans)


@pytest.mark.parametrize("double, tolerance", [(True, 1e-6), (False, 5e-3)])
@pytest.mark.parametrize("mode", ["adaptive", "fixed"])
def test_the_device_agrees_with_the_host(double, tolerance, mode):
    from lddecode.stack_opencl import StackOpenCL

    device = _device_or_skip()
    rng = np.random.default_rng(51)
    margin = stack.LOCK_MARGIN
    nout = 5000
    plan = _plan(rng, 4, nout + 2 * margin)
    fs = 75.0e6
    sinc = stack.sinc_lut()
    hi = stack.video_band_lut(fs, (stack.SPLIT_LO_HZ, stack.SPLIT_HI_HZ))
    parts = (np.ascontiguousarray(hi.real), np.ascontiguousarray(hi.imag))
    weight = [1.0, 0.8, 1.2, 0.9]
    afloor = [0.05, 0.05, 0.05, 0.05]
    lag = stack.carrier_lag(fs)
    reads = [stack._read_input(span, sinc, parts) for span in plan.inputs]
    want, _, want_band = stack._combine(reads, weight, afloor, mode, lag, margin)

    constants = {
        "PHASES": stack.SINC_PHASES,
        "SINC_TAPS": stack.SINC_TAPS,
        "HI_TAPS": stack.HI_TAPS,
        "LOCK_WIN": stack.LOCK_WIN,
        "CARRIER_WIN": stack.CARRIER_WIN,
    }
    constants.update({name: getattr(stack, name) for name in stack.PARAM_NAMES})
    backend = StackOpenCL(
        sinc,
        hi,
        weight,
        afloor,
        constants,
        lag=lag,
        adaptive=mode == "adaptive",
        want_band=True,
        double=double,
        device=device,
        cl=cl,
    )
    got, got_band = backend.run(plan, margin, nout)
    scale = np.sqrt(np.mean(want**2))
    assert np.sqrt(np.mean((got - want) ** 2)) < tolerance * scale
    assert np.sqrt(np.mean(np.abs(got_band - want_band) ** 2)) < tolerance * scale
