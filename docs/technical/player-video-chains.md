# LaserDisc player video chains

What real players do between the pickup and the composite output, read from their service
manuals, for comparison with ld-decode's own chain. Six players have been read: the Sony
LDP-1500P (PAL), Pioneer PR-7820 and PR-8210-A (NTSC, discrete), and the Pioneer CLD-S180,
CLD-D406 and Panasonic LX-1000U (NTSC, demodulator IC + digital TBC).

**How the figures were got.** Component values were read off the schematics, and confirmed
from the parts lists where the list gives them. Every response and group-delay figure here is a
simulation of those values (ideal components, ideal transistors unless stated, no strays), not
a number printed in a manual; figures the manuals print are marked *[manual]*. Where an IC pin's
source impedance is unknown both cases are given. Group delay (GD) is relative to 0.5 MHz unless
called absolute. RF figures are relative to the 8.1 MHz blanking carrier.

Compiled 2026-10-19/20.

## Summary

- **De-emphasis is the same everywhere, and it is ld-decode's.** Every network read lands
  within about 10 % of ld-decode's NTSC `video_deemp` (120 ns zero, 320 ns pole); the
  PR-8210-A's is 122/320 ns.
- **No player specifies or aligns its video response.** The alignment procedures set levels,
  dropout timing and VCO frequencies only. None measures multiburst, 2T or DG/DP. The only
  response "spec" is the PR-7820's "NTSC specification (exclusive of de-emphasis)" *[manual]*.
- **The video low-passes total about −0.2 to −1.7 dB at 4.2 MHz**, with −3 dB at 4.4 to
  5.45 MHz. ld-decode's 4.5 MHz 6th-order Butterworth (−1.57 dB at 4.2 MHz) sits inside that
  range at 4.2 MHz but rolls off earlier than all of them above it.
- **Only the Sony equalises group delay.** The other five add +87 to +400 ns at 4.2 MHz through
  their LC filters, the same sign and order as the −200 ns pre-distortion IEC 60857 puts on the
  disc, and appear to rely on it. ld-decode equalises to the IEC curve explicitly.
- **Readout-loss make-up is either a switched RF shelf or fixed video peaking.** The IC-era
  players switch one RF high-frequency shelf (+4.6 to +5.5 dB at 8.1 MHz) on or off by disc
  zone. The PR-7820 has a fixed RF boost and a fixed +6 dB video peaking stage. ld-decode adapts
  both of its equivalents per disc (the readout-MTF compensation and the burst-driven inverse-MTF
  boost).
- **The discrete demodulators hide little.** The pulse-count detectors' aperture costs 0.2 to
  0.5 dB at 4.2 MHz with constant delay. The filters around them that matter are the audio-trap
  stage's RF tilt and, on the PR-8210-A, a 220 ns LC delay line that doubles as a low-pass.

## Sources

| Player / document | Where | Pages used |
|---|---|---|
| DiscoVision PR-7820 Service Manual (1979) | https://archive.org/details/discovisionpr7820servicemanual | Specs p.2; HEDA §9.1 p.19; VDEM §9.2 pp.20–21; spectrum Fig.14 p.23; VTBC §9.9 pp.33–38; adjustments §11; schematics 17.5 HEDA p.132, 17.26 VDEM p.171, 17.31 VTBC-A pp.183–184 |
| PR-7820 Service Manual Supplement 2 (1981, VRT-002-0) | https://archive.org/details/7820SMS-2 | HEDA VWW-007; VDEM VWV-002 pp.50–52 with parts list; VTBC VWW-005 |
| Pioneer PR-8210-A Service Manual (VRT-019-0) | https://www.arcade-museum.com/manuals-laserdisc/Pioneer-PR-8210A-Service-Manual.pdf | Specs p.2; circuit description pp.9–11; adjustments pp.53, 61–62; RF CORR source p.86; VDEM/CPCB schematics pp.87–88; parts pp.89–91; AUDX output pp.94–95 |
| Pioneer LD-1100 Supplement 1 (VRT-004-0) | https://www.arcade-museum.com/manuals-laserdisc/Pioneer-LD-1100-Supplement-1.pdf | VWS-022 schematic and parts, pp.31–34; VSOP replacement note p.5 |
| Pioneer CLD-S180/S280 (RRV1380) | https://archive.org/details/hfe_pioneer_cld-s180_s280_service_rrv1380_en | SCH-5 mother assembly (PDF p.19); video & TBC block (PDF p.51) |
| Pioneer CLD-D406 | https://archive.org/details/cld-d-406-en-service-manual-scan | Mother assembly G-a/G-b (PDF pp.18–19); IC101 pin functions pp.49–50; video & TBC block p.69; specs p.72 |
| Panasonic LX-1000U | https://archive.org/details/lx-1000-u_202407 | Video block diagrams (PDF p.37); video schematic (p.44); digital process (p.46); alignment (p.32) |
| Sony LDP-1500P | https://archive.org/details/ldp1500p | PR-80 board (PDF p.57); VP-18 board (PDF p.60) |

