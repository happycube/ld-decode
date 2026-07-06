#!/usr/bin/env python3
"""Color bar analyzer for NTSC and PAL TBC and CVBS files.

Reads a .tbc file (with companion .tbc.db) or a CVBS .composite file
(with companion .meta), detects colour bars, and measures luminance,
chrominance amplitude, and chrominance phase for each bar against the
expected values.

NTSC: SMPTE bars (75% or 100%), absolute I/Q via the CombNTSC comb filter.
PAL:  EBU bars (100/0/75/0 or 100/0/100/0), U/V via burst-relative
      quadrature demodulation with V-switch folding.

The bar region is auto-detected; if no bars are found the script reports
which test patterns were detected and exits (use --lines to force).

Usage:
    python scripts/smpte_analyze.py cbar_he.tbc
    python scripts/smpte_analyze.py pal-kage.tbc
    python scripts/smpte_analyze.py jasonbars.composite
    python scripts/smpte_analyze.py --decode ../testdata/he010_cbar.lds
"""

import argparse
import os
import subprocess
import sys
import tempfile

import numpy as np

# Allow running from the scripts/ directory or project root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from lddecode.metrics import CombNTSC
from tbc_common import (
    load_tbc, load_cvbs, detect_patterns, summarize_patterns, detect_colorbars,
    burst_ref, demod_region, pal_fold_uv, phase_diff,
)


# ---------------------------------------------------------------------------
# Reference values
# ---------------------------------------------------------------------------

BAR_NAMES = ["White", "Yellow", "Cyan", "Green", "Magenta", "Red", "Blue", "Black"]

# RGB triplets for each bar at 100% amplitude, 100% saturation (no setup)
_BAR_RGB_100 = {
    "White":   (100, 100, 100),
    "Yellow":  (100, 100,   0),
    "Cyan":    (  0, 100, 100),
    "Green":   (  0, 100,   0),
    "Magenta": (100,   0, 100),
    "Red":     (100,   0,   0),
    "Blue":    (  0,   0, 100),
    "Black":   (  0,   0,   0),
}


def compute_expected_bars(amplitude_pct, saturation_pct=100, setup_ire=7.5):
    """Expected Y, I, Q, chroma amplitude and phase for NTSC SMPTE bars.

    amplitude_pct:  75 for 75% bars, 100 for 100% bars.
    saturation_pct: 100 for full saturation, 75 for reduced (75/75 bars).
    setup_ire:      NTSC setup level (7.5 IRE for standard, 0 for NTSC-J).
    """
    amp = amplitude_pct / 100.0
    sat = saturation_pct / 100.0
    expected = {}
    for name, (r100, g100, b100) in _BAR_RGB_100.items():
        r = amp * (r100 if r100 else (1 - sat) * 100) / 100.0
        g = amp * (g100 if g100 else (1 - sat) * 100) / 100.0
        b = amp * (b100 if b100 else (1 - sat) * 100) / 100.0

        y_norm = 0.299 * r + 0.587 * g + 0.114 * b
        y = y_norm * (100 - setup_ire) + setup_ire
        i = (0.596 * r - 0.275 * g - 0.321 * b) * 100
        q = (0.212 * r - 0.523 * g + 0.311 * b) * 100

        chroma = np.sqrt(i ** 2 + q ** 2)
        phase = np.degrees(np.arctan2(i, q)) % 360 if chroma > 0.1 else 0.0

        expected[name] = {
            "Y": y, "I": i, "Q": q,
            "chroma": chroma, "phase": phase,
        }
    return expected


