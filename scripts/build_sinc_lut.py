#!/usr/bin/env python3
"""Write the sinc resample look-up table the decoder ships.

``lddecode/sinc_lut.npz`` holds the fractional-delay filter bank that both
resampling kernels read, one row per tabulated phase.  It is generated rather
than computed at start-up because building it needs ``scipy.special.i0`` on a
grid, and every decode and every worker process would otherwise pay for it.

The table is read one row per *output* sample, so it is hot for the whole of
every field and its size is charged against the cache the decoder shares with
the signal it is resampling.  Both kernels interpolate between adjacent rows,
which is what lets it be small: 257 rows of 16 float32 weights, 16 KiB.

Run it after changing ``kaiser_beta``, ``sinc_tap_count`` or
``sinc_phase_count`` in ``lddecode/dsp.py``.  The table is an output baseline:
regenerating it moves decoded samples, so it re-records like any other.

Usage:

    python scripts/build_sinc_lut.py            # write lddecode/sinc_lut.npz
    python scripts/build_sinc_lut.py --check    # compare, write nothing
"""

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lddecode.dsp import (  # noqa: E402
    build_kaiser_lut, kaiser_beta, sinc_phase_count, sinc_tap_count,
)

LUT_PATH = Path(__file__).resolve().parent.parent / "lddecode" / "sinc_lut.npz"
KEY = "downscale_sinc_lut"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true",
        help="report whether the shipped table matches the parameters, and exit"
        " non-zero if it does not, without writing anything",
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=LUT_PATH,
        help="where to write the table (default: %(default)s)",
    )
    args = parser.parse_args()

    table = build_kaiser_lut(kaiser_beta, sinc_tap_count, sinc_phase_count)
    print("beta=%g taps=%d phases=%d -> %s %s, %d bytes uncompressed"
          % (kaiser_beta, sinc_tap_count, sinc_phase_count,
             table.shape, table.dtype, table.nbytes))

    if args.check:
        if not args.output.exists():
            print("%s does not exist" % args.output)
            return 1
        shipped = np.load(args.output)[KEY]
        if shipped.shape != table.shape or shipped.dtype != table.dtype:
            print("shipped table is %s %s, parameters give %s %s"
                  % (shipped.shape, shipped.dtype, table.shape, table.dtype))
            return 1
        if not np.array_equal(shipped, table):
            print("shipped table differs, max %g" % np.abs(shipped - table).max())
            return 1
        print("%s matches" % args.output)
        return 0

    np.savez_compressed(args.output, **{KEY: table})
    print("wrote %s, %d bytes on disc" % (args.output, args.output.stat().st_size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
