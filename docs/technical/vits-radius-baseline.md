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

`testdata/radius/` holds a thirteenth cut, `domesday-ds1-community-north-outer`. It is a regression
sample for the inverse-MTF's chroma-band ceiling rather than part of the sweep, so it is excluded
from every table here; where it is quoted for comparison it is named.

Twelve cuts, four discs at three radii each, taken at 5 %, 50 % and 95 % of each disc's *recorded
band* — that is, past the measured spin-up offset between the start of the capture and disc frame 1.
The cuts are 30 frames (PAL) or 20 frames (NTSC), sized so a decode yields at least ten same-parity
fields, which is what the coherent averaging in the conformance runner wants; the smallest yields
19.

Each cut was decoded serially (`-t 1`) from frame 0 and judged with
[`analysis/vits_conformance.py`](../../analysis/vits_conformance.py) at its **gated default** —
four fields coherently averaged per parity, falling back to a single field wherever the coherence
gate refuses the group. The first edition of this baseline ran at one field per parity because
that gate did not yet exist; see "What the coherence gate changed" below for what the two readings
differ by and why the averaged one is the better measurement. Checks are grouped by the
`allowance_kind` each one carries, so a row is one entry of `DECODER_ALLOWANCES` and the worst
reading it had to hold at each radius.

## The samples

| Sample | System | Radius | Source file frames | Size | Decoded fields | VITS |
|---|---|---|---|---|---|---|
| `ggv1011-side1-inner` | PAL | inner (5 %) | 1429–1458 | 30.3 MB | 60 (30 per parity) | blanked1, blanked2, its1, its2, mb1, mb2 |
| `ggv1011-side1-middle` | PAL | middle (50 %) | 12236–12265 | 32.3 MB | 54 (27 per parity) | blanked1, blanked2, its1, its2, mb1, mb2 |
| `ggv1011-side1-outer` | PAL | outer (95 %) | 23042–23071 | 33.1 MB | 58 (29 per parity) | blanked1, blanked2, its1, its2, mb1, mb2 |
| `domesday-ds2-community-north-inner` | PAL | inner (5 %) | 3036–3065 | 25.6 MB | 50 (25 per parity) | blanked1, blanked2, its1, its2, mb1, mb2 |
| `domesday-ds2-community-north-middle` | PAL | middle (50 %) | 27336–27365 | 36.1 MB | 58 (29 per parity) | blanked1, blanked2, its1, its2, mb1, mb2 |
| `domesday-ds2-community-north-outer` | PAL | outer (95 %) | 51636–51665 | 38.3 MB | 58 (29 per parity) | blanked1, blanked2, its1, its2, mb1, mb2 |
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
| `blanking_level` | PAL | IRE | +1.066 (1.07×) | +1.097 (1.10×) | +1.122 (1.12×) | `pal-blanked-field1/blanked` (ggv1011-side1) |
| `chroma_level` | NTSC | IRE | -4.455 (1.11×) | +4.044 (0.81×) | +2.259 (0.75×) | `ntsc-fcc-multiburst/packet_6` (ggv1069-side1) |
| `chroma_level` | PAL | IRE | -18.790 (4.37×) | -19.305 (4.49×) | -18.469 (4.30×) | `pal-multiburst-field1/packet_6` (ggv1011-side1) |
| `chroma_nonlinearity` | NTSC | fraction | +0.046 (0.46×) | +0.024 (0.24×) | +0.018 (0.18×) | `ntsc-ntc7-combination/chroma_nonlinearity` (dolby-surround-side1) |
| `chroma_nonlinearity` | PAL | fraction | +0.049 (0.49×) | +0.111 (1.11×) | +0.049 (0.49×) | `pal-multiburst-field2/chroma_nonlinearity` (domesday-ds2-community-north) |
| `differential_gain` | NTSC | fraction | +0.108 (1.08×) | +0.106 (1.06×) | +0.098 (0.98×) | `ntsc-ntc7-composite/chroma_reference/differential_gain` (dolby-surround-side1) |
| `differential_gain` | PAL | fraction | +0.339 (3.23×) | +0.165 (1.57×) | +0.155 (1.47×) | `pal-its-field2/staircase_subcarrier/differential_gain` (domesday-ds2-community-north) |
| `differential_phase` | NTSC | degrees | +6.044 (1.21×) | +1.990 (0.40×) | +3.012 (0.60×) | `ntsc-ntc7-composite/chroma_reference/differential_phase` (ggv1069-side1) |
| `differential_phase` | PAL | degrees | +5.517 (1.06×) | +3.673 (0.71×) | +11.562 (2.22×) | `pal-its-field2/staircase_subcarrier/differential_phase` (domesday-ds2-community-north) |
| `level_ceiling` | NTSC | IRE/percent | +105.499 (0.95×) | +103.046 (0.93×) | +103.284 (0.93×) | `ntsc-ntc7-composite/ceiling/luminance` (ggv1069-side1) |
| `level_ceiling` | PAL | IRE/percent | +123.855 (1.23×) | +94.570 (0.94×) | +96.938 (0.96×) | `pal-multiburst-field2/ceiling/saturation` (domesday-ds2-community-north) |
| `luma_chroma_ratio` | NTSC | ratio | +0.014 (1.43×) | +0.018 (1.75×) | +0.018 (1.80×) | `gain_ratio/NTSC` (ggv1069-side1) |
| `luma_chroma_ratio` | PAL | ratio | +0.117 (5.42×) | -0.025 (1.18×) | -0.037 (1.74×) | `gain_ratio/PAL` (domesday-ds2-community-north) |
| `luma_level` | NTSC | IRE | +5.499 (2.75×) | -7.846 (3.92×) | -8.370 (4.18×) | `ntsc-ntc7-composite/pulse_2t` (dolby-surround-side1) |
| `luma_level` | PAL | IRE | +5.687 (2.27×) | -15.031 (6.01×) | -11.177 (4.47×) | `pal-its-field1/pulse_2t` (domesday-ds2-community-north) |
| `multiburst_flatness` | NTSC | dB | +0.346 (0.46×) | — | — | `ntsc-fcc-multiburst/packet_3/response` (ggv1069-side1) |
| `multiburst_flatness` | PAL | dB | -0.144 (0.19×) | +0.170 (0.23×) | +0.643 (0.86×) | `pal-multiburst-field1/packet_3/response` (domesday-ds2-community-north) |
| `multiburst_frequency` | NTSC | MHz | +0.013 (0.52×) | +0.010 (0.20×) | +0.011 (0.23×) | `ntsc-fcc-multiburst/packet_3/frequency` (ggv1069-side1) |
| `multiburst_frequency` | PAL | MHz | +0.074 (0.55×) | +0.103 (0.76×) | +0.102 (0.75×) | `pal-multiburst-field1/packet_6/frequency` (domesday-ds2-community-north) |
| `multiburst_out_of_band_response` | NTSC | dB | +0.901 (0.72×) | — | — | `ntsc-fcc-multiburst/packet_5/response` (ggv1069-side1) |
| `multiburst_out_of_band_response` | PAL | dB | -7.764 (6.21×) | -8.315 (6.65×) | -7.838 (6.27×) | `pal-multiburst-field1/packet_6/response` (ggv1011-side1) |
| `step_inequality` | NTSC | fraction | +0.070 (0.70×) | +0.072 (0.72×) | +0.066 (0.66×) | `ntsc-ntc7-composite/staircase/nonlinearity` (dolby-surround-side1) |
| `step_inequality` | PAL | fraction | +0.046 (0.44×) | +0.027 (0.26×) | +0.030 (0.28×) | `pal-its-field2/staircase/nonlinearity` (domesday-ds2-community-north) |

