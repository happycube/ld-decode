"""Unit tests for lddecode.lds packing, the .lds 10-bit <-> 16-bit format.

The reference values here come from the C++ ld-lds-converter that this module
replaces, so these tests are what pins the format down.  Packing is an integer
and byte-level problem, so every comparison is exact.

The writer and the command-line front end live in
tests/functional/test_lds_cli.py: they need real files and a subprocess.
"""

import ctypes
import io

import numpy as np
import pytest

from lddecode import lds
from lds_vectors import packed_bytes, sample_array

pytestmark = [pytest.mark.unit, pytest.mark.format]


# The RIFF header the C++ tool emitted for --riff, verbatim.
CPP_RIFF_HEX = (
    "52494646FFFFFFFF57415645666D74201000000001000100409C0000885801000200"
    "10004C4953541A000000494E464F495346540E0000004C61766635382E32392E3130"
    "300064617461FFFFFFFF"
)


def cpp_unpack(data):
    """Literal transcription of the C++ DataConverter::unpackFile inner loop."""
    out = []
    for i in range(0, (len(data) // 5) * 5, 5):
        b0, b1, b2, b3, b4 = data[i : i + 5]
        words = (
            (b0 & 0xFF) * 4 + ((b1 & 0xC0) >> 6),
            (b1 & 0x3F) * 16 + ((b2 & 0xF0) >> 4),
            (b2 & 0x0F) * 64 + ((b3 & 0xFC) >> 2),
            (b3 & 0x03) * 256 + (b4 & 0xFF),
        )
        out.extend(ctypes.c_int16((w - 512) * 64).value for w in words)
    return out


def cpp_pack(samples):
    """Literal transcription of the C++ DataConverter::packFile inner loop."""
    out = bytearray()
    for i in range(0, (len(samples) // 4) * 4, 4):
        # int(x / 64) reproduces C++ integer division, which truncates
        # towards zero rather than flooring like a right shift would
        w = [int(int(s) / 64) + 512 for s in samples[i : i + 4]]
        out.append((w[0] & 0x03FC) >> 2)
        out.append(((w[0] & 0x0003) << 6) + ((w[1] & 0x03F0) >> 4))
        out.append(((w[1] & 0x000F) << 4) + ((w[2] & 0x03C0) >> 6))
        out.append(((w[2] & 0x003F) << 2) + ((w[3] & 0x0300) >> 8))
        out.append(w[3] & 0x00FF)
    return bytes(out)


@pytest.fixture(scope="module")
def random_packed():
    return packed_bytes()


@pytest.fixture(scope="module")
def random_samples():
    return sample_array()


def test_riff_header_matches_cpp():
    assert lds.RIFF_HEADER.hex().upper() == CPP_RIFF_HEX
    assert len(lds.RIFF_HEADER) == 78


def test_unpack_matches_cpp(random_packed):
    assert list(lds.unpack_samples(random_packed)) == cpp_unpack(random_packed)


def test_pack_matches_cpp_for_every_int16():
    """Exhaustive: every possible 16-bit input value must pack identically."""
    everything = np.arange(-32768, 32768, dtype=np.int16)
    assert lds.pack_samples(everything).tobytes() == cpp_pack(everything)


def test_pack_matches_cpp(random_samples):
    assert lds.pack_samples(random_samples).tobytes() == cpp_pack(random_samples)


def test_pack_truncates_towards_zero():
    """A plain >>6 would floor; the C++ tool truncated, so -1 maps to 512."""
    packed = lds.pack_samples(np.array([-1, -1, -1, -1], dtype=np.int16))
    assert list(lds.unpack_samples(packed.tobytes())) == [0, 0, 0, 0]


def test_unpack_then_pack_is_lossless(random_packed):
    """Unpacking is fully reversible - no 10-bit information is lost."""
    samples = lds.unpack_samples(random_packed)
    assert lds.pack_samples(samples).tobytes() == random_packed


def test_pack_then_unpack_is_stable(random_samples):
    """Packing quantises to 10 bits, but only once."""
    once = lds.pack_samples(random_samples).tobytes()
    twice = lds.pack_samples(lds.unpack_samples(once)).tobytes()
    assert once == twice


def test_unpack_sample_scaling():
    """Sample 0 is the bottom of the range, 512 is zero, 1023 the top."""
    # tenbit values 0, 512, 1023, 1023 packed by hand
    packed = lds.pack_samples(np.array([-32768, 0, 32767, 32767], dtype=np.int16))
    assert list(lds.unpack_samples(packed.tobytes())) == [-32768, 0, 32704, 32704]


def test_partial_groups_are_ignored(random_packed):
    full = lds.unpack_samples(random_packed)
    for extra in (1, 2, 3, 4):
        assert len(lds.unpack_samples(random_packed + b"\x5a" * extra)) == len(full)

    # Fewer than 4 samples cannot form a packed group
    for count in (1, 2, 3):
        assert lds.pack_samples(np.zeros(count, dtype=np.int16)).size == 0

    # Nor can fewer than 5 bytes form an unpackable group
    for short in (b"", b"\x01", b"\x01\x02\x03\x04"):
        assert lds.unpack_samples(short).size == 0


def test_stream_round_trip_across_chunk_boundaries(random_packed, monkeypatch):
    """A small CHUNK_SIZE forces the leftover-carrying path to be exercised."""
    # 7 is coprime with both 5 and 8, so nearly every chunk splits a group
    monkeypatch.setattr(lds, "CHUNK_SIZE", 7)

    unpacked = io.BytesIO()
    assert lds.unpack_stream(io.BytesIO(random_packed), unpacked) == 0

    repacked = io.BytesIO()
    unpacked.seek(0)
    assert lds.pack_stream(unpacked, repacked) == 0

    assert repacked.getvalue() == random_packed


def test_unpack_stream_reports_trailing_bytes(random_packed):
    out = io.BytesIO()
    discarded = lds.unpack_stream(io.BytesIO(random_packed + b"\x00\x01\x02"), out)
    assert discarded == 3


def test_riff_stream_prefixes_header(random_packed):
    plain = io.BytesIO()
    lds.unpack_stream(io.BytesIO(random_packed), plain)

    with_riff = io.BytesIO()
    lds.unpack_stream(io.BytesIO(random_packed), with_riff, riff=True)

    assert with_riff.getvalue() == lds.RIFF_HEADER + plain.getvalue()


def test_empty_input_produces_empty_output():
    out = io.BytesIO()
    assert lds.unpack_stream(io.BytesIO(b""), out) == 0
    assert out.getvalue() == b""


def test_agrees_with_decoder_hot_path(random_packed):
    """lddecode.utils has a separate jitted unpacker; it must agree with ours."""
    from lddecode.utils import load_packed_data_4_40

    readlen = (len(random_packed) // 5) * 4 - 8
    theirs = load_packed_data_4_40(io.BytesIO(random_packed), 0, readlen)
    mine = lds.unpack_samples(random_packed)[:readlen]

    assert np.array_equal(mine, theirs)
