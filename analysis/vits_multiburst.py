#!/usr/bin/env python3
"""
vits_multiburst - multiburst frequency-response conformance

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Turns the per-packet measurements analysis/vits_measure.py produces into a
frequency response: which published packet set the line carries, each
packet's measured centre frequency and amplitude, and its amplitude in dB
relative to the reference packet.  analysis/vits_conformance.py renders the
verdicts; the decisions about what may be judged, and against what, are all
here.

Two faults are kept apart on purpose.  A **frequency** error is a time-base
fault: the line is the right signal played at the wrong rate.  An
**amplitude** error is a response fault: the right frequencies at the wrong
levels.  Confusing them wastes triage, so they carry separate check
identifiers and separate failure messages, and a packet may fail one while
passing the other.

Flatness is judged in dB about the reference packet rather than against the
absolute nominal, which is the convention lddecode/decoder.py's video EQ
servo uses (_veq_estimate) and what makes the figure meaningful: the whole
train is read through one window model, so a common under-read cancels.  It
is judged only where a decode actually claims flatness - inside the band the
EQ servo anchors.  Above that the EQ is pinned to 0 dB by design and the
subcarrier region stays owned by the burst calibration, so what remains is
the disc's own recorded response; GGV PAL's +1.5-3 dB peak at 4-4.8 MHz is
recorded in docs/technical/vits-servos.md as exactly that, and demanding
flatness there would report a conformant disc as faulty.  Those packets are
measured and reported, not judged.

The absolute amplitude of every packet against the level its own figure
states is a separate matter and belongs to the level checks; this module is
about the shape of the response, not its height.
"""

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Optional, Sequence, Tuple

import numpy as np

# Local: analysis/ is a directory of scripts rather than a package, and every
# entry point puts it on sys.path before importing this module.
import vits_reference as vr
from vits_identify import identify_multiburst_set

