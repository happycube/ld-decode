import copy
import itertools
import os
import sqlite3
import sys
import time
import types
from importlib.resources import files
from textwrap import dedent

import numba

# standard numeric/scientific libraries
import numpy as np
import scipy.fft as npfft
import scipy.interpolate as spi
import scipy.signal as sps
from numba import njit
from scipy import interpolate

# internal libraries
from . import efm_pll
from . import utils_logging as logs
from .profiling import profile
import traceback

from .filters import (
    build_hilbert,
    calczc,
    emphasis_iir,
    fft_determine_slices,
    fft_do_slice,
    filtfft,
    gen_bpf_supergauss,
    inrange,
    polar2z,
    sqsum,
    unwrap_hilbert,
)
from .pulses import (
    Pulse,
    _dropout_unflag_sync,
    clb_findbursts,
    findpulses,
)
from .fileio import ac3_pipe, ldf_pipe
from .dsp import (
    FieldInfo,
    StridedCollector,
    angular_mean_helper,
    compute_mtf,
    dsa_rescale_and_clip,
    genwave,
    hz_to_output_array,
    n_orgt,
    n_ornotrange,
    n_ornotrange_scalar,
    nb_abs,
    nb_absmax,
    nb_max,
    nb_mean,
    nb_median,
    nb_min,
    nb_round,
    nb_std,
    phase_distance,
    rms,
    roundfloat,
    scale,
    scale_field,
)

# Uncomment (and add to) to get full traces of numpy warnings
#import warnings
#warnings.filterwarnings('error', "Mean of empty slice.")

from .params import (  # noqa: F401
    BLOCKSIZE, FilterParams_NTSC, FilterParams_NTSC_lowband,
    FilterParams_PAL, FilterParams_PAL_lowband, SysParams_NTSC,
    SysParams_PAL, calclinelen,
)

from .rfdecode import RFDecode  # noqa: F401


from .audio import (  # noqa: F401
    _downscale_audio_compute_locs_and_swow, _downscale_audio_to_output,
    downscale_audio,
)

# XXX: bring this enum-like thing into Field
# state order: HSYNC -> EQPUL1 -> VSYNC -> EQPUL2 -> HSYNC
HSYNC, EQPL1, VSYNC, EQPL2 = range(4)

