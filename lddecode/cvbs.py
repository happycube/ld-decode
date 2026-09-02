"""CVBS 4fsc output (see cvbs-file-format-specification/).

Lattice math for the spec's Video Standard Presets.  The writer that uses
these lives in CVBSWriter (added with the output mode).

The PAL 4fsc lattice is NOT line-locked: fsc = (1135/4 + 1/625) * fH, so a
line averages 1135.0064 samples, the sampling structure slips 4 samples per
625-line frame, and the normative sample count exists only at frame level
(709,379 samples).  All lattice arithmetic here is integer-exact — no float
accumulation across lines or frames.
"""

from fractions import Fraction

from .params import CVBSParams_NTSC, CVBSParams_PAL

PAL_FRAME_SAMPLES = CVBSParams_PAL["frame_samples"]      # 709379
PAL_FRAME_LINES = CVBSParams_PAL["frame_lines"]          # 625
PAL_SAMPLES_PER_LINE = Fraction(*CVBSParams_PAL["samples_per_line"])

NTSC_FRAME_SAMPLES = CVBSParams_NTSC["frame_samples"]    # 477750
NTSC_FRAME_LINES = CVBSParams_NTSC["frame_lines"]        # 525
NTSC_SAMPLES_PER_LINE = CVBSParams_NTSC["samples_per_line"]  # 910


