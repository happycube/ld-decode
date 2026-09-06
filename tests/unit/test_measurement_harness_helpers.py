"""Unit tests for the pure helpers inside the two measurement harnesses.

``scripts/bench_decode_throughput.py`` and ``scripts/report_working_set.py``
produce the numbers the working-set plan's phases are compared against, so the
parts of them that can be wrong quietly -- the decoder command line, the parse
of the decoder's own rate line, the cache sizes that say how many decoders a
box holds, and the recorders that decide which arrays ``demodblock`` touched
and which transform plans it needs -- are covered here.

Hermetic: no decoder is run, no file is opened and no process is started.  The
footprint recorders are exercised against an injected stand-in for ``RFDecode``
that indexes a known set of filters, which is exactly the seam they were
written to have.
"""

import types

import numpy as np
import pytest

from bench_decode_throughput import (decoder_argv, parse_cache_sizes,
                                     parse_post_setup)
from report_working_set import (RecordingMapping, RecordingNamespace,
                                RecordingTransforms, per_block_reads,
                                per_block_transforms, plan_table_bytes,
                                real_precision)

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


# --- cache sizes (bench_decode_throughput) ------------------------------------

#: cpu0's cache indexes on the reference box, as sysfs spells them.
ZEN3_ENTRIES = [("1\n", "32K\n"), ("1\n", "32K\n"),
                ("2\n", "512K\n"), ("3\n", "32768K\n")]

#: cpu0 on a Raptor Lake part, where cpu0 is a P-core.
RAPTOR_P_CORE_ENTRIES = [("1\n", "48K\n"), ("1\n", "32K\n"),
                         ("2\n", "2048K\n"), ("3\n", "36864K\n")]


def test_cache_sizes_of_the_reference_box():
    assert parse_cache_sizes(ZEN3_ENTRIES) == {
        "l2_bytes_per_core": 512 * 1024,
        "l3_bytes": 32 * 1024 * 1024,
    }


def test_cache_sizes_of_a_hybrid_part_report_the_p_core_l2():
    assert parse_cache_sizes(RAPTOR_P_CORE_ENTRIES) == {
        "l2_bytes_per_core": 2 * 1024 * 1024,
        "l3_bytes": 36864 * 1024,
    }


def test_a_size_given_in_megabytes_is_understood():
    assert parse_cache_sizes([("2\n", "2M\n"), ("3\n", "36M\n")]) == {
        "l2_bytes_per_core": 2 * 1024 * 1024,
        "l3_bytes": 36 * 1024 * 1024,
    }


def test_a_level_that_sysfs_does_not_report_comes_back_as_none():
    assert parse_cache_sizes([("1\n", "32K\n")]) == {
        "l2_bytes_per_core": None, "l3_bytes": None,
    }
    assert parse_cache_sizes([]) == {"l2_bytes_per_core": None, "l3_bytes": None}


@pytest.mark.parametrize(
    "entries",
    [
        [("2\n", "\n")],                 # size file present but empty
        [("2\n", "unknown\n")],          # unparseable size
        [("\n", "512K\n")],              # level file present but empty
        [("2\n", "K\n")],                # suffix with no digits
    ],
)
def test_an_entry_that_does_not_parse_is_skipped_rather_than_raising(entries):
    assert parse_cache_sizes(entries)["l2_bytes_per_core"] is None


def test_the_first_reported_index_of_a_level_wins():
    # A hybrid part lists a second L2 for the E-cluster; cpu0's own comes first
    # and is the one a P-core worker actually has.
    entries = [("2\n", "2048K\n"), ("2\n", "4096K\n"), ("3\n", "36864K\n")]
    assert parse_cache_sizes(entries)["l2_bytes_per_core"] == 2048 * 1024


# --- transform plan tables (report_working_set) --------------------------------


@pytest.mark.parametrize(
    "length, dtype, kind, expected",
    [
        # 2 reals per sample for a complex plan, 3 for a real one; see the
        # measured fit in the script's module docstring.
        (32768, np.float64, "complex", 2 * 32768 * 8),
        (32768, np.complex128, "complex", 2 * 32768 * 8),
        (32768, np.float64, "real", 3 * 32768 * 8),
        (32768, np.float32, "real", 3 * 32768 * 4),
        (32768, np.complex64, "real", 3 * 32768 * 4),
        (16384, np.float64, "complex", 2 * 16384 * 8),
        (16384, np.float32, "real", 3 * 16384 * 4),
        (1024, np.complex128, "complex", 2 * 1024 * 8),
        (1024, np.float64, "real", 3 * 1024 * 8),
    ],
)
def test_plan_table_bytes_scales_with_length_and_precision(length, dtype, kind, expected):
    assert plan_table_bytes(length, dtype, kind) == expected


def test_the_four_plans_a_block_needs_at_32768_match_the_measured_total():
    # 1668 KiB was measured as an RSS delta in a fresh interpreter; the model
    # is expected to land within a page or two of it, not on it exactly.
    total = (plan_table_bytes(32768, np.float64, "real")
             + plan_table_bytes(32768, np.float64, "complex")
             + plan_table_bytes(32768, np.float32, "real"))
    assert abs(total / 1024.0 - 1668) < 8


