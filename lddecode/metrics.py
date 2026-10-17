"""VITS metrics computation and partial NTSC comb filter for ld-decode."""

import numpy as np

from .filters import inrange
from .dsp import nb_mean, nb_median, rms, roundfloat


def detect_levels(rf, field, output_lines):
    """Sync, 0 IRE and 100 IRE levels of a field, from HSYNC areas and
    VITS white areas.  A pure per-field measurement (used by the AGC),
    so it can run wherever the field's data lives."""
    sync_hzs = []
    ire0_hzs = []
    ire100_hzs = []

    for wl in (
        rf.SysParams['LD_VITS_whitelocs'] + rf.SysParams['LD_VITS_code_slices']
    ):
        # Code slice areas have a fourth value for percentile.
        ls = field.lineslice(*wl[:3])
        cut = field.data['video']['demod'][ls]
        freq = np.percentile(cut, 50 if len(wl) == 3 else wl[3])
        freq_ire = rf.hztoire(freq, spec=True)

        if inrange(freq_ire, 95, 110):
            ire100_hzs.append(freq)

    for line in range(12, output_lines):
        lsa = field.lineslice(line, 0.25, 4)

        begin_ire0 = rf.SysParams["colorBurstUS"][1]
        end_ire0 = rf.SysParams["activeVideoUS"][0]
        lsb = field.lineslice(line, begin_ire0 + 0.25, end_ire0 - begin_ire0 - 0.5)

        # compute wow adjustment
        thislinelen = (
            field.linelocs[line + field.lineoffset]
            - field.linelocs[line + field.lineoffset - 1]
        )
        adj = rf.linelen / thislinelen

        if inrange(adj, 0.98, 1.02):
            sync_hzs.append(nb_median(field.data["video"]["demod_05"][lsa]) / adj)
            ire0_hzs.append(nb_median(field.data["video"]["demod_05"][lsb]) / adj)

    # if any of the levels are missing, use the default levels
    vsync_hz   = rf.iretohz(rf.DecoderParams["vsync_ire"])

    m_synchz   = np.median(sync_hzs)   if len(sync_hzs)   else vsync_hz
    m_ire0hz   = np.median(ire0_hzs)   if len(ire0_hzs)   else rf.iretohz(0)
    m_ire100hz = np.median(ire100_hzs) if len(ire100_hzs) else rf.iretohz(100)

    return m_synchz, m_ire0hz, m_ire100hz


