#!/usr/bin/env python3
"""PR-7820 video-path filter simulations (component values read from the schematics).

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Every stage from the HEDA RF equaliser to the VTBC output filters, from the
values on the 1979 DiscoVision service manual's schematics (HEDA p.132, VDEM
p.171, VTBC-A pp.183-184) and the 1981 Supplement 2's new boards.  Ladder
networks are solved with ABCD matrices; the two transistor feedback pairs by
small-signal nodal analysis (hybrid-pi: gm, r_pi, C_pi, C_mu).  Coil Q,
transistor parameters and the detector pulse width are assumptions.
Findings are written up in docs/technical/player-video-chains.md.

Usage: python3 scripts/player_chains/pr7820.py
"""

import numpy as np

p = 1e-12
n = 1e-9
u = 1e-6
k = 1e3
M = 1e6
VF = [0.5, 1, 2, 3, 3.58, 4.0, 4.2, 4.5, 5.0]  # video-domain report points (MHz)
RF = [3.9, 4.52, 6.0, 7.6, 8.1, 9.3, 10.0, 11.68, 12.3, 13.5, 15.0]  # RF points


def Zl(L, w, Q=None, f0=8e6):
    r = 0 if Q is None else 2 * np.pi * f0 * L / Q
    return r + 1j * w * L


def Zc(C, w):
    return 1 / (1j * w * C)


def par(a, b):
    return a * b / (a + b)


def ladder(elems, Rs, Rl, f):
    """elems: list of ('s'|'p', Zfunc(w)). Returns V(load)/Vsource (complex)."""
    f = np.atleast_1d(np.asarray(f, float))
    out = np.empty(len(f), complex)
    for i, wi in enumerate(2 * np.pi * f):
        A = np.array([[1, Rs], [0, 1]], dtype=complex)
        for kind, z in elems:
            Z = z(wi)
            A = A @ (np.array([[1, Z], [0, 1]]) if kind == "s" else np.array([[1, 0], [1 / Z, 1]]))
        out[i] = 1 / (A[0, 0] + A[0, 1] / Rl)
    return out


def gd(Hfun, fMHz, df=1e3):
    f = fMHz * M
    h1, h2 = Hfun(np.array([f - df])), Hfun(np.array([f + df]))
    return -(np.angle(h2[0] / h1[0])) / (2 * np.pi * 2 * df)


def table(name, Hfun, pts, ref=None):
    """Print magnitude (dB rel. ref MHz, or absolute if ref None) and group delay (ns)."""
    H = Hfun(np.array(pts) * M)
    H0 = Hfun(np.array([ref * M]))[0] if ref else 1.0
    print(f"--- {name}" + (f"  (dB rel {ref} MHz)" if ref else "  (dB absolute)"))
    for x, h in zip(pts, H):
        print(
            f"   {x:6.2f} MHz  {20 * np.log10(abs(h / H0)):7.2f} dB   GD {gd(Hfun, x) * 1e9:7.1f} ns"
        )


def m3db(Hfun, ref=0.5, lo=0.6, hi=20):
    f = np.arange(lo, hi, 0.005) * M
    H = Hfun(f)
    H0 = Hfun(np.array([ref * M]))[0]
    mag = 20 * np.log10(abs(H / H0))
    i = np.where(mag < -3)[0]
    return f[i[0]] / M if len(i) else None


# ---------------------------------------------------------------- HEDA Q5 equaliser
def heda_eq(f, re=5.0):
    w = 2 * np.pi * f
    Ze = par(330 + par(2.7 * k, Zc(0.047 * u, w)), 47 + Zc(47 * p, w))
    return 560 / (re + Ze)


# ---------------------------------------------------------------- VDEM RF band-pass (filter 2)
def vdem_bpf(f, Q=60, cgs=4 * p, Rl=par(6.8 * k, 1.2 * k)):
    el = [
        ("s", lambda w: Zc(56 * p, w)),
        ("p", lambda w: Zl(27 * u, w, Q)),
        ("s", lambda w: Zc(56 * p, w)),
        ("p", lambda w: Zc(8 * p, w)),
        ("s", lambda w: Zl(18 * u, w, Q)),
        ("p", lambda w: Zc(22 * p, w)),
        ("s", lambda w: Zl(18 * u, w, Q)),
        ("p", lambda w: Zc(8 * p + cgs, w)),
    ]
    return ladder(el, 1000 + 5, Rl, f)


