# VHS-decode

software defined VHS RF decoder

This is a fork (maybe temporary) of the ld-decode Laserdisc rf decoder.

# Usage

Just like ld-decode, vhs-decode will accept raw data in 8-bit and 10 bit formats.
The current ways used to record this are the domesday duplicator hardware for 10-bit data with a 40 Mhz sample rate,
or a Conexant cx2388x-based PCI video capture card using the custom [cxadc](https://github.com/happycube/cxadc-linux3)
driver with of 8 or 10 bit samples at 28.6 MHz or 35.8 MHz sample rate. 

VHS-decode currently assumes 40 Mhz sample rate by default, use ```--cxadc``` or ```--cxadc3``` 
to set the sample rate for cxadc and cxadc in tenfsc mode respectively

A .r8 file extension is assumed to mean 8-bit data, while other files are assumed to be in the 10-bit format 
the domesday duplicator hardware outputs.

As VHS stores chroma and luma separately, vhs-decode currently 
outputs chroma as a separate .tbc file (with the extension .tbcc).
As the upstream chroma decoders expects composite data, these have to be decoded separately into chroma and luma data,
and combined afterwards.

TODO

# Limitations
As this is in-progress, do not expect great results yet.

Currently standard VHS PAL and NTSC have implementations. The Luma part of SECAM and MESECAM can be decoded as it's the same as PAL,
but a secam color decoder has not been implemented as of now.

Auto-detection of whether a field is read from track/head 1 or 2 is not yet implemented, so if the chroma output is garbled,
try using the --othertrack option which alters the assumed track of the first decoded field.
A VCR will know which track is being read based on what head it has switched to,
but we don't yet have a way of capturing the head switch signal, so auto-detection will require looking at burst phase which is more
complicated.

Only video is handled currently, audio would require separate data streams for hi-fi and linear.

