"""Synthetic CVBS fields carrying VITS built from the reference nominals.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

A measurement primitive can only be trusted if it recovers a value that was
put there on purpose, so the hermetic lane needs a field whose VITS is drawn
from ``vits_reference`` rather than decoded from a capture.  ``make_field``
builds a ``video_common.VideoField`` on the real CVBS geometry -- including
the non-line-locked PAL row lattice and the sync pulses that
``vits_measure.measure_sync_origin`` looks for -- and ``render_definition``
draws every element of a definition onto its line at its stated nominal.

Nothing here opens a file, so a unit test using it stays hermetic.
"""

import numpy as np

import vits_reference as vr
from video_common import CVBS_GEOMETRY, CaptureParams, VideoField

#: Total lines per frame, mirroring vits_measure.FRAME_LINES.  Repeated here
#: rather than imported so the synthesiser cannot inherit a lattice bug from
#: the module it exists to test.
FRAME_LINES = {"NTSC": 525, "PAL": 625}

#: Sync depth below blanking, in IRE (SMPTE 170M-2004 Section 8; EBU Tech.
#: 3280-E Section 1.2).
SYNC_DEPTH_IRE = {"NTSC": -40.0, "PAL": -300.0 / 7.0}

#: Sync pulse width and rise time, in microseconds.
# SMPTE 170M-2004 Section 8: 4.7 us line sync.
# EBU Tech. 3280-E Section 1.2: 4.7 us line sync.
SYNC_WIDTH_US = 4.7
EDGE_RISE_US = 0.2


