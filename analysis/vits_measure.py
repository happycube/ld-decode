#!/usr/bin/env python3
"""
vits_measure - CVBS-domain VITS measurement primitives

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Measures the elements of the Vertical Interval Test Signals defined in
analysis/vits_reference.py from a decoded CVBS field: flat levels, staircase
treads and step inequality, multiburst packet amplitude and frequency,
chrominance amplitude and burst-relative phase, and sine-squared pulse
height, width and pulse-to-bar ratio.  Where a signal sits on a line comes
from analysis/vits_geometry.py; which signal it is comes from
analysis/vits_identify.py, which consumes this.

CVBS only.  The .tbc format is on its way out, so the single loader entry
point here is video_common.load_cvbs() and a .tbc path is refused rather
than quietly measured through a second code path.

Discs deviate, and two of those deviations are handled here rather than left
to the caller:

*   A definition is slid onto the signal before it is measured.  GGV PAL
    carries every element of its line 19 insertion test signal 0.85 us
    earlier than the ITU-T J.63 Annex I timing; a 2T pulse window is 0.4 us
    wide, so an unaligned window measures its skirt.  The offset applied is
    reported, so a timing deviation is visible rather than silently
    corrected.
*   A pedestal is measured only where it is exposed, and a chrominance
    element spanning a changing luminance is measured per pedestal, which is
    also the table a differential gain check reads.

Measurements are returned with a quality figure in 0..1.  That figure gates
identification and tells a developer how much to trust a number; it is not a
conformance limit, and no standard states one.  Pass/fail against the
tolerances in vits_reference belongs to the conformance layer above this.
"""

import copy
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Dict, Optional, Tuple

import numpy as np

# Local: analysis/ is a directory of scripts rather than a package, and every
# entry point puts it on sys.path before importing this module.
import vits_reference as vr
from vits_geometry import FieldGeometry, measure_sync_origin, row_lattice_offset
from video_common import (
    burst_ref,
    load_cvbs,
    phase_diff,
    segment_freq_pp,
    sine_fit_pp,
)

