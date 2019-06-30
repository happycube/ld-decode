/************************************************************************

    rgb.cpp

    ld-comb-ntsc - NTSC colourisation filter for ld-decode
    Copyright (C) 2018 Chad Page
    Copyright (C) 2018-2019 Simon Inns

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

RGB::RGB(double whiteIreParam, double blackIreParam, bool whitePoint100Param, bool blackAndWhiteParam, double colourBurstMedianParam)
{
    blackIreLevel = blackIreParam; // 0 or 7.5 IRE 16-bit level
    whiteIreLevel = whiteIreParam; // 100 IRE 16-bit level
    whitePoint75 = whitePoint100Param; // false = using 100% white point, true = 75%
    blackAndWhite = blackAndWhiteParam; // true = output in black and white only
    colourBurstMedian = colourBurstMedianParam; // 40 IRE burst amplitude measured by ld-decode
}

void RGB::convertLine(const YIQ *begin, const YIQ *end, quint16 *out)
{
    // Factors to scale Y according to the black to white interval
    // (i.e. make the black level 0 and the white level 65535)
    qreal yBlackLevel = blackIreLevel;
    qreal yScale = (1.0 / (blackIreLevel - whiteIreLevel)) * -65535;

    if (whitePoint75) {
        // NTSC uses a 75% white point; so here we scale the result by
        // 25% (making 100 IRE 25% over the maximum allowed white point)
        yScale *= 125.0 / 100.0;
    }

    // Compute I & Q scaling factor according to the colourBurstMedian
    //
    // Note: The colour burst median is the amplitude of the colour burst (divided
    // by two) measured by ld-decode.  Since the burst amplitude should be 40 IRE
    // this can be used to compensate the colour saturation loss due to MTF
    //
    // Note: this calculations should be 20 / colourBurstMedian (meaning that the
    // 'normal' colour burst median is 40 IRE (20 * 2).  At the moment this is
    // over saturating, so we are using 36 IRE (18 * 2).
    qreal iqScale = (18.0 / colourBurstMedian) * 2;

    if (blackAndWhite) {
        // Remove the colour components
        iqScale = 0;
    }

    for (const YIQ *yiq = begin; yiq < end; yiq++) {
        double y = yiq->y;
        double i = +(yiq->i);
        double q = +(yiq->q);

        // Scale the Y to 0-65535 where 0 = blackIreLevel and 65535 = whiteIreLevel
        y = (y - yBlackLevel) * yScale;
        y = clamp(y, 0.0, 65535.0);

        // Scale the I & Q components according to the colourburstMedian
        i *= iqScale;
        q *= iqScale;

        // YIQ to RGB colour-space conversion (from page 18
        // of Video Demystified, 5th edition)
        //
        // For RGB 0-255: Y 0-255. I 0- +-152. Q 0- +-134 :
        double r = y + (0.956 * i) + (0.621 * q);
        double g = y - (0.272 * i) - (0.647 * q);
        double b = y - (1.107 * i) + (1.704 * q);

        r = clamp(r, 0.0, 65535.0);
        g = clamp(g, 0.0, 65535.0);
        b = clamp(b, 0.0, 65535.0);

        // Place the 16-bit RGB values in the output array
        *out++ = static_cast<quint16>(r);
        *out++ = static_cast<quint16>(g);
        *out++ = static_cast<quint16>(b);
    }
}
