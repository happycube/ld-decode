"""
vits_reference - normative VITS definitions for NTSC and PAL LaserDiscs

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Pure data: the Vertical Interval Test Signals a LaserDisc may carry, where
they sit, what each element should measure, and where each number came from.
Consumed by the VITS conformance measurement in analysis/; imports nothing
from lddecode and touches no file, so it can be unit tested on its own.

Sources, in precedence order:

1. IEC 60857-1986 (NTSC LaserVision) and IEC 60856-1986 (PAL LaserVision)
   with their amendments define which lines carry test signals on a
   LaserDisc, and for PAL the element amplitudes and tolerances.
2. Where the LaserDisc standard defers, the document it names applies.
   IEC 60856-1986 9.1.3 cites CCIR Recommendation 473-3 Annex I (ITU-R 473-5
   in Amendment 2) for the PAL waveform geometry, so the IEC figures supply
   amplitudes and tolerances while the ITU definition supplies the timing.
   IEC 60857-1986 9.1.4 specifies no element values at all and cites NTC
   Report No. 7 / CCIR Recommendation 473-2; those come from the
   machine-readable definitions in the analogue-video-specifications
   submodule, resources/definitions/vits/ntsc/.
3. Where the two disagree, the IEC figure is normative for LaserDisc. The
   PAL multiburst frequency set is the case that matters and is recorded in
   PAL_MULTIBURST_IEC / PAL_MULTIBURST_ITU below.

Units: a nominal is stored in its standard's own convention - PAL as a
fraction of the 0.70 V p-p white reference, NTSC in IRE - and to_ire()
converts either onto the 0-100 blanking-to-white scale that
video_common.VideoField.output_to_ire() produces.

Tolerances: PAL entries carry the IEC mastering tolerances. NTSC entries
carry none, because neither IEC 60857 nor the NTC-7 definitions state any;
a conformance pass band is the mastering tolerance plus a decoder allowance,
and the allowance is not this module's to invent.
"""

from dataclasses import dataclass
from typing import Optional

# NB: dataclasses.field is deliberately not imported - VitsDefinition has an
# attribute called `field` (the field number within the frame) and every
# default here is an immutable tuple, so no default_factory is needed.


# ---------------------------------------------------------------------------
# Units and scales
# ---------------------------------------------------------------------------

# IEC 60856-1986-9.1.3 Figure 7: PAL amplitudes are quoted against a
# 0.70 V peak-to-peak blanking-to-white reference.
PAL_WHITE_MV = 700.0

# ITU-R BT.1700 Annex 1 Part A: 525-line 100 IRE corresponds to 714.3 mV.
NTSC_WHITE_MV = 714.3

# IEC 60856-1986-9.1.5 and IEC 60857-1986-9.1.6: the recorded signal shall
# not exceed these, on the 0-100 blanking-to-white scale.
MAX_LUMINANCE_IRE = 110.0
MAX_CHROMA_SATURATION_PERCENT = 100.0

# IEC 60856-1986-9.1.2: a pilot burst at 240 x f_H is superimposed on the PAL
# synchronisation level, at 6/7 of the blanking-to-peak-white difference
# +/-10%.  It sits on sync rather than on the active line, but its residue
# after demodulation contaminates a blanking reference measured too close to
# the back porch.
PAL_PILOT_BURST_MHZ = 3.75

# Nominal line period.  A VITS element window is measured from the leading
# edge of horizontal sync and must fall inside one line.
# EBU Tech. 3280-E: 64 us per 625-line line.
# SMPTE 170M-2004 Table 1: 63.5555... us per 525-line line.
LINE_PERIOD_US = {"PAL": 64.0, "NTSC": 63.555555555555556}

# Frame line n of field 2 is field line n minus this offset, so an IEC pair
# such as PAL (19, 332) or NTSC (19, 282) is the same field line in both
# parities.
# IEC 60856-1986-9.1.3: PAL VITS pairs 19/332, 20/333, 13/326, 22/335.
# IEC 60857-1986-9.1.3: NTSC VIRS pair 19/282; 9.1.4: ITS pair 20/283.
FIELD_TWO_FRAME_LINE_OFFSET = {"PAL": 313, "NTSC": 263}

SYSTEMS = ("NTSC", "PAL")

#: Element kinds.  A conformance check dispatches on these.
ELEMENT_KINDS = (
    "bar",           # flat luminance level held over a window
    "staircase",     # a run of luminance treads
    "pulse",         # sine-squared pulse (2T, 12.5T, 20T)
    "burst_packet",  # one packet of a multiburst frequency sweep
    "chroma_bar",    # sustained subcarrier at a stated amplitude
    "blanked",       # window required to hold blanking level and nothing else
)

CHANNELS = ("luma", "chroma")

#: How firmly the standard requires the signal to be present.
STATUSES = ("shall", "recommended", "permitted")


def to_ire(nominal, system):
    """A stored nominal on the 0-100 blanking-to-white measurement scale.

    PAL nominals are a fraction of the 0.70 V p-p white reference; NTSC
    nominals are already IRE.  This is the scale
    video_common.VideoField.output_to_ire() produces for either system, so a
    nominal and a measurement can be compared directly.
    """
    _check_system(system)
    return nominal * 100.0 if system == "PAL" else float(nominal)


