#!/usr/bin/env python3
"""Convert an ld-decode analog-audio .pcm file to .wav.

The sample format comes from the pcm_audio_parameters table in the
companion .tbc.db (bits / signedness / endianness / sample_rate), so
line-locked rates set with --NTSC_audio_rate etc. are honored.  The .pcm
stream itself is stereo interleaved L,R (channel count is not recorded
in the metadata).

Usage:

    python3 scripts/pcm_to_wav.py he010.pcm            # -> he010.wav
    python3 scripts/pcm_to_wav.py he010.pcm out.wav
    python3 scripts/pcm_to_wav.py --db other.tbc.db he010.pcm
"""

import argparse
import os
import sqlite3
import sys
import wave


def find_db(pcm_path):
    base = pcm_path[:-4] if pcm_path.endswith(".pcm") else pcm_path
    for cand in (base + ".tbc.db", base + ".db"):
        if os.path.exists(cand):
            return cand
    return None


def read_params(db_path):
    con = sqlite3.connect(db_path)
    try:
        row = con.execute(
            "SELECT bits, is_signed, is_little_endian, sample_rate "
            "FROM pcm_audio_parameters"
        ).fetchone()
    finally:
        con.close()
    if row is None:
        raise SystemExit(f"{db_path}: no pcm_audio_parameters row")
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pcm", help="input .pcm (raw analog audio from ld-decode)")
    ap.add_argument("wav", nargs="?", help="output .wav (default: <pcm base>.wav)")
    ap.add_argument("--db", help="metadata .tbc.db (default: derived from pcm name)")
    ap.add_argument("--channels", type=int, default=2,
                    help="channel count, not recorded in metadata (default 2)")
    args = ap.parse_args()

    db_path = args.db or find_db(args.pcm)
    if db_path is None:
        raise SystemExit(f"no .tbc.db found next to {args.pcm}; pass --db")

    bits, is_signed, is_le, rate = read_params(db_path)
    if bits != 16 or not is_signed or not is_le:
        raise SystemExit(
            f"unsupported pcm format in {db_path}: "
            f"bits={bits} signed={is_signed} little_endian={is_le} "
            "(only s16le is handled)"
        )

    wav_rate = round(rate)
    if wav_rate != rate:
        print(f"note: fractional sample rate {rate} Hz rounded to {wav_rate} "
              "for the WAV header", file=sys.stderr)

    out_path = args.wav or (
        (args.pcm[:-4] if args.pcm.endswith(".pcm") else args.pcm) + ".wav")

    frame_bytes = args.channels * (bits // 8)
    n_bytes = os.path.getsize(args.pcm)
    if n_bytes % frame_bytes:
        print(f"note: {n_bytes % frame_bytes} trailing bytes dropped "
              "(not a whole frame)", file=sys.stderr)
        n_bytes -= n_bytes % frame_bytes

    with open(args.pcm, "rb") as fin, wave.open(out_path, "wb") as wout:
        wout.setnchannels(args.channels)
        wout.setsampwidth(bits // 8)
        wout.setframerate(wav_rate)
        remaining = n_bytes
        while remaining:
            chunk = fin.read(min(remaining, 1 << 20))
            if not chunk:
                break
            wout.writeframes(chunk)
            remaining -= len(chunk)

    print(f"{out_path}: {n_bytes // frame_bytes} frames, "
          f"{args.channels}ch {bits}-bit @ {wav_rate} Hz (from {db_path})")


if __name__ == "__main__":
    main()