def row_starts(system, parity):
    """Lattice index of each field row's first sample within its frame.

    The same integer-exact ceiling ``video_common._cvbs_extract_field`` uses:
    field line k begins at ``ceil((k + offset * parity) * frame_samples /
    frame_lines)``.  NTSC divides exactly and so lands on the line grid.
    """
    geometry = CVBS_GEOMETRY[system]
    frame_samples = geometry["frame_samples"]
    lines = FRAME_LINES[system]
    offset = vr.FIELD_TWO_FRAME_LINE_OFFSET[system]
    return np.array([
        -(-(k + offset * parity) * frame_samples // lines)
        for k in range(geometry["field_height"])
    ], dtype=np.int64)


def make_field(system, is_first_field=True, field_phase_id=1,
               origin_samples=0.0, with_sync=True):
    """A blank CVBS field with sync, on the system's real row lattice.

    ``origin_samples`` places 0H that many samples into each row, which is
    what a real decode does by a fraction of a microsecond; the sync pulse
    and every rendered element move with it, so a measurement that ignores
    the origin reads the wrong window.

    The returned field carries ``cvbs_row_starts`` exactly as ``load_cvbs``
    would, and its ``dspicture`` is float64 in the normative 10-bit domain.
    """
    params = CaptureParams.for_cvbs(system)
    parity = 0 if is_first_field else 1
    record = {
        "field_id": 0,
        "is_first_field": is_first_field,
        "field_phase_id": field_phase_id,
    }
    data = np.full(params.field_samples, float(params.blanking_16b_ire))
    field = VideoField(data, 0, params, record)
    field.cvbs_row_starts = row_starts(system, parity)
    field.origin_samples = float(origin_samples)

    if with_sync:
        for line in range(1, params.field_height + 1):
            _draw_step(field, line, 0.0, SYNC_WIDTH_US, SYNC_DEPTH_IRE[system])
    return field


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def sample_of(field, line, us):
    """Fractional sample index within a row for a time in us from 0H.

    Deliberately written out here rather than taken from
    ``vits_measure.FieldGeometry``: a test that draws and measures with the
    same code cannot catch an error in it.
    """
    params = field.params
    geometry = CVBS_GEOMETRY[params.system]
    parity = 0 if field.isFirstField else 1
    frame_line = (line - 1) + parity * vr.FIELD_TWO_FRAME_LINE_OFFSET[params.system]
    true_start = frame_line * geometry["frame_samples"] / FRAME_LINES[params.system]
    lattice = float(field.cvbs_row_starts[line - 1]) - true_start
    return (field.origin_samples - lattice
            + us * params.sample_rate_mhz)


def _times(field, line, start_us, end_us):
    """(slice into the whole field, time in us from 0H of each sample in it).

    Indices are absolute rather than row-relative so a transition may spill
    across a row boundary, which is what a real capture does: a line's sync
    edge sits a fraction of a sample either side of where its row begins,
    and clipping it at the boundary would leave the edge measure_sync_origin
    is looking for half drawn.
    """
    params = field.params
    base = (line - 1) * params.field_width
    first = max(0, base + int(np.floor(sample_of(field, line, start_us))))
    last = min(len(field.dspicture),
               base + int(np.ceil(sample_of(field, line, end_us))) + 1)
    if last <= first:
        return slice(0, 0), np.zeros(0)
    origin = base + sample_of(field, line, 0.0)
    index = np.arange(first, last, dtype=np.float64)
    return slice(first, last), (index - origin) / params.sample_rate_mhz


def _raised_cosine(t_us, start_us, end_us, rise_us):
    """A gate that rises and falls over rise_us, in 0..1.

    A hard step would ring through the four-tap subcarrier null used by the
    level primitives; a real definition states a rise time for every element
    for the same reason.

    Each transition is centred on its window edge, so the half-amplitude
    point falls exactly at the stated time.  That is the convention every
    timing reference here uses -- ``vits_measure.measure_sync_origin`` looks
    for the half-amplitude crossing of the sync edge and has to find it at
    0H, not half a rise time later.
    """
    half = rise_us / 2.0
    up = np.clip((t_us - start_us + half) / rise_us, 0.0, 1.0)
    down = np.clip((end_us + half - t_us) / rise_us, 0.0, 1.0)
    gate = np.minimum(up, down)
    return 0.5 - 0.5 * np.cos(np.pi * gate)


def _draw_step(field, line, start_us, end_us, level_ire, rise_us=EDGE_RISE_US):
    """Set a window of one line to a level, in IRE above blanking.

    The level replaces whatever was there, crossfading over rise_us at each
    end, because that is what a reference nominal means for a bar: the
    multiburst's 80% white bar sits *at* 80% of the white reference, not 80%
    above the 50% pedestal it interrupts (see the "apparent 100 IRE" notes
    on the NTSC pedestal bars in vits_reference).
    """
    where, t_us = _times(field, line, start_us - rise_us, end_us + rise_us)
    if len(t_us) == 0:
        return
    gate = _raised_cosine(t_us, start_us, end_us, rise_us)
    picture = field.dspicture
    target = field.params.blanking_16b_ire + level_ire * field.params.out_scale
    picture[where] = picture[where] * (1.0 - gate) + target * gate


def draw_bar(field, line, start_us, end_us, level_ire, rise_us=EDGE_RISE_US):
    """A flat bar of the given level, in IRE above blanking.  Replaces."""
    _draw_step(field, line, start_us, end_us, level_ire, rise_us)


def draw_pulse(field, line, centre_us, half_duration_us, peak_ire):
    """A sine-squared pulse of the stated half-amplitude duration.

    ``sin^2`` has its half-amplitude points half a period apart, so a pulse
    of half-amplitude duration H spans 2H between its zeros.
    """
    where, t_us = _times(field, line,
                         centre_us - half_duration_us,
                         centre_us + half_duration_us)
    if len(t_us) == 0:
        return
    phase = (t_us - centre_us) / (2.0 * half_duration_us) * np.pi
    shape = np.where(np.abs(phase) < np.pi / 2, np.cos(phase) ** 2, 0.0)
    field.dspicture[where] += peak_ire * field.params.out_scale * shape


def draw_burst(field, line, start_us, end_us, peak_ire, freq_mhz,
               phase_deg=0.0, rise_us=0.4):
    """A gated carrier of the given peak amplitude, in IRE.

    The phase reference is 0H of the line, which is also the reference
    ``video_common.demod_region`` uses, so a burst drawn at 0 degrees and
    the colour burst drawn at 0 degrees measure as phase-aligned.
    """
    where, t_us = _times(field, line, start_us - rise_us, end_us + rise_us)
    if len(t_us) == 0:
        return
    gate = _raised_cosine(t_us, start_us, end_us, rise_us)
    carrier = np.cos(2 * np.pi * freq_mhz * t_us + np.radians(phase_deg))
    field.dspicture[where] += (
        peak_ire * field.params.out_scale * gate * carrier)


def draw_colour_burst(field, line, peak_ire=None, phase_deg=0.0):
    """The line's colour burst, in the capture's own burst window.

    Chrominance measurements are reported against this, so a line that will
    be measured for chroma has to carry one.
    """
    params = field.params
    if peak_ire is None:
        # SMPTE 170M-2004 Section 8.4 / EBU Tech. 3280-E Section 1.2: burst
        # amplitude is 40 IRE peak-to-peak, i.e. a 20 IRE carrier peak.
        peak_ire = 20.0
    start_us = params.colour_burst_start / params.sample_rate_mhz
    end_us = params.colour_burst_end / params.sample_rate_mhz
    freq_mhz = params.sample_rate_mhz / 4.0
    draw_burst(field, line, start_us, end_us, peak_ire, freq_mhz,
               phase_deg, rise_us=0.3)


# ---------------------------------------------------------------------------
# Whole definitions
# ---------------------------------------------------------------------------

def render_definition(field, entry, line=None, luma_gain=1.0, chroma_gain=1.0,
                      level_offset_ire=0.0, packet_gain=None,
                      packet_freq_scale=1.0, chroma_phase_deg=0.0,
                      element_gain=None):
    """Draw every element of a definition at its nominal onto one line.

    ``luma_gain``, ``chroma_gain`` and ``level_offset_ire`` inject the fault
    modes the conformance checks exist to catch: a flat gain error, a gain
    error confined to one band (the differential-level fault), and a
    pedestal shift.  All default to a conformant rendering.

    ``chroma_phase_deg`` turns every chrominance element on the line without
    moving the colour burst, which is the fault a disc shows when its
    recorded subcarrier is slightly off its own burst: successive fields
    read the same amplitude at a walking phase, and averaging them cancels
    the chrominance the burst says is there.

    ``element_gain`` is a mapping of element id to multiplier, applied to
    that luminance element alone.  It draws the fault a flat ``luma_gain``
    cannot: one element wrong *relative to the white reference bar on its
    own line*, which is the form IEC 60856-1986 Figure 7 states its
    tolerances in.

    ``packet_gain`` and ``packet_freq_scale`` do the same for a multiburst.
    ``packet_gain`` is called with a packet's nominal frequency in MHz and
    returns a multiplier, which is how a response tilt is drawn; the scale
    stretches every packet's frequency, which is how a time-base error is.
    They apply to burst_packet elements only, so the colour burst and any
    chrominance bar on the same line stay where they were.

    Elements are drawn in definition order, so a pedestal laid down first
    carries whatever rides on it.  Luminance bars replace the level in their
    window (a superimposed bar's nominal is its apparent absolute level);
    pulses and carriers add to it.

    The rendering is of the reference's model, not of the analogue waveform:
    where the reference describes a composite pulse's chrominance as a
    chroma_bar, it is drawn as a gated carrier of constant amplitude rather
    than with the sine-squared envelope a real 20T pulse carries.  That is
    the shape the primitive is specified to measure.
    """
    if line is None:
        line = entry.field_line
    system = entry.system
    scale = lambda nominal: vr.to_ire(nominal, system)

    needs_burst = any(element.channel == "chroma" for element in entry.elements)
    if needs_burst:
        draw_colour_burst(field, line)

    # Luminance first, then chrominance: a carrier is superimposed on the
    # luminance under it (that is how differential gain is measured), so a
    # bar drawn afterwards would erase the carrier it should be riding on.
    ordered = ([e for e in entry.elements if e.channel != "chroma"]
               + [e for e in entry.elements if e.channel == "chroma"])
    for element in ordered:
        if element.nominal is None:
            continue
        if element.kind == "blanked":
            continue

        if element.channel == "chroma":
            freq_mhz = element.freq_mhz or field.params.sample_rate_mhz / 4.0
            gain = chroma_gain
            if element.kind == "burst_packet":
                freq_mhz *= packet_freq_scale
                if packet_gain is not None:
                    gain *= packet_gain(element.freq_mhz)
            draw_burst(
                field, line, element.start_us, element.end_us,
                scale(element.nominal) * gain, freq_mhz,
                phase_deg=chroma_phase_deg,
            )
        elif element.kind == "staircase":
            windows = (element.step_windows_us
                       or _even_windows(element.window_us, len(element.steps)))
            own = luma_gain * (element_gain or {}).get(element.id, 1.0)
            for tread, window in zip(element.steps, windows):
                draw_bar(field, line, window[0], window[1],
                         scale(tread) * own + level_offset_ire)
        elif element.kind == "pulse":
            centre = (element.start_us + element.end_us) / 2.0
            half = (element.end_us - element.start_us) / 2.0
            own = luma_gain * (element_gain or {}).get(element.id, 1.0)
            draw_pulse(field, line, centre, half,
                       scale(element.nominal) * own)
        else:
            own = luma_gain * (element_gain or {}).get(element.id, 1.0)
            draw_bar(field, line, element.start_us, element.end_us,
                     scale(element.nominal) * own + level_offset_ire)
    return line


def _even_windows(window_us, count):
    start, end = window_us
    edges = [start + (end - start) * index / count for index in range(count + 1)]
    return [(edges[i], edges[i + 1]) for i in range(count)]


def add_noise(field, rng, sigma_ire):
    """Add white noise of the given standard deviation, in IRE, in place."""
    field.dspicture += rng.normal(
        0.0, sigma_ire * field.params.out_scale, len(field.dspicture))
    return field
