/************************************************************************

    processcav.cpp

    ld-process-cav - CAV disc processing for ld-decode
    Copyright (C) 2018 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-cav is free software: you can redistribute it and/or
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

#include "processcav.h"

ProcessCav::ProcessCav(QObject *parent) : QObject(parent)
{

}

bool ProcessCav::process(QString inputFileName)
{
    LdDecodeMetaData ldDecodeMetaData;
    SourceVideo sourceVideo;

    // Open the source video metadata
    if (!ldDecodeMetaData.read(inputFileName + ".json")) {
        qInfo() << "Unable to open ld-decode metadata file";
        return false;
    }

    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    qDebug() << "ProcessCav::process(): Input source is" << videoParameters.fieldWidth << "x" << videoParameters.fieldHeight << "filename" << inputFileName;

    // Open the source video
    if (!sourceVideo.open(inputFileName, videoParameters.fieldWidth * videoParameters.fieldHeight)) {
        // Could not open source video file
        qInfo() << "Unable to open ld-decode video file";
        return false;
    }

    // Read the available frames into an array read for sorting
    QVector<frame> availableFrames;

    qint32 framesToProcess = ldDecodeMetaData.getNumberOfFrames();

    // There must be at least 2 frames to process in the input TBC
    if (framesToProcess < 2) {
        qInfo() << "The source TBC contains less than 2 frames... Cannot process!";
        return false;
    }

    for (qint32 seqNumber = 1; seqNumber <= framesToProcess; seqNumber++) {
        frame tempFrame;

        // Get the first and second field numbers for the frame
        tempFrame.firstField = ldDecodeMetaData.getFirstFieldNumber(seqNumber);
        tempFrame.secondField = ldDecodeMetaData.getSecondFieldNumber(seqNumber);

        // Determine the field number from the VBI
        LdDecodeMetaData::Field firstFieldData = ldDecodeMetaData.getField(tempFrame.firstField);
        LdDecodeMetaData::Field secondFieldData = ldDecodeMetaData.getField(tempFrame.secondField);

        if (firstFieldData.vbi.inUse && firstFieldData.vbi.picNo != -1) {
            // Got frame number from the first field
            tempFrame.frameNumber = ldDecodeMetaData.getField(tempFrame.firstField).vbi.picNo;
        } else if (secondFieldData.vbi.inUse && secondFieldData.vbi.picNo != -1) {
            // Got frame number from the second field
            tempFrame.frameNumber = ldDecodeMetaData.getField(tempFrame.secondField).vbi.picNo;
        } else {
            // No frame number was found...
            tempFrame.frameNumber = -1;
        }

        if (tempFrame.frameNumber == -1) {
            qWarning() << "Sequential frame" << seqNumber << "[" << tempFrame.firstField << "/" << tempFrame.secondField << "] Has no VBI picture number";
            // Attempt a guess at the frame number based on the adjacent frames?
        } else {
            // Append the record to our array
            availableFrames.append(tempFrame);
        }
    }

    qInfo() << availableFrames.size() << "frames found with VBI frame numbers of" << framesToProcess << "available in input TBC file";

    // Sort the frames into numerical order according to the VBI frame number
    qInfo() << "Sorting the available frames into numerical order...";
    std::sort(availableFrames.begin(), availableFrames.end(), [](const frame& a, const frame& b) { return a.frameNumber < b.frameNumber; });

    // Remove duplicate frames
    qInfo() << "Removing duplicate frames...";
    qint32 removedFrames = 0;
    qint32 seqNumber = 0;
    qint32 currentFrameNumber = availableFrames[seqNumber].frameNumber;
    seqNumber++;

    while (seqNumber < availableFrames.size()) {
        if (availableFrames[seqNumber].frameNumber == currentFrameNumber) {
            // Duplicate... remove it
            // Note: once drop-out detection is implemented, this should probably make
            // a smart decision about which frame to keep...
            availableFrames.remove(seqNumber);
            removedFrames++;
        } else {
            currentFrameNumber = availableFrames[seqNumber].frameNumber;
            seqNumber++;
        }
    }
    qInfo() << "Removed" << removedFrames << "duplicate frames";

    // Check frames for continuity
    currentFrameNumber = availableFrames[0].frameNumber;
    for (qint32 seqNumber = 1; seqNumber < availableFrames.size(); seqNumber++) {
        if (availableFrames[seqNumber].frameNumber != currentFrameNumber + 1) {
            qint32 missingFrames = (availableFrames[seqNumber].frameNumber - currentFrameNumber) - 1;
            qInfo() << missingFrames << "frames missing between" << currentFrameNumber << "and" << availableFrames[seqNumber].frameNumber;
        }

        currentFrameNumber = availableFrames[seqNumber].frameNumber;
    }

//    qInfo() << "Final list:";
//    for (qint32 seqNumber = 0; seqNumber < availableFrames.size(); seqNumber++) {
//        qDebug() << "[" << seqNumber << "] = Frame number" << availableFrames[seqNumber].frameNumber;
//    }


    // Write the metadata file
//    QString outputFileName = inputFileName + ".json";
//    ldDecodeMetaData.write(outputFileName);
//    qInfo() << "Processing complete";

    // Close the source video
    sourceVideo.close();

    return true;
}
