"""PAL 8-field sequence position (fieldPhaseID).

A PAL field reads its position from two burst measurements: whether line 6
carries burst (the 4-field position, with the field's parity), and the
burst phase on lines 7, 11, 15 and 19 (fields 1-4 against 5-8, 180 degrees
apart).  Two ways these went wrong on real discs:

* with a noisy burst window, line 6 without burst reads a third of the
  burst level or more, between the fixed 0.2x / 0.8x bands, and a burst
  with noise on it trips the 30 IRE peak limit - most fields then fell
  back to continuing the sequence, and a decode that started on such a
  guess broke the sequence at the first real reading;
* on a disc whose burst sits near 90 degrees from the 0 degrees the
  per-field test compares with, the 1-4 / 5-8 half read at random.

So line 6 is judged against the field's own levels when the fixed bands
cannot decide it, and the commit stage decides the half against the burst
phase of the fields committed before.
"""

import types

import numpy as np
import pytest

from lddecode.decoder import LDdecode
from lddecode.dsp import (
    circular_mean_halfcycles,
    line6_burst_self_referenced,
    line6_burst_state,
)
from synthetic_field import make_field, make_rf

pytestmark = [pytest.mark.unit, pytest.mark.decode]


# -- line 6 ---------------------------------------------------------------

def test_the_fixed_bands_decide_as_before():
    assert line6_burst_state(20.0, 20.0) is True
    assert line6_burst_state(16.5, 20.0) is True
    assert line6_burst_state(3.9, 20.0) is False
    assert line6_burst_state(9.0, 20.0) is None     # between the bands
    assert line6_burst_state(25.0, 20.0) is None    # over 1.2x
    assert line6_burst_state(None, 20.0) is None


def test_a_noisy_window_without_burst_reads_as_its_line_5():
    """South DS10 outer: line 5 9.4, line 6 9.5, burst median 18.4 IRE."""
    assert line6_burst_self_referenced(9.5, 9.4, 18.4) is False
    assert line6_burst_self_referenced(7.5, 8.0, 21.2) is False
    # GGV inner: a quiet window, line 6 just over the fixed 0.2x band
    assert line6_burst_self_referenced(3.47, 2.39, 15.37) is False


def test_a_full_burst_past_the_peak_limit_reads_as_present():
    assert line6_burst_self_referenced(19.0, 9.0, 21.0) is True


def test_a_part_burst_is_undecided():
    """EcoDisc DS1: line 6 of a field 1 at half the burst, line 5 2.2 IRE."""
    assert line6_burst_self_referenced(11.2, 2.24, 21.6) is None
    assert line6_burst_self_referenced(15.0, 9.0, 21.0) is None


def test_more_than_the_burst_is_interference():
    assert line6_burst_self_referenced(26.0, 9.0, 21.0) is None


def test_unmeasurable_levels_decide_nothing():
    assert line6_burst_self_referenced(5.0, 0.0, 21.0) is None
    assert line6_burst_self_referenced(0.0, 5.0, 21.0) is None
    assert line6_burst_self_referenced(None, 5.0, 21.0) is None
    assert line6_burst_self_referenced(5.0, None, 21.0) is None


def test_circular_mean_wraps():
    assert circular_mean_halfcycles([1.95, 0.05]) == pytest.approx(0.0, abs=1e-9) or \
        circular_mean_halfcycles([1.95, 0.05]) == pytest.approx(2.0, abs=1e-9)
    assert circular_mean_halfcycles([0.45, 0.55]) == pytest.approx(0.5)
    assert circular_mean_halfcycles([1.4, 1.6]) == pytest.approx(1.5)


# -- the commit stage -----------------------------------------------------

def decoder_stub(phases=8):
    """The commit stage's view of a decoder: fields 1000 file samples apart."""
    it = types.SimpleNamespace(
        rf=types.SimpleNamespace(SysParams={"fieldPhases": phases}),
        fieldinfo=[], bytes_per_field=1000,
        burst_phase_ref=None, phase_id_measured=False, phase_jump_pending=None,
        BURST_PHASE_REF_WEIGHT=LDdecode.BURST_PHASE_REF_WEIGHT,
    )
    it._follows_last_committed = lambda f: LDdecode._follows_last_committed(it, f)
    it.settle = lambda f: LDdecode.settle_pal_phase_id(it, f)
    return it