class CombNTSC:
    """*partial* NTSC comb filter with optional 3D inter-frame filtering.

    Accepts 2-4 fields.  Metrics are always for the last field (second field
    of the current frame).  With two frames (4 fields, or 2 same-parity
    fields) 3D comb filtering is applied in splitIQ_line via inter-frame
    subtraction of the 1D comb buffers — no motion correction.
    """

    def __init__(self, fields):
        if not isinstance(fields, (list, tuple)):
            fields = [fields]
        self.fields = fields
        self.cbuffer = [self.buildCBuffer(f) for f in fields]

    @property
    def field(self):
        return self.fields[-1]

    @property
    def has_3d(self):
        if len(self.fields) < 2:
            return False
        if len(self.fields) >= 4:
            return True
        return self.fields[0].isFirstField == self.fields[-1].isFirstField

    @property
    def _ref_idx(self):
        return max(0, len(self.fields) - 3)

    def getlinephase(self, fnum, line):
        fieldID = self.fields[fnum].fieldPhaseID

        if (line % 2) == 0:
            return (fieldID == 1) | (fieldID == 4)
        else:
            return (fieldID == 2) | (fieldID == 3)

    def buildCBuffer(self, field, subset=None):
        data = field.dspicture

        if subset is not None:
            data = data[subset]

        # 1D bandpass at fSC: tc1 = (line[h] - ((line[h-2] + line[h+2]) / 2))
        fldata = data.astype(np.float32)
        cbuffer = np.zeros_like(fldata)

        cbuffer[2:-2] = (fldata[:-4] + fldata[4:]) / 2
        cbuffer[2:-2] -= fldata[2:-2]

        return cbuffer

    def splitIQ_line(self, line, sl):
        """Demodulate chroma into I and Q for the primary field.

        When 3D is available, applies inter-frame subtraction before
        demodulation: C = (current_1d - prev_frame_1d) / 2
        """
        fnum = len(self.fields) - 1
        cbuffer = self.cbuffer[fnum][sl]

        if self.has_3d:
            cbuffer = (cbuffer - self.cbuffer[self._ref_idx][sl]) / 2

        linephase = self.getlinephase(fnum, line)

        sq = cbuffer[::2].copy()
        si = cbuffer[1::2].copy()

        if not linephase:
            si[0::2] = -si[0::2]
            sq[1::2] = -sq[1::2]
        else:
            si[1::2] = -si[1::2]
            sq[0::2] = -sq[0::2]

        return si, sq

    def calcLine19Info(self):
        """ returns color burst phase (ideally 147 degrees) and (unfiltered!) SNR """
        f = self.field

        l19_slice = f.lineslice_tbc(19, 0, 40)
        l19_slice_i70 = f.lineslice_tbc(19, 14, 18)

        ire_out = f.output_to_ire(f.dspicture[l19_slice_i70])
        if not ((np.max(ire_out) < 100) and (np.min(ire_out) > 40)):
            return None, None, None

        if self.has_3d:
            ref_f = self.fields[self._ref_idx]
            ire_ref = ref_f.output_to_ire(ref_f.dspicture[l19_slice_i70])
            if not ((np.max(ire_ref) < 100) and (np.min(ire_ref) > 40)):
                return None, None, None

        si, sq = self.splitIQ_line(19, l19_slice)

        sl = slice(110, 230)
        cdata = np.sqrt((si[sl] ** 2.0) + (sq[sl] ** 2.0))

        phase = np.arctan2(np.mean(si[sl]), np.mean(sq[sl])) * 180 / np.pi
        if phase < 0:
            phase += 360

        signal = np.mean(cdata)
        noise = np.std(cdata)
        snr = 20 * np.log10(signal / noise)

        return signal / (2 * f.out_scale), phase, snr


def calcsnr(f, snrslice, psnr=False):
    # if dspicture isn't converted to float, this underflows at -40IRE
    data = f.output_to_ire(f.dspicture[snrslice].astype(float))

    signal = np.mean(data) if not psnr else 100
    noise = np.std(data)

    return 20 * np.log10(signal / noise)


def calcpsnr(f, snrslice):
    return calcsnr(f, snrslice, psnr=True)


# CCIR Rec. 567 unified noise weighting network: a single-time-constant
# low-pass (tau0 = 245 ns, -3 dB ~ 650 kHz) that models the eye's reduced
# sensitivity to high-frequency noise.  See references/README.md for the
# sources.  Broadcast-style weighted SNR = 100 IRE p-p vs weighted RMS,
# band-limited to 4.2 MHz (525-line) / 5.0 MHz (625-line).
UNIFIED_WEIGHTING_TAU = 245e-9


def weighted_noise_rms(noise_ire, fs_hz, lpf_hz):
    """RMS of a noise vector after unified weighting + band-limiting.

    Applied in the frequency domain: measurement slices are short, so a
    time-domain IIR's edge transient would span the whole segment.
    """
    n = len(noise_ire)
    freqs = np.fft.rfftfreq(n, 1.0 / fs_hz)
    spec = np.abs(np.fft.rfft(noise_ire)) ** 2
    w2 = 1.0 / (1.0 + (2 * np.pi * freqs * UNIFIED_WEIGHTING_TAU) ** 2)
    w2[(freqs > lpf_hz) | ((freqs < 10e3) & (freqs > 0))] = 0.0
    # Parseval for rfft: interior bins count twice
    scale = np.full(len(spec), 2.0)
    scale[0] = 1.0
    if n % 2 == 0:
        scale[-1] = 1.0
    meansq = np.sum(spec * w2 * scale) / (n * n)
    return np.sqrt(meansq)


