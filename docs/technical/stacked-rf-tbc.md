# Stacked RF and the read-time TBC

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

This page describes the multi-capture stacking and the read-time time-base
correction: what they do, how they work, and what they cost. The command
line is in the [command reference](../user-guide/command.md).

## Why

Two things limit a decode of one capture: the noise of that capture, and the
artefacts that every copy of a disc carries (the player's own clock lines,
the audio carriers' crosstalk into the video carrier, the chroma that leaks
into the RF baseband).

The first is fixed by reading more than one capture of the same disc and
combining them. The second is not: the leak is on the disc, or in the
player, so it is the same in every copy and averaging does not remove it.
It has to be taken out of the signal.

## The shape of it

Everything happens in the RF domain, before demodulation. A decode reads a
single RF stream, whatever produced it:

```
capture 1 ─┐
capture 2 ─┼─► pass 0 ──► pairing ──► timeline ──► combine ──► corrections ──► RF
capture 3 ─┘   (lines)    (VBI codes)  (positions)  (weights)    (3 of them)
```

The decoder itself is unchanged: it reads that stream and demodulates it as
usual, so its sync, VBI, dropout and resampling stages are the same code
either way. The output keeps its formats; only the RF it is decoded from changes.

## Pass 0: the lines, straight from the RF

The decoder normally locates the lines in the *demodulated* video. The
read-time TBC needs them a step earlier: it has to know where to read the
RF before it has demodulated anything.

So a first pass locates the lines directly from the RF. During a sync pulse
the carrier sits at its lowest frequency, so a coarse frequency estimate is
enough to find every pulse. Each horizontal sync is then refined the way the
decoder refines it: the 50 % crossing of the leading edge, then the colour
burst's phase (least squares at the colour subcarrier). The lines are
placed on a grid, the fields are counted, and the vertical interval's lines
carry the Philips code that identifies the frame.

The pass never demodulates, so it has no MTF calibration, no VITS and no
redo: it is a measurement of the RF, nothing more. On a full capture it
finds the same fields, the same parities and the same frame codes as the
decoder's own pass, with slightly less line-to-line noise (0.091 samples rms
against 0.101, at 75 MHz).

On PAL the lines lock onto the 3.75 MHz pilot the sync tip carries, not
onto the burst: the pilot is on every line, the burst only on some.

## Pairing the captures

A capture's frame is identified by its VBI frame code: the CAV picture
number and the CLV time code. Two captures of the same disc give the same
code for the same frame, so the code is what pairs the fields.

The pairing is deliberately conservative:

- a secondary capture's field is only examined once that capture is finished
  or has moved more than 16 fields past it;
- if the same code appears again within those 16 fields, the code is
  ambiguous and the field is left unpaired, rather than paired wrongly;
- a primary field is only laid down once every secondary capture either
  knows its code or has been paired past it.

An unpaired capture contributes nothing at that instant, and the others
carry on.

## The timeline

The primary capture's lines define the timeline: each anchor holds an ideal
time and, for each capture, its absolute position there. Between two
anchors the position is linear.

Two details matter:

- the anchors are placed to **half a line**, because a field overlaps the
  next by a few lines and each line must be kept once, in order;
- a capture whose line length differs from the primary's by more than 2 %
  is left out of that segment. That is the first alignment guard: a capture
  that jumped cannot be read at the primary's positions.

## Combining: the phase lock and the weights

Every output sample is read from every capture, at that capture's own
position for that instant, with a Kaiser-windowed sinc (32 taps) for the
full signal and a 128-tap analytic filter for the video band.

**The phase lock.** The FM carrier keeps its coherence over a lag, while the
band's noise loses it. Correlating a signal with itself delayed by that lag
therefore measures the carrier alone, blind to the noise level: a dropout's
noise, however loud, does not pass for a carrier. The measured rotation
aligns the captures on the video carrier.

**The guards.** A measured rotation is only trusted where it means
something:

- the *geometric* guard above (2 % of line length);
- the *coherence* guard: where the two captures' carriers are not clean over
  the window, the coherence says nothing about the alignment, so the
  capture fades out instead of being rotated wrongly;
- a zero-phase prior, which dominates when the measured rotation is noise:
  pass 0 aligns the captures to within a few hundredths of a radian.

**The weights.** Each capture is weighted by `1/sigma^2`, the inverse of its
noise floor measured in the band where nothing of the disc lives. On top of
that, the adaptive weight follows the carrier's amplitude sample by sample,
so a capture that drops out stops contributing and the others carry the
sample. The samples are normalised by the sum of the weights, so a stack
never amplifies what it reads.

The phase lock is applied to the **video band only**. The rest of each
capture (the EFM and the analog audio carriers) is summed as read: a lock
tuned on the video carrier would be wrong there.

## The three corrections

All three run on the combined stream, before the decoder sees it, and with
`--tbc_mode resample` on the capture's own stream (see "Resample: the RF
cleaned first" below).

In both modes each capture is centred first: its DC offset, its mean over
2 Mi samples a quarter into it (`stack.capture_dc`), is taken out of the
samples it is combined and cleaned from, and the primary's is put back on
the stream (the decoder ignores it). The corrections read zero past the
chunk and the capture, so an offset left in makes a step there that moves
their fits, and the same disc was cleaned otherwise from a signed capture
than from an unsigned one. A `.r30` (10-bit values on 512) decoded up to 35
levels away from the same samples in a `.s16`, 89 % of them off. Centred,
it decodes to the `.s16`'s bytes, with every correction on, once two more
roundings that followed the capture's scale or offset are gone:

- the offset is on a grid of 2^-32 and measured over a power-of-two span,
  so it is exact for integer samples, scales with them, and the stream of a
  source with nothing to cancel is the capture to the last bit;
- the stream's chunks are kept in double precision (the reference keeps
  f32): in single precision a sample's rounding carried the offset (512 in
  a `.r30`), and 2 % of the `.tbc` was a level off;
- the chroma leak's band filter puts the RF through a real FFT of its own:
  carried as the imaginary part of the instantaneous frequency's transform
  (the reference's), its rounding followed the frequency's magnitude (some
  1e7 Hz), and the fit moved with the RF's scale (6449 samples off, up to 6
  levels).

