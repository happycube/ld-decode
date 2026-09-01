"""Unit tests for the side-effect-free parts of lddecode.fileio.

Three things are hermetic in that module and are covered here:

``parse_frequency``
    A CLI string to a frequency in MHz.  Pure string and float arithmetic.

``make_loader``
    Filename to loader callable.  It is the project's worked example of a
    factory (see TESTING.md), and it does not touch the filesystem: it decides
    from the extension alone.  The tests below hand it names that do not exist
    to keep that honest -- if any of them ever started reading the file, these
    tests would fail rather than quietly become functional tests.

``unpack_data_4_40``
    The DdD 10-bit-in-5-bytes unpacker.  Byte layout, so asserted exactly
    against a group computed by hand.

The loader functions themselves take a file object and are covered in the
functional lane, where they read real captures.
"""

import numpy as np
import pytest

from lddecode.fileio import (
    LoadFFmpeg,
    LoadLDF,
    load_packed_data_3_32,
    load_packed_data_4_40,
    load_unpacked_data_float32,
    load_unpacked_data_s16,
    load_unpacked_data_u8,
    load_unpacked_data_u16,
    make_loader,
    parse_frequency,
    unpack_data_4_40,
)

pytestmark = [pytest.mark.unit, pytest.mark.format]

# A name with no file behind it.  Every make_loader assertion uses one of
# these, so a loader that started reading at construction time would fail here.
MISSING = "no-such-capture-anywhere"


# --- parse_frequency ------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected_mhz",
    [
        ("40", 40.0),  # bare numbers are MHz
        ("40mhz", 40.0),
        ("40000khz", 40.0),
        ("40000000hz", 40.0),
        ("0.04ghz", 40.0),
        ("28.636363", 28.636363),
        ("8", 8.0),
    ],
)
def test_parse_frequency_handles_si_suffixes(text, expected_mhz):
    # The result is always MHz whatever the suffix; this is what --inputfreq
    # feeds into the resampler, so a factor-of-1000 error would silently decode
    # at the wrong rate rather than fail.
    assert parse_frequency(text) == pytest.approx(expected_mhz, rel=1e-12)


@pytest.mark.parametrize("text", ["40MHz", "40MHZ", "40Mhz", "0.04GHz"])
def test_parse_frequency_is_case_insensitive(text):
    assert parse_frequency(text) == pytest.approx(40.0, rel=1e-12)


def test_parse_frequency_in_subcarrier_multiples():
    # NTSC fsc = 315/88 MHz.  cxadc captures are quoted in multiples of it, so
    # "4fsc" has to come out as the 4fsc sampling rate exactly.
    assert parse_frequency("1fsc") == pytest.approx(315.0 / 88.0, rel=1e-12)
    assert parse_frequency("4fsc") == pytest.approx(4 * 315.0 / 88.0, rel=1e-12)


def test_parse_frequency_in_pal_subcarrier_multiples():
    # PAL fsc = 283.75 * 15625 + 25 Hz = 4.43361875 MHz.  "fscpal" has to win
    # over the shorter "fsc" suffix, which it would not if the suffix table
    # were matched in a different order.
    assert parse_frequency("1fscpal") == pytest.approx(4.43361875, rel=1e-12)
    assert parse_frequency("4fscpal") == pytest.approx(4 * 4.43361875, rel=1e-12)


@pytest.mark.parametrize("text", ["", "mhz", "abc", "1.2.3", "40 mhz extra"])
def test_parse_frequency_rejects_malformed_input(text):
    # An unparseable rate must raise here, at argument-parsing time, rather
    # than produce a nonsense number that only shows up as a bad decode.
    with pytest.raises(ValueError):
        parse_frequency(text)


# --- make_loader dispatch -------------------------------------------------


