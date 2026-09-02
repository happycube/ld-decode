#!/usr/bin/env python3
"""
vits_conformance - judge a decoded CVBS capture against the VITS standards

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Takes the measurements analysis/vits_measure.py produces from the signals
analysis/vits_identify.py finds, and decides whether each one conforms.
Every verdict names the clause it enforces and shows the band it was judged
against, split into the specification's own tolerance and the decoder
allowance from analysis/vits_reference.py.

Three families of check:

*   **Absolute levels.**  Every element of every identified signal, plus the
    IEC 60856-1986 9.1.5 / IEC 60857-1986 9.1.6 ceilings and the PAL
    requirement that frame lines 22 and 335 be blanked.
*   **Differential levels**, the class of fault this exists to catch, where
    the low-frequency and high-frequency components of the same signal are
    independently mis-scaled: differential gain and phase, luminance and
    chrominance non-linearity, and the luminance/chrominance gain ratio.  A
    decode that scales luminance correctly and chrominance incorrectly
    passes every absolute luminance check and fails these.
*   **Multiburst frequency response**, in analysis/vits_multiburst.py: each
    packet's measured centre frequency against the published set the line
    actually carries, and its amplitude in dB about the reference packet
    across the band a decode claims to hold flat.

The final line is exactly one of

    VITS CONFORMANCE: PASS (...)
    VITS CONFORMANCE: FAIL (...)
    VITS CONFORMANCE: SKIPPED (no VITS detected)

matching the convention analysis/cvbs_verify.py uses, so a CTest entry can
gate on it with PASS_REGULAR_EXPRESSION.  --json writes the same checks as a
sidecar for CI artefact upload.

CVBS only; see analysis/vits_measure.py for why.
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from dataclasses import field as dataclass_field
from typing import Dict, List, Optional, Tuple

import numpy as np

# Local: analysis/ is a directory of scripts rather than a package, and every
# entry point puts it on sys.path before importing this module.
import vits_reference as vr
from video_common import (
    CHROMA_BAR_STEP_RATIOS,
    chrominance_gain_nonlinearity,
    differential_gain,
    differential_phase,
)
from vits_geometry import FieldGeometry
from vits_identify import identify_vits
from vits_manifest import (
    load_manifest,
    manifest_entry,
    presence_verdicts,
)
from vits_measure import (
    align_geometry,
    average_fields,
    load,
    measure_definition,
    pulse_under,
)
from vits_multiburst import (
    amplitude_admissible,
    flatness_judgement,
    frequency_band_mhz,
    frequency_clause,
    frequency_judgement,
    multiburst_response,
)

__all__ = [
    "Check",
    "check_blanked_lines",
    "check_carried",
    "check_ceilings",
    "check_chroma_nonlinearity",
    "check_differential",
    "check_levels",
    "check_luma_chroma_ratio",
    "check_multiburst",
    "check_staircases",
    "json_payload",
    "run_conformance",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Fields averaged per parity before measurement, unless overridden.  The
#: average is phase locked (see vits_measure.average_fields), because these
#: checks read chrominance amplitudes and an average across the colour
#: sequence cancels them.
DEFAULT_AVERAGE_FIELDS = 4

#: A measurement whose quality figure falls below this is reported but not
#: judged.  vits_measure's quality says how much of the window the primitive
#: could actually read; a level taken from a window the signal did not
#: occupy is not evidence either way, and turning it into a FAIL would
#: report a fault in the disc that is really a fault in the reading.
MIN_JUDGED_QUALITY = 0.20

#: Percentile used as the peak of the active picture when the level ceilings
#: are checked.  IEC states a ceiling on the signal, but a handful of
#: dropout samples in a field of roughly 290,000 must not condemn a disc, so
#: the peak is taken robustly and the absolute maximum is reported beside it.
CEILING_PERCENTILE = 99.99

#: Luminance range a chrominance element must span before differential gain
#: and phase are measured from it.  Both are defined as a change with
#: luminance (ITU-R BT.1439-1 3.3.1.3), so a chrominance bar sitting on one
#: flat pedestal has nothing to measure against; a five-riser staircase
#: spans about 90 IRE, so this separates the two cleanly.
DIFFERENTIAL_MIN_LUMA_SPAN_IRE = 40.0

#: Chrominance saturation, in per cent, is the carrier peak-to-peak level as
#: a proportion of the blanking-to-white reference: the 100% step of the PAL
#: three-level chrominance bar is 0.70 V p-p about a 50% pedestal (IEC
#: 60856-1986 9.1.3 Figure 10 a), which is what "100%" means in 9.1.5.
SATURATION_PER_CARRIER_PEAK = 2.0


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

@dataclass
class Check:
    """One conformance verdict.

    measured, nominal, spec_tolerance and allowance are all in `unit`.  band
    is spec_tolerance + allowance and is the figure the deviation is judged
    against; a check with no nominal (a ceiling) carries limit instead.

    allowance_kind names the budget the allowance came from - a key of
    vits_reference.DECODER_ALLOWANCES, or "multiburst_frequency" for the
    one allowance derived per packet from MULTIBURST_FREQ_ALLOWANCE_CYCLES
    rather than looked up.  It is what lets a survey across captures group a
    run's checks by the budget they were judged against without parsing
    their identifiers, which is how the radius baseline is built.
    """

    id: str
    label: str
    verdict: str
    measured: float
    unit: str
    clause: str
    nominal: Optional[float] = None
    allowance_kind: Optional[str] = None
    limit: Optional[float] = None
    spec_tolerance: Optional[float] = None
    allowance: Optional[float] = None
    band: Optional[float] = None
    field_line: Optional[int] = None
    parity: Optional[str] = None
    reason: str = ""
    detail: dict = dataclass_field(default_factory=dict)

    @property
    def deviation(self) -> Optional[float]:
        if self.nominal is None:
            return None
        return self.measured - self.nominal


def _verdict(deviation, band):
    return "PASS" if abs(deviation) <= band else "FAIL"


def _one_sided(measured, limit):
    return "PASS" if measured <= limit else "FAIL"


# ---------------------------------------------------------------------------
# Absolute levels
# ---------------------------------------------------------------------------

def _level_kind(element):
    """Which allowance an element's level is judged under."""
    if element.kind == "blanked" or element.nominal == 0.0:
        return "blanking_level"
    if element.channel == "chroma":
        return "chroma_level"
    return "luma_level"


