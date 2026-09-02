#!/usr/bin/env python3
"""
vits_identify - work out which VITS a decoded CVBS field actually carries

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Scores every definition in analysis/vits_reference.py against every
candidate line of a field, using the measurements analysis/vits_measure.py
takes, and reports the best match per line.  Run directly it prints what a
capture carries and what each element of it measures.

Matching is by measured content, never by line number.  Real discs move
these signals: the PAL multiburst sits on frame line 13 or 20 depending on
the pressing, and the frequency set on the disc is usually the ITU one
rather than the IEC one IEC 60856-1986 9.1.3 states.  A line number is
reported alongside a match as on_expected_line, and never used to make one.

The scoring is structural rather than conformant: a decode with a real level
or gain fault still has to be identified, or the conformance layer above
this never gets to report the fault.
"""

import sys
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Dict, Optional, Sequence

import numpy as np

# Local: analysis/ is a directory of scripts rather than a package, and every
# entry point puts it on sys.path before importing this module.
import vits_reference as vr
from vits_geometry import FieldGeometry
from vits_measure import (
    Measurement,
    TIME_ALIGN_MIN_CORRELATION,
    align_geometry,
    average_fields,
    chroma_expected,
    guarded_window,
    load,
    measure_definition,
)

__all__ = [
    "Identification",
    "identify_multiburst_set",
    "identify_vits",
    "run_report",
    "score_definition",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Identification gates.  Deliberately loose against the levels: a decode
#: with a real level fault still has to be identified so the conformance
#: layer can report the fault, rather than disappearing as "no VITS found".
IDENTIFY_LEVEL_TOLERANCE_IRE = 30.0
IDENTIFY_CHROMA_PRESENT_IRE = 5.0
IDENTIFY_FREQ_TOLERANCE_MHZ = 0.5
IDENTIFY_MIN_SCORE = 0.60

#: Every feature a definition offers must also clear this on its own.  The
#: mean alone is not enough: a PAL VBI data line reads as six low-frequency
#: "packets" that match no published multiburst set, yet its levels and its
#: chroma presence both score 1.0, and the mean of the three still clears
#: IDENTIFY_MIN_SCORE.  Requiring each feature makes the discriminating one
#: - here the frequency set - able to reject on its own.
IDENTIFY_FEATURE_FLOOR = 0.50

#: The features score_definition() averages into a match score.  Anything
#: else it reports - the alignment it found, the multiburst set it matched -
#: is evidence for the developer, not part of the verdict.
SCORED_FEATURES = ("levels", "chroma_present", "chroma_absent",
                   "frequency", "monotonic")

#: Field lines that may carry a VITS.  Vertical sync and the equalising
#: pulses end before these and the first active picture line follows them.
#: PAL reaches further up because IEC 60856-1986 9.1.3 Amendment 2 permits
#: the multiburst on frame line 13.
VITS_CANDIDATE_LINES = {
    "NTSC": tuple(range(10, 25)),
    "PAL": tuple(range(6, 24)),
}


@dataclass
class Identification:
    """Which VITS a field line was judged to carry, and how well it matched."""

    field_line: int
    vits_id: str
    score: float
    on_expected_line: bool
    features: dict = dataclass_field(default_factory=dict)


def identify_multiburst_set(freqs_mhz: Sequence[float], system: str):
    """Which published multiburst set a measured packet train matches.

    Returns (name, frequencies, score) for the best match among
    vits_reference.MULTIBURST_SETS[system], with score in 0..1 falling to 0
    at IDENTIFY_FREQ_TOLERANCE_MHZ of error per packet.  Real PAL discs
    carry the ITU set rather than the IEC one, so a measurement has to name
    the set it found instead of assuming the definition's.
    """
    measured = [f for f in freqs_mhz if f and f > 0]
    if not measured:
        return None, (), 0.0

    best = (None, (), -1.0)
    for name, frequencies in vr.MULTIBURST_SETS[system].items():
        pairs = min(len(measured), len(frequencies))
        if pairs == 0:
            continue
        errors = [abs(measured[i] - frequencies[i]) for i in range(pairs)]
        score = float(np.mean([
            max(0.0, 1.0 - error / IDENTIFY_FREQ_TOLERANCE_MHZ)
            for error in errors
        ]))
        # A train that is missing packets cannot match a set as well as a
        # complete one, so scale by how much of the set was seen.
        score *= pairs / len(frequencies)
        if score > best[2]:
            best = (name, frequencies, score)
    return best


def score_definition(geom: FieldGeometry, line: int, entry):
    """How well a line's measured content matches a definition, 0..1.

    Scored on structure rather than on conformance, so a decode with a real
    level or gain fault is still identified and the fault is reported by the
    conformance layer instead of vanishing as "nothing found".  The features
    are, where a definition has them:

      levels          fraction of luminance bars within
                      IDENTIFY_LEVEL_TOLERANCE_IRE of nominal
      chroma_present  fraction of the definition's chrominance elements
                      actually carrying chrominance
      chroma_absent   fraction of its luminance-only windows correctly free
                      of chrominance
      frequency       mean per-packet agreement with the best-matching
                      published multiburst set
      monotonic       1 if every staircase rises, 0 if any tread falls

    Each of these must also clear IDENTIFY_FEATURE_FLOOR on its own; the
    mean alone lets two soft features outvote the discriminating one.

    A line whose waveform the definition could not be located on at all -
    an alignment correlation below vits_measure.TIME_ALIGN_MIN_CORRELATION,
    which is already the threshold below which the measured offset is not
    believed - scores 0 whatever its levels read.  The features above are
    all deliberately loose against levels, so that a decode with a real
    fault is still identified; that looseness has to be paid for by
    requiring the shape.  Four coherently averaged fields of moving picture
    average to something flat and low, which reads as a plausible set of
    levels and matched the PAL chrominance reference on a picture line at
    score 1.0 with a correlation of 0.46, against 0.98 for the real one on
    the same field.

    Returns (score, features).  Definitions whose only elements are blanked
    score None: a blank line has no content to match, so it can only be
    recognised by the line number the standard names, and that check belongs
    with the conformance rule rather than here.
    """
    system = geom.params.system
    if all(element.kind == "blanked" for element in entry.elements):
        return None, {"reason": "blanked line has no content to match"}

    geom, offset_us, correlation = align_geometry(geom, line, entry)
    features = {"alignment_us": offset_us,
                "alignment_correlation": correlation}
    if correlation < TIME_ALIGN_MIN_CORRELATION:
        features["reason"] = "definition's shape not found on this line"
        return 0.0, features

    measurements = measure_definition(geom.field, entry, line, geom, align=False)
    if not measurements:
        features["reason"] = "nothing measurable on the line"
        return 0.0, features

    levels = []
    for element in entry.elements:
        if element.kind != "bar" or element.channel != "luma":
            continue
        if element.nominal is None or element.id not in measurements:
            continue
        nominal = vr.to_ire(element.nominal, system)
        error = abs(measurements[element.id].value - nominal)
        levels.append(1.0 if error <= IDENTIFY_LEVEL_TOLERANCE_IRE else 0.0)
    if levels:
        features["levels"] = float(np.mean(levels))

    # Presence and absence are scored apart.  Averaged together, a line that
    # carries none of the chrominance a definition requires still scores two
    # thirds, because its two luminance-only windows are correctly free of
    # chroma - which is how three blank VBI lines were each identified as an
    # NTSC VIRS.  A definition's chrominance has to be there.
    present_scores = []
    absent_scores = []
    for element in entry.elements:
        if element.id not in measurements:
            continue
        if element.channel == "chroma":
            present_scores.append(float(
                measurements[element.id].value >= IDENTIFY_CHROMA_PRESENT_IRE))
        else:
            if chroma_expected(entry, element.start_us, element.end_us):
                continue  # a luma window under a chroma element proves nothing
            window = guarded_window(*element.window_us)
            _, amplitude, _ = geom.demod(line, window[0], window[1])
            absent_scores.append(float(
                amplitude is None
                or amplitude < IDENTIFY_CHROMA_PRESENT_IRE))
    if present_scores:
        features["chroma_present"] = float(np.mean(present_scores))
    if absent_scores:
        features["chroma_absent"] = float(np.mean(absent_scores))

    packets = [element for element in entry.elements
               if element.kind == "burst_packet"]
    if packets:
        measured = [measurements[element.id].detail["freq_mhz"]
                    for element in packets if element.id in measurements]
        name, frequencies, score = identify_multiburst_set(measured, system)
        features["frequency"] = score
        features["multiburst_set"] = name
        features["multiburst_freqs_mhz"] = [float(f) for f in measured]

    staircases = [measurements[element.id] for element in entry.elements
                  if element.kind == "staircase" and element.id in measurements]
    if staircases:
        features["monotonic"] = float(
            all(item.detail["monotonic"] for item in staircases))

    numeric = [value for key, value in features.items()
               if key in SCORED_FEATURES]
    if not numeric:
        return 0.0, features
    if min(numeric) < IDENTIFY_FEATURE_FLOOR:
        return 0.0, features
    return float(np.mean(numeric)), features


def identify_vits(field, lines: Optional[Sequence[int]] = None,
                  geom: Optional[FieldGeometry] = None
                  ) -> Dict[int, Identification]:
    """Which VITS each candidate field line carries.

    Every definition for the system is scored against every candidate line;
    the line number is never the reason for a match, only something reported
    alongside it as on_expected_line, because real discs move these signals
    (the PAL multiburst sits on frame line 13 or 20 depending on the
    pressing).

    Where two definitions are indistinguishable by content - the NTSC VIRS
    is identical in both parities - the tie is broken on the field's own
    parity, which is a measured property of the field and not a line number.

    Returns {field_line: Identification} for the lines that scored at least
    IDENTIFY_MIN_SCORE.
    """
    if geom is None:
        geom = FieldGeometry(field)
    system = geom.params.system
    if lines is None:
        lines = VITS_CANDIDATE_LINES[system]

    parity = 1 if field.isFirstField else 2
    found: Dict[int, Identification] = {}

    for line in lines:
        if not 1 <= line <= geom.params.field_height:
            continue
        best = None
        for entry in vr.definitions_for(system):
            try:
                score, features = score_definition(geom, line, entry)
            except ValueError:
                continue
            if score is None or score < IDENTIFY_MIN_SCORE:
                continue
            expected_lines = {entry.field_line}
            if entry.alternate_frame_line is not None:
                expected_lines.add(vr.frame_line_to_field(
                    system, entry.alternate_frame_line)[1])
            candidate = Identification(
                field_line=line,
                vits_id=entry.id,
                score=score,
                on_expected_line=line in expected_lines,
                features=features,
            )
            rank = (score, entry.field == parity, candidate.on_expected_line)
            if best is None or rank > best[0]:
                best = (rank, candidate)
        if best is not None:
            found[line] = best[1]
    return found


def _format_measurement(name: str, measurement: Measurement) -> str:
    parts = [f"      {name:<24s} {measurement.value:8.2f} IRE"]
    if measurement.nominal is not None:
        parts.append(f"  nominal {measurement.nominal:7.2f}"
                     f"  dev {measurement.deviation:+7.2f}")
    if measurement.kind == "burst_packet":
        parts.append(f"  {measurement.detail['freq_mhz']:5.3f} MHz")
    if measurement.kind == "pulse" and measurement.detail["had_ns"]:
        parts.append(f"  HAD {measurement.detail['had_ns']:6.1f} ns")
        if measurement.detail["pulse_to_bar"]:
            parts.append(f"  p/b {measurement.detail['pulse_to_bar']:5.3f}")
    parts.append(f"  q {measurement.quality:4.2f}")
    return "".join(parts)


def run_report(path: str, max_fields: Optional[int] = None,
               average: int = 1) -> int:
    """Print what a CVBS capture carries.  Returns a process exit status."""
    params, fields, _ = load(path, max_fields)
    if not fields:
        print(f"{path}: no fields")
        return 2

    print(f"{path}: {params}")
    identified = 0
    for parity in (True, False):
        parity_fields = [f for f in fields if bool(f.isFirstField) == parity]
        if not parity_fields:
            continue
        if average > 1:
            # Phase locked, not merely same-parity: averaging across the
            # colour sequence cancels chrominance outright, and this report
            # measures chrominance elements.  The cost is needing four
            # (NTSC) to eight (PAL) times as many fields to reach a count.
            probe, used = average_fields(
                parity_fields, average, phase_locked=True)
        else:
            probe, used = parity_fields[0], 1

        geom = FieldGeometry(probe)
        origin = ("measured" if geom.origin_measured
                  else "row boundary (sync not found)")
        print(f"  {'first' if parity else 'second'} field, {used} averaged, "
              f"0H origin {geom.origin_samples:+.2f} samples ({origin})")
        if used < average:
            print(f"      only {used} of the {average} requested fields share "
                  "a subcarrier sequence position; decode more to average "
                  "further")

        for line, identification in sorted(identify_vits(probe, geom=geom).items()):
            identified += 1
            marker = "" if identification.on_expected_line else "  [moved]"
            print(f"    line {line:3d}  {identification.vits_id:<24s} "
                  f"score {identification.score:4.2f}{marker}")
            offset = identification.features.get("alignment_us", 0.0)
            if abs(offset) > 0.05:
                print(f"      timing offset {offset:+.2f} us "
                      f"(correlation "
                      f"{identification.features['alignment_correlation']:.2f})")
            if identification.features.get("multiburst_set"):
                print(f"      multiburst set "
                      f"{identification.features['multiburst_set']}")
            entry = vr.definition(identification.vits_id)
            for name, measurement in measure_definition(
                    probe, entry, line, geom).items():
                print(_format_measurement(name, measurement))

    print(f"VITS IDENTIFY: {'PASS' if identified else 'FAIL'} "
          f"({identified} signals)")
    return 0 if identified else 2


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        print("usage: vits_identify.py <file.cvbs> [max_fields] [average]")
        return 1
    path = sys.argv[1]
    max_fields = int(sys.argv[2]) if len(sys.argv) > 2 else None
    average = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    return run_report(path, max_fields, average)


if __name__ == "__main__":
    sys.exit(main())
