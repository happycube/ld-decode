"""VITS metrics computation and partial NTSC comb filter for ld-decode."""

import numpy as np

from .filters import inrange
from .dsp import (carrier_amplitude, nb_mean, nb_median, rms, roundfloat,
                  tone_sideband_powers)


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


#: The FM sideband readings (burst_sideband_ratio, pilot_sideband_ratio):
#: the lines they pool, past the vertical interval; how far in from each
#: end of the tone the window stops, clear of its envelope's rise and fall;
#: and how strong each sideband must stand against its noise floor (power
#: ratio) for the field's reading to count.
SIDEBAND_LINES = (20, 250)
SIDEBAND_TRIM_US = 0.2
SIDEBAND_MIN_SNR = 1.0

#: Where the PAL pilot burst sits, in us from the line's sync edge: it
#: rides the sync tip (IEC 60856-1986 9.1.2) and starts after the edge.
PILOT_WINDOW_US = (0.8, 4.3)


def _tone_sideband_ratio(rf, f, window_us, carrier_hz, tone_hz):
    """H(carrier - tone) / H(carrier + tone) from a tone's two first FM
    sidebands over the field's lines (dsp.tone_sideband_powers), or None
    when either sideband does not clear its noise floor."""
    b0, b1 = window_us
    delay = int(rf.delays["video_sync"])
    segs = []
    for line in range(*SIDEBAND_LINES):
        if line + f.lineoffset >= len(f.linelocs):
            break
        sl = f.lineslice(line, b0, b1 - b0)
        start, stop = sl.start - delay, sl.stop - delay
        if start >= 0 and stop <= len(f.rawdata):
            segs.append(f.rawdata[start:stop])
    if not segs:
        return None
    n = min(len(s) for s in segs)
    powers = tone_sideband_powers(
        np.stack([s[:n] for s in segs]), rf.freq_hz, carrier_hz, tone_hz)
    if powers is None:
        return None
    lower, upper, lower_noise, upper_noise = powers
    if (lower < SIDEBAND_MIN_SNR * lower_noise
            or upper < SIDEBAND_MIN_SNR * upper_noise):
        return None
    return float(np.sqrt(lower / upper))


def burst_sideband_ratio(rf, f):
    """The channel's H(blanking - fsc) / H(blanking + fsc) from the colour
    burst's two first FM sidebands, or None.

    The burst is a subcarrier tone riding the blanking carrier, so its
    sidebands stand in the readout's ratio at those two frequencies
    whatever the burst's recorded amplitude (dsp.tone_sideband_powers):
    the readout model's cutoff measurement (decoder checkMTF).  The upper
    sideband lies beyond the cutoff on the innermost PAL radii, and close
    to it on some NTSC discs; a field whose upper sideband does not clear
    its noise floor gives no reading."""
    b0, b1 = rf.SysParams["colorBurstUS"]
    return _tone_sideband_ratio(
        rf, f, (b0 + SIDEBAND_TRIM_US, b1 - SIDEBAND_TRIM_US),
        rf.DecoderParams["ire0"], rf.SysParams["fsc_mhz"] * 1e6)


def pilot_sideband_ratio(rf, f):
    """The channel's H(tip - 3.75 MHz) / H(tip + 3.75 MHz) from the PAL
    pilot burst's two first FM sidebands, or None (NTSC has no pilot).

    The pilot rides the sync tip, 0.34 MHz below blanking, and is a lower
    tone than the colour subcarrier, so its upper sideband (10.5 MHz)
    stays under the readout's cutoff on inner radii where the burst's
    (11.5 MHz) is gone - Domesday DD86 and the Industrial disc at 5 % of
    their band, which the burst cannot read at all.  Its recorded
    amplitude varies by some 3 dB between discs, which the ratio of its
    sidebands does not see."""
    if rf.system != "PAL":
        return None
    DP = rf.DecoderParams
    return _tone_sideband_ratio(
        rf, f, PILOT_WINDOW_US, rf.iretohz(DP["vsync_ire"]),
        rf.SysParams["pilot_mhz"] * 1e6)


