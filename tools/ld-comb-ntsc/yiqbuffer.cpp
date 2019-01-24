/************************************************************************

    yiqbuffer.cpp

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

#include "yiqbuffer.h"

YiqBuffer::YiqBuffer(void)
{
    bufferHeight = 525;
    yiqLine.resize(bufferHeight);
}

void YiqBuffer::clear(void)
{
    for (qint32 counter = 0; counter < bufferHeight; counter++) {
        yiqLine[counter].yiq->y = 0;
        yiqLine[counter].yiq->i = 0;
        yiqLine[counter].yiq->q = 0;
    }
}

// Overload the [] operator to return an indexed value
YiqLine& YiqBuffer::operator[] (const int index)
{
    if (index > bufferHeight || index < 0) {
        qCritical() << "BUG: Out of bounds call to YiqLine with an index of" << index;
        exit(EXIT_FAILURE);
    }

    return yiqLine[index];
}

// Return a qreal vector of the Y values in the YIQ buffer
QVector<qreal> YiqBuffer::yValues(void)
{
    QVector<qreal> yReturn;

    for (qint32 line = 0; line < bufferHeight; line++) {
        for (qint32 pixel = 0; pixel < yiqLine[line].width(); pixel++) {
            yReturn.append(yiqLine[line].yiq[pixel].y);
        }
    }

    return yReturn;
}
