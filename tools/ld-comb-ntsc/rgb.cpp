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

RGB::RGB(double whiteIreParam, double blackIreParam)
{
    blackIreLevel = blackIreParam / 100;
    whiteIreLevel = whiteIreParam / 100;
    ireScale = whiteIreLevel - blackIreLevel;
}

void RGB::conv(YIQ _y)
{
    YIQ t;

    double y = u16_to_ire(_y.y);
    double q = +(_y.q) / ireScale;
    double i = +(_y.i) / ireScale;

    // YIQ to RGB colour-space conversion (from page 18
    // of Video Demystified, 5th edition)
    //
    // For RGB 0-255: Y 0-255. I 0- +-152. Q 0- +-134
    r = y + (0.956 * i) + (0.621 * q);
    g = y - (0.272 * i) - (0.647 * q);
    b = y - (1.107 * i) + (1.704 * q);

    r = clamp(r * whiteIreLevel, 0, 65535);
    g = clamp(g * whiteIreLevel, 0, 65535);
    b = clamp(b * whiteIreLevel, 0, 65535);
}

// Private methods ----------------------------------------------------------------------------------------------------

double RGB::clamp(double v, double low, double high)
{
        if (v < low) return low;
        else if (v > high) return high;
        else return v;
}

double RGB::u16_to_ire(double level)
{
    if (level <= 0) return -100;

    return -40 + (static_cast<double>(level - blackIreLevel) / ireScale);
}