__all__ = [
    "PacketResponse",
    "amplitude_admissible",
    "flatness_judgement",
    "frequency_clause",
    "frequency_band_mhz",
    "frequency_judgement",
    "multiburst_response",
    "servo_band_mhz",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Frequency range a packet must fall in to be the reference the other
#: packets are reported against.  lddecode/decoder.py _veq_estimate takes
#: the first packet in 0.75-1.45 MHz as its reference, and
#: docs/technical/vits-servos.md describes the servo's deviations as
#: "relative to the ~1 MHz reference packet"; every published set in
#: vits_reference.MULTIBURST_SETS has exactly one packet in this range.
REFERENCE_BAND_MHZ = (0.75, 1.45)

#: The band the video EQ servo anchors, and so the only band in which a
#: decode claims a flat response.  lddecode/decoder.py _veq_estimate skips
#: any packet below 0.7 MHz or above self.veq_max_freq, which __init__ sets
#: to 3.6 MHz for PAL and 2.8 MHz for NTSC so the EQ - pinned to 0 dB beyond
#: its last anchor plus 0.5 MHz - never reaches the chroma band.
SERVO_ANCHOR_MIN_MHZ = 0.7
SERVO_ANCHOR_MAX_MHZ = {"PAL": 3.6, "NTSC": 2.8}

#: Bands whose response a conformant disc is not required to record flat and
#: a conformant decode is not permitted to correct.  docs/technical/
#: vits-servos.md, "Known residual": GGV's disc-recorded +1.5-3 dB peak at
#: 4-4.8 MHz on PAL lies inside the chroma sidebands, where a
#: composite-domain filter cannot serve luminance and chrominance at once,
#: so the EQ deliberately leaves it alone.  These sit above
#: SERVO_ANCHOR_MAX_MHZ and would be reported unjudged anyway; they are
#: named so the report can say which recorded residual a packet fell in
#: rather than only that it was out of band.
UNCORRECTED_BANDS_MHZ = {
    "PAL": ((4.0, 4.8),),
    "NTSC": (),
}

#: Same-parity fields that must be coherently averaged before the NTC-7
#: combination multiburst may be judged on amplitude at all.  Its packets
#: are about 3 us long, as short as the scan window at NTSC 4fsc, and
#: docs/technical/vits-servos.md records the single-line fit under-reading
#: by up to 2.5 dB with the wrong sign.  vits_measure now corrects the
#: window-occupancy part of that under-read, which is what makes the figure
#: usable at all; the averaging requirement stands because the correction
#: divides by an occupancy estimated from the fit residual, and on a single
#: field that residual is as much noise as it is gating.
NTC7_MIN_AVERAGE_FIELDS = 10


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

@dataclass
class PacketResponse:
    """One multiburst packet, as measured.

    relative_db is the amplitude in dB about the reference packet; it is
    0.0 on the reference itself.  nominal_freq_mhz comes from the matched
    published set, not from the definition, because real discs carry a
    different set from the one their figure states (vits_reference
    PAL_MULTIBURST_ITU).
    """

    element_id: str
    source: str
    freq_mhz: float
    nominal_freq_mhz: Optional[float]
    amplitude_ire: float
    relative_db: float
    cycles: float
    duty: float
    quality: float
    is_reference: bool = False
    in_servo_band: bool = False
    uncorrected_band: Optional[Tuple[float, float]] = None
    detail: dict = dataclass_field(default_factory=dict)

    @property
    def freq_error_mhz(self):
        if self.nominal_freq_mhz is None:
            return None
        return self.freq_mhz - self.nominal_freq_mhz


def servo_band_mhz(system):
    """The frequency band a decode claims a flat response over."""
    if system not in SERVO_ANCHOR_MAX_MHZ:
        known = ", ".join(sorted(SERVO_ANCHOR_MAX_MHZ))
        raise KeyError(f"No servo band for {system!r} (have: {known})")
    return SERVO_ANCHOR_MIN_MHZ, SERVO_ANCHOR_MAX_MHZ[system]


def _uncorrected_band(freq_mhz, system):
    """The recorded uncorrectable band a frequency falls in, or None."""
    for low, high in UNCORRECTED_BANDS_MHZ.get(system, ()):
        if low <= freq_mhz <= high:
            return (low, high)
    return None


def _reference_index(rows: Sequence[PacketResponse]):
    """Which packet the others are reported against, or None.

    The packet nearest 1 MHz inside REFERENCE_BAND_MHZ, so a train missing
    its 1 MHz packet reports no relative response rather than silently
    referring everything to whichever packet happened to come first.
    """
    candidates = [
        index for index, row in enumerate(rows)
        if REFERENCE_BAND_MHZ[0] <= row.freq_mhz <= REFERENCE_BAND_MHZ[1]
        and row.amplitude_ire > 0.0
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda i: abs(rows[i].freq_mhz - 1.0))


def multiburst_response(entry, measurements, system=None):
    """The frequency response of one multiburst line.

    Returns (set_name, set_score, rows).  set_name is the published set the
    measured frequencies matched, which may not be the one the definition
    was written from; rows are in packet order, with relative_db filled in
    once a reference packet has been found.
    """
    system = system or entry.system
    packets = [element for element in entry.elements
               if element.kind == "burst_packet"
               and element.id in measurements]
    if not packets:
        return None, 0.0, []

    measured = [measurements[element.id] for element in packets]
    freqs = [m.detail.get("freq_mhz", 0.0) for m in measured]
    set_name, nominals, set_score = identify_multiburst_set(freqs, system)

    low, high = servo_band_mhz(system)
    rows = []
    for index, (element, measurement) in enumerate(zip(packets, measured)):
        freq = float(measurement.detail.get("freq_mhz", 0.0))
        nominal = (float(nominals[index]) if index < len(nominals) else None)
        rows.append(PacketResponse(
            element_id=element.id,
            source=element.source or entry.source,
            freq_mhz=freq,
            nominal_freq_mhz=nominal,
            amplitude_ire=float(measurement.value),
            relative_db=float("nan"),
            cycles=float(measurement.detail.get("cycles", 0.0)),
            duty=float(measurement.detail.get("duty", 0.0)),
            quality=float(measurement.quality),
            in_servo_band=low <= freq <= high,
            uncorrected_band=_uncorrected_band(freq, system),
            detail={"nominal_ire": measurement.nominal},
        ))

    reference = _reference_index(rows)
    if reference is not None:
        rows[reference].is_reference = True
        base = rows[reference].amplitude_ire
        for row in rows:
            if row.amplitude_ire > 0.0:
                row.relative_db = float(
                    20.0 * np.log10(row.amplitude_ire / base))
    return set_name, set_score, rows


# ---------------------------------------------------------------------------
# What may be judged, and against what
# ---------------------------------------------------------------------------

def frequency_band_mhz(row: PacketResponse, system):
    """(spec_tolerance, allowance) for one packet's frequency, in MHz.

    The specification tolerance is a fraction of the matched nominal; the
    allowance is the estimator's own resolution, which scales with the
    window rather than with the frequency, so it is stated in cycles and
    divided by the window's duration here.
    """
    nominal = row.nominal_freq_mhz or 0.0
    spec = vr.MULTIBURST_FREQ_TOLERANCE.get(system, 0.0) * abs(nominal)
    duration_us = (row.cycles / row.freq_mhz) if row.freq_mhz > 0.0 else 0.0
    allowance = (vr.MULTIBURST_FREQ_ALLOWANCE_CYCLES / duration_us
                 if duration_us > 0.0 else float("inf"))
    return spec, allowance


def frequency_clause(row: PacketResponse, set_name, system):
    """The clause a packet's centre frequency is judged under.

    The nominal comes from whichever published set the line matched, which
    is not always the one the definition was written from, so the set is
    named beside the clause that states the tolerance.
    """
    stated = ("IEC 60856-1986 9.1.3 Figure 8 c)" if system == "PAL"
              else row.source)
    return f"{stated}, against the {set_name or 'unmatched'} frequency set"


def frequency_judgement(row: PacketResponse):
    """(judge, reason) for one packet's measured centre frequency."""
    if row.freq_mhz <= 0.0 or row.nominal_freq_mhz is None:
        return False, "no tone measured in this packet's window"
    if row.cycles < vr.MULTIBURST_FREQ_MIN_CYCLES:
        return False, (
            f"window holds {row.cycles:.1f} cycles, below "
            f"{vr.MULTIBURST_FREQ_MIN_CYCLES:.1f}; the estimator's own bias "
            f"stops improving there")
    return True, ""


def amplitude_admissible(entry, fields_averaged):
    """(admissible, reason) for amplitude conformance on a whole signal.

    Whether any amplitude - absolute level or relative flatness - measured
    from this definition may be judged at all.  An element the reference
    data marks as not amplitude-measurable is admissible only when enough
    same-parity fields were coherently averaged to make its short packets
    readable; see NTC7_MIN_AVERAGE_FIELDS.
    """
    if all(element.amplitude_measurable for element in entry.elements):
        return True, ""
    if fields_averaged >= NTC7_MIN_AVERAGE_FIELDS:
        return True, ""
    return False, (
        f"amplitude needs at least {NTC7_MIN_AVERAGE_FIELDS} coherently "
        f"averaged same-parity fields on this signal, and {fields_averaged} "
        f"were available; see vits_reference.NTSC_MULTIBURST_NTC7")


def flatness_judgement(entry, row: PacketResponse, reference, fields_averaged,
                       system):
    """(judge, reason) for one packet's dB deviation from the reference."""
    admissible, reason = amplitude_admissible(entry, fields_averaged)
    if not admissible:
        return False, reason
    if reference is None:
        return False, (
            f"no reference packet in {REFERENCE_BAND_MHZ[0]:.2f}-"
            f"{REFERENCE_BAND_MHZ[1]:.2f} MHz to report against")
    if row.is_reference:
        return False, "this is the reference packet the others are read from"
    if not np.isfinite(row.relative_db):
        return False, "no tone measured in this packet's window"
    if row.uncorrected_band is not None:
        low, high = row.uncorrected_band
        return False, (
            f"{low:.1f}-{high:.1f} MHz is recorded as a band the disc's own "
            f"response is not flat over and the video EQ deliberately does "
            f"not correct; see docs/technical/vits-servos.md")
    if not row.in_servo_band:
        low, high = servo_band_mhz(system)
        return False, (
            f"{row.freq_mhz:.2f} MHz is outside the {low:.1f}-{high:.1f} MHz "
            f"band the video EQ anchors, where it is pinned to 0 dB and the "
            f"response is the disc's own")
    return True, ""
