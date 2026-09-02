#!/usr/bin/env python3
"""
efm_quality - score a .efm T-value stream against frame-sync thresholds

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

CTest oracle for the RF -> .efm path: reads a ``.efm`` file (int8 T-values,
the same byte stream in both TBC and CVBS output modes) and an optional
``.efmc`` confidence sidecar (uint8, 1:1 with the T-values), scores it with
lddecode.efm_score, prints a machine-parseable summary, and judges the
scores against thresholds given on the command line.

The final line is exactly one of

    EFM QUALITY: PASS (...)
    EFM QUALITY: FAIL (...)

matching the convention analysis/cvbs_verify.py uses, so a CTest entry can
gate on it with PASS_REGULAR_EXPRESSION "EFM QUALITY: PASS".  With no
threshold flags the run is informational and always passes.  --json writes
the same numbers as a sidecar for CI artefact upload.

Thresholds are per capture, set at measured current performance so the gate
fails on regression (see docs/technical/efm-decoding.md for the baseline
table).  In particular the BBC Domesday / AIV discs interleave EFM sections
with analogue-audio or silent gaps, so their whole-capture sync rate is
bounded below 1.0 by the disc layout itself - their thresholds encode the
capture's own baseline, not an absolute standard.

Usage:
    efm_quality.py capture.efm [--efmc capture.efmc]
        [--min-sync-rate F] [--min-frame-588 F] [--max-invalid-t F]
        [--min-t-values N] [--json out.json]
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lddecode.efm_score import (  # noqa: E402
    frame_length_error_counts,
    score_t_values,
    summarise_confidence,
    symbol_separation,
)

# Frame-length errors are reported individually up to this magnitude in
# channel bits; anything larger (multi-frame gaps, dropouts, disc layout
# gaps) is pooled so the summary stays a fixed, parseable size.
ERROR_DETAIL_LIMIT = 10


def load_t_values(path):
    """Read a .efm file as int8 T-values (returns a fresh array)."""
    return np.fromfile(path, dtype=np.int8)


def load_confidence(path):
    """Read a .efmc file as uint8 confidence values (returns a fresh array)."""
    return np.fromfile(path, dtype=np.uint8)


def summarise_separation(prefm_path, sample_rate_hz):
    """Waveform-domain symbol separation of a .prefm file, as report rows.

    Informational (no threshold): the RMS distance of the filtered EFM
    waveform's zero-crossing intervals from the legal T3-T11 grid, the
    front-end filter comparison metric (museld's eval_efm_fir_filter idea).
    """
    waveform = np.fromfile(prefm_path, dtype=np.int16)
    sep = symbol_separation(waveform, sample_rate_hz)
    return {
        "separation_intervals": sep.n_intervals,
        "separation_bit_period": round(sep.bit_period, 4),
        "separation_rms_bits": round(sep.rms_bits, 6),
        "separation_worst_bits": round(sep.worst_bits, 4),
    }


def summarise(score, confidence_summary=None):
    """The report as an ordered {key: number} dict (JSON- and print-ready)."""
    out = {
        "t_values": score.n_t_values,
        "channel_bits": score.channel_bits,
        "expected_frames": round(score.expected_frames, 3),
        "sync_pairs": score.n_sync_pairs,
        "sync_rate": round(score.sync_rate, 6),
        "gaps": score.n_gaps,
        "frames_588": score.n_frames_588,
        "frame_588_fraction": round(score.frame_588_fraction, 6),
        "invalid_t_fraction": round(score.invalid_t_fraction, 6),
    }
    for t in range(len(score.t_counts)):
        if score.t_counts[t]:
            out[f"t_hist[{t}]"] = int(score.t_counts[t])
    if score.n_t_out_of_histogram:
        out["t_hist[other]"] = score.n_t_out_of_histogram

    errors, counts = frame_length_error_counts(score.gap_bits)
    small = np.abs(errors) <= ERROR_DETAIL_LIMIT
    for err, cnt in zip(errors[small], counts[small]):
        out[f"frame_error[{err:+d}]"] = int(cnt)
    if np.any(~small):
        out["frame_error[large]"] = int(counts[~small].sum())

    if confidence_summary is not None:
        out["confidence_values"] = confidence_summary.n_values
        out["confidence_mean"] = round(confidence_summary.mean, 2)
        out["confidence_low_fraction"] = round(confidence_summary.fraction_low, 6)
    return out


def judge(score, args):
    """Apply the command-line thresholds; returns a list of failure strings."""
    failures = []
    if args.min_t_values is not None and score.n_t_values < args.min_t_values:
        failures.append(f"t_values {score.n_t_values} < {args.min_t_values}")
    if args.min_sync_rate is not None and score.sync_rate < args.min_sync_rate:
        failures.append(f"sync_rate {score.sync_rate:.6f} < {args.min_sync_rate}")
    if args.min_frame_588 is not None and score.frame_588_fraction < args.min_frame_588:
        failures.append(f"frame_588_fraction {score.frame_588_fraction:.6f} < {args.min_frame_588}")
    if args.max_invalid_t is not None and score.invalid_t_fraction > args.max_invalid_t:
        failures.append(f"invalid_t_fraction {score.invalid_t_fraction:.6f} > {args.max_invalid_t}")
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Score a .efm T-value stream against frame-sync thresholds"
    )
    parser.add_argument("efm", help="path to the .efm file (int8 T-values)")
    parser.add_argument(
        "--efmc",
        help="path to the .efmc confidence sidecar (uint8, 1:1 with the T-values)",
    )
    parser.add_argument(
        "--min-sync-rate",
        type=float,
        help="fail if sync_rate (T11-T11 pairs per 588 channel bits) is below this",
    )
    parser.add_argument(
        "--min-frame-588",
        type=float,
        help="fail if the fraction of exactly-588-bit inter-sync gaps is below this",
    )
    parser.add_argument(
        "--max-invalid-t",
        type=float,
        help="fail if the fraction of T-values outside 3..11 is above this",
    )
    parser.add_argument(
        "--min-t-values",
        type=int,
        help="fail if the stream carries fewer T-values than this "
        "(catches a truncated or missing EFM decode)",
    )
    parser.add_argument(
        "--prefm",
        help="path to a .prefm file (int16 filtered EFM waveform): adds the "
        "waveform-domain symbol-separation metric to the summary "
        "(informational, no threshold)",
    )
    parser.add_argument(
        "--sample-rate",
        type=float,
        default=40e6,
        help="sample rate of the .prefm waveform in Hz (default 40e6)",
    )
    parser.add_argument("--json", help="write the summary to this path as JSON")
    args = parser.parse_args(argv)

    print(f"EFM quality: {args.efm}")
    if not os.path.exists(args.efm):
        print(f"EFM QUALITY: FAIL (no such file: {args.efm})")
        return 1

    score = score_t_values(load_t_values(args.efm))

    confidence_summary = None
    if args.efmc:
        confidence = load_confidence(args.efmc)
        confidence_summary = summarise_confidence(confidence)
        if confidence.size != score.n_t_values:
            print(
                f"EFM QUALITY: FAIL (.efmc carries {confidence.size} values "
                f"for {score.n_t_values} T-values; must be 1:1)"
            )
            return 1

    report = summarise(score, confidence_summary)
    if args.prefm:
        report.update(summarise_separation(args.prefm, args.sample_rate))
    width = max(len(k) for k in report)
    for key, value in report.items():
        print(f"  {key:<{width}}  {value}")

    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2)
            f.write("\n")

    failures = judge(score, args)
    if failures:
        print(f"EFM QUALITY: FAIL ({'; '.join(failures)})")
        return 1

    thresholds_applied = sum(
        x is not None
        for x in (
            args.min_sync_rate,
            args.min_frame_588,
            args.max_invalid_t,
            args.min_t_values,
        )
    )
    print(f"EFM QUALITY: PASS ({thresholds_applied} thresholds checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
