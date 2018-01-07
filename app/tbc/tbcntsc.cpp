/************************************************************************

    tcbntsc.cpp

    Time-Based Correction
    ld-decode - Software decode of Laserdiscs from raw RF
    Copyright (C) 2018 Chad Page
    Copyright (C) 2018 Simon Inns

    This file is part of ld-decode.

    ld-decode is free software: you can redistribute it and/or
    modify it under the terms of the GNU Lesser General Public License
    as published by the Free Software Foundation, either version 3 of
    the License, or (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

    Email: simon.inns@gmail.com

************************************************************************/

#include "tbcntsc.h"
#include "../../deemp.h"

TbcNtsc::TbcNtsc(quint16 fscSetting)
{
    // Note: FSC must be an even number
    // This was controlled by a define statement that
    // seemed to support FSC4, FSC10 or C32MHZ...
    switch(fscSetting) {
    case 10: // 10FSC
        c32mhz = false;
        videoInputFrequencyInFsc = 10.0;
        ntsc_iplinei = 227.5 * videoInputFrequencyInFsc; // pixels per line

        // Filters (used by process() and autoRange())
        longSyncFilter = new Filter(f_dsync10);
        f_syncid = new Filter(f_syncid10);
        f_endsync = new Filter(f_esync10);
        syncid_offset = syncid10_offset;
        break;

    case 32: // C32MHZ
        c32mhz = true;
        videoInputFrequencyInFsc = 32.0 / (315.0 / 88.0); // = 8.93
        ntsc_iplinei = 227.5 * videoInputFrequencyInFsc; // pixels per line

        // Filters (used by process() and autoRange())
        longSyncFilter = new Filter(f_dsync32);
        f_syncid = new Filter(f_syncid32);
        f_endsync = new Filter(f_esync32);
        syncid_offset = syncid32_offset;
        break;

    case 4: // FSC4
        c32mhz = false;
        videoInputFrequencyInFsc = 4.0;
        ntsc_iplinei = 227.5 * videoInputFrequencyInFsc; // pixels per line

        // Filters (used by process() and autoRange())
        longSyncFilter = new Filter(f_dsync4);
        f_syncid = new Filter(f_syncid4);
        f_endsync = new Filter(f_esync4);
        syncid_offset = syncid4_offset;
        break;

    default:
        c32mhz = false;
        videoInputFrequencyInFsc = 8.0;
        ntsc_iplinei = 227.5 * videoInputFrequencyInFsc; // pixels per line

        // Filters (used by process() and autoRange())
        longSyncFilter = new Filter(f_dsync);
        f_syncid = new Filter(f_syncid8);
        f_endsync = new Filter(f_esync8);
        syncid_offset = syncid8_offset;
    }

    // Global 'configuration'
    outputFrequencyInFsc = 4; // in FSC

    writeOnField = 1;
    f_flip = false;
    audio_only = false;
    performAutoRanging = (videoInputFrequencyInFsc == 4);
    freeze_frame = false;
    f_despackle = true;
    seven_five = (videoInputFrequencyInFsc == 4);
    f_highburst = false; // (FSC == 4);
    p_rotdetect = 40;

    f_debug = false;
    p_skipframes = 0;

    inscale = 327.68;
    inbase = (inscale * 20);	// IRE == -40
    a_read = 0;
    v_read = 0;
    va_ratio = 80;
    vblen = (ntsc_iplinei * 1100);	// should be divisible evenly by 16
    ablen = (ntsc_iplinei * 1100) / 40;
    absize = ablen * 8;
    vbsize = vblen * 2;
    abuf[ablen * 2];
    inbuf[vblen];

    // tunables
    afd = -1;
    fd = 0;
    black_ire = 7.5;
    write_locs = -1;

    // Globals for processAudio()
    afreq = 48000;
    prev_time = -1;
    next_audsample = 0;
    prev_loc = -1;
    prev_index = 0;
    prev_i = 0;

    // Globals for processAudioSample()
    pleft = 0;
    pright = 0;
    f_fml(f_fmdeemp);
    f_fmr(f_fmdeemp);
    aout_i = 0;

    // Audio output buffer
    aout[512];

    // Globals to do with the line processing functions
    // handlebadline() and processline()
    tline = 0;
    line = -2;
    phase = -1;
    first = true;
    frameno = -1;

    firstloc = -1;
    iline = 0;

    // Not sure yet...
    synclevel = inbase + (inscale * 15);

    // VBI? - Is this supposed to be based on FSC?  Looks like it...
    dots_usec = 4.0 * 315.0 / 88.0;

    // Despackle?
    out_x = 844;
    out_y = 505;

    // Autoset?
    low = 65535;
    high = 0;

    f[vblen];
    psync[ntsc_iplinei*1200];

    // Frame buffers
    frame[505][(int)(outputFrequencyInFsc * 211)];
    frameOriginal[505][(int)(outputFrequencyInFsc * 211)];
    deltaFrame[505][(int)(outputFrequencyInFsc * 211)];
    deltaFrameFilter[505][(int)(outputFrequencyInFsc * 211)];
}

