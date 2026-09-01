#!/usr/bin/env python3
"""
vits_geometry - microsecond to sample mapping inside a decoded CVBS field

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Answers one question for the VITS conformance measurement in
analysis/vits_measure.py: which samples of a field hold a given stretch of a
line, counted in microseconds from the leading edge of horizontal sync,
which is how every definition in analysis/vits_reference.py states its
timing.

Two things stand between those two coordinates:

*   **The PAL lattice is not line-locked.**  A line averages 709379/625 =
    1135.0064 samples, so a row's stored samples begin up to one sample
    after the true start of its line and the amount differs per row.  Every
    conversion here subtracts that row's own offset, computed exactly with
    integer arithmetic.
*   **0H is not exactly at sample 0.**  A decode places the sync edge a
    fraction of a microsecond away from the row boundary (measured:
    +0.136 us on NTSC, -0.055 us on PAL), so the origin is measured from
    the capture rather than assumed.

Pure geometry: this module opens no file and measures no signal level, so
the arithmetic can be unit tested on a field built in memory.
"""

import copy
from fractions import Fraction
from typing import Optional, Sequence, Tuple

import numpy as np

# Local: analysis/ is a directory of scripts rather than a package, and every
# entry point puts it on sys.path before importing this module.
import vits_reference as vr
from video_common import CVBS_GEOMETRY, demod_region

