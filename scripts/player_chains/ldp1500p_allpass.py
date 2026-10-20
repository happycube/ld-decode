#!/usr/bin/env python3
"""Sony LDP-1500P phase-splitter all-pass stages ("DELAY" and "PHASE EQUALIZER").

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

A phase splitter whose collector and emitter outputs are summed through an R
and a series LC: Q108/Q109 on the PR-80 board and Q15/Q16 on VP-18.  Ideal
transistors.  See docs/technical/player-video-chains.md.

Usage: python3 scripts/player_chains/ldp1500p_allpass.py
"""

import numpy as np

f = np.linspace(0.1e6, 10e6, 20000)
w = 2 * np.pi * f


def run(name, R, L, C, gc, ge, lc_on_collector):
    Y2 = 1 / (1j * w * L + 1 / (1j * w * C))
    G = 1 / R
    if lc_on_collector:
        H = (gc * Y2 + ge * G) / (G + Y2)
    else:
        H = (gc * G + ge * Y2) / (G + Y2)
    ph = np.unwrap(np.angle(H))
    gd = -np.gradient(ph, w)
    i0 = np.argmin(abs(f - 0.5e6))
    print("==", name, "fres=%.2f MHz" % (1 / (2 * np.pi * np.sqrt(L * C)) / 1e6))
    for fx in [1, 2, 3, 3.58, 4, 4.2, 4.5, 5, 6]:
        i = np.argmin(abs(f - fx * 1e6))
        print(
            "  %.2f MHz |H|=%.2f dB gd rel0.5=%6.1f ns"
            % (fx, 20 * np.log10(abs(H[i]) / abs(H[i0])), (gd[i] - gd[i0]) * 1e9)
        )


run(
    "LDP-1500P VP-18 'PHASE EQUALIZER' Q15/Q16 (R48 1.2k coll; L11 39uH+C50 68p emitter; C70 ignored)",
    1200,
    39e-6,
    68e-12,
    -1.0,
    1.0,
    False,
)
run(
    "LDP-1500P PR-80 'DELAY' Q108/Q109 (C135 56p+L110 27uH coll gain -1k/820; R134 1.2k emitter)",
    1200,
    27e-6,
    56e-12,
    -1000 / 820,
    1.0,
    True,
)