# ---------------------------------------------------------------- Q3 source traps (2.8 / 2.3 MHz)
def vdem_traps(f, rgm=150.0, Q=40):
    w = 2 * np.pi * f
    Z5 = par(Zl(18 * u, w, Q, 2.8e6), Zc(180 * p, w))
    Z6 = par(Zl(18 * u, w, Q, 2.3e6), Zc(270 * p, w))
    return 230 / (rgm + 100 + Z5 + Z6)


def rf_pre_limiter(f, **kw):
    return heda_eq(f) * vdem_bpf(f) * vdem_traps(f, **kw)


def fm_equiv(Hrf, fc):
    """Small-signal FM->video transfer of an RF filter followed by an ideal limiter/demod:
    G(fm) = [H(fc+fm)/H(fc) + conj(H(fc-fm)/H(fc))]/2"""

    def G(fm):
        H0 = Hrf(np.array([fc]))[0]
        return 0.5 * (Hrf(fc + fm) / H0 + np.conj(Hrf(fc - fm) / H0))

    return G


# ---------------------------------------------------------------- pulse-count detector aperture
def detector(f, tau=45 * n):
    return np.sinc(f * tau) * np.exp(-1j * np.pi * f * tau)


# ---------------------------------------------------------------- post-detector elliptic LPF
def vdem_lpf1(f, Rs=1300 + 60, Rl=100 * k):
    el = [
        ("p", lambda w: Zc(8 * p, w)),
        ("s", lambda w: par(Zl(39 * u, w, 60, 5e6), Zc(8 * p, w))),
        ("p", lambda w: Zc(33 * p, w)),
        ("s", lambda w: par(Zl(43 * u, w, 60, 5e6), Zc(15 * p, w))),
        ("p", lambda w: Zc(33 * p + 3 * p, w)),
    ]
    return ladder(el, Rs, Rl, f)


# ---------------------------------------------------------------- transistor nodal solver
def bjt_stamp(Y, b, c, e, gm, beta, w, fT=150e6, cmu=2 * p):
    rpi = beta / gm
    cpi = gm / (2 * np.pi * fT) - cmu
    ypi = 1 / rpi + 1j * w * cpi
    ymu = 1j * w * cmu

    def add(i, j, y):
        if i is not None:
            Y[i, i] += y
        if j is not None:
            Y[j, j] += y
        if i is not None and j is not None:
            Y[i, j] -= y
            Y[j, i] -= y

    add(b, e, ypi)
    add(b, c, ymu)
    # VCCS gm*(vb-ve) from c to e
    for row, s in ((c, 1), (e, -1)):
        if row is None:
            continue
        if b is not None:
            Y[row, b] += s * gm
        if e is not None:
            Y[row, e] -= s * gm


def q9q10(f, c58=470 * p, Ie=12e-3, beta=200, fT=150e6, r64=24 * k):
    """Q9 (CE, Re=R58 150) -> Q10 (CE, Re=R63 150 || C58 470p) with R64 feedback
    from Q10 collector to Q9 emitter. Input: ideal source at Q9 base. Output: Q10 collector."""
    gm = Ie / 0.02585
    out = []
    for wi in 2 * np.pi * np.atleast_1d(f):
        # nodes: 0 b9, 1 e9, 2 c9/b10, 3 e10, 4 c10
        Y = np.zeros((5, 5), complex)

        def g(i, j, y):
            Y[i, i] += y
            if j is not None:
                Y[j, j] += y
                Y[i, j] -= y
                Y[j, i] -= y

        g(1, None, 1 / 150)  # R58
        g(2, None, 1 / 1000 + 1 / 12.5e3)  # R57 (to AC gnd) || R60||R61
        g(3, None, 1 / 150 + 1j * wi * c58)  # R63 || C58
        g(4, None, 1 / 1000 + 1j * wi * 5 * p)  # R62 + Q11 base/strays
        g(4, 1, 1 / r64)  # R64 (C59 = short)
        bjt_stamp(Y, 0, 2, 1, gm, beta, wi, fT)
        bjt_stamp(Y, 2, 4, 3, gm, beta, wi, fT)
        # force v0 = 1: move column 0 to RHS
        A = Y[1:, 1:]
        rhs = -Y[1:, 0]
        v = np.linalg.solve(A, rhs)
        out.append(v[3])
    return np.array(out)


