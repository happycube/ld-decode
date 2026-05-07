"""
ld-lds-reader - LDS reader tool for ld-decode (Python implementation)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

from lddecode.utils import load_packed_data_4_40

DEFAULT_CHUNK_SAMPLES = 1_000_000


def _set_stdout_binary_mode() -> None:
    if sys.platform == "win32":
        import msvcrt

        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)


def _stream_lds_to_stdout(
    input_filename: str, start_offset: int, *, quiet: bool, chunk_samples: int
) -> int:
    input_path = Path(input_filename)
    if not input_path.exists():
        print(f"Input file does not exist: {input_filename}", file=sys.stderr)
        return 1

    file_size_bytes = input_path.stat().st_size
    total_samples = (file_size_bytes // 5) * 4

    if start_offset >= total_samples:
        if not quiet:
            print("Start offset is beyond end of capture; no data emitted.", file=sys.stderr)
        return 0

    if not quiet:
        print(f"Processing LDS file: {input_filename}", file=sys.stderr)
        if start_offset > 0:
            print(f"Start offset: {start_offset} samples", file=sys.stderr)

    with input_path.open("rb") as infile:
        current_sample = start_offset
        while current_sample < total_samples:
            readlen = min(chunk_samples, total_samples - current_sample)
            unpacked = load_packed_data_4_40(infile, current_sample, readlen)

            if unpacked is None:
                print(
                    "Unexpected end of file while unpacking LDS capture.",
                    file=sys.stderr,
                )
                return 1

            output = unpacked.astype(np.dtype("<i2"), copy=False)
            sys.stdout.buffer.write(output.tobytes())
            current_sample += readlen

    sys.stdout.flush()
    if not quiet:
        print("LDS reading completed successfully", file=sys.stderr)
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "ld-lds-reader - LDS reader tool for ld-decode (Python implementation)"
        )
    )
    parser.add_argument(
        "-s",
        "--start-offset",
        type=int,
        default=0,
        metavar="samples",
        help="Start offset in samples (default: 0)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress status output",
    )
    parser.add_argument(
        "input",
        help="Input LDS file",
    )
    return parser


def main(args: list[str] | None = None) -> int:
    check_args = args if args is not None else sys.argv[1:]
    if "--version" in check_args or "-v" in check_args:
        from lddecode import __version__

        print(__version__)
        return 0

    parser = _build_arg_parser()
    parsed_args = parser.parse_args(args=args)

    if parsed_args.start_offset < 0:
        parser.error("Start offset must be a non-negative integer")

    _set_stdout_binary_mode()
    return _stream_lds_to_stdout(
        parsed_args.input,
        parsed_args.start_offset,
        quiet=parsed_args.quiet,
        chunk_samples=DEFAULT_CHUNK_SAMPLES,
    )


if __name__ == "__main__":
    raise SystemExit(main())