def check_levels(entry, measurements, line, parity,
                 fields_averaged=1) -> List[Check]:
    """Absolute level of every element of one identified signal.

    Element tolerances are the specification's own; the decoder allowance
    comes from vits_reference.DECODER_ALLOWANCES.  NTSC elements carry no
    specification tolerance (no standard states a mastering tolerance for
    them), so their band is the allowance alone.

    fields_averaged decides whether a signal whose amplitude the reference
    data marks as unreadable from one line may be judged at all; the rule
    is vits_multiburst.amplitude_admissible, shared with the flatness
    checks so a signal cannot be refused by one and judged by the other.
    """
    checks = []
    for element in entry.elements:
        if element.nominal is None:
            continue
        if element.id not in measurements:
            checks.append(Check(
                id=f"{entry.id}/{element.id}",
                label=f"{element.label}, level",
                verdict="SKIP",
                measured=float("nan"),
                unit="IRE",
                clause=element.source or entry.source,
                nominal=vr.to_ire(element.nominal, entry.system),
                field_line=line,
                parity=parity,
                reason="element not measurable on this line",
            ))
            continue

        measurement = measurements[element.id]
        nominal = vr.to_ire(element.nominal, entry.system)
        spec = (0.0 if element.tolerance is None
                else vr.to_ire(element.tolerance, entry.system))
        kind = _level_kind(element)
        allowed = vr.allowance(kind).band(nominal)
        band = spec + allowed

        reason = ""
        admissible, refusal = amplitude_admissible(entry, fields_averaged)
        if not element.amplitude_measurable and not admissible:
            verdict = "SKIP"
            reason = refusal
        elif (element.channel == "chroma"
                and pulse_under(entry, element) is not None):
            # A chrominance component riding on a sine-squared pulse carries
            # that pulse's envelope, so the mean of its window is not its
            # amplitude.  What the standards take from a composite pulse is
            # the perturbation of the pulse's baseline (ITU-R BT.1439-1
            # section 3.3.2, EBU Tech. 3209 section 7.2.4 c), which is a
            # transient measurement and not this one.
            verdict = "SKIP"
            reason = ("chrominance of a composite pulse is not an amplitude "
                      "measurement; see EBU Tech. 3209 7.2.4 c)")
        elif measurement.quality < MIN_JUDGED_QUALITY:
            verdict = "SKIP"
            reason = (f"measurement quality {measurement.quality:.2f} below "
                      f"{MIN_JUDGED_QUALITY:.2f}")
        else:
            verdict = _verdict(measurement.value - nominal, band)

        checks.append(Check(
            id=f"{entry.id}/{element.id}",
            label=f"{element.label}, level",
            verdict=verdict,
            measured=measurement.value,
            unit="IRE",
            clause=element.source or entry.source,
            nominal=nominal,
            spec_tolerance=spec,
            allowance=allowed,
            allowance_kind=kind,
            band=band,
            field_line=line,
            parity=parity,
            reason=reason,
            detail={"quality": measurement.quality,
                    "alignment_us": measurement.detail.get("alignment_us")},
        ))
    return checks