def calcpsnr_weighted(f, snrslice):
    """Weighted PSNR (dB, 100 IRE p-p vs CCIR-567-weighted RMS noise).

    The slice is detrended with a linear fit (the noise meter's tilt-null)
    before weighting.
    """
    data = f.output_to_ire(f.dspicture[snrslice].astype(float))
    n = len(data)
    if n < 32:
        return None
    x = np.arange(n)
    noise = data - np.polyval(np.polyfit(x, data, 1), x)

    fs_hz = f.rf.SysParams["outfreq"] * 1e6
    lpf_hz = 4.2e6 if f.rf.system == "NTSC" else 5.0e6
    rms_w = weighted_noise_rms(noise, fs_hz, lpf_hz)
    if rms_w <= 0:
        return None
    return 20 * np.log10(100.0 / rms_w)


def computeMetricsPAL(metrics, rf, f, fp=None):
    if f.isFirstField:
        wl_slice = f.lineslice_tbc(13, 4.7 + 15.5, 3)
        metrics["greyPSNR"] = calcpsnr(f, wl_slice)
        metrics["greyIRE"] = nb_mean(f.output_to_ire(f.dspicture[wl_slice]))
    else:
        b50slice = f.lineslice_tbc(13, 36, 20)
        metrics["palVITSBurst50Level"] = rms(f.dspicture[b50slice]) / f.out_scale

    return metrics


def computeMetricsNTSC(metrics, rf, f, fp=None):
    # check for a white flag - only on earlier discs, and only on first "frame" fields
    wf_slice = f.lineslice_tbc(11, 15, 40)
    if inrange(np.mean(f.output_to_ire(f.dspicture[wf_slice])), 92, 108):
        metrics["ntscWhiteFlagSNR"] = calcpsnr(f, wf_slice)

    # use line 19 to determine 0 and 70 IRE burst levels for MTF compensation later
    c = CombNTSC([f])

    level, phase, snr = c.calcLine19Info()
    if level is not None:
        metrics["ntscLine19ColorPhase"] = phase
        metrics["ntscLine19ColorRawSNR"] = snr

    ire50_slice = f.lineslice_tbc(19, 36, 10)
    metrics["greyPSNR"] = calcpsnr(f, ire50_slice)
    metrics["greyIRE"] = nb_mean(f.output_to_ire(f.dspicture[ire50_slice]))

    ire50_rawslice = f.lineslice(19, 36, 10)
    rawdata = f.rawdata[
        ire50_rawslice.start
        - int(rf.delays["video_white"]) : ire50_rawslice.stop
        - int(rf.delays["video_white"])
    ]
    metrics["greyRFLevel"] = np.std(rawdata)

    _metrics_fp_ntsc(metrics, f, fp)

    return metrics


def _metrics_fp_ntsc(metrics, f, fp):
    """The previous-frame-dependent NTSC metrics (3D comb line-19 SNR
    and burst levels).  Split out so they can be computed at commit time
    against a metrics dict that was precomputed per-field."""
    if not f.isFirstField and fp is not None:
        c3d = CombNTSC([fp, f])

        level3d, phase3d, snr3d = c3d.calcLine19Info()
        if level3d is not None:
            metrics["ntscLine19Burst70IRE"] = level3d
            metrics["ntscLine19Color3DRawSNR"] = snr3d

            sl_cburst = f.lineslice_tbc(19, 4.7 + 0.8, 2.4)
            diff = (
                f.dspicture[sl_cburst].astype(float)
                - fp.dspicture[sl_cburst].astype(float)
            ) / 2

            metrics["ntscLine19Burst0IRE"] = np.sqrt(2) * rms(diff) / f.out_scale

    return metrics


