/************************************************************************

    comb.h

    ld-comb-ntsc - NTSC colourisation filter for ld-decode
    Copyright (C) 2018 Chad Page
    Copyright (C) 2018 Simon Inns

    This file is part of ld-decode-tools.

    ld-comb-ntsc is free software: you can redistribute it and/or
    modify it under the terms of the GNU General Public License as
    published by the Free Software Foundation, either version 3 of the
    License, or (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

************************************************************************/

#ifndef COMB_H
#define COMB_H

#include <QCoreApplication>
#include <QDebug>
#include <QFile>
#include <QtMath>

#include "filter.h"
#include "yiq.h"
#include "rgb.h"

// Fix required for Mac OS compilation - environment doesn't seem to set up
// the expected definitions properly
#ifndef M_PIl
#define M_PIl 0xc.90fdaa22168c235p-2L
#endif

class Comb
{
public:
    Comb();

    // Comb filter configuration parameters
    struct Configuration {
        bool blackAndWhite;
        bool colorlpf;
        bool colorlpf_hq;
        bool whitePoint100;

        qint32 fieldWidth;
        qint32 fieldHeight;

        qint32 activeVideoStart;
        qint32 activeVideoEnd;

        qint32 firstVisibleFrameLine;

        qint32 blackIre;
        qint32 whiteIre;
    };

    Configuration getConfiguration(void);
    void setConfiguration(Configuration configurationParam);
    QByteArray process(QByteArray topFieldInputBuffer, QByteArray bottomFieldInputBuffer, qreal burstMedianIre, qint32 topFieldPhaseID, qint32 bottomFieldPhaseID);

protected:

private:
    // Maximum supported input video frame size
    static const qint32 max_x = 910;
    static const qint32 max_y = 525;

    // Comb-filter configuration parameters
    Configuration configuration;

    // Some form of IRE scaling, no idea what the magic number is though
    qreal irescale;

    // Input frame buffer definitions
    struct yiqLine_t {
        YIQ pixel[max_x]; // One line of YIQ data
    };

    struct frame_t {
        QByteArray rawbuffer;

        qreal clpbuffer[3][max_y][max_x];
        qreal combk[3][max_y][max_x];

        QVector<yiqLine_t> yiqBuffer;

        qreal burstLevel;
        qint32 firstFieldPhaseID;
        qint32 secondFieldPhaseID;
    };

    // Input and output file handles
    QFile *inputFileHandle;
    QFile *outputFileHandle;

    void postConfigurationTasks(void);

    void filterIQ(QVector<yiqLine_t> &yiqBuffer);
    void split1D(frame_t *frameBuffer);
    void split2D(frame_t *frameBuffer);
    void splitIQ(frame_t *frameBuffer);
    void doCNR(QVector<yiqLine_t> &yiqBuffer);
    void doYNR(QVector<yiqLine_t> &yiqBuffer);
    QByteArray yiqToRgbFrame(QVector<yiqLine_t> yiqBuffer, qreal burstLevel);
    void adjustY(QVector<yiqLine_t> &yiqBuffer, qint32 firstFieldPhaseID, qint32 secondFieldPhaseID);

    qreal clamp(qreal v, qreal low, qreal high);
    qreal atan2deg(qreal y, qreal x);
    qreal ctor(qreal r, qreal i);
};

#endif // COMB_H
