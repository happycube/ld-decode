#!/usr/bin/env python3
"""Shared TBC/CVBS loading, chroma demodulation, and test-pattern detection.

Used by the analysis scripts (smpte_analyze.py, differential_phase.py).
Supports NTSC and PAL .tbc files (with companion .tbc.db) and CVBS
.composite files (with companion .meta, CVBS_U16_4FSC encoding) — see
load_video().

Chroma demodulation here is system-independent: both NTSC and PAL output
is sampled at exactly 4x the colour subcarrier, so the subcarrier sits at
fs/4 and can be demodulated with a fixed quadrature reference.  Absolute
phase is only meaningful per-line (PAL output subcarrier phase rotates
line to line), so phase measurements are referenced to the colour burst
of the same line.

Run directly to report which test patterns are present:

    python analysis/tbc_common.py file.tbc
    python analysis/tbc_common.py file.composite
"""

import mmap
import os
import sqlite3
import sys

import numpy as np


# ---------------------------------------------------------------------------
# TBC loading
# ---------------------------------------------------------------------------

# CVBS 4fsc field geometry (see cvbs-file-format-specification/).  Levels
# are the spec's 10-bit presets; active/burst windows match what ld-decode
# writes to .tbc.db for the same 4fsc line convention (0H at +0.8).
CVBS_GEOMETRY = {
    "NTSC": {
        "field_width": 910, "field_height": 263,
        "sample_rate": 4 * 315e6 / 88, "frame_samples": 477750,
        "active": (134, 894), "burst": (74, 110), "phase_cycle": 4,
        "levels": {"blanking": 240, "black": 282, "white": 800},
    },
    "PAL": {
        "field_width": 1135, "field_height": 313,
        "sample_rate": 17734475.0, "frame_samples": 709379,
        "active": (185, 1107), "burst": (98, 138), "phase_cycle": 8,
        "levels": {"blanking": 256, "black": 256, "white": 844},
    },
}


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

    @classmethod
    def for_cvbs(cls, system, black_level=None):
        """Build params for a CVBS .composite file from the spec presets."""
        g = CVBS_GEOMETRY[system]
        p = cls.__new__(cls)
        p.system = system
        p.field_width = g["field_width"]
        p.field_height = g["field_height"]
        p.video_sample_rate = g["sample_rate"]
        p.sample_rate_mhz = p.video_sample_rate / 1e6
        lv = g["levels"]
        p.white_16b_ire = lv["white"] * 64
        p.blanking_16b_ire = lv["blanking"] * 64
        p.black_16b_ire = (black_level if black_level is not None
                           else lv["black"]) * 64
        p.active_video_start, p.active_video_end = g["active"]
        p.colour_burst_start, p.colour_burst_end = g["burst"]
        p.capture_id = None
        p.out_scale = (p.white_16b_ire - p.blanking_16b_ire) / 100.0
        p.field_samples = p.field_width * p.field_height
        return p

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


