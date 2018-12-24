/************************************************************************

    filterthread.cpp

    ld-comb-pal - PAL colourisation filter for ld-decode
    Copyright (C) 2018 Simon Inns

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

FilterThread::FilterThread(LdDecodeMetaData::VideoParameters videoParametersParam, bool isVP415CropSetParam, QObject *parent) : QThread(parent)
{
    // Thread control variables
    isProcessing = false;
    abort = false;

    // Configure PAL colour
    videoParameters = videoParametersParam;
    isVP415CropSet = isVP415CropSetParam;
    palColour = new PalColour(videoParameters);

    // Calculate the frame height
    qint32 frameHeight = (videoParameters.fieldHeight * 2) - 1;

    outputData.resize(videoParameters.fieldWidth * frameHeight * 6);

    // Set the first and last active scan line
    firstActiveScanLine = 44;
    lastActiveScanLine = 617;
    videoStart = videoParameters.activeVideoStart;
    videoEnd = videoParameters.activeVideoEnd;

    // Calculate the VP415 video extents
    qreal vp415FirstActiveScanLine = firstActiveScanLine + ((frameHeight / 100) * 1.0);
    qreal vp415LastActiveScanLine = lastActiveScanLine - ((frameHeight / 100) * 1.0);
    qreal vp415VideoStart = videoParameters.activeVideoStart + ((videoParameters.fieldWidth / 100) * 1.0);
    qreal vp415VideoEnd = videoParameters.activeVideoEnd - ((videoParameters.fieldWidth / 100) * 1.0);

    if (isVP415CropSet) {
        firstActiveScanLine = static_cast<qint32>(vp415FirstActiveScanLine);
        lastActiveScanLine = static_cast<qint32>(vp415LastActiveScanLine);
        videoStart = static_cast<qint32>(vp415VideoStart);
        videoEnd = static_cast<qint32>(vp415VideoEnd);
    }

    // Make sure output height is even (better for ffmpeg processing)
    if (((lastActiveScanLine - firstActiveScanLine) % 2) != 0) {
       lastActiveScanLine--;
    }

    // Make sure output width is even (better for ffmpeg processing)
    if (((videoEnd - videoStart) % 2) != 0) {
       videoEnd++;
    }
}

FilterThread::~FilterThread()
{
    mutex.lock();
    abort = true;
    condition.wakeOne();
    mutex.unlock();

    wait();

    delete palColour;
}

void FilterThread::startFilter(QByteArray firstFieldParam, QByteArray secondFieldParam, qreal burstMedianIreParam)
{
    QMutexLocker locker(&mutex);

    // Move all the parameters to be local
    firstFieldData = firstFieldParam;
    secondFieldData = secondFieldParam;
    burstMedianIre = burstMedianIreParam;

    // Is the run process already running?
    if (!isRunning()) {
        // Yes, start with low priority
        start(LowPriority);
        isProcessing = true;
    } else {
        // No, set the restart condition
        isProcessing = true;
        condition.wakeOne();
    }
}

QByteArray FilterThread::getResult(void)
{
    return rgbOutputData;
}

bool FilterThread::isBusy(void)
{
    return isProcessing;
}

void FilterThread::run()
{
    qDebug() << "FilterThread::run(): Thread running";

    while(!abort) {
        if (isProcessing) {
            // Lock and copy all parameters to 'thread-safe' variables
            mutex.lock();
            tsFirstFieldData = firstFieldData;
            tsSecondFieldData = secondFieldData;
            mutex.unlock();

            // Calculate the saturation level from the burst median IRE
            // Note: This code works as a temporary MTF compensator whilst ld-decode gets
            // real MTF compensation added to it.
            qreal tSaturation = 125.0 + ((100.0 / 20.0) * (20.0 - burstMedianIre));

            // Perform the PALcolour filtering
            outputData = palColour->performDecode(tsFirstFieldData, tsSecondFieldData, 100, static_cast<qint32>(tSaturation));

            // The PAL colour library outputs the whole frame, so here we have to strip all the non-visible stuff to just get the
            // actual required image - it would be better if PALcolour gave back only the required RGB, but it's not my library.
            rgbOutputData.clear();

            // Since PALcolour uses +-3 scan-lines to colourise, the final lines before the non-visible area may not come out quite
            // right, but we're including them here anyway.
            for (qint32 y = firstActiveScanLine; y < lastActiveScanLine; y++) {
                rgbOutputData.append(outputData.mid((y * videoParameters.fieldWidth * 6) + (videoStart * 6),
                                                        ((videoEnd - videoStart) * 6)));
            }

            isProcessing = false;
        }

        // Sleep the thread until it is restarted
        mutex.lock();
        if (!isProcessing && !abort) condition.wait(&mutex);
        mutex.unlock();
    }
}