Two rows read from one cut only. `ntsc-fcc-multiburst` is the sole NTSC train whose amplitudes are
admissible at this field count — the NTC-7 combination's are not, by the restriction Phase 5 set —
and only `ggv1069-side1-inner` carries it. The six readings behind those NTSC rows are three field
lines × two parities of that one cut, not six cuts, so `multiburst_flatness` and
`multiburst_out_of_band_response` on NTSC say nothing about radius. Every other row is twelve cuts.

## What the baseline says

**Three allowances hold across a whole side, on discs they were not derived from.**

| Allowance | Worst of 12 cuts | Allowed |
|---|---|---|
| `multiburst_flatness` | 0.86× | 0.75 dB |
| `multiburst_frequency` | 0.75× | 0.020–0.051 MHz |
| `step_inequality` | 0.72× | 0.100 |

`multiburst_flatness` is the important one. Phase 5 set it from the video EQ servo's own dead-band
plus the largest residual [`vits-servos.md`](vits-servos.md) records it leaving, and modelled one
envelope across radius rather than a table per radius on the argument that removing radius
dependence is what the servo is *for* — the Louvre fr2000→6000 row. Over four discs and three radii
the worst reading uses 86 % of it. The argument holds, with less room than the first edition
reported: 0.86× against 0.63×, the difference being the disc, not the decoder.

`multiburst_out_of_band_response` holds on NTSC (0.72×) and fails on PAL at every radius. It is new
since the first edition, which had no allowance covering those frequencies at all; see "The band no
allowance covered" below.

**The clearest radius-dependent failure is still the 2T pulse, and it is still on both systems.**
Of the twenty-five luminance elements measured, the three 2T pulses are the worst by more than a
factor of two:

| Element | Worst | System |
|---|---|---|
| `pal-its-field1/pulse_2t` | 6.01× (−15.0 IRE) | PAL |
| `pal-its-field2/pulse_2t` | 4.47× (−11.2 IRE) | PAL |
| `ntsc-ntc7-composite/pulse_2t` | 4.18× (−8.4 IRE) | NTSC |
| *next worst of any kind* | 1.78× | PAL 20T luminance |

