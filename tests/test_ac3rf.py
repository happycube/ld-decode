#!/usr/bin/python3
#
# Loopback test for lddecode/ac3rf.py: modulate a random symbol stream as
# differential QPSK on a 2.88 MHz carrier and check that the demodulator
# recovers it.

import numpy as np

from lddecode.ac3rf import Ac3RfDemodulator, SYMBOL_RATE, CARRIER_FREQ


def dqpsk_modulate(symbols, sample_rate, amplitude=1.0):
    """Generate a real-valued DQPSK signal at CARRIER_FREQ.

    The demodulator mixes with exp(+j w t), so a transmitted phase phi is
    recovered as -phi at baseband; the differential decoder maps symbol 1
    to a -90 degree step, 2 to +90, 3 to 180."""
    phase_step = {0: 0.0, 1: -np.pi / 2, 2: np.pi / 2, 3: np.pi}
    phases = np.cumsum([phase_step[s] for s in symbols])

    n_samples = int(len(symbols) * sample_rate / SYMBOL_RATE)
    t = np.arange(n_samples)
    symbol_index = (t * SYMBOL_RATE / sample_rate).astype(int)
    return (
        amplitude * np.cos(2 * np.pi * CARRIER_FREQ / sample_rate * t + phases[symbol_index])
    ).astype(np.float32)


def find_and_compare(tx, rx, probe_start=500, probe_len=64):
    """Align rx against tx using a probe subsequence, then return the
    match rate over the overlapping tail."""
    probe = tx[probe_start : probe_start + probe_len]
    rx_bytes = rx.tobytes()
    pos = rx_bytes.find(probe.tobytes())
    assert pos >= 0, "transmitted probe sequence not found in demodulated output"

    tx_tail = tx[probe_start:]
    rx_tail = rx[pos : pos + len(tx_tail)]
    n = min(len(tx_tail), len(rx_tail))
    assert n > 1000
    return np.mean(tx_tail[:n] == rx_tail[:n])


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


if __name__ == "__main__":
    test_loopback_clean()
    test_loopback_noisy()
    print("OK")
