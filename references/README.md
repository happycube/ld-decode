# Standards references for weighted SNR

Local copies of the sources behind the CCIR/ITU unified noise weighting
implementation in `lddecode/metrics.py` (weighted SNR).

| File | What it is | Key content |
|---|---|---|
| `ITU-R-BT.1204-1995-video-noise-measurement.pdf` | ITU-R BT.1204 (1995), measuring methods for digital video equipment with analogue I/O | Noise measurement procedure: tilt-null / 200 kHz HPF options, band-limiting, use of the weighting network, 525/625 differences |
| `US7995149-weighted-noise-measurement-patent.pdf` | US patent 7,995,149 (Tektronix), subjectively weighted noise measurement | Quotes the unified weighting filter definition: "a 245 nanosecond time constant t0, given in Rec 567-2 FIG. 22"; notes analog/digital/software implementations and rescaling by active-line-time ratio for other formats |
| `Tektronix-25W_7247-NTSC-video-measurements-primer.pdf` | Tektronix NTSC video measurements primer | Background on NTC-7 composite/combination test signals and SNR definition (p-p signal vs RMS noise) |

The unified weighting network (CCIR Rec. 567, "unified" because it replaced
separate 525/625-line networks) is a single-time-constant low-pass:

    |W(f)|^2 = 1 / (1 + (2*pi*f*tau)^2),   tau = 245 ns   (-3 dB ~ 650 kHz)

Weighted SNR = 20*log10(714 mV / weighted RMS noise), band-limited to
4.2 MHz (525) / 5.0 MHz (625), measured on a flat, detrended signal region.
Predicted weighting advantage (numeric integration of the curve): 6.6 dB for
flat noise over 4.2 MHz, 12.5 dB for triangular (FM) noise — matching the
classic broadcast figures.

Note: the CCIR Rec. 567-2 text itself is not freely available; the 245 ns
single-pole form is corroborated by the patent above and instrument
documentation. Downloaded 2026-07-03.
