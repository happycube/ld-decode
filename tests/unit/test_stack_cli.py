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

import types

import pytest

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
    kept = _parse("capture.rf", "out", "--keep-audio-crosstalk",
                  "--keep-crystal-lines", "--keep-chroma-leak")
    assert kept.keep_audio_crosstalk
    assert kept.keep_crystal_lines
    assert kept.keep_chroma_leak


def test_rf_out_defaults_to_off():
    """--rf-out names the file the decoder's RF is written to."""
    assert _parse("capture.rf", "out").rf_out is None
    assert _parse("capture.rf", "out", "--rf-out", "rf.s16").rf_out == "rf.s16"


def _args(**kwargs):
    """The arguments build_stacked_source reads."""
    base = dict(inputfreq=None, stack_weight="adaptive", keep_audio_crosstalk=False,
                keep_crystal_lines=False, keep_chroma_leak=False, rf_out=None)
    base.update(kwargs)
    return types.SimpleNamespace(**base)


def test_a_compressed_capture_is_refused_by_the_read_time_path():
    """A packed or compressed capture cannot be read at arbitrary positions.

    The check is on the name alone, so no file is opened here.
    """
    with pytest.raises(ValueError, match="fixed-width"):
        build_stacked_source(["capture.ldf"], _args(), "NTSC")
