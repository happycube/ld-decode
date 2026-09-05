#!/usr/bin/env python3
"""Report, stage by stage, what one field's decode streams and what it
costs in cache traffic.

`report_working_set.py` answers what one decoder keeps resident.  This
script answers the other half: of the ~1.3 GB an L2 miss counter says a
PAL frame moves, which named stage moves it.  Footprint predicts nothing
on this box (a 4 MiB table's removal cost throughput); the counters do,
so a change that claims a memory effect is expected to name the stage it
takes the fills out of and to state the figure before and after.

Method.  A serial decode (`-t 1`, no worker processes, everything on the
parent's threads) runs in this process with a set of named stages wrapped
by a counter-reading decorator.  Each wrapper reads a per-thread group of
PMU counters on entry and exit, so a stage is charged its *exclusive*
traffic: what it caused minus what the wrapped stages it called caused.
Nesting is per thread, so the output lane, the CVBS resample thread and
the FLAC reader are attributed separately from the decode thread.
Alongside the counters each wrapper sums the `nbytes` of the arrays
passed in and returned, which is the intended traffic - the difference
between that and the fills is what the cache did or did not absorb.

The events are read through `perf_event_open` directly rather than
`perf stat`, because a per-stage figure needs the counter read inside the
process at stage boundaries.  Their encodings are this box's (Zen 3,
family 19h) as reported by `perf stat -vv -e <name> -- true`; on another
CPU the raw configs are wrong and `--events` must be given.

Threads whose entry point is itself a wrapped stage (the output lane's
run loop, the FLAC reader loop, the CVBS field resample) report a root
row, so the unattributed remainder within those threads is visible as the
root's own exclusive figure.  For the whole-process cross-check, run the
same decode under `perf stat` (the command is printed at the end) and
compare the totals: the stage table is expected to account for most, not
all, of it - the interpreter, the allocator and unwrapped glue are real
traffic that belongs to no stage.

Usage:
    python3 scripts/report_decode_traffic.py [options] input.ldf outbase
"""

import argparse
import ctypes
import importlib
import json
import os
import sys
import threading
import time
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MIB = float(2 ** 20)
LINE = 64  # bytes per cache line fill

# --- the counters --------------------------------------------------------

_SYS_perf_event_open = 298  # x86_64
PERF_TYPE_HARDWARE = 0
PERF_FORMAT_GROUP = 1 << 3
_ATTR_DISABLED = 1 << 0
_ATTR_EXCLUDE_KERNEL = 1 << 5
_ATTR_EXCLUDE_HV = 1 << 6

#: (label, perf type, config).  "core" resolves to this box's core PMU id.
#: Configs from `perf stat -vv`: l2_cache_misses_from_dc_misses 0x864,
#: ls_any_fills_from_sys.int_cache 0x244 (a fill from another cache, i.e.
#: L3 or a peer L2), ls_any_fills_from_sys.mem_io_local 0x844 (a fill that
#: came from DRAM).  Five events fit Zen 3's six programmable counters, so
#: the group is never multiplexed.
DEFAULT_EVENTS = (
    ("cycles", PERF_TYPE_HARDWARE, 0x0),
    ("instructions", PERF_TYPE_HARDWARE, 0x1),
    ("l2_miss", "core", 0x864),
    ("l3_fill", "core", 0x244),
    ("dram_fill", "core", 0x844),
)


class PerfEventAttr(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("size", ctypes.c_uint32),
        ("config", ctypes.c_uint64),
        ("sample_period", ctypes.c_uint64),
        ("sample_type", ctypes.c_uint64),
        ("read_format", ctypes.c_uint64),
        ("flags", ctypes.c_uint64),
        ("wakeup_events", ctypes.c_uint32),
        ("bp_type", ctypes.c_uint32),
        ("config1", ctypes.c_uint64),
        ("config2", ctypes.c_uint64),
    ]


def _core_pmu_type():
    with open("/sys/bus/event_source/devices/cpu/type") as fh:
        return int(fh.read().strip())


