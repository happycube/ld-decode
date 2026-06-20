"""VITS metrics computation and partial NTSC comb filter for ld-decode."""

import numpy as np

from .utils import inrange, nb_mean, rms, roundfloat


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

    if "whiteRFLevel" in metrics:
        metrics["blackToWhiteRFRatio"] = (
            metrics["blackLineRFLevel"] / metrics["whiteRFLevel"]
        )

    outputkeys = metrics.keys() if verbose else [
        "wSNR", "bPSNR",
        "ntscLine19Burst70IRE", "ntscLine19Color3DRawSNR", "ntscLine19Burst0IRE",
    ]

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
