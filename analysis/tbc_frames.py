"""Notebook-friendly frame access for .tbc and CVBS .composite files.

Built on tbc_common's parsers (load_tbc / load_cvbs): loads a group of
frames from either container, NTSC or PAL, and presents them as numpy
arrays with the subcarrier/burst bookkeeping needed for comb filter
experiments.  All test-pattern detection and VITS measurement helpers
from tbc_common are re-exported so one import serves a whole notebook.

Usage from a notebook:

    import sys
    sys.path.insert(0, "/home/cpage/ld-decode/chad-cutdown/analysis")
    from tbc_frames import load_frames

    frames = load_frames("cbar_he.tbc", n_frames=4)      # or .composite
    fr = frames[0]

    fr.first.ire                  # field picture, 2D float IRE
    fr.first.raw                  # same, raw uint16
    fr.interlaced()               # woven full frame, 2D IRE
    y, c = fr.first.split_comb1d()   # baseline luma/chroma split
    fr.first.burst_phasors()      # per-line complex burst (IRE, rad)

    frames.detect()               # which test patterns are present
    comb = fr.comb_ntsc()         # lddecode CombNTSC on this frame

Subcarrier geometry (both containers, both systems, 4x fsc sampling):

- The subcarrier sits at exactly fs/4, so exp(-0.5j*pi*n) demodulates it
  (demod_region / burst_ref in tbc_common use this convention).
- Absolute phase is only meaningful within one line.  Reference
  measurements to the same line's colour burst (burst_phasors).
- Stored-line-to-stored-line subcarrier phase within a field: NTSC
  advances 180 degrees per line (227.5 cycles/63.5us line); PAL advances
  270 degrees per line (283.75 cycles) with the V-switch alternating on
  top.  PAL CVBS line starts additionally drift +0.0064 samples/line
  (90 degrees of subcarrier per sample) — one more reason to work
  burst-relative.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from tbc_common import (  # noqa: F401  (re-exports for notebook use)
    CaptureParams, TBCField,
    load_tbc, load_cvbs, load_video,
    detect_patterns, summarize_patterns, detect_colorbars,
    burst_ref, demod_region, line_segment_ire, average_line_ire,
    pal_fold_uv, phase_diff, segment_freq_pp, sine_fit_pp,
    measure_ntc7_multiburst, measure_ntc7_pedestal,
    measure_ntc7_transients, measure_pal_its_transients,
    measure_transients, weighted_psnr, chroma_am_pm_noise,
    NTC7_MULTIBURST_FREQS, NTC7_PEDESTAL_PP,
)


class FieldView:
    """One field as 2D arrays plus chroma bookkeeping.

    Wraps a tbc_common field object and delegates everything it does not
    define (line_ire, lineslice_tbc, output_to_ire, dspicture,
    fieldPhaseID, ...), so a FieldView can be passed directly to the
    tbc_common measurement functions and to lddecode.metrics.CombNTSC.
    """

    def __init__(self, field):
        self.field = field
        self.params = field.params

    def __getattr__(self, name):
        return getattr(self.field, name)

    def __repr__(self):
        return (f"FieldView({self.params.system} field "
                f"{self.field.field_index}, "
                f"{'first' if self.field.isFirstField else 'second'}, "
                f"phase {self.field.fieldPhaseID})")

    @property
    def raw(self):
        """Field picture as (field_height, field_width) uint16."""
        p = self.params
        return self.field.dspicture[:p.field_samples].reshape(
            p.field_height, p.field_width)

    @property
    def ire(self):
        """Field picture as (field_height, field_width) float64 IRE."""
        return self.field.output_to_ire(self.raw)

    def carrier(self, n0=0, n1=None):
        """Quadrature fs/4 reference exp(-0.5j*pi*n) for samples [n0, n1).

        Multiply a composite line by this and average to demodulate
        chroma with the same sign convention as demod_region.
        """
        if n1 is None:
            n1 = self.params.field_width
        return np.exp(-0.5j * np.pi * np.arange(n0, n1))

    def burst_phasor(self, line):
        """Complex burst for one line: abs = IRE amplitude, angle = phase.

        Returns 0j when the burst is absent/too weak to measure.
        """
        amp, phase = burst_ref(self.field, line)
        if amp is None:
            return 0j
        return amp * np.exp(1j * np.radians(phase))

    def burst_phasors(self, lines=None):
        """Per-line burst phasors as a complex array over `lines`
        (default: every stored line; index i corresponds to line i+1)."""
        if lines is None:
            lines = range(1, self.params.field_height + 1)
        return np.array([self.burst_phasor(ln) for ln in lines])

    def split_comb1d(self):
        """Baseline horizontal 1D luma/chroma split, as 2D IRE arrays.

        The +/-2 sample comb (chroma = center - (left2+right2)/2) is
        exact for a pure fs/4 subcarrier and system-independent: the
        reference point for judging fancier combs.  Chroma is returned
        at full amplitude (the raw comb has gain 2 at fsc).
        """
        x = self.raw.astype(np.float64)
        c = np.zeros_like(x)
        c[:, 2:-2] = (x[:, 2:-2] - (x[:, :-4] + x[:, 4:]) / 2) / 2
        y = (x - self.params.blanking_16b_ire) / self.params.out_scale
        c /= self.params.out_scale
        return y - c, c

    def demod(self, line, start_us, duration_us):
        """(luma_ire, chroma_amp_ire, phase_deg) of a line region."""
        return demod_region(self.field, line, start_us, duration_us)


class Frame:
    """A first/second field pair."""

    def __init__(self, first, second, index):
        self.first = FieldView(first)
        self.second = FieldView(second)
        self.index = index
        self.params = first.params

    @property
    def fields(self):
        return (self.first, self.second)

    @property
    def system(self):
        return self.params.system

    def __repr__(self):
        return (f"Frame({self.index}, {self.system}, fields "
                f"{self.first.field.field_index}/"
                f"{self.second.field.field_index})")

    def interlaced(self, ire=True):
        """Plain weave of the two fields: first field on even rows.

        Which parity sits spatially on top depends on the source's field
        order — for comb experiments the weave just provides adjacent-
        scan-time neighbours; check parity before using it for display.
        """
        a = self.first.ire if ire else self.first.raw
        b = self.second.ire if ire else self.second.raw
        out = np.empty((2 * a.shape[0], a.shape[1]), dtype=a.dtype)
        out[0::2] = a
        out[1::2] = b
        return out

    def comb_ntsc(self, prev_frame=None):
        """lddecode CombNTSC over this frame's fields (NTSC only).

        With prev_frame, enables 3D inter-frame comb mode.  Metrics and
        splitIQ_line operate on the LAST field passed (this frame's
        second field).
        """
        if self.system != "NTSC":
            raise ValueError("CombNTSC is NTSC-only")
        from lddecode.metrics import CombNTSC
        flds = []
        if prev_frame is not None:
            flds += [prev_frame.first.field, prev_frame.second.field]
        return CombNTSC(flds + [self.first.field, self.second.field])

    def detect(self):
        """Test patterns present on this frame's two fields."""
        return detect_patterns(self.params,
                               [self.first.field, self.second.field])