qint32 TbcNtsc::execute(void)
{
    int rv = 0, arv = 0;
    long long dlen = -1;
    unsigned char *cinbuf = (unsigned char *)inbuf;
    unsigned char *cabuf = (unsigned char *)abuf;

    p_maxframes = 1 << 28;

    int c;

    if (p_skipframes > 0)
        p_maxframes += p_skipframes;

    qDebug() << "freq =" << videoInputFrequencyInFsc;

    rv = read(fd, inbuf, vbsize);
    while ((rv > 0) && (rv < vbsize)) {
        int rv2 = read(fd, &cinbuf[rv], vbsize - rv);
        if (rv2 <= 0) exit(0);
        rv += rv2;
    }

    qDebug() << "B" << absize << ablen * 2 * sizeof(float);

    if (afd != -1) {
        arv = read(afd, abuf, absize);
        while ((arv > 0) && (arv < absize)) {
            int arv2 = read(afd, &cabuf[arv], absize - arv);
            if (arv2 <= 0) exit(0);
            arv += arv2;
        }
    }

    memset(frame, 0, sizeof(frame));

    size_t aplen = 0;
    while (rv == vbsize && ((v_read < dlen) || (dlen < 0)) && (frameno < p_maxframes)) {
        if (performAutoRanging) {
            autoRange(inbuf, vbsize / 2);
        }

        int plen;

        plen = processVideoAndAudioBuffer(inbuf, rv / 2, abuf, arv / 8);

        if (plen < 0) {
            qDebug() << "skipping ahead";
            plen = vblen / 2;
        }

        v_read += plen;
        aplen = (v_read / va_ratio) - a_read;

        a_read += aplen;

//		qDebug() << "move " << plen << (vblen - plen) * 2;
        memmove(inbuf, &inbuf[plen], (vblen - plen) * 2);

                rv = read(fd, &inbuf[(vblen - plen)], plen * 2) + ((vblen - plen) * 2);
        while ((rv > 0) && (rv < vbsize)) {
            int rv2 = read(fd, &cinbuf[rv], vbsize - rv);
            if (rv2 <= 0) exit(0);
            rv += rv2;
        }

        if (afd != -1) {
            qDebug() << "AA " << plen << aplen << v_read << a_read << (double_t)v_read / (double_t)a_read;
            memmove(abuf, &abuf[aplen * 2], absize - (aplen * 8));
            qDebug() << abuf[0];

            arv = (absize - (aplen * 8));
            while (arv < absize) {
                int arv2 = read(afd, &cabuf[arv], absize - arv);
                if (arv2 <= 0) exit(0);
                arv += arv2;
            }

            if (arv == 0) exit(0);
        }
    }

    return 0;
}

// Private functions -------------------------------------------------------------------------------------

// should be autoRange(QVector<quint16> videoBuffer)
void TbcNtsc::autoRange(quint16 *videoBuffer, qint32 len, bool fullagc = true)
{
    int lowloc = -1;
    int checklen = (int)(videoInputFrequencyInFsc * 4);

    if (!fullagc) {
        low = 65535;
        high = 0;
    }

    qDebug() << "old base:scale =" << inbase << ':' << inscale;

//	f_longsync.clear(0);

    // phase 1:  get low (-40ire) and high (??ire)
    for (int i = 0; i < len; i++) {
        f[i] = longSyncFilter.feed(videoBuffer[i]);

        if ((i > (videoInputFrequencyInFsc * 256)) && (f[i] < low) && (f[i - checklen] < low)) {
            if (f[i - checklen] > f[i])
                low = f[i - checklen];
            else
                low = f[i];

            lowloc = i;
        }

        if ((i > (videoInputFrequencyInFsc * 256)) && (f[i] > high) && (f[i - checklen] > high)) {
            if (f[i - checklen] < f[i])
                high = f[i - checklen];
            else
                high = f[i];
        }
    }

    // phase 2: attempt to figure out the 0IRE porch near the sync

    if (!fullagc) {
        int gap = high - low;
        int nloc;

        for (nloc = lowloc; (nloc > lowloc - (videoInputFrequencyInFsc * 320)) && (f[nloc] < (low + (gap / 8))); nloc--);

        qDebug() << nloc << (lowloc - nloc) / videoInputFrequencyInFsc << f[nloc];

        nloc -= (videoInputFrequencyInFsc * 4);
        qDebug() << nloc << (lowloc - nloc) / videoInputFrequencyInFsc << f[nloc];

        qDebug() << "old base:scale =" << inbase << ':' << inscale;

        inscale = (f[nloc] - low) / ((seven_five) ? 47.5 : 40.0);
        inbase = low - (20 * inscale);	// -40IRE to -60IRE
        if (inbase < 1) inbase = 1;
        qDebug() << "new base:scale =" << inbase << ':' << inscale;
    } else {
        inscale = (high - low) / 140.0;
    }

    inbase = low;	// -40IRE to -60IRE
    if (inbase < 1) inbase = 1;

    qDebug() << "new base:scale =" << inbase << ':' << inscale << " low:" << low << high;

    synclevel = inbase + (inscale * 20);
}

