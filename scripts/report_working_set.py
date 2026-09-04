#!/usr/bin/env python3
"""Report what one decoder keeps resident and what it reads per RF block.

Throughput under several concurrent decoders is set by how much of one decoder's
hot data fits in the shared last-level cache, so footprint is a number this
project has to be able to state, not estimate.  This script constructs an
``RFDecode`` per system exactly as a decode does and reports:

* every resident filter array, by name, shape, dtype and size, plus the total;
* the sinc resample look-up table, which is read one 64-byte row per *output*
  sample and so is hot for the whole of every field;
* the bytes ``demodblock`` reads per block, measured rather than listed: the
  filter bank is substituted with a recording mapping and the per-channel audio
  filters with recording proxies, one block is demodulated, and the arrays that
  were actually indexed are summed;
* the peak transient allocation of one block, from ``tracemalloc`` (NumPy
  registers its buffers with it), which is what the block's temporaries cost --
  NumPy has no loop fusion, so each spectrum multiply materialises its own array.

Conditional paths are exercised: ``mtf_level`` is non-zero (so the MTF filter is
read) and, for PAL, the audio-carrier test is forced true (so the carrier notch
is read), which is the case on a disc that carries analogue audio.  Both are
reported per array, so a run where they do not apply can be read off the table.

Usage:
    python3 scripts/report_working_set.py [--systems PAL NTSC] [--json out.json]
"""

import argparse
import json
import os
import sys
import tracemalloc

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lddecode.rfdecode import RFDecode  # noqa: E402

MIB = float(2 ** 20)


class RecordingMapping(dict):
    """A dict that records which keys were fetched, and how often.

    Used in place of ``RFDecode.Filters`` for one ``demodblock`` call.  Only
    ``__getitem__`` records: ``in`` tests read no array bytes.
    """

    def __init__(self, source):
        super().__init__(source)
        self.reads = {}

    def __getitem__(self, key):
        self.reads[key] = self.reads.get(key, 0) + 1
        return super().__getitem__(key)


class RecordingNamespace:
    """Proxy over a namespace that records ndarray attributes as they are read."""

    def __init__(self, wrapped, name, sink):
        object.__setattr__(self, "_wrapped", wrapped)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_sink", sink)

    def __getattr__(self, attr):
        value = getattr(object.__getattribute__(self, "_wrapped"), attr)
        if isinstance(value, np.ndarray):
            sink = object.__getattribute__(self, "_sink")
            key = "audio.%s.%s" % (object.__getattribute__(self, "_name"), attr)
            entry = sink.setdefault(key, [value, 0])
            entry[1] += 1
        return value


def synthetic_block(rf, seed=12345):
    """A blocklen-sized RF block: FM carrier at mid-deviation plus noise.

    The numbers this script reports are array sizes and access counts, which do
    not depend on the signal; a plausible carrier is used only so the demodulator
    runs its normal path rather than degenerate cases.
    """
    rng = np.random.default_rng(seed)
    time_s = np.arange(rf.blocklen) / rf.freq_hz
    # Mid-deviation: the FM carrier frequency half way between 0 and 100 IRE.
    carrier = rf.SysParams["ire0"] + 50 * rf.SysParams["hz_ire"]
    signal = np.cos(2 * np.pi * carrier * time_s)
    signal += 0.01 * rng.standard_normal(rf.blocklen)
    return (signal * 4096 + 8192).astype(np.double)


def resident_filters(rf):
    """Every distinct resident filter array: [(name, shape, dtype, nbytes)]."""
    rows = []
    seen = set()
    for name, value in sorted(rf.Filters.items()):
        array = np.asarray(value) if not isinstance(value, np.ndarray) else value
        if array.dtype == object or array.size == 0:
            continue
        if id(array) in seen:
            continue
        seen.add(id(array))
        rows.append((name, tuple(array.shape), str(array.dtype), int(array.nbytes)))
    for channel in getattr(rf, "audio", {}) or {}:
        namespace = rf.audio[channel]
        for attr in sorted(vars(namespace)):
            value = getattr(namespace, attr)
            if not isinstance(value, np.ndarray) or value.size == 0:
                continue
            if id(value) in seen:
                continue
            seen.add(id(value))
            rows.append(
                ("audio.%s.%s" % (channel, attr), tuple(value.shape), str(value.dtype),
                 int(value.nbytes))
            )
    return rows


