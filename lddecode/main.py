#!/usr/bin/env python3
import os
import signal
import sys
import argparse
import traceback
import numpy as np

from lddecode.decoder import LDdecode
from lddecode.fileio import ldf_pipe, make_loader, parse_frequency
from lddecode.utils_logging import init_logging


def build_parser():
    """The ld-decode command line, as an argparse parser.

    Separate from main() so the flag definitions can be exercised without
    starting a decode; build_options() maps what it returns onto the
    decoder's option dictionaries.
    """
    options_epilog = """FREQ can be a bare number in MHz, or a number with one of the case-insensitive suffixes Hz, kHz, MHz, GHz, fSC (meaning NTSC) or fSCPAL."""
    parser = argparse.ArgumentParser(
        description="Extracts audio and video from raw RF laserdisc captures",
        epilog=options_epilog,
        formatter_class=argparse.RawTextHelpFormatter
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
    parser.add_argument(
        "--cvbs",
        dest="cvbs",
        action="store_true",
        default=True,
        help="write spec-compliant CVBS output (<out>.cvbs/.meta and "
        "spec WAV audio; this is the default)",
    )
    parser.add_argument(
        "--tbc",
        dest="cvbs",
        action="store_false",
        help="write the legacy .tbc/.tbc.db video output instead of CVBS",
    )
    parser.add_argument(
        "--cvbs-encoding",
        dest="cvbs_encoding",
        choices=["CVBS_U10_4FSC", "CVBS_U16_4FSC"],
        default=None,
        help="sample encoding preset for CVBS output "
        "(default: CVBS_U10_4FSC for PAL, CVBS_U16_4FSC for NTSC)",
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
        "-t",
        "--threads",
        metavar="threads",
        type=int,
        default=0,
        help="worker threads for block demodulation "
             "(0 = auto (default): min(cores - 2, 10); 1 = serial)",
    )
    parser.add_argument(
        "--demod-threads-only",
        dest="demod_threads_only",
        action="store_true",
        default=False,
        help="with -t: keep block demodulation in threads instead of worker processes",
    )
    parser.add_argument(
        "--exact-speculation",
        dest="exact_speculation",
        action="store_true",
        default=False,
        help="with -t: discard fields decoded ahead under old decoder parameters "
             "on any parameter change (bit-exact with -t 1); by default minor "
             "MTF drift is tolerated for throughput",
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
        "--tbc_efm",
        dest="tbc_efm",
        action="store_true",
        default=False,
        help="Time-base-correct the EFM waveform onto the video line time-base "
        "before the EFM PLL (removes wow/flutter drift; aligns EFM across "
        "captures of the same disc for pre-PLL stacking)",
    )
    parser.add_argument(
        "--efm_demod",
        "--efm-demod",
        dest="efm_demod",
        choices=["pll", "timing"],
        default="timing",
        help="EFM demodulator: 'timing' (default) is the symbol-rate "
        "timing-recovery demodulator (per-channel-bit Mueller & Muller loop "
        "with bit-domain frame sync); 'pll' is the previous zero-crossing "
        "run-length PLL",
    )
    parser.add_argument(
        "--efm_conf",
        dest="efm_conf",
        choices=["auto", "on", "off"],
        default="auto",
        help="Confidence-packed .efm output for .tbc mode (4-bit doubt, "
        "0 = trusted, in the high nibble of each T-value byte).  'auto' "
        "(default) and 'off' keep the plain .efm working with legacy "
        "tools.  CVBS output always packs (the EFM extension format "
        "defines the byte layout), so this option only affects .tbc "
        "output.  LDDECODE_EFM_EMITCONF=1/0 is the environment "
        "equivalent of on/off",
    )
    parser.add_argument(
        "--efm_eq_taps",
        dest="efm_eq_taps",
        type=int,
        default=0,
        help="Experimental: tap count for the timing demodulator's "
        "decision-directed adaptive equaliser (0 = off, the default; odd "
        "3..15 enables it).  Measured neutral-to-harmful on the validation "
        "captures - see docs/technical/efm-decoding.md before using",
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
        help="Enable additional VITS metrics",
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
        "--no_chroma_dg",
        dest="chroma_dg",
        action="store_false",
        default=True,
        help="Disable the chroma differential gain/phase servo (measured "
             "from the VITS modulated staircase, corrected on the TBC and "
             "CVBS outputs at write time; PAL only)",
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
        help="LD-V4300D PAL/digital audio captures: remove the spurious "
        "~8.5mhz digital-audio clock signal (legacy alias for "
        "--V4300D_coherent_subtract)",
    )

    parser.add_argument(
        "--V4300D_coherent_subtract",
        dest="V4300D_coherent_subtract",
        action="store_true",
        default=False,
        help="Coherently estimate and subtract the LD-V4300D's 8.4672mhz "
        "digital-audio clock spur and its +-88.2khz satellites. "
        "Self-disabling on captures without the spur. PAL only.",
    )

    parser.add_argument(
        "--rf_echo_cancel",
        dest="rf_echo_cancel",
        action="store_true",
        default=False,
        help="Cancel the capture/player multi-path reflection (\"ghost\"): "
        "auto-detect echo taps from the RF cepstrum, re-estimated across the "
        "disc, and apply the correction only when it measurably reduces the "
        "echo (no-op otherwise).  Forces serial demod.",
    )

    parser.add_argument(
        "--rf_echo",
        dest="rf_echo",
        type=str,
        default="",
        help="Manual echo taps for --rf_echo_cancel as comma-separated "
        "delay_samples:amplitude pairs (e.g. 17:0.11,28:0.05); overrides auto "
        "detection and keeps parallel demod.",
    )

    parser.add_argument(
        "--V4300D_no_defer",
        dest="V4300D_no_defer",
        action="store_true",
        default=False,
        help="Obsolete; accepted for compatibility and ignored.  The spur "
        "filter no longer defers (its no-video guard makes it safe from the "
        "first block) and parallel demod is always available.",
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
        default=None,
        help="Strength of deemphasis (default: 1.0; disables auto inverse-MTF chroma calibration)",
    )

    parser.add_argument(
        "--wow_level_adjust_smoothing",
        type=float,
        default=0,
        help=(
            "Adjusts the amount of smoothing in lines that is performed when compensating for brightness variations caused by wow. (default 0)"
            "\nWow calculation is based on position of hsync pulses which is affected by the accuracy of the TBC. "
            "\nIf you see vertical brightness variations (banding), setting to a value larger than 0 will smooth the wow adjustment."
        )
    )
    parser.add_argument(
        "--wow_interpolation_method",
        type=str,
        default="linear",
        choices=["linear", "quadratic", "cubic"],
        help=(
            "Sets the type of interpolation spline used to correct wow."
            "\n  linear     [default]"
            "\n  quadratic"
            "\n  cubic"
        )
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
        "--ntsc_audio_rate",
        dest="ntsc_audio_rate",
        action="store_true",
        default=False,
        help="Output analog audio locked to NTSC line timing "
        "(2.8 samples/line = 1470 samples/frame, ~44055.944hz) instead of 44100hz. "
        "NTSC only; ignored for PAL (already frame-locked at 44100hz).",
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

    parser.add_argument(
        "--write-test-ldf",
        dest="write_test_ldf",
        metavar="output.ldf",
        type=str,
        default=None,
        help="Write the input portion being decoded to a .ldf file for bug reporting",
    )

    return parser


def build_options(args):
    """Map parsed arguments onto the decoder's option dictionaries.

    Pure apart from the fatal exits on contradictory flags: everything
    here is decided by the command line alone, before any file is opened,
    so the mapping can be checked without running a decode.
    """
    vid_standard = "PAL" if args.pal else "NTSC"

    if args.pal and (args.ntsc or args.ntscj):
        print("ERROR: Can only be PAL or NTSC")
        sys.exit(1)

    # Resolve the analog audio output rate.  A negative value is interpreted
    # downstream as a multiple of the horizontal line frequency (HSYNC-locked
    # output); -2.8 yields exactly 2.8 samples/line (1470 samples/frame),
    # locking the audio to NTSC timing at ~44055.944hz.  PAL is already
    # frame-locked at 44100hz (1764 samples/frame), so the flag is a no-op there.
    analog_audio_freq = args.analog_audio_freq
    if args.ntsc_audio_rate:
        if vid_standard == "NTSC":
            analog_audio_freq = -2.8
        else:
            print(
                "WARNING: --ntsc_audio_rate ignored for PAL "
                "(audio is already frame-locked at 44100hz)",
                file=sys.stderr,
            )

    threads = args.threads
    if threads == 0:
        # auto (the default): leave 2 cores for the OS / main decode loop,
        # capped at 10 (diminishing returns past that on the shared read path)
        threads = min(max((os.cpu_count() or 4) - 2, 1), 10)

    extra_options = {
        "threads": threads,
        "process_demod": not args.demod_threads_only,
        "exact_speculation": args.exact_speculation,
        "useAGC": not args.noAGC,
        "write_RF_TBC": args.RF_TBC,
        "pipe_RF_TBC": None,
        "write_pre_efm": args.prefm,
        "tbc_efm": args.tbc_efm,
        "efm_demod": args.efm_demod,
        "efm_conf": args.efm_conf,
        "efm_eq_taps": args.efm_eq_taps,
        "deemp_coeff": (args.deemp_low, args.deemp_high),
        "deemp_str": args.deemp_strength if args.deemp_strength is not None else (1.0 if args.pal else 0.96),
        "auto_deemp": args.deemp_strength is None,
        "chroma_dg": args.chroma_dg,
        "MTF_level": args.MTF,
        "MTF_offset": args.MTF_offset,
        "audio_filterwidth": args.audio_filterwidth,
        "AC3": args.AC3,
        "use_profiler": args.use_profiler,
        "wow_level_adjust_smoothing": args.wow_level_adjust_smoothing,
        "wow_interpolation_method": args.wow_interpolation_method
    }

    if vid_standard == "NTSC" and args.NTSC_color_notch_filter:
        extra_options["NTSC_ColorNotchFilter"] = True

    if args.rf_echo:
        extra_options["rf_echo_cancel"] = [
            (float(p.split(":")[0]), float(p.split(":")[1]))
            for p in args.rf_echo.split(",") if ":" in p
        ]
    elif args.rf_echo_cancel:
        extra_options["rf_echo_cancel"] = True

    if vid_standard == "PAL" and (args.V4300D_notch_filter or args.V4300D_coherent_subtract):
        # --V4300D_notch_filter is a legacy alias: the coherent subtract
        # supersedes the FFT-bin notch (it also removes the leakage skirts
        # and the clock's satellites), and its no-video guard makes lead-in
        # deferral unnecessary, so both switches enable the same filter and
        # parallel demod stays available.
        extra_options["PAL_V4300D_CoherentSubtract"] = True

    if vid_standard == "PAL" and args.AC3:
        print("ERROR: AC3 audio decoding is only supported for NTSC")
        sys.exit(1)

    if args.lowband:
        extra_options["lowband"] = True

    if args.cvbs:
        extra_options["output_cvbs"] = True
        if args.ntscj:
            extra_options["cvbs_black_level"] = 240
        if args.cvbs_encoding:
            extra_options["cvbs_encoding"] = args.cvbs_encoding

    DecoderParamsOverride = {}
    if args.vbpf_low is not None:
        DecoderParamsOverride["video_bpf_low"] = args.vbpf_low * 1000000

    if args.vbpf_high is not None:
        DecoderParamsOverride["video_bpf_high"] = args.vbpf_high * 1000000

    if args.vlpf is not None:
        DecoderParamsOverride["video_lpf_freq"] = args.vlpf * 1000000

    if args.vlpf_order >= 1:
        DecoderParamsOverride["video_lpf_order"] = args.vlpf_order

    return {
        "system": vid_standard,
        "analog_audio_freq": analog_audio_freq,
        "extra_options": extra_options,
        "decoder_params_override": DecoderParamsOverride,
    }


def main(args=None):
    # Handle --version early before argparse requires positional arguments
    check_args = args if args is not None else sys.argv[1:]
    if "--version" in check_args or "-v" in check_args:
        from lddecode import __version__
        print(__version__)
        sys.exit(0)
    parser = build_parser()
    args = parser.parse_args(args)
    # print(args)
    filename = args.infile
    outname = args.outfile
    firstframe = args.start
    req_frames = args.length
    options = build_options(args)
    vid_standard = options["system"]
    analog_audio_freq = options["analog_audio_freq"]
    extra_options = options["extra_options"]
    DecoderParamsOverride = options["decoder_params_override"]

    # Safety check: ensure --write-test-ldf doesn't overwrite the input file
    if args.write_test_ldf is not None:
        # os (and os.path) is imported at module scope; a local re-import
        # here would make `os` function-local and shadow it everywhere else
        # in main().
        input_path = os.path.abspath(filename)
        output_path = os.path.abspath(args.write_test_ldf)
        if input_path == output_path:
            print("ERROR: --write-test-ldf output file cannot be the same as input file", file=sys.stderr)
            print(f"Input:  {filename}", file=sys.stderr)
            print(f"Output: {args.write_test_ldf}", file=sys.stderr)
            sys.exit(1)

    audio_pipe = None

    try:
        loader = make_loader(filename, args.inputfreq)
    except ValueError as e:
        print(e)
        sys.exit(1)

    # Wrap the LDdecode creation so that the signal handler is not taken by sub-threads,
    # allowing SIGINT/control-C's to be handled cleanly
    original_sigint_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)

    logger = init_logging(outname + ".log")

    from lddecode import __version__
    logger.debug("ld-decode version " + __version__)

    ldd = LDdecode(
        filename,
        outname,
        loader,
        logger,
        est_frames=req_frames,
        analog_audio=0 if args.daa else analog_audio_freq,
        digital_audio=not args.noefm,
        system=vid_standard,
        doDOD=not args.nodod,
        extra_options=extra_options,
        DecoderParamsOverride=DecoderParamsOverride,
    )

    signal.signal(signal.SIGINT, original_sigint_handler)

    # Store the starting sample position for --write-input-ldf
    start_sample_position = None
    end_sample_position = None

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

    # Capture the start sample position after all seeking
    if args.write_test_ldf is not None:
        start_sample_position = int(ldd.fdoffset)

    if args.verboseVITS:
        ldd.verboseVITS = True

    done = False

    def cleanup():
        ldd.close()
        if audio_pipe is not None:
            audio_pipe.close()

    while not done and ldd.fields_written < (req_frames * 2):
        try:
            f = ldd.readfield()
        except KeyboardInterrupt as kbd:
            print("\nTerminated, exiting", file=sys.stderr)
            # cleanup() -> ldd.close() finalizes and flushes the .tbc.db;
            # confirm the interrupted decode's metadata was saved.
            cleanup()
            if not ldd.output_cvbs and ldd.fields_written:
                print(
                    f"{outname}.tbc.db written and flushed to disk "
                    f"({ldd.fields_written} fields).",
                    file=sys.stderr,
                )
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

    if ldd.fields_written:
        print(f"\nCompleted, exiting.", file=sys.stderr)
    else:
        print(f"\nCompleted without handling any frames.", file=sys.stderr)

    # Write the input .ldf file if requested
    if args.write_test_ldf is not None and start_sample_position is not None:
        # Add buffer for decoder lookahead - approximately 1.5 field's worth
        # The decoder needs to read ahead for proper field decoding
        # NTSC: ~665K samples/field, PAL: ~1.05M samples/field
        buffer_samples = 1100000  # Safe for both NTSC and PAL
        end_sample_position = int(ldd.fdoffset) + buffer_samples
        write_input_ldf_file(
            ldd,
            args.write_test_ldf,
            start_sample_position,
            end_sample_position,
            filename
        )

    cleanup()

#    print(time.time()-firstdecode)


def write_input_ldf_file(ldd, output_filename, start_sample, end_sample, input_filename):
    """
    Write the input samples that were decoded to a .ldf file.
    This creates a reproducible test case for bug reporting.
    """
    print(f"\nWriting input samples to {output_filename}...", file=sys.stderr)
    print(f"  Start sample: {start_sample}", file=sys.stderr)
    print(f"  End sample: {end_sample}", file=sys.stderr)
    
    sample_count = end_sample - start_sample
    if sample_count <= 0:
        print("WARNING: No samples to write", file=sys.stderr)
        return
    
    # Create a new loader for reading the input file independently
    try:
        input_loader = make_loader(input_filename, None)
    except ValueError as e:
        print(f"ERROR: Cannot open input file for writing .ldf: {e}", file=sys.stderr)
        return
    
    # Use compression level 6 (balanced between size and speed)
    process, fd = ldf_pipe(output_filename, compression_level=6)
    
    try:
        # Write samples in chunks to avoid memory issues
        chunk_size = 16384
        samples_written = 0
        
        for i in range(start_sample, end_sample, chunk_size):
            remaining = end_sample - i
            read_len = min(chunk_size, remaining)
            
            # Read the data from the input file using the independent loader
            data = input_loader(input_filename, i, read_len)
            if data is not None and len(data) == read_len:
                dataout = np.array(data, dtype=np.int16)
                fd.write(dataout)
                samples_written += read_len
            else:
                print(f"WARNING: Short read at sample {i}", file=sys.stderr)
                break
        
        print(f"  Samples written: {samples_written}", file=sys.stderr)
        
    finally:
        fd.close()
        # Wait for ffmpeg to finish encoding
        process.wait()
        
    print(f"Successfully wrote {output_filename}", file=sys.stderr)


if __name__ == "__main__":
    main()