Background: RCA LaserDisc tech training manual (1990); Philips Technical Review vol.33 no.7
(1973) VLP articles; Badger & Allen, "The Audio Side of the Laser Videodisc", AES preprint 1935
(1982); patents US4340950 (Pioneer), US5073886 (Sanyo), US4858024 (Pioneer); the LD-V4300D
spec sheet as quoted by notonbluray.com. The original PR-8210 manual (VRT-006) was not found;
the PR-8210 supplement (VRT-010) has no video content. IEC 61599 (player measurement methods)
is paywalled and unread.

## Pioneer PR-7820 (NTSC, 1979)

A discrete industrial player with a CCD timebase corrector. The main video filters are the
same in both printings.

**Path.** Photodiode → FET cascode (≈20 dB *[manual]*) → Q5 "equalizing amplifier" → Q6/Q7
(≈30 dB total *[manual]*) → LC filter against 620 MHz laser spurii → VDEM: buffers, RF level
→ LC band-pass → FET stage with 2.3/2.8 MHz traps in its source → TA7302P limiter (untuned) →
SN75107 comparator → gate-delay pulse-count detector → elliptic low-pass → amplifiers (one with
emitter peaking) → de-emphasis → second low-pass → dropout switch → VTBC: high boost → two
CCD321A lines → 4.8 MHz video filter → clamp → (old board) 8 MHz low-pass → 75 Ω output.
Nothing switches with radius or disc type in the video path.

