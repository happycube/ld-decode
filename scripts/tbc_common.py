#!/usr/bin/env python3
"""Shared TBC loading, chroma demodulation, and test-pattern detection.

Used by the analysis scripts (smpte_analyze.py, differential_phase.py).
Supports both NTSC and PAL .tbc files (with companion .tbc.db).

Chroma demodulation here is system-independent: both NTSC and PAL TBC
output is sampled at exactly 4x the colour subcarrier, so the subcarrier
sits at fs/4 and can be demodulated with a fixed quadrature reference.
Absolute phase is only meaningful per-line (PAL output subcarrier phase
rotates line to line), so phase measurements are referenced to the colour
burst of the same line.

Run directly to report which test patterns are present:

    python scripts/tbc_common.py file.tbc
"""

import mmap
import os
import sqlite3
import sys

import numpy as np


# ---------------------------------------------------------------------------
# TBC loading
# ---------------------------------------------------------------------------

class CaptureParams:
    """System parameters from the capture table of a .tbc.db."""

    def __init__(self, db_path):
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM capture LIMIT 1").fetchone()
        if row is None:
            raise RuntimeError(f"No capture record in {db_path}")

        self.system = row["system"]
        self.field_width = row["field_width"]
        self.field_height = row["field_height"]
        self.video_sample_rate = row["video_sample_rate"]
        self.sample_rate_mhz = self.video_sample_rate / 1e6
        self.white_16b_ire = row["white_16b_ire"]
        self.black_16b_ire = row["black_16b_ire"]
        self.blanking_16b_ire = row["blanking_16b_ire"]
        self.active_video_start = row["active_video_start"]
        self.active_video_end = row["active_video_end"]
        self.colour_burst_start = row["colour_burst_start"]
        self.colour_burst_end = row["colour_burst_end"]
        self.capture_id = row["capture_id"]

        self.out_scale = (self.white_16b_ire - self.blanking_16b_ire) / 100.0
        self.field_samples = self.field_width * self.field_height
        con.close()

    def __repr__(self):
        return (
            f"CaptureParams(system={self.system}, "
            f"field={self.field_width}x{self.field_height}, "
            f"sample_rate={self.sample_rate_mhz:.4f} MHz)"
        )


class TBCField:
    """Lightweight field object, compatible with lddecode.metrics.CombNTSC.

    Provides: dspicture, fieldPhaseID, isFirstField, out_scale,
    lineslice_tbc(), output_to_ire().
    """

    def __init__(self, tbc_data, field_index, params, record):
        offset = field_index * params.field_samples
        self.dspicture = tbc_data[offset:offset + params.field_samples]
        self.fieldPhaseID = record["field_phase_id"]
        self.isFirstField = bool(record["is_first_field"])
        self.field_id = record["field_id"]
        self.field_index = field_index
        self.out_scale = params.out_scale
        self.params = params

    def lineslice_tbc(self, line, start_us, duration_us):
        p = self.params
        ls = (line - 1) * p.field_width
        s0 = ls + int(start_us * p.sample_rate_mhz)
        s1 = ls + int((start_us + duration_us) * p.sample_rate_mhz)
        return slice(s0, s1)

    def output_to_ire(self, data):
        return (data.astype(np.float64) - self.params.blanking_16b_ire) / self.out_scale

    def line_ire(self, line):
        """Whole line as IRE (PAL: 0-100 scale, 700 mV = 100)."""
        p = self.params
        sl = slice((line - 1) * p.field_width, line * p.field_width)
        return self.output_to_ire(self.dspicture[sl])