// Should be:
//processVideoAndAudioBuffer(QVector<quint16> videoBuffer, qint32 videoBufferElementsToProcess,
//                                          QVector<double_t> audioBuffer, bool processAudioData, quint16 videoSyncLevel,
//                                          bool *isVideoFrameBufferReadyForWrite)
qint32 TbcNtsc::processVideoAndAudioBuffer(quint16 *videoBuffer, qint32 videoLength, double_t *audioBuffer,
                                           qint32 audioLength)
{
    double_t linebuf[1820];
    double_t hsyncs[253];
    int field = -1;
    int offset = 500;

    memset(frame, 0, sizeof(frame));

    while (field < 1) {
        //find_vsync(&buf[firstsync - 1920], len - (firstsync - 1920));
        int vs = findVsync(videoBuffer, videoLength, offset);

        bool oddeven = vs > 0;
        vs = abs(vs);
        qDebug() << "findvsync" << oddeven << vs;

        if ((oddeven == false) && (field == -1))
            return vs + (videoInputFrequencyInFsc * 227.5 * 240);

        // Process skip-frames mode - zoom forward an entire frame
        if (frameno < p_skipframes) {
            frameno++;
            return vs + (videoInputFrequencyInFsc * 227.5 * 510);
        }

        field++;

        // zoom ahead to close to the first full proper sync
        if (oddeven) {
            vs = abs(vs) + (750 * videoInputFrequencyInFsc);
        } else {
            vs = abs(vs) + (871 * videoInputFrequencyInFsc);
        }

        findHsyncs(videoBuffer, videoLength, vs, hsyncs);
        bool err[252];

        // find hsyncs (rough alignment)
        for (int line = 0; line < 252; line++) {
            err[line] = hsyncs[line] < 0;
            hsyncs[line] = abs(hsyncs[line]);
        }

        // Determine vsync->0/7.5IRE transition point (TODO: break into function)
        for (int line = 0; line < 252; line++) {
            if (err[line] == true) continue;

            double_t prev = 0, begsync = -1, endsync = -1;
            const uint16_t tpoint = ire_to_in(-20);

            // find beginning of hsync
            f_endsync.clear();
            prev = 0;
            for (int i = hsyncs[line] - (20 * videoInputFrequencyInFsc);
                 i < hsyncs[line] - (8 * videoInputFrequencyInFsc); i++) {
                double_t cur = f_endsync.feed(videoBuffer[i]);

                if ((prev > tpoint) && (cur < tpoint)) {
//					qDebug() << "B" << i << line << hsyncs[line];
                    double_t diff = cur - prev;
                    begsync = ((i - 8) + (tpoint - prev) / diff);

//					qDebug() << prev << tpoint << cur << hsyncs[line];
                    break;
                }
                prev = cur;
            }

            // find end of hsync
            f_endsync.clear();
            prev = 0;
            for (int i = hsyncs[line] - (2 * videoInputFrequencyInFsc);
                 i < hsyncs[line] + (4 * videoInputFrequencyInFsc); i++) {
                double_t cur = f_endsync.feed(videoBuffer[i]);

                if ((prev < tpoint) && (cur > tpoint)) {
//					qDebug() << "E" << line << hsyncs[line];
                    double_t diff = cur - prev;
                    endsync = ((i - 8) + (tpoint - prev) / diff);

//					qDebug() << prev << tpoint << cur << hsyncs[line];
                    break;
                }
                prev = cur;
            }

            qDebug() << "S" << line << begsync << endsync << endsync - begsync;

            if ((!inRangeCF(endsync - begsync, 15.75, 17.25)) || (begsync == -1) || (endsync == -1)) {
                err[line] = true;
            } else {
                hsyncs[line] = endsync;
            }
        }

        // We need semi-correct lines for the next phases
        correctDamagedHSyncs(hsyncs, err);

        bool phaseflip;
        double_t blevel[252], phase[252];
        double_t tpodd = 0, tpeven = 0;
        int nodd = 0, neven = 0; // need to track these to exclude bad lines
        double_t bphase = 0;
        // detect alignment (undamaged lines only)
        for (int line = 0; line < 64; line++) {
            double_t line1 = hsyncs[line], line2 = hsyncs[line + 1];

            if (err[line] == true) {
                qDebug() << "ERR" << line;
                continue;

            }

            // burst detection/correction
            scale(videoBuffer, linebuf, line1, line2, 227.5 * videoInputFrequencyInFsc);
            if (!burstDetect2(linebuf, videoInputFrequencyInFsc, 4, -1, blevel[line], bphase, phaseflip, true)) {
                qDebug() << "ERRnoburst" << line;
                err[line] = true;
                continue;
            }

            phase[line] = bphase;

            if (line % 2) {
                tpodd += phaseflip;
                nodd++;
            } else {
                tpeven += phaseflip;
                neven++;
            }

            qDebug() << "BURST" << line << line1 << line2 << blevel[line] << bphase;
        }

        bool fieldphase = fabs(tpeven / neven) < fabs(tpodd / nodd);
        qDebug() << "PHASES:" << neven + nodd << tpeven / neven << tpodd / nodd << fieldphase;

        for (int pass = 0; pass < 4; pass++) {
               for (int line = 0; line < 252; line++) {
            bool lphase = ((line % 2) == 0);
            if (fieldphase) lphase = !lphase;

            double_t line1c = hsyncs[line] + ((hsyncs[line + 1] - hsyncs[line]) * 14.0 / 227.5);

            scale(videoBuffer, linebuf, hsyncs[line], line1c, 14 * videoInputFrequencyInFsc);
            if (!burstDetect2(linebuf, videoInputFrequencyInFsc, 4, lphase, blevel[line], bphase, phaseflip, false)) {
                err[line] = true;
                continue;
            }

            double_t tgt = .260;
//			if (bphase > .5) tgt += .5;

            double_t adj = (tgt - bphase) * 8;

            if (f_debug) qDebug() << "ADJ" << line << pass << bphase << tgt << adj;
            hsyncs[line] -= adj;
           }
        }

        correctDamagedHSyncs(hsyncs, err);

        // final output
        for (int line = 0; line < 252; line++) {
            double_t line1 = hsyncs[line], line2 = hsyncs[line + 1];
            int oline = 3 + (line * 2) + (oddeven ? 0 : 1);

            // 33 degree shift
            double_t shift33 = (33.0 / 360.0) * 4 * 2;

            if (videoInputFrequencyInFsc == 4) {
                // XXX THIS IS BUGGED, but works
                shift33 = (107.0 / 360.0) * 4 * 2;
            }

            double_t pt = -12 - shift33; // align with previous-gen tbc output

            scale(videoBuffer, linebuf, line1 + pt, line2 + pt, 910, 0);

            double_t framepos = (line / 525.0) + frameno + (field * .50);

            if (!field) framepos -= .001;

            processAudio(framepos, v_read + hsyncs[line], audioBuffer);

            bool lphase = ((line % 2) == 0);
            if (fieldphase) lphase = !lphase;
            frame[oline][0] = (lphase == 0) ? 32768 : 16384;
            frame[oline][1] = blevel[line] * (327.68 / inscale); // ire_to_out(in_to_ire(blevel[line]));

            if (err[line]) {
                        frame[oline][3] = frame[oline][5] = 65000;
                    frame[oline][4] = frame[oline][6] = 0;
            }

            for (int t = 4; t < 844; t++) {
                double_t o = linebuf[t];

                if (performAutoRanging) o = ire_to_out(in_to_ire(o));

                frame[oline][t] = (uint16_t)clamp(o, 1, 65535);
            }
        }

        offset = abs(hsyncs[250]);

        qDebug() << "new offset" << offset;
    }

    if (f_despackle) despackle();

    // Decode VBI data
    decodeVBI();

    frameno++;
    qDebug() << "WRITING\n";
    write(1, frame, sizeof(frame));
    memset(frame, 0, sizeof(frame));

    return offset;
}

