from types import SimpleNamespace

import numpy as np

from lddecode.core import RFDecode
from lddecode.start_finder import (
    FrameObservation,
    StartFinder,
    StartResult,
    VbiRunDetector,
    file_frame_from_readloc,
    main,
)


def observation(address, file_frame=0, readloc=0, disk_type="CAV"):
    return FrameObservation(file_frame, readloc, address, disk_type)


def test_file_frame_conversion_matches_start_seek_units():
    bytes_per_field = 674029
    readloc = (bytes_per_field * 2 * 1234) + bytes_per_field
    assert file_frame_from_readloc(readloc, bytes_per_field) == 1234


def test_sync_only_demodulation_matches_the_normal_sync_path():
    rf = RFDecode(system="NTSC", blocklen=32768)
    raw = np.random.default_rng(0).integers(
        -32768, 32767, size=rf.blocklen, dtype=np.int16
    )

    full = rf.demodblock(data=raw, cut=True)["video"]["demod_05"]
    sync = rf.demodblock_sync(data=raw, cut=True)

    np.testing.assert_array_equal(sync, full)


def test_vbi_run_requires_contiguous_addresses_of_one_disk_type():
    detector = VbiRunDetector(required_frames=5)
    assert detector.observe(observation(100)) is None
    assert detector.observe(observation(101)) is None
    assert detector.observe(observation(103)) is None
    assert detector.observe(observation(104)) is None
    assert detector.observe(observation(105)) is None
    assert detector.observe(observation(106)) is None
    result = detector.observe(observation(107))
    assert result.address == 103

    detector.reset()
    for address in (200, 201, 202, 203):
        assert detector.observe(observation(address, disk_type="CLV")) is None
    assert detector.observe(observation(204, disk_type="CAV")) is None


def test_vbi_run_rejects_paused_reverse_and_fast_forward_addresses():
    detector = VbiRunDetector(required_frames=3)
    assert detector.observe(observation(10)) is None
    assert detector.observe(observation(10)) is None
    assert detector.observe(observation(11)) is None
    assert detector.observe(observation(9)) is None
    assert detector.observe(observation(10)) is None
    assert detector.observe(observation(20)) is None
    assert detector.observe(observation(21)) is None
    assert detector.observe(observation(22)).address == 20


def test_default_vbi_run_requires_a_sustained_second_of_addresses():
    detector = VbiRunDetector()
    for address in range(29):
        assert detector.observe(observation(address)) is None
    assert detector.observe(observation(29)).address == 0


class FakeField:
    def __init__(
        self,
        readloc,
        is_first_field,
        address=None,
        disk_type="CAV",
        valid=True,
        field_phase_id=None,
    ):
        self.readloc = readloc
        self.isFirstField = is_first_field
        self.address = address
        self.disk_type = disk_type
        self.valid = valid
        self.fieldPhaseID = field_phase_id


class FakeDecoder:
    def __init__(self, events, bytes_per_field=100):
        self.events = list(events)
        self.bytes_per_field = bytes_per_field
        self.isCLV = False
        self.closed = False
        self.rf = SimpleNamespace(SysParams={"fieldPhases": 4})

    def decodefield(self, _position, _mtf, _previous):
        event = self.events.pop(0)
        if isinstance(event, BaseException):
            raise event
        if event is None:
            return None, None
        return event, self.bytes_per_field

    def decodeFrameNumber(self, _first, second):
        self.isCLV = second.disk_type == "CLV"
        return second.address

    def close(self):
        self.closed = True


class SyncProbeFakeDecoder(FakeDecoder):
    def __init__(self, events, sync_results, bytes_per_field=100):
        super().__init__(events, bytes_per_field)
        self.sync_results = iter(sync_results)
        self.sync_positions = []

    def has_sync(self, position):
        self.sync_positions.append(position)
        return next(self.sync_results)


def five_frames(start_file_frame=7, sample_base=0, disk_type="CAV"):
    fields = []
    for index in range(5):
        readloc = sample_base + ((start_file_frame + index) * 200)
        fields.append(FakeField(readloc, True, disk_type=disk_type))
        fields.append(FakeField(readloc + 100, False, 100 + index, disk_type))
    return fields