def _ceil_frac(f):
    return -(-f.numerator // f.denominator)


def pal_line_lattice(nlines=PAL_FRAME_LINES):
    """Per-line lattice structure of one PAL 4fsc frame.

    Returns a list of (first_sample_index, sample_count, start_phase) per
    line, where start_phase is the fractional lattice offset of the line's
    first sample past the line's start time, in lattice-sample units [0, 1).
    Integer-exact: sample counts are 1135 or 1136 and sum to exactly
    PAL_FRAME_SAMPLES over a full frame (four lines per frame carry the
    extra sample).
    """
    out = []
    spl = PAL_SAMPLES_PER_LINE
    for k in range(nlines):
        t0 = k * spl
        t1 = (k + 1) * spl
        j0 = _ceil_frac(t0)
        j1 = _ceil_frac(t1)
        out.append((j0, j1 - j0, float(j0 - t0)))
    return out


def pal_lattice_positions(n_samples, origin_lines=Fraction(0)):
    """Positions of PAL lattice samples in *line-time* units.

    Sample j of the frame lattice sits at time (origin_lines + j/spl)
    lines, where spl = 709379/625.  Returned as a float64 numpy array for
    feeding a field's expected-time -> input-position spline.  The uniform
    step is 625/709379 lines — the non-orthogonality is entirely captured
    by that ratio not being 1/1135.
    """
    import numpy as np

    step = 625.0 / 709379.0
    return float(origin_lines) + np.arange(n_samples, dtype=np.float64) * step


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

import os
import sqlite3
import struct

import numpy as np


_META_SCHEMA = """
PRAGMA user_version = 11;

CREATE TABLE cvbs_file (
    cvbs_file_id                INTEGER PRIMARY KEY,
    preset                      TEXT    NOT NULL
        CHECK (preset IN ('NTSC', 'PAL', 'PAL_M')),
    sample_encoding_preset      TEXT    NOT NULL
        CHECK (sample_encoding_preset IN ('CVBS_U10_4FSC', 'CVBS_U16_4FSC', 'RAW_S16_28M', 'RAW_S16_40M', 'CVBS_TPG21_4FSC', 'CVBS_S16_4FSC')),
    signal_state_preset         TEXT    NOT NULL
        CHECK (signal_state_preset IN (
            'STANDARD_STABLE_LOCKED',
            'STANDARD_STABLE_UNLOCKED',
            'STANDARD_RAW',
            'NONSTANDARD_STABLE_LOCKED',
            'NONSTANDARD_STABLE_UNLOCKED',
            'NONSTANDARD_RAW'
        )),
    sequence_continuous         BOOLEAN,
    signal_type                 TEXT    NOT NULL
        CHECK (signal_type IN ('composite', 'yc')),
    decoder                     TEXT    NOT NULL,
    git_branch                  TEXT,
    git_commit                  TEXT,
    number_of_sequential_frames INTEGER
        CHECK (number_of_sequential_frames IS NULL OR number_of_sequential_frames >= 1),
    black_level                 INTEGER,
    has_nonstandard_values      BOOLEAN,
    capture_notes               TEXT
);

CREATE TABLE audio_channel_pair (
    channel_pair                INTEGER PRIMARY KEY
        CHECK (channel_pair BETWEEN 0 AND 7),
    description                 TEXT
);
"""

# Lowest and highest 10-bit sample value a conformant file may contain.  Both
# sample encodings share the normative 10-bit domain and its reserved codes,
# so the clamp is expressed there once and applied on either output path.
# CVBS file format specification - sample-encoding-presets: protected values
# 0-3 and 1020-1023.
CVBS_CLAMP_LO10 = 4
CVBS_CLAMP_HI10 = 1019

# Range representable by the s16le container CVBS_U10_4FSC stores samples in.
# Its signed headroom is what lets a decode keep excursions outside the 10-bit
# range instead of clipping them away.
CVBS_U10_CONTAINER_MIN = -32768
CVBS_U10_CONTAINER_MAX = 32767


def encode_cvbs_frame(frame, sample_encoding, has_nonstandard_values=False):
    """Quantise one frame from the writer's working domain to file bytes.

    Parameters
    ----------
    frame : numpy.ndarray
        One frame in the internal working domain, which is the 10-bit sample
        value scaled by 64 (see CVBSWriter._to_spec_levels).
    sample_encoding : str
        "CVBS_U10_4FSC" (s16le, the 10-bit value with signed headroom) or
        "CVBS_U16_4FSC" (u16le, the 10-bit value shifted left 6).
    has_nonstandard_values : bool
        CVBS_U10_4FSC only: keep excursions outside the 10-bit range rather
        than clamping them to the reserved-code bounds.  A u16 container
        cannot represent them, which is why this option belongs to that
        encoding alone.

    Returns (payload_bytes, clamped_sample_count).

    Both encodings quantise to the *nearest* 10-bit code, so a decode written
    either way holds the same sample values.  Pure: no file access and no
    writer state, so the quantisation is unit-testable on its own.
    """
    # The working domain is 10-bit * 64, so this is the sample value itself.
    frame_10 = frame / 64.0

    if sample_encoding == "CVBS_U10_4FSC":
        if has_nonstandard_values:
            lo, hi = CVBS_U10_CONTAINER_MIN, CVBS_U10_CONTAINER_MAX
        else:
            lo, hi = CVBS_CLAMP_LO10, CVBS_CLAMP_HI10
    else:
        lo, hi = CVBS_CLAMP_LO10, CVBS_CLAMP_HI10

    n_clamped = int(np.count_nonzero((frame_10 < lo) | (frame_10 > hi)))
    if n_clamped:
        frame_10 = np.clip(frame_10, lo, hi)
    frame_10 = np.round(frame_10)

    if sample_encoding == "CVBS_U10_4FSC":
        return frame_10.astype("<i2").tobytes(), n_clamped
    # Scale the quantised code into the container.  Rounding to 16 bits and
    # masking the low six bits off would floor rather than round, biasing
    # every sample down by up to one code (about 0.17 IRE) against the
    # CVBS_U10_4FSC path for the same decode.
    # CVBS file format specification - sample-encoding-presets:
    # u16 = value_10bit * 64.
    return (frame_10.astype(np.int32) << 6).astype("<u2").tobytes(), n_clamped


class CVBSWriter:
    """Assembles decoded fields into spec-compliant CVBS output.

    Writes <basename>.cvbs, <basename>.meta (SQLite, spec core schema),
    optional <basename>_audio_0.wav, and the dropout / EFM extension
    sidecars (<basename>.dropouts.meta, <basename>.efm + .efm.meta, plus
    the optional <basename>.efmc confidence companion).

    The sample encoding preset governs the binary format of the .cvbs
    file.  CVBS_U10_4FSC (s16le, 10-bit domain with signed headroom)
    is selected automatically when the signal contains non-standard
    values such as PAL pilot bursts; CVBS_U16_4FSC (u16le, 10-bit<<6)
    is used otherwise.  An explicit choice overrides the auto-selection.

    Audio follows the SMPTE 272M-1994 profile the spec mandates: one
    channel pair (stereo) stored as a 48 kHz, 24-bit signed little-endian
    WAV, synchronous to video.  PAL carries 1920 samples/frame exactly;
    NTSC/PAL_M carry 8008 samples per 5-frame audio-frame sequence
    (1602/1601/1602/1601/1602), so the stored stream is trimmed or
    zero-padded at close to exactly offset(N) samples for N frames.

    Frames use the ld-decode line convention (sample 0 at the line start,
    0H ~ +0.8) — the layout decode-orc's cvbs_source reader expects.  One
    field pair produces exactly one frame, so extension frame indices align
    with the video by construction.

    Burst lock: PAL output is anchored to the 4fsc lattice with a global
    time shift.  The spec lattice samples at 45/135/225/315 degrees to +U,
    a constraint defined only mod 90 degrees — and 90 degrees of subcarrier
    is exactly one lattice sample, so the correction is always <= +/-0.5
    sample and cannot move 0H.  The V-switch folds out of the measurement
    via adjacent-line burst products (b_k * b_(k+1) has phase 2*theta).
    NTSC needs no re-anchoring (the decoder already rotates each field to
    the fsc_phase_deg target); its lock is measured and declared honestly.
    """

    PAL_LOCK_TARGET = 45.0     # folded burst phase target, deg (mod 90)
    NTSC_LOCK_TARGET = 147.25  # line-referenced burst phase target, deg
    LOCK_TOL = 3.0             # residual tolerance for claiming LOCKED

    # SMPTE 272M-1994 audio profile (spec's only permitted format)
    AUDIO_RATE = 48000         # Hz, synchronous to video
    AUDIO_BITS = 24            # signed little-endian PCM
    AUDIO_BYTES_PER_SAMPLE = 2 * (AUDIO_BITS // 8)   # stereo frame, bytes

    def __init__(self, fname_out, system, logger=None, version=None,
                 black_level=None, write_audio=False,
                 audio_description="Analogue stereo", capture_notes=None,
                 has_nonstandard_values=None, write_efm=False,
                 write_efm_conf=False, sample_encoding=None):
        self.system = system
        self.params = CVBSParams_PAL if system == "PAL" else CVBSParams_NTSC
        self.fname_out = fname_out
        self.logger = logger
        self.has_nonstandard_values = has_nonstandard_values

        if sample_encoding is None:
            sample_encoding = (
                "CVBS_U10_4FSC" if has_nonstandard_values
                else "CVBS_U16_4FSC"
            )
        self.sample_encoding = sample_encoding

        self.f_video = open(fname_out + ".cvbs", "wb")

        self._pending_first = None   # (field, fi, pic_or_None, efm, audio, efm_conf)
        self._started = False
        self._fields_seen = 0
        self.frames_written = 0
        self.clamped_samples = 0

        lv = self.params["levels"]
        self.blank16 = lv["blanking"] * 64
        self.white16 = lv["white"] * 64

        # burst lock state
        self._pal_shift = 0.0          # lattice-sample lattice shift
        self._lock_initialised = False
        self._lock_residuals = []      # per-frame residual, degrees

        # sequence continuity (spec sequence_continuous): the file is one
        # unbroken sequence unless the writer drops a field mid-file or the
        # decoder's fieldPhaseID progression breaks; without phase IDs to
        # check against, continuity is unknown (NULL), not asserted.
        self._seq_broken = False
        self._phase_seen = False
        self._last_phase = None

        # extension sidecar state
        self.dropout_rows = []         # (frame_id, sample_start, count, sev)
        self.write_efm = write_efm
        self.f_efm = None
        self._efm_index = []           # (frame_id, offset, count)
        self._efm_offset = 0
        # Optional confidence companion (<basename>.efmc): one uint8 per
        # t-value, byte-for-byte parallel to .efm and indexed by the same
        # efm_frame rows (see the EFM extension format specification).
        self.write_efm_conf = write_efm and write_efm_conf
        self.f_efmc = None

        # metadata fields
        self.version = version or ""
        self.black_level = black_level
        self.capture_notes = capture_notes

        # audio
        self.write_audio = write_audio
        self.audio_description = audio_description
        self.f_wav = None
        self._audio_bytes = 0

    # -- video ------------------------------------------------------------

    def push_field(self, fi, picture, field=None, efm=None, audio=None,
                   efm_conf=None):
        """Add one decoded field (with its dropout, EFM, and audio data).

        Audio rides through the same frame pairing so the WAV contains
        exactly the audio of the written frames (the spec requires the
        first audio sample to be synchronous with the first stored frame).
        """
        is_first = bool(fi["isFirstField"])
        self._fields_seen += 1

        if not self._started:
            # start the file at the conventional sequence position: a first
            # field opening NTSC colour frame A / PAL sequence frame 1
            # (fieldPhaseID 1).  Give up after 2 sequence lengths rather
            # than discard forever.
            cap = 8 if self.system == "NTSC" else 16
            phase_ok = (fi.get("fieldPhaseID") in (1, None)
                        or self._fields_seen > cap)
            if not (is_first and phase_ok):
                return
            self._started = True

        # Source-side continuity: consecutive fields must advance the colour
        # sequence by exactly one position.  Breaks only matter once content
        # is (or may end up) in the file; earlier ones just move the start.
        phase = fi.get("fieldPhaseID")
        if phase is not None:
            cycle = 4 if self.system == "NTSC" else 8
            if (self._last_phase is not None
                    and phase != self._last_phase % cycle + 1
                    and (self.frames_written > 0
                         or self._pending_first is not None)):
                self._seq_broken = True
            self._last_phase = phase
            self._phase_seen = True

        if is_first:
            if self._pending_first is not None:
                if self.frames_written > 0:
                    self._seq_broken = True
                if self.logger:
                    self.logger.warning("CVBS: dropping unpaired first field")
            self._pending_first = (field, fi, picture, efm, audio, efm_conf)
            return

        if self._pending_first is None:
            if self.frames_written > 0:
                self._seq_broken = True
            if self.logger:
                self.logger.warning("CVBS: dropping unpaired second field")
            return

        pending = self._pending_first
        self._pending_first = None
        self._emit_frame(pending, (field, fi, picture, efm, audio, efm_conf))

    def _emit_frame(self, first, second):
        f_a, fi_a, pic_a, efm_a, aud_a, conf_a = first
        f_b, fi_b, pic_b, efm_b, aud_b, conf_b = second

        if self.system == "NTSC":
            a = self._to_spec_levels(self._as_u16(pic_a), f_a)
            b = self._to_spec_levels(self._as_u16(pic_b), f_b)
            spl = self.params["samples_per_line"]
            frame = np.concatenate([a[: 263 * spl], b[: 262 * spl]])
            self._measure_ntsc_lock(frame)
        else:
            # PAL: resample both fields onto the frame lattice with the
            # current lock shift.  On the first frame, measure and anchor
            # (one re-resample); afterwards track with small corrections.
            # Burst measurement runs on the decoder-domain output (before
            # _to_spec_levels) so the amplitude threshold is consistent.
            a_raw = f_a.downscale_cvbs(self._pal_shift)
            if not self._lock_initialised:
                delta = self._pal_phase_error(a_raw)
                if delta is not None:
                    self._pal_shift += delta / 90.0
                    a_raw = f_a.downscale_cvbs(self._pal_shift)
                self._lock_initialised = True
            b_raw = f_b.downscale_cvbs(self._pal_shift)

            resid = self._pal_phase_error(a_raw)
            if resid is not None:
                self._lock_residuals.append(resid)
                self._pal_shift += np.clip(resid / 90.0, -0.05, 0.05)

            a = self._to_spec_levels(a_raw, f_a)
            b = self._to_spec_levels(b_raw, f_b)
            frame = np.concatenate([a, b])

        frame_id = self.frames_written
        self._write_frame(frame)
        self._collect_dropouts(frame_id, fi_a, fi_b)
        self._collect_efm(frame_id, efm_a, efm_b, conf_a, conf_b)
        for aud in (aud_a, aud_b):
            if aud is not None:
                self.push_audio(aud)

    def _as_u16(self, picture):
        return (np.frombuffer(picture, dtype=np.uint16)
                if isinstance(picture, (bytes, bytearray)) else picture)

    def _to_spec_levels(self, x, f):
        """Remap decoder 16-bit output onto the spec's level anchors.

        Returns float64 in the internal working domain (10-bit * 64);
        _write_frame applies the final encoding-specific conversion.

        The decoder's 16-bit scale pins the SYNC TIP at SysParams
        outputZero and white at output_white, with the measured (AGC)
        sync depth in between - so the blanking level lands wherever the
        disc's actual sync depth puts it.  The CVBS spec instead pins
        BLANKING (256<<6 PAL / 240<<6 NTSC) and 100 IRE white; sync depth
        is a property of the source signal, so the sync tip lands below
        blanking by the measured depth (the spec's nominal sync value
        corresponds to exactly 42.86 IRE PAL / 40 IRE NTSC).  Anchoring
        sync instead of blanking put blanking ~2-3 IRE low on
        shallow-sync discs and clipped half the sync-tip noise into the
        protected floor on nominal ones.

        Without a field to read the decoder's anchors from, the data is
        assumed to be at spec levels already."""
        if f is None:
            return x.astype(np.float64)
        blank_dec = float(f.hz_to_output(f.rf.DecoderParams["ire0"]))
        white_dec = float(f.hz_to_output(f.rf.iretohz(100.0)))
        gain = (self.white16 - self.blank16) / (white_dec - blank_dec)
        return (x.astype(np.float64) - blank_dec) * gain + self.blank16

    def _write_frame(self, frame):
        fs = self.params["frame_samples"]
        if len(frame) != fs:
            if self.frames_written > 0:
                self._seq_broken = True
            if self.logger:
                self.logger.warning(
                    "CVBS: frame size %d != %d, dropping", len(frame), fs)
            return

        payload, n_clamped = encode_cvbs_frame(
            frame, self.sample_encoding, self.has_nonstandard_values)
        self.clamped_samples += n_clamped
        self.f_video.write(payload)

        self.frames_written += 1

    # -- burst lock -------------------------------------------------------

    def _pal_phase_error(self, field_a_lattice):
        """Folded burst-vs-lattice phase error of a field-A stream, degrees.

        Returns wrap(target - measured) in (-45, 45], or None if bursts are
        too weak.  Adjacent-line burst products cancel the PAL V-switch:
        b_k * b_(k+1) has phase 2*theta_burst_axis.
        """
        x = field_a_lattice.astype(np.float64)
        spl = 709379.0 / 625.0
        bursts = []
        for k in range(30, 120):
            j0 = int(np.ceil(k * spl))
            seg = x[j0 + 98: j0 + 138]          # EBU burst window
            if len(seg) < 40:
                break
            n = np.arange(j0 + 98, j0 + 138)
            b = np.mean((seg - np.mean(seg)) * np.exp(-0.5j * np.pi * n))
            bursts.append(b)
        if len(bursts) < 20:
            return None
        bursts = np.array(bursts)
        amp = np.abs(bursts)
        if np.median(amp) < 40:                 # ~1 IRE in 16-bit units
            return None
        prods = bursts[:-1] * bursts[1:]
        p = np.sum(prods)
        if np.abs(p) == 0:
            return None
        measured = (np.degrees(np.angle(p)) / 2.0) % 90.0
        delta = (self.PAL_LOCK_TARGET - measured + 45.0) % 90.0 - 45.0
        return float(delta)

    def _measure_ntsc_lock(self, frame):
        """Record the frame's line-referenced burst phase residual."""
        x = frame.astype(np.float64)
        phasors = []
        for k in range(40, 200, 2):
            seg = x[k * 910 + 74: k * 910 + 110]
            if len(seg) < 36:
                return
            n = np.arange(74, 110)
            b = np.mean((seg - np.mean(seg)) * np.exp(-0.5j * np.pi * n))
            phasors.append(b)
        p = np.sum(phasors)
        if np.abs(p) < 40 * len(phasors) / 4:
            return
        measured = np.degrees(np.angle(p)) % 360.0
        # the NTSC colour sequence alternates 180 degrees per frame (frames
        # A/B) — fold it out; the lock criterion is phase mod 180
        resid = (self.NTSC_LOCK_TARGET - measured + 90.0) % 180.0 - 90.0
        self._lock_residuals.append(float(resid))

    def _lock_state(self):
        """Decide the signal_state_preset from the measured residuals."""
        if len(self._lock_residuals) < max(1, self.frames_written // 2):
            return "STANDARD_STABLE_UNLOCKED"
        r = np.array(self._lock_residuals[1:] or self._lock_residuals)
        if np.max(np.abs(r)) <= self.LOCK_TOL:
            return "STANDARD_STABLE_LOCKED"
        return "STANDARD_STABLE_UNLOCKED"

    # -- extensions -------------------------------------------------------

    def _collect_dropouts(self, frame_id, fi_a, fi_b):
        fs = self.params["frame_samples"]
        for parity, fi in ((0, fi_a), (1, fi_b)):
            do = fi.get("dropOuts") if fi else None
            if not do or not do.get("fieldLine"):
                continue
            for line, sx, ex in zip(do["fieldLine"], do["startx"],
                                    do["endx"]):
                if self.system == "NTSC":
                    base = 0 if parity == 0 else 263 * 910
                    start = base + (int(line) - 1) * 910 + int(sx)
                    count = max(1, int(ex) - int(sx))
                else:
                    # Field display line 0 maps to frame line 0 (field A)
                    # or 313 (field B) — see downscale_cvbs; the interlace
                    # half-line lives in the vsync structure, not in the
                    # 0H spacing.
                    t = (int(line) - 1) + float(sx) / 1135.0
                    if parity:
                        t += 313.0
                    start = int(round(t * 709379.0 / 625.0))
                    count = max(1, int(round(float(ex) - float(sx))))
                if start < 0 or start >= fs:
                    continue
                count = min(count, fs - start)
                self.dropout_rows.append((frame_id, start, count, 100))

    def _collect_efm(self, frame_id, efm_a, efm_b, conf_a=None, conf_b=None):
        if not self.write_efm:
            return
        if self.f_efm is None:
            self.f_efm = open(self.fname_out + ".efm", "wb")
            if self.write_efm_conf:
                self.f_efmc = open(self.fname_out + ".efmc", "wb")
        count = 0
        for efm, conf in ((efm_a, conf_a), (efm_b, conf_b)):
            if efm is None:
                continue
            buf = efm.tobytes() if hasattr(efm, "tobytes") else bytes(efm)
            self.f_efm.write(buf)
            count += len(buf)
            if self.f_efmc is not None:
                # The spec requires .efmc byte-for-byte parallel to .efm;
                # a producer that cannot supply confidence for a t-value
                # must not emit the sidecar at all, so this is enforced.
                cbuf = (conf.tobytes() if hasattr(conf, "tobytes")
                        else bytes(conf)) if conf is not None else b""
                if len(cbuf) != len(buf):
                    raise ValueError(
                        ".efmc must be 1:1 with .efm (%d confidence bytes "
                        "for %d t-values)" % (len(cbuf), len(buf)))
                self.f_efmc.write(cbuf)
        self._efm_index.append((frame_id, self._efm_offset, count))
        self._efm_offset += count

    # -- audio ------------------------------------------------------------

    def audio_sample_target(self, n_frames):
        """Normative total stereo-sample count for n_frames of 48 kHz audio.

        PAL: 1920 samples/frame exactly.  NTSC/PAL_M: an 8008-sample,
        5-frame audio-frame sequence (1602/1601/1602/1601/1602), so
        offset(n) = 8008*(n // 5) + cumulative offset for (n % 5).
        """
        if self.system == "PAL":
            return 1920 * n_frames
        seq_offset = (0, 1602, 3203, 4805, 6406)
        return 8008 * (n_frames // 5) + seq_offset[n_frames % 5]

    def push_audio(self, data):
        if not self.write_audio:
            return
        if self.f_wav is None:
            self.f_wav = open(self.fname_out + "_audio_0.wav", "wb")
            self.f_wav.write(self._wav_header(0))
        buf = self._pack_s24(data)
        self.f_wav.write(buf)
        self._audio_bytes += len(buf)

    def _pack_s24(self, data):
        """Pack interleaved 24-bit stereo samples as 24-bit signed LE PCM.

        The analog audio decode is run at 24-bit for CVBS (bits=24), so it
        arrives as int32 holding genuine 24-bit values in [-2^23, 2^23).
        The little-endian int32 low 3 bytes are exactly that value as
        24-bit two's-complement LE.
        """
        if isinstance(data, (bytes, bytearray)):
            data = np.frombuffer(data, dtype=np.int32)
        a = np.ascontiguousarray(np.asarray(data, dtype=np.int32))
        return np.ascontiguousarray(
            a.view(np.uint8).reshape(-1, 4)[:, :3]).tobytes()

    def _wav_header(self, data_len):
        # spec: stereo 24-bit signed LE PCM at 48 kHz (SMPTE 272M profile)
        rate = self.AUDIO_RATE
        bits = self.AUDIO_BITS
        block_align = self.AUDIO_BYTES_PER_SAMPLE
        byte_rate = rate * block_align
        return b"".join([
            b"RIFF", struct.pack("<I", 36 + data_len), b"WAVE",
            b"fmt ", struct.pack("<IHHIIHH", 16, 1, 2, rate, byte_rate,
                                 block_align, bits),
            b"data", struct.pack("<I", data_len),
        ])

    def _finalise_audio(self):
        """Trim or zero-pad the WAV to the normative synchronous count.

        The 48 kHz decode is rate-synchronous, so this only ever adjusts a
        handful of samples of accumulated fractional slack to land on the
        exact per-preset offset(N) the spec requires.
        """
        bps = self.AUDIO_BYTES_PER_SAMPLE
        target_bytes = self.audio_sample_target(self.frames_written) * bps
        if self._audio_bytes > target_bytes:
            self.f_wav.seek(len(self._wav_header(0)) + target_bytes)
            self.f_wav.truncate()
            self._audio_bytes = target_bytes
        elif self._audio_bytes < target_bytes:
            self.f_wav.write(b"\x00" * (target_bytes - self._audio_bytes))
            self._audio_bytes = target_bytes

    # -- close ------------------------------------------------------------

    def close(self):
        if self.f_video is None:
            return
        self.f_video.close()
        self.f_video = None

        if self.f_wav is not None:
            self._finalise_audio()
            self.f_wav.seek(0)
            self.f_wav.write(self._wav_header(self._audio_bytes))
            self.f_wav.close()
            self.f_wav = None

        if self.f_efm is not None:
            self.f_efm.close()
            self.f_efm = None
            self._write_efm_meta()
        if self.f_efmc is not None:
            self.f_efmc.close()
            self.f_efmc = None

        if self.dropout_rows:
            self._write_dropouts_meta()

        state = self._lock_state()
        self._write_meta(state, self._sequence_continuous())

        if self.logger:
            r = self._lock_residuals
            seq = self._sequence_continuous()
            self.logger.info(
                "CVBS: wrote %d frames %s, %s, sequence %s (%d samples "
                "clamped, burst residual max %.2f deg over %d frames)",
                self.frames_written, self.sample_encoding, state,
                {1: "continuous", 0: "BROKEN"}.get(seq, "unknown"),
                self.clamped_samples,
                max((abs(v) for v in r), default=float("nan")), len(r))

    def _sequence_continuous(self):
        """Spec sequence_continuous value: 1 unbroken, 0 broken, None unknown."""
        if self.frames_written == 0:
            return None
        if self._seq_broken:
            return 0
        return 1 if self._phase_seen else None

    @staticmethod
    def _open_db(path):
        """Open a fresh SQLite sidecar configured for a single bulk write.

        The .meta / .dropouts.meta / .efm.meta databases are written once
        at close() and never read back during the decode; a killed run
        regenerates them wholesale, so crash-durability journalling buys
        nothing.  Turning it off is faster and leaves no -journal/-wal
        sidecar next to the output.
        """
        con = sqlite3.connect(path)
        con.execute("PRAGMA journal_mode = OFF")   # no rollback journal
        con.execute("PRAGMA synchronous = OFF")    # no fsync per commit
        con.execute("PRAGMA locking_mode = EXCLUSIVE")
        con.execute("PRAGMA temp_store = MEMORY")  # index builds in RAM
        return con

    def _write_meta(self, signal_state, sequence_continuous):
        # version strings look like "branch:describe[:dirty]"
        git_branch = git_commit = None
        if self.version:
            parts = str(self.version).split(":")
            git_branch = parts[0] or None
            if len(parts) > 1:
                git_commit = ":".join(parts[1:]) or None

        meta_path = self.fname_out + ".meta"
        if os.path.exists(meta_path):
            os.unlink(meta_path)
        con = self._open_db(meta_path)
        con.executescript(_META_SCHEMA)
        con.execute(
            """INSERT INTO cvbs_file (
                   preset, sample_encoding_preset, signal_state_preset,
                   sequence_continuous, signal_type, decoder, git_branch,
                   git_commit, number_of_sequential_frames, black_level,
                   has_nonstandard_values, capture_notes
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (self.system, self.sample_encoding, signal_state,
             sequence_continuous,
             "composite", "ld-decode", git_branch, git_commit,
             self.frames_written if self.frames_written else None,
             self.black_level, self.has_nonstandard_values,
             self.capture_notes))
        # one channel pair (stereo), SMPTE 272M channels 1 & 2 -> _audio_0.wav
        # (every row must correspond to an existing channel-pair file)
        if self._audio_bytes:
            con.execute(
                "INSERT INTO audio_channel_pair (channel_pair, description) "
                "VALUES (0, ?)", (self.audio_description,))
        con.commit()
        con.close()

    def _write_dropouts_meta(self):
        path = self.fname_out + ".dropouts.meta"
        if os.path.exists(path):
            os.unlink(path)
        con = self._open_db(path)
        con.executescript("""
            PRAGMA user_version = 5;
            CREATE TABLE dropout_run (
                cvbs_file_id    INTEGER NOT NULL,
                frame_id        INTEGER NOT NULL CHECK (frame_id >= 0),
                sample_start    INTEGER NOT NULL CHECK (sample_start >= 0),
                sample_count    INTEGER NOT NULL CHECK (sample_count > 0),
                severity        INTEGER NOT NULL
                    CHECK (severity >= 0 AND severity <= 100),
                PRIMARY KEY (cvbs_file_id, frame_id, sample_start)
            );
            CREATE INDEX idx_dropout_run_frame
                ON dropout_run (cvbs_file_id, frame_id);
        """)
        con.executemany(
            "INSERT OR IGNORE INTO dropout_run (cvbs_file_id, frame_id, "
            "sample_start, sample_count, severity) VALUES (1, ?, ?, ?, ?)",
            self.dropout_rows)
        con.commit()
        con.close()

    def _write_efm_meta(self):
        path = self.fname_out + ".efm.meta"
        if os.path.exists(path):
            os.unlink(path)
        con = self._open_db(path)
        con.executescript("""
            PRAGMA user_version = 1;
            CREATE TABLE efm_frame (
                cvbs_file_id    INTEGER NOT NULL,
                frame_id        INTEGER NOT NULL CHECK (frame_id >= 0),
                t_value_offset  INTEGER NOT NULL CHECK (t_value_offset >= 0),
                t_value_count   INTEGER NOT NULL CHECK (t_value_count >= 0),
                PRIMARY KEY (cvbs_file_id, frame_id)
            );
            CREATE INDEX idx_efm_frame_frame
                ON efm_frame (cvbs_file_id, frame_id);
        """)
        con.executemany(
            "INSERT INTO efm_frame (cvbs_file_id, frame_id, t_value_offset, "
            "t_value_count) VALUES (1, ?, ?, ?)",
            self._efm_index)
        con.commit()
        con.close()
