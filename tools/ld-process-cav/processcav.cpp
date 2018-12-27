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

bool ProcessCav::process(QString inputFileName, QString outputFileName, qint32 firstFrameNumber)
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

    // Get the first frame number
    if (firstFrameNumber == -1) {
        // Get the first and second field numbers for the frame
        qint32 firstField = ldDecodeMetaData.getFirstFieldNumber(1);
        qint32 secondField = ldDecodeMetaData.getSecondFieldNumber(1);

        // Determine the field number from the VBI
        LdDecodeMetaData::Field firstFieldData = ldDecodeMetaData.getField(firstField);
        LdDecodeMetaData::Field secondFieldData = ldDecodeMetaData.getField(secondField);

        if (firstFieldData.vbi.inUse && firstFieldData.vbi.picNo != -1) {
            // Got frame number from the first field
            firstFrameNumber = ldDecodeMetaData.getField(firstField).vbi.picNo;
        } else if (secondFieldData.vbi.inUse && secondFieldData.vbi.picNo != -1) {
            // Got frame number from the second field
            firstFrameNumber = ldDecodeMetaData.getField(secondField).vbi.picNo;
        } else {
            // No frame number was found...
            qInfo() << "Unable to get initial frame number - please specify one and try again";
            return false;
        }
        qInfo() << "Guessed first frame number of" << firstFrameNumber;
    }

    // Read in all of the available frame numbers
    qInfo() << "Checking available frames for valid frame numbers:";
    for (qint32 seqNumber = 1; seqNumber <= framesToProcess; seqNumber++) {
        frame tempFrame;

        // Store the original sequential frame number (needed to look up the frame in
        // the ld-analyse application)
        tempFrame.seqFrameNumber = seqNumber;

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
            // No frame number was found... Give it a dummy frame number
            tempFrame.frameNumber = 123456;
        }

        if (tempFrame.frameNumber == 123456) {
            qInfo() << "Sequential frame" << seqNumber << "[" << tempFrame.firstField << "/" << tempFrame.secondField << "] Has no VBI picture number";
        }

        if (tempFrame.frameNumber != 123456) {
            // Range check the frame number to see if the number is valid (will only catch
            // corrupt VBI outside of normal frame range...)
            if (tempFrame.frameNumber < firstFrameNumber || tempFrame.frameNumber > 60000) {
                qInfo() << "Sequential frame" << seqNumber << "[" << tempFrame.firstField << "/" << tempFrame.secondField << "] Has a corrupt VBI picture number of " << tempFrame.frameNumber;
                tempFrame.frameNumber = 123456;
            }
        }

        // Check for a picture stop-code
        if (firstFieldData.vbi.picStop || secondFieldData.vbi.picStop) {
            qInfo() << "Found stop code in sequential frame" << seqNumber;
            tempFrame.stopCode = true;
        } else tempFrame.stopCode = false;

        // Append the record to our array (regardless of if we could get a frame number)
        tempFrame.fakeFrame = false;
        availableFrames.append(tempFrame);
    }

    // Look for frame repetition caused by stop-codes during capture
    qInfo() << "Looking for duplicate frames caused by stop-codes:";
    qint32 seqNumber = 0;
    while (seqNumber < availableFrames.size() - 1) {
        if (availableFrames[seqNumber].stopCode) {
            // Current frame has a stop-code remove any repeating frames that follow it
            while (availableFrames[seqNumber + 1].frameNumber == availableFrames[seqNumber].frameNumber &&
                   availableFrames[seqNumber + 1].stopCode) {
                qInfo() << "Removing stop-code repeated frame" << availableFrames[seqNumber].frameNumber << "[" << availableFrames[seqNumber + 1].seqFrameNumber << "]";
                availableFrames.remove(seqNumber + 1);
            }
        }

        seqNumber++;
    }

    // Check for any frames that are out of sequence (or have missing frame numbers) and try to guess the
    // frame number based on the adjacent frames
    // Note: Will not work correctly for NTSC will pull down (as the pull down frames have no frame number)
    qInfo() << "Checking for frame numbers that are out of sequence:";
    for (qint32 seqNumber = 1; seqNumber < availableFrames.size() - 1; seqNumber++) {

        // Try up to a distance of 5 frames to find the sequence
        for (qint32 gap = 1; gap < 5; gap++) {
            if (availableFrames[seqNumber].frameNumber != (availableFrames[seqNumber - 1].frameNumber + 1)) {
                if (availableFrames[seqNumber - 1].frameNumber == (availableFrames[seqNumber + gap].frameNumber - (gap + 1))) {
                    availableFrames[seqNumber].frameNumber = availableFrames[seqNumber - 1].frameNumber + 1;
                    qInfo() << "Sequential frame" << availableFrames[seqNumber].seqFrameNumber << "[" << availableFrames[seqNumber].firstField << "/" << availableFrames[seqNumber].secondField << "]" <<
                                  "out of sequence - corrected picture number to" << availableFrames[seqNumber].frameNumber << "( gap was" << gap << ")";
                    break; // done
                }
            }
        }
    }

    qInfo() << "Counting frames that could not be processed:";
    qint32 unprocessedFrames = 0;
    for (qint32 seqNumber = 0; seqNumber < availableFrames.size(); seqNumber++) {
        if (availableFrames[seqNumber].frameNumber == 123456) {
            qDebug() << "[" << availableFrames[seqNumber].seqFrameNumber << "] is still unknown";
        }
    }
    if (unprocessedFrames == 0) qInfo() << "All frames were processed";
    else qInfo() << unprocessedFrames << "frames were not processed";

    // Sort the frames into numerical order according to the VBI frame number
    qInfo() << "Sorting the available frames into numerical order:";
    std::sort(availableFrames.begin(), availableFrames.end(), [](const frame& a, const frame& b) { return a.frameNumber < b.frameNumber; });

    // Check for duplicate frames
    qInfo() << "Checking for (and removing) duplicate frames:";
    seqNumber = 0;
    while (seqNumber < availableFrames.size() - 1) {
        while (availableFrames[seqNumber + 1].frameNumber == availableFrames[seqNumber].frameNumber) {
            qInfo() << "Removing duplicate frame" << availableFrames[seqNumber].frameNumber << "[" << availableFrames[seqNumber + 1].seqFrameNumber << "]";
            availableFrames.remove(seqNumber + 1);
        }

        seqNumber++;
    }

    // Check final sorted frames for continuity
    qInfo() << "Checking the sorted frames for continuity and adding in blank filler frames:";
    qint32 currentFrameNumber = availableFrames[0].frameNumber;
    for (qint32 seqNumber = 1; seqNumber < availableFrames.size(); seqNumber++) {
        if (availableFrames[seqNumber].frameNumber != 123456 && !availableFrames[seqNumber].fakeFrame) {
            if (availableFrames[seqNumber].frameNumber != currentFrameNumber + 1) {
                qint32 missingFrames = (availableFrames[seqNumber].frameNumber - currentFrameNumber) - 1;
                if (missingFrames > 1) {
                    qInfo() << "Missing" << missingFrames << "frames - starting from" << currentFrameNumber + 1 << "[ should be after sequential frame" << availableFrames[seqNumber - 1].seqFrameNumber << "]";

                    // Add the missing frames
                    for (qint32 counter = 0; counter < missingFrames; counter++) {
                        frame tempFrame;
                        tempFrame.frameNumber = currentFrameNumber + 1 + counter;
                        tempFrame.firstField = -1;
                        tempFrame.secondField = -1;
                        tempFrame.seqFrameNumber = -1;
                        tempFrame.fakeFrame = true;
                        availableFrames.append(tempFrame);
                    }
                } else {
                    qInfo() << "Missing frame number" << currentFrameNumber + 1 << "[ should be after sequential frame" << availableFrames[seqNumber - 1].seqFrameNumber << "]";

                    // Add a blank frame
                    frame tempFrame;
                    tempFrame.frameNumber = currentFrameNumber + 1;
                    tempFrame.firstField = -1;
                    tempFrame.secondField = -1;
                    tempFrame.seqFrameNumber = -1;
                    tempFrame.fakeFrame = true;
                    availableFrames.append(tempFrame);
                }
            }

            currentFrameNumber = availableFrames[seqNumber].frameNumber;
        }
    }

    // Sort the resulting frames into numerical order according to the VBI frame number
    qInfo() << "Sorting the final frames into numerical order:";
    std::sort(availableFrames.begin(), availableFrames.end(), [](const frame& a, const frame& b) { return a.frameNumber < b.frameNumber; });

    qInfo() << "Results:";
    qInfo() << "First frame number =" << availableFrames[0].frameNumber;
    qInfo() << "Last frame number =" << availableFrames[availableFrames.size() - 1].frameNumber;
    qInfo() << "Total number of frames =" << availableFrames.size();

    if (outputFileName.isEmpty()) {
        qInfo() << "No output file name specified - All done";
        return true;
    }

//    // Generate JSON metadata file
//    LdDecodeMetaData outputMetadata;

//    // Copy all the non-frame related data from the original metadata
//    LdDecodeMetaData::VideoParameters existingVideoParameters = ldDecodeMetaData.getVideoParameters();
//    existingVideoParameters.numberOfSequentialFields = availableFrames.size() * 2;
//    outputMetadata.setVideoParameters(existingVideoParameters);
//    outputMetadata.setPcmAudioParameters(ldDecodeMetaData.getPcmAudioParameters());

//    // Now add the fields to the metadata
//    for (qint32 counter = 0; counter < availableFrames.size(); counter ++) {
//        LdDecodeMetaData::Field firstField;
//        LdDecodeMetaData::Field secondField;


//    }

    // Write the metadata file
//    QString outputFileName = inputFileName + ".json";
//    ldDecodeMetaData.write(outputFileName);
//    qInfo() << "Processing complete";

    // Close the source video
    sourceVideo.close();

    return true;
}
