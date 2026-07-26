"""Raw input-format coverage: convert a CI test capture and read it back.

Converts a slice of testdata/ntsc/ve-snw-cut.ldf (the ld-decode-testdata-ci
NTSC reference - a DdD capture whose samples are exactly 10 bits << 6) into
each raw sample format make_loader() accepts, then checks the loaders return
exactly the samples that were written, both from sample 0 and from an offset
that is not aligned with the formats' packing groups.  This pins the
np.frombuffer loader paths (which broke on numpy >= 2.0 upstream, PR #1049)
and the 10-bit packing arithmetic of the DdD .lds and .r30 loaders (.r30's
loader had never worked at all: it computed its byte count with the
samples-per-byte ratio inverted and compared a word count against it, so
every read returned None).

The end-to-end test decodes the .s16, .lds and .r30 conversions with
ld-decode.  The capture is 10-bit clean, so all three files carry identical
sample values (up to a constant gain/offset for .r30, which stores raw
0..1023) and the decodes must be bit-identical: .tbc/.pcm/.efm for .lds vs
.s16, and .tbc/.pcm for .r30 (whose 1/64 amplitude changes the EFM slice
values but not the FM demod, which depends only on the signal's angle).
"""

import os
import pathlib
import subprocess
import sys

import numpy as np
import pytest

from lddecode.fileio import make_loader

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_LDF = REPO_ROOT / "testdata" / "ntsc" / "ve-snw-cut.ldf"

# 4 M samples at 40 MSPS = 0.1 s of RF (~6 NTSC fields): enough for
# ld-decode to lock and write several fields, small enough to stay quick.
# A multiple of both 3 (.r30 words) and 4 (.lds groups), so the packed
# conversions need no padding.
N_SAMPLES = 3_999_996

# An offset aligned with neither packing group (7 % 4 = 3, 7 % 3 = 1), and
# an odd read length, to exercise the partial-first-group paths.
UNALIGNED_START = 1_000_003
UNALIGNED_LEN = 65_537

pytestmark = pytest.mark.skipif(
    not SOURCE_LDF.exists(), reason="testdata submodule not checked out"
)


def pack_lds(u10):
    """Pack 10-bit samples into the DdD .lds layout (4 samples in 5 bytes),
    the exact inverse of fileio.unpack_data_4_40()."""
    u = u10.astype(np.uint16)
    assert len(u) % 4 == 0
    out = np.zeros(len(u) // 4 * 5, dtype=np.uint8)
    out[0::5] = u[0::4] >> 2
    out[1::5] = ((u[0::4] & 0x03) << 6) | (u[1::4] >> 4)
    out[2::5] = ((u[1::4] & 0x0F) << 4) | (u[2::4] >> 6)
    out[3::5] = ((u[2::4] & 0x3F) << 2) | (u[3::4] >> 8)
    out[4::5] = u[3::4] & 0xFF
    return out.tobytes()


def pack_r30(u10):
    """Pack 10-bit samples into .r30 (3 samples per little-endian 32-bit
    word, low bits first), the inverse of fileio.load_packed_data_3_32()."""
    u = u10.astype(np.uint32)
    assert len(u) % 3 == 0
    words = u[0::3] | (u[1::3] << 10) | (u[2::3] << 20)
    return words.astype("<u4").tobytes()


@pytest.fixture(scope="module")
def conversions(tmp_path_factory):
    """The source sample slice and its conversion into every raw format:
    {ext: (path, expected loader output)}."""
    td = tmp_path_factory.mktemp("input-formats")

    src = make_loader(str(SOURCE_LDF))(None, 0, N_SAMPLES)
    assert src is not None and len(src) == N_SAMPLES
    src = np.asarray(src, dtype=np.int16)

    # DdD capture: every sample is a 10-bit value << 6.  The packed
    # conversions (and the end-to-end bit-identity assertion) rely on it.
    assert np.all(src.astype(np.int32) % 64 == 0), "source is not 10-bit clean"
    u10 = ((src.astype(np.int32) >> 6) + 512).astype(np.uint16)
    assert u10.min() >= 0 and u10.max() <= 1023

    files = {}

    def add(ext, payload, expected):
        path = td / f"conv.{ext}"
        path.write_bytes(payload)
        files[ext] = (path, expected)

    add("s16", src.astype("<i2").tobytes(), src)
    # DdD-style unsigned 16-bit (offset binary)
    u16 = (src.astype(np.int32) + 32768).astype("<u2")
    add("u16", u16.tobytes(), u16)
    # cxadc-style unsigned 8-bit: the top 8 of the 10 bits
    u8 = (u10 >> 2).astype(np.uint8)
    add("u8", u8.tobytes(), u8)
    # float32; the loader returns the samples scaled back by 32768
    add("rf", (src.astype(np.float32) / 32768.0).astype("<f4").tobytes(),
        src.astype(np.float32))
    add("lds", pack_lds(u10), src)          # unpacker restores (u10-512)<<6
    add("r30", pack_r30(u10), u10.astype(np.int16))  # raw 10-bit values

    return files


@pytest.mark.parametrize("ext", ["s16", "u16", "u8", "rf", "lds", "r30"])
def test_loader_roundtrip(conversions, ext):
    path, expected = conversions[ext]
    loader = make_loader(str(path))

    with open(path, "rb") as f:
        full = loader(f, 0, N_SAMPLES)
    assert full is not None and len(full) == N_SAMPLES
    assert np.array_equal(np.asarray(full), expected), \
        f".{ext} full read differs from what was written"

    with open(path, "rb") as f:
        part = loader(f, UNALIGNED_START, UNALIGNED_LEN)
    assert part is not None and len(part) == UNALIGNED_LEN
    assert np.array_equal(
        np.asarray(part),
        expected[UNALIGNED_START: UNALIGNED_START + UNALIGNED_LEN],
    ), f".{ext} unaligned read differs from what was written"


def _run_ld_decode(rf_path, out_base):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "ld-decode"), str(rf_path), str(out_base)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"ld-decode failed on {rf_path}:\n{result.stderr}"


def test_decode_converted_formats_end_to_end(conversions, tmp_path):
    outputs = {}
    for ext in ("s16", "lds", "r30"):
        out_base = tmp_path / f"dec-{ext}"
        _run_ld_decode(conversions[ext][0], out_base)
        outputs[ext] = {
            k: (tmp_path / f"dec-{ext}.{k}").read_bytes()
            for k in ("tbc", "pcm", "efm")
        }
        assert len(outputs[ext]["tbc"]) > 0, f".{ext} decode wrote no video"

    # .lds carries the identical 16-bit samples: everything matches .s16.
    for k in ("tbc", "pcm", "efm"):
        assert outputs["lds"][k] == outputs["s16"][k], \
            f".lds decode .{k} differs from .s16 decode"

    # .r30 carries the same signal at 1/64 amplitude without the << 6: the
    # FM video and audio demods depend only on the signal's angle, so
    # .tbc/.pcm are still bit-identical (.efm slice values scale with the
    # input, so the EFM stream legitimately differs).
    for k in ("tbc", "pcm"):
        assert outputs["r30"][k] == outputs["s16"][k], \
            f".r30 decode .{k} differs from .s16 decode"