but it no longer worsens monotonically outwards, and it has separated by disc. On the twelve cuts
the pulse now passes 5 of 12 — **5 of 6 on GGV1011 and 0 of 6 on Domesday**. GGV1011, a calibration
disc carrying a designed ITS, reads within 0.9 IRE of its own bar at five of six cuts; Domesday
misses its own bar at all six, by 2.9 to 15.0 IRE low on five of them and 5.7 IRE high on the
sixth. On the same cuts decoded by the same tree, DD86-DS1 passes 3 of 6, so the difference is
between the two pressings and not between the decoder and itself.

The 2T servo is not idle while that happens. On Domesday middle it drives `mtf_level` from 0.000
down to −0.744 — the direction that *raises* demodulated HF — and lifting its 100-field adoption
rate limit (a 30-frame cut is about 60 fields, so it normally adopts once) lets it continue to the
−1.000 clip floor. That second adoption lands after the fields the conformance check averages, so
the measured pulse is unchanged either way; what the probe does establish is that the loop is
already asking for the correction in the right direction and is not being held back by its own
convergence time inside a cut.

**`luma_chroma_ratio` fails on NTSC at every radius** — 1.43×, 1.75×, 1.80×. Phase 4 measured it on
the NTSC CI capture alone, where it passed. It is the second finding here that only a radius sweep
could produce. It no longer worsens monotonically outwards (2.09× at outer in the first edition
against 1.80× now).

**`chroma_level` on PAL fails on seven elements of eleven, and every one of them reads high except
the band edge.** This is the PAL chrominance error Phase 4 already records; what the sweep adds is
that it is not radius dependent — six of the seven have their worst reading at the inner radius —
and that it is ordered by frequency:

| Element | Worst | Frequency |
|---|---|---|
| `pal-multiburst-field1/packet_6` | 4.49× (−19.3 IRE) | 5.8/5.9 MHz |
| `pal-multiburst-field1/packet_5` | 3.07× (+13.2 IRE) | 4.8 MHz |
| `pal-multiburst-field2/chroma_reference` | 2.68× (+12.0 IRE) | 4.43 MHz |
| `pal-multiburst-field1/packet_4` | 2.58× (+11.1 IRE) | 4.0 MHz |
| `pal-multiburst-field2/chroma_bar_60` | 2.02× (+9.1 IRE) | 4.43 MHz |
| `pal-multiburst-field2/chroma_bar_100` | 1.83× (+11.9 IRE) | 4.43 MHz |
| `pal-its-field2/staircase_subcarrier` | 1.29× (+5.2 IRE) | 4.43 MHz |

The four that stay inside their bands — multiburst packets 1 to 3 at 0.5 to 2 MHz, worst 0.76×, and
the 20 % chrominance bar at 0.98× — are the low-frequency and low-amplitude ones. Everything at or
above 4.0 MHz reads high, and the 5.8 MHz packet alone reads low, which is the band-edge roll-off
Phase 5 records. Six of the seven failing elements have their worst reading on
`domesday-ds2-community-north-inner`, which is also the cut that carries the largest out-of-band
peak; the two are the same fault seen through two different signals.

## What moved since the first edition

The first edition of this table was measured on a different decoder, a different Domesday pressing
and a different averaging rule. All three moved together, so a row's movement is not attributable
to any one of them without the separations below. Direction is old → new, on the worst reading at
each radius:

| Allowance | System | inner | middle | outer | crosses 1.00× |
|---|---|---|---|---|---|
| `blanking_level` | PAL | 1.18 ↓ 1.07 | 1.08 ↑ 1.10 | 1.04 ↑ 1.12 | no |
| `chroma_level` | NTSC | 1.20 ↓ 1.11 | 1.07 ↓ 0.81 | 0.91 ↓ 0.75 | middle, below |
| `chroma_level` | PAL | 5.18 ↓ 4.37 | 4.25 ↑ 4.49 | 5.48 ↓ 4.30 | no |
| `chroma_nonlinearity` | NTSC | 0.61 ↓ 0.46 | 0.35 ↓ 0.24 | 0.11 ↑ 0.18 | no |
| `chroma_nonlinearity` | PAL | 0.54 ↓ 0.49 | 0.78 ↑ 1.11 | 1.13 ↓ 0.49 | **middle, above**; outer, below |
| `differential_gain` | NTSC | 1.63 ↓ 1.08 | 1.54 ↓ 1.06 | 1.22 ↓ 0.98 | outer, below |
| `differential_gain` | PAL | 3.01 ↑ 3.23 | 1.00 ↑ 1.57 | 1.38 ↑ 1.47 | **middle, above** |
| `differential_phase` | NTSC | 1.98 ↓ 1.21 | 0.58 ↓ 0.40 | 1.13 ↓ 0.60 | outer, below |
| `differential_phase` | PAL | 1.77 ↓ 1.06 | 0.92 ↓ 0.71 | 2.03 ↑ 2.22 | no |
| `level_ceiling` | NTSC | 0.93 ↑ 0.95 | 0.92 ↑ 0.93 | 0.93 = 0.93 | no |
| `level_ceiling` | PAL | 1.25 ↓ 1.23 | 1.13 ↓ 0.94 | 1.13 ↓ 0.96 | middle and outer, below |
| `luma_chroma_ratio` | NTSC | 1.23 ↑ 1.43 | 1.55 ↑ 1.75 | 2.09 ↓ 1.80 | no |
| `luma_chroma_ratio` | PAL | 5.91 ↓ 5.42 | 2.59 ↓ 1.18 | 2.14 ↓ 1.74 | no |
| `luma_level` | NTSC | 1.96 ↑ 2.75 | 4.81 ↓ 3.92 | 3.53 ↑ 4.18 | no |
| `luma_level` | PAL | 3.76 ↓ 2.27 | 5.83 ↑ 6.01 | 6.19 ↓ 4.47 | no |
| `multiburst_flatness` | NTSC | 0.33 ↑ 0.46 | — | — | no |
| `multiburst_flatness` | PAL | 0.44 ↓ 0.19 | 0.63 ↓ 0.23 | 0.41 ↑ 0.86 | no |
| `multiburst_frequency` | NTSC | 0.66 ↓ 0.52 | 0.38 ↓ 0.20 | 0.22 ↑ 0.23 | no |
| `multiburst_frequency` | PAL | 0.66 ↓ 0.55 | 0.71 ↑ 0.76 | 0.65 ↑ 0.75 | no |
| `step_inequality` | NTSC | 0.57 ↑ 0.70 | 0.69 ↑ 0.72 | 0.69 ↓ 0.66 | no |
| `step_inequality` | PAL | 0.63 ↓ 0.44 | 0.35 ↓ 0.26 | 0.29 ↓ 0.28 | no |

`multiburst_out_of_band_response` has no old row to move from: the first edition judged nothing at
those frequencies. It now reads 6.21× / 6.65× / 6.27× on PAL and 0.72× on NTSC.

**Eight rows cross 1.00×, six of them downwards.** The two that cross upwards are
`chroma_nonlinearity` PAL middle (0.78 → 1.11) and `differential_gain` PAL middle (1.00 → 1.57),
and both are the pressing swap rather than the decoder. Both are worst on
`pal-multiburst-field2` / `pal-its-field2` — the Domesday **second** parity, the one the coherence
gate refuses, so both are single-field readings. Decoded by the same tree at the same setting, the
two pressings give:

| Row, Domesday second parity | DD86-DS1 | DD86-DS2 |
|---|---|---|
| `chroma_nonlinearity`, inner / middle / outer | 0.20× / 0.13× / **13.74×** | 0.49× / **1.11×** / 0.18× |
| `differential_gain`, inner / middle / outer | **4.31×** / 0.79× / **1.92×** | **3.23×** / **1.57×** / **1.47×** |

A row that swings from 0.13× to 13.74× between two pressings of the same title, at the same radius
band and on the same decoder, is not measuring the decoder. It is measuring one field of a parity
that cannot be averaged, and that is the price of the coherence gate: it stops the average
cancelling the chrominance, but what it falls back to carries four times the noise. Four of the
five PAL chrominance allowances that fail — `chroma_nonlinearity`, `differential_gain`,
`differential_phase` and `level_ceiling` — have their worst reading on this parity at every radius.
The exception is `chroma_level`, whose worst is GGV1011's top multiburst packet on the first
parity, and it is averaged normally.

## What the coherence gate changed

The first edition ran at one field per parity throughout, because the gate did not exist and a
four-field average silently cancelled Domesday's chrominance. Measuring the same twelve decodes
both ways separates the averaging from everything else:

| Allowance | System | inner | middle | outer |
|---|---|---|---|---|
| `multiburst_flatness` | PAL | 0.20 → 0.19 | 0.23 → 0.23 | **3.75 → 0.86** |
| `luma_level` | PAL | 4.04 → 2.27 | 7.70 → 6.01 | 4.47 → 4.47 |
| `luma_level` | NTSC | 1.96 → 2.75 | 4.81 → 3.92 | 3.53 → 4.18 |
| `differential_gain` | NTSC | 1.63 → 1.08 | 1.54 → 1.06 | 1.22 → 0.98 |
| `differential_phase` | NTSC | 1.98 → 1.21 | 0.58 → 0.40 | 1.13 → 0.60 |
| `chroma_level` | PAL | 4.17 → 4.37 | 4.16 → 4.49 | 4.06 → 4.30 |

Most rows move by well under the noise the averaging removes. The one that matters is
`multiburst_flatness` PAL outer: a single field of `domesday-ds2-community-north-outer` reads the
2 MHz packet +2.811 dB (3.75×, a failure), and the four-field average of the same fields reads it
+0.643 dB (0.86×). That is one packet amplitude's single-field noise, and it is larger than the
whole in-band allowance. The averaged reading is the measurement; the single-field one was a
limitation the first edition had to accept.

