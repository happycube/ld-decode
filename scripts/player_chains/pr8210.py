#!/usr/bin/env python3
"""PR-8210-A / LD-1100 (VSOP VWS-022) video-path filter simulations.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Component values read from the PR-8210-A service manual (VRT-019-0) schematic
pp.87-88 and cross-checked against the VWS-022 parts lists (PR-8210-A
pp.89-90, LD-1100 Supplement 1 pp.33-34).  Ladder simulations are
ABCD-cascade solutions; the dropout-path low-pass is a nodal solution.
Transistor re/Rsat, FET gm, coil Q and the pulse-count pulse width are
assumptions.  See docs/technical/player-video-chains.md.

Usage: python3 scripts/player_chains/pr8210.py
"""

import numpy as np

p = 1e-12
u = 1e-6
n = 1e-9


def zl(L):
    return lambda w: 1j * w * L


def zc(C):
    return lambda w: 1 / (1j * w * C)


def zsum(*fs):
    return lambda w: sum(f(w) for f in fs)


def zpar(*fs):
    return lambda w: 1 / sum(1 / f(w) for f in fs)


def zr(R):
    return lambda w: R + 0 * w


def ladder(elems, rs, rl, f):
    """elems: list of ('s'|'p', zfunc) from source to load. Returns Vload/Vsource."""
    w = 2 * np.pi * np.asarray(f, dtype=float)
    out = np.empty(len(w), dtype=complex)
    for i, wi in enumerate(w):
        a = np.array([[1, rs], [0, 1]], dtype=complex)
        for kind, z in elems:
            zz = z(wi)
            m = np.array([[1, zz], [0, 1]]) if kind == "s" else np.array([[1, 0], [1 / zz, 1]])
            a = a @ m
        out[i] = 1 / (a[0, 0] + a[0, 1] / rl)
    return out


FG = np.linspace(0.02e6, 40e6, 80000)


def gd_of(h, f):
    ph = np.unwrap(np.angle(h))
    return -np.gradient(ph, 2 * np.pi * f)


def table(name, h, f, pts, ref_f, note=""):
    mag = 20 * np.log10(np.abs(h))
    gd = gd_of(h, f)
    iref = np.argmin(abs(f - ref_f))
    print(f"\n== {name} {note}")
    print(f"   (dB relative to {ref_f / 1e6:.2f} MHz; GD absolute and relative to ref)")
    for fx in pts:
        i = np.argmin(abs(f - fx * 1e6))
        print(
            f"   {fx:6.2f} MHz  {mag[i] - mag[iref]:8.2f} dB   gd {gd[i] * 1e9:7.1f} ns  (rel {1e9 * (gd[i] - gd[iref]):7.1f} ns)"
        )
    return mag - mag[iref], gd


def m3db(f, magrel, start_f):
    i0 = np.argmin(abs(f - start_f))
    idx = np.where(magrel[i0:] < -3)[0]
    return f[i0 + idx[0]] / 1e6 if len(idx) else None


def notches(f, magrel, below=-20):
    out = []
    for i in range(1, len(f) - 1):
        if magrel[i] < magrel[i - 1] and magrel[i] < magrel[i + 1] and magrel[i] < below:
            out.append((round(f[i] / 1e6, 2), round(magrel[i], 1)))
    return out


VPTS = [0.5, 1, 2, 3, 3.58, 4.0, 4.2, 4.5, 5.0, 6, 8.1, 9.3, 16.2, 18.6]
RPTS = [2.3, 2.8, 3.5, 3.9, 4.0, 4.5, 5, 6, 7, 7.6, 8.1, 9.3, 10, 11.7, 12.3, 13, 14, 15, 18]

# ---------------------------------------------------------------- RF chain
print("#" * 70, "\n# RF domain (relative to 8.1 MHz)")


# (1) Q201 RF correction: CE stage, Rc = R204 470, emitter R205 100 // (C205 270p + Q203 sat) when RF CORR on.
def q201(f, on, re=5.0, rsat=5.0, cpar=8 * p):
    w = 2 * np.pi * f
    ze = 100.0 + 0j * w
    if on:
        zb = rsat + 1 / (1j * w * 270 * p)
        ze = 100 * zb / (100 + zb)
    zc_load = 470 / (1 + 1j * w * 470 * cpar)
    return zc_load / (ze + re)


