"""Unit tests for the decoder's demodulation on an OpenCL device.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

demod_opencl.DemodOpenCL runs RFDecode.demodblock on a GPU, a batch of
blocks at a time.  The tests that need a device are skipped without
pyopencl or without an OpenCL device; the rest run everywhere.  All signals
are synthetic.
"""

import math

import numpy as np
import pytest

from lddecode import demod_opencl, rfdecode
from lddecode.rfdecode import RFDecode

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

TAU = 2.0 * math.pi


def test_the_fft_passes_cover_the_length():
    assert demod_opencl.fft_radices(32768) == [8, 8, 8, 8, 8]
    assert demod_opencl.fft_radices(16384) == [8, 8, 8, 8, 4]
    assert demod_opencl.fft_radices(1024) == [8, 8, 8, 2]
    with pytest.raises(ValueError):
        demod_opencl.fft_radices(3000)


def test_without_a_device_the_blocks_are_demodulated_on_the_cpu(monkeypatch):
    """demodblocks falls back to demodblock when the device cannot be opened."""
    rf = RFDecode(inputfreq=40.0, system="NTSC", extra_options={"DemodDevice": "opencl"})
    monkeypatch.setattr(rfdecode, "_device_demod", lambda rf: None)
    rng = np.random.default_rng(1)
    blocks = [rng.normal(scale=2000.0, size=rf.blocklen).astype(np.int16) for _ in range(2)]
    got = rf.demodblocks(blocks, 0, cut=True)
    want = [rf.demodblock(data=b, mtf_level=0, cut=True) for b in blocks]
    assert not rf.uses_device_demod()
    for g, w in zip(got, want):
        np.testing.assert_array_equal(g["video"]["demod"], w["video"]["demod"])


# --- on a device ------------------------------------------------------------


@pytest.fixture(scope="module")
def device():
    cl = pytest.importorskip("pyopencl")
    from lddecode.stack_opencl import open_device
    try:
        ctx, queue, _ = open_device(cl)
    except Exception as error:   # no platform, no device, no driver
        pytest.skip(f"no OpenCL device: {error}")
    return cl, ctx, queue


def test_the_device_fft_is_numpys(device):
    cl, ctx, queue = device
    program = cl.Program(ctx, demod_opencl.KERNEL_SOURCE).build(
        options=["-DN=1024", "-DM=512", "-DNRF=513"])
    kernels = {k.function_name: k for k in program.all_kernels()}
    rng = np.random.default_rng(2)
    for length in (1024, 512):
        x = rng.normal(size=(3, length)) + 1j * rng.normal(size=(3, length))
        mf = cl.mem_flags
        buf = cl.Buffer(ctx, mf.READ_WRITE | mf.COPY_HOST_PTR, hostbuf=x)
        scratch = cl.Buffer(ctx, mf.READ_WRITE, size=x.nbytes)
        fft = demod_opencl.DeviceFFT(cl, ctx, kernels, length, True)
        out = fft.run(queue, buf, scratch, 3)
        y = np.empty_like(x)
        cl.enqueue_copy(queue, y, out)
        queue.finish()
        np.testing.assert_allclose(y, np.fft.fft(x, axis=1), rtol=0,
                                   atol=1e-12 * np.abs(y).max())


def _rf_block(rf, seed):
    """An FM video carrier (a random slow picture, a sweep across the band)
    with the two audio carriers and some noise."""
    rng = np.random.default_rng(seed)
    n = rf.blocklen
    t = np.arange(n) / rf.freq_hz
    lo, hi = rf.iretohz(0.0), rf.iretohz(100.0)
    level = 0.5 + 0.5 * np.sin(TAU * 15734.0 * t + seed) * np.cos(TAU * 60.0 * t)
    freq = lo + (hi - lo) * level + 2e4 * rng.normal(size=n).cumsum() / np.sqrt(n)
    phase = TAU * np.cumsum(freq) / rf.freq_hz
    fa, fb = rf.SysParams["audio_lfreq"], rf.SysParams["audio_rfreq"]
    x = 8000.0 * np.cos(phase + 0.01 * np.sin(TAU * fa * t))
    x += 1500.0 * np.cos(TAU * fa * t + 0.3) + 1500.0 * np.cos(TAU * fb * t + 0.6)
    x += 200.0 * rng.normal(size=n)
    return np.clip(np.round(x), -32768, 32767).astype(np.int16)


@pytest.mark.parametrize("system", ["NTSC", "PAL"])
def test_the_device_demodulates_as_the_cpu_does(device, system):
    cl, ctx, queue = device
    rf = RFDecode(inputfreq=40.0, system=system, extra_options={},
                  decode_analog_audio=44100, decode_digital_audio=True)
    blocks = [_rf_block(rf, s) for s in range(3)]
    gpu = demod_opencl.DemodOpenCL(rf, cl=cl, ctx=ctx, queue=queue).demod(blocks, 0.4)
    cpu = [rf.demodblock(data=b, mtf_level=0.4, cut=True) for b in blocks]
    for g, c in zip(gpu, cpu):
        assert g["video"].dtype == c["video"].dtype
        assert g["video"].shape == c["video"].shape
        for name in c["video"].dtype.names:
            diff = np.abs(g["video"][name].astype(float) - c["video"][name].astype(float))
            # A float32 ulp at the video carrier's frequency is 0.5-1 Hz.
            assert diff.max() <= 2.0, name
        np.testing.assert_allclose(g["rfhpf"], c["rfhpf"], rtol=0, atol=1e-2)
        assert np.max(np.abs(g["efm"].astype(int) - c["efm"].astype(int))) <= 1
        for name in ("audio_left", "audio_right"):
            np.testing.assert_allclose(g["audio"][name], c["audio"][name], rtol=0, atol=1.0)