| Stage | Values | Response |
|---|---|---|
| HEDA Q5 RF equaliser (fixed) | R26 560 collector; emitter (R27 330 + R28 2.7k ∥ C18 0.047 µ) ∥ (R29 47 + C19 47p); re 5 Ω assumed | Zero 8.98 MHz, pole ≈65 MHz. −1.78/−0.95/+0.56/+1.92/+3.04 dB at 3.9/6/9.3/12.3/15 MHz |
| VDEM band-pass ("filter 2") | R11 1k source; series C7 56p, shunt L1 27 µ, series C8 56p; shunt C9 8p, series L2 18 µ, shunt C10 22p, series L3 18 µ, shunt C11 8p; load ≈1.02 kΩ | −3 dB 2.97–14.71 MHz; −0.70 dB at 3.9 MHz, −0.17 at 12.3, −3.63 at 15 |
| Q3 2SK19 audio-trap stage | Source: R17 100 + (L5 18 µ ∥ C17 180p) + (L6 18 µ ∥ C18 270p); 1/gm 150 Ω, coil Q 40 assumed | −28.7 dB at 2.3 MHz, −32 dB at 2.8 MHz. Above the traps the source looks capacitive: −7.3/−4.7/−1.7 dB at 3.9/4.52/6 MHz, +1.2 dB at 12.3 MHz |
| Pulse-count detector | 4 × 74LS08 per edge chain, C39 22p and VC1 10–45p trimmer ("linearity"), 74S00 combiner | Pulse width τ ≈ 35–50 ns (45 nominal, estimated). sinc(fτ): −0.47 dB at 4.2 MHz, flat 22.5 ns delay |
| Post-detector elliptic LPF | R41 1.3k; shunt C40 8p; L10 39 µ ∥ C41 8p (zero 9.01 MHz); shunt C42 33p; L11 43 µ ∥ C43 15p (zero 6.27 MHz); shunt C44 33p; high-Z load | −1.48 dB, absolute GD 275 ns at 4.2 MHz; −3 dB at 4.55 MHz; ≈−37 dB at 2× carrier |
| Q7/Q8 amplifier | R53 2.4k feedback | Flat (−0.07 dB at 4.2 MHz) |
| Q9/Q10 amplifier with emitter peaking | R64 24k feedback; Q10 emitter R63 150 ∥ C58 470p (parts list CQSH 471J) | Zero 2.26 MHz: +2.60/+5.52/+6.11 dB at 2/3.58/4.2 MHz; +74 ns at 4.2 MHz. +5.1 to +6.6 dB over transistor parameters |
| De-emphasis | Q11 emitter → R66 330 series → shunt R67 220 + C60 560p | τ zero 123 ns, pole 308 ns (312 with source). Shelf −7.96 dB; within 0.3 dB of ld-decode's 120/320 ns |
| Second LPF ("fc = 5 MHz" *[manual]*) | R69 300; shunt C62 33p, L14 8.2 µ, shunt C63 150p, L15 15 µ, shunt C64 160p; load ≈1.1k | −0.55 dB, absolute GD 141 ns at 4.2 MHz; −3 dB 5.33 MHz |
| VTBC high boost | Old: R202 510 ∥ C74 150p, R203 470, R204 330. New (VWW-005): R3 120 + R4 510 ∥ C2 150p, R5 330 | Old +2.89 dB, new +4.09 dB at 4.2 MHz |
| CCD sample-and-hold | 10 MHz clock *[manual]* | −0.64 dB (half-period hold) or −2.69 dB (full) at 4.2 MHz |
| VTBC video filter ("fc 4.8 MHz" *[manual]*) | Old: ≈900 Ω source; L8 27 µ, shunt C64 43p, L9 33 µ ∥ C62 15p (zero 7.16 MHz), shunt C65 47p, L10 36 µ ∥ C63 7p (zero 10.0 MHz), shunt C66 24p; load 1k | Old −0.21 dB, absolute GD 193 ns at 4.2 MHz, −3 dB 5.33 MHz. New: zeros 6.85/10.0 MHz, −0.30 dB, 237 ns, −3 dB 4.95 MHz |
| Old VTBC 8 MHz LPF | R162 1k; shunt C71 22p; L11 22 µ ∥ C70 3p; shunt C72 22p; R163 1.5k | −0.38 dB, 34 ns at 4.2 MHz. Removed on the new board |