// Split this from the process() function
//void TbcPal::applyVideoLineFilters(quint16 *videoBuffer, quint16 *deempFilterBuffer, double_t *psync,
//                                   qint32 videoBufferElementsToProcess, quint16 videoSyncLevel)

// Seems to be missing...
//double_t TbcPal::processVideoLineIntoFrame(quint16 *videoBuffer, QVector<LineStruct> *lineDetails,
//                                           qint32 lineToProcess, bool isCalledByRecursion)

// These functions seem to be a more complex replacement for the above?
qint32 TbcNtsc::findSync(quint16 *videoBuffer, qint32 videoLength, qint32 tgt = 50, bool debug = false)
{
    const int pad = 96;
    int rv = -1;

    const uint16_t to_min = ire_to_in(-45), to_max = ire_to_in(-35);
    const uint16_t err_min = ire_to_in(-55), err_max = ire_to_in(30);

    uint16_t clen = tgt * 3;
    uint16_t circbuf[clen];
    uint16_t circbuf_err[clen];

    memset(circbuf, 0, clen * 2);
    memset(circbuf_err, 0, clen * 2);

    int count = 0, errcount = 0, peak = 0, peakloc = 0;

    for (int i = 0; (rv == -1) && (i < videoLength); i++) {
        int nv = (videoBuffer[i] >= to_min) && (videoBuffer[i] < to_max);
        int err = (videoBuffer[i] <= err_min) || (videoBuffer[i] >= err_max);

        count = count - circbuf[i % clen] + nv;
        circbuf[i % clen] = nv;

        errcount = errcount - circbuf_err[i % clen] + err;
        circbuf_err[i % clen] = err;

        if (count > peak) {
            peak = count;
            peakloc = i;
        } else if ((count > tgt) && ((i - peakloc) > pad)) {
            rv = peakloc;

            if ((videoInputFrequencyInFsc > 4) && (errcount > 1)) {
                qDebug() << "HERR" << errcount;
                rv = -rv;
            }
        }

        if (debug) {
            qDebug() << i << videoBuffer[i] << peak << peakloc << i - peakloc;
        }
    }

    if (rv == -1)
        qDebug() << "not found" << peak << peakloc;

    return rv;
}

// This could probably be used for more than just field det, but eh
qint32 TbcNtsc::countSlevel(quint16 *videoBuffer, qint32 begin, qint32 end)
{
    const uint16_t to_min = ire_to_in(-45), to_max = ire_to_in(-35);
    int count = 0;

    for (int i = begin; i < end; i++) {
        count += (videoBuffer[i] >= to_min) && (videoBuffer[i] < to_max);
    }

    return count;
}

// returns index of end of VSYNC - negative if _ field
qint32 TbcNtsc::findVsync(quint16 *videoBuffer, qint32 videoLength, qint32 offset = 0)
{
    const uint16_t field_len = videoInputFrequencyInFsc * 227.5 * 280;

    if (videoLength < field_len) return -1;

    int pulse_ends[6];
    int slen = videoLength;

    int loc = offset;

    for (int i = 0; i < 6; i++) {
        // 32xFSC is *much* shorter, but it shouldn't get confused for an hsync -
        // and on rotted disks and ones with burst in vsync, this helps
        int syncend = abs(findSync(&videoBuffer[loc], slen, 32 * videoInputFrequencyInFsc));

        pulse_ends[i] = syncend + loc;
        qDebug() << pulse_ends[i];

        loc += syncend;
        slen = 3840;
    }

    int rv = pulse_ends[5];

    // determine line type
    int before_end = pulse_ends[0] - (127.5 * videoInputFrequencyInFsc);
    int before_start = before_end - (227.5 * 4.5 * videoInputFrequencyInFsc);

    int pc_before = countSlevel(videoBuffer, before_start, before_end);

    int after_start = pulse_ends[5];
    int after_end = after_start + (227.5 * 4.5 * videoInputFrequencyInFsc);
    int pc_after = countSlevel(videoBuffer, after_start, after_end);

    qDebug() << "beforeafter:" << pulse_ends[0] + offset << pulse_ends[5] + offset << pc_before << pc_after;

    if (pc_before < pc_after) rv = -rv;

    return rv;
}