def load_tbc(tbc_path, max_fields=None):
    """Load a TBC file (NTSC or PAL).  Returns (params, fields, tbc_data)."""
    db_path = tbc_path + ".db"
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")
    if not os.path.exists(tbc_path):
        raise FileNotFoundError(f"TBC file not found: {tbc_path}")

    params = CaptureParams(db_path)

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    records = con.execute(
        "SELECT field_id, is_first_field, field_phase_id "
        "FROM field_record WHERE capture_id = ? ORDER BY field_id",
        (params.capture_id,),
    ).fetchall()
    con.close()

    fd = os.open(tbc_path, os.O_RDONLY)
    try:
        mm = mmap.mmap(fd, os.fstat(fd).st_size, access=mmap.ACCESS_READ)
        tbc_data = np.frombuffer(mm, dtype=np.uint16)
    finally:
        os.close(fd)

    n = len(tbc_data) // params.field_samples
    if n < len(records):
        records = records[:n]
    if max_fields is not None:
        records = records[:max_fields]

    fields = [TBCField(tbc_data, i, params, records[i]) for i in range(len(records))]
    return params, fields, tbc_data


# ---------------------------------------------------------------------------
# fs/4 quadrature chroma demodulation (system-independent)
# ---------------------------------------------------------------------------

def demod_region(field, line, start_us, duration_us):
    """Demodulate chroma over a region of one line.

    Returns (luma_ire, chroma_amp_ire, phase_deg).  The phase reference is
    the line start, so phases are only comparable within one line - use
    burst_ref() and rel_phase() for burst-relative values.
    """
    p = field.params
    ire = field.line_ire(line)
    s0 = int(start_us * p.sample_rate_mhz)
    s1 = int((start_us + duration_us) * p.sample_rate_mhz)
    s1 = min(s1, len(ire))
    seg = ire[s0:s1]
    if len(seg) < 8:
        return None, None, None

    luma = np.mean(seg)
    n = np.arange(s0, s1)
    # Subcarrier at exactly fs/4: quadrature reference is a 4-sample cycle.
    c = np.mean((seg - luma) * np.exp(-0.5j * np.pi * n))
    amp = 2 * np.abs(c)
    phase = np.degrees(np.angle(c)) % 360
    return luma, amp, phase


def burst_ref(field, line):
    """Colour burst (amplitude_ire, phase_deg) for one line, or (None, None)."""
    p = field.params
    b0, b1 = p.colour_burst_start, p.colour_burst_end
    sr = p.sample_rate_mhz
    _, amp, phase = demod_region(field, line, b0 / sr, (b1 - b0) / sr)
    return amp, phase


def phase_diff(a, b):
    """Wrapped difference a - b in (-180, 180]."""
    d = (a - b) % 360
    return d - 360 if d > 180 else d


# ---------------------------------------------------------------------------
# Test pattern detection
# ---------------------------------------------------------------------------

# Detection thresholds (IRE)
CHROMA_PRESENT = 8.0
CHROMA_ABSENT = 5.0


def measure_bar_segments(field, line, n_bars=7, margin_frac=0.12):
    """Measure luma/chroma/phase for n_bars equal bars across active video.

    Returns list of (luma, chroma, phase) per bar.
    """
    p = field.params
    sr = p.sample_rate_mhz
    a0, a1 = p.active_video_start, p.active_video_end
    bar_w = (a1 - a0) / n_bars
    out = []
    for i in range(n_bars):
        s0 = a0 + i * bar_w + bar_w * margin_frac
        s1 = a0 + (i + 1) * bar_w - bar_w * margin_frac
        luma, amp, phase = demod_region(field, line, s0 / sr, (s1 - s0) / sr)
        out.append((luma, amp, phase))
    return out


def is_colorbar_line(field, line):
    """Check whether one line looks like 75/100% colour bars (7 bars).

    Criteria: monotonically decreasing luma, low chroma on the white bar,
    chroma present on at least 5 of the 6 colour bars.
    """
    bars = measure_bar_segments(field, line)
    lumas = [b[0] for b in bars]
    chromas = [b[1] for b in bars]
    if any(v is None for v in lumas):
        return False
    if lumas[0] < 55 or lumas[-1] > 25:
        return False
    if any(lumas[i + 1] > lumas[i] + 3 for i in range(6)):
        return False
    if chromas[0] > CHROMA_ABSENT + 2:
        return False
    if sum(1 for c in chromas[1:] if c > CHROMA_PRESENT) < 5:
        return False
    return True


