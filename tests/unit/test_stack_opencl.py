"""Unit tests for the OpenCL backend's wiring into the stacked source.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The device itself is out of reach of a hermetic test: the backend is
replaced by a recording stand-in (the ``opencl_factory`` seam), and these
tests check what the source hands it and what it does with the result.  The
kernels are checked on a real device by
tests/functional/test_stack_opencl_device.py.

All signals are synthetic.
"""

from __future__ import annotations

import builtins

import numpy as np
import pytest
from test_stack import FS, _capture, _install_locator

from lddecode import stack, stack_opencl
from lddecode.stack import StackedSource

pytestmark = [pytest.mark.unit, pytest.mark.decode]


class _Backend:
    """The device backend, recorded: it serves a known chunk."""

    instances: list = []

    def __init__(self, sinc, hi, weight, afloor, constants, **kwargs):
        self.sinc = sinc
        self.hi = hi
        self.weight = list(weight)
        self.afloor = list(afloor)
        self.constants = dict(constants)
        self.kwargs = kwargs
        self.runs = []
        _Backend.instances.append(self)

    def run(self, plan, margin, nout):
        self.runs.append((plan, margin, nout))
        return np.full(nout, 7.0), np.zeros(nout, dtype=np.complex128)


def _gpu_source(monkeypatch, **kwargs):
    rng = np.random.default_rng(41)
    captures = [_capture(0.0, rng, 5.0), _capture(1.5, rng, 5.0)]
    _install_locator(monkeypatch, captures, [0.0, 1.5])
    _Backend.instances.clear()
    options = dict(cancel_xtalk=False, cancel_xtal=False, cancel_leak=False)
    options.update(kwargs)
    return StackedSource(
        captures, FS, ntsc=True, device="opencl", opencl_factory=_Backend, **options
    )


def test_the_device_gets_the_tables_the_weights_and_the_constants(monkeypatch):
    """The backend is built from the host's own tables, weights and tuning
    constants, so the device evaluates the plan the host would."""
    source = _gpu_source(monkeypatch)
    try:
        backend = _Backend.instances[-1]
        assert backend.sinc is source._sinc
        assert backend.hi is source._hi
        assert backend.weight == source.weight
        assert backend.afloor == source.afloor
        assert backend.constants["PHASES"] == stack.SINC_PHASES
        assert backend.constants["LOCK_WIN"] == stack.LOCK_WIN
        assert backend.constants["Q_ROT"] == stack.Q_ROT
        assert backend.kwargs == dict(lag=source.lag, adaptive=True, want_band=False, double=True)
    finally:
        source.close()


def test_the_stream_is_the_devices_combination(monkeypatch):
    """With --device opencl the chunk is what the device combined, over the
    plan's samples within the lock margins."""
    source = _gpu_source(monkeypatch)
    try:
        got = source.read(0, 100)
        np.testing.assert_array_equal(got, np.full(100, 7.0, dtype=np.float32))
        plan, margin, nout = _Backend.instances[-1].runs[0]
        assert margin == stack.LOCK_MARGIN
        assert plan.length == nout + 2 * margin
        assert plan.inputs[0].a0 is not None
    finally:
        source.close()


def test_single_precision_and_the_fixed_weights_reach_the_device(monkeypatch):
    source = _gpu_source(monkeypatch, stack_weight="fixed", device_precision="single")
    try:
        assert _Backend.instances[-1].kwargs["adaptive"] is False
        assert _Backend.instances[-1].kwargs["double"] is False
    finally:
        source.close()


def test_an_unknown_device_is_refused():
    with pytest.raises(ValueError, match="device"):
        StackedSource([], FS, ntsc=True, device="cuda")


def test_the_kernels_are_built_with_every_digit_of_the_constants():
    """The device reads the host's values: the floats are written with
    repr, the integers as integers."""
    constants = {
        "PHASES": 1024,
        "SINC_TAPS": 32,
        "HI_TAPS": 128,
        "LOCK_WIN": 128,
        "CARRIER_WIN": 64,
        "QN_LOCK": 0.4,
        "QN_CARRIER": 0.5,
        "LOCK_PRIOR": 10.0,
        "KAPPA_LO": 0.5,
        "KAPPA_SPAN": 0.3,
        "Q_LO": 0.7,
        "Q_SPAN": 0.15,
        "Q_MAX": 0.999,
        "Q_ROT": 0.5,
        "H_LO": 0.5,
        "H_SPAN": 0.3,
    }
    opts = stack_opencl.build_options(
        constants, lag=5, adaptive=True, want_band=True, double=False
    )
    for expected in ("-DPHASES=1024", "-DQ_MAX=0.999", "-DLAG=5", "-DCARRIER_COMBINE"):
        assert expected in opts
    assert "-DXTALK" in opts and "-DREAL=float" in opts
    fixed = stack_opencl.build_options(
        constants, lag=5, adaptive=False, want_band=False, double=True
    )
    assert "-DCARRIER_COMBINE" not in fixed and "-DXTALK" not in fixed
    assert "-DREAL=double" in fixed


def test_a_missing_pyopencl_says_how_to_get_it(monkeypatch):
    real_import = builtins.__import__

    def no_pyopencl(name, *args, **kwargs):
        if name == "pyopencl":
            raise ImportError("no pyopencl")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_pyopencl)
    with pytest.raises(RuntimeError, match="pyopencl"):
        stack_opencl._import_pyopencl()
