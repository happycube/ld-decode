#!/usr/bin/env python3
"""Benchmark harness for RFDecode demodulation pipeline.

Creates a synthetic RF signal (using the same approach as computedelays)
and benchmarks demodblock_cpu, which is the core demodulation function
called by the worker threads in DemodCache.

Usage:
    python3 tools/bench_rf.py [--blocks N] [--system NTSC|PAL] [--audio] [--efm]
"""

import argparse
import time
import numpy as np
import numpy.fft as npfft
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lddecode.core import RFDecode
from lddecode.utils import genwave


def make_fake_signal(rf):
    """Generate a synthetic RF signal, similar to computedelays().

    Returns a blocklen-sized array that mimics real laserdisc RF data.
    """
    fakeoutput = np.zeros(rf.blocklen, dtype=np.double)
    fakeoutput[:] = rf.iretohz(0)  # black level

    synclen_full = int(4.7 * rf.freq)
    line_period_samples = int(rf.SysParams["line_period"] * rf.freq)

    # Generate multiple lines of fake video with sync, burst, and content
    pos = 500
    while pos + line_period_samples < rf.blocklen - 500:
        # Sync pulse
        fakeoutput[pos:pos + synclen_full] = rf.iretohz(rf.DecoderParams["vsync_ire"])

        # Back porch + color burst
        porch_start = pos + synclen_full + int(0.6 * rf.freq)
        burst_end = porch_start + int(2.4 * rf.freq)
        if burst_end < rf.blocklen:
            rate = np.full(burst_end - porch_start, rf.SysParams["fsc_mhz"], dtype=np.double)
            fakeoutput[porch_start:burst_end] += (
                genwave(rate, rf.freq / 2) * rf.DecoderParams["hz_ire"] * 20
            )

        # Active video area: ramp from black to white
        active_start = pos + int(9.5 * rf.freq)
        active_end = pos + line_period_samples
        if active_end < rf.blocklen:
            n_active = active_end - active_start
            ramp = np.linspace(0, 100, n_active)
            fakeoutput[active_start:active_end] = rf.iretohz(0) + ramp * rf.DecoderParams["hz_ire"]

        pos += line_period_samples

    # FM-modulate the baseband signal to produce RF
    fakeoutput_emp = npfft.ifft(
        npfft.fft(fakeoutput) * rf.Filters["Fvideo_lpf"] * rf.Filters["Femp"]
    ).real

    fakesignal = genwave(fakeoutput_emp, rf.freq_hz / 2)
    fakesignal *= 4096
    fakesignal += 8192

    return fakesignal


def bench_demodblock(rf, signal, n_blocks, label):
    """Benchmark demodblock_cpu on the given signal for n_blocks iterations."""

    # Warmup (includes JIT compilation for numba functions)
    _ = rf.demodblock(data=signal, mtf_level=0, cut=True)

    times = []
    for i in range(n_blocks):
        st = time.perf_counter()
        rv = rf.demodblock(data=signal, mtf_level=0, cut=True)
        elapsed = time.perf_counter() - st
        times.append(elapsed)

    times = np.array(times)
    total = times.sum()
    mean = times.mean()
    std = times.std()
    median = np.median(times)

    print(f"\n=== {label} ===")
    print(f"  Blocks:    {n_blocks}")
    print(f"  Block len: {rf.blocklen} samples ({rf.blocklen / rf.freq_hz * 1000:.1f} ms of signal)")
    print(f"  Total:     {total:.3f}s")
    print(f"  Mean:      {mean*1000:.2f} ms/block")
    print(f"  Median:    {median*1000:.2f} ms/block")
    print(f"  Std:       {std*1000:.2f} ms")
    print(f"  Min:       {min(times)*1000:.2f} ms")
    print(f"  Max:       {max(times)*1000:.2f} ms")

    # Estimate throughput
    samples_per_sec = rf.blocklen / mean
    fields_per_sec = samples_per_sec / (rf.linelen * 263)  # approx field size
    print(f"  Throughput: {samples_per_sec/1e6:.1f} Msamples/s ({fields_per_sec:.1f} fields/s)")

    return rv, times