def computeMetrics(rf, f, fp=None, verbose=False, verboseVITS=False):
    system = f.rf.system
    if verboseVITS:
        verbose = True

    metrics = {}

    if system == "NTSC":
        computeMetricsNTSC(metrics, rf, f, fp)
    else:
        computeMetricsPAL(metrics, rf, f, fp)

    # FIXME: these should probably be computed in the Field class
    f.whitesnr_slice = None

    for wl in f.rf.SysParams["LD_VITS_whitelocs"]:
        wl_slice = f.lineslice_tbc(*wl)
        if inrange(np.mean(f.output_to_ire(f.dspicture[wl_slice])), 90, 110):
            f.whitesnr_slice = wl
            metrics["wSNR"] = calcpsnr(f, wl_slice)
            wsnr_w = calcpsnr_weighted(f, wl_slice)
            if wsnr_w is not None:
                metrics["wSNRw"] = wsnr_w
            metrics["whiteIRE"] = np.mean(f.output_to_ire(f.dspicture[wl_slice]))

            rawslice = f.lineslice(*wl)
            rawdata = f.rawdata[
                rawslice.start
                - int(rf.delays["video_white"]) : rawslice.stop
                - int(rf.delays["video_white"])
            ]
            metrics["whiteRFLevel"] = np.std(rawdata)

            break

    bl_slice = f.lineslice(*rf.SysParams["blacksnr_slice"])
    bl_slicetbc = f.lineslice_tbc(*rf.SysParams["blacksnr_slice"])

    delay = int(rf.delays["video_sync"])
    bl_sliceraw = slice(bl_slice.start - delay, bl_slice.stop - delay)
    metrics["blackLineRFLevel"] = np.std(f.rawdata[bl_sliceraw])

    metrics["blackLinePreTBCIRE"] = rf.hztoire(
        np.mean(f.data["video"]["demod"][bl_slice])
    )
    metrics["blackLinePostTBCIRE"] = f.output_to_ire(
        np.mean(f.dspicture[bl_slicetbc])
    )

    metrics["bPSNR"] = calcpsnr(f, bl_slicetbc)
    bpsnr_w = calcpsnr_weighted(f, bl_slicetbc)
    if bpsnr_w is not None:
        metrics["bPSNRw"] = bpsnr_w

    if "whiteRFLevel" in metrics:
        metrics["blackToWhiteRFRatio"] = (
            metrics["blackLineRFLevel"] / metrics["whiteRFLevel"]
        )

    return _round_metrics(
        metrics, metrics.keys() if verbose else DEFAULT_OUTPUT_KEYS
    )


DEFAULT_OUTPUT_KEYS = [
    "wSNR", "bPSNR", "wSNRw", "bPSNRw",
    "ntscLine19Burst70IRE", "ntscLine19Color3DRawSNR", "ntscLine19Burst0IRE",
]


# A field whose burst reads at or below this is one with no usable burst.
MIN_USABLE_BURST_IRE = 5.0


def chroma_gain_to_nominal(burst_levels, nominal):
    """Gain that brings the colour burst of the written samples to its nominal level.

    burst_levels -- per-field median burst amplitudes in IRE (a field's medianBurstIRE)
    nominal -- the system's nominal burst amplitude in IRE

    Returns nominal over the median of the usable levels, so multiplying the chroma
    by it puts the burst at nominal; 1.0 when the samples already carry it.  Levels
    that are not finite, or at or below MIN_USABLE_BURST_IRE, are ignored.  Returns
    None when no field has a usable level.
    """
    levels = np.asarray([x for x in burst_levels if x is not None], dtype=np.float64)
    levels = levels[np.isfinite(levels) & (levels > MIN_USABLE_BURST_IRE)]
    if levels.size == 0:
        return None
    return float(nominal / np.median(levels))


def _round_metrics(metrics, outputkeys):
    metrics_rounded = {}

    for k in outputkeys:
        if k not in metrics:
            continue

        if "Ratio" in k:
            digits = 4
        elif "Burst" in k:
            digits = 3
        else:
            digits = 1
        rounded = float(roundfloat(metrics[k], places=digits))
        if np.isfinite(rounded):
            metrics_rounded[k] = rounded

    return metrics_rounded


def computeMetricsFP(rf, f, fp, base_metrics, verbose=False):
    """Combine a per-field metrics dict precomputed with fp=None with the
    previous-frame-dependent metrics, yielding the same dict that
    computeMetrics(rf, f, fp, verbose) returns.  The base values were already
    rounded by the same rules, so only the fp-dependent part is computed
    here.  base_metrics must have been computed with verbose=True, so that
    every key is present to select from."""
    outputkeys = base_metrics.keys() if verbose else DEFAULT_OUTPUT_KEYS
    out = {k: base_metrics[k] for k in outputkeys if k in base_metrics}

    if f.rf.system == "NTSC":
        fpm = {}
        _metrics_fp_ntsc(fpm, f, fp)
        out.update(_round_metrics(fpm, fpm.keys() if verbose else DEFAULT_OUTPUT_KEYS))

    return out


