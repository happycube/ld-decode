"""Writer and command-line tests for lddecode.lds.

Split out of the packing tests because these need real files on disk and a
subprocess: LdsWriter is exercised through the filesystem because buffering
across unaligned writes is exactly what a caller like ld-cut does to it, and
the CLI is exercised as a CLI because its argument handling and exit codes are
the contract under test.

The format itself is pinned in tests/unit/test_lds_packing.py.
"""

import subprocess
import sys

import numpy as np
import pytest

from lddecode import lds
from lds_vectors import packed_bytes, sample_array

pytestmark = [pytest.mark.functional, pytest.mark.format]


@pytest.fixture(scope="module")
def random_packed():
    return packed_bytes()


@pytest.fixture(scope="module")
def random_samples():
    return sample_array()


def test_writer_matches_pack(tmp_path, random_samples):
    out = tmp_path / "written.lds"
    writer = lds.LdsWriter(str(out))
    writer.write(random_samples)
    writer.close()

    assert out.read_bytes() == lds.pack_samples(random_samples).tobytes()


def test_writer_buffers_across_unaligned_writes(tmp_path, random_samples):
    """ld-cut writes in chunks; a chunk that is not a multiple of 4 samples
    must not lose or reorder anything."""
    out = tmp_path / "chunked.lds"
    with lds.LdsWriter(str(out)) as writer:
        pos = 0
        for size in (1, 2, 3, 5, 7, 11, 4, 13):
            writer.write(random_samples[pos : pos + size])
            pos += size
        writer.write(random_samples[pos:])

    assert out.read_bytes() == lds.pack_samples(random_samples).tobytes()


def test_writer_pads_trailing_partial_group(tmp_path):
    """A partial final group is padded, not dropped."""
    samples = np.array([1024, -2048, 4096], dtype=np.int16)
    out = tmp_path / "padded.lds"
    with lds.LdsWriter(str(out)) as writer:
        writer.write(samples)

    assert out.stat().st_size == 5
    recovered = lds.unpack_samples(out.read_bytes())
    assert list(recovered[:3]) == list(samples)
    assert recovered[3] == 0


def test_writer_accepts_empty_writes(tmp_path):
    out = tmp_path / "empty.lds"
    with lds.LdsWriter(str(out)) as writer:
        writer.write(np.empty(0, dtype=np.int16))

    assert out.read_bytes() == b""


def _run_cli(*cli_args, stdin=b""):
    return subprocess.run(
        [sys.executable, "-m", "lddecode.lds", *cli_args],
        input=stdin,
        capture_output=True,
    )


def test_cli_defaults_to_unpacking(random_packed):
    result = _run_cli(stdin=random_packed)
    assert result.returncode == 0
    assert result.stdout == lds.unpack_samples(random_packed).tobytes()


def test_cli_pack_via_stdio(random_samples):
    result = _run_cli("-p", stdin=random_samples.tobytes())
    assert result.returncode == 0
    assert result.stdout == lds.pack_samples(random_samples).tobytes()


def test_cli_round_trip_via_files(tmp_path, random_packed):
    src = tmp_path / "in.lds"
    src.write_bytes(random_packed)

    unpacked = tmp_path / "mid.s16"
    assert _run_cli("-u", "-i", str(src), "-o", str(unpacked)).returncode == 0

    out = tmp_path / "out.lds"
    assert _run_cli("-p", "-i", str(unpacked), "-o", str(out)).returncode == 0

    assert out.read_bytes() == random_packed


def test_cli_rejects_pack_and_unpack_together():
    result = _run_cli("-u", "-p")
    assert result.returncode == 1
    assert b"not both" in result.stderr


def test_cli_rejects_riff_without_unpack():
    result = _run_cli("-r", "-p")
    assert result.returncode == 1
    assert b"RIFF" in result.stderr


def test_cli_reports_missing_input_file(tmp_path):
    result = _run_cli("-i", str(tmp_path / "nope.lds"))
    assert result.returncode == 1
    assert b"Error" in result.stderr
