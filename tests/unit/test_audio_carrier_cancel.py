"""Unit tests for the analog audio carriers' line canceller.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The disc's audio FM carriers intermodulate with the video carrier, and
demodulated video carries lines at the audio carriers' own frequencies and
phase (NTSC: 2.30 and 2.81 MHz).  dsp.band_phasor takes a carrier's phase
from the RF; dsp.coherent_line_estimate fits a line locked to it, with an
amplitude that may follow the video level, and backs off for lines too weak
to fit.  RFDecode.audio_carrier_cancel wires the two into demodblock.

All signals are synthetic.
"""

import types

import numpy as np
import pytest

from lddecode.dsp import band_phasor, coherent_line_estimate
from lddecode.rfdecode import RFDecode

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

FS = 20e6           # the half-rate demod's lattice
N = 16384
FA = 2.3011e6       # NTSC audio_lfreq
FIT = slice(512, N)


def _fm_phase(rng, dev_hz=60e3, fm_hz=7e3):
    """An FM carrier's phase: FA, swept +-dev_hz by a tone at fm_hz."""
    t = np.arange(N) / FS
    return (2 * np.pi * FA * t
            + (dev_hz / fm_hz) * np.sin(2 * np.pi * fm_hz * t + rng.uniform(0, 6)))


def _level(rng):
    """A video level, 100 IRE = 1: a line-rate step pattern."""
    t = np.arange(N) / FS
    return 0.5 + 0.4 * np.sign(np.sin(2 * np.pi * 15734.0 * t + rng.uniform(0, 6)))


