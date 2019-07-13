/************************************************************************

    decoderpool.cpp

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

#include "decoderpool.h"

DecoderPool::DecoderPool(Decoder &decoderParam, QString inputFileNameParam,
                         LdDecodeMetaData &ldDecodeMetaDataParam, QString outputFileNameParam,
                         qint32 startFrameParam, qint32 lengthParam, qint32 maxThreadsParam,
                         QObject *parent)
    : QObject(parent), decoder(decoderParam), inputFileName(inputFileNameParam),
      outputFileName(outputFileNameParam), startFrame(startFrameParam),
      length(lengthParam), maxThreads(maxThreadsParam),
      abort(false), ldDecodeMetaData(ldDecodeMetaDataParam)
{
}

bool DecoderPool::process()
{
    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    // Configure the decoder, and check that it can accept this video
    if (!decoder.configure(videoParameters)) {
        return false;
    }

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
    QVector<QThread *> threads;
    threads.resize(maxThreads);
    for (qint32 i = 0; i < maxThreads; i++) {
        threads[i] = decoder.makeThread(abort, *this);
        threads[i]->start(QThread::LowPriority);
    }

    // Wait for the workers to finish
    for (qint32 i = 0; i < maxThreads; i++) {
        threads[i]->wait();
        delete threads[i];
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
bool DecoderPool::getInputFrame(qint32 &frameNumber, QByteArray &firstFieldData, QByteArray &secondFieldData,
                                qint32 &firstFieldPhaseID, qint32 &secondFieldPhaseID,
                                qreal& burstMedianIre)
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
    qDebug() << "DecoderPool::process(): Frame number" << frameNumber << "has a first-field of" << firstFieldNumber <<
                "and a second field of" << secondFieldNumber;

    // Fetch the input data
    firstFieldData = sourceVideo.getVideoField(firstFieldNumber);
    secondFieldData = sourceVideo.getVideoField(secondFieldNumber);
    burstMedianIre = ldDecodeMetaData.getField(firstFieldNumber).medianBurstIRE;
    firstFieldPhaseID = ldDecodeMetaData.getField(firstFieldNumber).fieldPhaseID;
    secondFieldPhaseID = ldDecodeMetaData.getField(secondFieldNumber).fieldPhaseID;

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
bool DecoderPool::putOutputFrame(qint32 frameNumber, QByteArray &rgbOutput)
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

        const qint32 outputCount = outputFrameNumber - startFrame;
        if ((outputCount % 32) == 0) {
            // Show an update to the user
            qreal fps = outputCount / (static_cast<qreal>(totalTimer.elapsed()) / 1000.0);
            qInfo() << outputCount << "frames processed -" << fps << "FPS";
        }
    }

    return true;
}
