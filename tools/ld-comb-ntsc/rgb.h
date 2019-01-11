/************************************************************************

    rgb.h

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

#ifndef RGB_H
#define RGB_H

#include <QCoreApplication>
#include <QDebug>

#include "yiq.h"

class RGB
{
public:
    double r, g, b;
    RGB(double whiteIreParam, double blackIreParam);

    void conv(YIQ _y, qreal colourBurstMedian);

private:
    double blackIreLevel;
    double whiteIreLevel;

    double clamp(double v, double low, double high);
    double scaleY(double level);
};

#endif // RGB_H
