"""Unit tests for the PAL analog audio carriers' image canceller.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The pits carry the video and audio FM carriers summed and hard-limited, so
the RF holds products at 2 fv - fa, the audio carriers' mirror images about
the video carrier.  Demodulated they are lines at fv - fa (6.0-7.2 MHz in
PAL) whose phase is the video carrier's less the audio carrier's.
RFDecode.pal_audio_image_cancel fits that line, with an amplitude that may
follow the video level; demodblock carries it beside the demod, and the
field subtracts it from the picture it writes only (dspicture, which the
servos and metrics read, stays as main decodes it).

All signals are synthetic.
"""

import types

import numpy as np
import pytest

from lddecode.rfdecode import RFDecode

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

RF_FS = 40e6
BL = 32768
L = BL // 2          # the half-rate demod's lattice
FL, FR = 0.68359375e6, 1.06640625e6
IRE0, HZ_IRE = 7.1e6, 8e5 / 100


def _stub():
    return types.SimpleNamespace(
        SysParams={"audio_lfreq": FL, "audio_rfreq": FR,
                   "ire0": IRE0, "hz_ire": HZ_IRE},
        blocklen=BL, freq_hz=RF_FS, blockcut=1024, blockcut_end=0,
        IMAGE_CANCEL_HALFBAND_HZ=RFDecode.IMAGE_CANCEL_HALFBAND_HZ,
        IMAGE_CANCEL_BAND_HZ=RFDecode.IMAGE_CANCEL_BAND_HZ,
        IMAGE_CANCEL_LEVEL_HZ=RFDecode.IMAGE_CANCEL_LEVEL_HZ,
        IMAGE_CANCEL_ORDER=RFDecode.IMAGE_CANCEL_ORDER,
    )


def _level(t):
    """A video level, 100 IRE = 1: a line-rate ramp between 0.1 and 0.7."""
    return 0.4 + 0.3 * np.sin(2 * np.pi * 15625.0 * t)


def _block(rng, audio):
    """The RF block's rfft (noise plus an FM carrier at each of audio),
    the analytic video carrier on the half-rate lattice, its level, and
    each audio carrier's phase on that lattice."""
    t = np.arange(BL) / RF_FS
    x = rng.normal(0, 1.0, BL)
    phases = {}
    for f in audio:
        phi = 2 * np.pi * f * t + 8.0 * np.sin(2 * np.pi * 7e3 * t + rng.uniform(0, 6))
        x += 30.0 * np.cos(phi)
        phases[f] = phi[0::2]
    th = np.arange(L) * 2 / RF_FS
    level = _level(th)
    fv = IRE0 + 100 * HZ_IRE * level
    phi_v = 2 * np.pi * np.cumsum(fv) * (2 / RF_FS)
    return np.fft.rfft(x), np.exp(1j * phi_v), fv, level, phases


def _image(level, phi_v, phi_a, c):
    """The image's line: Re(w(level) exp(j(phi_v - phi_a)))."""
    w = c[0] + c[1] * level + c[2] * level ** 2
    return np.real(w * np.exp(1j * (phi_v - phi_a)))


def _cancel(X, hilbert, demod):
    """The canceller's line taken out of demod, in place; the demod
    itself must come back untouched."""
    before = demod.copy()
    line = RFDecode.pal_audio_image_cancel(_stub(), X, hilbert, demod)
    np.testing.assert_array_equal(demod, before)
    if line is not None:
        demod -= line
    return line


def test_without_audio_carriers_there_is_no_line():
    rng = np.random.default_rng(1)
    X, hilbert, fv, _, _ = _block(rng, [])
    demod = fv + rng.normal(0, 3000, L)

    assert _cancel(X, hilbert, demod) is None


