# VITS-driven auto-calibration servos

The decoder continuously calibrates its filter parameters from the
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

The boost is applied to the demodulated composite, so it lifts whatever
shares the chroma band with the chroma, luminance detail and noise
included. On NTSC the curve is held flat above the top of the chroma
band (`inverse_mtf_hold_hz`, 4.2 MHz). PAL holds nothing, because its
6.3 MHz 16th-order video low-pass ends the curve within 0.6 MHz of its
band's top anyway. The NTSC curve used to keep rising, to +6.6 dB per unit at 7 MHz on NTSC, past a video low-pass
only 7-17 dB down over 5-6 MHz, and at the 1.2 units an outer-radius
NTSC disc asks for, that was most of the luminance noise the correction
added (issue 1072).

The correction is on by default; `--no_auto_chroma` turns it off
entirely, the burst servo and the multiburst ceiling (below) both. It is
written into the samples, so the output's capture notes record it either
way: the strength, the burst as written and as it read before the
correction, and the gain that would bring the burst to nominal (see
`docs/technical/metadata-format.md`).

Where the burst is low because the disc was mastered that way rather
than because the channel lost it, the servo cannot tell the two apart
and corrects both. Under the readout MTF model the channel loss is
mostly made good before demodulation, so less is left for this filter.
On five NTSC discs, the strength it holds drops from 0.84-1.27 to about
0.5-0.65, and the burst before it is applied reads within 0.5 dB of the
level the discs' sidebands say was recorded: 17.7 against 18.2 IRE on
ve-monitor, 17.9 against 18.0 on ve-snw.

### 2. `mtf_level` (2T pulse servo)

The black/white RF carrier ratio cannot predict the needed MTF level
across discs, and it clips at zero while real discs need HF *boost* at
outer radius (PAL). When an insertion test signal with a 2T pulse is
present — PAL: CCIR ITS on line 19 (bar 13–19 µs, 2T at ~25.2 µs, both
parities); NTSC: NTC-7 composite on line 20 first fields (bar
18–28 µs, 2T at ~34 µs), read from line 19 or, failing both, line 13,
where Pioneer's GGV discs carry it — the decoder measures the 2T pulse-to-bar
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
  MTF strength (about 3.2 dB at the subcarrier per level unit on PAL,
  1.0 on NTSC) so burst stays continuous instead of sagging until the
  tracker notices.

Fallback: with no usable ITS (no line, noisy content, scattered
estimates, or explicit `-m`/`--MTF_offset` overrides) the original
black/white carrier-ratio mapping drives `mtf_level` as before.

This servo runs under the pole-pair MTF model, which PAL uses. NTSC
uses the readout model instead, and there the servo stands down; see
"The readout MTF model" below.

### 3. Frequency-resolved video EQ (VITS multiburst servo)

Several discs carry a one-line multiburst in the VBI (PAL: GGV on line
13, Louvre and kagemusha on line 20 — first fields; packet sets around
0.5/1/2/4/4.8/5.8 MHz at ~50–60 IRE p-p. NTSC: the FCC multiburst on
line 22, both parities — GGV NTSC carries 1.25/2/3/3.58/4.1 MHz). A
scalar MTF level can only tilt the response; the multiburst reveals —
and corrects — shape errors, such as GGV's recorded −1 dB dip at 2 MHz
at inner radius (both the PAL and NTSC pressings show it).

The servo measures each packet's amplitude with a least-squares sine fit
over the packet's steady interior (per-window RMS under-reads short
low-frequency packets and biases everything), then builds a zero-phase
magnitude EQ with anchors at the packet frequencies **below 3.6 MHz
(PAL) / 2.8 MHz (NTSC)**, gains set to cancel the deviation from the
~1 MHz reference packet (clamped ±2.5 dB, 0.3 dB dead-band). The EQ is
pinned to 0 dB beyond its last anchor + 0.5 MHz, so the chroma band is
never touched: discs exist (GGV) whose luma is recorded hot around fsc
while chroma is recorded low, and a composite-domain filter cannot
serve both — the burst calibration keeps ownership of the subcarrier
region.

Discs without a multiburst line simply never engage the EQ. Where a
disc has no FCC line 22, the NTC-7 combination multiburst (second
fields, line 13 or 20) is read instead. It had been left out because its
~3 µs packets are as short as the scan window at NTSC 4fsc, and the fit
over the scan windows' span under-read them by up to 2.5 dB with the
wrong sign (measured on he010 and issue176). Fitted over their own
interiors (below), the 2.0–4.2 MHz packets agree with the conformance
checker to 0.3 dB on the GGV and Video Essentials pressings. The line
also carries three-level chrominance at the subcarrier frequency after
its 4.2 MHz packet, so the packets taken are the run along the line that
rises in frequency (`metrics._rising_run`). Dolby Surround's ~2.5 µs
packets leave under 16 samples of interior and are still refused.

The servo's bookkeeping reads what each pooled field was decoded under
off the EQ curve itself (`decoder.applied_eq_db`, the same
`dsp.video_eq_db` the filter is built from), not from the anchor list.
A packet between anchors - the 3.0 MHz key past a 2.75 MHz last anchor,
where the curve is still releasing - had read 0. It also moves each
sample's inverse-MTF share from the strength the field had to the
current one, as the flat-band estimate already did.

**Where the fit looks (2026-10-20).** The scan slides a 44-sample window
along the line and keeps the windows holding one clean tone; a packet is
a group of them. Two things went wrong with short packets, and NTSC's
FCC line is all short packets above 1.25 MHz (about 4 µs, with 1.5 µs
gaps):

- Windows were grouped while each frequency stayed within 0.3 MHz of
  the *previous* one. A window straddling the gap between two packets
  reads a frequency in between, and chained the 3.58 and 4.1 MHz packets
  into one 4.05 MHz "packet" fitted across the gap. They are now grouped
  against the group's median.
- The fit ran over the accepted windows' span less a fifth at each end.
  A window hanging into the gap after a packet is still mostly tone, so
  that span overran the packet. The fit now runs over the packet's own
  steady interior: where its envelope, demodulated at its frequency, is
  at 70 % or more of its 90th percentile, less an eighth at each end
  (`metrics._packet_interior`).

Against a fit over each packet's settled amplitude, the old reading was
0.7 dB low at 2.0 MHz and up to 2 dB low at 4.1 MHz relative to the
1.25 MHz reference, and the EQ answered with +1.6 dB at 2 MHz on the GGV
FCC pressings where +0.4-0.7 dB levels that packet with its reference.
PAL's packets are longer and moved by 0.05-0.1 dB.