// returns end of each line, -end if error detected in this phase
// (caller responsible for freeing array)
bool TbcNtsc::findHsyncs(quint16 *videoBuffer, qint32 videoLength, qint32 offset, double_t *rv, qint32 nlines = 253)
{
    // sanity check (XXX: assert!)
    if (videoLength < (nlines * videoInputFrequencyInFsc * 227.5))
        return false;

    int loc = offset;

    for (int line = 0; line < nlines; line++) {
    //	qDebug() << line << loc;
        int syncend = findSync(&videoBuffer[loc], 227.5 * 3 * videoInputFrequencyInFsc,
                               8 * videoInputFrequencyInFsc);

        double_t gap = 227.5 * videoInputFrequencyInFsc;

        int err_offset = 0;
        while (syncend < -1) {
            qDebug() << "error found" << line << syncend << ' ';
            err_offset += gap;
            syncend = findSync(&videoBuffer[loc] + err_offset, 227.5 * 3 * videoInputFrequencyInFsc,
                               8 * videoInputFrequencyInFsc);
            qDebug() << syncend;
        }

        // If it skips a scan line, fake it
        if ((line > 0) && (line < nlines) && (syncend > (40 * videoInputFrequencyInFsc))) {
            rv[line] = -(abs(rv[line - 1]) + gap);
            qDebug() << "XX" << line << loc << syncend << rv[line];
            syncend -= gap;
            loc += gap;
        } else {
            rv[line] = loc + syncend;
            if (err_offset) rv[line] = -rv[line];

            if (syncend != -1) {
                loc += fabs(syncend) + (200 * videoInputFrequencyInFsc);
            } else {
                loc += gap;
            }
        }
    }

    return rv;
}

// correct damaged hsyncs by interpolating neighboring lines
void TbcNtsc::correctDamagedHSyncs(double_t *hsyncs, bool *err)
{
    for (int line = 1; line < 251; line++) {
        if (err[line] == false) continue;

        int lprev, lnext;

        for (lprev = line - 1; (err[lprev] == true) && (lprev >= 0); lprev--);
        for (lnext = line + 1; (err[lnext] == true) && (lnext < 252); lnext++);

        // This shouldn't happen...
        if ((lprev < 0) || (lnext == 252)) continue;

        double_t linex = (hsyncs[line] - hsyncs[0]) / line;

        qDebug() << "FIX" << line << linex << hsyncs[line] << hsyncs[line] - hsyncs[line - 1] << lprev << lnext ;

        double_t lavg = (hsyncs[lnext] - hsyncs[lprev]) / (lnext - lprev);
        hsyncs[line] = hsyncs[lprev] + (lavg * (line - lprev));
        qDebug() << hsyncs[line];
    }
}

// void TbcPal::processAudio(double_t frame, qint64 loc, double_t *audioBuffer)
void TbcNtsc::processAudio(double_t frameBuffer, qint64 loc, double_t *audioBuffer)
{
    double_t time = frameBuffer / (30000.0 / 1001.0);

    if (firstloc == -1) firstloc = loc;

    double_t framea = (double_t)(loc - firstloc) / 1820.0 / 525.0;

//	qDebug() << "PA" << frame << loc;
    if (afd < 0) return;

    if (prev_time >= 0) {
        while (next_audsample < time) {
            double_t i1 = (next_audsample - prev_time) / (time - prev_time);
            long long i = (i1 * (loc - prev_loc)) + prev_loc;

            if (i < v_read) {
                processAudioSample(f_fml.val(), f_fmr.val(), 1.0);
            } else {
                long long index = (i / va_ratio) - a_read;
                if (index >= ablen) {
                    qDebug() << "audio error" << frameBuffer << time << i1
                             << i << index << ablen;
                    index = ablen - 1;
//					exit(0);
                }
                float left = audioBuffer[index * 2], right = audioBuffer[(index * 2) + 1];
                double_t frameb = (double_t)(i - firstloc) / 1820.0 / 525.0;
                qDebug() << "A" << frameBuffer << loc << frameb << i1 << i << i - prev_i <<
                            index << index - prev_index << left << right;
                prev_index = index;
                prev_i = i;
                processAudioSample(left, right, 1.0);
            }

            next_audsample += 1.0 / afreq;
        }
    }

    prev_time = time; prev_loc = loc;
}

// void TbcPal::processAudioSample(float_t channelOne, float_t channelTwo)
void TbcNtsc::processAudioSample(double_t channelOne, double_t channelTwo, double_t velocity)
{
    channelOne = f_fml.feed(channelOne * (65535.0 / 300000.0));
    channelOne += 32768;

    channelTwo = f_fmr.feed(channelTwo * (65535.0 / 300000.0));
    channelTwo += 32768;

    aout[aout_i * 2] = clamp(channelOne, 0, 65535);
    aout[(aout_i * 2) + 1] = clamp(channelTwo, 0, 65535);

    aout_i++;
    if (aout_i == 256) {
        int rv = write(audio_only ? 1 : 3, aout, sizeof(aout));

        rv = aout_i = 0;
    }
}


// inline double_t TbcPal::clamp(double_t value, double_t lowValue, double_t highValue)
inline double_t TbcNtsc::clamp(double_t value, double_t lowValue, double_t highValue)
{
        if (value < lowValue) return lowValue;
        else if (value > highValue) return highValue;
        else return value;
}

// inline double_t TbcPal::in_to_ire(quint16 level)
inline double_t TbcNtsc::in_to_ire(quint16 level)
{
    if (level == 0) return -100;

    return -40 + ((double_t)(level - inbase) / inscale);
}

// inline quint16 TbcPal::ire_to_in(double_t ire)
inline quint16 TbcNtsc::ire_to_in(double_t ire)
{
    if (ire <= -60) return 0;

    return clamp(((ire + 40) * inscale) + inbase, 1, 65535);
}

// inline quint16 TbcPal::ire_to_out(double_t ire)
inline quint16 TbcNtsc::ire_to_out(double_t ire)
{
    if (ire <= -60) return 0;

    return clamp(((ire + 60) * 327.68) + 1, 1, 65535);
}

// This wasn't used in the PAL TBC
double_t TbcNtsc::out_to_ire(quint16 in)
{
    return (in / 327.68) - 60;
}

// inline double_t TbcPal::peakdetect_quad(double_t *y)
inline double_t TbcNtsc::peakdetect_quad(double_t *y)
{
    return (2 * (y[2] - y[0]) / (2 * (2 * y[1] - y[0] - y[2])));
}

