# VITS conformance baseline across disc radius

The modulation transfer function of a LaserDisc changes with radius, so a decoder can pass every
conformance check at one radius and fail at another. This is the measured baseline that says which
of the decoder allowances in [`analysis/vits_reference.py`](../../analysis/vits_reference.py) hold
across a whole side and which do not. It is the evidence base those allowances cite, and it is
Phase 6 task 6 of the VITS conformance testing plan.

Nothing here is a proposal to widen anything. Where an allowance is exceeded, the excess is a fault
to be explained — AGENTS.md § 15 — and the ones this baseline surfaces are listed at the end as
Phase 8 work.

## Method

Twelve cuts, four discs at three radii each, taken at 5 %, 50 % and 95 % of each disc's *recorded
band* — that is, past the measured spin-up offset between the start of the capture and disc frame 1.
The cuts are 30 frames (PAL) or 20 frames (NTSC), sized so a decode yields at least ten same-parity
fields, which is what the coherent averaging in the conformance runner wants; the smallest yields
19.

Each cut was decoded serially (`-t 1`) from frame 0 and judged with
[`analysis/vits_conformance.py`](../../analysis/vits_conformance.py) at **one field per parity**,
not its default four-field coherent average — see "The averaging defect this baseline had to work
around" below. Checks are grouped by the `allowance_kind` each one carries, so a row is one entry of
`DECODER_ALLOWANCES` and the worst reading it had to hold at each radius.

## The samples

| Sample | System | Radius | Source file frames | Size | Decoded fields | VITS |
|---|---|---|---|---|---|---|
| `ggv1011-side1-inner` | PAL | inner (5 %) | 1429–1458 | 30.3 MB | 60 (30 per parity) | blanked1, blanked2, its1, its2, mb1, mb2 |
| `ggv1011-side1-middle` | PAL | middle (50 %) | 12236–12265 | 32.3 MB | 54 (27 per parity) | blanked1, blanked2, its1, its2, mb1, mb2 |
| `ggv1011-side1-outer` | PAL | outer (95 %) | 23042–23071 | 33.1 MB | 58 (29 per parity) | blanked1, blanked2, its1, its2, mb1, mb2 |
| `domesday-ds1-community-north-inner` | PAL | inner (5 %) | 3045–3074 | 25.7 MB | 58 (29 per parity) | blanked1, blanked2, its1, its2, mb1, mb2 |
| `domesday-ds1-community-north-middle` | PAL | middle (50 %) | 27351–27380 | 36.2 MB | 46 (23 per parity) | blanked1, blanked2, its1, its2, mb1, mb2 |
| `domesday-ds1-community-north-outer` | PAL | outer (95 %) | 51657–51686 | 38.3 MB | 60 (30 per parity) | blanked1, blanked2, its1, its2, mb1, mb2 |
| `ggv1069-side1-inner` | NTSC | inner (5 %) | 1545–1564 | 17.5 MB | 38 (19 per parity) | fcc-multiburst, ntc7-combination, ntc7-composite, virs1, virs2 |
| `ggv1069-side1-middle` | NTSC | middle (50 %) | 12888–12907 | 17.8 MB | 40 (20 per parity) | ntc7-combination, ntc7-composite, virs1, virs2 |
| `ggv1069-side1-outer` | NTSC | outer (95 %) | 24231–24250 | 18.9 MB | 38 (19 per parity) | ntc7-combination, ntc7-composite, virs1, virs2 |
| `dolby-surround-side1-inner` | NTSC | inner (5 %) | 2804–2823 | 16.4 MB | 40 (20 per parity) | ntc7-combination, ntc7-composite, virs1, virs2 |
| `dolby-surround-side1-middle` | NTSC | middle (50 %) | 23959–23978 | 20.9 MB | 38 (19 per parity) | ntc7-combination, ntc7-composite, virs1, virs2 |
| `dolby-surround-side1-outer` | NTSC | outer (95 %) | 45114–45133 | 23.2 MB | 40 (20 per parity) | ntc7-combination, ntc7-composite, virs1, virs2 |

## The samples

