# Filter Tuning

These ld-decode parameters can be useful for handling disks with bandwidth issues.  The default settings decode with wide bandwidth which works with most disks, but some require different settings...

--video_bpf_high (in mhz) (defaults: PAL 13.5mhz, NTSC 13.8mhz) - reduce this to 12.2 if you see the herringbone conditions seen in issue 206, and the disk does not suffer from crosstalk.

--video-lpf (also in mhz) (defaults: PAL 4.8mhz, NTSC 4.5mhz) - reduce this on NTSC disks to 4.2 if there's too much noise.

## Dealing with (video) Noise Issues

### NTSC

For pictures like https://github.com/happycube/ld-decode/issues/206:

- Try --lowband first.  This uses a set of filter settings which are better for older disks.

- If that does not work, use --WibbleRemover to reduce color waviness caused by bad data above 4.2mhz.  This has side effects on later/sharper disks, so only use when necessary.


### PAL

Captures from LD-V4300D players of PAL discs with digital audio carry a
spurious raw RF tone at 8.4672 MHz — the player's digital-audio master
clock (192 x 44.1 kHz) leaking into the RF tap — with weaker satellites
at ±88.2 kHz multiples (8.379, 8.555 and 8.644 MHz). It beats against
the video FM carrier (7.1–7.9 MHz) and appears as a wavy pattern in
solid picture areas, strongest in lighter ones.

Since the clock sits above the white tip of 7.9 MHz, it can be removed
selectively: `--V4300D_coherent_subtract` fits and subtracts the clock
line and its satellites coherently, leaving the video sidebands intact.
(`--V4300D_notch_filter` is a legacy alias for the same filter; the
original FFT-bin notch it named — the PAL version of --WibbleRemover —
left the spur's leakage skirts and satellites behind and has been
removed.)

## EFM (digital audio) tuning

The EFM bit-clock PLL has its own acquisition-loop tuning, controlled through
`LDDECODE_EFM_*` environment variables rather than command-line flags — see
[EFM decoding](efm-decoding.md) for the variable table, the defaults, and the
multi-decode ensemble workflow for marginal discs.
