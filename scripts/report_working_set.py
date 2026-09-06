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
  NumPy has no loop fusion, so each spectrum multiply materialises its own array;
* the pocketfft transform plans the block needs, discovered the same way (the
  ``scipy.fft`` module ``rfdecode`` calls is substituted with a recording proxy
  for one block).  A plan is a twiddle table that every transform of that
  length and precision reads, so it is per-process hot data exactly as the
  filter bank is, and it is invisible to both of the recorders above.

Plan sizes are measured, not derived.  ``plan_table_bytes`` returns
2*N*itemsize for a complex plan and 3*N*itemsize for a real one; those two
coefficients were fitted to the resident-set delta of building one plan in a
fresh interpreter, with the transform's own output allocation subtracted by
differencing against a repeat call that hits the cached plan::

    kind        N       measured      model    (bytes per sample)
    c2c f64     16384   17.25         16.0
    c2c f64     32768   16.38         16.0
    c2c f64     65536   16.19         16.0
    c2c f32     32768    8.62          8.0
    r2c/c2r f64 16384   23.75         24.0
    r2c/c2r f64 32768   23.88         24.0
    r2c/c2r f32 16384   11.75         12.0
    r2c/c2r f32 32768   11.88         12.0

Summed over the four plans a PAL block needs at blocklen 32768 the model gives
1664 KiB against 1668 KiB measured.  r2c and c2r share one plan at a given
length and precision, which the same probe confirms (building both costs what
building either costs); the probe is ``docs-planning`` material, not committed.

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

from lddecode import rfdecode as rfdecode_module  # noqa: E402
from lddecode.rfdecode import RFDecode  # noqa: E402

MIB = float(2 ** 20)

#: The mtf_level the recorded block is demodulated at.  Any non-zero level
#: exercises the same arrays; a decode is at one from its first block.
BLOCK_MTF_LEVEL = 1.13

#: Reals per sample in a pocketfft plan's twiddle tables, by transform kind.
#: Measured, not derived from the layout -- see the module docstring for the
#: fit and its residuals.
PLAN_REALS_PER_SAMPLE = {"complex": 2, "real": 3}


def plan_table_bytes(length, dtype, kind):
    """Bytes pocketfft keeps resident for one cached transform plan.

    length -- transform length in samples.  For an inverse real transform this
              is the length of the *real* side, which is what the plan is
              built for.
    dtype  -- the precision the transform runs in.  A complex dtype is taken
              as its real precision, so complex128 and float64 agree; anything
              that is not single precision is treated as double, which is what
              pocketfft promotes to.
    kind   -- "complex" for c2c in either direction, or "real" for r2c and
              c2r, which share one plan at a given length and precision.

    The coefficients are measured (module docstring), because pocketfft's
    twiddle layout is an implementation detail rather than a documented one.
    """
    if kind not in PLAN_REALS_PER_SAMPLE:
        raise ValueError("unknown transform kind %r" % (kind,))
    if length <= 0:
        raise ValueError("transform length must be positive, got %r" % (length,))
    itemsize = np.dtype(real_precision(dtype)).itemsize
    return int(PLAN_REALS_PER_SAMPLE[kind] * int(length) * itemsize)


def real_precision(dtype):
    """The real dtype a transform of `dtype` runs at.

    pocketfft has a single-precision path for float32/complex64 and promotes
    everything else to double, so this is a two-way split rather than a
    general dtype mapping.
    """
    dtype = np.dtype(dtype)
    return np.dtype(np.float32) if dtype in (np.dtype(np.float32),
                                             np.dtype(np.complex64)) else np.dtype(np.float64)


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


class RecordingTransforms:
    """Proxy over ``scipy.fft`` that records the plan every call needs.

    Substituted for the ``npfft`` module attribute of the module under
    measurement for the duration of one ``demodblock`` call.  Each call is
    reduced to the ``(kind, length, precision)`` triple that identifies the
    cached plan it uses, so calls sharing a plan are counted together and the
    resident cost is charged once.

    Thread-safety: none.  It swaps a module attribute, so only one may be
    installed at a time and nothing else may call the module concurrently.
    """

    def __init__(self, wrapped):
        self._wrapped = wrapped
        #: (kind, length, precision name) -> calls in the recorded block
        self.plans = {}

    def _record(self, kind, length, dtype):
        key = (kind, int(length), np.dtype(real_precision(dtype)).name)
        self.plans[key] = self.plans.get(key, 0) + 1

    @staticmethod
    def _length(array, n, axis, inverse_real):
        """The real-side length the plan is built for."""
        if n is not None:
            return n
        shape = np.asarray(array).shape
        extent = shape[axis] if shape else 1
        return 2 * (extent - 1) if inverse_real else extent

    def fft(self, x, n=None, axis=-1, **kwargs):
        self._record("complex", self._length(x, n, axis, False), np.asarray(x).dtype)
        return self._wrapped.fft(x, n, axis, **kwargs)

    def ifft(self, x, n=None, axis=-1, **kwargs):
        self._record("complex", self._length(x, n, axis, False), np.asarray(x).dtype)
        return self._wrapped.ifft(x, n, axis, **kwargs)

    def rfft(self, x, n=None, axis=-1, **kwargs):
        self._record("real", self._length(x, n, axis, False), np.asarray(x).dtype)
        return self._wrapped.rfft(x, n, axis, **kwargs)

    def irfft(self, x, n=None, axis=-1, **kwargs):
        self._record("real", self._length(x, n, axis, True), np.asarray(x).dtype)
        return self._wrapped.irfft(x, n, axis, **kwargs)

    def __getattr__(self, attr):
        # Anything the block does not use is passed through unrecorded.
        return getattr(self._wrapped, attr)