Two kinds of row barely move at all, for opposite reasons. `differential_gain` PAL is *identical*
in both columns (3.23× / 1.57× / 1.47×) because its worst reading is on the Domesday second parity,
where the gate refuses and the average never happens — the same single field is measured either
way. `chroma_level` PAL moves the other way, 4.17× → 4.37×, and that one is a genuine average: its
worst is GGV1011's 5.8 MHz packet on the first parity, and the noisier single-field reading
happened to sit slightly nearer nominal than the true value the average recovers.

## The averaging defect the gate exists for

**On one of these discs a coherent average cancelled chrominance**, which is why the first edition
of this baseline ran at one field per parity throughout. On the Domesday middle cut, four second
fields sharing one `fieldPhaseID` each read the chrominance reference at 9.4–10.9 / 30.7–33.2 /
50.0–53.8 IRE; their average read 2.7 / 7.8 / 12.9 IRE, a factor of four down.

It is **not** a PAL-wide fault, and the first statement of it in this document said it was. Measured
across all twelve cuts, the chrominance an average keeps of what its members carried is:

| Cut | First parity | Second parity |
|---|---|---|
| `ggv1011-side1` (PAL), all three radii | no chrominance on the VBI | 0.999–1.000 |
| `domesday-ds2-community-north` (PAL), all three radii | no chrominance on the VBI | **0.101–0.371** |
| `ggv1069-side1` (NTSC), all three radii | 1.000 | 1.000 |
| `dolby-surround-side1` (NTSC), all three radii | 1.000 | 0.999–1.000 |

One disc *family*, one parity — and not a damaged pressing. The three Domesday cuts were re-taken
from DD86-DS2, an undamaged copy of the same title, precisely to test that: it refuses exactly as
DS1 did, keeping 0.101–0.371 of its chrominance where DS1 kept 0.216–0.304. Whatever the BBC's AIV
mastering did to the subcarrier, it did to both pressings.

The cause is not the grouping and not the sample lattice. Following one
element down a line, each field's chrominance phase is *constant* — the same at 20, 40 and 50 µs
into the line — so the fields do not differ in subcarrier frequency across a line. They differ from
each other by a fixed rotation per field:

| Disc, second parity | Chrominance phase advance per frame | Closes on the 8-field sequence? |
|---|---|---|
| `ggv1011-side1` | 270.0° (σ 2.2°) | yes, exactly |
| `domesday-ds2-community-north` | 146° (σ 8–11°) | no |

270° per frame is four frames to the turn, which is the 8-field PAL sequence exactly, and grouping
by `fieldPhaseID` collects those fields correctly. Domesday's 146° closes on nothing: it is a
subcarrier offset of about 10 Hz between the recorded chrominance and the burst it is measured
against, so its second-parity fields walk steadily through phase no matter how they are grouped.
The colour burst does not show it — burst phase agrees to a degree within every group on both
discs — so the burst cannot be used to detect it either.

A `fieldPhaseID` states a position in the analogue colour sequence. That is a weaker claim than a
shared subcarrier phase, and on a disc like this one the two come apart.

**Fixed.** `vits_measure.average_fields()` now measures what an average kept of its members'
chrominance, over the VBI lines that may carry a VITS, and abandons the group for a single field
when the figure falls below `MIN_AVERAGE_COHERENCE` (0.85, set from the point at which cancellation
alone spends the whole of the tightest chrominance allowance). The threshold has wide clearance:
nothing measured on these twelve cuts lies between 0.35 and 0.999. A refusal is printed and carried
in the JSON context rather than showing only as a smaller field count. Only the three Domesday
second-parity cuts refuse; the other twenty-one parities keep their four-field average, and the
chrominance they report is the single-field reading to within the noise the averaging removes.

The search for whichever *subset* of a group does agree was deliberately not implemented: choosing
fields by the amplitude they report is selecting the answer, not measuring it.

The tables above are now taken at the gated default rather than at one field per parity; "What the
coherence gate changed" gives what the two readings differ by.

Why this was never seen: the PAL CI capture decodes to six fields, and grouping those by
`fieldPhaseID` leaves one field per group, so every PAL number this project has published was
already taken from a single field. A radius cut decodes to 46–60 fields, which is the first time the
averaging path has had anything to average.

Phase 5's NTC-7 restriction — amplitude conformance only against a combination coherently averaged
over at least ten same-parity fields — is unaffected, because it is NTSC only and NTSC averaging is
verified working above. Note that on a capture where the gate does refuse, that restriction will
now correctly decline to judge those amplitudes rather than judging a cancelled average.

## The band no allowance covered