__all__ = [
    "FieldGeometry",
    "Measurement",
    "align_geometry",
    "average_fields",
    "chroma_expected",
    "guarded_window",
    "load",
    "luma_template",
    "measure_burst_packet",
    "measure_chroma",
    "measure_definition",
    "measure_element",
    "measure_level",
    "measure_level_over",
    "measure_line_blanking",
    "measure_pulse",
    "measure_staircase",
    "measure_sync_origin",
    "measure_time_offset",
    "row_lattice_offset",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Microseconds trimmed from each end of a window before a flat level is
#: averaged.  The longest transition any definition states is the 0.4 us
#: chrominance rise time (analogue-video-specifications
#: resources/definitions/vits/pal/itu-composite.yaml, c_rise_time_us), and a
#: decoded edge rings for roughly as long again, so 0.5 us clears both.
LEVEL_GUARD_US = 0.5

#: A guard never eats more than this fraction of a window from each end, so
#: the short packets of the NTC-7 combination multiburst still yield a
#: segment rather than an empty slice.
LEVEL_GUARD_MAX_FRACTION = 0.25

#: Ripple, in IRE, at which a flat-level measurement is reported at quality
#: 0; a perfectly flat window reports 1.  A confidence indicator for the
#: developer and a gate for identification, not a conformance limit.
FLATNESS_ZERO_IRE = 10.0

#: How far outside its stated window a pulse peak is searched for.  The 2T
#: window is only 0.4 us wide, so a decode that shifts the pulse by a couple
#: of samples would otherwise be measured on its skirt.
PULSE_SEARCH_MARGIN_US = 1.0

#: Multiples of a pulse's own half-amplitude duration excluded either side
#: of its crest when the baseline under it is read.  A sine-squared pulse
#: has returned to the baseline by one half-duration out; the extra quarter
#: keeps the decoder's overshoot out of the median as well.
PULSE_BASELINE_EXCLUSION = 1.25

#: Fractional span either side of the measured frequency searched when
#: refining a burst packet's sine fit, and how many points that search uses.
#: The span is widened to at least the window's own FFT bin spacing, because
#: a packet only a cycle or two long cannot be located better than that.
PACKET_FREQ_SEARCH_SPAN = 0.08
PACKET_FREQ_SEARCH_POINTS = 33

#: Cycles a fit window must hold before its frequency is believed.  Below
#: about one cycle a least-squares sine latches onto the segment's own tilt
#: and reports an amplitude several times the truth, so the search floor is
#: set here rather than letting it run down towards DC.
PACKET_MIN_CYCLES = 1.2

#: Sub-windows a chroma envelope is split into to judge how flat it is.
CHROMA_ENVELOPE_SEGMENTS = 4

#: Shortest piece a chrominance window is split into at a luminance
#: boundary.  Below roughly a microsecond the guard bands leave too few
#: samples for the quadrature estimator, so such a piece is dropped and the
#: window is measured whole instead.
CHROMA_ZONE_MIN_US = 1.5

#: How far a definition is slid against a line when locating it, and the
#: normalised correlation its best fit must reach before the offset is
#: believed.  Real discs need this: GGV PAL carries every element of its
#: line 19 insertion test signal 0.85 us earlier than the ITU-T J.63 Annex I
#: timing, consistently across the bar, both pulses and all five treads,
#: while its colour burst sits where the standard puts it.  A 2T pulse is
#: 0.4 us wide, so an unaligned window measures its skirt.
TIME_ALIGN_SEARCH_US = 2.0
TIME_ALIGN_MIN_CORRELATION = 0.5

# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load(path, max_fields=None):
    """Load a CVBS capture for measurement.  Returns (params, fields, data).

    A thin guard over video_common.load_cvbs(), which is the only loader
    this module uses.  A .tbc path raises ValueError: the conformance
    measurements are specified against the CVBS sample lattice and levels,
    and .tbc is the format being retired.
    """
    if path.endswith(".tbc"):
        raise ValueError(
            f"vits_measure reads CVBS captures only, got a .tbc path: {path}"
        )
    return load_cvbs(path, max_fields)

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

@dataclass
class Measurement:
    """One measured VITS element.

    value and nominal are on the 0-100 blanking-to-white measurement scale
    (IRE), which is what video_common.VideoField.output_to_ire() produces
    and what vits_reference.to_ire() converts a stored nominal to.  For a
    chroma element the value is the carrier peak, half the peak-to-peak
    swing, matching the reference's convention.

    quality is 0..1 and says how much to trust the value; it is not a
    conformance verdict.  detail carries the per-kind extras (measured
    frequency, pulse width, staircase treads, ...) in the units its keys
    name.
    """

    element_id: str
    kind: str
    channel: str
    value: float
    quality: float
    nominal: Optional[float] = None
    tolerance: Optional[float] = None
    detail: dict = dataclass_field(default_factory=dict)

    @property
    def deviation(self) -> Optional[float]:
        """Measured minus nominal, in IRE, or None if there is no nominal."""
        if self.nominal is None:
            return None
        return self.value - self.nominal

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def guarded_window(start_us: float, end_us: float,
             guard_us: float = LEVEL_GUARD_US) -> Tuple[float, float]:
    """A window with its transitions trimmed off both ends."""
    span = end_us - start_us
    guard = min(guard_us, LEVEL_GUARD_MAX_FRACTION * span)
    return start_us + guard, end_us - guard


def _suppress_subcarrier(waveform: np.ndarray) -> np.ndarray:
    """A four-sample moving average of the waveform.

    Both systems' output is sampled at exactly 4x subcarrier, so a four-tap
    boxcar has an exact null at the subcarrier and removes a superimposed
    chrominance component from a luminance level without touching its DC.
    Returns a new array three samples shorter, or the input unchanged when
    it is too short to filter.
    """
    if len(waveform) < 4:
        return waveform
    return np.convolve(waveform, np.full(4, 0.25), mode="valid")


def _flatness(ripple_ire: float) -> float:
    """Quality 0..1 from a window's ripple.  See FLATNESS_ZERO_IRE."""
    return float(max(0.0, 1.0 - ripple_ire / FLATNESS_ZERO_IRE))


def _ripple(waveform: np.ndarray) -> float:
    """Peak-to-peak spread of a window, robust to a stray dropout sample."""
    if len(waveform) < 4:
        return float(np.ptp(waveform)) if len(waveform) else 0.0
    low, high = np.percentile(waveform, [2.5, 97.5])
    return float(high - low)


def _nominal_ire(element, system: str) -> Optional[float]:
    if element.nominal is None:
        return None
    return vr.to_ire(element.nominal, system)


def _tolerance_ire(element, system: str) -> Optional[float]:
    if element.tolerance is None:
        return None
    return vr.to_ire(element.tolerance, system)


def _tread_windows(element) -> Tuple[Tuple[float, float], ...]:
    """Per-tread windows of a staircase.

    Uses the element's own step_windows_us where the definition states them
    unevenly (the PAL treads run 4, 4, 4, 4 then 6 us), and divides the
    element window equally otherwise, which is the model the NTSC
    definitions use with their "steps: 5".
    """
    if not element.steps:
        raise ValueError(f"{element.id} is not a staircase: no treads")
    if element.step_windows_us:
        return tuple(tuple(window) for window in element.step_windows_us)
    count = len(element.steps)
    start, end = element.window_us
    edges = [start + (end - start) * index / count for index in range(count + 1)]
    return tuple((edges[i], edges[i + 1]) for i in range(count))


def _uncovered_windows(entry, element) -> Tuple[Tuple[float, float], ...]:
    """The parts of an element's window no other luminance element occupies.

    A pedestal is defined across the whole active line and then interrupted:
    the FCC multiburst's grey pedestal runs 9.2 to 62 us with a white
    reference bar sitting on its first 6.5 us.  Averaging the stated window
    whole would measure the pedestal and the bar together and report
    neither, so the bar's window is cut out first.  Chrominance elements are
    left in: they ride on the pedestal without changing its level, and the
    four-tap subcarrier null removes them.

    Returns the element's own window unchanged when nothing overlaps it.
    """
    pieces = [tuple(element.window_us)]
    for other in entry.elements:
        if other is element:
            continue
        # A chrominance bar rides on the level and the four-tap null takes
        # it back out, so it does not hide the pedestal.  A burst packet
        # does hide it: it sits at its own frequency, which no null here
        # removes, and its window has to come out.
        if other.channel != "luma" and other.kind != "burst_packet":
            continue
        if other.end_us <= element.start_us or other.start_us >= element.end_us:
            continue
        remaining = []
        for start, end in pieces:
            if other.start_us > start:
                remaining.append((start, min(end, other.start_us)))
            if other.end_us < end:
                remaining.append((max(start, other.end_us), end))
        pieces = [piece for piece in remaining if piece[1] > piece[0]]
    return tuple(pieces) if pieces else (tuple(element.window_us),)


def _chroma_subwindows(entry, element):
    """Pieces of a chrominance element's window that sit on a steady level.

    The window is cut at every luminance boundary that falls inside it - a
    staircase's tread edges, a bar's ends - because the quadrature estimator
    subtracts one luminance value per window and a step inside it leaks into
    the measured amplitude.  Cutting there also produces exactly the per-
    pedestal table a differential gain measurement needs.

    Returns None when the window carries no such boundary, or when cutting
    would leave pieces too short to demodulate, so the caller measures it
    whole.
    """
    start_us, end_us = element.window_us
    cuts = set()
    for other in entry.elements:
        if other is element or other.channel != "luma":
            continue
        if other.end_us <= start_us or other.start_us >= end_us:
            continue
        if other.kind == "pulse":
            # A pulse has no steady portion to split into.
            continue
        edges = (_tread_windows(other) if other.kind == "staircase"
                 else [tuple(other.window_us)])
        for edge_start, edge_end in edges:
            cuts.add(edge_start)
            cuts.add(edge_end)

    bounds = sorted({start_us, end_us}
                    | {cut for cut in cuts if start_us < cut < end_us})
    if len(bounds) < 3:
        return None
    pieces = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]
    pieces = [piece for piece in pieces
              if piece[1] - piece[0] >= CHROMA_ZONE_MIN_US]
    return pieces or None