@pytest.mark.parametrize(
    "extension, expected",
    [
        (".lds", load_packed_data_4_40),
        (".r30", load_packed_data_3_32),
        (".rf", load_unpacked_data_float32),
        (".s16", load_unpacked_data_s16),
        (".raw", load_unpacked_data_s16),
        (".r16", load_unpacked_data_u16),
        (".u16", load_unpacked_data_u16),
        (".r8", load_unpacked_data_u8),
        (".u8", load_unpacked_data_u8),
    ],
)
def test_raw_extensions_map_to_their_loader(extension, expected):
    # The sample format is carried entirely by the extension: .raw and .s16 are
    # the same signed 16-bit payload, .r16 and .u16 the same unsigned one.
    assert make_loader(MISSING + extension) is expected


@pytest.mark.parametrize("extension", [".ldf", ".flac", ".wav", ".vhs"])
def test_compressed_extensions_use_the_flac_reader(extension):
    pytest.importorskip("av", reason="PyAV is required for the .ldf reader")

    assert isinstance(make_loader(MISSING + extension), LoadLDF)


def test_oga_captures_use_the_flac_reader():
    pytest.importorskip("av", reason="PyAV is required for the .ldf reader")

    # Matched on the full "raw.oga" tail, not just the extension.
    assert isinstance(make_loader(MISSING + "raw.oga"), LoadLDF)


@pytest.mark.parametrize("extension", [".mkv", ".mov", ".unknown", ""])
def test_unrecognised_extensions_fall_back_to_ffmpeg(extension):
    # The fallback is what lets an arbitrary container be decoded without
    # ld-decode knowing about it, so it must stay a fallback and not an error.
    assert isinstance(make_loader(MISSING + extension), LoadFFmpeg)


@pytest.mark.parametrize(
    "extension, input_args",
    [
        (".s16", ["-f", "s16le"]),
        (".raw", ["-f", "s16le"]),
        (".r16", ["-f", "u16le"]),
        (".u16", ["-f", "u16le"]),
        (".tbc", ["-f", "u16le"]),
        (".rf", ["-f", "f32le"]),
        (".s8", ["-f", "s8"]),
        (".r8", ["-f", "u8"]),
        (".u8", ["-f", "u8"]),
        (".mkv", []),  # let ffmpeg work it out
    ],
)
def test_resampling_selects_the_right_raw_format(extension, input_args):
    # With --inputfreq everything goes through ffmpeg, which cannot guess the
    # layout of a headerless file, so the extension has to be translated into
    # an explicit -f argument.
    loader = make_loader(MISSING + extension, inputfreq=28.636363)

    assert isinstance(loader, LoadFFmpeg)
    assert loader.input_args == input_args


def test_resampling_adds_a_rate_conversion_filter():
    loader = make_loader(MISSING + ".s16", inputfreq=28.636363)

    # asetrate overrides whatever the container claims, then aresample brings
    # it to the 40 MHz the decoder works at.
    assert loader.output_args[0] == "-filter:a"
    assert "asetrate=28636363.0" in loader.output_args[1]
    assert "aresample=40000000.0" in loader.output_args[1]


def test_resampling_at_the_native_rate_adds_no_filter():
    loader = make_loader(MISSING + ".s16", inputfreq=40)

    # Already at 40 MHz: resampling would only cost time and accuracy.
    assert loader.output_args == []


@pytest.mark.parametrize("extension", [".lds", ".r30"])
def test_resampling_a_packed_format_is_rejected(extension):
    # ffmpeg has no way to express 10-bit packed samples, so this has to fail
    # loudly rather than read the bytes as something else.
    with pytest.raises(ValueError):
        make_loader(MISSING + extension, inputfreq=28.636363)


# --- unpack_data_4_40 -----------------------------------------------------


def pack_group(samples):
    """Pack four 10-bit samples into the five bytes the DdD writes."""
    a, b, c, d = samples
    return bytes(
        [
            a >> 2,
            ((a & 0x03) << 6) | (b >> 4),
            ((b & 0x0F) << 4) | (c >> 6),
            ((c & 0x3F) << 2) | (d >> 8),
            d & 0xFF,
        ]
    )