def compute_expected_bars_pal(amplitude_pct):
    """Expected Y, U, V, chroma amplitude and hue for PAL EBU bars.

    amplitude_pct: colour bar amplitude - 75 for 100/0/75/0 bars,
    100 for 100/0/100/0.  The white bar is always at 100%.  No setup.
    """
    amp = amplitude_pct / 100.0
    expected = {}
    for name, (r100, g100, b100) in _BAR_RGB_100.items():
        scale = 1.0 if name == "White" else amp
        r, g, b = (scale * r100 / 100.0, scale * g100 / 100.0,
                   scale * b100 / 100.0)

        y = 0.299 * r + 0.587 * g + 0.114 * b
        u = 0.493 * (b - y) * 100
        v = 0.877 * (r - y) * 100

        chroma = np.sqrt(u ** 2 + v ** 2)
        hue = np.degrees(np.arctan2(v, u)) % 360 if chroma > 0.1 else 0.0

        expected[name] = {
            "Y": y * 100, "U": u, "V": v,
            "chroma": chroma, "phase": hue,
        }
    return expected


# PAL burst: 300 mV p-p on a 700 mV scale
PAL_BURST_EXPECTED = 150.0 / 7.0


# ---------------------------------------------------------------------------
# NTSC bar measurement (CombNTSC comb filter, absolute I/Q)
# ---------------------------------------------------------------------------

def measure_bars_ntsc(params, field, comb, line_range):
    """Measure colour bars on a single NTSC field.

    Returns a dict keyed by bar name with keys:
        luma_ire, chroma_ire, phase_deg, I_ire, Q_ire
    """
    active_start = params.active_video_start
    active_end = params.active_video_end
    bar_width = (active_end - active_start) / 7.0

    # Accumulators per bar
    luma_acc = {n: [] for n in BAR_NAMES[:7]}
    i_acc = {n: [] for n in BAR_NAMES[:7]}
    q_acc = {n: [] for n in BAR_NAMES[:7]}

    for line in line_range:
        # Get the full line for splitIQ
        sl = field.lineslice_tbc(line, 0, 63.5)
        si, sq = comb.splitIQ_line(line, sl)

        # Luma: composite minus chroma.
        # cbuffer = (avg_neighbors - center), which equals -chroma for a
        # pure subcarrier, so luma = composite + cbuffer.
        cbuf = comb.cbuffer[-1][sl]
        composite = field.dspicture[sl].astype(np.float32)
        luma = composite + cbuf
        luma_ire = (luma - params.blanking_16b_ire) / params.out_scale

        for i, name in enumerate(BAR_NAMES[:7]):
            # Skip edge samples to avoid transitions between bars.
            margin = 15
            s0 = active_start + int(i * bar_width + margin)
            s1 = active_start + int((i + 1) * bar_width - margin)

            luma_acc[name].append(np.mean(luma_ire[s0:s1]))

            # IQ is decimated 2:1 relative to full samples.
            iq_s0 = s0 // 2
            iq_s1 = s1 // 2
            i_acc[name].append(np.mean(si[iq_s0:iq_s1]))
            q_acc[name].append(np.mean(sq[iq_s0:iq_s1]))

    results = {}
    for name in BAR_NAMES[:7]:
        mean_luma = np.mean(luma_acc[name])
        mean_i = np.mean(i_acc[name])
        mean_q = np.mean(q_acc[name])

        # Chroma amplitude in IRE.  The 1D comb filter has a gain of 2
        # for chroma (because subcarrier inverts every 2 samples at 4fsc),
        # so divide by 2*out_scale.
        chroma_raw = np.sqrt(mean_i ** 2 + mean_q ** 2)
        chroma_ire = chroma_raw / (2 * params.out_scale)

        phase = np.degrees(np.arctan2(mean_i, mean_q)) % 360 if chroma_ire > 0.5 else 0.0

        results[name] = {
            "luma_ire": mean_luma,
            "chroma_ire": chroma_ire,
            "phase_deg": phase,
            "I_ire": mean_i / (2 * params.out_scale),
            "Q_ire": mean_q / (2 * params.out_scale),
        }

    return results


