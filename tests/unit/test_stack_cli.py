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


def test_stdin_is_refused():
    """Read-time TBC reads its input at random positions, which stdin cannot do."""
    args = _parse("-", "out")
    with pytest.raises(ValueError, match="stdin"):
        resolve_io(args)


def test_time_base_mode_defaults_to_read():
    """The read-time TBC is the default; resample is the reference's way."""
    assert _parse("capture.rf", "out").tbc_mode is None
    assert _parse("capture.rf", "out", "--tbc-mode", "read").tbc_mode == "read"
    assert _parse("capture.rf", "out", "--tbc-mode", "resample").tbc_mode == "resample"


def test_stack_weight_defaults_to_adaptive():
    """A stack weighs its inputs per sample unless asked otherwise."""
    assert _parse("capture.rf", "out").stack_weight == "adaptive"
    assert _parse("capture.rf", "out", "--stack-weight", "fixed").stack_weight == "fixed"


def test_the_keep_flags_default_to_off():
    """The corrections run by default; each keep flag switches one off."""
    args = _parse("capture.rf", "out")
    assert not args.keep_audio_crosstalk
    assert not args.keep_crystal_lines
    assert not args.keep_chroma_leak
    kept = _parse(
        "capture.rf",
        "out",
        "--keep-audio-crosstalk",
        "--keep-crystal-lines",
        "--keep-chroma-leak",
    )
    assert kept.keep_audio_crosstalk
    assert kept.keep_crystal_lines
    assert kept.keep_chroma_leak


def test_rf_out_defaults_to_off():
    """--rf-out names the file the decoder's RF is written to."""
    assert _parse("capture.rf", "out").rf_out is None
    assert _parse("capture.rf", "out", "--rf-out", "rf.s16").rf_out == "rf.s16"


def _args(**kwargs):
    """The arguments build_stacked_source reads."""
    base = dict(
        inputfreq=None,
        stack_weight="adaptive",
        keep_audio_crosstalk=False,
        keep_crystal_lines=False,
        keep_chroma_leak=False,
        rf_out=None,
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