for on in (False, True):
    h = q201(FG, on)
    table(
        f"Q201 RF-correction stage, RF CORR {'ON (inner zone)' if on else 'OFF'}",
        h,
        FG,
        RPTS,
        8.1e6,
        "[my calc; re=5ohm, Q203 Rsat=5ohm, 8pF collector parasitic assumed]",
    )
h_on, h_off = q201(FG, True), q201(FG, False)
table("Q201 boost ON/OFF ratio", h_on / h_off, FG, [1, 2, 4, 6, 8.1, 10, 12, 14], 1e6, "[my calc]")

# (2) RF band-pass: R208 1k -> C209 56p(s) -> L201 27u(p) -> C210 56p(s) -> C211 8p(p) -> L202 18u(s)
#     -> C212 22p(p) -> L203 18u(s) -> C213 8p(p) -> R210 1.1k (+ 2SK19 gate ~5 pF)
bpf = [
    ("s", zc(56 * p)),
    ("p", zl(27 * u)),
    ("s", zc(56 * p)),
    ("p", zc(8 * p)),
    ("s", zl(18 * u)),
    ("p", zc(22 * p)),
    ("s", zl(18 * u)),
    ("p", zc((8 + 5) * p)),
]
h_bpf = ladder(bpf, 1000, 1100, FG)
mb, gb = table("RF BPF (R208 1k source, R210 1.1k load)", h_bpf, FG, RPTS, 8.1e6, "[my calc]")
pk = FG[np.argmax(mb)]
print(
    f"   peak at {pk / 1e6:.2f} MHz ({mb.max():.2f} dB rel 8.1); -3dB edges:",
    [round(FG[i] / 1e6, 2) for i in range(1, len(FG)) if (mb[i] + 3) * (mb[i - 1] + 3) < 0],
)


# (3) Q204 2SK19 source-degeneration audio traps: Zs = R212 330 + (L204 18u // C215 180p) + (L205 18u // C216 270p)
def trap(f, gm=6e-3, q=40.0, f0q=2.5e6):
    w = 2 * np.pi * f
    rL = 2 * np.pi * f0q * 18 * u / q  # coil series loss

    def tank(c):
        zlw = rL + 1j * w * 18 * u
        zcw = 1 / (1j * w * c)
        return zlw * zcw / (zlw + zcw)

    zs = 330 + tank(180 * p) + tank(270 * p)
    rd = 1000 / (1 + 1j * w * 1000 * 6 * p)  # R211 1k // ~6 pF (Cgd + Q205 input)
    return gm * rd / (1 + gm * zs)


for gm in (4e-3, 8e-3):
    h = trap(FG, gm)
    mt, gt = table(
        f"Q204 audio-trap stage gm={gm * 1e3:.0f} mS", h, FG, RPTS, 8.1e6, "[my calc; coil Q=40]"
    )
    print("   notches:", notches(FG[FG < 6e6], mt[FG < 6e6], -10))

h_rf = q201(FG, False) * h_bpf * trap(FG, 6e-3)
h_rf_on = q201(FG, True) * h_bpf * trap(FG, 6e-3)
mr, gr = table(
    "TOTAL RF (RF CORR off): Q201 x BPF x trap(gm 6mS)", h_rf, FG, RPTS, 8.1e6, "[my calc]"
)
mr2, gr2 = table("TOTAL RF (RF CORR on)", h_rf_on, FG, RPTS, 8.1e6, "[my calc]")

print(
    "\n   Sideband symmetry (upper/lower, dB; GD difference ns) around carrier fc for f_v=3.58, 4.2 MHz"
)
for lab, H in (("off", h_rf), ("on", h_rf_on)):
    m = 20 * np.log10(np.abs(H))
    g = gd_of(H, FG)
    for fc in (7.6, 8.1, 9.3):
        for fv in (3.58, 4.2):
            iu = np.argmin(abs(FG - (fc + fv) * 1e6))
            il = np.argmin(abs(FG - (fc - fv) * 1e6))
            ic = np.argmin(abs(FG - fc * 1e6))
            print(
                f"   RFCORR {lab:3s} fc {fc:4.1f}: fv {fv:4.2f}  L {m[il] - m[ic]:6.2f} dB  U {m[iu] - m[ic]:6.2f} dB"
                f"  U-L {m[iu] - m[il]:6.2f} dB   gdU-gdL {1e9 * (g[iu] - g[il]):7.1f} ns"
            )