def bench_substeps(rf, signal, n_blocks):
    """Benchmark individual steps within demodblock_cpu."""

    indata_fft = npfft.fft(signal[:rf.blocklen])

    # Warmup
    _ = rf.demodblock(data=signal, mtf_level=0, cut=True)

    steps = {}

    # Step 1: FFT of input
    times = []
    for _ in range(n_blocks):
        st = time.perf_counter()
        fft_out = npfft.fft(signal[:rf.blocklen])
        times.append(time.perf_counter() - st)
    steps["1_input_fft"] = np.array(times)

    # Step 2: RF video filter multiply + hilbert iFFT
    times = []
    for _ in range(n_blocks):
        indata_fft_filt = indata_fft * rf.Filters["RFVideo"]
        st = time.perf_counter()
        hilbert = npfft.ifft(indata_fft_filt)
        times.append(time.perf_counter() - st)
    steps["2_hilbert_ifft"] = np.array(times)

    # Step 3: unwrap_hilbert (phase demodulation)
    from lddecode.utils import unwrap_hilbert
    indata_fft_filt = indata_fft * rf.Filters["RFVideo"]
    hilbert = npfft.ifft(indata_fft_filt)
    times = []
    for _ in range(n_blocks):
        st = time.perf_counter()
        demod = unwrap_hilbert(hilbert, rf.freq_hz)
        times.append(time.perf_counter() - st)
    steps["3_unwrap_hilbert"] = np.array(times)

    # Step 4: clip + rfft of demod (replaces fft for real-valued data)
    demod = unwrap_hilbert(hilbert, rf.freq_hz)
    times = []
    for _ in range(n_blocks):
        st = time.perf_counter()
        clipped = np.clip(demod, 1500000, rf.freq_hz * 0.75)
        demod_rfft = npfft.rfft(clipped)
        times.append(time.perf_counter() - st)
    steps["4_clip_and_rfft"] = np.array(times)

    # Step 4b (old): clip + fft for comparison
    times = []
    for _ in range(n_blocks):
        st = time.perf_counter()
        clipped = np.clip(demod, 1500000, rf.freq_hz * 0.75)
        demod_fft = npfft.fft(clipped)
        times.append(time.perf_counter() - st)
    steps["4_clip_and_fft_OLD"] = np.array(times)

    # Step 5: batch irfft of stacked video filters (replaces 3-4 separate iffts + rolls)
    demod_rfft = npfft.rfft(np.clip(demod, 1500000, rf.freq_hz * 0.75))
    times = []
    for _ in range(n_blocks):
        st = time.perf_counter()
        video_results = npfft.irfft(
            demod_rfft * rf.Filters["FVideo_rfft_stack"], n=rf.blocklen, axis=1
        )
        times.append(time.perf_counter() - st)
    steps["5_batch_irfft"] = np.array(times)

    # Step 5b (old): separate iffts for comparison
    demod_fft = npfft.fft(np.clip(demod, 1500000, rf.freq_hz * 0.75))
    times = []
    for _ in range(n_blocks):
        st = time.perf_counter()
        npfft.ifft(demod_fft * rf.Filters["FVideo"]).real
        npfft.ifft(demod_fft * rf.Filters["FVideo05"]).real
        npfft.ifft(demod_fft * rf.Filters["FVideoBurst"]).real
        times.append(time.perf_counter() - st)
    steps["5_separate_iffts_OLD"] = np.array(times)

    # Step 6: rfhpf filter (new: irfft)
    rfft_len = rf.blocklen // 2 + 1
    indata_rfft = indata_fft[:rfft_len]
    times = []
    for _ in range(n_blocks):
        st = time.perf_counter()
        rfhpf = npfft.irfft(indata_rfft * rf.Filters["Frfhpf_half"], n=rf.blocklen)
        times.append(time.perf_counter() - st)
    steps["6_rfhpf_irfft"] = np.array(times)

    # Step 6b (old): rfhpf with full ifft for comparison
    times = []
    for _ in range(n_blocks):
        st = time.perf_counter()
        rfhpf_old = npfft.ifft(indata_fft * rf.Filters["Frfhpf"]).real
        times.append(time.perf_counter() - st)
    steps["6_rfhpf_ifft_OLD"] = np.array(times)

    # PAL-only: pilot filter
    if rf.system == "PAL":
        times = []
        for _ in range(n_blocks):
            st = time.perf_counter()
            pilot = npfft.ifft(demod_fft * rf.Filters["FVideoPilot"]).real
            times.append(time.perf_counter() - st)
        steps["5d_FVideoPilot_ifft"] = np.array(times)

    # Step 7: float32 casts + np.rec.array construction + np.roll
    out_video = npfft.ifft(demod_fft * rf.Filters["FVideo"]).real
    out_video05 = npfft.ifft(demod_fft * rf.Filters["FVideo05"]).real
    out_videoburst = npfft.ifft(demod_fft * rf.Filters["FVideoBurst"]).real
    times = []
    for _ in range(n_blocks):
        st = time.perf_counter()
        ov05 = np.roll(out_video05, -rf.Filters["F05_offset"])
        ovb = np.roll(out_videoburst, -rf.Filters["FVideoBurst_offset"])
        video_out = np.rec.array(
            [out_video.astype(np.float32), demod.astype(np.float32),
             ov05.astype(np.float32), ovb.astype(np.float32)],
            names=["demod", "demod_raw", "demod_05", "demod_burst"],
        )
        times.append(time.perf_counter() - st)
    steps["7_roll_cast_recarray"] = np.array(times)

    # Print results
    print(f"\n=== Substep breakdown ({n_blocks} iterations each) ===")
    total_median = sum(np.median(t) * 1000 for t in steps.values())
    for name, t in sorted(steps.items()):
        med = np.median(t) * 1000
        print(f"  {name:30s}  median: {med:6.2f} ms  ({med/total_median*100:5.1f}%)")

    print(f"  {'TOTAL (substeps)':30s}  median: {total_median:6.2f} ms")

    # Count FFT/iFFT operations in demodblock_cpu
    n_ffts = 1  # input FFT
    n_iffts = 4  # hilbert, FVideo, FVideo05, FVideoBurst
    n_iffts += 1  # rfhpf
    if rf.system == "PAL":
        n_iffts += 1  # FVideoPilot
    n_ffts += 1  # demod_fft
    print(f"\n  FFT/iFFT operations per block: {n_ffts} FFTs + {n_iffts} iFFTs = {n_ffts + n_iffts} total")
    print(f"  FFT size: {rf.blocklen} ({int(np.log2(rf.blocklen))} bits)")