def detect_colorbars(field, probe_step=8):
    """Scan a field for colour bars.  Returns (first_line, last_line) or None.

    Probes every probe_step lines over the picture area, then refines the
    boundaries of the longest matching run.
    """
    p = field.params
    lo, hi = 22, p.field_height - 5
    hits = [ln for ln in range(lo, hi, probe_step) if is_colorbar_line(field, ln)]
    if not hits:
        return None

    # Longest run of consecutive probe hits
    runs, cur = [], [hits[0]]
    for ln in hits[1:]:
        if ln - cur[-1] == probe_step:
            cur.append(ln)
        else:
            runs.append(cur)
            cur = [ln]
    runs.append(cur)
    best = max(runs, key=len)

    first, last = best[0], best[-1]
    while first > lo and is_colorbar_line(field, first - 1):
        first -= 1
    while last < hi - 1 and is_colorbar_line(field, last + 1):
        last += 1
    if last - first < 8:
        return None
    return first, last


def detect_ntsc_line19_vits(field):
    """NTSC LD VITS on line 19: 70 IRE colour bar (14-32 us) + 50 IRE grey.

    Returns dict or None.
    """
    luma_bar, chroma_bar, _ = demod_region(field, 19, 16, 14)
    luma_grey, chroma_grey, _ = demod_region(field, 19, 37, 8)
    if luma_bar is None or luma_grey is None:
        return None
    if not (40 < luma_bar < 100 and chroma_bar > CHROMA_PRESENT):
        return None
    if not (35 < luma_grey < 65 and chroma_grey < CHROMA_ABSENT):
        return None
    return {"bar_ire": luma_bar, "bar_chroma": chroma_bar, "grey_ire": luma_grey}


def detect_ntsc_line20_staircase(field):
    """NTSC LD VITS on line 20: white bar then 5-step staircase with chroma.

    Returns dict with step measurements or None.
    """
    luma_white, _, _ = demod_region(field, 20, 14, 6)
    if luma_white is None or not (85 < luma_white < 115):
        return None
    steps = []
    for us in (46.5, 49.5, 52.5, 55.5, 58.5):
        luma, amp, _ = demod_region(field, 20, us, 1.5)
        if luma is None:
            return None
        steps.append((us, luma, amp))
    lumas = [s[1] for s in steps]
    diffs = [lumas[i + 1] - lumas[i] for i in range(4)]
    if not (all(d > 5 for d in diffs) and lumas[-1] - lumas[0] > 50):
        return None
    has_chroma = all(s[2] > CHROMA_PRESENT for s in steps)
    return {"white_ire": luma_white, "steps": steps, "has_chroma": has_chroma}


def detect_ntsc_white_flag(field):
    """NTSC white flag on line 11 (early CAV discs)."""
    luma, _, _ = demod_region(field, 11, 15, 40)
    return luma is not None and 92 < luma < 108


def detect_pal_its(field, lines=(17, 18, 19, 20)):
    """PAL CCIR insertion test signal: white bar + 5-step staircase.

    Scans candidate field lines.  Returns dict or None:
      line:       field line the ITS was found on
      white_ire:  white bar level
      steps:      list of (start_us, luma, chroma_amp) for the staircase
      has_chroma: True if the staircase carries subcarrier (line 330 style),
                  enabling differential phase/gain measurement
      sc_packet:  (luma, chroma_amp) of the 0-level subcarrier packet at
                  30-39 us, or None
    """
    for line in lines:
        luma_white, _, _ = demod_region(field, line, 13, 7)
        if luma_white is None or not (75 < luma_white < 115):
            continue

        # 5-step staircase, risers at 40/44/48/52/56 us
        steps = []
        for us in (40.8, 44.8, 48.8, 52.8, 56.8):
            luma, amp, _ = demod_region(field, line, us, 2.4)
            if luma is None:
                break
            steps.append((us, luma, amp))
        if len(steps) < 5:
            continue
        lumas = [s[1] for s in steps]
        diffs = [lumas[i + 1] - lumas[i] for i in range(4)]
        if not (all(d > 5 for d in diffs) and lumas[-1] - lumas[0] > 50):
            continue

        has_chroma = all(s[2] > CHROMA_PRESENT for s in steps)

        sc_packet = None
        luma_sc, amp_sc, _ = demod_region(field, line, 31, 8)
        if luma_sc is not None and abs(luma_sc) < 10 and amp_sc > CHROMA_PRESENT:
            sc_packet = (luma_sc, amp_sc)

        return {
            "line": line, "white_ire": luma_white, "steps": steps,
            "has_chroma": has_chroma, "sc_packet": sc_packet,
        }
    return None