# (4) 1H-delayed-RF equaliser (DOC path): Q207 emitter R220 200 // (R282 33 + C286 1000p), re ~5
def q207(f, re=5.0):
    w = 2 * np.pi * f
    zb = 33 + 1 / (1j * w * 1000 * p)
    ze = 200 * zb / (200 + zb)
    return 1 / (ze + re)


table(
    "DOC 1H-delayed-RF emitter EQ (Q207: R220 200 // R282 33+C286 1n)",
    q207(FG),
    FG,
    [0.5, 1, 2, 4, 6, 8.1, 10, 12],
    8.1e6,
    "[my calc; re=5ohm]",
)

# ---------------------------------------------------------------- Video chain
print("\n" + "#" * 70, "\n# Video domain (relative to 0.5 MHz)")

# (5) pulse-count rectangular-pulse response sinc(f tau) (inside UA5001)
for tau in (25e-9, 40e-9):
    hs = np.sinc(FG * tau) * np.exp(-1j * np.pi * FG * tau)
    table(
        f"Pulse-count pulse shape, tau={tau * 1e9:.0f} ns",
        hs,
        FG,
        VPTS[:9],
        0.5e6,
        "[my calc; tau assumed, not printed]",
    )


# (6) Post-demod LPF ('F1 4.2 MHz'): pin29 R228 1.1k (Norton) -> C233 8p(p) -> L206 39u//C231 8p (s)
#     -> C234 33p(p) -> L207 43u//C232 15p (s) -> C235 33p(p) -> R229 100 -> Q209 base
def f1_elems(cload=5 * p):
    return [
        ("p", zc(8 * p)),
        ("s", zpar(zl(39 * u), zc(8 * p))),
        ("p", zc(33 * p)),
        ("s", zpar(zl(43 * u), zc(15 * p))),
        ("p", zc(33 * p)),
        ("s", zr(100)),
        ("p", zc(cload)),
    ]


res = {}
for rl, lab in ((200e3, "Q209 input ~200k//5pF"), (1100, "hypothetical 1.1k termination")):
    h = ladder(f1_elems(), 1100, rl, FG)
    mf, gf = table(f"F1 post-demod LPF, Rs=1.1k, load {lab}", h, FG, VPTS, 0.5e6, "[my calc]")
    print(f"   -3 dB at {m3db(FG, mf, 0.5e6)} MHz; notches: {notches(FG, mf, -25)}")
    res[lab] = h
h_f1 = res["Q209 input ~200k//5pF"]

# (7) 220 ns lumped delay (F2): R233 270 -> C241 51p(p) -> L208 12u -> C242 160p -> L209 16u -> C243 200p
#     -> L210 18u -> C244 200p -> L211 18u -> C245 150p -> R234 1.5k (Q210 base)
dl = [
    ("p", zc(51 * p)),
    ("s", zl(12 * u)),
    ("p", zc(160 * p)),
    ("s", zl(16 * u)),
    ("p", zc(200 * p)),
    ("s", zl(18 * u)),
    ("p", zc(200 * p)),
    ("s", zl(18 * u)),
    ("p", zc(150 * p)),
]
for rl in (1500, 280):
    h = ladder(dl, 270, rl, FG)
    md, gd = table(f"220 ns LC delay (F2), Rs=270, RL={rl}", h, FG, VPTS[:11], 0.5e6, "[my calc]")
    print(f"   -3 dB at {m3db(FG, md, 0.5e6)} MHz")
    if rl == 1500:
        h_dl = h


