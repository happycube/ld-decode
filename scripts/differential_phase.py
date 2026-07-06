#!/usr/bin/env python3
"""Differential phase measurement: chroma phase vs luminance level in TBC output.

Measures the relationship between luminance (IRE) and chroma phase across the
TBC output to characterize differential phase distortion.

Test patterns are auto-detected and only the analyses whose patterns are
present are run.

NTSC (CombNTSC 1D/3D comb demodulation):
  - Color burst region on every active line: phase at ~0 IRE
  - Line 19 VITS: 70 IRE color bar with chroma
  - Line 20 staircase: chroma at 18/36/54/73/91 IRE (first fields only -
    second fields have different content at the same line number)

PAL (burst-relative fs/4 quadrature demodulation):
  - CCIR ITS line (usually field line 19 on second fields): subcarrier
    packet at blanking level plus a 5-step staircase with subcarrier,
    giving six phase-vs-IRE points on a single line
  - Differential gain from the same regions
  - 50% luma full-line subcarrier reference (line 331 style) if present

Usage:
    python scripts/differential_phase.py [file.tbc | file.composite]
"""

import argparse
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from lddecode.metrics import CombNTSC
from tbc_common import (
    load_tbc, load_cvbs, detect_patterns, summarize_patterns,
    burst_ref, demod_region, phase_diff,
    NTC7_MULTIBURST_FREQS, NTC7_PEDESTAL_PP,
    measure_ntc7_transients, measure_pal_its_transients,
    weighted_psnr, chroma_am_pm_noise, line_segment_ire,
)


# ---------------------------------------------------------------------------
# NTSC phase measurement helpers (CombNTSC-based)
# ---------------------------------------------------------------------------

def measure_phase_at_position(comb, line, start_us, duration_us, params):
    """Demodulate chroma at a specific position and return (phase_deg, amplitude, luma_ire).

    Returns (None, None, None) if chroma amplitude is too low to measure.
    """
    f = comb.field

    # IQ demodulation: take a slice from line start to beyond our region
    end_us = start_us + duration_us
    full_sl = f.lineslice_tbc(line, 0, end_us + 2)
    si, sq = comb.splitIQ_line(line, full_sl)

    # Convert to IQ-sample indices (IQ samples are at half TBC rate)
    sr = params.sample_rate_mhz
    iq_start = int(start_us * sr) // 2
    iq_end = int(end_us * sr) // 2

    si_region = si[iq_start:iq_end]
    sq_region = sq[iq_start:iq_end]

    if len(si_region) < 2:
        return None, None, None

    mean_i = np.mean(si_region)
    mean_q = np.mean(sq_region)
    amp = np.sqrt(mean_i**2 + mean_q**2)

    # Measure luminance at the same position
    luma_sl = f.lineslice_tbc(line, start_us, duration_us)
    luma_ire = np.mean(f.output_to_ire(f.dspicture[luma_sl]))

    if amp < 500:  # threshold for meaningful chroma
        return None, amp, luma_ire

    phase = np.arctan2(mean_i, mean_q) * 180 / np.pi
    if phase < 0:
        phase += 360

    return phase, amp, luma_ire


def measure_burst_phase(comb, line, params):
    """Measure color burst phase and amplitude on a given line."""
    return measure_phase_at_position(comb, line, 5.3, 2.5, params)


# ---------------------------------------------------------------------------
# NTSC analysis routines
# ---------------------------------------------------------------------------

def analyze_burst_all_lines(comb, params, lines=None):
    """Measure burst phase on all active lines.  Returns list of (line, phase, amp, ire)."""
    if lines is None:
        lines = range(20, min(261, params.field_height - 2))
    results = []
    for line in lines:
        phase, amp, ire = measure_burst_phase(comb, line, params)
        if phase is not None:
            results.append((line, phase, amp, ire))
    return results


def analyze_line19(comb, params):
    """Measure phase at burst and at the 70 IRE color bar on line 19."""
    results = []

    # Burst (0 IRE region)
    phase, amp, ire = measure_burst_phase(comb, 19, params)
    if phase is not None:
        results.append(("L19 burst", ire, phase, amp))

    # 70 IRE color bar region: 13-34 us (stable chroma)
    for label, us_start, us_dur in [
        ("L19 bar-start", 13.0, 2.0),
        ("L19 bar-mid",   20.0, 2.0),
        ("L19 bar-end",   28.0, 2.0),
    ]:
        phase, amp, ire = measure_phase_at_position(comb, 19, us_start, us_dur, params)
        if phase is not None:
            results.append((label, ire, phase, amp))

    return results


def analyze_line20_staircase(comb, params):
    """Measure phase at each step of the line 20 staircase.

    Line 20 has chroma-bearing staircase steps at approximately:
      46-48.5 us: ~18 IRE
      49-51.5 us: ~36 IRE
      52-54   us: ~54 IRE
      55-57   us: ~73 IRE
      58-60   us: ~91 IRE
    Plus burst at ~0 IRE.
    """
    results = []

    # Burst
    phase, amp, ire = measure_burst_phase(comb, 20, params)
    if phase is not None:
        results.append(("L20 burst", ire, phase, amp))

    # Staircase steps (use center of each step, ~1.5 us window)
    steps = [
        ("L20 step ~18 IRE", 46.5, 1.5),
        ("L20 step ~36 IRE", 49.5, 1.5),
        ("L20 step ~54 IRE", 52.5, 1.5),
        ("L20 step ~73 IRE", 55.5, 1.5),
        ("L20 step ~91 IRE", 58.5, 1.5),
    ]
    for label, us_start, us_dur in steps:
        phase, amp, ire = measure_phase_at_position(comb, 20, us_start, us_dur, params)
        if phase is not None:
            results.append((label, ire, phase, amp))

    return results


def analyze_line19_transition(comb, params):
    """Measure phase across the 0->70 IRE transition on line 19 (~12-13 us)."""
    results = []
    for us_pos in np.arange(10.0, 14.0, 0.3):
        phase, amp, ire = measure_phase_at_position(comb, 19, us_pos, 0.5, params)
        if phase is not None:
            results.append((f"L19 @{us_pos:.1f}us", ire, phase, amp))
    return results


def print_section(num, title):
    print("=" * 90)
    print(f"{num}. {title}")
    print("=" * 90)


def print_skipped(num, title, reason):
    print_section(num, title)
    print(f"  SKIPPED - {reason}")
    print()


# ---------------------------------------------------------------------------
# NTSC report
# ---------------------------------------------------------------------------

