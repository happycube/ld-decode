import os
import time
import numpy as np
import traceback
import scipy.signal as sps
from collections import namedtuple

import lddecode.core as ldd

# from lddecode.core import npfft
# Use numpy fft rather than scipy fft as is imported in lddecode core as it seems to be slightly faster.
import numpy.fft as npfft

import lddecode.utils as lddu
import vhsdecode.utils as utils
from vhsdecode.utils import StackableMA, filtfft
from vhsdecode.chroma import demod_chroma_filt

import vhsdecode.formats as vhs_formats

from vhsdecode.addons.chromasep import ChromaSepClass
from vhsdecode.addons.resync import Resync
from vhsdecode.addons.chromaAFC import ChromaAFC

from vhsdecode.demod import replace_spikes, unwrap_hilbert, smooth_spikes

from vhsdecode.field import field_class_from_formats
from vhsdecode.video_eq import VideoEQ
from vhsdecode.doc import DodOptions
from vhsdecode.field_averages import FieldAverage
from vhsdecode.load_params_json import override_params
from vhsdecode.nonlinear_filter import sub_deemphasis
from vhsdecode.compute_video_filters import (
    gen_video_main_deemp_fft_params,
    gen_video_lpf_params,
    gen_nonlinear_bandpass_params,
    gen_nonlinear_amplitude_lpf,
    gen_custom_video_filters,
    create_sub_emphasis_params,
    gen_video_lpf_supergauss_params,
    gen_bpf_supergauss,
    gen_fm_audio_notch_params,
    NONLINEAR_AMP_LPF_FREQ_DEFAULT,
)
from vhsdecode import compute_video_filters as cvf
from vhsdecode.demodcache import DemodCacheTape


def is_secam(system: str):
    return system == "SECAM" or system == "MESECAM"


def _computefilters_dummy(self):
    self.Filters = {}
    # Needs to be defined here as it's referenced in constructor.
    self.Filters["F05_offset"] = 32


# HACK - override this in a hacky way for now to skip generating some filters we don't use.
# including one that requires > 20 mhz sample rate.
ldd.RFDecode.computefilters = _computefilters_dummy


def _demodcache_dummy(self, *args, **kwargs):
    self.ended = True
    pass