def to_percent(nominal, system):
    """A stored nominal as a percentage of the white reference.

    Numerically the same as to_ire(): both 625- and 525-line practice define
    the measurement scale as 0 at blanking and 100 at peak white, so "per
    cent of 0.70 V p-p" (the IEC PAL figures) and "IRE" (the NTSC
    definitions) name one scale in two vocabularies.  Both spellings exist
    here so a check can quote the number the way its own specification does.
    """
    return to_ire(nominal, system)


def to_millivolts(nominal, system):
    """A stored nominal in millivolts above blanking.

    Unlike to_ire(), the systems genuinely differ here: 100 on the
    measurement scale is 700 mV on 625-line and 714.3 mV on 525-line.
    """
    _check_system(system)
    white_mv = PAL_WHITE_MV if system == "PAL" else NTSC_WHITE_MV
    return to_ire(nominal, system) / 100.0 * white_mv


def sample_to_ire(sample, blanking, white):
    """A sample value on the 0-100 blanking-to-white scale.

    Mirrors video_common.CaptureParams.out_scale and
    VideoField.output_to_ire(): the result is a ratio, so the sample domain
    cancels and a 10-bit .cvbs and a 16-bit .tbc give the same answer as long
    as all three arguments come from the same capture.
    """
    if white == blanking:
        raise ValueError("white and blanking levels are equal; scale undefined")
    return (sample - blanking) / ((white - blanking) / 100.0)


def _check_system(system):
    if system not in SYSTEMS:
        raise ValueError(f"Unknown system: {system} (expected one of {SYSTEMS})")


# ---------------------------------------------------------------------------
# Frame line <-> field line
# ---------------------------------------------------------------------------

def frame_line_to_field(system, frame_line):
    """(field number, field line) for a frame line number.

    Every IEC line number is a frame line; video_common indexes field lines.
    Field 1 lines map straight through; field 2 lines sit
    FIELD_TWO_FRAME_LINE_OFFSET higher in the frame.
    """
    _check_system(system)
    offset = FIELD_TWO_FRAME_LINE_OFFSET[system]
    if frame_line <= 0:
        raise ValueError(f"Frame line must be positive, got {frame_line}")
    if frame_line > offset:
        return 2, frame_line - offset
    return 1, frame_line


def field_to_frame_line(system, field, field_line):
    """The frame line number of a given field line.  Inverse of the above."""
    _check_system(system)
    if field not in (1, 2):
        raise ValueError(f"Field must be 1 or 2, got {field}")
    if field_line <= 0:
        raise ValueError(f"Field line must be positive, got {field_line}")
    if field == 1:
        return field_line
    return field_line + FIELD_TWO_FRAME_LINE_OFFSET[system]


# ---------------------------------------------------------------------------
# Multiburst frequency sets
# ---------------------------------------------------------------------------

#: IEC 60856-1986-9.1.3 Figure 8 (as replaced by Amendment 2): the frequency
#: set a PAL LaserDisc multiburst is specified to carry, +/-2%.
#: Real discs do not all follow it - see PAL_MULTIBURST_ITU - so a measurement
#: must identify which set is present rather than assume this one.
PAL_MULTIBURST_IEC = (0.5, 1.3, 2.3, 4.2, 4.8, 5.8)

#: ITU-T J.63 Annex I section 3 / EBU Tech 3209 section 7.2.9: the generic
#: 625-line multiburst set.  Every PAL disc in testdata/ carries this rather
#: than the IEC set (GGV, Louvre and kagemusha, recorded in
#: docs/technical/vits-servos.md), so it is a conformant-in-practice
#: alternative and not a fault to be reported.
PAL_MULTIBURST_ITU = (0.5, 1.0, 2.0, 4.0, 4.8, 5.8)

#: FCC Rules Part 73 / EIA RS-498, via
#: analogue-video-specifications/resources/definitions/vits/ntsc/
#: fcc-multiburst.yaml.  IEC 60857 does not mention this signal, but GGV NTSC
#: carries it on field line 22 in both parities and it is the only NTSC
#: multiburst whose packets are long enough to measure amplitude from a
#: single line at 4fsc.
NTSC_MULTIBURST_FCC = (0.5, 1.25, 2.0, 3.0, 3.58, 4.1)

#: ITU-T J.63 Annex II section 3 / BT.1439 Annex 1, via
#: analogue-video-specifications/resources/definitions/vits/ntsc/
#: ntc7-combination.yaml.  Usable for presence and frequency, but not for
#: amplitude from a single line: the ~3 us packets are as short as the scan
#: window at NTSC 4fsc and the fit under-reads by up to 2.5 dB with the wrong
#: sign (measured on he010 and issue176, docs/technical/vits-servos.md).
NTSC_MULTIBURST_NTC7 = (0.5, 1.0, 2.0, 3.0, 3.58, 4.2)

#: Every set a measurement may match a detected packet train against.
MULTIBURST_SETS = {
    "PAL": {"IEC": PAL_MULTIBURST_IEC, "ITU": PAL_MULTIBURST_ITU},
    "NTSC": {"FCC": NTSC_MULTIBURST_FCC, "NTC7": NTSC_MULTIBURST_NTC7},
}