def ntsc_report(params, fields, det):
    l19_idx = det["ntsc_line19_vits"]
    l20_idx = sorted(i for i, v in det["ntsc_line20_staircase"].items()
                     if v["has_chroma"])
    l19_fields = [fields[i] for i in l19_idx]
    l20_fields = [fields[i] for i in l20_idx]

    # -----------------------------------------------------------------------
    # 1. Burst phase consistency across all active lines (first field, 1D)
    # -----------------------------------------------------------------------
    print_section(1, "BURST PHASE ACROSS ALL ACTIVE LINES (Field 0, 1D comb)")

    c1d_f0 = CombNTSC([fields[0]])
    burst_results = analyze_burst_all_lines(c1d_f0, params)

    print(f"{'Line':>5}  {'Phase':>8}  {'Amplitude':>10}  {'IRE':>7}")
    print("-" * 35)
    phases_burst = []
    for line, phase, amp, ire in burst_results:
        phases_burst.append(phase)
        if line <= 25 or line >= 255 or line % 20 == 0:
            print(f"{line:>5}  {phase:>8.2f}  {amp:>10.1f}  {ire:>7.1f}")
    print("...")
    print(f"  Burst phase: mean={np.mean(phases_burst):.2f}, "
          f"std={np.std(phases_burst):.2f}, "
          f"min={np.min(phases_burst):.2f}, max={np.max(phases_burst):.2f}")
    print(f"  Measured on {len(phases_burst)} lines")
    print()

    # -----------------------------------------------------------------------
    # 2 & 3. Line 19 analysis
    # -----------------------------------------------------------------------
    if not l19_fields:
        print_skipped(2, "LINE 19 ANALYSIS", "line 19 VITS not detected")
        print_skipped(3, "LINE 19 TRANSITION REGION", "line 19 VITS not detected")
    else:
        print_section(2, "LINE 19 ANALYSIS: BURST (0 IRE) vs 70 IRE COLOR BAR (1D comb)")

        c1d_l19 = CombNTSC([l19_fields[0]])
        l19_results = analyze_line19(c1d_l19, params)
        print(f"{'Region':>20}  {'IRE':>7}  {'Phase':>8}  {'Amplitude':>10}")
        print("-" * 50)
        for label, ire, phase, amp in l19_results:
            print(f"{label:>20}  {ire:>7.1f}  {phase:>8.2f}  {amp:>10.1f}")

        if len(l19_results) >= 2:
            burst_phase = l19_results[0][2]
            bar_phases = [r[2] for r in l19_results[1:]]
            bar_phase = np.mean(bar_phases)
            burst_ire = l19_results[0][1]
            bar_ire = np.mean([r[1] for r in l19_results[1:]])
            dp = bar_phase - burst_phase
            dp_per_ire = dp / (bar_ire - burst_ire) if abs(bar_ire - burst_ire) > 0.1 else float('nan')
            print(f"\n  Differential phase (burst->bar): {dp:+.2f} deg over "
                  f"{bar_ire - burst_ire:.1f} IRE = {dp_per_ire:.4f} deg/IRE")
        print()

        print_section(3, "LINE 19 TRANSITION REGION (0 -> 70 IRE)")

        trans_results = analyze_line19_transition(c1d_l19, params)
        print(f"{'Position':>15}  {'IRE':>7}  {'Phase':>8}  {'Amplitude':>10}")
        print("-" * 45)
        for label, ire, phase, amp in trans_results:
            print(f"{label:>15}  {ire:>7.1f}  {phase:>8.2f}  {amp:>10.1f}")
        print()

    # -----------------------------------------------------------------------
    # 4. Line 20 staircase: phase at 5 IRE levels
    # -----------------------------------------------------------------------
    if not l20_fields:
        print_skipped(4, "LINE 20 STAIRCASE", "line 20 staircase with chroma not detected")
    else:
        print_section(4, "LINE 20 STAIRCASE: PHASE AT MULTIPLE LUMINANCE LEVELS\n"
                         f"   (Field {l20_fields[0].field_id}, 1D comb)")

        c1d_l20 = CombNTSC([l20_fields[0]])
        l20_results = analyze_line20_staircase(c1d_l20, params)
        print(f"{'Region':>25}  {'IRE':>7}  {'Phase':>8}  {'Amplitude':>10}")
        print("-" * 55)
        for label, ire, phase, amp in l20_results:
            print(f"{label:>25}  {ire:>7.1f}  {phase:>8.2f}  {amp:>10.1f}")

        if len(l20_results) >= 2:
            ires_l20 = np.array([r[1] for r in l20_results])
            phases_l20 = np.array([r[2] for r in l20_results])

            # Linear regression: phase = a * IRE + b
            A = np.vstack([ires_l20, np.ones(len(ires_l20))]).T
            slope, intercept = np.linalg.lstsq(A, phases_l20, rcond=None)[0]

            print(f"\n  Linear fit: phase = {slope:.4f} * IRE + {intercept:.2f}")
            print(f"  Differential phase slope: {slope:.4f} deg/IRE")
            print(f"  Over full range ({ires_l20.min():.0f} to {ires_l20.max():.0f} IRE): "
                  f"{slope * (ires_l20.max() - ires_l20.min()):.2f} deg total")

            # Residuals to check linearity
            predicted = slope * ires_l20 + intercept
            residuals = phases_l20 - predicted
            print(f"\n  Residuals (phase_measured - phase_linear_fit):")
            for i, r in enumerate(l20_results):
                print(f"    {r[0]:>25}: {r[1]:>6.1f} IRE  residual = {residuals[i]:+.3f} deg")
            print(f"  RMS residual: {np.sqrt(np.mean(residuals**2)):.3f} deg")

            # Quadratic fit for curvature detection
            if len(l20_results) >= 3:
                coeffs = np.polyfit(ires_l20, phases_l20, 2)
                print(f"\n  Quadratic fit: phase = {coeffs[0]:.6f}*IRE^2 + {coeffs[1]:.4f}*IRE + {coeffs[2]:.2f}")
                pred_q = np.polyval(coeffs, ires_l20)
                res_q = phases_l20 - pred_q
                print(f"  Quadratic RMS residual: {np.sqrt(np.mean(res_q**2)):.3f} deg")
                if abs(coeffs[0]) > 1e-5:
                    print(f"  Curvature coefficient: {coeffs[0]:.6f} deg/IRE^2 "
                          f"({'convex' if coeffs[0] > 0 else 'concave'})")
                else:
                    print(f"  Curvature coefficient: {coeffs[0]:.6f} deg/IRE^2 (effectively linear)")
        print()

    # -----------------------------------------------------------------------
    # 5. Per-field variation
    # -----------------------------------------------------------------------
    print_section(5, "PER-FIELD VARIATION (1D comb)")

    # --- L19 across detected fields ---
    if l19_fields:
        print(f"\n  5a. Line 19 differential phase (burst vs 70 IRE bar):")
        print(f"  {'Field':>5}  {'PhID':>4}  {'1st?':>4}  {'BurstPh':>8}  {'BarPh':>8}  {'DP':>8}")
        print("  " + "-" * 45)

        field_dps_l19 = []
        for f in l19_fields[:10]:
            c = CombNTSC([f])
            burst_ph, _, burst_ire = measure_burst_phase(c, 19, params)
            bar_ph, _, bar_ire = measure_phase_at_position(c, 19, 15.0, 15.0, params)
            dp = None
            if burst_ph is not None and bar_ph is not None:
                dp = bar_ph - burst_ph
                field_dps_l19.append(dp)
            first = "yes" if f.isFirstField else "no"
            fmt_v = lambda v: f"{v:>8.2f}" if v is not None else f"{'---':>8}"
            print(f"  {f.field_id:>5}  {f.fieldPhaseID:>4}  {first:>4}  "
                  f"{fmt_v(burst_ph)}  {fmt_v(bar_ph)}  {fmt_v(dp)}")

        if field_dps_l19:
            arr = np.array(field_dps_l19)
            print(f"\n  L19 DP: mean={np.mean(arr):+.2f}, std={np.std(arr):.2f}, "
                  f"range=[{np.min(arr):+.2f}, {np.max(arr):+.2f}]")
    else:
        print("\n  5a. Line 19: SKIPPED - not detected")

    # --- L20 staircase across detected fields ---
    field_l20_slopes = []
    if l20_fields:
        print(f"\n  5b. Line 20 staircase:")
        print(f"  {'Field':>5}  {'PhID':>4}  "
              f"{'Burst':>8}  {'~18':>8}  {'~36':>8}  {'~54':>8}  {'~73':>8}  {'~91':>8}  {'DP_18-91':>8}")
        print("  " + "-" * 75)

        for f in l20_fields[:5]:
            c = CombNTSC([f])
            l20 = analyze_line20_staircase(c, params)

            phases_by_label = {r[0]: r[2] for r in l20}

            cols = []
            for lbl in ["L20 burst", "L20 step ~18 IRE", "L20 step ~36 IRE",
                         "L20 step ~54 IRE", "L20 step ~73 IRE", "L20 step ~91 IRE"]:
                if lbl in phases_by_label:
                    cols.append(f"{phases_by_label[lbl]:>8.2f}")
                else:
                    cols.append(f"{'---':>8}")

            # DP from lowest to highest step
            dp = None
            if "L20 step ~18 IRE" in phases_by_label and "L20 step ~91 IRE" in phases_by_label:
                dp = phases_by_label["L20 step ~91 IRE"] - phases_by_label["L20 step ~18 IRE"]

            # Linear slope for this field
            if len(l20) >= 3:
                ires_f = np.array([r[1] for r in l20])
                phases_f = np.array([r[2] for r in l20])
                Af = np.vstack([ires_f, np.ones(len(ires_f))]).T
                slope_f, _ = np.linalg.lstsq(Af, phases_f, rcond=None)[0]
                field_l20_slopes.append(slope_f)

            dp_str = f"{dp:>8.2f}" if dp is not None else f"{'---':>8}"
            print(f"  {f.field_id:>5}  {f.fieldPhaseID:>4}  " + "  ".join(cols) + f"  {dp_str}")

        if field_l20_slopes:
            arr = np.array(field_l20_slopes)
            print(f"\n  L20 slope: mean={np.mean(arr):.4f}, std={np.std(arr):.4f} deg/IRE")
            print(f"  range=[{np.min(arr):.4f}, {np.max(arr):.4f}]")
    else:
        print("\n  5b. Line 20 staircase: SKIPPED - not detected")
    print()

    # -----------------------------------------------------------------------
    # 6. 1D vs 3D comb comparison
    # -----------------------------------------------------------------------
    if not l20_fields:
        print_skipped(6, "1D vs 3D COMB FILTER COMPARISON",
                      "line 20 staircase with chroma not detected")
    else:
        print_section(6, "1D vs 3D COMB FILTER COMPARISON (fields with staircase)")

        print(f"{'Field':>5}  {'Mode':>4}  {'Region':>25}  {'IRE':>7}  {'Phase':>8}  {'Amplitude':>10}")
        print("-" * 70)

        # Use detected fields that have a preceding same-parity field for 3D
        for f in l20_fields[:4]:
            # Find preceding same-parity field
            prev = None
            for pf in fields:
                if pf.field_index < f.field_index and pf.isFirstField == f.isFirstField:
                    prev = pf  # keep last one found

            c1d = CombNTSC([f])
            results_1d = analyze_line20_staircase(c1d, params)
            for label, ire, phase, amp in results_1d:
                print(f"{f.field_id:>5}  {'1D':>4}  {label:>25}  {ire:>7.1f}  {phase:>8.2f}  {amp:>10.1f}")

            if prev is not None:
                c3d = CombNTSC([prev, f])
                results_3d = analyze_line20_staircase(c3d, params)
                for label, ire, phase, amp in results_3d:
                    print(f"{f.field_id:>5}  {'3D':>4}  {label:>25}  {ire:>7.1f}  {phase:>8.2f}  {amp:>10.1f}")

                # Show differences
                if len(results_1d) == len(results_3d):
                    diffs = []
                    for r1, r3 in zip(results_1d, results_3d):
                        d = r3[2] - r1[2]
                        diffs.append(d)
                    print(f"  3D-1D phase differences: {['%+.2f' % d for d in diffs]}")

            # Also do L19 1D vs 3D
            if f.field_index in det["ntsc_line19_vits"] and prev is not None:
                l19_1d = analyze_line19(c1d, params)
                l19_3d = analyze_line19(CombNTSC([prev, f]), params)
                if len(l19_1d) > 1 and len(l19_3d) > 1:
                    print(f"  L19 1D burst={l19_1d[0][2]:.2f}, bar={np.mean([r[2] for r in l19_1d[1:]]):.2f}")
                    print(f"  L19 3D burst={l19_3d[0][2]:.2f}, bar={np.mean([r[2] for r in l19_3d[1:]]):.2f}")

            print()

    # -----------------------------------------------------------------------
    # 7. Comprehensive IRE vs phase table
    # -----------------------------------------------------------------------
    print_section(7, "COMPREHENSIVE IRE vs PHASE TABLE\n"
                     "   (averaged over detected fields, 1D comb)")

    all_ire_phase = []

    for f in l19_fields[:5]:
        c = CombNTSC([f])

        ph, amp, ire = measure_burst_phase(c, 19, params)
        if ph is not None:
            all_ire_phase.append((ire, ph, "L19 burst", f.field_id))

        ph, amp, ire = measure_phase_at_position(c, 19, 15.0, 15.0, params)
        if ph is not None:
            all_ire_phase.append((ire, ph, "L19 70IRE bar", f.field_id))

    for f in l20_fields[:5]:
        c = CombNTSC([f])

        ph, amp, ire = measure_burst_phase(c, 20, params)
        if ph is not None:
            all_ire_phase.append((ire, ph, "L20 burst", f.field_id))

        for label, us_start, us_dur in [
            ("L20 ~18", 46.5, 1.5),
            ("L20 ~36", 49.5, 1.5),
            ("L20 ~54", 52.5, 1.5),
            ("L20 ~73", 55.5, 1.5),
            ("L20 ~91", 58.5, 1.5),
        ]:
            ph, amp, ire = measure_phase_at_position(c, 20, us_start, us_dur, params)
            if ph is not None:
                all_ire_phase.append((ire, ph, label, f.field_id))

    # Group by source
    grouped = defaultdict(list)
    for ire, phase, src, fid in all_ire_phase:
        grouped[src].append((ire, phase))

    ordered_sources = ["L19 burst", "L20 burst", "L20 ~18", "L20 ~36",
                       "L20 ~54", "L19 70IRE bar", "L20 ~73", "L20 ~91"]

    print(f"\n{'Source':>20}  {'Mean IRE':>8}  {'Mean Phase':>10}  {'Std Phase':>9}  {'N':>3}")
    print("-" * 55)

    summary_points = []
    for src in ordered_sources:
        if src in grouped:
            ires = np.array([x[0] for x in grouped[src]])
            phases = np.array([x[1] for x in grouped[src]])
            mean_ire = np.mean(ires)
            mean_phase = np.mean(phases)
            std_phase = np.std(phases)
            print(f"{src:>20}  {mean_ire:>8.1f}  {mean_phase:>10.2f}  {std_phase:>9.3f}  {len(phases):>3}")
            summary_points.append((mean_ire, mean_phase, std_phase, src))

    # Sort by IRE for the final fit
    summary_points.sort(key=lambda x: x[0])

    print()

    # -----------------------------------------------------------------------
    # 8. Final characterization
    # -----------------------------------------------------------------------
    if len(summary_points) >= 3:
        ires_s = np.array([p[0] for p in summary_points])
        phases_s = np.array([p[1] for p in summary_points])

        # Linear fit
        A = np.vstack([ires_s, np.ones(len(ires_s))]).T
        slope, intercept = np.linalg.lstsq(A, phases_s, rcond=None)[0]

        # Quadratic fit
        coeffs2 = np.polyfit(ires_s, phases_s, 2)

        print_section(8, "FINAL DIFFERENTIAL PHASE CHARACTERIZATION")
        print(f"\n  Data points: {len(summary_points)} (sorted by IRE)")
        for i, sp in enumerate(summary_points):
            print(f"    {sp[3]:>20}: {sp[0]:>6.1f} IRE -> {sp[1]:>8.2f} deg "
                  f"(+/- {sp[2]:.3f})")

        print(f"\n  IRE range: {ires_s.min():.1f} to {ires_s.max():.1f}")
        print(f"  Phase range: {phases_s.min():.2f} to {phases_s.max():.2f} deg")
        print(f"\n  LINEAR FIT: phase = {slope:.4f} * IRE + {intercept:.2f}")
        print(f"  Differential phase slope: {slope:.4f} deg/IRE")
        print(f"  Total DP over 0-100 IRE (extrapolated): {slope * 100:.2f} deg")

        predicted = slope * ires_s + intercept
        residuals = phases_s - predicted
        rms_res = np.sqrt(np.mean(residuals**2))
        print(f"  RMS residual: {rms_res:.3f} deg")

        print(f"\n  QUADRATIC FIT: phase = {coeffs2[0]:.6f}*IRE^2 + {coeffs2[1]:.4f}*IRE + {coeffs2[2]:.2f}")
        pred_q = np.polyval(coeffs2, ires_s)
        res_q = phases_s - pred_q
        rms_q = np.sqrt(np.mean(res_q**2))
        print(f"  RMS residual: {rms_q:.3f} deg")
        print(f"  Curvature: {coeffs2[0]:.6f} deg/IRE^2 "
              f"({'convex' if coeffs2[0] > 0 else 'concave'})")

        print(f"\n  Residuals from linear fit:")
        for i, sp in enumerate(summary_points):
            print(f"    {sp[3]:>20} ({sp[0]:>5.1f} IRE): "
                  f"meas={sp[1]:.2f}, pred={predicted[i]:.2f}, "
                  f"res={residuals[i]:+.3f} deg")

        # Segment analysis: does the slope change at different IRE regions?
        if len(summary_points) >= 4:
            print(f"\n  SEGMENT ANALYSIS (point-to-point slopes):")
            for i in range(len(summary_points) - 1):
                ire1, ph1 = summary_points[i][0], summary_points[i][1]
                ire2, ph2 = summary_points[i+1][0], summary_points[i+1][1]
                if abs(ire2 - ire1) > 0.5:
                    seg_slope = (ph2 - ph1) / (ire2 - ire1)
                    print(f"    {summary_points[i][3]:>15} -> {summary_points[i+1][3]:>15}: "
                          f"{ire1:>5.1f}->{ire2:>5.1f} IRE  "
                          f"slope={seg_slope:+.4f} deg/IRE  "
                          f"delta={ph2-ph1:+.2f} deg")

        print_dp_interpretation(slope, rms_res, rms_q)
    else:
        print_skipped(8, "FINAL DIFFERENTIAL PHASE CHARACTERIZATION",
                      "not enough chroma-vs-IRE measurement points detected")

    # -----------------------------------------------------------------------
    # 9. Burst phase variation between fields
    # -----------------------------------------------------------------------
    print()
    print_section(9, "BURST PHASE VARIATION BETWEEN FIELDS")

    print(f"\n{'Field':>5}  {'PhID':>4}  {'1st?':>4}  {'MedBurstPh':>10}  {'StdBurstPh':>10}  {'N_lines':>7}")
    print("-" * 50)

    field_med_phases = []
    for f in fields[:10]:
        c = CombNTSC([f])
        burst_data = analyze_burst_all_lines(c, params)
        if burst_data:
            phases = [r[1] for r in burst_data]
            med = np.median(phases)
            std = np.std(phases)
            field_med_phases.append((f.field_id, f.fieldPhaseID, f.isFirstField, med, std, len(phases)))
            first = "yes" if f.isFirstField else "no"
            print(f"{f.field_id:>5}  {f.fieldPhaseID:>4}  {first:>4}  {med:>10.2f}  {std:>10.3f}  {len(phases):>7}")

    if field_med_phases:
        all_meds = [x[3] for x in field_med_phases]
        print(f"\n  Overall: mean={np.mean(all_meds):.2f}, std={np.std(all_meds):.3f}, "
              f"range=[{np.min(all_meds):.2f}, {np.max(all_meds):.2f}]")

        odd_phases = [x[3] for x in field_med_phases if x[2]]  # isFirstField
        even_phases = [x[3] for x in field_med_phases if not x[2]]
        if odd_phases and even_phases:
            print(f"  First fields: mean={np.mean(odd_phases):.2f}, std={np.std(odd_phases):.3f}")
            print(f"  Second fields: mean={np.mean(even_phases):.2f}, std={np.std(even_phases):.3f}")
    print()

    # -----------------------------------------------------------------------
    # 10 & 11. NTC-7 combination VITS (multiburst + modulated pedestal)
    # -----------------------------------------------------------------------
    ntc7_report(det, fields)

    # -----------------------------------------------------------------------
    # 12. NTC-7 composite: transient response / ringing
    # -----------------------------------------------------------------------
    transient_report(det, fields)

    # -----------------------------------------------------------------------
    # 13. Weighted SNR
    # -----------------------------------------------------------------------
    weighted_snr_report(det, fields)

    # -----------------------------------------------------------------------
    # 14. Chrominance AM/PM noise
    # -----------------------------------------------------------------------
    chroma_noise_report(det, fields)


