"""Unit tests for the command line of ld-decode and ld-cut.

Between argparse and the decoder sits a mapping that is easy to break and
expensive to notice: a flag that silently stops reaching extra_options costs a
full decode to spot, and only if someone is looking at the right output.  The
mapping is pure -- it reads the parsed arguments and nothing else -- so it is
exercised here directly, without a decode.

The tests state what each vector *means*, not merely that a key is set: which
system is selected, which options are system-specific and therefore ignored
elsewhere, and which combinations are rejected outright.
"""

import pytest

from lddecode import cut
from lddecode.main import build_options, build_parser

pytestmark = [pytest.mark.unit]

# Every vector needs the two positionals; nothing in the mapping looks at
# them, and no path is ever touched.
BASE = ["capture.lds", "decoded"]


def parse(*argv):
    return build_parser().parse_args(BASE + list(argv))


def options(*argv):
    return build_options(parse(*argv))


def extra(*argv):
    return options(*argv)["extra_options"]


# --- the parser ---------------------------------------------------------


def test_the_positionals_are_the_input_and_the_output_base():
    args = parse()

    assert args.infile == "capture.lds"
    assert args.outfile == "decoded"


def test_an_unknown_flag_is_refused():
    with pytest.raises(SystemExit) as exit_info:
        parse("--not-a-real-flag")

    assert exit_info.value.code == 2


def test_the_positionals_are_required():
    with pytest.raises(SystemExit) as exit_info:
        build_parser().parse_args(["capture.lds"])

    assert exit_info.value.code == 2


@pytest.mark.parametrize("flag", ["--PAL", "-p", "--pal"])
def test_the_pal_flag_has_three_spellings(flag):
    assert parse(flag).pal is True


@pytest.mark.parametrize("flag", ["--NTSC", "-n", "--ntsc"])
def test_the_ntsc_flag_has_three_spellings(flag):
    assert parse(flag).ntsc is True


def test_ranges_are_parsed_as_frames():
    args = parse("-s", "12.5", "-l", "300", "-S", "7")

    assert (args.start, args.length, args.seek) == (12.5, 300, 7)


def test_the_sample_rate_accepts_a_suffixed_frequency():
    """FREQ takes Hz/kHz/MHz/GHz/fSC; the parsed value is in MHz."""
    assert parse("-f", "40").inputfreq == 40.0
    assert parse("-f", "40000000Hz").inputfreq == 40.0
    assert parse("--frequency", "8fsc").inputfreq == pytest.approx(28.6363636)


# --- output format ------------------------------------------------------


def test_composite_output_is_the_default():
    """ld-decode writes CVBS unless asked for TBC (spec v1.6.0)."""
    assert parse().cvbs is True
    assert extra()["output_cvbs"] is True


def test_the_tbc_flag_selects_the_time_base_corrected_output():
    assert parse("--tbc").cvbs is False
    assert "output_cvbs" not in extra("--tbc")


def test_the_output_flags_are_last_one_wins():
    """They share one destination, so the later flag on the line decides --
    which is what makes a wrapper script able to override a default."""
    assert parse("--cvbs", "--tbc").cvbs is False
    assert parse("--tbc", "--cvbs").cvbs is True


def test_a_japanese_ntsc_disc_moves_the_cvbs_black_level():
    """NTSC-J has no 7.5 IRE setup, so composite black sits at a different
    code; only meaningful when composite is actually being written."""
    assert extra("--cvbs", "-j")["cvbs_black_level"] == 240
    assert "cvbs_black_level" not in extra("--cvbs")
    assert "cvbs_black_level" not in extra("--tbc", "-j")


def test_the_cvbs_encoding_is_passed_through():
    """The sample encodings are a closed set, so a typo is caught by argparse
    rather than reaching the writer."""
    assert extra("--cvbs", "--cvbs-encoding", "CVBS_U16_4FSC")[
        "cvbs_encoding"] == "CVBS_U16_4FSC"
    assert "cvbs_encoding" not in extra("--cvbs")

    with pytest.raises(SystemExit) as exit_info:
        parse("--cvbs-encoding", "yc")
    assert exit_info.value.code == 2