# Single-field VITS measurements the decoder's servos pool (the 2T MTF
# servo and the video EQ).  They live here rather than with the servos so
# that a worker process can take them alongside the per-field metrics.

#: Largest ripple, as a fraction of the line's own white bar, that the ITS
#: bar and baseline windows may show and still be taken for an insertion
#: test signal.  Also the isolation limit for the 2T pulse's own tails.
ITS_FLATNESS_FRACTION = 0.15

# 2T reference layouts: (bar, baseline, pulse) windows in us and the VITS
# lines to search.  PAL: CCIR ITS (line 19, both parities).  NTSC: NTC-7
# composite (line 20, first fields; the second-field combination signal at
# the same line has no full bar and is rejected by the validity checks).
_VITS_2T_LAYOUT = {
    "PAL": ((13.0, 19.0), (22.2, 24.4), (24.4, 26.4), (19, 18, 20)),
    "NTSC": ((18.0, 28.0), (31.0, 33.0), (33.0, 35.0), (20, 19)),
}


def measure_its_2t_ratio(field, lines=None):
    """2T pulse-to-bar ratio from the insertion test signal, or None.

    Cheap single-field version of the analysis-side transient measurement
    (see _VITS_2T_LAYOUT for the per-system windows).  The line number is
    searched over `lines` because ITS placement can vary by one line
    between discs.  Validity checks reject anything that is not a clean
    bar + 2T pulse, so content lines and discs without an ITS yield
    None and the MTF servo falls back to the b/w RF ratio mapping.

    Returns (ratio, line) on success, else None.
    """
    bar_win, base_win, pulse_win, def_lines = \
        _VITS_2T_LAYOUT[field.rf.system]
    if lines is None:
        lines = def_lines
    for line in lines:
        try:
            def seg(a, b):
                sl = field.lineslice_tbc(line, a, b - a)
                return field.output_to_ire(
                    field.dspicture[sl].astype(np.float64))
            baseline_seg = seg(*base_win)
            bar_seg = seg(*bar_win)
            pulse_seg = seg(*pulse_win)
        except Exception:
            continue
        if len(pulse_seg) < 8 or len(bar_seg) < 8 or len(baseline_seg) < 8:
            continue

        baseline = float(np.median(baseline_seg))
        bar = float(np.median(bar_seg)) - baseline
        # must look like the ITS white bar over a blanking-level baseline
        if not (80.0 <= bar <= 125.0) or abs(baseline) > 6.0:
            continue
        # Flatness is judged against the bar this line carries, not in
        # absolute IRE.  A noisy pressing still presents a perfectly good
        # ITS - BBC Domesday DD86-DS1 runs 6-10 IRE of noise on every line,
        # against 2-4 IRE on a Pioneer calibration disc - and an absolute
        # 4 IRE gate rejected it outright, so the 2T servo never engaged on
        # exactly the discs whose HF response most needed correcting (its
        # 2T pulse then reads 0.85-0.90 of the bar against 0.99 where the
        # servo runs).  What separates an ITS from picture content is
        # structure, and structure is a large fraction of the bar: content
        # lines on the same disc scatter by 70-90% of it.  The same
        # relative scale is used by the isolation test below.  Measurement
        # noise is judged where it can be judged, over a pool of fields, by
        # the scatter gate in _mtf_servo_estimate().
        if (np.std(bar_seg) > ITS_FLATNESS_FRACTION * bar
                or np.std(baseline_seg) > ITS_FLATNESS_FRACTION * bar):
            continue

        # Locate the peak on a 3-tap-smoothed copy (argmax over the raw
        # window rides positive noise excursions, biasing the ratio high
        # and shifting the servo equilibrium), then interpolate the
        # height from the raw samples at that index.
        sm = np.convolve(pulse_seg, [0.25, 0.5, 0.25], mode="same")
        pk = int(np.argmax(sm[1:-1])) + 1
        if pk == 0 or pk == len(pulse_seg) - 1:
            continue
        # parabolic sub-sample peak: the 2T pulse top spans few samples
        a, b, c = pulse_seg[pk - 1], pulse_seg[pk], pulse_seg[pk + 1]
        denom = a - 2 * b + c
        peak = float(b) if denom >= 0 else float(b - 0.125 * (a - c) ** 2 / denom)
        pulse = peak - baseline
        ratio = pulse / bar
        if not (0.5 <= ratio <= 1.6):
            continue

        # half-amplitude width sanity: rejects blobs that are not a 2T pulse
        half = baseline + pulse / 2.0
        width = int(np.count_nonzero(pulse_seg > half))
        had_ns = width / field.rf.SysParams["outfreq"] * 1000.0
        if not (80.0 <= had_ns <= 400.0):
            continue

        # the pulse must be isolated: away from the peak the window
        # returns to baseline (rejects content/noise in the window)
        tails = np.concatenate([pulse_seg[:max(pk - 6, 0)],
                                pulse_seg[pk + 7:]])
        if (len(tails) < 8 or np.median(np.abs(tails - baseline))
                > ITS_FLATNESS_FRACTION * pulse):
            continue
        return ratio, line
    return None