def chroma_noise_report(det, fields):
    """Section 14: chrominance AM/PM noise from the line 19 SC region."""
    l19 = det.get("ntsc_line19_vits", [])
    if not l19:
        print_skipped(14, "CHROMINANCE AM/PM NOISE",
                      "line 19 modulated region not detected")
        return

    m = chroma_am_pm_noise([fields[i] for i in l19], 19, 15.0, 18.0)
    if m is None:
        print_skipped(14, "CHROMINANCE AM/PM NOISE",
                      "no usable subcarrier packet on line 19")
        return

    print_section(14, "CHROMINANCE AM/PM NOISE (line 19 modulated region, "
                      f"{m['n_fields']} fields)\n"
                      "   AM S/N = packet p-p vs rms envelope noise; "
                      "PM = rms phase noise")
    print(f"\n  Subcarrier packet: {m['sc_pp']:.1f} IRE p-p")
    print(f"\n{'Demod band':>22}  {'AM S/N':>8}  {'PM noise':>9}  {'PM S/N':>8}")
    print("-" * 54)
    for tag, label in (("band", "10-500 kHz (bcast)"), ("wide", "10 kHz-1.3 MHz")):
        am = m[f"am_snr_{tag}"]
        pm = m[f"pm_deg_{tag}"]
        pm_snr = 20 * np.log10(1.0 / np.radians(pm)) if pm > 0 else float("nan")
        am_s = f"{am:>7.2f}dB" if am is not None else f"{'—':>8}"
        print(f"{label:>22}  {am_s}  {pm:>8.3f}°  {pm_snr:>7.2f}dB")
    print("\n  (No CCIR weighting curve exists for chrominance; the 10-500 kHz")
    print("   demodulated band IS the broadcast 'weighted' convention.)")
    print()