class FrameSet:
    """A loaded group of frames; behaves as a sequence of Frame."""

    def __init__(self, path, params, frames):
        self.path = path
        self.params = params
        self.frames = frames

    @property
    def system(self):
        return self.params.system

    @property
    def fields(self):
        """All fields, in field order, as FieldViews."""
        return [fv for fr in self.frames for fv in fr.fields]

    def __len__(self):
        return len(self.frames)

    def __getitem__(self, i):
        return self.frames[i]

    def __iter__(self):
        return iter(self.frames)

    def __repr__(self):
        return (f"FrameSet({os.path.basename(self.path)}: {self.system}, "
                f"{len(self.frames)} frames)")

    def detect(self, max_fields=8):
        """Detect test patterns and print a summary; returns the dict."""
        flds = [fv.field for fv in self.fields]
        det = detect_patterns(self.params, flds, max_fields=max_fields)
        for line in summarize_patterns(det, flds):
            print(line)
        return det

    def average_line(self, line, first_fields=True):
        """Coherent IRE average of one field line across the group
        (matching parity only — the two parities carry different VITS)."""
        flds = [fv.field for fv in self.fields
                if fv.isFirstField == first_fields]
        return average_line_ire(flds, line)


def _pair_frames(fields, start_frame=0, n_frames=None):
    """Pair fields strictly (a first field followed by a second field
    makes a frame); leading or stray unpaired fields are skipped."""
    pairs = []
    i = 0
    while i < len(fields) - 1:
        if fields[i].isFirstField and not fields[i + 1].isFirstField:
            pairs.append((fields[i], fields[i + 1]))
            i += 2
        else:
            i += 1
    pairs = pairs[start_frame:
                  None if n_frames is None else start_frame + n_frames]
    return [Frame(a, b, start_frame + k) for k, (a, b) in enumerate(pairs)]


