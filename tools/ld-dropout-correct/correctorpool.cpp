/************************************************************************

    correctorpool.cpp

    ld-dropout-correct - Dropout correction for ld-decode
    Copyright (C) 2018-2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-dropout-correct is free software: you can redistribute it and/or
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

#include "correctorpool.h"

#include <cstdio>

CorrectorPool::CorrectorPool(QString _outputFilename, QString _outputJsonFilename,
                             qint32 _maxThreads, QVector<LdDecodeMetaData> &_ldDecodeMetaData, QVector<SourceVideo> &_sourceVideos,
                             bool _reverse, bool _intraField, bool _overCorrect, QObject *parent)
    : QObject(parent), outputFilename(_outputFilename), outputJsonFilename(_outputJsonFilename),
      maxThreads(_maxThreads), reverse(_reverse), intraField(_intraField), overCorrect(_overCorrect),
      abort(false), ldDecodeMetaData(_ldDecodeMetaData), sourceVideos(_sourceVideos)
{
}

bool CorrectorPool::process()
{
    // Open the target video
    targetVideo.setFileName(outputFilename);
    if (outputFilename == "-") {
        if (!targetVideo.open(stdout, QIODevice::WriteOnly)) {
                // Could not open stdout
                qInfo() << "Unable to open stdout";
                sourceVideos[0].close();
                return false;
        }
    } else {
        if (!targetVideo.open(QIODevice::WriteOnly)) {
                // Could not open target video file
                qInfo() << "Unable to open output video file";
                sourceVideos[0].close();
                return false;
        }
    }

    // If there is a leading field in the TBC which is out of field order, we need to copy it
    // to ensure the JSON metadata files match up
    qInfo() << "Verifying leading fields match...";
    qint32 firstFieldNumber = ldDecodeMetaData[0].getFirstFieldNumber(1);
    qint32 secondFieldNumber = ldDecodeMetaData[0].getSecondFieldNumber(1);

    if (firstFieldNumber != 1 && secondFieldNumber != 1) {
        QByteArray sourceField;
        sourceField = sourceVideos[0].getVideoField(1);
        if (!targetVideo.write(sourceField, sourceField.size())) {
            // Could not write to target TBC file
            qInfo() << "Writing first field to the output TBC file failed";
            targetVideo.close();
            sourceVideos[0].close();
            return false;
        }
    }

    // Show some information for the user
    qInfo() << "Using" << maxThreads << "threads to process" << ldDecodeMetaData[0].getNumberOfFrames() << "frames";

    // Initialise processing state
    inputFrameNumber = 1;
    outputFrameNumber = 1;
    lastFrameNumber = ldDecodeMetaData[0].getNumberOfFrames();
    totalTimer.start();

    // Start a vector of decoding threads to process the video
    QVector<QThread *> threads;
    threads.resize(maxThreads);
    for (qint32 i = 0; i < maxThreads; i++) {
        threads[i] = new DropOutCorrect(abort, *this);
        threads[i]->start(QThread::LowPriority);
    }

    // Wait for the workers to finish
    for (qint32 i = 0; i < maxThreads; i++) {
        threads[i]->wait();
        delete threads[i];
    }

    // Did any of the threads abort?
    if (abort) {
        sourceVideos[0].close();
        targetVideo.close();
        return false;
    }

    // Show the processing speed to the user
    qreal totalSecs = (static_cast<qreal>(totalTimer.elapsed()) / 1000.0);
    qInfo() << "Dropout correction complete -" << lastFrameNumber << "frames in" << totalSecs << "seconds (" <<
               lastFrameNumber / totalSecs << "FPS )";

    qInfo() << "Creating JSON metadata file for drop-out corrected TBC";
    ldDecodeMetaData[0].write(outputJsonFilename);

    qInfo() << "Processing complete";

    // Close the source and target video
    sourceVideos[0].close();
    targetVideo.close();

    return true;
}

// Get the next frame that needs processing from the input.
//
// Returns true if a frame was returned, false if the end of the input has been
// reached.
bool CorrectorPool::getInputFrame(qint32& frameNumber,
                                  QVector<qint32>& firstFieldNumber, QVector<QByteArray>& firstFieldVideoData, QVector<LdDecodeMetaData::Field>& firstFieldMetadata,
                                  QVector<qint32>& secondFieldNumber, QVector<QByteArray>& secondFieldVideoData, QVector<LdDecodeMetaData::Field>& secondFieldMetadata,
                                  QVector<LdDecodeMetaData::VideoParameters>& videoParameters,
                                  bool& _reverse, bool& _intraField, bool& _overCorrect)
{
    QMutexLocker locker(&inputMutex);

    if (inputFrameNumber > lastFrameNumber) {
        // No more input frames
        return false;
    }

    frameNumber = inputFrameNumber;
    inputFrameNumber++;

    qDebug() << "CorrectorPool::getInputFrame(): Frame number =" << frameNumber;

    // Prepare the vectors
    firstFieldNumber.resize(1);
    firstFieldVideoData.resize(1);
    firstFieldMetadata.resize(1);
    secondFieldNumber.resize(1);
    secondFieldVideoData.resize(1);
    secondFieldMetadata.resize(1);
    videoParameters.resize(1);

    // Determine the fields for the input frame
    firstFieldNumber[0] = ldDecodeMetaData[0].getFirstFieldNumber(frameNumber);
    secondFieldNumber[0] = ldDecodeMetaData[0].getSecondFieldNumber(frameNumber);

    // Fetch the input data (get the fields in TBC sequence order to save seeking)
    if (firstFieldNumber[0] < secondFieldNumber[0]) {
        firstFieldVideoData[0] = sourceVideos[0].getVideoField(firstFieldNumber[0]);
        secondFieldVideoData[0] = sourceVideos[0].getVideoField(secondFieldNumber[0]);
    } else {
        secondFieldVideoData[0] = sourceVideos[0].getVideoField(secondFieldNumber[0]);
        firstFieldVideoData[0] = sourceVideos[0].getVideoField(firstFieldNumber[0]);
    }

    firstFieldMetadata[0] = ldDecodeMetaData[0].getField(firstFieldNumber[0]);
    secondFieldMetadata[0] = ldDecodeMetaData[0].getField(secondFieldNumber[0]);
    videoParameters[0] = ldDecodeMetaData[0].getVideoParameters();

    _reverse = reverse;
    _intraField = intraField;
    _overCorrect = overCorrect;

    return true;
}

// Put a corrected frame into the output stream.
//
// The worker threads will complete frames in an arbitrary order, so we can't
// just write the frames to the output file directly. Instead, we keep a map of
// frames that haven't yet been written; when a new frame comes in, we check
// whether we can now write some of them out.
//
// Returns true on success, false on failure.
bool CorrectorPool::setOutputFrame(qint32 frameNumber,
                                   QByteArray firstTargetFieldData, QByteArray secondTargetFieldData,
                                   qint32 firstFieldSeqNo, qint32 secondFieldSeqNo)
{
    QMutexLocker locker(&outputMutex);

    // Put the output frame into the map
    OutputFrame outputFrame;
    outputFrame.firstTargetFieldData = firstTargetFieldData;
    outputFrame.secondTargetFieldData = secondTargetFieldData;
    outputFrame.firstFieldSeqNo = firstFieldSeqNo;
    outputFrame.secondFieldSeqNo = secondFieldSeqNo;
    pendingOutputFrames[frameNumber] = outputFrame;

    // Write out as many frames as possible
    while (pendingOutputFrames.contains(outputFrameNumber)) {
        const QByteArray& outputFirstTargetFieldData = pendingOutputFrames.value(outputFrameNumber).firstTargetFieldData;
        const QByteArray& outputSecondTargetFieldData = pendingOutputFrames.value(outputFrameNumber).secondTargetFieldData;
        const qint32& outputFirstFieldSeqNo = pendingOutputFrames.value(outputFrameNumber).firstFieldSeqNo;
        const qint32& secondFirstFieldSeqNo = pendingOutputFrames.value(outputFrameNumber).secondFieldSeqNo;

        // Save the frame data to the output file (with the fields in the correct order)
        bool writeFail = false;
        if (outputFirstFieldSeqNo < secondFirstFieldSeqNo) {
            // Save the first field and then second field to the output file
            if (!targetVideo.write(outputFirstTargetFieldData.data(), outputFirstTargetFieldData.size())) writeFail = true;
            if (!targetVideo.write(outputSecondTargetFieldData.data(), outputSecondTargetFieldData.size())) writeFail = true;
        } else {
            // Save the second field and then first field to the output file
            if (!targetVideo.write(outputSecondTargetFieldData.data(), outputSecondTargetFieldData.size())) writeFail = true;
            if (!targetVideo.write(outputFirstTargetFieldData.data(), outputFirstTargetFieldData.size())) writeFail = true;
        }

        // Was the write successful?
        if (writeFail) {
            // Could not write to target TBC file
            qCritical() << "Writing fields to the output TBC file failed";
            targetVideo.close();
            sourceVideos[0].close();
            return false;
        }

        if (outputFrameNumber % 100 == 0) {
            qInfo() << "Processed and written frame" << outputFrameNumber;
        }

        pendingOutputFrames.remove(outputFrameNumber);
        outputFrameNumber++;
    }

    return true;
}
