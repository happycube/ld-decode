"""Audio downscaling to 16-bit / 44.1 kHz output.

Split verbatim out of core.py.
"""

import numba
import numpy as np
from numba import njit

from . import utils_logging as logs
from .dsp import dsa_rescale_and_clip, nb_mean


@njit(cache=True, nogil=True)
def _downscale_audio_compute_locs_and_swow(
    lineinfo, line_period, linelen, linecount, timeoffset, freq, scale
):
    """compute locations and wow for audio scaling

    Parameters:
        lineinfo (list(float)): line locations
        line_period (int): Length of a line in usecs
        linelen (int): Length of a line in samples
        linecount (int): # of lines in field
        timeoffset (float): time of first audio sample (ignored w/- frequency)
        freq (int): Output frequency (negative values are multiple of HSYNC frequency)
        scale (int): sample rate decimation factor
    Returns: (tuple)
        locs (np.ndarray(float)): output location of audio sample?
        swow (np.ndarray(float)): offset/wow of sample?
        arange (np.ndarray(float)): "ticks" to align samples to?
        frametime (float): how long a (audio?) frame lasts
    """

    if freq < 0:
        # Override timeoffset value and set frequency to a multiple horizontal line clock
        timeoffset = 0
        freq = (1000000 / line_period) * -freq

    frametime = linecount / (1000000 / line_period)
    soundgap = 1 / freq

    # include one extra 'tick' to interpolate the last one and use as a return value
    # for the next frame
    arange = np.arange(
        timeoffset, frametime + (soundgap / 2), soundgap, dtype=np.double
    )

    locs = np.zeros(len(arange), dtype=numba.float64)
    swow = np.zeros(len(arange), dtype=numba.float64)

    for i, t in enumerate(arange):
        linenum = ((t * 1000000) / line_period) + 1
        intlinenum = int(linenum)

        # XXX:
        # The timing handling can sometimes go outside the bounds of the known line #'s.
        # This is a quick-ish fix that should work OK but may affect quality slightly.
        if linenum < 0:
            lineloc_cur = int(lineinfo[0] + (linelen * linenum))
            lineloc_next = lineloc_cur + linelen
        elif len(lineinfo) > linenum + 2:
            lineloc_cur, lineloc_next = lineinfo[intlinenum : intlinenum + 2]
        else:
            # Catch things that go past the last known line by using the last lines here.
            lineloc_cur = lineinfo[-2]
            lineloc_next = lineloc_cur + linelen

        sampleloc = lineloc_cur
        sampleloc += (lineloc_next - lineloc_cur) * (linenum - np.floor(linenum))

        swow[i] = (lineloc_next - lineloc_cur) / linelen
        # There's almost *no way* the disk is spinning more than 1.5% off, so mask TBC errors here
        # to reduce pops
        if i and np.abs(swow[i] - swow[i - 1]) > 0.015:
            swow[i] = swow[i - 1]

        locs[i] = sampleloc / scale

    return locs, swow, arange, frametime


@njit(cache=True, nogil=True)
def _downscale_audio_to_output(
    arange, locs, swow, audio_left, audio_right, audio_lfreq, audio_rfreq,
    fullscale
):
    """decimate audio to final output samples.

    Parameters:
        arange (np.arange(float)): "ticks" to align samples to?
        locs (np.ndarray(float)): output location of audio sample?
        swow (np.ndarray(float)): offset/wow of sample?
        audio_left (np.array(float)): left channel demodulated audio
        audio_right (np.array(float)): right channel demodulated audio
        audio_lfreq (float): left audio channel frequency
        audio_rfreq (float): right audio channel frequency
        fullscale (float): positive full-scale code (32767 for 16-bit,
            8388607 for 24-bit) - sets the output resolution
    Returns: (tuple)
        output (np.ndarray(int32)): output audio waveform (24-bit-capable;
            the caller narrows to int16 when fullscale is 32767)
        failed (bool): whether there were any failed samples that were muted
    """
    output = np.zeros((2 * (len(arange) - 1)), dtype=np.int32)

    failed = False

    for i in range(len(arange) - 1):
        start = int(locs[i])
        end = int(locs[i + 1])
        if end > start and end < len(audio_left):
            output_left = nb_mean(audio_left[start:end])
            output_right = nb_mean(audio_right[start:end])

            output_left = (output_left * swow[i]) - audio_lfreq
            output_right = (output_right * swow[i]) - audio_rfreq

            # Flipping audio here to line up with ralf/he010 digital sample
            # (when comparing, remove the first 265 samples of ralf.pcm as well)
            output[(i * 2) + 0] = -dsa_rescale_and_clip(output_left, fullscale)
            output[(i * 2) + 1] = -dsa_rescale_and_clip(output_right, fullscale)
        else:
            # TBC failure can cause this (issue #389)
            failed = True

    return output, failed


# Downscales to 16- or 24-bit PCM.  16-bit at 44.1 kHz matches CD/digital
# audio and is the default; 24-bit (bits=24) is used for the CVBS SMPTE 272M
# audio profile, where the demod's sub-16-bit resolution is actually kept.
def downscale_audio(audio, lineinfo, rf, linecount, timeoffset=0, freq=44100,
                    rv=None, bits=16):
    """downscale audio for output.

    Parameters:
        audio (float): Raw audio samples from RF demodulator
        lineinfo (list(float)): line locations
        rf (RFDecode): rf class
        linecount (int): # of lines in field
        timeoffset (float): time of first audio sample (ignored w/- frequency)
        freq (int): Output frequency (negative values are multiple of HSYNC frequency)
        bits (int): Output resolution, 16 (int16) or 24 (int32, 24-bit values)
    Returns: (tuple)
        output (np.array(int)):  int16 (bits=16) or int32 (bits=24) samples
        next_timeoffset (float): Time to start pulling samples in the next frame (ignore if sync4x)
    """

    fullscale = float((1 << (bits - 1)) - 1)

    locs, swow, arange, frametime = _downscale_audio_compute_locs_and_swow(
        lineinfo,
        rf.SysParams["line_period"],
        rf.linelen,
        linecount,
        timeoffset,
        freq,
        rf.Filters["audio_fdiv"],
    )

    output, failed = _downscale_audio_to_output(
        arange,
        locs,
        swow,
        audio["audio_left"],
        audio["audio_right"],
        rf.SysParams["audio_lfreq"],
        rf.SysParams["audio_rfreq"],
        fullscale,
    )

    # int16 for the 16-bit path keeps the .pcm output byte-for-byte as before
    # (values sit within int16 range, so the narrowing is exact)
    if bits <= 16:
        output = output.astype(np.int16)

    if failed:
        logs.logger.warning("Analog audio processing error, muting samples")

    if rv is not None:
        rv['dsaudio'] = output
        rv['audio_next_offset'] = arange[-1] - frametime

    return output, arange[-1] - frametime
