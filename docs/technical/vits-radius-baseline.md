# VITS conformance baseline across disc radius

The modulation transfer function of a LaserDisc changes with radius, so a decoder can pass every
conformance check at one radius and fail at another. This is the measured baseline that says which
of the decoder allowances in [`analysis/vits_reference.py`](https://github.com/happycube/ld-decode/blob/main/analysis/vits_reference.py) hold
across a whole side and which do not. It is the evidence base those allowances cite, and it is
Phase 6 task 6 of the VITS conformance testing plan.

Nothing here is a proposal to widen anything. Where an allowance is exceeded, the excess is a fault
to be explained — AGENTS.md § 15 — and the ones this baseline surfaces are listed at the end as
Phase 8 work.

## Method

`testdata/radius/` holds a thirteenth cut, `domesday-ds1-community-north-outer`. It is a regression
sample for the inverse-MTF's chroma-band ceiling rather than part of the sweep, so it is excluded
from every table here; where it is quoted for comparison it is named.

Eighteen cuts, six discs at three radii each, taken at 5 %, 50 % and 95 % of each disc's *recorded
band* — that is, past the measured spin-up offset between the start of the capture and disc frame 1.
The cuts are 30 frames (PAL) or 20 frames (NTSC), sized so a decode yields at least ten same-parity
fields, which is what the coherent averaging in the conformance runner wants; the smallest yields
19.

Each cut was decoded from frame 0 with `--exact-speculation` and judged with
[`analysis/vits_conformance.py`](https://github.com/happycube/ld-decode/blob/main/analysis/vits_conformance.py) at its **gated default** —
four fields coherently averaged per parity, falling back to a single field wherever the coherence
gate refuses the group. The first edition of this baseline ran at one field per parity because
that gate did not yet exist; see "What the coherence gate changed" below for what the two readings
differ by and why the averaged one is the better measurement. Checks are grouped by the
`allowance_kind` each one carries, so a row is one entry of `DECODER_ALLOWANCES` and the worst
reading it had to hold at each radius.

`--exact-speculation` is not the decoder's default, and this edition is the first to use it. Without
it the CVBS bytes depend on the thread count, which itself defaults to
`min(max(cpu_count - 2, 1), 10)` — 10 on the machine that measured the first two editions, 2 on a
CI runner. The first CI run of the sweep failed on exactly that: two ceilings recorded at 10 threads
were read at 2 and went over. Under the flag every thread count gives byte-identical output, so a
figure here means the same thing on any machine, and both this baseline and
[`analysis/vits_known_deviations.toml`](https://github.com/happycube/ld-decode/blob/main/analysis/vits_known_deviations.toml)
are measured from those decodes. It matters to the numbers and not only to their reproducibility:
loose speculation on many cores was reading the PAL chroma path better than it is. See "What the
third edition moved" below for the separation.

This is the fourth edition. Its decodes are the CTest radius sweep's at the decoder's defaults
plus `--exact-speculation`, after `21eeeffa`, with the readout model's line reaching zero at
0.90 of the cutoff rather than 0.95 (`readout_zero_fraction`) and never below 13.0 MHz
(`readout_zero_min_hz`, `b4cb5571`; see "What the fourth edition moved").
The defaults include, since `912a12e1`, the legacy CVBS line origin rather than the spec's
0H-aligned one. The runner reads every window against the 0H it
measures, so the origin does not move the figures: decoded again with `--cvbs-spec-origin`,
`ggv1011-side1-inner` is byte-identical, `dolby-surround-side1-inner` differs by float rounding,
and `industrial-lv-side1-inner`, whose legacy 0H sits a whole sample from the spec's, moves no
check by more than 0.05 IRE. See "What the fourth edition moved" below for what did move them.

## The samples

| Sample | System | Radius | Source file frames | Size | Decoded fields | VITS |
|---|---|---|---|---|---|---|
| `ggv1011-side1-inner` | PAL | inner (5 %) | 1429–1458 | 30.3 MB | 56 (28 per parity) | blanked1, blanked2, its1, its2, mb1, mb2 |
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
| `ggv1069-side1-ldv4300d-inner` | NTSC | inner (5 %) | 1560–1579 | 17.4 MB | 40 (20 per parity) | fcc-multiburst, ntc7-combination, ntc7-composite, virs1, virs2 |
| `ggv1069-side1-ldv4300d-middle` | NTSC | middle (50 %) | 12945–12964 | 17.7 MB | 38 (19 per parity) | ntc7-combination, ntc7-composite, virs1, virs2 |
| `ggv1069-side1-ldv4300d-outer` | NTSC | outer (95 %) | 24330–24349 | 18.9 MB | 40 (20 per parity) | ntc7-combination, ntc7-composite, virs1, virs2 |
| `industrial-lv-side1-inner` | PAL | inner (5 %) | 2235–2264 | 28.2 MB | 56 (28 per parity) | blanked1, blanked2, its1, its2, mb1, mb2 |
| `industrial-lv-side1-middle` | PAL | middle (50 %) | 19614–19643 | 34.0 MB | 54 (27 per parity) | blanked1, blanked2, its1, its2, mb1, mb2 |
| `industrial-lv-side1-outer` | PAL | outer (95 %) | 36992–37021 | 36.9 MB | 58 (29 per parity) | blanked1, blanked2, its1, its2, mb1, mb2 |

## What each allowance had to hold

One row per allowance per system, giving the worst any check judged against it read at each radius,
over all three discs of that system. The figure in brackets is how much of what the check was
allowed it used, so it is comparable across units: `1.00×` sits exactly on the limit and anything
above it is a failure. A blank cell means nothing of that kind was judged at that radius.

| Allowance | System | Unit | Worst inner | Worst middle | Worst outer | Worst check |
|---|---|---|---|---|---|---|
| `blanking_level` | PAL | IRE | +1.166 (1.17×) | +1.093 (1.09×) | +1.120 (1.12×) | `pal-blanked-field2/blanked` (ggv1011-side1) |
| `chroma_level` | NTSC | IRE | -5.789 (1.45×) | +1.828 (0.61×) | -2.230 (0.45×) | `ntsc-fcc-multiburst/packet_6` (ggv1069-side1-ldv4300d) |
| `chroma_level` | PAL | IRE | -21.694 (5.05×) | -19.844 (4.61×) | -19.439 (4.52×) | `pal-multiburst-field1/packet_6` (domesday-ds2-community-north) |
| `chroma_nonlinearity` | NTSC | fraction | +0.038 (0.38×) | +0.027 (0.27×) | +0.018 (0.18×) | `ntsc-ntc7-combination/chroma_nonlinearity` (dolby-surround-side1) |
| `chroma_nonlinearity` | PAL | fraction | +0.059 (0.59×) | +0.123 (1.23×) | +0.050 (0.50×) | `pal-multiburst-field2/chroma_nonlinearity` (domesday-ds2-community-north) |
| `differential_gain` | NTSC | fraction | +0.085 (0.85×) | +0.043 (0.43×) | +0.049 (0.49×) | `ntsc-ntc7-composite/chroma_reference/differential_gain` (ggv1069-side1) |
| `differential_gain` | PAL | fraction | +0.106 (1.01×) | +0.119 (1.13×) | +0.095 (0.90×) | `pal-its-field2/staircase_subcarrier/differential_gain` (domesday-ds2-community-north) |
| `differential_phase` | NTSC | degrees | +4.215 (0.84×) | +2.500 (0.50×) | +2.461 (0.49×) | `ntsc-ntc7-composite/chroma_reference/differential_phase` (dolby-surround-side1) |
| `differential_phase` | PAL | degrees | +3.133 (0.60×) | +2.169 (0.42×) | +2.654 (0.51×) | `pal-its-field2/staircase_subcarrier/differential_phase` (domesday-ds2-community-north) |
| `level_ceiling` | NTSC | IRE/percent | +100.975 (0.91×) | +101.606 (0.92×) | +102.163 (0.92×) | `ntsc-ntc7-composite/ceiling/luminance` (ggv1069-side1) |
| `level_ceiling` | PAL | IRE/percent | +102.952 (0.93×) | +108.339 (1.07×) | +96.843 (0.96×) | `pal-multiburst-field2/ceiling/saturation` (domesday-ds2-community-north) |
| `luma_chroma_ratio` | NTSC | ratio | -0.010 (0.99×) | +0.017 (1.67×) | -0.013 (1.34×) | `gain_ratio/NTSC` (ggv1069-side1-ldv4300d) |
| `luma_chroma_ratio` | PAL | ratio | -0.023 (1.05×) | +0.028 (1.29×) | -0.038 (1.78×) | `gain_ratio/PAL` (domesday-ds2-community-north) |
| `luma_level` | NTSC | IRE | -9.463 (4.73×) | -7.956 (3.98×) | -8.800 (4.40×) | `ntsc-ntc7-composite/pulse_2t` (dolby-surround-side1) |
| `luma_level` | PAL | IRE | -2.544 (1.02×) | -12.327 (4.93×) | -11.464 (4.59×) | `pal-its-field1/pulse_2t` (domesday-ds2-community-north) |
| `multiburst_flatness` | NTSC | dB | -0.326 (0.43×) | — | — | `ntsc-fcc-multiburst/packet_3/response` (ggv1069-side1-ldv4300d) |
| `multiburst_flatness` | PAL | dB | -0.121 (0.16×) | +0.301 (0.40×) | +0.479 (0.64×) | `pal-multiburst-field1/packet_3/response` (domesday-ds2-community-north) |
| `multiburst_frequency` | NTSC | MHz | -0.030 (0.61×) | +0.011 (0.22×) | +0.012 (0.23×) | `ntsc-ntc7-combination/packet_6/frequency` (dolby-surround-side1) |
| `multiburst_frequency` | PAL | MHz | +0.230 (1.69×) | +0.227 (1.67×) | +0.227 (1.67×) | `pal-multiburst-field1/packet_6/frequency` (industrial-lv-side1) |
| `multiburst_out_of_band_response` | NTSC | dB | +0.758 (0.61×) | — | — | `ntsc-fcc-multiburst/packet_1/response` (ggv1069-side1-ldv4300d) |
| `multiburst_out_of_band_response` | PAL | dB | -10.451 (8.36×) | -8.743 (6.99×) | -8.523 (6.82×) | `pal-multiburst-field1/packet_6/response` (domesday-ds2-community-north) |
| `step_inequality` | NTSC | fraction | +0.072 (0.72×) | +0.070 (0.70×) | +0.068 (0.68×) | `ntsc-ntc7-composite/staircase/nonlinearity` (dolby-surround-side1) |
| `step_inequality` | PAL | fraction | +0.041 (0.39×) | +0.027 (0.26×) | +0.033 (0.31×) | `pal-its-field2/staircase/nonlinearity` (ggv1011-side1) |

Two rows used to read from one cut only. `ntsc-fcc-multiburst` is the sole NTSC train whose
amplitudes are admissible at this field count — the NTC-7 combination's are not, by the restriction
Phase 5 set — and of the original twelve cuts only `ggv1069-side1-inner` carried it, so the six
readings behind `multiburst_flatness` and `multiburst_out_of_band_response` on NTSC were three
field lines × two parities of one cut rather than six cuts.

The table above still measures those two rows at the inner radius alone, because the FCC multiburst
is on the inner band of the GGV pressings and nowhere else. What has changed is that they are no
longer measured on one disc image: `ggv1069-side1-ldv4300d-inner` is the same pressing read on a
different player six years later, and `ntsc/ggv-ntsc-mb-v2800.ldf` is a third reading judged by its
own conformance lane. **The second image immediately put `multiburst_flatness` NTSC over its
allowance** — `ntsc-fcc-multiburst/packet_3/response` reads 0.811 dB on field line 24 of the second
parity and 0.773 dB on line 23 of the first, against 0.75 allowed, so 1.08× and 1.03×, where the
same row read 0.55× on the first capture alone. It still does in this edition, on one reading: 0.782 dB
on line 23 of the first parity, 1.04×, against 0.73× on the first capture. So the claim "this allowance holds across a whole
side" was resting on the one capture that fitted it; it is now carried as a known deviation rather
than as a row that holds. Every other row is eighteen cuts.

**Re-measured with the corrected multiburst fit (2026-10-20), the row holds again**, at 0.43×
(−0.326 dB, the same reading). The excess was the decoder's. Its multiburst fit read that 2.0 MHz
packet about 0.7 dB low against its 1.25 MHz reference, and the video EQ lifted 2 MHz 1.6 dB to
match. See "What the fourth edition moved".

## What the baseline says

**Three allowances hold across a whole side.** `step_inequality` has held in every edition, and
`differential_phase` and `multiburst_flatness` join it in this one, on both systems. `level_ceiling`
held until the corrected multiburst fit, which tipped Domesday DS2 middle's saturation ceiling to
1.02× (1.01× since the calibration pass). `multiburst_frequency`, lost in the third edition, is still lost.

| Allowance | Second edition (12 cuts) | Third edition (18 cuts) | This edition (18 cuts) | Allowed | Holds |
|---|---|---|---|---|---|
| `step_inequality` | 0.72× | 0.72× | 0.70× | 0.100 | yes |
| `differential_phase` | 2.22× | 2.13× | 0.84× | 5.0° NTSC, 5.2° PAL | yes |
| `level_ceiling` | 1.23× | 1.31× | **1.01×** | 101 IRE / 111 % | no |
| `multiburst_flatness` | 0.86× | **1.08×** | 0.43× | 0.75 dB | yes |
| `multiburst_frequency` | 0.75× | **1.71×** | **1.69×** | 0.020–0.051 MHz | no |

`differential_gain` misses joining them on two cuts: GGV1011 inner on PAL at 1.01×, where the
third edition's worst was 3.22×, and Domesday DS2 outer at 1.19× since the calibration pass. What moved the three new rows is the decoder, not the sample set;
see "What the fourth edition moved".

Neither loss is the determinism fix. `multiburst_flatness` NTSC went 0.46× → 0.55× on the flag and
0.55× → 1.08× on the second disc image; `multiburst_frequency` PAL did not move on the flag at all
(0.55×/0.76×/0.75× → 0.55×/0.75×/0.75×) and went to 1.71×/1.67×/1.71× on the sixth disc. Both were
lost to seeing a second image, which is what the images were added for, and neither has moved
materially since.

`multiburst_flatness` is the important one, and it is the one the addition cost. Phase 5 set it from
the video EQ servo's own dead-band plus the largest residual [`vits-servos.md`](vits-servos.md)
records it leaving, and modelled one envelope across radius rather than a table per radius on the
argument that removing radius dependence is what the servo is *for* — the Louvre fr2000→6000 row.
Over four discs and three radii the worst reading used 86 % of it, and the argument appeared to
hold.

It was resting on one capture. NTSC flatness is measurable only where the FCC multiburst is, which
of the original twelve cuts was `ggv1069-side1-inner` alone. Read the *same pressing* on a different
player six years later — `ggv1069-side1-ldv4300d-inner` — and `ntsc-fcc-multiburst/packet_3/response`
goes over on one of its six readings: 0.782 dB on field line 23 of the first parity, against 0.75
allowed, so 1.04× (the third edition read 0.811 and 0.773 dB, on two). Two captures of one disc
are enough to put it over, so the 0.86× figure was the
spread of one capture and not of the medium. The allowance is not widened; the excess is carried in
[`analysis/vits_known_deviations.toml`](https://github.com/happycube/ld-decode/blob/main/analysis/vits_known_deviations.toml)
as a fault to explain, per AGENTS.md § 15.

That fault has been explained, and the entry is gone. The decoder's own multiburst fit read short
packets low against the reference: 0.7 dB at 2.0 MHz, up to 2 dB at 4.1 MHz. So the video EQ
lifted the band the conformance checker then judged hot. With the fit corrected, the worst NTSC
reading is −0.326 dB, 0.43×. The second capture did what it was added for: it exposed a fault the
first one hid.

`multiburst_frequency` fails on `industrial-lv-side1-*` at 1.69×/1.67×/1.67×, on the top packet
only, at all three radii: 6.03 MHz against the 5.8 MHz nominal, stable to three decimals. That
packet is also 8 dB down, so the reading is not independent of the band-edge loss recorded beside
it, and this disc is the first `PAL_MULTIBURST_IEC` pressing here — packets 1 to 5 land within
0.07 MHz of the IEC nominals. `analysis/vits_reference.py` already records two pressings carrying
top nominals 0.1 MHz apart and says a third unrelated PAL pressing is what the derivation needs;
this is that third pressing, and telling a disc nominal from a measurement bias is the work the
deviation entry waits on.

`multiburst_out_of_band_response` holds on NTSC (0.59×) and fails on PAL at every radius, now on the
5.8 MHz packet alone. It is new since the first edition, which had no allowance covering those
frequencies at all; see "The band no allowance covered" below.

**The clearest radius-dependent failure is still the 2T pulse, and it is still on both systems.**
The three 2T pulses are the worst luminance elements measured, by more than a factor of two:

| Element | Worst | System |
|---|---|---|
| `pal-its-field1/pulse_2t` | 5.66× (−14.1 IRE) | PAL |
| `ntsc-ntc7-composite/pulse_2t` | 4.73× (−9.5 IRE) | NTSC |
| `pal-its-field2/pulse_2t` | 4.44× (−11.1 IRE) | PAL |
| *next worst luminance element of any kind* | 1.73× (+4.3 IRE) | PAL 20T luminance |

but it does not worsen monotonically outwards, and it separates by disc. Over the eighteen cuts the
pulse passes 13 of 27 readings, split almost entirely by what kind of disc it is:

| Disc | 2T readings | Passes |
|---|---|---|
| Pioneer GGV1011 (PAL calibration) | 6 | 6 |
| Pioneer Industrial LaserVision (PAL test/demo) | 6 | 3 |
| BBC Domesday DD86-DS2 (PAL programme) | 6 | 1 |
| Pioneer GGV1069 (NTSC calibration) | 3 | 1 |
| Pioneer GGV1069, LDV4300D capture | 3 | 2 |
| Checking Dolby Surround (NTSC programme) | 3 | 0 |

GGV1011, a calibration disc carrying a designed ITS, reads within its band at all six. Industrial
LaserVision, a Pioneer test disc, manages three. Domesday misses its own bar at five of six. The
third edition had every NTSC cut failing, calibration and programme disc alike, which mastering could
not explain. That is no longer so: on the readout MTF model NTSC now uses, the GGV1069 calibration
disc passes three of its six readings across the two captures, and Dolby Surround still passes
none. NTSC splits the way PAL does. Dolby's worst reading has moved, though, from +5.8 IRE over at
the inner radius in the third edition to −9.5 IRE under (2.92× → 4.73×), the worst NTSC luminance
reading in the sweep; the readout model does not run the 2T servo. In the third edition, on the
same cuts decoded by the same tree, DD86-DS1 passed 3 of 6 where DD86-DS2 passed 1, so among the
PAL programme discs the difference was between the two pressings and not between the decoder and
itself.

The PAL 2T servo is not idle while that happens. On Domesday middle it drives `mtf_level` from
0.000 down to −0.744 — the direction that *raises* demodulated HF — and lifting its 100-field
adoption rate limit (a 30-frame cut is about 60 fields, so it normally adopts once) lets it continue
to the −1.000 clip floor. That second adoption lands after the fields the conformance check
averages, so the measured pulse is unchanged either way; what the probe does establish is that the
loop is already asking for the correction in the right direction and is not being held back by its
own convergence time inside a cut.

**`luma_chroma_ratio` on NTSC now passes at the inner radius** and still fails at the middle and
outer ones — 0.96×, 1.67×, 1.34×, from the third edition's 1.85×, 2.46×, 1.80×, with 2 of 9
readings failing where 7 did (3 until the NTC-7 multiburst was read; see "What the fourth edition
moved"). Phase 4 measured it on the
NTSC CI capture alone, where it passed. It is the second finding here that only a radius sweep
could produce. The worst reading is still at the middle radius and still on the second GGV1069
capture rather than the first (1.67× against 0.87× on the same pressing read on a different
player), so part of what the row measures is the capture and not only the disc. On PAL it now
fails only at the inner and outer radii (1.06×, 1.63×), from 6.69× at the inner radius.

**`chroma_level` on PAL fails on three elements of eleven, and all three read low.** The third
edition recorded eight failing, every one of them reading high except the band edge, seven at their
worst on `domesday-ds2-community-north-inner`. That was the PAL chrominance error Phase 4 records,
and the decoder work between the editions removed it (see "What the fourth edition moved"):

| Element | Worst | Fails | Frequency |
|---|---|---|---|
| `pal-multiburst-field1/packet_6` | 5.07× (−21.8 IRE) | 9 of 9 | 5.8/5.9 MHz |
| `pal-multiburst-field2/chroma_bar_100` | 1.27× (−8.2 IRE) | 2 of 9 | 4.43 MHz |
| `pal-multiburst-field1/packet_5` | 1.05× (−4.5 IRE) | 1 of 9 | 4.8 MHz |
| `pal-multiburst-field2/chroma_bar_60` | 0.95× (−4.3 IRE) | 0 of 9 | 4.43 MHz |
| `pal-multiburst-field1/packet_4` | 0.84× (−3.6 IRE) | 0 of 9 | 4.0 MHz |
| `pal-multiburst-field2/chroma_reference` | 0.84× (−3.8 IRE) | 0 of 9 | 4.43 MHz |

The top packet is the band-edge loss treated below. The other two failures, and the worst of what
passes, are all on Domesday and all low, which is the other side of the correction that took its
high readings out: the multiburst now winds the inverse MTF *negative* on that disc, and the
chrominance bars and the 4.8 MHz packet go down with the peak it removes. The 20 % chrominance bar,
which the determinism fix put on the third edition's list at 1.33×, reads 0.61×.

**`chroma_level` on NTSC is the row this edition made worse.** The FCC multiburst's 1.25, 3.0 and
4.1 MHz packets read low on both GGV1069 captures, and 27 of their readings fail where 11 did at
`6a5c3a1f`; the worst is the 4.1 MHz packet on the LDV4300D capture of GGV1069 inner, 1.42× (−5.7
IRE), against 1.15× in the third edition. That is the readout model's equalisation reading the
upper luminance band lower than the pole model did, the same change that moves the NTSC 2T pulse.
With the line's zero at 0.95 of the cutoff it read 26 failing, the worst 1.44× (−5.8 IRE); at 0.90
without the 13.0 MHz floor, 21 and 1.18× (−4.7 IRE). The floor costs the 4.1 MHz packet about
0.4 dB on both inner cuts, for the differential gain it takes out there; see "What the fourth
edition moved".

## What moved between the first and second editions

The first edition of this table was measured on a different decoder, a different Domesday pressing
and a different averaging rule. All three moved together, so a row's movement is not attributable
to any one of them without the separations below. Direction is first → second, on the worst reading
at each radius. The figures in the right-hand column of each cell are the *second* edition's and no
longer the current ones; for those see the table above, and for the difference the section that
follows this one:

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

## What the third edition moved

This edition changed two things at once: the sweep gained a fifth and sixth disc, and the decodes
gained `--exact-speculation`. They are separable, because the twelve original cuts can be
re-measured under the flag on their own — so each row below says whether it moved because the decode
became deterministic, because the sweep saw more discs, or both. Direction is second edition → this
one:

| Allowance | System | inner | middle | outer | moved by |
|---|---|---|---|---|---|
| `blanking_level` | PAL | 1.07 ↑ 1.17 | 1.10 ↓ 1.09 | 1.12 = 1.12 | determinism |
| `chroma_level` | NTSC | 1.11 ↑ 1.15 | 0.81 ↑ 0.87 | 0.75 ↑ 0.76 | the added discs |
| `chroma_level` | PAL | 4.37 = 4.37 | 4.49 ↑ 4.52 | 4.30 ↑ 4.49 | determinism |
| `chroma_nonlinearity` | NTSC | 0.46 = 0.46 | 0.24 ↑ 0.28 | 0.18 = 0.18 | the added discs |
| `chroma_nonlinearity` | PAL | 0.49 = 0.49 | 1.11 = 1.11 | 0.49 ↑ 0.51 | determinism |
| `differential_gain` | NTSC | 1.08 = 1.08 | 1.06 = 1.06 | 0.98 = 0.98 | — |
| `differential_gain` | PAL | 3.23 ↓ 3.22 | 1.57 = 1.57 | 1.47 ↓ 1.44 | determinism |
| `differential_phase` | NTSC | 1.21 = 1.21 | 0.40 = 0.40 | 0.60 = 0.60 | — |
| `differential_phase` | PAL | 1.06 ↓ 1.04 | 0.71 ↑ 0.83 | 2.22 ↓ 2.13 | both |
| `level_ceiling` | NTSC | 0.95 = 0.95 | 0.93 = 0.93 | 0.93 = 0.93 | — |
| `level_ceiling` | PAL | 1.23 ↑ 1.31 | 0.94 ↑ 0.98 | 0.96 ↑ 0.97 | both |
| `luma_chroma_ratio` | NTSC | 1.43 ↑ 1.85 | 1.75 ↑ 2.46 | 1.80 = 1.80 | both |
| `luma_chroma_ratio` | PAL | 5.42 ↑ 6.69 | 1.18 = 1.18 | 1.74 ↓ 1.54 | determinism |
| `luma_level` | NTSC | 2.75 ↑ 2.92 | 3.92 = 3.92 | 4.18 = 4.18 | the added discs |
| `luma_level` | PAL | 2.27 ↑ 2.44 | 6.01 ↓ 5.97 | 4.47 ↓ 4.45 | determinism |
| `multiburst_flatness` | NTSC | **0.46 ↑ 1.08** | — | — | both |
| `multiburst_flatness` | PAL | 0.19 ↓ 0.04 | 0.23 ↑ 0.24 | 0.86 ↓ 0.72 | determinism |
| `multiburst_frequency` | NTSC | 0.52 = 0.52 | 0.20 = 0.20 | 0.23 = 0.23 | — |
| `multiburst_frequency` | PAL | **0.55 ↑ 1.71** | **0.76 ↑ 1.67** | **0.75 ↑ 1.71** | both |
| `multiburst_out_of_band_response` | NTSC | 0.72 ↑ 0.76 | — | — | the added discs |
| `multiburst_out_of_band_response` | PAL | 6.21 ↑ 6.34 | 6.65 ↑ 6.87 | 6.27 ↑ 6.91 | both |
| `step_inequality` | NTSC | 0.70 = 0.70 | 0.72 = 0.72 | 0.66 = 0.66 | — |
| `step_inequality` | PAL | 0.44 ↑ 0.60 | 0.26 = 0.26 | 0.28 ↑ 0.31 | determinism |

**Only two rows cross 1.00×, both upwards, and both are the added discs rather than the flag.**
`multiburst_flatness` NTSC and `multiburst_frequency` PAL are the two allowances the previous
section records losing, and the crossing in each case comes from the sixth disc or the second
capture, not from the change of decode.

**The determinism fix reads worse far more often than better, and it concentrates on PAL
chrominance.** `luma_chroma_ratio` PAL inner is the largest single move attributable to the flag
alone, 5.42× → 6.69×, and the same cut's chrominance bars and chrominance reference move with it —
they are the entries re-recorded in
[`analysis/vits_known_deviations.toml`](https://github.com/happycube/ld-decode/blob/main/analysis/vits_known_deviations.toml),
where the 100 % bar goes 1.84× → 2.45×, the 60 % bar 2.02× → 2.58× and the chrominance reference
2.67× → 3.28×. Of twenty-two entries the re-measurement moved, nineteen are on
`domesday-ds2-community-north-inner` and `-middle`. One check moved the other way far
enough to pass and its entry is deleted, `pal-its-field2/pulse_2t` on the inner cut, which had been
recorded at 1.16×.

That direction is the point. Loose speculation accepts more of what it guesses, and on a machine
with ten worker threads it accepted enough to read the PAL chroma path better than it is. The
second edition's PAL chrominance figures were therefore taken in the decoder's favour by up to
0.6× of a band, and the flag does not make the decoder worse — it stops the measurement flattering
it. Ten readings do improve, and every one of them is PAL: eight by less than 0.1× of a band, on
rows that were already failing or already passing comfortably, and two worth naming —
`multiburst_flatness` PAL outer 0.86× → 0.72× and `luma_chroma_ratio` PAL outer 1.74× → 1.54×,
the two places where the second edition overstated a fault rather than understating one.

## What the fourth edition moved

This edition changed the decoder and nothing else: the same eighteen cuts, decoded and judged the
same way. Between the third edition and this one the decoder took 68 commits, in two groups that
matter here.

- **Before `6a5c3a1f`.** Among much else, the Domesday chroma, differential-gain and
  differential-phase fixes (`6efbdad6`, `3e66cd63`, `f448f83f`) — the first of which lets the
  multiburst ceiling wind the inverse MTF negative, bounded by `IMTF_STRENGTH_LIMIT` — and the PAL
  MTF frame-rate fix (`1e9f8041`). They were not separated commit by commit.
- **`f50f23dd`.** NTSC moved to the disc readout MTF model, which equalises to the optical cutoff the
  decoder measures from the burst's FM sidebands (or, short of those, the carrier tilt) and does not
  run the 2T servo, and gained the
  chroma differential-gain corrector PAL already had. PAL output is byte-identical across it.
- **The readout line's zero at 0.90 of the cutoff**, not 0.95 (`readout_zero_fraction`, after
  `21eeeffa`). The slope of the line the channel is equalised to does not touch the video, but it
  sets how hard the weak upper RF sideband is lifted, and with it the 3–4.2 MHz noise at inner
  radius; see [`vits-servos.md`](vits-servos.md). NTSC only; PAL runs the pole model.
- **The zero never below 13.0 MHz** (`readout_zero_min_hz`, `b4cb5571`), peak white's carrier plus
  the subcarrier. Below it the line clipped the upper chroma sideband of bright picture at inner
  radius and lifted chroma with luminance. Only cutoffs under 14.4 MHz move.

The NTSC rows were also measured at `6a5c3a1f`, which separates the work before it from the
readout model; those readings are bracketed in the last column (inner / middle / outer), and
`f50f23dd` there includes the zero at 0.90 and its floor. Direction is third edition → this one, and
a bold cell crosses 1.00×:

| Allowance | System | inner | middle | outer | moved by (NTSC at `6a5c3a1f`) |
|---|---|---|---|---|---|
| `blanking_level` | PAL | 1.17 = 1.17 | 1.09 = 1.09 | 1.12 = 1.12 | — |
| `chroma_level` | NTSC | 1.15 ↑ 1.42 | 0.87 ↓ 0.61 | 0.76 ↓ 0.45 | `f50f23dd` (1.15 / 0.87 / 0.76) |
| `chroma_level` | PAL | 4.37 ↑ 5.07 | 4.52 ↑ 4.61 | 4.49 ↑ 4.50 | before `6a5c3a1f` |
| `chroma_nonlinearity` | NTSC | 0.46 ↓ 0.38 | 0.28 ↓ 0.27 | 0.18 = 0.18 | — (0.48 / 0.27 / 0.17) |
| `chroma_nonlinearity` | PAL | 0.49 ↑ 0.61 | 1.11 ↑ 1.19 | 0.51 = 0.51 | before `6a5c3a1f` |
| `differential_gain` | NTSC | **1.08 ↓ 0.85** | **1.06 ↓ 0.43** | 0.98 ↓ 0.49 | both (0.94 / 0.71 / 0.63) |
| `differential_gain` | PAL | 3.22 ↓ 1.01 | **1.57 ↓ 0.86** | **1.44 ↓ 0.71** | before `6a5c3a1f` |
| `differential_phase` | NTSC | **1.21 ↓ 0.84** | 0.40 ↑ 0.50 | 0.60 ↓ 0.49 | both (1.01 / 0.45 / 0.54) |
| `differential_phase` | PAL | **1.04 ↓ 0.61** | 0.83 ↓ 0.42 | **2.13 ↓ 0.51** | before `6a5c3a1f` |
| `level_ceiling` | NTSC | 0.95 ↓ 0.92 | 0.93 ↓ 0.92 | 0.93 ↓ 0.92 | — (0.95 / 0.93 / 0.93) |
| `level_ceiling` | PAL | **1.31 ↓ 0.94** | 0.98 = 0.98 | 0.97 ↓ 0.96 | before `6a5c3a1f` |
| `luma_chroma_ratio` | NTSC | **1.85 ↓ 0.96** | 2.46 ↓ 1.67 | 1.80 ↓ 1.34 | `f50f23dd` (1.83 / 2.45 / 1.80) |
| `luma_chroma_ratio` | PAL | 6.69 ↓ 1.06 | **1.18 ↓ 0.55** | 1.54 ↑ 1.63 | before `6a5c3a1f` |
| `luma_level` | NTSC | 2.92 ↑ 4.73 | 3.92 ↑ 4.00 | 4.18 ↑ 4.40 | both (2.88 / 3.92 / 4.18) |
| `luma_level` | PAL | 2.44 ↓ 1.20 | 5.97 ↓ 5.66 | 4.45 ↓ 4.44 | before `6a5c3a1f` |
| `multiburst_flatness` | NTSC | 1.08 ↓ 1.04 | — | — | before `6a5c3a1f` (1.03 / — / —) |
| `multiburst_flatness` | PAL | 0.04 ↑ 0.16 | 0.24 ↑ 0.37 | 0.72 ↓ 0.71 | before `6a5c3a1f` |
| `multiburst_frequency` | NTSC | 0.52 ↑ 0.61 | 0.20 ↑ 0.22 | 0.23 = 0.23 | — (0.52 / 0.20 / 0.22) |
| `multiburst_frequency` | PAL | 1.71 ↓ 1.69 | 1.67 = 1.67 | 1.71 ↓ 1.67 | before `6a5c3a1f` |
| `multiburst_out_of_band_response` | NTSC | 0.76 ↓ 0.59 | — | — | `f50f23dd` (0.77 / — / —) |
| `multiburst_out_of_band_response` | PAL | 6.34 ↑ 8.40 | 6.87 ↑ 7.08 | 6.91 ↓ 6.75 | before `6a5c3a1f` |
| `step_inequality` | NTSC | 0.70 = 0.70 | 0.72 ↓ 0.70 | 0.66 ↑ 0.68 | — (0.69 / 0.71 / 0.69) |
| `step_inequality` | PAL | 0.60 ↓ 0.39 | 0.26 = 0.26 | 0.31 ↑ 0.32 | before `6a5c3a1f` |

**Ten readings cross 1.00×, and every one of them downwards.** No row that passed in the third
edition fails in this one.

**Most of the movement is PAL chrominance, and it is the work before `6a5c3a1f`.**
`luma_chroma_ratio` PAL inner goes 6.69× → 1.06×, `differential_gain` PAL inner 3.22× → 1.01×,
`differential_phase` PAL outer 2.13× → 0.51×, `level_ceiling` PAL inner 1.31× → 0.94×, and the PAL
`chroma_level` elements that fail go from eight to three. Nearly all of those worst readings were
Domesday's. The cost is at the band edge: the inverse MTF is broadband, so the negative strength
that flattens Domesday's 4–4.8 MHz peak also takes its 5.8 MHz packet from −3.30 to −10.51 dB at
the inner radius, and `multiburst_out_of_band_response` PAL inner goes 6.34× → 8.40× and
`chroma_level` PAL inner 4.37× → 5.07× on that one packet.

**The NTSC readout model trades the upper luminance band for the gain ratio and the 2T pass rate.**
At the zero's 0.90 alone, before the floor below, `luma_chroma_ratio` NTSC goes 1.83×/2.45×/1.80× → 0.89×/1.67×/1.34× across it, 7 of 9 readings
failing to 4, and the NTSC 2T pulse passes 3 of 9 where it passed none. The differential-gain
corrector takes `differential_gain` NTSC from 0.94×/0.71×/0.63× to 0.69×/0.43×/0.49× and
`differential_phase` NTSC inner from 1.01× to 0.90×; the work before it had already taken those
rows from 1.08× and 1.21×. Against that, the FCC multiburst packets at 1.25, 3.0 and 4.1 MHz read
lower, which takes `chroma_level` NTSC inner from 1.15× to 1.18×, and Dolby Surround's inner 2T
pulse goes from +5.8 IRE over to −9.3 IRE under. The middle and outer `chroma_level` readings
improve (0.87× → 0.61×, 0.76× → 0.45×), and `multiburst_out_of_band_response` NTSC goes 0.77× →
0.61×.

**The zero at 0.90 rather than 0.95 is most of what the readout model gives back.** Measured at
0.95 the same sweep read `chroma_level` NTSC inner 1.44× (the 4.1 MHz packet on GGV1069 inner −5.0
IRE, against −3.8 at 0.90 and −4.1 at `6a5c3a1f`), the Dolby inner 2T 4.87×, the NTSC gain ratio
at the inner radius 1.09×, and failed 51 checks across the NTSC captures where 0.90 fails 44. What
0.90 costs is `differential_phase` NTSC inner, 0.84× → 0.90× (Dolby Surround inner, 3.57° to
4.50°), and the gain ratio on the two GGV1069 outer cuts, which go just over: 1.00× and 1.05×.

**The zero's 13.0 MHz floor moves the inner radius and little else.** At 0.90 of a cutoff under
14.4 MHz the line reached zero below the upper chroma sideband of bright picture, and a carrier
whose upper sideband is clipped keeps only its lower one, so the line lifted chroma with luminance
(on a disc matching the readout model, +8.5 % at 90 IRE at a 13.6 MHz cutoff). The floor takes that
lift out, and the worst `differential_gain` NTSC inner reading *rises*, 0.69× → 0.85×, because on
GGV1069 inner the lift had been offsetting a fall the real channel puts in above 12 MHz and the
model does not (0.069 → 0.085). The same pressing on the LDV4300D falls 0.067 → 0.037, Dolby Surround inner holds
at 0.059, and off the sweep Doobie, the one NTSC capture that failed, goes 0.105 → 0.047; part of
what is left is the player's response, which no disc model carries. `differential_phase` NTSC inner
improves 0.90× → 0.84× (Dolby Surround inner 4.50° → 4.19°; the worst is now the LDV4300D cut at
4.20°) and `chroma_nonlinearity` 0.47× → 0.38×. The cost is the lift the clipped line gave 4.1 MHz
luminance through the lower sideband: about 0.4 dB on both GGV1069 inner cuts, which takes
`chroma_level` NTSC inner 1.18× → 1.42× and the failing FCC multiburst readings from 21 to 27,
back to where the zero at 0.95 had them. The Dolby inner 2T goes 4.66× → 4.73×. Decodes start at
an MTF level of 1.0, where the floor applies, before the cutoff is measured, so the first servo
readings move on every NTSC cut and leave the middle and outer ones a few hundredths off (the
GGV1069 outer gain ratio, which sat on its limit at 1.00×, now passes, and the NTSC gain ratio
fails 3 of 9).

**The corrected multiburst fit (2026-10-20) moves the GGV FCC cuts and Domesday DS2.**
`metrics.measure_vits_multiburst` grouped its scan windows against the previous window's frequency
and fitted over the windows' span. That read the FCC multiburst's short packets low against the
1.25 MHz reference: 0.7 dB at 2.0 MHz, up to 2 dB at 4.1 MHz where the 3.58 and 4.1 MHz packets
were chained into one. It now groups against the median and fits each packet's steady interior. On
NTSC, read correctly, the chroma band measures flat 0.5–1.0 dB short of where the burst puts it, so
the multiburst ceiling only caps a boost more than 1.5 dB past flat (`IMTF_CEILING_ENGAGE_DB`; see
[`vits-servos.md`](vits-servos.md)). Without that gate the GGV FCC cuts lose 0.25 strength units.
- **GGV FCC cuts.** `multiburst_flatness` NTSC inner goes 1.04× → 0.43×, and the GGV1069 inner 2T
  passes on both players (102.1 → 101.0, 102.5 → 100.5; `level_ceiling` NTSC inner 0.92× → 0.91×).
  The 2.0 MHz packet's absolute level now fails on all three FCC captures (24.9–26.0 IRE against a
  26 floor). Their multiburst is recorded low (the 1.25 MHz reference reads 25.7–26.4), and only the
  1.6 dB lift had carried that packet over. These are 20 new known deviations, recorded as such.
  `chroma_level` NTSC inner 1.42× → 1.41×.
- **Domesday DS2.** PAL's packets are longer and moved 0.05–0.1 dB. That was enough at DS2, whose
  2T servo, multiburst EQ and ceiling sit at their thresholds. At middle radius the 2T servo ran to
  its −1.0 limit, so `differential_gain` PAL middle goes 0.86× → 1.04×, `level_ceiling` PAL middle
  0.98× → 1.02× and `chroma_nonlinearity` PAL middle 1.19× → 1.22×. At outer radius the ceiling
  settled 0.03 strength units lower: `luma_chroma_ratio` 1.63× → 1.78× and `luma_level` 4.44× →
  4.59×. The inner cut moves the other way: three failures pass, `luma_level` inner 1.20× → 1.02×
  and `chroma_level` PAL inner 5.07× → 4.96×.
- **The NTC-7 multiburst read as well.** Fitted over their own interiors, the NTC-7 combination's
  packets on NTSC second fields agree with the conformance checker to 0.3 dB, so the EQ servo now
  reads them where a disc has no FCC line; the subcarrier packet is told from the three-level
  chrominance after it by taking the run of packets that rises in frequency. Dolby Surround's
  ~2.5 µs packets are too short and still go unread. On the GGV1069 middle and outer cuts the EQ's
  estimate stays inside its dead-band. The LDV4300D outer cut's gain ratio passes (2 of 9 NTSC
  readings fail where 3 did), and off the sweep ve-monitor's 2T goes 1.38× → 1.14× of its band.

**The calibration pass (2026-10-20) moves Domesday DS2 and the NTSC phase.** The decoder now decodes
at least ten frames ahead before writing, until no servo has moved for six fields, where it had
stopped after two (see [`vits-servos.md`](vits-servos.md), "Calibrating before the first frame"). It
also raises the multiburst's cut threshold from 1.0 to 1.5 dB. Settled, DS2's middle and outer cuts
read their chroma band 1.24 and 1.16 dB hot: the 2T servo's pre-demod boost on a disc whose 2T reads
low, with Domesday's mastered 4–4.8 MHz peak on top. A 1.0 dB threshold cut them and took the
chrominance under its references (gain ratio 0.266).
- **NTSC differential phase.** `differential_phase` NTSC inner 0.84× → 0.60× (Dolby Surround inner
  4.19° → 2.14°, GGV1069 inner 3.80° → 2.15°, the LDV4300D cut 4.20° → 3.00°). The phase decision
  needs sixteen pooled fields, and on these cuts it now arrives two to five frames into the clip
  rather than about frame 16 — but not because the pass collected them. The staircase is on one field
  in two, so ten frames give the pool at most ten. The committed decode then goes back over the
  pass's fields, and each servo's pool replaces a reading only when it is the pool's last entry, so
  those fields are pooled a second time and the pool reaches sixteen early. Pooling each field once
  puts all three back where they were; having the pass wait for sixteen distinct fields takes them
  to 1.3–1.7°, but stretches the pass to 17–25 frames, longer than most of the sweep's clips.
- **Domesday DS2.** At outer radius `luma_chroma_ratio` PAL 1.78× → 0.61× (0.262 → 0.299) and the
  chroma bars pass. DG goes 0.72× → 1.19× and the 4.0 MHz response, no longer cut, reads +1.37 dB.
  At middle radius `level_ceiling` PAL 1.02× → 1.01×. The 2T servo still runs to its −1.0 limit there,
  and its second-field 2T reads 97.6 against a 98.2 floor.
- **Dolby Surround outer DG** 0.049 → 0.080 (0.49× → 0.80×). Its slope sits on the corrector's
  engage line: the pass adopts −0.00112/IRE, and four frames in the pool's median dips to −0.00095
  and the correction is released for the rest of the clip.
- Net, the list holds 110 entries where it held 113.

**The DG slope's hysteresis (2026-10-20) keeps Dolby Surround outer corrected.** An engaged slope
correction now releases only under 0.0008/IRE on NTSC and 0.0010 on PAL, where it engages at 0.0010
and 0.0015, as the phase correction already did (see [`vits-servos.md`](vits-servos.md), "4. Chroma
differential gain and phase"). Dolby Surround outer's pooled median wanders between −0.00095 and
−0.00118, so it held the correction only until the first dip under 0.0010, and the rate limit kept
it off from there.
- `differential_gain` NTSC outer 0.80× → 0.44× (Dolby Surround outer 0.080 → 0.034). The LDV4300D
  inner cut had released the same way, and goes 0.051 → 0.035.
- The correction moves those cuts' chroma a little. `luma_chroma_ratio` NTSC outer 1.43× → 1.52×,
  and `chroma_level` NTSC inner 1.40× → 1.45× (the LDV4300D cut's 4.1 MHz packet, recorded low, a
  further 0.2 IRE under), both inside their listed ceilings.
- No verdict changes; the list still holds 110 entries.

**Each field pooled once, and the pass waits for the phase decision (2026-10-20).** The committed
decode goes back over the fields the calibration pass read, and every servo's pool now replaces a
field's reading wherever it stands (`decoder.pool_reading`) where it used to compare against its last
entry only, so the pass's fields are no longer pooled twice. On a disc with a modulated staircase the
pass also waits, up to 25 frames, until the DG corrector's phase pool holds the sixteen readings its
decision takes; the staircase discs now write from 17–25 frames (see
[`vits-servos.md`](vits-servos.md), "Calibrating before the first frame").
- `differential_phase` NTSC inner 0.60× → 0.33×, corrected from the first frame: Dolby Surround
  inner 2.14° → 1.66°, GGV1069 inner 2.15° → 1.29°, the LDV4300D cut 2.98° → 1.35°.
- `differential_gain` NTSC inner 0.85× → 0.60×: GGV1069 inner's slope is corrected now that the
  pass pools enough of it, 0.085 → 0.035. Its multiburst's 3.0 MHz packet, recorded low, goes
  26.03 → 25.77 IRE against a 26 floor on two more lines, now listed with its other lines.
- **DD86-DS2 middle** is no longer DG-corrected. Read once per field its PAL slope pools +0.0012 to
  +0.0013/IRE, under the 0.0015 engage line, which it had crossed only on doubled readings:
  `differential_gain` PAL middle 0.94× → 1.27× (0.099 → 0.133). Its multiburst's 4.0 and 4.8 MHz
  packets, which straddle the subcarrier, read 1.6× and 1.5× of their band; its first-field 2T
  improves, `luma_level` PAL middle 5.63× → 4.60×, and the 5.8 MHz packet 5.01× → 4.22×. All four
  new entries are listed with their reasons.
- GGV1011 inner, the PAL control the phase thresholds keep untouched, still reads 1.31°.
- Net, the list holds 114 entries where it held 110.

**The calibration pass made opt-in (2026-10-20).** `--calibration_frames` now defaults to 0, and the
sweep judges the default decode again; the table above is that decode, with the change below. Five cuts are decoded a
second time with a 10-frame pass and judged against their own list
(`analysis/vits_known_deviations_calibrated.toml`), where the figures in the three paragraphs above
still hold. Against the last decoder without the pass (7ceee4eb), the default decode differs only
on DD86-DS2 middle, where each field being pooled once stops the 2T servo at −0.86 rather than its
−1.0 limit:
- `luma_level` PAL middle 5.39× → 4.93× (its first-field 2T) and the 5.8 MHz packet's response
  4.92× → 4.52×.
- The chroma strength fed forward with the MTF level leaves the chroma band 0.47 dB higher:
  `luma_chroma_ratio` PAL middle 0.56× → 1.29× (0.311 → 0.328), `level_ceiling` PAL middle 1.02× →
  1.07×, and the 4.8 MHz packet 1.06 → 1.51 dB over the reference. Both new failures are listed.
- `differential_gain` PAL middle 1.04× → 1.13×.
- Net, the default list holds 115 entries where 7ceee4eb's held 113.

**The DG slope decided before the first frame (2026-10-21).** The default warm-up now pools the
staircase too, and waits for the DG corrector's slope decision, so the opening frames are
gain-corrected where they used to go out with the corrector off. Five cuts adopt before writing:
Dolby Surround inner (−0.00153/IRE) and middle (−0.00102), the LDV4300D inner cut (−0.00101),
Industrial inner (+0.00208) and DD86-DS2 inner (+0.00367). The table above is this decode with
the change below. The
differential checks fit every field of the clip, so the opening frames weigh little in them:
- `differential_phase` PAL inner 2.80° → 1.18° on Industrial inner, 1.84° → 1.49° on Industrial
  middle; ve-monitor's NTSC 2.27° → 1.67°.
- `differential_gain` PAL on DD86-DS2 inner 0.044 → 0.059 (0.42× → 0.56×). Its warm-up adopts
  +0.00367, and the clip ends before the commit path trims it to the +0.00320 it reached before.
- The LDV4300D inner cut's `gain_ratio/NTSC` 0.53× → 0.38×, and its multiburst packets about 0.06×
  of their bands either way.
- Dolby Surround inner's 12.5T luma bar reads 48.51 IRE where it read 48.47 and passes; its entry
  is deleted, and the default list holds 114.

**The first frame written once the servos agree (2026-10-21).** With no pass, the warm-up used to
run its whole 40-field budget on most cuts: the video EQ only counted as decided once it adopted,
and a disc that needs no EQ never adopts. It now also stops for an EQ estimate inside its
dead-band, and waits for the 2T servo until four fields decoded at its level would hold it there.
The nine cuts that ran the full 20 frames now write after 4–8, pal-cvbs after 9.5 and ve-monitor
after 5.5. DD86-DS2 inner waits 14.5 frames for its servo to reach −1.0, where stopping on the EQ
alone would have written it at −0.711. The first frame carries the same parameters as before on
every other cut, Industrial inner's DG slope aside (+0.00188 where it was +0.00208). The table
above is this decode. What moved is what the 20-frame budget had been settling as a side effect:
- The DG phase decision. It needs 16 staircase fields, which 40 fields of warm-up reached and 4–8
  frames do not, so it is taken a few frames into the decode again. The differential-phase gains
  credited to the slope change above were this: Industrial inner 1.18° → 2.79° (0.54×), Industrial
  middle 1.49° → 1.84°, ve-monitor's NTSC 1.67° → 2.27°, all back where they were before it and
  inside their band.
- The later steps of slow servos. A smaller pool carried into the decode moves the 2T servo
  sooner, inside the four fields per parity the levels are averaged over: DD86-DS1 outer steps to
  −1.0 at field 6 rather than 12, and its 4.0 MHz packet reads 1.38 dB over the reference (1.07
  before); Industrial outer takes a step to −0.225 that it did not take before, and its
  second-field 2T reads 103.15 IRE (102.64). DD86-DS2 inner's first frame goes out with the
  chroma-band ceiling at −1.428 where 20 frames trimmed it to −1.293, and its 100 % bar reads
  42.70 IRE (43.84). Three entries are recorded or re-recorded, and the default list holds 116.
- pal-cvbs is six frames, so the 20-frame budget had been calibrating it from frames it never
  writes; the ceiling's 0.000 → 0.066 lift found there is not reached, the first-field 4.0 MHz
  packet reads 25.50 IRE against its 25.7 edge, and the clip's pinned count is 6 of 46.

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
across all eighteen cuts, the chrominance an average keeps of what its members carried is:

| Cut | First parity | Second parity |
|---|---|---|
| `ggv1011-side1` (PAL), all three radii | no chrominance on the VBI | 0.999–1.000 |
| `industrial-lv-side1` (PAL), all three radii | no chrominance on the VBI | 1.000–1.000 |
| `domesday-ds2-community-north` (PAL), all three radii | no chrominance on the VBI | **0.101–0.359** |
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
nothing measured on these eighteen cuts lies between 0.36 and 0.999. A refusal is printed and
carried in the JSON context rather than showing only as a smaller field count. Only the three
Domesday second-parity cuts refuse; the other thirty-three parities keep their four-field average,
and the chrominance they report is the single-field reading to within the noise the averaging
removes.

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

The tables above used to judge one multiburst packet of six. The other five declined: one below the
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

**Neither term re-measures as it was derived.** On the current decoder the within-capture spread
is 0.294 dB on the first GGV1069 capture (at 3.58 MHz) and 0.406 dB on the second (at 3.0 MHz).
The pressing-to-pressing gap went up and has come back down. The third edition read it at 3.71 dB
at 4.0 MHz inner and 3.59 dB at 4.8 MHz, because the inverse-MTF ceiling fix had removed
GGV1011's share of the 4–4.8 MHz peak and left Domesday's standing. The ceiling now also winds the
inverse MTF negative where the multiburst authorises it (`_imtf_ceiling` in `decoder.py`), which
takes Domesday's peak back out, and the widest gap at one radius and one nominal is now 1.18 dB,
at 4.8 MHz inner, with Domesday the lower of the two:

| Nominal | Band | GGV1011 | DD86-DS1 | DD86-DS2 |
|---|---|---|---|---|
| 4.0 MHz | inner | −0.26 dB | — | +0.54 dB |
| 4.0 MHz | middle | +0.02 dB | — | +1.06 dB |
| 4.0 MHz | outer | +0.07 dB | +0.73 dB | +0.44 dB |
| 4.8 MHz | inner | +0.52 dB | — | −0.66 dB |
| 4.8 MHz | middle | −0.01 dB | — | +0.71 dB |
| 4.8 MHz | outer | +0.10 dB | +0.20 dB | +0.12 dB |

All three decoded by the same tree at the same setting. Only the DD86-DS1 outer cut is in the
sample set; the inner and middle decodes the third edition showed beside it for comparison were
not repeated.

An earlier edition of this table read +0.98 / +1.47 dB for GGV1011 outer and +2.90 / +3.88 dB for
DD86-DS1 outer. Both were the inverse-MTF correction running above what the multiburst justifies,
and both went away when the chroma-band ceiling was given its own publication schedule — see
[`vits-servos.md`](vits-servos.md). GGV1011 is inside ±0.52 dB from 0.5 to 4.8 MHz at every radius in
this edition, and DD86-DS1 outer inside +0.73 dB.

**The allowance is held at 1.25 dB rather than re-derived.** Re-deriving from 3.71 dB would put it
near 4 dB and forgive exactly the readings it exists to catch, which AGENTS.md § 15 forbids.
Deriving instead from the frequency where the pressings still agree — 0.52 dB at 0.5 MHz, the only
other out-of-band packet PAL carries — would give about 0.85 dB, but a 0.5 MHz packet says nothing
about the medium's spread at 4.8 MHz, where it is certainly larger. 1.25 dB lies between the two
and is the figure the earlier, less corrected decoder supported. With the Domesday peak now taken
out the gap is 1.18 dB, inside it, so the question no longer presses; it is still not re-derived.

Two pressings could not settle this. With one peaking and one flat there was no way to tell which
was the disc and which was the decoder, and the two Domesday pressings do not even agree with each
other away from the inner radius. What the derivation needed was a **third unrelated PAL pressing
carrying a Figure 8 multiburst**.

**That pressing is now in the sweep.** `industrial-lv-side1-*`, Pioneer's Industrial
LaserDisc/LaserVision System disc, was added on 2026-09-02 to give the PAL gates a non-Domesday
second image, and it carries a multiburst at every radius. What it says is in the table below. The
derivation it unblocks is Phase 8 work and is not attempted here; the allowance still stands at
1.25 dB and the excess is still a fault to explain.

### What the eighteen cuts read

| System | Packet | Range | Cuts | Verdict |
|---|---|---|---|---|
| NTSC | 0.5 MHz | +0.61 … +0.76 dB | 2 | pass, 12 of 12 |
| NTSC | 3.0 MHz | −0.29 … +0.12 dB | 2 | pass, 12 of 12 |
| NTSC | 3.58 MHz | +0.18 … +0.58 dB | 2 | pass, 12 of 12 |
| NTSC | 4.1 MHz | −0.15 … +0.23 dB | 2 | pass, 12 of 12 |
| PAL | 0.5 MHz | −0.32 … +0.50 dB | 9 | pass, 9 of 9 |
| PAL | 4.0/4.2 MHz | −0.26 … +1.06 dB | 9 | pass, 9 of 9 |
| PAL | 4.8 MHz | −0.66 … +0.71 dB | 9 | pass, 9 of 9 |
| PAL | 5.8 MHz | −10.51 … −4.10 dB | 9 | **fail, 9 of 9** |

The NTSC rows are twelve readings — three field lines × two parities × the two cuts that carry an
admissible multiburst, both at the inner radius — so they say nothing about radius. The PAL rows
are one reading from each of nine cuts.

No in-band verdict fails on PAL. On NTSC one does, and only on the second GGV1069 capture; see
`multiburst_flatness` above.

**The third pressing settled the 4–4.8 MHz peak against the decoder's accusers.** Split by disc,
the two bands the first edition attributed to the decoder read, in the third edition and in this
one:

| Packet | GGV1011 | Industrial LaserVision | Domesday DD86-DS2, third edition | Domesday DD86-DS2, this edition |
|---|---|---|---|---|
| 4.0/4.2 MHz | −0.26 … +0.07 dB | −0.06 … +0.39 dB | +0.47 … **+3.58 dB** | +0.44 … +1.06 dB |
| 4.8 MHz | −0.01 … +0.52 dB | −0.45 … +0.28 dB | +0.25 … **+4.03 dB** | −0.66 … +0.71 dB |
| 5.8 MHz | −8.71 … −7.82 dB | −8.85 … −7.85 dB | −5.29 … −3.30 dB | −10.51 … −4.10 dB |

Two unrelated pressings — a Pioneer calibration disc and a Pioneer industrial disc, cut on
different equipment — are flat to within 0.52 dB across 4.0 to 4.8 MHz at every radius. In the
third edition all four failures there were Domesday DD86-DS2, and DD86-DS1 was clean at the one
radius the sample set carries it. A deviation that two unrelated pressings do not share is not the
decoder's, which is the criterion this section set for itself: **the peak at 4–4.8 MHz is
Domesday's mastering.** The decoder now takes it back out, from the disc's own multiburst, so no
reading there fails in this edition — but the verdict on whose peak it is stands.

**The same three pressings convict the decoder at 5.8 MHz.** GGV1011 and Industrial LaserVision
lose 7.8 to 8.9 dB there, agreeing with each other to within 0.6 dB at every radius on discs cut
on different equipment — and by this section's own criterion a deviation two unrelated pressings
share at the same frequency and radius is the decoder's. Domesday read 3.3 to 5.3 dB in the third
edition, less loss and not more; in this edition it reads 4.1 dB at the outer radius and 10.5 dB at
the inner, where the negative inverse-MTF strength that flattens its peak takes the band edge down
with it. The top packet is treated separately below.

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

On the sample set as it stands now — eighteen cuts at the gated default,
decoded with `--exact-speculation` — the PAL 2T pulse passes 10 of 18
readings and the NTSC pulse 3 of 9 (none of 9 in the third edition). The PAL figure is almost entirely the
pressing rather than the decoder: GGV1011 passes 6 of 6, Industrial
LaserVision 3 of 6 and DD86-DS2 1 of 6. See "What the baseline says" for the
full split and for what the servo does about it.

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

| cut | reading | frequency it was measured at |
|---|---|---|
| ggv1011 inner | −7.82 dB | 5.80 MHz |
| ggv1011 middle | −8.71 dB | 5.79 MHz |
| ggv1011 outer | −8.44 dB | 5.79 MHz |
| industrial-lv inner | −7.87 dB | 6.03 MHz |
| industrial-lv middle | −8.85 dB | 6.03 MHz |
| industrial-lv outer | −7.85 dB | 6.03 MHz |
| domesday-ds2 inner | −10.51 dB | 5.88 MHz |
| domesday-ds2 middle | −6.54 dB | 5.90 MHz |
| domesday-ds2 outer | −4.10 dB | 5.90 MHz |

All nine still fail, by 2.9 to 9.3 dB beyond the 1.25 dB allowance. Domesday inner, the best of
the nine in the third edition at −3.30 dB, is now the worst: the multiburst winds the inverse MTF
negative there to take out the disc's 4–4.8 MHz peak, and the inverse MTF is broadband.

GGV1011 outer reads 2.0 dB worse here than it did before the chroma-band ceiling was given its own
publication schedule, and that is the honest number rather than a regression: the inverse-MTF is
broadband, so a correction wound past what the chroma band justifies was propping up the top packet
as a side effect. Removing an unjustified lift is not allowed to be judged by the packet it
happened to flatter.

**The third pressing breaks the frequency explanation and supplies the evidence this section said
it lacked.** With two discs the disc reading *worse* was the one whose packet sat **lower** in
frequency — the opposite of what a passband edge would do, which is why the top packet is excluded
from the pressing-to-pressing term above. Industrial LaserVision carries its top packet higher than
either, at 6.03 MHz, and reads −7.9 to −8.9 dB: essentially the same as GGV1011 at 5.79 MHz. In
the third edition Domesday, sitting between them at 5.88 MHz, read 4 dB better than both. Loss is
therefore not a function of where the packet sits, and the ordering that looked like a paradox
with two discs is simply not a trend.

What is left is the criterion this document set for itself. **Two unrelated pressings — Pioneer
GGV1011 and Pioneer's Industrial LaserVision disc, cut on different equipment and carrying their
top packets 0.24 MHz apart — lose 7.8 to 8.9 dB there, agreeing to within 0.6 dB at every
radius.** A deviation two unrelated pressings share at the same frequency and radius is the
decoder's, so the ~8 dB is a decoder loss and not a property of the medium. Domesday is the outlier
either way: one pressing mastered with more high-frequency content, which read better at the band
edge for the same reason it read high below it, and now reads 4.1 to 10.5 dB down because the
decoder takes that content back out across the whole upper band.

The residual still is not the filter's, and it is not correctable by one. The inverse-MTF is the
only broadband lift the decoder has; its strength is set by burst amplitude and bounded by the
chroma band, and both say "do not boost". Driving a correction from the top packet would make that
packet its own reference and its own verdict. What has changed is that the fault is now located:
it is the decoder's, on the evidence of two unrelated pressings, and it is Phase 8's to explain.

## What this baseline sends to Phase 8

| Allowance | System | Worst | Where | Reading |
|---|---|---|---|---|
| `multiburst_out_of_band_response` | PAL | 8.40× | 5.8 MHz packet, all nine cuts | Top-end loss beyond the video low-pass; located as the decoder's, on two unrelated pressings agreeing to 0.6 dB. Worst now on Domesday inner, where the negative inverse-MTF strength takes the band edge down |
| `luma_level` | PAL, NTSC | 5.66×, 4.73× | `pulse_2t`, Domesday on PAL and Dolby on NTSC | High-frequency luminance above the EQ's anchor band. The PAL 2T servo is already at or driving to its clip; NTSC's readout model does not run it, and Dolby inner went from over to under on it |
| `chroma_level` | PAL | 5.07× | 5.8 MHz packet, all nine cuts; the 100 % bar and 4.8 MHz packet on Domesday inner | The high-reading PAL chrominance error of earlier editions is gone; what is left reads low |
| `luma_chroma_ratio` | PAL, NTSC | 1.63×, 1.67× | Domesday outer; second GGV1069 capture, middle | Much reduced on both (from 6.69× and 2.46×); the NTSC worst is still the second capture of one pressing |
| `multiburst_frequency` | PAL | 1.69× | Industrial LaserVision top packet, all radii | 6.03 MHz against a 5.8 MHz nominal on a packet already 8 dB down; disc nominal or measurement bias is not yet separated |
| `chroma_level` | NTSC | 1.42× | FCC multiburst 1.25, 3.0 and 4.1 MHz packets, both GGV1069 captures | The readout model reads the upper luminance band lower (27 failing readings, from 11; the zero's floor adds six on the 4.1 MHz packet); only measurable where the FCC multiburst is |
| `chroma_nonlinearity` | PAL | 1.19× | Domesday middle only | Marginal, one radius, and on the unaveragable parity |
| `blanking_level` | PAL | 1.17× | GGV1011, all radii | The pedestal offset Phase 4 found, confirmed across the side |
| `multiburst_flatness` | NTSC | 1.04× | FCC multiburst, second GGV1069 capture | Was 0.46× when one capture carried the only reading; see "What the baseline says" |
| `differential_gain` | PAL | 1.01× | GGV1011 inner | Marginal, one reading; was 3.22× on Domesday. NTSC passes (0.85×) |

`differential_phase` and `level_ceiling` have left the list: both hold on both systems.

Two of these — `luma_chroma_ratio` and `chroma_nonlinearity` on PAL — have their worst readings on
the Domesday second parity, which the coherence gate refuses. They are single field measurements and
the least trustworthy rows in the table; the same rows swung by an order of magnitude between two
pressings of the same title in the second edition.

The second edition ended this section by saying that a PAL disc whose second parity *can* be
averaged would be worth more here than any decoder change. `industrial-lv-side1-*` is one: its
second parity coheres at 1.000 at every radius, and it is a pressing unrelated to both GGV1011 and
Domesday. Set beside the others, in this edition (third edition in brackets), it reads:

| Allowance | GGV1011 | Industrial LaserVision | Domesday DD86-DS2 |
|---|---|---|---|
| `luma_chroma_ratio` | 0.55× (0.48×) | 1.06× (0.97×) | **1.63×** (6.69×) |
| `differential_gain` | **1.01×** (1.28×) | 0.86× (1.84×) | 0.86× (3.22×) |
| `differential_phase` | 0.44× (0.73×) | 0.54× (1.03×) | 0.61× (2.13×) |
| `level_ceiling` | 0.96× (0.97×) | 0.98× (0.98×) | 0.98× (1.31×) |
| `chroma_nonlinearity` | 0.51× (0.51×) | 0.47× (0.41×) | **1.19×** (1.11×) |

In the third edition Domesday sat at twice to seven times either of the others on all five, and
this section read that as the single-field fallback showing through. The fallback has not changed —
Domesday's second parity still refuses averaging — and three of the five rows now read alike on all
three discs. So most of that gap was the decoder's Domesday chrominance error, read through a
single field, rather than the fallback itself. `luma_chroma_ratio` and `chroma_nonlinearity` still
single Domesday out, by less, and remain the rows this table should trust least until a Domesday
pressing arrives whose second parity can be averaged.

`differential_gain` no longer survives the comparison as a PAL fault: Industrial LaserVision reads
0.86× where it read 1.84× on a cleanly averaged parity, and what fails is one GGV1011 reading at
1.01×.

Two rows arrived in the third edition with the fifth and sixth discs rather than with any decoder
change, `multiburst_flatness` on NTSC and `multiburst_frequency` on PAL, and both are still here.
They are the two allowances "What the baseline says" records losing, and they are the return on
adding a second image behind gates that had only one. One row is this edition's own cost:
`chroma_level` on NTSC, which the readout model made worse while it improved the NTSC gain ratio
and 2T pass rate.

None of these is a reason to widen an allowance. Every one of them is a measurement that has to be
explained (AGENTS.md § 15).
