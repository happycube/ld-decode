"""Unit tests for the stacking command line.

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

The read-time TBC path adds a second way of naming the captures and the
output: -i (repeatable, to stack several captures of the same disc) and -o.
The positional form (infile outfile) stays the reference's, so the two forms
are exclusive.  These tests exercise the parser and the resolution of the
two forms; nothing here touches a file or starts a decode.

All signals are synthetic.
"""

import logging
import types

import numpy as np
import pytest

from lddecode import main
from lddecode.main import build_parser, build_stacked_source, resolve_io

pytestmark = [pytest.mark.unit, pytest.mark.decode]


def _parse(*argv):
    return build_parser().parse_args(list(argv))


def test_positional_form_gives_one_input_and_the_output():
    """The reference's positional form still names one capture and the output."""
    args = _parse("capture.rf", "out")
    inputs, outname = resolve_io(args)
    assert inputs == ["capture.rf"]
    assert outname == "out"


def test_repeated_input_flag_stacks_captures():
    """-i may be repeated; the captures are stacked, the first is the primary."""
    args = _parse("-i", "a.rf", "-i", "b.rf", "-i", "c.rf", "-o", "out")
    inputs, outname = resolve_io(args)
    assert inputs == ["a.rf", "b.rf", "c.rf"]
    assert outname == "out"


def test_mixing_the_positional_and_flag_forms_is_refused():
    """infile and -i name the captures in two different ways: pick one."""
    args = _parse("capture.rf", "out", "-i", "other.rf")
    with pytest.raises(ValueError, match="not both"):
        resolve_io(args)


def test_input_flag_without_an_output_is_refused():
    """-i needs -o: the output base name has to come from somewhere."""
    args = _parse("-i", "capture.rf")
    with pytest.raises(ValueError, match="-o"):
        resolve_io(args)


def test_output_flag_without_an_input_is_refused():
    """-o on its own names no capture."""
    args = _parse("-o", "out")
    with pytest.raises(ValueError, match="-o needs -i"):
        resolve_io(args)


def test_missing_output_name_is_refused():
    """A capture with no output base name has nowhere to write."""
    args = _parse("capture.rf")
    with pytest.raises(ValueError, match="no output file name"):
        resolve_io(args)


def test_stdin_still_decodes_the_reference_way():
    """The reference's stdin input is untouched by the stacking options."""
    inputs, outname = resolve_io(_parse("-", "out"))
    assert inputs == ["-"]


def test_stdin_is_refused_by_the_read_time_path():
    """The read-time TBC reads its input at random positions, which stdin
    cannot do."""
    with pytest.raises(ValueError, match="stdin"):
        build_stacked_source(["-"], _args(), "NTSC")


def test_time_base_mode_defaults_to_resample():
    """The reference's way is the default whatever the input; the read-time
    TBC is only what was asked for."""
    assert _parse("capture.rf", "out").tbc_mode == "resample"
    assert _parse("-i", "a.rf", "-i", "b.rf", "-o", "out").tbc_mode == "resample"
    assert _parse("capture.rf", "out", "--tbc-mode", "read").tbc_mode == "read"
    assert _parse("capture.rf", "out", "--tbc-mode", "resample").tbc_mode == "resample"


def test_stack_weight_defaults_to_adaptive():
    """A stack weighs its inputs per sample unless asked otherwise."""
    assert _parse("capture.rf", "out").stack_weight == "adaptive"
    assert _parse("capture.rf", "out", "--stack-weight", "fixed").stack_weight == "fixed"


def test_the_corrections_run_unless_switched_off():
    """The corrections run by default; each --no_ flag switches one off,
    as rev 8's --no_mtf_servo and --no_auto_chroma do."""
    args = _parse("capture.rf", "out")
    assert not args.no_audio_carrier_cancel
    assert not args.no_crystal_lines
    assert not args.no_chroma_leak
    off = _parse(
        "capture.rf",
        "out",
        "--no_audio_carrier_cancel",
        "--no_crystal_lines",
        "--no_chroma_leak",
    )
    assert off.no_audio_carrier_cancel
    assert off.no_crystal_lines
    assert off.no_chroma_leak


