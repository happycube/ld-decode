#!/usr/bin/env python3
"""
burst_metrics - per-field colour burst metrics from CombNTSC comb analysis

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Reports line 19 burst level, phase and SNR for every field, in both 1D
(single field) and 3D (inter-frame) comb modes, plus the median burst phase
across the active lines and the 3D burst cancellation residue.

Reads whatever video_common.load_video() accepts: a .cvbs/.composite file with
its .meta sidecar, in either 4fsc sample encoding, or a legacy .tbc with its
.tbc.db.  Loading, capture parameters and the field objects all come from
video_common, so this measures the same field data, through the same code path,
as differential_phase.py and the rest of the analysis oracles.

NTSC only: the metrics come from lddecode.metrics.CombNTSC, which is an NTSC
comb filter.  PAL captures are rejected rather than silently mismeasured.

Usage:
    python analysis/burst_metrics.py file.cvbs
    python analysis/burst_metrics.py file.tbc -n 20
"""

import argparse
import os
import sys

import numpy as np

# Allow running from the analysis/ directory or the project root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lddecode.dsp import rms
from lddecode.metrics import CombNTSC
from video_common import load_video

# Line 19 colour burst window, measured from the start of the line: the line
# sync is 4.7 us and the 4fsc line convention puts 0H at +0.8 us.
BURST_LINE = 19
BURST_START_US = 4.7 + 0.8
BURST_DURATION_US = 2.4

# Amplitude below which a line's burst phase is undefined rather than weak.
# This is a divide-by-zero guard on arctan2, not a level gate: against a
# nominal burst it is negligible in either sample domain (about 0.0003 IRE on
# a 16-bit .tbc, 0.018 IRE on a 10-bit .cvbs), so it only rejects lines with
# no subcarrier at all.
PHASE_DEFINED_MIN_AMP = 0.1


def calc_median_burst_phase(comb, params):
    """Median colour burst phase across the active lines, in degrees."""
    burst_start_iq = params.colour_burst_start // 2
    burst_end_iq = params.colour_burst_end // 2
    f = comb.field

    phases = []
    for line in range(20, params.field_height - 3):
        sl = f.lineslice_tbc(line, 0, 10)
        si, sq = comb.splitIQ_line(line, sl)

        bsl = slice(burst_start_iq, burst_end_iq)
        mean_i = np.mean(si[bsl])
        mean_q = np.mean(sq[bsl])

        amp = np.sqrt(mean_i**2 + mean_q**2)
        if amp < PHASE_DEFINED_MIN_AMP:
            continue

        phase = np.arctan2(mean_i, mean_q) * 180 / np.pi
        if phase < 0:
            phase += 360
        phases.append(phase)

    return np.median(phases) if phases else None


def measure_burst(field):
    """RMS of the line 19 burst window, scaled by the capture's out_scale.

    Taken over the samples as stored rather than about blanking, which is the
    same quantity lddecode.metrics reports for palVITSBurst50Level.  Both the
    RMS and out_scale scale with the sample domain, so the ratio is the same
    for a .tbc and a .cvbs of one decode.
    """
    sl = field.lineslice_tbc(BURST_LINE, BURST_START_US, BURST_DURATION_US)
    data = field.dspicture[sl].astype(np.float64)
    return rms(data) / field.out_scale


def measure_burst_3d(field, prev_field):
    """3D burst-zero level: the residue left by inter-frame cancellation.

    Differencing two same-parity fields removes the pedestal, so unlike
    measure_burst() this is a pure a.c. measurement.
    """
    sl = field.lineslice_tbc(BURST_LINE, BURST_START_US, BURST_DURATION_US)
    diff = (
        field.dspicture[sl].astype(np.float64)
        - prev_field.dspicture[sl].astype(np.float64)
    ) / 2
    return np.sqrt(2) * rms(diff) / field.out_scale


def format_row(field, mode, level, phase, snr, burst_rms=None, burst0=None,
               med_phase=None):
    """Format a single results row."""
    first = "yes" if field.isFirstField else "no"

    def fmt(val, width, decimals):
        if val is not None:
            return f"{val:>{width}.{decimals}f}"
        return f"{'---':>{width}}"

    return (
        f"{field.field_id:>5}  {first:>4}  {field.fieldPhaseID:>5}  "
        f"{mode:>4}  {fmt(level, 8, 4)}  {fmt(phase, 7, 2)}  {fmt(snr, 7, 2)}  "
        f"{fmt(burst_rms, 8, 4)}  {fmt(burst0, 8, 4)}  {fmt(med_phase, 8, 2)}"
    )


def run_analysis(path, max_fields=None, verbose=False):
    """Report CombNTSC burst metrics for a .cvbs or .tbc file."""
    try:
        params, fields, _ = load_video(path, max_fields=max_fields)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if params.system != "NTSC":
        print(f"Error: CombNTSC analysis only supports NTSC (got {params.system})",
              file=sys.stderr)
        return 1

    if not fields:
        print(f"Error: no fields found in {path}", file=sys.stderr)
        return 1

    if verbose:
        print(f"Capture: {params!r}")
        if params.sample_encoding:
            print(f"Sample encoding: {params.sample_encoding}")
        print(f"Fields loaded: {len(fields)}")

    print(f"{'Field':>5}  {'1st?':>4}  {'Phase':>5}  {'Mode':>4}  "
          f"{'Burst70':>8}  {'Phase':>7}  {'SNR_dB':>7}  "
          f"{'BurstRMS':>8}  {'Burst0':>8}  {'MedPhase':>8}")
    print("-" * 90)

    for i, f in enumerate(fields):
        # 1D analysis: single field.
        c1d = CombNTSC([f])
        level_1d, phase_1d, snr_1d = c1d.calcLine19Info()
        burst_rms = measure_burst(f)
        med_phase_1d = calc_median_burst_phase(c1d, params)

        print(format_row(f, "1D", level_1d, phase_1d, snr_1d,
                         burst_rms, med_phase=med_phase_1d))

        # 3D analysis: needs the same-parity field of the previous frame,
        # which is two fields back.
        if i >= 2:
            prev = fields[i - 2]
            if prev.isFirstField == f.isFirstField:
                c3d = CombNTSC([prev, f])
                level_3d, phase_3d, snr_3d = c3d.calcLine19Info()
                burst0 = measure_burst_3d(f, prev)
                med_phase_3d = calc_median_burst_phase(c3d, params)

                print(format_row(f, "3D", level_3d, phase_3d, snr_3d,
                                 burst_rms, burst0, med_phase_3d))

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Report per-field colour burst metrics using the "
                    "CombNTSC comb filter (NTSC only)."
    )
    parser.add_argument(
        "video_file",
        help="Path to a .cvbs/.composite file (companion .meta must exist) "
             "or a legacy .tbc (companion .tbc.db must exist)",
    )
    parser.add_argument(
        "-n", "--max-fields",
        type=int,
        default=None,
        help="Maximum number of fields to analyse",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print additional diagnostic information",
    )

    args = parser.parse_args()
    sys.exit(run_analysis(args.video_file, args.max_fields, args.verbose))


if __name__ == "__main__":
    main()
