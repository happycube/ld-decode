/************************************************************************

    tbcpal.h

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

#ifndef TBCPAL_H
#define TBCPAL_H

#include <QCoreApplication>
#include <QDebug>
#include <QFile>
#include <QDataStream>
#include <QVector>

// Needed for reading and writing to stdin/stdout
#include <stdio.h>

#include "filter.h"

class TbcPal
{
public:
    TbcPal(quint16 fscSetting);

    // Execute the time-based correction
    qint32 execute(void);

    // TBC PAL parameter settings
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

    bool f_diff;
    qint32 writeOnField;
    bool f_flip;
    bool audio_only;
    bool performAutoRanging;
    bool freeze_frame;
    bool despackle;
    bool seven_five;
    bool f_highburst;
    double_t f_tol;
    double_t p_rotdetect;

    // Other configuration which does not have a 'set' function
    // in the class to set or get the value
    bool c32mhz;
    double_t videoInputFrequencyInFsc;
    qint32 pal_iplinei;
    double_t pal_ipline;
    double_t pixels_per_usec;

    // Constants (sort of...)
    double_t pal_opline;
    double_t pal_blanklen;
    double_t scale_linelen;
    double_t pal_ihsynctoline;
    double_t iscale15_len;
    double_t pal_hsynctoline;
    double_t outputFrequencyInFsc;
    double_t burstFrequencyMhz;
    double_t scale15_len;
    double_t scale4fsc_len;
    double_t hfreq;
    qint64 fr_count;
    qint64 au_count;
    double_t inputMaximumIreLevel;
    double_t inputMinimumIreLevel;
    qint64 a_read;  // Used by audio processing
    qint64 v_read;  // Used by audio processing
    qint32 va_ratio;

    // Two-dimensional (time-corrected) video frame buffer
    quint16 frameBuffer[610][1052];

    // Global filter declarations
    Filter *longSyncFilter; // Used by autoRange()
    Filter *f_syncid; // Used by processAudioAndVideo and applyVideoLineFilters
    qint32 syncid_offset; // Used by processAudioAndVideo and applyVideoLineFilters

    // Globals for processAudio() and processAudioSample()
    struct processAudioStateStruct {
        double_t afreq;
        double_t prev_time;
        double_t next_audsample;
        size_t prev_loc;
        qint64 prev_index;
        qint64 prev_i;

        double_t _audioChannelOne;
        double_t _audioChannelTwo;
        Filter *f_fml;
        Filter *f_fmr;
        quint16 audioOutputBuffer[512];
        qint32 audioOutputBufferPointer;
    } processAudioState;

    // Structure to store state for line processing functions
    // handleBadLine() and processline()
    struct lineProcessingStateStruct {
        double_t tline;
        double_t line;
        qint32 phase;
        bool first;
        double_t prev_linelen;
        double_t prev_offset_begin;
        double_t prev_offset_end;
        double_t prev_begin;
        double_t prev_end;
        double_t prev_beginlen;
        double_t prev_endlen;
        double_t prev_lvl_adjust;
        qint32 frameno; // Used to pass back the frame number last processed by processLine()
    } lineProcessingState;

    // Structure for storing video line details
    struct LineStruct {
        double_t center;
        double_t peak;
        double_t beginSync;
        double_t endSync;
        qint32 lineNumber;
        bool isBad;
    };

    // Private functions
    quint16 autoRange(QVector<quint16> videoBuffer);
    qint32 processVideoAndAudioBuffer(QVector<quint16> videoBuffer, qint32 len,
                                      QVector<double_t> audioBuffer, bool processAudioData, quint16 videoSyncLevel,
                                      bool *isVideoFrameBufferReadyForWrite);
    void applyVideoLineFilters(quint16 *videoBuffer, quint16 *deempFilterBuffer, double_t *psync,
                               qint32 videoBufferElementsToProcess, quint16 videoSyncLevel);
    double_t processVideoLineIntoFrame(quint16 *videoBuffer, QVector<LineStruct> *lineDetails, qint32 lineToProcess,
                                       bool isCalledByRecursion);
    void handleBadLine(QVector<LineStruct> *lineDetails, qint32 lineToProcess);

    void processAudio(double_t frameBuffer, qint64 loc, double_t *audioBuffer);
    void processAudioSample(double_t channelOne, double_t channelTwo);

    inline double_t clamp(double_t value, double_t lowValue, double_t highValue);

    inline double_t in_to_ire(quint16 level);
    inline quint16 ire_to_in(double_t ire);
    inline quint16 ire_to_out(double_t ire);
    inline double_t peakdetect_quad(double_t *y);

    inline double_t cubicInterpolate(quint16 *y, double_t x);
    inline void scale(quint16 *buf, double_t *outbuf, double_t start, double_t end, double_t outlen);

    inline bool inRange(double_t v, double_t l, double_t h);
    inline bool inRangeF(double_t v, double_t l, double_t h);

    bool pilotDetect(double_t *line, double_t loc, double_t &plevel, double_t &pphase);
    bool burstDetect(double_t *line, qint32 start, qint32 end, double_t &plevel, double_t &pphase);

    inline qint32 get_oline(double_t line);
    inline bool isPeak(double_t *p, qint32 i);
};

#endif // TBCPAL_H
