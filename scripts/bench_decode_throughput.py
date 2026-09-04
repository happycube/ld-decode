#!/usr/bin/env python3
"""Whole-decode throughput and resident-memory harness.

Runs one measurement *cell* -- a (system, mode, threads, seek, length, capture)
tuple -- a stated number of times and writes one JSON row per repeat.  A cell may
run several identical decoders concurrently (``--concurrency``), which is how the
"N independent serial decoders" arm is measured; process *k* decodes the span
starting at ``seek + k * length`` so the arms do not share page cache.

Each row carries, for the repeat it describes:

* ``postsetup_fps_each`` -- every decoder's own "N frames (F FPS post-setup)"
  line, which excludes filter construction and JIT warm-up, and is therefore the
  figure to compare across cells;
* ``aggregate_fps`` -- frames committed by all decoders divided by wall time,
  which does include start-up and is the right figure for a batch of work;
* ``peak_rss_sum_mb`` / ``peak_rss_single_mb`` -- peak resident set over the whole
  process tree (worker processes included), sampled at ``--rss-interval`` seconds.

The harness shells out to ``python -m lddecode.main`` with an argument list
(``shell=False``) and imports nothing from ``lddecode``; it measures the decoder
as shipped and never alters it.

Reference box for the figures recorded in ``plans/decode-working-set-plan.md``:
AMD Ryzen 7 5800X (8 physical cores, 16 SMT threads, 32 MiB shared L3), 64 GiB
dual-channel DDR4, captures on NFS.  ``box`` in each row records the box actually
used, so rows from different machines stay distinguishable.

Reference captures and spans for that plan's baseline:

* PAL, ``Domesday_DD86-DS2_NationalA_PP_20191014_CAV_PAL_00001-54000.ldf``,
  ``-s 5000 -l 1000``;
* NTSC, ``Bambi_CLV_NTSC_side1_JapanImport_LDG_2020-01-22_20-25-19.ldf``,
  ``-s 5000 -l 1000``.

Decoder output is written under ``--work-dir`` and deleted after each repeat
unless ``--keep-output`` is given; a 1000-frame PAL cell writes about 1.4 GB per
decoder, so a concurrency-8 cell needs ~12 GB free.

Usage:
    python3 scripts/bench_decode_throughput.py --capture CAPTURE.ldf \
        --system pal --mode cvbs --threads 6 --seek 5000 --length 1000 \
        --repeats 3 --out results.jsonl
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

# The decoder prints exactly one of these when it finishes; the post-setup rate
# excludes filter construction and numba compilation.
POST_SETUP_RE = re.compile(r"decode (\d+) frames \(([0-9.]+) FPS post-setup\)")

PAGE_KIB = os.sysconf("SC_PAGE_SIZE") // 1024


def decoder_argv(python, capture, output, system, mode, threads, seek, length):
    """Build the argv for one decoder run.

    ``system`` is "pal" or "ntsc", ``mode`` is "cvbs" or "tbc".  Returned as a
    list for ``subprocess`` with ``shell=False``; no element is ever interpolated
    into a shell string.
    """
    if system not in ("pal", "ntsc"):
        raise ValueError("system must be 'pal' or 'ntsc', not %r" % (system,))
    if mode not in ("cvbs", "tbc"):
        raise ValueError("mode must be 'cvbs' or 'tbc', not %r" % (mode,))
    argv = [python, "-m", "lddecode.main", "--" + system, "--" + mode]
    argv += ["-t", str(int(threads)), "-s", str(int(seek)), "-l", str(int(length))]
    argv += [str(capture), str(output)]
    return argv


def parse_post_setup(text):
    """Return (frames, fps) from a decoder log, or None if it did not finish."""
    match = POST_SETUP_RE.search(text)
    if match is None:
        return None
    return int(match.group(1)), float(match.group(2))


def process_children():
    """Map parent pid -> list of child pids, from a single sweep of /proc."""
    children = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open("/proc/%s/stat" % entry) as handle:
                stat = handle.read()
            # The comm field is parenthesised and may itself contain spaces, so
            # split after its closing parenthesis: ppid is then field 2.
            ppid = int(stat[stat.rindex(")") + 2:].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        children.setdefault(ppid, []).append(int(entry))
    return children


def tree_rss_kib(roots):
    """Summed and largest-single resident set (KiB) over roots and descendants.

    Races with process exit are expected and ignored: a pid that disappears
    between the /proc sweep and the statm read contributes nothing.
    """
    children = process_children()
    pids = set()
    stack = list(roots)
    while stack:
        pid = stack.pop()
        if pid in pids:
            continue
        pids.add(pid)
        stack.extend(children.get(pid, ()))
    total = 0
    largest = 0
    for pid in pids:
        try:
            with open("/proc/%d/statm" % pid) as handle:
                rss_pages = int(handle.read().split()[1])
        except (OSError, ValueError, IndexError):
            continue
        kib = rss_pages * PAGE_KIB
        total += kib
        largest = max(largest, kib)
    return total, largest


def describe_box():
    """Machine identity, so rows measured elsewhere stay distinguishable."""
    box = {
        "logical_cpus": os.cpu_count(),
        "physical_cores": None,
        "model_name": None,
        "l3_bytes": None,
        "mem_total_kib": None,
    }
    try:
        with open("/proc/cpuinfo") as handle:
            cores = set()
            for line in handle:
                if line.startswith("model name") and box["model_name"] is None:
                    box["model_name"] = line.split(":", 1)[1].strip()
                elif line.startswith("core id"):
                    cores.add(line.split(":", 1)[1].strip())
            if cores:
                box["physical_cores"] = len(cores)
    except OSError:
        pass
    for index in range(4):
        path = "/sys/devices/system/cpu/cpu0/cache/index%d" % index
        try:
            with open(os.path.join(path, "level")) as handle:
                level = handle.read().strip()
            with open(os.path.join(path, "size")) as handle:
                size = handle.read().strip()
        except OSError:
            continue
        if level == "3" and size.endswith("K"):
            box["l3_bytes"] = int(size[:-1]) * 1024
    try:
        with open("/proc/meminfo") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    box["mem_total_kib"] = int(line.split()[1])
                    break
    except OSError:
        pass
    return box


def run_repeat(args, work_dir, repeat_index):
    """Run one repeat of the cell: ``--concurrency`` decoders, start to finish."""
    os.makedirs(work_dir, exist_ok=True)
    procs = []
    logs = []
    log_paths = []
    start = time.time()
    for k in range(args.concurrency):
        output = os.path.join(work_dir, "decode_%02d" % k)
        argv = decoder_argv(
            args.python,
            args.capture,
            output,
            args.system,
            args.mode,
            args.threads,
            args.seek + k * args.length,
            args.length,
        )
        log_path = os.path.join(work_dir, "decode_%02d.log" % k)
        log_paths.append(log_path)
        handle = open(log_path, "w")
        logs.append(handle)
        procs.append(subprocess.Popen(argv, stdout=handle, stderr=subprocess.STDOUT))

    peak_sum = 0
    peak_single = 0
    stop = threading.Event()

    def sample_rss():
        nonlocal peak_sum, peak_single
        roots = [proc.pid for proc in procs]
        while not stop.is_set():
            total, largest = tree_rss_kib(roots)
            peak_sum = max(peak_sum, total)
            peak_single = max(peak_single, largest)
            stop.wait(args.rss_interval)

    sampler = threading.Thread(target=sample_rss, daemon=True)
    sampler.start()
    return_codes = [proc.wait() for proc in procs]
    stop.set()
    sampler.join(timeout=2.0)
    wall = time.time() - start
    for handle in logs:
        handle.close()

    frames = 0
    fps_each = []
    for log_path in log_paths:
        with open(log_path, errors="replace") as handle:
            parsed = parse_post_setup(handle.read())
        if parsed is None:
            continue
        frames += parsed[0]
        fps_each.append(parsed[1])

    row = {
        "label": args.label,
        "repeat": repeat_index,
        "system": args.system,
        "mode": args.mode,
        "threads": args.threads,
        "concurrency": args.concurrency,
        "seek": args.seek,
        "length": args.length,
        "capture": args.capture,
        "return_codes": return_codes,
        "frames_total": frames,
        "wall_s": round(wall, 2),
        "aggregate_fps": round(frames / wall, 3) if wall > 0 else 0.0,
        "postsetup_fps_each": [round(value, 3) for value in fps_each],
        "postsetup_fps_sum": round(sum(fps_each), 3),
        "peak_rss_sum_mb": round(peak_sum / 1024.0, 1),
        "peak_rss_single_mb": round(peak_single / 1024.0, 1),
        "started": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(start)),
        "box": describe_box(),
    }
    if not args.keep_output:
        shutil.rmtree(work_dir, ignore_errors=True)
    return row


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--capture", required=True, help="path to the RF capture")
    parser.add_argument("--system", choices=["pal", "ntsc"], required=True)
    parser.add_argument("--mode", choices=["cvbs", "tbc"], default="cvbs")
    parser.add_argument("--threads", type=int, default=1, help="decoder -t value")
    parser.add_argument("--seek", type=int, default=5000, help="decoder -s value, frames")
    parser.add_argument("--length", type=int, default=1000, help="decoder -l value, frames")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="independent decoders to run at once; decoder k starts at seek + k * length",
    )
    parser.add_argument("--repeats", type=int, default=1, help="times to run the cell")
    parser.add_argument("--label", default=None, help="name for this cell in the output rows")
    parser.add_argument("--out", default=None, help="append JSON rows (one per line) here")
    parser.add_argument(
        "--work-dir",
        default=None,
        help="where decoder output is written (default: a temporary directory)",
    )
    parser.add_argument(
        "--keep-output", action="store_true", help="do not delete decoder output afterwards"
    )
    parser.add_argument(
        "--rss-interval", type=float, default=0.5, help="seconds between RSS samples"
    )
    parser.add_argument(
        "--python", default=sys.executable, help="interpreter used to run lddecode.main"
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.concurrency < 1 or args.repeats < 1:
        raise SystemExit("--concurrency and --repeats must be at least 1")
    if args.label is None:
        args.label = "%s_%s_t%d_c%d" % (args.system, args.mode, args.threads, args.concurrency)
    base_dir = args.work_dir or os.path.join(
        os.environ.get("TMPDIR", "/tmp"), "bench_decode_throughput"
    )

    rows = []
    for repeat in range(args.repeats):
        work_dir = os.path.join(base_dir, "%s_r%d" % (args.label, repeat))
        row = run_repeat(args, work_dir, repeat)
        rows.append(row)
        print(json.dumps(row))
        sys.stdout.flush()
        if args.out:
            with open(args.out, "a") as handle:
                handle.write(json.dumps(row) + "\n")

    if args.repeats > 1:
        sums = [row["postsetup_fps_sum"] for row in rows]
        spread = (max(sums) - min(sums)) / max(sums) if max(sums) else 0.0
        print(
            "# %s: post-setup fps sum min %.3f max %.3f spread %.1f%%"
            % (args.label, min(sums), max(sums), spread * 100),
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
