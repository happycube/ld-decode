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
        bool blackAndWhite = false;
        ChromaFilterMode chromaFilter = palColourFilter;
        TransformPal::TransformMode transformMode = TransformPal::thresholdMode;
        double transformThreshold = 0.4;

        // Interlaced line 44 is PAL line 23 (the first active half-line)
        qint32 firstActiveLine = 44;
        // Interlaced line 619 is PAL line 623 (the last active half-line)
        qint32 lastActiveLine = 620;

        qint32 getLookBehind() const;
        qint32 getLookAhead() const;
    };

    const Configuration &getConfiguration() const;
    void updateConfiguration(const LdDecodeMetaData::VideoParameters &videoParameters,
                             const Configuration &configuration);

    // Decode two fields to produce an interlaced frame.
    QByteArray decodeFrame(const SourceField &firstField, const SourceField &secondField);

    // Decode a sequence of fields into a sequence of interlaced frames
    void decodeFrames(const QVector<SourceField> &inputFields, qint32 startIndex, qint32 endIndex,
                      QVector<QByteArray> &outputFrames);

    // Maximum frame size, based on PAL
    static const qint32 MAX_WIDTH = 1135;
    static const qint32 MAX_HEIGHT = 625;

private:
    // Decode one field into outputFrame.
    void decodeField(const SourceField &inputField, const double *chromaData, double chromaGain, QByteArray &outputFrame);

    // Information about a line we're decoding.
    struct LineInfo {
        explicit LineInfo(qint32 number);

        qint32 number;
        double bp, bq;
        double Vsw;
        double burstNorm;
    };

    // Detect the colourburst on a line.
    // Stores the burst details into line.
    void detectBurst(LineInfo &line, const quint16 *inputData);

    // Decode one line into outputFrame.
    // chromaData (templated, so it can be any numeric type) is the input to
    // the chroma demodulator; this may be the composite signal from
    // inputField, or it may be pre-filtered down to chroma.
    template <typename ChromaSample, bool useTransformFilter>
    void decodeLine(const SourceField &inputField, const ChromaSample *chromaData, const LineInfo &line, double chromaGain,
                    QByteArray &outputFrame);

    // Configuration parameters
    bool configurationSet;
    Configuration configuration;
    LdDecodeMetaData::VideoParameters videoParameters;

    // Transform PAL filter
    QScopedPointer<TransformPal> transformPal;

    // The subcarrier reference signal
    double sine[MAX_WIDTH], cosine[MAX_WIDTH];
    double refAmpl;
    double refNorm;

    // Coefficients for the three 2D chroma low-pass filters. There are
    // separate filters for U and V, but only the signs differ, so they can
    // share a set of coefficients.
    //
    // The filters are horizontally and vertically symmetrical, so each 2D
    // array represents one quarter of a filter. The zeroth horizontal element
    // is included in the sum twice, so the coefficient is halved to
    // compensate. Each filter is (2 * FILTER_SIZE) + 1 elements wide.
    static const qint32 FILTER_SIZE = 7;
    double cfilt[FILTER_SIZE + 1][4];
    double yfilt[FILTER_SIZE + 1][2];

    // Method to build the required look-up tables
    void buildLookUpTables();
};

#endif // PALCOLOUR_H