def test_the_stacking_options_take_underscores_and_dashes_alike():
    """The options are spelt with underscores, as rev 8's are; the spelling
    with dashes is accepted as well."""
    for spelling in (
        ("--tbc_mode", "read", "--stack_weight", "fixed", "--rf_out", "a.s16",
         "--device_precision", "double", "--no_crystal_lines", "--no_chroma_leak",
         "--no_audio_carrier_cancel"),
        ("--tbc-mode", "read", "--stack-weight", "fixed", "--rf-out", "a.s16",
         "--device-precision", "double", "--no-crystal-lines", "--no-chroma-leak",
         "--no-audio-carrier-cancel"),
    ):
        args = _parse("capture.rf", "out", *spelling)
        assert (args.tbc_mode, args.stack_weight, args.rf_out, args.device_precision) == (
            "read", "fixed", "a.s16", "double")
        assert args.no_crystal_lines and args.no_chroma_leak and args.no_audio_carrier_cancel


def test_the_v4300d_options_are_left_out_of_the_help():
    """The clock lines take the LD-V4300D's clock out by default with the
    read-time TBC: its own options no longer show in the help."""
    text = build_parser().format_help()
    assert "--V4300D" not in text and "-V," not in text
    # The clock lines' own help says where the V4300D's clock went.
    assert "LD-V4300D" in text
    # One option for the audio crosstalk: rev 8's prototype is out of it.
    assert "--audio_carrier_cancel " not in text and "--audio_carrier_cancel\n" not in text
    assert "--no_audio_carrier_cancel" in text


def test_a_v4300d_option_with_the_read_time_tbc_warns(monkeypatch, capsys):
    """With --tbc_mode read, --V4300D_coherent_subtract is left to the clock
    lines, and the command line says so."""
    _run_main(
        monkeypatch,
        ["-i", "capture.s16", "-o", "out", "--tbc_mode", "read", "-p",
         "--V4300D_coherent_subtract"],
        40e6,
    )
    assert "clock lines" in capsys.readouterr().err


def test_rf_out_defaults_to_off():
    """--rf-out names the file the decoder's RF is written to."""
    assert _parse("capture.rf", "out").rf_out is None
    assert _parse("capture.rf", "out", "--rf-out", "rf.s16").rf_out == "rf.s16"


def _args(**kwargs):
    """The arguments build_stacked_source reads."""
    base = dict(
        inputfreq=None,
        stack_weight="adaptive",
        no_audio_carrier_cancel=False,
        no_crystal_lines=False,
        no_chroma_leak=False,
        rf_out=None,
        device="cpu",
        device_precision="single",
    )
    base.update(kwargs)
    return types.SimpleNamespace(**base)


def test_a_compressed_capture_is_refused_by_the_read_time_path():
    """A packed or compressed capture cannot be read at arbitrary positions.

    The check is on the name alone, so no file is opened here.
    """
    with pytest.raises(ValueError, match="fixed-width"):
        build_stacked_source(["capture.ldf"], _args(), "NTSC")


# --- the rate the decoder is told about --------------------------------


class _FakeDecoder:
    """The decoder, stubbed: it records how it was built and does nothing."""

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.fdoffset = 0
        self.fields_written = 0
        self.leadOut = False
        self.output_cvbs = True

    def roughseek(self, *args, **kwargs):
        pass

    def readfield(self):
        return None

    def close(self):
        pass


class _FakeSource:
    """The virtual stream, stubbed: it reads as silence."""

    def read(self, sample, readlen):
        return np.zeros(readlen, dtype=np.int16)


def _run_main(monkeypatch, argv, rate_hz):
    """Run main() with the decoder, the loader and the source stubbed out."""
    built = []

    class _Decoder(_FakeDecoder):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            built.append(kwargs)

    monkeypatch.setattr(main, "LDdecode", _Decoder)
    monkeypatch.setattr(main, "init_logging", lambda name: logging.getLogger("lddecode-test"))
    monkeypatch.setattr(main, "make_loader", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        main, "build_stacked_source", lambda *args, **kwargs: (_FakeSource(), rate_hz)
    )
    main.main(argv)
    return built[0]


