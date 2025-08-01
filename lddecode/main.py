#!/usr/bin/env python3
import signal
import sys
import argparse
import traceback

from lddecode.core import *
from lddecode.utils import *
from lddecode.utils_logging import init_logging


def main(args=None):
    options_epilog = """FREQ can be a bare number in MHz, or a number with one of the case-insensitive suffixes Hz, kHz, MHz, GHz, fSC (meaning NTSC) or fSCPAL."""
    parser = argparse.ArgumentParser(
        description="Extracts audio and video from raw RF laserdisc captures",
        epilog=options_epilog,
    )
    parser.add_argument("infile", metavar="infile", type=str, help="source file")
    parser.add_argument(
        "outfile", metavar="outfile", type=str, help="base name for destination files"
    )
    parser.add_argument(
        "--start",
        "-s",
        dest="start",
        metavar="file-location",
        type=float,
        default=0,
        help="rough jump to frame n of capture (default is 0)",
    )
    parser.add_argument(
        "--length",
        "-l",
        dest="length",
        metavar="frames",
        type=int,
        default=110000,
        help="limit length to n frames",
    )
    parser.add_argument(
        "--seek",
        "-S",
        dest="seek",
        metavar="frame",
        type=int,
        default=-1,
        help="seek to frame n of capture",
    )
    # parser.add_argument('-E', '--end', metavar='end', type=int, default=-1, help='cutting: last frame')
    parser.add_argument(
        "--PAL",
        "-p",
        "--pal",
        dest="pal",
        action="store_true",
        help="source is in PAL format",
    )
    parser.add_argument(
        "--NTSC",
        "-n",
        "--ntsc",
        dest="ntsc",
        action="store_true",
        help="source is in NTSC format",
    )
    parser.add_argument(
        "--NTSCJ",
        "-j",
        dest="ntscj",
        action="store_true",
        help="source is in NTSC-J (IRE 0 black) format",
    )
    # parser.add_argument('-c', '--cut', dest='cut', action='store_true', help='cut (to r16) instead of decode')
    parser.add_argument(
        "-m",
        "--MTF",
        metavar="mtf",
        type=float,
        default=1.0,
        help="mtf compensation multiplier",
    )
    parser.add_argument(
        "--MTF_offset",
        metavar="mtf_offset",
        type=float,
        default=0,
        help="mtf compensation offset",
    )
    parser.add_argument(
        "--noAGC", dest="noAGC", action="store_true", default=False, help="Disable AGC"
    )
    parser.add_argument(
        "--noDOD",
        dest="nodod",
        action="store_true",
        default=False,
        help="disable dropout detector",
    )
    parser.add_argument(
        "--noEFM",
        dest="noefm",
        action="store_true",
        default=False,
        help="Disable EFM front end",
    )
    parser.add_argument(
        "--preEFM",
        dest="prefm",
        action="store_true",
        default=False,
        help="Write filtered but otherwise pre-processed EFM data",
    )
    parser.add_argument(
        "--disable_analog_audio",
        "--disable_analogue_audio",
        "--daa",
        dest="daa",
        action="store_true",
        default=False,
        help="Disable analog(ue) audio decoding",
    )
    parser.add_argument(
        "--AC3",
        action="store_true",
        default=False,
        help="Enable AC3 audio decoding (NTSC only)",
    )
    parser.add_argument(
        "--start_fileloc",
        metavar="start_fileloc",
        type=float,
        default=-1,
        help="jump to precise sample # in the file",
    )
    parser.add_argument(
        "--ignoreleadout",
        dest="ignoreleadout",
        action="store_true",
        default=False,
        help="continue decoding after lead-out seen",
    )
    parser.add_argument(
        "--verboseVITS",
        dest="verboseVITS",
        action="store_true",
        default=False,
        help="Enable additional JSON fields",
    )

    parser.add_argument(
        "--RF_TBC",
        dest="RF_TBC",
        action="store_true",
        default=False,
        help="Create a .tbc.ldf file with TBC'd RF",
    )

    parser.add_argument(
        "--lowband",
        dest="lowband",
        action="store_true",
        default=False,
        help="Use more restricted RF settings for noisier disks",
    )

    parser.add_argument(
        "--NTSC_color_notch_filter",
        "-N",
        dest="NTSC_color_notch_filter",
        action="store_true",
        default=False,
        help="Mitigate interference from analog audio in reds in NTSC captures",
    )
    parser.add_argument(
        "--V4300D_notch_filter",
        "-V",
        dest="V4300D_notch_filter",
        action="store_true",
        default=False,
        help="LD-V4300D PAL/digital audio captures: remove spurious ~8.5mhz signal",
    )

    parser.add_argument(
        "--deemp_low",
        metavar="deemp_low",
        type=float,
        default=0,
        help="Deemphasis low frequency in nsecs (defaults:  NTSC 3.125mhz, PAL 2.5mhz)",
    )
    parser.add_argument(
        "--deemp_high",
        metavar="deemp_high",
        type=float,
        default=0,
        help="Deemphasis high frequency in mhz (defaults:  NTSC 8.33mhz, PAL 10mhz)",
    )
    parser.add_argument(
        "--deemp_strength",
        metavar="deemp_str",
        type=float,
        default=1,
        help="Strength of deemphasis (default 1.0)",
    )

    parser.add_argument(
        "-t",
        "--threads",
        metavar="threads",
        type=int,
        default=4,
        help="number of CPU threads to use",
    )

    parser.add_argument(
        "-f",
        "--frequency",
        dest="inputfreq",
        metavar="FREQ",
        type=parse_frequency,
        default=None,
        help="RF sampling frequency in source file (default is 40MHz)",
    )

    parser.add_argument(
        "--analog_audio_frequency",
        dest="analog_audio_freq",
        metavar="AFREQ",
        type=int,
        default=44100,
        help="RF sampling frequency in source file (default is 44100hz)",
    )

    parser.add_argument(
        "--video_bpf_low",
        dest="vbpf_low",
        metavar="FREQ",
        type=parse_frequency,
        default=None,
        help="Video BPF high end frequency",
    )
    parser.add_argument(
        "--video_bpf_high",
        dest="vbpf_high",
        metavar="FREQ",
        type=parse_frequency,
        default=None,
        help="Video BPF high end frequency",
    )
    parser.add_argument(
        "--video_lpf",
        dest="vlpf",
        metavar="FREQ",
        type=parse_frequency,
        default=None,
        help="Video low-pass filter frequency",
    )
    parser.add_argument(
        "--video_lpf_order",
        dest="vlpf_order",
        type=int,
        default=-1,
        help="Video low-pass filter order",
    )
    parser.add_argument(
        "--audio_filterwidth",
        dest="audio_filterwidth",
        metavar="FREQ",
        type=parse_frequency,
        default=None,
        help="Analog audio filter width",
    )
    parser.add_argument(
        "--use_profiler",
        action="store_true",
        default=False,
        help="Enable line_profiler on select functions",
    )


    args = parser.parse_args(args)
    # print(args)
    filename = args.infile
    outname = args.outfile
    firstframe = args.start
    req_frames = args.length
    vid_standard = "PAL" if args.pal else "NTSC"

    if args.pal and (args.ntsc or args.ntscj):
        print("ERROR: Can only be PAL or NTSC")
        sys.exit(1)

    audio_pipe = None

    extra_options = {
        "useAGC": not args.noAGC,
        "write_RF_TBC": args.RF_TBC,
        "pipe_RF_TBC": audio_pipe,
        "write_pre_efm": args.prefm,
        "deemp_coeff": (args.deemp_low, args.deemp_high),
        "deemp_str": args.deemp_strength,
        "MTF_level": args.MTF,
        "MTF_offset": args.MTF_offset,
        "audio_filterwidth": args.audio_filterwidth,
        "AC3": args.AC3,
        "use_profiler": args.use_profiler,
    }

    if vid_standard == "NTSC" and args.NTSC_color_notch_filter:
        extra_options["NTSC_ColorNotchFilter"] = True

    if vid_standard == "PAL" and args.V4300D_notch_filter:
        extra_options["PAL_V4300D_NotchFilter"] = True

    if vid_standard == "PAL" and args.V4300D_notch_filter:
        extra_options["PAL_V4300D_NotchFilter"] = True

    if vid_standard == "PAL" and args.AC3:
        print("ERROR: AC3 audio decoding is only supported for NTSC")
        sys.exit(1)

    if args.lowband:
        extra_options["lowband"] = True

    try:
        loader = make_loader(filename, args.inputfreq)
    except ValueError as e:
        print(e)
        sys.exit(1)

    # Wrap the LDdecode creation so that the signal handler is not taken by sub-threads,
    # allowing SIGINT/control-C's to be handled cleanly
    original_sigint_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)

    logger = init_logging(outname + ".log")

    version = get_git_info()
    logger.debug("ld-decode branch " + version[0] + " build " + version[1])

    DecoderParamsOverride = {}
    if args.vbpf_low is not None:
        DecoderParamsOverride["video_bpf_low"] = args.vbpf_low * 1000000

    if args.vbpf_high is not None:
        DecoderParamsOverride["video_bpf_high"] = args.vbpf_high * 1000000

    if args.vlpf is not None:
        DecoderParamsOverride["video_lpf_freq"] = args.vlpf * 1000000

    if args.vlpf_order >= 1:
        DecoderParamsOverride["video_lpf_order"] = args.vlpf_order

    ldd = LDdecode(
        filename,
        outname,
        loader,
        logger,
        est_frames=req_frames,
        analog_audio=0 if args.daa else args.analog_audio_freq,
        digital_audio=not args.noefm,
        system=vid_standard,
        doDOD=not args.nodod,
        threads=args.threads,
        extra_options=extra_options,
        DecoderParamsOverride=DecoderParamsOverride,
    )

    signal.signal(signal.SIGINT, original_sigint_handler)

    if args.start_fileloc != -1:
        ldd.roughseek(args.start_fileloc, False)
    else:
        ldd.roughseek(firstframe * 2)

    if vid_standard == "NTSC" and not args.ntscj:
        ldd.blackIRE = 7.5

    # print(ldd.blackIRE)

    if args.seek != -1:
        if ldd.seek(args.seek if firstframe == 0 else firstframe, args.seek) is None:
            print("ERROR: Seeking failed", file=sys.stderr)
            sys.exit(1)

    if args.verboseVITS:
        ldd.verboseVITS = True

    done = False

    jsondumper = JSONDumper(ldd, outname)

    def cleanup():
        # logger.flush()
        jsondumper.close()
        ldd.close()
        if audio_pipe is not None:
            audio_pipe.close()

    while not done and ldd.fields_written < (req_frames * 2):
        try:
            f = ldd.readfield()
        except KeyboardInterrupt as kbd:
            print("\nTerminated, saving JSON and exiting", file=sys.stderr)
            cleanup()
            sys.exit(1)
        except Exception as err:
            print(
                "\nERROR - please paste the following into a bug report:",
                file=sys.stderr,
            )
            print("current sample:", ldd.fdoffset, file=sys.stderr)
            print("arguments:", args, file=sys.stderr)
            print("Exception:", err, " Traceback:", file=sys.stderr)
            traceback.print_tb(err.__traceback__)
            cleanup()
            sys.exit(1)

        if f is None or (args.ignoreleadout == False and ldd.leadOut == True):
            done = True

        if ldd.fields_written < 100 or ((ldd.fields_written % 500) == 0):
            jsondumper.write()

    if ldd.fields_written:
        print(f"\nCompleted: saving JSON and exiting.", file=sys.stderr)
    else:
        print(f"\nCompleted without handling any frames.", file=sys.stderr)

    cleanup()

#    print(time.time()-firstdecode)
