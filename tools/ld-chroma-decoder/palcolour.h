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

#include "lddecodemetadata.h"

class PalColour : public QObject
{
    Q_OBJECT

public:
    explicit PalColour(QObject *parent = nullptr);
    void updateConfiguration(LdDecodeMetaData::VideoParameters videoParametersParam);

    // Method to perform the colour decoding
    QByteArray performDecode(QByteArray topFieldData, QByteArray bottomFieldData, qint32 brightness, qint32 saturation, bool blackAndWhite);

    // Replacements for #DEFINE values
    static const qint32 MAX_WIDTH = 1135; // Simon: Maximum based on PAL width
    static const qint32 MAX_HEIGHT = 625; // Simon: Maximum based on PAL height

private:
    // Configuration parameters
    LdDecodeMetaData::VideoParameters videoParameters;

    // Look up tables array and constant definitions
    double sine[MAX_WIDTH], cosine[MAX_WIDTH];    // formerly short int
    static const qint32 arraySize = 14; // 'a' is the array-size, corresponding to at least half the filter-width, and should be at least Fsampling(max supported by build)/colourfilterBandwidth(min supported by build)
    //  'a' must be greater than or equal to the bigger of 'ca' and 'ya' above
    double cfilt[arraySize + 1][4];
    double yfilt[arraySize + 1][2];

    double refAmpl;
    double normalise;
    QByteArray outputFrame;

    bool configurationSet;

    // Method to build the required look-up tables
    void buildLookUpTables();
};

#endif // PALCOLOUR_H
