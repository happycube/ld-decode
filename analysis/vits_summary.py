#!/usr/bin/env python3
"""
vits_summary - a CI-readable table of what a VITS conformance run measured

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

analysis/vits_conformance.py writes one JSON sidecar per capture it judges.
Across the radius sweep that is thirteen files and some six hundred checks,
which is a log nobody reads: the run goes red and the next question - which
capture, which check, how far out, and out of what band - costs a download
and a text search to answer.

This renders those sidecars as GitHub-flavoured Markdown for
$GITHUB_STEP_SUMMARY.  One row per capture gives the totals and the verdict;
one row per *failing* check gives the measurement, the band it had to sit in
and the clause it was judged under.  Passing checks are counted, not listed,
because a table of six hundred rows is the log again.

Nothing here opens a file except load_reports and main, so the table can be
unit tested on its own (AGENTS.md 4.2).
"""

import argparse
import json
import math
import os
import sys

from vits_deviations import band_used, capture_name

__all__ = [
    "capture_rows",
    "failure_rows",
    "load_reports",
    "render_summary",
]


def _capture_name(payload):
    """The capture a report describes, as the manifest labels it."""
    path = (payload.get("context") or {}).get("path") or ""
    return capture_name(path) or "(unnamed)"


def _verdict(summary):
    """The one word a capture's totals amount to."""
    if summary.get("failed"):
        return "FAIL"
    if not (summary.get("passed") or summary.get("known")):
        # Nothing judged at all: the manifest says this capture carries none
        # of the signals, so nothing was proved and a "PASS" here would read
        # as a clean bill on checks that were never attempted.
        return "SKIPPED"
    return "PASS"


def capture_rows(payloads):
    """One row each: capture, system, fields, the four counts, and a verdict.

    "Known" is kept in its own column rather than folded into the passes: a
    fault the build has agreed to carry is not a fault that went away, and
    the column is the number that should be shrinking.
    """
    rows = []
    for payload in payloads:
        context = payload.get("context") or {}
        summary = payload.get("summary") or {}
        rows.append((
            _capture_name(payload),
            context.get("system", "?"),
            context.get("fields", 0),
            summary.get("passed", 0),
            summary.get("failed", 0),
            summary.get("known", 0),
            summary.get("skipped", 0),
            _verdict(summary),
        ))
    return rows


def _measured(check):
    """The measurement as text, in the check's own unit."""
    value = check.get("measured")
    if value is None or not math.isfinite(value):
        return check.get("reason") or "not measurable"
    return f"{value:.3f} {check.get('unit', '')}".strip()


def _against(check):
    """What the measurement was held to: a nominal and band, or a limit."""
    band = check.get("band")
    nominal = check.get("nominal")
    limit = check.get("limit")
    if nominal is not None and band is not None:
        return f"{nominal:.3f} +/-{band:.3f}"
    if limit is not None:
        return f"limit {limit:.3f}"
    return "-"


def _band_used(check):
    """How much of what it was allowed the check used, as text."""
    used = band_used(check)
    return "-" if used is None else f"{used:.2f}x"


def failure_rows(payloads):
    """One row per failing check, across every report given."""
    rows = []
    for payload in payloads:
        capture = _capture_name(payload)
        for check in payload.get("checks") or ():
            if check.get("verdict") != "FAIL":
                continue
            line = check.get("field_line")
            rows.append((
                capture,
                check.get("id", "?"),
                "-" if line is None else str(line),
                _measured(check),
                _against(check),
                _band_used(check),
                check.get("clause", ""),
            ))
    return rows


def _table(headers, rows):
    """A Markdown table; the header alone if there are no rows."""
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    out.extend("| " + " | ".join(str(cell) for cell in row) + " |"
               for row in rows)
    return "\n".join(out)


def render_summary(payloads):
    """The whole step summary as Markdown."""
    captures = capture_rows(payloads)
    failures = failure_rows(payloads)
    failed_captures = sum(1 for row in captures if row[-1] == "FAIL")
    carried = sum(row[5] for row in captures)

    lines = ["## VITS conformance", ""]
    if failed_captures:
        lines.append(f"**{len(failures)} checks failed across "
                     f"{failed_captures} of {len(captures)} captures.**")
    else:
        lines.append(f"**{len(captures)} captures, no failing checks.**")
    if carried:
        lines.append(f"{carried} known deviations were carried; they are"
                     " listed in `analysis/vits_known_deviations.toml`.")
    lines.extend([
        "",
        _table(("Capture", "System", "Fields", "Passed", "Failed", "Known",
                "Skipped", "Verdict"), captures),
        "",
    ])
    if failures:
        lines.extend([
            "### Failing checks",
            "",
            "`Band used` is how much of the check's allowed band the"
            " deviation spent; 1.00x sits exactly on the limit.",
            "",
            _table(("Capture", "Check", "Line", "Measured", "Against",
                    "Band used", "Clause"), failures),
            "",
        ])
    return "\n".join(lines)


def load_reports(paths):
    """Read the JSON sidecars at `paths`, in the order given."""
    payloads = []
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            payloads.append(json.load(handle))
    return payloads


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=("Render vits_conformance.py JSON sidecars as a Markdown"
                     " summary"))
    parser.add_argument("reports", nargs="+",
                        help="the .conformance.json files to summarise")
    parser.add_argument("--output", default=None,
                        help="write here instead of stdout (appends, so "
                             "$GITHUB_STEP_SUMMARY can be given directly)")
    args = parser.parse_args(argv)

    text = render_summary(load_reports(sorted(args.reports)))
    if args.output:
        with open(args.output, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
