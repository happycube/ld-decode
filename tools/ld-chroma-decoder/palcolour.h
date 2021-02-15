/************************************************************************

    palcolour.h

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2018-2019 Simon Inns
    Copyright (C) 2019 Adam Sampson

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

#ifndef PALCOLOUR_H
#define PALCOLOUR_H

#include <QDebug>
#include <QObject>
#include <QScopedPointer>
#include <QVector>
#include <QtMath>

#include "lddecodemetadata.h"

#include "decoder.h"
#include "outputframe.h"
#include "sourcefield.h"
#include "transformpal.h"

class PalColour : public QObject
{
    Q_OBJECT

public:
    explicit PalColour(QObject *parent = nullptr);

    // Specify which filter to use to separate luma and chroma information.
    enum ChromaFilterMode {
        // PALColour's 2D FIR filter
        palColourFilter = 0,
        // 2D Transform PAL frequency-domain filter
        transform2DFilter,
        // 3D Transform PAL frequency-domain filter
        transform3DFilter
    };

    struct Configuration {
        double chromaGain = 1.0;
        double yNRLevel = 0.5;
        bool simplePAL = false;
        ChromaFilterMode chromaFilter = palColourFilter;
        TransformPal::TransformMode transformMode = TransformPal::thresholdMode;
        double transformThreshold = 0.4;
        QVector<double> transformThresholds;
        Decoder::PixelFormat pixelFormat = Decoder::PixelFormat::RGB48;
        bool outputYCbCr = false;
        bool showFFTs = false;
        qint32 showPositionX = 200;
        qint32 showPositionY = 200;

        qint32 getThresholdsSize() const;
        qint32 getLookBehind() const;
        qint32 getLookAhead() const;
    };

    const Configuration &getConfiguration() const;
    void updateConfiguration(const LdDecodeMetaData::VideoParameters &videoParameters,
                             const Configuration &configuration);

    // Decode a sequence of fields into a sequence of interlaced frames
    void decodeFrames(const QVector<SourceField> &inputFields, qint32 startIndex, qint32 endIndex,
                      QVector<OutputFrame> &outputFrames);

    // Maximum frame size, based on PAL
    static constexpr qint32 MAX_WIDTH = 1135;

private:
    // Information about a line we're decoding.
    struct LineInfo {
        explicit LineInfo(qint32 number);

        qint32 number;
        double bp, bq;
        double Vsw;
    };

    void buildLookUpTables();
    void decodeField(const SourceField &inputField, const double *chromaData, double chromaGain, OutputFrame &outputFrame);
    void detectBurst(LineInfo &line, const quint16 *inputData);
    void doYNR(double *inY);
    template <typename ChromaSample, bool PREFILTERED_CHROMA>
    void decodeLine(const SourceField &inputField, const ChromaSample *chromaData, const LineInfo &line, double chromaGain,
                    OutputFrame &outputFrame);

    // Configuration parameters
    bool configurationSet;
    Configuration configuration;
    LdDecodeMetaData::VideoParameters videoParameters;

    // Transform PAL filter
    QScopedPointer<TransformPal> transformPal;

    // The subcarrier reference signal
    double sine[MAX_WIDTH], cosine[MAX_WIDTH];

    // extract luma first so it can be run through NR
    double extractedY[MAX_WIDTH];

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
};

#endif // PALCOLOUR_H