def measure_burst_ntsc(params, field, comb, line_range):
    """Measure average colour burst amplitude and phase via splitIQ."""
    burst_iq_start = params.colour_burst_start // 2
    burst_iq_end = params.colour_burst_end // 2

    amps = []
    phases = []
    for line in line_range:
        sl = field.lineslice_tbc(line, 0, 10)
        si, sq = comb.splitIQ_line(line, sl)
        bsl = slice(burst_iq_start, burst_iq_end)
        mi = np.mean(si[bsl])
        mq = np.mean(sq[bsl])
        amp = np.sqrt(mi ** 2 + mq ** 2)
        amps.append(amp)
        phase = np.degrees(np.arctan2(mi, mq)) % 360
        phases.append(phase)

    mean_amp = np.mean(amps) / (2 * params.out_scale)
    mean_phase = np.median(phases)
    return mean_amp, mean_phase


def average_ntsc_fields(all_results):
    """Average per-field NTSC bar measurements, with circular phase mean."""
    avg_results = {}
    for name in BAR_NAMES[:7]:
        avg_results[name] = {
            key: np.mean([r[name][key] for r in all_results])
            for key in all_results[0][name]
        }
        phases_rad = [np.radians(r[name]["phase_deg"]) for r in all_results]
        if avg_results[name]["chroma_ire"] > 0.5:
            avg_results[name]["phase_deg"] = np.degrees(np.arctan2(
                np.mean(np.sin(phases_rad)),
                np.mean(np.cos(phases_rad)),
            )) % 360
    return avg_results


# ---------------------------------------------------------------------------
# PAL bar measurement (burst-relative quadrature demod, U/V)
# ---------------------------------------------------------------------------

def measure_bars_pal(params, field, line_range, expected):
    """Measure colour bars on a single PAL field.

    Returns (results, burst_amp) where results is keyed by bar name with:
        luma_ire, chroma_ire, phase_deg (hue re +U), U_ire, V_ire
    """
    sr = params.sample_rate_mhz
    a0, a1 = params.active_video_start, params.active_video_end
    bar_width = (a1 - a0) / 7.0

    expected_hues = [
        expected[n]["phase"] if expected[n]["chroma"] > 0.5 else None
        for n in BAR_NAMES[:7]
    ]

    luma_acc = {n: [] for n in BAR_NAMES[:7]}
    line_phasors = {}
    burst_amps = []

    for line in line_range:
        bamp, bphase = burst_ref(field, line)
        if bamp is None or bamp < 5:
            continue
        burst_amps.append(bamp)

        phasors = []
        for i, name in enumerate(BAR_NAMES[:7]):
            margin = 15
            s0 = a0 + i * bar_width + margin
            s1 = a0 + (i + 1) * bar_width - margin
            luma, amp, phase = demod_region(field, line, s0 / sr, (s1 - s0) / sr)
            luma_acc[name].append(luma)
            phasors.append(amp * np.exp(1j * np.radians(phase - bphase)))
        line_phasors[line] = phasors

    folded, _ = pal_fold_uv(line_phasors, expected_hues)

    results = {}
    for i, name in enumerate(BAR_NAMES[:7]):
        c = np.mean([folded[line][i] for line in folded])
        amp = np.abs(c)
        results[name] = {
            "luma_ire": np.mean(luma_acc[name]),
            "chroma_ire": amp,
            "phase_deg": np.degrees(np.angle(c)) % 360 if amp > 0.5 else 0.0,
            "U_ire": np.real(c),
            "V_ire": np.imag(c),
        }

    return results, np.mean(burst_amps)


def average_pal_fields(all_results):
    """Average per-field PAL bar measurements via the U/V vectors."""
    avg_results = {}
    for name in BAR_NAMES[:7]:
        u = np.mean([r[name]["U_ire"] for r in all_results])
        v = np.mean([r[name]["V_ire"] for r in all_results])
        amp = np.hypot(u, v)
        avg_results[name] = {
            "luma_ire": np.mean([r[name]["luma_ire"] for r in all_results]),
            "chroma_ire": amp,
            "phase_deg": np.degrees(np.arctan2(v, u)) % 360 if amp > 0.5 else 0.0,
            "U_ire": u,
            "V_ire": v,
        }
    return avg_results