def transient_report(det, fields):
    """Section 12: NTC-7 2T pulse / bar edge transient response."""
    comp_idx = sorted(det.get("ntsc_ntc7_composite", {}))
    if not comp_idx:
        print_skipped(12, "NTC-7 2T PULSE AND BAR EDGE (transient response)",
                      "NTC-7 composite VITS not detected")
        return

    m = measure_ntc7_transients([fields[i] for i in comp_idx])
    if m is None:
        print_skipped(12, "NTC-7 2T PULSE AND BAR EDGE (transient response)",
                      "could not resolve pulse/bar on the averaged line")
        return

    print_section(12, "NTC-7 2T PULSE AND BAR EDGE: TRANSIENT RESPONSE / RINGING\n"
                      f"   (line 20 averaged over {m['n_fields']} fields)")
    print(f"\n  Bar level:               {m['bar_ire']:.1f} IRE")
    print(f"  2T pulse-to-bar ratio:   {m['pulse_ratio']:.3f}  (ideal 1.0)")
    print(f"  2T half-amp duration:    {m['pulse_had_ns']:.0f} ns  (nominal 250 ns)")
    print(f"  Pulse ringing:           {m['pulse_ring_pct']:.2f}% of pulse "
          f"(largest lobe 0.4-1.8 us from peak)")
    print(f"  Bar edge 10-90% rise:    {m['edge_rise_ns']:.0f} ns   fall: {m['edge_fall_ns']:.0f} ns")
    print(f"  Edge overshoot:          {m['edge_overshoot_pct']:.2f}% of step")
    print(f"  Edge ringing:            {m['edge_ring_pct']:.2f}% of step (lobes after first extremum)")
    verdict = ("excellent (< 2%)" if max(m['pulse_ring_pct'], m['edge_overshoot_pct']) < 2
               else "good (2-4%)" if max(m['pulse_ring_pct'], m['edge_overshoot_pct']) < 4
               else "visible ringing (> 4%)")
    print(f"  Assessment:              {verdict}")
    print()