def test_start_finder_returns_first_cav_frame_of_vbi_run():
    decoder = FakeDecoder(five_frames())
    result = StartFinder(
        lambda: decoder, sample_rate=100, required_frames=5, pre_roll_search_seconds=0
    ).search()
    assert result.confidence == "vbi"
    assert result.file_frame == 7
    assert result.readloc == 1400
    assert result.disk_type == "CAV"
    assert result.addresses == (100, 101, 102, 103, 104)
    assert decoder.closed


def test_start_finder_recreates_decoder_after_decode_failure():
    first = FakeDecoder([RuntimeError("bad RF")])
    second = FakeDecoder(five_frames(start_file_frame=9))
    decoders = iter([first, second])
    result = StartFinder(
        lambda: next(decoders), sample_rate=100, required_frames=5, pre_roll_search_seconds=0
    ).search()
    assert result.confidence == "vbi"
    assert result.file_frame == 9
    assert first.closed
    assert second.closed


def test_start_finder_skips_sync_free_preamble_without_full_field_decode():
    decoder = SyncProbeFakeDecoder(five_frames(), [False, True])
    result = StartFinder(
        lambda: decoder, sample_rate=100, required_frames=5, pre_roll_search_seconds=0
    ).search()

    assert result.confidence == "vbi"
    assert decoder.sync_positions == [0, 100]
    assert decoder.closed


def test_start_finder_returns_guarded_fallback_for_stable_video_without_vbi():
    fields = [
        FakeField(index * 100, index % 2 == 0, None)
        for index in range(11)
    ]
    decoder = FakeDecoder(fields, bytes_per_field=100)
    result = StartFinder(
        lambda: decoder, sample_rate=100, fallback_seconds=10
    ).search()
    assert result.confidence == "fallback"
    assert result.file_frame == 0
    assert result.readloc == 0


def test_start_finder_returns_first_clv_frame_of_the_stable_run():
    decoder = FakeDecoder(five_frames(start_file_frame=30, disk_type="CLV"))
    result = StartFinder(
        lambda: decoder, sample_rate=100, required_frames=5, pre_roll_search_seconds=0
    ).search()
    assert result.confidence == "vbi"
    assert result.disk_type == "CLV"
    assert result.file_frame == 30
    assert result.readloc == 6000


def test_start_finder_keeps_clean_pre_roll_after_last_phase_break():
    forward = FakeDecoder(five_frames(start_file_frame=20))
    replay = FakeDecoder(
        [
            FakeField(3500, True, field_phase_id=1),
            FakeField(3600, False, field_phase_id=2),
            # The player re-locks at a new first field.  Keep this field and
            # the following clean pre-roll rather than returning the later
            # VBI-confirmed programme frame at sample 4000.
            FakeField(3700, True, field_phase_id=1),
            FakeField(3800, False, field_phase_id=2),
            FakeField(3900, True, field_phase_id=3),
            FakeField(4000, False, field_phase_id=4),
        ]
    )
    decoders = iter([forward, replay])

    result = StartFinder(
        lambda: next(decoders),
        sample_rate=100,
        required_frames=5,
        pre_roll_search_seconds=5,
    ).search()

    assert result.confidence == "vbi"
    assert result.file_frame == 18
    assert result.readloc == 3700
    assert forward.closed
    assert replay.closed


def test_main_writes_only_confirmed_start_argument_to_stdout(monkeypatch, capsys):
    result = StartResult(42, 8400, "vbi", "CAV", (1, 2, 3, 4, 5), 3.0)
    monkeypatch.setattr("lddecode.start_finder.find_start", lambda *_args, **_kwargs: result)
    assert main(["capture.ldf"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "--start 42\n"
    assert "found CAV run" in captured.err


def test_main_keeps_guarded_fallback_off_stdout(monkeypatch, capsys):
    result = StartResult(42, 8400, "fallback", None, tuple(), 10.0)
    monkeypatch.setattr("lddecode.start_finder.find_start", lambda *_args, **_kwargs: result)
    assert main(["capture.ldf"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--start 42" in captured.err


def test_main_returns_one_without_a_candidate(monkeypatch, capsys):
    monkeypatch.setattr("lddecode.start_finder.find_start", lambda *_args, **_kwargs: None)
    assert main(["capture.ldf"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no qualifying programme start" in captured.err