def chroma_expected(entry, start_us: float, end_us: float) -> bool:
    """Whether any chrominance element of a definition covers a window."""
    for element in entry.elements:
        if element.channel != "chroma":
            continue
        if element.end_us > start_us and element.start_us < end_us:
            return True
    return False


def _phase_locked(field) -> bool:
    """Whether a field's chroma survives however it was assembled.

    A single field is always phase locked to itself; an average is only
    phase locked if average_fields() matched the subcarrier sequence.
    """
    return bool(getattr(field, "phase_locked", True))

# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def measure_line_blanking(geom: FieldGeometry, line: int) -> float:
    """The line's own back-porch level, in IRE.

    Reads 0 when the decode's blanking level matches the capture's declared
    one; a staircase is measured against it so that a whole-line pedestal
    offset shows up as an offset rather than as a step error.
    """
    params = geom.params
    guard = int(round(0.3 * geom.fs_mhz))
    segment = geom.row_slice(line,
                             params.colour_burst_end + guard,
                             params.active_video_start - guard)
    if len(segment) == 0:
        return 0.0
    return float(np.mean(segment))


def measure_level(geom: FieldGeometry, line: int, start_us: float, end_us: float,
                  element_id: str = "level", channel: str = "luma",
                  suppress_subcarrier: bool = False,
                  guard_us: float = LEVEL_GUARD_US) -> Measurement:
    """Mean level of a flat window, in IRE, with a flatness quality.

    Set suppress_subcarrier for a window that carries superimposed
    chrominance: the level is then read through the four-tap subcarrier null
    so the chroma does not inflate the ripple or bias a short mean.
    """
    return measure_level_over(
        geom, line, [(start_us, end_us)], element_id=element_id,
        channel=channel, suppress_subcarrier=suppress_subcarrier,
        guard_us=guard_us)


def measure_level_over(geom: FieldGeometry, line: int, windows,
                       element_id: str = "level", channel: str = "luma",
                       suppress_subcarrier: bool = False,
                       guard_us: float = LEVEL_GUARD_US) -> Measurement:
    """Mean level across several windows of one line, in IRE.

    Each window is guarded and read separately, then the pieces are
    concatenated, so a level defined across the line but interrupted by
    other elements (see _uncovered_windows) is measured only where it is
    actually exposed.  The quality is the flatness of the pieces taken
    together, which correctly falls if they disagree with each other.
    """
    pieces = []
    used = []
    for start_us, end_us in windows:
        guard_start, guard_end = guarded_window(start_us, end_us, guard_us)
        if guard_end <= guard_start:
            continue
        try:
            segment = geom.segment(line, guard_start, guard_end)
        except ValueError:
            continue
        if len(segment) == 0:
            continue
        pieces.append(_suppress_subcarrier(segment)
                      if suppress_subcarrier else segment)
        used.append((guard_start, guard_end))
    if not pieces:
        raise ValueError(
            f"windows {list(windows)} us on line {line} hold no samples"
        )

    filtered = np.concatenate(pieces)
    value = float(np.mean(filtered))
    ripple = _ripple(filtered)
    return Measurement(
        element_id=element_id,
        kind="bar",
        channel=channel,
        value=value,
        quality=_flatness(ripple),
        detail={
            "ripple_ire": ripple,
            "samples": int(len(filtered)),
            "windows_us": used,
            "subcarrier_suppressed": bool(suppress_subcarrier),
        },
    )


