#!/usr/bin/env python3
"""Pioneer CLD-S180/CLD-D406 and Panasonic LX-1000U video-path filter simulations.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The post-demodulator, post-NR and post-DAC low-passes, the de-emphasis
networks (inverting-amplifier assumption), the switched RF correction shelves
and the LX-1000U's phase splitter, coupling network and A/D anti-alias filter,
from the values on the CLD-D406 mother assembly (G-a/G-b), the CLD-S180 SCH-5
and the LX-1000U video and digital-process schematics.  Ideal components and
transistors.  This supersedes ladders_early.py's model of the CLD-S180's
second low-pass (its load is the Q475 base, not R483).  See docs/technical/player-video-chains.md.

Usage: python3 scripts/player_chains/ic_players.py
"""

import numpy as np

p = 1e-12
u = 1e-6
F = [3.58, 4.0, 4.2, 4.5, 5.0, 6.0]


def Zl(L, w):
    return 1j * w * L


def Zc(C, w):
    return 1 / (1j * w * C)


def par(a, b):
    return a * b / (a + b)


def ladder(elems, Rs, Rl, f):
    out = []
    for wi in 2 * np.pi * f:
        A = np.array([[1, Rs], [0, 1]], dtype=complex)
        for k, z in elems:
            Z = z(wi)
            A = A @ (np.array([[1, Z], [0, 1]]) if k == "s" else np.array([[1, 0], [1 / Z, 1]]))
        out.append(1 / (A[0, 0] + A[0, 1] / Rl))
    return np.array(out)


f = np.linspace(0.05e6, 25e6, 50000)


def analyse(name, H):
    i0 = np.argmin(abs(f - 0.5e6))
    mag = 20 * np.log10(abs(H / H[i0]))
    gd = -np.gradient(np.unwrap(np.angle(H)), 2 * np.pi * f)
    s = f"{name}: " + ", ".join(f"{x}MHz {mag[np.argmin(abs(f - x * 1e6))]:.2f}dB" for x in F)
    s += f" | GD rel0.5: 4.0 {1e9 * (gd[np.argmin(abs(f - 4e6))] - gd[i0]):.0f}ns, 4.2 {1e9 * (gd[np.argmin(abs(f - 4.2e6))] - gd[i0]):.0f}ns"
    i3 = np.where(mag < -3)[0]
    s += f" | -3dB {f[i3[0]] / 1e6:.2f}MHz" if len(i3) else ""
    notch = [
        round(f[i] / 1e6, 2)
        for i in range(1, len(f) - 1)
        if mag[i] < mag[i - 1] and mag[i] < mag[i + 1] and mag[i] < -30
    ]
    s += f" | notches {notch}"
    print(s)
    return mag, gd


def lad(name, el, Rs, Rl):
    return analyse(f"{name} [Rs={Rs},Rl={Rl}]", ladder(el, Rs, Rl, f))


print("=== CLD-D406 filter 1 (pin25->Q451), C434=12p")
d406 = [
    ("p", lambda w: Zc(27 * p, w)),
    ("s", lambda w: par(Zl(43 * u, w), Zc(12 * p, w))),
    ("p", lambda w: Zc(33 * p, w)),
    ("s", lambda w: par(Zl(43 * u, w), Zc(1 / (1 / 7 + 1 / 10) * p, w))),
    ("p", lambda w: Zc(12 * p, w)),
]
for Rs in [1, 1200]:
    lad("D406 LPF1", d406, Rs, 1200)
print("=== CLD-S180 filter 1 (C434=15p) for reference")
s180 = [
    ("p", lambda w: Zc(27 * p, w)),
    ("s", lambda w: par(Zl(43 * u, w), Zc(15 * p, w))),
    ("p", lambda w: Zc(33 * p, w)),
    ("s", lambda w: par(Zl(43 * u, w), Zc(1 / (1 / 7 + 1 / 10) * p, w))),
    ("p", lambda w: Zc(12 * p, w)),
]
for Rs in [1, 1200]:
    lad("S180 LPF1", s180, Rs, 1200)
print("=== D406/S180 filter 2 (pin14 -> R480 820 -> Q475 base), load = base ~100k")
f2 = [
    ("s", lambda w: 820 + 0 * w),
    ("p", lambda w: Zc(12 * p, w)),
    ("s", lambda w: par(Zl(22 * u, w), Zc(15 * p, w))),
    ("p", lambda w: Zc(39 * p, w)),
]
for Rl in [100e3, 10e3]:
    lad("LPF2", f2, 1, Rl)
print("=== LX-1000 5.5MHz LPF (Q3204 emitter -> R3221 560 -> ladder -> R3222 5.6k || Q3205)")
lx1 = [
    ("s", lambda w: 560 + 0 * w),
    ("p", lambda w: Zc(24 * p, w)),
    ("s", lambda w: Zl(20 * u, w)),
    ("p", lambda w: Zc(82 * p, w)),
    ("s", lambda w: Zl(30 * u, w)),
    ("p", lambda w: Zc(100 * p, w)),
    ("s", lambda w: Zl(30 * u, w)),
    ("p", lambda w: Zc(82 * p, w)),
]
for Rl in [5600, 4500, 560]:
    lad("LX LPF 5.5", lx1, 1, Rl)