| Sample | System | Radius | Source file frames | Size | Decoded fields | VITS |
|---|---|---|---|---|---|---|
| `ggv1011-side1-inner` | PAL | inner (5 %) | 1429–1458 | 30.3 MB | 60 (30 per parity) | blanked1, blanked2, its1, its2, mb1, mb2 |
| `ggv1011-side1-middle` | PAL | middle (50 %) | 12236–12265 | 32.3 MB | 54 (27 per parity) | blanked1, blanked2, its1, its2, mb1, mb2 |
| `ggv1011-side1-outer` | PAL | outer (95 %) | 23042–23071 | 33.1 MB | 58 (29 per parity) | blanked1, blanked2, its1, its2, mb1, mb2 |
| `domesday-ds1-community-north-inner` | PAL | inner (5 %) | 3045–3074 | 25.7 MB | 58 (29 per parity) | blanked1, blanked2, its1, its2, mb1, mb2 |
| `domesday-ds1-community-north-middle` | PAL | middle (50 %) | 27351–27380 | 36.2 MB | 46 (23 per parity) | blanked1, blanked2, its1, its2, mb1, mb2 |
| `domesday-ds1-community-north-outer` | PAL | outer (95 %) | 51657–51686 | 38.3 MB | 60 (30 per parity) | blanked1, blanked2, its1, its2, mb1, mb2 |
| `ggv1069-side1-inner` | NTSC | inner (5 %) | 1545–1564 | 17.5 MB | 38 (19 per parity) | fcc-multiburst, ntc7-combination, ntc7-composite, virs1, virs2 |
| `ggv1069-side1-middle` | NTSC | middle (50 %) | 12888–12907 | 17.8 MB | 40 (20 per parity) | ntc7-combination, ntc7-composite, virs1, virs2 |
| `ggv1069-side1-outer` | NTSC | outer (95 %) | 24231–24250 | 18.9 MB | 38 (19 per parity) | ntc7-combination, ntc7-composite, virs1, virs2 |
| `dolby-surround-side1-inner` | NTSC | inner (5 %) | 2804–2823 | 16.4 MB | 40 (20 per parity) | ntc7-combination, ntc7-composite, virs1, virs2 |
| `dolby-surround-side1-middle` | NTSC | middle (50 %) | 23959–23978 | 20.9 MB | 38 (19 per parity) | ntc7-combination, ntc7-composite, virs1, virs2 |
| `dolby-surround-side1-outer` | NTSC | outer (95 %) | 45114–45133 | 23.2 MB | 40 (20 per parity) | ntc7-combination, ntc7-composite, virs1, virs2 |

## What each allowance had to hold

One row per allowance per system, giving the worst any check judged against it read at each radius,
over both discs of that system. The figure in brackets is how much of what the check was allowed it
used, so it is comparable across units: `1.00×` sits exactly on the limit and anything above it is a
failure. A blank cell means nothing of that kind was judged at that radius.

| Allowance | System | Unit | Worst inner | Worst middle | Worst outer | Worst check |
|---|---|---|---|---|---|---|
| `blanking_level` | PAL | IRE | +1.175 (1.18×) | +1.080 (1.08×) | +1.041 (1.04×) | `pal-blanked-field2/blanked` (ggv1011-side1) |
| `chroma_level` | NTSC | IRE | -4.796 (1.20×) | +5.332 (1.07×) | +2.731 (0.91×) | `ntsc-fcc-multiburst/packet_6` (ggv1069-side1) |
| `chroma_level` | PAL | IRE | -22.273 (5.18×) | -18.285 (4.25×) | -23.569 (5.48×) | `pal-multiburst-field1/packet_6` (ggv1011-side1) |
| `chroma_nonlinearity` | NTSC | fraction | +0.061 (0.61×) | +0.035 (0.35×) | +0.011 (0.11×) | `ntsc-ntc7-combination/chroma_nonlinearity` (ggv1069-side1) |
| `chroma_nonlinearity` | PAL | fraction | +0.054 (0.54×) | +0.078 (0.78×) | +0.113 (1.13×) | `pal-multiburst-field2/chroma_nonlinearity` (domesday-ds1-community-north) |
| `differential_gain` | NTSC | fraction | +0.163 (1.63×) | +0.154 (1.54×) | +0.122 (1.22×) | `ntsc-ntc7-composite/chroma_reference/differential_gain` (dolby-surround-side1) |
| `differential_gain` | PAL | fraction | +0.316 (3.01×) | +0.105 (1.00×) | +0.145 (1.38×) | `pal-its-field2/staircase_subcarrier/differential_gain` (domesday-ds1-community-north) |
| `differential_phase` | NTSC | degrees | +9.919 (1.98×) | +2.911 (0.58×) | +5.651 (1.13×) | `ntsc-ntc7-composite/chroma_reference/differential_phase` (ggv1069-side1) |
| `differential_phase` | PAL | degrees | +9.183 (1.77×) | +4.796 (0.92×) | +10.540 (2.03×) | `pal-its-field2/staircase_subcarrier/differential_phase` (domesday-ds1-community-north) |
| `level_ceiling` | NTSC | IRE/percent | +103.496 (0.93×) | +102.143 (0.92×) | +103.771 (0.93×) | `ntsc-ntc7-composite/ceiling/luminance` (ggv1069-side1) |
| `level_ceiling` | PAL | IRE/percent | +126.064 (1.25×) | +114.563 (1.13×) | +114.501 (1.13×) | `pal-multiburst-field2/ceiling/saturation` (ggv1011-side1) |
| `luma_chroma_ratio` | NTSC | ratio | +0.012 (1.23×) | +0.016 (1.55×) | +0.021 (2.09×) | `gain_ratio/NTSC` (ggv1069-side1) |
| `luma_chroma_ratio` | PAL | ratio | +0.127 (5.91×) | +0.056 (2.59×) | +0.046 (2.14×) | `gain_ratio/PAL` (domesday-ds1-community-north) |
| `luma_level` | NTSC | IRE | -3.916 (1.96×) | -9.617 (4.81×) | -7.062 (3.53×) | `ntsc-ntc7-composite/pulse_2t` (dolby-surround-side1) |
| `luma_level` | PAL | IRE | -9.388 (3.76×) | -14.566 (5.83×) | -15.476 (6.19×) | `pal-its-field2/pulse_2t` (domesday-ds1-community-north) |
| `multiburst_flatness` | NTSC | dB | +0.248 (0.33×) | — | — | `ntsc-fcc-multiburst/packet_3/response` (ggv1069-side1) |
| `multiburst_flatness` | PAL | dB | +0.333 (0.44×) | +0.470 (0.63×) | +0.307 (0.41×) | `pal-multiburst-field1/packet_3/response` (domesday-ds1-community-north) |
| `multiburst_frequency` | NTSC | MHz | +0.017 (0.66×) | -0.019 (0.38×) | -0.011 (0.22×) | `ntsc-fcc-multiburst/packet_3/frequency` (ggv1069-side1) |
| `multiburst_frequency` | PAL | MHz | +0.090 (0.66×) | +0.097 (0.71×) | +0.088 (0.65×) | `pal-multiburst-field1/packet_6/frequency` (domesday-ds1-community-north) |
| `step_inequality` | NTSC | fraction | +0.057 (0.57×) | +0.069 (0.69×) | +0.069 (0.69×) | `ntsc-ntc7-composite/staircase/nonlinearity` (dolby-surround-side1) |
| `step_inequality` | PAL | fraction | +0.066 (0.63×) | +0.037 (0.35×) | +0.031 (0.29×) | `pal-its-field1/staircase/nonlinearity` (domesday-ds1-community-north) |