def weighted_snr_report(det, fields):
    """Section 13: CCIR-567 weighted SNR from flat VITS regions."""
    regions = []
    l19 = det.get("ntsc_line19_vits", [])
    if l19:
        regions.append(("line 19 50 IRE grey", [fields[i] for i in l19], 19, 39.0, 7.0))
        regions.append(("line 19 7.5 IRE black", [fields[i] for i in l19], 19, 51.0, 8.0))
    comp = sorted(det.get("ntsc_ntc7_composite", {}))
    if comp:
        regions.append(("line 20 100 IRE bar", [fields[i] for i in comp], 20, 18.0, 9.0))

    if not regions:
        print_skipped(13, "WEIGHTED SNR (CCIR 567 unified weighting)",
                      "no flat VITS regions detected")
        return

    print_section(13, "WEIGHTED SNR (CCIR 567 unified weighting, tau0 = 245 ns)\n"
                      "   PSNR = 100 IRE p-p vs RMS noise, band-limited to 4.2 MHz")
    print(f"\n{'Region':>24}  {'IRE':>6}  {'Fields':>6}  {'Unweighted':>10}  "
          f"{'Weighted':>9}  {'Advantage':>9}")
    print("-" * 74)
    for label, flds, line, start, dur in regions:
        r = weighted_psnr(flds, line, start, dur)
        if r is None:
            print(f"{label:>24}  {'—':>6}")
            continue
        w_db, flat_db, ire = r
        print(f"{label:>24}  {ire:>6.1f}  {len(flds):>6}  {flat_db:>9.2f}dB  "
              f"{w_db:>8.2f}dB  {w_db - flat_db:>+8.2f}dB")
    print("\n  (Weighted values are the ones comparable to broadcast SNR grades:")
    print("   >=60 studio, 54-60 broadcast chain, 46-54 good consumer source.)")
    print()