def detect_pal_line20_ref(field, lines=(20,)):
    """PAL line 331-style reference: ~50% luma with full-line subcarrier."""
    for line in lines:
        luma, amp, _ = demod_region(field, line, 14, 44)
        if luma is None:
            continue
        if 35 < luma < 60 and amp > 15:
            # Verify it is flat (not picture content)
            l1, _, _ = demod_region(field, line, 14, 10)
            l2, _, _ = demod_region(field, line, 46, 10)
            if abs(l1 - l2) < 6:
                return {"line": line, "luma": luma, "chroma": amp}
    return None


def detect_pal_grey50(field, lines=(13,)):
    """PAL 50% grey reference line (used by ld-decode's PAL VITS metrics)."""
    for line in lines:
        luma, amp, _ = demod_region(field, line, 16, 16)
        if luma is None:
            continue
        if 40 < luma < 60 and amp < CHROMA_ABSENT:
            return {"line": line, "luma": luma}
    return None


def detect_patterns(params, fields, max_fields=8):
    """Detect test patterns across the first few fields of a capture.

    Returns a dict:
      system:            "NTSC" or "PAL"
      colorbars:         {field_index: (first_line, last_line)} for fields
                         where bars were found
      ntsc_line19_vits:  list of field indices
      ntsc_line20_staircase: {field_index: info}
      ntsc_white_flag:   list of field indices
      pal_its:           {field_index: info}
      pal_line20_ref:    {field_index: info}
      pal_grey50:        {field_index: info}
    """
    det = {
        "system": params.system,
        "colorbars": {},
        "ntsc_line19_vits": [],
        "ntsc_line20_staircase": {},
        "ntsc_white_flag": [],
        "pal_its": {},
        "pal_line20_ref": {},
        "pal_grey50": {},
    }

    for f in fields[:max_fields]:
        i = f.field_index
        bars = detect_colorbars(f)
        if bars:
            det["colorbars"][i] = bars

        if params.system == "NTSC":
            if detect_ntsc_line19_vits(f):
                det["ntsc_line19_vits"].append(i)
            l20 = detect_ntsc_line20_staircase(f)
            if l20:
                det["ntsc_line20_staircase"][i] = l20
            if detect_ntsc_white_flag(f):
                det["ntsc_white_flag"].append(i)
        else:
            its = detect_pal_its(f)
            if its:
                det["pal_its"][i] = its
            ref = detect_pal_line20_ref(f)
            if ref:
                det["pal_line20_ref"][i] = ref
            grey = detect_pal_grey50(f)
            if grey:
                det["pal_grey50"][i] = grey

    return det


