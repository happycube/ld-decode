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


def computeMetricsFP(rf, f, fp, base_metrics):
    """Combine a per-field metrics dict precomputed with fp=None with the
    previous-frame-dependent metrics, yielding the same dict that
    computeMetrics(rf, f, fp) returns.  The base values were already
    rounded by the same rules, so only the fp-dependent part is computed
    here."""
    out = {k: base_metrics[k] for k in DEFAULT_OUTPUT_KEYS if k in base_metrics}

    if f.rf.system == "NTSC":
        fpm = {}
        _metrics_fp_ntsc(fpm, f, fp)
        out.update(_round_metrics(fpm, DEFAULT_OUTPUT_KEYS))

    return out
