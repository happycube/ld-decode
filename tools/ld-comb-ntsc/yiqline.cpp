/************************************************************************

    yiqline.cpp

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

#include "yiqline.h"

YiqLine::YiqLine()
{
    lineWidth = 910;
    yiq.resize(lineWidth);
}

// Overload the [] operator to return an indexed value
YIQ& YiqLine::operator[] (const int index)
{
    if (index > lineWidth || index < 0) {
        qCritical() << "BUG: Out of bounds call to YiqLine with an index of" << index;
        exit(EXIT_FAILURE);
    }

    return yiq[index];
}

// Method to return the width of the lines within the YiqLine object
qint32 YiqLine::width(void)
{
    return lineWidth;
}
