# VITS-driven auto-calibration servos (PAL)

The PAL decoder continuously calibrates three filter parameters from the
test signals many discs carry in the vertical blanking interval,
replacing fixed calibrations that could not follow a CAV disc's response
drift with radius. All three run automatically, are dead-banded and rate
limited so decodes stay reproducible, and fall back gracefully when a
disc does not carry the reference signal. NTSC currently keeps its
original behavior (see "Status" below).

## The control loops

### 1. Inverse-MTF chroma strength (burst tracking)

The burst-based chroma calibration (`inverse_mtf_strength`, which scales
a zero-phase boost shaped like the disc's optical MTF) previously locked
once at decode start. The required strength drifts with radius (Louvre
PAL: 0.39 at frame 2000 to 0.65 at frame 40000) and moves whenever the
RF MTF level adapts, so it now tracks continuously: a rolling pool of
per-field burst medians re-estimates the strength with a 0.05 dead-band.
Trims are adopted "tolerantly" — handed to future decode jobs without
re-decoding in-flight fields — because a dead-band step changes chroma
by under 2%.

### 2. `mtf_level` (2T pulse servo)

The black/white RF carrier ratio cannot predict the needed MTF level
across discs, and it clips at zero while real discs need HF *boost* at
outer radius. When the CCIR insertion test signal is present (line 19:
white bar 13–19 µs, blanking gap, 2T pulse at ~25.2 µs, both field
parities), the decoder measures the 2T pulse-to-bar ratio per field and
servos `mtf_level` so the response is flat. Negative levels invert the
MTF filter into an HF boost; both directions are used in practice.

Key stability properties (they were all learned the hard way):

- Estimates are *absolute*: each sample pairs the measured ratio with
  the `mtf_level` and `inverse_mtf_strength` the field was decoded
  under, so stale in-flight measurements cannot integrate into runaway.
- The chroma filter's and the video EQ's known lift of the 2T pulse are
  divided out of the measurement, decoupling the loops.
- The two PAL ITS parities differ a few percent in 2T amplitude, so the
  estimate averages per-parity medians rather than a plain median.
- MTF adoptions feed-forward their known chroma cost onto the inverse-
  MTF strength (about 1.2 strength units per level unit) so burst stays
  continuous instead of sagging until the tracker notices.

Fallback: with no usable ITS (no line, noisy content, scattered
estimates, or explicit `-m`/`--MTF_offset` overrides) the original
black/white carrier-ratio mapping drives `mtf_level` as before.

### 3. Frequency-resolved video EQ (VITS multiburst servo)

Several PAL discs carry a one-line multiburst in the VBI (GGV on line
13, Louvre and kagemusha on line 20 — first fields; packet sets around
0.5/1/2/4/4.8/5.8 MHz at ~50–60 IRE p-p). A scalar MTF level can only
tilt the response; the multiburst reveals — and corrects — shape errors,
such as GGV's recorded −1 dB dip at 2 MHz at inner radius.

The servo measures each packet's amplitude with a least-squares sine fit
over the packet's central span (per-window RMS under-reads short
low-frequency packets and biases everything), then builds a zero-phase
magnitude EQ with anchors at the packet frequencies **below 3.6 MHz**,
gains set to cancel the deviation from the ~1 MHz reference packet
(clamped ±2.5 dB, 0.3 dB dead-band). The EQ is pinned to 0 dB beyond its
last anchor + 0.5 MHz, so the chroma band is never touched: discs exist
(GGV) whose luma is recorded hot around fsc while chroma is recorded
low, and a composite-domain filter cannot serve both — the burst
calibration keeps ownership of the subcarrier region.

Discs without a multiburst line simply never engage the EQ.

## Measured results (2026-08-31)

| Disc / point | Before | After |
|---|---|---|
| Louvre fr2000→6000 span | burst drifted 21.8→20.9 IRE | held 21.3–21.5, 12.3 FPS (was 6.9) |
| Louvre outer radius 2T | 0.933 (uncorrectable) | ~0.99 on a negative level, <1 dB wSNR cost |
| jason 2T pulse-to-bar | 1.014 | 1.000 |
| GGV 2 MHz multiburst dip | −0.96 dB | +0.19 dB (one adoption, stable) |
| NTSC (ve-snw-cut) | — | bit-identical (servos PAL-only) |

Known residual: GGV's disc-recorded +1.5–3 dB peak at 4–4.8 MHz lies
inside the chroma sidebands and is deliberately not corrected.

## Status / porting to NTSC

Both servos are gated PAL-only (`mtf_2t_servo`, `veq_servo` in
`decoder.py`); every NTSC decode is bit-identical to the pre-servo
code. The measurement windows are the PAL-specific parts: NTSC would use
the NTC-7 composite layout on line 20 first fields (bar 18–28 µs, 2T at
~34 µs, HAD nominal 250 ns) and the FCC multiburst some discs carry on
line 22 (1.25–4.1 MHz packets). Cautions for the port: the NTSC MTF
mapping and `MTF_basemult` are separately tuned, high MTF levels break
FM demodulation at the innermost radius, NTSC keeps phased RF filters
(level changes move differential phase), and the EQ's chroma-protect
boundary shifts to ~2.8 MHz for fsc = 3.58.
