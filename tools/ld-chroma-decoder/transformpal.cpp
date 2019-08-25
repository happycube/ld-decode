/************************************************************************

    transformpal.cpp

    ld-chroma-decoder - Colourisation filter for ld-decode
    Copyright (C) 2019 Adam Sampson

    Reusing code from pyctools-pal, which is:
    Copyright (C) 2014 Jim Easterbrook

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

#include "transformpal.h"

#include <cmath>

TransformPal::TransformPal()
    : configurationSet(false)
{
}

TransformPal::~TransformPal()
{
}

void TransformPal::updateConfiguration(const LdDecodeMetaData::VideoParameters &_videoParameters,
                                       qint32 _firstActiveLine, qint32 _lastActiveLine,
                                       TransformPal::TransformMode _mode, double _threshold)
{
    videoParameters = _videoParameters;
    firstActiveLine = _firstActiveLine;
    lastActiveLine = _lastActiveLine;
    mode = _mode;
    threshold = _threshold;

    configurationSet = true;
}

void TransformPal::overlayFFT(qint32 positionX, qint32 positionY,
                              const QVector<SourceField> &inputFields, qint32 startIndex, qint32 endIndex,
                              QVector<QByteArray> &rgbFrames)
{
    // Visualise the first field for each output frame
    for (int fieldIndex = startIndex, outputIndex = 0; fieldIndex < endIndex; fieldIndex += 2, outputIndex++) {
        overlayFFTFrame(positionX, positionY, inputFields, fieldIndex, rgbFrames[outputIndex]);
    }
}

// Overlay the input and output FFT arrays, in either 2D or 3D
void TransformPal::overlayFFTArrays(const fftw_complex *fftIn, const fftw_complex *fftOut,
                                    qint32 xSize, qint32 ySize, qint32 zSize,
                                    FrameCanvas &canvas)
{
    // How many pixels to draw for each element
    const qint32 xScale = 2;
    const qint32 yScale = 2;

    // Each block shows the absolute value of the real component of an FFT element using a log scale.
    // Work out a scaling factor to make all values visible.
    double maxValue = 0;
    for (qint32 i = 0; i < xSize * ySize * zSize; i++) {
        maxValue = qMax(maxValue, abs(fftIn[i][0]));
        maxValue = qMax(maxValue, abs(fftOut[i][0]));
    }
    const double valueScale = 65535.0 / log2(maxValue);

    // Draw each 2D plane of the array
    for (qint32 z = 0; z < zSize; z++) {
        for (qint32 column = 0; column < 2; column++) {
            const fftw_complex *fftData = column == 0 ? fftIn : fftOut;

            // Work out where this 2D array starts
            const qint32 yStart = canvas.top() + (z * ((yScale * ySize) + 1));
            const qint32 xStart = canvas.right() - ((2 - column) * ((xScale * xSize) + 1)) - 1;

            // Outline the array
            canvas.drawRectangle(xStart, yStart, (xScale * xSize) + 2, (yScale * ySize) + 2, canvas.green);

            // Draw the elements in the array
            for (qint32 y = 0; y < ySize; y++) {
                for (qint32 x = 0; x < xSize; x++) {
                    const double value = abs(fftData[(((z * ySize) + y) * xSize) + x][0]);
                    const double shade = value <= 0 ? 0 : log2(value) * valueScale;
                    const quint16 shade16 = static_cast<quint16>(qBound(0.0, shade, 65535.0));
                    canvas.fillRectangle(xStart + (x * xScale) + 1, yStart + (y * yScale) + 1, xScale, yScale, canvas.grey(shade16));
                }
            }
        }
    }
}