class ThreadCounters:
    """One perf event group, counting the calling thread only.

    The group is read in one syscall (PERF_FORMAT_GROUP), which is what
    makes a per-stage read cheap enough to put on every call.
    """

    def __init__(self, libc, events, pmu_type):
        self.libc = libc
        self.n = len(events)
        self.fds = []
        leader = -1
        for name, etype, config in events:
            attr = PerfEventAttr()
            attr.size = ctypes.sizeof(PerfEventAttr)
            attr.type = pmu_type if etype == "core" else etype
            attr.config = config
            attr.read_format = PERF_FORMAT_GROUP
            attr.flags = _ATTR_EXCLUDE_KERNEL | _ATTR_EXCLUDE_HV
            if leader == -1:
                attr.flags |= _ATTR_DISABLED
            fd = libc.syscall(_SYS_perf_event_open, ctypes.byref(attr),
                              0, -1, leader, 0)
            if fd < 0:
                err = ctypes.get_errno()
                raise OSError(err, "perf_event_open(%s) failed: %s"
                              % (name, os.strerror(err)))
            self.fds.append(fd)
            if leader == -1:
                leader = fd
        self.leader = leader
        # PERF_EVENT_IOC_ENABLE with PERF_IOC_FLAG_GROUP
        if libc.ioctl(leader, 0x2400, 1) < 0:
            raise OSError(ctypes.get_errno(), "PERF_EVENT_IOC_ENABLE failed")
        self.buf = (ctypes.c_uint64 * (1 + self.n))()
        self.size = ctypes.sizeof(self.buf)

    def read(self):
        if self.libc.read(self.leader, self.buf, self.size) != self.size:
            raise OSError("short read from the counter group")
        return self.buf[1:]

    def close(self):
        for fd in self.fds:
            os.close(fd)
        self.fds = []


# --- the instrument ------------------------------------------------------

class Tally:
    __slots__ = ("calls", "wall_ns", "excl", "incl", "bytes_in", "bytes_out")

    def __init__(self, n):
        self.calls = 0
        self.wall_ns = 0
        self.excl = [0] * n
        self.incl = [0] * n
        self.bytes_in = 0
        self.bytes_out = 0


def _array_bytes(obj, depth=0):
    """Bytes of the arrays in one argument (one level into containers)."""
    if isinstance(obj, np.ndarray):
        return obj.nbytes
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return len(obj)
    if depth < 2 and isinstance(obj, (tuple, list)):
        return sum(_array_bytes(o, depth + 1) for o in obj)
    if depth < 2 and isinstance(obj, dict):
        return sum(_array_bytes(o, depth + 1) for o in obj.values())
    return 0


