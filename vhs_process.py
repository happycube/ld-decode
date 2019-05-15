import math
import numpy as np
import pandas as pd
import scipy as sp
import scipy.signal as sps
import scipy.fftpack as fftpack
import copy


import matplotlib.pyplot as plt

import lddecode_core as ldd
import lddutils as lddu
from lddutils import unwrap_hilbert, inrange

import vhs_formats

class FieldPALVHS(ldd.FieldPAL):
    def __init__(self, rf, rawdata, rawdecode, start, audio_offset = 0, keepraw = True):
        super(FieldPALVHS, self).__init__(rf, rawdata, rawdecode, start)


    def refine_linelocs_pilot(self, linelocs = None):
        if linelocs is None:
            linelocs = self.linelocs2.copy()
        else:
            linelocs = linelocs.copy()

        return linelocs


    #
    def compute_linelocs(self):
        """Try to find vsync and hsync locations."""

        # Use the halfway point for zero crossing and sync pulse length
        # VHS note - moved the range of this downwards slightly
        pulse_hz_min = self.rf.iretohz(self.rf.SysParams['vsync_ire'] - 20)
        pulse_hz_max = self.rf.iretohz((self.rf.SysParams['vsync_ire'] - 10) / 2)

        pulses = lddu.findareas_inrange(self.data[0]['demod_05'], pulse_hz_min, pulse_hz_max)

        # the ratio of sync pulses/data should be about .08.  If it's sharply different
        # this isn't valid video and the upper layer should skip ahead.

        psum = sum([z[2] for z in pulses])
        pulseratio = psum / pulses[-1][1]

        if not inrange(pulseratio, .05, .15):
            print("ERROR: invalid data pulseratio = ", pulseratio)
            return None, None

        vsync1 = self.find_vsync(pulses, 0)
        if vsync1 is None:
            print("ERROR: no vsync area found")
            return None, None, None

        vsync2 = self.find_vsync(pulses, vsync1[1])
        if vsync2 is None:
            print("ERROR: invalid data v2", vsync1)
            basepulse = vsync1[0] - 9
            if basepulse < 0:
                basepulse = 0

            return None, None, pulses[basepulse][0] + (self.inlinelen * self.outlinecount - 5)

        vsyncs = (*vsync1, *vsync2)

        # these are the expected gaps between beginning and end of vsyncs
        # (should be valid for both NTSC and PAL)

        fieldlen = self.rf.SysParams['frame_lines'] / 2

        vsync_length = 3 if self.rf.system == 'NTSC' else 2.5

        gaps = [(0, 2, fieldlen),
                (1, 2, fieldlen-vsync_length),
                (1, 3, fieldlen),
                (0, 3, fieldlen+vsync_length),
                (0, 1, vsync_length),
                (2, 3, vsync_length),]

        # Two passes are used here - the first establishes valid vsync areas and
        # determines the average line length, the second uses it to refine w/tighter
        # precision

        linelen = self.inlinelen

        for p in range(2):
            relvol = []
            validated = np.full(4, False)

            for i in gaps:
                # scale tolerance for short gaps
                # XXX: compare w/Dragons Lair metal-backed disk caps
                tol = i[2] * (.002 if p == 0 else .0005)

                ll = self.compute_distance(pulses, vsyncs[i[0]], vsyncs[i[1]], linelen, False)

                #print(i[0], i[1], ll, i[2]-tol, i[2]+tol)

                if inrange(ll, i[2]-tol, i[2]+tol):
                    #print('a')
                    validated[i[0]] = True
                    validated[i[1]] = True

                    # If this is an inter-field computation, use it to compute avg linelength
                    if i[2] > 200:
                        relvol.append(i[2] / ll)

            if len(relvol):
                linelen /= np.mean(relvol)
            else:
                break

        hsynclen_med = np.median([p[2] for p in pulses[vsyncs[1]+6:vsyncs[2]-6] if p[2] > self.usectoinpx(2.5)])
        hsynclen_min = hsynclen_med - self.usectoinpx(.2)
        hsynclen_max = hsynclen_med + self.usectoinpx(.2)

        # Save off beginnings of vsyncs
        # XXX: use ends - X lines when beginnings are invalid

        self.vsync1loc = pulses[vsyncs[0]][0]
        self.vsync2loc = pulses[vsyncs[2]][0]

        '''
        Get votes for whether or not this is a first or second field, using the distance between
        each line and the validated vsync pulses.
        '''

        vsyncedge_locations = (3.5, 6.5, 266, 269) if self.rf.system == 'NTSC' else (3, 5.5, 315.5, 318)

        dists = []

        for vsync_pnum, loc, valid in zip(vsyncs, vsyncedge_locations, validated):
            if not valid:
                continue

            for p in range(vsyncs[1], vsyncs[2]+1):
                if inrange(pulses[p][2], hsynclen_min, hsynclen_max):
                    l = self.compute_distance(pulses, vsync_pnum, p, linelen, round=True)

                    # apply a correction factor for vsync edges falling at .5H, so
                    # the distance computation is consistent .xH-wise against all of them
                    l += (.5 if loc != np.floor(loc) else 0)
                    dists.append(l != np.floor(l))

        # All that mess produces a 0.0-1.0 probability here, indicating where the vertical sync
        # area is relative to the regular lines.  This can then be used to determine if a field
        # is first or second... depending on standard. :)

        # VHS note: Added a not here temporarily. The fields seems to end up being swapped in ld-analyse,
        # inverting gives us the right order when checking "change field order" in analyse
        # TODO: Find out the proper fix here.
        self.isFirstField = not (np.mean(dists) < .5) if self.rf.system == 'PAL' else (np.mean(dists) > .5)

        # choose just one valid VSYNC.  If there are none, these fields are in bad shape ;)
        vsync_pulse = None

        for z in zip(vsyncs, vsyncedge_locations, validated):
            if z[2] == True:
                vsync_pulse = z[0]
                vsync_pulse_offset = z[1]

                # adjust the pulse offset by .5H if needed so that the computed line #'s
                # are properly aligned
                if self.rf.system == 'PAL':
                    vsync_pulse_offset -= (.5 if np.mean(dists) > .5 else 0)
                else:
                    vsync_pulse_offset += (.5 if np.mean(dists) > .5 else 0)

                break

        # Now build up a dictionary of line locations (it makes handling gaps easier)
        linelocs_dict = {}
        prevpulse = None

        for p in range(1, len(pulses)):
            # outside the vsync interval, enforce longer pulses
            minpulselen = 2.5 if ((p > (vsyncs[1]+7)) and (p < (vsyncs[2] - 7))) else 1.5

            if pulses[p][2] > self.usectoinpx(minpulselen):
                # Check if this pulse somewhat matches up to an expected pulse location.
                linenum = self.compute_distance(pulses, vsync_pulse, p, linelen, round=True) + vsync_pulse_offset

                if np.abs(linenum - np.round(linenum)) == 0:
                    if prevpulse is not None:
                        this_linelen = pulses[p][0] - pulses[prevpulse][0]
                    else:
                        this_linelen = linelen

                    # cover for skipped lines
                    while this_linelen > (linelen * 1.5):
                        this_linelen -= linelen

                    # Check if the detected line is within a reasonable tolerance window.
                    # Has to be a bit larger for VHS than LD, may have to increase it further for bad
                    # tapes.
                    # TODO:  use running average of last X line lengths for comparison?
                    if inrange(this_linelen, linelen *.80, linelen * 1.20):
                        linelocs_dict[linenum] = pulses[p][0]

                        prevpulse = p

        # Convert dictionary into list, then fill in gaps
        linelocs = [linelocs_dict[l] if l in linelocs_dict else -1 for l in range(0, self.outlinecount + 6)]
        linelocs_filled = linelocs.copy()

        #print("Line locs: ", linelocs)
        #print("self.outlinecount + 6" , self.outlinecount + 6)

        for l in range(1, self.outlinecount + 6):
            if linelocs_filled[l] < 0:
                prev_valid = None
                next_valid = None

                for i in range(l, -10, -1):
                    if linelocs[i] > 0:
                        prev_valid = i
                        break
                for i in range(l, self.outlinecount + 1):
                    if linelocs[i] > 0:
                        next_valid = i
                        break

                if prev_valid is None and next_valid is None:
                    avglen = self.inlinelen
                    linelocs2[l] = avglen * l
                elif prev_valid is None:
                    avglen = self.inlinelen
                    linelocs_filled[l] = linelocs[next_valid] - (avglen * (next_valid - l))
                elif next_valid is not None:
                    avglen = (linelocs[next_valid] - linelocs[prev_valid]) / (next_valid - prev_valid)
                    #avglen = self.inlinelen
                    linelocs_filled[l] = linelocs[prev_valid] + (avglen * (l - prev_valid))
                else:
                    #avglen = (linelocs[next_valid] - linelocs[prev_valid]) / (next_valid - prev_valid)
                    avglen = self.inlinelen
                    linelocs_filled[l] = linelocs[prev_valid] + (avglen * (l - prev_valid))

                #print(l, prev_valid, next_valid, linelocs_filled[l], avglen)

        # *finally* done :)

        rv_ll = [linelocs_filled[l] for l in range(0, self.outlinecount + 6)]
        rv_err = [linelocs[l] <= 0 for l in range(0, self.outlinecount + 6)]

        #print(rv_ll[0])

        return rv_ll, rv_err, pulses[vsync2[0] - 9][0]


    def refine_linelocs_hsync(self):
        """Refine the hsync locations.
        The LD implementation doesn't seem to work well with VHS, so we just skip this for now as
        the original locations gives a reasonable result.
        """
        linelocs2 = self.linelocs1.copy()
        return linelocs2