# ---------------------------------------------------------------------------
# Bar level detection
# ---------------------------------------------------------------------------

def detect_bar_level_ntsc(bar_results):
    """Auto-detect amplitude from white bar luma level.

    Returns (amplitude_pct, saturation_pct).  Saturation is always 100 by
    default - use --bars AMP/SAT to override.
    """
    white_luma = bar_results["White"]["luma_ire"]
    amplitude_pct = 100 if white_luma > 90 else 75
    return amplitude_pct, 100


def detect_bar_level_pal(bar_results):
    """Auto-detect PAL colour amplitude from the yellow bar luma.

    White is 100% in both variants; yellow is ~66 IRE for 75% bars and
    ~89 IRE for 100% bars.
    """
    yellow_luma = bar_results["Yellow"]["luma_ire"]
    amplitude_pct = 100 if yellow_luma > 78 else 75
    return amplitude_pct, 100


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_report(system, bar_results, burst_amp, burst_phase, amplitude_pct,
                 saturation_pct=100, setup_ire=7.5):
    """Print a comparison of measured vs expected values."""
    if system == "NTSC":
        expected = compute_expected_bars(amplitude_pct, saturation_pct, setup_ire)
        title = (f"SMPTE Color Bar Analysis (NTSC)  --  "
                 f"{amplitude_pct}/{saturation_pct}% bars, setup = {setup_ire} IRE")
        burst_note = "(expected ~14.14)"
        comp_names = ("I", "Q")
        phase_hdr = "Phase"
    else:
        expected = compute_expected_bars_pal(amplitude_pct)
        title = (f"EBU Color Bar Analysis (PAL)  --  "
                 f"100/0/{amplitude_pct}/0 bars")
        burst_note = f"(expected ~{PAL_BURST_EXPECTED:.2f})"
        comp_names = ("U", "V")
        phase_hdr = "Hue"

    print()
    print(f"  {title}")
    print()
    if burst_phase is not None:
        print(f"  Color burst:  amplitude = {burst_amp:.2f} IRE  {burst_note},"
              f"  phase = {burst_phase:.1f} deg")
    else:
        print(f"  Color burst:  amplitude = {burst_amp:.2f} IRE  {burst_note}")
    print()

    # --- Luminance ---
    print("  Luminance (IRE)")
    print(f"  {'Bar':>10}  {'Measured':>9}  {'Expected':>9}  {'Error':>7}")
    print(f"  {'-'*40}")
    for name in BAR_NAMES[:7]:
        meas = bar_results[name]["luma_ire"]
        exp = expected[name]["Y"]
        err = meas - exp
        print(f"  {name:>10}  {meas:>9.2f}  {exp:>9.2f}  {err:>+7.2f}")
    print()

    # --- Chrominance ---
    print("  Chrominance")
    print(f"  {'Bar':>10}  {'Amp meas':>9}  {'Amp exp':>9}  {'Amp err':>8}  "
          f"{phase_hdr + ' meas':>11}  {phase_hdr + ' exp':>10}  {phase_hdr + ' err':>10}")
    print(f"  {'-'*76}")
    for name in BAR_NAMES[:7]:
        m = bar_results[name]
        e = expected[name]
        amp_m = m["chroma_ire"]
        amp_e = e["chroma"]
        ph_m = m["phase_deg"]
        ph_e = e["phase"]

        if amp_e > 0.5:
            ph_err_str = f"{phase_diff(ph_m, ph_e):>+10.1f}"
            amp_err_str = f"{amp_m - amp_e:>+8.2f}"
        else:
            ph_err_str = f"{'---':>10}"
            amp_err_str = f"{'---':>8}"

        print(f"  {name:>10}  {amp_m:>9.2f}  {amp_e:>9.2f}  {amp_err_str}  "
              f"{ph_m:>11.1f}  {ph_e:>10.1f}  {ph_err_str}")
    print()

    # --- Component breakdown ---
    cn1, cn2 = comp_names
    print(f"  {cn1}/{cn2} Components (IRE)")
    print(f"  {'Bar':>10}  {cn1 + ' meas':>8}  {cn1 + ' exp':>8}  {cn1 + ' err':>8}  "
          f"{cn2 + ' meas':>8}  {cn2 + ' exp':>8}  {cn2 + ' err':>8}")
    print(f"  {'-'*62}")
    for name in BAR_NAMES[:7]:
        m = bar_results[name]
        e = expected[name]
        c1_m = m[f"{cn1}_ire"]
        c2_m = m[f"{cn2}_ire"]
        c1_e = e[cn1]
        c2_e = e[cn2]
        print(f"  {name:>10}  {c1_m:>8.2f}  {c1_e:>8.2f}  {c1_m - c1_e:>+8.2f}  "
              f"{c2_m:>8.2f}  {c2_e:>8.2f}  {c2_m - c2_e:>+8.2f}")
    print()


