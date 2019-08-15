/************************************************************************

    comb.h

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2018 Chad Page
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-chroma-decoder is free software: you can redistribute it and/or
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

#include "lddecodemetadata.h"

#include "yiq.h"
#include "rgb.h"
#include "opticalflow.h"
#include "yiqbuffer.h"

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
        bool blackAndWhite = false;
        bool colorlpf = true;
        bool colorlpf_hq = true;
        bool whitePoint100 = false;
        bool use3D = false;
        bool showOpticalFlowMap = false;

        // Interlaced line 40 is NTSC line 21 (the closed-caption line before the first active line)
        qint32 firstActiveLine = 40;

        qreal cNRLevel = 0.0;
        qreal yNRLevel = 1.0;
    };

    const Configuration &getConfiguration() const;
    void updateConfiguration(const LdDecodeMetaData::VideoParameters &videoParameters,
                             const Configuration &configuration);

    QByteArray process(QByteArray topFieldInputBuffer, QByteArray bottomFieldInputBuffer, qreal burstMedianIre, qint32 topFieldPhaseID, qint32 bottomFieldPhaseID);

protected:

private:
    // Comb-filter configuration parameters
    bool configurationSet;
    Configuration configuration;
    LdDecodeMetaData::VideoParameters videoParameters;

    // IRE scaling
    qreal irescale;

    // Calculated frame height
    qint32 frameHeight;

    // Input frame buffer definitions
    struct PixelLine {
        qreal pixel[526][911]; // 526 is the maximum allowed field lines, 911 is the maximum field width
    };

    struct FrameBuffer {
        QByteArray rawbuffer;

        QVector<PixelLine> clpbuffer; // Unfiltered chroma for the current phase (can be I or Q)
        QVector<qreal> kValues;
        YiqBuffer yiqBuffer; // YIQ values for the frame

        qreal burstLevel; // The median colour burst amplitude for the frame
        qint32 firstFieldPhaseID; // The phase of the frame's first field
        qint32 secondFieldPhaseID; // The phase of the frame's second field
    };

    // Input and output file handles
    QFile *inputFileHandle;
    QFile *outputFileHandle;

    // Optical flow processor
    OpticalFlow opticalFlow;

    // Previous and next frame for 3D processing
    FrameBuffer previousFrameBuffer;

    inline qint32 GetFieldID(FrameBuffer *frameBuffer, qint32 lineNumber);
    inline bool GetLinePhase(FrameBuffer *frameBuffer, qint32 lineNumber);

    void split1D(FrameBuffer *frameBuffer);
    void split2D(FrameBuffer *frameBuffer);
    void split3D(FrameBuffer *currentFrame, FrameBuffer *previousFrame);

    void filterIQ(YiqBuffer &yiqBuffer);
    void splitIQ(FrameBuffer *frameBuffer);

    void doCNR(YiqBuffer &yiqBuffer);
    void doYNR(YiqBuffer &yiqBuffer);

    QByteArray yiqToRgbFrame(const YiqBuffer &yiqBuffer, qreal burstLevel);
    void overlayOpticalFlowMap(const FrameBuffer &frameBuffer, QByteArray &rgbOutputFrame);
    void adjustY(FrameBuffer *frameBuffer, YiqBuffer &yiqBuffer);
};

#endif // COMB_H