def picture_peak_ire(geom):
    """Robust peak of the active picture, in IRE, with the absolute maximum.

    Reported as context, never judged.  IEC's ceiling is a statement about
    the mastered signal; applied per sample to a decode it is a statement
    about FM noise and edge overshoot instead - both CI captures carry
    0.1% (NTSC) and 0.9% (PAL) of their active samples above 110 IRE, with
    absolute peaks of 119.6 and 129.8, and no plausible allowance separates
    an over-level disc from a noisy one at that resolution.  The ceiling is
    judged on the signals whose level is known; see check_ceilings.
    """
    params = geom.params
    rows = geom.field.output_to_ire(geom.field.dspicture).reshape(
        params.field_height, params.field_width)
    active = rows[:, params.active_video_start:params.active_video_end]
    return (float(np.percentile(active, CEILING_PERCENTILE)),
            float(np.max(active)))


def check_ceilings(entry, measurements, line, parity) -> List[Check]:
    """The maximum-luminance ceiling, over an identified signal.

    IEC 60856-1986 9.1.5 and IEC 60857-1986 9.1.6 cap the *luminance* level
    at 110, and cap chrominance separately as a saturation (see
    check_saturation).  The two are named separately in the clause because
    the composite of both routinely exceeds either: the PAL modulated
    staircase reaches a nominal 120 IRE where its 20 IRE subcarrier rides
    the 100% tread, and is conformant.  So only the luminance component is
    judged here - including the pedestal a chrominance element sits on,
    which is a luminance level the definitions do not otherwise state.
    """
    peaks = []
    for element in entry.elements:
        if element.id not in measurements:
            continue
        measurement = measurements[element.id]
        if element.channel == "chroma":
            for zone in measurement.detail.get("zones", []):
                peaks.append((zone["luma_ire"], element.id))
        elif element.kind == "staircase":
            peaks.append((max(measurement.detail["treads_ire"]), element.id))
        elif element.kind in ("bar", "pulse"):
            peaks.append((measurement.value, element.id))
    if not peaks:
        return []

    peak, source = max(peaks)
    clause = ("IEC 60856-1986 9.1.5" if entry.system == "PAL"
              else "IEC 60857-1986 9.1.6")
    allowed = vr.allowance("level_ceiling").band()
    limit = vr.MAX_LUMINANCE_IRE + allowed
    return [Check(
        id=f"{entry.id}/ceiling/luminance",
        label="Maximum composite luminance excursion",
        verdict=_one_sided(peak, limit),
        measured=peak,
        unit="IRE",
        clause=clause,
        limit=limit,
        allowance=allowed,
        allowance_kind="level_ceiling",
        field_line=line,
        parity=parity,
        detail={"element": source},
    )]


def check_saturation(entry, measurements, line, parity) -> List[Check]:
    """The chrominance saturation ceiling, from a signal's own carriers."""
    peaks = [measurements[element.id].value
             for element in entry.elements
             if element.channel == "chroma" and element.id in measurements
             and pulse_under(entry, element) is None
             and element.amplitude_measurable]
    if not peaks:
        return []
    saturation = SATURATION_PER_CARRIER_PEAK * max(peaks)
    clause = ("IEC 60856-1986 9.1.5" if entry.system == "PAL"
              else "IEC 60857-1986 9.1.6")
    allowed = vr.allowance("level_ceiling").band()
    limit = vr.MAX_CHROMA_SATURATION_PERCENT + allowed
    return [Check(
        id=f"{entry.id}/ceiling/saturation",
        label="Maximum chrominance saturation",
        verdict=_one_sided(saturation, limit),
        measured=saturation,
        unit="percent",
        clause=clause,
        limit=limit,
        allowance=allowed,
        allowance_kind="level_ceiling",
        field_line=line,
        parity=parity,
    )]


def check_blanked_lines(geom, parity) -> List[Check]:
    """PAL frame lines 22 and 335 must be blanked.

    IEC 60856-1986 9.1.3: "The lines 22 and 335 shall be blanked before
    optical recording, to enable disk noise measurements."  The only
    unconditional requirement the PAL clause makes, and the only check here
    anchored to a line number rather than to measured content - a blank line
    has no content to identify it by, so the standard's line number is the
    whole of the definition.
    """
    if geom.params.system != "PAL":
        return []

    checks = []
    for entry in vr.definitions_for("PAL"):
        if not all(element.kind == "blanked" for element in entry.elements):
            continue
        if (entry.field == 1) != bool(geom.field.isFirstField):
            continue
        element = entry.elements[0]
        try:
            level = geom.segment(entry.field_line,
                                 element.start_us, element.end_us)
        except ValueError:
            continue
        if len(level) == 0:
            continue
        # The clause blanks these lines "to enable disk noise measurements",
        # so what must be absent is signal, not noise: the verdict is on the
        # line's mean level, and the noise it was blanked to expose is
        # reported beside it rather than judged.  A peak would judge the
        # noise instead - on a single PAL field the largest of 890 samples
        # reaches 6.6 IRE around a mean of 1.35.
        residual = abs(float(np.mean(level)))
        allowed = vr.allowance("blanking_level").band()
        checks.append(Check(
            id=f"{entry.id}/blanked",
            label=f"Frame line {entry.frame_line} blanked",
            verdict=_one_sided(residual, allowed),
            measured=residual,
            unit="IRE",
            clause=entry.source,
            limit=allowed,
            allowance=allowed,
            allowance_kind="blanking_level",
            field_line=entry.field_line,
            parity=parity,
            detail={"mean_ire": float(np.mean(level)),
                    "noise_rms_ire": float(np.sqrt(np.mean(level ** 2))),
                    "absolute_max_ire": float(np.max(np.abs(level)))},
        ))
    return checks


