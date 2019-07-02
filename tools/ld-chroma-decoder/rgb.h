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
    RGB(double whiteIreParam, double blackIreParam, bool whitePoint100Param, bool blackAndWhiteParam, double colourBurstMedianParam);

    void convertLine(const YIQ *begin, const YIQ *end, quint16 *out);

private:
    double blackIreLevel;
    double whiteIreLevel;
    bool whitePoint75;
    bool blackAndWhite;
    double colourBurstMedian;
};

// Clamp a value to within a fixed range.
// (Equivalent to C++17's std::clamp.)
template <typename T>
static inline const T& clamp(const T& v, const T& low, const T& high)
{
    if (v < low) return low;
    else if (v > high) return high;
    else return v;
}

#endif // RGB_H