def _multiburst_window_scan(y, fs_mhz, W, step):
    """Single-tone windows along a VBI line: (freq_hz, amp_ire_pp, start).

    Slides a W-sample Hann window along ``y`` (IRE) in steps of ``step``
    and keeps the windows that hold one clean tone of at least 12 IRE
    p-p, with the tone's frequency refined by a parabolic fit to the
    spectral peak.  Every window is scanned at once as one (n, W) array -
    one batched transform rather than ~65 small ones per line - with the
    same operations, in the same order, as a per-window loop, so the
    candidates are identical to it.  Returns a list in window order.
    """
    nwin = (len(y) - W) // step
    if nwin <= 0:
        return []
    starts = np.arange(nwin) * step
    windows = np.lib.stride_tricks.sliding_window_view(y, W)[starts]
    wd = windows - windows.mean(axis=1, keepdims=True)
    # p-p from rms: exact for a sine at any sampling phase
    pp = 2.0 * np.sqrt(2.0) * np.std(wd, axis=1)
    keep = ~(pp < 12.0)
    starts, pp, wd = starts[keep], pp[keep], wd[keep]
    if not len(starts):
        return []
    spec = np.abs(np.fft.rfft(wd * np.hanning(W), axis=1))
    rows = np.arange(len(spec))
    k = np.argmax(spec[:, 1:], axis=1) + 1
    keep = k < spec.shape[1] - 1
    rows, k, starts, pp = rows[keep], k[keep], starts[keep], pp[keep]
    a, b, c = spec[rows, k - 1], spec[rows, k], spec[rows, k + 1]
    # tone purity: reject windows that are not a single packet
    e_pk = a ** 2 + b ** 2 + c ** 2
    keep = ~(e_pk < 0.8 * np.sum(spec[rows] ** 2, axis=1))
    k, starts, pp = k[keep], starts[keep], pp[keep]
    a, b, c = a[keep], b[keep], c[keep]
    denom = a - 2 * b + c
    refine = np.abs(denom) > 1e-12
    kf = k.astype(np.float64)
    kf[refine] = k[refine] + 0.5 * (a[refine] - c[refine]) / denom[refine]
    freqs = kf * fs_mhz / W * 1e6
    return list(zip(freqs.tolist(), pp.tolist(), starts.tolist()))