def pack(samples):
    """Pack a whole number of groups."""
    assert len(samples) % 4 == 0
    return b"".join(pack_group(samples[i : i + 4]) for i in range(0, len(samples), 4))


def unpack(samples, readlen, offset=0):
    """Unpack `samples` the way load_packed_data_4_40 calls the unpacker.

    unpack_data_4_40 writes readlen + 4 values through strided views over the
    packed bytes, so its caller always reads one slack group beyond what was
    asked for and passes a readlen four short of what the buffer holds.  The
    helper reproduces that convention so the tests below drive the function
    exactly as the loader does.
    """
    assert len(samples) >= readlen + offset + 4
    indata = np.frombuffer(pack(samples), dtype=np.uint8)
    return unpack_data_4_40(indata, len(samples) - 4, offset)[:readlen]


def as_ddd_int16(samples):
    """The DdD's signed 16-bit convention: (value - 512) << 6."""
    return ((np.array(samples, dtype=np.int32) - 512) * 64).astype(np.int16)


def test_packing_layout_of_a_hand_computed_group():
    # 0x000, 0x3FF, 0x155, 0x2AA: all zeros, all ones, and the two alternating
    # bit patterns, so every bit position in the 5-byte group is exercised in
    # both states.  Worked through by hand from the layout in fileio.py:
    #   0x000 -> 00000000 00......
    #   0x3FF -> ......11 111111..
    #   0x155 -> ........ ....0101 010101..
    #   0x2AA -> ................. ......10 10101010
    assert pack_group([0x000, 0x3FF, 0x155, 0x2AA]) == bytes(
        [0x00, 0x3F, 0xF5, 0x56, 0xAA]
    )


def test_unpack_of_a_hand_computed_group():
    samples = [0x000, 0x3FF, 0x155, 0x2AA]

    unpacked = unpack(samples + [512] * 4, 4)

    # Byte-level format, so exact equality -- there is nothing here to
    # approximate and a single wrong shift would corrupt every sample.
    assert np.array_equal(unpacked, as_ddd_int16(samples))
    assert unpacked.dtype == np.int16


def test_unpack_covers_the_full_ten_bit_range():
    samples = [0, 1, 511, 512, 513, 1022, 1023, 512]

    unpacked = unpack(samples + [512] * 4, 8)

    # 0 maps to the most negative code and 1023 to the most positive; 512 is
    # the DdD's zero.  This is where an int16 overflow would show up.
    assert np.array_equal(unpacked, as_ddd_int16(samples))
    assert unpacked[0] == -32768
    assert unpacked[6] == 32704
    assert unpacked[3] == 0


@pytest.mark.parametrize("offset", [0, 1, 2, 3])
def test_unpack_offset_selects_within_the_group(offset):
    samples = [100, 200, 300, 400, 500, 600, 700, 800]

    unpacked = unpack(samples + [512] * 4, 4, offset)

    # A read that does not start on a group boundary unpacks the whole group
    # and then drops the samples before the one asked for.  Without this the
    # first read of an unaligned seek would be up to three samples early.
    assert np.array_equal(unpacked, as_ddd_int16(samples[offset : offset + 4]))


@pytest.mark.parametrize("readlen", [1, 2, 5, 8])
def test_unpack_returns_exactly_the_requested_length(readlen):
    samples = list(range(0, 1024, 64))

    assert len(unpack(samples, readlen)) == readlen


def test_unpack_round_trips_a_seeded_block(seeded_rng):
    samples = seeded_rng.integers(0, 1024, 400).tolist()

    unpacked = unpack(samples, len(samples) - 4)

    # Bulk cover for the ordinary case: the hand-computed group above pins the
    # layout, this pins that it holds for every bit pattern in a seeded block.
    assert np.array_equal(unpacked, as_ddd_int16(samples[:-4]))
