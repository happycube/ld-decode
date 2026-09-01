"""Synthetic AC3-RF signals shared by the loopback and end-to-end tests.

The DQPSK modulator is the inverse of what lddecode/ac3rf.py demodulates, so
both the hermetic loopback tests and the full-decode test drive it -- one
straight into the demodulator, the other mixed under a synthesised video
carrier and written out as a capture.  It lives here so the two lanes
modulate against exactly the same definition.
"""

import numpy as np

from lddecode.ac3rf import CARRIER_FREQ, SYMBOL_RATE


def dqpsk_modulate(
    symbols, sample_rate, amplitude=1.0, carrier_freq=CARRIER_FREQ, symbol_rate=SYMBOL_RATE
):
    """Generate a real-valued DQPSK signal at carrier_freq.

    The demodulator mixes with exp(+j w t), so a transmitted phase phi is
    recovered as -phi at baseband; the differential decoder maps symbol 1
    to a -90 degree step, 2 to +90, 3 to 180.

    The carrier and symbol rate default to the demodulator's own, which
    is what a loopback test wants; pass them explicitly to modulate
    against fixed values independent of what ac3rf.py believes."""
    phase_step = {0: 0.0, 1: -np.pi / 2, 2: np.pi / 2, 3: np.pi}
    phases = np.cumsum([phase_step[s] for s in symbols])

    n_samples = int(len(symbols) * sample_rate / symbol_rate)
    t = np.arange(n_samples)
    symbol_index = (t * symbol_rate / sample_rate).astype(int)
    return (
        amplitude * np.cos(2 * np.pi * carrier_freq / sample_rate * t + phases[symbol_index])
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