def per_block_transforms(rf, module=None):
    """Plans one ``demodblock`` call needs: [(kind, length, precision, bytes, calls)].

    `module` is the module whose ``npfft`` attribute is substituted, and is
    the seam a unit test injects through; it defaults to the module
    ``RFDecode`` itself calls into.  Distinct plans are reported once each,
    with the number of calls that hit them, because the resident cost is the
    plan and not the call.
    """
    if module is None:
        module = rfdecode_module

    data = synthetic_block(rf)
    if hasattr(rf, "mtf_response"):
        rf.mtf_response(BLOCK_MTF_LEVEL)

    original_npfft = module.npfft
    original_carrier_test = getattr(rf, "pal_audio_carriers_present", None)
    carrier_test_was_instance_attr = "pal_audio_carriers_present" in vars(rf)

    recorder = RecordingTransforms(original_npfft)
    module.npfft = recorder
    if original_carrier_test is not None:
        rf.pal_audio_carriers_present = lambda _fft: True

    try:
        rf.demodblock(data=data, mtf_level=BLOCK_MTF_LEVEL, cut=True, raw_mtf=True)
    finally:
        module.npfft = original_npfft
        if original_carrier_test is not None:
            if carrier_test_was_instance_attr:
                rf.pal_audio_carriers_present = original_carrier_test
            else:
                del rf.pal_audio_carriers_present

    rows = [
        (kind, length, precision, plan_table_bytes(length, precision, kind), calls)
        for (kind, length, precision), calls in recorder.plans.items()
    ]
    rows.sort(key=lambda row: -row[3])
    return rows


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
    held = getattr(rf, "_mtf_response_cache", None)
    if held is not None:
        # Held outside Filters: Filters["MTF"] raised to the current level,
        # which demodblock reads per block instead of recomputing (see
        # RFDecode.mtf_response).  Resident for as long as the level holds.
        response = held[1]
        seen.add(id(response))
        rows.append(
            ("MTF**level (held)", tuple(response.shape), str(response.dtype),
             int(response.nbytes))
        )
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

    # A decode runs at a settled mtf_level for a whole field at a time, so the
    # steady-state block reads the held MTF response, not Filters["MTF"] (which
    # is only touched when the level moves).  Prime it so the recorded block is
    # the steady-state one.
    if hasattr(rf, "mtf_response"):
        rf.mtf_response(BLOCK_MTF_LEVEL)

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
        rf.demodblock(data=data, mtf_level=BLOCK_MTF_LEVEL, cut=True, raw_mtf=True)
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
    held = getattr(rf, "_mtf_response_cache", None)
    if held is not None and id(held[1]) not in seen:
        rows.append(("MTF**level (held)", int(held[1].nbytes), 1))
    rows.sort(key=lambda row: -row[1])
    return rows


def block_scratch(rf):
    """The per-thread working buffers demodblock reuses: [(name, nbytes)].

    These used to be per-block allocations and are counted in
    ``per_block_peak_bytes`` no longer, because they are allocated before the
    measured call.  They are read and written on every block all the same, so
    they belong in the hot set, and the honest way to report the change is to
    show what moved rather than to let it fall off the total.
    """
    scratch = getattr(rf, "_scratch_store", None)
    scratch = getattr(scratch, "scratch", None) if scratch is not None else None
    if scratch is None:
        return []
    rows = []
    for name, value in sorted(vars(scratch).items()):
        if isinstance(value, np.ndarray) and value.size:
            rows.append((name, int(value.nbytes)))
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

    # Prime the held MTF response so the resident report counts it: a decode
    # is at a non-zero level from its first block onwards.
    if hasattr(rf, "mtf_response"):
        rf.mtf_response(BLOCK_MTF_LEVEL)

    resident = resident_filters(rf)
    resident_total = sum(row[3] for row in resident)
    lut = np.asarray(rf.downscale_sinc_lut)
    block = per_block_reads(rf)
    block_total = sum(row[1] for row in block)
    plans = per_block_transforms(rf)
    plan_total = sum(row[3] for row in plans)
    temporaries = per_block_peak_bytes(rf)
    scratch = block_scratch(rf)
    scratch_total = sum(row[1] for row in scratch)
    hot = block_total + int(lut.nbytes) + temporaries + scratch_total + plan_total

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
    print("  %-42s %32.2f MiB" % ("filter bytes read per block", block_total / MIB))
    print("  %-42s %32.2f MiB" % ("peak block temporaries", temporaries / MIB))
    print("-- block scratch (held per demodulating thread) --")
    for name, nbytes in scratch:
        print("  %-26s %9.1f KiB" % (name, nbytes / 1024.0))
    print("  %-42s %32.2f MiB" % ("scratch held per thread", scratch_total / MIB))
    print("-- transform plan tables (pocketfft, per process) --")
    for kind, length, precision, nbytes, calls in plans:
        print("  %-9s %-9s %-9d %11.1f KiB   x%d calls"
              % (kind, precision, length, nbytes / 1024.0, calls))
    print("  %-42s %32.2f MiB" % ("plan tables held", plan_total / MIB))
    print("-- totals --")
    print("  %-42s %32.2f MiB"
          % ("resident, all filters + LUT", (resident_total + lut.nbytes) / MIB))
    print("  %-52s %22.2f MiB"
          % ("hot per block (read + LUT + temps + scratch + plans)", hot / MIB))
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
            "block_scratch_bytes": int(scratch_total),
            "block_scratch": [{"name": n, "bytes": b} for n, b in scratch],
            "transform_plan_bytes": int(plan_total),
            "transform_plans": [
                {"kind": k, "length": n, "precision": p, "bytes": b, "calls": c}
                for k, n, p, b, c in plans
            ],
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