@pytest.mark.parametrize("kind", ["c2c", "r2c", "", None])
def test_plan_table_bytes_refuses_a_kind_it_does_not_know(kind):
    with pytest.raises(ValueError, match="unknown transform kind"):
        plan_table_bytes(1024, np.float64, kind)


@pytest.mark.parametrize("length", [0, -32768])
def test_plan_table_bytes_refuses_a_non_positive_length(length):
    with pytest.raises(ValueError, match="must be positive"):
        plan_table_bytes(length, np.float64, "real")


@pytest.mark.parametrize(
    "dtype, expected",
    [
        (np.float32, np.float32), (np.complex64, np.float32),
        (np.float64, np.float64), (np.complex128, np.float64),
        (np.int16, np.float64),
    ],
)
def test_real_precision_splits_single_from_everything_else(dtype, expected):
    assert real_precision(dtype) == np.dtype(expected)


class TransformStub:
    """A stand-in whose ``demodblock`` issues a known set of transforms.

    Two calls share the real float64 plan and two share the real float32 one,
    which is the property the recorder has to get right: a plan is resident
    once however many calls read it.
    """

    def __init__(self, module, blocklen=256):
        self._module = module
        self.blocklen = blocklen
        self.freq_hz = 40e6
        self.SysParams = {"ire0": 8.1e6, "hz_ire": 1.7e4}
        self.blocks_seen = 0

    def pal_audio_carriers_present(self, _fft):
        return False

    def demodblock(self, data=None, mtf_level=0, cut=False, raw_mtf=False):
        assert data is not None and len(data) == self.blocklen
        self.blocks_seen += 1
        fft = self._module.npfft
        n = self.blocklen
        half = fft.rfft(data)                                  # real f64 @ n
        fft.irfft(half, n=n)                                   # real f64 @ n
        fft.ifft(np.zeros(n, dtype=np.complex128))             # complex f64 @ n
        narrow = fft.rfft(np.zeros(n, dtype=np.float32))       # real f32 @ n
        fft.irfft(narrow, n=n)                                 # real f32 @ n
        fft.ifft(np.zeros(64, dtype=np.complex128))            # complex f64 @ 64
        return {}


def _transform_module():
    import scipy.fft

    return types.SimpleNamespace(npfft=scipy.fft)


def test_per_block_transforms_charges_each_plan_once_however_many_calls_read_it():
    module = _transform_module()
    stub = TransformStub(module)
    rows = per_block_transforms(stub, module=module)
    by_plan = {(kind, length, precision): (nbytes, calls)
               for kind, length, precision, nbytes, calls in rows}
    assert by_plan == {
        ("real", 256, "float64"): (3 * 256 * 8, 2),
        ("complex", 256, "float64"): (2 * 256 * 8, 1),
        ("real", 256, "float32"): (3 * 256 * 4, 2),
        ("complex", 64, "float64"): (2 * 64 * 8, 1),
    }
    assert stub.blocks_seen == 1


def test_per_block_transforms_reports_largest_plan_first():
    module = _transform_module()
    rows = per_block_transforms(TransformStub(module), module=module)
    assert [row[3] for row in rows] == sorted((row[3] for row in rows), reverse=True)


def test_per_block_transforms_restores_the_module_it_instrumented():
    module = _transform_module()
    original = module.npfft
    stub = TransformStub(module)
    carrier_test = stub.pal_audio_carriers_present
    per_block_transforms(stub, module=module)
    assert module.npfft is original
    assert stub.pal_audio_carriers_present == carrier_test
    assert "pal_audio_carriers_present" not in vars(stub)


def test_the_recorder_restores_the_module_even_when_the_block_raises():
    module = _transform_module()
    original = module.npfft

    class Exploding(TransformStub):
        def demodblock(self, **kwargs):
            self._module.npfft.rfft(np.zeros(self.blocklen))
            raise RuntimeError("block failed")

    with pytest.raises(RuntimeError):
        per_block_transforms(Exploding(module), module=module)
    assert module.npfft is original


def test_the_recorder_passes_through_attributes_it_does_not_wrap():
    import scipy.fft

    recorder = RecordingTransforms(scipy.fft)
    assert recorder.next_fast_len(354689) == scipy.fft.next_fast_len(354689)
    assert recorder.plans == {}


def test_an_inverse_real_transform_without_n_is_charged_the_real_side_length():
    import scipy.fft

    recorder = RecordingTransforms(scipy.fft)
    recorder.irfft(np.zeros(129, dtype=np.complex128))
    assert list(recorder.plans) == [("real", 256, "float64")]


def test_a_batched_transform_is_charged_its_transform_axis():
    import scipy.fft

    recorder = RecordingTransforms(scipy.fft)
    recorder.irfft(np.zeros((4, 129), dtype=np.complex64), n=256, axis=1)
    assert list(recorder.plans) == [("real", 256, "float32")]