// inline double_t TbcPal::cubicInterpolate(quint16 *y, double_t x)
// taken from http://www.paulinternet.nl/?page=bicubic
inline double_t TbcNtsc::cubicInterpolate(quint16 *y, double_t x)
{
    double_t p[4];
    p[0] = y[0]; p[1] = y[1]; p[2] = y[2]; p[3] = y[3];

    return p[1] + 0.5 * x*(p[2] - p[0] + x*(2.0*p[0] - 5.0*p[1] + 4.0*p[2] - p[3] + x*(3.0*(p[1] - p[2]) + p[3] - p[0])));
}

// inline void TbcPal::scale(quint16 *videoBuffer, double_t *outbuf, double_t start, double_t end, double_t outlen)
inline void TbcNtsc::scale(uint16_t *buf, double_t *outbuf, double_t start, double_t end,
                           double_t outlen, double_t offset = 0, qint32 from = 0, qint32 to = -1)
{
    double_t inlen = end - start;
    double_t perpel = inlen / outlen;

    if (to == -1) to = (int)outlen;

    double_t p1 = start + (offset * perpel);
    for (int i = from; i < to; i++) {
        int index = (int)p1;
        if (index < 1) index = 1;

        outbuf[i] = clamp(cubicInterpolate(&buf[index - 1], p1 - index), 0, 65535);

        p1 += perpel;
    }
}

// inline bool TbcPal::inRange(double_t v, double_t l, double_t h)
bool TbcNtsc::inRange(double_t v, double_t l, double_t h)
{
    return ((v > l) && (v < h));
}

// inline bool TbcPal::inRangeF(double_t v, double_t l, double_t h)
bool TbcNtsc::inRangeCF(double_t v, double_t l, double_t h)
{
    return inRange(v, l * videoInputFrequencyInFsc, h * videoInputFrequencyInFsc);
}

// bool TbcPal::pilotDetect(double_t *line, double_t loc, double_t &plevel, double_t &pphase)
// bool TbcPal::burstDetect(double_t *line, qint32 start, qint32 end, double_t &plevel, double_t &pphase)
bool TbcNtsc::burstDetect2(double_t *line, qint32 freq, double_t _loc, qint32 tgt, double_t &plevel,
                           double_t &pphase, bool &phaseflip, bool do_abs = false)
{
    int len = (6 * freq);
    int loc = _loc * freq;
    double_t start = 0 * freq;

    double_t peakh = 0, peakl = 0;
    int npeakh = 0, npeakl = 0;
    double_t lastpeakh = -1, lastpeakl = -1;

    double_t highmin = ire_to_in(f_highburst ? 11 : 9);
    double_t highmax = ire_to_in(f_highburst ? 23 : 22);
    double_t lowmin = ire_to_in(f_highburst ? -11 : -9);
    double_t lowmax = ire_to_in(f_highburst ? -23 : -22);

    int begin = loc + (start * freq);
    int end = begin + len;

    // first get average (probably should be a moving one)

    double_t avg = 0;
    for (int i = begin; i < end; i++) {
        avg += line[i];
    }
    avg /= (end - begin);

    // or we could just ass-u-me IRE 0...
    //avg = ire_to_in(0);

    // get first and last ZC's, along with first low-to-high transition
    double_t firstc = -1;
    double_t firstc_h = -1;
    double_t lastc = -1;

    double_t avg_htl_zc = 0, avg_lth_zc = 0;
    int n_htl_zc = 0, n_lth_zc = 0;

    for (int i = begin ; i < end; i++) {
        if ((line[i] > highmin) && (line[i] < highmax) && (line[i] > line[i - 1]) && (line[i] > line[i + 1])) {
            peakh += line[i];
            npeakh++;
            lastpeakh = i; lastpeakl = -1;
        } else if ((line[i] < lowmin) && (line[i] > lowmax) && (line[i] < line[i - 1]) && (line[i] < line[i + 1])) {
            peakl += line[i];
            npeakl++;
            lastpeakl = i; lastpeakh = -1;
        } else if (((line[i] >= avg) && (line[i - 1] < avg)) && (lastpeakl != -1)) {
            // XXX: figure this out quadratically
            double_t diff = line[i] - line[i - 1];
            double_t zc = i - ((line[i] - avg) / diff);

            if (firstc == -1) firstc = zc;
            if (firstc_h == -1) firstc_h = zc;
            lastc = zc;

            double_t ph_zc = (zc / freq) - floor(zc / freq);
            // XXX this has a potential edge case where a legit high # is wrapped
            if (ph_zc > .9) ph_zc -= 1.0;
            avg_lth_zc += ph_zc;
            n_lth_zc++;

            if (f_debug) qDebug() << "ZCH" << i << line[i - 1] << avg << line[i] << zc << ph_zc;
        } else if (((line[i] <= avg) && (line[i - 1] > avg)) && (lastpeakh != -1)) {
            // XXX: figure this out quadratically
            double_t diff = line[i] - line[i - 1];
            double_t zc = i - ((line[i] - avg) / diff);

            if (firstc == -1) firstc = zc;
            lastc = zc;

            double_t ph_zc = (zc / freq) - floor(zc / freq);
            // XXX this has a potential edge case where a legit high # is wrapped
            if (ph_zc > .9) ph_zc -= 1.0;
            avg_htl_zc += ph_zc;
            n_htl_zc++;

            if (f_debug) qDebug() << "ZCL" << i << line[i - 1] << avg << line[i] << zc <<  ph_zc;
        }
    }

//	qDebug() << "ZC" << n_htl_zc << n_lth_zc;

    if (n_htl_zc) {
        avg_htl_zc /= n_htl_zc;
    } else return false;

    if (n_lth_zc) {
        avg_lth_zc /= n_lth_zc;
    } else return false;

    if (f_debug) qDebug() << "PDETECT" << fabs(avg_htl_zc - avg_lth_zc) <<
                             n_htl_zc << avg_htl_zc << n_lth_zc << avg_lth_zc;

    double_t pdiff = fabs(avg_htl_zc - avg_lth_zc);

    if ((pdiff < .35) || (pdiff > .65)) return false;

    plevel = ((peakh / npeakh) - (peakl / npeakl)) / 4.3;

    if (avg_htl_zc < .5) {
        pphase = (avg_htl_zc + (avg_lth_zc - .5)) / 2;
        phaseflip = false;
    } else {
        pphase = (avg_lth_zc + (avg_htl_zc - .5)) / 2;
        phaseflip = true;
    }

    return true;
}