# ---------------------------------------------------------------------------
# Reference data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Element:
    """One measurable element of a VITS.

    nominal and tolerance are in the system's own unit (PAL: a fraction of
    the 0.70 V p-p white reference; NTSC: IRE); use to_ire() to compare
    against a measurement.  For a chroma_bar or burst_packet, nominal is the
    carrier peak amplitude (half the peak-to-peak swing) about its pedestal.

    window_us is (start, end) from the leading edge of horizontal sync.
    superimposed marks an element that rides on another in the same window
    rather than replacing it, which is what makes overlapping windows legal.

    step_windows_us gives a staircase's treads their own windows when the
    definition does not space them evenly; left empty the treads divide
    window_us equally, which is the model the NTSC definitions use.
    """

    id: str
    label: str
    kind: str
    window_us: tuple
    nominal: Optional[float] = None
    tolerance: Optional[float] = None
    channel: str = "luma"
    superimposed: bool = False
    steps: tuple = ()
    step_windows_us: tuple = ()
    freq_mhz: Optional[float] = None
    freq_tolerance_mhz: Optional[float] = None
    source: str = ""

    @property
    def start_us(self):
        return self.window_us[0]

    @property
    def end_us(self):
        return self.window_us[1]

    @property
    def duration_us(self):
        return self.window_us[1] - self.window_us[0]


@dataclass(frozen=True)
class VitsDefinition:
    """One VITS: where it sits on the disc and what it should measure.

    field is the field number within the frame (1 or 2), not a video field
    object.  alternate_frame_line records the second placement a standard
    permits for the same signal, if any.
    """

    id: str
    system: str
    frame_line: int
    field: int
    field_line: int
    status: str
    source: str
    elements: tuple = ()
    alternate_frame_line: Optional[int] = None
    notes: str = ""

    def element(self, element_id):
        """The element with this id, or None."""
        for elem in self.elements:
            if elem.id == element_id:
                return elem
        return None


# ---------------------------------------------------------------------------
# PAL - IEC 60856-1986 clause 9.1.3, Figures 7 to 10
#
# Amplitudes and tolerances are the IEC figures.  Element timing follows the
# CCIR Recommendation 473-3 Annex I geometry that 9.1.3 defers to, taken from
# analogue-video-specifications/resources/definitions/vits/pal/; the two agree
# on every level where both state one (Figure 8's 80%/20% reference bars are
# the ITU multiburst's +/-210 mV about a 350 mV pedestal, and Figure 9's
# 0.28 V p-p superimposed subcarrier is its 140 mV carrier peak).
# ---------------------------------------------------------------------------

# IEC 60856-1986-9.1.3 Figure 7: white reference bar B2 is 0.70 V p-p +/-0.5%,
# and every other element's tolerance is stated relative to it.
_PAL_BAR_TOLERANCE = 0.005          # +/-0.5% of 0.70 V p-p
_PAL_ELEMENT_TOLERANCE = 0.010      # +/-1% of B2

_PAL_STAIRCASE_TREADS = (0.20, 0.40, 0.60, 0.80, 1.00)

# ITU-T J.63 Annex I sections 2 and 4: the treads are not evenly spaced - the
# last runs to the end of the active line, 6 us against the other four's 4 us.
_PAL_STAIRCASE_TREAD_WINDOWS = (
    (40.0, 44.0),
    (44.0, 48.0),
    (48.0, 52.0),
    (52.0, 56.0),
    (56.0, 62.0),
)

# IEC 60856-1986-9.1.3 Figure 7 d): "Number of levels = 6 (black and white
# incl.)" - blanking plus the five treads above.
PAL_STAIRCASE_LEVEL_COUNT = 6

# IEC 60856-1986-9.1.3 Figure 7 d): step inequality < 0.5%.
PAL_STAIRCASE_STEP_INEQUALITY = 0.005

# IEC 60856-1986-9.1.3 Figure 9: composite staircase differential gain
# <= 0.5% and differential phase <= 0.2 degrees.
PAL_DIFFERENTIAL_GAIN_LIMIT = 0.005
PAL_DIFFERENTIAL_PHASE_LIMIT_DEG = 0.2

_PAL_LINE19_BAR = Element(
    id="white_reference_bar",
    label="White reference bar B2",
    kind="bar",
    # ITU-T J.63 Annex I section 2: 100% white bar, 12.0-22.0 us.
    window_us=(12.0, 22.0),
    # IEC 60856-1986-9.1.3 Figure 7 a): 0.70 V p-p +/-0.5%.
    nominal=1.00,
    tolerance=_PAL_BAR_TOLERANCE,
    source="IEC 60856-1986 9.1.3 Figure 7 a)",
)

_PAL_LINE19_2T = Element(
    id="pulse_2t",
    label="2T sine-squared pulse B1",
    kind="pulse",
    # ITU-T J.63 Annex I section 2: centred 26.0 us, half-duration 0.200 us.
    window_us=(25.8, 26.2),
    # IEC 60856-1986-9.1.3 Figure 7 b): 0.70 V p-p, within +/-0.5% of B2.
    nominal=1.00,
    tolerance=_PAL_BAR_TOLERANCE,
    source="IEC 60856-1986 9.1.3 Figure 7 b)",
)

