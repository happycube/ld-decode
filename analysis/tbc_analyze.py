#!/usr/bin/env python3
"""Standalone TBC analyzer: reads .tbc files and runs CombNTSC metrics.

Loads field data from raw .tbc files and their companion .tbc.db SQLite
databases, then runs the CombNTSC comb filter analysis to produce Line 19
color burst metrics (level, phase, SNR) for each field.
"""

import argparse
import mmap
import os
import sqlite3
import sys

import numpy as np

# Allow running from the analysis/ directory or project root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lddecode.metrics import CombNTSC
from lddecode.dsp import rms


class CaptureParams:
    """System parameters read from the capture table."""

    def __init__(self, db_path):
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM capture LIMIT 1").fetchone()
        if row is None:
            raise RuntimeError(f"No capture record found in {db_path}")

        self.system = row["system"]
        self.field_width = row["field_width"]
        self.field_height = row["field_height"]
        self.video_sample_rate = row["video_sample_rate"]
        self.white_16b_ire = row["white_16b_ire"]
        self.black_16b_ire = row["black_16b_ire"]
        self.active_video_start = row["active_video_start"]
        self.active_video_end = row["active_video_end"]
        self.colour_burst_start = row["colour_burst_start"]
        self.colour_burst_end = row["colour_burst_end"]
        self.capture_id = row["capture_id"]

        self.blanking_16b_ire = row["blanking_16b_ire"]
        self.sample_rate_mhz = self.video_sample_rate / 1e6
        self.out_scale = (self.white_16b_ire - self.blanking_16b_ire) / 100.0
        self.field_samples = self.field_width * self.field_height

        con.close()

    def __repr__(self):
        return (
            f"CaptureParams(system={self.system}, "
            f"field={self.field_width}x{self.field_height}, "
            f"sample_rate={self.sample_rate_mhz:.4f} MHz, "
            f"white={self.white_16b_ire}, black={self.black_16b_ire})"
        )


class FieldRecord:
    """Per-field metadata from the field_record table."""

    def __init__(self, field_id, is_first_field, field_phase_id):
        self.field_id = field_id
        self.is_first_field = is_first_field
        self.field_phase_id = field_phase_id