# Superclass to override laserdisc-specific parts of ld-decode with stuff that works for VHS
#
# We do this simply by using inheritance and overriding functions. This results in some redundant
# work that is later overridden, but avoids altering any ld-decode code to ease merging back in
# later as the ld-decode is in flux at the moment.
class VHSDecode(ldd.LDdecode):
    def __init__(self, fname_in, fname_out, freader, system = 'NTSC', doDOD = False,
                 inputfreq = 40):
        super(VHSDecode, self).__init__(fname_in, fname_out, freader, analog_audio = False,
                                        system = system, doDOD = doDOD)
        # Overwrite the rf decoder with the VHS-altered one
        self.rf = VHSRFDecode(system = system, inputfreq = inputfreq)
        self.FieldClass = FieldPALVHS

    # Override to avoid NaN in JSON.
    def calcsnr(self, f, snrslice):
        data = f.output_to_ire(f.dspicture[snrslice])

        signal = np.mean(data)
        noise = np.std(data)

        # Make sure signal is positive so we don't try to do log on a negative value.
        if signal < 0.0:
                print("WARNING: Negative mean for SNR, changing to absolute value.")
                signal = abs(signal)

        return 20 * np.log10(signal / noise)

    def calcpsnr(self, f, snrslice):
        data = f.output_to_ire(f.dspicture[snrslice])