def check_carried(system, entry, found_ids, parity) -> List[Check]:
    """Whether every VITS the manifest records was found in this decode.

    Without this a capture that carries nothing prints PASS, because a check
    that is never attempted leaves no trace in the summary line.  The
    manifest turns "no NTC-7 checks were made" into "skipped: capture
    carries no ntsc-ntc7-combination", which is a statement a reader can act
    on.  See vits_manifest.presence_verdicts for the three cases.

    Only the definitions belonging to `parity` are judged.  The other
    parity's signals are not on this field to be found, and asking after
    them here would fail every one of them in turn.
    """
    field = 1 if parity == "first" else 2
    definitions = [definition for definition in vr.definitions_for(system)
                   if definition.field == field]
    checks = []
    for vits_id, verdict, reason in presence_verdicts(
            definitions, entry, found_ids):
        definition = vr.definition(vits_id)
        checks.append(Check(
            id=f"{vits_id}/carried",
            label=f"{vits_id} present as surveyed",
            verdict=verdict,
            measured=float("nan"),
            unit="",
            clause=definition.source,
            field_line=definition.field_line,
            parity=parity,
            reason=reason or "",
            detail={"manifest": entry.get("label") or entry.get("capture")},
        ))
    return checks


# ---------------------------------------------------------------------------
# Differential levels
# ---------------------------------------------------------------------------

def check_staircases(entry, measurements, line, parity) -> List[Check]:
    """Luminance non-linearity of every staircase on a signal.

    ITU-R BT.1439-1 section 3.3.1.1 defines it as the difference between the
    largest and smallest riser over the largest; EBU Tech. 3209 section
    7.2.2 d) sets the generator's own limit at 0.5% of the largest riser.
    A white-bar check cannot see this: the bar and the staircase top can
    both be right while the middle bows.
    """
    checks = []
    for element in entry.elements:
        if element.kind != "staircase" or element.id not in measurements:
            continue
        detail = measurements[element.id].detail
        inequality = detail["step_inequality"]
        spec = (vr.PAL_STAIRCASE_STEP_INEQUALITY if entry.system == "PAL"
                else 0.0)
        allowed = vr.allowance("step_inequality").band()
        limit = spec + allowed
        if not np.isfinite(inequality) or not detail["monotonic"]:
            verdict, reason = "SKIP", "staircase did not rise monotonically"
        else:
            verdict, reason = _one_sided(inequality, limit), ""
        checks.append(Check(
            id=f"{entry.id}/{element.id}/nonlinearity",
            label="Luminance non-linearity of the staircase",
            verdict=verdict,
            measured=float(inequality),
            unit="fraction",
            clause="ITU-R BT.1439-1 3.3.1.1; EBU Tech. 3209 7.2.2 d)",
            limit=limit,
            spec_tolerance=spec,
            allowance=allowed,
            allowance_kind="step_inequality",
            field_line=line,
            parity=parity,
            reason=reason,
            detail={"risers_ire": detail["risers_ire"],
                    "treads_ire": detail["treads_ire"]},
        ))
    return checks