_PAL_LINE19_20T_LUMA = Element(
    id="pulse_20t_luma",
    label="Composite 20T pulse F, luminance component",
    kind="pulse",
    # ITU-T J.63 Annex I section 2: centred 32.0 us, half-duration 2.0 us.
    window_us=(30.0, 34.0),
    # IEC 60856-1986-9.1.3 Figure 7 c): 0.70 V p-p, within +/-1% of B2.
    nominal=0.50,
    tolerance=_PAL_ELEMENT_TOLERANCE,
    source="IEC 60856-1986 9.1.3 Figure 7 c)",
)

_PAL_LINE19_20T_CHROMA = Element(
    id="pulse_20t_chroma",
    label="Composite 20T pulse F, chrominance component",
    kind="chroma_bar",
    window_us=(30.0, 34.0),
    nominal=0.50,
    tolerance=_PAL_ELEMENT_TOLERANCE,
    channel="chroma",
    superimposed=True,
    # EBU Tech. 3280-E: PAL colour subcarrier 4.43361875 MHz.
    freq_mhz=4.43361875,
    source="IEC 60856-1986 9.1.3 Figure 7 c)",
)

_PAL_STAIRCASE = Element(
    id="staircase",
    label="Staircase D1",
    kind="staircase",
    # ITU-T J.63 Annex I section 2: characteristic instants 20H/32 to 31H/32.
    window_us=(40.0, 62.0),
    # IEC 60856-1986-9.1.3 Figure 7 d): 0.70 V p-p, within +/-1% of B2.
    nominal=1.00,
    tolerance=_PAL_ELEMENT_TOLERANCE,
    steps=_PAL_STAIRCASE_TREADS,
    step_windows_us=_PAL_STAIRCASE_TREAD_WINDOWS,
    source="IEC 60856-1986 9.1.3 Figure 7 d)",
)

VITS_PAL_LINE19 = VitsDefinition(
    id="pal-its-field1",
    system="PAL",
    frame_line=19,
    field=1,
    field_line=19,
    status="permitted",
    source="IEC 60856-1986 9.1.3 Figure 7",
    elements=(
        _PAL_LINE19_BAR,
        _PAL_LINE19_2T,
        _PAL_LINE19_20T_LUMA,
        _PAL_LINE19_20T_CHROMA,
        _PAL_STAIRCASE,
    ),
    notes=(
        "Luminance-only staircase; its field 2 counterpart on frame line 332 "
        "carries the same staircase with subcarrier superimposed."
    ),
)

VITS_PAL_LINE332 = VitsDefinition(
    id="pal-its-field2",
    system="PAL",
    frame_line=332,
    field=2,
    field_line=19,
    status="permitted",
    source="IEC 60856-1986 9.1.3 Figure 9",
    elements=(
        # IEC 60856-1986-9.1.3 Figure 9 a) and b): bar and 2T pulse identical
        # to line 19.
        _PAL_LINE19_BAR,
        _PAL_LINE19_2T,
        # IEC 60856-1986-9.1.3 Figure 9 c): composite staircase D2 is the
        # line 19 staircase with subcarrier superimposed.
        _PAL_STAIRCASE,
        Element(
            id="staircase_subcarrier",
            label="Staircase superimposed subcarrier",
            kind="chroma_bar",
            # ITU-T J.63 Annex I section 4: sustained over the staircase.
            window_us=(30.0, 60.0),
            # IEC 60856-1986-9.1.3 Figure 9: 0.28 V p-p +/-5%, i.e. a 140 mV
            # carrier peak, which is 20% of the 0.70 V p-p reference.
            nominal=0.20,
            tolerance=0.05 * 0.20,
            channel="chroma",
            superimposed=True,
            freq_mhz=4.43361875,
            source="IEC 60856-1986 9.1.3 Figure 9",
        ),
    ),
    notes=(
        "The differential gain and differential phase reference: the same "
        "staircase as frame line 19 but modulated, so comparing the two "
        "parities isolates chroma-dependent luma error."
    ),
)

# IEC 60856-1986-9.1.3 Figure 8 (Amendment 2): frequencies +/-2%.
_PAL_MULTIBURST_FREQ_TOLERANCE = 0.02

# IEC 60856-1986-9.1.3 Figure 8 c): burst amplitude 60% of 0.70 V p-p +/-1%.
# The figure quotes the envelope, which is the carrier peak-to-peak, so the
# carrier peak this module stores is half of it.
_PAL_MULTIBURST_AMPLITUDE = 0.30

# ITU-T J.63 Annex I section 3: the six packet windows, in order.
_PAL_MULTIBURST_WINDOWS = (
    (24.0, 28.0),
    (30.0, 35.0),
    (36.0, 41.0),
    (42.0, 47.0),
    (48.0, 53.0),
    (54.0, 60.0),
)

_PAL_MULTIBURST_PACKETS = tuple(
    Element(
        id=f"packet_{index + 1}",
        label=f"{freq_mhz} MHz burst C3",
        kind="burst_packet",
        window_us=window,
        nominal=_PAL_MULTIBURST_AMPLITUDE,
        tolerance=0.01 * _PAL_MULTIBURST_AMPLITUDE,
        channel="chroma",
        superimposed=True,
        freq_mhz=freq_mhz,
        freq_tolerance_mhz=freq_mhz * _PAL_MULTIBURST_FREQ_TOLERANCE,
        source="IEC 60856-1986 9.1.3 Figure 8 c)",
    )
    for index, (freq_mhz, window) in enumerate(
        zip(PAL_MULTIBURST_IEC, _PAL_MULTIBURST_WINDOWS)
    )
)