def _cvbs_extract_field(data, frame_idx, parity, params):
    """One field of a CVBS frame as a flat field_width*field_height array.

    NTSC frames are orthogonal (910 samples/line, field A 263 lines then
    field B 262).  The PAL lattice is not line-locked: a line averages
    709379/625 = 1135.0064 samples, and line syncs sit on the integer
    line grid with the second field's line 1 at frame line 313 (see
    Field.downscale_cvbs), so each field line k (0-based) starts at
    lattice index ceil((k + parity*313) * 709379/625), computed with
    exact integer math.  Rows are 1135 samples wide, matching the PAL TBC
    line convention; the sub-sample start offset (< 1 sample) cancels out
    of burst-relative phase measurements.

    Reads run past the frame boundary into the next frame where the signal
    genuinely continues (NTSC field B line 263, PAL field B line 313);
    only samples past the end of the file are padded with blanking.
    """
    fw, fh = params.field_width, params.field_height
    out = np.full(fh * fw, params.blanking_16b_ire, dtype=np.uint16)
    f0 = frame_idx * CVBS_GEOMETRY[params.system]["frame_samples"]

    if params.system == "NTSC":
        starts = [f0 + (parity * 263 + k) * fw for k in range(fh)]
    else:
        # ceil((k + 313*parity) * 709379/625), integer-exact
        starts = [f0 - (-(k + 313 * parity) * 709379 // 625)
                  for k in range(fh)]

    for k, s in enumerate(starts):
        e = min(s + fw, len(data))
        if s >= len(data):
            break
        out[k * fw: k * fw + (e - s)] = data[s:e]
    return out


def load_cvbs(path, max_fields=None):
    """Load a CVBS .composite file (NTSC or PAL, CVBS_U16_4FSC).

    Accepts the .composite path or the basename.  Returns (params, fields,
    data) with the same interfaces as load_tbc().

    Field phase IDs are reconstructed from position: the spec requires the
    file to open on a first field starting the colour sequence (NTSC colour
    frame A / PAL sequence frame 1), so field i has phase ID i % cycle + 1.
    """
    base = path[:-len(".composite")] if path.endswith(".composite") else path
    comp_path, meta_path = base + ".composite", base + ".meta"
    if not os.path.exists(meta_path):
        raise FileNotFoundError(f"Metadata not found: {meta_path}")
    if not os.path.exists(comp_path):
        raise FileNotFoundError(f"CVBS file not found: {comp_path}")

    con = sqlite3.connect(meta_path)
    row = con.execute(
        "SELECT preset, sample_encoding_preset, black_level "
        "FROM cvbs_file LIMIT 1").fetchone()
    con.close()
    if row is None:
        raise RuntimeError(f"No cvbs_file record in {meta_path}")
    system, encoding, black_level = row
    if encoding != "CVBS_U16_4FSC":
        raise RuntimeError(f"Unsupported CVBS encoding: {encoding}")
    if system not in CVBS_GEOMETRY:
        raise RuntimeError(f"Unsupported CVBS preset: {system}")

    params = CaptureParams.for_cvbs(system, black_level)
    phase_cycle = CVBS_GEOMETRY[system]["phase_cycle"]

    fd = os.open(comp_path, os.O_RDONLY)
    try:
        mm = mmap.mmap(fd, os.fstat(fd).st_size, access=mmap.ACCESS_READ)
        data = np.frombuffer(mm, dtype=np.uint16)
    finally:
        os.close(fd)

    n_fields = 2 * (len(data) // CVBS_GEOMETRY[system]["frame_samples"])
    if max_fields is not None:
        n_fields = min(n_fields, max_fields)

    fields = []
    for i in range(n_fields):
        arr = _cvbs_extract_field(data, i // 2, i % 2, params)
        record = {"field_id": i, "is_first_field": i % 2 == 0,
                  "field_phase_id": i % phase_cycle + 1}
        f = TBCField(arr, 0, params, record)
        f.field_index = i
        fields.append(f)
    return params, fields, data


def load_video(path, max_fields=None):
    """Load a .tbc or CVBS .composite file, dispatching on the extension
    (or, for a bare basename, on which companion metadata file exists)."""
    if path.endswith(".composite"):
        return load_cvbs(path, max_fields)
    if path.endswith(".tbc"):
        return load_tbc(path, max_fields)
    if os.path.exists(path + ".meta"):
        return load_cvbs(path, max_fields)
    return load_tbc(path, max_fields)


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


def average_line_ire(fields, line):
    """Coherent average of one TBC line across fields (noise drops ~sqrt(N))."""
    acc = None
    for f in fields:
        y = f.line_ire(line)
        acc = y.astype(np.float64) if acc is None else acc + y
    return acc / len(fields)


def measure_ntc7_transients(fields, line=20):
    """NTC-7 composite transients (NTSC): bar 12-30 us, 2T ~33.9 us.

    See measure_transients for the returned metrics.
    """
    return measure_transients(
        fields, line,
        bar_win=(18.0, 28.0), baseline_win=(31.0, 33.0),
        pulse_win=(33.0, 35.0), lead_win=(11.0, 13.5), trail_win=(29.0, 31.5),
    )


def measure_pal_its_transients(fields, line=19):
    """PAL CCIR ITS transients: white bar ~11-21 us, 2T pulse ~25.2 us.

    Both field parities carry the bar and pulse.  See measure_transients.
    (PAL 2T nominal HAD is 200 ns vs NTSC's 250 ns.)
    """
    return measure_transients(
        fields, line,
        bar_win=(13.0, 19.0), baseline_win=(22.2, 24.4),
        pulse_win=(24.4, 26.4), lead_win=(9.8, 12.3), trail_win=(20.2, 22.7),
    )


def measure_transients(fields, line, bar_win, baseline_win, pulse_win,
                       lead_win, trail_win):
    """Transient-response metrics from an averaged bar + 2T pulse line.

    Returns a dict:
      bar_ire            bar top level
      pulse_ratio        2T pulse height / bar height (ideal 1.0)
      pulse_had_ns       pulse half-amplitude duration
      pulse_ring_pct     largest lobe within +/-(0.4..1.8) us of the pulse,
                         as % of pulse height (ringing around the pulse)
      edge_rise_ns       bar leading-edge 10-90% time
      edge_fall_ns       bar trailing-edge 90-10% time
      edge_overshoot_pct max excursion beyond the settled levels within
                         1.5 us after each edge, as % of the bar step
                         (worst of leading overshoot / trailing undershoot)
      edge_ring_pct      largest subsequent lobe after the first overshoot
      n_fields           fields averaged
    """
    if not fields:
        return None
    fs = fields[0].params.sample_rate_mhz
    y = average_line_ire(fields, line)
    idx = lambda us: int(round(us * fs))
    seg = lambda a, b: y[idx(a):idx(b)]

    baseline = float(np.mean(seg(*baseline_win)))
    bar = float(np.mean(seg(*bar_win))) - baseline
    if bar < 50:
        return None

    # --- 2T pulse ---
    pw = seg(*pulse_win)
    pk = int(np.argmax(pw))
    pk_us = pulse_win[0] + pk / fs
    pulse = float(pw[pk]) - baseline
    half = baseline + pulse / 2
    # half-amplitude duration via interpolated crossings around the peak
    i = pk
    while i > 0 and pw[i] > half:
        i -= 1
    lo = i + (half - pw[i]) / (pw[i + 1] - pw[i]) if pw[i + 1] != pw[i] else i
    i = pk
    while i < len(pw) - 1 and pw[i] > half:
        i += 1
    hi = i - 1 + (pw[i - 1] - half) / (pw[i - 1] - pw[i]) if pw[i - 1] != pw[i] else i
    had_ns = (hi - lo) / fs * 1000.0

    ring = np.concatenate([seg(pk_us - 1.8, pk_us - 0.4), seg(pk_us + 0.4, pk_us + 1.8)])
    pulse_ring = float(np.max(np.abs(ring - baseline))) / pulse * 100.0

    # --- bar edges ---
    def edge_metrics(a_us, b_us, rising):
        e = seg(a_us, b_us)
        lo_l, hi_l = baseline, baseline + bar
        # 50% crossing
        thr = baseline + bar / 2
        xs = np.nonzero((e[:-1] < thr) == rising)[0]
        xs = [i for i in xs if (e[i + 1] >= thr) == rising]
        if not xs:
            return None
        c = xs[0] if rising else xs[-1]
        # 10-90% time around the crossing
        t10, t90 = baseline + 0.1 * bar, baseline + 0.9 * bar
        i = c
        while i > 0 and ((e[i] > t10) if rising else (e[i] < t90)):
            i -= 1
        j = c
        while j < len(e) - 1 and ((e[j] < t90) if rising else (e[j] > t10)):
            j += 1
        rise_ns = (j - i) / fs * 1000.0
        # settled side after the transition
        post = e[j + int(0.25 * fs):j + int(1.75 * fs)]
        settled = hi_l if rising else lo_l
        if len(post) < 4:
            return None
        dev = (post - settled) * (1 if rising else -1)
        overshoot = float(np.max(dev)) / bar * 100.0
        # ringing: largest opposite-going lobe after the first extremum
        first_ext = int(np.argmax(dev))
        ring_pct = 0.0
        if first_ext + 2 < len(dev):
            ring_pct = float(np.max(np.abs(dev[first_ext + 1:]))) / bar * 100.0
        return rise_ns, overshoot, ring_pct

    lead = edge_metrics(lead_win[0], lead_win[1], True)
    trail = edge_metrics(trail_win[0], trail_win[1], False)
    if lead is None or trail is None:
        return None

    return {
        "bar_ire": bar,
        "pulse_ratio": pulse / bar,
        "pulse_had_ns": had_ns,
        "pulse_ring_pct": pulse_ring,
        "edge_rise_ns": lead[0],
        "edge_fall_ns": trail[0],
        "edge_overshoot_pct": max(lead[1], trail[1]),
        "edge_ring_pct": max(lead[2], trail[2]),
        "n_fields": len(fields),
    }


# CCIR Rec. 567 unified noise weighting (single time constant, 245 ns).
# See references/README.md in the repo root for sources.
UNIFIED_WEIGHTING_TAU = 245e-9


def weighted_psnr(fields, line, start_us, duration_us):
    """Broadcast-style weighted PSNR of a flat region (dB vs 100 IRE p-p).

    Each field's segment is detrended with a linear fit (tilt null); the
    noise power spectra are averaged across fields, then the CCIR-567
    unified weighting and the system band-limit (4.2 MHz NTSC / 5.0 MHz
    PAL) are applied in the frequency domain.  Returns
    (weighted_db, unweighted_db, mean_ire) or None.
    """
    if not fields:
        return None
    p = fields[0].params
    fs_hz = p.sample_rate_mhz * 1e6
    lpf_hz = 4.2e6 if p.system == "NTSC" else 5.0e6

    acc, n, ire_sum = None, None, 0.0
    for f in fields:
        seg = line_segment_ire(f, line, start_us, duration_us)
        if n is None:
            n = len(seg)
        if len(seg) != n or n < 64:
            return None
        x = np.arange(n)
        noise = seg - np.polyval(np.polyfit(x, seg, 1), x)
        spec = np.abs(np.fft.rfft(noise)) ** 2
        acc = spec if acc is None else acc + spec
        ire_sum += float(np.mean(seg))
    acc /= len(fields)

    freqs = np.fft.rfftfreq(n, 1.0 / fs_hz)
    band = (freqs <= lpf_hz) & ((freqs >= 10e3) | (freqs == 0))
    w2 = 1.0 / (1.0 + (2 * np.pi * freqs * UNIFIED_WEIGHTING_TAU) ** 2)
    scale = np.full(len(acc), 2.0)
    scale[0] = 1.0
    if n % 2 == 0:
        scale[-1] = 1.0

    ms_flat = np.sum(acc * band * scale) / (n * n)
    ms_w = np.sum(acc * band * w2 * scale) / (n * n)
    if ms_w <= 0 or ms_flat <= 0:
        return None
    return (20 * np.log10(100.0 / np.sqrt(ms_w)),
            20 * np.log10(100.0 / np.sqrt(ms_flat)),
            ire_sum / len(fields))


def chroma_am_pm_noise(fields, line, start_us, duration_us):
    """Chrominance AM/PM noise from a flat subcarrier region (VM700-style).

    Demodulates the region at fs/4, rotates by the mean phasor so the real
    axis is amplitude (AM) and the imaginary axis is phase (PM), and
    accumulates the two noise spectra across fields.  There is no CCIR
    weighting curve for chrominance -- broadcast practice band-limits the
    demodulated noise instead -- so results are reported for both the
    broadcast band (10-500 kHz) and wideband (10 kHz - 1.3 MHz).

    Returns dict:
      sc_pp                  subcarrier packet amplitude (IRE p-p)
      am_snr_band/_wide      packet p-p vs rms envelope noise, dB
      pm_deg_band/_wide      rms phase noise, degrees
      n_fields
    or None.
    """
    if not fields:
        return None
    p = fields[0].params
    fs_hz = p.sample_rate_mhz * 1e6

    acc_am, acc_pm, n = None, None, None
    amp_sum = 0.0
    for f in fields:
        seg = line_segment_ire(f, line, start_us, duration_us)
        if n is None:
            n = len(seg)
        if len(seg) != n or n < 96:
            return None
        x = np.arange(n)
        seg = seg - np.polyval(np.polyfit(x, seg, 1), x)  # remove luma tilt
        c = seg * np.exp(-0.5j * np.pi * (x + int(start_us * p.sample_rate_mhz)))
        # kill the 2*fsc demod image and out-of-band junk
        C = np.fft.fft(c)
        fr = np.fft.fftfreq(n, 1.0 / fs_hz)
        C[np.abs(fr) > 1.3e6] = 0
        c = np.fft.ifft(C)
        m = np.mean(c)
        if np.abs(m) < 1.0:  # need a real subcarrier packet (>= ~4 IRE p-p)
            return None
        d = c * np.conj(m) / np.abs(m)
        am = np.real(d) - np.abs(m)          # envelope/2 fluctuation, IRE
        pm = np.imag(d) / np.abs(m)          # radians
        sa = np.abs(np.fft.rfft(am)) ** 2
        sp = np.abs(np.fft.rfft(pm)) ** 2
        acc_am = sa if acc_am is None else acc_am + sa
        acc_pm = sp if acc_pm is None else acc_pm + sp
        amp_sum += 4 * np.abs(m)             # packet p-p

    acc_am /= len(fields)
    acc_pm /= len(fields)
    sc_pp = amp_sum / len(fields)

    freqs = np.fft.rfftfreq(n, 1.0 / fs_hz)
    scale = np.full(len(acc_am), 2.0)
    scale[0] = 1.0
    if n % 2 == 0:
        scale[-1] = 1.0

    def band_rms(acc, lo, hi):
        mask = (freqs >= lo) & (freqs <= hi)
        return np.sqrt(np.sum(acc * mask * scale) / (n * n))

    out = {"sc_pp": sc_pp, "n_fields": len(fields)}
    for tag, lo, hi in (("band", 10e3, 500e3), ("wide", 10e3, 1.3e6)):
        rms_env = 2 * band_rms(acc_am, lo, hi)      # envelope noise, IRE rms
        rms_pm = band_rms(acc_pm, lo, hi)           # radians rms
        out[f"am_snr_{tag}"] = (20 * np.log10(sc_pp / rms_env)
                                if rms_env > 0 else None)
        out[f"pm_deg_{tag}"] = np.degrees(rms_pm)
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
        print(f"Usage: {sys.argv[0]} file.tbc|file.composite", file=sys.stderr)
        return 2
    if sys.argv[1].endswith(".composite"):
        params, fields, _ = load_cvbs(sys.argv[1])
    else:
        params, fields, _ = load_tbc(sys.argv[1])
    print(f"{sys.argv[1]}: {params!r}, {len(fields)} fields")
    det = detect_patterns(params, fields)
    for line in summarize_patterns(det, fields):
        print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