The tables above judge one multiburst packet of six. The other five declined: one below the
0.7 MHz anchor floor, one as the reference the rest are read against, two inside a recorded
"uncorrected band" at 4–4.8 MHz, and one above the 3.6 MHz ceiling. NTSC judged one of six for the
same reasons. `multiburst_flatness` holding at 0.63× — as it did in the first edition of the table
above — therefore said nothing at all about the frequencies where the decoder was later found, by
eye, to be wrong.

The exclusion above the anchored band conflated two different claims — *the servo does not correct
here* and *the decoder may be arbitrarily wrong here*. Only the first is true. Every packet whose
amplitude can be read is now judged; what changes across the band is which allowance applies.

### Setting the out-of-band allowance

Out there the response is the static filter chain acting on whatever the disc recorded, so the
disc's own contribution is what has to be allowed for. The only estimate of it this project holds
is the agreement between unrelated pressings: where two discs cut on different equipment show the
same deviation at the same frequency and radius, that deviation is the decoder's. So the allowance
was built from what the pressings *disagree* by, never from what they share:

| Term | Measured | Where |
|---|---|---|
| within-capture repeatability | 0.293 dB | widest spread of one packet across the probes and both parities of a single capture (GGV1069 inner, 4.1 MHz) |
| pressing-to-pressing at one radius | 0.85 dB | widest gap between the two PAL pressings at the same radius band and the same published nominal (4.0 MHz, inner; against 0.20 at 0.5 MHz and 0.78 at 4.8 MHz) |
| **`OUT_OF_BAND_RESPONSE_DB`** | **1.25 dB** | sum, rounded up from 1.14 |

The top packet is excluded from the pressing term: the two discs carry different top nominals
(5.8 MHz IEC against 5.9), consistently 0.1 MHz apart at all three radii, and the response is steep
enough there that the gap would be measuring the frequency difference rather than the pressings.
The spread across *radii* is excluded on principle — the optical MTF loss that varies with radius
is what the inverse-MTF filter exists to correct, so forgiving it here would excuse the decoder
with its own uncorrected error.

**The first term re-measures unchanged and the second does not.** On the current decoder and
sample set the within-capture spread is still 0.293 dB, on the same packet of the same capture. The
pressing-to-pressing gap is now 3.71 dB at 4.0 MHz inner and 3.59 dB at 4.8 MHz, because the
inverse-MTF ceiling fix removed GGV1011's share of the 4–4.8 MHz peak and left Domesday's standing.
The two discs that used to agree there now disagree by more than the allowance itself:

| Nominal | Band | GGV1011 | DD86-DS1 | DD86-DS2 |
|---|---|---|---|---|
| 4.0 MHz | inner | −0.24 dB | +3.12 dB | +3.47 dB |
| 4.0 MHz | middle | +0.08 dB | −0.22 dB | +1.62 dB |
| 4.0 MHz | outer | +0.06 dB | +0.26 dB | +0.40 dB |
| 4.8 MHz | inner | +0.32 dB | +3.48 dB | +3.91 dB |
| 4.8 MHz | middle | +0.06 dB | −0.27 dB | +1.60 dB |
| 4.8 MHz | outer | +0.09 dB | −0.45 dB | +0.14 dB |

All three decoded by the same tree at the same setting. Only the DD86-DS1 outer cut is in the
sample set; its inner and middle are shown for comparison.

An earlier edition of this table read +0.98 / +1.47 dB for GGV1011 outer and +2.90 / +3.88 dB for
DD86-DS1 outer. Both were the inverse-MTF correction running above what the multiburst justifies,
and both went away when the chroma-band ceiling was given its own publication schedule — see
[`vits-servos.md`](vits-servos.md). GGV1011 is now inside ±0.32 dB across the whole band at every
radius, and so is DD86-DS1.

**The allowance is held at 1.25 dB rather than re-derived.** Re-deriving from 3.71 dB would put it
near 4 dB and forgive exactly the readings it exists to catch, which AGENTS.md § 15 forbids.
Deriving instead from the frequency where the pressings still agree — 0.52 dB at 0.5 MHz, the only
other out-of-band packet PAL carries — would give about 0.85 dB, but a 0.5 MHz packet says nothing
about the medium's spread at 4.8 MHz, where it is certainly larger. 1.25 dB lies between the two
and is the figure the earlier, less corrected decoder supported.

Two pressings cannot settle this. With one peaking and one flat there is no way to tell which is
the disc and which is the decoder, and the two Domesday pressings do not even agree with each other
away from the inner radius. What the derivation needs is a **third unrelated PAL pressing carrying
a Figure 8 multiburst**; until there is one, the allowance stands and the excess is a fault to
explain rather than a band to widen.

### What the twelve cuts then read