def measure_staircase(geom: FieldGeometry, line: int, element,
                      system: Optional[str] = None,
                      suppress_subcarrier: bool = False) -> Measurement:
    """Staircase treads, risers and step inequality.

    value is the top tread, in IRE.  detail carries:

      treads_ire        each tread's level
      risers_ire        the rise into each tread, the first measured from
                        the line's own blanking so that a pedestal offset
                        does not masquerade as a step error
      blanking_ire      that blanking reference
      amplitude_ire     top tread minus blanking
      step_inequality   the largest departure of a riser from the mean
                        riser, as a fraction of amplitude_ire

    IEC 60856-1986 9.1.3 Figure 7 d) states six levels including black and
    white, so a five-tread definition has five risers: blanking into tread
    one, then tread to tread.  risers_ire holds exactly those.
    """
    system = system or geom.params.system
    blanking = measure_line_blanking(geom, line)

    treads = []
    qualities = []
    for window in _tread_windows(element):
        tread = measure_level(
            geom, line, window[0], window[1],
            element_id=element.id,
            suppress_subcarrier=suppress_subcarrier,
        )
        treads.append(tread.value)
        qualities.append(tread.quality)

    risers = [treads[0] - blanking]
    risers.extend(treads[i + 1] - treads[i] for i in range(len(treads) - 1))
    amplitude = treads[-1] - blanking
    mean_riser = float(np.mean(risers))
    if abs(amplitude) < 1e-9:
        inequality = float("inf")
    else:
        inequality = float(
            max(abs(riser - mean_riser) for riser in risers) / abs(amplitude)
        )

    monotonic = all(riser > 0 for riser in risers)
    quality = float(min(qualities)) if monotonic else 0.0
    return Measurement(
        element_id=element.id,
        kind="staircase",
        channel=element.channel,
        value=float(treads[-1]),
        quality=quality,
        nominal=_nominal_ire(element, system),
        tolerance=_tolerance_ire(element, system),
        detail={
            "treads_ire": [float(tread) for tread in treads],
            "risers_ire": [float(riser) for riser in risers],
            "blanking_ire": float(blanking),
            "amplitude_ire": float(amplitude),
            "step_inequality": inequality,
            "monotonic": monotonic,
            "nominal_treads_ire": [
                vr.to_ire(step, system) for step in element.steps
            ],
        },
    )


def measure_burst_packet(geom: FieldGeometry, line: int, element,
                         system: Optional[str] = None) -> Measurement:
    """A multiburst packet's amplitude and frequency.

    value is the carrier peak in IRE, half the peak-to-peak swing, matching
    the convention vits_reference stores chrominance nominals in.  The
    frequency is measured, not assumed: it comes from the segment's own
    spectrum and is then refined to maximise the least-squares sine fit, so
    a disc carrying a different multiburst set reports the set it carries.

    detail carries freq_mhz, freq_error_mhz against the element's nominal,
    pp_ire, and coherence - the fitted amplitude as a fraction of the
    segment's total AC content, which falls below 1 when the window holds
    noise or more than one tone.
    """
    system = system or geom.params.system
    start_us, end_us = guarded_window(*element.window_us)
    segment = geom.segment(line, start_us, end_us)
    if len(segment) < 16:
        raise ValueError(
            f"packet window {element.window_us} on line {line} is too short "
            f"to fit ({len(segment)} samples)"
        )

    coarse_freq, rms_pp = segment_freq_pp(segment, geom.fs_mhz)
    if coarse_freq <= 0.0:
        return Measurement(
            element_id=element.id,
            kind="burst_packet",
            channel=element.channel,
            value=0.0,
            quality=0.0,
            nominal=_nominal_ire(element, system),
            tolerance=_tolerance_ire(element, system),
            detail={"freq_mhz": 0.0, "pp_ire": float(rms_pp),
                    "coherence": 0.0, "reason": "no tone in window"},
        )

    # Refine the frequency by maximising the fitted amplitude: the FFT bin
    # of a short packet is coarse, and a mistuned fit under-reads.  The
    # search has to be at least one bin wide, or the 0.5 MHz packet - only
    # about 1.5 cycles inside a guarded PAL window - is fitted where the
    # interpolated FFT peak landed rather than where the tone is.
    duration_us = len(segment) / geom.fs_mhz
    span = max(PACKET_FREQ_SEARCH_SPAN * coarse_freq, 1.0 / duration_us)
    lowest = max(coarse_freq - span, PACKET_MIN_CYCLES / duration_us)
    highest = max(coarse_freq + span, lowest * 1.05)
    candidates = np.linspace(lowest, highest, PACKET_FREQ_SEARCH_POINTS)
    fitted = np.array([sine_fit_pp(segment, geom.fs_mhz, f) for f in candidates])
    best = int(np.argmax(fitted))
    freq, pp = float(candidates[best]), float(fitted[best])
    if 0 < best < len(candidates) - 1:
        # Parabolic interpolation of the fit maximum, which sits between
        # search points far more often than on one.
        a, b, c = fitted[best - 1], fitted[best], fitted[best + 1]
        denominator = a - 2 * b + c
        if abs(denominator) > 1e-12:
            step = 0.5 * (a - c) / denominator
            if abs(step) <= 1.0:
                freq = float(candidates[best] + step
                             * (candidates[1] - candidates[0]))
                pp = float(sine_fit_pp(segment, geom.fs_mhz, freq))

    coherence = float(min(1.0, pp / rms_pp)) if rms_pp > 0 else 0.0
    nominal_freq = element.freq_mhz
    return Measurement(
        element_id=element.id,
        kind="burst_packet",
        channel=element.channel,
        value=pp / 2.0,
        quality=coherence,
        nominal=_nominal_ire(element, system),
        tolerance=_tolerance_ire(element, system),
        detail={
            "freq_mhz": freq,
            "nominal_freq_mhz": nominal_freq,
            "freq_error_mhz": (None if nominal_freq is None
                               else freq - nominal_freq),
            "pp_ire": pp,
            "coherence": coherence,
            "samples": int(len(segment)),
        },
    )


