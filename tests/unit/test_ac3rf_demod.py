"""Loopback tests for AC3-RF demodulation.

A random symbol stream is modulated as differential QPSK on a 2.88 MHz carrier
and fed straight back into lddecode/ac3rf.py, clean and then with noise.  The
demodulator's integration into a full decode is covered by
tests/functional/test_ac3rf_decode.py.
"""

import numpy as np
import pytest

from lddecode.ac3rf import Ac3RfDemodulator

from ac3_signals import dqpsk_modulate, find_and_compare

pytestmark = [pytest.mark.unit, pytest.mark.dsp]


def test_loopback_clean():
    rng = np.random.default_rng(12345)
    tx = rng.integers(0, 4, 20000, dtype=np.uint8)
    rf = dqpsk_modulate(tx, 40e6)

    demod = Ac3RfDemodulator(40e6)
    assert demod.input_sample_alignment() == 1

    # Feed the signal in uneven block sizes to exercise the streaming state
    rx = b""
    pos = 0
    for blocklen in [100001, 65536, 999999] * 100:
        if pos >= len(rf):
            break
        rx += demod.demodulate_to_symbols(rf[pos : pos + blocklen])
        pos += blocklen

    rx = np.frombuffer(rx, np.uint8)
    match_rate = find_and_compare(tx, rx)
    assert match_rate > 0.999, f"symbol match rate {match_rate}"


def test_loopback_noisy():
    rng = np.random.default_rng(999)
    tx = rng.integers(0, 4, 20000, dtype=np.uint8)
    rf = dqpsk_modulate(tx, 40e6)
    rf += rng.normal(0, 0.25, len(rf)).astype(np.float32)

    demod = Ac3RfDemodulator(40e6)
    rx = np.frombuffer(demod.demodulate_to_symbols(rf), np.uint8)

    match_rate = find_and_compare(tx, rx)
    assert match_rate > 0.99, f"symbol match rate {match_rate}"