On `ggv1069-side1-outer`, a signed capture whose offset is 2 % of its RMS,
the centring moves 7.6 % of the `.tbc`'s samples (0.08 levels on average,
a level at the 99th percentile), and leaves the carriers' lines where they
were (+0.76 and +0.96 dB over the floor, against +2.78 and +3.27 uncleaned).
Against the cleaned resample before them, the three changes cost 4 %
(`ggv1069-side1-outer`, 4.72 to 4.54 frames/s) to 9 % (`ve-monitor`, 7.15 to
6.49) of its speed with `-t 4`, and the decoder's process some 165 MB of
read-ahead. What the cleaning itself costs, against the RF left as it is, is
in "The limits" below. The reference
implementation does not centre its captures. Pass 0's line locator reads
the captures as they are.

### The audio carriers' crosstalk

The analog audio carriers leak into the video carrier's phase. The leak is
the same on every copy of a disc, so no amount of stacking removes it.

What shows in the picture is a line at each carrier's own frequency that
follows the carrier's phase (rev 8's `--audio_carrier_cancel` model, which
takes it out of the demodulated video). It is what the **decoder's** video
filter and readout compensation make of the crosstalk's sidebands: the
compensation lifts the upper sideband over the lower, and the pair, which
the optics' roll-off had left as much amplitude as phase, demodulates as a
line. So the RF is looked at through the decoder's own filter (built by rev
8's `RFDecode`, with the decode's options), at the readout level measured on
the capture as the decoder's MTF servo starts from it (the colour burst's,
or PAL's pilot burst's, two first sidebands on the lines pass 0 locates,
through the readout model to a cutoff and a level). On that view, per chunk:

