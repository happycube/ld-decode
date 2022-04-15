/************************************************************************

    comb.h

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2018 Chad Page
    Copyright (C) 2018-2019 Simon Inns
    Copyright (C) 2020-2021 Adam Sampson
    Copyright (C) 2021 Phillip Blucas

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

#include "componentframe.h"
#include "decoder.h"
#include "sourcefield.h"
#include "transformntsc3d.h"

class Comb
{
public:
    Comb();

    // Specify which filter to use to separate luma and chroma information.
    enum ChromaFilterMode {
        // "dimensions" options of Comb
        ntsc1DFilter = 1,
        ntsc2DCombFilter,
        ntsc3DCombFilter,
        // frequency-domain filter
        transform3DFilter
    };

    // Comb filter configuration parameters
    struct Configuration {
        double chromaGain = 1.0;
        double chromaPhase = 0.0;
        bool colorlpf = false;
        bool colorlpf_hq = true;
        bool whitePoint75 = false;
      //qint32 dimensions;
        bool simplePAL = false;
        ChromaFilterMode chromaFilter = ntsc2DCombFilter;
        TransformPal::TransformMode transformMode = TransformPal::thresholdMode;
        double transformThreshold = 0.4;
        QVector<double> transformThresholds;
        bool showFFTs = false;
        qint32 showPositionX = 200;
        qint32 showPositionY = 200;
        bool adaptive = true;
        bool showMap = false;
        bool phaseCompensation = false;

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
                      QVector<ComponentFrame> &componentFrames);

    // Maximum frame size
    static constexpr qint32 MAX_WIDTH = 910;
    static constexpr qint32 MAX_HEIGHT = 525;

protected:

private:
    // Comb-filter configuration parameters
    bool configurationSet;
    Configuration configuration;
    LdDecodeMetaData::VideoParameters videoParameters;

    // Transform NTSC filter
    QScopedPointer<TransformNtsc3D> transformNtsc;
    // used for Transform NTSC
    // Information about a line we're decoding.
    struct LineInfo {
        explicit LineInfo(qint32 number);

        qint32 number;
        // detectBurst computes bp, bq = cos(t), sin(t), where t is the burst phase.
        // They're used to build a rotation matrix for the chroma signals in decodeLine.
        double bp, bq;
        double Vsw;
    };
    void detectBurst(LineInfo &line, const quint16 *inputData);
    void decodeField(const SourceField &inputField, const double *chromaData, ComponentFrame &componentFrame);
    void decodeLine(const SourceField &inputField, const double *chromaData, const LineInfo &line,
                    ComponentFrame &componentFrame);
    void doYNR(double *Yline);
    // Coefficients for the three 2D chroma low-pass filters. There are
    // separate filters for U and V, but only the signs differ, so they can
    // share a set of coefficients.
    //
    // The filters are horizontally and vertically symmetrical, so each 2D
    // array represents one quarter of a filter. The zeroth horizontal element
    // is included in the sum twice, so the coefficient is halved to
    // compensate. Each filter is (2 * FILTER_SIZE) + 1 elements wide.
    static constexpr qint32 FILTER_SIZE = 7;
    double cfilt[FILTER_SIZE + 1][4];
    double yfilt[FILTER_SIZE + 1][2];

    // An input frame in the process of being decoded
    class FrameBuffer {
    public:
        FrameBuffer(const LdDecodeMetaData::VideoParameters &videoParameters_, const Configuration &configuration_);

        void loadFields(const SourceField &firstField, const SourceField &secondField);

        void split1D();
        void split2D();
        void split3D(const FrameBuffer &previousFrame, const FrameBuffer &nextFrame);

        void setComponentFrame(ComponentFrame &_componentFrame) {
            componentFrame = &_componentFrame;
        }

        void splitIQ();
        void splitIQlocked();
        void filterIQ();
        void filterIQFull();
        void adjustY();
        void doCNR();
        void doYNR();
        void transformIQ(double chromaGain, double chromaPhase);

        void overlayMap(const FrameBuffer &previousFrame, const FrameBuffer &nextFrame);

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
        struct Sample {
            double pixel[MAX_HEIGHT][MAX_WIDTH];
        } clpbuffer[3];

        // Result of evaluating a 3D candidate
        struct Candidate {
            double penalty;
            double sample;
        };

        // The component frame for output (if there is one)
        ComponentFrame *componentFrame;

        inline qint32 getFieldID(qint32 lineNumber) const;
        inline bool getLinePhase(qint32 lineNumber) const;
        void getBestCandidate(qint32 lineNumber, qint32 h,
                              const FrameBuffer &previousFrame, const FrameBuffer &nextFrame,
                              qint32 &bestIndex, double &bestSample) const;
        Candidate getCandidate(qint32 refLineNumber, qint32 refH,
                               const FrameBuffer &frameBuffer, qint32 lineNumber, qint32 h,
                               double adjustPenalty) const;
    };
};

#endif // COMB_H