def test_the_decoder_demodulates_the_virtual_stream_at_its_own_rate(monkeypatch):
    """The read-time TBC path serves the virtual stream at the captures' own
    rate, and the decoder is told that rate.

    The reference's loader resamples the RF to 40 MHz, so that is the rate
    the decoder expects there.  Told 40 MHz for a 75 MHz stream, it would
    look for the sync pulses of a 2542-sample line in a stream whose lines
    are 4767 samples long, and find none: the decode would produce nothing.
    """
    kwargs = _run_main(
        monkeypatch,
        ["-i", "capture.rf", "-o", "out", "-f", "75", "--tbc-mode", "read"],
        75e6,
    )

    assert kwargs["inputfreq"] == 75.0


def test_the_reference_path_demodulates_at_40_mhz(monkeypatch):
    """The reference's way resamples the RF to 40 MHz, and the decoder is
    told 40 MHz."""
    kwargs = _run_main(
        monkeypatch,
        ["capture.rf", "out", "-f", "75", "--tbc-mode", "resample"],
        75e6,
    )

    assert kwargs["inputfreq"] == 40


def test_a_stack_without_the_read_time_tbc_is_refused():
    """Several captures are only stacked when the read-time TBC is asked
    for: the mode never changes with the input."""
    with pytest.raises(SystemExit):
        main.main(["-i", "a.s16", "-i", "b.s16", "-o", "out"])


def test_the_default_decode_never_builds_the_stacked_source(monkeypatch):
    """--write-test-ldf copies the capture at the positions the decode read,
    which only the reference's path reads the capture at; that path is the
    default, and the stub source is never built."""
    built_source = []
    monkeypatch.setattr(main, "write_input_ldf_file", lambda *args, **kwargs: True)

    def no_stack(*args, **kwargs):
        built_source.append(True)
        raise AssertionError("the stacked source must not be built")

    monkeypatch.setattr(main, "LDdecode", _FakeDecoder)
    monkeypatch.setattr(main, "init_logging", lambda name: logging.getLogger("lddecode-test"))
    monkeypatch.setattr(main, "make_loader", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "build_stacked_source", no_stack)
    main.main(["capture.s16", "out", "--write-test-ldf", "bug.ldf"])
    assert not built_source


def test_write_test_ldf_with_an_explicit_read_is_refused(monkeypatch):
    """Asked for both, the copy would not be what the decoder read."""
    with pytest.raises(SystemExit):
        main.main(["capture.s16", "out", "--tbc-mode", "read", "--write-test-ldf", "bug.ldf"])


def test_the_stacked_loader_closes_the_source_and_the_captures():
    """The decoder closes its reader through _close: the read-ahead stops,
    the --rf-out file and the captures are closed."""
    source = types.SimpleNamespace(read=lambda sample, readlen: np.zeros(readlen), closed=[])
    source.close = lambda: source.closed.append("source")
    capture = types.SimpleNamespace(closed=False)
    capture.close = lambda: setattr(capture, "closed", True)

    loader = main.StackedLoader(source, [capture])
    assert loader(None, 5, 7).shape == (7,)
    loader._close()

    assert source.closed == ["source"]
    assert capture.closed


def test_a_capture_without_a_sidecar_is_taken_at_40_mhz(monkeypatch):
    """Without -f and without a sidecar the rate is the decoder's own
    default, as for any other decode."""
    from lddecode import fileio

    monkeypatch.setattr(fileio.os.path, "isfile", lambda path: False)
    assert fileio.capture_sample_rate("capture.s16") == 40.0e6
    assert fileio.capture_sample_rate("capture.s16", 28.636) == pytest.approx(28.636e6)


def test_the_device_defaults_to_the_cpu_and_the_gpu_to_single_precision():
    args = _parse("capture.rf", "out")
    assert (args.device, args.device_precision) == ("cpu", "single")


def test_the_domesday_duplicator_sidecar_gives_the_rate_in_hertz():
    """The Domesday Duplicator writes its keys quoted, the rate in hertz."""
    import io

    from lddecode.fileio import sidecar_sample_rate

    text = (
        '"schema_version": 1\n'
        '"capture":\n'
        '  "file": "copy_2_stack_small_1.ddd.s16"\n'
        '  "sample_rate_hz": 75000000\n'
        '  "duration_seconds": 10.206\n'
    )
    assert sidecar_sample_rate(io.StringIO(text)) == 75.0e6
    assert sidecar_sample_rate(io.StringIO("sample_rate_hz: 40000000  # DdD\n")) == 40.0e6
    assert sidecar_sample_rate(io.StringIO('"capture":\n  "file": "x"\n')) is None
