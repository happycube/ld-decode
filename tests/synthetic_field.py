"""Minimally-constructed RFDecode and Field objects for the hermetic lane.

A decoded ``Field`` normally comes out of the demodulator with several
megabytes of sample data behind it, but the coordinate maths, the line-loc
repair and the VITS measurements are all functions of a handful of scalars:
the system's ``SysParams``/``DecoderParams``, the line-location array, and
whatever signal the test chooses to put under it.  ``make_field`` assembles
exactly those, so a unit test can exercise the geometry without a capture.

``RFDecode`` is constructible without touching a capture file -- it reads
only its own packaged sinc table -- and takes about 50 ms, so tests build one
per module rather than sharing a mutable instance.  ``DecoderParams`` is a
per-instance deep copy, so a test that retunes one cannot leak into another.
"""

import numpy as np

from lddecode.field import FieldNTSC, FieldPAL
from lddecode.rfdecode import RFDecode

FIELD_CLASS = {"NTSC": FieldNTSC, "PAL": FieldPAL}

#: Default lineoffset per system.  NTSC counts from line 0; PAL's field
#: parity shifts the whole field by a line (see Field.process).
PAL_LINEOFFSET = {True: 2, False: 3}


def make_rf(system="NTSC", **kwargs):
    """An RFDecode with the stock parameters for `system`."""
    return RFDecode(system=system, **kwargs)


def nominal_linelocs(rf, count, first=0.0, linelen=None):
    """Line locations for a field with no wow: `count` evenly spaced lines."""
    if linelen is None:
        linelen = rf.linelen
    return first + np.arange(count, dtype=np.float64) * linelen


def make_field(
    rf,
    linelocs=None,
    lineoffset=None,
    linecount=None,
    is_first_field=True,
    field_phase_id=1,
    video=None,
    dspicture=None,
):
    """A Field carrying only what the pure per-field maths reads.

    `video` becomes ``field.data["video"]``, the dict of demodulated
    products (``demod``, ``demod_05``, ...) that the pre-TBC measurements
    slice into; `dspicture` is the downscaled output the post-TBC ones read.
    Either may be left out when the test does not touch it.
    """
    field = FIELD_CLASS[rf.system](rf, {"input": None, "startloc": 0,
                                        "video": video or {}})

    if lineoffset is None:
        lineoffset = 0 if rf.system == "NTSC" else PAL_LINEOFFSET[is_first_field]
    field.lineoffset = lineoffset

    field.linecount = (
        linecount if linecount is not None else (rf.SysParams["frame_lines"] // 2)
    )

    if linelocs is None:
        # process() builds linelocs over proclines, which is what every
        # lineslice() call indexes into.
        linelocs = nominal_linelocs(rf, field.outlinecount + lineoffset + 10)
    field.linelocs = np.asarray(linelocs, dtype=np.float64)

    field.linebad = np.full(len(field.linelocs), False)
    field.isFirstField = is_first_field
    field.fieldPhaseID = field_phase_id
    field.dspicture = dspicture
    field.valid = True
    field.out_scale = field.compute_out_scale()

    return field
