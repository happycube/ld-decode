"""The LDdecode top-level decoder / orchestrator.

Split verbatim out of core.py.
"""

import os
import sqlite3
import sys
import time
import traceback
from textwrap import dedent

import numpy as np
import scipy.fft as npfft

from . import efm_pll
from . import utils_logging as logs
from .profiling import profile
from .rfdecode import RFDecode
from .field import Field, FieldNTSC, FieldPAL
from .fileio import ac3_pipe, ldf_pipe
from .filters import inrange
from .dsp import FieldInfo, StridedCollector, nb_abs, nb_median, roundfloat


class LDdecode:
    def __init__(
        self,
        fname_in,
        fname_out,
        freader,
        _logger,
        est_frames=None,
        analog_audio=0,
        digital_audio=False,
        system="NTSC",
        doDOD=True,
        inputfreq=40,
        extra_options=None,
        DecoderParamsOverride=None
    ):
        if extra_options is None:
            extra_options = {}
        if DecoderParamsOverride is None:
            DecoderParamsOverride = {}

        self.logger = _logger
        logs.logger = self.logger
        self.reader_ended = False

        from lddecode import __version__
        self.version = __version__
        if fname_in == '-':
            self.infile = sys.stdin
        else:
            self.infile = open(fname_in, "rb")
        self.freader = freader

        self.est_frames = est_frames

        self.fields_written = 0

        self.blackIRE = 0

        self.start_time = time.time()
        self.second_decode = None
        self.use_profiler = extra_options.get("use_profiler", False)
        if self.use_profiler:
            from line_profiler import LineProfiler

            self.lpf = LineProfiler()
            self.lpf.add_function(Field.process)
            self.lpf.add_function(Field.compute_linelocs)
            self.lpf.add_function(Field.getpulses)
            self.lpf.add_function(LDdecode.demod_read)

        # Negative values are a multiple of the HSYNC frequency (line-locked
        # output, e.g. -2.8 for NTSC-locked ~44055.944hz) and must keep their
        # fractional part; positive values are a plain integer rate in hz.
        self.analog_audio = analog_audio if analog_audio < 0 else int(analog_audio)
        self.digital_audio = digital_audio
        self.ac3 = extra_options.get("AC3", False)
        self.write_rf_tbc = extra_options.get("write_RF_TBC", False)

        self.has_analog_audio = True
        if system == "PAL":
            if analog_audio == 0:
                self.has_analog_audio = False

        self.lastvalidfield = {False: None, True: None}
        self.lastFieldWritten = None

        self.outfile_video = None
        self.outfile_audio = None
        self.outfile_efm = None
        self.outfile_pre_efm = None
        self.outfile_ac3 = None
        self.ffmpeg_rftbc, self.outfile_rftbc = None, None
        self.do_rftbc = False

        self.output_cvbs = extra_options.get("output_cvbs", False)
        self.cvbs_writer = None

        if fname_out is not None:
            if self.output_cvbs:
                from .cvbs import CVBSWriter

                # NTSC line-locked 44100 is rate-locked to video but NOT at
                # the spec's rational locked rate; only the -N line-locked
                # mode (2.8 samples/line = 44,100,000/1001 Hz) qualifies.
                if system == "PAL":
                    aud_locked, aud_rate = True, 44100
                else:
                    aud_locked = analog_audio < 0
                    aud_rate = 44100000 / 1001 if aud_locked else 44100

                self.cvbs_writer = CVBSWriter(
                    fname_out, system, logger=_logger, version=self.version,
                    black_level=extra_options.get("cvbs_black_level"),
                    write_audio=bool(self.analog_audio),
                    audio_rate=aud_rate,
                    audio_locked=aud_locked if self.analog_audio else None,
                    capture_notes=(
                        "LaserDisc PAL: pilot burst may be present in blanking"
                        if system == "PAL" else None),
                    has_nonstandard_values=True if system == "PAL" else None,
                )
            else:
                self.outfile_video = open(fname_out + ".tbc", "wb")
                if self.analog_audio:
                    self.outfile_audio = open(fname_out + ".pcm", "wb")
            if self.digital_audio:
                # feed EFM stream into ld-ldstoefm
                self.efm_pll = efm_pll.EFM_PLL()
                self.outfile_efm = open(fname_out + ".efm", "wb")
                if extra_options.get("write_pre_efm", False):
                    self.outfile_pre_efm = open(fname_out + ".prefm", "wb")
            if self.write_rf_tbc:
                self.ffmpeg_rftbc, self.outfile_rftbc = ldf_pipe(fname_out + ".tbc.ldf")
                self.do_rftbc = True
            if self.ac3:
                self.AC3Collector = StridedCollector(cut_begin=1024, cut_end=0)
                self.ac3_processes, self.outfile_ac3 = ac3_pipe(fname_out + ".ac3")
                self.do_rftbc = True

            if self.output_cvbs:
                # CVBS mode replaces the .tbc video output and its sqlite
                # metadata; the spec .meta file is written by CVBSWriter.
                self.dbconn = None
            else:
                if os.path.exists(fname_out + '.tbc.db'):
                    os.unlink(fname_out + '.tbc.db')
                self.dbconn = sqlite3.connect(fname_out + '.tbc.db')
                self.create_db_schema()

        self.pipe_rftbc = extra_options.get("pipe_RF_TBC", None)
        if self.pipe_rftbc:
            self.do_rftbc = True

        self.fname_out = fname_out

        self.firstfield = None  # In frame output mode, the first field goes here
        self.capture_id = None

        self.system = system
        self.rf_opts = {
            'inputfreq':inputfreq,
            'system':system,
            'decode_analog_audio':analog_audio,
            'decode_digital_audio':digital_audio,
            'has_analog_audio':self.has_analog_audio,
            'extra_options':extra_options,
            'blocklen': 32 * 1024,
            'decoder_params_override': DecoderParamsOverride
        }

        self.rf = RFDecode(**self.rf_opts)

        # Steady-state reads cover one field plus margin.  Each field is
        # anchored to the previous field's end, so line0 lands only ~20-35 lines
        # into the buffer and compute_linelocs() (which needs sync pulses out to
        # proclines, ~273/325 lines past line0) is satisfied with ~25-30 lines of
        # slack.  The first field - and any re-acquisition with no previous field
        # to anchor on - has no such guarantee: line0 can be up to a full field
        # in, so readlen_first reads ~2 fields to reliably capture a whole field.
        if system == "PAL":
            self.FieldClass = FieldPAL
            self.readlen = self.rf.linelen * 340
            self.readlen_first = self.rf.linelen * 625
            self.clvfps = 25
        else:  # NTSC
            self.FieldClass = FieldNTSC
            self.readlen = ((self.rf.linelen * 300) // 16384) * 16384
            self.readlen_first = ((self.rf.linelen * 525) // 16384) * 16384
            self.clvfps = 30

        self.blocksize = self.rf.blocklen
        # Block size used when coalescing demodulated output: each loaded
        # block of blocklen samples overlaps its neighbour by the cut amounts.
        self.demod_blocksize = self.rf.blocklen - (self.rf.blockcut + self.rf.blockcut_end)

        self.output_lines = (self.rf.SysParams["frame_lines"] // 2) + 1

        self.bytes_per_frame = int(self.rf.freq_hz / self.rf.SysParams["FPS"])
        self.bytes_per_field = int(self.rf.freq_hz / (self.rf.SysParams["FPS"] * 2)) + 1
        self.outwidth = self.rf.SysParams["outlinelen"]

        self.fdoffset = 0
        self.mtf_level = 1

        self.fieldstack = [None, None, None, None]

        self.doDOD = doDOD

        self.fieldinfo = FieldInfo()

        self.leadIn = False
        self.leadOut = False
        self.isCLV = False
        self.frameNumber = None

        self.autoMTF = True
        self.useAGC = extra_options.get("useAGC", True)
        self.wow_level_adjust_smoothing = extra_options.get("wow_level_adjust_smoothing", 0)
        self.wow_interpolation_method = extra_options.get("wow_interpolation_method", "linear")

        self.auto_deemp = extra_options.get("auto_deemp", True)
        self.deemp_calibrated = not self.auto_deemp
        self._deemp_burst_samples = []
        self._deemp_burst_offset = None

        self.verboseVITS = extra_options.get("verboseVITS", False)

        self.bw_ratios = []

    def __del__(self):
        try:
            self._close_reader()
        except Exception:
            pass

    def _close_reader(self):
        """ Close the RF reader (e.g. the ffmpeg subprocess) to avoid warnings
            on exit.  Idempotent so close() and __del__ can both call it. """
        if getattr(self, "reader_ended", True):
            return
        self.reader_ended = True

        reader = getattr(self, "freader", None)
        if reader is not None and hasattr(reader, "_close") and callable(reader._close):
            reader._close()

    def close(self):
        """ deletes all open files, so it's possible to pickle an LDDecode object """

        if self.cvbs_writer is not None:
            try:
                self.cvbs_writer.close()
            except Exception:
                pass
            self.cvbs_writer = None

        if self.ffmpeg_rftbc is not None:
            try:
                self.ffmpeg_rftbc.kill()
            except Exception:
                pass

        # use setattr to force file closure by unlinking the objects
        for outfiles in [
            "infile",
            "outfile_video",
            "outfile_audio",
            "outfile_efm",
            "outfile_rftbc",
            "outfile_ac3",
        ]:
            setattr(self, outfiles, None)

        self._close_reader()

        # Refresh capture-level metadata with the final calibration values
        # (AGC may have adjusted levels after the first field) and commit.
        if hasattr(self, 'dbconn') and self.dbconn is not None:
            try:
                self.build_sqlite_metadata()
                self.dbconn.commit()
            except Exception:
                pass

        if self.use_profiler:
            self.lpf.print_stats()

        self.print_stats()

    def update_sqlite_field_count(self):
        if self.capture_id:
            self.dbconn.execute(
                "UPDATE capture SET number_of_sequential_fields = ? WHERE capture_id = ?",
                (len(self.fieldinfo), self.capture_id),
            )

    def create_db_schema(self):
        cur = self.dbconn.cursor()

        cur.executescript(dedent('''\
            PRAGMA user_version = 1;

            CREATE TABLE capture (
                capture_id INTEGER PRIMARY KEY,
                system TEXT NOT NULL CHECK (system IN ('NTSC','PAL','PAL_M')),
                decoder TEXT NOT NULL CHECK (decoder IN ('ld-decode','vhs-decode')),
                git_branch TEXT,
                git_commit TEXT,
                video_sample_rate REAL,
                active_video_start INTEGER,
                active_video_end INTEGER,
                field_width INTEGER,
                field_height INTEGER,
                number_of_sequential_fields INTEGER,
                colour_burst_start INTEGER,
                colour_burst_end INTEGER,
                is_mapped INTEGER CHECK (is_mapped IN (0,1)),
                is_subcarrier_locked INTEGER CHECK (is_subcarrier_locked IN (0,1)),
                is_widescreen INTEGER CHECK (is_widescreen IN (0,1)),
                white_16b_ire INTEGER,
                black_16b_ire INTEGER,
                blanking_16b_ire INTEGER,
                capture_notes TEXT
            );

            CREATE TABLE pcm_audio_parameters (
                capture_id INTEGER PRIMARY KEY REFERENCES capture(capture_id) ON DELETE CASCADE,
                bits INTEGER,
                is_signed INTEGER CHECK (is_signed IN (0,1)),
                is_little_endian INTEGER CHECK (is_little_endian IN (0,1)),
                sample_rate REAL
            );

            CREATE TABLE field_record (
                capture_id INTEGER NOT NULL REFERENCES capture(capture_id) ON DELETE CASCADE,
                field_id INTEGER NOT NULL,
                audio_samples INTEGER,
                decode_faults INTEGER,
                disk_loc REAL,
                efm_t_values INTEGER,
                field_phase_id INTEGER,
                file_loc INTEGER,
                is_first_field INTEGER CHECK (is_first_field IN (0,1)),
                median_burst_ire REAL,
                pad INTEGER CHECK (pad IN (0,1)),
                sync_conf INTEGER,
                ntsc_is_fm_code_data_valid INTEGER CHECK (ntsc_is_fm_code_data_valid IN (0,1)),
                ntsc_fm_code_data INTEGER,
                ntsc_field_flag INTEGER CHECK (ntsc_field_flag IN (0,1)),
                ntsc_is_video_id_data_valid INTEGER CHECK (ntsc_is_video_id_data_valid IN (0,1)),
                ntsc_video_id_data INTEGER,
                ntsc_white_flag INTEGER CHECK (ntsc_white_flag IN (0,1)),
                PRIMARY KEY (capture_id, field_id)
            );

            CREATE TABLE vits_metrics (
                capture_id INTEGER NOT NULL,
                field_id INTEGER NOT NULL,
                b_psnr REAL,
                w_snr REAL,
                b_psnr_weighted REAL,
                w_snr_weighted REAL,
                ntsc_line19_burst70_ire REAL,
                ntsc_line19_color_3d_raw_snr REAL,
                ntsc_line19_burst0_ire REAL,
                FOREIGN KEY (capture_id, field_id)
                    REFERENCES field_record(capture_id, field_id) ON DELETE CASCADE,
                PRIMARY KEY (capture_id, field_id)
            );

            CREATE TABLE vbi (
                capture_id INTEGER NOT NULL,
                field_id INTEGER NOT NULL,
                vbi0 INTEGER NOT NULL,
                vbi1 INTEGER NOT NULL,
                vbi2 INTEGER NOT NULL,
                FOREIGN KEY (capture_id, field_id)
                    REFERENCES field_record(capture_id, field_id) ON DELETE CASCADE,
                PRIMARY KEY (capture_id, field_id)
            );

            CREATE TABLE drop_outs (
                capture_id INTEGER NOT NULL,
                field_id INTEGER NOT NULL,
                field_line INTEGER NOT NULL,
                startx INTEGER NOT NULL,
                endx INTEGER NOT NULL,
                FOREIGN KEY (capture_id, field_id)
                    REFERENCES field_record(capture_id, field_id) ON DELETE CASCADE,
                PRIMARY KEY (capture_id, field_id, field_line, startx, endx)
            );

            CREATE TABLE vitc (
                capture_id INTEGER NOT NULL,
                field_id INTEGER NOT NULL,
                vitc0 INTEGER NOT NULL,
                vitc1 INTEGER NOT NULL,
                vitc2 INTEGER NOT NULL,
                vitc3 INTEGER NOT NULL,
                vitc4 INTEGER NOT NULL,
                vitc5 INTEGER NOT NULL,
                vitc6 INTEGER NOT NULL,
                vitc7 INTEGER NOT NULL,
                FOREIGN KEY (capture_id, field_id)
                    REFERENCES field_record(capture_id, field_id) ON DELETE CASCADE,
                PRIMARY KEY (capture_id, field_id)
            );

            CREATE TABLE closed_caption (
                capture_id INTEGER NOT NULL,
                field_id INTEGER NOT NULL,
                data0 INTEGER,
                data1 INTEGER,
                FOREIGN KEY (capture_id, field_id)
                    REFERENCES field_record(capture_id, field_id) ON DELETE CASCADE,
                PRIMARY KEY (capture_id, field_id)
            );
        '''))

        self.dbconn.commit()

        cur.close()

    def roughseek(self, location, isField=True):
        self.prevPhaseID = None

        self.fdoffset = location
        if isField:
            self.fdoffset *= self.bytes_per_field

    def checkMTF(self, field, pfield=None):
        oldmtf = self.mtf_level

        if not self.autoMTF:
            self.mtf_level = max(1 - ((self.frameNumber or 0) / 10000), 0)
        else:
            if len(self.bw_ratios) == 0:
                return True

            # scale for NTSC - 1.1 to 1.55
            self.mtf_level = np.clip((np.mean(self.bw_ratios) - 1.08) / 0.38, 0, 1)

        return np.abs(self.mtf_level - oldmtf) < 0.05

    def checkAutoDeemp(self, field):
        """Calibrate inverse-MTF chroma correction from burst amplitude.

        Returns True if no adjustment was needed, False if filters were
        recomputed (caller should redo the field).  Collects burst
        measurements over the first few fields (so MTF has time to settle),
        then calibrates once and stays locked.

        De-emphasis stays at full strength (1.0) for correct phase response.
        The inverse MTF filter is a zero-phase (real-valued) correction
        whose shape follows the disc's optical MTF; its strength is set so
        burst amplitude matches the spec value.
        """
        if self.deemp_calibrated:
            return True

        # NaN must not enter the sample pool: every comparison below fails
        # open for NaN and would lock in a NaN strength.
        if not np.isfinite(field.burstmedian) or field.burstmedian <= 5:
            return True

        # On a redo the same field comes through again (fdoffset unchanged);
        # replace its sample rather than double-counting it.
        if self._deemp_burst_offset == self.fdoffset and self._deemp_burst_samples:
            self._deemp_burst_samples[-1] = field.burstmedian
        else:
            self._deemp_burst_samples.append(field.burstmedian)
            self._deemp_burst_offset = self.fdoffset

        if len(self._deemp_burst_samples) < 3:
            return True

        expected = self.rf.SysParams["burst_ire"]
        measured = np.median(self._deemp_burst_samples)
        log_base = self.rf.inverse_mtf_log_at_fsc

        self.deemp_calibrated = True

        if not np.isfinite(measured) or measured <= 0 or log_base <= 0:
            return True

        if measured >= expected:
            return True

        strength = float(np.clip(
            np.log(expected / measured) / log_base, 0.0, 2.0
        ))

        if strength < 0.02:
            return True

        logs.logger.debug(
            f"Auto inverse-MTF chroma: burst {measured:.1f} IRE "
            f"(expected {expected:.1f}), "
            f"inverse_mtf_strength 0.000 → {strength:.3f}"
        )
        self.rf.DecoderParams["inverse_mtf_strength"] = strength
        self.rf.recompute_fvideo()
        return False

    @profile
    def detectLevels(self, field):
        # Returns sync level, 0IRE, and 100IRE levels of a field
        # computed from HSYNC areas and VITS

        sync_hzs = []
        ire0_hzs = []
        ire100_hzs = []

        for wl in (
            field.rf.SysParams['LD_VITS_whitelocs'] + field.rf.SysParams['LD_VITS_code_slices']
        ):
            # Code slice areas have a fourth value for percentile.
            ls = field.lineslice(*wl[:3])
            cut = field.data['video']['demod'][ls]
            freq = np.percentile(cut, 50 if len(wl) == 3 else wl[3])
            freq_ire = field.rf.hztoire(freq, spec=True)

            if inrange(freq_ire, 95, 110):
                ire100_hzs.append(freq)

        for line in range(12, self.output_lines):
            lsa = field.lineslice(line, 0.25, 4)

            begin_ire0 = field.rf.SysParams["colorBurstUS"][1]
            end_ire0 = field.rf.SysParams["activeVideoUS"][0]
            lsb = field.lineslice(line, begin_ire0 + 0.25, end_ire0 - begin_ire0 - 0.5)

            # compute wow adjustment
            thislinelen = (
                field.linelocs[line + field.lineoffset]
                - field.linelocs[line + field.lineoffset - 1]
            )
            adj = field.rf.linelen / thislinelen

            if inrange(adj, 0.98, 1.02):
                sync_hzs.append(nb_median(field.data["video"]["demod_05"][lsa]) / adj)
                ire0_hzs.append(nb_median(field.data["video"]["demod_05"][lsb]) / adj)

        # if any of the levels are missing, use the default levels
        vsync_hz   = self.rf.iretohz(self.rf.DecoderParams["vsync_ire"])

        m_synchz   = np.median(sync_hzs)   if len(sync_hzs)   else vsync_hz
        m_ire0hz   = np.median(ire0_hzs)   if len(ire0_hzs)   else self.rf.iretohz(0)
        m_ire100hz = np.median(ire100_hzs) if len(ire100_hzs) else self.rf.iretohz(100)

        return m_synchz, m_ire0hz, m_ire100hz

    def AC3filter(self, rftbc):
        self.AC3Collector.add(rftbc)

        blk = self.AC3Collector.get_block()
        while blk is not None:
            fftdata = np.fft.fft(blk)
            filtdata = np.fft.ifft(fftdata * self.rf.Filters['AC3']).real
            odata = self.AC3Collector.cut(filtdata)
            odata = np.clip(odata / 64, -100, 100)

            self.outfile_ac3.write(np.int8(odata))

            blk = self.AC3Collector.get_block()

    def writeout(self, dataset):
        f, fi, picture, audio, efm = dataset
        if self.digital_audio is True:
            if self.outfile_pre_efm is not None:
                self.outfile_pre_efm.write(efm.tobytes())

            efm_out = self.efm_pll.process(efm)
            self.outfile_efm.write(efm_out.tobytes())

        fi["audioSamples"] = 0 if audio is None else int(len(audio) / 2)
        fi["efmTValues"] = len(efm_out) if self.digital_audio else 0

        self.fieldinfo.append(fi)

        if self.dbconn is None:
            self._writeout_data(fi, picture, audio, f)
            return

        if not self.capture_id:
            self.build_sqlite_metadata()

        c_id = self.capture_id
        f_id = self.fields_written

        decodeFaults = None if fi.get('decodeFaults') == 0 else fi.get('decodeFaults')

        # Insert parent record into 'field_record'
        # We cast booleans to int because of the CHECK (val IN (0,1)) constraint
        self.dbconn.execute('''
            INSERT INTO field_record (
                capture_id, field_id, is_first_field, sync_conf, disk_loc,
                file_loc, median_burst_ire, field_phase_id, decode_faults,
                audio_samples, efm_t_values, pad
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (c_id, f_id, int(fi['isFirstField']), fi['syncConf'], fi['diskLoc'],
                fi['fileLoc'], fi['medianBurstIRE'], fi['fieldPhaseID'], decodeFaults,
                fi['audioSamples'], fi['efmTValues'], 0))

        if vitsMetrics := fi.get('vitsMetrics'):
            w_snr  = vitsMetrics.get('wSNR', 0)
            b_psnr = vitsMetrics.get('bPSNR', 0)
            w_snr_w  = vitsMetrics.get('wSNRw')
            b_psnr_w = vitsMetrics.get('bPSNRw')
            burst70 = vitsMetrics.get('ntscLine19Burst70IRE')
            snr3d   = vitsMetrics.get('ntscLine19Color3DRawSNR')
            burst0  = vitsMetrics.get('ntscLine19Burst0IRE')

            self.dbconn.execute('''
                INSERT INTO vits_metrics (
                    capture_id, field_id, w_snr, b_psnr,
                    w_snr_weighted, b_psnr_weighted,
                    ntsc_line19_burst70_ire, ntsc_line19_color_3d_raw_snr,
                    ntsc_line19_burst0_ire
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (c_id, f_id, w_snr, b_psnr, w_snr_w, b_psnr_w,
                 burst70, snr3d, burst0))

        # Insert VBI data if present
        vbi_data = fi.get("vbi", {}).get("vbiData", [])
        if vbi_data:
            vbi_row = (vbi_data + [0, 0, 0])[:3]
            self.dbconn.execute(
                "INSERT INTO vbi (capture_id, field_id, vbi0, vbi1, vbi2) VALUES (?, ?, ?, ?, ?)",
                (c_id, f_id, *vbi_row),
            )

        # Insert dropouts (if any) into 'drop_outs'
        if self.doDOD and fi.get("dropOuts"):
            dropout_lines = fi["dropOuts"]["fieldLine"]
            dropout_starts = fi["dropOuts"]["startx"]
            dropout_ends = fi["dropOuts"]["endx"]

            # Use executemany for cleaner/faster insertion of multiple rows
            dropout_data = [
                (c_id, f_id, line, start, end)
                for line, start, end in zip(dropout_lines, dropout_starts, dropout_ends)
            ]

            self.dbconn.executemany('''
                INSERT INTO drop_outs (
                    capture_id, field_id, field_line, startx, endx
                ) VALUES (?, ?, ?, ?, ?)''',
                dropout_data)

        self.update_sqlite_field_count()

        # Commit per field so the .tbc.db never trails the .tbc video if the
        # decode is killed mid-run.
        self.dbconn.commit()

        self._writeout_data(fi, picture, audio, f)

    def _writeout_data(self, fi, picture, audio, f):
        """Write the field's sample data (video/rf-tbc/audio outputs)."""
        if self.cvbs_writer is not None:
            self.cvbs_writer.push_field(fi, picture, f)
        else:
            self.outfile_video.write(picture)
        self.fields_written += 1

        if self.do_rftbc:
            rftbc = f.rf_tbc()

            if self.outfile_rftbc is not None:
                self.outfile_rftbc.write(rftbc)

            if self.outfile_ac3 is not None:
                self.AC3filter(rftbc)

            if self.pipe_rftbc is not None:
                self.pipe_rftbc.send(rftbc)

        if audio is not None:
            if self.cvbs_writer is not None:
                self.cvbs_writer.push_audio(audio)
            elif self.outfile_audio is not None:
                self.outfile_audio.write(audio)

    @profile
    def demod_read(self, begin, length, MTF=0):
        """ Read each input block, demodulate it, and concatenate the per-block
            outputs into contiguous arrays for further processing.  Returns None
            at EOF. """
        blocksize = self.demod_blocksize
        t = {"input": [], "video": [], "audio": [], "efm": [], "rfhpf": []}

        end = begin + length

        for b in range(begin // blocksize, (end // blocksize) + 1):
            rawinput = self.freader(self.infile, b * blocksize, self.rf.blocklen)
            if rawinput is None or len(rawinput) < self.rf.blocklen:
                # EOF
                return None

            demod = self.rf.demodblock(
                data=rawinput,
                fftdata=npfft.fft(rawinput),
                mtf_level=MTF,
                cut=True,
            )

            t["input"].append(rawinput[self.rf.blockcut : -self.rf.blockcut_end])
            for k in ("video", "audio", "efm", "rfhpf"):
                if k in demod:
                    t[k].append(demod[k])

        rv = {}
        for k in t.keys():
            rv[k] = np.concatenate(t[k]) if len(t[k]) else None

        if rv["audio"] is not None:
            rv["audio_phase1"] = rv["audio"]
            rv["audio"] = self.rf.audio_phase2(rv["audio"])

        rv["startloc"] = (begin // blocksize) * blocksize

        return rv

    @profile
    def decodefield(self, start, mtf_level, prevfield=None, initphase=False):
        """ returns field object if valid, and the offset to the next decode """

        readloc = int(start - self.rf.blockcut)
        if readloc < 0:
            readloc = 0

        # With no previous field to anchor on (first field, or re-acquisition
        # after a dropped field) line0 can be far into the buffer, so read more
        # to capture the whole field rather than dropping and re-seeking it.
        readlen = self.readlen_first if prevfield is None else self.readlen

        readloc_block = readloc // self.blocksize
        numblocks = (readlen // self.blocksize) + 2

        rawdecode = self.demod_read(
            readloc_block * self.blocksize,
            numblocks * self.blocksize,
            mtf_level,
        )

        if rawdecode is None:
            # logs.logger.info("Failed to demodulate data")
            return None, None

        f = self.FieldClass(
            self.rf,
            rawdecode,
            prevfield=prevfield,
            initphase=initphase,
            fields_written=self.fields_written,
            readloc=rawdecode["startloc"],
            wow_level_adjust_smoothing=self.wow_level_adjust_smoothing,
            wow_interpolation_method=self.wow_interpolation_method
        )

        # set an object-level variable to make notebook debugging easier
        self.curfield = f

        if self.use_profiler:
            if not getattr(self, '_profiler_fields_added', False):
                if self.system == 'NTSC':
                    self.lpf.add_function(f.refine_linelocs_burst)
                    self.lpf.add_function(f.compute_burst_offsets)

                self.lpf.add_function(f.get_linelen)
                self.lpf.add_function(f.get_burstlevel)
                self.lpf.add_function(f.compute_line_bursts)
                self._profiler_fields_added = True
            lpf_wrapper = self.lpf(f.process)
        else:
            lpf_wrapper = f.process

        lpf_wrapper()

        offset = f.nextfieldoffset - (readloc - rawdecode["startloc"])

        if not f.valid:
            # logs.logger.info("Bad data - jumping one second")
            offset = f.nextfieldoffset

        return f, offset

    def _adjust_agc(self, f, redo):
        if not (self.useAGC and f.isFirstField and f.sync_confidence > 80):
            return redo

        sync_hz, ire0_hz, ire100_hz = self.detectLevels(f)

        actualwhiteIRE = f.rf.hztoire(ire100_hz)

        sync_ire_diff = nb_abs(self.rf.hztoire(sync_hz) - self.rf.DecoderParams["vsync_ire"])
        whitediff = nb_abs(self.rf.hztoire(ire100_hz) - actualwhiteIRE)
        ire0_diff = nb_abs(self.rf.hztoire(ire0_hz))

        acceptable_diff = 2 if self.fields_written else 0.5

        if max((whitediff, ire0_diff, sync_ire_diff)) > acceptable_diff:
            hz_ire = (ire100_hz - ire0_hz) / 100
            vsync_ire = (sync_hz - ire0_hz) / hz_ire

            if vsync_ire > -20:
                logs.logger.warning(
                    f"At field #{len(self.fieldinfo)}, Auto-level detection malfunction "
                    f"(vsync IRE computed at {np.round(vsync_ire, 2)}, nominal ~= -40), "
                    f"possible disk skipping"
                )
            else:
                self.rf.DecoderParams["ire0"] = ire0_hz
                # Note that vsync_ire is a negative number, so (sync_hz - ire0_hz) is correct
                self.rf.DecoderParams["hz_ire"] = hz_ire
                self.rf.DecoderParams["vsync_ire"] = vsync_ire
                return True

        return redo

    @profile
    def readfield(self, initphase=False):
        adjusted = False
        picture = audio = efm = None

        if len(self.fieldstack) >= 4:
            # XXX: Need to cut off the previous field here, since otherwise
            # it'll leak for now.
            if self.fieldstack[-1]:
                self.fieldstack[-1].prevfield = None

            self.fieldstack.pop(-1)

        # Decode-then-process, one field at a time.  self.fdoffset is the file
        # offset of the field to decode; prevfield anchors the next field's sync
        # search.  On a redo we re-decode the *same* field (fdoffset unchanged)
        # with the parameters checkMTF()/AGC just adjusted.  Decoding is now
        # synchronous, so there is no look-ahead - this also changes which
        # mtf_level a field sees vs. the old one-field-ahead pipeline.
        prevfield = self.fieldstack[0]

        while True:
            if self.second_decode is None and self.fields_written:
                self.second_decode = time.time()

            f, offset = self.decodefield(self.fdoffset, self.mtf_level, prevfield, initphase)

            if f is None:
                # EOF / failed demod (decodefield returns (None, None))
                self.fieldstack.insert(0, None)
                return None

            if not f.valid:
                # Bad field - skip past it and try the next one, unanchored.
                self.fdoffset += offset
                prevfield = None
                continue

            picture, audio, efm = f.downscale(
                linesout=self.output_lines,
                final=True,
                audio=self.analog_audio,
                lastfieldwritten=self.lastFieldWritten,
            )

            metrics = self.computeMetrics(f, None, verbose=True)
            if "blackToWhiteRFRatio" in metrics and not adjusted:
                keep = 900 if self.isCLV else 30
                self.bw_ratios.append(metrics["blackToWhiteRFRatio"])
                self.bw_ratios = self.bw_ratios[-keep:]

            redo = f.needrerun or not self.checkMTF(f, self.fieldstack[0])
            redo = redo or not self.checkAutoDeemp(f)

            agc_adjusted = self._adjust_agc(f, False)
            redo = redo or agc_adjusted

            # Allow one redo only: re-decode this same field with adjusted params.
            if not adjusted and redo:
                adjusted = True
                if agc_adjusted and not self.deemp_calibrated:
                    # The AGC just rewrote ire0/hz_ire, so burst samples
                    # measured under the old levels are not comparable.
                    self._deemp_burst_samples.clear()
                    self._deemp_burst_offset = None
                prevfield = self.fieldstack[0]
                continue

            fieldlength = f.linelocs[self.output_lines] - f.linelocs[0]
            fieldlength /= f.inlinelen
            if ((f.sync_confidence < 50) and not
                 inrange(fieldlength, self.output_lines - 2, self.output_lines + 2)):
                logs.logger.warning("WARNING: Possible player skip detected - check output")

            self.fieldstack.insert(0, f)
            self.fdoffset += offset
            break

        if f is None or not f.valid:
            return None

        if self.fname_out is not None:
            # Only write a FirstField first
            if len(self.fieldinfo) == 0 and not f.isFirstField:
                return f

            # XXX: this routine currently performs a needed sanity check
            fi, needFiller = self.buildmetadata(f)

            self.lastvalidfield[f.isFirstField] = (f, fi, picture, audio, efm)

            if needFiller:
                if self.lastvalidfield[not f.isFirstField] is not None:
                    self.writeout(self.lastvalidfield[not f.isFirstField])
                    self.writeout(self.lastvalidfield[f.isFirstField])

                # If this is the first field to be written, don't write anything
                return f

            self.lastFieldWritten = (self.fields_written, f.readloc)
            self.writeout(self.lastvalidfield[f.isFirstField])

        return f

    def print_stats(self):
        if self.fields_written:
            timeused = time.time() - self.start_time
            timeused2 = time.time() - self.second_decode
            frames = self.fields_written // 2
            fps = frames / timeused2

            logs.logger.info(
                f"Took {timeused:.2f} seconds to decode {frames} frames ({fps:.2f} FPS post-setup)"
            )

    def decodeFrameNumber(self, f1, f2):
        """ decode frame #/information from Philips code data on both fields """

        # CLV
        self.isCLV = False
        self.earlyCLV = False
        self.clvMinutes = None
        self.clvSeconds = None
        self.clvFrameNum = None

        def decodeBCD(bcd):
            """Read a BCD-encoded number.
            Raise ValueError if any of the digits aren't valid BCD."""

            if bcd == 0:
                return 0
            else:
                digit = bcd & 0xF
                if digit > 9:
                    raise ValueError("Non-decimal BCD digit")
                return (10 * decodeBCD(bcd >> 4)) + digit

        leadoutCount = 0

        for linecode in f1.linecode + f2.linecode:
            if linecode is None:
                continue

            if linecode == 0x80EEEE:  # lead-out reached
                leadoutCount += 1
                # Require two leadouts, since there may only be one field in the raw data w/it
                if leadoutCount == 2:
                    self.leadOut = True
            elif linecode == 0x88FFFF:  # lead-in
                self.leadIn = True
            elif (linecode & 0xF0DD00) == 0xF0DD00:  # CLV minutes/hours
                try:
                    self.clvMinutes = decodeBCD(linecode & 0xFF) + (
                        decodeBCD((linecode >> 16) & 0xF) * 60
                    )
                    self.isCLV = True
                except ValueError:
                    pass
            elif (linecode & 0xF00000) == 0xF00000:  # CAV frame
                # Ignore the top bit of the first digit, used for PSC
                try:
                    rv = decodeBCD(linecode & 0x7FFFF)
                    self.isCLV = False
                    return rv
                except ValueError:
                    pass
            elif (linecode & 0x80F000) == 0x80E000:  # CLV picture #
                try:
                    sec1s = decodeBCD((linecode >> 8) & 0xF)
                    sec10s = ((linecode >> 16) & 0xF) - 0xA
                    if sec10s < 0:
                        raise ValueError("Digit 2 not in range A-F")

                    self.clvFrameNum = decodeBCD(linecode & 0xFF)
                    self.clvSeconds = sec1s + (10 * sec10s)
                    self.isCLV = True
                except ValueError:
                    pass

            if self.clvMinutes is not None:
                minute_seconds = self.clvMinutes * 60

                if self.clvSeconds is not None:  # newer CLV
                    # XXX: does not auto-decrement for skip frames
                    return (
                        (minute_seconds + self.clvSeconds) * self.clvfps
                    ) + self.clvFrameNum
                else:
                    self.earlyCLV = True
                    return minute_seconds

        return None  # seeking won't work w/minutes only

    def computeMetrics(self, f, fp=None, verbose=False):
        from .metrics import computeMetrics
        return computeMetrics(self.rf, f, fp, verbose, self.verboseVITS)

    @profile
    def buildmetadata(self, f, check_phase=True):
        """ returns field information dict and whether or not a backfill field is needed """
        prevfi = self.fieldinfo[-1] if len(self.fieldinfo) else None

        fi = {
            "isFirstField": bool(f.isFirstField),
            "syncConf": f.compute_syncconf(),
            "seqNo": len(self.fieldinfo) + 1,
            "diskLoc": np.round((f.readloc / self.bytes_per_field) * 10) / 10,
            "fileLoc": int(np.floor(f.readloc)),
            "medianBurstIRE": roundfloat(f.burstmedian),
        }

        if self.doDOD:
            dropout_lines, dropout_starts, dropout_ends = f.dropout_detect()
            if len(dropout_lines):
                fi["dropOuts"] = {
                    "fieldLine": dropout_lines,
                    "startx": dropout_starts,
                    "endx": dropout_ends,
                }

        # This is a bitmap, not a counter
        decodeFaults = 0

        fi["fieldPhaseID"] = f.fieldPhaseID

        if prevfi is not None:
            is_phase_sequential = (
                (
                    fi["fieldPhaseID"] == 1
                    and prevfi["fieldPhaseID"] == f.rf.SysParams["fieldPhases"]
                )
                or (fi["fieldPhaseID"] == prevfi["fieldPhaseID"] + 1)
            )
            if check_phase and not is_phase_sequential:
                logs.logger.warning(
                    f"At field #{len(self.fieldinfo)}, Field phaseID sequence mismatch "
                    f"({prevfi['fieldPhaseID']}->{fi['fieldPhaseID']}) (player may be paused)"
                )
                decodeFaults |= 2

            if prevfi["isFirstField"] == fi["isFirstField"]:
                # logs.logger.info('WARNING!  isFirstField stuck between fields')
                if inrange(fi["diskLoc"] - prevfi["diskLoc"], 0.95, 1.05):
                    decodeFaults |= 1
                    fi["isFirstField"] = not prevfi["isFirstField"]
                    fi["syncConf"] = 10
                else:
                    logs.logger.error("Skipped field")
                    decodeFaults |= 4
                    fi["syncConf"] = 0
                    return fi, True

        fi["decodeFaults"] = decodeFaults
        fp_3d = self.fieldstack[2] if len(self.fieldinfo) >= 3 else None
        fi["vitsMetrics"] = self.computeMetrics(self.fieldstack[0], fp_3d)

        fi["vbi"] = {"vbiData": [int(lc) for lc in f.linecode if lc is not None]}

        self.frameNumber = None
        if f.isFirstField:
            self.firstfield = f
        else:
            # use a stored first field, in case we start with a second field
            if self.firstfield is not None:
                # process VBI frame info data
                self.frameNumber = self.decodeFrameNumber(self.firstfield, f)

                rawloc = np.floor((f.readloc / self.bytes_per_field) / 2)

                disk_Type = "CLV" if self.isCLV else "CAV"
                disk_TimeCode = None
                disk_Frame = None
                special = None

                try:
                    if self.isCLV and self.earlyCLV:  # early CLV
                        disk_TimeCode = f"{self.clvMinutes}:xx"

                    elif (
                        self.isCLV
                        and self.frameNumber is not None
                        and self.clvMinutes is not None
                    ):
                        disk_TimeCode = (
                            f"{self.clvMinutes}:{self.clvSeconds:02d}.{self.clvFrameNum:02d} "
                            f"Frame #{self.frameNumber}"
                        )
                    elif self.frameNumber:

                        disk_Frame = f"{self.frameNumber}"
                    elif self.leadIn:
                        special = "Lead In"
                    elif self.leadOut:
                        special = "Lead Out"
                    else:
                        special = "Pulldown/Telecine Frame"

                    if self.est_frames is not None:
                        outstr = (
                            f"Frame {(self.fields_written//2)+1}/{int(self.est_frames)}: "
                            f"File Frame {int(rawloc)}: {disk_Type} "
                        )
                    else:
                        outstr = f"File Frame {int(rawloc)}: {disk_Type} "
                    if self.isCLV and disk_TimeCode:
                        outstr += f"Timecode {disk_TimeCode} "
                    elif disk_Frame:
                        outstr += f"Frame #{disk_Frame} "


                    if special is not None:
                        outstr += special

                    self.logger.status(outstr)
                except Exception:
                    logs.logger.warning("file frame %d : VBI decoding error", rawloc)
                    traceback.print_exc()

        return fi, False

    def seek_getframenr(self, startfield):
        """ Reads from file location startfield, returns first VBI frame # or None on failure
        and revised startfield """

        """ Note that if startfield is not 0, and the read fails, it will automatically retry
            at file location 0
        """

        curfield = None
        prevfield = None

        self.roughseek(startfield)

        for fields in range(10):
            f, offset = self.decodefield(self.fdoffset, 0)

            if f is None:
                # If given an invalid starting location (i.e. seeking to a frame in an already cut
                # raw file),
                # go back to the beginning and try again.
                if startfield != 0:
                    startfield = 0
                    self.roughseek(startfield)
                else:
                    return None, startfield, None
            elif not f.valid:
                self.fdoffset += offset
            else:
                prevfield = curfield
                curfield = f
                self.fdoffset += offset

                # Two fields are needed to be sure to have sufficient Philips code data
                # to determine frame #.
                if prevfield is not None and f.valid:
                    fnum = self.decodeFrameNumber(prevfield, curfield)

                    if self.earlyCLV:
                        logs.logger.error("Cannot seek in early CLV disks w/o timecode")
                        return None, startfield, None
                    elif fnum is not None:
                        rawloc = np.floor((f.readloc / self.bytes_per_field) / 2)
                        logs.logger.info("seeking: file loc %d frame # %d", rawloc, fnum)

                        return fnum, startfield, f.readloc

        return None, None, None

    def seek(self, startframe, target):
        """ Attempts to find frame target from file location startframe """
        logs.logger.info("Beginning seek")

        if not sys.warnoptions:
            import warnings

            warnings.simplefilter("ignore")

        curfield = startframe * 2

        for retries in range(3):
            fnr, curfield, readloc = self.seek_getframenr(curfield)
            if fnr is None:
                return None

            cur = int((readloc / self.bytes_per_field))
            if fnr == target:
                logs.logger.info("Finished seek")
                logs.logger.info("Finished seeking, starting at frame %d", fnr)
                self.roughseek(cur)
                return cur

            curfield += ((target - fnr) * 2) - 1

        return None

    def build_sqlite_metadata(self):
        cursor = self.dbconn.cursor()

        for f in self.fieldstack:
            if f:
                break

        if not f:
            return

        git_branch = git_commit = ""
        if isinstance(self.version, str) and self.version:
            if ":" in self.version:
                git_branch, _, git_commit = self.version.partition(":")
            elif "/" in self.version and self.version.count("/") == 1:
                git_branch, git_commit = self.version.split("/", 1)
            elif "+git." in self.version:
                git_commit = self.version.split("+git.", 1)[1].split(".", 1)[0]
                git_branch = "release"

        spu = f.rf.SysParams["outfreq"]
        badj = -1.4

        video_values = (
            f.rf.system, 'ld-decode',
            git_branch, git_commit,
            spu * 1000000,
            int(np.round(f.rf.SysParams["activeVideoUS"][0] * spu + badj)),
            int(np.round(f.rf.SysParams["activeVideoUS"][1] * spu + badj)),
            f.rf.SysParams["outlinelen"], f.outlinecount, len(self.fieldinfo),
            int(np.round(f.rf.SysParams["colorBurstUS"][0] * spu + badj)),
            int(np.round(f.rf.SysParams["colorBurstUS"][1] * spu + badj)),
            float(f.hz_to_output(f.rf.iretohz(100))),
            float(f.hz_to_output(f.rf.iretohz(self.blackIRE))),
            float(f.hz_to_output(f.rf.iretohz(0))),
            0, f.rf.system == "NTSC", 0,
        )

        # capture_id is None on the first call (SQLite assigns the rowid);
        # later calls pass the existing id so ON CONFLICT refreshes the row
        # with the final calibration values.
        cursor.execute("""
            INSERT INTO capture (
                capture_id,
                system, decoder, git_branch, git_commit,
                video_sample_rate, active_video_start, active_video_end,
                field_width, field_height, number_of_sequential_fields,
                colour_burst_start, colour_burst_end,
                white_16b_ire, black_16b_ire, blanking_16b_ire,
                is_mapped, is_subcarrier_locked, is_widescreen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(capture_id) DO UPDATE SET
                system=excluded.system, decoder=excluded.decoder,
                git_branch=excluded.git_branch, git_commit=excluded.git_commit,
                video_sample_rate=excluded.video_sample_rate,
                active_video_start=excluded.active_video_start,
                active_video_end=excluded.active_video_end,
                field_width=excluded.field_width, field_height=excluded.field_height,
                number_of_sequential_fields=excluded.number_of_sequential_fields,
                colour_burst_start=excluded.colour_burst_start,
                colour_burst_end=excluded.colour_burst_end,
                white_16b_ire=excluded.white_16b_ire,
                black_16b_ire=excluded.black_16b_ire,
                blanking_16b_ire=excluded.blanking_16b_ire,
                is_mapped=excluded.is_mapped,
                is_subcarrier_locked=excluded.is_subcarrier_locked,
                is_widescreen=excluded.is_widescreen
        """, (self.capture_id,) + video_values)

        if not self.capture_id:
            self.capture_id = cursor.lastrowid

        if self.analog_audio < 0:
            audio_sample_rate = (1000000 / self.rf.SysParams["line_period"]) * -self.analog_audio
        else:
            audio_sample_rate = self.analog_audio

        pcm_values = (16, 1, 1, audio_sample_rate)

        cursor.execute("""
            INSERT INTO pcm_audio_parameters (
                capture_id, bits, is_little_endian, is_signed, sample_rate
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(capture_id) DO UPDATE SET
                bits=excluded.bits, is_little_endian=excluded.is_little_endian,
                is_signed=excluded.is_signed, sample_rate=excluded.sample_rate
        """, (self.capture_id,) + pcm_values)

        self.dbconn.commit()
        cursor.close()
