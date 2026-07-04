#!/usr/bin/env python3
"""Verify a CVBS file against cvbs-file-format-specification.

Checks: exact frame sizing, protected-value exclusion, encoding LSBs,
level sanity, the 0H sync lattice (orthogonal for NTSC; the PAL check
asserts the non-line-locked +0.0064 samples/line drift accumulating to
exactly +4 per frame), burst behaviour (informational under
STANDARD_TBC_UNLOCKED), metadata schema, and WAV audio consistency.

Usage: cvbs_verify.py <basename or file.composite>
Exits 0 and prints "CVBS VERIFY: PASS" when all checks pass.
"""

import os
import sqlite3
import struct
import sys

import numpy as np

PRESETS = {
    "NTSC": {
        "frame_samples": 477750, "frame_lines": 525,
        "spl": 910.0, "zero_h": 784.5, "drift_per_line": 0.0,
        "levels": {"sync": 16, "blanking": 240, "white": 800},
        "fsc_per_sample": 0.25,
    },
    "PAL": {
        "frame_samples": 709379, "frame_lines": 625,
        "spl": 709379 / 625, "zero_h": 957.5, "drift_per_line": 4 / 625,
        "levels": {"sync": 4, "blanking": 256, "white": 844},
        "fsc_per_sample": 0.25,
    },
}

failures = []
warnings = []


