/************************************************************************

    rgb.cpp

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

#include "rgb.h"

RGB::RGB(double _whiteIreLevel, double _blackIreLevel, bool _whitePoint75, double _chromaGain)
    : whiteIreLevel(_whiteIreLevel), blackIreLevel(_blackIreLevel), whitePoint75(_whitePoint75),
      chromaGain(_chromaGain)
{
}

void RGB::convertLine(const YIQ *begin, const YIQ *end, quint16 *out)
{
    // Factors to scale Y according to the black to white interval
    // (i.e. make the black level 0 and the white level 65535)
    qreal yBlackLevel = blackIreLevel;
    qreal yScale = 65535.0 / (whiteIreLevel - blackIreLevel);

    // Compute I & Q scaling factor.
    // This is the same as for Y, i.e. when 7.5% setup is in use the chroma
    // scale is reduced proportionately.
    const double iqScale = yScale * chromaGain;

    if (whitePoint75) {
        // NTSC uses a 75% white point; so here we scale the result by
        // 25% (making 100 IRE 25% over the maximum allowed white point).
        // This doesn't affect the chroma scaling.
        yScale *= 125.0 / 100.0;
    }

    for (const YIQ *yiq = begin; yiq < end; yiq++) {
        double y = yiq->y;
        double i = yiq->i;
        double q = yiq->q;

        // Scale the Y to 0-65535 where 0 = blackIreLevel and 65535 = whiteIreLevel
        y = (y - yBlackLevel) * yScale;
        y = qBound(0.0, y, 65535.0);

        // Scale the I & Q components
        i *= iqScale;
        q *= iqScale;

        // YIQ to RGB colour-space conversion (from page 18
        // of Video Demystified, 5th edition)
        //
        // For RGB 0-255: Y 0-255. I 0- +-152. Q 0- +-134 :
        double r = y + (0.956 * i) + (0.621 * q);
        double g = y - (0.272 * i) - (0.647 * q);
        double b = y - (1.107 * i) + (1.704 * q);

        r = qBound(0.0, r, 65535.0);
        g = qBound(0.0, g, 65535.0);
        b = qBound(0.0, b, 65535.0);

        // Place the 16-bit RGB values in the output array
        *out++ = static_cast<quint16>(r);
        *out++ = static_cast<quint16>(g);
        *out++ = static_cast<quint16>(b);
    }
}