def test_band_phasor_is_the_carriers_phase_at_unit_magnitude():
    rng = np.random.default_rng(1)
    phi = _fm_phase(rng)
    block = 3.0 * np.cos(phi) + 0.01 * rng.normal(size=N)
    fpb = FS / N
    p = band_phasor(np.fft.rfft(block), int((FA - 250e3) / fpb),
                    int((FA + 250e3) / fpb) + 1, N)

    np.testing.assert_allclose(np.abs(p), 1.0, atol=1e-9)
    mid = slice(N // 4, 3 * N // 4)
    err = np.angle(p[mid] * np.exp(-1j * phi[mid]))
    assert np.sqrt(np.mean(err ** 2)) < 0.02


def test_band_phasor_on_half_the_lattice_is_the_even_samples():
    """demodblock's half-rate chain: the n/2-point inverse of the same bins
    is the full-rate phasor's even samples."""
    rng = np.random.default_rng(2)
    block = np.cos(_fm_phase(rng)) + 0.01 * rng.normal(size=N)
    spec = np.fft.rfft(block)
    lo, hi = int((FA - 250e3) / FS * N), int((FA + 250e3) / FS * N) + 1

    np.testing.assert_allclose(band_phasor(spec, lo, hi, N // 2),
                               band_phasor(spec, lo, hi, N)[0::2], atol=1e-9)


def test_a_level_dependent_line_is_estimated_and_removed():
    rng = np.random.default_rng(3)
    p = np.exp(1j * _fm_phase(rng))
    level = _level(rng)
    c0, c1 = 4000 * np.exp(0.7j), 1500 * np.exp(-1.9j)
    line = np.real((c0 + c1 * level) * p)
    target = 8.1e6 + line + rng.normal(0, 3000, N)

    est, gain = coherent_line_estimate(target, p, level, FIT, FS)

    assert gain > 0.95
    resid = (line - est)[FIT]
    assert np.sqrt(np.mean(resid ** 2)) < 0.1 * np.sqrt(np.mean(line[FIT] ** 2))


def test_without_a_line_the_estimate_backs_off():
    """Noise alone projects onto the regressors; the control fits see the
    same projection, so the gain falls and little is subtracted."""
    rng = np.random.default_rng(4)
    p = np.exp(1j * _fm_phase(rng))
    noise = rng.normal(0, 3000, N)

    est, gain = coherent_line_estimate(8.1e6 + noise, p, _level(rng), FIT, FS)

    assert gain < 0.5
    assert np.sqrt(np.mean(est ** 2)) < 0.02 * 3000


def test_picture_detail_off_the_carrier_is_left_alone():
    """A 2.0 MHz picture tone beside the line keeps its amplitude once the
    estimate is subtracted."""
    rng = np.random.default_rng(5)
    p = np.exp(1j * _fm_phase(rng))
    t = np.arange(N) / FS
    picture = 20000 * np.cos(2 * np.pi * 2.0e6 * t)
    line = np.real(5000 * p)
    target = 8.1e6 + picture + line + rng.normal(0, 3000, N)

    est, _ = coherent_line_estimate(target, p, _level(rng), FIT, FS)
    left = (target - est)[FIT]
    probe = np.exp(-2j * np.pi * 2.0e6 * t[FIT])
    amp = 2 * np.abs(np.mean((left - left.mean()) * probe))

    np.testing.assert_allclose(amp, 20000, rtol=0.01)


# --- RFDecode.audio_carrier_cancel wiring, on a stub `self` -------------

RF_FS = 40e6
BL = 32768
FL, FR = 2.3011e6, 2.8125e6


def _rf_stub(ac3=False):
    stub = types.SimpleNamespace(
        SysParams={"audio_lfreq": FL, "audio_rfreq": FR, "AC3": ac3,
                   "ire0": 8.1e6, "hz_ire": 1.7e6 / 140, "vsync_ire": -40},
        full_rate_demod=False, blocklen=BL, freq_hz=RF_FS,
        freq_hz_demod=RF_FS / 2, blockcut=1024, blockcut_end=0,
        AUDIO_CANCEL_HALFBAND_HZ=RFDecode.AUDIO_CANCEL_HALFBAND_HZ,
        AUDIO_CANCEL_MIN_SNR=RFDecode.AUDIO_CANCEL_MIN_SNR,
    )
    return lambda X, demod: RFDecode.audio_carrier_cancel(stub, X, demod)


def _rf_block(rng, carriers):
    """Noise, plus an FM carrier at each frequency in carriers; returns the
    rfft and each carrier's phase on the half-rate lattice."""
    t = np.arange(BL) / RF_FS
    x = rng.normal(0, 1.0, BL)
    phases = {}
    for f in carriers:
        phi = 2 * np.pi * f * t + 8.0 * np.sin(2 * np.pi * 7e3 * t + rng.uniform(0, 6))
        x += 30.0 * np.cos(phi)
        phases[f] = phi[0::2]
    return np.fft.rfft(x), phases


def _demod(rng):
    """Half-rate demod at blanking, with noise."""
    return 8.1e6 + rng.normal(0, 3000, BL // 2)


def test_without_audio_carriers_the_demod_is_untouched():
    rng = np.random.default_rng(6)
    X, _ = _rf_block(rng, [])
    demod = _demod(rng)
    before = demod.copy()

    _rf_stub()(X, demod)

    np.testing.assert_array_equal(demod, before)


def test_a_carriers_line_is_removed_from_the_demod():
    rng = np.random.default_rng(7)
    X, ph = _rf_block(rng, [FL, FR])
    clean = _demod(rng)
    demod = (clean + np.real(5000 * np.exp(1.1j) * np.exp(1j * ph[FL]))
             + np.real(6000 * np.exp(-2.0j) * np.exp(1j * ph[FR])))
    line_rms = np.sqrt(np.mean((demod - clean)[512:] ** 2))

    _rf_stub()(X, demod)

    assert np.sqrt(np.mean((demod - clean)[512:] ** 2)) < 0.1 * line_rms


def test_ac3s_right_channel_is_never_a_phase_reference():
    """With AC3 the right channel is QPSK, not an FM carrier: a line locked
    to whatever sits there is left in place."""
    rng = np.random.default_rng(8)
    X, ph = _rf_block(rng, [FR])
    clean = _demod(rng)
    demod = clean + np.real(6000 * np.exp(1j * ph[FR]))
    before = demod.copy()

    _rf_stub(ac3=True)(X, demod)

    np.testing.assert_array_equal(demod, before)
