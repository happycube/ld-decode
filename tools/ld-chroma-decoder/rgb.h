/************************************************************************

    rgb.h

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2018 Chad Page
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

#ifndef RGB_H
#define RGB_H

#include <QCoreApplication>
#include <QDebug>

#include "yiq.h"

class RGB
{
public:
    // whiteIreLevel: 100 IRE 16-bit level
    // blackIreLevel: 0 or 7.5 IRE 16-bit level
    // whitePoint75: false = using 100% white point, true = 75%
    // chromaGain: gain applied to I/Q channels
    RGB(double whiteIreLevel, double blackIreLevel, bool whitePoint75, double chromaGain);

    void convertLine(const YIQ *begin, const YIQ *end, quint16 *out);

private:
    double whiteIreLevel;
    double blackIreLevel;
    bool whitePoint75;
    double chromaGain;
};

#endif // RGB_H