def load_field_records(db_path, capture_id):
    """Load all field records ordered by field_id."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT field_id, is_first_field, field_phase_id "
        "FROM field_record WHERE capture_id = ? ORDER BY field_id",
        (capture_id,),
    ).fetchall()
    con.close()

    return [
        FieldRecord(
            field_id=r["field_id"],
            is_first_field=bool(r["is_first_field"]),
            field_phase_id=r["field_phase_id"],
        )
        for r in rows
    ]


class TBCField:
    """Lightweight field object satisfying the CombNTSC interface.

    Provides: dspicture, fieldPhaseID, isFirstField, out_scale,
    lineslice_tbc(), output_to_ire().
    """

    def __init__(self, mmap_array, field_index, params, record):
        offset = field_index * params.field_samples
        self.dspicture = mmap_array[offset : offset + params.field_samples]
        self.fieldPhaseID = record.field_phase_id
        self.isFirstField = record.is_first_field
        self.out_scale = params.out_scale
        self._params = params

    def lineslice_tbc(self, line, start_us, duration_us):
        p = self._params
        line_start = (line - 1) * p.field_width
        s0 = line_start + int(start_us * p.sample_rate_mhz)
        s1 = line_start + int((start_us + duration_us) * p.sample_rate_mhz)
        return slice(s0, s1)

    def output_to_ire(self, data):
        return (data.astype(np.float64) - self._params.blanking_16b_ire) / self.out_scale


def run_analysis(tbc_path, max_fields=None, verbose=False):
    """Run CombNTSC analysis on a .tbc file."""
    db_path = tbc_path + ".db"
    if not os.path.exists(db_path):
        print(f"Error: database not found: {db_path}", file=sys.stderr)
        return 1
    if not os.path.exists(tbc_path):
        print(f"Error: TBC file not found: {tbc_path}", file=sys.stderr)
        return 1

    params = CaptureParams(db_path)
    records = load_field_records(db_path, params.capture_id)

    if params.system != "NTSC":
        print(f"Error: CombNTSC analysis only supports NTSC (got {params.system})",
              file=sys.stderr)
        return 1

    if verbose:
        print(f"Capture: {params}")
        print(f"Fields in database: {len(records)}")

    # Memory-map the TBC file as uint16 array.
    fd = os.open(tbc_path, os.O_RDONLY)
    try:
        file_size = os.fstat(fd).st_size
        mm = mmap.mmap(fd, file_size, access=mmap.ACCESS_READ)
        tbc_data = np.frombuffer(mm, dtype=np.uint16)
    finally:
        os.close(fd)

    expected_samples = len(records) * params.field_samples
    if len(tbc_data) < expected_samples:
        print(
            f"Warning: TBC file has {len(tbc_data)} samples, "
            f"expected {expected_samples} for {len(records)} fields",
            file=sys.stderr,
        )

    n_fields = len(records)
    if max_fields is not None:
        n_fields = min(n_fields, max_fields)

    # Build TBCField objects.
    fields = []
    for i in range(n_fields):
        fields.append(TBCField(tbc_data, i, params, records[i]))

    # Print header.
    print(f"{'Field':>5}  {'1st?':>4}  {'Phase':>5}  {'Mode':>4}  "
          f"{'Burst70':>8}  {'Phase':>7}  {'SNR_dB':>7}  "
          f"{'BurstRMS':>8}  {'Burst0':>8}  {'MedPhase':>8}")
    print("-" * 90)

    for i, f in enumerate(fields):
        # 1D analysis: single field.
        c1d = CombNTSC([f])
        level_1d, phase_1d, snr_1d = c1d.calcLine19Info()
        burst_rms = measure_burst(f, params)
        med_phase_1d = calc_median_burst_phase(c1d, params)

        print(format_row(records[i], "1D", level_1d, phase_1d, snr_1d,
                         burst_rms, med_phase=med_phase_1d))

        # 3D analysis: need a same-parity field from the previous frame
        # (2 fields back for same parity).
        if i >= 2:
            prev = fields[i - 2]
            if prev.isFirstField == f.isFirstField:
                c3d = CombNTSC([prev, f])
                level_3d, phase_3d, snr_3d = c3d.calcLine19Info()
                burst0 = measure_burst_3d(f, prev, params)
                med_phase_3d = calc_median_burst_phase(c3d, params)

                print(format_row(records[i], "3D", level_3d, phase_3d, snr_3d,
                                 burst_rms, burst0, med_phase_3d))

    return 0


def calc_median_burst_phase(comb, params):
    """Compute median color burst phase across all active lines."""
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
        if amp < 0.1:
            continue

        phase = np.arctan2(mean_i, mean_q) * 180 / np.pi
        if phase < 0:
            phase += 360
        phases.append(phase)

    return np.median(phases) if phases else None


def measure_burst(field, params):
    """Measure RMS of line 19 color burst (always works, no VITS check)."""
    sl = field.lineslice_tbc(19, 4.7 + 0.8, 2.4)
    data = field.dspicture[sl].astype(np.float64)
    return rms(data) / field.out_scale


def measure_burst_3d(field, prev_field, params):
    """Measure 3D burst-zero level (inter-frame burst cancellation)."""
    sl = field.lineslice_tbc(19, 4.7 + 0.8, 2.4)
    diff = (
        field.dspicture[sl].astype(np.float64)
        - prev_field.dspicture[sl].astype(np.float64)
    ) / 2
    return np.sqrt(2) * rms(diff) / field.out_scale


def format_row(record, mode, level, phase, snr, burst_rms=None, burst0=None,
               med_phase=None):
    """Format a single results row."""
    first = "yes" if record.is_first_field else "no"

    def fmt(val, width, decimals):
        if val is not None:
            return f"{val:>{width}.{decimals}f}"
        return f"{'---':>{width}}"

    return (
        f"{record.field_id:>5}  {first:>4}  {record.field_phase_id:>5}  "
        f"{mode:>4}  {fmt(level, 8, 4)}  {fmt(phase, 7, 2)}  {fmt(snr, 7, 2)}  "
        f"{fmt(burst_rms, 8, 4)}  {fmt(burst0, 8, 4)}  {fmt(med_phase, 8, 2)}"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Analyze .tbc files using CombNTSC comb filter metrics."
    )
    parser.add_argument(
        "tbc_file",
        help="Path to the .tbc file (companion .tbc.db must exist)",
    )
    parser.add_argument(
        "-n", "--max-fields",
        type=int,
        default=None,
        help="Maximum number of fields to analyze",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print additional diagnostic information",
    )

    args = parser.parse_args()
    sys.exit(run_analysis(args.tbc_file, args.max_fields, args.verbose))


if __name__ == "__main__":
    main()