| System | Packet | Range | Cuts | Verdict |
|---|---|---|---|---|
| NTSC | 0.5 MHz | +0.58 … +0.64 dB | 1 | pass, 6 of 6 |
| NTSC | 3.0 MHz | +0.24 … +0.48 dB | 1 | pass, 6 of 6 |
| NTSC | 3.58 MHz | +0.66 … +0.90 dB | 1 | pass, 6 of 6 |
| NTSC | 4.1 MHz | −0.28 … +0.01 dB | 1 | pass, 6 of 6 |
| PAL | 0.5 MHz | −0.10 … +0.46 dB | 6 | pass, 6 of 6 |
| PAL | 4.0 MHz | −0.24 … +3.47 dB | 6 | **fail, 2 of 6** |
| PAL | 4.8 MHz | +0.06 … +3.91 dB | 6 | **fail, 2 of 6** |
| PAL | 5.8/5.9 MHz | −8.32 … −3.44 dB | 6 | **fail, 6 of 6** |

The NTSC rows are six readings — three field lines × two parities — of the single cut that carries
an admissible multiburst, so they say nothing about radius. The PAL rows are one reading from each
of six cuts.

No in-band verdict fails on either system. NTSC is clean across its whole train, which localises
the fault: it is PAL-specific and above the 3.6 MHz anchor ceiling.

**Both 4–4.8 MHz rows improved from 6 of 6 and 5 of 6 failing to 2 of 6.** The first edition of this
section attributed the peak to the decoder, because GGV1011 and DD86-DS1 both showed it and a
residual two unrelated pressings share is not one disc's mastering. Half of that reasoning has been
repaid: the shared component was the inverse-MTF running unbounded, and the ceiling fix removed it
from GGV1011. All four remaining failures are Domesday DD86-DS2 — 4.0 and 4.8 MHz at the inner and
middle radii — and GGV1011 is clean across the whole band at every radius. So is DD86-DS1, at the
one radius the sample set carries it. What is left does not track radius and differs by up to
3.5 dB between two pressings of the same title, which is what a disc-side property looks like; two
pressings cannot prove it.

The top packet did not improve and is treated separately below.

## The 2T pulse was judged against the wrong reference

The first edition of the table above made the PAL 2T pulse the worst
allowance in this document at 6.19x. Most of that was the comparison, not
the pulse.

IEC 60856-1986 Figure 7 states the 2T pulse "within +/-0.5 % of `B2`" — the
white reference bar beside it on the same line — and the 20T pulse and
staircase within +/-1 % of it. The check judged all three against an
absolute nominal instead. GGV1011's ITS line runs 2.3-2.6 IRE low at every
radius, and measured absolutely the 2T pulse inherited the whole of that
offset on top of whatever its own error was. The line's level is a real
fault, and it is caught: `white_reference_bar` fails on three of the six
GGV1011 cuts. It was simply being counted again at every element beside it.

`Element.relative_to` now carries the referent the standard names, and the
three Figure 7 elements use it. NTSC stays absolute — no NTSC source this
project holds states a tolerance about the bar, and the NTSC bars measure
within 1.6 IRE of nominal at every radius, so nothing material rides on it.

### What the changes did, separately

The 2T servo's setpoint moved in the same round of work
(`_mtf_servo_target()`; see [`vits-servos.md`](vits-servos.md)), so both
decodes were measured against both comparisons to keep them apart. This
table was taken on the sample set as it then stood — DD86-DS1, at one field
per parity — because an A/B needs both arms measured the same way, and the
old setpoint no longer exists to re-measure:

| PAL 2T pulse, 12 checks | absolute comparison | differential comparison |
|---|---|---|
| old setpoint | 8 pass / 4 fail | 5 pass / 7 fail |
| new setpoint | 6 pass / 6 fail | **8 pass / 4 fail** |

Read down the wrong column and the setpoint change looks like a regression
of two checks. Read down the right one it is an improvement of three, and
none of the twelve moves the other way. The absolute comparison was giving
the old setpoint credit for GGV1011's low line — an offset that happened to
cancel part of its error — and charging the new setpoint for removing it.

The setpoint change also shifted the order the servos adopt in, which
exposed two defects in the multiburst ceiling on the inverse-MTF: it was
applied only at a *following* burst adoption, and its evidence threshold did
not match the one the same pool was adopted on. Both are recorded in
[`vits-servos.md`](vits-servos.md). Whether a disc got a ceiling at all had
been decided by how many fields happened to be in hand.

With all three fixed, and measured against the differential comparison
throughout, those twelve cuts moved **25 checks from FAIL to PASS and none
the other way**; the PAL 2T pulse went from 5 of 12 inside its band to 9 of
12.

On the sample set as it stands now — DD86-DS2, at the gated default — the
standing figure is 5 of 12, and the difference is the pressing rather than
the decoder. Measured the same way throughout, this tree at the gated
default, GGV1011 passes 5 of 6 and DD86-DS1 passes 3 of 6: the sample set as
it was reads 8 of 12 and the sample set as it is reads 5. See "What the
baseline says" for what the servo does about it.

The differential comparison is not a relaxation. On the PAL CI capture it
newly fails `pal-its-field1/pulse_2t`, which sits 3.1 IRE above the bar on
its own line; measured absolutely at 100.8 IRE it looked correct.

