/************************************************************************

    palcolour.h

    ld-chroma-decoder - Colourisation filter for ld-decode
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

    // Method to perform the colour decoding
    QByteArray performDecode(QByteArray topFieldData, QByteArray bottomFieldData, qint32 contrast, qint32 saturation);

    // Maximum frame size, based on PAL
    static const qint32 MAX_WIDTH = 1135;
    static const qint32 MAX_HEIGHT = 625;

private:
    // Configuration parameters
    LdDecodeMetaData::VideoParameters videoParameters;
    qint32 firstActiveLine;
    qint32 lastActiveLine;

    // Look up tables array and constant definitions
    double sine[MAX_WIDTH], cosine[MAX_WIDTH];
    // cfilt and yfilt are the coefficients for the chroma and luma 2D FIR filters.
    // The filters are horizontally and vertically symmetrical (with signs
    // adjusted later to deal with phase differences between lines), so each
    // 2D array represents one quarter of a filter. The zeroth horizontal
    // element is included in the sum twice, so the coefficient is halved to
    // compensate. Each filter is (2 * FILTER_SIZE) + 1 elements wide.
    static const qint32 FILTER_SIZE = 7;
    double cfilt[FILTER_SIZE + 1][4];
    double yfilt[FILTER_SIZE + 1][2];

    double refAmpl;
    double refNorm;
    QByteArray outputFrame;

    bool configurationSet;

    // Method to build the required look-up tables
    void buildLookUpTables();
};

#endif // PALCOLOUR_H
