#!/usr/bin/env python3
"""
vits_manifest - what a capture is recorded as carrying, and what follows

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

A conformance run on a capture that carries no NTC-7 insertion test signal
finds no NTC-7 checks to make, and prints a PASS.  Nothing was wrong with
the disc and nothing was wrong with the decoder, but the report says the
same thing it would say if both were perfect - the checks that mattered were
never attempted, and nobody reading the summary line can tell.

The manifest closes that.  It records, per capture, which VITS the disc
actually carries, measured by analysis/vits_inventory.py rather than assumed
from a line number, and a run against it can then say "skipped: capture
carries no NTC-7 ITS" where it would otherwise have said nothing at all.
A capture the manifest does not mention is refused outright: an unsurveyed
capture cannot be told apart from a survey that has gone stale.

Nothing here opens a file except load_manifest, so the decisions can be unit
tested on their own (AGENTS.md 4.2).
"""

import json
import os

__all__ = [
    "MANIFEST_FILENAME",
    "carried_vits",
    "load_manifest",
    "manifest_entry",
    "presence_verdicts",
]


#: Name the manifest is expected to have beside the captures it describes.
MANIFEST_FILENAME = "vits-manifest.json"


def load_manifest(path):
    """Read a manifest file; returns its records as a list."""
    with open(path, encoding="utf-8") as handle:
        loaded = json.load(handle)
    return loaded if isinstance(loaded, list) else [loaded]


def _names(record):
    """Every name a record answers to."""
    names = set()
    for key in ("label", "capture"):
        value = record.get(key)
        if not value:
            continue
        base = os.path.basename(value)
        names.update({value, base, os.path.splitext(base)[0]})
    return names


def manifest_entry(records, capture):
    """The record describing `capture`, or None.

    `capture` may be the source capture's path or name, the decoded file's
    name, or the label the inventory table uses, because the thing being
    judged is a decode and the thing surveyed was the capture it came from -
    the decoder writes no reference to its input into the CVBS metadata, so
    the two are tied together by name.
    """
    base = os.path.basename(capture)
    wanted = {capture, base, os.path.splitext(base)[0]}
    for record in records:
        if _names(record) & wanted:
            return record
    return None


def carried_vits(entry):
    """The vits_ids a manifest record says its capture carries."""
    return {vits_id for vits_id, record in (entry.get("vits") or {}).items()
            if record.get("carried")}


def presence_verdicts(definitions, entry, found_ids):
    """Whether each definition was where the manifest said it would be.

    Returns [(vits_id, verdict, reason)] with verdict in PASS/FAIL/SKIP:

    - the manifest records it and the decode found it: PASS;
      every verdict carries a reason, because a presence check has no
      number and its reason is the whole of what it reports;
    - the manifest records it and the decode did not: FAIL, because the
      manifest is the surveyed truth about the disc and a decode that loses
      a signal the disc carries is the regression this exists to catch;
    - the manifest does not record it: SKIP, naming the capture as the
      reason, so the summary line cannot read as a clean bill on checks that
      were never attempted.

    Definitions made only of blanked lines are left out: a blank line has no
    content to be found by, so its presence is not a question the identifier
    can answer, and vits_conformance.check_blanked_lines judges it directly
    and unconditionally instead.
    """
    carried = carried_vits(entry)
    verdicts = []
    for definition in definitions:
        if all(element.kind == "blanked" for element in definition.elements):
            continue
        if definition.id not in carried:
            verdicts.append((
                definition.id, "SKIP",
                f"capture carries no {definition.id}"))
        elif definition.id in found_ids:
            verdicts.append((
                definition.id, "PASS",
                "found where the manifest records it"))
        else:
            verdicts.append((
                definition.id, "FAIL",
                f"the manifest records this capture carries "
                f"{definition.id}, and this decode does not"))
    return verdicts