class Instrument:
    def __init__(self, events, warmup_fields=0):
        self.events = events
        self.warmup_fields = warmup_fields
        self.fields = 0
        self.counting_from = time.time()
        self.n = len(events)
        self.libc = ctypes.CDLL("libc.so.6", use_errno=True)
        self.libc.syscall.restype = ctypes.c_int
        self.pmu_type = _core_pmu_type()
        self._local = threading.local()
        self._lock = threading.Lock()
        self.tallies = defaultdict(lambda: Tally(self.n))
        self.patched = []
        # One entry per thread that ever entered a stage: its counter
        # group and the reading at the start of the counting window.  The
        # difference at the end is that thread's true total, which is the
        # denominator the stage table is measured against - a thread's
        # roots cannot serve as one, since they are entered before the
        # warm-up discard and would carry it.
        self.threads = []

    def _state(self):
        st = getattr(self._local, "st", None)
        if st is None:
            counters = ThreadCounters(self.libc, self.events, self.pmu_type)
            name = threading.current_thread().name
            with self._lock:
                seen = sum(1 for e in self.threads if e[0].startswith(name))
                if seen:
                    name = "%s#%d" % (name, seen + 1)
                self.threads.append([name, counters, counters.read()])
            st = self._local.st = (counters, [], name)
        return st

    def thread_totals(self):
        """Each thread's counters over the counting window."""
        out = {}
        for name, counters, base in self.threads:
            now = counters.read()
            out[name] = [now[i] - base[i] for i in range(self.n)]
        return out

    def _record(self, thread, label, wall, incl, excl, nin, nout):
        with self._lock:
            if label == "writeout":
                self.fields += 1
                if self.fields == self.warmup_fields:
                    # Everything so far is warm-up: filter construction,
                    # numba compilation, the first FFT plans and the AGC's
                    # re-decodes.  None of it is per-frame traffic, and at
                    # ten seconds it would dominate a short run.
                    self.tallies.clear()
                    self.counting_from = time.time()
                    for entry in self.threads:
                        entry[2] = entry[1].read()
            t = self.tallies[(thread, label)]
            t.calls += 1
            t.wall_ns += wall
            t.bytes_in += nin
            t.bytes_out += nout
            for i in range(self.n):
                t.incl[i] += incl[i]
                t.excl[i] += excl[i]

    def wrap(self, label, fn):
        n = self.n

        def wrapper(*args, **kwargs):
            counters, stack, thread = self._state()
            nin = _array_bytes(args) + _array_bytes(kwargs)
            child = [0] * n
            stack.append(child)
            c0 = counters.read()
            t0 = time.perf_counter_ns()
            result = None
            try:
                result = fn(*args, **kwargs)
            finally:
                wall = time.perf_counter_ns() - t0
                c1 = counters.read()
                stack.pop()
                incl = [c1[i] - c0[i] for i in range(n)]
                excl = [incl[i] - child[i] for i in range(n)]
                if stack:
                    parent = stack[-1]
                    for i in range(n):
                        parent[i] += incl[i]
                self._record(thread, label, wall, incl, excl,
                             nin, _array_bytes(result))
            return result

        wrapper.__name__ = getattr(fn, "__name__", label)
        wrapper.__wrapped_stage__ = label
        return wrapper

    def install(self, stages):
        for label, paths in stages:
            for path in paths:
                owner, name, target = _resolve(path)
                setattr(owner, name, self.wrap(label, target))
                self.patched.append((owner, name, target))

    def remove(self):
        for owner, name, target in reversed(self.patched):
            setattr(owner, name, target)
        self.patched = []


def _resolve(path):
    """Split "a.b.C.meth" into the owner object, the attribute and its value."""
    parts = path.split(".")
    module = None
    for i in range(len(parts) - 1, 0, -1):
        try:
            module = importlib.import_module(".".join(parts[:i]))
        except ImportError:
            continue
        rest = parts[i:]
        break
    if module is None:
        raise ValueError("no importable module prefix in %r" % path)
    owner = module
    for attr in rest[:-1]:
        owner = getattr(owner, attr)
    name = rest[-1]
    if not hasattr(owner, name):
        raise ValueError("%r has no attribute %r" % (owner, name))
    return owner, name, getattr(owner, name)


# --- the stages ----------------------------------------------------------
#
# Rules for this table:
#
# * A numba kernel is patched only where it is *used* (lddecode.field...),
#   never on lddecode.dsp: a jitted function resolves its globals from its
#   own module when it compiles, and a Python wrapper sitting there would
#   break any kernel that compiles after this script starts.
# * Nothing called per line goes in.  The wrapper costs a few microseconds;
#   a stage entered once per field or per block can carry that, a stage
#   entered 300 times per field cannot.
# * Where a subclass overrides a wrapped method and calls super(), both are
#   listed: the exclusive figures then split correctly between them.

