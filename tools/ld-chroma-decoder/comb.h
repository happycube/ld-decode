/************************************************************************

    comb.h

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2018 Chad Page
    Copyright (C) 2018-2019 Simon Inns
    Copyright (C) 2020 Adam Sampson

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

#include "rgb.h"
#include "rgbframe.h"
#include "sourcefield.h"
#include "yiq.h"

class Comb
{
public:
    Comb();

    // Comb filter configuration parameters
    struct Configuration {
        double chromaGain = 1.0;
        bool colorlpf = false;
        bool colorlpf_hq = true;
        bool whitePoint75 = false;
        qint32 dimensions = 2;
        bool adaptive = true;
        bool showMap = false;

        double cNRLevel = 0.0;
        double yNRLevel = 1.0;

        qint32 getLookBehind() const;
        qint32 getLookAhead() const;
    };

    const Configuration &getConfiguration() const;
    void updateConfiguration(const LdDecodeMetaData::VideoParameters &videoParameters,
                             const Configuration &configuration);

    // Decode a sequence of fields into a sequence of interlaced frames
    void decodeFrames(const QVector<SourceField> &inputFields, qint32 startIndex, qint32 endIndex,
                      QVector<RGBFrame> &outputFrames);

    // Maximum frame size
    static constexpr qint32 MAX_WIDTH = 910;
    static constexpr qint32 MAX_HEIGHT = 525;

protected:

private:
    // Comb-filter configuration parameters
    bool configurationSet;
    Configuration configuration;
    LdDecodeMetaData::VideoParameters videoParameters;

    // An input frame in the process of being decoded
    class FrameBuffer {
    public:
        FrameBuffer(const LdDecodeMetaData::VideoParameters &videoParameters_, const Configuration &configuration_);

        void loadFields(const SourceField &firstField, const SourceField &secondField);

        void split1D();
        void split2D();
        void split3D(const FrameBuffer &previousFrame);

        void splitIQ();
        void filterIQ();
        void adjustY();

        void doCNR();
        void doYNR();

        RGBFrame yiqToRgbFrame();
        void overlayMap(RGBFrame &rgbOutputFrame);

    private:
        const LdDecodeMetaData::VideoParameters &videoParameters;
        const Configuration &configuration;

        // Calculated frame height
        qint32 frameHeight;

        // IRE scaling
        double irescale;

        // Baseband samples (interlaced to form a complete frame)
        SourceVideo::Data rawbuffer;

        // Chroma phase of the frame's two fields
        qint32 firstFieldPhaseID;
        qint32 secondFieldPhaseID;

        // 1D, 2D and 3D-filtered chroma samples
        struct {
            double pixel[MAX_HEIGHT][MAX_WIDTH];
        } clpbuffer[3];

        // Demodulated YIQ samples
        YIQ yiqBuffer[MAX_HEIGHT][MAX_WIDTH];

        // Motion detection result, from 0 (none) to 1 (lots)
        QVector<double> kValues;

        inline qint32 getFieldID(qint32 lineNumber) const;
        inline bool getLinePhase(qint32 lineNumber) const;
    };
};

#endif // COMB_H
