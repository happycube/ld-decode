# VITS conformance: what is checked, and against what

Many LaserDiscs carry test signals in the vertical blanking interval. They were
put there so a player, a transfer chain or a broadcast feed could be measured
against a published shape rather than judged by eye, and they serve the same
purpose here: they are the only part of a decode whose correct answer is
written down in a standard.

[`analysis/vits_conformance.py`](https://github.com/happycube/ld-decode/blob/main/analysis/vits_conformance.py)
finds those signals in a decoded `.cvbs` capture, measures every element of
them, and judges each measurement against the specification's own tolerance
plus a decoder allowance. It prints one of

```
VITS CONFORMANCE: PASS (...)
VITS CONFORMANCE: FAIL (...)
VITS CONFORMANCE: SKIPPED (no VITS detected)
```

so CTest can gate on it, and `--json` writes every check as a sidecar for CI
to keep.

## The signals

| Identifier | System | Frame line (field line) | Status | Normative source |
|---|---|---|---|---|
| `pal-its-field1` | PAL | 19 (19) | permitted | IEC 60856-1986 9.1.3 Figure 7 |
| `pal-its-field2` | PAL | 332 (19) | permitted | IEC 60856-1986 9.1.3 Figure 9 |
| `pal-multiburst-field1` | PAL | 20, or 13 (20) | permitted | IEC 60856-1986 9.1.3 Figure 8 |
| `pal-multiburst-field2` | PAL | 333, or 326 (20) | permitted | IEC 60856-1986 9.1.3 Figure 10 |
| `pal-blanked-field1` | PAL | 22 (22) | shall | IEC 60856-1986 9.1.3 |
| `pal-blanked-field2` | PAL | 335 (22) | shall | IEC 60856-1986 9.1.3 |
| `ntsc-virs-field1` | NTSC | 19 (19) | shall | IEC 60857-1986 9.1.3 |
| `ntsc-virs-field2` | NTSC | 282 (19) | shall | IEC 60857-1986 9.1.3 |
| `ntsc-ntc7-composite` | NTSC | 20 (20) | recommended | IEC 60857-1986 9.1.4 |
| `ntsc-ntc7-combination` | NTSC | 283 (20) | recommended | IEC 60857-1986 9.1.4 |
| `ntsc-fcc-multiburst` | NTSC | 22 (22) | permitted | `analogue-video-specifications` FCC multiburst |

The PAL multiburst has two homes: IEC 60856-1986 9.1.3 Amendment 2 permits
frame line 13 as an alternative, and the GGV test disc uses it. Matching that is
only possible by content, which is what the identifier does.

IEC 60857-1986 9.1.3 makes the VIRS on lines 19 and 282 the only test *signal*
any LaserDisc standard mandates; the two PAL entries marked `shall` are the
opposite requirement, that those lines carry nothing at all. Everything else
above is carried by convention, which is why the identifier scores measured
content rather than trusting a line number, and why what a disc actually
carries is a surveyed fact rather than an assumption — see "The manifest"
below.

The differential-level and gain-ratio checks take their limits from
ITU-R BT.1439-1 3.3.1.2 and 3.3.1.3 and EBU Tech. 3209 7.2.2.

## What a check is judged against

Each check is `measured` against `nominal ± band`, or against a one-sided
`limit` where the quantity is a ceiling. `band` is the specification's own
tolerance plus a **decoder allowance**: what a correct ld-decode may add on top
of a correct disc.

The allowances live in
[`analysis/vits_reference.py`](https://github.com/happycube/ld-decode/blob/main/analysis/vits_reference.py)
as `DECODER_ALLOWANCES`, each carrying its own rationale and the measurement it
came from. They are derived, not chosen: a measurement floor, a servo's
dead-band plus the residual it is recorded leaving, or an end-to-end figure two
unrelated pressings disagree by. [`vits-servos.md`](vits-servos.md) documents
the servos, and [`vits-radius-baseline.md`](vits-radius-baseline.md) records
what each allowance actually had to hold across six discs and three radii.

**An allowance is never widened to make a check pass.** A failing check is a
fault to diagnose or a deviation to record; see AGENTS.md §15.

## The manifest

A conformance run on a capture that carries no NTC-7 insertion test signal
finds no NTC-7 checks to make and prints a pass. Nothing was wrong, but the
summary line reads exactly as it would if both disc and decoder were perfect —
the checks that mattered were never attempted and nobody can tell.

`testdata/vits-manifest.json` closes that. It records, per capture, which VITS
the disc actually carries, surveyed with
[`analysis/vits_inventory.py`](https://github.com/happycube/ld-decode/blob/main/analysis/vits_inventory.py)
rather than assumed from a line number. With `--manifest`:

- a signal the manifest does not record is **skipped by name**, and counted as
  skipped in the summary line;
- a signal the manifest records and the decode does not find is a **failure**,
  because losing a signal the disc carries is the regression this exists to
  catch;
- a capture the manifest does not mention at all is **refused** with exit
  status 2, because an unsurveyed capture and a survey that has gone stale look
  identical from here.

## Known deviations

The decoder has faults it has not closed yet — the PAL 5.8 MHz multiburst
packet, the 2T pulse, the luma/chroma gain ratio. Registering the radius sweep
in CI put seventy-six failing checks behind the build, and a permanently red
job proves nothing.

They are listed instead, by name, one entry per failing check per capture, in
[`analysis/vits_known_deviations.toml`](https://github.com/happycube/ld-decode/blob/main/analysis/vits_known_deviations.toml).
Passed as `--known-deviations`, a listed check reports `KNOWN` and does not fail
the build. Everything else about the list is arranged to make it shrink:

- a listed check that now **passes** fails the build, so the entry is deleted in
  the change that fixes the fault rather than left to rot;
- a listed check that spends more of its band than its recorded `ceiling` fails
  the build, so a fault getting worse is still a regression;
- a listed check this run never made fails the build, so an entry cannot outlive
  the check it describes.

`measured` in an entry is what the check read when the entry was written. It is
documentation and is deliberately never compared against: a figure that must be
updated on every unrelated decode change is a figure nobody keeps true. The
`ceiling` is recorded at 1.10× the deviation's band usage, so run-to-run
variation is not a failure and a real worsening is.

The list is the **only** mechanism for carrying a known fault. Widening an
allowance would hide it everywhere; marking a test `WILL_FAIL` would swallow
the next regression alongside the known ones.

Entries are recorded from a decode forced to `--exact-speculation`, and the
sweep decodes with that flag for the same reason. Without it the CVBS output
depends on the thread count — which defaults to `min(max(cpu_count - 2, 1), 10)`
and so differs between a developer machine and a CI runner — and a `ceiling`
recorded on one machine is then not a statement about the decoder. Re-record
with the flag, never from a default decode.

## The radius sweep

The modulation transfer function of a LaserDisc changes with radius, so a
decoder can pass every check at one radius and fail at another. `testdata/radius/`
holds eighteen cuts — six discs at 5 %, 50 % and 95 % of their recorded band —
plus `domesday-ds1-community-north-outer`, kept as a regression sample for one
behaviour no other cut has: its multiburst finds the chroma band already flat,
so the video EQ servo declines inside its dead-band and never adopts, which is
the path that once let the burst servo wind unbounded.

Two of the six discs are there so that no gate rests on a single disc image.
`ggv1069-side1-ldv4300d-*` is the same pressing as `ggv1069-side1-*` read on a
different player six years later, which is the only way here to tell a fault of
the decoder from a fault of one capture; `industrial-lv-side1-*` is a
non-Domesday PAL pressing, so a fault of the Domesday mastering and a fault of
the decoder no longer read the same. Two whole captures already in
`testdata/ntsc/` — `ggv-ntsc-mb-v2800` and `ve-monitor` — are judged by the same
lane for the same reason, at no cost in capture data. The FCC multiburst was the
signal that made this necessary: it reached CI on one cut, so
`multiburst_flatness` and `multiburst_out_of_band_response` on NTSC were each
one measurement. See [`vits-radius-baseline.md`](vits-radius-baseline.md),
"What the baseline says", for what the second image changed.

Each cut is decoded to CVBS and judged, as one CTest pair per cut, under the
`vits` label:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release

# The whole sweep
ctest --test-dir build -L vits --output-on-failure

# One cut, with its full output
ctest --test-dir build -R conformance-ggv1011-side1-inner-vits -V

# Everything except the sweep
ctest --test-dir build -LE vits --output-on-failure
```

The decodes take the default `CVBS_U10_4FSC` encoding rather than forcing
`CVBS_U16_4FSC`, so the encoding users actually get is the encoding under test.

In CI the sweep is its own job, `VITS Conformance`, running beside the
functional lane rather than inside it. It uploads the JSON sidecars as an
artefact and renders them into the run summary with
[`analysis/vits_summary.py`](https://github.com/happycube/ld-decode/blob/main/analysis/vits_summary.py):
one row per capture with its totals, and one row per failing check with what it
measured, the band it missed and the clause it was judged under.

## Working on a failure

1. Run the one cut with `-V` and read the measured value against its band. The
   `Band used` column in the CI summary says the same thing as a multiple:
   `1.00×` sits exactly on the limit.
2. Check whether it fails at every radius or only at one. A fault at one radius
   is a servo that is not tracking; a fault at all three is the static chain.
   [`vits-radius-baseline.md`](vits-radius-baseline.md) has the reading each
   allowance had at each radius to compare against.
3. Fix the cause, and delete the deviation entry in the same change. Do not
   widen the allowance.