def test_a_level_dependent_image_line_is_removed():
    rng = np.random.default_rng(2)
    X, hilbert, fv, level, ph = _block(rng, [FL, FR])
    phi_v = np.angle(hilbert)
    clean = fv + rng.normal(0, 3000, L)
    lines = (_image(level, phi_v, ph[FR], (6000 * np.exp(0.4j), -4000, 2000j))
             + _image(level, phi_v, ph[FL], (3000 * np.exp(-1.2j), 1500, 0)))
    demod = clean + lines
    kept = slice(1024, None)
    line_rms = np.sqrt(np.mean(lines[kept] ** 2))

    _cancel(X, hilbert, demod)

    assert np.sqrt(np.mean((demod - clean)[kept] ** 2)) < 0.1 * line_rms


def test_a_block_of_one_level_still_fits_its_line():
    """Black or a still caption: the level barely moves, so its powers are
    nearly collinear; the fit falls back to a constant amplitude."""
    rng = np.random.default_rng(4)
    X, _, _, _, ph = _block(rng, [FR])
    fv = np.full(L, IRE0 + 1.0)
    hilbert = np.exp(1j * 2 * np.pi * np.cumsum(fv) * (2 / RF_FS))
    clean = fv + rng.normal(0, 3000, L)
    lines = _image(np.zeros(L), np.angle(hilbert), ph[FR], (5000, 0, 0))
    demod = clean + lines

    line = _cancel(X, hilbert, demod)

    assert line is not None and np.all(np.isfinite(line))
    kept = slice(1024, None)
    assert (np.sqrt(np.mean((demod - clean)[kept] ** 2))
            < 0.1 * np.sqrt(np.mean(lines[kept] ** 2)))


def test_picture_detail_in_the_fit_band_is_left_alone():
    """A 6.0 MHz picture tone, inside the band the image is fitted in but
    not locked to the audio's phase, keeps its amplitude."""
    rng = np.random.default_rng(3)
    X, hilbert, fv, _, _ = _block(rng, [FL, FR])
    th = np.arange(L) * 2 / RF_FS
    picture = 20000 * np.cos(2 * np.pi * 6.0e6 * th)
    demod = fv + picture + rng.normal(0, 3000, L)

    _cancel(X, hilbert, demod)

    probe = np.exp(-2j * np.pi * 6.0e6 * th[1024:])
    got = 2 * np.abs(np.mean((demod - fv)[1024:] * probe))
    np.testing.assert_allclose(got, 20000, rtol=0.01)


def test_the_field_writes_the_cleaned_demod_and_keeps_the_raw_one():
    """image_cleaned_demod is demod less the carried line, and None for a
    decode that does not carry one (the option off: output unchanged)."""
    from lddecode.field import Field

    video = np.rec.fromarrays(
        [np.full(8, 7.5e6), np.arange(8, dtype=np.float64)],
        names=["demod", "demod_image"])
    f = types.SimpleNamespace(data={"video": video})
    np.testing.assert_array_equal(Field.image_cleaned_demod(f),
                                  (7.5e6 - np.arange(8)).astype(np.float32))
    np.testing.assert_array_equal(video["demod"], 7.5e6)

    plain = types.SimpleNamespace(
        data={"video": np.rec.fromarrays([np.full(8, 7.5e6)], names=["demod"])})
    assert Field.image_cleaned_demod(plain) is None
    assert Field.image_cleaned_demod(types.SimpleNamespace(data=None)) is None


def test_the_image_is_subtracted_only_in_its_band():
    # The fitted line is taken out of the written picture in 5.0-7.9 MHz only:
    # unity across fv - fa (5.4-7.5 MHz), zero outside 5.0 / 7.9 MHz.
    rf = types.SimpleNamespace(IMAGE_BAND_HZ=RFDecode.IMAGE_BAND_HZ, freq_hz_demod=RF_FS / 2)
    n = 16384
    band = RFDecode.image_band(rf, n)
    f = np.fft.rfftfreq(n, 1.0 / rf.freq_hz_demod)
    assert band.shape == f.shape
    assert np.all(band[(f >= 5.4e6) & (f <= 7.5e6)] == 1.0)
    assert np.all(band[(f <= 5.0e6) | (f >= 7.9e6)] == 0.0)
    edge = band[(f > 5.0e6) & (f < 5.4e6)]
    assert np.all(np.diff(edge) >= 0) and edge.min() >= 0 and edge.max() <= 1
