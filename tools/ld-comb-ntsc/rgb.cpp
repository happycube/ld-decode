/************************************************************************

    rgb.cpp

    ld-comb-ntsc - NTSC colourisation filter for ld-decode
    Copyright (C) 2018 Chad Page
    Copyright (C) 2018 Simon Inns

    This file is part of ld-decode-tools.

    ld-comb-ntsc is free software: you can redistribute it and/or
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

#include "rgb.h"

RGB::RGB(double whiteIreParam, double blackIreParam, bool whitePoint100Param)
{
    blackIreLevel = blackIreParam; // 0 or 7.5 IRE 16-bit level
    whiteIreLevel = whiteIreParam; // 100 IRE 16-bit level
    whitePoint100 = whitePoint100Param; // true = using 100% white point, false = 75%
}

void RGB::conv(YIQ _y, qreal colourBurstMedian)
{
    double y = _y.y;
    double i = +(_y.i);
    double q = +(_y.q);

    // Scale the Y to 0-65535 where 0 = blackIreLevel and 65535 = whiteIreLevel
    y = scaleY(_y.y);

    // Scale the I & Q components according to the colourburstMedian
    //
    // Note: The colour burst median is the amplitude of the colour burst (divided
    // by two) measured by ld-decode.  Since the burst amplitude should be 40 IRE
    // this can be used to compensate the colour saturation loss due to MTF
    qreal saturationCompensation = (20.0 / colourBurstMedian) * 2;

    i *= saturationCompensation;
    q *= saturationCompensation;

    // YIQ to RGB colour-space conversion (from page 18
    // of Video Demystified, 5th edition)
    //
    // For RGB 0-255: Y 0-255. I 0- +-152. Q 0- +-134 :
    r = y + (0.956 * i) + (0.621 * q);
    g = y - (0.272 * i) - (0.647 * q);
    b = y - (1.107 * i) + (1.704 * q);

    r = clamp(r, 0, 65535);
    g = clamp(g, 0, 65535);
    b = clamp(b, 0, 65535);
}

// Private methods ----------------------------------------------------------------------------------------------------

double RGB::clamp(double v, double low, double high)
{
        if (v < low) return low;
        else if (v > high) return high;
        else return v;
}

double RGB::scaleY(double level)
{
    // Scale Y to according to the black to white interval
    // (i.e. make the black level 0 and the white level 65535)
    qreal result = ((level - blackIreLevel) / (blackIreLevel - whiteIreLevel)) * -65535;

    // NTSC uses a 75% white point; so here we scale the result by
    // 25% (making 100 IRE 25% over the maximum allowed white point)
    if (!whitePoint100) result = (result/100) * 125;

    // Now we clip the result back to the 16-bit range
    if (result < 0) result = 0;
    if (result > 65535) result = 65535;

    return result;
}

