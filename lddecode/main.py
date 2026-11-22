#!/usr/bin/env python3
import os
import signal
import sys
import argparse
import traceback
import numpy as np

from lddecode.decoder import LDdecode
from lddecode.fileio import (RawCapture, capture_sample_rate, ldf_pipe, make_loader,
                             parse_frequency, raw_layout, samples_to_s16)
from lddecode.utils_logging import init_logging

# FLAC decode threads for a compressed input when the decode itself is
# threaded (see fileio.LoadLDF).  On an 18-core box, NTSC CVBS: -t 8 19.1 ->
# 21.9 fps and -t 4 11.4 -> 13.7 fps with 4; 2 was slower than 1, and one
# per core no better than 4.
FLAC_DECODE_THREADS = 4


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
    # main() answers --version before parsing (the positionals would
    # otherwise be demanded first); registered here so --help lists it.
    from lddecode import __version__
    parser.add_argument("-v", "--version", action="version", version=__version__,
                        help="print the version and exit")
    parser.add_argument("infile", metavar="infile", type=str, nargs="?",
                        help="source file (or use -i)")
    parser.add_argument(
        "outfile", metavar="outfile", type=str, nargs="?",
        help="base name for destination files (or use -o)"
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="inputs",
        metavar="file",
        action="append",
        help="source file; repeat to stack several captures of the same disc. "
             "The first is the primary",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output",
        metavar="base",
        help="base name for destination files (with -i)",
    )
    parser.add_argument(
        "--tbc-mode",
        dest="tbc_mode",
        choices=("read", "resample"),
        default="resample",
        help="time-base correction: 'resample' (the default) resamples the "
             "demodulated video, the reference decoder's way; 'read' locates "
             "the lines straight from the RF and reads the RF at the corrected "
             "positions before demodulating (needed to stack several -i)",
    )
    parser.add_argument(
        "--stack-weight",
        dest="stack_weight",
        choices=("adaptive", "fixed"),
        default="adaptive",
        help="how a stack weighs its inputs: 'adaptive' (per sample, by "
             "carrier amplitude, with an alignment guard) or 'fixed' (one "
             "weight per input)",
    )
    parser.add_argument(
        "--keep-audio-crosstalk",
        dest="keep_audio_crosstalk",
        action="store_true",
        help="leave the analog audio carriers' crosstalk in the video "
             "(--tbc read takes it out by default)",
    )
    parser.add_argument(
        "--keep-crystal-lines",
        dest="keep_crystal_lines",
        action="store_true",
        help="leave the clock lines in the RF (--tbc read subtracts them by "
             "default)",
    )
    parser.add_argument(
        "--keep-chroma-leak",
        dest="keep_chroma_leak",
        action="store_true",
        help="leave the chroma that leaks into the RF baseband (NTSC; --tbc "
             "read cancels it by default)",
    )
    parser.add_argument(
        "--device",
        dest="device",
        choices=("cpu", "opencl"),
        default="cpu",
        help="where --tbc-mode read reads and combines the captures: 'cpu' "
             "(every core, the default) or 'opencl' (a GPU; needs pyopencl)",
    )
    parser.add_argument(
        "--device-precision",
        dest="device_precision",
        choices=("double", "single"),
        default="double",
        help="the precision of --device opencl: 'double' (the default) or "
             "'single' (faster on a consumer GPU)",
    )
    parser.add_argument(
        "--rf-out",
        dest="rf_out",
        metavar="file",
        default=None,
        help="also write the RF the decoder reads (the stacked or "
             "time-base corrected stream, s16 at the input rate)",
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
    parser.add_argument(
        "--cvbs-legacy-origin",
        dest="cvbs_legacy_origin",
        action="store_true",
        help="keep the decoder's own line origin in CVBS output, as written "
        "before frames were 0H-aligned (NTSC 0H 0.3-1.9 samples after "
        "sample 0), for readers built to that layout; not spec compliant, "
        "and noted in the .meta capture_notes",
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
        "--no_mtf_servo",
        action="store_true",
        help="Do not adapt the MTF level from the 2T pulse; keep the level the "
        "RF black-to-white ratio gives (the readout MTF model, NTSC's "
        "default, never runs the servo)",
    )
    parser.add_argument(
        "--calibration_frames",
        metavar="frames",
        type=int,
        default=0,
        help="Run a calibration pass: decode at least this many frames ahead "
        "to settle the calibration servos (MTF, chroma, video EQ, chroma DG) "
        "before the first frame is written; 10 is a good choice (default 0: "
        "no pass, write as soon as they are stable)",
    )
    parser.add_argument(
        "-t",
        "--threads",
        metavar="threads",
        type=int,
        default=0,
        help="worker threads for block demodulation "
             "(0 = auto (default): min(physical cores - 2, 10); 1 = serial)",
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
             "MTF drift and chroma DG trims are tolerated for throughput",
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
        "--no_auto_chroma",
        dest="auto_chroma",
        action="store_false",
        default=True,
        help="Disable the automatic chroma level correction (the inverse-MTF "
             "chroma filter, its strength set from the colour burst and "
             "bounded by the VITS multiburst).  The chroma is then written as "
             "the filter chain demodulates it, and the burst level measured "
             "is recorded in the output's capture notes either way",
    )

    parser.add_argument(
        "--vits_white_level",
        dest="vits_white_level",
        action="store_true",
        default=False,
        help="Scale the luminance so that the VITS white bar (the PAL ITS's, "
             "NTSC's NTC-7) reads 100 IRE: corrects a disc mastered a "
             "percent or so hot or cold.  Applied at write time to the "
             "TBC and CVBS outputs; sync, burst and chroma are left as "
             "they are.  No effect on discs without that bar",
    )

    parser.add_argument(
        "--no_chroma_dg",
        dest="chroma_dg",
        action="store_false",
        default=True,
        help="Disable the chroma differential gain/phase servo (measured "
             "from the VITS modulated staircase - the PAL ITS, NTSC's NTC-7 "
             "composite - and corrected on the TBC and CVBS outputs at "
             "write time)",
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
        "--audio_carrier_cancel",
        dest="audio_carrier_cancel",
        action="store_true",
        default=False,
        help="Prototype: subtract the analog audio carriers' intermodulation "
        "lines (2.30 and 2.81 MHz) from NTSC video, fitted per block to the "
        "carriers' own phase.  NTSC only.",
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
        help="Deemphasis low frequency in mhz (defaults:  NTSC 3.125mhz, PAL 2.5mhz)",
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
        help="Strength of deemphasis (default: NTSC 0.96, PAL 1.0; giving one "
             "also stops the burst from setting the inverse-MTF chroma "
             "strength, see --no_auto_chroma)",
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
        help="Analog audio output sample rate in hz (default is 44100hz)",
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
        help="Video BPF low end frequency",
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


def build_options(args, core_count=None):
    """Map parsed arguments onto the decoder's option dictionaries.

    Pure apart from the fatal exits on contradictory flags: everything
    here is decided by the command line alone, before any file is opened,
    so the mapping can be checked without running a decode.  The one thing
    the machine decides, the auto (-t 0) thread count, comes from
    `core_count`, a callable giving the physical core count
    (physical_cpu_count when None).
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
        # capped at 10 (diminishing returns past that on the shared read
        # path).  Physical cores, not SMT threads: the workers are
        # FFT-bound and two of them on one core's siblings run at about
        # half speed each, so an 8-core/16-thread box decodes faster with
        # 6 workers than with 10.
        threads = min(max((core_count or physical_cpu_count)() - 2, 1), 10)

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
        "auto_deemp": args.auto_chroma and args.deemp_strength is None,
        "auto_chroma": args.auto_chroma,
        "chroma_dg": args.chroma_dg,
        "calibration_frames": max(0, args.calibration_frames),
        "vits_white_level": args.vits_white_level,
        "MTF_level": args.MTF,
        "MTF_offset": args.MTF_offset,
        "mtf_servo": not args.no_mtf_servo,
        # parse_frequency gives MHz; the audio filters take Hz
        "audio_filterwidth": (
            args.audio_filterwidth * 1000000 if args.audio_filterwidth is not None else None
        ),
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

    if vid_standard == "NTSC" and args.audio_carrier_cancel:
        extra_options["AudioCarrierCancel"] = True

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
        extra_options["cvbs_legacy_origin"] = args.cvbs_legacy_origin

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


def count_cores(sibling_lists):
    """Physical cores described by a set of sysfs thread_siblings_list
    strings ("0,8", "1-3", ...): SMT siblings of one core share a
    list, so the distinct lists count the cores."""
    cores = set()
    for text in sibling_lists:
        cpus = set()
        for part in text.strip().split(","):
            if not part:
                continue
            if "-" in part:
                lo, hi = part.split("-", 1)
                cpus.update(range(int(lo), int(hi) + 1))
            else:
                cpus.add(int(part))
        if cpus:
            cores.add(frozenset(cpus))
    return len(cores)


def read_sibling_lists(sysfs):
    """Every thread_siblings_list in the Linux CPU topology under sysfs."""
    import glob
    lists = []
    for path in glob.glob(
            os.path.join(sysfs, "cpu[0-9]*", "topology",
                         "thread_siblings_list")):
        with open(path) as fh:
            lists.append(fh.read())
    return lists


def physical_cpu_count(sysfs="/sys/devices/system/cpu",
                       read_lists=read_sibling_lists):
    """Physical cores on this machine, from the Linux CPU topology;
    the logical count wherever that is not exposed.  `read_lists(sysfs)`
    returns the topology's thread_siblings_list strings."""
    logical = os.cpu_count() or 4
    try:
        cores = count_cores(read_lists(sysfs))
    except (OSError, ValueError):
        return logical
    return cores if 0 < cores <= logical else logical


def resolve_io(args):
    """The capture list and the output base name.

    The positional form (infile outfile) and the -i/-o form are exclusive.
    -i may be repeated: the captures are then stacked, the first one is the
    primary.  Raises ValueError when the two forms are mixed or when the
    output name is missing.
    """
    positional = args.infile is not None
    flagged = bool(args.inputs)
    if positional and flagged:
        raise ValueError("give either infile or -i, not both")
    if flagged and args.output is None:
        raise ValueError("-i needs -o, the base name for the destination files")
    if not flagged and args.output is not None:
        raise ValueError("-o needs -i")
    inputs = list(args.inputs) if flagged else [args.infile]
    outname = args.output if flagged else args.outfile
    if outname is None:
        raise ValueError("no output file name given")
    return inputs, outname


def build_stacked_source(inputs, args, vid_standard):
    """The stacked, time-base-corrected RF source the decoder reads.

    Returns (source, fs), the source and the capture rate in Hz.  Raises
    ValueError when the captures cannot be read that way: a capture that is
    not fixed-width raw, a capture whose sample rate is unknown, or captures
    that do not share one sample rate.
    """
    # The captures are checked before the stacking module is imported, so
    # that a capture the read-time TBC cannot serve is reported as such.
    rates = set()
    for path in inputs:
        if path == "-":
            raise ValueError("the read-time TBC reads its input at random positions, "
                             "which stdin cannot do")
        if raw_layout(path) is None:
            raise ValueError(
                "--tbc read needs a fixed-width raw input (s16, raw, r16, u16, "
                f"r8, u8, s8, rf); {path} is not one"
            )
        rate = capture_sample_rate(path, args.inputfreq)
        if rate is None:
            raise ValueError(
                f"the sidecar next to {path} gives no readable sample_rate_hz; "
                "pass the capture's rate with -f/--frequency"
            )
        rates.add(round(rate))
    if len(rates) > 1:
        raise ValueError("stacked captures must share one sample rate")
    fs = float(rates.pop())

    from lddecode.stack import StackInput, StackedSource

    files = []
    try:
        captures = []
        for path in inputs:
            capture = RawCapture(path)
            files.append(capture)
            captures.append(
                StackInput(path=path, read_fn=capture.read, length=capture.length)
            )
        source = StackedSource(
            captures,
            fs,
            ntsc=(vid_standard != "PAL"),
            stack_weight=args.stack_weight,
            cancel_xtalk=not args.keep_audio_crosstalk,
            cancel_xtal=not args.keep_crystal_lines,
            cancel_leak=not args.keep_chroma_leak,
            rf_out=args.rf_out,
            rf_out_dtype=raw_layout(inputs[0])[0],
            device=args.device,
            device_precision=args.device_precision,
        )
    except BaseException:
        for capture in files:
            capture.close()
        raise
    return StackedLoader(source, files), fs


class StackedLoader:
    """The stacked source in the loader protocol the decoder reads.

    Called as ``loader(infile, sample, readlen)`` like every capture loader
    (``infile`` is ignored: the source reads its own captures).  The decoder
    closes its reader through ``_close``, which stops the source's
    read-ahead, closes the ``--rf-out`` file and the captures.

    Thread-safety: the decoder serialises its raw reads under one reader
    lock, and the source serves one reader at a time.
    """

    def __init__(self, source, files=()):
        self.source = source
        self._files = list(files)

    def __call__(self, _infile, sample, readlen):
        return self.source.read(sample, readlen)

    def _close(self):
        try:
            self.source.close()
        finally:
            for capture in self._files:
                capture.close()
            self._files = []


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
    try:
        inputs, outname = resolve_io(args)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    filename = inputs[0]
    firstframe = args.start
    req_frames = args.length
    options = build_options(args)
    vid_standard = options["system"]
    analog_audio_freq = options["analog_audio_freq"]
    extra_options = options["extra_options"]
    DecoderParamsOverride = options["decoder_params_override"]

    # The time-base correction: "resample" (the default) is the reference
    # decoder's way, and keeps its bytes; "read" locates the lines straight
    # from the RF and reads the RF at the corrected positions before
    # demodulating.  It is only ever what was asked for: the mode never
    # changes with the input, and a "read" that cannot run is an error.
    tbc_mode = args.tbc_mode
    if args.write_test_ldf is not None and tbc_mode == "read":
        # --write-test-ldf re-reads the capture at the positions the decode
        # read; those of the virtual stream are not the capture's.
        print("ERROR: --write-test-ldf copies the capture the decoder read; it needs "
              "--tbc-mode resample", file=sys.stderr)
        sys.exit(1)
    if tbc_mode == "resample" and len(inputs) > 1:
        print("ERROR: several inputs are stacked with the read-time TBC; "
              "pass --tbc-mode read", file=sys.stderr)
        sys.exit(1)
    if args.device != "cpu" and tbc_mode != "read":
        print("ERROR: --device runs the read-time TBC; it needs --tbc-mode read",
              file=sys.stderr)
        sys.exit(1)
    if args.rf_out is not None and tbc_mode != "read":
        print("ERROR: --rf-out writes the read-time corrected RF; it needs "
              "--tbc-mode read", file=sys.stderr)
        sys.exit(1)

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

    loader = None
    if tbc_mode == "resample":
        try:
            loader = make_loader(
                filename,
                args.inputfreq,
                decode_threads=FLAC_DECODE_THREADS if extra_options["threads"] > 1 else 1,
            )
        except ValueError as e:
            print(e, file=sys.stderr)
            sys.exit(1)

    # Wrap the LDdecode creation so that the signal handler is not taken by sub-threads,
    # allowing SIGINT/control-C's to be handled cleanly
    original_sigint_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)

    logger = init_logging(outname + ".log")

    from lddecode import __version__
    logger.debug("ld-decode version " + __version__)

    # The rate the decoder demodulates at.  The loader resamples the RF to
    # 40 MHz, so that is the rate the decoder is told about.
    decoder_inputfreq = 40

    if tbc_mode == "read":
        try:
            loader, fs = build_stacked_source(inputs, args, vid_standard)
        except Exception as e:
            print(f"ERROR: --tbc-mode read: {e}", file=sys.stderr)
            sys.exit(1)
        # The virtual stream is at the captures' own rate: the decoder
        # demodulates it there, as the reference implementation does.  Told
        # 40 MHz, it would look for the sync pulses of a line that is 4767
        # samples long at 75 MHz in a 2542-sample line, and find none.
        decoder_inputfreq = fs / 1e6
        logger.info("Read-time TBC: %d capture(s) at %g MHz, %s weights, on %s",
                    len(inputs), fs / 1e6, args.stack_weight, args.device)

    ldd = LDdecode(
        filename,
        outname,
        loader,
        logger,
        est_frames=req_frames,
        inputfreq=decoder_inputfreq,
        analog_audio=0 if args.daa else analog_audio_freq,
        digital_audio=not args.noefm,
        system=vid_standard,
        doDOD=not args.nodod,
        extra_options=extra_options,
        DecoderParamsOverride=DecoderParamsOverride,
    )

    signal.signal(signal.SIGINT, original_sigint_handler)

    # Store the starting sample position for --write-test-ldf
    start_sample_position = None

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

    while not done and ldd.fields_written < (req_frames * 2):
        try:
            f = ldd.readfield()
        except KeyboardInterrupt:
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

    # A loader that hit a decode error ends the input as end of file does;
    # the output then stops there, and must not be reported as complete.
    input_failed = getattr(loader, "failed", None)
    exit_status = 1 if input_failed else 0
    if input_failed:
        message = (f"Input could not be read past sample {int(ldd.fdoffset)} "
                   f"({input_failed}); the output is incomplete")
        logger.error(message)
        print(f"\nERROR: {message}", file=sys.stderr)
    elif ldd.fields_written:
        print("\nCompleted, exiting.", file=sys.stderr)
    else:
        print("\nCompleted without handling any frames.", file=sys.stderr)

    # Write the input .ldf file if requested
    if args.write_test_ldf is not None and start_sample_position is not None:
        # Add buffer for decoder lookahead - approximately 1.5 field's worth
        # The decoder needs to read ahead for proper field decoding
        # NTSC: ~665K samples/field, PAL: ~1.05M samples/field
        buffer_samples = 1100000  # Safe for both NTSC and PAL
        end_sample_position = int(ldd.fdoffset) + buffer_samples
        if not write_input_ldf_file(
            ldd,
            args.write_test_ldf,
            start_sample_position,
            end_sample_position,
            filename,
            args.inputfreq,
        ):
            exit_status = 1

    cleanup()

    if exit_status:
        sys.exit(exit_status)

#    print(time.time()-firstdecode)


def write_input_ldf_file(
    ldd, output_filename, start_sample, end_sample, input_filename, inputfreq=None
):
    """
    Write the input samples that were decoded to a .ldf file.
    This creates a reproducible test case for bug reporting.

    The .ldf is encoded under a ".part" name and moved into place only once
    every sample was read and ffmpeg exited cleanly, so a failed run leaves
    nothing that looks like a good capture.  Returns True on success.
    """
    print(f"\nWriting input samples to {output_filename}...", file=sys.stderr)
    print(f"  Start sample: {start_sample}", file=sys.stderr)
    print(f"  End sample: {end_sample}", file=sys.stderr)

    sample_count = end_sample - start_sample
    if sample_count <= 0:
        print("WARNING: No samples to write", file=sys.stderr)
        return True

    # Create a new loader for reading the input file independently.  It must
    # resample exactly as the decode's loader did: the start and end positions
    # count 40 MHz samples, and the .ldf is written at 40 MHz.
    try:
        input_loader = make_loader(input_filename, inputfreq)
    except ValueError as e:
        print(f"ERROR: Cannot open input file for writing .ldf: {e}", file=sys.stderr)
        return False

    partial = output_filename + ".part"
    failure = None
    ended_at = None
    samples_written = 0

    # The raw loaders seek and read a file object (and LoadFFmpeg hands it to
    # ffmpeg as stdin), so give them one rather than the filename.
    try:
        infile = open(input_filename, "rb")
        # Use compression level 6 (balanced between size and speed)
        process, fd = ldf_pipe(partial, compression_level=6)
    except OSError as e:
        print(f"ERROR: Cannot write {output_filename}: {e}", file=sys.stderr)
        return False

    try:
        # Write samples in chunks to avoid memory issues
        chunk_size = 16384

        for i in range(start_sample, end_sample, chunk_size):
            read_len = min(chunk_size, end_sample - i)

            # Read the data from the input file using the independent loader
            data = input_loader(infile, i, read_len)
            if data is None or len(data) != read_len:
                # The window runs past the last decoded field, so a decode
                # that reached the end of the input ends here too.
                ended_at = i
                break
            fd.write(samples_to_s16(data))
            samples_written += read_len
    except OSError as e:
        # BrokenPipeError: ffmpeg has died, and its status says more
        if not isinstance(e, BrokenPipeError):
            failure = str(e)
    finally:
        infile.close()
        try:
            fd.close()
        except OSError:
            pass
        status = process.wait()

    input_failed = getattr(input_loader, "failed", None)
    if failure is None and input_failed:
        failure = f"input could not be read past sample {ended_at} ({input_failed})"
    if failure is None and status != 0:
        failure = f"ffmpeg exited with status {status}"
    if failure is None:
        try:
            os.replace(partial, output_filename)
        except OSError as e:
            failure = f"could not move it into place: {e}"

    if failure is not None:
        print(f"ERROR: {output_filename} was not written: {failure}", file=sys.stderr)
        try:
            os.unlink(partial)
        except OSError:
            pass
        return False

    print(f"  Samples written: {samples_written}", file=sys.stderr)
    if ended_at is not None:
        print(f"Wrote {output_filename}: the input ends at sample {ended_at}, "
              f"so it holds {samples_written} of the {sample_count} samples "
              "requested", file=sys.stderr)
    else:
        print(f"Successfully wrote {output_filename}", file=sys.stderr)
    return True


if __name__ == "__main__":
    main()