# --- system selection ---------------------------------------------------


def test_ntsc_is_the_default_system():
    assert options()["system"] == "NTSC"


@pytest.mark.parametrize("flag", ["--PAL", "-p"])
def test_the_pal_flag_selects_pal(flag):
    assert options(flag)["system"] == "PAL"


def test_ntscj_is_still_ntsc():
    """--NTSCJ changes levels, not the line standard."""
    assert options("-j")["system"] == "NTSC"


@pytest.mark.parametrize("conflict", [["-p", "-n"], ["-p", "-j"], ["-p", "-n", "-j"]])
def test_asking_for_both_systems_is_refused(conflict, capsys):
    with pytest.raises(SystemExit) as exit_info:
        options(*conflict)

    assert exit_info.value.code == 1
    assert "Can only be PAL or NTSC" in capsys.readouterr().out


# --- audio --------------------------------------------------------------


def test_the_analogue_audio_rate_defaults_to_cd_rate():
    assert options()["analog_audio_freq"] == 44100


def test_an_explicit_audio_rate_is_used_as_given():
    assert options("--analog_audio_frequency", "48000")["analog_audio_freq"] == 48000


def test_ntsc_audio_can_be_locked_to_the_line_rate():
    """A negative rate means samples per line rather than Hz: -2.8 is 1470
    samples a frame, which is NTSC's exact 44055.944 Hz."""
    assert options("--ntsc_audio_rate")["analog_audio_freq"] == -2.8


def test_line_locked_audio_is_a_no_op_on_pal(capsys):
    """PAL is already frame-locked at 44100, so the flag is refused with a
    warning rather than silently applied."""
    assert options("-p", "--ntsc_audio_rate")["analog_audio_freq"] == 44100
    assert "ignored for PAL" in capsys.readouterr().err


def test_ac3_is_ntsc_only(capsys):
    """The AC3 carrier replaces the right analogue channel, which only exists
    in that position on NTSC discs."""
    assert extra("--AC3")["AC3"] is True

    with pytest.raises(SystemExit) as exit_info:
        options("-p", "--AC3")

    assert exit_info.value.code == 1
    assert "only supported for NTSC" in capsys.readouterr().out


def test_disabling_analogue_audio_is_left_to_the_decoder():
    """--daa is not part of the option mapping: main() passes 0 as the rate
    instead, so the resolved rate here is unaffected by it."""
    assert parse("--daa").daa is True
    assert options("--daa")["analog_audio_freq"] == 44100


# --- threading ----------------------------------------------------------


def test_an_explicit_thread_count_is_used_as_given():
    assert extra("-t", "4")["threads"] == 4


def test_the_default_thread_count_is_chosen_from_the_machine():
    """Auto leaves two cores for the OS and the main loop and caps at ten;
    the exact number depends on the machine, the bounds do not."""
    assert 1 <= extra()["threads"] <= 10


def test_speculation_and_demod_only_threading_are_off_by_default():
    assert extra()["exact_speculation"] is False
    assert extra()["process_demod"] is True

    assert extra("--exact-speculation")["exact_speculation"] is True
    assert extra("--demod-threads-only")["process_demod"] is False


# --- de-emphasis --------------------------------------------------------


@pytest.mark.parametrize("system_flag, strength", [([], 0.96), (["-p"], 1.0)])
def test_the_default_deemphasis_strength_is_per_system(system_flag, strength):
    """NTSC discs are decoded slightly under full de-emphasis; PAL at full.
    Leaving the flag off also arms the auto-calibration servo."""
    options_out = extra(*system_flag)

    assert options_out["deemp_str"] == strength
    assert options_out["auto_deemp"] is True


