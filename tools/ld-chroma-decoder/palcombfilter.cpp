/************************************************************************

    palcombfilter.cpp

    ld-chroma-decoder - Colourisation filter for ld-decode
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

#include "palcombfilter.h"

PalCombFilter::PalCombFilter(LdDecodeMetaData &ldDecodeMetaDataParam,
                             QObject *parent)
    : QObject(parent), ldDecodeMetaData(ldDecodeMetaDataParam)
{
    abort = false;
}

bool PalCombFilter::process(QString inputFileName, QString outputFileName,
                            qint32 startFrame, qint32 length, bool reverse,
                            bool blackAndWhite, qint32 maxThreads)
{
    // Reverse field order if required
    if (reverse) {
        qInfo() << "Expected field order is reversed to second field/first field";
        ldDecodeMetaData.setIsFirstFieldFirst(false);
    }

    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    // Ensure the source video is PAL
    if (!videoParameters.isSourcePal) {
        qInfo() << "This colour filter is for PAL video sources only";
        return false;
    }

    // Calculate the frame height
    qint32 frameHeight = (videoParameters.fieldHeight * 2) - 1;

    // Set the width of the active scan line
    qint32 videoStart = videoParameters.activeVideoStart;
    qint32 videoEnd = videoParameters.activeVideoEnd;

    // Make sure output width is divisible by 16 (better for ffmpeg processing)
    while (((videoEnd - videoStart) % 16) != 0) {
       videoEnd++;
    }

    // Show output information to the user
    qInfo() << "Input video of" << videoParameters.fieldWidth << "x" << frameHeight <<
                   "will be colourised and trimmed to" << videoEnd - videoStart << "x 576";

    // Open the source video file
    if (!sourceVideo.open(inputFileName, videoParameters.fieldWidth * videoParameters.fieldHeight)) {
        // Could not open source video file
        qInfo() << "Unable to open ld-decode video file";
        return false;
    }

    // If no startFrame parameter was specified, set the start frame to 1
    if (startFrame == -1) startFrame = 1;

    if (startFrame > ldDecodeMetaData.getNumberOfFrames()) {
        qInfo() << "Specified start frame is out of bounds, only" << ldDecodeMetaData.getNumberOfFrames() << "frames available";
        return false;
    }

    // If no length parameter was specified set the length to the number of available frames
    if (length == -1) {
        length = ldDecodeMetaData.getNumberOfFrames() - (startFrame - 1);
    } else {
        if (length + (startFrame - 1) > ldDecodeMetaData.getNumberOfFrames()) {
            qInfo() << "Specified length of" << length << "exceeds the number of available frames, setting to" << ldDecodeMetaData.getNumberOfFrames() - (startFrame - 1);
            length = ldDecodeMetaData.getNumberOfFrames() - (startFrame - 1);
        }
    }

    // Open the output RGB file
    if (outputFileName.isNull()) {
        // No output filename, use stdout instead
        if (!targetVideo.open(stdout, QIODevice::WriteOnly)) {
            // Failed to open stdout
            qCritical() << "Could not open stdout for RGB output";
            sourceVideo.close();
            return false;
        }
        qInfo() << "Using stdout as RGB output";
    } else {
        // Open output file
        targetVideo.setFileName(outputFileName);
        if (!targetVideo.open(QIODevice::WriteOnly)) {
            // Failed to open output file
            qCritical() << "Could not open " << outputFileName << "as RGB output file";
            sourceVideo.close();
            return false;
        }
    }

    qInfo() << "Using" << maxThreads << "threads";
    qInfo() << "Processing from start frame #" << startFrame << "with a length of" << length << "frames";

    // Initialise processing state
    inputFrameNumber = startFrame;
    outputFrameNumber = startFrame;
    lastFrameNumber = length + (startFrame - 1);
    totalTimer.start();

    // Start a vector of filtering threads to process the video
    QVector<FilterThread*> filterThreads;
    filterThreads.resize(maxThreads);
    for (qint32 i = 0; i < maxThreads; i++) {
        filterThreads[i] = new FilterThread(abort, *this, videoParameters, blackAndWhite);
        filterThreads[i]->start(QThread::LowPriority);
    }

    // Wait for the workers to finish
    for (qint32 i = 0; i < maxThreads; i++) {
        filterThreads[i]->wait();
        delete filterThreads[i];
    }

    // Did any of the threads abort?
    if (abort) {
        sourceVideo.close();
        targetVideo.close();
        return false;
    }

    // Check we've processed all the frames, now the workers have finished
    if (inputFrameNumber != (lastFrameNumber + 1) || outputFrameNumber != (lastFrameNumber + 1)
        || !pendingOutputFrames.empty()) {
        qCritical() << "Incorrect state at end of processing";
        sourceVideo.close();
        targetVideo.close();
        return false;
    }

    qreal totalSecs = (static_cast<qreal>(totalTimer.elapsed()) / 1000.0);
    qInfo() << "Processing complete -" << length << "frames in" << totalSecs << "seconds (" <<
               length / totalSecs << "FPS )";

    // Show processing summary
    qInfo() << "Processed" << length << "frames into" <<
               videoEnd - videoStart << "x 576" <<
               "RGB16-16-16 frames";

    // Close the source video
    sourceVideo.close();

    // Close the target video
    targetVideo.close();

    return true;
}

// Get the next frame that needs processing from the input.
//
// Returns true if a frame was returned, false if the end of the input has been
// reached.
bool PalCombFilter::getInputFrame(qint32 &frameNumber, QByteArray& firstField, QByteArray& secondField, qreal& burstMedianIre)
{
    QMutexLocker locker(&inputMutex);

    if (inputFrameNumber > lastFrameNumber) {
        // No more input frames
        return false;
    }

    frameNumber = inputFrameNumber;
    inputFrameNumber++;

    // Determine the first and second fields for the frame number
    qint32 firstFieldNumber = ldDecodeMetaData.getFirstFieldNumber(frameNumber);
    qint32 secondFieldNumber = ldDecodeMetaData.getSecondFieldNumber(frameNumber);

    // Show what we are about to process
    qDebug() << "PalCombFilter::process(): Frame number" << frameNumber << "has a first-field of" << firstFieldNumber <<
                "and a second field of" << secondFieldNumber;

    // Fetch the input data
    firstField = sourceVideo.getVideoField(firstFieldNumber)->getFieldData();
    secondField = sourceVideo.getVideoField(secondFieldNumber)->getFieldData();
    burstMedianIre = ldDecodeMetaData.getField(firstFieldNumber).medianBurstIRE;

    return true;
}

// Put a decoded frame into the output stream.
//
// The worker threads will complete frames in an arbitrary order, so we can't
// just write the frames to the output file directly. Instead, we keep a map of
// frames that haven't yet been written; when a new frame comes in, we check
// whether we can now write some of them out.
//
// Returns true on success, false on failure.
bool PalCombFilter::putOutputFrame(qint32 frameNumber, QByteArray& rgbOutput)
{
    QMutexLocker locker(&outputMutex);

    // Put this frame into the map
    pendingOutputFrames[frameNumber] = rgbOutput;

    // Write out as many frames as possible
    while (pendingOutputFrames.contains(outputFrameNumber)) {
        const QByteArray& outputData = pendingOutputFrames.value(outputFrameNumber);

        // Save the frame data to the output file
        if (!targetVideo.write(outputData.data(), outputData.size())) {
            // Could not write to target video file
            qCritical() << "Writing to the output video file failed";
            return false;
        }

        pendingOutputFrames.remove(outputFrameNumber);
        outputFrameNumber++;

        if ((outputFrameNumber % 32) == 0) {
            // Show an update to the user
            qreal fps = outputFrameNumber / (static_cast<qreal>(totalTimer.elapsed()) / 1000.0);
            qInfo() << outputFrameNumber << "frames processed -" << fps << "FPS";
        }
    }

    return true;
}
