/************************************************************************

    ycbcr.cpp

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

#include "ycbcr.h"


YCbCr::YCbCr(double _whiteIreLevel, double _blackIreLevel, bool _whitePoint75, double _chromaGain)
    : whiteIreLevel(_whiteIreLevel), blackIreLevel(_blackIreLevel), whitePoint75(_whitePoint75),
      chromaGain(_chromaGain)
{
}

void YCbCr::convertLine(const YIQ *begin, const YIQ *end, quint16 *outY, quint16 *outCb, quint16 *outCr)
{
    // Factors to scale Y according to the black to white interval
    double yBlackLevel = blackIreLevel;
    double yScale = 219.0 * 257.0 / (whiteIreLevel - blackIreLevel);

    // Compute I & Q scaling factors
    const double iqScale = chromaGain / (whiteIreLevel - blackIreLevel);
    const double cbScale = 112 * 256 / (ONE_MINUS_Kb * kB); // Poynton, Eq 25.5 & 28.1
    const double crScale = 112 * 256 / (ONE_MINUS_Kr * kR);

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

        // Scale and offset Y such that 16 * 256 = blackIreLevel and 235 * 256 = whiteIreLevel
        y = (y - yBlackLevel) * yScale + 16 * 256;

        // Scale the I & Q components to [0,1]
        i *= iqScale;
        q *= iqScale;

        // Rotate 33 degrees and swap axis to switch to U & V
        double U = (-SIN33 * i + COS33 * q);
        double V = ( COS33 * i + SIN33 * q);

        // Scale and offset to create CbCr
        double Cb = U * cbScale + 128 * 256;
        double Cr = V * crScale + 128 * 256;

        // Clamp to valid range, per ITU-R BT.601-7 § 2.5.3
        y  = qBound(1.0 * 256.0, y,  254.75 * 256.0);
        Cb = qBound(1.0 * 256.0, Cb, 254.75 * 256.0);
        Cr = qBound(1.0 * 256.0, Cr, 254.75 * 256.0);

        // Place the 16-bit YCbCr values in the output arrays
        *outY++ = static_cast<quint16>(y);
        *outCb++ = static_cast<quint16>(Cb);
        *outCr++ = static_cast<quint16>(Cr);
    }
}