__all__ = [
    "FRAME_LINES",
    "FieldGeometry",
    "SYNC_DEPTH_IRE",
    "measure_sync_origin",
    "row_lattice_offset",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# SMPTE 170M-2004 Section 11.3: 525 lines/frame, 2:1 interlace.
# ITU-R BT.1700 Annex 1 Part B Table 1 item 1: 625 lines/frame.
FRAME_LINES = {"NTSC": 525, "PAL": 625}

# SMPTE 170M-2004 Section 8: synchronizing level is 40 IRE below blanking.
# EBU Tech. 3280-E Section 1.2: 625-line sync amplitude is 0.300 V against
# the 0.700 V blanking-to-white reference, i.e. 42.86 on the same 0-100
# measurement scale.
SYNC_DEPTH_IRE = {"NTSC": -40.0, "PAL": -300.0 / 7.0}

#: How many line boundaries measure_sync_origin() probes, and the largest
#: scatter (median absolute deviation, in samples) it will accept before
#: declaring the origin unmeasurable.
SYNC_PROBE_LINES = 32
SYNC_PROBE_FIRST_LINE = 40
SYNC_PROBE_LINE_STEP = 4
SYNC_ORIGIN_MAX_SCATTER_SAMPLES = 1.0


def row_lattice_offset(field, line: int) -> float:
    """How far a row's first stored sample sits past the true start of its
    line, in samples, in [0, 1).

    PAL 4fsc is not line-locked: line k of the frame begins at lattice
    position k * 709379/625, which is rarely an integer, and load_cvbs
    stores each row from the next whole sample (see _cvbs_extract_field).
    Subtracting this offset is what keeps a microsecond window on the signal
    instead of drifting a sample every few lines.  NTSC is orthogonal at 910
    samples per line, so the offset is always 0.

    The arithmetic is exact: the true line start is a Fraction, never a
    float accumulated across lines.
    """
    params = field.params
    starts = getattr(field, "cvbs_row_starts", None)
    if starts is None:
        raise ValueError(
            "field has no cvbs_row_starts; row placement is only known for "
            "fields produced by video_common.load_cvbs"
        )
    index = line - 1
    if not 0 <= index < len(starts):
        raise ValueError(
            f"line {line} is outside the field's {len(starts)} rows"
        )

    geometry = CVBS_GEOMETRY[params.system]
    parity = 0 if field.isFirstField else 1
    frame_line = index + parity * vr.FIELD_TWO_FRAME_LINE_OFFSET[params.system]
    true_start = Fraction(
        frame_line * geometry["frame_samples"], FRAME_LINES[params.system]
    )
    return float(Fraction(int(starts[index])) - true_start)


def measure_sync_origin(field, probe_lines: Optional[Sequence[int]] = None):
    """Where 0H sits inside a row, in samples, or None.

    Every window in vits_reference is timed from the leading edge of
    horizontal sync, but a decoded row does not start exactly there.  This
    finds the half-amplitude crossing of the sync edge that opens each of
    several rows, corrects each for that row's lattice offset, and returns
    (origin_samples, scatter_samples) using the median and the median
    absolute deviation.

    Returns None when fewer than half the probes yield a crossing or the
    scatter exceeds SYNC_ORIGIN_MAX_SCATTER_SAMPLES, which is the honest
    answer for a capture whose sync the caller should not rely on.
    """
    params = field.params
    width = params.field_width
    height = params.field_height
    if probe_lines is None:
        probe_lines = range(
            SYNC_PROBE_FIRST_LINE,
            min(height, SYNC_PROBE_FIRST_LINE
                + SYNC_PROBE_LINES * SYNC_PROBE_LINE_STEP),
            SYNC_PROBE_LINE_STEP,
        )
    probe_lines = [line for line in probe_lines if 1 <= line < height]
    if not probe_lines:
        return None

    threshold = SYNC_DEPTH_IRE[params.system] / 2.0
    # The front porch is 1.5 us (NTSC) / 1.65 us (PAL), so a window of a few
    # samples either side of the boundary is blanking before the edge and
    # sync after it whatever the line carried.
    margin = 8
    picture = field.output_to_ire(field.dspicture)

    offsets = []
    for line in probe_lines:
        # Row `line` + 1 begins at line * field_width; its sync edge is the
        # boundary we are locating.
        boundary = line * width
        if boundary - margin < 0 or boundary + margin > len(picture):
            continue
        window = picture[boundary - margin: boundary + margin]
        below = np.nonzero(window < threshold)[0]
        below = below[below > 0]
        if len(below) == 0:
            continue
        index = int(below[0])
        before, after = float(window[index - 1]), float(window[index])
        if before <= after:
            continue
        crossing = (index - 1) + (before - threshold) / (before - after)
        offsets.append(
            crossing - margin + row_lattice_offset(field, line + 1)
        )

    if len(offsets) < max(2, len(probe_lines) // 2):
        return None
    offsets = np.asarray(offsets, dtype=np.float64)
    origin = float(np.median(offsets))
    scatter = float(np.median(np.abs(offsets - origin)))
    if scatter > SYNC_ORIGIN_MAX_SCATTER_SAMPLES:
        return None
    return origin, scatter


class FieldGeometry:
    """Microsecond-to-sample mapping for one CVBS field.

    Holds the field's 0H origin so it is measured once rather than per
    element.  Construct with origin_samples=0.0 to work in the row's own
    coordinates, which is what a synthesised field wants.

    Not thread-safe to mutate; read-only use from several threads is fine.
    """

    def __init__(self, field, origin_samples: Optional[float] = None,
                 alignment_us: float = 0.0):
        self.field = field
        self.params = field.params
        self.fs_mhz = field.params.sample_rate_mhz
        self.origin_scatter = None
        self.origin_measured = False
        #: Microseconds a definition's windows are slid by before they are
        #: measured, to follow a disc that inserted its test signal off the
        #: stated timing.  See measure_time_offset().
        self.alignment_us = float(alignment_us)

        if origin_samples is None:
            found = measure_sync_origin(field)
            if found is None:
                # Fall back to the row boundary, and say so: a caller that
                # cares can refuse the capture rather than trust a window
                # that may be a sample or two out.
                origin_samples = 0.0
            else:
                origin_samples, self.origin_scatter = found
                self.origin_measured = True
        self.origin_samples = float(origin_samples)

    def aligned(self, alignment_us: float) -> "FieldGeometry":
        """A copy of this geometry with its windows slid by alignment_us.

        A time offset and an origin offset are the same thing to the
        conversion below, so an alignment costs nothing to apply and the
        measured 0H origin is carried over rather than measured again.
        """
        clone = copy.copy(self)
        clone.alignment_us = float(alignment_us)
        return clone

    def sample(self, line: int, us: float) -> float:
        """Fractional sample index within a row for a time in us from 0H."""
        return (self.origin_samples
                - row_lattice_offset(self.field, line)
                + (us + self.alignment_us) * self.fs_mhz)

    def row_slice(self, line: int, first: int, last: int) -> np.ndarray:
        """A window given directly in row samples, in IRE.

        For the parts of a line the capture defines by sample index rather
        than by a time from 0H - the burst window and the back porch - which
        must not move when a definition is aligned.
        """
        width = self.params.field_width
        first = max(0, min(width, first))
        last = max(first, min(width, last))
        return self.field.line_ire(line)[first:last]

    def bounds(self, line: int, start_us: float, end_us: float) -> Tuple[int, int]:
        """Half-open integer sample bounds of a window, clipped to the row.

        Raises ValueError if the window lies wholly outside the row, which
        means the caller asked for a time that does not exist rather than a
        window that merely needs trimming.
        """
        width = self.params.field_width
        first = int(round(self.sample(line, start_us)))
        last = int(round(self.sample(line, end_us)))
        if last <= 0 or first >= width:
            raise ValueError(
                f"window {start_us}-{end_us} us falls outside line {line}"
            )
        return max(0, first), min(width, last)

    def segment(self, line: int, start_us: float, end_us: float) -> np.ndarray:
        """The waveform over a window, in IRE.  Returns a new array."""
        first, last = self.bounds(line, start_us, end_us)
        return self.field.line_ire(line)[first:last]

    def demod(self, line: int, start_us: float, end_us: float):
        """(luma_ire, chroma_carrier_peak_ire, phase_deg) over a window.

        Defers to video_common.demod_region so there is one fs/4 quadrature
        demodulator in the tree.  The microseconds handed over are chosen so
        that demod_region's own truncation lands on exactly the bounds
        computed here; its phase reference is the row start, the same one
        burst_ref() uses, so burst-relative phases still cancel.

        The window is trimmed to a whole number of subcarrier cycles.  At
        4fsc that makes the estimator exact rather than merely close: over a
        multiple of four samples the luminance term and the image of the
        quadrature reference both sum to zero, so a pure carrier reads its
        own amplitude.  A window left at an arbitrary length under-reads a
        chrominance bar by a per cent or two - a third of the +/-1%-of-B2
        band IEC 60856-1986 9.1.3 allows the element itself.
        """
        first, last = self.bounds(line, start_us, end_us)
        whole_cycles = ((last - first) // 4) * 4
        if whole_cycles >= 4:
            last = first + whole_cycles
        return demod_region(
            self.field,
            line,
            (first + 0.5) / self.fs_mhz,
            (last - first) / self.fs_mhz,
        )