## What the baseline says

**Three allowances hold across a whole side, on discs they were not derived from.**

| Allowance | Worst of 12 cuts | Allowed |
|---|---|---|
| `multiburst_flatness` | 0.63× | 0.75 dB |
| `multiburst_frequency` | 0.71× | 0.020–0.051 MHz |
| `step_inequality` | 0.69× | 0.100 |

`multiburst_flatness` is the important one. Phase 5 set it from the video EQ servo's own dead-band
plus the largest residual [`vits-servos.md`](vits-servos.md) records it leaving, and modelled one
envelope across radius rather than a table per radius on the argument that removing radius
dependence is what the servo is *for* — the Louvre fr2000→6000 row. Over four discs and three radii
the worst reading uses 63 % of it. The argument holds.

**The clearest radius-dependent failure is the 2T pulse, and it is on both systems.** Of the
twenty-five luminance elements measured, the three 2T pulses are the worst by a factor of four:

| Element | Worst | System |
|---|---|---|
| `pal-its-field2/pulse_2t` | 6.19× (−15.5 IRE) | PAL |
| `pal-its-field1/pulse_2t` | 5.51× (−13.8 IRE) | PAL |
| `ntsc-ntc7-composite/pulse_2t` | 4.81× (−9.6 IRE) | NTSC |
| *next worst of any kind* | 1.09× | PAL white reference bar |

and it worsens outwards: on Domesday `pal-its-field2/pulse_2t` reads 3.76×, 5.83× and 6.19× at
inner, middle and outer radius. Every bar and staircase on the same lines stays inside its band at
every radius, bar the GGV1011 white reference at 1.09×. A 2T pulse is the highest-frequency
luminance element there is, and it sits above the band the video EQ servo anchors (0.7–3.6 MHz on
PAL, 0.7–2.8 MHz on NTSC), where the EQ is pinned to 0 dB. This is the modulation transfer function
of the disc arriving uncorrected, and it is exactly what a single-radius suite could not have
seen.

**`luma_chroma_ratio` fails on NTSC at every radius, worsening outwards** — 1.23×, 1.55×, 2.09×.
Phase 4 measured it on the NTSC CI capture alone, where it passed. It is the second finding here
that only a radius sweep could produce.

**`chroma_level` on PAL fails on seven elements of eleven, and every one of them reads high
except the band edge.** This is the PAL chrominance error Phase 4 already records; what the sweep
adds is that it is not radius dependent — the worst reading for each element is at the inner radius
for five of the seven — and that it is ordered by frequency:

| Element | Worst | Frequency |
|---|---|---|
| `pal-multiburst-field1/packet_6` | 5.48× (−23.6 IRE) | 5.8 MHz |
| `pal-multiburst-field2/chroma_reference` | 2.79× (+12.6 IRE) | 4.43 MHz |
| `pal-multiburst-field1/packet_5` | 2.13× (+9.2 IRE) | 4.8 MHz |
| `pal-multiburst-field2/chroma_bar_100` | 2.00× (+13.0 IRE) | 4.43 MHz |
| `pal-multiburst-field1/packet_4` | 1.81× (+7.8 IRE) | 4.2 MHz |
| `pal-multiburst-field2/chroma_bar_60` | 1.79× (+8.0 IRE) | 4.43 MHz |
| `pal-its-field2/staircase_subcarrier` | 1.54× (+6.2 IRE) | 4.43 MHz |

The four that stay inside their bands — multiburst packets 1 to 3 at 0.5 to 2 MHz, worst 0.59×, and
the 20 % chrominance bar at 0.80× — are the low-frequency and low-amplitude ones. Everything at or
above 4.2 MHz reads high, and the 5.8 MHz packet alone reads low, which is the band-edge roll-off
Phase 5 records.

## The averaging defect this baseline had to work around

**These figures are taken from one field per parity, not the conformance runner's default four,
because coherent averaging cancels PAL chrominance.** On the Domesday middle cut, four second
fields sharing one `fieldPhaseID` each read the chrominance reference at 9.4–10.9 / 30.7–33.2 /
50.0–53.8 IRE; their average reads 2.7 / 7.8 / 12.9 IRE, a factor of four down. The same run on
NTSC is unaffected — GGV1069's chroma zones read 11.2 / 21.9 / 45.3 IRE from one field and
10.5 / 21.5 / 44.0 IRE from four, which is the noise reduction the averaging is for.

`vits_measure.average_fields` groups by `fieldPhaseID` precisely to avoid this, and on NTSC that
works. On PAL it does not, and the reason is not one a different grouping can fix. Measuring the
subcarrier phase against the field's own sample lattice, in the same fields:

| Field | `fieldPhaseID` | Phase at 6.8 µs (burst) | Phase at 24 µs (chroma bar) |
|---|---|---|---|
| 1 | 2 | +1.09° | +129.6° |
| 9 | 2 | +1.96° | +267.8° |
| 17 | 2 | +0.05° | +28.7° |

The burst agrees to a degree; the bar 18 µs later does not, and the disagreement is different at
the two offsets. The fields differ in subcarrier *frequency* across the line, not merely in phase,
so no per-field grouping or rotation can align them — sample-wise averaging of PAL chrominance
across fields is not a thing that can be made to work as it stands.

Why this was never seen: the PAL CI capture decodes to six fields, and grouping those by
`fieldPhaseID` leaves one field per group, so every PAL number this project has published was
already taken from a single field. A radius cut decodes to 46–60 fields, which is the first time the
averaging path has had anything to average.

Phase 5's NTC-7 restriction — amplitude conformance only against a combination coherently averaged
over at least ten same-parity fields — is unaffected, because it is NTSC only and NTSC averaging is
verified working above.

## What this baseline sends to Phase 8

| Allowance | System | Worst | Where | Reading |
|---|---|---|---|---|
| — | PAL | 4× under-read | Any chrominance measured through `average_fields` | The averaging defect above; the runner's default `--average 4` reports PAL chrominance wrongly on any capture with enough fields to group |
| `luma_level` | PAL, NTSC | 6.19×, 4.81× | `pulse_2t`, worsening outwards | High-frequency luminance above the EQ's anchor band |
| `luma_chroma_ratio` | NTSC, PAL | 2.09×, 5.91× | Every radius of every disc | Fails on NTSC too, which Phase 4 did not see |
| `chroma_level` | PAL | 5.48× | 5.8 MHz multiburst packet | The band-edge roll-off Phase 5 records |
| `differential_gain` | PAL, NTSC | 3.01×, 1.63× | Worst at inner radius on both | Real on PAL, marginal on NTSC |
| `differential_phase` | PAL, NTSC | 2.03×, 1.98× | Inner and outer, not middle | Not monotonic in radius, so not an MTF effect |
| `level_ceiling` | PAL | 1.25× | GGV1011 saturation, worst at inner | The GGV over-saturation Phase 4 found |
| `blanking_level` | PAL | 1.18× | GGV1011, all radii | The pedestal offset Phase 4 found, confirmed across the side |
| `chroma_nonlinearity` | PAL | 1.13× | Domesday outer only | Marginal, and only at one radius |

None of these is a reason to widen an allowance. Every one of them is a measurement that has to be
explained (AGENTS.md § 15).