def summarize_patterns(det, fields):
    """Human-readable summary lines for a detect_patterns() result."""
    def parity(idxs):
        firsts = sorted(i for i in idxs if fields[i].isFirstField)
        seconds = sorted(i for i in idxs if not fields[i].isFirstField)
        parts = []
        if firsts:
            parts.append(f"first fields {firsts}")
        if seconds:
            parts.append(f"second fields {seconds}")
        return ", ".join(parts) if parts else "none"

    out = [f"System: {det['system']}"]

    if det["colorbars"]:
        ranges = {i: r for i, r in det["colorbars"].items()}
        example = next(iter(ranges.values()))
        out.append(f"Colour bars: lines {example[0]}-{example[1]} "
                   f"({parity(ranges.keys())})")
    else:
        out.append("Colour bars: not detected")

    if det["system"] == "NTSC":
        out.append(f"Line 19 VITS (70 IRE bar): "
                   f"{parity(det['ntsc_line19_vits']) if det['ntsc_line19_vits'] else 'not detected'}")
        if det["ntsc_line20_staircase"]:
            any_info = next(iter(det["ntsc_line20_staircase"].values()))
            chroma = "with chroma" if any_info["has_chroma"] else "luma only"
            out.append(f"Line 20 staircase ({chroma}): "
                       f"{parity(det['ntsc_line20_staircase'].keys())}")
        else:
            out.append("Line 20 staircase: not detected")
        out.append(f"White flag (line 11): "
                   f"{parity(det['ntsc_white_flag']) if det['ntsc_white_flag'] else 'not detected'}")
    else:
        if det["pal_its"]:
            infos = det["pal_its"]
            wc = [i for i, v in infos.items() if v["has_chroma"]]
            wo = [i for i, v in infos.items() if not v["has_chroma"]]
            line = next(iter(infos.values()))["line"]
            if wc:
                out.append(f"ITS staircase with chroma (line {line}): {parity(wc)}")
            if wo:
                out.append(f"ITS staircase, luma only (line {line}): {parity(wo)}")
        else:
            out.append("ITS staircase: not detected")
        if det["pal_line20_ref"]:
            info = next(iter(det["pal_line20_ref"].values()))
            out.append(f"50% subcarrier reference (line {info['line']}): "
                       f"{parity(det['pal_line20_ref'].keys())}")
        else:
            out.append("50% subcarrier reference: not detected")
        if det["pal_grey50"]:
            info = next(iter(det["pal_grey50"].values()))
            out.append(f"50% grey reference (line {info['line']}): "
                       f"{parity(det['pal_grey50'].keys())}")
        else:
            out.append("50% grey reference: not detected")

    return out


# ---------------------------------------------------------------------------
# PAL U/V folding
# ---------------------------------------------------------------------------

def pal_fold_uv(line_phasors, expected_hues):
    """Resolve the PAL V-switch and fold burst-relative phasors into U+jV.

    line_phasors: {line: [complex burst-relative phasor per measurement]}
        Each phasor is amplitude * exp(1j * radians(phase - burst_phase)).
    expected_hues: nominal hue in degrees (atan2(V, U)) per measurement
        column, or None for columns with no chroma (e.g. the white bar).

    On a +V line the true chroma vector is r * e^{j135deg}; on a -V line it
    is conj(r) * e^{j135deg}.  Which parity of field lines is +V cannot be
    determined from internal consistency (the wrong choice yields the
    conjugate rotated by -90deg for every line), so the assignment that
    best matches the expected hues wins.

    Returns (folded, v_even) where folded is {line: [complex U+jV per
    measurement]} and v_even is True when even field lines were chosen +V.
    """
    e135 = np.exp(1j * np.radians(135))

    def fold(v_even):
        out = {}
        for line, phasors in line_phasors.items():
            plus_v = (line % 2 == 0) == v_even
            out[line] = [
                (r if plus_v else np.conj(r)) * e135 for r in phasors
            ]
        return out

    def hue_error(folded):
        # Amplitude-weighted wrapped hue error against expectations
        total = 0.0
        for vals in folded.values():
            for k, v in enumerate(vals):
                if expected_hues[k] is None or np.abs(v) < 2.0:
                    continue
                err = phase_diff(np.degrees(np.angle(v)), expected_hues[k])
                total += np.abs(v) * abs(err)
        return total

    cand = {ve: fold(ve) for ve in (True, False)}
    v_even = min(cand, key=lambda ve: hue_error(cand[ve]))
    return cand[v_even], v_even


# ---------------------------------------------------------------------------
# CLI: report detected patterns
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} file.tbc", file=sys.stderr)
        return 2
    params, fields, _ = load_tbc(sys.argv[1])
    print(f"{sys.argv[1]}: {params!r}, {len(fields)} fields")
    det = detect_patterns(params, fields)
    for line in summarize_patterns(det, fields):
        print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