# ---------------------------------------------------------------------------
# Decode helper
# ---------------------------------------------------------------------------

def decode_lds(lds_path, output_base=None, system="NTSC"):
    """Decode an .lds (or .ldf) file to TBC using ld-decode.

    Returns the path to the .tbc file.
    """
    if output_base is None:
        # Put the TBC in a temp directory
        tmpdir = tempfile.mkdtemp(prefix="smpte_")
        base = os.path.splitext(os.path.basename(lds_path))[0]
        output_base = os.path.join(tmpdir, base)

    tbc_path = output_base + ".tbc"
    if os.path.exists(tbc_path) and os.path.exists(tbc_path + ".db"):
        print(f"Using existing TBC: {tbc_path}", file=sys.stderr)
        return tbc_path

    # Find ld-decode entry point.  Set PYTHONPATH so the development tree
    # is used rather than any system-installed version.
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ld_decode_main = os.path.join(project_root, "lddecode", "main.py")

    env = os.environ.copy()
    env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")

    cmd = [
        sys.executable, ld_decode_main,
        "--PAL" if system == "PAL" else "--NTSC",
        "--length", "3",
        lds_path,
        output_base,
    ]

    print(f"Decoding: {' '.join(cmd)}", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        print(f"Decode stderr:\n{result.stderr}", file=sys.stderr)
        raise RuntimeError(f"ld-decode failed (exit {result.returncode})")

    if not os.path.exists(tbc_path):
        raise FileNotFoundError(f"Decode did not produce {tbc_path}")

    return tbc_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Analyze colour bars from an NTSC or PAL TBC file.",
    )
    parser.add_argument(
        "tbc_file",
        nargs="?",
        help="Path to .tbc file (companion .tbc.db must exist) or "
             "CVBS .composite file (companion .meta must exist)",
    )
    parser.add_argument(
        "--decode",
        metavar="LDS_FILE",
        help="Decode an .lds/.ldf file first, then analyze the resulting TBC",
    )
    parser.add_argument(
        "--decode-system",
        choices=["NTSC", "PAL"],
        default="NTSC",
        help="Video system for --decode (default: NTSC)",
    )
    parser.add_argument(
        "--output-base", "-o",
        metavar="PATH",
        help="Base path for decoded TBC (used with --decode)",
    )
    parser.add_argument(
        "--field", "-f",
        type=int,
        default=None,
        help="Specific field index to analyze (default: average first few fields)",
    )
    parser.add_argument(
        "--lines",
        metavar="START-END",
        default=None,
        help="Force the field line range for bar measurement "
             "(default: auto-detect; also skips the bars-present check)",
    )
    parser.add_argument(
        "--bars",
        metavar="AMP[/SAT]",
        default=None,
        help="Force bar level, e.g. 75, 100, or 75/75 (default: auto-detect)",
    )
    parser.add_argument(
        "--setup",
        type=float,
        default=7.5,
        help="NTSC setup level in IRE (default: 7.5, use 0 for NTSC-J)",
    )

    args = parser.parse_args()

    # Determine TBC path
    tbc_path = args.tbc_file
    if args.decode:
        tbc_path = decode_lds(args.decode, args.output_base, args.decode_system)
    if tbc_path is None:
        parser.error("Provide a .tbc file or use --decode with an .lds/.ldf file")

    # Load
    if tbc_path.endswith(".composite"):
        params, fields, tbc_data = load_cvbs(tbc_path)
    else:
        params, fields, tbc_data = load_tbc(tbc_path)
    system = params.system
    print(f"Input: {tbc_path}", file=sys.stderr)
    print(f"  {system}, {params.field_width}x{params.field_height}, "
          f"{params.video_sample_rate/1e6:.4f} MHz, "
          f"{len(fields)} fields", file=sys.stderr)
    print(f"  Active region: samples {params.active_video_start}-{params.active_video_end} "
          f"({params.active_video_end - params.active_video_start} wide)", file=sys.stderr)

    # Pick fields to analyze
    if args.field is not None:
        field_indices = [args.field]
    else:
        field_indices = list(range(min(len(fields), 10)))

    # Determine the bar line range: forced or auto-detected
    if args.lines:
        lo, hi = args.lines.split("-")
        line_ranges = {fi: range(int(lo), int(hi)) for fi in field_indices}
    else:
        line_ranges = {}
        for fi in field_indices:
            bars = detect_colorbars(fields[fi])
            if bars:
                # Stay clear of the top/bottom edges of the bar region
                line_ranges[fi] = range(bars[0] + 4, bars[1] - 3)

        if not line_ranges:
            print("\nNo colour bars detected.  Patterns present:", file=sys.stderr)
            det = detect_patterns(params, fields)
            for line in summarize_patterns(det, fields):
                print("  " + line, file=sys.stderr)
            print("\nUse --lines START-END to force a bar region.", file=sys.stderr)
            return 1

        field_indices = sorted(line_ranges.keys())
        example = line_ranges[field_indices[0]]
        print(f"  Detected bars on {len(field_indices)} field(s), "
              f"lines {example.start}-{example.stop}", file=sys.stderr)

    # Parse forced bar level up front (needed for PAL folding expectations)
    forced_level = None
    if args.bars:
        parts = args.bars.split("/")
        forced_level = (int(parts[0]),
                        int(parts[1]) if len(parts) > 1 else 100)

    # Measure
    all_results = []
    all_burst_amp = []
    all_burst_phase = []

    if system == "NTSC":
        for fi in field_indices:
            f = fields[fi]
            comb = CombNTSC([f])
            all_results.append(measure_bars_ntsc(params, f, comb, line_ranges[fi]))
            burst_amp, burst_phase = measure_burst_ntsc(params, f, comb, line_ranges[fi])
            all_burst_amp.append(burst_amp)
            all_burst_phase.append(burst_phase)

        avg_results = average_ntsc_fields(all_results)
        avg_burst_phase = np.median(all_burst_phase)
        amplitude_pct, saturation_pct = (
            forced_level or detect_bar_level_ntsc(avg_results))
    else:
        # The V-switch folding needs expected hues, which are the same for
        # both EBU variants, so use 75% as the folding reference.
        fold_expected = compute_expected_bars_pal(75)
        for fi in field_indices:
            f = fields[fi]
            results, burst_amp = measure_bars_pal(
                params, f, line_ranges[fi], fold_expected)
            all_results.append(results)
            all_burst_amp.append(burst_amp)

        avg_results = average_pal_fields(all_results)
        # PAL burst phase alternates with the V-switch; only amplitude is
        # meaningful here.
        avg_burst_phase = None
        amplitude_pct, saturation_pct = (
            forced_level or detect_bar_level_pal(avg_results))

    avg_burst_amp = np.mean(all_burst_amp)
    print(f"  Detected bar level: {amplitude_pct}/{saturation_pct}%", file=sys.stderr)

    print_report(system, avg_results, avg_burst_amp, avg_burst_phase,
                 amplitude_pct, saturation_pct, args.setup)

    return 0


if __name__ == "__main__":
    sys.exit(main())
