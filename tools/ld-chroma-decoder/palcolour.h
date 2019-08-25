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

#include <QObject>
#include <QtMath>
#include <QDebug>
#include <QVector>

#include "lddecodemetadata.h"

#include "sourcefield.h"
#include "transformpal.h"

class PalColour : public QObject
{
    Q_OBJECT

public:
    explicit PalColour(QObject *parent = nullptr);

    struct Configuration {
        bool blackAndWhite = false;
        bool useTransformFilter = false;
        TransformPal::TransformMode transformMode = TransformPal::thresholdMode;
        double transformThreshold = 0.4;

        // Interlaced line 44 is PAL line 23 (the first active half-line)
        qint32 firstActiveLine = 44;
        // Interlaced line 619 is PAL line 623 (the last active half-line)
        qint32 lastActiveLine = 620;
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
    // Information about a field we're decoding.
    struct FieldInfo {
        explicit FieldInfo(qint32 offset, const Configuration &configuration);

        // Vertical pixels to offset this field within the interlaced frame --
        // i.e. 0 for the top field, 1 for the bottom field.
        qint32 offset;

        // firstLine/lastLine are the range of active lines within the field.
        qint32 firstLine;
        qint32 lastLine;
    };

    // Decode one field into outputFrame.
    void decodeField(const QByteArray &fieldData, const double *chromaData, const FieldInfo &fieldInfo, double chromaGain,
                     QByteArray &outputFrame);

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
    // inputData (templated, so it can be any numeric type) is the input to the
    // filter; this may be the composite signal, or it may be pre-filtered down
    // to chroma.
    // compData is the composite signal, used for reconstructing Y at the end.
    template <typename InputSample, bool useTransformFilter>
    void decodeLine(const FieldInfo &fieldInfo, const LineInfo &line, double chromaGain,
                    const InputSample *inputData, const quint16 *compData, QByteArray &outputFrame);

    // Configuration parameters
    bool configurationSet;
    Configuration configuration;
    LdDecodeMetaData::VideoParameters videoParameters;

    // Transform PAL filter
    TransformPal transformPal;

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
