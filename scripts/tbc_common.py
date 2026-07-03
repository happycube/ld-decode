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


# ---------------------------------------------------------------------------
# NTC-7 VITS (broadcast-style test lines, e.g. THX-mastered discs)
#
# Composite (line 20, one field parity): 100 IRE line bar to ~30 us, 2T sin^2
# pulse, modulated 12.5T chroma pulse (~37 us), 5-step modulated staircase.
# Combination (line 20, other parity): short white bar, 6-packet multiburst
# on a 50 IRE pedestal (0.5/1/2/3/3.58/4.2 MHz, 50 IRE p-p), then a 3-level
# modulated pedestal (20/40/80 IRE p-p subcarrier on 50 IRE).
# ---------------------------------------------------------------------------

NTC7_MULTIBURST_FREQS = (0.5, 1.0, 2.0, 3.0, 3.58, 4.2)
NTC7_PEDESTAL_PP = (20.0, 40.0, 80.0)


def line_segment_ire(field, line, start_us, duration_us):
    """Raw waveform of part of one line, in IRE."""
    p = field.params
    ire = field.line_ire(line)
    s0 = int(start_us * p.sample_rate_mhz)
    s1 = min(int((start_us + duration_us) * p.sample_rate_mhz), len(ire))
    return ire[s0:s1]


def segment_freq_pp(seg, fs_mhz):
    """Dominant frequency (MHz) and sine peak-to-peak (IRE) of a segment.

    p-p is estimated as 2*sqrt(2)*rms, which is exact for a sine at any
    sampling phase (unlike sample min/max, which underestimates near fs/4).
    """
    if seg is None or len(seg) < 16:
        return 0.0, 0.0
    y = seg - np.mean(seg)
    pp = float(2.0 * np.sqrt(2.0) * np.std(y))
    if pp < 2.0:
        return 0.0, pp
    spec = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    k = int(np.argmax(spec[1:])) + 1
    if 1 <= k < len(spec) - 1:  # quadratic peak interpolation
        a, b, c = spec[k - 1], spec[k], spec[k + 1]
        denom = a - 2 * b + c
        if abs(denom) > 1e-12:
            k = k + 0.5 * (a - c) / denom
    return float(k * fs_mhz / len(y)), pp


def sine_fit_pp(seg, fs_mhz, freq_mhz):
    """Peak-to-peak of a sine at freq_mhz, by least squares (DC + sin + cos).

    Exact for a clean sine at any sampling phase and for fractional cycle
    counts, unlike min/max or rms estimators.
    """
    n = np.arange(len(seg))
    w = 2 * np.pi * freq_mhz / fs_mhz
    M = np.column_stack([np.ones(len(seg)), np.cos(w * n), np.sin(w * n)])
    coef, *_ = np.linalg.lstsq(M, seg, rcond=None)
    return 2.0 * float(np.hypot(coef[1], coef[2]))


def measure_ntc7_multiburst(field, line=20, start_us=16.5, end_us=45.0):
    """Locate multiburst packets on one line.

    Returns [(center_us, freq_mhz, pp_ire)], one entry per packet.  Sliding
    windows are grouped while the dominant frequency stays put; windows
    straddling two packets read an intermediate frequency and break the run.
    Each packet's amplitude comes from a sine fit over the packet extent,
    with the frequency refined to maximise the fitted amplitude.
    """
    fs = field.params.sample_rate_mhz
    win, step = 2.5, 0.5
    meas = []
    t = start_us
    while t + win <= end_us:
        f, pp = segment_freq_pp(line_segment_ire(field, line, t, win), fs)
        meas.append((t + win / 2, f, pp))
        t += step

    # Same packet while the frequency stays put.  The tolerance needs an
    # absolute floor: at 0.5 MHz a 2.5 us window holds ~1.25 cycles and the
    # FFT estimate jitters by ~0.15 MHz window to window.
    def same_packet(f_prev, f_new):
        return abs(f_new - f_prev) <= max(0.20, 0.08 * f_prev)

    groups, cur = [], []
    for m in meas:
        if m[2] > 12 and m[1] > 0.2:
            if cur and not same_packet(cur[-1][1], m[1]):
                groups.append(cur)
                cur = []
            cur.append(m)
        else:
            if cur:
                groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)

    packets = []
    for grp in groups:
        if len(grp) < 2:
            continue
        # Packets are short (2-8 cycles between pedestal stretches), so most
        # sliding windows straddle an edge.  Fit a tight window centred on
        # the max-energy window only, refining the frequency for best fit.
        # Energy-weighted centroid locates the packet centre more stably
        # than the single max-energy window.
        wsum = sum(m[2] for m in grp)
        center = sum(m[0] * m[2] for m in grp) / wsum
        f0 = float(np.median([m[1] for m in grp]))
        # Keep >=1.4 cycles in the fit window, or the frequency search can
        # drift low and absorb the packet edges into an inflated amplitude.
        win_fit = 3.0 if f0 < 0.8 else 2.0
        seg = line_segment_ire(field, line, center - win_fit / 2, win_fit)
        fmin = max(f0 * 0.8, 1.4 / win_fit)
        fmax = max(f0 * 1.25, fmin * 1.15)
        best_f, best_pp = f0, 0.0
        for f in np.linspace(fmin, fmax, 19):
            pp = sine_fit_pp(seg, fs, f)
            if pp > best_pp:
                best_f, best_pp = f, pp
        packets.append((center, best_f, best_pp))
    return packets