# Superclass to override laserdisc-specific parts of ld-decode with stuff that works for VHS
#
# We do this simply by using inheritance and overriding functions. This results in some redundant
# work that is later overridden, but avoids altering any ld-decode code to ease merging back in
# later as the ld-decode is in flux at the moment.
class VHSDecode(ldd.LDdecode):
    def __init__(
        self,
        fname_in,
        fname_out,
        freader,
        logger,
        system="NTSC",
        tape_format="VHS",
        doDOD=True,
        threads=1,
        inputfreq=40,
        level_adjust=0,
        rf_options={},
        extra_options={},
        debug_plot=None,
    ):

        # monkey patch init with a dummy to prevent calling set_start_method twice on macos
        # and not create extra threads.
        # This is kinda hacky and should be sorted in a better way ideally.
        temp_init = ldd.DemodCache.__init__
        ldd.DemodCache.__init__ = _demodcache_dummy

        if system == "405":
            sys_params_pal_temp = ldd.SysParams_PAL.copy()
            # If we are using 405-line we need to override this so the superclasses are initialized with the right values.
            ldd.SysParams_PAL = vhs_formats.get_sys_params_405()

        super(VHSDecode, self).__init__(
            fname_in,
            fname_out,
            freader,
            logger,
            analog_audio=False,
            system=vhs_formats.parent_system(system),
            doDOD=doDOD,
            threads=threads,
            inputfreq=inputfreq,
            extra_options=extra_options,
        )

        # Adjustment for output to avoid clipping.
        self.level_adjust = level_adjust
        # Overwrite the rf  with the VHS-altered one
        self.rf = VHSRFDecode(
            system=system,
            tape_format=tape_format,
            inputfreq=inputfreq,
            rf_options=rf_options,
            extra_options=extra_options,
            debug_plot=debug_plot,
        )

        if system == "405":
            SysParams_PAL = sys_params_pal_temp

        # Store reference to ourself in the rf decoder - needed to access data location for track
        # phase, may want to do this in a better way later.
        self.rf.decoder = self
        self.FieldClass = field_class_from_formats(system, tape_format)

        # Restore init functino now that superclass constructor is finished.
        ldd.DemodCache.__init__ = temp_init

        self.demodcache = DemodCacheTape(
            self.rf,
            self.infile,
            self.freader,
            self.rf_opts,
            num_worker_threads=self.numthreads,
        )

        if fname_out is not None and self.rf.options.write_chroma:
            self.outfile_chroma = open(fname_out + "_chroma.tbc", "wb")
        else:
            self.outfile_chroma = None

        self.debug_plot = debug_plot

        # Needs to be overridden since this is overwritten for 405-line.
        # self.output_lines = (self.rf.SysParams["frame_lines"] // 2) + 1
        # Not modified as of now but may be tweaked for 405-line later
        # self.outwidth = self.rf.SysParams["outlinelen"]

    # Override to avoid NaN in JSON.
    def calcsnr(self, f, snrslice, psnr=False):
        # if dspicture isn't converted to float, this underflows at -40IRE
        data = f.output_to_ire(f.dspicture[snrslice].astype(float))

        signal = np.mean(data) if not psnr else 100
        noise = np.std(data)
        # Make sure signal is positive so we don't try to do log on a negative value.
        if signal < 0.0:
            ldd.logger.info(
                "WARNING: Negative mean for SNR, changing to absolute value."
            )
            signal = abs(signal)
        if noise == 0:
            return 0
        return 20 * np.log10(signal / noise)

    def buildmetadata(self, f, check_phase=False):
        """returns field information JSON and whether or not a backfill field is needed"""
        prevfi = self.fieldinfo[-1] if len(self.fieldinfo) else None

        # Not calulated and used for tapes at the moment
        # bust_median = lddu.roundfloat(np.nan_to_num(f.burstmedian)) #lddu.roundfloat(f.burstmedian if not math.isnan(f.burstmedian) else 0.0)
        # "medianBurstIRE": bust_median,

        fi = {
            "isFirstField": True if f.isFirstField else False,
            "syncConf": f.compute_syncconf(),
            "seqNo": len(self.fieldinfo) + 1,
            "diskLoc": np.round((f.readloc / self.bytes_per_field) * 10) / 10,
            "fileLoc": int(np.floor(f.readloc)),
            "fieldPhaseID": f.fieldPhaseID,
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

        if prevfi is not None:
            if prevfi["isFirstField"] == fi["isFirstField"]:
                # logger.info('WARNING!  isFirstField stuck between fields')
                if lddu.inrange(fi["diskLoc"] - prevfi["diskLoc"], 0.95, 1.05):
                    decodeFaults |= 1
                    fi["isFirstField"] = not prevfi["isFirstField"]
                    fi["syncConf"] = 10
                else:
                    # TODO: Do we want to handle this differently?
                    # Also check if this is done properly by calling function
                    # Not sure if it is at the moment..
                    ldd.logger.error(
                        "Possibly skipped field (Two fields with same isFirstField in a row), writing out an copy of last field to compensate.."
                    )
                    decodeFaults |= 4
                    fi["syncConf"] = 0
                    return fi, True

        fi["decodeFaults"] = decodeFaults
        fi["vitsMetrics"] = self.computeMetrics(self.fieldstack[0], self.fieldstack[1])

        self.frameNumber = None
        if f.isFirstField:
            self.firstfield = f
        else:
            # use a stored first field, in case we start with a second field
            if self.firstfield is not None:
                # process VBI frame info data
                self.frameNumber = None

                rawloc = np.floor((f.readloc / self.bytes_per_field) / 2)

                tape_format = (
                    self.rf.options.tape_format
                )  # "CLV" if self.isCLV else "CAV"

                try:
                    if self.est_frames is not None:
                        outstr = f"Frame {(self.fields_written//2)+1}/{int(self.est_frames)}: File Frame {int(rawloc)}: {tape_format} "
                    else:
                        outstr = f"File Frame {int(rawloc)}: {tape_format} "

                    self.logger.status(outstr)
                except Exception:
                    ldd.logger.warning("file frame %d : VBI decoding error", rawloc)
                    traceback.print_exc()

        return fi, False

    # Again ignored for tapes
    def checkMTF(self, field, pfield=None):
        return True

    def writeout(self, dataset):
        f, fi, (picturey, picturec), audio, efm = dataset

        # Remove fields that are currently not used to cut down on space usage.
        # the qt tools will load them as 0 with the current code
        # if they don't exist.
        if "audioSamples" in fi:
            del fi["audioSamples"]

        self.fieldinfo.append(fi)

        self.outfile_video.write(picturey)
        if self.rf.options.write_chroma:
            self.outfile_chroma.write(picturec)
        self.fields_written += 1

    def close(self):
        if self.rf.options.write_chroma:
            setattr(self, "outfile_chroma", None)
        super(VHSDecode, self).close()

    def computeMetricsPAL(self, metrics, f, fp=None):
        return None

    def computeMetricsNTSC(self, metrics, f, fp=None):
        return None

    def build_json(self):
        try:
            # if not f:
            #    # Make sure we don't fail if the last attempted field failed to decode
            #    # Might be better to fix this elsewhere.
            #    f = self.prevfield
            jout = super(VHSDecode, self).build_json()

            black = jout["videoParameters"]["black16bIre"]
            white = jout["videoParameters"]["white16bIre"]

            if self.rf.color_system == "MPAL" or self.rf.color_system == "NLINHA":
                # jout["videoParameters"]["isSourcePal"] = True
                # jout["videoParameters"]["isSourcePalM"] = True
                jout["videoParameters"]["system"] = "PAL-M"

            jout["videoParameters"]["black16bIre"] = black * (1 - self.level_adjust)
            jout["videoParameters"]["white16bIre"] = white * (1 + self.level_adjust)

            jout["videoParameters"]["tapeFormat"] = self.rf.options.tape_format
            return jout
        except TypeError as e:
            traceback.print_exc()
            print("Cannot build json: %s" % e)
            return None

    def readfield(self, initphase=False):
        done = False
        adjusted = False
        redo = None
        df_args = None
        f = None
        offset = 0

        if len(self.fieldstack) >= 2:
            ## Done in main files
            # XXX: Need to cut off the previous field here, since otherwise
            # it'll leak for now.
            # if self.fieldstack[-1]:
            #    self.fieldstack[-1].prevfield = None
            self.fieldstack.pop(-1)

        while done is False:
            if redo:
                # Drop existing thread
                self.decodethread = None

                f, offset = self.decodefield(
                    redo, self.mtf_level, self.fieldstack[0], initphase, redo
                )

                # Only allow one redo, no matter what
                done = True
                redo = None

            else:
                if self.decodethread and self.decodethread.ident:
                    self.decodethread.join()
                    self.decodethread = None

                # In non-threaded mode self.threadreturn was filled earlier...
                # ... but if the first call, this is empty
                if len(self.threadreturn) > 0:
                    f, offset = self.threadreturn["field"], self.threadreturn["offset"]

            # Start new thread
            self.threadreturn = {}
            if f and f.valid:
                prevfield = f
                toffset = self.fdoffset + offset
            else:
                prevfield = None
                toffset = self.fdoffset

                if offset:
                    toffset += offset

            df_args = (
                toffset,
                self.mtf_level,
                prevfield,
                initphase,
                False,
                self.threadreturn,
            )

            # THis doesn't actually seem to do anything in the background so disable for now.
            # if self.numthreads != 0:
            #    self.decodethread = threading.Thread(target=self.decodefield, args=df_args)
            #    self.decodethread.start()
            # else:
            self.decodefield(*df_args)

            # process previous run
            if f:
                self.fdoffset += offset
            elif offset is None:
                # Probable end, so push an empty field
                self.fieldstack.insert(0, None)

            if f and f.valid:
                picture, audio, efm = f.downscale(
                    linesout=self.output_lines,
                    final=True,
                    audio=self.analog_audio,
                    lastfieldwritten=self.lastFieldWritten,
                )

                _ = self.computeMetrics(f, None, verbose=True)
                # if "blackToWhiteRFRatio" in metrics and adjusted is False:
                #    keep = 900 if self.isCLV else 30
                #    self.bw_ratios.append(metrics["blackToWhiteRFRatio"])
                #    self.bw_ratios = self.bw_ratios[-keep:]

                redo = f.needrerun
                if redo:
                    redo = self.fdoffset - offset

                # Perform AGC changes on first fields only to prevent luma mismatch intra-field
                if self.useAGC and f.isFirstField and f.sync_confidence > 80:
                    # TODO: actuall test this after changes
                    sync_hz, ire0_hz, ire100_hz = self.detectLevels(f)

                    actualwhiteIRE = f.rf.hztoire(ire100_hz)

                    sync_ire_diff = lddu.nb_abs(
                        self.rf.hztoire(sync_hz) - self.rf.DecoderParams["vsync_ire"]
                    )
                    whitediff = lddu.nb_abs(self.rf.hztoire(ire100_hz) - actualwhiteIRE)
                    ire0_diff = lddu.nb_abs(self.rf.hztoire(ire0_hz))

                    acceptable_diff = 2 if self.fields_written else 0.5

                    if max((whitediff, ire0_diff, sync_ire_diff)) > acceptable_diff:
                        hz_ire = (ire100_hz - ire0_hz) / 100
                        vsync_ire = (sync_hz - ire0_hz) / hz_ire

                        if vsync_ire > -20:
                            ldd.logger.warning(
                                "At field #{0}, Auto-level detection malfunction (vsync IRE computed at {1}, nominal ~= -40), possible disk skipping".format(
                                    len(self.fieldinfo), np.round(vsync_ire, 2)
                                )
                            )
                        else:
                            redo = self.fdoffset - offset

                            self.rf.DecoderParams["ire0"] = ire0_hz
                            # Note that vsync_ire is a negative number, so (sync_hz - ire0_hz) is correct
                            self.rf.DecoderParams["hz_ire"] = hz_ire
                            self.rf.DecoderParams["vsync_ire"] = vsync_ire

                if adjusted is False and redo:
                    self.demodcache.flush_demod()
                    adjusted = True
                    self.fdoffset = redo
                else:
                    done = True
                    self.fieldstack.insert(0, f)

            if f is None and offset is None:
                # EOF, probably
                return None

            if self.decodethread and not self.decodethread.ident and not redo:
                self.decodethread.start()

        if f is None or f.valid is False:
            return None

        if f is not None and self.fname_out is not None:
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


class VHSRFDecode(ldd.RFDecode):
    def __init__(
        self,
        inputfreq=40,
        system="NTSC",
        tape_format="VHS",
        rf_options={},
        extra_options={},
        debug_plot=None,
    ):
        # First init the rf decoder normally.
        super(VHSRFDecode, self).__init__(
            inputfreq,
            vhs_formats.parent_system(system),
            decode_analog_audio=False,
            has_analog_audio=False,
            extra_options=extra_options,
        )

        # Store a separate setting for *color* system as opposed to 525/625 line here.
        # TODO: Fix upstream so we don't have to fake tell ld-decode code that we are using ntsc for
        # palm to avoid it throwing errors.
        self._color_system = system

        self._dod_options = DodOptions(
            dod_threshold_p=rf_options.get(
                "dod_threshold_p", vhs_formats.DEFAULT_THRESHOLD_P_DDD
            ),
            dod_threshold_a=rf_options.get("dod_threshold_a", None),
            dod_hysteresis=rf_options.get(
                "dod_hysteresis", vhs_formats.DEFAULT_HYSTERESIS
            ),
        )

        self._chroma_trap = rf_options.get("chroma_trap", False)
        # TODO: integrate this under chroma_trap later
        self._use_fsc_notch_filter = (
            tape_format == "BETAMAX" or tape_format == "BETAMAX_HIFI"
        )
        track_phase = None if is_secam(system) else rf_options.get("track_phase", None)
        self._recheck_phase = rf_options.get("recheck_phase", False)
        high_boost = rf_options.get("high_boost", None)
        self._notch = rf_options.get("notch", None)
        self._notch_q = rf_options.get("notch_q", 10.0)
        self._disable_diff_demod = rf_options.get("disable_diff_demod", False)
        self.useAGC = extra_options.get("useAGC", False)
        self.debug = extra_options.get("debug", False)
        # Enable cafc for betamax until proper track detection for it is implemented.
        self._do_cafc = (
            True
            if (tape_format == "BETAMAX" and system != "NTSC")
            else rf_options.get("cafc", False)
        )
        # cafc requires --recheck_phase
        self._recheck_phase = True if self._do_cafc else self._recheck_phase

        self.detect_track = False
        self.needs_detect = False
        if track_phase is None:
            self.track_phase = 0
            if not is_secam(system):
                self.detect_track = True
                self.needs_detect = True
        elif track_phase == 0 or track_phase == 1:
            self.track_phase = track_phase
        else:
            raise Exception("Track phase can only be 0, 1 or None")

        self.hsync_tolerance = 0.8

        self.field_number = 0
        self.last_raw_loc = None

        self.SysParams, self.DecoderParams = vhs_formats.get_format_params(
            system,
            tape_format,
            vhs_formats.parse_tape_speed(rf_options.get("tape_speed", "sp")),
            ldd.logger,
        )

        params_file = extra_options.get("params_file", None)
        if params_file:
            override_params(self.SysParams, self.DecoderParams, params_file, ldd.logger)

        # Make (intentionally) mutable copies of HZ<->IRE levels
        # (NOTE: used by upstream functions, we use a namedtuple to keep const values already)
        self.DecoderParams["ire0"] = self.SysParams["ire0"]
        self.DecoderParams["hz_ire"] = self.SysParams["hz_ire"]
        self.DecoderParams["vsync_ire"] = self.SysParams["vsync_ire"]
        self.DecoderParams["track_ire0_offset"] = self.SysParams.get(
            "track_ire0_offset", [0, 0]
        )

        export_raw_tbc = rf_options.get("export_raw_tbc", False)
        ire0_adjust = rf_options.get("ire0_adjust", False)
        is_color_under = vhs_formats.is_color_under(tape_format)
        write_chroma = (
            is_color_under
            and not export_raw_tbc
            and not rf_options.get("skip_chroma", False)
            and not (system == "405")
        )

        # No idea if this is a common pythonic way to accomplish it but this gives us values that
        # can't be changed later.
        # first depends on IRE/Hz so has to be set after that is properly set.
        # TODO: May want to split this up eventually
        self._options = namedtuple(
            "Options",
            [
                "diff_demod_check_value",
                "tape_format",
                "disable_comb",
                "nldeemp",
                "subdeemp",
                "disable_right_hsync",
                "disable_dc_offset",
                "fallback_vsync",
                "saved_levels",
                "y_comb",
                "write_chroma",
                "color_under",
                "chroma_deemphasis_filter",
                "skip_hsync_refine",
                "hsync_refine_use_threshold",
                "export_raw_tbc",
                "fm_audio_notch",
                "chroma_offset",
                "ire0_adjust",
            ],
        )(
            self.iretohz(100) * 2,
            tape_format,
            rf_options.get("disable_comb", False) or is_secam(system),
            rf_options.get("nldeemp", False),
            self.DecoderParams.get("use_sub_deemphasis", False)
            or rf_options.get("subdeemp", False),
            rf_options.get("disable_right_hsync", False),
            rf_options.get("disable_dc_offset", False),
            # Always use this if we are decoding TYPEC since it doesn't have normal vsync.
            # also enable by default with EIAJ since that was typically used with a primitive sync gen
            # which output not quite standard vsync.
            rf_options.get("fallback_vsync", False)
            or tape_format == "TYPEC"
            or tape_format == "EIAJ"
            or system == "405",
            rf_options.get("saved_levels", False),
            rf_options.get("y_comb", 0) * self.SysParams["hz_ire"],
            write_chroma,
            is_color_under,
            tape_format == "VIDEO8" or tape_format == "HI8",
            rf_options.get("skip_hsync_refine", False),
            # hsync_refine_use_threshold - use detected level for hsync refine
            # TODO: This should be used for everything eventually but needs proper testing
            True,
            export_raw_tbc,
            rf_options.get("fm_audio_notch", 0),
            int(self.DecoderParams.get("chroma_offset", 5) * (self.freq / 40.0)),
            ire0_adjust,
        )

        # As agc can alter these sysParams values, store a copy to then
        # initial value for reference.
        self._sysparams_const = namedtuple(
            "SysparamsConst", "hz_ire vsync_hz vsync_ire ire0 vsync_pulse_us"
        )(
            self.SysParams["hz_ire"],
            self.iretohz(self.SysParams["vsync_ire"]),
            self.SysParams["vsync_ire"],
            self.SysParams["ire0"],
            self.SysParams["vsyncPulseUS"],
        )

        #
        self._sub_emphasis_params = create_sub_emphasis_params(
            self.DecoderParams,
            self.SysParams,
            self._sysparams_const.hz_ire,
            self._sysparams_const.vsync_ire,
        )

        self.debug_plot = debug_plot

        # Lastly we re-create the filters with the new parameters.
        self._computevideofilters_b()

        DP = self.DecoderParams

        self._high_boost = (
            high_boost if high_boost is not None else DP["boost_bpf_mult"]
        )

        # controls the sharpness EQ gain
        sharpness_level = (
            rf_options.get("sharpness", vhs_formats.DEFAULT_SHARPNESS) / 100
        )

        self._video_eq = None
        if sharpness_level != 0:
            self._video_eq = VideoEQ(DP, sharpness_level, self.freq_hz)

        # Heterodyning / chroma wave related filter part

        self._chroma_afc = ChromaAFC(
            self.freq_hz,
            DP["chroma_bpf_upper"] / DP["color_under_carrier"],
            self.SysParams,
            self.DecoderParams["color_under_carrier"],
            self.DecoderParams.get("chroma_bpf_order", 4),
            tape_format=tape_format,
            do_cafc=self._do_cafc,
        )

        self.Filters["FVideoBurst"] = (
            self._chroma_afc.get_chroma_bandpass()
            if self._options.color_under
            else self._chroma_afc.get_chroma_bandpass_final(False)
        )

        if self.options.chroma_deemphasis_filter:
            from vhsdecode.addons.biquad import peaking

            out_freq_half = self._chroma_afc.getOutFreqHalf()

            (b, a) = peaking(
                self.sys_params["fsc_mhz"] / out_freq_half,
                3.4,
                BW=0.5 / out_freq_half,
                type="constantq",
            )
            self.Filters["chroma_deemphasis"] = (b, a)

        if self._notch is not None:
            if not self._do_cafc:
                self.Filters["FVideoNotch"] = sps.iirnotch(
                    self._notch / self.freq_half, self._notch_q
                )
            else:
                self.Filters["FVideoNotch"] = sps.iirnotch(
                    self._notch / self._chroma_afc.getOutFreqHalf(), self._notch_q
                )

            self.Filters["FVideoNotchF"] = abs(
                lddu.filtfft(self.Filters["FVideoNotch"], self.blocklen)
            )
        else:
            self.Filters["FVideoNotch"] = None, None

        # The following filters are for post-TBC:
        # The output sample rate is 4fsc
        out_size = self.SysParams["outlinelen"] * (
            (self.SysParams["frame_lines"] // 2) + 1
        )
        self.Filters["FChromaFinal"] = self._chroma_afc.get_chroma_bandpass_final(
            self._options.color_under
        )

        if is_color_under:
            self.chroma_heterodyne = self._chroma_afc.getChromaHet()
            self.fsc_wave, self.fsc_cos_wave = self._chroma_afc.getFSCWaves()

        # Increase the cutoff at the end of blocks to avoid edge distortion from filters
        # making it through.
        self.blockcut_end = 1024

        level_detect_divisor = rf_options.get("level_detect_divisor", 1)

        if level_detect_divisor < 1 or level_detect_divisor > 10:
            ldd.logger.warning(
                "Invalid level detect divisor value %s, using default.",
                level_detect_divisor,
            )
            level_detect_divisor = 1
        elif inputfreq / level_detect_divisor < 4:
            ldd.logger.warning(
                "Level detect divisor too high (%s) for input frequency (%s) mhz. Limiting to %s",
                level_detect_divisor,
                inputfreq,
                int(inputfreq // 4),
            )
            level_detect_divisor = int(inputfreq // 4)

        self.resync = Resync(
            self.freq_hz,
            self.SysParams,
            self._sysparams_const,
            divisor=level_detect_divisor,
            debug=self.debug,
        )

        if self._chroma_trap:
            self.chromaTrap = ChromaSepClass(
                self.freq_hz, self.SysParams["fsc_mhz"], ldd.logger
            )

        if self.useAGC:
            self.AGClevels = StackableMA(
                window_average=self.SysParams["FPS"] / 2
            ), StackableMA(window_average=self.SysParams["FPS"] / 2)

        self._field_averages = FieldAverage()

        # TODO: This should be managed elsewhere.
        self._compute_linelocs_issues = False

    @property
    def sysparams_const(self):
        return self._sysparams_const

    @property
    def sys_params(self):
        return self.SysParams

    @property
    def options(self):
        return self._options

    @property
    def notch(self):
        return self._notch

    @property
    def chroma_afc(self):
        return self._chroma_afc

    @property
    def do_cafc(self):
        return self._do_cafc

    @property
    def recheck_phase(self):
        return self._recheck_phase

    @property
    def color_system(self):
        return self._color_system

    @property
    def dod_options(self):
        return self._dod_options

    @property
    def field_averages(self):
        return self._field_averages

    @property
    def compute_linelocs_issues(self):
        return self._compute_linelocs_issues

    @compute_linelocs_issues.setter
    def compute_linelocs_issues(self, value):
        self._compute_linelocs_issues = value

    def computefilters(self):
        # Override the stuff used in lddecode to skip generating filters we don't use.
        self.computevideofilters()
        self.computedelays()

    def computevideofilters(self):
        self.Filters = {}
        # Needs to be defined here as it's referenced in constructor.
        self.Filters["F05_offset"] = 32

    def _computevideofilters_b(self):
        # Use some shorthand to compact the code.
        SF = self.Filters
        DP = self.DecoderParams

        SF["hilbert"] = lddu.build_hilbert(self.blocklen)

        self.Filters["EnvLowPass"] = sps.butter(
            1, [1.0 / self.freq_half], btype="lowpass"
        )

        if DP.get("video_bpf_supergauss", False):
            self.Filters["RFVideo"] = gen_bpf_supergauss(
                DP["video_bpf_low"],
                DP["video_bpf_high"],
                DP["video_bpf_order"],
                self.freq_hz_half,
                self.blocklen,
            )[:-1]
            # Mirror to negative frequencies
            self.Filters["RFVideo"] = np.concatenate(
                (self.Filters["RFVideo"], np.flip(self.Filters["RFVideo"]))
            )
        else:
            # Filter for rf before demodulating.
            # Only use bpf if order defined - otherwise skip
            if DP.get("video_bpf_order", None):
                y_fm = lddu.filtfft(
                    sps.butter(
                        DP["video_bpf_order"],
                        [
                            DP["video_bpf_low"] / self.freq_hz_half,
                            DP["video_bpf_high"] / self.freq_hz_half,
                        ],
                        btype="bandpass",
                    ),
                    self.blocklen,
                )
            else:
                y_fm = None

            # Gen fft filter from sos filter
            # TODO: Move this elsewhere
            def sosfiltfft(filter_value, block_len):
                return sps.sosfreqz(filter_value, block_len, whole=True)[1]

            y_fm_lowpass = sosfiltfft(
                sps.butter(
                    DP["video_lpf_extra_order"],
                    [DP["video_lpf_extra"] / self.freq_hz_half],
                    btype="lowpass",
                    output="sos",
                ),
                self.blocklen,
            )

            y_fm_highpass = sosfiltfft(
                sps.butter(
                    DP["video_hpf_extra_order"],
                    [DP["video_hpf_extra"] / self.freq_hz_half],
                    btype="highpass",
                    output="sos",
                ),
                self.blocklen,
            )

            if y_fm is not None:
                # Only use this if defined
                self.Filters["RFVideo"] = (
                    abs(y_fm) * abs(y_fm_lowpass) * abs(y_fm_highpass)
                )
            else:
                self.Filters["RFVideo"] = abs(y_fm_lowpass) * abs(y_fm_highpass)

        if DP.get("video_rf_peak_freq", False):
            # Add optional rf peaking filter
            from vhsdecode.addons.biquad import peaking

            peaking_filter = lddu.filtfft(
                peaking(
                    DP["video_rf_peak_freq"] / self.freq_hz_half,
                    DP.get("video_rf_peak_gain", 3),
                    BW=DP.get("video_rf_peak_bandwidth", 2.5e6) / self.freq_hz_half,
                    type="constantq",
                ),
                self.blocklen,
            )
            self.Filters["RFVideo"] *= abs(peaking_filter)

        # b, a = ([1, -1], [1])
        # rf_eq = filtfft((b, a), self.blocklen)
        # self.Filters["rf_eq"] = b, a
        # self.Filters["rf_eq_fft"] = abs(rf_eq)

        # self.Filters["RFVideo"] *= abs(rf_eq)

        # Make sure this is an int in case it could be passed in as a string via the gui.
        if int(self.options.fm_audio_notch) > 0:
            if "fm_audio_channel_0_freq" in DP and "fm_audio_channel_1_freq" in DP:
                # Optionally enable double notch filter on fm audio channel frequencies.
                # This is mainly useful on VHS (and possibly PAL betamax with hifi?)
                # The hifi carriers on vhs are depth-multiplexed and read by a different head
                # but they still sometimes are picked up strongly enough by the video heads to
                # interfere with the video signal. The carrier for the upper channel especially since
                # it sits high enough that it it overlaps with the lower video sideband.
                # On formats where audio and video share the same heads (8mm, betamax NTSC hifi) the audio and
                # video bands are set up to be separatated more cleanly but for vhs cutting off the video sideband
                # above the audio carrier cuts off too much so use this approach instead and only if needed.
                audio_fm_notch_filter = gen_fm_audio_notch_params(
                    DP, self.options.fm_audio_notch, self.freq_hz_half, self.blocklen
                )
                self.Filters["RFVideo"] *= abs(audio_fm_notch_filter)
            else:
                ldd.logger.warning(
                    "Audio frequencies are not specified for this format, audio fm notch filters not enabled!"
                )

        if DP.get("boost_rf_linear_0", None) is not None:
            ramp = cvf.gen_ramp_filter_params(
                DP,
                self.freq_hz_half,
                self.blocklen,
            )

            self.Filters["RFVideo"] *= ramp
            if DP.get("boost_rf_linear_double", False):
                self.Filters["RFVideo"] *= ramp

        self.Filters["RFTop"] = sps.butter(
            1,
            [
                DP["boost_bpf_low"] / self.freq_hz_half,
                DP["boost_bpf_high"] / self.freq_hz_half,
            ],
            btype="bandpass",
            output="sos",
        )

        # Video (luma) main de-emphasis
        filter_deemp = gen_video_main_deemp_fft_params(DP, self.freq_hz, self.blocklen)

        if DP.get("video_lpf_supergauss", False) is True:
            filter_video_lpf = gen_video_lpf_supergauss_params(
                DP, self.freq_hz_half, self.blocklen
            )
        else:
            (_, filter_video_lpf) = gen_video_lpf_params(
                DP, self.freq_hz_half, self.blocklen
            )

        if DP.get("video_custom_luma_filters", None) is not None:
            self.Filters["FCustomVideo"] = gen_custom_video_filters(
                DP["video_custom_luma_filters"],
                self.freq_hz,
                self.blocklen,
            )
        else:
            self.Filters["FCustomVideo"] = 1.0

        # additional filters:  0.5mhz, used for sync detection.
        # Using an FIR filter here to get a known delay
        F0_5 = sps.firwin(65, [0.5 / self.freq_half], pass_zero=True)
        filter_05 = filtfft((F0_5, [1.0]), self.blocklen, False)

        # SF["F05"] = lddu.filtfft((F0_5, [1.0]), self.blocklen)
        # Defined earlier
        # SF["F05_offset"] = 32

        self.Filters["FEnvPost"] = sps.butter(
            1, [700000 / self.freq_hz_half], btype="lowpass", output="sos"
        )

        self.Filters["NLAmplitudeLPF"] = gen_nonlinear_amplitude_lpf(
            DP.get("nonlinear_amp_lpf_freq", NONLINEAR_AMP_LPF_FREQ_DEFAULT),
            self.freq_hz_half,
        )

        if self._use_fsc_notch_filter:
            self.Filters["fsc_notch"] = sps.iirnotch(
                self.sys_params["fsc_mhz"] / self.freq_half, 2
            )

        self.Filters["FDeemp"] = filter_deemp

        self.Filters["FVideo"] = (
            filter_deemp * filter_video_lpf * self.Filters["FCustomVideo"]
        )

        SF["FVideo05"] = filter_video_lpf * filter_deemp * filter_05

        # SF["YNRHighPass"] = sps.butter(
        #     1,
        #     [
        #         (0.5e6) / self.freq_hz_half,
        #     ],
        #     btype="highpass",
        #     output="sos",
        # )

        if self.options.nldeemp or self.options.subdeemp:
            SF["NLHighPassF"] = gen_nonlinear_bandpass_params(
                DP, self.freq_hz_half, self.blocklen
            )

        if self.debug_plot and self.debug_plot.is_plot_requested("rf_luma"):
            from vhsdecode.debug_plot import plot_luma_rf

            plot_luma_rf(self, self.Filters["RFVideo"])

        if (
            self.debug_plot
            and self.debug_plot.is_plot_requested("nldeemp")
            and self.options.subdeemp
        ):
            from vhsdecode.nonlinear_filter import test_filter

            test_filter(
                self.Filters,
                self.freq_hz,
                self.blocklen,
                (self._sysparams_const.hz_ire * 143.0),
                self._sub_emphasis_params,
            )

        if self.debug_plot and self.debug_plot.is_plot_requested("deemphasis"):
            from vhsdecode.debug_plot import plot_deemphasis

            plot_deemphasis(self, filter_video_lpf, DP, filter_deemp)

    def computedelays(self, mtf_level=0):
        """Override computedelays
        It's normally used for dropout compensation, but the dropout compensation implementation
        in ld-decode assumes composite color. This function is called even if it's disabled, and
        seems to break with the VHS setup, so we disable it by overriding it for now.
        """
        # Set these to 0 for now, the metrics calculations look for them.
        self.delays = {}
        self.delays["video_sync"] = 0
        self.delays["video_white"] = 0

    def demodblock(
        self, data=None, mtf_level=0, fftdata=None, cut=False, thread_benchmark=False
    ):
        rv = {}
        demod_start_time = time.time()
        if fftdata is not None:
            indata_fft = fftdata
        elif data is not None:
            indata_fft = npfft.fft(data[: self.blocklen])
        else:
            raise Exception("demodblock called without raw or FFT data")

        if data is None:
            data = npfft.ifft(indata_fft).real

        if self.debug_plot and self.debug_plot.is_plot_requested("demodblock"):
            # If we're doing a plot make a copy of the input to be able to plot it since we
            # are modifying the data in place.
            indata_fft_copy = indata_fft.copy()

        if self._notch is not None:
            indata_fft *= self.Filters["FVideoNotchF"]

        # Applies RF filters
        indata_fft *= self.Filters["RFVideo"]

        raw_filtered = npfft.ifft(indata_fft * self.Filters["hilbert"]).real

        # Calculate an evelope with signal strength using absolute of hilbert transform.
        # Roll this a bit to compensate for filter delay, value eyballed for now.
        np.abs(raw_filtered, out=raw_filtered)
        raw_env = np.roll(raw_filtered, 4)
        del raw_filtered
        # Downconvert to single precision for some possible speedup since we don't need
        # super high accuracy for the dropout detection.
        env = utils.filter_simple(raw_env, self.Filters["FEnvPost"]).astype(np.single)
        del raw_env
        env_mean = np.mean(env)

        # Boost high frequencies in areas where the signal is weak to reduce missed zero crossings
        # on sharp transitions. Using filtfilt to avoid phase issues.
        if len(np.where(env == 0)[0]) == 0:  # checks for zeroes on env
            if self._high_boost is not None:
                data_filtered = npfft.ifft(indata_fft).real
                high_part = utils.filter_simple(
                    data_filtered, self.Filters["RFTop"]
                ) * ((env_mean * 0.9) / env)
                del data_filtered
                indata_fft += npfft.fft(high_part * self._high_boost)
        else:
            ldd.logger.warning("RF signal is weak. Is your deck tracking properly?")

        hilbert = npfft.ifft(indata_fft * self.Filters["hilbert"])

        # FM demodulator
        demod = unwrap_hilbert(hilbert, self.freq_hz).real

        # If there are obviously out of bounds values, do an extra demod on a diffed waveform and
        # replace the spikes with data from the diffed demod. (Which in practice is an extra EQed signal)
        if not self._disable_diff_demod:
            check_value = self.options.diff_demod_check_value

            if np.max(demod[20:-20]) > check_value:
                demod_b = unwrap_hilbert(
                    np.ediff1d(hilbert, to_begin=0), self.freq_hz
                ).real

                demod = replace_spikes(demod, demod_b, check_value)
                del demod_b
                # Not used yet, needs more testing.
                # 2.2 seems to be a sweet spot between reducing spikes and not causing
                # more
                if False:
                    demod = smooth_spikes(demod, check_value * 2.2)

        # Disabled if sharpness level is zero (default).
        # TODO: This should be done after the deemphasis steps
        if self._video_eq:
            # applies the video EQ
            demod = self._video_eq.filter_video(demod)

        # TODO: This should be done after the deemphasis steps
        if self._chroma_trap:
            # applies the Subcarrier trap
            demod = self.chromaTrap.work(demod)

        # applies main deemphasis filter
        demod_fft = npfft.rfft(demod)
        out_video_fft = demod_fft * self.Filters["FVideo"]
        out_video = npfft.irfft(out_video_fft).real

        if self.options.nldeemp:
            # Extract the high frequency part of the signal
            hf_part = npfft.irfft(out_video_fft * self.Filters["NLHighPassF"])
            # Limit it to preserve sharp transitions
            np.clip(
                hf_part,
                self.DecoderParams["nonlinear_highpass_limit_l"],
                self.DecoderParams["nonlinear_highpass_limit_h"],
                out=hf_part,
            )

            # And subtract it from the output signal.
            out_video -= hf_part

        if self.options.subdeemp:
            out_video = sub_deemphasis(
                out_video,
                out_video_fft,
                self.Filters,
                self._sub_emphasis_params.deviation,
                self._sub_emphasis_params.exponential_scaling,
                self._sub_emphasis_params.scaling_1,
                self._sub_emphasis_params.scaling_2,
                self._sub_emphasis_params.logistic_mid,
                self._sub_emphasis_params.logistic_rate,
                self._sub_emphasis_params.static_factor,
            )

        del out_video_fft

        if self._use_fsc_notch_filter:
            out_video = sps.filtfilt(
                self.Filters["fsc_notch"][0], self.Filters["fsc_notch"][1], out_video
            )

        out_video05 = npfft.irfft(demod_fft * self.Filters["FVideo05"]).real
        out_video05 = np.roll(out_video05, -self.Filters["F05_offset"])

        # Filter out the color-under signal from the raw data.
        chroma_source = data if self.options.color_under else out_video
        out_chroma = (
            demod_chroma_filt(
                chroma_source,
                self.Filters["FVideoBurst"],
                self.blocklen,
                self.Filters["FVideoNotch"],
                self._notch,
                move=int(self.options.chroma_offset),
                # TODO: Do we need to tweak move elsewhere too?
                # if cafc is enabled, this filtering will be done after TBC
            )
            if not self._do_cafc
            else data[: self.blocklen]
        )

        if self.debug_plot and self.debug_plot.is_plot_requested("magdens"):
            from vhsdecode.debug_plot import plot_magnitude_density

            plot_magnitude_density(
                raw_data=data[: self.blocklen],
                filtered_data=npfft.ifft(indata_fft).real,
                rfdecode=self,
            )

        if self.debug_plot and self.debug_plot.is_plot_requested("demodblock"):
            from vhsdecode.debug_plot import plot_input_data

            plot_input_data(
                raw_data=data,
                env=env,
                env_mean=env_mean,
                raw_fft=indata_fft_copy,
                filtered_fft=indata_fft,
                demod_video=demod,
                filtered_video=out_video,
                chroma=out_chroma,
                rf_filter=self.Filters["RFVideo"],
                rfdecode=self,
                plot_chroma_fft=True,
            )

        if self.options.export_raw_tbc:
            out_video = demod

        # demod_burst is a bit misleading, but keeping the naming for compatability.
        video_out = np.rec.array(
            [out_video, out_video05, out_chroma, env],
            names=["demod", "demod_05", "demod_burst", "envelope"],
        )

        rv["video"] = (
            video_out[self.blockcut : -self.blockcut_end] if cut else video_out
        )

        demod_end_time = time.time()
        if thread_benchmark:
            ldd.logger.debug(
                "Demod thread %d, work done in %.02f msec"
                % (os.getpid(), (demod_end_time - demod_start_time) * 1e3)
            )

        return rv
