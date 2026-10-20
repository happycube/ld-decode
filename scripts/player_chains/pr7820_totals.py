#!/usr/bin/env python3
"""PR-7820 chain totals, the effective de-emphasis, and RF sideband ratios.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Builds on the stage models in pr7820.py: the whole chain (RF at 7.6/8.1/9.3 MHz
through the VDEM and either VTBC board), each divided by an ideal 120/320 ns
de-emphasis so it compares with ld-decode's own chain, and the upper/lower
sideband ratio of the RF chain.  See docs/technical/player-video-chains.md.

Usage: python3 scripts/player_chains/pr7820_totals.py
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pr7820 import (  # noqa: E402
    VF,
    M,
    ccd_aperture,
    deemph,
    deemph_ldd,
    detector,
    fm_equiv,
    gd,
    ldd_lpf,
    m3db,
    q7q8,
    q9q10,
    rf_pre_limiter,
    vdem_bpf,
    vdem_lpf1,
    vdem_lpf2,
    vdem_traps,
    vdem_video,
    vtbc_new,
    vtbc_old,
)

VFx = VF


def rel(name, H, ref=0.5):
    f = np.array(VFx) * M
    h = H(f)
    h0 = H(np.array([ref * M]))[0]
    g0 = gd(H, ref)
    print(f"--- {name}")
    print(
        "   "
        + "  ".join(
            f"{x}:{20 * np.log10(abs(v / h0)):+.2f}dB/{(gd(H, x) - g0) * 1e9:+.0f}ns"
            for x, v in zip(VFx, h)
        )
    )
    print(f"   abs GD at 0.5 MHz {g0 * 1e9:.0f} ns; -3 dB at {m3db(H)} MHz")


nod = lambda H: lambda f: H(f) / deemph_ldd(f)
rf81 = fm_equiv(rf_pre_limiter, 8.1e6)
pole26 = lambda f: 1 / (1 + 1j * f / 26e6)
rf81p = fm_equiv(lambda f: rf_pre_limiter(f) * pole26(f), 8.1e6)
rel("RF chain FM-equiv @8.1 (EQ*BPF*traps)", rf81)
rel("RF chain FM-equiv @8.1 incl. 26 MHz head-amp pole", rf81p)
rel("VDEM video chain / ideal 120-320 deemph", nod(vdem_video))
rel(
    "VDEM video chain without C58 / ideal deemph",
    nod(
        lambda f: (
            detector(f) * vdem_lpf1(f) * q7q8(f) * q9q10(f, c58=1e-15) * deemph(f) * vdem_lpf2(f)
        )
    ),
)
rel("PR-7820 deemph / ideal ldd deemph (mismatch)", lambda f: deemph(f) / deemph_ldd(f))
for nm, vt in (("old VTBC", vtbc_old), ("new VTBC", vtbc_new)):
    rel(
        f"RF@8.1 * VDEM * {nm}  / ideal deemph",
        nod(lambda f, vt=vt: rf81(f) * vdem_video(f) * vt(f)),
    )
    rel(
        f"RF@8.1 * VDEM * {nm}  / ideal deemph, CCD hold T",
        nod(
            lambda f, vt=vt: (
                rf81(f) * vdem_video(f) * vt(f) / ccd_aperture(f) * ccd_aperture(f, hold=1.0)
            )
        ),
    )
    rel("VDEM output only (no RF, no VTBC) / ideal deemph", nod(vdem_video))
rel(
    "RF@7.6 * VDEM * old VTBC / deemph",
    nod(lambda f: fm_equiv(rf_pre_limiter, 7.6e6)(f) * vdem_video(f) * vtbc_old(f)),
)
rel(
    "RF@9.3 * VDEM * old VTBC / deemph",
    nod(lambda f: fm_equiv(rf_pre_limiter, 9.3e6)(f) * vdem_video(f) * vtbc_old(f)),
)
for rgm in (100, 300):
    rel(
        f"RF@8.1 (1/gm={rgm}) * VDEM * old VTBC / deemph",
        nod(
            lambda f: (
                fm_equiv(lambda x: rf_pre_limiter(x, rgm=rgm), 8.1e6)(f)
                * vdem_video(f)
                * vtbc_old(f)
            )
        ),
    )
rel("ld-decode LPF (Butterworth6 4.5)", ldd_lpf)
# sideband ratios
for fc in (7.6e6, 8.1e6, 9.3e6):
    for fm in (3.58e6, 4.2e6):
        H = lambda x: rf_pre_limiter(np.array([x]))[0]
        print(
            f"fc {fc / M} fm {fm / M}: USB/LSB = {20 * np.log10(abs(H(fc + fm) / H(fc - fm))):+.2f} dB ; BPF*traps only {20 * np.log10(abs(vdem_bpf(np.array([fc + fm]))[0] * vdem_traps(np.array([fc + fm]))[0] / (vdem_bpf(np.array([fc - fm]))[0] * vdem_traps(np.array([fc - fm]))[0]))):+.2f} dB"
        )
print(
    "deemph tz=%.1f ns tp(Rsrc=0)=%.1f ns tp(Rsrc=7)=%.1f ns shelf=%.2f dB"
    % (220 * 560e-3, 550 * 560e-3, 557 * 560e-3, 20 * np.log10(220 / 550))
)