STAGES = [
    # transforms: every scipy.fft call in the process, wherever it is made
    ("fft.rfft", ["scipy.fft.rfft"]),
    ("fft.irfft", ["scipy.fft.irfft"]),
    ("fft.fft", ["scipy.fft.fft"]),
    ("fft.ifft", ["scipy.fft.ifft"]),

    # the block demodulator
    ("demodblock", ["lddecode.rfdecode.RFDecode.demodblock"]),
    ("unwrap_hilbert", ["lddecode.rfdecode.unwrap_hilbert"]),
    ("apply_v4300d", ["lddecode.rfdecode.RFDecode.apply_v4300d"]),

    # field assembly
    ("concatenate_blocks", ["lddecode.decoder.concatenate_blocks",
                            "lddecode.parallel.concatenate_blocks"]),
    ("Field.process", ["lddecode.field.Field.process"]),
    ("FieldPAL.process", ["lddecode.field.FieldPAL.process"]),
    ("FieldNTSC.process", ["lddecode.field.FieldNTSC.process"]),
    ("compute_linelocs", ["lddecode.field.Field.compute_linelocs"]),
    ("compute_linelocs_kernel", ["lddecode.field.compute_linelocs_kernel"]),
    ("refinepulses", ["lddecode.field.Field.refinepulses"]),
    ("refine_linelocs_hsync", ["lddecode.field.Field.refine_linelocs_hsync"]),
    ("refine_hsync_zcs", ["lddecode.field.refine_hsync_zcs"]),
    ("refine_linelocs_pilot", ["lddecode.field.FieldPAL.refine_linelocs_pilot"]),
    ("refine_pilot_zcs", ["lddecode.field.refine_pilot_zcs"]),
    ("refine_linelocs_burst", ["lddecode.field.FieldNTSC.refine_linelocs_burst"]),

    # the TBC picture and its resample
    ("computewow_scaled", ["lddecode.field.Field.computewow_scaled"]),
    ("Field.downscale", ["lddecode.field.Field.downscale"]),
    ("FieldNTSC.downscale", ["lddecode.field.FieldNTSC.downscale"]),
    ("scale_field", ["lddecode.field.scale_field"]),
    ("hz_to_output_array", ["lddecode.field.hz_to_output_array"]),

    # the CVBS lattice resample
    ("downscale_cvbs", ["lddecode.field.FieldPAL.downscale_cvbs"]),
    ("scale_positions", ["lddecode.field.scale_positions"]),

    # the chroma differential gain correction
    ("chroma_dg", ["lddecode.field._correct_chroma_vs_luma"]),
    ("chroma_dg (tbc)", ["lddecode.field.apply_chroma_dg_correction_output"]),

    # dropouts, audio, metrics
    ("dropout_detect_demod", ["lddecode.field.Field.dropout_detect_demod"]),
    ("dropout_detect", ["lddecode.field.Field.dropout_detect"]),
    ("downscale_audio", ["lddecode.field.downscale_audio"]),
    ("measure_vits_multiburst", ["lddecode.decoder.measure_vits_multiburst"]),
    ("measure_vits_dg_staircase", ["lddecode.decoder.measure_vits_dg_staircase"]),
    ("measure_its_2t_ratio", ["lddecode.decoder.measure_its_2t_ratio"]),

    # the decode driver and the output stage
    ("decodefield", ["lddecode.decoder.LDdecode.decodefield"]),
    ("decode_stage2", ["lddecode.decoder.LDdecode.decode_stage2"]),
    ("buildmetadata", ["lddecode.decoder.LDdecode.buildmetadata"]),
    ("writeout", ["lddecode.decoder.LDdecode.writeout"]),
    ("_write_field", ["lddecode.decoder.LDdecode._write_field"]),
    ("AC3demodulate", ["lddecode.decoder.LDdecode.AC3demodulate"]),
    ("efm_demod.process", ["lddecode.efm_demod.EFMTimingDemod.process"]),

    # the CVBS writer
    ("cvbs.push_field", ["lddecode.cvbs.CVBSWriter.push_field"]),
    ("cvbs._emit_frame", ["lddecode.cvbs.CVBSWriter._emit_frame"]),
    ("cvbs._to_spec_levels", ["lddecode.cvbs.CVBSWriter._to_spec_levels"]),
    ("cvbs.encode_cvbs_frame", ["lddecode.cvbs.encode_cvbs_frame"]),
    ("cvbs._write_frame", ["lddecode.cvbs.CVBSWriter._write_frame"]),
    ("cvbs._pal_phase_error", ["lddecode.cvbs.CVBSWriter._pal_phase_error"]),

    # thread roots: everything one auxiliary thread does is inside these
    ("[root] main", ["lddecode.main.main"]),
    ("[root] output lane", ["lddecode.parallel.OrderedOutputLane._run"]),
    ("[root] flac reader", ["lddecode.fileio.LoadLDF._reader_loop"]),
]

