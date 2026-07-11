"""Coherent-average NTC-7 multiburst level measurement.

Usage: python3 analysis/mb_measure.py <file.tbc> [max_frames]

Collects up to 10 same-parity fields carrying the 6-packet NTC-7 combination
multiburst, coherently averages the line-20 waveform (killing random noise so
the sine-fit p-p is unbiased), then measures per-packet peak-to-peak IRE.
Prints levels and dB relative to the 0.5 MHz packet.  Exits non-zero with a
pattern summary if no multiburst is found.
"""
import sys
import copy
import numpy as np
sys.path.insert(0, "analysis")
from tbc_common import (load_video, measure_ntc7_multiburst,
                        detect_patterns, summarize_patterns)

NOM = [0.5, 1.0, 2.0, 3.0, 3.58, 4.2]


def main():
    path = sys.argv[1]
    max_frames = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    params, fields, _ = load_video(path)
    scan = min(len(fields), 2 * max_frames + 20)

    # A real combination multiburst has six packets whose measured
    # frequencies climb monotonically and sit near the nominal set; content
    # or noise can spuriously yield six "packets" at scrambled frequencies
    # (seen on the Phil Collins CLV disc), so gate on frequency plausibility.
    def is_valid(pk):
        if len(pk) != 6:
            return False
        freqs = [p[1] for p in pk]
        if any(b <= a for a, b in zip(freqs, freqs[1:])):
            return False
        return all(abs(f - nom) < 0.4 for f, nom in zip(freqs, NOM))

    # group valid multiburst fields by parity; coherent averaging needs one
    groups = {True: [], False: []}
    for f in fields[:scan]:
        if is_valid(measure_ntc7_multiburst(f)):
            groups[f.isFirstField].append(f)

    grp = max(groups.values(), key=len)[:10]
    if not grp:
        det = detect_patterns(params, fields, max_fields=16)
        print(f"{path}: NO multiburst found. Patterns present:")
        for line in summarize_patterns(det, fields):
            print("  " + line)
        sys.exit(2)

    mean_pic = np.mean([f.dspicture.astype(np.float64) for f in grp], axis=0)
    af = copy.copy(grp[0])
    af.dspicture = mean_pic
    pk = measure_ntc7_multiburst(af)
    ref = pk[0][2]

    print(f"{path}: {len(grp)} fields "
          f"({'first' if grp[0].isFirstField else 'second'} parity), "
          f"field indices {[f.field_index for f in grp]}")
    for fq, (_, fmeas, pp) in zip(NOM, pk):
        print(f"  {fq:5.2f} MHz (meas {fmeas:5.3f})  {pp:6.2f} IRE  "
              f"{20 * np.log10(pp / ref):+6.2f} dB")


if __name__ == "__main__":
    main()