_PAL_MULTIBURST_COMMON = (
    Element(
        id="grey_pedestal",
        label="Grey pedestal",
        kind="bar",
        # ITU-T J.63 Annex I section 3: 50% pedestal across the active line.
        window_us=(12.0, 62.0),
        nominal=0.50,
        tolerance=_PAL_ELEMENT_TOLERANCE,
        source="ITU-T J.63 Annex I section 3",
    ),
    Element(
        id="white_reference_bar",
        label="White reference bar C1",
        kind="bar",
        window_us=(12.0, 16.0),
        # IEC 60856-1986-9.1.3 Figure 8 a): 80% of 0.70 V p-p +/-1%.
        nominal=0.80,
        tolerance=_PAL_ELEMENT_TOLERANCE,
        superimposed=True,
        source="IEC 60856-1986 9.1.3 Figure 8 a)",
    ),
    Element(
        id="black_reference_bar",
        label="Black reference bar C2",
        kind="bar",
        window_us=(16.0, 20.0),
        # IEC 60856-1986-9.1.3 Figure 8 b): 20% of 0.70 V p-p +/-1%.
        nominal=0.20,
        tolerance=_PAL_ELEMENT_TOLERANCE,
        superimposed=True,
        source="IEC 60856-1986 9.1.3 Figure 8 b)",
    ),
) + _PAL_MULTIBURST_PACKETS

VITS_PAL_MULTIBURST_FIELD1 = VitsDefinition(
    id="pal-multiburst-field1",
    system="PAL",
    # IEC 60856-1986-9.1.3 (Amendment 2): "lines 19, 13 or 20, 332 and 326 or
    # 333".  GGV and Roger Rabbit use line 13; Louvre, kagemusha, Domesday and
    # the Industrial disc use line 20.
    frame_line=20,
    field=1,
    field_line=20,
    status="permitted",
    source="IEC 60856-1986 9.1.3 Figure 8",
    elements=_PAL_MULTIBURST_COMMON,
    alternate_frame_line=13,
)

VITS_PAL_MULTIBURST_FIELD2 = VitsDefinition(
    id="pal-multiburst-field2",
    system="PAL",
    frame_line=333,
    field=2,
    field_line=20,
    status="permitted",
    source="IEC 60856-1986 9.1.3 Figure 10",
    elements=(
        Element(
            id="grey_pedestal",
            label="Grey pedestal",
            kind="bar",
            # ITU-T J.63 Annex I section 5: 50% pedestal across the line.
            window_us=(12.0, 62.0),
            # IEC 60856-1986-9.1.3 Figure 10 a): grey level 50% +/-1%.
            nominal=0.50,
            tolerance=_PAL_ELEMENT_TOLERANCE,
            source="IEC 60856-1986 9.1.3 Figure 10 a)",
        ),
        # IEC 60856-1986-9.1.3 Figure 10 a): three level chrominance bar G1
        # at 20%, 60% and 100% of 0.70 V p-p, within +/-1% of B2.  As with
        # the multiburst above, the figure quotes the envelope, so the
        # carrier peak stored here is half of it and the +/-1%-of-B2 band
        # halves with it.  ITU-T J.63 Annex I section 5 states the same
        # three steps directly as carrier amplitudes of 70, 210 and 350 mV,
        # which is exactly 0.10, 0.30 and 0.50 of the 700 mV reference.
        Element(
            id="chroma_bar_20",
            label="Three level chrominance bar G1, 20% step",
            kind="chroma_bar",
            window_us=(14.0, 18.0),
            nominal=0.10,
            tolerance=_PAL_ELEMENT_TOLERANCE / 2.0,
            channel="chroma",
            superimposed=True,
            freq_mhz=4.43361875,
            source="IEC 60856-1986 9.1.3 Figure 10 a)",
        ),
        Element(
            id="chroma_bar_60",
            label="Three level chrominance bar G1, 60% step",
            kind="chroma_bar",
            window_us=(18.0, 22.0),
            nominal=0.30,
            tolerance=_PAL_ELEMENT_TOLERANCE / 2.0,
            channel="chroma",
            superimposed=True,
            freq_mhz=4.43361875,
            source="IEC 60856-1986 9.1.3 Figure 10 a)",
        ),
        Element(
            id="chroma_bar_100",
            label="Three level chrominance bar G1, 100% step",
            kind="chroma_bar",
            window_us=(22.0, 28.0),
            nominal=0.50,
            tolerance=_PAL_ELEMENT_TOLERANCE / 2.0,
            channel="chroma",
            superimposed=True,
            freq_mhz=4.43361875,
            source="IEC 60856-1986 9.1.3 Figure 10 a)",
        ),
        Element(
            id="chroma_reference",
            label="Chrominance reference E",
            kind="chroma_bar",
            # ITU-T J.63 Annex I section 5: sustained over the line's latter
            # portion, at a carrier amplitude of 210 mV.
            window_us=(34.0, 60.0),
            # IEC 60856-1986-9.1.3 Figure 10 b): 60% of 0.70 V p-p, within
            # +/-1% of B2 - the envelope again, so half of it here.
            nominal=0.30,
            tolerance=_PAL_ELEMENT_TOLERANCE / 2.0,
            channel="chroma",
            superimposed=True,
            freq_mhz=4.43361875,
            source="IEC 60856-1986 9.1.3 Figure 10 b)",
        ),
    ),
    alternate_frame_line=326,
    notes=(
        "The luma/chroma gain reference: chrominance reference E is a chroma "
        "level stated against the same white reference as the luma bars, so a "
        "decode that scales the two bands differently fails here while every "
        "luma-only check still passes."
    ),
)