#        signal = np.mean(data)
        noise = np.std(data)

        return 20 * np.log10(100 / noise)

    def buildmetadata(self, f):
        if math.isnan(f.burstmedian):
            f.burstmedian = 0.0
        return super(VHSDecode, self).buildmetadata(f)

    # For laserdisc this decodes frame numbers from VBI metadata, but there won't be such a thing on
    # VHS, so just skip it.
    def decodeFrameNumber(self, f1, f2):
        return None

class VHSRFDecode(ldd.RFDecode):
    def __init__(self, inputfreq = 40, system = 'NTSC'):
        # First init the rf decoder normally.
        super(VHSRFDecode, self).__init__(inputfreq, system, decode_analog_audio = False,
                                              have_analog_audio = False)

        # Then we override the laserdisc parameters with VHS ones.
        if system == 'PAL':
                # Give the decoder it's separate own full copy to be on the safe side.
            self.SysParams = copy.deepcopy(vhs_formats.SysParams_PAL_VHS)
            self.DecoderParams = copy.deepcopy(vhs_formats.RFParams_PAL_VHS)
        else:
            print("Non-PAL Not implemented yet!")
            exit(1)

                    # Lastly we re-create the filters with the new parameters.
        self.computevideofilters()

        cc = vhs_formats.VHS_COLOR_CARRIER_MHZ