def bench_blocklens(args):
    """Sweep block lengths and report demodblock throughput for each."""

    # Powers of 2 from 2^13 to 2^18, plus some composite-friendly sizes
    blocklens = sorted(set([
        8192,           # 2^13
        12288,          # 3 * 2^12
        16384,          # 2^14
        20480,          # 5 * 2^12
        24576,          # 3 * 2^13
        32768,          # 2^15  (current default)
        40960,          # 5 * 2^13
        49152,          # 3 * 2^14
        65536,          # 2^16
        81920,          # 5 * 2^14
        98304,          # 3 * 2^15
        131072,         # 2^17
    ]))

    n_blocks = args.blocks

    print(f"=== Block length sweep ({args.system}, freq={args.freq}MHz, {n_blocks} blocks each) ===")
    print(f"{'blocklen':>8s}  {'ms_sig':>7s}  {'median':>8s}  {'mean':>8s}  {'min':>8s}  "
          f"{'Msamp/s':>8s}  {'usable':>7s}  {'eff%':>5s}  {'notes':s}")
    print("-" * 95)

    for bl in blocklens:
        try:
            rf = RFDecode(
                inputfreq=args.freq,
                system=args.system,
                blocklen=bl,
                decode_digital_audio=False,
                decode_analog_audio=0,
            )
        except Exception as e:
            print(f"{bl:>8d}  FAILED: {e}")
            continue

        signal = make_fake_signal(rf)

        # Warmup
        try:
            _ = rf.demodblock(data=signal, mtf_level=0, cut=True)
        except Exception as e:
            print(f"{bl:>8d}  DEMOD FAILED: {e}")
            continue

        times = []
        for _ in range(n_blocks):
            st = time.perf_counter()
            rf.demodblock(data=signal, mtf_level=0, cut=True)
            times.append(time.perf_counter() - st)

        times = np.array(times)
        median = np.median(times)
        mean = times.mean()
        minimum = times.min()

        usable = rf.blocklen - rf.blockcut - rf.blockcut_end
        efficiency = usable / rf.blocklen * 100
        ms_of_signal = rf.blocklen / rf.freq_hz * 1000
        msamp_per_s = rf.blocklen / median / 1e6

        # Check if power of 2
        is_pow2 = (bl & (bl - 1)) == 0
        notes = "pow2" if is_pow2 else ""
        if bl == 32768:
            notes += " <-- current default"

        print(f"{bl:>8d}  {ms_of_signal:>6.2f}ms  {median*1000:>7.2f}ms  {mean*1000:>7.2f}ms  "
              f"{minimum*1000:>7.2f}ms  {msamp_per_s:>7.1f}M  {usable:>7d}  {efficiency:>4.1f}%  {notes}")

    print()