def measure_chroma(geom: FieldGeometry, line: int, element,
                   system: Optional[str] = None, windows=None) -> Measurement:
    """A chrominance element's carrier peak and burst-relative phase.

    value is the carrier peak in IRE.  detail["zones"] carries one entry per
    window measured - its luminance pedestal, chrominance amplitude, phase
    and phase against the line's own colour burst - which is exactly the
    table a differential gain and differential phase check reads.

    windows defaults to the element's own, but a chrominance element that
    spans a changing luminance has to be measured in pieces: the quadrature
    estimator subtracts one luminance value per window, so a staircase edge
    inside the window leaks into the amplitude (measured at +3.5% on the
    NTC-7 chrominance reference before this was split).  measure_element()
    supplies the pieces from the definition; see _chroma_subwindows.

    Quality falls with the spread of amplitude across the zones, which for a
    chrominance reference laid over a staircase is the differential gain
    itself.  It is forced to 0 when the field is an average that did not
    match the subcarrier sequence: such an average cancels chroma, and any
    amplitude read from it is meaningless.
    """
    system = system or geom.params.system
    if windows is None:
        start_us, end_us = guarded_window(*element.window_us)
        edges = np.linspace(start_us, end_us, CHROMA_ENVELOPE_SEGMENTS + 1)
        zone_windows = [(start_us, end_us)]
        envelope_windows = [(edges[i], edges[i + 1])
                            for i in range(CHROMA_ENVELOPE_SEGMENTS)]
    else:
        zone_windows = [guarded_window(*window) for window in windows]
        envelope_windows = zone_windows

    zones = []
    burst_amplitude, burst_phase = burst_ref(geom.field, line)
    for window in zone_windows:
        luma, amplitude, phase = geom.demod(line, window[0], window[1])
        if amplitude is None:
            continue
        zones.append({
            "window_us": (float(window[0]), float(window[1])),
            "luma_ire": float(luma),
            "amp_ire": float(amplitude),
            "phase_deg": float(phase),
            "burst_relative_phase_deg": (
                None if burst_phase is None
                else float(phase_diff(phase, burst_phase))),
        })
    if not zones:
        raise ValueError(
            f"chroma window {element.window_us} on line {line} is too short"
        )

    # Duration weighted, so splitting a window into uneven pieces gives the
    # same answer as measuring it whole when the amplitude really is flat.
    weights = np.array([zone["window_us"][1] - zone["window_us"][0]
                        for zone in zones])
    amplitudes = np.array([zone["amp_ire"] for zone in zones])
    value = float(np.average(amplitudes, weights=weights))

    envelope = []
    for window in envelope_windows:
        _, part, _ = geom.demod(line, window[0], window[1])
        if part is not None:
            envelope.append(float(part))
    if envelope and value > 0:
        spread = (max(envelope) - min(envelope)) / value
        quality = float(max(0.0, 1.0 - spread))
    else:
        quality = 0.0
    if not _phase_locked(geom.field):
        quality = 0.0

    return Measurement(
        element_id=element.id,
        kind=element.kind,
        channel="chroma",
        value=value,
        quality=quality,
        nominal=_nominal_ire(element, system),
        tolerance=_tolerance_ire(element, system),
        detail={
            "zones": zones,
            "luma_ire": float(np.average(
                [zone["luma_ire"] for zone in zones], weights=weights)),
            "phase_deg": zones[0]["phase_deg"],
            "burst_amp_ire": (None if burst_amplitude is None
                              else float(burst_amplitude)),
            "burst_relative_phase_deg": zones[0]["burst_relative_phase_deg"],
            "envelope_ire": envelope,
            "phase_locked": _phase_locked(geom.field),
        },
    )


