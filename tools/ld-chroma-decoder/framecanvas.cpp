/************************************************************************

    framecanvas.cpp

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2019 Adam Sampson

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

#include "framecanvas.h"

// Definitions of static constexpr data members, for compatibility with
// pre-C++17 compilers
constexpr FrameCanvas::RGB FrameCanvas::green;

FrameCanvas::FrameCanvas(QByteArray &_rgbFrame, const LdDecodeMetaData::VideoParameters &_videoParameters,
                         qint32 _firstActiveLine, qint32 _lastActiveLine)
    : rgbData(reinterpret_cast<quint16 *>(_rgbFrame.data())), rgbSize(_rgbFrame.size() / sizeof(quint16)),
      videoParameters(_videoParameters), firstActiveLine(_firstActiveLine), lastActiveLine(_lastActiveLine)
{
}

qint32 FrameCanvas::top()
{
    return firstActiveLine;
}

qint32 FrameCanvas::bottom()
{
    return lastActiveLine;
}

qint32 FrameCanvas::left()
{
    return videoParameters.activeVideoStart;
}

qint32 FrameCanvas::right()
{
    return videoParameters.activeVideoEnd;
}

FrameCanvas::RGB FrameCanvas::grey(quint16 value)
{
    return RGB {value, value, value};
}

void FrameCanvas::drawPoint(qint32 x, qint32 y, const RGB& colour)
{
    const qint32 offset = ((y * videoParameters.fieldWidth) + x) * 3;
    if (x < 0 || x >= videoParameters.fieldWidth || offset < 0 || offset >= (rgbSize - 2)) {
        // Outside the frame
        return;
    }

    rgbData[offset] = colour.r;
    rgbData[offset + 1] = colour.g;
    rgbData[offset + 2] = colour.b;
}

void FrameCanvas::drawRectangle(qint32 xStart, qint32 yStart, qint32 w, qint32 h, const RGB& colour)
{
    for (qint32 y = yStart; y < yStart + h; y++) {
        drawPoint(xStart, y, colour);
        drawPoint(xStart + w - 1, y, colour);
    }
    for (qint32 x = xStart + 1; x < xStart + w - 1; x++) {
        drawPoint(x, yStart, colour);
        drawPoint(x, yStart + h - 1, colour);
    }
}

void FrameCanvas::fillRectangle(qint32 xStart, qint32 yStart, qint32 w, qint32 h, const RGB& colour)
{
    for (qint32 y = yStart; y < yStart + h; y++) {
        for (qint32 x = xStart; x < xStart + w; x++) {
            drawPoint(x, y, colour);
        }
    }
}
