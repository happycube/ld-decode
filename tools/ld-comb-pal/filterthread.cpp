/************************************************************************

    filterthread.cpp

    ld-comb-pal - PAL colourisation filter for ld-decode
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-comb-pal is free software: you can redistribute it and/or
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

#include "filterthread.h"
#include "palcombfilter.h"

FilterThread::FilterThread(QAtomicInt& abortParam, PalCombFilter& combFilterParam, LdDecodeMetaData::VideoParameters videoParametersParam, bool blackAndWhiteParam, QObject *parent)
    : QThread(parent), abort(abortParam), combFilter(combFilterParam)
{
    // Configure PAL colour
    videoParameters = videoParametersParam;
    palColour.updateConfiguration(videoParameters);
    blackAndWhite = blackAndWhiteParam;

    // Calculate the frame height
    qint32 frameHeight = (videoParameters.fieldHeight * 2) - 1;

    outputData.resize(videoParameters.fieldWidth * frameHeight * 6);

    // Set the first and last active scan line
    firstActiveScanLine = 44;
    lastActiveScanLine = 620;
    videoStart = videoParameters.activeVideoStart;
    videoEnd = videoParameters.activeVideoEnd;

    // Make sure output height is even (better for ffmpeg processing)
    if (((lastActiveScanLine - firstActiveScanLine) % 2) != 0) {
       lastActiveScanLine--;
    }

    // Make sure output width is divisible by 16 (better for ffmpeg processing)
    while (((videoEnd - videoStart) % 16) != 0) {
       videoEnd++;
    }
}

void FilterThread::run()
{
    qint32 frameNumber;

    // Input data buffers
    QByteArray firstFieldData;
    QByteArray secondFieldData;
    QByteArray rgbOutputData;

    // Burst level data
    qreal burstMedianIre;

    qDebug() << "FilterThread::run(): Thread running";

    while(!abort) {
        // Get the next frame to process from the input file
        if (!combFilter.getInputFrame(frameNumber, firstFieldData, secondFieldData, burstMedianIre)) {
            // No more input frames -- exit
            break;
        }

        // Calculate the saturation level from the burst median IRE
        // Note: This code works as a temporary MTF compensator whilst ld-decode gets
        // real MTF compensation added to it.
        qreal tSaturation = 125.0 + ((100.0 / 20.0) * (20.0 - burstMedianIre));

        // Perform the PALcolour filtering
        outputData = palColour.performDecode(firstFieldData, secondFieldData, 100, static_cast<qint32>(tSaturation), blackAndWhite);

        // The PAL colour library outputs the whole frame, so here we have to strip all the non-visible stuff to just get the
        // actual required image - it would be better if PALcolour gave back only the required RGB, but it's not my library.
        rgbOutputData.clear();

        // Add additional output lines to ensure the output height is 576 lines
        QByteArray blankLine;
        blankLine.resize((videoEnd - videoStart) * 6 );
        blankLine.fill(0);
        for (qint32 y = 0; y < 576 - (lastActiveScanLine - firstActiveScanLine); y++) {
            rgbOutputData.append(blankLine);
        }

        // Since PALcolour uses +-3 scan-lines to colourise, the final lines before the non-visible area may not come out quite
        // right, but we're including them here anyway.
        for (qint32 y = firstActiveScanLine; y < lastActiveScanLine; y++) {
            rgbOutputData.append(outputData.mid((y * videoParameters.fieldWidth * 6) + (videoStart * 6),
                                                    ((videoEnd - videoStart) * 6)));
        }

        // Write the result to the output file
        if (!combFilter.putOutputFrame(frameNumber, rgbOutputData)) {
            abort = true;
            break;
        }
    }
}
