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

// OpenCV2 used by OpticalFlow3D method
#include <opencv2/core/core.hpp>
#include <opencv2/video/tracking.hpp>

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
        bool adaptive2d;
        bool colorlpf;
        bool colorlpf_hq;
        bool opticalflow;
        qint32 filterDepth;

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

    // Processed frame counter
    qint32 frameCounter;

    // Some local configuration to do with 3D/2D processing...
    qreal p_3dcore;
    qreal p_3drange;
    qreal p_2drange;

    // Some form of IRE scaling, no idea what the magic number is though
    qreal irescale;

    // Tunables (more unknown local configuration parameters)
    qreal nr_c; // Used by doCNR method
    qreal nr_y; // Used by doYNR method

    // Internal globals
    qreal aburstlev; // average color burst (used by yiqToRgbFrame method to track average between calls)
    qint32 cline = -1; // used by yiqToRgbFrame method

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

    QVector<frame_t> frameBuffer;

    // Filter definitions for YNR and CNR noise reduction
    Filter *f_hpy, *f_hpi, *f_hpq;

    // Input and output file handles
    QFile *inputFileHandle;
    QFile *outputFileHandle;

    // Globals used by the opticalFlow3D method
    cv::Mat prev[2];
    cv::Mat flow[2];

    void postConfigurationTasks(void);

    void filterIQ(QVector<yiqLine_t> &yiqBuffer);
    void split1D(qint32 currentFrameBuffer);
    void split2D(qint32 currentFrameBuffer);
    void split3D(qint32 currentFrameBuffer, bool opt_flow = false);
    void splitIQ(qint32 currentFrameBuffer);
    void doCNR(QVector<yiqLine_t> &yiqBuffer, qreal min = -1.0);
    void doYNR(QVector<yiqLine_t> &yiqBuffer, qreal min = -1.0);
    QByteArray yiqToRgbFrame(qint32 currentFrameBuffer, QVector<yiqLine_t> yiqBuffer);
    void opticalFlow3D(QVector<yiqLine_t> yiqBuffer, qint32 frameCounter);
    void adjustY(qint32 currentFrameBuffer, QVector<yiqLine_t> &yiqBuffer);

    qreal clamp(qreal v, qreal low, qreal high);
    qreal atan2deg(qreal y, qreal x);
    qreal ctor(qreal r, qreal i);
};

#endif // COMB_H
