"""
test_rf_sync - unit tests for the RF line location

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2026 ld-decode contributors

Hermetic tests: every signal is synthesised in memory, every generator is
seeded, and the capture is reached through the injected `read_fn` seam (no
file, no network, no clock).
"""

import numpy as np
import pytest

from lddecode.rf_sync import (
    FieldRecord,
    SyncSystem,
    frame_code,
    locate,
    porch_window,
    system_for,
)

pytestmark = [pytest.mark.unit, pytest.mark.dsp]

#: The capture rate the synthetic captures are made at.  It is not the 75 MHz
#: the sample counts are given at, so the rescaling is exercised too.
FS = 40.0e6

#: The carrier frequency of one IRE, in Hz, of each standard.
HZ_IRE = {True: 1.7e6 / 140.0, False: 8000.0}

#: The CAV picture numbers and the CLV time codes the synthetic carries.
WORD_A = 0xF01234
WORD_B = 0xF05678
WORD_C = 0x80ABCD
WORD_D = 0x80ABCE
WORD_E = 0x80ABCF


# --------------------------------------------------------------------------
# The synthetic captures
# --------------------------------------------------------------------------


def _synth_capture(
    system: SyncSystem,
    fs: float = FS,
    n_frames: int = 3,
    words_per_frame=None,
    pre_lines: int = 8,
    code_ire: float = 80.0,
    pilot_ire: float = 0.0,
):
    """A synthetic RF capture of a LaserDisc-like signal.

    The signal is an FM carrier: its frequency sits at the blanking level,
    dips to the sync level during the sync tip, carries the colour burst (or,
    on PAL, the 3.75 MHz pilot on the sync tip) and the Philips code in the
    back porch, and is modulated by a synthetic picture elsewhere.

    The vertical interval is one equalizing pulse and one broad pulse; the
    equalizing pulse opens the interval a full line after the last hsync on
    one field and half a line after it on the other, which is how the tracker
    tells the two fields apart.

    Parameters
    ----------
    system : SyncSystem
        The standard to synthesise.
    fs : float
        The sample rate, in Hz.
    n_frames : int
        How many frames (two fields each) to synthesise.
    words_per_frame : list, optional
        Per frame, the list of ``(line index, word)`` pairs of the first
        field's VBI lines.
    pre_lines : int
        How many hsyncs to put before the first vertical interval (the tracker
        needs one hsync before it can see an interval).
    code_ire : float
        The depth of the Philips code, in IRE above the blanking level.
    pilot_ire : float
        The depth of the PAL pilot on the sync tip, in IRE.

    Returns
    -------
    tuple[numpy.ndarray, list]
        The RF samples (float64) and, per field, the dictionary of the
        Philips words the field carries.
    """
    hz_ire = HZ_IRE[system.ntsc]
    blank = system.blank_hz
    sync = system.sync_hz
    line_s = system.line_us * 1e-6
    tip_s = 4.5e-6
    # The colour burst sits in the back porch; PAL has none (its pilot is on
    # the sync tip instead).
    burst_us = (21.0e6 / system.fsc_hz * 1e-6, 28.0e6 / system.fsc_hz * 1e-6)
    burst_ire = 20.0
    # The Philips code starts after the back porch (the porch level is
    # measured there) and its first bit is 48 us long.
    code_start = 10.5e-6
    rng = np.random.default_rng(12345)

    segs = []  # (start, end, kind, payload)

    def add_line(t0, words=None):
        segs.append((t0, t0 + tip_s, "tip", t0))
        if system.ntsc:
            segs.append((t0 + tip_s, t0 + burst_us[0], "blank", None))
            segs.append((t0 + burst_us[0], t0 + burst_us[1], "burst", t0 + burst_us[0]))
            segs.append((t0 + burst_us[1], t0 + code_start, "blank", None))
        else:
            segs.append((t0 + tip_s, t0 + code_start, "blank", None))
        if words is not None:
            segs.append((t0 + code_start, t0 + code_start + 48e-6, "code", words))
            segs.append((t0 + code_start + 48e-6, t0 + line_s, "pic", None))
        else:
            segs.append((t0 + code_start, t0 + line_s, "pic", None))

    def add_interval(last_h, first):
        # The equalizing pulse opens the interval a full line after the last
        # hsync on the first field and half a line after it on the other.
        # (PAL: the half-line start marks the first field.)
        if first == system.ntsc:
            pattern = [(1.0, "E"), (1.5, "V")]
        else:
            pattern = [(0.5, "E"), (1.0, "V")]
        for off, kind in pattern:
            start = last_h + off * line_s
            width = 1.8e-6 if kind == "E" else 27e-6
            segs.append((start, start + width, "vint", None))

    t = 0.0
    for _ in range(pre_lines):
        add_line(t)
        t += line_s
    fields = []
    for f in range(n_frames):
        for fi in (0, 1):
            first = fi == 0
            last_h = t - line_s
            add_interval(last_h, first)
            # The interval takes two line slots; the field's first line is the
            # one after the last hsync, the interval's slot included.
            t = last_h + 2.0 * line_s
            n_lines = (system.field_lines[0] if first else system.field_lines[1]) - 1
            words = {}
            if first and words_per_frame is not None:
                for idx, word in words_per_frame[f][fi]:
                    words[idx] = word
            for i in range(n_lines):
                add_line(t, words.get(i))
                t += line_s
            fields.append((first, words))

    total = t
    n = int(round(total * fs))
    freq = np.full(n, blank, dtype=np.float64)
    tt = np.arange(n, dtype=np.float64) / fs
    for a, b, kind, payload in segs:
        i0 = int(round(a * fs))
        i1 = min(int(round(b * fs)), n)
        if i1 <= i0:
            continue
        if kind == "tip":
            if pilot_ire > 0.0:
                seg = tt[i0:i1]
                freq[i0:i1] = sync + pilot_ire * hz_ire * np.cos(
                    2 * np.pi * system.lock_hz * (seg - payload)
                )
            else:
                freq[i0:i1] = sync
        elif kind == "vint":
            freq[i0:i1] = sync
        elif kind == "blank":
            freq[i0:i1] = blank
        elif kind == "burst":
            seg = tt[i0:i1]
            freq[i0:i1] = blank + burst_ire * hz_ire * np.cos(
                2 * np.pi * system.fsc_hz * (seg - payload)
            )
        elif kind == "pic":
            # A synthetic picture: the carrier frequency wanders by a few IRE.
            nb = max(1, int(round(0.5e-6 * fs)))
            blocks = np.arange(i0, i1, nb)
            vals = rng.uniform(-8.0, 8.0, size=(blocks.size, 1)) * hz_ire
            idx = np.arange(i0, i1)
            bsel = np.searchsorted(blocks, idx, side="right") - 1
            freq[i0:i1] = blank + vals[bsel, 0]
        elif kind == "code":
            # The Philips code: 24 bits, biphase, 2 us per bit.  The first
            # half-cell of a bit is at the porch level for a 1 and above it for
            # a 0, so the direction of the mid-bit transition is the bit.
            levels = []
            for i in range(24):
                bit = (payload >> (23 - i)) & 1
                levels.append(0 if bit else 1)
                levels.append(1 if bit else 0)
            levels = np.array(levels, dtype=np.float64)
            half = max(1, int(round(1e-6 * fs)))
            idx = np.arange(i1 - i0)
            cell = np.minimum(idx // half, 47)
            freq[i0:i1] = blank + code_ire * hz_ire * levels[cell]

    phase = 2 * np.pi * np.cumsum(freq) / fs
    return np.cos(phase), fields


def _reader(rf: np.ndarray):
    """A read_fn over an in-memory capture."""

    def read_fn(start: int, count: int) -> np.ndarray:
        start = max(start, 0)
        end = min(start + count, rf.size)
        if end <= start:
            return np.zeros(0, dtype=np.float64)
        return rf[start:end]

    return read_fn


def _code_lines(system: SyncSystem) -> list[int]:
    """The line indices (within a field's hsyncs) the codes are read from.

    The codes are read from the field's lines `vbi_lines`, and only from the
    lines that are a few lines after the vertical interval's broad pulse.
    """
    extra_vbi = (6.0, 14.0) if system.ntsc else (8.0, 24.0)
    # The broad pulse is 0.5 lines before the field's first hsync (the
    # interval opens a full line after the last hsync on the first field).
    first = 0.5
    lo, hi = system.vbi_lines
    lines = []
    for index in range(lo - 1, hi - 1):
        # The line is `index + 1` slots into the field, the first slot being
        # the vertical interval's.
        after = index + 1 + 0.5 - first
        if extra_vbi[0] <= after <= extra_vbi[1]:
            lines.append(index)
    return lines


def _words(n_frames: int, lines: list[int], per_frame):
    """The Philips words per frame, on the given lines."""
    out = []
    for f in range(n_frames):
        frame = [[], []]
        for line, word in zip(lines, per_frame[f]):
            if word is not None:
                frame[0].append((line, word))
        out.append(frame)
    return out


@pytest.fixture(scope="module")
def ntsc_system() -> SyncSystem:
    return system_for(True)


@pytest.fixture(scope="module")
def ntsc_lines(ntsc_system) -> list[int]:
    return _code_lines(ntsc_system)


@pytest.fixture(scope="module")
def ntsc_capture(ntsc_system, ntsc_lines):
    """Three frames, each with its own picture number (as a CAV disc has)."""
    per_frame = [[WORD_A, WORD_B, WORD_C], [WORD_A, WORD_B, WORD_D], [WORD_A, WORD_B, WORD_E]]
    words = _words(3, ntsc_lines, per_frame)
    rf, fields = _synth_capture(ntsc_system, n_frames=3, words_per_frame=words)
    return rf, fields, per_frame


@pytest.fixture(scope="module")
def ntsc_records(ntsc_capture):
    rf, _, _ = ntsc_capture
    return list(locate(_reader(rf), FS, system_for(True)))


@pytest.fixture(scope="module")
def ntsc_repair_records(ntsc_system, ntsc_lines):
    """A capture whose third frame loses a word and whose fourth loses them all."""
    per_frame = [
        [WORD_A, WORD_B, WORD_C],
        [WORD_A, WORD_B, WORD_D],
        [None, WORD_B, WORD_E],  # the first word was lost to a dropout
        [WORD_A, None, None],  # only a word every field carries is left
    ]
    words = _words(4, ntsc_lines, per_frame)
    rf, _ = _synth_capture(ntsc_system, n_frames=4, words_per_frame=words)
    return list(locate(_reader(rf), FS, ntsc_system))


@pytest.fixture(scope="module")
def pal_records():
    system = system_for(False)
    lines = _code_lines(system)
    words = _words(2, lines, [[WORD_A, WORD_B]] * 2)
    rf, _ = _synth_capture(
        system, n_frames=2, words_per_frame=words, code_ire=120.0, pilot_ire=40.0
    )
    return list(locate(_reader(rf), FS, system))


# --------------------------------------------------------------------------
# The standards
# --------------------------------------------------------------------------


def test_system_for_ntsc_constants():
    """The NTSC constants are the ones of SMPTE 170M."""
    system = system_for(True)
    assert system.ntsc is True
    np.testing.assert_allclose(system.fsc_hz, 315.0e6 / 88.0, rtol=0, atol=1e-6)
    np.testing.assert_allclose(system.lock_hz, system.fsc_hz, rtol=0, atol=1e-9)
    np.testing.assert_allclose(system.blank_hz, 8.1e6, rtol=0, atol=1e-6)
    np.testing.assert_allclose(system.sync_hz, 8.1e6 - 40.0 * (1.7e6 / 140.0), rtol=0, atol=1e-6)
    assert system.coarse_band == (4.5e6, 12.5e6)
    assert system.fine_band == (3.8e6, 13.0e6)
    assert system.vbi_lines == (12, 20)
    assert system.field_lines == (263, 262)
    np.testing.assert_allclose(system.line_us, 63.5, rtol=0, atol=1e-9)
    np.testing.assert_allclose(system.line_hz, 15734.264, rtol=0, atol=1e-6)
    assert porch_window(system) == (8.0, 9.0)
    assert system.porch_us == 8.0


def test_system_for_pal_constants():
    """The PAL constants are the ones of ITU-R BT.470."""
    system = system_for(False)
    assert system.ntsc is False
    np.testing.assert_allclose(system.lock_hz, 3.75e6, rtol=0, atol=1e-6)
    np.testing.assert_allclose(system.blank_hz, 7.1e6, rtol=0, atol=1e-6)
    np.testing.assert_allclose(
        system.sync_hz, 7.1e6 - 0.3 * (100.0 / 0.7) * 8000.0, rtol=0, atol=1e-6
    )
    assert system.coarse_band == (2.6e6, 11.5e6)
    assert system.fine_band == (2.4e6, 12.0e6)
    assert system.vbi_lines == (10, 30)
    assert system.field_lines == (312, 313)
    np.testing.assert_allclose(system.line_us, 64.0, rtol=0, atol=1e-9)
    np.testing.assert_allclose(system.line_hz, 15625.0, rtol=0, atol=1e-6)
    assert porch_window(system) == (8.3, 9.5)


def test_system_is_frozen():
    """The standards cannot be changed under a caller."""
    system = system_for(True)
    with pytest.raises(Exception):
        system.ntsc = False  # type: ignore[misc]


# --------------------------------------------------------------------------
# The frame code
# --------------------------------------------------------------------------


def test_frame_code_selects_the_cav_and_clv_words():
    """Only the CAV picture numbers and the CLV time codes identify a frame."""
    words = [
        0xF01234,  # a CAV picture number (top nibble 0xF)
        0x80ABCD,  # a CLV picture number (top nibble 0x8)
        0x0F1234,  # top nibble 0x0: not a frame code
        0x7ABCDE,  # top nibble 0x7: not a frame code
        0xF05678,  # another CAV picture number
        0,  # not a word at all
        -0xF01234,  # negative: not a word at all
    ]
    assert frame_code(words) == (0x80ABCD, 0xF01234, 0xF05678)


def test_frame_code_sorts_and_deduplicates():
    """The frame code is a set: two captures of a frame give the same code."""
    assert frame_code([0xF05678, 0xF01234, 0xF05678]) == (0xF01234, 0xF05678)
    assert frame_code([]) == ()
    assert frame_code([0x000000]) == ()


# --------------------------------------------------------------------------
# The NTSC capture
# --------------------------------------------------------------------------


def test_locate_ntsc_finds_the_fields_and_their_parity(ntsc_records, ntsc_capture):
    """Every field of the capture is found, first and second field in turn."""
    _, fields, _ = ntsc_capture
    # The capture holds three frames (six fields); the last one is only
    # flushed when the field after it starts, so five are reported.
    assert len(ntsc_records) == 5
    assert [rec.first for rec in ntsc_records] == [True, False, True, False, True]
    assert [first for first, _ in fields] == [True, False, True, False, True, False]


def test_locate_ntsc_field_line_counts(ntsc_records):
    """Each field reports its own lines, plus the overlap into the next."""
    assert [rec.lines.size for rec in ntsc_records] == [273, 272, 273, 272, 273]


def test_locate_ntsc_line_positions_are_stable(ntsc_records):
    """The lines sit on an even grid, to well under a sample."""
    nominal = FS * 63.5e-6
    for rec in ntsc_records:
        spacing = np.diff(rec.lines)
        # The line length is tracked from the pulses themselves.
        np.testing.assert_allclose(spacing, nominal, rtol=0, atol=0.05)
        # The line-to-line noise of this synthetic capture: the picture is
        # quiet and the carrier exact, so the lines are far better placed
        # than the 0.091 samples rms the RF pass reports on a real capture
        # at 75 MHz.  This capture measures 0.010 samples rms (and 0.028
        # samples at worst) at 40 MHz.
        assert float(np.std(spacing - spacing.mean())) < 0.05
        assert spacing.min() > 0.0


def test_locate_ntsc_reads_the_frame_codes(ntsc_records, ntsc_capture):
    """The Philips codes of the first field are read and the frame selected."""
    _, _, per_frame = ntsc_capture
    expected = [frame_code(words) for words in per_frame]
    assert expected[0] == (WORD_C, WORD_A, WORD_B)
    assert expected[1] == (WORD_D, WORD_A, WORD_B)
    assert expected[2] == (WORD_E, WORD_A, WORD_B)
    codes = [rec.code for rec in ntsc_records]
    # Each frame's first field carries its own code; the second field of a
    # frame inherits the code of the first.
    assert codes[0] == expected[0]
    assert codes[1] == expected[0]
    assert codes[2] == expected[1]
    assert codes[3] == expected[1]
    assert codes[4] == expected[2]


def test_locate_ntsc_code_lines_are_the_vbi_lines(ntsc_lines, ntsc_system):
    """The codes are read from the field's VBI lines."""
    assert ntsc_lines
    lo, hi = ntsc_system.vbi_lines
    for index in ntsc_lines:
        assert lo - 1 <= index < hi - 1


# --------------------------------------------------------------------------
# The dropped frame codes
# --------------------------------------------------------------------------


def test_locate_repairs_a_dropped_frame_code(ntsc_repair_records):
    """A code that lost a word gets it back from the codes before it."""
    codes = [rec.code for rec in ntsc_repair_records if rec.first]
    assert codes[0] == frame_code([WORD_A, WORD_B, WORD_C])
    assert codes[1] == frame_code([WORD_A, WORD_B, WORD_D])
    # The third frame lost WORD_A: it is shared by the two codes before it and
    # is put back.
    assert codes[2] == frame_code([WORD_A, WORD_B, WORD_E])
    assert WORD_A in codes[2]


def test_locate_drops_a_code_with_only_shared_words(ntsc_repair_records):
    """A code left with only the words every field carries identifies no frame."""
    codes = [rec.code for rec in ntsc_repair_records if rec.first]
    # The fourth frame carries only WORD_A, which the two codes before it
    # share: the field is left unpaired rather than paired with a wrong one.
    assert codes[3] == ()


def test_locate_keeps_the_field_of_a_dropped_code(ntsc_repair_records):
    """A field whose code was dropped is still located."""
    assert len(ntsc_repair_records) == 7
    assert ntsc_repair_records[-1].first is True
    assert ntsc_repair_records[-1].code == ()


# --------------------------------------------------------------------------
# The PAL capture
# --------------------------------------------------------------------------


def test_locate_pal_finds_the_fields_and_their_parity(pal_records):
    """The PAL path finds the fields of a 312/313 line capture."""
    assert len(pal_records) == 3
    assert [rec.first for rec in pal_records] == [True, False, True]
    assert [rec.lines.size for rec in pal_records] == [322, 323, 322]


def test_locate_pal_line_positions_are_stable(pal_records):
    """The PAL lines sit on an even grid too."""
    nominal = FS * 64.0e-6
    for rec in pal_records:
        spacing = np.diff(rec.lines)
        # This capture measures 0.003 samples at worst and 0.002 samples rms.
        np.testing.assert_allclose(spacing, nominal, rtol=0, atol=0.05)
        assert float(np.std(spacing - spacing.mean())) < 0.05


def test_locate_pal_reads_the_frame_codes(pal_records):
    """The Philips codes are read on PAL too."""
    expected = frame_code([WORD_A, WORD_B])
    for rec in pal_records:
        assert rec.code == expected


# --------------------------------------------------------------------------
# The degenerate captures
# --------------------------------------------------------------------------


def test_locate_without_any_lines_finds_no_fields():
    """A capture with no usable lines yields no field at all."""
    rng = np.random.default_rng(12345)
    rf = rng.normal(0.0, 0.1, size=int(FS // 400)).astype(np.float64)
    assert list(locate(_reader(rf), FS, system_for(True))) == []


def test_locate_an_empty_capture_finds_no_fields():
    """An empty capture yields no field at all."""
    assert list(locate(_reader(np.zeros(0)), FS, system_for(True))) == []


def test_locate_stops_when_the_caller_asks():
    """The scan stops where the caller stops it."""
    system = system_for(True)
    lines = _code_lines(system)
    words = _words(2, lines, [[WORD_A, WORD_B]] * 2)
    rf, _ = _synth_capture(system, n_frames=2, words_per_frame=words)

    calls = {"n": 0}

    def stop() -> bool:
        calls["n"] += 1
        return True

    assert list(locate(_reader(rf), FS, system, stop=stop)) == []
    assert calls["n"] == 1

    calls["n"] = 0

    def never() -> bool:
        calls["n"] += 1
        return False

    assert list(locate(_reader(rf), FS, system, stop=never))
    assert calls["n"] >= 1


def test_field_record_carries_the_field():
    """A field record carries its parity, its code and its lines."""
    rec = FieldRecord(first=True, code=(1, 2), lines=np.zeros(0, dtype=np.float64))
    assert rec.first is True
    assert rec.code == (1, 2)
    assert rec.lines.size == 0
    assert rec.lines.dtype == np.float64