## Calibrating before the first frame

Before anything is written, the decoder decodes ahead and lets the
servos settle (`_calibration_warmup`), then starts over from the first
field, so nothing is skipped. By default it stops once no servo has moved
for two fields and, on a disc with a modulated staircase, the DG corrector
has taken its slope decision (three staircase fields), so the first frame
goes out gain-corrected; the phase decision, sixteen readings, is left to
the commit path. `--calibration_frames N` (off by default; 10 is a good
choice) makes it a calibration pass: at least N frames, then until no
servo has moved for 6 fields (`WARMUP_STABLE_FIELDS`), within a further
60 fields. The AGC, the MTF level, the inverse-MTF strength, the
multiburst EQ and its ceiling, and the chroma DG corrector all adopt in
the pass.

The pass is opt-in. It costs a few seconds on every decode, more on
staircase discs, and on a 20-30 frame clip it reads most of the clip
before writing. The radius sweep judges the default decode, and five of
its cuts again with a 10-frame pass, against their own list
(`analysis/vits_known_deviations_calibrated.toml`); a serial and a
`-t 8 --exact-speculation` decode with the pass on are compared byte for
byte. See "The calibration pass" in `cmake_modules/LdDecodeTests.cmake`.

Without the pass, on the radius sweep the EQ, the
2T servo, the inverse-MTF strength and the DG corrector then still
adopted after writing had begun on 13 of 21 captures. DD86-DS2 middle's 2T
servo moved at frame 25 of 30, and its ceiling's cut never arrived before
the clip ended. A 20–30 frame clip carried two calibrations that its
conformance then averaged. With the pass, only three captures move a
decode parameter after the first frame (DD86-DS1 outer, DS2 middle,
GGV1069 LDV4300D outer), and the lane takes 3 % longer. On a long decode
the cost is decoding those frames twice, once. On a few frames cut from a
long capture it is about 3 s (`-l 3`: 4.8 s to 8.1 s). A capture shorter
than the pass just ends it early. The decoder logs whether it is running
a pass, and a line when calibration ends, with what it settled on.

Without a pass, two quiet fields are not by themselves a settled
decoder; two loops needed more:

- **The multiburst EQ.** On a disc whose EQ estimate stays inside its
  0.3 dB dead-band the EQ never adopts, `veq_calibrated` never sets, and
  the warm-up used to run its whole 40-field budget waiting for it: GGV1011
  outer, GGV1069 middle and outer, the LDV4300D middle and outer cuts, the
  three Industrial cuts, DD86-DS1 outer and DS2 inner all decoded 20
  frames ahead, as did ve-monitor and `pal-cvbs`. An estimate held inside the dead-band now counts as decided
  (`_veq_held`).
- **The 2T servo.** Its pool mixes fields decoded at every level it has
  passed through, and each sample is only as absolute as the loop gain is
  right, so the older ones pull the median back and it steps toward its
  level a few fields apart: DD86-DS2 inner goes 0.256 → −0.818 → −0.711 →
  −0.897 → −1.0. Stopping for two quiet fields between steps wrote DS2
  inner's first frame at −0.711. Its six fields decoded there read −0.83,
  and its PAL gain ratio went from 0.23× to 1.35× of its band. So the
  warm-up also waits until the fields decoded at the level in force (at
  least `MTF_SERVO_SETTLE_SAMPLES`, four) would hold it within the servo's
  dead-band (`_mtf_servo_settled`), unless the pool is too scattered for
  the servo to trust.