def check_differential(entry, measurements, line, parity) -> List[Check]:
    """Differential gain and differential phase of a modulated staircase.

    ITU-R BT.1439-1 section 3.3.1.3 refers both to the subcarrier at
    blanking level, which is the first zone vits_measure reports for a
    chrominance element laid over a staircase.  The specification limits are
    the "inherent" ones EBU Tech. 3209 section 7.2.2 g) and h) place on the
    generator, and IEC 60856-1986 9.1.3 Figure 9 repeats for a LaserDisc
    master.
    """
    checks = []
    for element in entry.elements:
        if element.channel != "chroma" or element.id not in measurements:
            continue
        zones = measurements[element.id].detail.get("zones", [])
        if len(zones) < 3:
            continue
        lumas = [zone["luma_ire"] for zone in zones]
        if max(lumas) - min(lumas) < DIFFERENTIAL_MIN_LUMA_SPAN_IRE:
            # Not laid over a staircase: nothing varies the luminance.
            continue
        if any(zone["burst_relative_phase_deg"] is None for zone in zones):
            continue

        amplitudes = [zone["amp_ire"] for zone in zones]
        phases = [zone["burst_relative_phase_deg"] for zone in zones]
        table = {"lumas_ire": lumas, "amplitudes_ire": amplitudes,
                 "phases_deg": phases}

        try:
            dg_pp, dg_plus, dg_minus = differential_gain(amplitudes)
        except ValueError as error:
            checks.append(Check(
                id=f"{entry.id}/{element.id}/differential_gain",
                label="Differential gain", verdict="SKIP",
                measured=float("nan"), unit="fraction",
                clause="ITU-R BT.1439-1 3.3.1.3",
                field_line=line, parity=parity, reason=str(error),
                detail=table))
        else:
            spec = (vr.PAL_DIFFERENTIAL_GAIN_LIMIT if entry.system == "PAL"
                    else 0.0)
            allowed = vr.allowance("differential_gain").band()
            checks.append(Check(
                id=f"{entry.id}/{element.id}/differential_gain",
                label="Differential gain, peak to peak",
                verdict=_one_sided(dg_pp, spec + allowed),
                measured=dg_pp,
                unit="fraction",
                clause=("ITU-R BT.1439-1 3.3.1.3; EBU Tech. 3209 7.2.2 g); "
                        "IEC 60856-1986 9.1.3 Figure 9"),
                limit=spec + allowed,
                spec_tolerance=spec,
                allowance=allowed,
                allowance_kind="differential_gain",
                field_line=line,
                parity=parity,
                detail=dict(table, positive=dg_plus, negative=dg_minus),
            ))

        dp_pp, dp_plus, dp_minus = differential_phase(phases)
        spec = (vr.PAL_DIFFERENTIAL_PHASE_LIMIT_DEG if entry.system == "PAL"
                else 0.0)
        allowed = vr.allowance("differential_phase").band()
        checks.append(Check(
            id=f"{entry.id}/{element.id}/differential_phase",
            label="Differential phase, peak to peak",
            verdict=_one_sided(dp_pp, spec + allowed),
            measured=dp_pp,
            unit="degrees",
            clause=("ITU-R BT.1439-1 3.3.1.3; EBU Tech. 3209 7.2.2 h); "
                    "IEC 60856-1986 9.1.3 Figure 9"),
            limit=spec + allowed,
            spec_tolerance=spec,
            allowance=allowed,
            allowance_kind="differential_phase",
            field_line=line,
            parity=parity,
            detail=dict(table, positive=dp_plus, negative=dp_minus),
        ))
    return checks


#: The three-level chrominance bar of each system, smallest step first.
CHROMA_BAR_ELEMENTS = {
    "pal-multiburst-field2": ("chroma_bar_20", "chroma_bar_60",
                              "chroma_bar_100"),
    "ntsc-ntc7-combination": ("chroma_zone_1", "chroma_zone_2",
                              "chroma_zone_3"),
}


def check_chroma_nonlinearity(entry, measurements, line, parity) -> List[Check]:
    """Chrominance gain non-linearity of a three-level chrominance bar.

    ITU-R BT.1439-1 section 3.3.1.2.  The chrominance counterpart of the
    staircase check above: it compares the three steps against each other,
    so a gain error that scales all three equally cancels and only curvature
    shows.  The flat part of a chrominance gain error is caught by
    check_luma_chroma_ratio instead.
    """
    element_ids = CHROMA_BAR_ELEMENTS.get(entry.id)
    if not element_ids or not all(i in measurements for i in element_ids):
        return []
    amplitudes = [measurements[i].value for i in element_ids]
    allowed = vr.allowance("chroma_nonlinearity").band()
    try:
        value = chrominance_gain_nonlinearity(amplitudes, entry.system)
    except ValueError as error:
        return [Check(
            id=f"{entry.id}/chroma_nonlinearity",
            label="Chrominance gain non-linearity", verdict="SKIP",
            measured=float("nan"), unit="fraction",
            clause="ITU-R BT.1439-1 3.3.1.2",
            field_line=line, parity=parity, reason=str(error))]
    return [Check(
        id=f"{entry.id}/chroma_nonlinearity",
        label="Chrominance gain non-linearity",
        verdict=_one_sided(value, allowed),
        measured=value,
        unit="fraction",
        clause="ITU-R BT.1439-1 3.3.1.2",
        limit=allowed,
        spec_tolerance=0.0,
        allowance=allowed,
        allowance_kind="chroma_nonlinearity",
        field_line=line,
        parity=parity,
        detail={"amplitudes_ire": amplitudes,
                "step_ratios": list(CHROMA_BAR_STEP_RATIOS[entry.system])},
    )]


#: Which element is the luminance reference and which the chrominance one,
#: per system, for the gain-ratio check.  Both must come from the same
#: parity so the same decode conditions apply to each.
GAIN_RATIO_PAIRS = {
    "PAL": (("pal-its-field2", "white_reference_bar"),
            ("pal-multiburst-field2", "chroma_reference")),
    "NTSC": (("ntsc-ntc7-composite", "white_reference_bar"),
             ("ntsc-ntc7-composite", "chroma_reference")),
}