# IEC 60856-1986-9.1.3: "The lines 22 and 335 shall be blanked before optical
# recording, to enable disk noise measurements."  The only unconditional PAL
# requirement in the clause, and the noise-floor reference.
_PAL_BLANKED_LINE = (
    Element(
        id="blanked_active_line",
        label="Blanked active line",
        kind="blanked",
        window_us=(12.0, 62.0),
        nominal=0.0,
        source="IEC 60856-1986 9.1.3",
    ),
)

VITS_PAL_BLANKED_FIELD1 = VitsDefinition(
    id="pal-blanked-field1",
    system="PAL",
    frame_line=22,
    field=1,
    field_line=22,
    status="shall",
    source="IEC 60856-1986 9.1.3",
    elements=_PAL_BLANKED_LINE,
)

VITS_PAL_BLANKED_FIELD2 = VitsDefinition(
    id="pal-blanked-field2",
    system="PAL",
    frame_line=335,
    field=2,
    field_line=22,
    status="shall",
    source="IEC 60856-1986 9.1.3",
    elements=_PAL_BLANKED_LINE,
)


# ---------------------------------------------------------------------------
# NTSC - IEC 60857-1986 clauses 9.1.3 and 9.1.4
#
# IEC 60857 states no element values of its own; every nominal below comes
# from analogue-video-specifications/resources/definitions/vits/ntsc/, which
# is the machine-readable form of the FCC/SMPTE and NTC-7 definitions the
# clause defers to.  Neither states a mastering tolerance, so none is
# recorded here.
# ---------------------------------------------------------------------------

_VIRS_YAML = "analogue-video-specifications resources/definitions/vits/ntsc/virs.yaml"
_NTC7_COMPOSITE_YAML = (
    "analogue-video-specifications resources/definitions/vits/ntsc/ntc7-composite.yaml"
)
_NTC7_COMBINATION_YAML = (
    "analogue-video-specifications resources/definitions/vits/ntsc/ntc7-combination.yaml"
)
_FCC_MULTIBURST_YAML = (
    "analogue-video-specifications resources/definitions/vits/ntsc/fcc-multiburst.yaml"
)

# SMPTE 170M-2004 Section 8.1: 525-line reference black sits 7.5 IRE above
# blanking.  The measurement scale here is blanking-referenced, so a level
# quoted against reference black converts as level * (100 - 7.5)/100 + 7.5.
NTSC_SETUP_IRE = 7.5

# SMPTE RP 168 / EIA RS-498.
#
# These are the canonical VIRS levels and zone boundaries, NOT the ones in
# virs.yaml, which is the only place the submodule and this module disagree.
# The YAML (and NTSC-VITS.md with it) states 68/46/0 IRE over 9.15, 35.50,
# 48.70 and 62.00 us, with a 22 IRE carrier peak.  Those are the canonical
# figures expressed against reference black instead of blanking: apply
# NTSC_SETUP_IRE and 68 -> 70.4, 46 -> 50.05, 0 -> 7.5 and 22 -> 20.35.
#
# Measured on testdata/ntsc/ve-snw-cut.ldf decoded to CVBS, field line 19 of
# both parities: zones of 70.7, 50.4 and 7.35 IRE with a 20.4 IRE carrier
# peak, running 11.5 to 35.4, 35.4 to 47.7 and 47.7 to 60.0 us.  That agrees
# with the canonical values on all four levels and all four boundaries, and
# with the YAML on none of the levels; the 7.35 IRE black reference settles
# it, since no gain error can put a 0 IRE element there.  The same decode
# reads its NTC-7 white bar at 101.11 and its NTC-7 pedestal at 50.54, so
# the decode's own scale is not in question.
_VIRS_ELEMENTS = (
    Element(
        id="first_zone_bar",
        label="70 IRE chrominance reference zone",
        kind="bar",
        window_us=(12.00, 36.00),
        nominal=70.0,
        source="SMPTE RP 168",
    ),
    Element(
        id="chroma_reference",
        label="Chrominance reference burst, centred on the 70 IRE bar",
        kind="chroma_bar",
        # The burst's flat portion, inset within the zone; measured on
        # ve-snw-cut as 13.0 to 34.5 us.
        window_us=(13.00, 34.50),
        # Carrier peak 20 IRE, i.e. 40 IRE p-p, so the composite spans 50 to
        # 90 IRE.
        nominal=20.0,
        channel="chroma",
        superimposed=True,
        # SMPTE 170M-2004 Section 8: colour subcarrier 3.579545 MHz.
        freq_mhz=3.579545,
        source="SMPTE RP 168",
    ),
    Element(
        id="second_zone_bar",
        label="50 IRE luminance reference zone",
        kind="bar",
        window_us=(36.00, 48.00),
        nominal=50.0,
        source="SMPTE RP 168",
    ),
    Element(
        id="black_reference",
        label="Reference black zone",
        kind="bar",
        window_us=(48.00, 60.00),
        # Reference black, not blanking: NTSC_SETUP_IRE above it.
        nominal=NTSC_SETUP_IRE,
        source="SMPTE RP 168",
    ),
)

