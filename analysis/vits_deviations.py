#!/usr/bin/env python3
"""
vits_deviations - the faults a conformance run is allowed to still have

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Registering the radius sweep in CI puts thirteen captures and some six
hundred checks behind the build, and seventy-six of those checks fail today
on faults the decoder is already known to have - the PAL 5.8 MHz multiburst
packet, the 2T pulse, the luma/chroma gain ratio.  A permanently red job
proves nothing, and the two usual ways of turning it green are both
forbidden: widening an allowance would make the fault invisible everywhere
(AGENTS.md 15), and marking the test WILL_FAIL would swallow the next
regression alongside the known ones.

So the faults are listed instead, by name, one entry per failing check per
capture, in analysis/vits_known_deviations.toml.  A listed check reports
KNOWN and does not fail the build.  Everything else about the list is
designed to make it shrink:

- a listed check that now **passes** fails the build, so the entry is
  deleted in the change that fixes it rather than left to rot;
- a listed check that spends more of its band than its recorded `ceiling`
  fails the build, so a fault getting worse is still a regression;
- a listed check this run never made fails the build, so an entry cannot
  outlive the check it describes.

`measured` and `unit` in an entry are the reading when it was recorded.
They are documentation - what the fault looked like - and are deliberately
not compared against, because a figure that must be updated on every
unrelated decode change is a figure nobody keeps true.

Nothing here opens a file except load_deviations, so the decisions can be
unit tested on their own (AGENTS.md 4.2).
"""

import math
import os
import tomllib

__all__ = [
    "DEVIATIONS_FILENAME",
    "band_used",
    "capture_name",
    "load_deviations",
    "reconcile",
]


#: Name of the committed list, beside the runner that reads it.
DEVIATIONS_FILENAME = "vits_known_deviations.toml"


def capture_name(path):
    """The capture a path names, as the manifest and the list both label it."""
    return os.path.splitext(os.path.basename(path))[0]


def band_used(record):
    """How much of what it was allowed a check spent, or None.

    A check with a nominal is allowed a band either side of it, so the
    figure is its deviation over that band.  A ceiling has no nominal - it
    is judged against `limit` directly - so there the figure is the
    measurement over the limit.  Both read the same way: 1.0 sits exactly on
    what the check was allowed, which is what makes the number comparable
    between an IRE level and a dB response.
    """
    measured = record.get("measured")
    if measured is None or not math.isfinite(measured):
        return None
    band = record.get("band")
    nominal = record.get("nominal")
    if band and nominal is not None:
        return abs(measured - nominal) / band
    limit = record.get("limit")
    if limit:
        return abs(measured) / abs(limit)
    return None


def load_deviations(path):
    """Read the list at `path`; returns its `deviation` entries."""
    with open(path, "rb") as handle:
        return tomllib.load(handle).get("deviation", [])


def _key(record):
    """What identifies one check within one capture.

    The identifier alone is not enough: a capture carrying its multiburst on
    three field lines of both parities makes the same six checks six times
    over, and they are different measurements of different lines.
    """
    return (record.get("id"), record.get("field_line"), record.get("parity"))


def _entry_key(entry):
    return (entry.get("check"), entry.get("field_line"), entry.get("parity"))


def for_capture(entries, capture):
    """The entries describing `capture`, which may be given as a path."""
    wanted = capture_name(capture)
    return [entry for entry in entries
            if capture_name(entry.get("capture", "")) == wanted]


def reconcile(records, entries, capture):
    """Judge this run's checks against the list of known deviations.

    `records` are the run's checks as mappings, in the order the run made
    them; `entries` is the whole list, of which only those naming `capture`
    are consulted.

    Returns (verdicts, complaints):

    - verdicts is [(index, verdict, reason)] for the checks the list speaks
      to, where verdict is KNOWN for a fault that is still what it was
      recorded as, and FAIL for one that has got worse than its ceiling;
    - complaints is [(entry, reason)] for entries this run refutes - a check
      that now passes, one that was skipped, one the run never made.  Each
      is a build failure: the list is only useful while it is true.
    """
    mine = for_capture(entries, capture)
    by_key = {}
    for entry in mine:
        by_key.setdefault(_entry_key(entry), []).append(entry)

    verdicts = []
    complaints = []
    seen = set()
    for index, record in enumerate(records):
        key = _key(record)
        matches = by_key.get(key)
        if not matches:
            continue
        seen.add(key)
        entry = matches[0]
        if len(matches) > 1:
            # Two entries for one measurement means one of them is wrong and
            # neither can be trusted to be the one that gets deleted.
            complaints.append((entry, (
                f"listed {len(matches)} times for the same measurement "
                f"({entry.get('check')}); keep one")))
            continue
        verdict = record.get("verdict")
        if verdict == "PASS":
            complaints.append((entry, (
                f"recorded as a known deviation, and this run passes it "
                f"({record.get('id')}); delete the entry")))
            continue
        if verdict != "FAIL":
            complaints.append((entry, (
                f"recorded as a known deviation, and this run did not judge "
                f"it ({record.get('id')}: {verdict})")))
            continue
        ceiling = entry.get("ceiling")
        used = band_used(record)
        if ceiling is not None and used is not None and used > ceiling:
            verdicts.append((index, "FAIL", (
                f"known deviation, worse than recorded: {used:.2f}x of its "
                f"band against a ceiling of {ceiling:.2f}x")))
            continue
        reason = entry.get("reason", "")
        owner = entry.get("owner")
        if owner:
            reason = f"{reason} -- owned by {owner}" if reason else owner
        verdicts.append((index, "KNOWN", reason))

    for entry in mine:
        if _entry_key(entry) not in seen:
            complaints.append((entry, (
                f"recorded as a known deviation, and this run makes no such "
                f"check ({entry.get('check')})")))
    return verdicts, complaints