def load_frames(path, n_frames=None, start_frame=0):
    """Load a group of frames from a .tbc or CVBS .composite file.

    path:        .tbc (companion .tbc.db), .composite (companion .meta),
                 or a basename of either.
    n_frames:    frames to return (default: all available).
    start_frame: first frame to return, counted in frame pairs from the
                 start of the file.

    Returns a FrameSet.
    """
    max_fields = None
    if n_frames is not None:
        # +2 spare fields in case the file opens on an unpaired second field
        max_fields = 2 * (start_frame + n_frames) + 2
    params, fields, _ = load_video(path, max_fields=max_fields)
    return FrameSet(path, params, _pair_frames(fields, start_frame, n_frames))


def frames_from_decoded(decoded_fields, black_ire=None):
    """Build a FrameSet directly from in-memory decoder Field objects.

    Takes the list that ldd.readfield() / a notebook rundecode() helper
    returns — no file round-trip, independent of the output mode chosen,
    since it reads the fields before they are written.  None entries and
    fields without a picture are skipped.

    Capture parameters are derived exactly as the .tbc.db capture row
    would be (decoder.build_sqlite_metadata): geometry and measurement
    windows from SysParams at the 4fsc output rate, levels via
    hz_to_output.  black_ire sets black_16b_ire only (default 7.5 NTSC,
    0 PAL).

    Each wrapped field keeps the full decoder Field reachable as
    .decoded (for linelocs, demod data, draw_field, plotline, ...).
    """
    flds = [f for f in decoded_fields
            if f is not None and getattr(f, "dspicture", None) is not None]
    if not flds:
        raise ValueError("no decoded fields with pictures")
    f0 = flds[0]
    system = f0.rf.system
    if black_ire is None:
        black_ire = 7.5 if system == "NTSC" else 0.0

    spu = f0.rf.SysParams["outfreq"]
    badj = -1.4  # burst/active window adjustment, as in the .tbc.db writer
    p = CaptureParams.__new__(CaptureParams)
    p.system = system
    p.field_width = f0.rf.SysParams["outlinelen"]
    p.field_height = min(f.outlinecount for f in flds)
    p.video_sample_rate = spu * 1e6
    p.sample_rate_mhz = spu
    p.white_16b_ire = float(f0.hz_to_output(f0.rf.iretohz(100)))
    p.black_16b_ire = float(f0.hz_to_output(f0.rf.iretohz(black_ire)))
    p.blanking_16b_ire = float(f0.hz_to_output(f0.rf.iretohz(0)))
    p.active_video_start = int(round(f0.rf.SysParams["activeVideoUS"][0] * spu + badj))
    p.active_video_end = int(round(f0.rf.SysParams["activeVideoUS"][1] * spu + badj))
    p.colour_burst_start = int(round(f0.rf.SysParams["colorBurstUS"][0] * spu + badj))
    p.colour_burst_end = int(round(f0.rf.SysParams["colorBurstUS"][1] * spu + badj))
    p.capture_id = None
    p.out_scale = (p.white_16b_ire - p.blanking_16b_ire) / 100.0
    p.field_samples = p.field_width * p.field_height

    fields = []
    for i, f in enumerate(flds):
        record = {"field_id": i, "is_first_field": bool(f.isFirstField),
                  "field_phase_id": getattr(f, "fieldPhaseID", None)}
        tf = TBCField(np.asarray(f.dspicture), 0, p, record)
        tf.field_index = i
        tf.decoded = f
        fields.append(tf)
    return FrameSet("<decoded fields>", p, _pair_frames(fields))