def commit(it, position, phase, read=None, fallback=False, m4=True, gap=0):
    """Commit the next field: at sequence `position`, burst phase `phase`
    (half-cycles), its own reading `read` (default: right).  Returns the
    committed position."""
    n = len(it.fieldinfo)
    loc = (it.fieldinfo[-1]["fileLoc"] + 1000 * (1 + gap)) if n else 0
    f = types.SimpleNamespace(
        fieldPhaseID=position if read is None else read,
        phase_id_fallback=fallback,
        phase_m4=((position - 1) % 4) + 1 if m4 else None,
        burst_phase=phase, readloc=float(loc), isFirstField=position % 2 == 1,
    )
    it.settle(f)
    it.fieldinfo.append({"fileLoc": loc, "isFirstField": f.isFirstField,
                         "fieldPhaseID": f.fieldPhaseID})
    return f.fieldPhaseID


def sequence(sch, n=24, start=1, seed=0, noise=0.03):
    """Fields of a run whose fields 1-4 burst sits at `sch` half-cycles."""
    rng = np.random.default_rng(seed)
    out = []
    for k in range(n):
        pos = (start - 1 + k) % 8 + 1
        half = 0 if pos <= 4 else 1
        out.append((pos, (sch + half + rng.normal(0, noise)) % 2.0))
    return out


def test_burst_near_0_degrees_commits_what_the_fields_read():
    it = decoder_stub()
    for pos, phase in sequence(0.02):
        assert commit(it, pos, phase) == pos


def test_burst_near_90_degrees_follows_the_first_reading():
    """NPE outer-middle: the burst sits 0.49 half-cycles off, each field's
    own half is a coin toss; after the first field the run decides."""
    rng = np.random.default_rng(1)
    it = decoder_stub()
    for k, (pos, phase) in enumerate(sequence(0.5, n=40)):
        coin = pos if rng.random() < 0.5 else (pos + 3) % 8 + 1
        assert commit(it, pos, phase, read=coin if k else pos) == pos


def test_the_reference_follows_a_slow_drift():
    it = decoder_stub()
    rng = np.random.default_rng(2)
    for k in range(400):
        pos = k % 8 + 1
        sch = 0.6 * k / 400          # 108 degrees over the run
        phase = (sch + (pos > 4) + rng.normal(0, 0.02)) % 2.0
        assert commit(it, pos, phase, read=(pos + 3) % 8 + 1 if k else pos) == pos


def test_a_tied_field_is_decided_by_its_burst_phase():
    """No reference yet: against 0 degrees; then against the reference."""
    it = decoder_stub()
    assert commit(it, 5, 1.02, read=1, fallback=True) == 5
    assert commit(it, 6, 0.98, read=2, fallback=True) == 6


def test_a_field_without_a_4_field_position_keeps_its_fallback():
    it = decoder_stub()
    commit(it, 1, 0.0)
    assert commit(it, 2, None, read=2, fallback=True, m4=False) == 2


def test_a_single_misread_field_keeps_the_sequence():
    """North DS5 outer: a first field read line 6 as burst (1 read as 3)."""
    it = decoder_stub()
    for pos in (5, 6, 7, 8):
        commit(it, pos, 1.0)
    assert commit(it, 1, 0.0, read=3) == 1
    assert commit(it, 2, 0.0) == 2
    assert commit(it, 3, 0.0) == 3


def test_a_misread_held_across_fallback_fields():
    it = decoder_stub()
    for pos in (1, 2, 3):
        commit(it, pos, 0.0)
    assert commit(it, 4, 0.0, read=6) == 4
    assert commit(it, 5, None, fallback=True, m4=False) == 5
    assert commit(it, 6, 1.0) == 6


def test_a_real_jump_is_taken_one_field_late():
    """A track jump back one frame: 1 2 3 4 | 3 4 5 ..."""
    it = decoder_stub()
    got = [commit(it, p, 0.0) for p in (1, 2, 3, 4)]
    got += [commit(it, p, 0.0) for p in (3, 4)]
    got += [commit(it, p, 1.0) for p in (5, 6)]
    assert got == [1, 2, 3, 4, 5, 4, 5, 6]


def test_a_still_frame_is_still_reported_every_frame():
    it = decoder_stub()
    got = [commit(it, p, 0.0) for p in (1, 2, 1, 2, 1, 2)]
    assert got == [1, 2, 3, 2, 3, 2]


def test_a_reading_on_a_guessed_sequence_is_taken_at_once():
    """The decode began on fields that could not read line 6, numbered
    on from a guess; the first reading replaces the guess."""
    it = decoder_stub()
    commit(it, 1, None, fallback=True, m4=False)
    commit(it, 2, None, fallback=True, m4=False)
    # the committed guess says 3 next; the field reads 7
    assert commit(it, 7, 1.0, read=7) == 7