def measure_ntc7_pedestal(field, line=20, start_us=45.5, end_us=59.5):
    """Measure the 3-level modulated pedestal (nominal 20/40/80 IRE p-p).

    Returns [(center_us, luma, chroma_pp, phase_deg)] for the three packets
    (phase is line-start-referenced, comparable to burst_ref on this line),
    or [] if three increasing levels are not found.
    """
    win, step = 1.5, 0.25
    ts, amps = [], []
    t = start_us
    while t + win <= end_us:
        _, amp, _ = demod_region(field, line, t, win)
        ts.append(t + win / 2)
        amps.append(amp if amp is not None else 0.0)
        t += step
    if len(ts) < 8:
        return []
    ts, amps = np.array(ts), np.array(amps)

    # The two largest upward envelope steps split the region into 3 packets.
    lag = max(1, int(round(1.0 / step)))
    jumps = amps[lag:] - amps[:-lag]
    cuts = []
    for idx in np.argsort(jumps)[::-1]:
        tcut = ts[idx] + 0.5
        if jumps[idx] <= 2.0:
            break
        if all(abs(tcut - c) > 2.0 for c in cuts):
            cuts.append(tcut)
        if len(cuts) == 2:
            break
    if len(cuts) != 2:
        return []

    out = []
    bounds = [start_us] + sorted(cuts) + [end_us]
    for a, b in zip(bounds[:-1], bounds[1:]):
        if b - a < 1.2:
            return []
        mid, span = (a + b) / 2, (b - a) * 0.5
        luma, amp, phase = demod_region(field, line, mid - span / 2, span)
        if luma is None:
            return []
        out.append((mid, luma, 2 * amp, phase))
    if not all(out[i + 1][2] > out[i][2] * 1.2 for i in range(2)):
        return []
    return out


def detect_ntsc_ntc7_composite(field):
    """NTC-7 composite VITS on line 20 (bar + 12.5T pulse + mod staircase).

    Returns dict or None.  The staircase itself is also reported through
    detect_ntsc_line20_staircase; this adds the modulated 12.5T check that
    distinguishes NTC-7 from the plain LD staircase VITS.
    """
    bar, bar_chroma, _ = demod_region(field, 20, 16, 12)
    if bar is None or not (90 < bar < 115) or bar_chroma > CHROMA_ABSENT:
        return None
    stair = detect_ntsc_line20_staircase(field)
    if not stair or not stair["has_chroma"]:
        return None

    # Modulated 12.5T pulse near 37 us, riding at/near blanking level
    best = None
    t = 32.0
    while t <= 40.0:
        luma, amp, _ = demod_region(field, 20, t, 2.0)
        if luma is not None and luma < 70 and (best is None or amp > best[1]):
            best = (t + 1.0, amp)
        t += 0.5
    if best is None or best[1] < 10:
        return None
    return {"bar_ire": bar, "pulse_us": best[0], "pulse_pp": 2 * best[1],
            "staircase": stair}


def detect_ntsc_ntc7_combination(field):
    """NTC-7 combination VITS on line 20 (multiburst + modulated pedestal).

    Returns dict with "packets" (multiburst) and "pedestal" (may be []) or
    None.
    """
    bar, _, _ = demod_region(field, 20, 12.5, 2.5)
    if bar is None or not (85 < bar < 115):
        return None
    # Everything after the short bar rides a ~50 IRE pedestal; this also
    # rejects the composite signal (100 IRE bar through ~30 us).
    for t in (20, 26, 32, 41, 50, 56):
        luma, _, _ = demod_region(field, 20, t, 2.0)
        if luma is None or not (30 < luma < 70):
            return None

    packets = measure_ntc7_multiburst(field)
    if len(packets) < 4:
        return None
    freqs = [p[1] for p in packets]
    if max(freqs) < 3.0 or min(freqs) > 1.2:
        return None
    return {"bar_ire": bar, "packets": packets,
            "pedestal": measure_ntc7_pedestal(field)}


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
      ntsc_ntc7_composite:   {field_index: info}
      ntsc_ntc7_combination: {field_index: info}
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
        "ntsc_ntc7_composite": {},
        "ntsc_ntc7_combination": {},
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
            ntc7c = detect_ntsc_ntc7_composite(f)
            if ntc7c:
                det["ntsc_ntc7_composite"][i] = ntc7c
            ntc7m = detect_ntsc_ntc7_combination(f)
            if ntc7m:
                det["ntsc_ntc7_combination"][i] = ntc7m
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
        out.append(f"NTC-7 composite (line 20): "
                   f"{parity(det['ntsc_ntc7_composite'].keys()) if det['ntsc_ntc7_composite'] else 'not detected'}")
        if det["ntsc_ntc7_combination"]:
            n_pkts = max(len(v["packets"])
                         for v in det["ntsc_ntc7_combination"].values())
            has_ped = any(v["pedestal"]
                          for v in det["ntsc_ntc7_combination"].values())
            desc = f"{n_pkts}-packet multiburst"
            if has_ped:
                desc += " + modulated pedestal"
            out.append(f"NTC-7 combination (line 20, {desc}): "
                       f"{parity(det['ntsc_ntc7_combination'].keys())}")
        else:
            out.append("NTC-7 combination (line 20): not detected")
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