def check_luma_chroma_ratio(bundle, parity, system) -> List[Check]:
    """Chrominance amplitude against luminance amplitude on the same field.

    The check the whole plan turns on: a decode that scales luminance
    correctly and chrominance incorrectly passes every absolute luminance
    check, passes the non-linearity checks (which are gain invariant), and
    fails only here.

    The specification tolerance is derived rather than stated: if each of
    the two elements is within its own tolerance, their ratio is within the
    sum of the two relative tolerances, so that sum is the band the
    standards actually imply.  ITU-R BT.1439-1 calls the quantity
    chrominance/luminance gain inequality.
    """
    pair = GAIN_RATIO_PAIRS.get(system)
    if pair is None:
        return []
    (luma_id, luma_element), (chroma_id, chroma_element) = pair
    luma = bundle.get(luma_id, {}).get(luma_element)
    chroma = bundle.get(chroma_id, {}).get(chroma_element)
    if luma is None or chroma is None or luma.value == 0:
        return []

    luma_nominal = luma.nominal
    chroma_nominal = chroma.nominal
    if not luma_nominal or not chroma_nominal:
        return []

    measured = chroma.value / luma.value
    nominal = chroma_nominal / luma_nominal
    spec = 0.0
    for measurement, element_nominal in ((luma, luma_nominal),
                                         (chroma, chroma_nominal)):
        if measurement.tolerance:
            spec += measurement.tolerance / abs(element_nominal)
    allowed = vr.allowance("luma_chroma_ratio").band()
    band = (spec + allowed) * nominal
    return [Check(
        id=f"gain_ratio/{system}",
        label=(f"Chrominance/luminance gain ratio "
               f"({chroma_id}/{chroma_element} against "
               f"{luma_id}/{luma_element})"),
        verdict=_verdict(measured - nominal, band),
        measured=measured,
        unit="ratio",
        clause="ITU-R BT.1439-1 3.3.1.2; IEC 60856-1986 9.1.3 Figure 10 b)",
        nominal=nominal,
        spec_tolerance=spec * nominal,
        allowance=allowed * nominal,
        allowance_kind="luma_chroma_ratio",
        band=band,
        parity=parity,
        detail={"luma_ire": luma.value, "chroma_ire": chroma.value,
                "relative_deviation": measured / nominal - 1.0},
    )]


# ---------------------------------------------------------------------------
# Multiburst frequency response
# ---------------------------------------------------------------------------

def check_multiburst(entry, measurements, line, parity,
                     fields_averaged=1) -> Tuple[List[Check], dict]:
    """Frequency and flatness of one multiburst line.

    Returns (checks, response), with response the per-packet table the
    report and the JSON sidecar carry whether or not a packet was judged: a
    frequency that could not be judged is still worth reading.

    The two checks are deliberately separate.  A packet may fail
    .../frequency while passing .../response, which says the disc or the
    time base is wrong rather than the equaliser, and the reverse says the
    equaliser is wrong rather than the time base.
    """
    system = entry.system
    set_name, set_score, rows = multiburst_response(entry, measurements,
                                                    system)
    if not rows:
        return [], {}

    reference = next((row for row in rows if row.is_reference), None)
    checks = []
    for row in rows:
        judge, reason = frequency_judgement(row)
        spec, allowed = frequency_band_mhz(row, system)
        band = spec + allowed
        error = row.freq_error_mhz
        checks.append(Check(
            id=f"{entry.id}/{row.element_id}/frequency",
            label=f"{row.element_id} centre frequency",
            verdict=("SKIP" if not judge else _verdict(error, band)),
            measured=row.freq_mhz,
            unit="MHz",
            clause=frequency_clause(row, set_name, system),
            nominal=row.nominal_freq_mhz,
            spec_tolerance=spec,
            allowance=allowed,
            allowance_kind="multiburst_frequency",
            band=band,
            field_line=line,
            parity=parity,
            reason=reason,
            detail={"set": set_name, "set_score": set_score,
                    "cycles": row.cycles},
        ))

    allowed_db = vr.allowance("multiburst_flatness").band()
    for row in rows:
        judge, reason = flatness_judgement(entry, row, reference,
                                           fields_averaged, system)
        checks.append(Check(
            id=f"{entry.id}/{row.element_id}/response",
            label=f"{row.element_id} amplitude about the reference packet",
            verdict=("SKIP" if not judge
                     else _verdict(row.relative_db, allowed_db)),
            measured=row.relative_db,
            unit="dB",
            clause="docs/technical/vits-servos.md, frequency-resolved video EQ",
            nominal=0.0,
            spec_tolerance=0.0,
            allowance=allowed_db,
            allowance_kind="multiburst_flatness",
            band=allowed_db,
            field_line=line,
            parity=parity,
            reason=reason,
            detail={"freq_mhz": row.freq_mhz,
                    "amplitude_ire": row.amplitude_ire,
                    "duty": row.duty},
        ))

    response = {
        "vits_id": entry.id,
        "field_line": line,
        "set": set_name,
        "set_score": set_score,
        "reference": None if reference is None else reference.element_id,
        "packets": [asdict(row) for row in rows],
    }
    return checks, response


