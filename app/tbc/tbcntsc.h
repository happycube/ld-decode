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
    void setTol(double_t value);
    void setRot(double_t value);
    void setSkipFrames(qint32 value);
    void setMaximumFrames(qint32 value);

private:
    // Private configuration globals that have
    // matching 'set' functions to manipulate
    // the setting publicly (for command line
    // options)
    QString sourceVideoFileName;
    QString sourceAudioFileName;
    QString targetVideoFileName;

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

    // Other configuration which does not have a 'set' function
    // in the class to set or get the value
    bool c32mhz;
    double_t videoInputFrequencyInFsc;	// in FSC.  Must be an even number!
    qint32 ntsc_iplinei;

    // Two-dimensional (time-corrected) video frame buffers
    //
    // Frame buffers (505x844 for NTSC and 610x1052 for PAL (with FSC=4))
    // Previously these were dynamically assigned, but I've used constants
    // as it avoids the need for vectors (decision based on execution speed)
    quint16 frameBuffer[505][844];
    quint16 frameOriginal[505][844];
    double_t deltaFrame[505][844];
    double_t deltaFrameFilter[505][844];

    // Global filter declarations
    Filter *longSyncFilter;
    Filter *f_endsync;

    // To be sorted
    double_t inputMaximumIreLevel;
    double_t inputMinimumIreLevel;
    qint64 a_read;
    qint64 v_read;
    qint32 va_ratio;
    double_t outputFrequencyInFsc;

    // Globals for processAudio()
    double_t afreq;
    double_t prev_time;
    double_t nextAudioSample;
    size_t prev_loc;
    qint64 prev_index;
    qint64 prev_i;

    // Globals for processAudioSample()
    Filter *audioChannelOneFilter;
    Filter *audioChannelTwoFilter;
    qint32 audioOutputBufferPointer;

    // Globals to do with the line processing functions
    // handlebadline() and processline()
    double_t line;
    qint32 phase;
    bool first;
    qint32 frameno;

    qint64 firstloc;

    // Auto-ranging state
    double_t low;
    double_t high;

    // Private functions
    quint16 autoRange(QVector<quint16> videoBuffer);
    qint32 processVideoAndAudioBuffer(QVector<quint16> videoBuffer, qint32 videoBufferElementsToProcess,
                                      QVector<double_t> audioBuffer, bool processAudioData,
                                      bool *isVideoFrameBufferReadyForWrite);

    qint32 findSync(quint16 *videoBuffer, qint32 videoLength);
    qint32 findSync(quint16 *videoBuffer, qint32 videoLength, qint32 tgt);

    qint32 countSlevel(quint16 *videoBuffer, qint32 begin, qint32 end);

    qint32 findVsync(quint16 *videoBuffer, qint32 videoLength);
    qint32 findVsync(quint16 *videoBuffer, qint32 videoLength, qint32 offset);

    bool findHsyncs(quint16 *videoBuffer, qint32 videoLength, qint32 offset, double_t *rv);
    bool findHsyncs(quint16 *videoBuffer, qint32 videoLength, qint32 offset, double_t *rv, qint32 nlines);

    void correctDamagedHSyncs(double_t *hsyncs, bool *err);
    void processAudio(double_t frameBuffer, qint64 loc, double_t *audioBuffer);
    void processAudioSample(double_t channelOne, double_t channelTwo);

    inline double_t clamp(double_t value, double_t lowValue, double_t highValue);

    inline double_t in_to_ire(quint16 level);
    inline quint16 ire_to_in(double_t ire);
    inline quint16 ire_to_out(double_t ire);
    double_t out_to_ire(quint16 in);
    inline double_t peakdetect_quad(double_t *y);

    inline double_t cubicInterpolate(quint16 *y, double_t x);

    void scale(uint16_t *buf, double_t *outbuf, double_t start, double_t end, double_t outlen);
    void scale(uint16_t *buf, double_t *outbuf, double_t start, double_t end, double_t outlen, double_t offset);
    void scale(uint16_t *buf, double_t *outbuf, double_t start, double_t end, double_t outlen, double_t offset, qint32 from, qint32 to);

    bool inRange(double_t v, double_t l, double_t h);
    bool inRangeCF(double_t v, double_t l, double_t h);

    bool burstDetect2(double_t *line, qint32 freq, double_t _loc, double_t &plevel, double_t &pphase, bool &phaseflip);

    bool isPeak(double_t *p, qint32 i);

    quint32 readPhillipsCode(quint16 *line);
    inline double_t max(double_t a, double_t b);
    void despackle(void);
    bool checkWhiteFlag(qint32 l);
    void decodeVBI(void);
};

#endif // TBCNTSC_H