def test_an_explicit_deemphasis_strength_disarms_the_servo():
    """Asking for a value means the user has chosen one; the auto servo must
    not then move it underneath them."""
    result = extra("--deemp_strength", "0.8")

    assert result["deemp_str"] == 0.8
    assert result["auto_deemp"] is False


def test_the_deemphasis_time_constants_are_passed_as_a_pair():
    result = extra("--deemp_low", "1.3", "--deemp_high", "4.7")

    assert result["deemp_coeff"] == (1.3, 4.7)
    assert extra()["deemp_coeff"] == (0, 0)


# --- echo cancellation --------------------------------------------------


def test_automatic_echo_cancellation_is_a_flag():
    assert "rf_echo_cancel" not in extra()
    assert extra("--rf_echo_cancel")["rf_echo_cancel"] is True


def test_manual_echo_taps_are_parsed_as_delay_and_amplitude_pairs():
    assert extra("--rf_echo", "1.5:0.2,3.25:-0.1")["rf_echo_cancel"] == [
        (1.5, 0.2), (3.25, -0.1)
    ]


def test_manual_echo_taps_override_the_automatic_search():
    """Given both, the measured taps are what the user asked for."""
    result = extra("--rf_echo", "2:0.3", "--rf_echo_cancel")

    assert result["rf_echo_cancel"] == [(2.0, 0.3)]


def test_a_malformed_echo_tap_is_dropped_rather_than_crashing():
    """Entries without a colon are skipped, so a trailing comma is harmless."""
    assert extra("--rf_echo", "2:0.3,")["rf_echo_cancel"] == [(2.0, 0.3)]


# --- system-specific corrections ----------------------------------------


def test_the_v4300d_options_apply_to_pal_only():
    """They exist for one PAL player's 8.4672 MHz clock spur; on NTSC the
    flags parse but must not reach the decoder."""
    assert extra("-p", "--V4300D_coherent_subtract")["PAL_V4300D_CoherentSubtract"] is True
    assert "PAL_V4300D_CoherentSubtract" not in extra("--V4300D_coherent_subtract")


def test_the_notch_switch_is_an_alias_for_the_coherent_subtract():
    """--V4300D_notch_filter/-V predates the coherent subtract; it now maps
    to the same (better) filter so existing command lines keep working."""
    assert extra("-p", "-V")["PAL_V4300D_CoherentSubtract"] is True
    assert "PAL_V4300D_CoherentSubtract" not in extra("-V")


def test_the_spur_filter_no_longer_defers():
    """The no-video guard makes the filter safe from the first block, so
    nothing sets the old defer option (which forced serial demod), and the
    obsolete --V4300D_no_defer switch still parses."""
    assert "V4300_defer" not in extra("-p", "--V4300D_coherent_subtract")
    assert "V4300_defer" not in extra("-p", "--V4300D_coherent_subtract", "--V4300D_no_defer")


def test_the_colour_notch_filter_applies_to_ntsc_only():
    assert extra("-N")["NTSC_ColorNotchFilter"] is True
    assert "NTSC_ColorNotchFilter" not in extra("-p", "-N")


def test_lowband_selects_the_reduced_bandwidth_parameter_set():
    assert "lowband" not in extra()
    assert extra("--lowband")["lowband"] is True


# --- filter overrides ---------------------------------------------------


def test_no_filter_overrides_by_default():
    assert options()["decoder_params_override"] == {}


def test_the_band_pass_edges_are_converted_to_hertz():
    """The flags take MHz (or any suffixed frequency); DecoderParams is in Hz."""
    override = options("--video_bpf_low", "3.5", "--video_bpf_high", "13.2")[
        "decoder_params_override"
    ]

    assert override == {"video_bpf_low": 3.5e6, "video_bpf_high": 13.2e6}


def test_the_video_low_pass_override_is_converted_to_hertz():
    override = options("--video_lpf", "4200000Hz")["decoder_params_override"]

    assert override["video_lpf_freq"] == pytest.approx(4.2e6)


