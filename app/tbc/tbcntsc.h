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

    // Execute the time-based correction
    qint32 execute(void);

    // TBC NTSC parameter settings
    void setShowDifferenceBetweenPixels(bool setting);
    void setMagneticVideoMode(bool setting);
    void setFlipFields(bool setting);
    void setAudioOnly(bool setting);
    void setPerformAutoSet(bool setting);
    void setPerformDespackle(bool setting);
    void setPerformFreezeFrame(bool setting);
    void setPerformSevenFive(bool setting);
    void setPerformHighBurst(bool setting);
    void setSourceVideoFile(QString stringValue);
    void setSourceAudioFile(QString stringValue);
    void setTargetVideoFile(QString stringValue);
    void setTargetAudioFile(QString stringValue);
    void setTol(double_t value);
    void setRot(double_t value);
    void setSkipFrames(qint32 value);
    void setMaximumFrames(qint32 value);

private:
    // Private configuration globals that have
    // matching 'set' functions to manipulate
    // the setting publicly (for command line
    // options)
    struct tbcConfigurationStruct {
        qint32 writeOnField;
        bool f_flip;
        bool audio_only;
        bool performAutoRanging;
        bool freeze_frame;
        bool f_despackle;
        bool seven_five;
        bool f_highburst;
        double_t p_rotdetect;
        qint32 p_skipframes;
        qint32 p_maxframes;

        QString sourceVideoFileName;
        QString sourceAudioFileName;
        QString targetVideoFileName;
        QString targetAudioFileName;
    } tbcConfiguration;

    // Other configuration which does not have a 'set' function
    // in the class to set or get the value
    bool c32mhz;
    double_t videoInputFrequencyInFsc;	// in FSC.  Must be an even number!
    qint32 ntsc_iplinei;

    // Globals for processAudio()
    struct processAudioStateStruct {
        double_t afreq;
        double_t prev_time;
        double_t nextAudioSample;
        size_t prev_loc;
        qint64 prev_index;
        qint64 prev_i;
        qint64 firstloc;

        qint64 a_read;
        qint64 v_read;
        qint32 va_ratio;

        // Globals for processAudioSample()
        Filter *audioChannelOneFilter;
        Filter *audioChannelTwoFilter;
        qint32 audioOutputBufferPointer;
    } processAudioState;

    // Globals to do with the line processing functions
    // handlebadline() and processline()
    struct processLineStateStruct {
        qint32 frameno;
    } processLineState;

    // Auto-ranging state
    struct autoRangeStateStruct {
        double_t low;
        double_t high;
        Filter *longSyncFilter;
        Filter *f_endsync;

        double_t inputMaximumIreLevel;
        double_t inputMinimumIreLevel;
    } autoRangeState;

    // Two-dimensional (time-corrected) video frame buffer
    //quint16 videoOutputBuffer[505][844]; // Frame buffer (844 'pixels' x 505 lines for NTSC and 610x1052 for PAL (with FSC=4))

    // Private functions
    quint16 autoRange(QVector<quint16> &videoInputBuffer);
    qint32 processVideoAndAudioBuffer(QVector<quint16> videoInputBuffer, qint32 videoInputBufferElementsToProcess,
                                      QVector<double_t> audioInputBuffer, bool processAudioData,
                                      bool *isVideoFrameBufferReadyForWrite, bool *isAudioBufferReadyForWrite,
                                      QVector<QVector<quint16> > &videoOutputBuffer, QVector<quint16> &audioOutputBuffer);

    qint32 findSync(quint16 *videoBuffer, qint32 videoLength);
    qint32 findSync(quint16 *videoBuffer, qint32 videoLength, qint32 tgt);

    qint32 countSlevel(quint16 *videoBuffer, qint32 begin, qint32 end);

    qint32 findVsync(quint16 *videoBuffer, qint32 videoLength);
    qint32 findVsync(quint16 *videoInputBuffer, qint32 videoLength, qint32 offset);

    bool findHsyncs(quint16 *videoBuffer, qint32 videoLength, qint32 offset, double_t *horizontalSyncs);
    bool findHsyncs(quint16 *videoBuffer, qint32 videoLength, qint32 offset, double_t *horizontalSyncs, qint32 nlines);

    void correctDamagedHSyncs(double_t *hsyncs, bool *err);

    bool processAudio(double_t frameBuffer, qint64 loc, double_t *audioInputBuffer, quint16 *audioOutputBuffer);
    bool processAudioSample(double_t channelOne, double_t channelTwo, quint16 *audioOutputBuffer);

    inline double_t clamp(double_t value, double_t lowValue, double_t highValue);

    inline double_t in_to_ire(quint16 level);
    inline quint16 ire_to_in(double_t ire);
    inline quint16 ire_to_out(double_t ire);
    double_t out_to_ire(quint16 in);
    inline double_t peakdetect_quad(double_t *y);

    inline double_t cubicInterpolate(quint16 *y, double_t x);

    void scale(quint16 *buf, double_t *outbuf, double_t start, double_t end, double_t outlen);
    void scale(quint16 *buf, double_t *outbuf, double_t start, double_t end, double_t outlen, double_t offset);
    void scale(quint16 *buf, double_t *outbuf, double_t start, double_t end, double_t outlen, double_t offset,
               qint32 from, qint32 to);

    bool inRange(double_t v, double_t l, double_t h);
    bool inRangeCF(double_t v, double_t l, double_t h);

    bool burstDetect2(double_t *line, qint32 freq, double_t _loc, double_t &plevel, double_t &pphase, bool &phaseflip);
    bool isPeak(QVector<double_t> p, qint32 i);
    void despackle(QVector<QVector<quint16> > &videoOutputBuffer);

    quint32 readVbiData(QVector<QVector<quint16 > > videoOutputBuffer, quint16 line);
    bool checkWhiteFlag(qint32 l, QVector<QVector<quint16> > videoOutputBuffer);
    void decodeVbiData(QVector<QVector<quint16> > &videoOutputBuffer);
};

// TODO: Clean this up...
//
//    TBC line 0 format (presumably shared for PAL/NTSC):
//
//    All data in uint32_t, using pairs of 16-bit words in the line.
//
//    words 0-5: decoded VBI data
//
//    word 6:
//        bit 0: CAV/CLV
//        bit 1: Frame begins on odd field (CAV only)
//        bit 2: CX enable/disable
//        bit 8: white flag on odd frame
//        bit 9: white flag on even frame
//        bits 16-31: chapter #
//
//    word 7:  Frame # (CAV *and* CLV)
//        CLV:  ((Hour * 3600) + (Minute * 60) + Second) * FPS) + frame #

#define FRAME_INFO_CLV		0x1
#define FRAME_INFO_CAV_EVEN	0x4
#define FRAME_INFO_CAV_ODD	0x8
#define FRAME_INFO_CX		0x10

#define FRAME_INFO_WHITE_ODD	0x100
#define FRAME_INFO_WHITE_EVEN	0x200

#endif // TBCNTSC_H