def ntc7_report(det, fields):
    """Sections 10-11: NTC-7 combination measurements (if detected)."""
    comb = det.get("ntsc_ntc7_combination", {})
    comb_idx = sorted(comb)

    if not comb_idx:
        print_skipped(10, "NTC-7 MULTIBURST FREQUENCY RESPONSE",
                      "NTC-7 combination VITS not detected")
        print_skipped(11, "NTC-7 MODULATED PEDESTAL",
                      "NTC-7 combination VITS not detected")
        return

    print_section(10, "NTC-7 MULTIBURST FREQUENCY RESPONSE\n"
                      "   (line 20, packets nominally 50 IRE p-p on 50 IRE pedestal)")

    # Pool packets across detected fields, keyed by nearest nominal frequency
    by_nom = defaultdict(list)
    for i in comb_idx:
        for us, freq, pp in comb[i]["packets"]:
            nom = min(NTC7_MULTIBURST_FREQS, key=lambda n: abs(n - freq))
            by_nom[nom].append((freq, pp))

    # Median across fields: the first fields of a decode can read low at
    # high frequencies while MTF calibration is still settling.
    rows = []
    for nom in sorted(by_nom):
        freqs = [x[0] for x in by_nom[nom]]
        pps = [x[1] for x in by_nom[nom]]
        rows.append((nom, np.median(freqs), np.median(pps), np.std(pps), len(pps)))

    ref_pp = rows[0][2]
    print(f"\n{'Nominal MHz':>12}  {'Measured':>9}  {'p-p IRE':>8}  {'std':>6}  "
          f"{'vs {:.1f} MHz'.format(rows[0][0]):>11}  {'Fields':>6}")
    print("-" * 62)
    for nom, fmeas, pp, ppstd, n in rows:
        db = 20 * np.log10(pp / ref_pp) if ref_pp > 0 else float("nan")
        print(f"{nom:>12.2f}  {fmeas:>9.2f}  {pp:>8.1f}  {ppstd:>6.2f}  "
              f"{db:>+10.2f}dB  {n:>6}")
    missing = [n for n in NTC7_MULTIBURST_FREQS if n not in by_nom]
    if missing:
        print(f"  Packets not resolved: {missing}")
    at_fsc = by_nom.get(3.58)
    if at_fsc and ref_pp > 0:
        pp_fsc = np.median([x[1] for x in at_fsc])
        print(f"\n  Response at fsc (3.58 MHz): {pp_fsc / ref_pp * 100:.1f}% "
              f"({20 * np.log10(pp_fsc / ref_pp):+.2f} dB) of low-frequency reference")
    print()

    ped_idx = [i for i in comb_idx if comb[i]["pedestal"]]
    if not ped_idx:
        print_skipped(11, "NTC-7 MODULATED PEDESTAL",
                      "3-level modulated pedestal not resolved")
        return

    print_section(11, "NTC-7 MODULATED PEDESTAL: CHROMA GAIN LINEARITY AND\n"
                      "   PHASE vs CHROMA AMPLITUDE (line 20, nominal 20/40/80 IRE p-p)")

    # Per-level stats across fields; phase is measured burst-relative
    levels = defaultdict(lambda: {"pp": [], "luma": [], "relph": []})
    for i in ped_idx:
        f = fields[i]
        _, burst_ph = burst_ref(f, 20)
        for k, (us, luma, pp, phase) in enumerate(comb[i]["pedestal"][:3]):
            levels[k]["pp"].append(pp)
            levels[k]["luma"].append(luma)
            if burst_ph is not None:
                levels[k]["relph"].append(phase_diff(phase, burst_ph))

    print(f"\n{'Nominal p-p':>12}  {'Measured p-p':>12}  {'Gain':>6}  "
          f"{'Luma IRE':>9}  {'Phase-burst':>11}  {'Fields':>6}")
    print("-" * 66)
    gains, relphs = [], []
    for k in sorted(levels):
        nom = NTC7_PEDESTAL_PP[k]
        pp = np.mean(levels[k]["pp"])
        gain = pp / nom
        gains.append(gain)
        relph = np.mean(levels[k]["relph"]) if levels[k]["relph"] else float("nan")
        relphs.append(relph)
        print(f"{nom:>12.0f}  {pp:>12.1f}  {gain:>6.3f}  "
              f"{np.mean(levels[k]['luma']):>9.1f}  {relph:>11.2f}  "
              f"{len(levels[k]['pp']):>6}")

    if len(gains) == 3 and gains[1] > 0:
        print(f"\n  Chroma gain nonlinearity (vs 40 IRE packet): "
              f"20 IRE {100 * (gains[0] / gains[1] - 1):+.1f}%, "
              f"80 IRE {100 * (gains[2] / gains[1] - 1):+.1f}%")
    if len(relphs) == 3 and not any(np.isnan(p) for p in relphs):
        print(f"  Phase vs chroma amplitude (20 -> 80 IRE p-p): "
              f"{relphs[2] - relphs[0]:+.2f} deg")
        print(f"  (luma constant at ~50 IRE, so this isolates amplitude-dependent "
              f"phase from luma DP)")
    print()


def print_dp_interpretation(slope, rms_res, rms_q):
    total_dp = slope * 100
    print(f"\n  INTERPRETATION:")
    print(f"  - Differential phase is {abs(total_dp):.1f} degrees over 100 IRE")
    if abs(total_dp) < 3:
        quality = "excellent (< 3 deg)"
    elif abs(total_dp) < 5:
        quality = "good (3-5 deg)"
    elif abs(total_dp) < 10:
        quality = "acceptable (5-10 deg)"
    elif abs(total_dp) < 15:
        quality = "marginal (10-15 deg)"
    else:
        quality = "poor (> 15 deg)"
    print(f"  - Quality assessment: {quality}")
    print(f"  - {'Phase increases' if slope > 0 else 'Phase decreases'} with luminance")
    if rms_q < rms_res * 0.7:
        print(f"  - Significant curvature detected (quadratic improves fit by "
              f"{(1 - rms_q/rms_res)*100:.0f}%)")
    else:
        print(f"  - Relationship is approximately linear "
              f"(quadratic improvement: {max(0, (1 - rms_q/rms_res)*100):.0f}%)")


# ---------------------------------------------------------------------------
# PAL report
# ---------------------------------------------------------------------------

def pal_measure_its(field, info):
    """Measure burst-relative phase/amplitude on a PAL ITS line.

    All regions are on the same line, so burst-relative phases are directly
    comparable (no V-switch handling needed).

    Returns list of (label, ire, rel_phase_deg, chroma_amp).
    """
    line = info["line"]
    bamp, bphase = burst_ref(field, line)
    if bamp is None or bamp < 5:
        return []

    points = []
    if info["sc_packet"] is not None:
        luma, amp, phase = demod_region(field, line, 31, 8)
        if amp > 5:
            points.append(("SC packet (0 level)", luma,
                           (phase - bphase) % 360, amp))

    for us, _, _ in info["steps"]:
        luma, amp, phase = demod_region(field, line, us, 2.4)
        if amp > 5:
            points.append((f"step @{us:.0f}us", luma,
                           (phase - bphase) % 360, amp))
    return points


