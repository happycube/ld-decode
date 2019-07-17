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

CorrectorPool::CorrectorPool(QString _inputFilename, QString _outputFilename, qint32 _maxThreads, LdDecodeMetaData &_ldDecodeMetaData,
                             bool _reverse, bool _intraField, bool _overCorrect, QObject *parent)
    : QObject(parent), inputFilename(_inputFilename), outputFilename(_outputFilename), maxThreads(_maxThreads), reverse(_reverse),
      intraField(_intraField), overCorrect(_overCorrect),  abort(false), ldDecodeMetaData(_ldDecodeMetaData)
{
}

bool CorrectorPool::process()
{
    // Reverse field order if required
    if (reverse) {
        qInfo() << "Expected field order is reversed to second field/first field";
        ldDecodeMetaData.setIsFirstFieldFirst(false);
    }

    // Intrafield only correction if required
    if (intraField) {
        qInfo() << "Using intra-field correction only";
    }

    // Overcorrection if required
    if (overCorrect) {
        qInfo() << "Using over correction mode";
    }

    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    qDebug() << "DropOutDetector::process(): Input source is" << videoParameters.fieldWidth << "x" << videoParameters.fieldHeight <<
                "input filename" << inputFilename << "output filename" << outputFilename;

    // Open the source video
    qInfo() << "Opening source and target video files...";
    if (!sourceVideo.open(inputFilename, videoParameters.fieldWidth * videoParameters.fieldHeight)) {
        // Could not open source video file
        qInfo() << "Unable to open ld-decode video file";
        return false;
    }

    // Open the target video
    targetVideo.setFileName(outputFilename);
    if (!targetVideo.open(QIODevice::WriteOnly)) {
            // Could not open target video file
            qInfo() << "Unable to open output video file";
            sourceVideo.close();
            return false;
    }

    // Check TBC and JSON field numbers match
    qInfo() << "Verifying metadata (number of available fields)...";
    if (sourceVideo.getNumberOfAvailableFields() != ldDecodeMetaData.getNumberOfFields()) {
        qInfo() << "Warning: TBC file contains" << sourceVideo.getNumberOfAvailableFields() <<
                   "fields but the JSON indicates" << ldDecodeMetaData.getNumberOfFields() <<
                   "fields - some fields will be ignored";
    }

    // If there is a leading field in the TBC which is out of field order, we need to copy it
    // to ensure the JSON metadata files match up
    qInfo() << "Verifying leading fields match...";
    qint32 firstFieldNumber = ldDecodeMetaData.getFirstFieldNumber(1);
    qint32 secondFieldNumber = ldDecodeMetaData.getSecondFieldNumber(1);

    if (firstFieldNumber != 1 && secondFieldNumber != 1) {
        QByteArray sourceField;
        sourceField = sourceVideo.getVideoField(1);
        if (!targetVideo.write(sourceField, sourceField.size())) {
            // Could not write to target TBC file
            qInfo() << "Writing first field to the output TBC file failed";
            targetVideo.close();
            sourceVideo.close();
            return false;
        }
    }

    // Show some information for the user
    qInfo() << "Using" << maxThreads << "threads to process" << ldDecodeMetaData.getNumberOfFrames() << "frames";

    // Initialise processing state
    inputFrameNumber = 1;
    outputFrameNumber = 1;
    lastFrameNumber = ldDecodeMetaData.getNumberOfFrames();
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
        sourceVideo.close();
        targetVideo.close();
        return false;
    }

    // Show the processing speed to the user
    qreal totalSecs = (static_cast<qreal>(totalTimer.elapsed()) / 1000.0);
    qInfo() << "Dropout correction complete -" << lastFrameNumber << "frames in" << totalSecs << "seconds (" <<
               lastFrameNumber / totalSecs << "FPS )";

    qInfo() << "Creating JSON metadata file for drop-out corrected TBC";
    ldDecodeMetaData.write(outputFilename + ".json");

    qInfo() << "Processing complete";

    // Close the source and target video
    sourceVideo.close();
    targetVideo.close();

    return true;
}

// Get the next frame that needs processing from the input.
//
// Returns true if a frame was returned, false if the end of the input has been
// reached.
bool CorrectorPool::getInputFrame(qint32& frameNumber,
                                  qint32& firstFieldNumber, QByteArray& firstFieldVideoData, LdDecodeMetaData::Field& firstFieldMetadata,
                                  qint32& secondFieldNumber, QByteArray& secondFieldVideoData, LdDecodeMetaData::Field& secondFieldMetadata,
                                  LdDecodeMetaData::VideoParameters& videoParameters,
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

    // Determine the fields for the input frame
    firstFieldNumber = ldDecodeMetaData.getFirstFieldNumber(frameNumber);
    secondFieldNumber = ldDecodeMetaData.getSecondFieldNumber(frameNumber);

    // Fetch the input data (get the fields in TBC sequence order to save seeking)
    if (firstFieldNumber < secondFieldNumber) {
        firstFieldVideoData = sourceVideo.getVideoField(firstFieldNumber);
        secondFieldVideoData = sourceVideo.getVideoField(secondFieldNumber);
    } else {
        secondFieldVideoData = sourceVideo.getVideoField(secondFieldNumber);
        firstFieldVideoData = sourceVideo.getVideoField(firstFieldNumber);
    }

    firstFieldMetadata = ldDecodeMetaData.getField(firstFieldNumber);
    secondFieldMetadata = ldDecodeMetaData.getField(secondFieldNumber);
    videoParameters = ldDecodeMetaData.getVideoParameters();

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
            sourceVideo.close();
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