VITS_NTSC_VIRS_FIELD1 = VitsDefinition(
    id="ntsc-virs-field1",
    system="NTSC",
    frame_line=19,
    field=1,
    field_line=19,
    # IEC 60857-1986-9.1.3: "The video signal shall contain on lines 19 and
    # 282 a VIR signal".  The only VITS any LaserDisc standard mandates.
    status="shall",
    source="IEC 60857-1986 9.1.3",
    elements=_VIRS_ELEMENTS,
    notes="Not present on monochrome discs (IEC 60857-1986 9.1.3).",
)

VITS_NTSC_VIRS_FIELD2 = VitsDefinition(
    id="ntsc-virs-field2",
    system="NTSC",
    frame_line=282,
    field=2,
    field_line=19,
    status="shall",
    source="IEC 60857-1986 9.1.3",
    elements=_VIRS_ELEMENTS,
    notes="Not present on monochrome discs (IEC 60857-1986 9.1.3).",
)

VITS_NTSC_NTC7_COMPOSITE = VitsDefinition(
    id="ntsc-ntc7-composite",
    system="NTSC",
    frame_line=20,
    field=1,
    field_line=20,
    # IEC 60857-1986-9.1.4: "It is recommended that the video signal shall
    # contain on line 20 a composite test signal".
    status="recommended",
    source="IEC 60857-1986 9.1.4",
    elements=(
        Element(
            id="white_reference_bar",
            label="100 IRE white reference bar",
            kind="bar",
            window_us=(12.00, 30.00),
            nominal=100.0,
            source=_NTC7_COMPOSITE_YAML,
        ),
        Element(
            id="pulse_2t",
            label="2T luminance sine-squared pulse",
            kind="pulse",
            window_us=(33.75, 34.25),
            nominal=100.0,
            source=_NTC7_COMPOSITE_YAML,
        ),
        Element(
            id="pulse_12t5_luma",
            label="12.5T modulated pulse, luminance component",
            kind="pulse",
            window_us=(35.40, 38.60),
            nominal=50.0,
            source=_NTC7_COMPOSITE_YAML,
        ),
        Element(
            id="pulse_12t5_chroma",
            label="12.5T modulated pulse, chrominance component",
            kind="chroma_bar",
            window_us=(35.40, 38.60),
            nominal=50.0,
            channel="chroma",
            superimposed=True,
            freq_mhz=3.579545,
            source=_NTC7_COMPOSITE_YAML,
        ),
        Element(
            id="chroma_reference",
            label="Chrominance reference burst over the staircase",
            kind="chroma_bar",
            window_us=(42.00, 60.00),
            nominal=20.0,
            channel="chroma",
            superimposed=True,
            freq_mhz=3.579545,
            source=_NTC7_COMPOSITE_YAML,
        ),
        Element(
            id="staircase",
            label="5-step luminance staircase",
            kind="staircase",
            window_us=(46.00, 60.00),
            nominal=90.0,
            steps=(18.0, 36.0, 54.0, 72.0, 90.0),
            source=_NTC7_COMPOSITE_YAML,
        ),
        Element(
            id="staircase_terminus",
            label="Reference level bar at the staircase top",
            kind="bar",
            window_us=(60.00, 62.00),
            nominal=90.0,
            source=_NTC7_COMPOSITE_YAML,
        ),
    ),
    notes=(
        "The differential gain and differential phase reference for NTSC: the "
        "chrominance burst spans the staircase, so chroma amplitude and phase "
        "can be read against five luma pedestals on one line."
    ),
)

_NTC7_COMBINATION_PACKET_WINDOWS = (
    (18.00, 23.00),
    (24.00, 27.00),
    (28.00, 31.00),
    (32.00, 35.00),
    (36.00, 39.00),
    (40.00, 43.00),
)