#        video_lpf = sps.butter(4,((vhs_formats.VHS_COLOR_CARRIER_MHZ + 0.05)/self.freq_half), 'low')
        video_lpf = sps.butter(4, [(cc-.15)/self.freq_half, (cc+.15)/self.freq_half], btype='bandpass')
        self.Filters['FVideoBurst'] = lddu.filtfft(video_lpf, self.blocklen)

        #plt.ion()
        #plt.show()
        #self.fig, self.ax1 = plt.subplots()
        #self.ax2 = self.ax1.twinx()


        # Override computedelays
        # It's normally used for dropout compensation, but the dropout compensation implementation
        # in ld-decode assumes composite color. This function is called even if it's disabled, and
        # seems to break with the VHS setup, so we disable it by overriding it for now.
    def computedelays(self, mtf_level = 0):
        # Set these to 0 for now, the metrics calculations look for them.
        self.delays = {}
        self.delays['video_sync'] = 0
        self.delays['video_white'] = 0

    def demodblock(self, data, mtf_level = 0):
        rv_efm = None

        mtf_level *= self.mtf_mult
        if self.system == 'NTSC':
            mtf_level *= .7
        mtf_level += self.mtf_offset

        indata_fft = np.fft.fft(data[:self.blocklen])
        indata_fft_filt = indata_fft * self.Filters['RFVideo']

        if mtf_level != 0:
            indata_fft_filt *= self.Filters['MTF'] ** mtf_level

        hilbert = np.fft.ifft(indata_fft_filt)
        demod = unwrap_hilbert(hilbert, self.freq_hz)

        demod_fft = np.fft.fft(demod)

        out_video = np.fft.ifft(demod_fft * self.Filters['FVideo']).real

        out_video05 = np.fft.ifft(demod_fft * self.Filters['FVideo05']).real
        out_video05 = np.roll(out_video05, -self.Filters['F05_offset'])

        min_level = np.nanmin(out_video05)
        min_ire = self.hztoire(min_level)
        sync_filter_high = self.iretohz(min_ire + 35)

        out_videoburst = np.fft.ifft(indata_fft * self.Filters['FVideoBurst']).real

        # NTSC: filtering for vsync pulses from -55 to -25ire seems to work well even on rotted disks
        # Need to change to
        output_sync = inrange(out_video05, min_ire, sync_filter_high)
        # Perform FFT convolution of above filter
        output_syncf = np.fft.ifft(np.fft.fft(output_sync) * self.Filters['FPsync']).real

        #print("min_ire ", min_ire)

        if self.system == 'PAL':
            out_videopilot = np.fft.ifft(demod_fft * self.Filters['FVideoPilot']).real
            rv_video = np.rec.array([out_video, demod, out_video05, output_syncf, out_videoburst, out_videopilot], names=['demod', 'demod_raw', 'demod_05', 'demod_sync', 'demod_burst', 'demod_pilot'])
        else:
            rv_video = np.rec.array([out_video, demod, out_video05, output_syncf, out_videoburst], names=['demod', 'demod_raw', 'demod_05', 'demod_sync', 'demod_burst'])

        if False:
            self.fig, self.ax1 = plt.subplots()
            self.ax2 = self.ax1.twinx()
            fig, ax1 = self.fig, self.ax1
            #fig.clf()
            #fig.cla()
            ax1.cla()

            ax1.axhline(self.iretohz(-55))
            ax1.axhline(self.iretohz(-25))

            color = 'tab:red'
            ax1.axhline(self.iretohz(self.SysParams['vsync_ire']), color=color)
            ax1.axhline(self.iretohz(0), color='0.0')
            ax1.axhline(min_level, color='#00FF00')
            ax1.axhline(sync_filter_high, color='#0000FF')

            ax1.plot(range(0, len(out_video)), out_video)
            ax1.plot(range(0, len(out_video05)), out_video05)

            ax2 = self.ax2#ax1.twinx()
            ax2.cla()

            ax2.plot(range(0, len(out_videoburst)), out_videoburst, color='#FF0000')

#            ax2.plot(range(0, len(output_syncf)), output_syncf, color='tab:green')
#            ax2.plot(range(0, len(output_sync)), output_sync, color='tab:gray')


            #fig.tight_layout()

            #	plt.plot(range(0, len(doutput)), doutput)
            #	plt.plot(range(0, len(output_prefilt)), output_prefilt)
            #plt.show()
            #        plt.draw()

            #fig.canvas.draw()
            #fig.canvas.flush_events()
            plt.show()
            #plt.pause(0.1)

        if self.decode_analog_audio == False:
            return rv_video, None, rv_efm

        # Audio phase 1
        hilbert = np.fft.ifft(self.audio_fdslice(indata_fft) * self.Filters['audio_lfilt'])
        audio_left = unwrap_hilbert(hilbert, self.Filters['freq_arf']) + self.Filters['audio_lowfreq']

        hilbert = np.fft.ifft(self.audio_fdslice(indata_fft) * self.Filters['audio_rfilt'])
        audio_right = unwrap_hilbert(hilbert, self.Filters['freq_arf']) + self.Filters['audio_lowfreq']

        rv_audio = np.rec.array([audio_left, audio_right], names=['audio_left', 'audio_right'])

        return rv_video, rv_audio, rv_efm
