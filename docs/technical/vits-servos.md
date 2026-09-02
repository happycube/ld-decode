# VITS-driven auto-calibration servos

The decoder continuously calibrates three filter parameters from the
test signals many discs carry in the vertical blanking interval,
replacing fixed calibrations that could not follow a CAV disc's response
drift with radius. All three run automatically, are dead-banded and rate
limited so decodes stay reproducible, and fall back gracefully when a
disc does not carry the reference signal. Brought up on PAL
(2026-08-30/31), ported to NTSC (2026-08-31); the measurement windows,
loop gains and clamp ranges are per-system (see "NTSC specifics"
below).

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
outer radius (PAL). When an insertion test signal with a 2T pulse is
present — PAL: CCIR ITS on line 19 (bar 13–19 µs, 2T at ~25.2 µs, both
parities); NTSC: NTC-7 composite on line 20 first fields (bar
18–28 µs, 2T at ~34 µs) — the decoder measures the 2T pulse-to-bar
ratio per field and servos `mtf_level` so the response is flat. On PAL
negative levels invert the MTF filter into an HF boost; both
directions are used in practice.

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

Several discs carry a one-line multiburst in the VBI (PAL: GGV on line
13, Louvre and kagemusha on line 20 — first fields; packet sets around
0.5/1/2/4/4.8/5.8 MHz at ~50–60 IRE p-p. NTSC: the FCC multiburst on
line 22, both parities — GGV NTSC carries 1.25/2/3/3.58/4.1 MHz). A
scalar MTF level can only tilt the response; the multiburst reveals —
and corrects — shape errors, such as GGV's recorded −1 dB dip at 2 MHz
at inner radius (both the PAL and NTSC pressings show it).

The servo measures each packet's amplitude with a least-squares sine fit
over the packet's central span (per-window RMS under-reads short
low-frequency packets and biases everything), then builds a zero-phase
magnitude EQ with anchors at the packet frequencies **below 3.6 MHz
(PAL) / 2.8 MHz (NTSC)**, gains set to cancel the deviation from the
~1 MHz reference packet (clamped ±2.5 dB, 0.3 dB dead-band). The EQ is
pinned to 0 dB beyond its last anchor + 0.5 MHz, so the chroma band is
never touched: discs exist (GGV) whose luma is recorded hot around fsc
while chroma is recorded low, and a composite-domain filter cannot
serve both — the burst calibration keeps ownership of the subcarrier
region.

Discs without a multiburst line simply never engage the EQ. The NTC-7
combination multiburst (NTSC line 20 second fields) is deliberately
not used: its ~3 µs packets are as short as the scan window at NTSC
4fsc, so the single-line amplitude fit under-reads by up to 2.5 dB
with the wrong sign (measured on he010 and issue176) — only the
long-packet FCC line 22 variant is trusted.

## Which pulse the 2T servo holds

`_mtf_servo_estimate()` divides the inverse-MTF filter's and the video EQ's
lift out of every measured pulse-to-bar ratio, so what it pools measures the
pre-filter chain alone — a property of `mtf_level` and the disc, independent
of what those two filters were set to when a field was decoded. That is what
makes samples taken either side of a trim comparable, and it stays.

What moved is the *setpoint*. Holding the pre-filter ratio at 1.0 leaves the
pulse in the output high by exactly the gain those filters supply, and
trimming either of them — the multiburst ceiling on `inverse_mtf_strength`
does exactly that — walks the output pulse with nothing to pull it back.
`_mtf_servo_target()` therefore returns `1 / (imtf_2t_gain × veq_2t_gain)`,
read from the adopted `DecoderParams` and never from a live sample pool, so
the sequence of setpoints is the same whether fields arrive serially or from
the job engine.

Measured over the twelve radius cuts, against the differential comparison
IEC 60856-1986 Figure 7 states (see below): the PAL 2T pulse goes from 5 of
12 checks inside their band to 8 of 12 — three moving to PASS, none the
other way.

## When the multiburst ceiling reaches the burst servo

`_imtf_ceiling()` bounds the inverse-MTF strength by what the multiburst
says the chroma band actually needs, because burst amplitude cannot tell a
channel that lost the subcarrier from a disc that recorded it low. Two
defects meant that bound often never arrived, both exposed by the 2T
setpoint change shifting the order adoptions happen in:

**It was only ever applied at the next burst adoption.**
`_deemp_calibrate()` consults the ceiling while it is adopting an estimate,
and returns early inside its own dead-band. A burst servo that had already
converged therefore never saw a ceiling published after it settled.
Measured on BBC Domesday DD86-DS1 outer: the servo settles at 0.456, the
multiburst then reports the band flat at 0.000, and over a 150-frame decode
no further burst adoption ever happens — leaving chrominance about 20 % hot.
`_apply_imtf_ceiling()` now runs where the ceiling is published, at a video
EQ adoption, which the dead-band and rate limit have already made
reproducible. It only ever lowers.

**Its evidence threshold did not match the pool's.** `_veq_estimate()`
adopts a *first* video EQ on 3 samples and every later one on
`VEQ_MIN_SAMPLES`; the flat-band measurement demanded `VEQ_MIN_SAMPLES`
unconditionally. A first adoption holding 3 to 5 samples published no
ceiling at all — and on DD86-DS1 outer that adoption holds exactly 5, every
one carrying the chroma-band packets. Two thresholds over one pool, read at
one moment for one decision, is not a second opinion; both now take the same
number. A later adoption whose pool has thinned also no longer erases a
verdict an earlier one reached.