#: Burst levels at or below this are no reading (a field with no burst,
#: or one lost to dropouts) - the floor checkAutoDeemp already uses.
MIN_USABLE_BURST_IRE = 5.0


def chroma_correction_note(record, nominal_ire, db_per_unit_at_fsc, auto):
    """The capture-notes record of the chroma level correction.

    `record` is (burst IRE as written, inverse-MTF strength decoded
    under) per written field; `db_per_unit_at_fsc` is what the inverse-MTF
    filter adds at the subcarrier per unit of strength.  The correction is
    written into the samples, so the notes say what it was and what the
    burst read without it - the burst over the filter's gain at the
    subcarrier, field by field - and the gain that would bring the burst
    as written to nominal, for a reader that wants to apply or take out a
    chroma gain of its own.  Medians over the usable fields; key=value
    pairs joined by "; ", as the CVBS capture notes already are.
    """
    usable = [(float(b), float(s)) for b, s in record
              if b is not None and np.isfinite(b) and b > MIN_USABLE_BURST_IRE]
    parts = [f"chroma_correction={'auto' if auto else 'off'}"]
    if not usable:
        return "; ".join(parts)
    bursts = np.array([b for b, _ in usable])
    strengths = np.array([s for _, s in usable])
    written = float(np.median(bursts))
    uncorrected = float(np.median(
        bursts / 10.0 ** (strengths * db_per_unit_at_fsc / 20.0)))
    if auto:
        strength = float(np.median(strengths))
        parts.append(f"inverse_mtf_strength={strength:.3f} "
                     f"({strengths.min():.3f}..{strengths.max():.3f})")
        parts.append(f"inverse_mtf_gain_at_fsc_db={strength * db_per_unit_at_fsc:.2f}")
    parts.append(f"median_burst_ire={written:.2f}")
    if auto:
        parts.append(f"median_burst_ire_uncorrected={uncorrected:.2f}")
    parts.append(f"nominal_burst_ire={nominal_ire:.2f}")
    parts.append(f"chroma_gain_to_nominal={nominal_ire / written:.4f}")
    return "; ".join(parts)


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
    white_carrier = None

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
            white_carrier = carrier_amplitude(rawdata, rf.freq_hz)

            break

    bl_slice = f.lineslice(*rf.SysParams["blacksnr_slice"])
    bl_slicetbc = f.lineslice_tbc(*rf.SysParams["blacksnr_slice"])

    delay = int(rf.delays["video_sync"])
    bl_sliceraw = slice(bl_slice.start - delay, bl_slice.stop - delay)
    metrics["blackLineRFLevel"] = np.std(f.rawdata[bl_sliceraw])
    black_carrier = carrier_amplitude(f.rawdata[bl_sliceraw], rf.freq_hz)

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
        # The same ratio from the carrier alone (noise, the audio carriers
        # and EFM taken out), which is the readout's own tilt between the
        # blanking and white carriers: the readout MTF model's measure of
        # the disc's cutoff (decoder.checkMTF).
        if white_carrier and black_carrier:
            metrics["carrierTiltRatio"] = black_carrier / white_carrier

    if getattr(rf, "mtf_model", "poles") == "readout":
        for key, reading in (("burstSidebandRatio", burst_sideband_ratio),
                             ("pilotSidebandRatio", pilot_sideband_ratio)):
            ratio = reading(rf, f)
            if ratio is not None:
                metrics[key] = ratio

    return _round_metrics(
        metrics, metrics.keys() if verbose else DEFAULT_OUTPUT_KEYS
    )