# The Field class contains common features used by NTSC and PAL
class Field:
    burst_lines = (11, 264)  # NTSC default
    burst_max_ire = None  # PAL overrides to 30
    output_black = 0x0400  # NTSC default
    output_white = 0xC800

    def __init__(
        self,
        rf,
        decode,
        prevfield=None,
        initphase=False,
        fields_written=0,
        readloc=0,
        wow_level_adjust_smoothing=0,
        wow_interpolation_method="linear"
    ):
        self.rawdata = decode["input"]
        self.data = decode
        self.initphase = initphase  # used for seeking or first field
        self.readloc = readloc

        self.prevfield = prevfield
        self.fields_written = fields_written

        self.rf = rf
        self.freq = self.rf.freq

        self.inlinelen = self.rf.linelen
        self.outlinelen = self.rf.SysParams["outlinelen"]

        self.lineoffset = 0

        self.needrerun = False
        self.valid = False
        self.sync_confidence = 100

        self.dspicture = None
        self.dsaudio = None

        self.interpolated_pixel_locs = None
        self.wowfactors = None

        # On NTSC linecount rounds up to 263, and PAL 313
        self.outlinecount = (self.rf.SysParams["frame_lines"] // 2) + 1
        # this is eventually set to 262/263 and 312/313 for audio timing
        self.linecount = None

        self.wow_level_adjust_smoothing = wow_level_adjust_smoothing
        self.wow_interpolation_method = wow_interpolation_method

    @profile
    def process(self):
        self.linelocs1, self.linebad, self.nextfieldoffset = self.compute_linelocs()

        if self.linelocs1 is None:
            if self.nextfieldoffset is None:
                self.nextfieldoffset = self.rf.linelen * 200

            return

        self.linebad   = self.compute_deriv_error(self.linelocs1, self.linebad)

        self.linelocs2 = self.refine_linelocs_hsync()
        self.linebad   = self.compute_deriv_error(self.linelocs2, self.linebad)

        self.linelocs  = self.linelocs2

        self.valid     = True

        self.out_scale = np.double(self.output_white - self.output_black) / (
            100 - self.rf.DecoderParams["vsync_ire"]
        )

    @profile
    def get_linelen(self, line=None, linelocs=None):
        # compute adjusted frequency from neighboring line lengths

        # If this is run early, line locations are unknown, so return
        # the general value
        if linelocs is None:
            if hasattr(self, "linelocs"):
                linelocs = self.linelocs

        if line is None or linelocs is None:
            return self.rf.linelen

        if line >= self.linecount + self.lineoffset:
            length = linelocs[line] - linelocs[line - 1]
        elif line > 0:
            length = (linelocs[line + 1] - linelocs[line - 1]) / 2
        else:
            length = linelocs[1] - linelocs[0]

        if length <= 0:
            # linelocs aren't monotonic -- probably TBC failure
            return self.rf.linelen

        return length

    def get_burstlevel(self, line, linelocs=None):
        # Fields that pass validity checks can still have nonsense linelocs
        # (issue #621); an empty slice makes nb_mean/max throw.
        try:
            burstarea = self.data["video"]["demod"][self.lineslice(line, 5.5, 2.4, linelocs)].copy()
            burstarea -= nb_mean(burstarea)
            if self.burst_max_ire is not None and max(burstarea) > (self.burst_max_ire * self.rf.DecoderParams["hz_ire"]):
                return None
            return rms(burstarea) * np.sqrt(2)
        except Exception:
            return None

    def calc_burstmedian(self):
        burstlevel = [b for b in (self.get_burstlevel(l) for l in range(*self.burst_lines)) if b is not None]
        return (np.median(burstlevel) / self.rf.DecoderParams["hz_ire"]) if burstlevel else 0.0

    def get_linefreq(self, line=None, linelocs=None):
        return self.rf.samplesperline * self.get_linelen(line, linelocs)

    def usectoinpx(self, x, line=None):
        return x * self.get_linefreq(line)

    def inpxtousec(self, x, line=None):
        return x / self.get_linefreq(line)

    @profile
    def lineslice(self, line, begin=None, length=None, linelocs=None, begin_offset=0):
        """ return a slice corresponding with pre-TBC line l, begin+length are uSecs """

        # for PAL, each field has a different offset so normalize that
        line_adj = line + self.lineoffset

        _begin = linelocs[line_adj] if linelocs is not None else self.linelocs[line_adj]
        _begin += self.usectoinpx(begin, line_adj) if begin is not None else 0

        _length = length if length is not None else self.rf.SysParams["line_period"]
        _length = self.usectoinpx(_length)

        return slice(
            int(_begin + begin_offset),
            int(_begin + _length + begin_offset + 1),
        )

    def usectooutpx(self, x):
        return x * self.rf.SysParams["outfreq"]

    def outpxtousec(self, x):
        return x / self.rf.SysParams["outfreq"]

    @profile
    def hz_to_output(self, input):
        if isinstance(input, np.ndarray):
            return hz_to_output_array(
                input,
                self.rf.DecoderParams["ire0"],
                self.rf.DecoderParams["hz_ire"],
                self.rf.SysParams["outputZero"],
                self.rf.DecoderParams["vsync_ire"],
                self.out_scale
            )

        reduced = (input - self.rf.DecoderParams["ire0"]) / self.rf.DecoderParams["hz_ire"]
        reduced -= self.rf.DecoderParams["vsync_ire"]

        return np.uint16(np.round(
            np.clip(
                (reduced * self.out_scale) + self.rf.SysParams["outputZero"], 0, 65535
            )
        ))

    def output_to_ire(self, output):
        return (
            (output - self.rf.SysParams["outputZero"]) / self.out_scale
        ) + self.rf.DecoderParams["vsync_ire"]


    def lineslice_tbc(self, line, begin=None, length=None, linelocs=None, keepphase=False):
        """ return a slice corresponding with pre-TBC line l """

        _begin = self.rf.SysParams["outlinelen"] * (line - 1)

        begin_offset = self.usectooutpx(begin) if begin is not None else 0
        if keepphase:
            begin_offset = (begin_offset // 4) * 4

        _begin += begin_offset
        _length = (
            self.usectooutpx(length)
            if length is not None
            else self.rf.SysParams["outlinelen"]
        )

        return slice(nb_round(_begin), nb_round(_begin + _length))

    @profile
    def get_timings(self):
        pulses = self.rawpulses
        hsync_typical = self.usectoinpx(self.rf.SysParams["hsyncPulseUS"])

        # Some disks have odd sync levels resulting in short and/or long pulse lengths.
        # So, take the median hsync and adjust the expected values accordingly

        hsync_checkmin = self.usectoinpx(self.rf.SysParams["hsyncPulseUS"] - 1.75)
        hsync_checkmax = self.usectoinpx(self.rf.SysParams["hsyncPulseUS"] + 2)

        hlens = []
        for p in pulses:
            if inrange(p.len, hsync_checkmin, hsync_checkmax):
                hlens.append(p.len)

        LT = {}
        if len(hlens) > 0:
            LT["hsync_median"] = np.median(hlens)
        else:
            LT["hsync_median"] = self.rf.SysParams["hsyncPulseUS"]

        hsync_min = LT["hsync_median"] + self.usectoinpx(-0.5)
        hsync_max = LT["hsync_median"] + self.usectoinpx(0.5)

        LT["hsync"] = (hsync_min, hsync_max)

        LT["hsync_offset"] = LT["hsync_median"] - hsync_typical

        eq_min = (
            self.usectoinpx(self.rf.SysParams["eqPulseUS"] - 0.5) + LT["hsync_offset"]
        )
        eq_max = (
            self.usectoinpx(self.rf.SysParams["eqPulseUS"] + 0.5) + LT["hsync_offset"]
        )

        LT["eq"] = (eq_min, eq_max)

        vsync_min = (
            self.usectoinpx(self.rf.SysParams["vsyncPulseUS"] * 0.5)
            + LT["hsync_offset"]
        )
        vsync_max = (
            self.usectoinpx(self.rf.SysParams["vsyncPulseUS"] + 1) + LT["hsync_offset"]
        )

        LT["vsync"] = (vsync_min, vsync_max)

        return LT

    def pulse_qualitycheck(self, prevpulse: Pulse, pulse: Pulse):
        if prevpulse[0] > 0 and pulse[0] > 0:
            exprange = (0.4, 0.6)
        elif prevpulse[0] == 0 and pulse[0] == 0:
            exprange = (0.9, 1.1)
        else:  # transition to/from regular hsyncs can be .5 or 1H
            exprange = (0.4, 1.1)

        linelen = (pulse[1].start - prevpulse[1].start) / self.inlinelen
        inorder = inrange(linelen, *exprange)

        return inorder

    @profile
    def run_vblank_state_machine(self, pulses, LT):
        """ Determines if a pulse set is a valid vblank by running a state machine """

        done = 0

        vsyncs = []  # VSYNC area (first broad pulse->first EQ after broad pulses)

        validpulses = []
        vsync_start = None

        # state_end tracks the earliest expected phase transition...
        state_end = 0
        # ... and state length is set by the phase transition to set above (in H)
        state_length = None

        for p in pulses:
            spulse = None

            state = validpulses[-1][0] if len(validpulses) > 0 else -1

            if state == -1:
                # First valid pulse must be a regular HSYNC
                if inrange(p.len, *LT["hsync"]):
                    spulse = (HSYNC, p)
            elif state == HSYNC:
                # HSYNC can transition to EQPUL/pre-vsync at the end of a field
                if inrange(p.len, *LT["hsync"]):
                    spulse = (HSYNC, p)
                elif inrange(p.len, *LT["eq"]):
                    spulse = (EQPL1, p)
                    state_length = self.rf.SysParams["numPulses"] / 2
                elif inrange(p.len, *LT["vsync"]):
                    # should not happen(tm)
                    vsync_start = len(validpulses) - 1
                    spulse = (VSYNC, p)
            elif state == EQPL1:
                if inrange(p.len, *LT["eq"]):
                    spulse = (EQPL1, p)
                elif inrange(p.len, *LT["vsync"]):
                    # len(validpulses)-1 before appending adds index to first VSYNC pulse
                    vsync_start = len(validpulses) - 1
                    spulse = (VSYNC, p)
                    state_length = self.rf.SysParams["numPulses"] / 2
                elif inrange(p.len, *LT["hsync"]):
                    # previous state transition was likely in error!
                    spulse = (HSYNC, p)
            elif state == VSYNC:
                if inrange(p.len, *LT["eq"]):
                    # len(validpulses)-1 before appending adds index to first EQ pulse
                    vsyncs.append((vsync_start, len(validpulses) - 1))
                    spulse = (EQPL2, p)
                    state_length = self.rf.SysParams["numPulses"] / 2
                elif inrange(p.len, *LT["vsync"]):
                    spulse = (VSYNC, p)
                elif p.start > state_end and inrange(p.len, *LT["hsync"]):
                    spulse = (HSYNC, p)
            elif state == EQPL2:
                if inrange(p.len, *LT["eq"]):
                    spulse = (EQPL2, p)
                elif inrange(p.len, *LT["hsync"]):
                    spulse = (HSYNC, p)
                    done = True

            if spulse is not None and spulse[0] != state:
                if spulse[1].start < state_end:
                    spulse = None
                elif state_length:
                    state_end = spulse[1].start + (
                        (state_length - 0.1) * self.inlinelen
                    )
                    state_length = None

            # Quality check
            if spulse is not None:
                good = (
                    self.pulse_qualitycheck(validpulses[-1], spulse)
                    if len(validpulses)
                    else False
                )

                validpulses.append((spulse[0], spulse[1], good))

            if done:
                return done, validpulses

        return done, validpulses

    @profile
    def refinepulses(self):
        self.LT = self.get_timings()

        i = 0
        valid_pulses = []
        num_vblanks = 0

        while i < len(self.rawpulses):
            curpulse = self.rawpulses[i]
            if inrange(curpulse.len, *self.LT["hsync"]):
                good = (
                    self.pulse_qualitycheck(valid_pulses[-1], (0, curpulse))
                    if len(valid_pulses)
                    else False
                )
                valid_pulses.append((HSYNC, curpulse, good))
                i += 1
            elif (
                i > 2
                and inrange(self.rawpulses[i].len, *self.LT["eq"])
                and (len(valid_pulses) and valid_pulses[-1][0] == HSYNC)
            ):
                done, vblank_pulses = self.run_vblank_state_machine(
                    self.rawpulses[i - 2 : i + 24], self.LT
                )
                if done:
                    valid_pulses.extend(vblank_pulses[2:])
                    i += len(vblank_pulses) - 2
                    num_vblanks += 1
                else:
                    i += 1
            else:
                i += 1

        return valid_pulses

    @profile
    def getBlankRange(self, validpulses, start=0):
        vp_type    = np.array([p[0] for p in validpulses])

        vp_vsyncs  = np.where(vp_type[start:] == VSYNC)[0]
        firstvsync = vp_vsyncs[0] + start if len(vp_vsyncs) else None

        if firstvsync is None or firstvsync < 10:
            return None, None

        for newstart in range(firstvsync - 10, firstvsync - 4):
            blank_locs = np.where(vp_type[newstart:] > 0)[0]
            if len(blank_locs) == 0:
                continue

            firstblank = blank_locs[0] + newstart
            hsync_locs = np.where(vp_type[firstblank:] == 0)[0]

            if len(hsync_locs) == 0:
                continue

            lastblank = hsync_locs[0] + firstblank - 1

            if (lastblank - firstblank) > 12:
                return firstblank, lastblank

        # there isn't a valid range to find, or it's impossibly short
        return None, None

    def getVBlankLength(self, isFirstField):
        core = self.rf.SysParams["numPulses"] * 3 * 0.5

        if self.rf.system == "NTSC":
            return core + 1
        else:
            return core + 0.5 + (0 if isFirstField else 1)

    def processVBlank(self, validpulses, start, limit=None):

        firstblank, lastblank = self.getBlankRange(validpulses, start)

        """
        First Look at each equalization/vblank pulse section - if the expected # are there and
        valid,
        it can be used to determine where line 0 is...
        """

        # locations of lines before after/vblank.  may not be line 0 etc
        lastvalid = len(validpulses) if limit is None else start + limit
        if firstblank is None or firstblank > lastvalid:
            return None, None, None, None

        loc_presync = validpulses[firstblank - 1][1].start

        pt = np.array([v[0] for v in validpulses[firstblank:]])
        pstart = np.array([v[1].start for v in validpulses[firstblank:]])
        plen = np.array([v[1].len for v in validpulses[firstblank:]])

        numPulses = self.rf.SysParams["numPulses"]

        for i in [VSYNC, EQPL1, EQPL2]:
            ptmatch = pt == i
            grouploc = None

            for j in range(0, lastblank - firstblank):
                if ptmatch[j : j + numPulses].all():
                    if ptmatch[j : j + numPulses + 4].sum() != numPulses:
                        break

                    # take the (second) derivative of the line gaps and lengths to determine
                    # if all are valid
                    gaps = np.diff(np.diff(pstart[j : j + numPulses]))
                    lengths = np.diff(plen[j : j + numPulses])

                    if np.max(gaps) < (self.rf.freq * 0.2) and np.max(lengths) < (
                        self.rf.freq * 0.2
                    ):
                        grouploc = j
                        break

            if grouploc is None:
                continue

            setbegin = validpulses[firstblank + grouploc]
            firstloc = setbegin[1].start

            # compute the distance of the first pulse of this block to line 1
            # (line 0 may be .5H or 1H before that)
            distfroml1 = ((i - 1) * self.rf.SysParams["numPulses"]) * 0.5

            dist = (firstloc - loc_presync) / self.inlinelen
            # get the integer rounded X * .5H distance.  then invert to determine
            # the half-H alignment with the sync/blank pulses
            hdist = nb_round(dist * 2)

            isfirstfield = (hdist % 2) == (self.rf.SysParams["firstFieldH"][1] != 1)

            # for PAL VSYNC, the offset is 2.5H, so the calculation must be reversed
            if (distfroml1 * 2) % 2:
                isfirstfield = not isfirstfield

            eqgap = self.rf.SysParams["firstFieldH"][isfirstfield]
            line0 = firstloc - ((eqgap + distfroml1) * self.inlinelen)

            return int(line0), isfirstfield, firstblank, 100

        """
        If there are no valid sections, check line 0 and the first eq pulse, and the last eq
        pulse and the following line.  If the combined xH is correct for the standard in question
        (1.5H for NTSC, 1 or 2H for PAL, that means line 0 has been found correctly.
        """

        if (
            validpulses[firstblank - 1][2]
            and validpulses[firstblank][2]
            and validpulses[lastblank][2]
            and validpulses[lastblank + 1][2]
        ):
            gap1 = (
                validpulses[firstblank][1].start - validpulses[firstblank - 1][1].start
            )
            gap2 = validpulses[lastblank + 1][1].start - validpulses[lastblank][1].start

            if self.rf.system == "PAL" and inrange(
                np.abs(gap2 - gap1), 0, self.rf.freq * 1
            ):
                isfirstfield = inrange((gap1 / self.inlinelen), 0.45, 0.55)
            elif self.rf.system == "NTSC" and inrange(
                np.abs(gap2 + gap1), self.inlinelen * 1.4, self.inlinelen * 1.6
            ):
                isfirstfield = inrange((gap1 / self.inlinelen), 0.95, 1.05)
            else:
                self.sync_confidence = 0
                return None, None, None, 0

            return validpulses[firstblank - 1][1].start, isfirstfield, firstblank, 50

        return None, None, None, 0

    @profile
    def computeLineLen(self, validpulses):
        # determine longest run of 0's
        longrun = [-1, -1]
        currun = None
        for i, v in enumerate([p[0] for p in validpulses]):
            if v != 0:
                if currun is not None and currun[1] > longrun[1]:
                    longrun = currun
                currun = None
            elif currun is None:
                currun = [i, 0]
            else:
                currun[1] += 1

        if currun is not None and currun[1] > longrun[1]:
            longrun = currun

        linelens = []
        for i in range(longrun[0] + 1, longrun[0] + longrun[1]):
            linelen = validpulses[i][1].start - validpulses[i - 1][1].start
            if inrange(linelen / self.inlinelen, 0.95, 1.05):
                linelens.append(
                    validpulses[i][1].start - validpulses[i - 1][1].start
                )

        if len(linelens) > 0:
            return np.mean(linelens)
        else:
            return self.inlinelen


    def skip_check(self):
        """ This routine checks to see if there's a (probable) VSYNC at the end.
            Returns a (currently rough) probability.
        """
        score = 0
        vsync_lines = 0

        vsync_ire = self.rf.DecoderParams["vsync_ire"]

        for line in range(self.outlinecount, self.outlinecount + 8):
            sl = self.lineslice(line, 0, self.rf.SysParams["line_period"])
            line_ire = self.rf.hztoire(nb_median(self.data["video"]["demod"][sl]))

            # vsync_ire is always negative, so /2 is the higher number

            if inrange(line_ire, vsync_ire - 10, vsync_ire / 2):
                vsync_lines += 1
            elif inrange(line_ire, -5, 5):
                score += 1
            else:
                score -= 1

        if vsync_lines >= 2:
            return 100
        elif vsync_lines == 1 and score > 0:
            return 50
        elif score > 0:
            return 25

        return 0

    # pull the above together into a routine that (should) find line 0, the last line of
    # the previous field.

    @profile
    def getLine0(self, validpulses, meanlinelen):
        # Gather the local line 0 location and projected from the previous field

        self.sync_confidence = 100

        # If we have a previous field, the first vblank should be close to the beginning,
        # and we need to reject anything too far in (which could be the *next* vsync)
        limit = 100 if (self.prevfield is not None and self.prevfield.skip_check() >= 50) else None
        line0loc_local, isFirstField_local, firstblank_local, conf_local = self.processVBlank(
            validpulses, 0, limit
        )

        line0loc_next, isFirstField_next, conf_next = None, None, None

        # If we have a vsync at the end, use it to compute the likely line 0
        if line0loc_local is not None:
            self.vblank_next, isNotFirstField_next, firstblank_next, conf_next = self.processVBlank(
                validpulses, firstblank_local + 40
            )

            if self.vblank_next is not None:
                isFirstField_next = not isNotFirstField_next

                fieldlen = (
                    meanlinelen
                    * self.rf.SysParams["field_lines"][0 if isFirstField_next else 1]
                )
                line0loc_next = nb_round(self.vblank_next - fieldlen)

                if line0loc_next < 0:
                    self.sync_confidence = 10
        else:
            self.vblank_next = None

        # Use the previous field's end to compute a possible line 0
        line0loc_prev, isFirstField_prev = None, None
        if self.prevfield is not None and self.prevfield.valid:
            frameoffset = self.data["startloc"] - self.prevfield.data["startloc"]

            line0loc_prev = (
                self.prevfield.linelocs[self.prevfield.linecount] - frameoffset
            )
            isFirstField_prev = not self.prevfield.isFirstField
            conf_prev = self.prevfield.sync_confidence



        # Best case - all three line detectors returned something - perform TOOT using median
        if (
            line0loc_local is not None
            and line0loc_next is not None
            and line0loc_prev is not None
        ):
            isFirstField_all = (
                isFirstField_local + isFirstField_prev + isFirstField_next
            ) >= 2
            return (
                np.median([line0loc_local, line0loc_next, line0loc_prev]),
                self.vblank_next,
                isFirstField_all,
            )

        if line0loc_local is not None and conf_local > 50:
            self.sync_confidence = min(self.sync_confidence, 90)
            return line0loc_local, self.vblank_next, isFirstField_local
        elif line0loc_prev is not None:
            new_sync_confidence = max(conf_prev - 10, 10)
            self.sync_confidence = min(self.sync_confidence, new_sync_confidence)
            return line0loc_prev, self.vblank_next, isFirstField_prev
        elif line0loc_next is not None:
            self.sync_confidence = conf_next
            return line0loc_next, self.vblank_next, isFirstField_next
        else:
            # Failed to find anything useful - the caller is expected to skip ahead and try again
            return None, None, None


    def getpulses(self, do_retry=True):
        # pass one using standard levels

        pulse_hz_min = self.rf.iretohz(self.rf.DecoderParams["vsync_ire"] - 20)
        pulse_hz_max = self.rf.iretohz(-20)

        pulses = findpulses(self.data["video"]["demod_05"], pulse_hz_min, pulse_hz_max)

        if len(pulses) == 0:
            if do_retry and not self.fields_written:
                # if the first field decoded, recalibrate sync levels and retry
                ire0 = np.percentile(self.data["video"]["demod_05"], 15)
                self.rf.DecoderParams["ire0"] = ire0

                return self.getpulses(do_retry=False)
            else:
                # otherwise, can't do anything about this
                return pulses

        # determine sync pulses from vsync
        vsync_locs = []
        vsync_means = []

        minlength = self.usectoinpx(10)

        for i, p in enumerate(pulses):
            if p.len > minlength:
                vsync_locs.append(i)
                vsync_means.append(
                    np.mean(
                        self.data["video"]["demod_05"][
                            int(p.start + self.rf.freq) : int(
                                p.start + p.len - self.rf.freq
                            )
                        ]
                    )
                )


        if len(vsync_means) == 0:
            return None

        synclevel = np.median(vsync_means)

        if np.abs(self.rf.hztoire(synclevel) - self.rf.DecoderParams["vsync_ire"]) < 5:
            # sync level is close enough to use
            return pulses

        if not vsync_locs:
            return None

        # Now compute black level and try again

        # take the eq pulses before and after vsync
        r1 = range(vsync_locs[0] - 5, vsync_locs[0])
        r2 = range(vsync_locs[-1] + 1, vsync_locs[-1] + 6)

        black_means = []

        for i in itertools.chain(r1, r2):
            if i < 0 or i >= len(pulses):
                continue

            p = pulses[i]
            if inrange(p.len, self.rf.freq * 0.75, self.rf.freq * 2.5):
                black_means.append(
                    np.mean(
                        self.data["video"]["demod_05"][
                            int(p.start + (self.rf.freq * 5)) : int(
                                p.start + (self.rf.freq * 20)
                            )
                        ]
                    )
                )

        blacklevel = np.median(black_means)

        pulse_hz_min = synclevel - (self.rf.DecoderParams["hz_ire"] * 10)
        pulse_hz_max = (blacklevel + synclevel) / 2

        return findpulses(self.data["video"]["demod_05"], pulse_hz_min, pulse_hz_max)

    @profile
    def compute_linelocs(self):

        self.rawpulses = self.getpulses()
        if self.rawpulses is None or len(self.rawpulses) == 0:
            if self.fields_written:
                logs.logger.error("Unable to find any sync pulses, skipping one field")
                return None, None, None
            else:
                logs.logger.error("Unable to find any sync pulses, skipping one second")
                return None, None, int(self.rf.freq_hz)


        self.validpulses = validpulses = self.refinepulses()
        meanlinelen = self.computeLineLen(validpulses)
        line0loc, lastlineloc, self.isFirstField = self.getLine0(validpulses, meanlinelen)
        self.linecount = self.rf.SysParams["field_lines"][0 if self.isFirstField else 1]

        # Number of lines to actually process.  This is set so that the entire following
        # VSYNC is processed
        proclines = self.outlinecount + self.lineoffset + 10
        if self.rf.system == "PAL":
            proclines += 3

        # It's possible for getLine0 to return None for lastlineloc
        if lastlineloc is not None:
            numlines = (lastlineloc - line0loc) / self.inlinelen
            self.skipdetected = numlines < (self.linecount - 5)
        else:
            self.skipdetected = False

        linelocs_dict = {}
        linelocs_dist = {}

        if line0loc is None:
            if not self.initphase:
                logs.logger.error("Unable to determine start of field - dropping field")

            return None, None, self.inlinelen * 200

        # If we don't have enough data at the end, move onto the next field
        lastline = (self.rawpulses[-1].start - line0loc) / meanlinelen
        if lastline < proclines:
            return None, None, line0loc - (meanlinelen * 20)

        for p in validpulses:
            lineloc = (p[1].start - line0loc) / meanlinelen
            rlineloc = nb_round(lineloc)
            lineloc_distance = np.abs(lineloc - rlineloc)

            if self.skipdetected:
                lineloc_end = self.linecount - (
                    (lastlineloc - p[1].start) / meanlinelen
                )
                rlineloc_end = nb_round(lineloc_end)
                lineloc_end_distance = np.abs(lineloc_end - rlineloc_end)

                if (
                    p[0] == 0
                    and rlineloc > 23
                    and lineloc_end_distance < lineloc_distance
                ):
                    lineloc = lineloc_end
                    rlineloc = rlineloc_end
                    lineloc_distance = lineloc_end_distance

            # only record if it's closer to the (probable) beginning of the line
            if lineloc_distance > self.rf.hsync_tolerance or (
                rlineloc in linelocs_dict and lineloc_distance > linelocs_dist[rlineloc]
            ):

                continue

            # also skip non-regular lines (non-hsync) that don't seem to be in valid order (p[2])
            # (or hsync lines in the vblank area)
            if rlineloc > 0 and not p[2]:
                if p[0] > 0 or (p[0] == 0 and rlineloc < 10):
                    continue

            linelocs_dict[rlineloc] = p[1].start
            linelocs_dist[rlineloc] = lineloc_distance

        rv_err = np.full(proclines, False)

        # Convert dictionary into list, then fill in gaps
        linelocs = [
            linelocs_dict[line] if line in linelocs_dict else -1 for line in range(0, proclines)
        ]
        linelocs_filled = linelocs.copy()

        self.linelocs0 = linelocs.copy()

        if linelocs_filled[0] < 0:
            next_valid = None
            for i in range(0, self.outlinecount + 1):
                if linelocs[i] > 0:
                    next_valid = i
                    break

            if next_valid is None:
                return None, None, line0loc + (self.inlinelen * self.outlinecount - 7)

            linelocs_filled[0] = linelocs_filled[next_valid] - (
                next_valid * meanlinelen
            )

            if linelocs_filled[0] < self.inlinelen:
                return None, None, line0loc + (self.inlinelen * self.outlinecount - 7)

        # Pre-compute nearest valid line after each position (single forward pass)
        scan_end = min(proclines, self.outlinecount + 1)
        next_valid_arr = [None] * proclines
        last_seen = None
        for i in range(scan_end - 1, -1, -1):
            if linelocs[i] > 0:
                last_seen = i
            next_valid_arr[i] = last_seen

        prev_valid = 0 if linelocs[0] > 0 else None

        for line in range(1, proclines):
            if linelocs_filled[line] < 0:
                rv_err[line] = True

                next_valid = next_valid_arr[line] if line < scan_end else None

                if prev_valid is None:
                    avglen = self.inlinelen
                    linelocs_filled[line] = linelocs[next_valid] - (
                        avglen * (next_valid - line)
                    )
                elif next_valid is not None:
                    avglen = (linelocs[next_valid] - linelocs[prev_valid]) / (
                        next_valid - prev_valid
                    )
                    linelocs_filled[line] = linelocs[prev_valid] + (
                        avglen * (line - prev_valid)
                    )
                else:
                    avglen = self.inlinelen
                    linelocs_filled[line] = linelocs[prev_valid] + (
                        avglen * (line - prev_valid)
                    )
            else:
                prev_valid = line

        # *finally* done :)

        rv_ll = [linelocs_filled[line] for line in range(0, proclines)]


        if self.vblank_next is None:
            nextfield = linelocs_filled[self.outlinecount - 7]
        else:
            nextfield = self.vblank_next - (self.inlinelen * 8)



        return rv_ll, rv_err, nextfield

    @profile
    def refine_linelocs_hsync(self):
        linelocs2 = self.linelocs1.copy()

        for i in range(len(self.linelocs1)):
            # skip VSYNC lines, since they handle the pulses differently
            if inrange(i, 3, 6) or (self.rf.system == "PAL" and inrange(i, 1, 2)):
                self.linebad[i] = True
                continue

            # refine beginning of hsync
            ll1 = self.linelocs1[i] - self.rf.freq
            zc = calczc(
                self.data["video"]["demod_05"],
                ll1,
                self.rf.iretohz(self.rf.DecoderParams["vsync_ire"] / 2),
                reverse=False,
                count=self.rf.freq * 2,
            )

            if zc is not None and not self.linebad[i]:
                linelocs2[i] = zc

                # The hsync area, burst, and porches should not leave -50 to 30 IRE (on PAL or NTSC)
                hsync_area = self.data["video"]["demod_05"][
                    int(zc - (self.rf.freq * 0.75)) : int(zc + (self.rf.freq * 8))
                ]
                if nb_min(hsync_area) < self.rf.iretohz(-55) or nb_max(
                    hsync_area
                ) > self.rf.iretohz(30):
                    # don't use the computed value here if it's bad
                    self.linebad[i] = True
                    linelocs2[i] = self.linelocs1[i]
                else:
                    porch_level = nb_median(
                        self.data["video"]["demod_05"][
                            int(zc + (self.rf.freq * 8)) : int(zc + (self.rf.freq * 9))
                        ]
                    )
                    sync_level = nb_median(
                        self.data["video"]["demod_05"][
                            int(zc + (self.rf.freq * 1)) : int(
                                zc + (self.rf.freq * 2.5)
                            )
                        ]
                    )

                    zc2 = calczc(
                        self.data["video"]["demod_05"],
                        ll1,
                        (porch_level + sync_level) / 2,
                        reverse=False,
                        count=400,
                    )

                    # any wild variation here indicates a failure
                    if zc2 is not None and np.abs(zc2 - zc) < (self.rf.freq / 2):
                        linelocs2[i] = zc2
                    else:
                        self.linebad[i] = True
            else:
                self.linebad[i] = True

            if self.linebad[i]:
                linelocs2[i] = self.linelocs1[
                    i
                ]  # don't use the computed value here if it's bad

        return linelocs2

    def compute_deriv_error(self, linelocs, baserr):
        """ compute errors based off the second derivative - if it exceeds 1 something's wrong,
            and if 4 really wrong...
        """

        derr1 = np.full(len(linelocs), False)
        derr1[1:-1] = np.abs(np.diff(np.diff(linelocs))) > 4

        derr2 = np.full(len(linelocs), False)
        derr2[2:] = np.abs(np.diff(np.diff(linelocs))) > 4

        return baserr | derr1 | derr2

    def fix_badlines(self, linelocs_in, linelocs_backup_in=None):
        self.linebad = self.compute_deriv_error(linelocs_in, self.linebad)
        linelocs = np.array(linelocs_in.copy())

        if linelocs_backup_in is not None:
            linelocs_backup = np.array(linelocs_backup_in.copy())
            badlines = np.isnan(linelocs)
            linelocs[badlines] = linelocs_backup[badlines]

        for line in np.where(self.linebad)[0]:
            prevgood = line - 1
            while prevgood >= 0 and self.linebad[prevgood]:
                prevgood -= 1

            nextgood = line + 1
            while nextgood < len(linelocs) and self.linebad[nextgood]:
                nextgood += 1

            firstcheck = 0 if self.rf.system == "PAL" else 1
            if prevgood >= firstcheck and nextgood < (len(linelocs) + self.lineoffset):
                gap = (linelocs[nextgood] - linelocs[prevgood]) / (nextgood - prevgood)
                linelocs[line] = (gap * (line - prevgood)) + linelocs[prevgood]

        return linelocs

    def computewow_scaled(self):
        """Compute how much the line deviates fron expected,
           and scale input samples to output samples
        """
        actual_linelocs = np.array(self.linelocs, dtype=np.float64)
        expected_linelocs = np.array(
            [i * self.inlinelen for i in range(len(actual_linelocs))], dtype=np.float64
        )

        outscale = self.inlinelen / self.outlinelen
        outsamples = self.outlinecount * self.outlinelen
        outline_offset = (self.lineoffset + 1) * self.outlinelen

        WOW_METHODS = {
            "linear": (1, None),
            "quadratic": (2, None),
            "cubic": (3, "natural"),
        }
        if self.wow_interpolation_method not in WOW_METHODS:
            raise ValueError(
                f"Invalid wow_interpolation_method: {self.wow_interpolation_method!r}"
                " (must be 'linear', 'quadratic', or 'cubic')"
            )
        k, bc_type = WOW_METHODS[self.wow_interpolation_method]

        # create a spline that interpolates the exact sample value based on expected vs. actual
        # line locations
        spl = interpolate.make_interp_spline(
            expected_linelocs, actual_linelocs, k=k, bc_type=bc_type, check_finite=False
        )

        # scale up to compute where the output pixel would fall on the interpolated line loc
        scaled_pixel_locs = np.arange(outsamples + outline_offset) * outscale

        # interpolate the expected pixel location
        self.interpolated_pixel_locs = spl(scaled_pixel_locs)
        # amount of wow for each scaled pixel
        self.wowfactors = spl(scaled_pixel_locs, 1)

        return self.interpolated_pixel_locs, self.wowfactors

    @profile
    def downscale(
        self,
        lineinfo=None,
        linesout=None,
        outwidth=None,
        channel="demod",
        audio=0,
        final=False,
        lastfieldwritten=None,
    ):
        if lineinfo is None:
            lineinfo = self.linelocs
        if outwidth is None:
            outwidth = self.outlinelen
        if linesout is None:
            # for video always output 263/313 lines
            linesout = self.outlinecount

        if lastfieldwritten and audio >= 16000:
            # This computes the current field based on checking the raw data location
            # against the last written field's, then computes the location of the
            # last audio sample written, so the A/V sync will remain (hopefully) correct

            rf_samples_per_field = self.rf.freq_hz / self.rf.SysParams['FPS'] / 2
            read_gap = (self.readloc - lastfieldwritten[1]) / rf_samples_per_field
            field_number = nb_round(lastfieldwritten[0] + read_gap)

            linecount = sum(self.rf.SysParams["field_lines"]) * (field_number // 2)
            if not self.isFirstField:
                linecount += self.rf.SysParams["field_lines"][0]

            # Now compute the # of audio samples that should be written, and then the
            # location of that relative to the current line
            samples_per_line = (self.rf.SysParams['line_period'] / 1000000) / (1 / audio)

            audsamp_count = linecount * samples_per_line
            audsamp_offset = (audsamp_count - np.floor(audsamp_count))

            if audsamp_offset > .5:
                audio_offset = (1 - audsamp_offset) * (1 / audio)
            else:
                audio_offset = -audsamp_offset * (1 / audio)
        else:
            # Either analog audio is disabled, or we're using hsync-locked sampling
            audio_offset = 0

        if audio != 0 and self.rf.decode_analog_audio:
            audio_rv = {}
            downscale_audio(
                self.data["audio"],
                lineinfo,
                self.rf,
                self.linecount,
                audio_offset,
                audio,
                audio_rv,
            )

        dsout = np.zeros((linesout * outwidth), dtype=np.float32)
        interpolated_pixel_locs, wowfactors = self.computewow_scaled()
        scale_field(
            self.data["video"][channel].astype(np.float32, copy=False),
            dsout,
            interpolated_pixel_locs,
            wowfactors,
            self.rf.downscale_sinc_lut,
            self.lineoffset,
            outwidth,
            wow_level_adjust_smoothing=self.wow_level_adjust_smoothing
        )

        if self.rf.decode_digital_audio:
            self.efmout = self.data["efm"][
                int(self.linelocs[1]) : int(self.linelocs[self.linecount + 1])
            ]
        else:
            self.efmout = None

        if final:
            dsout = self.hz_to_output(dsout)
            self.dspicture = dsout

        if audio != 0 and self.rf.decode_analog_audio:
            self.dsaudio = audio_rv["dsaudio"]
            self.audio_next_offset = audio_rv["audio_next_offset"]

        return dsout, self.dsaudio, self.efmout

    @profile
    def rf_tbc(self, linelocs=None):
        """ This outputs a TBC'd version of the input RF data, mostly intended
            to assist in audio processing.  Outputs a uint16 array.
        """

        # Convert raw RF to floating point to help the scaler
        fdata = self.data["input"].astype(float)

        if linelocs is None:
            linelocs = self.linelocs

        # Ensure that the output line length is an integer
        linelen = int(round(self.inlinelen))

        # Adjust for the demodulation/filtering delays
        delay = self.rf.delays["video_white"]

        # On PAL, always ignore self.lineoffset
        startline = self.lineoffset if self.rf.system == "NTSC" else 1
        endline = startline + self.linecount

        output = []

        for line in range(startline, endline):
            scaled = scale(fdata, linelocs[line] - delay, linelocs[line + 1] - delay, linelen)
            output.append(np.round(scaled).astype(np.int16))

        return np.concatenate(output)

    def decodephillipscode(self, linenum):
        linestart = self.linelocs[linenum]
        data = self.data["video"]["demod"]
        curzc = calczc(
            data,
            int(linestart + self.usectoinpx(2)),
            self.rf.iretohz(50),
            count=int(self.usectoinpx(12)),
        )

        zc = []
        while curzc is not None:
            zc.append(
                (curzc, data[int(curzc - self.usectoinpx(0.5))] < self.rf.iretohz(50))
            )
            curzc = calczc(
                data,
                curzc + self.usectoinpx(1.9),
                self.rf.iretohz(50),
                count=int(self.usectoinpx(0.2)),
            )

        usecgap = self.inpxtousec(np.diff([z[0] for z in zc]))
        valid = len(zc) == 24 and np.min(usecgap) > 1.85 and np.max(usecgap) < 2.15

        if valid:
            bitset = [z[1] for z in zc]
            linecode = np.int64(0)

            for b in range(0, 24, 4):
                linecode *= 0x10
                linecode += (np.packbits(bitset[b : b + 4]) >> 4)[0]

            return linecode

        return None

    def compute_syncconf(self):
        """ use final lineloc data to compute sync confidence """

        newconf = 100

        lld = np.diff(self.linelocs[self.lineoffset : self.lineoffset + self.linecount])
        lld2 = np.diff(lld)
        lld2max = np.max(lld2)

        if lld2max > 4:
            newconf = int(50 - (5 * np.sum(lld2 > 4)))

        newconf = max(newconf, 0)

        self.sync_confidence = min(self.sync_confidence, newconf)
        return int(self.sync_confidence)

    def get_vsync_area(self):
        """ return beginning, length in lines, and end of vsync area """
        vsync_begin = int(self.linelocs[0])
        vsync_end_line = int(self.getVBlankLength(self.isFirstField) + 0.6)
        vsync_end = int(self.linelocs[vsync_end_line]) + 1

        return vsync_begin, vsync_end_line, vsync_end

    def get_vsync_lines(self):
        rv = []
        end = 10 if self.isFirstField else 9
        for i in range(1, end):
            rv.append(i)

        if self.rf.system == 'PAL':
            start2 = 311 if self.isFirstField else 310
            for i in range(start2, 318):
                rv.append(i)

        return rv

    @profile
    def dropout_detect_demod(self):
        # current field
        f = self

        isPAL = self.rf.system == "PAL"

        rfstd = nb_std(f.data["rfhpf"])
        iserr_rf1 = (f.data["rfhpf"] < (-rfstd * 3)) | (
            f.data["rfhpf"] > (rfstd * 3)
        )  # | (f.rawdata <= -32000)
        iserr_rf = np.full_like(iserr_rf1, False)
        iserr_rf[self.rf.delays["video_rot"] :] = iserr_rf1[
            : -self.rf.delays["video_rot"]
        ]

        # Demod threshold flags are tracked separately from the RF flags so
        # that the sync-area unflagging below (which only knows the relaxed
        # demod thresholds) cannot erase RF-detected rot inside sync pulses.
        iserr = np.full_like(iserr_rf1, False)

        # Scalar thresholds for normal video and sync areas
        normal_min    = f.rf.iretohz(-70 if isPAL else -50)
        normal_max    = f.rf.iretohz(150 if isPAL else 160)
        normal_min_05 = f.rf.iretohz(-30)
        normal_max_05 = f.rf.iretohz(115)

        hsync_len   = int(f.LT['hsync'][1])
        vsync_ire   = f.rf.SysParams['vsync_ire']
        vsync_lines = set(self.get_vsync_lines())

        sync_min    = f.rf.iretohz(vsync_ire - 60 if isPAL else vsync_ire - 35)
        sync_min_05 = f.rf.iretohz(vsync_ire - 10)

        # Build sync region lookup: array of (start, end) for sync-min regions
        # and (start, end) for hsync-only regions
        demod = f.data["video"]["demod"]
        demod_05 = f.data["video"]["demod_05"]

        # Check normal regions with scalar comparison (avoids 4 large array allocs)
        n_ornotrange_scalar(iserr, demod, normal_min, normal_max)
        n_ornotrange_scalar(iserr, demod_05, normal_min_05, normal_max_05)

        # Un-flag sync areas where the lower thresholds apply
        for line in range(1, len(f.linelocs)):
            if line in vsync_lines:
                start = int(f.linelocs[line])
                end = int(f.linelocs[line + 1])
                _dropout_unflag_sync(iserr, demod, demod_05, start, end,
                                     sync_min, normal_max, sync_min_05, normal_max_05)
            else:
                start = int(f.linelocs[line])
                end = start + hsync_len
                _dropout_unflag_sync(iserr, demod, demod_05, start, end,
                                     sync_min, normal_max, sync_min_05, normal_max_05)

        iserr |= iserr_rf

        # detect absurd fluctuations in pre-deemp demod, since only dropouts can cause them
        n_orgt(iserr, f.data["video"]["demod_raw"], self.rf.freq_hz_half)

        # filter out dropouts outside actual field
        iserr[:int(f.linelocs[f.lineoffset + 1])] = False
        iserr[int(f.linelocs[f.lineoffset + f.linecount + 1]):] = False

        return iserr

    @profile
    def build_errlist(self, errmap):
        errlist = []

        firsterr = errmap[np.nonzero(errmap >= self.linelocs[self.lineoffset])[0][0]]
        curerr = (firsterr, firsterr)

        for e in errmap:
            if e > curerr[0] and e <= (curerr[1] + 20):
                pad = ((e - curerr[0])) * 1.7
                pad = min(pad, self.rf.freq * 12)
                epad = curerr[0] + pad
                curerr = (curerr[0], epad)
            elif e > firsterr:
                errlist.append((curerr[0] - 8, curerr[1] + 4))
                curerr = (e, e)

        errlist.append(curerr)

        return errlist

    @profile
    def dropout_errlist_to_tbc(self, errlist):
        """Convert data from raw data coordinates to tbc coordinates, and splits up
        multi-line dropouts.
        """
        dropouts = []

        if len(errlist) == 0:
            return dropouts

        # Now convert the above errlist into TBC locations
        errlistc = errlist.copy()
        lineoffset = -self.lineoffset

        # Remove dropouts occurring before the start of the frame so they don't
        # cause the rest to be skipped
        curerr = errlistc.pop(0)
        while len(errlistc) > 0 and curerr[0] < self.linelocs[self.lineoffset]:
            curerr = errlistc.pop(0)

        # TODO: This could be reworked to be a bit cleaner and more performant.

        for line in range(self.lineoffset, self.linecount + self.lineoffset):
            while curerr is not None and inrange(
                curerr[0], self.linelocs[line], self.linelocs[line + 1]
            ):
                start_rf_linepos = curerr[0] - self.linelocs[line]
                start_linepos = start_rf_linepos / (
                    self.linelocs[line + 1] - self.linelocs[line]
                )
                start_linepos = int(start_linepos * self.outlinelen)

                end_rf_linepos = curerr[1] - self.linelocs[line]
                end_linepos = end_rf_linepos / (
                    self.linelocs[line + 1] - self.linelocs[line]
                )
                end_linepos = nb_round(end_linepos * self.outlinelen)

                first_line = line + 1 + lineoffset

                # If the dropout spans multiple lines, we need to split it up into one for each
                # line.
                if end_linepos > self.outlinelen:
                    num_lines = end_linepos // self.outlinelen

                    # First line.
                    dropouts.append((first_line, start_linepos, self.outlinelen))
                    # Full lines in the middle.
                    for n in range(num_lines - 1):
                        dropouts.append((first_line + n + 1, 0, self.outlinelen))
                    # leftover on last line.
                    dropouts.append(
                        (
                            first_line + (num_lines),
                            0,
                            np.remainder(end_linepos, self.outlinelen),
                        )
                    )
                else:
                    dropouts.append((first_line, start_linepos, end_linepos))

                if len(errlistc):
                    curerr = errlistc.pop(0)
                else:
                    curerr = None

        return dropouts

    @profile
    def dropout_detect(self):
        """ returns dropouts in three arrays (lines, starts, ends). """

        rv_lines = []
        rv_starts = []
        rv_ends = []

        iserr = self.dropout_detect_demod()
        errmap = np.nonzero(iserr)[0]

        if len(errmap) > 0 and errmap[-1] > self.linelocs[self.lineoffset]:
            errlist = self.build_errlist(errmap)

            for r in self.dropout_errlist_to_tbc(errlist):
                rv_lines.append(r[0] - 1)
                rv_starts.append(int(r[1]))
                rv_ends.append(int(r[2]))

        return rv_lines, rv_starts, rv_ends

    @profile
    def compute_line_bursts(self, linelocs, _line, prev_phaseadjust=0):
        line = _line + self.lineoffset
        # calczc works from integers, so get the start and remainder
        s = int(linelocs[line])
        s_rem = linelocs[line] - s

        lfreq = self.get_linefreq(line)

        fsc_mhz_inv = 1 / self.rf.SysParams["fsc_mhz"]

        # compute approximate burst beginning/end
        bstime = 21 * fsc_mhz_inv  # approx start of core burst in usecs
        betime = 28 * fsc_mhz_inv  # approx end of core burst in usecs

        bstart = int(bstime * lfreq)
        bend   = int(betime * lfreq)

        # copy and get the mean of the burst area to factor out wow/flutter
        burstarea = self.data["video"]["demod_burst"][s + bstart : s + bend]
        if len(burstarea) == 0:
            return None, None

        burstarea = burstarea - nb_mean(burstarea)
        threshold = rms(burstarea)

        burstarea_demod = self.data["video"]["demod"][s + bstart : s + bend]
        burstarea_demod = burstarea_demod - nb_mean(burstarea_demod)

        if nb_absmax(burstarea_demod) > (30 * self.rf.DecoderParams["hz_ire"]):
            return None, None

        zcburstdiv = (lfreq * fsc_mhz_inv) / 2

        # Apply phase adjustment from previous frame/line if available.
        phase_adjust = -prev_phaseadjust

        # a proper color burst should have ~12-13 zero crossings
        isrising = np.zeros(16, dtype=np.bool_)
        zcs = np.zeros(16, dtype=np.float32)

        # The first pass computes phase_offset, the second uses it to determine
        # the colo(u)r burst phase of the line.
        for passcount in range(2):
            # this subroutine is in utils.py, broken out so it can be JIT'd
            zc_count, phase_adjust, rising_count = clb_findbursts(
                isrising, zcs, burstarea, 0, len(burstarea) - 1,
                threshold, bstart, s_rem, zcburstdiv, phase_adjust
            )

        rising = rising_count > (zc_count / 2)

        return rising, -phase_adjust


# These classes extend Field to do PAL/NTSC specific TBC features.


class FieldPAL(Field):
    burst_lines = (11, 313)
    burst_max_ire = 30
    output_black = 0x0100
    output_white = 0xD300

    def refine_linelocs_pilot(self, linelocs=None):
        if linelocs is None:
            linelocs = self.linelocs2.copy()
        else:
            linelocs = linelocs.copy()

        plen = {}

        zcs = []
        for line in range(0, 323):
            adjfreq = self.rf.freq
            if line > 1:
                adjfreq /= (linelocs[line] - linelocs[line - 1]) / self.rf.linelen

            plen[line] = (adjfreq / self.rf.SysParams["pilot_mhz"]) / 2

            ls = self.lineslice(line, 0, 6, linelocs)
            lsoffset = linelocs[line] - ls.start

            pilots = self.data["video"]["demod_pilot"][ls]

            peakloc = np.argmax(np.abs(pilots))

            zc_base = calczc(pilots, peakloc, 0)
            if zc_base is not None:
                zc = (zc_base - lsoffset) / plen[line]
            else:
                zc = zcs[-1] if len(zcs) else 0

            zcs.append(zc)

        angles = angular_mean_helper(np.array(zcs))
        am = np.angle(np.mean(angles)) / (np.pi * 2)
        if (am < 0):
            am = 1 + am

        for line in range(0, 323):
            linelocs[line] += (phase_distance(zcs[line], am) * plen[line]) * 1

        return np.array(linelocs)

    def get_following_field_number(self):
        if self.prevfield is not None:
            newphase = self.prevfield.fieldPhaseID + 1
            return 1 if newphase == 9 else newphase
        else:
            # This can be triggered by the first pass at the first field
            # logs.logger.error("Cannot determine PAL field sequence of first field")
            return 1

    def determine_field_number(self):

        """ Background
        PAL has an eight field sequence that can be split into two four field sequences.

        Field 1: First field of frame , no colour burst on line 6
        Field 2: Second field of frame, colour burst on line 6 (319)
        Field 3: First field of frame, colour burst on line 6
        Field 4: Second field of frame, no colour burst on line 6 (319)

        Fields 5-8 can be differentiated using the burst phase on line 7+4x (based off the first
        line guaranteed to have colour burst)  Ideally the rising phase would be at 0 or 180
        degrees, but since this is Laserdisc it's often quite off.  So the determination is
        based on which phase is closer to 0 degrees.
        """

        # First compute the 4-field sequence
        # This map is based in (first field, has burst on line 6)
        map4 = {(True, False): 1, (False, True): 2, (True, True): 3, (False, False): 4}

        # Determine if line 6 has valid burst - or lack of it.  If there's rot interference,
        # the burst level may be in the middle (or even None), and if so extrapolate
        # from the previous field.
        burstlevel6 = self.get_burstlevel(6)

        if burstlevel6 is None:
            return self.get_following_field_number()

        burstlevel6 /= self.rf.DecoderParams["hz_ire"]

        if inrange(burstlevel6, self.burstmedian * 0.8, self.burstmedian * 1.2):
            hasburst = True
        elif burstlevel6 < self.burstmedian * 0.2:
            hasburst = False
        else:
            return self.get_following_field_number()

        m4 = map4[(self.isFirstField, hasburst)]

        # Now compute if it's field 1-4 or 5-8.

        rcount = 0
        count  = 0

        self.phase_adjust = {}

        for line in range(7, 22, 4):
            # Usually line 7 is used to determine burst phase, but
            # take the best of 5 if it's unstable
            prev_phaseadjust = 0
            try:
                # For this first field, this doesn't exist (so use a try/except/pass pattern)
                # and on a bad disk, this value could be None...
                if self.prevfield.phase_adjust[line] is not None:
                    prev_phaseadjust = self.prevfield.phase_adjust[line]
            except (AttributeError, KeyError):
                pass

            rising, self.phase_adjust[line] = self.compute_line_bursts(
                self.linelocs, line, prev_phaseadjust
            )

            if rising is not None:
                rcount += (rising is True)
                count  += 1

        if count == 0 or (rcount * 2) == count:
            return self.get_following_field_number()

        # Use the # of rising edges to determine if it's the first or second half
        is_firstfour = (rcount * 2) > count
        if m4 == 2:
            # For field 2/6, reverse the above.
            is_firstfour = not is_firstfour

        return m4 + (0 if is_firstfour else 4)

    def process(self):
        super(FieldPAL, self).process()

        if not self.valid:
            return

        self.linelocs3 = self.refine_linelocs_pilot(self.linelocs2)
        # do a second pass for fine tuning (typically < .1px), because the adjusted
        # frequency changes slightly from the first pass
        self.linelocs3a = self.refine_linelocs_pilot(self.linelocs3)
        self.linelocs = self.fix_badlines(self.linelocs3a)

        self.burstmedian = self.calc_burstmedian()

        self.linecount = 312 if self.isFirstField else 313
        self.lineoffset = 2 if self.isFirstField else 3

        self.linecode = [
            self.decodephillipscode(line + self.lineoffset) for line in [16, 17, 18]
        ]

        self.fieldPhaseID = self.determine_field_number()


# CombNTSC and metric functions live in lddecode.metrics


class FieldNTSC(Field):
    phase_adjust_median = 0

    @profile
    def compute_burst_offsets(self, linelocs):
        rising_sum = 0
        adjs = {}

        for line in range(0, 266):
            prev_phaseadjust = self.phase_adjust_median

            if prev_phaseadjust == 0 and self.prevfield:
                prev_phaseadjust = self.prevfield.phase_adjust_median

            rising, phase_adjust = self.compute_line_bursts(linelocs, line, prev_phaseadjust)
            if rising is None:
                continue

            # For adjustments, 1/2 the phase_adjust value is used for better results
            # (todo: recheck)
            adjs[line] = phase_adjust / 2

            even_line = not (line % 2)
            rising_sum += 1 if (even_line and rising) else 0

        # If more than half of the lines have rising phase alignment, it's (probably) field 1 or 4
        field14 = rising_sum > (len(adjs.keys()) // 4)

        # store the full phase adjustment value here so things line up next time
        self.phase_adjust_median = np.median([adjs[a] for a in adjs]) * 2

        return field14, adjs

    @profile
    def refine_linelocs_burst(self, linelocs=None):
        if linelocs is None:
            linelocs = self.linelocs2

        linelocs_adj = linelocs.copy()

        field14, adjs_new = self.compute_burst_offsets(linelocs_adj)

        adjs = {}

        for line in range(1, 266):
            if line not in adjs_new:
                self.linebad[line] = True

        # compute the adjustments for each line but *do not* apply, so outliers can be bypassed
        for line in range(0, 266):
            if not (np.isnan(linelocs_adj[line]) or self.linebad[line]):
                lfreq = self.get_linefreq(line, linelocs)

                try:
                    adjs[line] = adjs_new[line] * lfreq * (1 / self.rf.SysParams["fsc_mhz"])
                except Exception:
                    # Not sure if this is an error or just control flow.

                    # traceback.print_exc()
                    pass

        if len(adjs.keys()):
            adjs_median = np.median([adjs[a] for a in adjs])
            lastvalid_adj = adjs_median

            for line in range(0, 266):
                if line in adjs and inrange(adjs[line] - adjs_median, -2, 2):
                    linelocs_adj[line] += adjs[line]
                    lastvalid_adj = adjs[line]
                else:
                    linelocs_adj[line] += lastvalid_adj

            # This map is based on (first field, field14)
            map4 = {
                (True, True): 1,
                (False, False): 2,
                (True, False): 3,
                (False, True): 4,
            }
            self.fieldPhaseID = map4[(self.isFirstField, field14)]
        else:
            self.fieldPhaseID = 1

        return linelocs_adj

    def downscale(self, lineoffset=0, final=False, *args, **kwargs):
        if not final:
            if "audio" in kwargs:
                kwargs["audio"] = 0

        dsout, dsaudio, dsefm = super(FieldNTSC, self).downscale(
            final=final, *args, **kwargs
        )

        return dsout, dsaudio, dsefm

    def apply_offsets(self, linelocs, phaseoffset, picoffset=0):
        return (
            np.array(linelocs)
            + picoffset
            + (phaseoffset * (self.rf.freq / self.rf.SysParams["outfreq"]))
        )

    @profile
    def process(self):
        super(FieldNTSC, self).process()

        if not self.valid:
            return

        self.linecode = [
            self.decodephillipscode(line + self.lineoffset) for line in [16, 17, 18]
        ]

        self.linelocs3 = self.refine_linelocs_burst(self.linelocs2)
        self.linelocs4 = self.fix_badlines(self.linelocs3, self.linelocs2)

        self.burstmedian = self.calc_burstmedian()

        # Subcarrier phase offset in degrees, calibrated for correct NTSC
        # burst phase (~147°) at the output.  Increasing it decreases the
        # output burst phase 1:1.  Calibrated per RF filter chain.
        fsc_phase_deg = self.rf.DecoderParams.get("fsc_phase_deg", 117.25)
        shift_samples = (fsc_phase_deg / 360) / self.rf.SysParams["fsc_mhz"] * self.rf.freq
        self.linelocs = np.array(self.linelocs4) - shift_samples


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

        if fname_out is not None:
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
            burst70 = vitsMetrics.get('ntscLine19Burst70IRE')
            snr3d   = vitsMetrics.get('ntscLine19Color3DRawSNR')
            burst0  = vitsMetrics.get('ntscLine19Burst0IRE')

            self.dbconn.execute('''
                INSERT INTO vits_metrics (
                    capture_id, field_id, w_snr, b_psnr,
                    ntsc_line19_burst70_ire, ntsc_line19_color_3d_raw_snr,
                    ntsc_line19_burst0_ire
                ) VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (c_id, f_id, w_snr, b_psnr, burst70, snr3d, burst0))

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

        if audio is not None and self.outfile_audio is not None:
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