**RF tilt.** The equaliser, band-pass and trap stage together lift the upper sideband over the
lower by 9.3 dB at ±3.58 MHz and 12.7 dB at ±4.2 MHz around 8.1 MHz (11.5/17.4 dB around
7.6 MHz, 6.3/7.5 dB around 9.3 MHz): a fixed, RF-domain version of ld-decode's readout-MTF
compensation. The FM-equivalent video response of that RF chain on a flat disc is −1.46 dB at
4.2 MHz (−1.81 dB with the head amplifier's 26 MHz pole).

**Video peaking.** C58 makes the effective high-frequency de-emphasis about −2 dB instead of
−8 dB: a fixed video-domain readout-loss boost, the closest hardware counterpart to ld-decode's
inverse-MTF boost.

**Totals at 4.2 MHz.**

| Chain | Response | GD | −3 dB |
|---|---|---|---|
| VDEM alone, ideal de-emphasis divided out | +3.8 dB | +287 ns | 4.88 MHz |
| VDEM alone without C58 | −3.4 dB | | 3.99 MHz |
| Whole chain incl. de-emphasis, old VTBC | −1.70 dB | +352 ns | 4.44 MHz |
| Whole chain incl. de-emphasis, new VTBC | −0.21 dB | +390 ns | 4.56 MHz |
| Whole chain, ideal de-emphasis divided out, old VTBC | +4.0 dB | +413 ns | 4.83 MHz |

**Dropout path.** RF taken before the limiter → 1H glass delay line (PDL-683B/K or ADL-CN983U)
→ separate HA1137P quadrature detector → one-capacitor "de-emphasis + high-cut" (C82 15p, 33p in
1981). 74123 one-shots delay the switch by the filters' "several hundred ns" *[manual]*. The
quadrature tank as printed (L19 18 µ ∥ C81 43p ≈ 5.7 MHz) does not centre on 8.1 MHz; not
simulated.

**Specs and alignment.** Video response "NTSC specification (exclusive of de-emphasis)"; 1 Vp-p
into 75 Ω *[manual]*. No S/N figure. VC1 (detector linearity) and VR2 (limiter balance) appear
only in the circuit text. The video adjustments are dropout sensitivity and VTBC output level
(1 V ± 0.1 V) only.

**Caveats.** Inductors are values printed on the schematic (the parts list gives coil part
numbers only); coil Q, 2SK19 gm, transistor fT/beta and τ are estimates. Between printings,
R18 220 → 100, R48 1k → 820 and the dropout-path tuning changed.

## Pioneer PR-8210-A (NTSC)

Read from the PR-8210-A manual, VSOP board VWS-022, which is also the LD-1100's board from
serial 3611501. The original PR-8210 and early LD-1100s used an older VSOP (VWS-020 + VWV-015)
that has not been read. Capacitors and coils are confirmed from the parts lists; resistors are
read from 200 dpi 1-bit schematics only.

**Path.** RF in (R201 110 Ω) → Q201 common-emitter amplifier with switched HF boost (Q203,
driven by RF CORR) → Q202 → LC band-pass → Q204 2SK19 with the audio traps in its source → Q205
→ UA5001 limiter (untuned; pins carry only 0.01 µ decoupling) → UA5001 pulse-count
discriminator (timing C236 47p N750) → R228 1.1k load → "F1 4.2 MHz" elliptic LPF → Q209 →
VR201 level → internal amplifier (31–32 dB *[manual]*) → Q223 → "F2 220 ns" LC delay → Q210 →
internal dropout switch → de-emphasis → Q213 → CPCB chroma-phase corrector → clamp and blanking
switches → Q211 → AUDX Q10 → 470 µF → 68 Ω → 75 Ω BNC. No peaking, no group-delay equaliser and
no adjustable coils in the video path.

**RF boost switching.** RF CORR comes from the spindle chip's disc-zone switches; the manual
says gain is compensated "up to frame number #13500 (approx), especially in the high frequency
region" *[manual]*, i.e. the inner zone of a CAV disc.

| Stage | Values | Response |
|---|---|---|
| Q201 RF boost, on | R204 470; emitter R205 100 ∥ (C205 270p + Q203); re and Rsat 5 Ω assumed | Zero 5.9 MHz. −2.93/−2.21/+0.77/+2.45/+3.68 dB at 4/5/9.3/12.3/15 MHz; +4.7 dB at 8.1 MHz re 1 MHz. Off: flat within 0.3 dB |
| Band-pass | Rs 1k; C209 56p series, L201 27 µ shunt, C210 56p series, C211 8p shunt, L202 18 µ series, C212 22p shunt, L203 18 µ series, C213 8p shunt; RL 1.1k + 5 pF | −3 dB at 2.90 and 14.81 MHz; −0.23 dB at 4 MHz, −1.38 dB at 14 MHz. Same values as the PR-7820 |
| Audio-trap stage | Source R212 330 + (L204 18 µ ∥ C215 180p) + (L205 18 µ ∥ C216 270p); Rd 1k; gm 4–8 mS, coil Q 40 | −24 to −26 dB at 2.28 MHz, −27 to −29 dB at 2.80 MHz; −2.8 to −3.8 dB at 4 MHz, −1.0 to −1.5 dB at 5 MHz |
| Pulse-count aperture | C236 47p (Fig.3 draws 68p) | τ not printed; −0.16 dB at 4.2 MHz for 25 ns, −0.40 dB for 40 ns, constant delay τ/2. Images around 2× carrier, removed by F1 |
| F1 elliptic LPF | Rs 1.1k; C233 8p; L206 39 µ ∥ C231 8p (zero 9.01 MHz); C234 33p; L207 43 µ ∥ C232 15p (zero 6.27 MHz); C235 33p; R229 100 into Q209 | −1.48 dB, +143 ns at 4.2 MHz; −3 dB 4.68 MHz; −43 dB at 8.1 MHz, −36 dB at 16.2–18.6 MHz. Same ladder as the PR-7820's |
| F2 220 ns delay (9th-order LC) | Rs R233 270; C241 51p, L208 12 µ, C242 160p, L209 16 µ, C243 200p, L210 18 µ, C244 200p, L211 18 µ, C245 150p; RL R234 1.5k | +0.19 dB, +117 ns at 4.2 MHz; −3 dB 5.13 MHz; absolute 225 ns. Ripple depends on R234, whose role is uncertain (matched ≈280 Ω: −0.18 dB, +146 ns) |
| De-emphasis | R241 680 + C251 180p, R240 1.1k | τ zero 122 ns, pole 320 ns (+≈9 ns with 50 Ω source). Within 0.15 dB of ld-decode to 5 MHz |

**RF tilt (USB − LSB).** RF CORR off: +1.9 dB at ±3.58 MHz and +3.8 dB at ±4.2 MHz around
8.1 MHz (+3.5/+7.9 dB around 7.6 MHz, ≈0 around 9.3 MHz), mostly from the trap skirts. RF CORR
on: +9.6 dB at ±4.2 MHz.

**Totals at 4.2 MHz** (aperture τ 30 ns × F1 × F2, de-emphasis divided out): −1.38 dB, +261 ns,
−3 dB at 4.74 MHz, ripple +0.5 dB at 1 MHz and +0.7 dB at 3 MHz. Over a ±5 % L/C tolerance spread:
−2.8 to −0.3 dB, +181 to +377 ns, −3 dB at 3.8 to 4.9 MHz.

**Side paths.** The dropout substitute is RF through a 1H glass delay line (DL201) with 2.2 µH
matching coils, a Q207 emitter equaliser (≈+10 dB shelf from 1 to 8 MHz), a second
discriminator in the UA5002, and a 3rd-order Sallen-Key low-pass at 1.36 MHz (−18.5 dB at
4.2 MHz): luma only, since NTSC chroma one line later is phase-inverted. The CPCB (VWV-023) is a
0.5 µs delay line and a varactor-tuned 3.58 MHz phase shifter driven by the tangential-servo
error: a chroma phase corrector, not simulated.

**Specs and alignment.** Video 1 Vp-p into 75 Ω; video S/N "More than 42dB" *[manual]*. Video
alignment is output level (VR201, 1 ± 0.1 V sync tip to white), 1H-delayed level (VR202), DOS
timing (VR204, 5.5 MHz 200 mVp-p injected) and V-sync trailing edge (VR203) only.

## Pioneer CLD-S180 / CLD-D406 (NTSC)

The two share their analog video circuit; the CLD-D406's C434 reads 12p where the CLD-S180's
is 15p. Video IC: PAC005B (CLD-S180), LA7134M (CLD-D406); limiter and demodulator are inside
it and the demodulator type is not stated.

**Path (CLD-D406).** Pickup → Q152 inverter with Q805 RF correction → Q803 RF buffer (split to
EFM, analog audio, video) → Q411 → LC band-pass with audio traps → IC400 limiter/demodulator →
LPF 1 → Q451 → VR450 level → de-emphasis amplifier → noise reduction → LPF 2 → Q475 → sync clamp
→ IC500 PD0234A digital TBC (ADC at 4fsc, 1H memory, dropout compensation) → DAC → post-DAC LPF →
Q701 → MC14577CP output amplifier (gain 2).

| Stage | Values | Response |
|---|---|---|
| RF correction (switched) | Q152 emitter R807 330; R810 100 + C806 68p to Q805 | Zero 5.44 MHz, pole 23.4 MHz: +1.8/+3.2/+4.6/+5.3/+6.7 dB at 4/6/8.1/9.3/12 MHz |
| RF band-pass | C468 47p + C415 15p series, shunt L410 100 µ + C425 39p (2.55 MHz); C467 27p + R418 680; traps L411 27 µ ∥ C416 120p (2.80 MHz) and L412 22 µ ∥ C417 220p (2.29 MHz); C418 16p, L413 10 µ, C419 27p, L414 8.2 µ ∥ C421 10p, C420 10p; R417 680 | Roughly 4–15 MHz: −4 dB at 4 MHz, −3.5 dB at 15 MHz; notch 17.6 MHz |
| LPF 1 (before de-emphasis) | Shunt C433 27p; L420 43 µ ∥ C434 12p; shunt C435 33p; L421 43 µ ∥ (C436 7p + C438 10p in series); shunt C437 12p; load R425 1.2k | Low-Z source: −1.95 dB, +75 ns at 4.2 MHz, −3 dB 4.65 MHz. Matched 1.2k: −0.43 dB, +76 ns, −3 dB 5.19 MHz. Notches 7.01, 11.96 MHz |
| LPF 2 (after NR) | R480 820; shunt C474 12p; L470 22 µ ∥ C475 15p; shunt C476 39p; high-Z load | +0.61 dB, +41 ns at 4.2 MHz; −3 dB 5.93 MHz; notch 8.76 MHz |
| Post-DAC LPF | R600 820; shunt C594 15p; L590 27 µ ∥ C617 7p; shunt C596 47p; L591 27 µ ∥ C618 22p; shunt C598 39p | High-Z load: +0.92 dB, +111 ns at 4.2 MHz, −3 dB 5.15 MHz; notches 6.53, 11.58 MHz |
| DAC hold (if uncompensated) | 14.318 MHz zero-order hold | −1.27 dB at 4.2 MHz |
| De-emphasis | Input R456 1k; feedback R458 5.6k ∥ (R457 3.9k + C452 33p), inverting assumed | τ zero 128.7 ns, pole 313.5 ns, shelf −7.73 dB |

**RF correction switching.** Driven by RF CORR from IC101 PD0245A2 pin 2, whose description
reads "RF correction switch signal output H : Gain UP CD, CDV-A : Low, CAV inner circuit gain up,
others are High" *[manual]*. That suggests the boost is on for CAV inner and possibly for
CLV, but the wording is ambiguous. The position comes from inner/outer pickup switches.

**Totals at 4.2 MHz (CLD-D406).** About +227 ns (+179 ns at 4.0 MHz); about −0.2 dB with a
matched LPF 1 source or −1.7 dB with a low-Z one, including the DAC hold. The CLD-S180's analog
filters alone give about +115 to +148 ns. The digital processor has outline-correction and
sharpness controls whose response is undocumented. Specs give only 1 Vp-p; alignment is output
level only.

## Panasonic LX-1000U (NTSC)

**Path.** Pickup → head amp → Q22001 → Q3201–Q3203 with the MTF switch QR3201 → R3210 820 →
LC3201 band-pass module → LC3202 2.3 MHz trap → LC3203 2.8 MHz trap → peaking arm → Q3206 with a
diode limiter → IC3201 AN2661NK limiter and demodulator → 5.5 MHz LPF → Q3205 phase splitter →
VR3201 level → de-emphasis → Q3209 LPF → MC14576A → A/D LPF → 14.3 MHz A/D → digital TBC (dropout
detection, 1H memory) → digital Y/C separator → Y and C D/As → two Y noise cancellers (one active
on CLV only) → outputs. The chroma path has a phase compensator with a chroma trap.

| Stage | Values | Response |
|---|---|---|
| MTF switch (on except on the outer part of CAV discs) | Q3202 collector R3204 1k, emitter R3205 270 / R3206 330; C3271 100p + R3421 68 to QR3201 UN2211 | Zero 4.71 MHz: +2.2/+3.9/+5.5/+6.3/+7.7 dB at 4/6/8.1/9.3/12 MHz |
| RF band-pass and trap modules | Values not shown | From the manual's graph: ≈−5 dB at 4 MHz, 0 dB 5–12 MHz, −10 dB at 14 MHz, notches near 2.3 and 2.9 MHz |
| Post-trap arms | Shunt R3211 1.8k + (L3237 8.2 µ ∥ C3373 15p, 14.35 MHz); coupling R3283 560 + C3277 75p + L3220 4.7 µ | Mild upper-band-edge lift; −0.6 dB at 4 MHz |
| 5.5 MHz LPF (before de-emphasis) | R3221 560; shunt C3213 24p; L3221 20 µ; shunt C3214 82p; L3222 30 µ; shunt C3215 100p; L3223 30 µ; shunt C3227 82p; load R3222 5.6k | 7th-order all-pole: +0.09 dB, +71 ns at 4.2 MHz; −3 dB 5.45 MHz |
| Q3205 phase splitter | R3223 220 collector, R3353 220 emitter, C3279 33p and R3239 560 summed | −1.26 dB, −9 ns at 4.2 MHz |
| De-emphasis | Feedback R3319 3.9k ∥ (R3320 2.7k + C3280 43p), inverting assumed | τ zero 116.1 ns, pole 283.8 ns, shelf −7.76 dB |
| Q3209 LPF | R3321 390; shunt C3284 27p; L3224 10 µ; shunt C3285 68p | Flat to 5 MHz; −3 dB ≈9 MHz |
| A/D anti-alias LPF | R3705 560; shunt C3706 33p; L3702 27 µ; shunt C3707 68p; L3703 27 µ ∥ C3709 3p; shunt C3708 33p; R3706 560 | −0.18 dB, +21 ns at 4.2 MHz; −3 dB 6.35 MHz; notch 17.7 MHz |

**Totals at 4.2 MHz.** About −1.3 dB and +87 ns (+71 ns at 4.0 MHz), excluding the D/A,
digital Y/C separation and noise cancellers. No video response or S/N spec; alignment is four
level adjustments.

## Sony LDP-1500P (PAL)

**RF.** Q101 2SK184 "MTF COMPENSATOR" switches C103 180p across the 220 Ω emitter resistor of
RF amplifier Q102 (corner ≈4 MHz). It is driven from an "MTF POSITION DETECTOR" (slider pot,
comparators, 8/12-inch switch), with gate voltages annotated "INNER: 0.34 / OUTER: −1.64"
*[manual]*: a two-state, radius-switched boost. Then an LC LPF (C111 8.2p, L103 15 µ, C112
8.2p) and emitter traps L104 120 µ ∥ C113 470p and L105 47 µ ∥ C114 470p at 0.67 and 1.07 MHz,
the PAL sound carriers.

**Demodulator.** M51481P: limiter → monostable → multiplier (pulse-count).

**Video.** Output ladder (R125 1.5k, C129 12p, L108 68 µ, C130 33p, L109 68 µ ∥ C132 2.7p,
C131 10p, into 1k + 2.2k): flat ±0.15 dB to 4.5 MHz, −2.4 dB at 6 MHz, notch 11.75 MHz, +34 ns
at 4.2 MHz. A "DELAY" phase-splitter stage (Q108/Q109; C135 56p + L110 27 µ vs R134 1.2k) gives
about −64 ns at 4.0 MHz. After the CXL1004P CCD TBC a "PHASE EQUALIZER" (Q15/Q16; R48 1.2k vs
L11 39 µ + C50 68p, a 3.09 MHz second-order all-pass) gives about −78 ns at 4.2 MHz, followed by
an LPF (R51 1k, C52 8.2p, L12 27 µ ∥ C55 56p, C53 47p, L13 56 µ, C54 22p, R52 2.2k), a switched
pilot-burst trap and a 1k/330p buffer. C55 56p (checked at 600 dpi) puts a notch near 4.09 MHz
in a PAL path, which is unexplained. The only player read with group-delay equalising stages.

**Alignment.** Demodulator level 2.0 ± 0.1 V at TP102; dropout detector set with an injected
5.0/5.5 MHz signal.

## Across the players

**De-emphasis**

| Player | Zero τ | Pole τ | HF shelf |
|---|---|---|---|
| PR-8210-A | 122 ns | 320 ns | −8.3 dB |
| PR-7820 | 123 ns | 308 ns | −8.0 dB |
| CLD-S180 / CLD-D406 | 129 ns | 314 ns | −7.7 dB |
| LX-1000U | 116 ns | 284 ns | −7.8 dB |
| ld-decode NTSC `video_deemp` | 120 ns | 320 ns | −8.5 dB |

**RF high-frequency boost**

| Player | Switching | At 8.1 MHz |
|---|---|---|
| PR-7820 | Fixed | Zero 8.98 MHz; with the trap-stage tilt, USB − LSB +12.7 dB at ±4.2 MHz |
| PR-8210-A | On up to ≈ frame 13500 (CAV inner) | +4.7 dB |
| CLD-D406 | Two-state, "CAV inner" per the pin description | +4.6 dB |
| LX-1000U | Off only on CAV outer | +5.5 dB |
| LDP-1500P | Two-state, inner/outer by slider | Not calculated |

The patents agree: Sanyo's US5073886 describes conventional correction as "merely switched
stepwise" from a position table, applied "only at the inner track" on CAV and across the whole
disc on CLV. Pioneer's US4340950 drives the equaliser from the video carrier level instead.

**Video low-pass and group delay at 4.2 MHz** (de-emphasis excluded)

| Player | Response | GD | −3 dB | GD equaliser |
|---|---|---|---|---|
| PR-7820 | VDEM LPFs −2.0 dB; whole chain with peaking and TBC −1.7 / −0.2 dB (old / new TBC) | +352 / +390 ns whole chain | 4.44 / 4.56 MHz whole chain | None |
| PR-8210-A | −1.38 dB | +261 ns | 4.74 MHz | None |
| CLD-D406 | −0.2 to −1.7 dB | +227 ns | ≈4.7–5.2 MHz | None |
| LX-1000U | −1.3 dB | +87 ns | ≈5.4 MHz | −9 ns phase splitter |
| LDP-1500P (PAL) | Output ladder ≈0 dB (post-TBC LPF not totalled) | +34 ns, then two −64/−78 ns stages | ≈6 MHz (output ladder) | Two stages |
| ld-decode NTSC `video_lpf` | −1.57 dB | +92 ns, then equalised to IEC 60857 | 4.5 MHz | All-pass to the IEC curve |

**Demodulators.** Pulse-count where stated (PR-7820 gate-delay detector, PR-8210-A UA5001,
LDP-1500P M51481P). Their aperture is a sinc of the pulse width, −0.2 to −0.5 dB at 4.2 MHz with
constant delay; the images around twice the carrier are what the elliptic LPFs' 6.27/9.01 MHz
zeros and stopbands are for. The IC players' demodulators (PAC005B, LA7134M, AN2661NK) are not
documented. Other Pioneer video demodulator ICs listed in the GGF-613 repair guide: SN76670N
(LD-707/V3000), PA0023 (LD-717, V2000, V4200, 838D, CLD-1010/1050), UA5002A (CLD-909).

**Specs.** LD-V4300D spec sheet: "4.1MHz, -6dB (NTSC) / 4.8MHz, -6db (PAL)", S/N 48 dB NTSC /
43 dB PAL. PR-8210-A: S/N "More than 42dB". Badger & Allen give typical disc video S/N of 38 to
43 dB. No other player read gives a video response or S/N figure.

## Against ld-decode's chain

ld-decode's NTSC chain is: RF band-pass 3.7 MHz (2nd-order Butterworth high-pass) to 13.8 MHz
(3rd-order low-pass) → readout-MTF compensation (a straight-line target from the 8.1 MHz carrier
to a zero at least 13.0 MHz) → ideal phase demodulator → 4.5 MHz 6th-order Butterworth → 120/320 ns
de-emphasis → inverse-MTF chroma boost (held above 4.2 MHz) → all-pass group-delay equaliser to
IEC 60857's curve.

Simulated through `RFDecode.demodblock` with a model disc (2026-10-19), the readout compensation
leaves the RF side flat, so before the boost the chain at 4.2 MHz is the low-pass alone: −1.5 dB.
The burst-driven inverse-MTF boost adds 2.4 dB per unit of strength at 4.2 MHz, and the servo
settles between about 0.15 and 1.7 per capture, so the decoded response at 4.2 MHz varies with
the capture.

- **De-emphasis** matches every player.
- **The video low-pass** is inside the players' range at 4.2 MHz but steeper above it:
  −3 dB at 4.5 MHz against 4.4 to 5.45 MHz.
- **The RF compensation** does what the players' switched shelves and the Pioneer trap-stage tilt
  do. It is continuous with radius rather than two-state.
- **The inverse-MTF boost** has a fixed hardware counterpart in the PR-7820's +6 dB video
  peaking. The later players have no video-domain boost.
- **Group delay**: the players' filters roughly cancel the disc's pre-distortion by accident of
  their own delay; ld-decode subtracts its low-pass's delay and equalises to the IEC curve.

## Simulation scripts

The simulations are kept in `scripts/player_chains/`, one script per player (or pair of players
sharing a circuit) plus `ldd_chain.py`, which splits ld-decode's own chain into its factors
through `RFDecode.demodblock`. The README there lists them. Each prints its tables to stdout and
needs numpy and scipy only; component values, source and load assumptions are in the code
beside each stage.

## Open questions

- The original PR-8210 and early LD-1100 VSOP boards (VWS-020 + VWV-015) are unread.
- No datasheet exists online for the UA5001/UA5002, PAC005B or the internals of the LA7134M and
  AN2661NK.
- The LDP-1500P's 4.09 MHz notch in a PAL path is unexplained.
- Not yet read: CLD-2710K, Sony MDP-450/650D, Philips LDP 600 WS (all on archive.org), and any
  LD-V4300D, LD-V8000 or CLD-V2800 service manual (not found).