DEFAULT_OUTPUT_KEYS = [
    "wSNR", "bPSNR", "wSNRw", "bPSNRw",
    "ntscLine19Burst70IRE", "ntscLine19Color3DRawSNR", "ntscLine19Burst0IRE",
]


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
# lines to search, in order.  PAL: CCIR ITS (line 19, both parities).
# NTSC: NTC-7 composite (line 20, first fields; the second-field
# combination signal at the same line has no full bar and is rejected by
# the validity checks).  Pioneer's GGV discs carry NTC-7 on line 13
# instead, searched last so that it is only read when lines 20 and 19
# have no 2T pulse to give.
_VITS_2T_LAYOUT = {
    "PAL": ((13.0, 19.0), (22.2, 24.4), (24.4, 26.4), (19, 18, 20)),
    "NTSC": ((18.0, 28.0), (31.0, 33.0), (33.0, 35.0), (20, 19, 13)),
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


#: The ITS / NTC-7 white bar's level above blanking, in IRE (100 IRE is
#: the PAL ITS's 700 mV as well as NTC-7's white reference).
ITS_WHITE_NOMINAL_IRE = 100.0


def measure_its_white_level(field, lines=None):
    """The insertion test signal's white bar above its blanking baseline,
    in IRE, or None.

    Read only from the line measure_its_2t_ratio accepts as the ITS (a
    flat bar over a blanking baseline with an isolated 2T pulse after
    it), so a bright content line cannot pass for it, and from the same
    bar and baseline windows (_VITS_2T_LAYOUT).  The baseline is
    subtracted, so a blanking-level offset does not read as a gain.

    Returns (level_ire, line) on success, else None.
    """
    found = measure_its_2t_ratio(field, lines)
    if found is None:
        return None
    line = found[1]
    bar_win, base_win, _, _ = _VITS_2T_LAYOUT[field.rf.system]

    def median(a, b):
        sl = field.lineslice_tbc(line, a, b - a)
        return float(np.median(field.output_to_ire(
            field.dspicture[sl].astype(np.float64))))

    return median(*bar_win) - median(*base_win), line


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


def _packet_interior(y, freq_hz, fs_mhz, lo, hi):
    """(start, stop) of the steady part of the freq_hz packet in y[lo:hi].

    The windows the scan accepts for a packet run past both its ends -
    a window hanging into the gap after it is still mostly tone - so
    their span is not the packet.  The packet is where its own envelope
    is: the line demodulated at freq_hz and averaged over whole cycles
    (about 12 samples), the longest run at 70 % or more of the envelope's
    90th percentile, less an eighth of its length (and half the averaging
    length) at each end for the edges' transients.  None if under 16
    samples are left.  Fitting over the accepted windows' span less a
    fifth at each end took in the gap after short packets: NTSC FCC's
    2.0 MHz packet read 0.7 dB low against its 1.25 MHz reference, and
    its 4.1 MHz packet up to 2 dB low.
    """
    lo, hi = max(0, lo), min(len(y), hi)
    seg = y[lo:hi]
    if len(seg) < 16:
        return None
    per = fs_mhz * 1e6 / freq_hz
    length = max(4, int(round(per * max(1, round(12 / per)))))
    n = np.arange(lo, hi)
    bb = (seg - np.median(seg)) * np.exp(-2j * np.pi * freq_hz / (fs_mhz * 1e6) * n)
    env = 2.0 * np.abs(np.convolve(bb, np.ones(length) / length, "same"))
    on = env >= 0.7 * np.percentile(env, 90)
    best = (0, 0, 0)
    run = start = 0
    for i, v in enumerate(on):
        if v:
            if run == 0:
                start = i
            run += 1
            if run > best[0]:
                best = (run, start, i + 1)
        else:
            run = 0
    run, a, b = best
    trim = max(length // 2, run // 8)
    a, b = a + trim, b - trim
    return (lo + a, lo + b) if b - a >= 16 else None


def _rising_run(fitted):
    """The longest subsequence of (position, freq, amp), in line order,
    whose frequency rises strictly: a multiburst's packets.  Returned as
    (freq, amp) pairs.  Earliest wins a tie."""
    n = len(fitted)
    if not n:
        return []
    length, prev = [1] * n, [-1] * n
    for i in range(n):
        for j in range(i):
            if fitted[j][1] < fitted[i][1] and length[j] + 1 > length[i]:
                length[i], prev[i] = length[j] + 1, j
    i = max(range(n), key=lambda k: (length[k], -k))
    out = []
    while i >= 0:
        out.append((fitted[i][1], fitted[i][2]))
        i = prev[i]
    return out[::-1]


def measure_vits_multiburst(field, lines=None):
    """One-line VITS multiburst from a VBI line, or None.

    PAL (first fields): GGV carries one on line 13 (0.5-5.8 MHz
    packets), the Louvre disc on line 20 (0.6-5.9 MHz).  NTSC: the FCC
    multiburst some discs carry on line 22 (1.25-4.1 MHz, both
    parities), and failing that the NTC-7 combination multiburst
    (0.5-4.2 MHz, second fields, on line 13 or 20).  Returns
    (packets, line) where packets is a list of (freq_hz, amp_ire_pp)
    for at least 4 packets at monotonically increasing frequencies
    including a reference packet near 1 MHz.  Validity checks reject
    picture content and plain reference lines, so discs without a
    multiburst line yield None and the EQ servo stays inactive.

    The packets taken are the longest run along the line that rises in
    frequency (_rising_run): NTC-7's three-level chrominance follows its
    4.2 MHz packet at the subcarrier frequency, and without that its
    largest bar was taken for the 3.58 MHz packet (+4 dB).  The NTC-7
    line had been left out because the fit over the scan windows' span
    under-read its ~3 us packets by up to 2.5 dB; over their own
    interiors its 2.0-4.2 MHz packets agree with the conformance checker
    to 0.3 dB on the GGV and Video Essentials pressings.  The ~2.5 us
    packets of some discs (dolby-surround) leave under 16 samples of
    interior and are refused.
    """
    if field.dspicture is None:
        return None
    if field.rf.system == "PAL":
        if not field.isFirstField:
            return None
        if lines is None:
            lines = (13, 20)
    elif lines is None:
        lines = ((22,) if getattr(field, "isFirstField", True)
                 else (22, 13, 20))
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
            # Against the group's median, not its last member: windows
            # straddling the gap between two packets read a frequency in
            # between, and chained one packet into the next (NTSC FCC's
            # 3.58 and 4.1 MHz fitted as one 4.05 MHz packet across the
            # gap, 2 dB low).
            if groups and abs(f - np.median(groups[-1][0])) < 0.3e6:
                groups[-1][0].append(f)
                groups[-1][2].append(i0)
            else:
                groups.append(([f], a, [i0]))
        # A group's windows split where they stop being contiguous along
        # the line: one frequency can occur twice (NTC-7's subcarrier
        # packet and its chrominance bars).
        runs = []
        for fl, _, il in groups:
            order = np.argsort(il)
            fl = [fl[i] for i in order]
            il = [il[i] for i in order]
            start = 0
            for k in range(1, len(il) + 1):
                if k == len(il) or il[k] - il[k - 1] > W:
                    if k - start >= 2:
                        runs.append((fl[start:k], il[start:k]))
                    start = k
        fitted = []
        for fl, il in runs:
            fmed = float(np.median(fl))
            # amplitude from a least-squares sine fit over the packet's
            # steady interior: unbiased for any (non-integer) cycle count,
            # unlike the per-window rms the scan uses
            extent = _packet_interior(y, fmed, fs_mhz, min(il), max(il) + W)
            if extent is None:
                continue
            seg = y[extent[0]:extent[1]]
            t = 2 * np.pi * fmed / (fs_mhz * 1e6) * np.arange(len(seg))
            A = np.column_stack([np.sin(t), np.cos(t), np.ones(len(seg))])
            coef, *_ = np.linalg.lstsq(A, seg, rcond=None)
            amp = 2.0 * float(np.hypot(coef[0], coef[1]))
            # the fit must explain the segment (rejects noise "packets")
            resid = seg - A @ coef
            if np.var(resid) > 0.35 * np.var(seg - seg.mean()):
                continue
            fitted.append((extent[0], fmed, amp))
        packets = _rising_run(sorted(fitted))
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