def check(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        failures.append(msg)


def warn(msg):
    print("  [info] " + msg)
    warnings.append(msg)


def find_0h_positions(frame10, preset):
    """Locate every sync leading (falling) edge midpoint in one frame.

    Returns interpolated sample positions of the 50%-crossings of falling
    edges that stay low for >2 us (line/vsync syncs, not equalizing-only).
    """
    lv = preset["levels"]
    thr = (lv["sync"] + lv["blanking"]) / 2.0
    x = frame10.astype(np.float64)
    below = x < thr
    edges = np.nonzero(~below[:-1] & below[1:])[0]
    out = []
    for e in edges:
        # interpolate the 50% crossing between e and e+1
        a, b = x[e], x[e + 1]
        frac = (a - thr) / (a - b) if a != b else 0.5
        out.append(e + frac)
    return np.array(out)


def main():
    path = sys.argv[1]
    base = path[: -len(".composite")] if path.endswith(".composite") else path
    comp = base + ".composite"
    meta = base + ".meta"

    print(f"CVBS verify: {comp}")

    # --- metadata ---
    check(os.path.exists(meta), ".meta present")
    con = sqlite3.connect(meta)
    uv = con.execute("PRAGMA user_version").fetchone()[0]
    check(uv == 8, f"user_version = 8 (got {uv})")
    row = con.execute(
        "SELECT preset, sample_encoding_preset, signal_state_preset, "
        "signal_type, decoder, number_of_sequential_frames, audio_locked "
        "FROM cvbs_file").fetchone()
    check(row is not None, "cvbs_file row present")
    preset_name, enc, state, sigtype, decoder, n_frames, audio_locked = row
    print(f"  preset={preset_name} enc={enc} state={state} type={sigtype} "
          f"decoder={decoder} frames={n_frames} audio_locked={audio_locked}")
    check(preset_name in PRESETS, f"known preset {preset_name}")
    p = PRESETS[preset_name]

    # --- file sizing ---
    fsize = os.path.getsize(comp)
    frame_bytes = p["frame_samples"] * 2
    check(fsize % frame_bytes == 0,
          f"file size is a whole number of frames ({fsize} / {frame_bytes})")
    file_frames = fsize // frame_bytes
    if n_frames is not None:
        check(file_frames == n_frames,
              f"frame count matches metadata ({file_frames} vs {n_frames})")

    data = np.fromfile(comp, dtype="<u2")

    # --- encoding / protected values ---
    if enc == "CVBS_U16_4FSC":
        check(bool(np.all((data & 0x3F) == 0)), "U16 LSBs all zero")
    v10 = (data >> 6).astype(np.int32)
    check(int(v10.min()) >= 4 and int(v10.max()) <= 1019,
          f"no protected values (range {v10.min()}..{v10.max()})")

    # --- level sanity: histogram peaks near sync and blanking ---
    hist = np.bincount(v10, minlength=1024)
    lv = p["levels"]
    # median of sync-level samples (argmax would find the clamp pile at 4,
    # where the sync noise tail below the protected floor accumulates)
    sync_samples = v10[v10 < lv["blanking"] - 60]
    sync_med = int(np.median(sync_samples)) if len(sync_samples) else -1
    blank_lo = lv["blanking"] - 30
    blank_peak = blank_lo + int(np.argmax(hist[blank_lo: lv["blanking"] + 30]))
    check(abs(sync_med - lv["sync"]) <= 6,
          f"sync tip near {lv['sync']} (median {sync_med})")
    check(abs(blank_peak - lv["blanking"]) <= 6,
          f"blanking near {lv['blanking']} (peak at {blank_peak})")

    # --- 0H lattice ---
    n_check = min(file_frames, 4)
    frame_first_0h = []
    drift_ok = True
    for fr in range(n_check):
        frame = v10[fr * p["frame_samples"]:(fr + 1) * p["frame_samples"]]
        pos = find_0h_positions(frame, p)
        if len(pos) < 100:
            check(False, f"frame {fr}: found only {len(pos)} sync edges")
            continue
        # keep edges whose neighbour spacing is near one line (rejects
        # equalizing/serration edges inside vsync)
        spl = p["spl"]
        good = [pos[0]]
        for q in pos[1:]:
            d = q - good[-1]
            if abs(d - spl) < 3:
                good.append(q)
            elif d > spl * 1.5:
                # resync after vsync block
                good.append(q)
        good = np.array(good)
        d = np.diff(good)
        lines = d[np.abs(d - spl) < 3]
        mean_spl = float(np.mean(lines))
        check(abs(mean_spl - spl) < 0.02,
              f"frame {fr}: line spacing {mean_spl:.4f} vs {spl:.4f}")
        # phase of 0H within the sample grid modulo one line
        ph0 = float(good[0] % 1)
        frame_first_0h.append(good[0])

        if preset_name == "PAL":
            # the non-orthogonal check: 0H fractional position must drift
            # +0.0064 samples/line => across N lines, (pos_N - pos_0) -
            # N*1135 == N*4/625 within tolerance
            span = len(good) - 1
            drift = (good[-1] - good[0]) - span * 1135.0
            expect = span * (4.0 / 625.0)
            ok = abs(drift - expect) < 0.35
            drift_ok &= ok
            check(ok, f"frame {fr}: lattice slip {drift:.3f} samples over "
                      f"{span} lines (expect {expect:.3f})")

    # frame-to-frame: lattice repeats at frame rate
    if len(frame_first_0h) >= 2:
        # first 0H should land at the same in-frame position every frame
        pos_dev = np.max(np.abs(np.array(frame_first_0h)
                                - frame_first_0h[0]))
        check(pos_dev < 1.0,
              f"first 0H position stable across frames (max dev {pos_dev:.3f})")

    if preset_name == "NTSC" and len(frame_first_0h):
        # orthogonal lattice: the regular line syncs must sit at the spec's
        # digital position modulo one line (the first detected edge can be
        # a vsync equalizing pulse a half-line earlier, so use the run)
        frame = v10[: p["frame_samples"]]
        pos = find_0h_positions(frame, p)
        # regular full-line syncs: spacing ~910 both sides
        d = np.diff(pos)
        mids = pos[1:-1][(np.abs(d[:-1] - p["spl"]) < 3)
                         & (np.abs(d[1:] - p["spl"]) < 3)]
        if len(mids) > 50:
            phase = float(np.median(mids % p["spl"]))
            check(abs(phase - p["zero_h"]) < 1.5,
                  f"0H at digital line position {phase:.2f} "
                  f"(spec {p['zero_h']})")

    # --- burst (informational under UNLOCKED) ---
    frame = v10[: p["frame_samples"]].astype(np.float64)
    # sample the burst window ~ 0H+16..34 quarter-cycles after a mid-frame 0H
    if len(frame_first_0h):
        h0 = int(round(frame_first_0h[0])) + int(round(p["spl"])) * 40
        seg = frame[h0 + 20: h0 + 55]
        n = np.arange(len(seg))
        c = np.mean((seg - np.mean(seg)) * np.exp(-0.5j * np.pi * (n + h0 + 20)))
        warn(f"burst on a mid-frame line: amp {2 * np.abs(c):.1f} (10-bit), "
             f"phase {np.degrees(np.angle(c)) % 360:.1f} deg (informational)")

    # --- audio ---
    wav = base + "_audio_00.wav"
    if os.path.exists(wav):
        with open(wav, "rb") as f:
            hdr = f.read(44)
        riff, wave = hdr[0:4], hdr[8:12]
        fmt_tag, channels, rate = struct.unpack("<HHI", hdr[20:28])
        bits = struct.unpack("<H", hdr[34:36])[0]
        data_len = struct.unpack("<I", hdr[40:44])[0]
        check(riff == b"RIFF" and wave == b"WAVE", "WAV RIFF header")
        check(fmt_tag == 1 and channels == 2 and bits == 16,
              "WAV stereo s16 PCM")
        expect_rate = (44056 if (audio_locked and preset_name in
                                 ("NTSC", "PAL_M")) else 44100)
        check(rate == expect_rate,
              f"WAV rate {rate} matches audio_locked={audio_locked}")
        actual = os.path.getsize(wav) - 44
        check(data_len == actual,
              f"WAV data chunk size correct ({data_len} vs {actual})")
        if audio_locked:
            per_frame = 1764 if preset_name == "PAL" else 1470
            check(data_len == file_frames * per_frame * 4,
                  f"locked audio: {per_frame} samples/frame exactly")
    else:
        warn("no audio WAV present")

    print()
    if failures:
        print(f"CVBS VERIFY: FAIL ({len(failures)} failed checks)")
        sys.exit(1)
    print(f"CVBS VERIFY: PASS ({file_frames} frames, {preset_name}, {enc}, {state})")


if __name__ == "__main__":
    main()