def main():
    parser = argparse.ArgumentParser(description="Benchmark RFDecode demodulation pipeline")
    parser.add_argument("--blocks", type=int, default=100, help="Number of blocks to benchmark (default: 100)")
    parser.add_argument("--system", choices=["NTSC", "PAL"], default="NTSC", help="Video system (default: NTSC)")
    parser.add_argument("--audio", action="store_true", help="Enable analog audio decoding")
    parser.add_argument("--efm", action="store_true", help="Enable EFM/digital audio decoding")
    parser.add_argument("--substeps", action="store_true", help="Benchmark individual substeps")
    parser.add_argument("--freq", type=float, default=40, help="Input frequency in MHz (default: 40)")
    parser.add_argument("--blocklens", action="store_true",
                        help="Sweep block lengths (powers of 2 and nearby composites)")
    args = parser.parse_args()

    if args.blocklens:
        bench_blocklens(args)
        return

    print(f"Initializing RFDecode (system={args.system}, freq={args.freq}MHz, "
          f"audio={'on' if args.audio else 'off'}, efm={'on' if args.efm else 'off'})...")

    rf = RFDecode(
        inputfreq=args.freq,
        system=args.system,
        decode_digital_audio=args.efm,
        decode_analog_audio=44100 if args.audio else 0,
    )

    print(f"Block length: {rf.blocklen} samples ({rf.blocklen / rf.freq_hz * 1000:.1f} ms)")
    print(f"Block cut: {rf.blockcut} front, {rf.blockcut_end} end")
    print(f"Usable samples per block: {rf.blocklen - rf.blockcut - rf.blockcut_end}")
    print(f"Line length: {rf.linelen} samples")

    print("\nGenerating synthetic RF signal...")
    signal = make_fake_signal(rf)
    print(f"Signal: {len(signal)} samples, range [{signal.min():.0f}, {signal.max():.0f}]")

    # Main benchmark: full demodblock
    bench_demodblock(rf, signal, args.blocks, f"demodblock ({args.system}, video only)")

    # If audio enabled, benchmark with audio
    if args.audio:
        bench_demodblock(rf, signal, args.blocks, f"demodblock ({args.system}, video+audio)")

    # Substep breakdown
    if args.substeps:
        bench_substeps(rf, signal, args.blocks)


if __name__ == "__main__":
    main()