ROOT_PREFIX = "[root] "


def _import_targets():
    for name in ("lddecode.main", "lddecode.decoder", "lddecode.field",
                 "lddecode.rfdecode", "lddecode.dsp", "lddecode.cvbs",
                 "lddecode.efm_demod", "lddecode.fileio", "lddecode.parallel",
                 "lddecode.audio", "scipy.fft"):
        importlib.import_module(name)


# --- the run -------------------------------------------------------------

def run_decode(argv):
    import lddecode.main as ldmain

    started = time.time()
    try:
        ldmain.main(argv)
    except SystemExit as exc:
        if exc.code not in (0, None):
            raise
    return time.time() - started


def report(inst, totals, frames, elapsed, args):
    names = [e[0] for e in inst.events]
    rows = []
    for (thread, label), t in inst.tallies.items():
        rows.append({
            "thread": thread,
            "stage": label,
            "calls_per_frame": t.calls / frames,
            "ms_per_frame": t.wall_ns / 1e6 / frames,
            "bytes_in_per_frame": t.bytes_in / frames,
            "bytes_out_per_frame": t.bytes_out / frames,
            "exclusive": {n: v / frames for n, v in zip(names, t.excl)},
            "inclusive": {n: v / frames for n, v in zip(names, t.incl)},
        })
    rows.sort(key=lambda r: -r["exclusive"]["l2_miss"])
    staged = [r for r in rows if not r["stage"].startswith(ROOT_PREFIX)]

    print()
    print("%d frames in %.1f s (%.2f fps, instrumented, warm-up discarded)" %
          (frames, elapsed, frames / elapsed))

    # --- what each thread cost, and how much of it has a stage name ---
    per_thread = {}
    for r in staged:
        acc = per_thread.setdefault(r["thread"], {n: 0.0 for n in names})
        for n in names:
            acc[n] += r["exclusive"][n]
    print()
    head = ("%-16s %10s %10s %10s %9s %9s"
            % ("thread", "Gcycles", "L2 miss", "L3 fill", "DRAM MiB", "named"))
    print(head)
    print("-" * len(head))
    total = {n: 0.0 for n in names}
    attributed = {n: 0.0 for n in names}
    for name, tot in sorted(totals.items(),
                            key=lambda kv: -kv[1][names.index("l2_miss")]):
        per = [v / frames for v in tot]
        got = per_thread.get(name, {n: 0.0 for n in names})
        for i, n in enumerate(names):
            total[n] += per[i]
            attributed[n] += got[n]
        share = (100.0 * got["l2_miss"] / per[names.index("l2_miss")]
                 if per[names.index("l2_miss")] else 0.0)
        print("%-16s %10.3f %10.3g %10.3g %9.1f %8.0f%%"
              % (name[:16], per[names.index("cycles")] / 1e9,
                 per[names.index("l2_miss")], per[names.index("l3_fill")],
                 per[names.index("dram_fill")] * LINE / MIB, share))
    print("-" * len(head))
    print("%-16s %10.3f %10.3g %10.3g %9.1f %8.0f%%"
          % ("whole process", total["cycles"] / 1e9, total["l2_miss"],
             total["l3_fill"], total["dram_fill"] * LINE / MIB,
             100.0 * attributed["l2_miss"] / total["l2_miss"]
             if total["l2_miss"] else 0.0))

    # --- and where inside each thread it went ---
    print()
    print("per frame, exclusive of the wrapped stages each one calls:")
    print()
    head = ("%-26s %-14s %7s %8s %10s %10s %10s %9s %9s"
            % ("stage", "thread", "calls", "ms", "Gcycles",
               "L2 miss", "L3 fill", "DRAM MiB", "in+out MiB"))
    print(head)
    print("-" * len(head))
    for r in staged:
        e = r["exclusive"]
        if e["l2_miss"] < 1000 and r["ms_per_frame"] < 0.5:
            continue
        print("%-26s %-14s %7.2f %8.2f %10.3f %10.3g %10.3g %9.1f %9.1f"
              % (r["stage"], r["thread"][:14], r["calls_per_frame"],
                 r["ms_per_frame"], e["cycles"] / 1e9, e["l2_miss"],
                 e["l3_fill"], e["dram_fill"] * LINE / MIB,
                 (r["bytes_in_per_frame"] + r["bytes_out_per_frame"]) / MIB))
    print("-" * len(head))
    print("%-26s %-14s %7s %8s %10.3f %10.3g %10.3g %9.1f"
          % ("named stages", "", "", "", attributed["cycles"] / 1e9,
             attributed["l2_miss"], attributed["l3_fill"],
             attributed["dram_fill"] * LINE / MIB))
    print("%-26s %-14s %7s %8s %10.3f %10.3g %10.3g %9.1f"
          % ("unnamed (glue, alloc, ...)", "", "", "",
             (total["cycles"] - attributed["cycles"]) / 1e9,
             total["l2_miss"] - attributed["l2_miss"],
             total["l3_fill"] - attributed["l3_fill"],
             (total["dram_fill"] - attributed["dram_fill"]) * LINE / MIB))
    print()
    print("L2-miss traffic: %.2f GB/frame total, %.2f GB/frame named (%.0f%%)"
          % (total["l2_miss"] * LINE / 1e9, attributed["l2_miss"] * LINE / 1e9,
             100.0 * attributed["l2_miss"] / total["l2_miss"]
             if total["l2_miss"] else 0.0))
    print("DRAM fills: %.3g/frame total (%.0f MiB)"
          % (total["dram_fill"], total["dram_fill"] * LINE / MIB))
    print()
    print("whole-process cross-check (run separately, uninstrumented):")
    print("  perf stat -e cycles:u,instructions:u,"
          "l2_cache_misses_from_dc_misses:u,ls_any_fills_from_sys.int_cache:u,"
          "ls_any_fills_from_sys.mem_io_local:u -- \\")
    print("    %s -m lddecode.main %s" % (sys.executable, " ".join(args)))

    return {"per_stage": rows,
            "per_thread": {k: [v / frames for v in t]
                           for k, t in totals.items()},
            "events": names}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--system", choices=("pal", "ntsc"), default="pal")
    ap.add_argument("--output", choices=("cvbs", "tbc"), default="cvbs")
    ap.add_argument("-s", "--start", type=int, default=5000)
    ap.add_argument("-l", "--length", type=int, default=40)
    ap.add_argument("--decoder-arg", action="append", default=[],
                    help="extra argument passed to lddecode (repeatable)")
    ap.add_argument("--warmup", type=int, default=20,
                    help="fields to decode before the tallies are cleared "
                         "(default 20: filter build, numba compilation and "
                         "FFT planning are not per-frame traffic)")
    ap.add_argument("--json", help="write the per-stage rows here")
    ap.add_argument("infile")
    ap.add_argument("outbase")
    args = ap.parse_args()

    decoder_args = [
        "--%s" % args.system, "--%s" % args.output, "-t", "1",
        "-s", str(args.start), "-l", str(args.length),
        *args.decoder_arg, args.infile, args.outbase,
    ]

    _import_targets()
    inst = Instrument(DEFAULT_EVENTS, warmup_fields=args.warmup)
    inst.install(STAGES)
    try:
        run_decode(decoder_args)
        totals = inst.thread_totals()
    finally:
        inst.remove()
    elapsed = time.time() - inst.counting_from

    fields = sum(t.calls for (_, label), t in inst.tallies.items()
                 if label == "writeout")
    frames = max(fields / 2.0, 1.0)
    out = report(inst, totals, frames, elapsed, decoder_args)
    if args.json:
        out.update({"frames": frames, "elapsed": elapsed, "args": decoder_args})
        with open(args.json, "w") as fh:
            json.dump(out, fh, indent=1)
        print("wrote %s" % args.json)


if __name__ == "__main__":
    main()
