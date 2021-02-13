/************************************************************************

    ycbcr.h

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2018 Chad Page
    Copyright (C) 2018-2019 Simon Inns
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

#ifndef YCBCR_H
#define YCBCR_H

#include <QCoreApplication>
#include <QDebug>

#include "yiq.h"

// ITU-R BT.601-7
static constexpr double ONE_MINUS_Kb (1 - 0.114);
static constexpr double ONE_MINUS_Kr (1 - 0.299);

// Poynton, "Digital Video and HDTV" first edition, Eq 28.1
// kB = sqrt(209556997.0 / 9614691.0) / 3.0
// kR = sqrt(221990474.0 / 288439473.0)
static constexpr double kB = 0.49211104112248356308804691718185;
static constexpr double kR = 0.877283221458919247158029475165;

static constexpr double SIN33 = 0.54463903501502708222408369208157;
static constexpr double COS33 = 0.83867056794542402963759094180455;

class YCbCr
{
public:
    // whiteIreLevel: 100 IRE 16-bit level
    // blackIreLevel: 0 or 7.5 IRE 16-bit level
    // whitePoint75: false = using 100% white point, true = 75%
    // chromaGain: gain applied to I/Q channels
    YCbCr(double whiteIreLevel, double blackIreLevel, bool whitePoint75, double chromaGain);

    void convertLine(const YIQ *begin, const YIQ *end, quint16 *outY, quint16 *outCb, quint16 *outCr);

private:
    double whiteIreLevel;
    double blackIreLevel;
    bool whitePoint75;
    double chromaGain;
};

#endif // YCBCR_H
