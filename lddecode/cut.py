#!/usr/bin/env python3
"""ld-cut - extract a sample area from raw RF laserdisc captures."""

import os
import signal
import sys
import argparse

import numpy as np

from lddecode.decoder import LDdecode
from lddecode.fileio import ffmpeg_pipe, ldf_pipe, make_loader, samples_to_s16
from lddecode.lds import LdsWriter
from lddecode.utils_logging import init_logging


def build_parser():
    """The ld-cut command line, as an argparse parser.

    Separate from main() so the flag definitions can be exercised without
    opening a capture.
    """
    parser = argparse.ArgumentParser(
        description="Extract a sample area from raw RF laserdisc captures.  (Similar to ld-decode, except it outputs samples)"
    )
    # main() answers --version before parsing; registered so --help lists it
    from lddecode import __version__
    parser.add_argument("-v", "--version", action="version", version=__version__,
                        help="print the version and exit")
    parser.add_argument("infile", metavar="infile", type=str, help="source file")
    parser.add_argument(
        "outfile",
        metavar="outfile",
        type=str,
        help="destination file (recommended to use .lds suffix)",
    )

    parser.add_argument(
        "-s",
        "--start",
        metavar="start",
        type=float,
        default=0,
        help="rough jump to frame n of capture (default is 0)",
    )
    parser.add_argument(
        "-l",
        "--length",
        metavar="length",
        type=int,
        default=-1,
        help="limit length to n frames",
    )

    parser.add_argument(
        "-S",
        "--seek",
        metavar="seek",
        type=int,
        default=-1,
        help="seek to frame n of capture",
    )
    parser.add_argument(
        "-E", "--end", metavar="end", type=int, default=-1, help="cutting: last frame"
    )

    parser.add_argument(
        "-p", "--pal", dest="pal", action="store_true", help="source is in PAL format"
    )
    parser.add_argument(
        "-n", "--ntsc", dest="ntsc", action="store_true", help="source is in NTSC format"
    )
    parser.add_argument(
        "-C",
        "--ldf-compression-level",
        dest="ldfcomp",
        type=int,
        default=11,
        help="compression level for .ldf files",
    )

    parser.add_argument(
        "-F",
        "--fmpeg-options",
        dest="ffmpeg_options",
        type=str,
        default=None,
        help="custom ffmpeg format options"
    )

    return parser


def resolve_output(outname):
    """Destination name and writer choice for the outfile argument.

    "-" means stdout, and the writer is picked from the last three
    characters of the name: .lds packs in-process, .ldf pipes through
    ld-compress, anything else is written as raw 16-bit samples.  Note
    that redirecting to stdout therefore always produces raw samples.
    """
    if outname == '-':
        outname = "/dev/stdout"

    makelds = True if outname[-3:] == "lds" else False
    makeldf = True if outname[-3:] == "ldf" else False

    return outname, makelds, makeldf


def same_file(infile, outname):
    """True when outname names the capture being read.

    The writers open their destination for writing (ffmpeg with -y), which
    truncates it; with the input as the destination the capture is gone
    before the first read.  Compared by identity when the output already
    exists (catching links and /dev/stdout redirected onto the input), and
    by resolved path otherwise.  "-" input (stdin) is never a file here.
    """
    if infile == "-":
        return False
    try:
        if os.path.exists(outname) and os.path.samefile(infile, outname):
            return True
    except OSError:
        pass
    return os.path.realpath(infile) == os.path.realpath(outname)


def main(args=None):
    # Handle --version early before argparse requires positional arguments
    check_args = args if args is not None else sys.argv[1:]
    if "--version" in check_args or "-v" in check_args:
        from lddecode import __version__
        print(__version__)
        sys.exit(0)

    parser = build_parser()
    args = parser.parse_args(args)

    filename = args.infile
    outname, makelds, makeldf = resolve_output(args.outfile)

    if args.pal and args.ntsc:
        print("ERROR: Can only be PAL or NTSC", file=sys.stderr)
        sys.exit(1)

    if args.start < 0:
        print("ERROR: --start must not be negative", file=sys.stderr)
        sys.exit(1)

    if args.length != -1 and args.length < 1:
        print("ERROR: --length must be at least 1 frame", file=sys.stderr)
        sys.exit(1)

    # Before anything opens the output: every writer truncates it.
    if same_file(filename, outname):
        print(f"ERROR: output {args.outfile} is the input file", file=sys.stderr)
        sys.exit(1)

    try:
        loader = make_loader(filename, None)
    except ValueError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    system = "PAL" if args.pal else "NTSC"

    # Wrap the LDdecode creation so that the signal handler is not taken by sub-threads,
    # allowing SIGINT/control-C's to be handled cleanly
    original_sigint_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
    logger = init_logging(None)
    ldd = LDdecode(filename, None, loader, system=system, doDOD=False, _logger=logger)
    signal.signal(signal.SIGINT, original_sigint_handler)

    # note that endloc and startloc are in field #'s

    if args.seek != -1:
        startloc = ldd.seek(args.seek if args.start == 0 else args.start, args.seek)
        if startloc is None:
            print("ERROR: Seeking failed", file=sys.stderr)
            sys.exit(1)
        elif startloc > 1:
            startloc -= 1
    else:
        startloc = args.start * 2

    if args.end != -1:
        # seek() takes a frame number to start probing from, not a field
        endloc = ldd.seek(startloc // 2, args.end)
        if endloc is None:
            print("ERROR: Seeking failed", file=sys.stderr)
            sys.exit(1)
    elif args.length != -1:
        endloc = startloc + (args.length * 2) + 2
    else:
        # Set end location to well after any reasonable length so EOF is reached
        endloc = startloc + (2 ** 40)

    ldd.roughseek(startloc)
    startidx = int(ldd.fdoffset)

    ldd.roughseek(endloc)
    endidx = int(ldd.fdoffset)

    process = None
    if args.ffmpeg_options is not None:
        process, fd = ffmpeg_pipe(outname, args.ffmpeg_options)
    elif makelds:
        # Pack in-process rather than piping through the ld-lds-converter-py
        # command, so .lds output does not depend on PATH
        fd = LdsWriter(outname)
    elif makeldf:
        process, fd = ldf_pipe(outname, args.ldfcomp)
    else:
        fd = open(outname, "wb")

    try:
        for i in range(startidx, endidx, 16384):
            l = min(endidx - i, 16384)

            data = ldd.freader(ldd.infile, i, l)
            if data is not None and len(data) == l:
                if makelds or makeldf or args.ffmpeg_options is not None:
                    # Encoders take signed 16-bit samples
                    dataout = samples_to_s16(data)
                else:
                    dataout = np.array(data, dtype=np.int16)
                fd.write(dataout)
            else:
                break
    finally:
        fd.close()
        # Let the encoder flush its last frames before ld-cut exits, so a
        # following command never reads a truncated file.
        if process is not None:
            process.wait()

    input_failed = getattr(loader, "failed", None)
    if input_failed:
        print(f"ERROR: input ended early ({input_failed}); {outname} is incomplete",
              file=sys.stderr)
        sys.exit(1)

    if process is not None and process.returncode != 0:
        print(f"ERROR: encoder exited with status {process.returncode}; "
              f"{outname} is incomplete", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main(sys.argv[1:])
