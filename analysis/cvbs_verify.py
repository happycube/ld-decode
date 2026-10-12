#!/usr/bin/env python3
"""Verify a CVBS file against cvbs-file-format-specification.

Checks: exact frame sizing, protected-value exclusion, encoding LSBs,
level sanity, the 0H sync lattice (orthogonal for NTSC; the PAL check
asserts the non-line-locked +0.0064 samples/line drift accumulating to
exactly +4 per frame) and its 0H-aligned origin, burst behaviour and the
colour-sequence position of each frame (informational under
STANDARD_STABLE_UNLOCKED), metadata schema, and WAV audio consistency.

Usage: cvbs_verify.py <basename or file.composite>
Exits 0 and prints "CVBS VERIFY: PASS" when all checks pass.
"""

import os
import sqlite3
import struct
import sys

import numpy as np

# Frames are 0H-aligned (video-standard-presets, "Stored Frame and Line
# Origin"): sample 0 is the first sampling instant at or after 0H of the
# frame's first line, so 0H falls in the sample before it.
ORIGIN_TOLERANCE = 0.1  # samples, for the measurement
PRESETS = {
    "NTSC": {
        "frame_samples": 477750,
        "frame_lines": 525,
        "spl": 910.0,
        "drift_per_line": 0.0,
        "levels": {"sync": 16, "blanking": 240, "white": 800},
        "burst": (72, 108),
    },
    "PAL": {
        "frame_samples": 709379,
        "frame_lines": 625,
        "spl": 709379 / 625,
        "drift_per_line": 4 / 625,
        "levels": {"sync": 4, "blanking": 256, "white": 844},
        "burst": (98, 138),
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


def find_0h_positions(frame10, preset, sync_level=None, blank_level=None):
    """Locate sync leading (falling) edge midpoints in one frame.

    Returns interpolated sample positions of 50%-crossings of falling
    edges whose level then DWELLS near the sync floor for ~2.3 us — this
    rejects picture-content transients (which cross the threshold but do
    not stay down) AND sustained darker-than-black picture content (which
    can hover near the threshold without ever reaching sync level),
    keeping line syncs and vsync broad/equalizing pulses.

    The threshold sits halfway between the MEASURED sync and blanking
    levels when given (blanking is anchored by the spec, but the sync tip
    lands below it by the source's actual sync depth); the preset's
    nominal levels are the fallback.
    """
    lv = preset["levels"]
    if sync_level is None:
        sync_level = lv["sync"]
    if blank_level is None:
        blank_level = lv["blanking"]
    thr = (sync_level + blank_level) / 2.0
    # Low-pass first: LaserDisc PAL carries a ~3.75 MHz pilot burst across
    # the sync region (declared via has_nonstandard_values); a 5-sample
    # average removes it while shifting all edges identically.
    raw = frame10.astype(np.float64)
    x = np.convolve(raw, np.ones(5) / 5, "same")
    below = x < thr
    edges = np.nonzero(~below[:-1] & below[1:])[0]
    dwell = 33  # ~2.3 us at 4fsc — shorter than an equalizing pulse
    # Every legitimate sync edge - line sync, equalizing, vsync broad -
    # falls FROM blanking (front porch / serration gap), while spurious
    # edges from darker-than-black picture content (e.g. a multiburst
    # packet around a sub-black pedestal, which hovers at the threshold
    # and satisfies the dwell test) fall from more content.  Require the
    # ~1.3 us before the edge to sit near blanking.
    pre_min = blank_level - 0.3 * (blank_level - sync_level)
    out = []
    for e in edges:
        seg = below[e + 2 : e + 2 + dwell]
        if len(seg) < dwell or np.count_nonzero(seg) < dwell * 0.9:
            continue
        if e < 24 or np.median(x[e - 24 : e - 6]) < pre_min:
            continue
        a, b = x[e], x[e + 1]
        frac = (a - thr) / (a - b) if a != b else 0.5
        out.append(e + frac)
    return np.array(out)


def frame_origin(frame10, preset):
    """Where 0H of the frame's line 0 sits, in samples from sample 0, or
    None: the median over lines 40-199 of each line's sync edge
    half-amplitude crossing, from its lattice position (PAL's
    1135.0064-sample lines carry their own drift).

    The levels are measured: blanking from the front porch (a disc's can
    sit well off nominal - ggv1016-side1's histogram peak reads 260 where
    its porch reads 240) and the tip as the floor of the sync region (its
    5th percentile), since PAL LaserDiscs carry a 3.75 MHz pilot up from
    it that a mean or median would take for the tip.  The same estimator
    as lddecode.cvbs.CVBSWriter._origin_shift, which places sample 0.
    """
    x = frame10.astype(np.float64)
    pitch = preset["frame_samples"] / preset["frame_lines"]
    rows = range(40, 200)
    starts = [int(np.ceil(r * pitch)) for r in rows]
    tip = np.median([np.percentile(x[s + 4: s + 60], 5) for s in starts])
    porch = np.median([np.median(x[s - 18: s - 6]) for s in starts])
    thr = (tip + porch) / 2.0
    crossings = []
    for r, s in zip(rows, starts):
        seg = x[s - 8: s + 12]
        i = np.nonzero((seg[:-1] >= thr) & (seg[1:] < thr))[0]
        if len(i):
            i = i[0]
            at = s - 8 + i + (seg[i] - thr) / (seg[i] - seg[i + 1])
            crossings.append(at - r * pitch)
    if len(crossings) < len(starts) // 2:
        return None
    return float(np.median(crossings))


def _wrap(deg):
    return (deg + 180.0) % 360.0 - 180.0


#: Burst phase of colour frame A at 0 deg SC/H, deg, as the phase of
#: cos(90 (n - h0) + phase) over the frame's sample index n, with h0 the
#: frame's 0H.  The spec fixes frame A in stored coordinates - with 0H at
#: -0.63, stored line 9 sample 125 is a +I sample (SMPTE 244M 4.1.2) -
#: which puts the burst at cos(90 n + 147) on every line; frame B is 180
#: degrees away.  A disc's SC/H moves both, so the colour frame is the one
#: nearer, as read from the frame's own 0H.
NTSC_FRAME_A_BURST = 147.0 + 90.0 * -0.63

#: PAL frames 1-4 by (V-switch, +U phase at 0H of frame line 0), deg.  EBU
#: 3280: +U at zero phase at 0H of line 1 field 1 (stored frame line 0) at
#: 0 deg Sc-H, and each frame 270 degrees on; BT.470 2.16: the burst at
#: +135 deg on odd broadcast lines - even stored ones - of fields 1, 2, 5
#: and 6 and at -135 on the others, so odd stored lines lead even ones by
#: 90 degrees in frames 1 and 3 and lag them in 2 and 4.  BT.470 note 21
#: identifies the sequence by the +U phase to within 90 degrees.
PAL_FRAMES = {(+1, 0.0): 1, (-1, 270.0): 2, (+1, 180.0): 3, (-1, 90.0): 4}


#: How close to the boundary between two sequence positions (90 degrees
#: from either) a frame's SC/H may read before its position is ambiguous:
#: about the 0H measurement's own uncertainty.  A source that far off
#: 0 deg SC/H has no well-defined colour frame for any reader.
AMBIGUOUS_DEG = 10.0


def colour_phase(frame10, preset_name, p, origin):
    """The frame's colour-sequence phase from its burst against its 0H, or
    None when it cannot be read: (sequence phase, V-switch).  The sequence
    phase is SC/H plus the frame's offset in the sequence - about 0 in NTSC
    colour frame A and 180 in B; for PAL the +U phase at 0H of frame line
    0, about 270 (k - 1) in frame k.  V-switch is +1/-1 for PAL frames
    1, 3 / 2, 4 and None for NTSC."""
    if origin is None:
        return None
    b0, b1 = p["burst"]
    x = frame10.astype(np.float64)
    sums = [0j, 0j]
    for k in range(40, 200):
        j0 = int(np.ceil(k * p["spl"]))
        n = np.arange(j0 + b0, j0 + b1)
        seg = x[n]
        sums[k % 2] += np.mean((seg - seg.mean()) * np.exp(-0.5j * np.pi * n))
    if abs(sums[0]) == 0 or abs(sums[1]) == 0:
        return None
    if preset_name == "NTSC":
        phase = np.degrees(np.angle(sums[0] + sums[1])) + 90.0 * origin
        return (phase - NTSC_FRAME_A_BURST) % 360, None
    even, odd = (np.degrees(np.angle(v)) + 90.0 * origin for v in sums)
    vswitch = 1 if _wrap(odd - even) > 0 else -1
    # A +135 deg burst reads the +U phase + 45 here, a -135 one + 135;
    # frames 1/3 carry +135 on even stored lines, 2/4 on odd ones
    lead_even, lead_odd = (45.0, 135.0) if vswitch > 0 else (135.0, 45.0)
    u = np.degrees(np.angle(np.exp(1j * np.radians(even - lead_even))
                            + np.exp(1j * np.radians(odd - lead_odd)))) % 360
    return u, vswitch


def colour_frame(reading, preset_name):
    """'A'/'B' for NTSC, 1-4 for PAL, '?' within AMBIGUOUS_DEG of a
    boundary, or None for no reading."""
    if reading is None:
        return None
    phase, vswitch = reading
    if preset_name == "NTSC":
        candidates = {"A": 0.0, "B": 180.0}
    else:
        candidates = {n: u0 for (vs, u0), n in PAL_FRAMES.items() if vs == vswitch}
    for label, centre in candidates.items():
        if abs(_wrap(phase - centre)) < 90 - AMBIGUOUS_DEG:
            return label
    return "?"


def sequence_steps_ok(readings, preset_name):
    """Whether successive frames advance one sequence position each: NTSC
    180 degrees, PAL 270 with the V-switch alternating."""
    step = 180.0 if preset_name == "NTSC" else 270.0
    for r0, r1 in zip(readings, readings[1:]):
        if r0 is None or r1 is None:
            return False
        if abs(_wrap(r1[0] - r0[0] - step)) > 45:
            return False
        if preset_name != "NTSC" and r1[1] == r0[1]:
            return False
    return True


def main():
    path = sys.argv[1]
    base = path
    for ext in (".cvbs", ".composite"):
        if path.endswith(ext):
            base = path[: -len(ext)]
            break
    # .cvbs is the spec extension; .composite is the pre-spec name.
    comp = base + ".cvbs"
    if not os.path.exists(comp):
        comp = base + ".composite"
    meta = base + ".meta"

    print(f"CVBS verify: {comp}")

    # --- metadata ---
    check(os.path.exists(meta), ".meta present")
    con = sqlite3.connect(meta)
    uv = con.execute("PRAGMA user_version").fetchone()[0]
    check(uv == 11, f"user_version = 11 (got {uv})")
    row = con.execute(
        "SELECT preset, sample_encoding_preset, signal_state_preset, "
        "sequence_continuous, signal_type, decoder, "
        "number_of_sequential_frames FROM cvbs_file"
    ).fetchone()
    check(row is not None, "cvbs_file row present")
    preset_name, enc, state, seq_cont, sigtype, decoder, n_frames = row
    print(
        f"  preset={preset_name} enc={enc} state={state} "
        f"seq_continuous={seq_cont} type={sigtype} "
        f"decoder={decoder} frames={n_frames}"
    )
    check(seq_cont in (None, 0, 1), f"sequence_continuous is boolean or NULL (got {seq_cont!r})")
    if seq_cont == 0:
        warn("producer declares a sequence discontinuity")
    check(preset_name in PRESETS, f"known preset {preset_name}")
    p = PRESETS[preset_name]

    # --- file sizing ---
    fsize = os.path.getsize(comp)
    frame_bytes = p["frame_samples"] * 2
    check(
        fsize % frame_bytes == 0, f"file size is a whole number of frames ({fsize} / {frame_bytes})"
    )
    file_frames = fsize // frame_bytes
    if n_frames is not None:
        check(
            file_frames == n_frames, f"frame count matches metadata ({file_frames} vs {n_frames})"
        )

    # --- encoding / protected values ---
    if enc == "CVBS_U10_4FSC":
        # s16le, 10-bit domain with signed headroom: excursions below 0
        # and above 1023 are legal; only the protected codes 0-3 and
        # 1020-1023 are reserved (sample-encoding-presets.md).
        data = np.fromfile(comp, dtype="<i2")
        v10 = data.astype(np.int32)
        n_prot = int(np.count_nonzero(((v10 >= 0) & (v10 <= 3)) | ((v10 >= 1020) & (v10 <= 1023))))
        check(
            n_prot == 0,
            f"no protected values (range {v10.min()}..{v10.max()}, "
            f"{n_prot} samples in reserved codes)",
        )
    else:
        data = np.fromfile(comp, dtype="<u2")
        if enc == "CVBS_U16_4FSC":
            check(bool(np.all((data & 0x3F) == 0)), "U16 LSBs all zero")
        v10 = (data >> 6).astype(np.int32)
        check(
            int(v10.min()) >= 4 and int(v10.max()) <= 1019,
            f"no protected values (range {v10.min()}..{v10.max()})",
        )

    # --- level sanity: histogram peaks near sync and blanking ---
    # (clip for the histogram only: U10 headroom excursions may be negative)
    hist = np.bincount(np.clip(v10, 0, 1023), minlength=1024)
    lv = p["levels"]
    # median of sync-level samples (argmax would find the clamp pile at 4,
    # where the sync noise tail below the protected floor accumulates)
    sync_samples = v10[v10 < lv["blanking"] - 60]
    sync_med = int(np.median(sync_samples)) if len(sync_samples) else -1
    blank_lo = lv["blanking"] - 30
    blank_peak = blank_lo + int(np.argmax(hist[blank_lo : lv["blanking"] + 30]))
    # Blanking is the anchored level, so it must sit at the spec value.
    # The sync tip lands below it by the disc's measured sync depth - a
    # property of the source signal, not of format compliance (nominal is
    # 42.86 IRE PAL / 40 IRE NTSC, i.e. sync at exactly lv["sync"], but
    # shallow-sync discs are common) - so require a plausible depth
    # rather than the nominal code.
    nominal_depth = lv["blanking"] - lv["sync"]
    depth = blank_peak - sync_med
    check(
        0.70 * nominal_depth <= depth <= 1.15 * nominal_depth,
        f"sync depth plausible (sync median {sync_med}, "
        f"depth {depth} vs nominal {nominal_depth})",
    )
    check(
        abs(blank_peak - lv["blanking"]) <= 6,
        f"blanking near {lv['blanking']} (peak at {blank_peak})",
    )

    # --- 0H lattice ---
    n_check = min(file_frames, 4)
    frame_first_0h = []
    drift_ok = True
    for fr in range(n_check):
        frame = v10[fr * p["frame_samples"] : (fr + 1) * p["frame_samples"]]
        pos = find_0h_positions(frame, p, sync_level=sync_med, blank_level=blank_peak)
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
        check(abs(mean_spl - spl) < 0.02, f"frame {fr}: line spacing {mean_spl:.4f} vs {spl:.4f}")
        # Frame anchor: the first edge that starts a clean run of
        # line-spaced syncs, i.e. the first full line sync after the
        # opening vsync block.  The raw first detected edge is not a
        # stable anchor: the frame opens inside vsync, whose half-line
        # equalizing pulses dwell marginally (~2.35 us vs the 2.3 us
        # requirement) and are detected or missed per frame.
        anchor = None
        for i in range(len(pos) - 15):
            dd = np.diff(pos[i : i + 16])
            if np.all(np.abs(dd - spl) < 3):
                anchor = float(pos[i])
                break
        frame_first_0h.append(anchor if anchor is not None else float(good[0]))

        if preset_name == "PAL":
            # the non-orthogonal check: consecutive line syncs must be
            # spaced 1135.0064 samples apart, i.e. the 0H position slips
            # +4/625 sample per line — over a frame, exactly +4 samples.
            # (Computed from single-line gaps only; the edge run also
            # contains multi-line jumps across the vsync blocks.)
            slip_per_line = mean_spl - 1135.0
            total = slip_per_line * 625.0
            ok = abs(total - 4.0) < 1.5
            drift_ok &= ok
            check(
                ok,
                f"frame {fr}: lattice slip {total:.2f} samples/frame "
                f"(expect 4.00; {slip_per_line:.5f}/line over "
                f"{len(lines)} line gaps)",
            )

        # Whole-frame integer line grid: EVERY line sync must sit on the
        # same integer-line lattice, including across the field seam (line
        # syncs are 64 us apart throughout a frame; the interlace
        # half-line lives in vsync, not in 0H spacing).  This catches a
        # field placed at a half-line offset, which per-field spacing
        # checks cannot see.
        t = pos * p["frame_lines"] / p["frame_samples"]  # line-time units
        # anchor to the dominant grid phase (circular mean), not the first
        # edge — the frame can open on a vsync half-line pulse
        grid = np.angle(np.sum(np.exp(2j * np.pi * t))) / (2 * np.pi)
        frac = np.abs(((t - grid + 0.5) % 1.0) - 0.5)
        # ignore vsync serration/equalizing edges (half-line offenders in
        # the real signal): a genuine seam error displaces the MEDIAN
        n_half = int(np.count_nonzero(frac > 0.35))
        med_frac = float(np.median(frac))
        check(
            med_frac < 0.05 and n_half < len(t) * 0.2,
            f"frame {fr}: line syncs on one integer-line grid "
            f"(median frac {med_frac:.3f}, {n_half}/{len(t)} half-line "
            f"edges incl. vsync)",
        )

    # frame-to-frame: lattice repeats at frame rate
    if len(frame_first_0h) >= 2:
        # first 0H should land at the same in-frame position every frame
        pos_dev = np.max(np.abs(np.array(frame_first_0h) - frame_first_0h[0]))
        check(pos_dev < 1.0, f"first 0H position stable across frames (max dev {pos_dev:.3f})")

    # 0H-aligned origin: 0H of line 0 within the sample before sample 0
    # (a decoder's own line convention can put it a sample or two in,
    # which on the orthogonal NTSC lattice also turns the colour frame
    # the spec reads at its reference sample)
    origin = frame_origin(v10[: p["frame_samples"]], p)
    if origin is None:
        check(False, "frame 0: 0H origin measurable from its line syncs")
    else:
        check(
            -1.0 - ORIGIN_TOLERANCE < origin <= ORIGIN_TOLERANCE,
            f"0H of frame line 0 at {origin:+.2f} samples "
            f"(spec: in the sample before sample 0)",
        )

    # --- burst phase: assertion when LOCKED, informational otherwise ---
    b0, b1 = p["burst"]
    frame_phases = []
    for fr in range(n_check):
        frame = v10[fr * p["frame_samples"] : (fr + 1) * p["frame_samples"]]
        x = frame.astype(np.float64)
        bursts = []
        for k in range(40, 200, 2):
            if preset_name == "NTSC":
                j0 = k * 910
            else:
                j0 = int(np.ceil(k * p["spl"]))
            seg = x[j0 + b0 : j0 + b1]
            if len(seg) < b1 - b0:
                continue
            n = np.arange(j0 + b0, j0 + b1) if preset_name == "PAL" else np.arange(b0, b1)
            bursts.append(np.mean((seg - np.mean(seg)) * np.exp(-0.5j * np.pi * n)))
        if not bursts:
            continue
        bursts = np.array(bursts)
        if preset_name == "PAL":
            # fold the V-switch: adjacent products have phase 2*theta;
            # the lattice constraint is defined mod 90 degrees
            psum = np.sum(bursts[:-1] * bursts[1:])
            ph = (np.degrees(np.angle(psum)) / 2.0) % 90.0
        else:
            ph = np.degrees(np.angle(np.sum(bursts))) % 360.0
        frame_phases.append(ph)

    if frame_phases:
        arr = np.array(frame_phases)
        # PAL lattice phase is defined mod 90; NTSC folds the 2-frame
        # colour-sequence alternation out mod 180
        halfspan = 45.0 if preset_name == "PAL" else 90.0
        dev = np.abs((arr - arr[0] + halfspan) % (2 * halfspan) - halfspan)
        msg = (
            f"burst-vs-lattice phase per frame: "
            + ", ".join(f"{v:.2f}" for v in arr)
            + f" deg (max dev {np.max(dev):.2f})"
        )
        if state == "STANDARD_STABLE_LOCKED":
            check(bool(np.max(dev) <= 3.0), "LOCKED: " + msg)
        else:
            warn(msg)

    # --- colour-sequence position ---
    # The spec leaves the position out of band, to be read from the burst;
    # a phase-locked file must make that reading correct, and one that
    # declares itself continuous must progress through the sequence.
    # ld-decode also opens every file on colour frame A / PAL frame 1,
    # which load_cvbs numbers its fields from.
    seq_frames = min(file_frames, 8)
    readings = []
    for fr in range(seq_frames):
        frame = v10[fr * p["frame_samples"] : (fr + 1) * p["frame_samples"]]
        fo = frame_origin(frame, p)
        readings.append(colour_phase(frame, preset_name, p, fo))
    if readings:
        positions = [colour_frame(r, preset_name) for r in readings]
        first = "A" if preset_name == "NTSC" else 1
        msg = "colour sequence positions " + " ".join(str(v) for v in positions)
        locked = state == "STANDARD_STABLE_LOCKED"
        report = check if locked else (lambda ok, m: None if ok else warn(m))
        if positions[0] == "?":
            warn(f"{msg}: frame 0 is {_wrap(readings[0][0]):+.0f} deg from "
                 f"{first}, too near a "
                 f"boundary for its colour frame to be defined")
        else:
            report(positions[0] == first,
                   f"{msg}: file opens on {first} (ld-decode convention)")
        if seq_cont == 1:
            report(sequence_steps_ok(readings, preset_name),
                   f"{msg}: progress one position per frame")

    # --- extension sidecars ---
    do_meta = base + ".dropouts.meta"
    if os.path.exists(do_meta):
        dcon = sqlite3.connect(do_meta)
        duv = dcon.execute("PRAGMA user_version").fetchone()[0]
        check(duv == 5, f"dropouts.meta user_version = 5 (got {duv})")
        bad = dcon.execute(
            "SELECT COUNT(*) FROM dropout_run WHERE sample_start < 0 OR "
            "sample_start + sample_count > ? OR frame_id >= ?",
            (p["frame_samples"], file_frames),
        ).fetchone()[0]
        total = dcon.execute("SELECT COUNT(*) FROM dropout_run").fetchone()[0]
        check(bad == 0, f"dropout runs in bounds ({total} rows)")
        dcon.close()
    else:
        warn("no dropout extension sidecar")

    efm_meta = base + ".efm.meta"
    efm_bin = base + ".efm"
    if os.path.exists(efm_meta) and os.path.exists(efm_bin):
        econ = sqlite3.connect(efm_meta)
        euv = econ.execute("PRAGMA user_version").fetchone()[0]
        check(euv == 1, f"efm.meta user_version = 1 (got {euv})")
        rows = econ.execute(
            "SELECT frame_id, t_value_offset, t_value_count FROM efm_frame " "ORDER BY frame_id"
        ).fetchall()
        ok = bool(rows) and rows[0][1] == 0
        expect_off = 0
        for _, off, cnt in rows:
            ok &= off == expect_off
            expect_off = off + cnt
        ok &= expect_off == os.path.getsize(efm_bin)
        check(
            ok,
            f"efm_frame index contiguous and matches .efm size "
            f"({len(rows)} frames, {expect_off} t-values)",
        )
        check(
            len(rows) == file_frames, f"efm index covers every frame ({len(rows)} vs {file_frames})"
        )
        econ.close()
    else:
        warn("no EFM extension sidecar")

    # --- audio (SMPTE 272M: 48 kHz, 24-bit stereo, synchronous) ---
    pairs = con.execute(
        "SELECT channel_pair, description FROM audio_channel_pair " "ORDER BY channel_pair"
    ).fetchall()
    wav = base + "_audio_0.wav"
    if os.path.exists(wav):
        check(any(cp == 0 for cp, _ in pairs), "audio_channel_pair row present for pair 0")
        with open(wav, "rb") as f:
            hdr = f.read(44)
        riff, wave = hdr[0:4], hdr[8:12]
        fmt_tag, channels, rate = struct.unpack("<HHI", hdr[20:28])
        bits = struct.unpack("<H", hdr[34:36])[0]
        data_len = struct.unpack("<I", hdr[40:44])[0]
        check(riff == b"RIFF" and wave == b"WAVE", "WAV RIFF header")
        check(fmt_tag == 1 and channels == 2 and bits == 24, "WAV stereo 24-bit PCM")
        check(rate == 48000, f"WAV rate 48000 (got {rate})")
        actual = os.path.getsize(wav) - 44
        check(data_len == actual, f"WAV data chunk size correct ({data_len} vs {actual})")
        # synchronous per-preset total: 1920/frame (PAL) or the 8008-per-
        # 5-frame 1602/1601 sequence (NTSC/PAL_M)
        if preset_name == "PAL":
            target = 1920 * file_frames
        else:
            seq = (0, 1602, 3203, 4805, 6406)
            target = 8008 * (file_frames // 5) + seq[file_frames % 5]
        check(
            data_len == target * 6, f"synchronous audio: {target} samples for {file_frames} frames"
        )
    else:
        check(not pairs, "no audio_channel_pair rows without a WAV file")
        warn("no audio WAV present")

    print()
    if failures:
        print(f"CVBS VERIFY: FAIL ({len(failures)} failed checks)")
        sys.exit(1)
    print(f"CVBS VERIFY: PASS ({file_frames} frames, {preset_name}, {enc}, {state})")


if __name__ == "__main__":
    main()