def measure_pulse(geom: FieldGeometry, line: int, element,
                  system: Optional[str] = None,
                  bar_ire: Optional[float] = None,
                  suppress_subcarrier: bool = False) -> Measurement:
    """A sine-squared pulse's peak, half-amplitude duration and bar ratio.

    value is the peak above the local baseline, in IRE.  The peak is
    searched for within PULSE_SEARCH_MARGIN_US of the stated window so a
    pulse shifted by a couple of samples is measured on its crest rather
    than its skirt, and the baseline is the median of the waveform just
    outside the window on both sides.

    detail carries had_ns (the half-amplitude duration, interpolated across
    the crossings), centre_us, baseline_ire and pulse_to_bar, the ratio
    against bar_ire that a flat frequency response holds at 1.  centre_us is
    in the definition's own time frame, so on an aligned geometry it reads
    against the stated centre rather than against 0H.

    Set suppress_subcarrier for a composite pulse whose chrominance
    component would otherwise be measured as luminance ripple; leave it off
    for a 2T pulse, whose 200 ns half-duration is only a few samples wide
    and would be flattened by the filter.
    """
    system = system or geom.params.system
    start_us, end_us = element.window_us
    search_start = start_us - PULSE_SEARCH_MARGIN_US
    search_end = end_us + PULSE_SEARCH_MARGIN_US

    waveform = geom.segment(line, search_start, search_end)
    if len(waveform) < 8:
        raise ValueError(
            f"pulse window {element.window_us} on line {line} is too short "
            f"to measure ({len(waveform)} samples)"
        )
    if suppress_subcarrier:
        waveform = _suppress_subcarrier(waveform)
        # The boxcar delays by 1.5 samples; the shift cancels out of a
        # width and a ratio, and the centre is reported with it removed.
        centre_shift = 1.5
    else:
        centre_shift = 0.0

    first, last = geom.bounds(line, search_start, search_end)
    fs = geom.fs_mhz

    # The crest is looked for across the whole search window, not just its
    # middle: a disc that inserted the pulse late enough to sit near the
    # edge of the window still has to be measured on its crest, and the
    # margin exists to widen the search, not to narrow it.
    peak_index = 1 + int(np.argmax(waveform[1:len(waveform) - 1]))

    # The baseline is what the line sits at either side of the pulse, taken
    # clear of the pulse's own skirts: beyond about one half-amplitude
    # duration from the crest a sine-squared pulse has returned to it.
    expected_had_us = (element.end_us - element.start_us) / 2.0
    exclusion = max(2, int(round(PULSE_BASELINE_EXCLUSION * expected_had_us * fs)))
    outside = np.concatenate([
        waveform[:max(0, peak_index - exclusion)],
        waveform[min(len(waveform), peak_index + exclusion + 1):],
    ])
    if len(outside) < 4:
        raise ValueError(
            f"pulse window {element.window_us} on line {line} leaves no "
            "baseline outside the pulse"
        )
    baseline = float(np.median(outside))
    skirts = outside

    peak, peak_offset = _interpolated_peak(waveform, peak_index)
    peak -= baseline
    centre_us = ((first + peak_index + peak_offset + centre_shift)
                 - geom.sample(line, 0.0)) / fs

    had_ns = _half_amplitude_ns(waveform, peak_index, baseline, peak, fs)
    ratio = None if not bar_ire else float(peak / bar_ire)
    skirt_ripple = _ripple(skirts)

    # Quality: how close the crest is to the shape the definition states.
    # Every pulse window here is the centre plus and minus the pulse's own
    # half-amplitude duration, so the expected width is half the window.
    # Judging the skirts instead would score a perfectly good 12.5T pulse at
    # zero merely because a 2T pulse sits 1 us away from it.
    expected_had_ns = (element.end_us - element.start_us) / 2.0 * 1000.0
    if peak <= 0 or had_ns is None or expected_had_ns <= 0:
        quality = 0.0
    else:
        quality = float(max(
            0.0, 1.0 - abs(had_ns - expected_had_ns) / expected_had_ns))

    return Measurement(
        element_id=element.id,
        kind="pulse",
        channel=element.channel,
        value=peak,
        quality=quality,
        nominal=_nominal_ire(element, system),
        tolerance=_tolerance_ire(element, system),
        detail={
            "had_ns": had_ns,
            "expected_had_ns": expected_had_ns,
            "centre_us": float(centre_us),
            "baseline_ire": baseline,
            "skirt_ripple_ire": skirt_ripple,
            "pulse_to_bar": ratio,
            "bar_ire": bar_ire,
            "subcarrier_suppressed": bool(suppress_subcarrier),
        },
    )


def _interpolated_peak(waveform: np.ndarray, index: int) -> Tuple[float, float]:
    """(peak value, sub-sample offset from index) of a crest.

    A PAL 2T pulse is about 3.5 samples wide at half amplitude in a 4fsc
    lattice, so its crest usually falls between two samples and the largest
    sample under-reads the peak by a per cent or two - enough to move a
    pulse-to-bar ratio outside a tolerance the decode actually met.  The
    three samples around the maximum fix a parabola, which is exact for the
    top of a sine-squared pulse to well within that error.
    """
    if index <= 0 or index >= len(waveform) - 1:
        return float(waveform[index]), 0.0
    a, b, c = (float(waveform[index - 1]), float(waveform[index]),
               float(waveform[index + 1]))
    denominator = a - 2.0 * b + c
    if denominator >= 0.0:
        return b, 0.0
    offset = 0.5 * (a - c) / denominator
    if abs(offset) > 1.0:
        return b, 0.0
    return b - 0.25 * (a - c) * offset, offset


def _half_amplitude_ns(waveform: np.ndarray, peak_index: int, baseline: float,
                       peak: float, fs_mhz: float) -> Optional[float]:
    """Half-amplitude duration of a crest, in ns, or None if it is unbounded.

    The crossings are interpolated between samples: at 4fsc a PAL 2T pulse
    is only about 3.5 samples wide at half amplitude, so a sample-counted
    width would quantise to 30% steps.
    """
    if peak <= 0:
        return None
    half = baseline + peak / 2.0

    index = peak_index
    while index > 0 and waveform[index] > half:
        index -= 1
    if waveform[index] > half:
        return None
    lower = index
    if waveform[index + 1] != waveform[index]:
        lower = index + (half - waveform[index]) / (
            waveform[index + 1] - waveform[index])

    index = peak_index
    while index < len(waveform) - 1 and waveform[index] > half:
        index += 1
    if waveform[index] > half:
        return None
    upper = index
    if waveform[index - 1] != waveform[index]:
        upper = index - 1 + (waveform[index - 1] - half) / (
            waveform[index - 1] - waveform[index])

    return float((upper - lower) / fs_mhz * 1000.0)

# ---------------------------------------------------------------------------
# Locating a definition on a line
# ---------------------------------------------------------------------------

