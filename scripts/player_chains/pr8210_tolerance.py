#!/usr/bin/env python3
"""Monte Carlo tolerance spread of the PR-8210-A's main video path (F1 x F2 x aperture).

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

300 draws with +/-5 % on every L and C and +/-0.5 pF on the 8 pF parts; prints
the min/median/max magnitude and group delay at the multiburst frequencies and
the spread of the -3 dB point.  See docs/technical/player-video-chains.md.

Usage: python3 scripts/player_chains/pr8210_tolerance.py
"""

import numpy as np

p = 1e-12
u = 1e-6


def ladder(elems, rs, rl, f):
    w = 2 * np.pi * f
    out = np.empty(len(w), complex)
    for i, wi in enumerate(w):
        a = np.array([[1, rs], [0, 1]], complex)
        for k, z in elems:
            zz = z(wi)
            m = np.array([[1, zz], [0, 1]]) if k == "s" else np.array([[1, 0], [1 / zz, 1]])
            a = a @ m
        out[i] = 1 / (a[0, 0] + a[0, 1] / rl)
    return out


f = np.array([0.5, 1, 2, 3, 3.58, 4.0, 4.2, 4.5, 5.0]) * 1e6
fg = np.linspace(0.3e6, 6e6, 2000)
rng = np.random.default_rng(1)


def build(t):
    L = lambda v: lambda w, v=v: 1j * w * v
    C = lambda v: lambda w, v=v: 1 / (1j * w * v)
    P = lambda a, b: lambda w: 1 / (1 / a(w) + 1 / b(w))
    R = lambda v: lambda w, v=v: v + 0 * w
    f1 = [
        ("p", C(t(8 * p, 0.5 * p, 1))),
        ("s", P(L(t(39 * u, 0.05)), C(t(8 * p, 0.5 * p, 1)))),
        ("p", C(t(33 * p, 0.05))),
        ("s", P(L(t(43 * u, 0.05)), C(t(15 * p, 0.05)))),
        ("p", C(t(33 * p, 0.05))),
        ("s", R(100)),
        ("p", C(5 * p)),
    ]
    dl = [
        ("p", C(t(51 * p, 0.05))),
        ("s", L(t(12 * u, 0.05))),
        ("p", C(t(160 * p, 0.05))),
        ("s", L(t(16 * u, 0.05))),
        ("p", C(t(200 * p, 0.05))),
        ("s", L(t(18 * u, 0.05))),
        ("p", C(t(200 * p, 0.05))),
        ("s", L(t(18 * u, 0.05))),
        ("p", C(t(150 * p, 0.05))),
    ]
    return f1, dl


res = []
for k in range(300):

    def t(v, tol, absol=0):
        return v + rng.uniform(-tol, tol) if absol else v * (1 + rng.uniform(-tol, tol))

    f1, dl = build(t)
    h = ladder(f1, 1100, 200e3, fg) * ladder(dl, 270, 1500, fg) * np.sinc(fg * 30e-9)
    m = 20 * np.log10(abs(h))
    g = -np.gradient(np.unwrap(np.angle(h)), 2 * np.pi * fg)
    i0 = np.argmin(abs(fg - 0.5e6))
    row = []
    for fx in f:
        i = np.argmin(abs(fg - fx))
        row.append((m[i] - m[i0], 1e9 * (g[i] - g[i0])))
    i3 = np.where(m - m[i0] < -3)[0]
    row.append((fg[i3[0]] / 1e6, 0))
    res.append(row)
res = np.array(res)
print("freq  mag(min/median/max dB)   GDrel(min/median/max ns)")
for j, fx in enumerate(list(f / 1e6) + ["-3dB MHz"]):
    a = res[:, j, 0]
    b = res[:, j, 1]
    print(
        fx,
        np.round([a.min(), np.median(a), a.max()], 2),
        np.round([b.min(), np.median(b), b.max()], 0),
    )
