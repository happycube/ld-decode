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
PRAGMA user_version = 8;

CREATE TABLE cvbs_file (
    cvbs_file_id                INTEGER PRIMARY KEY,
    preset                      TEXT    NOT NULL
        CHECK (preset IN ('NTSC', 'PAL', 'PAL_M')),
    sample_encoding_preset      TEXT    NOT NULL
        CHECK (sample_encoding_preset IN ('CVBS_U10_4FSC', 'CVBS_U16_4FSC', 'RAW_S16_28M', 'RAW_S16_40M', 'CVBS_TPG21_4FSC', 'CVBS_S16_FSC')),
    signal_state_preset         TEXT    NOT NULL
        CHECK (signal_state_preset IN (
            'STANDARD_TBC_LOCKED',
            'STANDARD_TBC_UNLOCKED',
            'STANDARD_RAW',
            'NONSTANDARD_TBC_LOCKED',
            'NONSTANDARD_TBC_UNLOCKED',
            'NONSTANDARD_RAW'
        )),
    signal_type                 TEXT    NOT NULL
        CHECK (signal_type IN ('composite', 'yc')),
    decoder                     TEXT    NOT NULL,
    git_branch                  TEXT,
    git_commit                  TEXT,
    number_of_sequential_frames INTEGER
        CHECK (number_of_sequential_frames IS NULL OR number_of_sequential_frames >= 1),
    black_level                 INTEGER,
    has_nonstandard_values      BOOLEAN,
    audio_locked                BOOLEAN,
    capture_notes               TEXT
);
"""


class CVBSWriter:
    """Assembles decoded fields into spec-compliant CVBS output.

    Writes <basename>.composite (u16le, CVBS_U16_4FSC), <basename>.meta
    (SQLite, spec core schema), optional <basename>_audio_00.wav, and the
    dropout / EFM extension sidecars (<basename>.dropouts.meta,
    <basename>.efm + .efm.meta).

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

    def __init__(self, fname_out, system, logger=None, version=None,
                 black_level=None, write_audio=False, audio_rate=44100,
                 audio_locked=None, capture_notes=None,
                 has_nonstandard_values=None, write_efm=False):
        self.system = system
        self.params = CVBSParams_PAL if system == "PAL" else CVBSParams_NTSC
        self.fname_out = fname_out
        self.logger = logger

        self.f_video = open(fname_out + ".composite", "wb")

        self._pending_first = None   # (field, fi, pic_or_None, efm)
        self._started = False
        self._fields_seen = 0
        self.frames_written = 0
        self.clamped_samples = 0

        lv = self.params["levels"]
        self.clamp_lo = 4 * 64
        self.clamp_hi = 1019 * 64
        self.blank16 = lv["blanking"] * 64

        # burst lock state
        self._pal_shift = 0.0          # lattice-sample lattice shift
        self._lock_initialised = False
        self._lock_residuals = []      # per-frame residual, degrees

        # extension sidecar state
        self.dropout_rows = []         # (frame_id, sample_start, count, sev)
        self.write_efm = write_efm
        self.f_efm = None
        self._efm_index = []           # (frame_id, offset, count)
        self._efm_offset = 0

        # metadata fields
        self.version = version or ""
        self.black_level = black_level
        self.capture_notes = capture_notes
        self.has_nonstandard_values = has_nonstandard_values

        # audio
        self.write_audio = write_audio
        self.audio_rate = audio_rate
        self.audio_locked = audio_locked
        self.f_wav = None
        self._audio_bytes = 0

    # -- video ------------------------------------------------------------

    def push_field(self, fi, picture, field=None, efm=None, audio=None):
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

        if is_first:
            if self._pending_first is not None and self.logger:
                self.logger.warning("CVBS: dropping unpaired first field")
            self._pending_first = (field, fi, picture, efm, audio)
            return

        if self._pending_first is None:
            if self.logger:
                self.logger.warning("CVBS: dropping unpaired second field")
            return

        pending = self._pending_first
        self._pending_first = None
        self._emit_frame(pending, (field, fi, picture, efm, audio))

    def _emit_frame(self, first, second):
        f_a, fi_a, pic_a, efm_a, aud_a = first
        f_b, fi_b, pic_b, efm_b, aud_b = second

        if self.system == "NTSC":
            a = self._as_u16(pic_a)
            b = self._as_u16(pic_b)
            spl = self.params["samples_per_line"]
            frame = np.concatenate([a[: 263 * spl], b[: 262 * spl]])
            self._measure_ntsc_lock(frame)
        else:
            # PAL: resample both fields onto the frame lattice with the
            # current lock shift.  On the first frame, measure and anchor
            # (one re-resample); afterwards track with small corrections.
            a = f_a.downscale_cvbs(self._pal_shift)
            if not self._lock_initialised:
                delta = self._pal_phase_error(a)
                if delta is not None:
                    self._pal_shift += delta / 90.0
                    a = f_a.downscale_cvbs(self._pal_shift)
                self._lock_initialised = True
            b = f_b.downscale_cvbs(self._pal_shift)
            frame = np.concatenate([a, b])

            resid = self._pal_phase_error(a)
            if resid is not None:
                self._lock_residuals.append(resid)
                # tracking: correct slow Sc/H drift, next frame
                self._pal_shift += np.clip(resid / 90.0, -0.05, 0.05)

        frame_id = self.frames_written
        self._write_frame(frame)
        self._collect_dropouts(frame_id, fi_a, fi_b)
        self._collect_efm(frame_id, efm_a, efm_b)
        for aud in (aud_a, aud_b):
            if aud is not None:
                self.push_audio(aud)

    def _as_u16(self, picture):
        return (np.frombuffer(picture, dtype=np.uint16)
                if isinstance(picture, (bytes, bytearray)) else picture)

    def _write_frame(self, frame):
        fs = self.params["frame_samples"]
        if len(frame) != fs:
            if self.logger:
                self.logger.warning(
                    "CVBS: frame size %d != %d, dropping", len(frame), fs)
            return
        n_out = int(np.count_nonzero((frame < self.clamp_lo)
                                     | (frame > self.clamp_hi)))
        if n_out:
            self.clamped_samples += n_out
            frame = np.clip(frame, self.clamp_lo, self.clamp_hi)
        # CVBS_U16_4FSC: 10-bit values << 6 — force the 6 LSBs clear
        frame = (frame & 0xFFC0).astype("<u2")
        self.f_video.write(frame.tobytes())
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
            return "STANDARD_TBC_UNLOCKED"
        r = np.array(self._lock_residuals[1:] or self._lock_residuals)
        if np.max(np.abs(r)) <= self.LOCK_TOL:
            return "STANDARD_TBC_LOCKED"
        return "STANDARD_TBC_UNLOCKED"

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
                    t = (int(line) - 1) + float(sx) / 1135.0
                    if parity:
                        t += 312.5
                    start = int(round(t * 709379.0 / 625.0))
                    count = max(1, int(round(float(ex) - float(sx))))
                if start < 0 or start >= fs:
                    continue
                count = min(count, fs - start)
                self.dropout_rows.append((frame_id, start, count, 100))

    def _collect_efm(self, frame_id, efm_a, efm_b):
        if not self.write_efm:
            return
        if self.f_efm is None:
            self.f_efm = open(self.fname_out + ".efm", "wb")
        count = 0
        for efm in (efm_a, efm_b):
            if efm is None:
                continue
            buf = efm.tobytes() if hasattr(efm, "tobytes") else bytes(efm)
            self.f_efm.write(buf)
            count += len(buf)
        self._efm_index.append((frame_id, self._efm_offset, count))
        self._efm_offset += count

    # -- audio ------------------------------------------------------------

    def push_audio(self, data):
        if not self.write_audio:
            return
        if self.f_wav is None:
            self.f_wav = open(self.fname_out + "_audio_00.wav", "wb")
            self.f_wav.write(self._wav_header(0))
        buf = data.tobytes() if hasattr(data, "tobytes") else bytes(data)
        self.f_wav.write(buf)
        self._audio_bytes += len(buf)

    def _wav_header(self, data_len):
        # spec: stereo s16le PCM; the integer header rate is 44056 for the
        # NTSC/PAL_M locked rational rate 44,100,000/1001
        rate = int(round(self.audio_rate))
        block_align = 4
        byte_rate = rate * block_align
        return b"".join([
            b"RIFF", struct.pack("<I", 36 + data_len), b"WAVE",
            b"fmt ", struct.pack("<IHHIIHH", 16, 1, 2, rate, byte_rate,
                                 block_align, 16),
            b"data", struct.pack("<I", data_len),
        ])

    # -- close ------------------------------------------------------------

    def close(self):
        if self.f_video is None:
            return
        self.f_video.close()
        self.f_video = None

        if self.f_wav is not None:
            self.f_wav.seek(0)
            self.f_wav.write(self._wav_header(self._audio_bytes))
            self.f_wav.close()
            self.f_wav = None

        if self.f_efm is not None:
            self.f_efm.close()
            self.f_efm = None
            self._write_efm_meta()

        if self.dropout_rows:
            self._write_dropouts_meta()

        state = self._lock_state()
        self._write_meta(state)

        if self.logger:
            r = self._lock_residuals
            self.logger.info(
                "CVBS: wrote %d frames, %s (%d samples clamped, burst "
                "residual max %.2f deg over %d frames)",
                self.frames_written, state, self.clamped_samples,
                max((abs(v) for v in r), default=float("nan")), len(r))

    def _write_meta(self, signal_state):
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
        con = sqlite3.connect(meta_path)
        con.executescript(_META_SCHEMA)
        con.execute(
            """INSERT INTO cvbs_file (
                   preset, sample_encoding_preset, signal_state_preset,
                   signal_type, decoder, git_branch, git_commit,
                   number_of_sequential_frames, black_level,
                   has_nonstandard_values, audio_locked, capture_notes
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (self.system, "CVBS_U16_4FSC", signal_state,
             "composite", "ld-decode", git_branch, git_commit,
             self.frames_written if self.frames_written else None,
             self.black_level, self.has_nonstandard_values,
             self.audio_locked, self.capture_notes))
        con.commit()
        con.close()

    def _write_dropouts_meta(self):
        path = self.fname_out + ".dropouts.meta"
        if os.path.exists(path):
            os.unlink(path)
        con = sqlite3.connect(path)
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
        con = sqlite3.connect(path)
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
