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

In some cases, captures from LD-V4300D players in PAL mode have a spurious raw RF signal around 8.46mhz.

Since it is above the white tip of 7.9mhz, it is possible to selectively remove the signal without severe side effects, which is the PAL version of --WibbleRemover.