def q7q8(f, Ie=8e-3, beta=200, fT=150e6):
    """Q7 (CE, Re=R49 150, Rc=R48 1k) -> Q8 (CE, Re=R54 150, Rc=VR3 1k) with R53 2.4k
    feedback from Q8 collector to Q7 emitter."""
    gm = Ie / 0.02585
    out = []
    for wi in 2 * np.pi * np.atleast_1d(f):
        Y = np.zeros((5, 5), complex)

        def g(i, j, y):
            Y[i, i] += y
            if j is not None:
                Y[j, j] += y
                Y[i, j] -= y
                Y[j, i] -= y

        g(1, None, 1 / 150)
        g(2, None, 1 / 1000 + 1 / 12.5e3)
        g(3, None, 1 / 150)
        g(4, None, 1 / 1000 + 1j * wi * 5 * p)
        g(4, 1, 1 / 2400)
        bjt_stamp(Y, 0, 2, 1, gm, beta, wi, fT)
        bjt_stamp(Y, 2, 4, 3, gm, beta, wi, fT)
        A = Y[1:, 1:]
        rhs = -Y[1:, 0]
        out.append(np.linalg.solve(A, rhs)[3])
    return np.array(out)


# ---------------------------------------------------------------- de-emphasis (R66/R67/C60)
def deemph(f, Rsrc=7.0, Rl=50 * k):
    w = 2 * np.pi * f
    sh = par(220 + Zc(560 * p, w), Rl)
    return sh / (Rsrc + 330 + sh)


def deemph_ldd(f):
    w = 2 * np.pi * f
    return (1 + 1j * w * 120 * n) / (1 + 1j * w * 320 * n)


# ---------------------------------------------------------------- second LPF (R69, L14, L15)
def vdem_lpf2(f, Rs=300 + 5, Rl=par(par(1.8 * k, 3 * k), 150 * k)):
    el = [
        ("p", lambda w: Zc(33 * p, w)),
        ("s", lambda w: Zl(8.2 * u, w, 60, 5e6)),
        ("p", lambda w: Zc(150 * p, w)),
        ("s", lambda w: Zl(15 * u, w, 60, 5e6)),
        ("p", lambda w: Zc(160 * p + 3 * p, w)),
    ]
    return ladder(el, Rs, Rl, f)


def vdem_video(f, tau=45 * n):
    return detector(f, tau) * vdem_lpf1(f) * q7q8(f) * q9q10(f) * deemph(f) * vdem_lpf2(f)


# ---------------------------------------------------------------- VTBC (original VWW-003)
def vtbc_boost_old(f, Rl=100 * k):
    w = 2 * np.pi * f
    sh = par(330, Rl)
    return sh / (sh + 470 + par(510, Zc(150 * p, w)))


def vtbc_boost_new(f, Rl=par(1 * k, 1 * k) * 0 + 500):
    # VWW-005: R3 120 + (R4 510 || C2 150p) series, R5 330 shunt; Q2 base; Q2 drives R201/R202 1k
    w = 2 * np.pi * f
    sh = 330
    return sh / (sh + 120 + par(510, Zc(150 * p, w)))


def ccd_aperture(f, fclk=10e6, hold=0.5):
    T = hold / fclk
    return np.sinc(f * T) * np.exp(-1j * np.pi * f * T)


