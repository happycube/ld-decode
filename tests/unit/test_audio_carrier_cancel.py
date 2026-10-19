"""Unit tests for the analog audio carriers' line canceller.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The disc's audio FM carriers intermodulate with the video carrier, and
demodulated video carries lines at the audio carriers' own frequencies and
phase (NTSC: 2.30 and 2.81 MHz).  The canceller works on slices of the
spectra: dsp.band_baseband takes a band down to 0 Hz on a sparse lattice
and dsp.band_subtract puts a signal back; dsp.unit_phasor reduces the
carrier to its phase; dsp.coherent_line_estimate fits a line locked to it,
with an amplitude that may follow the video level, and backs off for lines
too weak to fit.  RFDecode.audio_carrier_cancel wires them into demodblock.

All signals are synthetic.
"""

import types

import numpy as np
import pytest

from lddecode.dsp import (band_baseband, band_subtract, coherent_line_estimate,
                          unit_phasor)
from lddecode.rfdecode import RFDecode

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

FS = 20e6           # the half-rate demod's lattice
N = 16384
M = 2048            # slice bins, so a lattice every N/M = 8 samples
FA = 2.3011e6       # NTSC audio_lfreq
K0 = int(round(FA / (FS / N)))
LO = K0 - M // 2     # the carrier in the middle of its slice
BAND = slice(M // 2 - 205, M // 2 + 206)
FSD = FS * M / N
FIT = slice(64, M)


def _fm_phase(rng, t, dev_hz=60e3, fm_hz=7e3):
    """An FM carrier's phase at times t: FA, swept +-dev_hz by a tone at
    fm_hz.  Periodic over the block, as a block transform sees it."""
    fm = round(fm_hz * N / FS) * FS / N
    return (2 * np.pi * K0 * FS / N * t
            + (dev_hz / fm) * np.sin(2 * np.pi * fm * t + rng.uniform(0, 6)))


def _level(rng, t):
    """A video level, 100 IRE = 1: a slow line-rate pattern."""
    return 0.5 + 0.4 * np.sin(2 * np.pi * 15734.0 * t + rng.uniform(0, 6))


def _lattice():
    return np.arange(M) * (N // M) / FS


def test_band_baseband_is_the_analytic_signal_moved_down_on_a_sparse_lattice():
    rng = np.random.default_rng(1)
    t = np.arange(N) / FS
    x = np.cos(_fm_phase(rng, t))
    full = np.fft.fft(x)
    full[N // 2 + 1 :] = 0
    full[1 : N // 2] *= 2
    analytic = np.fft.ifft(full)[:: N // M]
    rot = np.exp(-2j * np.pi * LO * np.arange(M) / M)

    np.testing.assert_allclose(band_baseband(np.fft.rfft(x), LO, M, N),
                               analytic * rot, atol=1e-6)


def test_band_subtract_puts_back_what_band_baseband_took():
    rng = np.random.default_rng(2)
    t = np.arange(N) / FS
    far = 0.5 * np.cos(2 * np.pi * 4915 * FS / N * t)    # 6 MHz, on a bin
    spec = np.fft.rfft(np.cos(_fm_phase(rng, t)) + far)

    band_subtract(spec, band_baseband(spec, LO, M, N), LO, N)

    np.testing.assert_allclose(np.fft.irfft(spec, N), far, atol=1e-9)


def test_unit_phasor_is_the_carriers_phase_at_unit_magnitude():
    rng = np.random.default_rng(3)
    t = np.arange(N) / FS
    phi = _fm_phase(rng, t)
    spec = np.fft.rfft(3.0 * np.cos(phi) + 0.01 * rng.normal(size=N))
    p = unit_phasor(band_baseband(spec, LO, M, N, BAND))

    np.testing.assert_allclose(np.abs(p), 1.0, atol=1e-9)
    want = phi[:: N // M] - 2 * np.pi * LO * np.arange(M) / M
    err = np.angle(p * np.exp(-1j * want))
    assert np.sqrt(np.mean(err ** 2)) < 0.02


def test_a_level_dependent_line_is_estimated_and_removed():
    rng = np.random.default_rng(4)
    t = _lattice()
    p = np.exp(1j * _fm_phase(rng, t))
    level = _level(rng, t)
    c0, c1 = 4000 * np.exp(0.7j), 1500 * np.exp(-1.9j)
    line = (c0 + c1 * level) * p
    noise = rng.normal(0, 3000, M) + 1j * rng.normal(0, 3000, M)

    est, gain = coherent_line_estimate(line + noise, p, level, FIT, FSD)

    assert gain > 0.95
    resid = (line - est)[FIT]
    assert np.sqrt(np.mean(np.abs(resid) ** 2)) < 0.1 * np.sqrt(np.mean(np.abs(line[FIT]) ** 2))


def test_without_a_line_the_estimate_backs_off():
    """Noise alone projects onto the regressors; the control fits see the
    same projection, so the gain falls and little is subtracted."""
    rng = np.random.default_rng(5)
    t = _lattice()
    p = np.exp(1j * _fm_phase(rng, t))
    noise = rng.normal(0, 3000, M) + 1j * rng.normal(0, 3000, M)

    est, gain = coherent_line_estimate(noise, p, _level(rng, t), FIT, FSD)

    assert gain < 0.5
    assert np.sqrt(np.mean(np.abs(est) ** 2)) < 0.05 * 3000


def test_picture_detail_off_the_carrier_is_left_alone():
    """A 2.0 MHz picture tone beside the line keeps its amplitude once the
    estimate is taken out of the spectrum."""
    rng = np.random.default_rng(6)
    tf = np.arange(N) / FS
    picture = 20000 * np.cos(2 * np.pi * 2.0e6 * tf)
    carrier = np.cos(_fm_phase(rng, tf))
    spec = np.fft.rfft(picture + 5000 * carrier + rng.normal(0, 3000, N))
    p = unit_phasor(band_baseband(np.fft.rfft(carrier), LO, M, N, BAND))

    est, _ = coherent_line_estimate(band_baseband(spec, LO, M, N), p,
                                    _level(rng, _lattice()), FIT, FSD)
    band_subtract(spec, est, LO, N)
    left = np.fft.irfft(spec, N)[512:]
    probe = np.exp(-2j * np.pi * 2.0e6 * tf[512:])

    np.testing.assert_allclose(2 * np.abs(np.mean(left * probe)), 20000, rtol=0.01)


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
        AUDIO_CANCEL_SLICE=RFDecode.AUDIO_CANCEL_SLICE,
        AUDIO_CANCEL_LEVEL_HZ=RFDecode.AUDIO_CANCEL_LEVEL_HZ,
    )

    def cancel(X, demod):
        """The canceller on demod's spectrum, as demodblock runs it; demod
        takes the result, and the spectrum before and after is returned."""
        spectrum = np.fft.rfft(demod - 8.1e6)
        before = spectrum.copy()
        RFDecode.audio_carrier_cancel(stub, X, spectrum, 8.1e6)
        demod[:] = np.fft.irfft(spectrum, len(demod)) + 8.1e6
        return before, spectrum

    return cancel


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
    before, after = _rf_stub()(X, _demod(rng))

    np.testing.assert_array_equal(after, before)


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
    before, after = _rf_stub(ac3=True)(X, clean + np.real(6000 * np.exp(1j * ph[FR])))

    np.testing.assert_array_equal(after, before)
