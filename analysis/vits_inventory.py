#!/usr/bin/env python3
"""
vits_inventory - what VITS a capture carries, at each radius of the disc

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The MTF of a LaserDisc changes with radius, so a decoder can be correct at
one radius and wrong at another, and a conformance test is only as good as
the sample it runs on.  Choosing those samples needs to know what each
candidate capture actually carries and where - which is a survey, and a
survey written out by hand goes stale the moment a detector changes.

This runs the survey instead.  Given a capture and a set of probe points, it
decodes a short sample at each, identifies the VITS on every field through
analysis/vits_identify.py, and emits the result as JSON and as a markdown
row.  Re-running it on an unchanged capture reproduces the same bytes: the
decodes are serial (-t 1), nothing dated or timed goes into the record, and
the JSON is written with sorted keys.

Probe points are fractions of the whole file, not of the recorded band,
because the band is only known once a decode has reported the spin-up
offset.  The offset is measured and reported alongside, and a probe that
lands inside it is refused rather than surveyed - a decode there reads the
lead-in, not the disc.

Usage:
    python3 analysis/vits_inventory.py <capture.ldf> [options]
    python3 analysis/vits_inventory.py --json-in a.json b.json --markdown
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict

# Local: analysis/ is a directory of scripts rather than a package.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from video_common import load_video                        # noqa: E402
from vits_conformance import check_blanked_lines           # noqa: E402
from vits_geometry import FieldGeometry                    # noqa: E402
from vits_identify import (                                # noqa: E402
    IDENTIFY_LEVEL_TOLERANCE_IRE,
    identify_vits,
)


__all__ = [
    "capture_frames",
    "is_line_blank",
    "disc_frame_at_start",
    "manifest_row",
    "manifest_table",
    "markdown_row",
    "markdown_table",
    "merge_profiles",
    "parse_frame_log",
    "probe_frames",
    "recorded_band_frames",
    "spin_up_offset",
    "survey_capture",
    "system_from_name",
    "vits_profile",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Sample rate of an .ldf, in Hz.  The FLAC header of a capture declares
#: sample_rate=40000 as a placeholder and its duration field is wrong by a
#: factor of 1000, so the frame count has to come from the sample count and
#: this rate rather than from anything the container says about time.
CAPTURE_SAMPLE_RATE_HZ = 40e6

#: Frame rates, as the exact rationals the standards state: 25 Hz for
#: 625-line (EBU Tech. 3280-E Section 1.2) and 30000/1001 Hz for 525-line
#: (SMPTE 170M-2004 Section 8).
FRAME_RATE_HZ = {"PAL": 25.0, "NTSC": 30000.0 / 1001.0}

#: Where along the file the survey probes, as percentages.  Inner, middle
#: and outer of the recorded band; the MTF change across that span is what
#: makes a radius sweep worth taking at all.
DEFAULT_PROBE_PERCENTAGES = (5.0, 50.0, 95.0)

#: Frames to decode at each probe point.  Enough that both parities appear
#: several times over, so a VITS carried on only one of them is still seen
#: repeatedly rather than once.
DEFAULT_PROBE_LENGTH_FRAMES = 12

#: Identification score a VITS must reach at a probe point before the
#: inventory records it as carried.  Above vits_identify's own
#: IDENTIFY_MIN_SCORE, because a survey that feeds test selection should
#: report what a capture reliably carries rather than what it might.
INVENTORY_MIN_SCORE = 0.75

#: Probe points a VITS must appear at before it is called carried, as a
#: fraction of the points surveyed.  A signal seen at one radius out of
#: three is a finding about that radius, not about the disc.
INVENTORY_MIN_PROBE_FRACTION = 0.5

#: How far a blanked line's mean may sit from blanking and still count as
#: blanked, in IRE.  This is a survey, not a verdict: a disc whose line 22
#: carries a 1.1 IRE pedestal offset does carry a blanked line 22, and it is
#: check_blanked_lines that must report the offset as a fault.  Reusing
#: vits_identify's own level tolerance keeps the survey as loose against
#: levels as the identification of every other signal is, and for the same
#: reason - a decode with a real level fault still has to be surveyed, or
#: the conformance layer never gets to report the fault.
INVENTORY_BLANK_TOLERANCE_IRE = IDENTIFY_LEVEL_TOLERANCE_IRE

#: Fields of a parity a VITS must be found on, as a fraction, before the
#: line it was found on is reported as one of its lines.  A signal seen on
#: one line of one field is a misread; a disc that repeats a signal on
#: several lines - GGV1069 carries the FCC multiburst on field lines 22, 23
#: and 24 - shows it on all of them in every field of the parity, so the
#: denominator is the parity's fields and never the total occurrences.
INVENTORY_MIN_LINE_FRACTION = 0.5

#: The decoder's own per-frame report, e.g.
#: "File Frame 1430: CAV Frame #1201" or "File Frame 90: CLV Timecode 00:01".
FRAME_LOG_RE = re.compile(
    r"File Frame (?P<file_frame>\d+): (?P<disc_format>CAV|CLV) "
    r"(?:Frame #(?P<disc_frame>\d+)|Timecode (?P<timecode>\S+))")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def system_from_name(name):
    """"PAL", "NTSC" or None, from a capture's file name.

    Every library surveyed names the system in the file, and the decoder
    needs to be told which to expect.  Returned as None when the name does
    not say so the caller can insist on being told rather than guess.
    """
    upper = os.path.basename(name).upper()
    found = {token for token in ("PAL", "NTSC") if f"_{token}_" in upper}
    return found.pop() if len(found) == 1 else None


def capture_frames(sample_count, system):
    """Whole frames a capture of `sample_count` samples holds."""
    if sample_count is None or sample_count <= 0:
        return None
    return int(sample_count / (CAPTURE_SAMPLE_RATE_HZ / FRAME_RATE_HZ[system]))


def parse_frame_log(text):
    """Every "File Frame n: CAV Frame #m" line of a decode log, as dicts.

    Keys: file_frame, disc_format, and one of disc_frame (CAV) or timecode
    (CLV).  The decoder is the only thing that reads a disc's own frame
    numbering, so the spin-up offset and the CAV/CLV question are both
    answered from here rather than from the file name.
    """
    entries = []
    for match in FRAME_LOG_RE.finditer(text):
        entry = {"file_frame": int(match.group("file_frame")),
                 "disc_format": match.group("disc_format")}
        if match.group("disc_frame") is not None:
            entry["disc_frame"] = int(match.group("disc_frame"))
        else:
            entry["timecode"] = match.group("timecode")
        entries.append(entry)
    return entries


def spin_up_offset(entries):
    """File frames between the start of the capture and disc frame 1.

    Every capture in the libraries surveyed is a full disc including
    spin-up, so a decode has to start past it.  Only CAV entries can answer
    this, because only they carry an absolute disc frame number; None when
    none do.
    """
    offsets = [e["file_frame"] - e["disc_frame"] for e in entries
               if e.get("disc_frame") is not None]
    return min(offsets) if offsets else None


def probe_frames(total_frames, percentages=DEFAULT_PROBE_PERCENTAGES):
    """File frames to survey, from percentages along the whole file."""
    return [int(total_frames * percentage / 100.0)
            for percentage in percentages]


def is_line_blank(check, tolerance_ire=INVENTORY_BLANK_TOLERANCE_IRE):
    """Whether a blanking check found a blanked line, level fault aside.

    Takes a Check from vits_conformance.check_blanked_lines.  Its verdict
    answers a different question - whether the residual is inside the
    decoder allowance - and a survey that used the verdict would report a
    disc with a small pedestal offset on line 22 as not carrying a blanked
    line 22 at all, which is not what the disc says.
    """
    mean_ire = check.detail.get("mean_ire")
    return mean_ire is not None and abs(mean_ire) <= tolerance_ire


def recorded_band_frames(total_frames, spin_up,
                         percentages=DEFAULT_PROBE_PERCENTAGES):
    """File frames at points along the recorded band, past the spin-up.

    probe_frames() places its points along the whole file, because the
    survey that measures the spin-up offset cannot use it before it has run.
    An extraction runs after the survey, so it can place its cuts along the
    band that actually holds the programme - which is what a radius means -
    rather than along the file, which starts in the lead-in.
    """
    start = 0 if spin_up is None else max(0, spin_up)
    span = max(0, total_frames - start)
    return [start + int(span * percentage / 100.0)
            for percentage in percentages]


def vits_profile(identifications, blanked=(),
                 min_score=INVENTORY_MIN_SCORE,
                 min_line_fraction=INVENTORY_MIN_LINE_FRACTION):
    """What one decoded sample carries, as {vits_id: {lines, parities}}.

    `identifications` is [(parity, {field_line: Identification})], one entry
    per field, as vits_identify.identify_vits returns for each.  A VITS is
    reported with every field line and parity it was seen on, because a line
    number is evidence and never the reason for a match: real discs move
    these signals, and a survey that assumed the definition's line would
    report the PAL multiburst as absent on half the pressings.

    A line is only reported once the VITS was found on it in at least
    `min_line_fraction` of that parity's fields, so a single misread field
    does not add a line the disc does not carry, while a disc that really
    does repeat a signal on three consecutive lines keeps all three.

    `blanked` is [(parity, field_line, vits_id, is_blank)] for the lines a
    standard requires blank - IEC 60856-1986 9.1.3 lines 22 and 335.  Those
    cannot be identified by content, because being blank is the whole of
    their content, so their presence is a measurement of absence taken from
    the check the conformance runner makes.  Folded in here so one column
    answers what a capture carries rather than two.
    """
    fields_of_parity = Counter(parity for parity, _ in identifications)
    seen = defaultdict(Counter)    # vits_id -> {(parity, field_line): fields}
    best_score = defaultdict(float)

    for parity, found in identifications:
        for field_line, identification in found.items():
            if identification.score < min_score:
                continue
            seen[identification.vits_id][(parity, field_line)] += 1
            best_score[identification.vits_id] = max(
                best_score[identification.vits_id], identification.score)

    for parity, field_line, vits_id, is_blank in blanked:
        if is_blank:
            seen[vits_id][(parity, field_line)] += 1
            best_score[vits_id] = max(best_score[vits_id], 1.0)

    profile = {}
    for vits_id, counts in sorted(seen.items()):
        kept = {where: count for where, count in counts.items()
                if count >= min_line_fraction * fields_of_parity[where[0]]}
        if not kept:
            continue
        profile[vits_id] = {
            "field_lines": sorted({line for _, line in kept}),
            "parities": sorted({parity for parity, _ in kept}),
            "fields": sum(kept.values()),
            "best_score": round(best_score[vits_id], 3),
        }
    return profile


def merge_profiles(profiles,
                   min_probe_fraction=INVENTORY_MIN_PROBE_FRACTION):
    """One profile for the disc from the profiles of its probe points.

    A VITS has to appear at enough of the points to be called carried; the
    ones that do not are still reported, marked with the points they were
    seen at, because "present at the inner radius only" is a finding about
    the pressing rather than noise to be dropped.
    """
    if not profiles:
        return {}
    needed = max(1, int(round(min_probe_fraction * len(profiles))))
    merged = {}
    for index, profile in enumerate(profiles):
        for vits_id, record in profile.items():
            entry = merged.setdefault(
                vits_id, {"field_lines": set(), "parities": set(),
                          "fields": 0, "best_score": 0.0, "probes": []})
            entry["field_lines"].update(record["field_lines"])
            entry["parities"].update(record["parities"])
            entry["fields"] += record["fields"]
            entry["best_score"] = max(entry["best_score"],
                                      record["best_score"])
            entry["probes"].append(index)
    return {vits_id: {"field_lines": sorted(entry["field_lines"]),
                      "parities": sorted(entry["parities"]),
                      "fields": entry["fields"],
                      "best_score": entry["best_score"],
                      "probes": entry["probes"],
                      "at_every_radius": len(entry["probes"]) == len(profiles),
                      "carried": len(entry["probes"]) >= needed}
            for vits_id, entry in sorted(merged.items())}


def _vits_phrase(vits_id, record):
    lines = "/".join(str(line) for line in record["field_lines"])
    parities = "".join(f"F{parity}" for parity in record["parities"])
    phrase = f"`{vits_id}` line {lines} {parities}"
    if not record.get("at_every_radius", True):
        phrase += f" ({len(record['probes'])} of the probes)"
    return phrase


def _spin_up_cell(spin_up):
    """The Spin-up column: file frames between the file and disc frame 1.

    Negative on a cut, which has no spin-up at all - it begins inside the
    disc, and the offset then says how far in.  Rendered as that rather than
    as a negative spin-up, which would read as nonsense.
    """
    if spin_up is None:
        return "?"
    if spin_up < 0:
        return f"from disc frame {-spin_up}"
    return str(spin_up)


def markdown_row(record):
    """One row of the inventory table for one capture.

    Every VITS found is listed, including one found at some radii and not
    others - GGV1069 carries the FCC multiburst at the inner radius alone -
    because a signal that comes and goes across the disc is the finding a
    radius survey exists to make, and dropping it would leave the row saying
    the disc does not carry it at all.  Those are flagged with the count of
    probe points that saw them.
    """
    carried = [_vits_phrase(vits_id, vits)
               for vits_id, vits in record["vits"].items()]
    frames = record.get("frames")
    return (f"| `{record['label']}` | {record['system']} "
            f"| {record.get('disc_format') or '?'} "
            f"| {'?' if frames is None else f'~{frames}'} "
            f"| {_spin_up_cell(record.get('spin_up'))} "
            f"| {'; '.join(carried) if carried else 'none identified'} |")


def markdown_table(records):
    """The whole inventory table, header included."""
    return "\n".join(
        ["| Capture | System | Format | Frames | Spin-up | VITS carried |",
         "|---|---|---|---|---|---|"]
        + [markdown_row(record) for record in records])


def disc_frame_at_start(record):
    """The disc's own frame number where a capture begins, or None.

    A full-disc capture begins in the lead-in, so this is 0 or below and is
    reported as the spin-up instead; a cut begins somewhere inside the
    programme, and this says where.  Only CAV can answer it - CLV has no
    absolute frame number - and a capture whose spin-up could not be
    measured cannot answer it either.
    """
    spin_up = record.get("spin_up")
    if spin_up is None:
        return None
    start = (record.get("source_file_frames") or [0])[0]
    frame = start - spin_up
    return frame if frame > 0 else None


def manifest_row(record):
    """One row of the manifest table for one capture."""
    frames = record.get("source_file_frames")
    disc_frame = disc_frame_at_start(record)
    carried = "; ".join(_vits_phrase(vits_id, vits)
                        for vits_id, vits in record["vits"].items())
    band = record.get("radius_band")
    if band and record.get("band_percentage") is not None:
        band = f"{band} ({record['band_percentage']:.0f} %)"
    return "| " + " | ".join([
        f"`{record.get('capture') or record['label']}`",
        record.get("disc") or "—",
        record.get("side") or "—",
        record["system"],
        record.get("disc_format") or "?",
        record.get("source_library") or "—",
        "—" if not frames else f"{frames[0]}–{frames[1]}",
        "—" if disc_frame is None else str(disc_frame),
        band or "—",
        _spin_up_cell(record.get("spin_up")),
        carried or "none identified",
    ]) + " |"


def manifest_table(records):
    """The table that goes beside the captures, one row per capture.

    Wider than the inventory table above because it answers a different
    question: not "what does this library hold" but "may this capture be
    used for this check", which needs the provenance as well as the VITS.
    """
    header = ("| File | Disc | Side | System | Format | Source library "
              "| File frames | Disc frame | Radius | Spin-up | VITS |")
    return "\n".join([header, "|" + "---|" * 11]
                      + [manifest_row(record) for record in records])


# ---------------------------------------------------------------------------
# Decoding and surveying
# ---------------------------------------------------------------------------

def probe_sample_count(path, runner=subprocess.run):
    """Samples in a capture, via ffprobe, or None if it cannot be read.

    The frame count is the only column that needs a tool this project does
    not own, so it degrades to "?" rather than failing the survey.
    """
    try:
        result = runner(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=duration_ts",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, check=False)
    except (OSError, ValueError):
        return None
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip().splitlines()[0])
    except (IndexError, ValueError):
        return None


def decode_sample(path, system, file_frame, length, out_base,
                  runner=subprocess.run):
    """Decode `length` frames from `file_frame`; returns the decoder's log.

    Serial (-t 1) so the same capture gives the same samples every run, and
    without audio or EFM because neither carries a VITS.
    """
    result = runner(
        [sys.executable, "-m", "lddecode.main",
         "--PAL" if system == "PAL" else "--NTSC",
         "-s", str(file_frame), "-l", str(length),
         "-t", "1", "--daa", "--noEFM", path, out_base],
        capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"decode of {path} at frame {file_frame} failed:\n"
            f"{result.stderr[-2000:]}")
    return result.stdout + result.stderr


def survey_probe(path, system, file_frame, length, work_dir):
    """Decode one probe point and identify what its fields carry.

    A probe that decodes nothing is surveyed as carrying nothing rather than
    raised: the lead-out of a disc decodes to an empty file, and a survey
    tool that died there could not report on a capture that reaches it.
    """
    out_base = os.path.join(work_dir, f"probe-{file_frame}")
    log = decode_sample(path, system, file_frame, length, out_base)

    decoded = out_base + ".cvbs"
    if not os.path.exists(decoded) or os.path.getsize(decoded) == 0:
        entries = parse_frame_log(log)
        return {
            "file_frame": file_frame, "decoded_fields": 0,
            "disc_format": entries[0]["disc_format"] if entries else None,
            "disc_frame": entries[0].get("disc_frame") if entries else None,
            "timecode": entries[0].get("timecode") if entries else None,
            "spin_up": spin_up_offset(entries), "vits": {},
        }

    _, fields, _ = load_video(decoded)

    identifications, blanked = [], []
    for field in fields:
        parity = 1 if field.isFirstField else 2
        geometry = FieldGeometry(field)
        identifications.append((parity, identify_vits(field, geom=geometry)))
        blanked.extend(
            (parity, check.field_line, check.id.split("/")[0],
             is_line_blank(check))
            for check in check_blanked_lines(geometry, parity))

    entries = parse_frame_log(log)
    return {
        "file_frame": file_frame,
        "decoded_fields": len(fields),
        "disc_format": entries[0]["disc_format"] if entries else None,
        "disc_frame": entries[0].get("disc_frame") if entries else None,
        "timecode": entries[0].get("timecode") if entries else None,
        "spin_up": spin_up_offset(entries),
        "vits": vits_profile(identifications, blanked),
    }


def survey_capture(path, system=None, percentages=DEFAULT_PROBE_PERCENTAGES,
                   length=DEFAULT_PROBE_LENGTH_FRAMES, label=None,
                   work_dir=None):
    """Survey one capture at every probe point; returns its record."""
    system = system or system_from_name(path)
    if system is None:
        raise ValueError(
            f"cannot tell the system of {path!r} from its name; "
            f"pass --system")

    samples = probe_sample_count(path)
    frames = capture_frames(samples, system)
    if frames is None:
        raise RuntimeError(
            f"cannot read the sample count of {path!r}; ffprobe is needed "
            f"to place probe points along the file")

    record = {
        # As given, not resolved: a manifest checked in beside the captures
        # it describes must not carry the absolute path of the machine the
        # survey happened to run on.
        "capture": path,
        "label": label or os.path.join(*os.path.abspath(path).split(os.sep)[-2:]),
        "system": system,
        "samples": samples,
        "frames": frames,
        "probe_length_frames": length,
        "probe_percentages": list(percentages),
    }

    made_work_dir = work_dir is None
    if made_work_dir:
        work_dir = tempfile.mkdtemp(prefix="vits-inventory-")
    try:
        probes = [survey_probe(path, system, file_frame, length, work_dir)
                  for file_frame in probe_frames(frames, percentages)]
    finally:
        if made_work_dir:
            for name in os.listdir(work_dir):
                os.unlink(os.path.join(work_dir, name))
            os.rmdir(work_dir)

    spin_ups = [p["spin_up"] for p in probes if p["spin_up"] is not None]
    record["spin_up"] = min(spin_ups) if spin_ups else None
    formats = {p["disc_format"] for p in probes if p["disc_format"]}
    record["disc_format"] = formats.pop() if len(formats) == 1 else None
    record["probes"] = probes
    record["vits"] = merge_profiles([p["vits"] for p in probes])

    inner = probes[0]["file_frame"] if probes else None
    if record["spin_up"] is not None and inner is not None:
        if inner <= record["spin_up"]:
            raise RuntimeError(
                f"inner probe at file frame {inner} is inside the "
                f"{record['spin_up']}-frame spin-up of {path!r}; raise the "
                f"first --probe-percentages entry")
    return record


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Survey what VITS a capture carries, at each radius.")
    parser.add_argument("captures", nargs="*",
                        help="capture files to survey")
    parser.add_argument("--system", choices=("PAL", "NTSC"),
                        help="override the system read from the file name")
    parser.add_argument("--label", action="append", default=[],
                        help="table label for each capture, in order")
    parser.add_argument("--probe-percentages", default=",".join(
        str(p) for p in DEFAULT_PROBE_PERCENTAGES),
        help="comma-separated points along the file to survey")
    parser.add_argument("--length", type=int,
                        default=DEFAULT_PROBE_LENGTH_FRAMES,
                        help="frames to decode at each probe point")
    parser.add_argument("--json", help="write the records here")
    parser.add_argument("--json-in", nargs="+", default=[],
                        help="render records already surveyed, instead")
    parser.add_argument("--markdown", action="store_true",
                        help="print the inventory table")
    parser.add_argument("--manifest-table", action="store_true",
                        help=("print the wider table that goes beside the "
                              "captures, with their provenance"))
    args = parser.parse_args(argv)

    records = []
    for path in args.json_in:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
        records.extend(loaded if isinstance(loaded, list) else [loaded])

    percentages = tuple(float(p) for p in args.probe_percentages.split(","))
    for index, path in enumerate(args.captures):
        label = args.label[index] if index < len(args.label) else None
        records.append(survey_capture(path, system=args.system,
                                      percentages=percentages,
                                      length=args.length, label=label))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(records, handle, indent=2, sort_keys=True)
            handle.write("\n")

    if args.manifest_table:
        print(manifest_table(records))
    elif args.markdown or not args.json:
        print(markdown_table(records))
    return 0


if __name__ == "__main__":
    sys.exit(main())