## The top multiburst packet, and what is left of it

Most of the 5.8/5.9 MHz loss this baseline records was the video low-pass. Its corner sat *on* the
packet IEC 60856-1986 Figure 8 specifies, and a Butterworth's corner is its −3 dB point, so the
filter took 3.01 dB (3.65 dB at 5.9 MHz) out of the thing it was placed to reach. A 6.3 MHz order
16 design puts both packets inside the passband for 1.23× the FM-weighted noise, against 1.89× for
simply moving a 7th-order corner out to 7.2 MHz — see [`vits-servos.md`](vits-servos.md).

Measured over the six PAL cuts as they then stood — DD86-DS1, at one field per parity, both arms
the same way — the top packet recovered 1.07–2.70 dB:

| cut | 5.8 MHz order 7 | 6.3 MHz order 16 |
|---|---|---|
| domesday-ds1 inner | −6.10 dB | −3.40 dB |
| domesday-ds1 middle | −8.55 dB | −7.49 dB |
| domesday-ds1 outer | −9.50 dB | −6.96 dB |
| ggv1011 inner | −9.17 dB | −7.69 dB |
| ggv1011 middle | −9.93 dB | −8.40 dB |
| ggv1011 outer | −7.87 dB | −6.14 dB |

On the sample set as it stands now, the packet reads:

| cut | reading | nominal it was measured at |
|---|---|---|
| domesday-ds2 inner | −3.44 dB | 5.87 MHz |
| domesday-ds2 middle | −5.12 dB | 5.90 MHz |
| domesday-ds2 outer | −4.45 dB | 5.90 MHz |
| ggv1011 inner | −7.76 dB | 5.79 MHz |
| ggv1011 middle | −8.32 dB | 5.79 MHz |
| ggv1011 outer | −7.84 dB | 5.79 MHz |

All six still fail, by 2.2 to 7.1 dB beyond the 1.25 dB allowance.

GGV1011 outer reads 2.0 dB worse here than it did before the chroma-band ceiling was given its own
publication schedule, and that is the honest number rather than a regression: the inverse-MTF is
broadband, so a correction wound past what the chroma band justifies was propping up the top packet
as a side effect. Removing an unjustified lift is not allowed to be judged by the packet it
happened to flatter. Note that the disc reading *worse*
is the one whose packet sits **lower** in frequency, which is the opposite of what a passband edge
would do and is the reason the top packet is excluded from the pressing-to-pressing term above.

The residual is not the filter's, and it is not correctable by one. The inverse-MTF is the only
broadband lift the decoder has; its strength is set by burst amplitude and bounded by the chroma
band, and both say "do not boost". Driving a correction from the top packet would make that packet
its own reference and its own verdict. Separating what the medium loses from what the decoder loses
needs evidence this project does not have — two unrelated pressings both losing 3–8 dB there cannot
provide it.

## What this baseline sends to Phase 8

| Allowance | System | Worst | Where | Reading |
|---|---|---|---|---|
| `multiburst_out_of_band_response` | PAL | 6.65× | 5.8/5.9 MHz packet, all six cuts | Top-end loss beyond the video low-pass; not correctable by a filter |
| `luma_level` | PAL, NTSC | 6.01×, 4.18× | `pulse_2t`, Domesday on PAL and Dolby on NTSC | High-frequency luminance above the EQ's anchor band; the 2T servo is already at or driving to its clip |
| `luma_chroma_ratio` | PAL, NTSC | 5.42×, 1.80× | Every radius of every disc | Fails on NTSC too, which Phase 4 did not see |
| `chroma_level` | PAL | 4.49× | Every element at or above 4.0 MHz | The PAL chrominance error Phase 4 records, ordered by frequency |
| `differential_gain` | PAL, NTSC | 3.23×, 1.08× | Worst at inner radius on both | Real on PAL, marginal on NTSC |
| `differential_phase` | PAL, NTSC | 2.22×, 1.21× | PAL outer, NTSC inner | Not monotonic in radius, so not an MTF effect |
| `level_ceiling` | PAL | 1.23× | Domesday saturation, inner only | Over-saturation; the disc has changed since Phase 4 attributed it to GGV |
| `blanking_level` | PAL | 1.12× | GGV1011, all radii | The pedestal offset Phase 4 found, confirmed across the side |
| `chroma_nonlinearity` | PAL | 1.11× | Domesday middle only | Marginal, one radius, and on the unaveragable parity |

Three of these — `chroma_level`, `differential_gain` and `chroma_nonlinearity` on PAL — have their
worst readings on the Domesday second parity, which the coherence gate refuses. They are single
field measurements and the least trustworthy rows in the table; the same rows swing by an order of
magnitude between two pressings of the same title. A PAL disc whose second parity *can* be averaged
would be worth more to this table than any decoder change.

None of these is a reason to widen an allowance. Every one of them is a measurement that has to be
explained (AGENTS.md § 15).