def luma_template(entry, times_us: np.ndarray) -> np.ndarray:
    """The luminance a definition describes, in IRE, at each time in us.

    A step model: bars and staircase treads set the level over their window
    in definition order, so a pedestal laid down first carries the bars that
    interrupt it, and pulses are then added as sine-squared crests.  Edge
    shaping is left out deliberately - this exists to be correlated against
    a measured line, and a correlation does not care about a 0.2 us rise.
    """
    times_us = np.asarray(times_us, dtype=np.float64)
    out = np.zeros(len(times_us), dtype=np.float64)

    for element in entry.elements:
        if element.channel != "luma" or element.nominal is None:
            continue
        if element.kind == "staircase":
            for tread, window in zip(element.steps, _tread_windows(element)):
                inside = (times_us >= window[0]) & (times_us < window[1])
                out[inside] = vr.to_ire(tread, entry.system)
        elif element.kind in ("bar", "blanked"):
            inside = ((times_us >= element.start_us)
                      & (times_us < element.end_us))
            out[inside] = vr.to_ire(element.nominal, entry.system)

    for element in entry.elements:
        if element.channel != "luma" or element.nominal is None:
            continue
        if element.kind != "pulse":
            continue
        centre = (element.start_us + element.end_us) / 2.0
        half = (element.end_us - element.start_us) / 2.0
        if half <= 0:
            continue
        phase = (times_us - centre) / (2.0 * half) * np.pi
        out += vr.to_ire(element.nominal, entry.system) * np.where(
            np.abs(phase) < np.pi / 2, np.cos(phase) ** 2, 0.0)
    return out


def measure_time_offset(geom: FieldGeometry, line: int, entry,
                        search_us: float = TIME_ALIGN_SEARCH_US):
    """Where a definition actually sits on a line, in us from its stated time.

    Returns (offset_us, correlation).  A negative offset means the disc
    carries the signal earlier than the definition states, which is what GGV
    PAL does by 0.85 us across its whole line 19 test signal.

    The measured luminance is correlated against luma_template() over a
    range of sub-sample lags; the correlation is normalised, so it is a
    quality figure in -1..1 that does not depend on the decode's gain.  When
    the definition has no luminance structure to correlate - the PAL
    chrominance bar line is a flat pedestal - the offset is 0 and the
    correlation is reported as 0, and the caller measures unaligned.
    """
    # Widened by the search range, so the outermost elements' own edges are
    # inside the window rather than sitting on its boundary: the PAL
    # chrominance bar line has no luminance structure but its pedestal, and
    # a window that stopped at the pedestal's ends would see a flat line.
    # Clipped to the capture's active region so the widening never reaches
    # the next line's sync, which the template knows nothing about.
    active_start_us = geom.params.active_video_start / geom.fs_mhz
    active_end_us = geom.params.active_video_end / geom.fs_mhz
    lo = max(min(element.start_us for element in entry.elements) - search_us,
             active_start_us)
    hi = min(max(element.end_us for element in entry.elements) + search_us,
             active_end_us)
    measured = _suppress_subcarrier(geom.segment(line, lo, hi))
    if len(measured) < 16:
        return 0.0, 0.0

    fs = geom.fs_mhz
    first, _ = geom.bounds(line, lo, hi)
    # The four-tap null delays by 1.5 samples: filtered sample k is the
    # average of input samples first+k to first+k+3, so it sits 1.5 samples
    # later than its index says.  Getting this sign wrong biases every
    # offset by three samples, which is 0.21 us on NTSC.
    origin = geom.sample(line, 0.0) - 1.5
    times_us = (first + np.arange(len(measured)) - origin) / fs

    reference = luma_template(entry, times_us)
    if np.ptp(reference) < 1.0:
        return 0.0, 0.0

    lags = np.arange(-int(round(search_us * fs)), int(round(search_us * fs)) + 1)
    scores = np.array([
        _normalised_correlation(
            measured, luma_template(entry, times_us - lag / fs))
        for lag in lags
    ])
    best = int(np.argmax(scores))
    offset_samples = float(lags[best])
    correlation = float(scores[best])
    if 0 < best < len(lags) - 1:
        a, b, c = scores[best - 1], scores[best], scores[best + 1]
        denominator = a - 2 * b + c
        if denominator < 0:
            step = 0.5 * (a - c) / denominator
            if abs(step) <= 1.0:
                offset_samples += step
    return offset_samples / fs, correlation