def test_the_low_pass_order_is_only_overridden_when_it_is_valid():
    """The sentinel is -1, and an order below 1 is not a filter."""
    assert "video_lpf_order" not in options("--video_lpf_order", "-1")[
        "decoder_params_override"
    ]
    assert options("--video_lpf_order", "5")["decoder_params_override"][
        "video_lpf_order"
    ] == 5


# --- pass-through options -----------------------------------------------


def test_the_mtf_controls_reach_the_decoder():
    result = extra("-m", "1.4", "--MTF_offset", "0.5")

    assert result["MTF_level"] == 1.4
    assert result["MTF_offset"] == 0.5


def test_the_diagnostic_outputs_are_off_by_default():
    result = extra()

    assert result["write_RF_TBC"] is False
    assert result["write_pre_efm"] is False
    assert result["tbc_efm"] is False
    assert result["use_profiler"] is False


def test_the_agc_is_on_unless_disabled():
    assert extra()["useAGC"] is True
    assert extra("--noAGC")["useAGC"] is False


def test_the_wow_correction_defaults_to_linear_interpolation():
    assert extra()["wow_interpolation_method"] == "linear"
    assert extra()["wow_level_adjust_smoothing"] == 0

    result = extra("--wow_interpolation_method", "cubic",
                   "--wow_level_adjust_smoothing", "3")
    assert result["wow_interpolation_method"] == "cubic"
    assert result["wow_level_adjust_smoothing"] == 3


def test_the_rf_tbc_pipe_is_not_wired_up_from_the_command_line():
    """pipe_RF_TBC is part of the decoder's option contract but ld-decode
    never opens a pipe for it; it is always None here."""
    assert extra("--RF_TBC")["pipe_RF_TBC"] is None
    assert extra("--RF_TBC")["write_RF_TBC"] is True


# --- ld-cut -------------------------------------------------------------

CUT_BASE = ["capture.ldf", "cut.lds"]


def cut_parse(*argv):
    return cut.build_parser().parse_args(CUT_BASE + list(argv))


def test_ld_cut_takes_a_source_and_a_destination():
    args = cut_parse()

    assert (args.infile, args.outfile) == ("capture.ldf", "cut.lds")
    assert (args.start, args.length, args.seek, args.end) == (0, -1, -1, -1)


def test_ld_cut_ranges_are_parsed():
    args = cut_parse("-s", "5", "-l", "200", "-S", "3", "-E", "400")

    assert (args.start, args.length, args.seek, args.end) == (5.0, 200, 3, 400)


def test_ld_cut_defaults_to_maximum_ldf_compression():
    assert cut_parse().ldfcomp == 11
    assert cut_parse("-C", "3").ldfcomp == 3


def test_ld_cut_takes_custom_ffmpeg_options():
    assert cut_parse().ffmpeg_options is None
    assert cut_parse("-F", "-f s16le").ffmpeg_options == "-f s16le"


@pytest.mark.parametrize("name, expected", [
    ("cut.lds", ("cut.lds", True, False)),
    ("cut.ldf", ("cut.ldf", False, True)),
    ("cut.r16", ("cut.r16", False, False)),
    ("cut", ("cut", False, False)),
])
def test_the_ld_cut_writer_is_chosen_by_suffix(name, expected):
    assert cut.resolve_output(name) == expected


def test_ld_cut_writes_raw_samples_to_stdout():
    """"-" becomes /dev/stdout, whose suffix matches neither packer, so a
    piped cut is raw 16-bit samples rather than .lds."""
    assert cut.resolve_output("-") == ("/dev/stdout", False, False)


def test_the_ld_cut_suffix_match_is_case_sensitive():
    """Pinned rather than endorsed: an upper-case .LDS is written raw."""
    assert cut.resolve_output("cut.LDS") == ("cut.LDS", False, False)