def vtbc_filter_old(f, Rs=900, Rl=1000):
    el = [
        ("s", lambda w: Zl(27 * u, w, 60, 5e6)),
        ("p", lambda w: Zc(43 * p, w)),
        ("s", lambda w: par(Zl(33 * u, w, 60, 5e6), Zc(15 * p, w))),
        ("p", lambda w: Zc(47 * p, w)),
        ("s", lambda w: par(Zl(36 * u, w, 60, 5e6), Zc(7 * p, w))),
        ("p", lambda w: Zc(24 * p, w)),
    ]
    return ladder(el, Rs, Rl, f)


def vtbc_filter_new(f, Rs=900, Rl=1000):
    el = [
        ("s", lambda w: Zl(3.9 * u, w, 60, 5e6)),
        ("p", lambda w: Zc(33 * p, w)),  # CT2 feed-through
        ("s", lambda w: 1.0 + 0 * w),  # R157
        ("p", lambda w: 6.8 * k + 0 * w),  # R155 (assumed to AC ground)
        ("s", lambda w: Zl(27 * u, w, 60, 5e6)),
        ("p", lambda w: Zc(43 * p, w)),
        ("s", lambda w: par(Zl(36 * u, w, 60, 5e6), Zc(7 * p, w))),
        ("p", lambda w: Zc(47 * p, w)),
        ("s", lambda w: par(Zl(36 * u, w, 60, 5e6), Zc(15 * p, w))),
        ("p", lambda w: Zc(24 * p, w)),
    ]
    return ladder(el, Rs, Rl, f)


def vtbc_8m_old(f, Rs=1000 + 10, Rl=1500):
    el = [
        ("p", lambda w: Zc(22 * p, w)),
        ("s", lambda w: par(Zl(22 * u, w, 60, 5e6), Zc(3 * p, w))),
        ("p", lambda w: Zc(22 * p, w)),
    ]
    return ladder(el, Rs, Rl, f)


def vtbc_old(f, **kw):
    return vtbc_boost_old(f) * ccd_aperture(f, **kw) * vtbc_filter_old(f) * vtbc_8m_old(f)


def vtbc_new(f, **kw):
    return vtbc_boost_new(f) * ccd_aperture(f, **kw) * vtbc_filter_new(f)


def ldd_lpf(f):
    from scipy.signal import butter, freqs

    b, a = butter(6, 2 * np.pi * 4.5e6, analog=True)
    return freqs(b, a, 2 * np.pi * f)[1]


