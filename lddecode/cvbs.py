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
    (SQLite, spec core schema), and optionally <basename>_audio_00.wav.

    Fields are paired into frames; only complete frames are written, and
    the sample stream is globally offset so 0H lands at the preset's
    digital-line position (SMPTE 244M / EBU 3280 line structure).
    """

    def __init__(self, fname_out, system, logger=None, version=None,
                 black_level=None, write_audio=False, audio_rate=44100,
                 audio_locked=None, capture_notes=None,
                 has_nonstandard_values=None):
        self.system = system
        self.params = CVBSParams_PAL if system == "PAL" else CVBSParams_NTSC
        self.fname_out = fname_out
        self.logger = logger

        self.f_video = open(fname_out + ".composite", "wb")

        # global stream offset: the stored frame begins in the previous
        # temporal line so that 0H lands at the preset's digital position
        if system == "NTSC":
            spl = self.params["samples_per_line"]
            # +1: the measured 50% crossing of the sinc-shaped sync edge
            # sits ~0.8 samples past the TBC lineloc; this centres the
            # stored 0H on the spec's 784.5 position
            self.stream_skip = int(round(spl - self.params["zero_h_sample"] + 0.5)) + 1
        else:
            # PAL: the field lattice streams start at line-0 0H; the stored
            # frame must start so 0H of frame line 1 lands at lattice
            # position 957.5 (EBU 3280).  Same +1 sinc-edge bias as NTSC.
            spl = 709379 / 625
            self.stream_skip = int(round(spl - self.params["zero_h_sample"] + 0.5)) + 1

        self._skipped = 0
        self._buf = []          # list of pending u16 arrays (temporal order)
        self._buflen = 0
        self._pending_first = None
        self._started = False
        self._fields_seen = 0
        self.frames_written = 0
        self.clamped_samples = 0

        lv = self.params["levels"]
        self.clamp_lo = 4 * 64
        self.clamp_hi = 1019 * 64
        self.blank16 = lv["blanking"] * 64

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

    def push_field(self, fi, picture, field=None):
        """Add one decoded field.  picture is the u16 TBC raster bytes/array.

        For NTSC the raster is the CVBS lattice already (orthogonal 4fsc);
        for PAL the caller must pass the non-orthogonal lattice samples
        produced by the CVBS assembler (step 4).
        """
        if self.system == "PAL":
            # the .tbc raster is line-locked; the CVBS lattice is not —
            # resample this field onto its portion of the frame lattice
            pic = field.downscale_cvbs()
        else:
            pic = np.frombuffer(picture, dtype=np.uint16) if isinstance(
                picture, (bytes, bytearray)) else picture

        is_first = bool(fi["isFirstField"])
        self._fields_seen += 1

        if not self._started:
            # start the file at the conventional sequence position:
            # a first field opening colour frame A (NTSC fieldPhaseID 1).
            # Give up after 8 fields rather than discard forever.
            phase_ok = (self.system != "NTSC"
                        or fi.get("fieldPhaseID") in (1, None)
                        or self._fields_seen > 8)
            if not (is_first and phase_ok):
                return
            self._started = True

        if is_first:
            if self._pending_first is not None and self.logger:
                self.logger.warning("CVBS: dropping unpaired first field")
            self._pending_first = pic
            return

        if self._pending_first is None:
            if self.logger:
                self.logger.warning("CVBS: dropping unpaired second field")
            return

        a, b = self._pending_first, pic
        self._pending_first = None
        self._emit_frame(a, b)

    def _emit_frame(self, first, second):
        """Queue the temporal sample stream of one frame and flush."""
        if self.system == "NTSC":
            spl = self.params["samples_per_line"]
            fl = (263, 262)   # SysParams field_lines
            frame = np.concatenate(
                [first[: fl[0] * spl], second[: fl[1] * spl]])
        else:
            # PAL: caller supplies exact per-field lattice streams
            frame = np.concatenate([first, second])

        self._queue(frame)

    def _queue(self, samples):
        if self._skipped < self.stream_skip:
            take = min(self.stream_skip - self._skipped, len(samples))
            samples = samples[take:]
            self._skipped += take
        if len(samples):
            self._buf.append(samples)
            self._buflen += len(samples)
        self._flush()

    def _flush(self, pad_final=False):
        fs = self.params["frame_samples"]
        if pad_final and 0 < self._buflen < fs:
            pad = np.full(fs - self._buflen, self.blank16, dtype=np.uint16)
            self._buf.append(pad)
            self._buflen = fs
        while self._buflen >= fs:
            buf = np.concatenate(self._buf) if len(self._buf) > 1 else self._buf[0]
            frame, rest = buf[:fs], buf[fs:]
            self._buf = [rest] if len(rest) else []
            self._buflen = len(rest)

            n_low = int(np.count_nonzero(frame < self.clamp_lo))
            n_high = int(np.count_nonzero(frame > self.clamp_hi))
            if n_low or n_high:
                self.clamped_samples += n_low + n_high
                frame = np.clip(frame, self.clamp_lo, self.clamp_hi)
            # CVBS_U16_4FSC: 10-bit values << 6 — force the 6 LSBs clear
            frame = (frame & 0xFFC0).astype("<u2")
            self.f_video.write(frame.tobytes())
            self.frames_written += 1

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
        self._flush(pad_final=True)
        self.f_video.close()
        self.f_video = None

        if self.f_wav is not None:
            self.f_wav.seek(0)
            self.f_wav.write(self._wav_header(self._audio_bytes))
            self.f_wav.close()
            self.f_wav = None

        self._write_meta()

        if self.logger:
            self.logger.info(
                "CVBS: wrote %d frames (%d samples clamped to legal range)",
                self.frames_written, self.clamped_samples)

    def _write_meta(self):
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
            (self.system, "CVBS_U16_4FSC", "STANDARD_TBC_UNLOCKED",
             "composite", "ld-decode", git_branch, git_commit,
             self.frames_written if self.frames_written else None,
             self.black_level, self.has_nonstandard_values,
             self.audio_locked, self.capture_notes))
        con.commit()
        con.close()