def pal_report(params, fields, det):
    its_idx = sorted(i for i, v in det["pal_its"].items() if v["has_chroma"])

    # -----------------------------------------------------------------------
    # 1. Burst amplitude consistency
    # -----------------------------------------------------------------------
    print_section(1, "BURST AMPLITUDE ACROSS ALL ACTIVE LINES")

    for f in fields[:4]:
        amps = []
        for line in range(23, params.field_height - 2):
            amp, _ = burst_ref(f, line)
            if amp is not None and amp > 2:
                amps.append(amp)
        if amps:
            print(f"  Field {f.field_id}: burst amplitude "
                  f"mean={np.mean(amps):.2f} IRE, std={np.std(amps):.3f}, "
                  f"n={len(amps)} lines (nominal 21.43)")
    print()

    # -----------------------------------------------------------------------
    # 2. ITS phase vs IRE (differential phase)
    # -----------------------------------------------------------------------
    if not its_idx:
        print_skipped(2, "ITS DIFFERENTIAL PHASE",
                      "no ITS staircase with chroma detected")
        print_skipped(3, "ITS DIFFERENTIAL GAIN",
                      "no ITS staircase with chroma detected")
        pal_quality_reports(det, fields)
        return

    print_section(2, "ITS DIFFERENTIAL PHASE (phase relative to burst, per line)")

    slopes = []
    dgs = []
    for fi in its_idx[:8]:
        f = fields[fi]
        info = det["pal_its"][fi]
        points = pal_measure_its(f, info)
        if len(points) < 2:
            continue

        print(f"\n  Field {f.field_id} (line {info['line']}, "
              f"{'first' if f.isFirstField else 'second'} field):")
        print(f"  {'Region':>22}  {'IRE':>7}  {'RelPhase':>9}  {'Amplitude':>10}")
        print("  " + "-" * 55)

        # Unwrap relative phases around the first point to keep the fit sane
        ref = points[0][2]
        ires, phases, amps = [], [], []
        for label, ire, relph, amp in points:
            ph = ref + phase_diff(relph, ref)
            print(f"  {label:>22}  {ire:>7.1f}  {ph:>9.2f}  {amp:>10.2f}")
            ires.append(ire)
            phases.append(ph)
            amps.append(amp)

        ires = np.array(ires)
        phases = np.array(phases)

        A = np.vstack([ires, np.ones(len(ires))]).T
        slope, intercept = np.linalg.lstsq(A, phases, rcond=None)[0]
        slopes.append(slope)
        residuals = phases - (slope * ires + intercept)
        print(f"  Linear fit: phase = {slope:.4f} * IRE + {intercept:.2f}  "
              f"(RMS residual {np.sqrt(np.mean(residuals**2)):.3f} deg)")
        print(f"  DP over {ires.min():.0f}-{ires.max():.0f} IRE: "
              f"{slope * (ires.max() - ires.min()):+.2f} deg")

        # Differential gain: amplitude change relative to the 0-level packet
        if points[0][0].startswith("SC packet"):
            ref_amp = points[0][3]
            dg = (np.max(amps[1:]) - ref_amp) / ref_amp * 100
            dgs.append(dg)

    if slopes:
        arr = np.array(slopes)
        print(f"\n  DP slope over {len(arr)} field(s): "
              f"mean={np.mean(arr):+.4f} deg/IRE, std={np.std(arr):.4f}")
        print(f"  Extrapolated DP over 0-100 IRE: {np.mean(arr) * 100:+.2f} deg")
        print_dp_interpretation(np.mean(arr), 1.0, 1.0)
    print()

    # -----------------------------------------------------------------------
    # 3. Differential gain
    # -----------------------------------------------------------------------
    print_section(3, "ITS DIFFERENTIAL GAIN (subcarrier amplitude vs luma level)")
    if dgs:
        arr = np.array(dgs)
        print(f"  Peak amplitude deviation from 0-level packet: "
              f"mean={np.mean(arr):+.2f}%, std={np.std(arr):.2f} "
              f"({len(arr)} field(s))")
        print(f"  (Broadcast target is within +/-10%)")
    else:
        print("  SKIPPED - no 0-level subcarrier packet detected on the ITS line")
    print()

    # -----------------------------------------------------------------------
    # 4. 50% subcarrier reference line
    # -----------------------------------------------------------------------
    if det["pal_line20_ref"]:
        print_section(4, "50% LUMA SUBCARRIER REFERENCE LINE")
        for fi, info in sorted(det["pal_line20_ref"].items()):
            f = fields[fi]
            luma, amp, _ = demod_region(f, info["line"], 14, 44)
            print(f"  Field {f.field_id} line {info['line']}: "
                  f"luma={luma:.1f} IRE, subcarrier amplitude={amp:.2f} IRE")
        print()

    pal_quality_reports(det, fields)


