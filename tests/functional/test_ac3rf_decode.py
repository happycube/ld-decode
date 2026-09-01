"""End-to-end AC3-RF decode.

Synthesises a complete NTSC LD signal carrying an AC3 QPSK subcarrier, writes
it out as a raw capture and runs ld-decode --AC3 over it.  This covers the
demodulator's integration into the decoder -- per-field demodulation, the
.ac3sym output, and the per-field symbol counts recorded in the metadata --
none of which exists below the level of a whole decode run, which is why this
cannot be a unit test.  The demodulator itself is covered by
tests/unit/test_ac3rf_demod.py.
"""

import os
import pathlib
import sqlite3
import subprocess
import sys

import numpy as np
import pytest

from ac3_signals import dqpsk_modulate, find_and_compare

pytestmark = [pytest.mark.functional, pytest.mark.decode, pytest.mark.slow]


# NTSC LD signal parameters, matching SysParams_NTSC in lddecode/core.py.
SAMPLE_RATE = 40e6
HALFLINE_US = 63.55555555555555 / 2
HALFLINES_PER_FIELD = 525  # 262.5 lines
IRE0_HZ = 8100000.0
HZ_IRE = 1700000 / 140.0
SYNC_IRE = -40.0
BLACK_IRE = 7.5
HSYNC_US = 4.7
EQ_US = 2.3
VSYNC_US = 27.1
NUM_PULSES = 6

# Subcarrier level relative to the video FM carrier.  On a real disc the
# audio carriers sit well below the video carrier.
QPSK_AMPLITUDE = 0.15

# The AC3 subcarrier as specified for LD, stated here rather than taken
# from ac3rf.py so that the end-to-end test is modulating against the
# spec and would notice if the demodulator's own values drifted from it.
AC3_CARRIER_HZ = 2.88e6
AC3_SYMBOL_RATE = 288e3

# tests/functional/<this file> -> the repo root is two levels up.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def build_field_ire():
    """Return one NTSC field as an IRE waveform, over a black raster.

    Each field is 262.5 lines: 6 equalizing pulses, 6 serrated vertical
    sync pulses and 6 more equalizing pulses (all at twice line rate),
    then normal lines each with a horizontal sync pulse.  Fields are
    identical, and interlace falls out of a field being an odd number of
    half-lines, so successive fields start on alternating whole-line and
    half-line boundaries."""
    total = int(round(HALFLINES_PER_FIELD * HALFLINE_US * SAMPLE_RATE / 1e6))
    ire = np.full(total, BLACK_IRE, dtype=np.float64)

    def punch(start_us, dur_us):
        start = int(round(start_us * SAMPLE_RATE / 1e6))
        end = int(round((start_us + dur_us) * SAMPLE_RATE / 1e6))
        ire[start : min(end, total)] = SYNC_IRE

    for halfline in range(HALFLINES_PER_FIELD):
        t = halfline * HALFLINE_US
        if halfline < NUM_PULSES:
            punch(t, EQ_US)
        elif halfline < 2 * NUM_PULSES:
            punch(t, VSYNC_US)
        elif halfline < 3 * NUM_PULSES:
            punch(t, EQ_US)
        elif (halfline - 3 * NUM_PULSES) % 2 == 0:
            punch(t, HSYNC_US)

    return ire


def synthesize_disc_rf(n_fields, rng):
    """Return (samples, symbols) for a synthetic AC3 disc RF signal.

    The video is FM modulated onto the LD video carrier, and the AC3 QPSK
    subcarrier is mixed in underneath it."""
    ire = np.tile(build_field_ire(), n_fields)
    video = np.cos(np.cumsum(2 * np.pi * (IRE0_HZ + ire * HZ_IRE) / SAMPLE_RATE))

    n_symbols = int(np.ceil(len(video) * AC3_SYMBOL_RATE / SAMPLE_RATE))
    symbols = rng.integers(0, 4, n_symbols, dtype=np.uint8)
    qpsk = dqpsk_modulate(
        symbols,
        SAMPLE_RATE,
        amplitude=QPSK_AMPLITUDE,
        carrier_freq=AC3_CARRIER_HZ,
        symbol_rate=AC3_SYMBOL_RATE,
    )

    n = min(len(video), len(qpsk))
    combined = video[:n] + qpsk[:n]
    combined *= 0.8 / np.max(np.abs(combined))
    return (combined * 32767).astype(np.int16), symbols


def run_ld_decode(rf_path, out_base):
    """Run ld-decode --AC3 over rf_path, writing output to out_base."""
    env = dict(os.environ)
    # Run against this checkout, whether or not lddecode is installed.
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "ld-decode"), "--tbc", "--AC3", str(rf_path), str(out_base)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"ld-decode failed:\n{result.stderr}"


def test_decode_ac3_end_to_end(tmp_path):
    rng = np.random.default_rng(1234)
    samples, tx = synthesize_disc_rf(10, rng)

    # .s16 is raw 16-bit samples at 40 MHz, which ld-decode reads directly.
    rf_path = tmp_path / "ac3-synthetic.s16"
    samples.tofile(rf_path)
    out_base = tmp_path / "ac3-synthetic"
    run_ld_decode(rf_path, out_base)

    rx = np.fromfile(str(out_base) + ".ac3sym", np.uint8)
    assert len(rx) > 0, "no symbols were written"
    assert set(np.unique(rx)) <= {0, 1, 2, 3}, f"symbols out of range: {np.unique(rx)}"

    # ld-decode starts part way into the file, so the demodulated stream is
    # a subsequence of the transmitted one: probe from it to find where.
    match_rate = find_and_compare(rx, tx)
    assert match_rate > 0.99, f"symbol match rate {match_rate}"

    # Each field records how many symbols were demodulated during it, so
    # that consumers can reconstruct each field's range by summation; the
    # counts must therefore account for the .ac3sym file exactly.
    with sqlite3.connect(str(out_base) + ".tbc.db") as conn:
        counts = [
            row[0]
            for row in conn.execute(
                "SELECT ac3_symbols FROM field_record ORDER BY field_id"
            )
        ]
    assert len(counts) > 1, "expected more than one field to be decoded"
    assert all(count > 0 for count in counts), f"field with no symbols: {counts}"
    assert sum(counts) == len(rx), (
        f"per-field counts sum to {sum(counts)}, but .ac3sym holds {len(rx)} symbols"
    )