if __name__ == "__main__":
    np.set_printoptions(precision=2)
    print("=========== RF (pre-limiter) ===========")
    table("HEDA Q5 equaliser (re=5)", heda_eq, RF, ref=8.1)
    print(
        "   EQ zero/pole [my calc]: fz=1/(2pi*377*47p)=%.2f MHz, fp=1/(2pi*(47+re)*47p)=%.1f MHz"
        % (1 / (2 * np.pi * 377 * 47 * p) / M, 1 / (2 * np.pi * 52 * 47 * p) / M)
    )
    table("VDEM RF band-pass (R11 1k src, 1.02k load, Cgs 4p, Q=60)", vdem_bpf, RF, ref=8.1)
    print("   BPF -3 dB points:", end=" ")
    ff = np.arange(1, 25, 0.01) * M
    Hb = abs(vdem_bpf(ff))
    Hb /= abs(vdem_bpf(np.array([8.1e6]))[0])
    idx = np.where(20 * np.log10(Hb) > -3)[0]
    print(f"{ff[idx[0]] / M:.2f} .. {ff[idx[-1]] / M:.2f} MHz (rel 8.1 MHz)")
    for rgm in (100, 150, 300):
        table(
            f"Q3 source-trap stage (1/gm={rgm})",
            lambda f: vdem_traps(f, rgm=rgm),
            [2.3, 2.8] + RF,
            ref=8.1,
        )
    table("RF total pre-limiter (EQ*BPF*traps, 1/gm=150)", rf_pre_limiter, [2.3, 2.8] + RF, ref=8.1)
    for fc in (7.6e6, 8.1e6, 9.3e6):
        for nm, Hrf in (
            ("BPF only", vdem_bpf),
            ("BPF*traps", lambda f: vdem_bpf(f) * vdem_traps(f)),
            ("EQ*BPF*traps", rf_pre_limiter),
        ):
            table(
                f"FM-equivalent video response of RF chain [{nm}] at fc={fc / M} MHz",
                fm_equiv(Hrf, fc),
                VF,
                ref=0.5,
            )
    print("=========== video domain ===========")
    for tau in (35 * n, 45 * n, 50 * n):
        table(f"pulse-count aperture sinc, tau={tau / n:.0f} ns", lambda f: detector(f, tau), VF)
    table(
        "post-detector elliptic LPF (L10/L11)",
        vdem_lpf1,
        VF + [6.26, 7, 8, 9.0, 10, 16.2, 18.6],
        ref=0.5,
    )
    print("   -3 dB:", m3db(vdem_lpf1))
    print(
        "   trap freqs [my calc]: L10||C41 %.2f MHz, L11||C43 %.2f MHz"
        % (
            1 / (2 * np.pi * np.sqrt(39 * u * 8 * p)) / M,
            1 / (2 * np.pi * np.sqrt(43 * u * 15 * p)) / M,
        )
    )
    for Rl in (100 * k, 20 * k):
        table(f"   LPF1 with Rl={Rl / k:.0f}k", lambda f: vdem_lpf1(f, Rl=Rl), [3.58, 4.2], ref=0.5)
    table("Q7/Q8 feedback pair (fT 150 MHz)", q7q8, VF, ref=0.5)
    print("   midband gain", abs(q7q8(np.array([1e6]))[0]))
    table("Q9/Q10 feedback pair with C58 470p", q9q10, VF, ref=0.5)
    table("Q9/Q10 pair with C58 removed", lambda f: q9q10(f, c58=1e-15), VF, ref=0.5)
    print(
        "   midband gain",
        abs(q9q10(np.array([1e6]))[0]),
        "without C58",
        abs(q9q10(np.array([1e6]), c58=1e-15)[0]),
    )
    table("De-emphasis R66 330 / R67 220 + C60 560p", deemph, VF, ref=0.5)
    table("ld-decode 120/320 ns de-emphasis", deemph_ldd, VF, ref=0.5)
    table("second LPF (R69/L14/L15)", vdem_lpf2, VF + [6, 7, 8, 10], ref=0.5)
    print("   -3 dB:", m3db(vdem_lpf2))
    table("VDEM video chain total (tau 45 ns)", vdem_video, VF, ref=0.5)
    print("   -3 dB:", m3db(vdem_video))
    table("VTBC (old) high boost", vtbc_boost_old, VF, ref=0.5)
    table("VTBC (new VWW-005) high boost", vtbc_boost_new, VF, ref=0.5)
    for hold in (0.5, 1.0):
        table(f"CCD aperture fclk 10 MHz hold {hold}T", lambda f: ccd_aperture(f, hold=hold), VF)
    table("VTBC (old) video filter L8-L10", vtbc_filter_old, VF + [7.16, 10], ref=0.5)
    print("   -3 dB:", m3db(vtbc_filter_old))
    table("VTBC (new) video filter L201,L2-L4", vtbc_filter_new, VF + [6.85, 10], ref=0.5)
    print("   -3 dB:", m3db(vtbc_filter_new))
    table("VTBC (old) 8 MHz LPF L11", vtbc_8m_old, VF + [8, 19.6], ref=0.5)
    table("VTBC old total (hold T/2)", vtbc_old, VF, ref=0.5)
    table("VTBC new total (hold T/2)", vtbc_new, VF, ref=0.5)
    for nm, vt in (("old VTBC", vtbc_old), ("new VTBC", vtbc_new)):
        tot = lambda f, vt=vt: vdem_video(f) * vt(f) * fm_equiv(rf_pre_limiter, 8.1e6)(f)
        table(f"WHOLE CHAIN RF(8.1)*VDEM*{nm}", tot, VF, ref=0.5)
        print("   -3 dB:", m3db(tot))
        tot2 = lambda f, vt=vt: vdem_video(f) * vt(f)
        table(f"video-domain only VDEM*{nm}", tot2, VF, ref=0.5)
        print("   -3 dB:", m3db(tot2))
    table("ld-decode 6th-order Butterworth 4.5 MHz", ldd_lpf, VF, ref=0.5)
