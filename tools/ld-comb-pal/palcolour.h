/************************************************************************

    palcombfilters.h

    ld-colourfilter - Analogue LaserDisc video colourisation
    Copyright (C) 2018 Simon Inns

    The PALcolour algorithm used in this class is:
    Copyright (C) 2018 William Andrew Steer
    http://techmind.org/vd/paldec.html
    https://github.com/techmindorg/PALcolour

    This file is part of ld-colourfilter.

    ld-colourfilter is free software: you can redistribute it and/or
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
    static const int MAX_WIDTH = 1135; // Simon: Maximum based on PAL width
    static const int MAX_HEIGHT = 625; // Simon: Maximum based on PAL height

private:
    // Configuration parameters
    LdDecodeMetaData::VideoParameters videoParameters;

    // Look up tables array and constant definitions
    double sine[MAX_WIDTH], cosine[MAX_WIDTH];    // formerly short int
    static const int32_t arraySize = 14; // 'a' is the array-size, corresponding to at least half the filter-width, and should be at least Fsampling(max supported by build)/colourfilterBandwidth(min supported by build)
    //  'a' must be greater than or equal to the bigger of 'ca' and 'ya' above
    double cfilt0[arraySize + 1];
    double cfilt1[arraySize + 1];
    double cfilt2[arraySize + 1];
    double cfilt3[arraySize + 1];
    double yfilt0[arraySize + 1];
    double yfilt2[arraySize + 1];

    double cdiv;
    double ydiv;
    double refAmpl;
    double normalise;
    QByteArray outputFrame;

    bool configurationSet;

    // Method to build the required look-up tables
    void buildLookUpTables(void);
};

#endif // PALCOLOUR_H