def pal_quality_reports(det, fields):
    """Sections 5-7: weighted SNR, chroma AM/PM noise, ITS transients."""
    its_all = sorted(det.get("pal_its", {}))
    its_line = (next(iter(det["pal_its"].values()))["line"]
                if det.get("pal_its") else 19)
    its_chroma = sorted(i for i, v in det.get("pal_its", {}).items()
                        if v["has_chroma"])

    # --- 5. Weighted SNR ---
    def flat_run(f, line, target_ire, lo_us=12.0, hi_us=58.0):
        """Longest run where the raw waveform is genuinely flat near target.

        Checks the segment's own std, not just its mean — a mean-and-
        chroma test is blind to sub-fsc modulation (e.g. multiburst
        content riding at the target level).
        """
        best, cur = None, None
        for t in np.arange(lo_us, hi_us - 2.0, 0.5):
            seg = line_segment_ire(f, line, t, 2.0)
            ok = (len(seg) > 8 and abs(np.mean(seg) - target_ire) < 3.0
                  and np.std(seg) < 4.0)
            if ok:
                cur = (cur[0], t + 2.0) if cur else (t, t + 2.0)
                if best is None or cur[1] - cur[0] > best[1] - best[0]:
                    best = cur
            else:
                cur = None
        return best if best and best[1] - best[0] >= 6.0 else None

    regions = []
    grey = sorted(det.get("pal_grey50", {}))
    if grey:
        gline = next(iter(det["pal_grey50"].values()))["line"]
        # the "grey" line often carries other test content; measure only
        # its longest verified-flat stretch
        run = flat_run(fields[grey[0]], gline, 50.0)
        if run:
            regions.append((f"line {gline} 50% grey", [fields[i] for i in grey],
                            gline, run[0] + 0.5, run[1] - run[0] - 1.0))
    if its_all:
        regions.append((f"ITS white bar (line {its_line})",
                        [fields[i] for i in its_all], its_line, 13.0, 6.0))

    if not regions:
        print_skipped(5, "WEIGHTED SNR (CCIR 567 unified weighting)",
                      "no flat reference regions detected")
    else:
        print_section(5, "WEIGHTED SNR (CCIR 567 unified weighting, tau0 = 245 ns)\n"
                         "   PSNR = 100 IRE p-p vs RMS noise, band-limited to 5.0 MHz")
        print(f"\n{'Region':>24}  {'IRE':>6}  {'Fields':>6}  {'Unweighted':>10}  "
              f"{'Weighted':>9}  {'Advantage':>9}")
        print("-" * 74)
        for label, flds, line, start, dur in regions:
            r = weighted_psnr(flds, line, start, dur)
            if r is None:
                print(f"{label:>24}  {'—':>6}")
                continue
            w_db, flat_db, ire = r
            print(f"{label:>24}  {ire:>6.1f}  {len(flds):>6}  {flat_db:>9.2f}dB  "
                  f"{w_db:>8.2f}dB  {w_db - flat_db:>+8.2f}dB")
        print("\n  (Weighted values are the ones comparable to broadcast SNR grades:")
        print("   >=60 studio, 54-60 broadcast chain, 46-54 good consumer source.)")
        print()

    # --- 6. Chroma AM/PM noise ---
    # Prefer the full 50% subcarrier reference line; fall back to the ITS
    # 0-level subcarrier packet (short, so band resolution is coarser).
    src = None
    if det.get("pal_line20_ref"):
        idxs = sorted(det["pal_line20_ref"])
        rline = next(iter(det["pal_line20_ref"].values()))["line"]
        src = (f"50% SC reference line {rline}",
               [fields[i] for i in idxs], rline, 16.0, 40.0)
    elif its_chroma:
        # packet spans ~29.5-38.5 us; stay clear of the edges
        src = (f"ITS 0-level SC packet (line {its_line})",
               [fields[i] for i in its_chroma], its_line, 30.3, 7.4)

    if src is None:
        print_skipped(6, "CHROMINANCE AM/PM NOISE",
                      "no flat subcarrier region detected")
    else:
        label, flds, line, start, dur = src
        m = chroma_am_pm_noise(flds, line, start, dur)
        if m is None:
            print_skipped(6, "CHROMINANCE AM/PM NOISE",
                          f"no usable subcarrier packet ({label})")
        else:
            print_section(6, f"CHROMINANCE AM/PM NOISE ({label}, "
                             f"{m['n_fields']} fields)\n"
                             "   AM S/N = packet p-p vs rms envelope noise; "
                             "PM = rms phase noise")
            print(f"\n  Subcarrier packet: {m['sc_pp']:.1f} IRE p-p")
            print(f"\n{'Demod band':>22}  {'AM S/N':>8}  {'PM noise':>9}  {'PM S/N':>8}")
            print("-" * 54)
            for tag, blabel in (("band", "10-500 kHz (bcast)"),
                                ("wide", "10 kHz-1.3 MHz")):
                am = m[f"am_snr_{tag}"]
                pm = m[f"pm_deg_{tag}"]
                pm_snr = (20 * np.log10(1.0 / np.radians(pm))
                          if pm > 0 else float("nan"))
                am_s = f"{am:>7.2f}dB" if am is not None else f"{'—':>8}"
                print(f"{blabel:>22}  {am_s}  {pm:>8.3f}°  {pm_snr:>7.2f}dB")
            print()

    # --- 7. ITS transients ---
    if not its_all:
        print_skipped(7, "ITS 2T PULSE AND BAR EDGE (transient response)",
                      "ITS line not detected")
        return
    m = measure_pal_its_transients([fields[i] for i in its_all], its_line)
    if m is None:
        print_skipped(7, "ITS 2T PULSE AND BAR EDGE (transient response)",
                      "could not resolve pulse/bar on the averaged line")
        return
    print_section(7, "ITS 2T PULSE AND BAR EDGE: TRANSIENT RESPONSE / RINGING\n"
                     f"   (line {its_line} averaged over {m['n_fields']} fields)")
    print(f"\n  Bar level:               {m['bar_ire']:.1f} IRE")
    print(f"  2T pulse-to-bar ratio:   {m['pulse_ratio']:.3f}  (ideal 1.0)")
    print(f"  2T half-amp duration:    {m['pulse_had_ns']:.0f} ns  (nominal 200 ns)")
    print(f"  Pulse ringing:           {m['pulse_ring_pct']:.2f}% of pulse "
          f"(largest lobe 0.4-1.8 us from peak)")
    print(f"  Bar edge 10-90% rise:    {m['edge_rise_ns']:.0f} ns   fall: {m['edge_fall_ns']:.0f} ns")
    print(f"  Edge overshoot:          {m['edge_overshoot_pct']:.2f}% of step")
    print(f"  Edge ringing:            {m['edge_ring_pct']:.2f}% of step (lobes after first extremum)")
    verdict = ("excellent (< 2%)" if max(m['pulse_ring_pct'], m['edge_overshoot_pct']) < 2
               else "good (2-4%)" if max(m['pulse_ring_pct'], m['edge_overshoot_pct']) < 4
               else "visible ringing (> 4%)")
    print(f"  Assessment:              {verdict}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Measure differential phase from an NTSC or PAL TBC file.",
    )
    parser.add_argument(
        "tbc_file",
        nargs="?",
        default=os.path.join(os.path.dirname(__file__), "..", "main.tbc"),
        help="Path to .tbc or CVBS .composite file (default: main.tbc in the project root)",
    )
    parser.add_argument(
        "-n", "--max-fields",
        type=int,
        default=12,
        help="Maximum number of fields to load (default: 12)",
    )
    args = parser.parse_args()

    tbc_path = os.path.abspath(args.tbc_file)

    print("=" * 90)
    print("DIFFERENTIAL PHASE MEASUREMENT")
    print(f"TBC file: {tbc_path}")
    print("=" * 90)

    if tbc_path.endswith(".composite"):
        params, fields, _ = load_cvbs(tbc_path, max_fields=args.max_fields)
    else:
        params, fields, _ = load_tbc(tbc_path, max_fields=args.max_fields)
    print(f"Loaded {len(fields)} fields, system={params.system}")
    print(f"  field_width={params.field_width}, field_height={params.field_height}")
    print(f"  sample_rate={params.sample_rate_mhz:.4f} MHz")
    print(f"  blanking_16b={params.blanking_16b_ire}, white_16b={params.white_16b_ire}")
    print(f"  out_scale={params.out_scale:.2f}")

    # Detect which test patterns are present, and only verify those.
    det = detect_patterns(params, fields, max_fields=len(fields))
    print("\nDetected test patterns:")
    for line in summarize_patterns(det, fields):
        print("  " + line)
    print()

    if params.system == "NTSC":
        ntsc_report(params, fields, det)
    else:
        pal_report(params, fields, det)

    print("=" * 90)
    print("ANALYSIS COMPLETE")
    print("=" * 90)


if __name__ == "__main__":
    main()
