/************************************************************************

    tcbntsc.h

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

#ifndef TBCNTSC_H
#define TBCNTSC_H

#include <QCoreApplication>
#include <QDebug>
#include <QFile>
#include <QDataStream>
#include <QVector>

// Needed for reading and writing to stdin/stdout
#include <stdio.h>

#include "filter.h"

class TbcNtsc
{
public:
    TbcNtsc(quint16 fscSetting);
    qint32 execute(void);

private:


    // Unsorted NTSC globals...
    #define OUT_FREQ 4

    bool c32mhz;
    double_t FSC;	// in FSC.  Must be an even number!
    Filter *f_longsync;
    Filter *f_syncid;
    Filter *f_endsync;
    qint32 syncid_offset;

    // Global 'configuration'
    qint32 writeonfield;
    bool f_flip;
    bool audio_only;
    bool do_autoset;
    bool freeze_frame;
    bool despackle;
    bool seven_five;
    bool f_highburst;
    double_t p_rotdetect;

    bool f_debug;
    qint32 p_skipframes;
    qint32 ntsc_iplinei;

    double_t inscale;
    double_t inbase;
    qint64 a_read;
    qint64 v_read;
    qint32 va_ratio;
    qint32 vblen;
    qint32 ablen;
    qint32 absize;
    qint32 vbsize;
    double_t abuf[ablen * 2];
    quint8 inbuf[vblen];

    // tunables
    qint32 afd;
    qint32 fd;
    double_t black_ire;
    qint32 write_locs;

    // Globals for processAudio()
    double_t afreq;
    double_t prev_time;
    double_t next_audsample;
    size_t prev_loc;
    qint64 prev_index;
    qint64 prev_i;

    // Globals for processAudioSample()
    double_t pleft;
    double_t pright;
    Filter *f_fml;
    Filter *f_fmr;
    qint32 aout_i;

    // Audio output buffer
    uint16_t aout[512];

    // Globals to do with the line processing functions
    // handlebadline() and processline()
    double_t tline;
    double_t line;
    qint32 phase;
    bool first;
    qint32 frameno;

    qint64 firstloc;
    qint32 iline;

    // Not sure yet...
    uint16_t synclevel;

    // VBI?
    double_t dots_usec;

    // Despackle?
    const qint32 out_x;
    const qint32 out_y;

    // Autoset?
    double_t low;
    double_t high;

    double_t f[vblen];
    double_t psync[ntsc_iplinei*1200];

    // Frame buffers
    uint16_t frame[505][(qint32)(OUT_FREQ * 211)];
    uint16_t frame_orig[505][(qint32)(OUT_FREQ * 211)];
    double_t Δframe[505][(qint32)(OUT_FREQ * 211)];
    double_t Δframe_filt[505][(qint32)(OUT_FREQ * 211)];


    // Private functions
    void autoset(quint16 *buf, qint32 len, bool fullagc = true);
    qint32 Process(quint16 *buf, qint32 len, double_t *abuf, qint32 alen);
    qint32 find_sync(quint16 *buf, qint32 len, qint32 tgt = 50, bool debug = false);
    qint32 count_slevel(quint16 *buf, qint32 begin, qint32 end);
    qint32 find_vsync(quint16 *buf, qint32 len, qint32 offset = 0);
    bool find_hsyncs(quint16 *buf, qint32 len, qint32 offset, double_t *rv, qint32 nlines = 253);
    void CorrectDamagedHSyncs(double_t *hsyncs, bool *err);
    void ProcessAudio(double_t frame, qint64 loc, double_t *abuf);
    void ProcessAudioSample(double_t left, double_t right, double_t vel);

    inline double_t clamp(double_t v, double_t low, double_t high);
    inline double_t in_to_ire(quint16 level);
    inline quint16 ire_to_in(double_t ire);
    inline quint16 ire_to_out(double_t ire);
    double_t out_to_ire(quint16 in);
    inline double_t peakdetect_quad(double_t *y);
    inline double_t CubicInterpolate(quint16 *y, double_t x);
    inline void Scale(uint16_t *buf, double_t *outbuf, double_t start, double_t end, double_t outlen, double_t offset = 0, qint32 from = 0, qint32 to = -1);
    bool InRange(double_t v, double_t l, double_t h);
    bool InRangeCF(double_t v, double_t l, double_t h);
    bool BurstDetect2(double_t *line, qint32 freq, double_t _loc, qint32 tgt, double_t &plevel, double_t &pphase, bool &phaseflip, bool do_abs = false);
    bool IsPeak(double_t *p, qint32 i);

    quint32 ReadPhillipsCode(quint16 *line);
    inline double_t max(double_t a, double_t b);
    void Despackle(void);
    bool CheckWhiteFlag(qint32 l);
    void DecodeVBI(void);
};

#endif // TBCNTSC_H