def _normalised_correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson correlation of two equal-length signals, or 0 if degenerate."""
    a = a - np.mean(a)
    b = b - np.mean(b)
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denominator <= 0:
        return 0.0
    return float(np.dot(a, b) / denominator)


def align_geometry(geom: FieldGeometry, line: int, entry,
                   search_us: float = TIME_ALIGN_SEARCH_US):
    """(geometry slid onto the signal, offset_us, correlation).

    The offset is only applied when the correlation reaches
    TIME_ALIGN_MIN_CORRELATION; a poor fit leaves the geometry alone rather
    than sliding the windows onto whatever correlated best.
    """
    offset_us, correlation = measure_time_offset(geom, line, entry, search_us)
    if correlation < TIME_ALIGN_MIN_CORRELATION:
        return geom, 0.0, correlation
    return geom.aligned(geom.alignment_us + offset_us), offset_us, correlation

# ---------------------------------------------------------------------------
# Whole-definition measurement
# ---------------------------------------------------------------------------

def measure_element(geom: FieldGeometry, line: int, element, entry=None,
                    bar_ire: Optional[float] = None) -> Measurement:
    """Measure one element, dispatching on its kind.

    entry, when given, is the definition the element belongs to; it is used
    only to decide whether a luminance window carries superimposed
    chrominance that has to be filtered out before the level is read.
    """
    system = geom.params.system
    chroma_here = (entry is not None
                   and element.channel == "luma"
                   and chroma_expected(entry, element.start_us, element.end_us))

    if element.kind in ("bar", "blanked"):
        windows = ([(element.start_us, element.end_us)] if entry is None
                   else _uncovered_windows(entry, element))
        measurement = measure_level_over(
            geom, line, windows,
            element_id=element.id, channel=element.channel,
            suppress_subcarrier=chroma_here,
        )
        measurement.kind = element.kind
        measurement.nominal = _nominal_ire(element, system)
        measurement.tolerance = _tolerance_ire(element, system)
        return measurement
    if element.kind == "staircase":
        return measure_staircase(
            geom, line, element, system, suppress_subcarrier=chroma_here)
    if element.kind == "burst_packet":
        return measure_burst_packet(geom, line, element, system)
    if element.kind == "chroma_bar":
        windows = None if entry is None else _chroma_subwindows(entry, element)
        return measure_chroma(geom, line, element, system, windows)
    if element.kind == "pulse":
        return measure_pulse(
            geom, line, element, system, bar_ire=bar_ire,
            suppress_subcarrier=chroma_here)
    raise ValueError(f"{element.id}: unknown element kind {element.kind!r}")


def measure_definition(field, entry, line: Optional[int] = None,
                       geom: Optional[FieldGeometry] = None,
                       align: bool = True) -> Dict[str, Measurement]:
    """Measure every element of a definition on one line.

    Returns {element_id: Measurement}.  Bars are measured first so the
    largest of them can serve as the pulse-to-bar reference, which is what
    the 2T and 20T ratios are stated against.

    With align set (the default) the definition is first slid onto the
    signal by align_geometry(), because real discs insert their test
    signals off the stated timing and a 0.4 us pulse window has no room to
    absorb that.  The offset applied is reported in every measurement's
    detail as alignment_us, so a timing deviation is visible rather than
    silently corrected.  Pass align=False to measure at the stated times.

    An element that cannot be measured at all (a window off the end of the
    row, a packet too short to fit) is left out of the result rather than
    reported as zero; the caller sees a missing key, not a fabricated value.
    """
    if geom is None:
        geom = FieldGeometry(field)
    if line is None:
        line = entry.field_line

    offset_us, correlation = 0.0, 0.0
    if align:
        geom, offset_us, correlation = align_geometry(geom, line, entry)

    measurements: Dict[str, Measurement] = {}
    ordered = ([element for element in entry.elements
                if element.kind in ("bar", "blanked")]
               + [element for element in entry.elements
                  if element.kind not in ("bar", "blanked")])

    bar_ire = None
    for element in ordered:
        try:
            measurement = measure_element(geom, line, element, entry, bar_ire)
        except ValueError:
            continue
        measurements[element.id] = measurement
        if (element.kind == "bar" and element.channel == "luma"
                and element.nominal is not None
                and vr.to_ire(element.nominal, geom.params.system) >= 50.0):
            # The white reference bar of the definition, whichever it is
            # called; the pulse ratios are stated against it.
            if bar_ire is None or measurement.value > bar_ire:
                bar_ire = measurement.value

    for measurement in measurements.values():
        measurement.detail["alignment_us"] = offset_us
        measurement.detail["alignment_correlation"] = correlation
    return measurements

# ---------------------------------------------------------------------------
# Coherent averaging
# ---------------------------------------------------------------------------

def average_fields(fields, count: int = 10, phase_locked: bool = True,
                   parity: Optional[bool] = None):
    """Coherently average fields that share a sample lattice.

    Random noise falls as the square root of the field count, which is what
    makes a sine fit over a short multiburst packet unbiased rather than
    merely noisy.  Only fields that land on the same lattice may be
    averaged, so they are grouped before averaging:

      phase_locked=True   group by field_phase_id, so the subcarrier
                          sequence position matches too.  Required for any
                          chrominance measurement: averaging across the
                          8-field PAL (4-field NTSC) sequence cancels
                          chroma outright.
      phase_locked=False  group by parity only.  Enough for luminance and
                          for multiburst packets, which are not locked to
                          the subcarrier, and reaches the requested count
                          from a quarter to an eighth as many fields.

    parity, when given, restricts the group to first (True) or second
    (False) fields.

    Returns (averaged_field, n_used).  The result is a shallow copy of the
    first field of the group carrying a float64 dspicture, so it keeps that
    field's params and cvbs_row_starts, and gains n_averaged and
    phase_locked attributes that the chroma primitives read.
    """
    if count < 1:
        raise ValueError(f"count must be at least 1, got {count}")
    usable = [f for f in fields
              if parity is None or bool(f.isFirstField) == parity]
    if not usable:
        raise ValueError("no fields of the requested parity")

    groups: Dict[object, list] = {}
    for item in usable:
        key = item.fieldPhaseID if phase_locked else bool(item.isFirstField)
        groups.setdefault(key, []).append(item)
    group = max(groups.values(), key=len)[:count]

    averaged = copy.copy(group[0])
    averaged.dspicture = np.mean(
        [item.dspicture.astype(np.float64) for item in group], axis=0)
    averaged.n_averaged = len(group)
    averaged.phase_locked = bool(phase_locked) or len(group) == 1
    return averaged, len(group)