VITS_NTSC_NTC7_COMBINATION = VitsDefinition(
    id="ntsc-ntc7-combination",
    system="NTSC",
    frame_line=283,
    field=2,
    field_line=20,
    # IEC 60857-1986-9.1.4: "and on line 283 a combination test signal".
    status="recommended",
    source="IEC 60857-1986 9.1.4",
    elements=(
        Element(
            id="grey_pedestal",
            label="Grey background level",
            kind="bar",
            window_us=(12.00, 62.00),
            nominal=50.0,
            source=_NTC7_COMBINATION_YAML,
        ),
        Element(
            id="reference_boost",
            label="Grey reference boost over the pedestal",
            kind="bar",
            window_us=(12.00, 16.00),
            # +50 IRE on the 50 IRE pedestal, an apparent 100 IRE.
            nominal=100.0,
            superimposed=True,
            source=_NTC7_COMBINATION_YAML,
        ),
    ) + tuple(
        Element(
            id=f"packet_{index + 1}",
            label=f"{freq_mhz} MHz burst",
            kind="burst_packet",
            window_us=window,
            nominal=25.0,
            channel="chroma",
            superimposed=True,
            freq_mhz=freq_mhz,
            source=_NTC7_COMBINATION_YAML,
        )
        for index, (freq_mhz, window) in enumerate(
            zip(NTSC_MULTIBURST_NTC7, _NTC7_COMBINATION_PACKET_WINDOWS)
        )
    ) + (
        Element(
            id="chroma_zone_1",
            label="Chrominance staircase zone 1",
            kind="chroma_bar",
            window_us=(46.00, 50.00),
            nominal=10.0,
            channel="chroma",
            superimposed=True,
            freq_mhz=3.579545,
            source=_NTC7_COMBINATION_YAML,
        ),
        Element(
            id="chroma_zone_2",
            label="Chrominance staircase zone 2",
            kind="chroma_bar",
            window_us=(50.00, 54.00),
            nominal=20.0,
            channel="chroma",
            superimposed=True,
            freq_mhz=3.579545,
            source=_NTC7_COMBINATION_YAML,
        ),
        Element(
            id="chroma_zone_3",
            label="Chrominance staircase zone 3",
            kind="chroma_bar",
            window_us=(54.00, 60.00),
            nominal=40.0,
            channel="chroma",
            superimposed=True,
            freq_mhz=3.579545,
            source=_NTC7_COMBINATION_YAML,
        ),
    ),
    notes=(
        "Amplitude conformance must not be measured from this multiburst on a "
        "single line: its ~3 us packets are as short as the scan window at "
        "NTSC 4fsc.  See NTSC_MULTIBURST_NTC7."
    ),
)

_FCC_MULTIBURST_WINDOWS = (
    (18.20, 26.70),
    (28.20, 34.20),
    (35.20, 40.20),
    (41.20, 46.20),
    (47.20, 52.20),
    (53.20, 58.20),
)

VITS_NTSC_FCC_MULTIBURST = VitsDefinition(
    id="ntsc-fcc-multiburst",
    system="NTSC",
    # FCC Rules Part 73 / EIA RS-498 national usage, on a line IEC 60857 does
    # not assign.  GGV NTSC carries it on field line 22 in both parities.
    frame_line=22,
    field=1,
    field_line=22,
    status="permitted",
    source=_FCC_MULTIBURST_YAML,
    elements=(
        Element(
            id="grey_pedestal",
            label="Grey pedestal",
            kind="bar",
            window_us=(9.20, 62.00),
            nominal=40.0,
            source=_FCC_MULTIBURST_YAML,
        ),
        Element(
            id="white_reference_bar",
            label="White reference boost over the pedestal",
            kind="bar",
            window_us=(9.20, 15.70),
            # +60 IRE on the 40 IRE pedestal, an apparent 100 IRE.
            nominal=100.0,
            superimposed=True,
            source=_FCC_MULTIBURST_YAML,
        ),
    ) + tuple(
        Element(
            id=f"packet_{index + 1}",
            label=f"{freq_mhz} MHz burst",
            kind="burst_packet",
            window_us=window,
            nominal=30.0,
            channel="chroma",
            superimposed=True,
            freq_mhz=freq_mhz,
            source=_FCC_MULTIBURST_YAML,
        )
        for index, (freq_mhz, window) in enumerate(
            zip(NTSC_MULTIBURST_FCC, _FCC_MULTIBURST_WINDOWS)
        )
    ),
    notes=(
        "The only NTSC multiburst whose packets are long enough to measure "
        "amplitude from a single line at 4fsc."
    ),
)


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

VITS_DEFINITIONS = (
    VITS_PAL_LINE19,
    VITS_PAL_LINE332,
    VITS_PAL_MULTIBURST_FIELD1,
    VITS_PAL_MULTIBURST_FIELD2,
    VITS_PAL_BLANKED_FIELD1,
    VITS_PAL_BLANKED_FIELD2,
    VITS_NTSC_VIRS_FIELD1,
    VITS_NTSC_VIRS_FIELD2,
    VITS_NTSC_NTC7_COMPOSITE,
    VITS_NTSC_NTC7_COMBINATION,
    VITS_NTSC_FCC_MULTIBURST,
)


def definitions_for(system):
    """Every VITS definition for one system, in frame-line order."""
    _check_system(system)
    return tuple(
        sorted(
            (d for d in VITS_DEFINITIONS if d.system == system),
            key=lambda d: d.frame_line,
        )
    )


def definition(vits_id):
    """The definition with this id, or None."""
    for entry in VITS_DEFINITIONS:
        if entry.id == vits_id:
            return entry
    return None


def definitions_on_field_line(system, field_line):
    """Every definition that may appear on a given field line.

    A field line can host more than one candidate - PAL field line 20 carries
    the multiburst in field 1 and the chrominance bars in field 2 - so the
    caller has to choose by measured content, not by line number.
    """
    _check_system(system)
    matches = []
    for entry in VITS_DEFINITIONS:
        if entry.system != system:
            continue
        lines = {entry.field_line}
        if entry.alternate_frame_line is not None:
            lines.add(frame_line_to_field(system, entry.alternate_frame_line)[1])
        if field_line in lines:
            matches.append(entry)
    return tuple(matches)