print("=== LX-1000 post-de-emph LPF (pin18 -> R3321 390 -> 27p / 10uH / 68p -> Q3209 base)")
lx2 = [
    ("s", lambda w: 390 + 0 * w),
    ("p", lambda w: Zc(27 * p, w)),
    ("s", lambda w: Zl(10 * u, w)),
    ("p", lambda w: Zc(68 * p, w)),
]
for Rl in [100e3, 10e3]:
    lad("LX LPF3", lx2, 1, Rl)
print(
    "=== LX Q3205 phase splitter (coll R3223 220, emit R3353 220; C3279 33p from coll, R3239 560 from emit)"
)
w = 2 * np.pi * f
for rc in [0, 220]:
    Yc = 1 / (rc + 1 / (1j * w * 33 * p))
    Ye = 1 / 560
    H = (-1 * Yc + 1 * Ye) / (Yc + Ye)
    analyse(f"LX Q3205 net (coll src R={rc})", H)
print(
    "=== De-emphasis (inverting amp, Zf = R1 || (R2 + C)); response relative 0.5 MHz is not the point: give shelf & corners"
)
for name, R1, R2, C in [
    ("S180/D406 pins21-22: R458 5.6k || (R457 3.9k + C452 33p)", 5600, 3900, 33 * p),
    ("LX-1000 pins18-19: R3319 3.9k || (R3320 2.7k + C3280 43p)", 3900, 2700, 43 * p),
]:
    tp = C * (R1 + R2)
    tz = C * R2
    Z = lambda w: par(R1, R2 + 1 / (1j * w * C))
    print(
        f"{name}: tau_pole={tp * 1e9:.1f}ns (fp={1 / (2 * np.pi * tp) / 1e6:.3f}MHz), tau_zero={tz * 1e9:.1f}ns (fz={1 / (2 * np.pi * tz) / 1e6:.3f}MHz), HF shelf={20 * np.log10(par(R1, R2) / R1):.2f}dB"
    )
    H = Z(w) / R1
    analyse("   deemph", H)
print("=== RF correction boosts (gain ratio ON/OFF), ideal CE stage gain ~ Rc/Re")
for name, Re, Rs_, Cs in [
    ("D406 Q152+Q805: Re=R807 330, shunt R810 100 + C806 68p", 330, 100, 68 * p),
    ("LX Q3202+QR3201: Re(ac)=R3205 270, shunt R3421 68 + C3271 100p", 270, 68, 100 * p),
]:
    for fx in [1, 4, 6, 7.6, 8.1, 9.3, 10, 12, 14]:
        ww = 2 * np.pi * fx * 1e6
        Ron = par(Re, Rs_ + 1 / (1j * ww * Cs))
        print(f"  {name} {fx}MHz: +{20 * np.log10(abs(Re / Ron)):.2f} dB")
    print(
        f"   zero {1 / (2 * np.pi * (Re + Rs_) * Cs) / 1e6:.2f} MHz, pole {1 / (2 * np.pi * Rs_ * Cs) / 1e6:.2f} MHz, max +{20 * np.log10(Re / par(Re, Rs_)):.1f} dB"
    )
print("=== LX RF coupling R3283 560 + C3277 75p + L3220 4.7uH into ~505 ohm")
Rl = 505
for fx in [2.3, 4, 6, 7.6, 8.1, 8.5, 9.3, 10, 12, 14, 16]:
    ww = 2 * np.pi * fx * 1e6
    Zs = 560 + 1j * ww * 4.7 * u + 1 / (1j * ww * 75 * p)
    H = Rl / (Zs + Rl)
    ww0 = 2 * np.pi * 8.1e6
    H0 = Rl / (560 + 1j * ww0 * 4.7 * u + 1 / (1j * ww0 * 75 * p) + Rl)
    print(f"  {fx} MHz {20 * np.log10(abs(H / H0)):.2f} dB rel 8.1")
print(
    "=== LX-1000 A/D anti-alias LPF (Q3701 emitter -> R3705 560 -> 33p/27uH/68p/27uH||3p/33p -> R3706 560)"
)
lx4 = [
    ("s", lambda w: 560 + 0 * w),
    ("p", lambda w: Zc(33 * p, w)),
    ("s", lambda w: Zl(27 * u, w)),
    ("p", lambda w: Zc(68 * p, w)),
    ("s", lambda w: par(Zl(27 * u, w), Zc(3 * p, w))),
    ("p", lambda w: Zc(33 * p, w)),
]
for Rl in [560, 100e3]:
    lad("LX ADC LPF", lx4, 1, Rl)
H = ladder(lx4, 1, 560, np.array([0.5e6, 7.16e6, 8e6, 10e6, 10.3e6, 14.3e6]))
print(
    "  atten rel 0.5MHz at 7.16, 8, 10, 10.3 (=14.318-4.0), 14.3 MHz:",
    [round(20 * np.log10(abs(h / H[0])), 1) for h in H[1:]],
)
print(
    "=== CLD-D406 post-DAC LPF (Q501 emitter -> R600 820 -> 15p / 27uH||7p / 47p / 27uH||22p / 39p -> Q701 base)"
)
d4 = [
    ("s", lambda w: 820 + 0 * w),
    ("p", lambda w: Zc(15 * p, w)),
    ("s", lambda w: par(Zl(27 * u, w), Zc(7 * p, w))),
    ("p", lambda w: Zc(47 * p, w)),
    ("s", lambda w: par(Zl(27 * u, w), Zc(22 * p, w))),
    ("p", lambda w: Zc(39 * p, w)),
]
for Rl in [100e3, 10e3, 820]:
    lad("D406 DAC LPF", d4, 1, Rl)