# ---------------------------------------------------------------------------
# Driving the checks
# ---------------------------------------------------------------------------

def run_conformance(path, max_fields=None, average=DEFAULT_AVERAGE_FIELDS,
                    manifest_record=None):
    """Every check for a capture.  Returns (checks, context).

    context records what the run actually had to work with - how many fields
    were averaged per parity, which signals were identified and where - so a
    PASS on a capture carrying nothing is not mistaken for a clean bill.

    manifest_record, when given, is the capture's entry from
    testdata/vits-manifest.json; it adds a carried check per definition so
    the VITS this capture does not hold are named as skipped rather than
    passing over in silence.  See vits_manifest.
    """
    params, fields, _ = load(path, max_fields)
    checks: List[Check] = []
    context = {"path": path, "system": params.system,
               "fields": len(fields), "parities": [],
               "manifest": (manifest_record or {}).get("label")}
    if not fields:
        return checks, context

    for is_first in (True, False):
        parity_fields = [f for f in fields if bool(f.isFirstField) == is_first]
        if not parity_fields:
            continue
        parity = "first" if is_first else "second"
        if average > 1:
            probe, used = average_fields(parity_fields, average,
                                         phase_locked=True)
        else:
            probe, used = parity_fields[0], 1

        geom = FieldGeometry(probe)
        identifications = identify_vits(probe, geom=geom)
        bundle: Dict[str, Dict[str, object]] = {}
        found = []
        responses = []
        for line, identification in sorted(identifications.items()):
            entry = vr.definition(identification.vits_id)
            aligned, offset_us, _ = align_geometry(geom, line, entry)
            measurements = measure_definition(probe, entry, line, aligned,
                                              align=False)
            bundle[entry.id] = measurements
            found.append({"line": line, "vits_id": entry.id,
                          "score": identification.score,
                          "alignment_us": offset_us,
                          "on_expected_line": identification.on_expected_line})

            checks += check_levels(entry, measurements, line, parity, used)
            checks += check_ceilings(entry, measurements, line, parity)
            checks += check_saturation(entry, measurements, line, parity)
            checks += check_staircases(entry, measurements, line, parity)
            checks += check_differential(entry, measurements, line, parity)
            checks += check_chroma_nonlinearity(entry, measurements, line,
                                                parity)
            packet_checks, response = check_multiburst(
                entry, measurements, line, parity, used)
            checks += packet_checks
            if response:
                responses.append(response)

        checks += check_luma_chroma_ratio(bundle, parity, params.system)
        checks += check_blanked_lines(geom, parity)
        if manifest_record is not None:
            checks += check_carried(params.system, manifest_record,
                                    {f["vits_id"] for f in found}, parity)
        robust_peak, absolute_peak = picture_peak_ire(geom)
        context["parities"].append({
            "parity": parity, "fields_averaged": used,
            "chroma_coherence": getattr(probe, "chroma_coherence", None),
            "averaging_refused": getattr(probe, "averaging_refused", ""),
            "origin_samples": geom.origin_samples,
            "origin_measured": geom.origin_measured,
            "picture_peak_ire": robust_peak,
            "picture_max_ire": absolute_peak,
            "identified": found,
            "multiburst": responses,
        })
    return checks, context


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _format_check(check: Check) -> str:
    marker = {"PASS": "  [PASS] ", "FAIL": "  [FAIL] ",
              "SKIP": "  [skip] "}[check.verdict]
    where = "" if check.field_line is None else f" line {check.field_line}"
    head = f"{marker}{check.id}{where}: "
    if not np.isfinite(check.measured):
        # A check with no number to print - it was declined, or it is a
        # presence check, whose whole answer is its reason.
        return head + (check.reason or "not measurable")

    body = f"{check.measured:.3f} {check.unit}"
    if check.nominal is not None:
        body += (f", nominal {check.nominal:.3f}, "
                 f"deviation {check.deviation:+.3f}")
    if check.limit is not None:
        body += f", limit {check.limit:.3f}"
    if check.band is not None:
        body += f", band +/-{check.band:.3f}"
    if check.spec_tolerance is not None and check.allowance is not None:
        body += (f" (spec {check.spec_tolerance:.3f} + allowance "
                 f"{check.allowance:.3f})")
    if check.reason:
        body += f" -- {check.reason}"
    return head + body + f" -- {check.clause}"