With both, the nine flat radius cuts write after 4–8 frames instead of 20
(ve-monitor 5.5, `pal-cvbs` 9.5), DS2 inner after 14.5 at −1.0, and every
cut but DS2 inner writes its first frame under the parameters the 20-frame
warm-up settled on (Industrial inner's DG slope aside, +0.00188 against
+0.00208). What the
longer warm-up still bought is the DG phase decision, whose sixteen
staircase readings 40 fields reached and 4–8 frames do not, and a few
small trims the 2T servo does not
gate: DS2 inner's chroma strength, −1.293 then against −1.428 now; the
multiburst ceiling lifting `pal-cvbs`'s from 0.000 to 0.066 after more
than 12 frames; and on DS1 outer and Industrial outer an adoption after
writing that comes at a different field. `pal-cvbs`'s 4.0 MHz packet 26.06 →
25.50 IRE (its band's edge is 25.7), DS2 inner's 100 % chroma bar 43.84 →
42.70 IRE, DS1 outer's 4.0 MHz response 1.07 → 1.38 dB and Industrial
outer's second-field 2T 102.6 → 103.1 IRE; the phase decision taken
after writing begins puts Industrial inner's differential phase back at
2.79° (1.18° with it), Industrial middle's at 1.84° (1.49°) and
ve-monitor's at 2.27° (1.67°), all inside their band. The three
radius-cut checks are recorded in the default list, and `pal-cvbs`'s pin
goes from 5 of 46 failing to 6. Waiting for 6 quiet fields, as
the pass does, recovers none of them and lets DD86-DS2 middle and outer
adopt the 2T servo on a momentary dip in its scatter gate; requiring a
full six-reading pool before an EQ hold counts recovers none either and
puts DS1 outer's chroma ceiling over its band.

The 2T servo's scatter gate was also measured restated for the pool's size
(`std·√(8/n)`), so that a full pool could be proportionally noisier: on
DD86-DS2 outer the per-sample spread is 0.44–0.50 level units around a
median steady at −0.64, and the per-sample gate holds it at the open-loop
level for the whole decode. It engages the servo on four PAL cuts, and on
the noisy Domesday pressings it then walks to its −1.0 clip (−0.61 → −0.80
→ −1.0 on DS1 outer). DS2 outer's first-field 2T and chroma bars pass, but
its multiburst's 4.0–4.8 MHz responses fail and DS1 outer's gain ratio
goes from 0.68× to 1.34×. The gate stays per-sample: a pulse that scatters
that much per field marks a disc on which the level is the wrong
correction.

On a disc with a modulated staircase the pass also waits, up to 25 frames
(`WARMUP_DG_PHASE_FIELDS`), for the DG corrector's phase pool to hold the
`DG_PHASE_MIN_SAMPLES` (16) readings its decision takes. The staircase is
on one field in two and any servo's adoption empties the pool, so ten
frames give it ten readings at most. On the sweep the staircase discs now
write from 17–25 frames, and the NTSC inner cuts' differential phase is
corrected from the first frame (Dolby Surround inner 2.14° → 1.66°,
GGV1069 inner 2.15° → 1.29°, the LDV4300D cut 2.98° → 1.35°).

The committed decode then goes back over the fields the pass read. Every
servo's pool keeps one reading per field (`pool_reading()`): a field
already pooled has its reading replaced where it stands. The pools used to
compare a reading against their last entry only, which caught a redo but
not this, so once writing began each of the pass's fields was pooled
twice, and the medians leaned toward the clip's opening fields. That was
how the phase decision had reached sixteen readings a few frames into the
clip, and how DD86-DS2 middle's DG slope, +0.0012 to +0.0013/IRE read once
per field, had crossed PAL's 0.0015 engage line.

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

Measured over the twelve radius cuts as they then stood, against the
differential comparison IEC 60856-1986 Figure 7 states (see below): the PAL
2T pulse went from 5 of 12 checks inside their band to 8 of 12 — three
moving to PASS, none the other way. An A/B needs both arms measured the same
way and the old setpoint no longer exists, so that pairing is left as it was
taken (DD86-DS1, one field per parity).

On the sample set as it stands now the pulse passes 5 of 12: 5 of 6 on
GGV1011, 0 of 6 on Domesday DD86-DS2. That drop is the pressing and not the
decoder. Measured the same way throughout — this tree, the gated default —
GGV1011 passes 5 of 6 and DD86-DS1 passes 3 of 6, so the sample set as it
was reads 8 of 12 and the sample set as it is reads 5.

On Domesday middle the servo drives `mtf_level` from 0.000 to −0.744, which
is the direction that *raises* demodulated HF, so the loop is asking for the
correction rather than withholding it; see
[`vits-radius-baseline.md`](vits-radius-baseline.md).

### 4. Chroma differential gain and phase (ITS modulated-staircase servo)

The FM channel scales — and rotates — recovered chrominance by the
luminance it rides on. Luminance moves the carrier across its deviation range (PAL 6.757
to 7.900 MHz), carrying the subcarrier's sidebands across the RF filter
chain's tilts — and inward of about mid-radius the disc's own optical
MTF has taken the upper sideband entirely (0.08 falling to 0.04 of
unity across 11.5–12.3 MHz), so chrominance is recovered from the lower
sideband alone and nothing cancels the tilt it sweeps. The luminance
staircase stays linear while this happens (its own sidebands sit close
to the carrier, where every chain is locally flat), which is what makes
it *differential* gain: measured on BBC Domesday DD86-DS2 at inner
radius, 35 % of chroma gain across the luma range against a staircase
nonlinearity of 3–8 %.

That shape rules out two whole classes of fix, both tried and measured:

- A pre-demod filter reshape cannot remove it without moving the
  baseband response — the same RF frequencies serve "chroma at another
  luminance" and "another baseband frequency at this luminance" — and
  flattening the swept bands regressed 16 conformance lanes
  (`pulse_2t`, `packet_6`, `gain_ratio`, NTSC differential gain).
- A memoryless transfer curve would bend luminance by exactly what it
  straightens in chroma.

What is consistent with every constraint is the classic corrector
topology, applied to the composite output with a complex gain — its
magnitude corrects differential gain, its argument differential phase:

    out = composite + Re[(G(luma) − 1) · chroma_analytic]
    G(L) = (1 + slope·50) / (1 + slope·max(L, 0))
           · exp(−j·radians(phase)·max(L, 0))

`measure_vits_dg_staircase()` reads the ITS modulated staircase (PAL
second fields, line 19±1 — NTSC below; six zones from the blanking-level subcarrier
stretch to the 100 IRE tread, each guarded clear of the risers and of
the subcarrier's own end at 60 µs) and fits chroma amplitude and
quadrature phase against luminance (the zones share one line's
4-sample subcarrier lattice, so their phases compare directly, each
referred to the blanking-level zone); the fitted fractional gain slope
per IRE and phase slope in degrees per IRE are pooled and adopted by
`checkChromaDG()` under the usual dead-band and rate limit into
`DecoderParams["chroma_dg_slope"]` and `["chroma_dg_phase"]`, and the
write-time corrector nulls both on both outputs — `downscale_cvbs()`
for the CVBS path, `apply_chroma_dg_correction_output()` in the
parent's `_writeout_data()` for the TBC path (the TBC picture is
downscaled on worker threads before the estimate exists, so the
correction is applied to a write-time copy and `dspicture` keeps the
raw decode). Measured on DD86-DS2 CommunityNorth frames 3000–3100:
pooled differential gain 0.366 → 0.031, chroma flat 17.9–18.4 IRE
across the staircase, luminance levels unchanged.

NTSC reads the NTC-7 composite signal's staircase the same way: first
fields, line 20, or 19, or — Pioneer's GGV discs — 13; the 20 IRE
chrominance reference over blanking, then the five treads to 90 IRE
3.0 µs apart (`_VITS_DG_ZONES_NTSC`, guarded for both the GGV placement
and the one 0.35 µs later that the other discs use). The NTSC CVBS writer
takes the decoder's line-locked rows directly rather than resampling
them, so it asks each field for its corrected picture
(`Field.chroma_dg_cvbs_picture()`) where PAL corrects inside
`downscale_cvbs()`. The NTC-7 estimate is the tighter of the two:
across 25 NTSC captures (20–90 fields each) the pooled in-decoder
slope lands within 0.0002/IRE of the conformance checker's own fit,
with the sign always right, so NTSC engages the gain at 0.0010/IRE —
the limit (0.10 over a 90 IRE staircase) less that error — where PAL
holds 0.0015. Captures that read 0.11–0.18 there went to 0.02–0.06
(saveuniverse 0.182 → 0.039, a Doobie Brothers LD-V4400 capture
0.130 → 0.059, dbcut 0.113 → 0.015); the phase servo's unchanged
thresholds take GGV1016 from 5.7° to 3.9°. Conforming discs whose slope
stays under 0.0010 (VE monitor, he010, GGV1069 middle) are untouched.
Once engaged, the slope correction releases only when the pooled median
falls under `DG_SLOPE_RELEASE` (NTSC 0.0008, the engage line less the
estimator's error again; PAL 0.0010, its conformance limit), as the phase
correction releases under 0.02 where it engages at 0.035. A disc whose
slope sits on the engage line otherwise drops out the first time its
median dips under it, and the rate limit then keeps it off for 100 fields:
Dolby Surround side 1 outer pools −0.00095 to −0.00118 and went out
uncorrected from four frames in (0.080, against 0.034 corrected).

Three properties carry the design:

- **The correction never touches decoding.** Every other servo measures
  upstream of it (`dspicture`, input-rate demod), so no loop closes
  through the correction, an adoption never redoes a field, and nothing
  travels to worker processes — serial and threaded decodes adopt
  identically because both pool the same committed fields at the same
  points.
- **G's magnitude is anchored at the 50 IRE grey pedestal**, the level
  the multiburst-driven chroma calibration measures at, so the levels
  those servos set stay set; blanking-level chrominance — burst
  included — gains the same factor as all other chroma, which is what
  zero differential gain means. Anchoring at blanking instead measured
  the mid-luminance chroma bars 15 % low. **G's argument is anchored at
  blanking**: burst sits at blanking level, hue is decoded relative to
  burst, so the reference must never rotate — every other level's
  chroma is rotated back to the burst's phase, which is what zero
  differential phase means. (For the magnitude the anchor choice
  cancels out of the chroma-to-burst ratio a decoder normalises by;
  for the argument it does not, so only the blanking anchor is
  correct.)
- **A conforming capture gets no correction, by construction**: a disc
  without the modulated staircase never feeds the pool, and a pooled
  slope inside the spec band (|slope| < 0.0015/IRE; the 0.105
  conformance limit itself is ~0.00105 over the 100 IRE staircase) is
  held at zero, because at that size the estimator cannot be trusted
  with the sign — GGV1011's bar capture measures −0.0010 against a
  −0.0003 ground truth, and engaging there put differential gain *in*
  (0.033 → 0.085). The clamp is asymmetric (−0.004 to +0.008 per IRE)
  because the peak-white gain grows as 1/(1 + 100·slope) on the
  negative side. The phase servo holds the same line at
  |phase| < 0.035°/IRE, and takes that decision only from a pool of at
  least 16 per-field readings: a single field's phase fit scatters by
  0.014–0.06°/IRE — a 3-sample first-adoption median once carried
  GGV1011 (whose pooled median is 0.021–0.025, a true 1.8° rise well
  inside the 5.2° limit) over the line — and rotations that small are
  invisible. An engaged correction releases only below 0.02°/IRE, so a
  capture sitting right at the engage threshold corrects or does not
  but never alternates.

On differential phase, the loudest number turned out to be the
instrument. Both differential figures are max-spread statistics, so
per-field noise only ever inflates them: the per-field spread read
12–18° on Domesday, but per-field zone readings referred to their own
blanking-level zone pool across fields without any subcarrier
coherence, and the pooled truth is a monotonic 3.6–4.5° rise (GGV1011:
1.8°) with ~0.4° standard error. The conformance checker now pools the
staircase zone table the same way (`_pooled_differential_zones` in
`analysis/vits_conformance.py`, up to 48 fields per parity), so the
lanes judge the disc rather than the reading; the servo's linear phase
correction then takes the one capture genuinely past the 5.2° limit
(DD86-DS2 NationalA, +0.058°/IRE ≈ 5–6°) back inside it.

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

The mechanism is visible on DD86-DS2 outer, where the strength reaches
0.936 on burst alone and the ceiling takes it to 0.633, and on DD86-DS2
middle, where it does so twice, 1.207 to 0.716 and later 0.348 to 0.000.

**Its evidence threshold did not match the pool's.** `_veq_estimate()`
adopts a *first* video EQ on 3 samples and every later one on
`VEQ_MIN_SAMPLES`; the flat-band measurement demanded `VEQ_MIN_SAMPLES`
unconditionally. A first adoption holding 3 to 5 samples published no
ceiling at all — and on DD86-DS1 outer that adoption holds exactly 5, every
one carrying the chroma-band packets. Two thresholds over one pool, read at
one moment for one decision, is not a second opinion; both now take the same
number. A later adoption whose pool has thinned also no longer erases a
verdict an earlier one reached.

**It borrowed its schedule from the wrong decision.** Publishing at a video
EQ adoption made the ceiling's reproducibility depend on the EQ having
something to adopt, and those are not the same question. The EQ adopts when
it has a correction worth making inside the band it *anchors*; the ceiling
says what the band *above* it needs, and "nothing" is a verdict. A channel
already flat enough for the EQ to decline inside its 0.3 dB dead-band
therefore published no ceiling at all - and that is exactly the channel the
multiburst is most confident about.

Measured on BBC Domesday DD86-DS1 outer, which is in the test data for this
reason and no other: the EQ wants ±0.13 dB at 2 MHz and never adopts across
the whole decode, the chroma band measures flat from the tenth field on, and
the burst servo winds to 1.418 chasing a burst the disc recorded at 15.7 IRE
against the 21.4 it expects. Twenty of forty-nine conformance checks fail,
every one of them a chrominance amplitude. DD86-DS2 adopts an EQ at every
radius, so the pressing that replaced DS1 in the sweep cannot catch this.

`_publish_imtf_flat_band()` therefore gives the verdict its own dead-band
(`IMTF_DEADBAND_DB`, 0.135 dB at the subcarrier on PAL - the same figure
the burst servo holds its own trims inside, on the same quantity, because
a ceiling that moves by less than that cannot change what the burst servo
does) and
its own rate limit, rather than borrowing the EQ's. It still reads the same
pool at the same moment on the same sample-count threshold. On DD86-DS1
outer the strength is now capped at 0.000 and six of forty-six checks fail.

Across the twelve sweep cuts the change moves three checks from FAIL to PASS
and one the other way, and the PAL CI capture goes from 5 of 46 failing to
6. Both regressions are readings that already sat at 0.83× of their band:
`pal-multiburst-field1/packet_5/response` on DD86-DS2 middle (0.83× → 1.28×)
and `pal-its-field2/pulse_2t` on the CI capture (0.83× → 1.06×). The CI
capture is six fields, fewer than any servo needs to settle, so whichever
loop moves last decides the pulse; here that became the burst servo adopting
a capped 0.200 after the 2T servo had already settled. Letting the 2T servo
re-adopt when a ceiling moves was tried and changes nothing, because the
move that matters is the burst servo's own capped adoption and not the
ceiling's.

One further effect is worth stating plainly rather than reading as a
regression. The inverse-MTF is broadband, so a correction wound past what
the chroma band justifies was propping up the top multiburst packet as a
side effect: GGV1011 outer reads −7.84 dB there now against −5.82 before.
Removing an unjustified lift is not allowed to be judged by the packet it
happened to flatter.

Measured over the twelve radius cuts as they then stood, this and the
setpoint change together moved **25 checks from FAIL to PASS and none the
other way**, and took the PAL CI capture from 16 of 46 failing to 5 of 46.

One consequence only became visible once the video low-pass was also fixed:
the inverse-MTF running unbounded was most of the +1.4 to +2.9 dB peak the
radius baseline recorded at 4–4.8 MHz on *both* PAL pressings. With the
ceiling in place GGV1011 reads −0.24 to +1.47 dB across that band and only
Domesday still peaks. The peak was therefore not one shared disc-side
residual, and the reasoning that read it as one is set out in
[`vits-radius-baseline.md`](vits-radius-baseline.md).

## What authorises a cut, and what is only noise

The multiburst ceiling reaches below zero so it can take back gain
something upstream added — the case it exists for is BBC Domesday DD86-DS2
inner, whose chroma band reads +3.6 dB at 4.0 MHz and +4.0 at 4.8 with the
burst servo already bottomed out and the video EQ barred from the band by
`veq_max_freq`. Nothing else in the chain can reach that.

But a cut is a *claim* that gain was added, and the pooled multiburst
estimate cannot carry that claim at any size. `_imtf_ceiling()` already
calls a band "within about a dB of flat" when it is refusing burst
amplitude a boost; the same dB has to mean the same thing in the other
direction, so `IMTF_CUT_ENGAGE_DB` (1.5 dB at the subcarrier; 1.0 until the
calibration pass, below) gates the negative half and the ceiling floors at zero
below it.

The two sides of the threshold are far apart in practice, which is what
makes it a threshold rather than a tuning knob. Across the thirteen radius
cuts and the CI captures only two decodes ask for a cut at all:

| capture | band at fsc | cut |
|---|---|---|
| domesday-ds2-community-north-inner | 4.58 dB hot | −1.701 |
| pal-cut-decoded | 1.69 dB hot | −0.628 |
| domesday-ds2-community-north-middle | 1.24 dB hot | none since 1.5 dB |
| domesday-ds2-community-north-outer | 1.16 dB hot | none since 1.5 dB |
| industrial-lv-side1-inner | 0.58 dB hot | none — under the threshold |

The two DD86-DS2 rows came with the calibration pass. With the decode
allowed to settle before writing, the 2T servo there boosts pre-demod HF
(the disc's 2T reads low) and the band then reads a little over a dB
hot, Domesday's mastered 4–4.8 MHz peak included. At 1.0 dB that was cut,
and the chrominance went under its references: gain ratio 0.266 on the
middle cut, the 3.58 MHz packet −0.46 dB on both. At 1.5 the outer cut's
chroma bars and gain ratio pass again (0.262 → 0.299). Its 4.0 MHz
response then shows the mastered peak at +1.37 dB, which the list
carries.

industrial-lv side 1 inner is the case the threshold was written for. Its
multiburst reads 0.58 dB hot while burst amplitude simultaneously asks for
a 1.9 dB boost — two instruments disagreeing about which way to go, which
is what a measurement at the noise floor looks like. Cutting on it took
0.5 IRE off the 2T pulse, deepened the top packet from −7.9 to −8.7 dB and
dropped the luma/chroma gain ratio from 0.279 to 0.261, outside its
conformance band. Nothing was wrong with that decode's chroma before.

It is a gate and not a subtraction: above the threshold the whole measured
excess is spent, because half a blowout is still a blowout. And it is
stated in dB rather than strength units because one unit of strength is
3.48 dB at PAL's 4.43 MHz but only 1.67 dB at NTSC's 3.58 — a threshold
held in strength units would mean a different channel fault on each system.
Every other bound on this filter is now stated the same way, for the same
reason and for one more: a strength unit is worth whatever the modelled MTF
curve says, so a bound in strength units also moves whenever that curve is
corrected. See "The curve the correction rides" below.

Domesday's cut is unchanged by this, and the top packet it takes with it is
the same effect stated above in reverse: with the band levelled, packets 1
to 5 read flat within 0.6 dB and the 5.8 MHz packet falls to −10.3 dB from
the −3.3 dB it read while the blowout was lifting it. The correction is
measured at the subcarrier and the inverse-MTF curve it rides keeps
deepening above it, so 5.8 MHz gets 7.8 dB of a cut worth 4.6 dB at 4.43.
Capping the cut's extrapolation at the top of the probe band was tried and
returns 1.4 dB of the 10.3, so it does not change the verdict; the packet's
recorded deviation was re-taken against the corrected decode instead.
Removing an unjustified lift is not allowed to be judged by the packet it
happened to flatter, in this direction either.

## When the multiburst may cap a boost on NTSC

Read correctly, NTSC's FCC multiburst puts the chroma band flat 0.5-1.0
dB short of where the burst and the VITS chrominance references (NTC-7,
VIRS) put it, on every Pioneer pressing in hand that carries one:
GGV1069 inner on both players and the GGV multiburst disc. With the
ceiling binding there the strength fell from 0.62 to 0.38 (GGV1069
inner) and from 0.83 to 0.54 (GGV multiburst disc). The 3.58 and
4.1 MHz packets and the luma/chroma gain ratio failed with it, and the
chrominance references read low. The old fit had read that band low by
about as much, so the ceiling never engaged on these discs and the
disagreement did not show.

That is a disc whose multiburst and chrominance were mastered a little
apart, not a channel the boost would overdrive. So on NTSC the boost
side gets the same kind of gate as the cut: `IMTF_CEILING_ENGAGE_DB`,
1.5 dB at the subcarrier. The burst must ask for more than that past the
multiburst's flat-band strength before the multiburst caps it, and once
it does the cap is the flat-band strength, not flat plus the margin. At
1.0 dB the GGV multiburst disc (0.97 dB) capped and released by turns;
1.5 dB leaves half a dB either side of it. PAL caps on any excess, as it
was validated, and the BBC AIV discs the ceiling exists for ask for about
2 dB past flat on either system's terms.

With the gate the strengths are back where they were (0.636, 0.590,
0.832). What the corrected fit still changes on these discs is the 2 MHz
EQ. Their FCC multiburst is recorded low: the 1.25 MHz reference reads
25.7-26.4 IRE against 30, and the 2.0 MHz packet now sits level with it
instead of 1.6 dB above it. Twenty packet-level checks went to the
known-deviation list as recorded low, while the 2.0 MHz response checks
and the GGV1069 inner 2T (102.1 and 102.5 to 101.0 and 100.5) passed.
On Domesday DD86-DS2 the few hundredths of a dB the PAL readings moved
were enough to tip three coupled loops at their thresholds. At middle
radius the 2T servo ran to its -1.0 limit, so the 4.0 MHz response,
saturation ceiling and staircase DG now fail. The inner cut passes three
checks it failed. The list carries both.

## The curve the correction rides

Everything above is stated as dB at the subcarrier, and the exchange rate
between those dB and the strength units the servos actually hold is the
modelled optical MTF: `compute_mtf()` in `lddecode/dsp.py`, whose cutoff is
the readout objective's spatial cutoff, 2·NA/λ cycles per unit length,
carried past the spot at the track velocity. A CAV disc turns once per
frame, so that velocity is 2·π·r·fps and the cutoff scales directly with the
disc's rotation rate.

`get_fmax()` defaulted that rate to 30 rev/s and nothing passed one, so PAL
was modelled at NTSC's rotation: a cutoff of 13.82 MHz where a PAL disc's
is 11.52, and a correction curve half again too shallow — 2.69 dB per unit
of strength at 4.43 MHz against the 3.48 the disc's own response gives. It
is now built at `SysParams["FPS"]`, 25 rev/s on PAL and 29.97 on NTSC. (The
54000 in the same expression is a count of *tracks* between the CAV
programme radii, not of seconds, so it is the same on both systems and does
not move with the rate.)

The first-order effect cancels: both loops that set the strength regulate
dB at the subcarrier, so a converged decode lands at the same correction
under either curve. What does not cancel is everything measured in strength
units — and, on captures short enough that the loops take one or two steps
rather than converging, the step size itself. A Jacobian a third too small
lands a third short, and the residual shows up where the multiburst can see
it. Across the ten PAL radius cuts, the two packets straddling the
subcarrier (4.0 and 4.8 MHz — the band this filter owns and the only direct
measurement of it) go from a worst residual of **1.54 dB to 0.75 dB**, and
the two cuts that carried nearly all of it come back flat:

| Cut | 4.0 MHz | 4.8 MHz | Adopted, dB at fsc |
|---|---|---|---|
| DD86-DS2 middle | +1.54 → +0.31 | +1.47 → +0.05 | +0.73 → +1.86 |
| DD86-DS1 outer | +1.20 → +0.75 | +1.15 → +0.21 | +1.81 → 0.00 |
| DD86-DS2 outer | +0.42 → +0.41 | +0.20 → −0.23 | +1.79 → −1.07 |
| DD86-DS2 inner | +0.52 → +0.55 | −0.62 → −0.65 | −4.58 → −4.56 |
| GGV1011 ×3, industrial-lv ×3 | within 0.06 | within 0.16 | unchanged, or 1.01 → 0.40 |

The Domesday direction is the one to read: the pressing whose chrominance
reads hot gets *less* lift, not more, and DD86-DS1 outer's is withdrawn
entirely — the multiburst was already saying that band was flat and the
under-steep curve was under-hearing it.

The costs are the two effects this page has already described twice, in
both directions. The correction still deepens above the subcarrier faster
than the error does, so the 5.8 MHz packet moves with it (worse by 1.1 to
1.9 dB on DD86-DS1 outer and DD86-DS2 middle, better by 0.3 to 0.5 on
DD86-DS2 outer and industrial-lv outer, and 4 to 10 dB out on every PAL cut
either way). And work withdrawn from the inverse MTF falls to `mtf_level`,
which on DD86-DS1 outer now reaches its −1.0 PAL clip and leaves the 2T
pulse 2.4 IRE lower than the recorded deviation.

The second of those was hidden at first, because the change also cost
DD86-DS2 middle its identification of `pal-its-field1` — and with it the 2T
pulse deviation that line is the only place to read. That line's only
chrominance element is the 20T modulated pulse, which this pressing records
at 5.7 IRE against a 50 IRE nominal where GGV1011 and industrial-lv read 30
to 32, so it sat a tenth of an IRE above the 5 IRE floor `chroma_present`
in
[`analysis/vits_identify.py`](https://github.com/happycube/ld-decode/blob/main/analysis/vits_identify.py)
held it to, and this change moved it to 4.9. Every other feature of the
line still matched: 0.975 alignment correlation, luminance levels within
tolerance, a monotonic staircase.

The floor was the wrong instrument, not the wrong number. A modulated
pulse's chrominance window carries the pulse's envelope rather than an
amplitude, which is why
[`analysis/vits_conformance.py`](https://github.com/happycube/ld-decode/blob/main/analysis/vits_conformance.py)
already refuses to judge it against its nominal, citing EBU Tech. 3209
7.2.4 c); across testdata it spans 4.9 to 37.5 IRE on discs whose sustained
chrominance bars all read 41 to 46. Holding it to a level made a chrominance
level fault delete the identification of the line reporting it, which is
exactly what this layer's looseness against levels exists to prevent. It is
now judged against the line's own chrominance-free windows instead — five
times the quietest of them, floored at the demodulator's own 0.5 IRE — which
every true reading in testdata clears twice over and the closest false one, a
picture line matched at the 0.50 correlation limit, misses by the same
margin. Sustained chrominance keeps the level floor, which is what still
tells the two PAL ITS lines apart: they differ in chrominance alone, and the
field 2 line's is a bar.

With the line identified again, its 2T pulse reads 80.28 IRE against a
100.56 reference — 8.11× its band, against the 5.97× recorded before this
change. That is the same third more band the curve correction costs the
pulse on DD86-DS1 outer (3.19× → 4.15×), on the worst cut of the family, and
it is recorded as such.

Because the strength unit is defined by this curve, every threshold on the
filter is now written in dB at the subcarrier and divided into strength
units per system at construction — `IMTF_LIMIT_DB`, `IMTF_DEADBAND_DB`,
`IMTF_ENGAGE_DB` and `MTF_DEEMP_FEEDFORWARD_DB`, joining the
`IMTF_CUT_ENGAGE_DB` that was already stated that way. Each value is its
system's historical strength-unit figure restated in the dB it meant there,
so correcting the curve leaves every loop exactly where it was tuned and
only the curve itself moves; on NTSC, where the rate changed by 0.1 %, the
adopted `mtf_level` is identical on all nine radius cuts.

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

## The video low-pass and the top of the multiburst

The PAL video low-pass was a 5.8 MHz order 7 Butterworth, chosen to reach the
5.8 MHz multiburst packet IEC 60856-1986 Figure 8 specifies. A Butterworth's
corner *is* its −3 dB point, so the filter took 3.01 dB out of the packet it
was placed for — 3.65 dB on discs recording it at 5.9 MHz, as BBC Domesday
does. That is most of the top-end loss visible on decoded PAL material.

Widening the corner is the obvious fix and a bad one. Demodulated FM noise
power density rises as *f²*, so the last MHz of passband carries far more
noise than signal:

| design | 5.8 MHz | 5.9 MHz | 4fsc Nyquist | FM-weighted noise |
|---|---|---|---|---|
| 5.8 MHz order 7 (was) | −3.01 dB | −3.65 dB | −32.5 dB | 1.00× |
| 7.2 MHz order 7 | −0.11 dB | −0.15 dB | −16.9 dB | 1.89× |
| **6.3 MHz order 16** | **−0.19 dB** | **−0.36 dB** | **−57.6 dB** | **1.23×** |

The 7.2 MHz order 7 option was built and measured before being rejected: it
roughly doubled the RMS on the two lines IEC 60856-1986 9.1.3 blanks for
exactly this measurement (GGV1011 1.24 → 1.44 IRE, Domesday 3.57 → 9.53).

A sharper filter buys the passband without opening the stopband. At order 16
the corner only has to move to 6.3 MHz, which costs 1.23× the FM-weighted
noise and *improves* the stopband by 25 dB. It is also easier on
`build_groupdelay_equalizer()` — a corner sitting in the band generates the
group delay the all-pass then has to undo, and the impulse response holding
99.9 % of the equaliser's energy shrinks from 241 samples to 33. Passband
ripple below 4 MHz stays at 0.000 dB.

Measured over the six PAL radius cuts as they then stood the top packet
recovered **1.07 to 2.70 dB**, and the blanked-line RMS moved 1.24 → 1.24,
1.37 → 1.41 and 1.56 → 1.66 IRE on GGV1011.

**It does not close the gap.** On the current sample set the top packet
reads −3.4 to −8.3 dB and fails all six PAL cuts.
What remains is the channel's, and the decoder has no reference that could
correct it: the inverse-MTF is the only broadband lift available, its
strength is set by burst amplitude and bounded by the chroma band, and both
say "do not boost". A correction driven by the top packet itself would make
the packet its own reference *and* its own verdict, which would destroy the
conformance check rather than pass it.

**One coupling worth knowing.** The 2T servo's scatter gate
(`mtf_servo_scatter`, 0.35 level units) is measured on a pool whose noise
depends on the passband. On BBC Domesday DD86-DS1 middle that scatter sat at
0.35–0.41 — right on the threshold — and the wider passband takes it to
0.42–0.50, so the servo declines the pool on every field there and
`mtf_level` stays at its open-loop value. The gate is behaving correctly;
the pool really is noisier. The consequence is that a static filter choice
decides whether a servo engages, on a disc noisy enough to sit on the
boundary.

It is disc-specific, not a property of the passband alone: on DD86-DS2
middle, the pressing that replaced DS1 in the test data, the same pool
passes the gate and the servo adopts.

## The readout MTF model

`FilterParams["MTF_model"]` selects the pre-demodulation MTF
compensation: `"poles"` is the pole pair raised to `mtf_level` described
above, and `"readout"` is a physical model of the disc's readout. NTSC
uses the readout model, and PAL stays on the poles (see below).

### What the model is

The HF readout passes the disc's spatial frequencies through the overlap
of the zero and first diffracted orders in the objective's pupil, the
autocorrelation of the pupil amplitude. IEC 60857/60856 clause 11.1
specify the reference readout as 632.8 nm, NA 0.40, with the pupil
filled by a Gaussian 23 % (intensity) at its rim. The temporal cutoff is
fc = (2 NA / λ) · v, so on a CAV disc it grows with radius from 13.09
MHz (NTSC, r = 55 mm) or 10.92 MHz (PAL). `dsp.readout_otf` tabulates
it. `mtf_level` names the cutoff as `readout_ref_cutoff_hz` over it.

`dsp.readout_compensation` equalises the channel, readout times the
decoder's own RF band-pass (`RFVideo`), to a straight line rather than
to flat. The line is unity at the blanking carrier and reaches zero at
0.90 fc (`readout_zero_fraction`). A zero-phase response affine in
frequency multiplies an analytic FM signal by a real envelope and leaves
its phase, which is the video, untouched, so only curvature distorts. A
flat target put luminance-dependent gain on the chroma once the upper
sideband crossed the cutoff (differential gain 0.31 on GGV1069 inner).
Designing against the band-pass as well fixed the low burst (11-13 IRE)
on discs whose lower chroma sideband the band-pass's low edge was
cutting.

The line's slope is free as far as the video is concerned, but not as
far as the noise is. Baseband noise at f comes from the RF at fc ± f,
each side scaled by the compensation there relative to the carrier. At
inner radius the readout has the upper sideband 12-20 dB down while the
capture's noise floor is flat out there, so the compensation's lift of
that side is mostly lift of noise. With the zero at 0.95 fc it lifted
11-13 MHz by 4-6.5 dB, doubled the upper side's share of the 3-4.2 MHz
noise (27-31 % to 58-61 %), and left that band 2.5 dB noisier per unit
response than no compensation at all, on an NTSC DdD capture at a
14.9 MHz cutoff. A steeper line lifts the upper side less and the lower
side more. At that capture's cutoff 0.90 fc puts the zero at 13.5 MHz,
peak white's 4.2 MHz upper sideband; below about 15 MHz the line clips
the highest sidebands of the brightest picture, as 0.95 fc already did
below 14.2 MHz, and on the GGV1069 inner cuts (13.8 MHz) that did not
cost a check. On that capture it took 0.9 dB off the 3-4.2
MHz band, and across the NTSC VITS captures it failed 44 checks where
0.95 failed 51. Bounding the boost instead (`readout_max_boost_db` 8 or
12 dB, a Wiener floor) is quieter still but is not a straight line, and
put the differential gain back up (0.042 to 0.075 on GGV1069 LDV4300D
middle). Only the inner radii notice either way: from about 17 MHz up
the upper sideband is strong enough that the lift costs little.

The clipping that did not cost a check there does cost the chroma. A
carrier whose upper chroma sideband lies past the zero keeps only its
lower one, and the line then lifts chroma with luminance: on a disc that
matches the readout model exactly, at an MTF level of 0.96 (13.6 MHz),
by +4.6 % at 72 IRE, +8.5 % at 90 and +11 % at 100. Doobie (CLV, 0.96)
read an NTC-7 differential gain of 0.105 that way, the only NTSC capture
over its band. So the zero is never put below `readout_zero_min_hz`,
13.0 MHz: peak white's carrier plus the subcarrier, with 0.1 MHz to
spare. Only cutoffs under 14.4 MHz (levels above about 0.906) move. On
the model-matched synthetic disc the chroma then stays within 0.4 % at
0.96 and 2.2 % at 1.0; a higher floor asks for more lift above 13 MHz
than the boost bound allows and the chroma falls instead. On the real
inner cuts Doobie goes to 0.047, dbcut 0.080 to 0.056 and GGV1069
LDV4300D inner 0.067 to 0.037, for no change in weighted noise (within
±0.1 dB). It also takes away a lift the clipped line was giving 4.1 MHz
luminance through the lower sideband, about 4 %: the FCC multiburst's
4.1 MHz packet reads 0.4 dB lower on the GGV1069 inner cuts, which puts
it past its band. And it uncovers a second error the clipping had been
offsetting: on real inner-radius discs the compensation now pulls chroma
*down* with luminance (GGV1069 inner from 0.069 to 0.085), where the
model-matched disc stays flat. The real channel falls faster above 12
MHz than the model, and by different amounts on the same disc in two
players (0.089 against 0.034 peak to peak), so part of it is the player's
own response, which a disc model cannot carry.

### Measuring the cutoff

The cutoff is read from the RF, field by field, and pooled like the
other servos' samples. In order of preference:

1. **The PAL pilot's sidebands** (`metrics.pilot_sideband_ratio`). IEC
   60856 9.1.2 puts a 3.75 MHz pilot burst on the PAL sync tip. As FM
   it is a line spectrum, with the two first sidebands at J1(β) H(f) and
   |J₋₁| = |J₁|, so their ratio is H(tip − 3.75 MHz) / H(tip + 3.75
   MHz) whatever the pilot's recorded amplitude. That amplitude varies
   by about 3 dB between discs. The upper sideband, at 10.5 MHz, stays
   under the cutoff on inner radii where the colour burst's has gone.
2. **The colour burst's sidebands** (`metrics.burst_sideband_ratio`).
   This is the same reading, the subcarrier either side of the blanking
   carrier: 4.53 / 11.69 MHz on NTSC, 2.67 / 11.54 MHz on PAL.
3. **The carrier's own tilt** between blanking and white
   (`carrierTiltRatio`), with the raw b/w ratio before that is measured.

A sideband pool is preferred once it holds five readings and at least
half as many as the tilt's. A field gives no reading while either
sideband fails to clear its noise floor, so a sparse pool is the few
fields whose noise read high. `dsp.readout_cutoff_from_tilt` inverts
whichever ratio is chosen through the model.

The tilt is the fallback because it spans only the 1.2 MHz carrier
swing (0.8 MHz on PAL), and the player's and capture's electronics tilt
it too. On GGV1069 outer it reads a 57 MHz cutoff where the CAV radius
gives 22.6 and the burst sidebands 19.9. Over an NTSC survey of 26
captures (the radius cuts plus whole and partial disc captures, each
decoded with `--exact-speculation`), the burst sidebands give 49 failing
conformance checks, the tilt 53, and the pole pair with its 2T servo 79.

### What the sidebands show about the channel

The ratios that are independent of recorded level (pilot and burst,
both systems) put middle and outer radii on the IEC optics at the CAV
radius' cutoff to within 1-3 %, once a fixed droop of about 0.28 dB/MHz
is allowed for. Most of that droop is the Domesday Duplicator 2.2.1
board. The board's measured response is −0.45 dB at 4.5 MHz, −2.0 dB at
11.7 MHz and −4.0 dB at 20 MHz, relative to 1 MHz, with linear phase.
That is 1.56 dB of the roughly 2 dB measured across the burst's
sidebands; the rest is the player. The droop costs no information: the
noise at 11.7 MHz sits about 20 dB above the 18-20 MHz floor, so it
enters before the board and is attenuated with the signal. Inner radii
read a cutoff 3-10 % above the CAV formula.

An earlier channel probe identified the system against an FM reference
rebuilt from the capture's own phase. That reference is biased wherever
the upper sideband is lost, and it read PAL's low end up to 10 dB short
of the optics, which was wrong. The sideband readings replace it.

### Why PAL stays on the poles

PAL's carrier swings to within 3.5 MHz of the cutoff at inner radius,
so luminance detail and chroma above that ride on one sideband alone.
That sideband's level against the carrier varies by disc, and the
pole pair's 2T servo follows it while an open-loop physical model
cannot. Over 15 PAL captures (failing checks, pole pair 93):

| Readout variant | Failing checks |
|---|---|
| Cutoff from the carrier tilt | 124 |
| Cutoff from the CAV radius | 123 |
| Cutoff from the pilot sidebands | 142 |
| CAV cutoff, with the pole pair's 2T servo on top | 113 |
| 2T servo driving the readout level | 134-137 |

The last is unstable: the 2T pulse's response to the level changes sign
between inner and outer radius. Differential gain improves under every
variant (GGV1011 inner 0.106 → about 0.045). The PAL parameter set
carries the readout parameters, and the pilot reading only runs under
the readout model, so switching PAL over takes only `MTF_model`.

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

Known residual, restated after the inverse-MTF ceiling and video
low-pass fixes:

**The 4–4.8 MHz peak was mostly the decoder's, and most of it is gone.**
It was originally attributed to GGV's own recording and left
uncorrected on the grounds that it lies inside the chroma sidebands.
The radius baseline refuted that by finding the same peak on BBC
Domesday DD86-DS1, an unrelated pressing cut on different equipment,
and it is now judged — see `vits_reference.OUT_OF_BAND_RESPONSE_DB`,
which sets a limit from what two pressings genuinely *disagree* by
rather than from what they share. With the inverse-MTF ceiling
reaching the burst servo the shared component goes: GGV1011 now reads
−0.24 to +1.47 dB across 4.0 and 4.8 MHz, and the two rows fail 2 of 6
cuts each instead of 6 of 6 and 5 of 6, and once the ceiling was also
given its own publication schedule all four remaining failures are
Domesday DD86-DS2, at the inner and middle radii. GGV1011 is clean
across the whole band at every radius, within ±0.32 dB, and so is
DD86-DS1. What is left does not track radius and differs by up to
3.5 dB between two pressings of the same title.

**The top packet is not.** All six PAL cuts still fail at 5.8/5.9 MHz,
reading −3.4 to −8.3 dB, and no servo the decoder has can reach it —
see "The video low-pass and the top of the multiburst" above. Part of
what used to sit between those figures and the truth was the
inverse-MTF running above what the chroma band justifies; with the
ceiling now published on its own schedule the loss is fully exposed.

NTSC is clean out of band at every packet (worst +0.90 dB), on the one
cut whose multiburst amplitudes are admissible at this field count.

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