def test_a_field_after_a_gap_is_taken_as_it_reads():
    it = decoder_stub()
    for pos in (1, 2, 3, 4):
        commit(it, pos, 0.0)
    assert commit(it, 7, 1.0, gap=2) == 7


def test_ntsc_is_left_alone():
    it = decoder_stub(phases=4)
    assert commit(it, 1, 0.0, read=3) == 3
    assert it.burst_phase_ref is None


# -- a synthetic PAL field ------------------------------------------------

@pytest.fixture(scope="module")
def pal_rf():
    return make_rf("PAL")


def synthetic_pal_field(rf, first, burst6, sch, noise_ire, seed=0):
    """Blanking lines with a 21.4 IRE burst at phase `sch` (radians, from
    each line's start) on lines 7-310, and on line 6 if `burst6`, under
    white noise of `noise_ire` rms."""
    rng = np.random.default_rng(seed)
    field = make_field(rf, is_first_field=first)
    linelocs = field.linelocs + 3000.0
    field.linelocs = linelocs
    n = int(linelocs[-1] + rf.linelen) + 3000
    fsc, freq = rf.SysParams["fsc_mhz"], rf.freq
    hz_ire = rf.DecoderParams["hz_ire"]
    signal = np.full(n, rf.iretohz(0), dtype=np.float64)
    for line in range(1, 311):
        if line < 6 or (line == 6 and not burst6):
            continue
        loc = linelocs[line + field.lineoffset]
        b0, b1 = int(loc + 5.6 * freq), int(loc + 8.0 * freq)
        t = np.arange(b0, b1, dtype=np.float64) - loc
        signal[b0:b1] += 21.4 * hz_ire * np.sin(2 * np.pi * fsc * t / freq + sch)
    signal += rng.normal(0.0, noise_ire * hz_ire, n)

    names = ["demod", "demod_raw", "demod_05", "demod_burst"]
    video = np.recarray(n, dtype=[(name, np.float32) for name in names])
    for name in names:
        video[name] = signal
    field.data["video"] = video
    field.anchor = None
    field.burstmedian = field.calc_burstmedian()
    return field


@pytest.mark.parametrize("first,burst6,m4", [
    (True, False, 1), (False, True, 2), (True, True, 3), (False, False, 4)])
def test_line_6_is_read_through_a_noisy_window(pal_rf, first, burst6, m4):
    """6 IRE of noise: the no-burst window reads ~8 IRE, a third of the
    burst, and the burst mostly trips the 30 IRE peak limit, so the fixed
    bands decide few of these.  Never wrong; undecided (a sequence
    fallback) at most now and then."""
    hz_ire = pal_rf.DecoderParams["hz_ire"]
    read, fixed = [], []
    for seed in range(8):
        field = synthetic_pal_field(pal_rf, first, burst6, 0.0, 6.0, seed=seed)
        level6 = field.get_burstlevel(6)
        fixed.append(line6_burst_state(
            None if level6 is None else level6 / hz_ire, field.burstmedian))
        field.determine_field_number()
        read.append(field.phase_m4)
    assert set(fixed) <= {burst6, None}
    assert set(read) <= {m4, None}
    assert read.count(m4) >= 6
    assert read.count(m4) > fixed.count(burst6)


def test_quiet_fields_decide_as_the_fixed_bands_did(pal_rf):
    for first, burst6, m4 in [(True, False, 1), (False, True, 2)]:
        field = synthetic_pal_field(pal_rf, first, burst6, 0.0, 0.3)
        assert line6_burst_state(
            field.get_burstlevel(6) / pal_rf.DecoderParams["hz_ire"],
            field.burstmedian) is burst6
        field.determine_field_number()
        assert field.phase_m4 == m4


def test_the_burst_phase_measures_the_subcarrier_phase(pal_rf):
    """Half a cycle of subcarrier is one half-cycle of burst_phase, a
    quarter cycle half of one, on either field parity."""
    def phase(sch, first=True):
        field = synthetic_pal_field(pal_rf, first, True, sch, 0.3)
        field.determine_field_number()
        return field.burst_phase

    def dist(a, b):
        return abs((a - b + 1.0) % 2.0 - 1.0)

    p0 = phase(0.0)
    assert dist(phase(np.pi), p0) == pytest.approx(1.0, abs=0.05)
    assert dist(phase(np.pi / 2), p0) == pytest.approx(0.5, abs=0.05)
    # field 2/6 reads the opposite way round, and burst_phase folds that in
    assert dist(phase(0.0, first=False), phase(np.pi, first=False)) == \
        pytest.approx(1.0, abs=0.05)