// inline bool TbcPal::isPeak(double_t *p, qint32 i)
bool TbcNtsc::isPeak(double_t *p, qint32 i)
{
    return (fabs(p[i]) >= fabs(p[i - 1])) && (fabs(p[i]) >= fabs(p[i + 1]));
}


// To be integrated ----------------------------------------------------------------------------------------


// Essential VBI/Phillips code reference: http://www.daphne-emu.com/mediawiki/index.php/VBIInfo
// (LD-V6000A info page is cryptic but very essential!)
quint32 TbcNtsc::readPhillipsCode(quint16 *line)
{
    int first_bit = -1; // 108 - dots_usec;
    uint32_t out = 0;

    double_t deltaLine[844];

    for (int i = 1; i < 843; i++) {
        deltaLine[i] = line[i] - line[i - 1];
    }

    // find first positive transition (exactly halfway into bit 0 which is *always* 1)
    for (int i = 70; (first_bit == -1) && (i < 140); i++) {
//		qDebug() << i << out_to_ire(line[i]) << Δline[i];
        if (isPeak(deltaLine, i) && (deltaLine[i] > 10 * 327.68)) {
            first_bit = i;
        }
    }
    if (first_bit < 0) return 0;

    for (int i = 0; i < 24; i++) {
        int rloc = -1, loc = (first_bit + (i * 2 * dots_usec));
        double_t rpeak = -1;

        for (int h = loc - 8; (h < loc + 8); h++) {
            if (isPeak(deltaLine, h)) {
                if (fabs(deltaLine[h]) > rpeak) {
                    rpeak = fabs(deltaLine[h]);
                    rloc = h;
                }
            }
        }

        if (rloc == -1) rloc = loc;

        out |= (deltaLine[rloc] > 0) ? (1 << (23 - i)) : 0;
        qDebug() << i << loc << deltaLine[loc] << rloc << deltaLine[rloc] << deltaLine[rloc] / inscale << out;

        if (!i) first_bit = rloc;
    }
    qDebug() << "P" << hex << out << dec;

    return out;
}

inline double_t TbcNtsc::max(double_t a, double_t b)
{
    return (a > b) ? a : b;
}

void TbcNtsc::despackle(void)
{
    memcpy(frameOriginal, frame, sizeof(frame));

    for (int y = 22; y < out_y; y++) {
        double_t rotdetect = p_rotdetect * inscale;

        for (int x = 60; x < out_x - 16; x++) {

            double_t comp = 0;

            for (int cy = y - 1; (cy < (y + 2)) && (cy < out_y); cy++) {
                for (int cx = x - 3; (cx < x + 3) && (cx < (out_x - 12)); cx++) {
                    comp = max(comp, deltaFrameFilter[cy][cx]);
                }
            }

            if ((out_to_ire(frame[y][x]) < -20) || (out_to_ire(frame[y][x]) > 140) ||
                    ((deltaFrame[y][x] > rotdetect) && ((deltaFrame[y][x] - comp) > rotdetect))) {
                qDebug() << "R" << y << x << rotdetect << deltaFrame[y][x] << comp << deltaFrameFilter[y][x];
                for (int m = x - 4; (m < (x + 14)) && (m < out_x); m++) {
                    double_t tmp = (((double_t)frameOriginal[y - 2][m - 2]) +
                            ((double_t)frameOriginal[y - 2][m + 2])) / 2;

                    if (y < (out_y - 3)) {
                        tmp /= 2;
                        tmp += ((((double_t)frameOriginal[y + 2][m - 2]) +
                                ((double_t)frameOriginal[y + 2][m + 2])) / 4);
                    }

                    frame[y][m] = clamp(tmp, 0, 65535);
                }
                x = x + 14;
            }
        }
    }
}

bool TbcNtsc::checkWhiteFlag(qint32 l)
{
    int wc = 0;

    for (int i = 100; i < 800; i++) {
        if (out_to_ire(frame[l][i]) > 80) wc++;
        if (wc >= 200) return true;
    }

    return false;
}