- each carrier the disc carries (its band 5 times the spectrum beside it;
  a digital-only disc's EFM there is not chased) gives the phase
  reference, its band cut out of the RF and reduced to a unit phasor -
  provided the capture's coupling to it is steady (below);
- the line locked to it is fitted on the demodulated video taken down
  around the carrier (the picture elsewhere stays out of the fit), its
  amplitude following the video level, and backed off when the same model
  fitted off frequency explains as much (dsp.coherent_line_estimate);
- the phase the lines integrate to is taken off the view, and the change
  goes back to the RF through the filter's inverse, above 3.0-3.6 MHz
  (NTSC; PAL its band split), so the decoder's compensation finds nothing
  left to lift.

Which carriers are corrected at all is decided once per capture. The
crosstalk is the disc's and the player's, so its coupling is the same all
through a capture; what the picture puts near a carrier by chance is not.
The same fit is made on eight chunks spread over the capture, and a carrier
is corrected when the coupling of the chunks where it is modulated spreads
under 25 % of the pooled one (over at least two of them), and the pooled fit
stands over its off-frequency controls. A silent carrier is a pure tone, which
a still picture's line can match, so silent chunks are pooled but not judged,
and a carrier silent throughout is left. On RF_Reference the couplings
spread 2 and 4 %; on `ggv1011-side1-middle` (a test disc's still picture) the
0.684 MHz carrier's spread 69 %, its phase turning from chunk to chunk, and
correcting it chunk by chunk had raised the noise by 0.018 IRE (61 fields,
paired: 13 standard errors); left, it is the RF as it is.

Measured (blank-line noise in IRE; the lines in dB over the spectrum beside
them), the RF as it is against the cancellation: RF_Reference (NTSC, 40
MHz) 1.256 to 1.208, lines 1.7/5.2 to 0.1/0.7; an NTSC capture at 75 MHz
1.112 to 1.023, lines 2.0/6.8 to 0.2/0.7; `ggv1069-side1-inner` 0.892 to
0.885; `ggv1011-side1-middle` (PAL) 1.131 to 1.131 (no carrier steady);
`ggv1011-side1-inner` 1.580 to 1.576; `industrial-lv-side1-outer` 3.268 to
3.275 (its one steady carrier corrected: 0.007 IRE, the one loss). Rev 8's
canceller on the same captures: 1.209, lines removed; 0.885; and, made to
run on PAL, 1.168 and 1.594. The model this replaced (one gain per carrier
fitted on the instantaneous frequency of the stack's own video band) took
half the lines out and raised PAL's noise: 1.238, 0.936, 1.294, 1.677.

It costs about 5 s on a 30-frame decode at 40 MHz (27 s to 32 s on
`ggv1011-side1-inner`, `-t 1`): about 2 s once for the decoder's filter and
the level, then 270 ms per 2 Mi-sample chunk (three transforms of the chunk
and the fits), on each of the cleaning's four processes, which keep ahead of
the decoder.

### The clock lines

The player's EFM decoder crystal (16.9344 MHz) leaves its multiples of the
192nd (88.2 kHz) in the capture; the player's 4fsc video clock and the
capture board's clocks leave theirs. They are narrow lines that stand at one
frequency all through the capture.

They are found in four stretches spread over the capture: a line must be at
least 10 dB over the local floor in all of them, and a local maximum of its
neighbours. The stretches run from the capture's first located line to its
end, so the detection covers the part of the capture that carries a picture.
The crystal's drift is followed with a Goertzel recurrence every 2^16
samples, so the line stays where it is.

What is deliberately left out: the bands where the disc's own signal makes
steady lines (the audio carriers, the chroma leak's band, the video
carrier's swing), anything above 14.5 MHz (nothing the decoder reads reaches
that high), and **any line with another one a line frequency away** - a
still picture's RF is a comb, and without that guard a PAL still picture
produced 183 false lines.

**Every line found is then checked before it is subtracted.** A stretch of
2^21 samples is about a field and a half: the disc's speed hardly moves
there, so a line the disc itself carries looks as narrow as a clock, and on a
short capture all four stretches fall in the same picture. On the ~1 s
`testdata/radius` cuts the detection accepted 54 to 87 lines, most of them
the picture's; subtracting them raised the blank-line noise of
`ggv1011-side1-inner` from 1.68 to 2.18 IRE. The check, which needs no
time-base correction and so is the same in both modes:

- **Narrow over long stretches.** Four stretches of at least 8 frames (2^24
  samples at 40 MHz, or what the capture holds). Over several rotations the
  spindle's speed variations spread a line the disc carries, while a clock
  stays narrow: the line's peak must hold 12 % of the power within 64 bins
  of it in its three central bins, in every stretch. The disc's line at
  0.97 MHz on `ggv1011-side1-inner` wanders by about ±500 Hz from one
  stretch of 2^21 samples to the next, and holds 5 to 10 % over the long
  ones; the clocks hold 16 to 94 %.
- **Outside the disc's sensitive bands.** The EFM (up to 2 MHz) and the
  analog audio carriers are continuous signals of the disc's that nothing in
  the video interrupts: the lines in their bands are left.
- **Not cut by the sync.** Each line's amplitude, in phase with it, is folded
  on the position in the line and accumulated over the lines pass 0 locates
  in the stretches (at least a field). A clock runs through the sync and the
  blanking unchanged; what the video makes is interrupted every line. A
  line is left only where the fold is clear (in-phase amplitude 8 times the
  quadrature's, falling below 30 % of its mean somewhere in the line); one
  too weak to judge is kept on the stretches' word.

The LD-V4300D's satellites go with its master line, kept or left: they are
the sidebands of one modulated clock, less narrow than the master, and the
master subtracted without one of them raised the noise of
`industrial-lv-side1-outer` from 3.25 to 3.46 IRE.

Measured on four PAL cuts (blank-line noise, IRE: without the clock lines,
before the check, with it): `ggv1011-side1-inner` 1.68, 2.18, 1.68;
`ggv1011-side1-middle` 1.29, 1.62, 1.28; `domesday-ds2-community-north-inner`
2.55, 2.56, 2.53; `industrial-lv-side1-outer` 3.25, 3.32, 3.26. The domesday
cut's 69 lines kept of 75 are nearly all on the crystal's grid.

Measured: **+0.09 dB** at 75 MHz, 37.41 to 37.55 dB at 40 MHz where more
lines fold into the band, neutral in a stack (the captures' lines, at
unrelated phases, already average down).

The lines are measured over a super-block of 2^22 samples, in one pass: the
phasors of all the lines are taken over all the blocks of the super-block at
once, and the subtraction reuses the same tables of exponentials from one
piece to the next. That is **177 Msamples/s** for the measurement and
**17.5 Msamples/s** for the subtraction, on one core.

### The disc's own lines: `--disc_lines`

A clock that leaked into the signal at mastering is on the disc: it follows
the disc's speed, spread in the capture's time and narrow on the disc's, and
the clock lines above leave it (they take what is narrow in the capture's
time). `--disc_lines` takes it out, with the read-time TBC only (an error with
`resample`, which never reads the RF on the disc's timeline); it is off by
default.

It is found on the primary capture, read on its own located lines over four
stretches of at least 8 frames (pass 0 run on each, so it needs no pass 0 over
the whole capture), and a line is taken only on every count: narrow on the
disc's timeline in every stretch and 10 dB over the floor; spread in the
capture's time; outside the EFM's and the audio carriers' bands; no neighbour
within 30 dB a line, frame or field rate away (the picture's combs); and,
folded on the position in the line as above, **shown** continuous through the
sync (in-phase amplitude 8 times the quadrature's, never below 70 % of its
mean). A line too weak to be judged is left: what is taken from the disc's own
signal must be shown not to be the picture. Each line is subtracted from each
chunk of the combined stream, its phasor measured over the chunk with the
phase referenced to the stream's first sample, so a sample gets the same
value whatever order the chunks are computed in.

Measured on three NTSC captures (a 20-minute side at 40 MHz, 60 s at 40 MHz,
11 s at 75 MHz): the lines narrow on the disc's timeline were the captures'
clocks, the picture's combs, the EFM and the audio carriers; none passed the
tests (the log says "none found"), and the decode with `--disc_lines` (20
frames, `--tbc_mode read`) is the same, byte for byte, as without. On a synthetic capture whose disc wanders by 1e-4, a 3.1 MHz clock
leaked on the disc is found to 5 Hz and nothing else is, even with the comb
test turned off (the video's 528 comb teeth are then candidates, and the fold
leaves every one).

### The chroma leak

On NTSC the composite chroma leaks into the RF baseband around the colour
subcarrier. It beats with the video carrier and makes the fine wavering
vertical stripes of saturated areas - the "colour wobble" the player's own
output shows.

The chroma is the video band's instantaneous frequency through the band; the
RF's same band is fitted on it with a 13-tap filter, and the fit is
subtracted. The fit is only applied where it explains at least 5 % of the
band's power, so a disc (or a stretch) without the leak is left byte for
byte as it was.

Measured: the bump at 4.73-4.95 MHz over its neighbours goes from **+5.8 dB
to -0.2 dB**, and the VITS measures do not move - it removes an artefact,
it does not smooth the picture.

## On real captures

The pass 0 and the clock lines were checked against the reference
implementation on real NTSC captures at 75 MHz (ten seconds of signal
each, a disc segment captured three times over).

- **The fields.** The pass 0 finds the same number of fields as the
  reference: 646 on the primary capture of the reference stack, 852 on the
  longest one, every one of them with its frame code, and the parities
  alternating all the way.
- **The lines.** The line grid comes out at 4767.16 samples a line (the
  reference says 4767) and 273 lines a field, the overlap into the next
  field included (263 without it). The jitter of the lines about their
  own grid is **0.085 samples rms**, against the reference's 0.091.
- **The clock lines.** The crystal's frequency, the multiples subtracted
  and the other steady lines are the same as the reference's on all
  eighteen captures of the reference stack, to the kilohertz.

The stacking itself was then run on three captures of the same segment
(809 M samples each at 75 MHz), with the three corrections on:

- **The build.** The pass 0 over the three captures, the clock lines'
  detection and the pairing of the fields took **57 s**, that is 43 M
  samples a second over the 2.4 G samples of the three captures.
- **The read.** The virtual stream runs at **0.54 M samples/s** on one core
  (1488 s for the whole 809 M samples of the stream). The synthetic captures
  used for the figures below are close to four times quicker: they carry no
  clock line, and the subtraction of the clock lines is a fifth of the time.
- **The result.** The stacked stream comes out at 4798 rms over its whole
  length. On the primary capture, the band the disc carries nothing in
  (16-19.5 MHz) holds 50 rms equivalent against 4417 rms for the whole
  signal: nothing stands in an empty band.
- **The lines, once removed.** Measured on the primary capture, the fifteen
  lines the reference subtracts are dropped by **31 to 59 dB** (43 dB in
  the middle): what is left of them is the numerical floor.

## Against the reference implementation

The reference implementation (the Rust rewrite) was built on this machine and
run on the same captures, so the two could be compared on the same data: the
same eighteen captures, the same 75 MHz, the same `--tbc_mode read`.

- **The clock lines.** The same eight multiples of the EFM decoder's crystal
  and the same seven other steady lines, to the kilohertz, on all eighteen
  captures.
- **The stack's weights.** The noise floor each capture is weighed by comes
  out identical on all eighteen (2.4954e4 and 4.0073e-5 for the capture with
  the least noise, 3.6393e4 and 2.7478e-5 for the one with the most).
- **The RF the decoder reads.** The two streams are aligned to the sample:
  **94 %** of the samples are bit for bit the same on the stack of the
  eighteen captures, the difference has an rms of **0.27** over a signal of
  4864 (**85 dB** down), and the correlation is 0.9999999984. (Before the
  step-by-step comparison below, it was 54 % and an rms of 1.0.)
- **The picture.** The same fields, in the same order, with the same VBI
  codes (the VBI rows are identical, one for one), the same CLV timecode
  and the same sync confidence: **42.4 dB** of PSNR and a correlation of
  0.9984.
- **Where the last half of a decibel goes.** The same difference appears on
  the reference's own path (`--tbc_mode resample`), which this port does not
  touch: it is the difference between the two demodulators, not between the
  two stacking implementations. The reference is bit reproducible run to run
  (two runs of the same command differ by nothing), but its own output moved
  by 270 rms when its stack was made faster, in November.
- **The noise floor.** The reference's demodulator carries **2.2 dB less**
  noise in the 6-10 MHz band of the picture than this decoder's (89 600
  against 115 300), at 40 MHz as well as at 75 MHz: that is the demodulator,
  not the rate.
- **The chroma burst.** The reference measures the burst at 15.0 IRE and this
  decoder at 20.0, in both modes: the two demodulators agree on everything
  else (the sync confidence, the EFM's timing values, to 0.1 %) and not on
  the burst's level.

The comparison found one bug on this side, and it was a blocking one: the
decoder was not told the rate of the virtual stream, and looked for the sync
pulses of a 2542-sample line in a stream whose lines are 4767 samples long.
It found none, and decoded nothing at all.

The reference decodes the eighteen captures in 880 s (645 fields); this port
takes about 19 s a frame for the same result, the demodulator being the
reference implementation's own.

## Step by step with the reference implementation

The reference implementation (the Rust rewrite) is the source of truth for
every one of these features: this port follows it step by step, and the steps
were compared one by one against it.

What follows is that comparison, and what it changed.

### The steps, and where each one lives

| step | the reference | this port |
| --- | --- | --- |
| the line location (pass 0) | `rfsync.rs` | `lddecode/rf_sync.py` |
| the field pairing and the timeline | `stack.rs` (`Live::advance`) | `lddecode/stack.py` (`build_timeline`) |
| the plan of the reads | `stack.rs` (`Inner::plan`) | `lddecode/stack.py` (`_plan`) |
| the filters (the sinc and the video band) | `stack.rs` (`sinc_lut`, `video_band_lut`) | `lddecode/stack.py` (`sinc_lut`, `video_band_lut`) |
| the carrier's measure and the phase lock | `stack.rs` (`carrier`, `lock`) | `lddecode/stack.py` (`carrier_measure`, `phase_lock`) |
| the combination of the inputs | `stack.rs` (`combine_fixed`, `compute_task`) | `lddecode/stack.py` (`_combine`) |
| the clock lines' detection and subtraction | `stack.rs` (`CrystalLines`) | `lddecode/stack_corrections.py` (`CrystalLines`) |
| the audio carriers' crosstalk | `stack.rs` (`cancel_crosstalk`) | `lddecode/stack_corrections.py` (`cancel_crosstalk`) |
| the chroma leak | `stack.rs` (`cancel_chroma_leak`) | `lddecode/stack_corrections.py` (`cancel_chroma_leak`) |

The order of the operations is the reference's: the clock lines are subtracted
from each capture as it is read, before the filters; the inputs are combined
after; the crosstalk is cancelled, then the chroma leak, on the combined
stream. The decoder is told the rate of the virtual stream, and demodulates it
after all of it.

### What the comparison found

The comparison of each step against the reference's source, and the
translation of the reference's formulas into Python to compare them output
against output, found these differences. All of them are fixed.

- **The line's length.** The reference uses the line's own length
  (227.5e6 / fsc, 63.5555 us); this port used a rounded 63.5 us. The line
  grid was therefore off by 4 samples a line at 75 MHz, and the pass 0's
  tracker started from the wrong grid.
- **The windows of the pass 0.** The reference reads its windows with the
  low bound included (a horizontal sync is 3.6 to 6.2 us wide, the low bound
  included; the VBI candidates are the lines 6 to 14 lines after the broad
  pulse, 14 excluded). This port had them the other way round on the low
  bounds, and included the high bound of the VBI window.
- **The broad pulse of the vertical sync.** The reference resets it at every
  chunk of the scan, so the VBI candidate lines are the ones that follow a
  broad pulse of the same chunk. This port kept it across the chunks.
- **The damaged lines.** The reference decides the whole set of them at once,
  on the positions as measured: a line dropped out of the way does not change
  its neighbours' verdict. This port dropped them one by one, so a dropped
  line did change the verdict of the next.
- **The rounding.** The reference rounds half away from zero everywhere (the
  carrier's lag, the filter's fractional phase, the half-line step of the
  timeline, the peak's bin, the pivot of a solve). This port rounded half to
  even in those places. On an exact half, the two choose different sides.
- **The leak's subtraction.** The reference subtracts the leak in double
  precision and rounds once; this port rounded the leak first and subtracted
  it in single precision, rounding twice.

### What it cost

On one capture, the RF the two decoders read, compared sample by sample:

| | before | after |
| --- | --- | --- |
| bit-for-bit identical samples | 38.5 % | **92.7 %** |
| rms of the difference | 4.451 | **0.635** |
| correlation | 0.999999504 | **0.999999990** |

On the stack of the eighteen captures, over the first chunk of the stream:

| | before | after |
| --- | --- | --- |
| bit-for-bit identical samples | 53.9 % | **93.8 %** |
| rms of the difference | 1.001 | **0.272** |
| over a signal of | 4822 | 4864 |
| ratio | 73.7 dB | **85.1 dB** |
| correlation | 0.99999998 | 0.9999999984 |

The picture itself did not move: it is still 42.4 dB of PSNR against the
reference, because what is left of the difference is the difference between
the two demodulators (the reference is on revision 7 of the reference
decoder, this one on revision 8), not between the two stacking
implementations. The RF the decoder reads, on the other hand, is now the
reference's to within 0.6 rms on a signal of 4471, and to within 0.3 rms on
the stack of eighteen captures.

### What is still not the same

- **The precision.** The reference's stack works in single precision, this
  one in double. The filters and the phase lock are the reference's
  `exact` path (the one `--preset slow` takes), but the reference's default
  path is not, and its demodulator is a different one.
- **The order of the summations.** The reference's sums over a task of 65536
  samples, this port's over a chunk of 2^21: the same sums, rounded
  differently, to about 1e-13.
- **The features the reference does not have.** The `.rfx` container and
  `--recompute-tbc` are not ported, nor the `--preset` choice (the GPU's
  precision is `--device_precision` instead).

## What the branch adds, and what rev 8 adds

The reference implementation this port follows is not rev 8. Its decoder crate
(`crates/ld-decode/src/`) is byte for byte the upstream 7.4.0 decoder: its
first commit says "bit-exact vs python 7.3.0", and its PAL work targets
"ld-decode 7.4". `git diff upstream/main vrunk11_main -- crates/ld-decode/src`
is empty. Everything the branch adds lives in the CLI crate, next to the
decoder.

So the two bodies of work are disjoint, and the question "what is mine, and what
is rev 8's" has a clean answer.

### The branch's own commits

79 commits sit outside `upstream/main`: 10 merges, 9 exploratory spikes (Claude,
design notes and a NumPy prototype), and 60 substantive ones. They fall into:

| group | commits | what it does |
| --- | --- | --- |
| the stack and its command line | 30 | the RF pass 0, the virtual source, the timeline, the read-time TBC, the weights, the three cancellations |
| the containers | 9 | the LDX container, the `.rfx` archive |
| the decoder | 7 | PAL, the pass 0's shortcuts, the GPU demodulator |
| the fixes and the tests | 5 | the input rate in the EFM PLL and in the `.efm` band-pass |
| the docs and the CI | 5 | the branch's own documentation |
| the GPU and the performance | 3 | the OpenCL stack, the double precision demodulator |

Two of the fixes (`e923c39`, `58f28bc`, the input rate in the EFM PLL and in the
`.efm` band-pass) are already in the branch's `main`. The PAL parity work
(`13610d5`, `d1a7555`, `a24df84`) and the OpenCL demodulator (`e09bbf3`) sit in
the branch's other branches, and are not in `upstream/main`. This port keeps
the PAL work out of scope (the Python decoder already has the PAL path); the
OpenCL demodulator is ported, on rev 8's `demodblock` (see "The demodulator on
the GPU").

### What rev 8 has that the reference port does not

Rev 8 is not a revision of the same idea, it is a different set of servos.
The ones that matter for interference and for the picture:

| feature | option | in the reference port |
| --- | --- | --- |
| the timing-based EFM demodulator (the default since rev 8) | `--efm_demod timing` | no, it only has the 7.4 PLL |
| the 2T MTF servo | `--no_mtf_servo` | no, it has the 7.4 b/w ratio |
| the auto chroma (the inverse MTF, calibrated on the burst) | `--no_auto_chroma` | no |
| the multiburst video EQ servo | always on | no |
| the chroma DG servo | `--no_chroma_dg` | no |
| the VITS white level servo | `--vits_white_level` | no |
| the RF echo cancellation (the multipath ghost) | `--rf_echo_cancel`, `--rf_echo` | no |
| the coherent subtraction of the V4300D clock | `--V4300D_coherent_subtract` | no |
| the audio carrier cancellation | `--audio_carrier_cancel` | removed: replaced by the branch's model, on by default in both modes (below) |
| the dropout record (metadata, no masking) | `--noDOD` | yes |
| the AGC | `--noAGC` | yes |
| the group delay equaliser, the audio carrier notches, the zero phase RF | always on | yes |
| the CVBS output and its sidecars | `--cvbs` | no |

All of them are in this repository, because this repository is rev 8. None of
them has to be ported: they are the decoder's own work, and it runs on the
virtual stream like it runs on a plain capture.

### The interference cancellations, and who owns what

The three cancellations this branch ports are not in rev 8, and rev 8's own
ones are not in the reference port. Two of them meet: the audio carriers'
crosstalk, and the V4300D's clock.

| cancellation | rev 8 | this branch | the reference port |
| --- | --- | --- | --- |
| the audio carriers' crosstalk | `--audio_carrier_cancel`, on the demodulated spectrum (opt-in prototype, NTSC; replaced) | its model, on the RF seen through the decoder's filter, in both modes (NTSC and PAL; by default) | yes, in both modes |
| the clock lines | no | yes, in both modes | yes, in both modes |
| the chroma leak | no | yes, in both modes | yes, in both modes |
| the RF echo (the ghost) | yes (`--rf_echo_cancel`) | no | no |
| the V4300D clock | `--V4300D_coherent_subtract` (PAL; out of the help) | the clock lines (NTSC and PAL), its satellites included | the master clock alone |
| the audio excursion blanking | yes | inherited | yes |
| the demodulator clipping | yes | inherited | yes |
| the dropout record | yes | inherited | yes |

**The crosstalk** is cancelled by default in both modes, by one model and
one piece of code, `stack_corrections.cancel_crosstalk`, and
`--no_audio_carrier_cancel` leaves it in either. On each chunk of the stream
(2 Mi samples), the line each audio carrier puts in the demodulated video is
fitted on the RF seen through the decoder's own filter and readout
compensation, and its phase is taken off the RF before the demodulator (see
the audio carriers' crosstalk, above). With `--tbc_mode read` the stacked
source does it on the RF it hands over; with `--tbc_mode resample` the
cleaned source does it on the capture's RF (below), as the reference
implementation's `--tbc resample` does since it cleans the RF too.

Rev 8's canceller, an opt-in prototype (`--audio_carrier_cancel`, NTSC),
fitted the lines on each block's demodulated spectrum and subtracted them
there. Its model is the one above; what changes is where it acts. In the RF,
before the decoder's readout compensation, the correction is lifted with
the crosstalk instead of after it, it is the same in both TBC modes (the
decoder never sees the crosstalk), and it runs on PAL, where rev 8's could
not (the slice it centres between PAL's carriers starts below 0 Hz). The
earlier model of this branch, one gain per carrier fitted on the
instantaneous frequency of the stack's own video band over the whole chunk,
is gone: fitted on a flat band it measured the crosstalk's phase there, not
what the decoder's compensation makes of it, and the picture across the
band entered its fit.

Every decode a VITS conformance test reads (the "vits" label's cuts and
captures, and the functional lane's `ntsc-cvbs` and `pal-cvbs`) leaves the
RF as it is (`--no_audio_carrier_cancel --no_crystal_lines --no_chroma_leak`,
`VITS_DECODE_FLAGS` in `cmake_modules/LdDecodeTests.cmake`), as the decoder
ran when its known deviations were recorded; the cancellations are tested by
their own unit tests. A small correction moves rev 8's servos: on
`ve-monitor` the decoder-level crosstalk model moved the multiburst's 2 MHz
packet by 0.01 dB, the video EQ's estimate sits on its 0.3 dB dead-band
there, and the EQ adopted at frame 5 instead of frame 2, so the opening
fields the lane averages were decoded without it (2T 97.73 to 97.41 IRE,
past its recorded deviation). A servo's first move after the calibration
warm-up is not rate-limited, so it lands a few frames into the output,
inside the fields the lane averages. Reordering the warm-up so that it
decides for the first frame was tried and moved thirteen cuts' readings,
some far (the 2T of `domesday-ds2-community-north-middle` to 79.8 IRE): a
change to rev 8's calibration and its recorded deviations, not to this one.

**The V4300D's clock** is the EFM crystal's 96th multiple (192 x 44.1 kHz =
8.4672 MHz), and the clock lines take it with the crystal's other multiples,
on NTSC as well as on PAL; rev 8's subtraction is PAL only. Its satellites,
88.2 and 176.4 kHz either side, stand only a few times over the floor: on the
GGV1069 capture read on a V4300D (NTSC) the 94th and 95th multiples are 9.6
and 5.3 times over it, against 2.1 and 2.6 on another player. Where the
master clock is found, the satellites are kept from 3 times the floor (rev
8's threshold), unless a still picture's comb explains them; the reference
kept none of them. So the clock lines cover what `--V4300D_coherent_subtract`
does, on any player and either system. That option is left out of the help:
in either mode it warns and is left to the clock lines, unless
`--no_crystal_lines` leaves them in (then it acts, on PAL).

The option is the test the clock lines are held to: found on their own,
they must do at least what it does on the player it was written for. On the
three PAL cuts of `industrial-lv-side1` read on a V4300D (blank-line noise,
IRE, the decoder's MTF and chroma servos held so that only the RF differs;
paired change over 61 fields): inner 1.753, the option -0.285, the clock
lines -0.373; middle 1.594, -0.027, -0.089; outer 2.511, -0.011, -0.039.
With the servos running, on a 30-frame cut, the outer one read +0.315: the
calibration had not settled when the input ended (its MTF level at -0.027
against -0.111 without the lines), so the frames were decoded at another
level; on a cut that short a servo's trajectory, not the RF, can make the
difference.  Each line's phasor is measured block by block (2^16 samples):
fitting one amplitude and a linear phase over each super-block instead
gained a little on PAL and lost on the V4300D's modulated NTSC clock
(`ggv1069-side1-ldv4300d-inner`, -0.081 to -0.069), so it is not done.

### Resample: the RF cleaned first

As the reference implementation's `--tbc resample` does, `--tbc_mode
resample` takes the three out of the capture's RF before the decoder reads
it, on a timeline that maps each sample to itself (`stack.CleanedSource`,
the reference's `Live::identity`): the same chunks, the same clock-line
subtraction, crosstalk and chroma-leak cancellations as the stacked source,
then the decoder's own resampling of the demodulated video. With all three
left in, the decoder reads the capture through its usual loader, and the
output is the reference decoder's to the byte.

Where it differs from the reference's, for rev 8:

- **The rate.** Rev 8's resample loader resampled a capture taken at another
  rate (`-f`) to 40 MHz with ffmpeg. It no longer does: in either mode, cleaned
  or not, the decoder demodulates at the capture's own rate (`-f`, else the
  sidecar's, else 40 MHz), as the reference implementation does and as the
  read-time TBC always did. So no option changes the rate the decoder works
  at, and a 40 MHz capture with all three left in is still the reference
  decoder's to the byte.
- **The read.** On a timeline that maps each sample to itself the stack's
  sinc read is the sample (its phase is always zero), so it is skipped; the
  analytic video band the cancellations need is the stacked source's at
  phase zero, computed as one convolution by FFT (the filter is the same at
  every sample), the same to 5e-11 of 2e4.
- **The producers.** The chunks are cleaned by four processes, each with its
  own reader and its own clock lines rebuilt from the ones detected (a
  `CrystalLines` keeps a reader and a cache of its own, which neither cross
  a process boundary nor are safe to share between threads). On threads of
  the decoder's own process they held its interpreter from the decode: in
  one session, a resample of `ve-monitor` ran at 5.2 frames/s cleaned on one
  thread, 6.4 on four threads and 8.1 on four processes. These were
  measured before the DC centring, with the decoder's default thread count;
  the current figures, with `-t 4`, are in "The limits" below.

The clock lines are detected a quarter into the capture, at most 4 Mi
samples from its end (the reference's `min(len / 4, len - 2^22)`), where
there is picture. Every capture is read at positions (`fileio.open_capture`):
raw, packed (`.lds`, `.r30`, through the decoder's own unpackers) and
compressed (`.ldf`, `.flac`, through its FLAC reader, which seeks in the
stream; the reference indexes the FLAC frames itself). stdin is buffered to
a temporary 16-bit file first, removed when the run ends, unless resample
leaves all three in. There is no fallback between the modes: a capture that
cannot be read at positions, a cleaning that cannot run, or a read-time TBC
that finds no lines is an error, which says how to decode the RF as it is.

### What the stacking cannot fix

Most interference is either per capture (the noise, the dropouts, the level) or
is removed by the pass 0 (the timing, the drift, the wow). The stacking
handles those on its own. Two are not covered, because they are identical on
every copy of the same disc:

- the **RF echo**: the ghost is deterministic per capture, and stacking makes
  it worse, since ghosts of different delays average into a blur. Rev 8's
  cancellation is the answer, and it belongs in the pass 0, before the
  stacking.
- the **disk's own colour errors**: the chroma DG and the video EQ are
  properties of the disc, and they are in rev 8 already.

The V4300D's clock is on every copy too, but the clock lines take it out of
each capture as it is read (above). The RF echo is the only rev 8
cancellation worth bringing into the stacking path.

## The decoder at the capture's rate

Rev 8's capture loaders resampled the RF to 40 MHz, so its decoder had only
ever run at that rate, and three of its stages held it as a constant. This
branch hands it the captures' own rate, in either mode, where all three were
wrong.
The reference implementation had the same three, and fixed them in its
decoder (`e923c39`, `58f28bc`); they are ported here the same way. At 40 MHz
each one is the value it was, bit for bit.

- **The EFM PLL** (`--efm_demod pll`) took its channel bit period as 40 MHz
  over the bit rate whatever the input: 9.26 samples where 75 MHz has 17.35,
  far outside its +-10 % window, so it never locked. It now takes the input
  rate. The default timing demodulator already followed it.
- **The EFM band-pass** was built against a 20 MHz Nyquist frequency: at
  75 MHz its 20 kHz-1.6 MHz band moved to 37.5 kHz-3 MHz, and let the 2.3 MHz
  audio carrier into the EFM at full level. It now uses the input rate's
  Nyquist frequency.
- **The block's end cut** was the filter delay, 32 samples. The analog
  audio is cut by `cut // audio_fdiv`, and at 75 MHz `audio_fdiv` is 64: a
  block was 495.5 audio samples long, so the audio drifted half a sample per
  block against the video. The cut is now rounded up to a multiple of
  `audio_fdiv` (64 at 75 MHz, still 32 at 40 MHz).

## Pass 0, alongside the decode

As in the reference, the pass 0 runs alongside the decoder's reads: one scan
per capture feeds its fields to the timeline as it finds them
(`LiveTimeline`, the reference's `Live`), and a chunk of the stream waits
only for the anchors it needs. When the decode stops, so does the pass 0, at
its next chunk: a `--length 10` decode of an hour of RF locates a few seconds
of it, not the hour.

The reference runs each scan on a thread. Here each scan of a raw capture
runs in a process of its own, which opens the capture by its name and sends
its fields back: the scan is Python and NumPy, and eighteen scans on threads
of the decoder's own process held its interpreter from the stream's
computation. Measured on the eighteen captures of the reference stack (75
MHz, 10 s each), the read of the stream went from 0.69 M samples/s with the
scans on threads to 1.94 once the scans in processes are over; they are over
85 s after the start, having located 13.8 G samples. While they run, they
hold most of the cores, and the stream runs slower.

The pairing is the reference's live one. A secondary capture's field is
examined once that capture is finished or 16 fields past it; a primary field
is laid down once every secondary knows its code, has been paired past it, or
is finished. A code that repeats further than 16 fields on is seen after its
first field was paired, and does not undo that pairing. Where a secondary
skips back, the moment the last condition is met can depend on how far each
scan has gone, as it can in the reference.

## How the decoder reads the stream

The stream reaches the decoder through the loader protocol, as a capture
does, with two properties it relies on:

- **The samples are float64**, neither rounded nor clipped (the reference
  hands its decoder f32; see "The three corrections" for why not here). A
  stack carries finer steps than any one capture, and an unsigned 16-bit
  capture reads up to 65535, past the int16 range.
- **The end of the stream is a short read**: the decoder takes a read that
  returns fewer samples than asked as the end of its input.

The read-ahead keeps its chunks by use, not by position: with `-t N` the
decoder's field jobs read several fields ahead of its own inline reads, and
a buffer that only kept what lies behind the newest read would compute the
same chunks again. The decoder serialises its raw reads under one lock, so
the source serves one reader at a time.

## What it costs

The pass 0 reads the capture once more (it runs alongside the decode, and
stops where the decode stops), and
the corrections run on every chunk. On a 2^21-sample chunk the crosstalk's
cancellation takes about 270 ms (three transforms of the chunk, through the
decoder's filter, and the fits) and the chroma leak's about 8.5 ms.

Measured on this machine (one core, NumPy 2.5, Numba 0.68), on synthetic NTSC
captures, before the stages below were compiled:

| stage | rate | an hour of RF at 75 MHz (270 M samples) |
| --- | --- | --- |
| the line location (the pass 0) | 27 M samples/s at 40 MHz, 34 M at 75 MHz | 8 s |
| the clock lines' detection (once per capture) | 7 M samples/s | 40 s |
| the stacking (the read of the virtual stream) | 2 M samples/s | 2 min 15 s |

On a real capture, which carries the clock lines to subtract, the read of the
virtual stream runs at **0.54 M samples/s** instead (8 min 20 s for an hour
of RF), and the build of the stack at 37 M samples/s.

The check of the lines found, added since, reads four stretches of 2^24
samples (at 40 MHz) and runs the line location over them, a few seconds per
capture whatever its length. It pays for itself where it leaves lines: on
`ggv1011-side1-inner` (`-t 1`) the default decode went from 41 to 28 s, 22
lines subtracted instead of 87.

### On every core

The figures above are the first port's, on one core. The reference runs its
CPU path over every core; the port now does too, for the three stages that
weighed most. They are compiled kernels in `lddecode/stack_kernels.py`, each
checked against the vectorised version it replaced (kept as
`_read_input_reference`, `_combine_reference`, `CrystalLines.clean_reference`):

- **the read of each capture**: the sinc and both halves of the video band in
  one pass over the taps, instead of three;
- **the combination**: the carrier measure, the phase lock, the guard and the
  weights, sample by sample. The running sums behind the windowed measures
  are taken per block of 8192 samples, from the first sample the block's
  windows reach, so the blocks run in parallel. The blocks are fixed, so a
  sample's sums do not depend on the number of threads;
- **the clock lines' subtraction**: piece by piece, each piece between two
  seeds of the super-block.

Every output sample is computed on its own from the same terms, so a chunk
comes out the same whatever the number of threads. Measured on synthetic NTSC
captures at 75 MHz carrying five clock lines each, with the three corrections
on (32 threads, NumPy 2.5, Numba 0.68):

The plan no longer builds every sample's position: it hands each capture's
per-segment law (`a0`, `slope`) to the kernels, which compute the positions
themselves, as the reference's GPU kernel does, and the span each capture is
read over comes from the segments' ends. The audio crosstalk's narrow bands
and correction, and the measure of the clock lines on each super-block (one
pass over the samples for every line), are compiled kernels as well.

| captures | one core, vectorised | every core | OpenCL, double | OpenCL, single |
| --- | --- | --- | --- | --- |
| 3 | 0.64 M samples/s | **5.5 M samples/s** | 5.7 M samples/s | **6.7 M samples/s** |
| 18 | - | **2.0 M samples/s** | 1.7 M samples/s | **3.2 M samples/s** |

## On a GPU: `--device opencl`

As in the reference, `--device opencl` reads every capture at its own
positions and combines them on an OpenCL device (`lddecode/stack_opencl.py`,
the reference's kernels less the 16-bit code input of its `.rfx` archives).
The clock lines are subtracted on the host before the samples are sent, and
the cancellations run on the host after. The positions are computed on the
device in double precision from each segment's law; the dot products and the
combination run in `--device_precision single` (the default) or `double`.

Measured on the synthetic captures above, against the host's compiled path:
the double precision stream differs by 9e-5 rms over a signal of 2206 (147 dB
down; 71 % of the float32 samples are the same bit for bit), the single
precision one by 2.5e-4 rms (139 dB down). On a consumer GPU, whose double
precision runs at a small fraction of its single precision, `double` is no
quicker than the host; `single` is the one that pays, and pays most with many
captures, since the read and the combination grow with them while the rest
does not. It needs pyopencl (`pip install 'ld-decode[opencl]'`) and an OpenCL
driver; the GPU with the most compute units is taken, or the one
`PYOPENCL_CTX` names. In the Nix environment pyopencl comes with the package
and the development shell, where nixpkgs builds it; outside NixOS, point its
driver loader at the system's drivers with `OCL_ICD_VENDORS=/etc/OpenCL/vendors`.

### The demodulator on the GPU

`--device opencl` also runs the decoder's block demodulation on the device,
in either mode (`lddecode/demod_opencl.py`), as the reference's `--gpu-fast`
runs its 7.4 decoder's: rev 8's `demodblock`, a batch of blocks at a time.
On the device: the block's FFT, the RF high-pass and EFM products and their
inverses, the video band (RF video filter, PAL carrier notch, MTF), its
inverse at half rate, the discriminator, and the video channels' filters
(the crosstalk is taken out of the RF before the decoder reads it). On the host: the PAL carriers' presence and the
analog audio's first stage, read off the block's spectrum by `demodblock`'s
own code (`RFDecode.audio_stage1`). The FFTs are radix-8/4/2 Stockham
transforms with twiddles tabulated in double precision, and the precision
is the host's: double up to the discriminator, single for the video
channels, after it has been centred on blanking.

The decoder hands the device whole windows (`RFDecode.demodblocks`): the
read of a field's window in the main process, and in each worker process
the blocks of its field job not yet in its cache. The CPU stays the
reference and the fallback: the opt-in RF echo cancellation and the V4300D
coherent subtraction run there, and a device that cannot be opened or fails
sends the blocks back to it, once, with a warning.

Against the CPU, on 64 blocks of `ggv1069-side1-outer` (NTSC) and
`ggv1011-side1-middle` (PAL): the video channels within 1 Hz
(a float32 ulp at the carrier's frequency), `demod_raw` the same, the RF
high-pass, the EFM and the analog audio the same; 0.66-0.76 ms a block on an
RTX 5080 Laptop GPU against 4 ms on one core. A whole decode differs in
0.01-0.02 % of its output samples, by 1 LSB. On one thread ve-monitor decodes
at 7.2 frames/s against 3.8; on every core both reach 8.1, where the main
process, which validates and writes the fields, is the limit.

## On the real captures, after the changes above

The eighteen captures of the reference stack (NTSC, 75 MHz, 10 s each, 13.8 G
samples in all), with the three corrections on, on a 32-thread CPU and an
RTX 5080 laptop GPU:

| | CPU | OpenCL, single |
| --- | --- | --- |
| the stream, once the pass 0 is over | 1.94 M samples/s | 2.44 M samples/s |
| 15 frames, from the start | 110 s | 101 s |
| the whole stack (646 fields) | - | **548 s** |

The reference decodes the same stack in 880 s (645 fields). The picture is the
previous port's to 78-80 dB of PSNR (a median over the fields), so the changes
above changed what it computes by rounding only; the GPU's is the host's to
105 dB. Against the reference it is 41.8 dB over the first ninety fields, and
35.5-36.7 dB from there on: that drop is in the previous port's output too,
field for field, and starts where rev 8's own servos (the MTF level, the auto
chroma) settle, so it is the two decoders that differ there, not the stacks.

The pass 0 costs the same whether it is used for the stacking or on its own:
it is a measurement of the RF, and it is over long before the decode is.

## The limits

- **One sample rate.** Every capture of a stack must be at the same rate.
- **Only when asked for.** `--tbc_mode resample`, the reference's way, is
  the default whatever the input; the read-time TBC runs only with
  `--tbc_mode read`, which stacking several captures needs. Where it cannot
  run (no lines found) it is an error: the decode never changes mode on its
  own.
- **Not the reference's bytes, unless asked for.** The corrections remove
  the three interferences above, so by default neither mode produces the
  reference decoder's output. `--tbc_mode resample` with
  `--no_audio_carrier_cancel --no_crystal_lines --no_chroma_leak` reads the
  capture through the decoder's usual loader and keeps its bytes for a 40 MHz
  capture.
- **What the cleaning costs.** The default resample cleans the RF in four
  producer processes: with `-t 4`, `ve-monitor` decodes at 6.5 frames/s
  against 8.4 left as it is, and `ggv1069-side1-outer` at 4.6 against 5.3;
  the decode's processes peak at 2.6-3.0 GB against 1.25-1.3 GB.
- **The field's position.** A field decoded from the virtual stream is
  reported at its position in that stream (`diskLoc`, `fileLoc` in the
  `.tbc.db`), where the reference reports the position in the primary
  capture. The virtual stream starts at the capture's first located line, so
  the two differ by the length of the lead-in.
