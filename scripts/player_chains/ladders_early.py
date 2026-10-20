#!/usr/bin/env python3
"""First-pass ladder simulations: CLD-S180 filters and RF band-pass, LDP-1500P low-pass.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The CLD-S180 post-demodulator low-pass (several source impedances) and RF
band-pass, and the Sony LDP-1500P PR-80 post-demodulator low-pass.  The
CLD-S180 second low-pass here is loaded with R483 1k, which was a misreading:
R483 is Q475's emitter resistor.  ic_players.py has the corrected model.
See docs/technical/player-video-chains.md.

Usage: python3 scripts/player_chains/ladders_early.py
"""

import numpy as np


def Zl(L, w):
    return 1j * w * L


def Zc(C, w):
    return 1 / (1j * w * C)


def par(a, b):
    return a * b / (a + b)


def ladder(elems, Rs, Rl, f):
    # elems: list of ('s', zfunc) or ('p', zfunc) from source to load; ABCD
    w = 2 * np.pi * f
    H = []
    for wi in w:
        A = np.array([[1, Rs], [0, 1]], dtype=complex)
        for kind, z in elems:
            Z = z(wi)
            M = np.array([[1, Z], [0, 1]]) if kind == "s" else np.array([[1, 0], [1 / Z, 1]])
            A = A @ M
        # V_in source / V_load
        H.append(1 / (A[0, 0] + A[0, 1] / Rl))
    H = np.array(H)
    return H


def report(name, elems, Rs, Rl, Hdc_norm=True):
    f = np.linspace(0.05e6, 20e6, 40000)
    H = ladder(elems, Rs, Rl, f)
    H0 = H[np.argmin(abs(f - 0.5e6))]
    mag = 20 * np.log10(abs(H / H0))
    ph = np.unwrap(np.angle(H))
    gd = -np.gradient(ph, 2 * np.pi * f)
    gd0 = gd[np.argmin(abs(f - 0.5e6))]
    print(f"== {name}  Rs={Rs} Rl={Rl}")
    for fx in [1, 2, 3, 3.58, 4.0, 4.2, 4.5, 5, 5.5, 6, 7, 8.1, 9.3, 12, 16.2]:
        i = np.argmin(abs(f - fx * 1e6))
        print(f"  {fx:5.2f} MHz: {mag[i]:7.2f} dB  gd(rel 0.5MHz) {1e9 * (gd[i] - gd0):7.1f} ns")
    i3 = np.where(mag < -3)[0][0]
    print(f"  -3 dB at {f[i3] / 1e6:.2f} MHz; abs gd@0.5MHz {gd0 * 1e9:.1f} ns")
    # zeros
    mins = [
        f[i] / 1e6
        for i in range(1, len(f) - 1)
        if mag[i] < mag[i - 1] and mag[i] < mag[i + 1] and mag[i] < -30
    ]
    print("  notches (MHz):", [round(m, 2) for m in mins])


p = 1e-12
u = 1e-6
# CLD-S180 post-demod LPF (IC400 pin25 -> Q451)
s180 = [
    ("p", lambda w: Zc(27 * p, w)),
    ("s", lambda w: par(Zl(43 * u, w), Zc(15 * p, w))),
    ("p", lambda w: Zc(33 * p, w)),
    ("s", lambda w: par(Zl(43 * u, w), Zc(1 / (1 / 7 + 1 / 10) * p, w))),
    ("p", lambda w: Zc(12 * p, w)),
]
for Rs in [0.1, 47, 1200]:
    report("CLD-S180 post-demod LPF", s180, Rs, 1200)
# CLD-S180 second LPF pin14 -> Q475
s180b = [
    ("s", lambda w: 820 + 0 * w),
    ("p", lambda w: Zc(12 * p, w)),
    ("s", lambda w: par(Zl(22 * u, w), Zc(15 * p, w))),
    ("p", lambda w: Zc(39 * p, w)),
]
report("CLD-S180 LPF pin14->Q475 (R480 820 src, Rl=1k R483)", s180b, 0.1, 1000)
# LDP-1500P PR-80 post-demod LPF
l15 = [
    ("p", lambda w: Zc(12 * p, w)),
    ("s", lambda w: Zl(68 * u, w)),
    ("p", lambda w: Zc(33 * p, w)),
    ("s", lambda w: par(Zl(68 * u, w), Zc(2.7 * p, w))),
    ("p", lambda w: Zc(10 * p, w)),
]
for Rs, Rl in [(1500, 3200), (1500, 1500)]:
    report("LDP-1500P PR-80 post-demod LPF", l15, Rs, Rl)
print("\n#### RF filter CLD-S180")
rf = [
    ("s", lambda w: Zc(27 * p, w) + 680),
    ("s", lambda w: par(Zl(27 * u, w), Zc(120 * p, w))),
    ("s", lambda w: par(Zl(22 * u, w), Zc(220 * p, w))),
    ("p", lambda w: Zc(16 * p, w)),
    ("s", lambda w: Zl(10 * u, w)),
    ("p", lambda w: Zc(27 * p, w)),
    ("s", lambda w: par(Zl(8.2 * u, w), Zc(10 * p, w))),
    ("p", lambda w: Zc(10 * p, w)),
]
f = np.array([1, 2.3, 2.8, 4, 5, 6, 7, 7.6, 8.1, 9.3, 10, 11, 12, 13, 14, 15, 17.6, 20]) * 1e6
H = ladder(rf, 0.1, 680, f)
ref = abs(ladder(rf, 0.1, 680, np.array([8.1e6]))[0])
for fi, h in zip(f, H):
    print("  %5.1f MHz %7.2f dB (rel 8.1 MHz)" % (fi / 1e6, 20 * np.log10(abs(h) / ref)))