Measured over the twelve radius cuts, this and the setpoint change together
move **25 checks from FAIL to PASS and none the other way**, and take the
PAL CI capture from 16 of 46 failing to 5 of 46.

## The 2T pulse is judged against its own bar

IEC 60856-1986 Figure 7 states every element of the PAL insertion test
signal as a tolerance about `B₂`, the white reference bar beside it on the
same line — the 2T pulse "within ±0.5 % of `B₂`", the 20T pulse and the
staircase within ±1 %. That is a differential statement, and
`analysis/vits_conformance.py` now judges it as one (`Element.relative_to`).

Judging those elements against an absolute nominal instead reported one
fault several times and sent triage to the wrong subsystem. GGV1011's ITS
line runs 2.3–2.6 IRE low at every radius; measured absolutely, the 2T pulse
inherited the whole of that offset, so a servo holding the pulse at unity
*against its own bar* — which is what `measure_its_2t_ratio()` reads, and
what the pulse measures the HF response with — was reported as failing.
The line's level is still caught, once, at the bar, which fails on three of
the six GGV1011 cuts.

It is not a relaxation. On the PAL CI capture the differential comparison
newly fails `pal-its-field1/pulse_2t`: the pulse sits 3.1 IRE above the bar
on its own line, an overshoot the absolute comparison hid because 100.8 IRE
looks like 100.

No NTSC source this project holds states a tolerance about the bar — the
NTC-7 composite YAML gives the bar and the 2T pulse 100 IRE each and no
relation between them — so NTSC elements stay absolute. Nothing material
rides on that: the NTSC bars measure within 1.6 IRE of nominal on every
radius cut.

## Measured results (2026-08-31)

| Disc / point | Before | After |
|---|---|---|
| Louvre fr2000→6000 span | burst drifted 21.8→20.9 IRE | held 21.3–21.5, 12.3 FPS (was 6.9) |
| Louvre outer radius 2T | 0.933 (uncorrectable) | ~0.99 on a negative level, <1 dB wSNR cost |
| jason 2T pulse-to-bar | 1.014 | 1.000 |
| GGV PAL 2 MHz multiburst dip | −0.96 dB | +0.19 dB (one adoption, stable) |
| he010 inner radius 2T | 1.040 (b/w level 0.45) | 0.999 (servo level 1.5) |
| he010 inner multiburst | +1.2 dB peak at 3.5–4 MHz | flat within +0.4 dB |
| GGV NTSC 2 MHz dip | −1.0 dB | corrected +1.02 dB via FCC line 22 |

Known residual: a +1.0–3.6 dB peak at 4–4.8 MHz on PAL, and a loss of
5.6–9.3 dB at the top multiburst packet (5.8/5.9 MHz). Both were
previously attributed to GGV's own recording and left uncorrected on
the grounds that they lie inside the chroma sidebands. That
attribution does not survive the radius baseline: BBC Domesday
DD86-DS1, an unrelated pressing cut on different equipment, shows the
same peak within 0.85 dB and the same top-end loss at all three radii.
A residual two unrelated pressings share is the decoder's, not one
disc's mastering, so it is now judged — see
`vits_reference.OUT_OF_BAND_RESPONSE_DB`, which sets a limit from what
the two pressings genuinely *disagree* by rather than from what they
share. Six of the twelve radius cuts fail it at 4.0 MHz and all six
PAL cuts fail it at the top packet; NTSC is clean out of band
(worst +0.90 dB).

## NTSC specifics (measured on he010 radius sweeps, 2026-08-31)

The plumbing is shared; the per-system parts live in `__init__`
(`mtf_servo_gain` / `mtf_servo_deadband` / `mtf_servo_scatter` /
`mtf_servo_clip` / `mtf_deemp_feedforward` / `veq_max_freq`) and the
`_VITS_2T_LAYOUT` window table:

- **Loop gain 20** (PAL 6): `MTF_basemult` 0.4 plus a flattening
  response make d(pulse/bar)/d(level) only ~−0.05 over the operating
  range. The dead-band, scatter gate and speculation tolerance scale
  with the gain so they stay the same size in ratio units.
- **Clamp [0, +1.5]**, not symmetric: he010 sweeps show the mid/outer
  2T deficit (ratio ~0.95 at every level) is *not* level-correctable
  on NTSC — the slope collapses to ~0 and goes non-monotonic — so an
  unclamped servo would integrate to a spurious HF boost. The zero
  floor pins it exactly where the b/w mapping lands at those radii;
  the correctable regime (inner radius, ratio > 1, real slope)
  converges normally. The ceiling stays far below level ~2, where FM
  demodulation breaks at inner radius.
- **DP cost**: NTSC keeps phased RF filters, and the MTF poles' phase
  demodulates as differential phase that scales with level — he010
  inner radius measures +0.5° at the b/w level vs +2.2° at servo level
  1.5 (still well inside the ≤5° broadcast-chain band). Amplitude-only
  MTF was tried to remove this and rejected: `|MTF|**level` loses FM
  sync entirely at inner radius at effective exponents the phased
  filter handles fine.
- The inner-radius HF peak previously recorded as "disc-intrinsic" is
  real but *is* correctable by `mtf_level` (it acts on RF before
  demodulation, so it is exempt from the composite-domain chroma
  conflict that caps the EQ); the servo now removes it, at ~0.5 dB
  weighted-SNR cost.
