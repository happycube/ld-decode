"""Unit tests for the ffmpeg command line ld-cut and --write-test-ldf encode with.

ffmpeg_pipe built its argv by splitting one string on single spaces, so a
quoted option value holding a space (ld-cut -F '-metadata title="A B"') was
cut in two, and two spaces in a row made an empty argument.  The options are
now split with shell quoting rules - without a shell.
"""

import pytest

from lddecode.fileio import ffmpeg_command

pytestmark = [pytest.mark.unit, pytest.mark.format]

BASE = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "quiet",
        "-f", "s16le", "-ar", "40k", "-ac", "1", "-i", "-"]


def test_no_options_encodes_with_the_base_command():
    assert ffmpeg_command("out.wav", None) == [*BASE, "out.wav"]
    assert ffmpeg_command("out.wav", "") == [*BASE, "out.wav"]


def test_options_are_split_into_separate_arguments():
    assert ffmpeg_command("out.ldf", "-acodec flac -f ogg") == [
        *BASE, "-acodec", "flac", "-f", "ogg", "out.ldf"]


def test_a_quoted_value_stays_one_argument_and_extra_spaces_add_none():
    assert ffmpeg_command("out.mkv", '-metadata  title="A B"') == [
        *BASE, "-metadata", "title=A B", "out.mkv"]


def test_the_output_name_is_never_split():
    assert ffmpeg_command("my capture; rm x.ldf", "-f ogg")[-1] == "my capture; rm x.ldf"
