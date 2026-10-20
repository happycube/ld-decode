#!/usr/bin/env python3
"""Split ld-decode's NTSC video response at multiburst frequencies into its factors.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

FM-modulates pre-emphasised tones (on a 50 IRE pedestal, 25 IRE peak) onto
the 8.1 MHz carrier, passes them through a model disc readout
(dsp.readout_otf at the cutoff an MTF level names), and demodulates them with
RFDecode.demodblock.  Prints the video low-pass and inverse-MTF boost on
their own, then the chain with no disc, with the low-pass removed, with the
disc uncompensated, compensated, and with the boost.  Columns are dB absolute
/ dB relative to 0.5 MHz.  See docs/technical/player-video-chains.md.

Usage: python3 scripts/player_chains/ldd_chain.py [MTF_LEVEL [INVERSE_MTF_STRENGTH]]
(defaults 0.816 and 0.741, the GGV colour-bar capture's settled values).
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from lddecode.core import RFDecode  # noqa: E402
from lddecode.dsp import readout_otf  # noqa: E402

LEVEL = float(sys.argv[1]) if len(sys.argv) > 1 else 0.816
STRENGTH = float(sys.argv[2]) if len(sys.argv) > 2 else 0.741
FREQS = [0.5e6, 1.0e6, 2.0e6, 3.0e6, 3.58e6, 4.1e6, 4.2e6, 4.5e6, 5.0e6]


def make():
    return RFDecode(system="NTSC", has_analog_audio=False, decode_digital_audio=False)


rf = make()
fs, n = rf.freq_hz, rf.blocklen
DP = rf.DecoderParams
t = np.arange(n) / fs
bins = np.fft.fftfreq(n, 1 / fs)
emp = 1.0 / rf.Filters["Fdeemp"]


def rf_signal(f, amp_ire, disc):
    fb = round(f * n / fs) * fs / n  # on a bin: circular filtering
    video = 50.0 + amp_ire * np.cos(2 * np.pi * fb * t)
    video = np.fft.ifft(np.fft.fft(video) * emp).real  # pre-emphasis
    inst = DP["ire0"] + DP["hz_ire"] * video
    sig = np.cos(2 * np.pi * np.cumsum(inst) / fs)
    if disc:
        cutoff = DP["readout_ref_cutoff_hz"] / rf.scaled_mtf_level(LEVEL)
        h = readout_otf(np.abs(bins), cutoff) / readout_otf(DP["readout_ref_hz"], cutoff)
        sig = np.fft.ifft(np.fft.fft(sig) * h).real
    return fb, 8192 + 4000 * sig


def tone(x, fb):
    m = len(x)
    core = slice(m // 6, m - m // 6)
    tt = np.arange(m)[core] / fs
    A = np.stack([np.cos(2 * np.pi * fb * tt), np.sin(2 * np.pi * fb * tt), np.ones_like(tt)], 1)
    c = np.linalg.lstsq(A, x[core], rcond=None)[0]
    return np.hypot(c[0], c[1]) / DP["hz_ire"]


def response(rf, disc, level, amp=25.0):
    out = []
    for f in FREQS:
        fb, sig = rf_signal(f, amp, disc)
        v = rf.demodblock(data=sig, mtf_level=level)["video"]["demod"]
        out.append(tone(np.asarray(v, float), fb) / amp)
    return np.array(out)


def db(x):
    return 20 * np.log10(x)


def set_strength(rf, s):
    rf.DecoderParams["inverse_mtf_strength"] = s
    rf.recompute_fvideo()


lpf = np.abs(rf.Filters["Fvideo_lpf"])
imtf = np.abs(rf.Filters["Finverse_mtf_base"])
idx = [round(f * n / fs) for f in FREQS]

set_strength(rf, 0.0)
ideal = response(rf, disc=False, level=0)  # RF bpf + demod + LPF + deemp
set_strength(rf, STRENGTH)
full = response(rf, disc=True, level=LEVEL)
set_strength(rf, 0.0)
no_imtf = response(rf, disc=True, level=LEVEL)
uncomp = response(rf, disc=True, level=0)  # disc loss, no RF compensation

# the LPF removed from FVideo
rf2 = make()
rf2.Filters["Fvideo_lpf"] = np.ones_like(rf2.Filters["Fvideo_lpf"])
set_strength(rf2, 0.0)  # rebuilds FVideo from the flat LPF
nolpf = response(rf2, disc=False, level=0)

print(
    f"mtf level {LEVEL}, inverse_mtf_strength {STRENGTH}; dB re 0.5 MHz packet is the second number"
)
hdr = "MHz   LPF   imtf^s | noDisc noDisc-noLPF | disc-uncomp  disc+comp  +imtf(full)"
print(hdr)
for i, f in enumerate(FREQS):
    k = idx[i]
    r = lambda a: f"{db(a[i]):+6.2f}/{db(a[i] / a[0]):+6.2f}"
    print(
        f"{f / 1e6:4.2f} {db(lpf[k]):+6.2f} {STRENGTH * db(imtf[k]):+6.2f} | {r(ideal)} {r(nolpf)} | {r(uncomp)} {r(no_imtf)} {r(full)}"
    )
