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
#include <cassert>

#include "lddecodemetadata.h"

class PalColour : public QObject
{
    Q_OBJECT

public:
    explicit PalColour(QObject *parent = nullptr);
    void updateConfiguration(LdDecodeMetaData::VideoParameters videoParameters, qint32 firstActiveLine, qint32 lastActiveLine);

    // Decode two fields to produce an interlaced frame.
    // contrast and saturation are user-adjustable controls; 100 is nominal.
    QByteArray performDecode(QByteArray topFieldData, QByteArray bottomFieldData, qint32 contrast, qint32 saturation);

    // Maximum frame size, based on PAL
    static const qint32 MAX_WIDTH = 1135;
    static const qint32 MAX_HEIGHT = 625;

private:
    // Information about a field we're decoding.
    struct FieldInfo {
        explicit FieldInfo(qint32 number, qint32 contrast, qint32 saturation, qint32 firstActiveLine, qint32 lastActiveLine);

        // number is 0 for the top field, 1 for the bottom field.
        qint32 number;
        qint32 contrast;
        qint32 saturation;
        // firstLine/lastLine are the range of active lines within the field.
        qint32 firstLine;
        qint32 lastLine;
    };

    // Decode one field into outputFrame.
    void decodeField(const FieldInfo &field, const QByteArray &fieldData);

    // Decode one line into outputFrame.
    void decodeLine(const FieldInfo &field, qint32 fieldLine, const quint16 *inputData);

    // Configuration parameters
    bool configurationSet;
    LdDecodeMetaData::VideoParameters videoParameters;
    qint32 firstActiveLine;
    qint32 lastActiveLine;

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

    // The output frame
    QByteArray outputFrame;

    // Method to build the required look-up tables
    void buildLookUpTables();
};

#endif // PALCOLOUR_H
