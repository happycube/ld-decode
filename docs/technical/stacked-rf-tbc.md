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
  **94 %** of the samples are bit for bit the same on the stack of the
  eighteen captures, the difference has an rms of **0.27** over a signal of
  4864 (**85 dB** down), and the correlation is 0.9999999984. (Before the
  step-by-step comparison below, it was 54 % and an rms of 1.0.)
- **The picture.** The same fields, in the same order, with the same VBI
  codes (the VBI rows are identical, one for one), the same CLV timecode
  and the same sync confidence: **42.4 dB** of PSNR and a correlation of
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
- **The pass 0 runs before the decode.** The reference runs the pass 0
  alongside the decode, and the virtual stream waits for the lines it needs.
  This port runs the pass 0 over the whole capture first. The timeline is the
  same, but the reference stops the pass 0 when the decode stops, and this
  port does not.
- **The features the reference does not have.** The `.rfx` container and
  `--recompute-tbc`, the `--device opencl` path and the `--preset` choice
  are not ported.

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
them out of scope: the Python decoder already has the PAL path, and OpenCL is
out.

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
| the audio carrier cancellation | `--audio_carrier_cancel` | replaced, in a better place (below) |
| the dropout record (metadata, no masking) | `--noDOD` | yes |
| the AGC | `--noAGC` | yes |
| the group delay equaliser, the audio carrier notches, the zero phase RF | always on | yes |
| the CVBS output and its sidecars | `--cvbs` | no |

All of them are in this repository, because this repository is rev 8. None of
them has to be ported: they are the decoder's own work, and it runs on the
virtual stream like it runs on a plain capture.

### The interference cancellations, and who owns what

The three cancellations this branch ports are not in rev 8, and rev 8's own
ones are not in the reference port. They do not overlap, except in one place.

| cancellation | rev 8 | this branch | the reference port |
| --- | --- | --- | --- |
| the audio carriers' crosstalk | after demodulation, on the demodulated spectrum, NTSC only | before demodulation, on the RF's instantaneous frequency, NTSC and PAL | yes, the same as this branch |
| the clock lines | no | yes | yes |
| the chroma leak | no | yes | yes |
| the audio carrier intermodulation lines | yes (`--audio_carrier_cancel`) | no | no |
| the RF echo (the ghost) | yes (`--rf_echo_cancel`) | no | no |
| the V4300D clock | yes (PAL) | no | no |
| the audio excursion blanking | yes | inherited | yes |
| the demodulator clipping | yes | inherited | yes |
| the dropout record | yes | inherited | yes |

The crosstalk is the one that meets. Rev 8's `--audio_carrier_cancel` fits a
complex gain per audio carrier on the demodulated spectrum, NTSC only. The
branch's cancellation fits the same gains on the RF's instantaneous frequency
over the video band, before the demodulator, in NTSC and PAL. It removes the
phase of the leak as well as its amplitude, and it is what the stacked stream
needs: the leak is the same on every copy, so stacking averages it out
instead of removing it.

### What the stacking cannot fix

Most interference is either per capture (the noise, the dropouts, the level) or
is removed by the pass 0 (the timing, the drift, the wow). The stacking
handles those on its own. Three are not covered, because they are identical on
every copy of the same disc:

- the **RF echo**: the ghost is deterministic per capture, and stacking makes
  it worse, since ghosts of different delays average into a blur. Rev 8's
  cancellation is the answer, and it belongs in the pass 0, before the
  stacking.
- the **V4300D clock**: the reader's 8.4672 MHz clock is on every copy. The
  clock lines detection does not take it, because it looks for the lines of
  the capture, and it leaves that band out.
- the **disk's own colour errors**: the chroma DG and the video EQ are
  properties of the disc, and they are in rev 8 already.

The first two are the only rev 8 cancellations worth bringing into the
stacking path.

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
