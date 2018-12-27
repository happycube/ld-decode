/************************************************************************

    dropoutdetector.cpp

    ld-dropout-detect - Dropout detection for ld-decode
    Copyright (C) 2018 Simon Inns

    This file is part of ld-decode-tools.

    ld-dropout-detect is free software: you can redistribute it and/or
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

#include "dropoutdetector.h"

DropOutDetector::DropOutDetector(QObject *parent) : QObject(parent)
{
    // Set-up drop out corrections defaults:

    // The postTriggerWidth is the number of 'non dropout' pixels required after
    // a drop-out has been detected before the detector considers the dropout
    // to be finished.  Note: the pre-trigger width is always 1.
    docConfiguration.postTriggerWidth = 10;

    // The preTriggerReplacement is the number of pixels before a dropout is
    // detected that are also considered as part of the drop-out (drop-outs tend
    // to 'ramp-up' before they can be detected, so this covers the leading
    // pixels).
    docConfiguration.preTriggerReplacement = 16;

    // The postTriggerReplacement is the number of pixels after a dropout has
    // finished that are also considered as part of the drop-out (drop-outs tend
    // to 'ramp-down' after the last detected dropout, so this covers the
    // trailing pixels).
    docConfiguration.postTriggerReplacement = 10;
}

bool DropOutDetector::process(QString inputFileName)
{
    LdDecodeMetaData ldDecodeMetaData;
    SourceVideo sourceVideo;

    // Open the source video metadata
    if (!ldDecodeMetaData.read(inputFileName + ".json")) {
        qInfo() << "Unable to open ld-decode metadata file";
        return false;
    }

    LdDecodeMetaData::VideoParameters videoParameters = ldDecodeMetaData.getVideoParameters();

    qDebug() << "DropOutDetector::process(): Input source is" << videoParameters.fieldWidth << "x" << videoParameters.fieldHeight << "filename" << inputFileName;

    // Open the source video
    if (!sourceVideo.open(inputFileName, videoParameters.fieldWidth * videoParameters.fieldHeight)) {
        // Could not open source video file
        qInfo() << "Unable to open ld-decode video file";
        return false;
    }

    // Check TBC and JSON field numbers match
    if (sourceVideo.getNumberOfAvailableFields() != ldDecodeMetaData.getNumberOfFields()) {
        qInfo() << "Warning: TBC file contains" << sourceVideo.getNumberOfAvailableFields() <<
                   "fields but the JSON indicates" << ldDecodeMetaData.getNumberOfFields() <<
                   "fields - some fields will be ignored";
    }

    // Process the fields
    SourceField *sourceField;
    for (qint32 fieldNumber = 1; fieldNumber <= ldDecodeMetaData.getNumberOfFields(); fieldNumber++) {
        // Get the source frame
        sourceField = sourceVideo.getVideoField(fieldNumber);

        // Get the existing field data from the metadata
        qDebug() << "DropOutDetector::process(): Getting metadata for field" << fieldNumber;
        LdDecodeMetaData::Field field = ldDecodeMetaData.getField(fieldNumber);

        // Perform dropout detection on the field
        qDebug() << "DropOutDetector::process(): Performing drop-out detection for field" << fieldNumber;
        field.dropOuts = detectDropOuts(sourceField->getFieldData(), videoParameters);

        // Show the drop-out detection results
        for (qint32 index = 0; index < field.dropOuts.startx.size(); index++) {
            qDebug() << "DropOutDetector::process(): Field [" << fieldNumber << "] - Found drop out" << index <<
                        "on field line =" << field.dropOuts.fieldLine[index] + 1 <<
                        "startx =" << field.dropOuts.startx[index] << "endx =" << field.dropOuts.endx[index];
        }

        // Show an update to the user
        if (field.dropOuts.startx.size() != 1) qInfo() << "Field #" << fieldNumber << "processed -" << field.dropOuts.startx.size() << "dropouts detected";
        else qInfo() << "Field #" << fieldNumber << "processed -" << field.dropOuts.startx.size() << "dropout detected";

        // Update the dropout metadata for the frame
        ldDecodeMetaData.updateField(field, fieldNumber);
        qDebug() << "DropOutDetector::process(): Updating metadata for field" << fieldNumber;
    }

    // Write the metadata file
    QString outputFileName = inputFileName + ".json";
    ldDecodeMetaData.write(outputFileName);
    qInfo() << "Processing complete";

    // Close the source video
    sourceVideo.close();

    return true;
}

// Private method to detect drop-outs and build a drop out list
LdDecodeMetaData::DropOuts DropOutDetector::detectDropOuts(QByteArray sourceFieldData, LdDecodeMetaData::VideoParameters videoParameters)
{
    LdDecodeMetaData::DropOuts dropOuts;

    qint32 doStart = 0;
    bool dropout = false;
    bool dropoutInProgress = false;

    // Determine the first and last active field line based on the source format
    qint32 firstActiveFieldLine;
    qint32 lastActiveFieldLine;
    if (videoParameters.isSourcePal) {
        firstActiveFieldLine = 22;
        lastActiveFieldLine = 308;
    } else {
        firstActiveFieldLine = 20;
        lastActiveFieldLine = 259;
    }

    qint32 postTriggerCount = 0;
    for (qint32 y = firstActiveFieldLine; y < lastActiveFieldLine; y++) {
        // Extract the current field line data from the field
        qint32 startPointer = (y - 1) * videoParameters.fieldWidth * 2;
        qint32 length = videoParameters.fieldWidth * 2;
        QByteArray fieldLineData = sourceFieldData.mid(startPointer, length);

        for (qint32 x = videoParameters.colourBurstStart; x <= videoParameters.activeVideoEnd; x++) {
            qint32 dp = x * 2;
            qint32 pixelValue = (static_cast<uchar>(fieldLineData[dp + 1]) * 256) + static_cast<uchar>(fieldLineData[dp]);

            // Examine the current pixel
            if (pixelValue == 0 || pixelValue >= 65535) dropout = true; else dropout = false;

            // Ensure we don't exceed the end of the field line
            if (x >= videoParameters.activeVideoEnd - 1 && (dropoutInProgress || dropout)) {
                dropout = false;
                postTriggerCount = docConfiguration.postTriggerWidth + 1;
            }

            if (dropout && !dropoutInProgress) {
                // A new dropout has been detected
                dropoutInProgress = true;
                postTriggerCount = 0;
                doStart = x;
            } else if (dropout && dropoutInProgress) {
                // A dropout is continuing
                postTriggerCount = 0;
            } else if (!dropout & dropoutInProgress) {
                // A dropout is in progress, but this pixel is ok
                postTriggerCount++;

                // Reached post trigger tolerance or end of line?
                if (postTriggerCount > docConfiguration.postTriggerWidth) {
                    // Drop out has stopped
                    dropoutInProgress = false;
                    postTriggerCount = 0;

                    // Add the pre- and post-pixels to the detected drop-out
                    qint32 startx = doStart - docConfiguration.preTriggerReplacement;
                    if (startx < 0) startx = 0;
                    qint32 endx = x - 1 + docConfiguration.postTriggerReplacement;
                    if (endx >= videoParameters.activeVideoEnd) endx = videoParameters.activeVideoEnd;

                    // Append a drop out entry
                    dropOuts.startx.append(startx);
                    dropOuts.endx.append(endx);
                    dropOuts.fieldLine.append(y);
                }
            } else if (!dropout & !dropoutInProgress) {
                // No dropout in progress and this pixel is ok
            }
        }
    }

    return dropOuts;
}