def report(checks, context, stream=None) -> int:
    """Print the report.  Returns the process exit status.

    stream is resolved here rather than defaulted to sys.stdout in the
    signature, so a caller that has replaced sys.stdout - a test capturing
    output, or a CI wrapper - is actually written to.
    """
    stream = sys.stdout if stream is None else stream
    print(f"{context['path']}: {context['system']}, "
          f"{context['fields']} fields", file=stream)
    for parity in context["parities"]:
        print(f"  {parity['parity']} fields, "
              f"{parity['fields_averaged']} averaged, "
              f"0H origin {parity['origin_samples']:+.2f} samples, "
              f"active picture peaks at {parity['picture_peak_ire']:.1f} IRE "
              f"(max {parity['picture_max_ire']:.1f}, not judged)",
              file=stream)
        if parity.get("averaging_refused"):
            print(f"    note: {parity['averaging_refused']}", file=stream)
        for found in parity["identified"]:
            moved = "" if found["on_expected_line"] else "  [moved]"
            print(f"    line {found['line']:3d}  {found['vits_id']:<24s} "
                  f"score {found['score']:4.2f}  "
                  f"timing {found['alignment_us']:+.2f} us{moved}",
                  file=stream)
        for response in parity.get("multiburst", ()):
            print(f"    {response['vits_id']} line "
                  f"{response['field_line']}: {response['set']} set "
                  f"(match {response['set_score']:.2f}), reference packet "
                  f"{response['reference']}", file=stream)
            for row in response["packets"]:
                nominal = row["nominal_freq_mhz"]
                against = ("" if nominal is None
                           else f" ({nominal:5.2f} nominal)")
                relative = ("      " if not np.isfinite(row["relative_db"])
                            else f"{row['relative_db']:+6.2f}")
                print(f"      {row['element_id']:<9s} "
                      f"{row['freq_mhz']:5.3f} MHz{against}  "
                      f"{row['amplitude_ire']:6.2f} IRE  "
                      f"{relative} dB  "
                      f"{row['cycles']:5.2f} cycles  "
                      f"occupancy {row['duty']:.2f}", file=stream)
    print(file=stream)

    for check in checks:
        print(_format_check(check), file=stream)
    print(file=stream)

    failed = [c for c in checks if c.verdict == "FAIL"]
    judged = [c for c in checks if c.verdict != "SKIP"]
    skipped = len(checks) - len(judged)
    if not judged:
        print("VITS CONFORMANCE: SKIPPED (no VITS detected)", file=stream)
        return 0
    if failed:
        print(f"VITS CONFORMANCE: FAIL ({len(failed)} of {len(judged)} "
              f"checks failed, {skipped} skipped)", file=stream)
        return 1
    print(f"VITS CONFORMANCE: PASS ({len(judged)} checks, {skipped} skipped)",
          file=stream)
    return 0


def json_payload(checks, context):
    """The checks and their context as plain data, ready to serialise.

    Kept apart from write_json so the shape can be tested without a
    filesystem.
    """
    return {
        "context": context,
        "checks": [asdict(check) for check in checks],
        "summary": {
            "passed": sum(1 for c in checks if c.verdict == "PASS"),
            "failed": sum(1 for c in checks if c.verdict == "FAIL"),
            "skipped": sum(1 for c in checks if c.verdict == "SKIP"),
        },
    }


def write_json(path, checks, context):
    """Write the checks and their context as a CI artefact."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(json_payload(checks, context), handle,
                  indent=2, sort_keys=True, default=float)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Judge a decoded CVBS capture against the VITS standards")
    parser.add_argument("path", help="a .cvbs capture, or its basename")
    parser.add_argument("--max-fields", type=int, default=None,
                        help="stop reading after this many fields")
    parser.add_argument("--average", type=int, default=DEFAULT_AVERAGE_FIELDS,
                        help=("fields to coherently average per parity "
                              "(phase locked; default "
                              f"{DEFAULT_AVERAGE_FIELDS})"))
    parser.add_argument("--json", dest="json_path", default=None,
                        help="write the checks to this file as JSON")
    parser.add_argument("--manifest", default=None,
                        help=("a vits-manifest.json describing the captures; "
                              "with it, the VITS this capture does not carry "
                              "are reported as skipped by name"))
    parser.add_argument("--capture", default=None,
                        help=("name of the source capture in the manifest "
                              "(default: the name of the file being judged)"))
    args = parser.parse_args(argv)

    record = None
    if args.manifest:
        capture = args.capture or args.path
        record = manifest_entry(load_manifest(args.manifest), capture)
        if record is None:
            # An unsurveyed capture and a survey that has gone stale look the
            # same from here, and neither may be judged as if it were known.
            print(f"VITS CONFORMANCE: ERROR ({capture} has no entry in "
                  f"{args.manifest}; survey it with vits_inventory.py)",
                  file=sys.stderr)
            return 2

    checks, context = run_conformance(args.path, args.max_fields, args.average,
                                      manifest_record=record)
    status = report(checks, context)
    if args.json_path:
        write_json(args.json_path, checks, context)
    return status


if __name__ == "__main__":
    sys.exit(main())