void TbcNtsc::decodeVBI(void)
{
    uint32_t code[6];

    uint32_t clv_time = 0;
    uint32_t chap = 0;
    uint32_t flags = 0;

    bool odd = false; // CAV framecode on odd scanline
    bool even = false; // on even scanline (need to report both, since some frames have none!)
    bool clv = false;
    bool cx  = false;
    int fnum = 0;

    memset(code, 0, sizeof(code));
    for (int i = 14; i < 20; i++) {
        code[i - 14] = readPhillipsCode(frame[i]);
    }
    qDebug() << "Phillips codes" << hex << code[0] << code[1] << code[2] << code[3] << code[4] << code[5] << dec;

    for (int i = 0; i < 6; i++) {
        frame[0][i * 2] = code[i] >> 16;
        frame[0][(i * 2) + 1] = code[i] & 0xffff;

        if ((code[i] & 0xf00fff) == 0x800fff) {
            chap =  ((code[i] & 0x00f000) >> 12);
            chap += (((code[i] & 0x0f0000) >> 16) - 8) * 10;
        }

        if ((code[i] & 0xfff000) == 0x8dc000) {
            cx = true;
        }

        if (0x87ffff == code[i]) {
            clv = true;
        }
    }

    if (clv == true) {
        uint16_t hours = 0;
        uint16_t minutes = 0;
        uint16_t seconds = 0;
        uint16_t framenum = 0;
        // Find CLV frame # data
        for (int i = 0; i < 6; i++) {
            // CLV Picture #
            if (((code[i] & 0xf0f000) == 0x80e000) && ((code[i] & 0x0f0000) >= 0x0a0000)) {
                seconds = (((code[i] & 0x0f0000) - 0x0a0000) >> 16) * 10;
                seconds += (code[i] & 0x000f00) >> 8;
                framenum = code[i] & 0x0f;
                framenum += ((code[i] & 0x000f0) >> 4) * 10;
            }
            if ((code[i] & 0xf0ff00) == 0xf0dd00) {
                hours = ((code[i] & 0x0f0000) >> 16);
                minutes = code[i] & 0x0f;
                minutes += ((code[i] & 0x000f0) >> 4) * 10;
            }
        }
        fnum = (((hours * 3600) + (minutes * 60) + seconds) * 30) + framenum;
        clv_time = (hours << 24) | (minutes << 16) || (seconds << 8) || framenum;
        qDebug() << "CLV" << hours << ':' << minutes << ':' << seconds << '.' << framenum;
    } else {
        for (int i = 0; i < 6; i++) {
            // CAV frame:  f80000 + frame
            if ((code[i] >= 0xf80000) && (code[i] <= 0xffffff)) {
                // Convert from BCD to binary
                fnum = code[i] & 0x0f;
                fnum += ((code[i] & 0x000f0) >> 4) * 10;
                fnum += ((code[i] & 0x00f00) >> 8) * 100;
                fnum += ((code[i] & 0x0f000) >> 12) * 1000;
                fnum += ((code[i] & 0xf0000) >> 16) * 10000;
                if (fnum >= 80000) fnum -= 80000;
                qDebug() << i << "CAV frame" << fnum;
                if (i % 2) odd = true;
                if (!(i % 2)) even = true;
            }
        }
    }
    qDebug() << "fnum" << fnum;

    flags = (clv ? FRAME_INFO_CLV : 0) | (even ? FRAME_INFO_CAV_EVEN : 0) |
            (odd ? FRAME_INFO_CAV_ODD : 0) | (cx ? FRAME_INFO_CX : 0);
    flags |= checkWhiteFlag(4) ? FRAME_INFO_WHITE_EVEN : 0;
    flags |= checkWhiteFlag(5) ? FRAME_INFO_WHITE_ODD  : 0;

    qDebug() << "Status" << hex << flags << dec << "chapter" << chap;

    frame[0][12] = chap;
    frame[0][13] = flags;
    frame[0][14] = fnum >> 16;
    frame[0][15] = fnum & 0xffff;
    frame[0][16] = clv_time >> 16;
    frame[0][17] = clv_time & 0xffff;
}

// Configuration parameter handling functions -----------------------------------------

// Set f_diff
void TbcNtsc::setShowDifferenceBetweenPixels(bool setting)
{
    // Doesn't appear to do anything useful...  Should this be removed?
    f_diff = setting;
}

// Set writeonfield
void TbcNtsc::setMagneticVideoMode(bool setting)
{
    if (setting) qInfo() << "Magnetic video mode is selected";
    if (setting) writeOnField = 1;
    else writeOnField = 2;
}

// Set f_flip
void TbcNtsc::setFlipFields(bool setting)
{
    if (setting) qInfo() << "Flip fields is selected";
    f_flip = setting;
}

// Set audio_only
void TbcNtsc::setAudioOnly(bool setting)
{
    if (setting) qInfo() << "Audio only is selected";
    audio_only = setting;
}

// Toggle do_autoset
void TbcNtsc::setPerformAutoSet(bool setting)
{
    if (setting) qInfo() << "Audio ranging is selected";
    if (setting) performAutoRanging = !performAutoRanging;
}

// Set despackle
void TbcNtsc::setPerformDespackle(bool setting)
{
    if (setting) qInfo() << "Despackle is selected";
    despackle = setting; // Seems to be always forced to false?
}

// Set freeze_frame
void TbcNtsc::setPerformFreezeFrame(bool setting)
{
    if (setting) qInfo() << "Perform freeze frame is selected";
    freeze_frame = setting;
}

// Set seven_five
void TbcNtsc::setPerformSevenFive(bool setting)
{
    if (setting) qInfo() << "Perform seven-five is selected";
    seven_five = setting;
}

// Toggle f_highburst
void TbcNtsc::setPerformHighBurst(bool setting)
{
    if (setting) qInfo() << "Perform high-burst is selected";
    if (setting) f_highburst = !f_highburst;
}

// Set the source video file's file name
void TbcNtsc::setSourceVideoFile(QString stringValue)
{
    sourceVideoFileName = stringValue;
}

// Set the source audio file's file name
void TbcNtsc::setSourceAudioFile(QString stringValue)
{
    sourceAudioFileName = stringValue;
}

// Set the target video file's file name
void TbcNtsc::setTargetVideoFile(QString stringValue)
{
    targetVideoFileName = stringValue;
}

// Set f_tol
void TbcNtsc::setTol(double_t value)
{
    f_tol = value;
}

// Set p_rotdetect
void TbcNtsc::setRot(double_t value)
{
    qInfo() << "setRot is not supported by the NTSC TBC";
    //p_rotdetect = value;
}

// Set skip frames
void TbcNtsc::setSkipFrames(qint32 value)
{
    p_skipframes = value;
}

// Set maximum frames
void TbcNtsc::setMaximumFrames(qint32 value)
{
    p_maxframes = value;
}


