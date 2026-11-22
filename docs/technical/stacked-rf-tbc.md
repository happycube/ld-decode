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
either way. The output is a better decode, not a different format.

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

All three run on the combined stream, before the decoder sees it.

### The audio carriers' crosstalk

The analog audio carriers leak into the video carrier's phase. The leak is
the same on every copy of a disc, so no amount of stacking removes it.

Each carrier is taken out of the RF itself (mixed down to 0 Hz, narrowed
with three boxcars, mixed back up), and the video band's instantaneous
frequency is fitted on both by least squares: one complex gain each. The
picture does not follow the carriers, so the fit measures the leak. The
frequency error becomes a phase error, and the video band is turned back by
it. The correction is kept above 3.0-3.6 MHz (NTSC), so the audio carriers
and the EFM are left as they are.

Measured on NTSC captures at 75 MHz: **+0.48 to +0.83 dB** weighted SNR
over the reference's resampling. On PAL the audio carriers sit far below the
video, and the correction is neutral.

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

Measured: **+0.09 dB** at 75 MHz, 37.41 to 37.55 dB at 40 MHz where more
lines fold into the band, neutral in a stack (the captures' lines, at
unrelated phases, already average down).

The lines are measured over a super-block of 2^22 samples, in one pass: the
phasors of all the lines are taken over all the blocks of the super-block at
once, and the subtraction reuses the same tables of exponentials from one
piece to the next. That is **177 Msamples/s** for the measurement and
**17.5 Msamples/s** for the subtraction, on one core.

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
same eighteen captures, the same 75 MHz, the same `--tbc read`.

- **The clock lines.** The same eight multiples of the EFM decoder's crystal
  and the same seven other steady lines, to the kilohertz, on all eighteen
  captures.
- **The stack's weights.** The noise floor each capture is weighed by comes
  out identical on all eighteen (2.4954e4 and 4.0073e-5 for the capture with
  the least noise, 3.6393e4 and 2.7478e-5 for the one with the most).
- **The RF the decoder reads.** The two streams are aligned to the sample:
  **54 %** of the samples are bit for bit the same, the difference has an rms
  of **1.0** over a signal of 4822 (**73.7 dB** down), and the correlation is
  0.99999998.
- **The picture.** The same fields, in the same order, with the same VBI
  codes (the VBI rows are identical, one for one), the same CLV timecode
  and the same sync confidence: **42.5 dB** of PSNR and a correlation of
  0.9984.
- **Where the last half of a decibel goes.** The same difference appears on
  the reference's own path (`--tbc resample`), which this port does not
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

## What it costs

The pass 0 reads the capture once more (it runs alongside the decode), and
the corrections run on every chunk. On a 2^21-sample chunk (28 ms of signal
at 75 MHz, three captures) the two corrections that work on the video band
take about 10.5 ms (crosstalk) and 8.5 ms (chroma leak) on the CPU pool.

Measured on this machine (one core, NumPy 2.5, Numba 0.68), on synthetic NTSC
captures:

| stage | rate | an hour of RF at 75 MHz (270 M samples) |
| --- | --- | --- |
| the line location (the pass 0) | 27 M samples/s at 40 MHz, 34 M at 75 MHz | 8 s |
| the clock lines' detection (once per capture) | 7 M samples/s | 40 s |
| the stacking (the read of the virtual stream) | 2 M samples/s | 2 min 15 s |

On a real capture, which carries the clock lines to subtract, the read of the
virtual stream runs at **0.54 M samples/s** instead (8 min 20 s for an hour
of RF), and the build of the stack at 37 M samples/s.

The hot loop of the fractional delay filters, which read every capture at its
own position, runs in Numba, like the demodulator's own. The rest is vectorised
NumPy.

The pass 0 costs the same whether it is used for the stacking or on its own:
it is a measurement of the RF, and it is over long before the decode is.

## The limits

- **Fixed-width raw captures only.** The path reads a capture at arbitrary
  positions, which a compressed capture cannot serve.
- **One sample rate.** Every capture must be at the same rate.
- **The fallback.** Where the read-time TBC cannot run - stdin, a
  compressed capture, no lines found - and where it was not asked for
  explicitly, the decode falls back to the reference's resampling, with a
  warning. An explicit `--tbc-mode read` that fails is an error.
- **Not the reference's bytes.** The read-time TBC and the corrections make
  a better decode than the reference's, so they do not produce the
  reference's output. Use `--tbc-mode resample` when byte parity with the
  reference matters.
- **The field's position.** A field decoded from the virtual stream is
  reported at its position in that stream (`diskLoc`, `fileLoc` in the
  `.tbc.db`), where the reference reports the position in the primary
  capture. The virtual stream starts at the capture's first located line, so
  the two differ by the length of the lead-in.