def measure_vits_multiburst(field, lines=None):
    """One-line VITS multiburst from a VBI line, or None.

    PAL (first fields): GGV carries one on line 13 (0.5-5.8 MHz
    packets), the Louvre disc on line 20 (0.6-5.9 MHz).  NTSC (both
    parities): the FCC multiburst some discs carry on line 22
    (1.25-4.1 MHz).  The NTC-7 combination multiburst (line 20 second
    fields) is deliberately NOT used: its packets are only ~3 us — as
    short as the scan window at NTSC 4fsc — so nearly every window
    straddles a packet edge and the amplitude fit under-reads by up to
    2.5 dB (measured on he010/issue176), with the wrong sign vs the
    averaged-field analysis measurement.  Returns (packets, line)
    where packets is a list of
    (freq_hz, amp_ire_pp) for at least 4 packets at monotonically
    increasing frequencies including a reference packet near 1 MHz.
    Validity checks reject picture content and plain reference lines,
    so discs without a multiburst line yield None and the EQ servo
    stays inactive.
    """
    if field.dspicture is None:
        return None
    if field.rf.system == "PAL":
        if not field.isFirstField:
            return None
        if lines is None:
            lines = (13, 20)
    elif lines is None:
        lines = (22,)
    fs_mhz = field.rf.SysParams["outfreq"]
    for line in lines:
        try:
            sl = field.lineslice_tbc(line, 16.0, 46.0)
            y = field.output_to_ire(field.dspicture[sl].astype(np.float64))
        except Exception:
            continue
        if len(y) < 400:
            continue

        W = 44
        cands = _multiburst_window_scan(y, fs_mhz, W, 6)

        if len(cands) < 8:
            continue
        cands.sort()
        groups = []
        for f, a, i0 in cands:
            if groups and f - groups[-1][0][-1] < 0.3e6:
                groups[-1][0].append(f)
                groups[-1][2].append(i0)
            else:
                groups.append(([f], a, [i0]))
        packets = []
        for fl, _, il in groups:
            if len(fl) < 2:
                continue
            fmed = float(np.median(fl))
            # amplitude from a least-squares sine fit over the packet's
            # central span: unbiased for any (non-integer) cycle count,
            # unlike the per-window rms the scan uses
            lo, hi = min(il), max(il) + W
            span = hi - lo
            lo += span // 5
            hi -= span // 5
            seg = y[lo:hi]
            if len(seg) < 24:
                continue
            t = 2 * np.pi * fmed / (fs_mhz * 1e6) * np.arange(len(seg))
            A = np.column_stack([np.sin(t), np.cos(t), np.ones(len(seg))])
            coef, *_ = np.linalg.lstsq(A, seg, rcond=None)
            amp = 2.0 * float(np.hypot(coef[0], coef[1]))
            # the fit must explain the segment (rejects noise "packets")
            resid = seg - A @ coef
            if np.var(resid) > 0.35 * np.var(seg - seg.mean()):
                continue
            packets.append((fmed, amp))
        if len(packets) < 4:
            continue
        freqs = [p[0] for p in packets]
        if any(b <= a for a, b in zip(freqs, freqs[1:])):
            continue
        if freqs[-1] - freqs[0] < 2.5e6:
            continue
        ref = [p for p in packets if 0.75e6 <= p[0] <= 1.45e6]
        if not ref or not (25.0 <= ref[0][1] <= 90.0):
            continue
        return packets, line
    return None


#: The VITS servo measurements precompute_vits() can take, by name.
VITS_SERVO_MEASURES = {
    "measure_its_2t_ratio": measure_its_2t_ratio,
    "measure_vits_multiburst": measure_vits_multiburst,
}


def precompute_vits(field, names):
    """The named VITS_SERVO_MEASURES of a field, each with the vsync
    level it was read under: {name: (vsync_ire, result)}.

    The measurements read the picture in IRE through the live
    DecoderParams["vsync_ire"], which the AGC can move before the servo
    pools the result.  Keeping the level with each result lets the
    servo use it only while that level still stands (see
    LDdecode._vits_measurement), and measure afresh otherwise.  A level
    that moves while a measurement runs leaves nothing for that name.
    """
    dp = field.rf.DecoderParams
    out = {}
    for name in names:
        vsync_ire = dp["vsync_ire"]
        result = VITS_SERVO_MEASURES[name](field)
        if dp["vsync_ire"] == vsync_ire:
            out[name] = (vsync_ire, result)
    return out