def per_block_reads(rf):
    """Arrays ``demodblock`` indexes for one block: [(name, nbytes, reads)].

    Substitutes recording views of the filter bank and the audio filter
    namespaces, demodulates one synthetic block with the MTF path and (on PAL)
    the audio-carrier notch engaged, then restores the originals.
    """
    data = synthetic_block(rf)

    original_filters = rf.Filters
    original_audio = dict(getattr(rf, "audio", {}) or {})
    original_carrier_test = getattr(rf, "pal_audio_carriers_present", None)
    carrier_test_was_instance_attr = "pal_audio_carriers_present" in vars(rf)

    recording = RecordingMapping(original_filters)
    audio_sink = {}
    rf.Filters = recording
    for channel, namespace in original_audio.items():
        rf.audio[channel] = RecordingNamespace(namespace, channel, audio_sink)
    if original_carrier_test is not None:
        rf.pal_audio_carriers_present = lambda _fft: True

    try:
        rf.demodblock(data=data, mtf_level=1.0, cut=True, raw_mtf=True)
    finally:
        rf.Filters = original_filters
        for channel, namespace in original_audio.items():
            rf.audio[channel] = namespace
        if original_carrier_test is not None:
            if carrier_test_was_instance_attr:
                rf.pal_audio_carriers_present = original_carrier_test
            else:
                del rf.pal_audio_carriers_present

    rows = []
    seen = set()
    for name, count in recording.reads.items():
        array = original_filters[name]
        array = array if isinstance(array, np.ndarray) else np.asarray(array)
        if id(array) in seen:
            continue
        seen.add(id(array))
        rows.append((name, int(array.nbytes), count))
    for name, (array, count) in audio_sink.items():
        if id(array) in seen:
            continue
        seen.add(id(array))
        rows.append((name, int(array.nbytes), count))
    rows.sort(key=lambda row: -row[1])
    return rows


def per_block_peak_bytes(rf, repeats=3):
    """Peak simultaneously-live allocation during one ``demodblock`` call.

    NumPy registers its buffers with ``tracemalloc``, so the peak minus the
    entry level is the block's temporaries: the mirrored spectrum, the filtered
    copies, the hilbert and demod results, the video stack and the float32
    copies.  Run more than once and take the smallest, so a first-call cache or
    plan allocation is not counted as per-block cost.
    """
    data = synthetic_block(rf)
    rf.demodblock(data=data, mtf_level=1.0, cut=True, raw_mtf=True)
    peaks = []
    for _ in range(repeats):
        tracemalloc.start()
        entry = tracemalloc.get_traced_memory()[0]
        rf.demodblock(data=data, mtf_level=1.0, cut=True, raw_mtf=True)
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        peaks.append(peak - entry)
    return min(peaks)


def report(system, json_rows):
    rf = RFDecode(
        system=system,
        decode_digital_audio=True,
        decode_analog_audio=44100,
        has_analog_audio=True,
    )

    resident = resident_filters(rf)
    resident_total = sum(row[3] for row in resident)
    lut = np.asarray(rf.downscale_sinc_lut)
    block = per_block_reads(rf)
    block_total = sum(row[1] for row in block)
    temporaries = per_block_peak_bytes(rf)
    hot = block_total + int(lut.nbytes) + temporaries

    print("=== %s: blocklen %d, input %.1f MSPS ===" % (system, rf.blocklen, rf.freq))
    print("-- resident filter arrays (largest first) --")
    for name, shape, dtype, nbytes in sorted(resident, key=lambda row: -row[3])[:14]:
        print("  %-26s %-16s %-11s %9.1f KiB" % (name, shape, dtype, nbytes / 1024.0))
    if len(resident) > 14:
        print("  %-26s %48.1f KiB" % ("(%d smaller arrays)" % (len(resident) - 14),
                                      sum(row[3] for row in
                                          sorted(resident, key=lambda r: -r[3])[14:]) / 1024.0))
    print("  %-26s %48.2f MiB" % ("resident filter bank", resident_total / MIB))
    print("-- resample look-up table --")
    print("  %-26s %-16s %-11s %9.2f MiB"
          % ("downscale_sinc_lut", tuple(lut.shape), str(lut.dtype), lut.nbytes / MIB))
    print("  row stride %d bytes; one row read per output sample"
          % (lut.nbytes // max(lut.shape[0], 1)))
    print("-- arrays demodblock indexes per block --")
    for name, nbytes, count in block:
        print("  %-26s %9.1f KiB   x%d" % (name, nbytes / 1024.0, count))
    print("  %-34s %40.2f MiB" % ("filter bytes read per block", block_total / MIB))
    print("  %-34s %40.2f MiB" % ("peak block temporaries", temporaries / MIB))
    print("-- totals --")
    print("  %-34s %40.2f MiB"
          % ("resident, all filters + LUT", (resident_total + lut.nbytes) / MIB))
    print("  %-34s %40.2f MiB" % ("hot per block (read + LUT + temps)", hot / MIB))
    print("  32 MiB L3 holds %.1f decoders' hot sets" % (32 * MIB / hot))
    print()

    json_rows.append(
        {
            "system": system,
            "blocklen": int(rf.blocklen),
            "resident_filter_bytes": int(resident_total),
            "resident_filters": [
                {"name": n, "shape": list(s), "dtype": d, "bytes": b} for n, s, d, b in resident
            ],
            "sinc_lut_bytes": int(lut.nbytes),
            "sinc_lut_shape": list(lut.shape),
            "per_block_bytes": int(block_total),
            "per_block_reads": [{"name": n, "bytes": b, "reads": c} for n, b, c in block],
            "per_block_peak_temporary_bytes": int(temporaries),
            "hot_bytes": int(hot),
        }
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--systems", nargs="+", default=["PAL", "NTSC"], choices=["PAL", "NTSC"])
    parser.add_argument("--json", default=None, help="also write the figures here")
    args = parser.parse_args(argv)

    json_rows = []
    for system in args.systems:
        report(system, json_rows)
    if args.json:
        with open(args.json, "w") as handle:
            json.dump(json_rows, handle, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
