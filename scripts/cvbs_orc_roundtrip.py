#!/usr/bin/env python3
"""Round-trip a CVBS output through decode-orc and compare against the
TBC path.

Renders one frame from <basename>.composite and one from <tbc_basename>.tbc
through decode-orc's raw_video_sink (same chroma decoder), then asserts:

  1. the luma difference is parity-balanced (even vs odd display rows) —
     a misplaced field makes one parity's rows garbage while the other
     matches perfectly (how the PAL field-B half-line bug manifested);
  2. the best global 2D shift between the renders is (0, 0);
  3. the mean difference is small (same content, same decoder).

The two decodes may start on different disc frames (the CVBS writer
aligns to the colour sequence origin), so this comparison relies on the
CI discs being static test signals.

Usage: cvbs_orc_roundtrip.py <cvbs_basename> <tbc_basename> <NTSC|PAL>

Prints "ORC ROUNDTRIP: PASS" on success, "ORC ROUNDTRIP: SKIPPED" when
orc-cli is not available (ctest treats that as a skip).
"""

import os
import subprocess
import sys
import tempfile

import numpy as np

ORC_CANDIDATES = [
    os.environ.get("ORC_CLI", ""),
    os.path.expanduser("~/ld-decode/decode-orc/result/bin/orc-cli"),
]

PROJECT = """# ORC Project File
# Version: 2.0

project:
  name: cvbs-roundtrip
  version: 2.0
  video_format: {system}
  source_format: Composite
  amplitude_unit: IRE
dag:
  nodes:
    - id: 1
      stage: {source_stage}
      node_type: SOURCE
      display_name: Source
      user_label: Source
      x: 50
      y: 50
      parameters:
        input_path:
          type: string
          value: {input_path}
{extra_params}
    - id: 2
      stage: frame_map
      node_type: TRANSFORM
      display_name: Frame Map
      user_label: Frame Map
      x: 300
      y: 50
      parameters:
        ranges:
          type: string
          value: "1"
    - id: 3
      stage: raw_video_sink
      node_type: SINK
      display_name: Raw Video Sink
      user_label: Raw Video Sink
      x: 550
      y: 50
      parameters:
        decoder_type:
          type: string
          value: {decoder}
        output_format:
          type: string
          value: yuv
        output_path:
          type: string
          value: {output_path}
  edges:
    - from: 1
      to: 2
    - from: 2
      to: 3
"""


def find_orc():
    for c in ORC_CANDIDATES:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def render(orc, workdir, system, source_stage, input_path, extra_params,
           decoder, output_path):
    prj = os.path.join(workdir, os.path.basename(output_path) + ".orcprj")
    with open(prj, "w") as f:
        f.write(PROJECT.format(system=system, source_stage=source_stage,
                               input_path=input_path,
                               extra_params=extra_params, decoder=decoder,
                               output_path=output_path))
    r = subprocess.run([orc, prj, "--process"], capture_output=True,
                       text=True, timeout=600)
    if not os.path.exists(output_path):
        print(r.stdout[-2000:])
        print(r.stderr[-2000:])
        raise RuntimeError(f"orc-cli produced no output for {input_path}")


def luma(path, height):
    d = np.fromfile(path, dtype="<u2")
    width = len(d) // 3 // height  # yuv444p16le, whole frames
    frames = len(d) // (width * height * 3)
    return d[: width * height].reshape(height, width).astype(np.float64), \
        width, frames


def main():
    cvbs_base, tbc_base, system = sys.argv[1], sys.argv[2], sys.argv[3]

    orc = find_orc()
    if orc is None:
        print("ORC ROUNDTRIP: SKIPPED (orc-cli not found; set ORC_CLI)")
        return

    height = 576 if system == "PAL" else 488
    decoder = "pal2d" if system == "PAL" else "ntsc2d"
    src_stage = f"{system}_CVBS_Source"

    with tempfile.TemporaryDirectory() as td:
        y_cvbs = os.path.join(td, "cvbs.yuv")
        y_tbc = os.path.join(td, "tbc.yuv")

        render(orc, td, system, src_stage,
               os.path.abspath(cvbs_base + ".composite"), "", decoder, y_cvbs)

        extra = ("        db_path:\n"
                 "          type: string\n"
                 f"          value: {os.path.abspath(tbc_base + '.tbc.db')}")
        render(orc, td, system, "tbc_source",
               os.path.abspath(tbc_base + ".tbc"), extra, decoder, y_tbc)

        a, wa, _ = luma(y_cvbs, height)
        b, wb, _ = luma(y_tbc, height)

    ok = True
    if wa != wb:
        print(f"FAIL: render widths differ ({wa} vs {wb})")
        ok = False
    else:
        d = np.abs(a - b)
        even, odd = d[0::2].mean(), d[1::2].mean()
        total = d.mean()
        # 16-bit units; 66% of full scale would be catastrophic — observed
        # good decodes sit near 1000-2000, the PAL field bug at ~20000/odd
        parity_ratio = abs(even - odd) / max(total, 1.0)
        print(f"diff: total={total:.0f} even={even:.0f} odd={odd:.0f} "
              f"parity imbalance={parity_ratio:.2f}")
        if total > 6000:
            print("FAIL: renders differ too much overall")
            ok = False
        if parity_ratio > 0.5:
            print("FAIL: field parity imbalance (one field misplaced?)")
            ok = False

        A = np.fft.fft2(a - a.mean())
        B = np.fft.fft2(b - b.mean())
        xc = np.fft.ifft2(A * np.conj(B)).real
        iy, ix = np.unravel_index(np.argmax(xc), xc.shape)
        dy = iy if iy < a.shape[0] // 2 else iy - a.shape[0]
        dx = ix if ix < a.shape[1] // 2 else ix - a.shape[1]
        print(f"best global shift: dy={dy} dx={dx}")
        if abs(dy) > 1 or abs(dx) > 1:
            print("FAIL: renders are displaced")
            ok = False

    if not ok:
        print("ORC ROUNDTRIP: FAIL")
        sys.exit(1)
    print(f"ORC ROUNDTRIP: PASS ({system}, width {wa})")


if __name__ == "__main__":
    main()
