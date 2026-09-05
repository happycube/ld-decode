"""Unit tests for the pure helpers inside the two measurement harnesses.

``scripts/bench_decode_throughput.py`` and ``scripts/report_working_set.py``
produce the numbers the working-set plan's phases are compared against, so the
parts of them that can be wrong quietly -- the decoder command line, the parse
of the decoder's own rate line, and the recorders that decide which arrays
``demodblock`` touched -- are covered here.

Hermetic: no decoder is run, no file is opened and no process is started.  The
footprint recorders are exercised against an injected stand-in for ``RFDecode``
that indexes a known set of filters, which is exactly the seam they were
written to have.
"""

import types

import numpy as np
import pytest

from bench_decode_throughput import decoder_argv, parse_post_setup
from report_working_set import RecordingMapping, RecordingNamespace, per_block_reads

pytestmark = [pytest.mark.unit, pytest.mark.parallel]


def test_decoder_argv_names_system_mode_and_span():
    argv = decoder_argv(
        "/usr/bin/python3", "/captures/disc.ldf", "/work/out",
        system="pal", mode="cvbs", threads=6, seek=5000, length=1000,
    )
    assert argv[:5] == ["/usr/bin/python3", "-m", "lddecode.main", "--pal", "--cvbs"]
    assert argv[5:11] == ["-t", "6", "-s", "5000", "-l", "1000"]
    assert argv[11:] == ["/captures/disc.ldf", "/work/out"]


def test_decoder_argv_selects_the_legacy_tbc_output():
    argv = decoder_argv(
        "python3", "disc.ldf", "out", system="ntsc", mode="tbc",
        threads=1, seek=0, length=30,
    )
    assert "--ntsc" in argv and "--tbc" in argv and "--cvbs" not in argv


@pytest.mark.parametrize(
    "system, mode",
    [("PAL", "cvbs"), ("secam", "cvbs"), ("pal", "TBC"), ("pal", "ld")],
)
def test_decoder_argv_rejects_a_system_or_mode_it_cannot_spell(system, mode):
    with pytest.raises(ValueError):
        decoder_argv("python3", "disc.ldf", "out", system=system, mode=mode,
                     threads=1, seek=0, length=1)


def test_post_setup_line_yields_frames_and_rate():
    log = (
        "Starting decode\n"
        "completed decode 1000 frames (4.723 FPS post-setup)\n"
        "Exiting\n"
    )
    assert parse_post_setup(log) == (1000, 4.723)


def test_a_decode_that_did_not_finish_reports_no_rate():
    assert parse_post_setup("Starting decode\nTraceback (most recent call last):\n") is None


def test_recording_mapping_counts_fetches_but_not_membership_tests():
    mapping = RecordingMapping({"RFVideo": np.zeros(4), "FcutPAL": np.zeros(4)})
    _ = mapping["RFVideo"]
    _ = mapping["RFVideo"]
    assert "FcutPAL" in mapping
    assert mapping.reads == {"RFVideo": 2}


def test_recording_namespace_records_only_array_attributes():
    sink = {}
    wrapped = types.SimpleNamespace(filt1=np.zeros(8), a1_freq=1.0e6)
    proxy = RecordingNamespace(wrapped, "left", sink)
    assert proxy.a1_freq == 1.0e6
    array = proxy.filt1
    assert array is wrapped.filt1
    assert list(sink) == ["audio.left.filt1"]
    assert sink["audio.left.filt1"][1] == 1


class StubDecoder:
    """The smallest object ``per_block_reads`` can measure.

    Indexes two filters (one of them twice) and one audio filter per block, so
    the recorded set and the byte total are known in advance.
    """

    def __init__(self):
        self.blocklen = 256
        self.freq_hz = 40e6
        self.SysParams = {"ire0": 8.1e6, "hz_ire": 1.7e4}
        self.Filters = {
            "RFVideo": np.zeros(64, dtype=np.complex128),   # 1024 bytes
            "MTF": np.zeros(32, dtype=np.float64),          # 256 bytes
            "NeverRead": np.zeros(4096, dtype=np.complex128),
        }
        self.audio = {"left": types.SimpleNamespace(filt1=np.zeros(16, dtype=np.float64))}
        self.blocks_seen = 0

    def pal_audio_carriers_present(self, _fft):
        return False

    def demodblock(self, data=None, mtf_level=0, cut=False, raw_mtf=False):
        assert data is not None and len(data) == self.blocklen
        self.blocks_seen += 1
        _ = self.Filters["RFVideo"] * 1
        _ = self.Filters["RFVideo"] * 2
        if mtf_level != 0:
            _ = self.Filters["MTF"] * mtf_level
        _ = self.audio["left"].filt1
        return {}


def test_per_block_reads_sees_only_the_arrays_the_block_indexed():
    stub = StubDecoder()
    rows = per_block_reads(stub)
    by_name = {name: (nbytes, reads) for name, nbytes, reads in rows}
    assert set(by_name) == {"RFVideo", "MTF", "audio.left.filt1"}
    assert by_name["RFVideo"] == (1024, 2)
    assert by_name["MTF"] == (256, 1)
    assert by_name["audio.left.filt1"] == (128, 1)
    assert sum(nbytes for nbytes, _ in by_name.values()) == 1408


def test_per_block_reads_restores_the_decoder_it_instrumented():
    stub = StubDecoder()
    filters, audio = stub.Filters, stub.audio["left"]
    carrier_test = stub.pal_audio_carriers_present
    per_block_reads(stub)
    assert stub.Filters is filters
    assert stub.audio["left"] is audio
    assert stub.pal_audio_carriers_present == carrier_test
    assert stub.blocks_seen == 1