# (8) De-emphasis: pin10 -> R240 1.1k -> node(Q213 base) ; node -> R241 680 -> C251 180p -> gnd
def deemph(f, rsrc=0.0, rload=1e6):
    w = 2 * np.pi * f
    zsh = 680 + 1 / (1j * w * 180 * p)
    zsh = zsh * rload / (zsh + rload)
    return zsh / (zsh + 1100 + rsrc)


for rsrc in (0.0, 50.0):
    h = deemph(FG, rsrc)
    table(
        f"De-emphasis R240 1.1k / R241 680 + C251 180p, Rsrc={rsrc:.0f}",
        h,
        FG,
        VPTS[:9],
        0.5e6,
        "[my calc]",
    )
# ld-decode reference 120/320 ns
w = 2 * np.pi * FG
h_ld = (1 + 1j * w * 120e-9) / (1 + 1j * w * 320e-9)
table("ld-decode video_deemp 120/320 ns (reference)", h_ld, FG, VPTS[:9], 0.5e6, "[my calc]")
h_de = deemph(FG, 0.0)
print("   PR-8210-A deemph minus ld-decode deemph (dB / ns):")
for fx in VPTS[:9]:
    i = np.argmin(abs(FG - fx * 1e6))
    print(
        f"     {fx:5.2f} MHz  {20 * np.log10(abs(h_de[i]) / abs(h_ld[i])):6.3f} dB  "
        f"{1e9 * (gd_of(h_de, FG)[i] - gd_of(h_ld, FG)[i]):6.2f} ns"
    )


# (9) DOC (1H-delayed video) LPF: pin12 Norton into R260 1.2k // C283 15p; R261 1.2k; C267 120p feedback
#     to Q217 emitter (unity follower); C268 62p base-gnd.   Nodal solution.
def doc_lpf(f, a=0.98):
    out = []
    for wi in 2 * np.pi * f:
        g1, g2 = 1 / 1200, 1 / 1200
        y283, y267, y268 = 1j * wi * 15 * p, 1j * wi * 120 * p, 1j * wi * 62 * p
        # unknowns v1 (node B), v2 (base). vout = a*v2. Current source I=1 injected at node B.
        # node B: (v1)(g1 + y283) + (v1 - v2) g2 + (v1 - a v2) y267 = I
        # base : (v2 - v1) g2 + v2 y268 = 0
        A = np.array([[g1 + y283 + g2 + y267, -g2 - a * y267], [-g2, g2 + y268]], dtype=complex)
        v = np.linalg.solve(A, np.array([1, 0], dtype=complex))
        out.append(a * v[1])
    return np.array(out)


h_doc = doc_lpf(FG)
md, gdd = table(
    "DOC-path LPF (UA5002 pin12 -> Q217 Sallen-Key)", h_doc, FG, VPTS, 0.5e6, "[my calc]"
)
print(f"   -3 dB at {m3db(FG, md, 0.5e6)} MHz")

# ---------------------------------------------------------------- totals
print(
    "\n" + "#" * 70, "\n# Main video path total: pulse sinc(tau=30ns) x F1 x F2 delay x de-emphasis"
)
hs = np.sinc(FG * 30e-9) * np.exp(-1j * np.pi * FG * 30e-9)
for lab, H in (
    ("without de-emphasis", hs * h_f1 * h_dl),
    ("with de-emphasis", hs * h_f1 * h_dl * h_de),
    (
        "with de-emph, divided by ideal 120/320 de-emph (= what ld-decode's LPF/GD stage must model)",
        hs * h_f1 * h_dl * h_de / h_ld,
    ),
):
    mt, gt = table(f"TOTAL {lab}", H, FG, VPTS[:9], 0.5e6, "[my calc]")
    print(f"   -3 dB at {m3db(FG, mt, 0.5e6)} MHz")

# ld-decode video LPF reference: 6th-order Butterworth 4.5 MHz (analog proto for comparison)
from scipy import signal

b, a = signal.butter(6, 2 * np.pi * 4.5e6, analog=True)
_, hb = signal.freqs(b, a, worN=2 * np.pi * FG)
table(
    "ld-decode reference: 6th-order Butterworth 4.5 MHz (analog prototype)",
    hb,
    FG,
    VPTS[:9],
    0.5e6,
    "[my calc]",
)
