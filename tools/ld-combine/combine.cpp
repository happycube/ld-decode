/************************************************************************

    combine.cpp

    ld-combine - Combine TBC files
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-combine is free software: you can redistribute it and/or
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

#include "combine.h"

Combine::Combine(QObject *parent) : QObject(parent)
{

}

bool Combine::process(QString primaryFilename, QString secondaryFilename, QString outputFilename, bool reverse)
{
    linesReplaced = 0;
    dropoutsReplaced = 0;
    failedReplaced = 0;

    // Open the primary source video metadata
    if (!primaryLdDecodeMetaData.read(primaryFilename + ".json")) {
        qInfo() << "Unable to open ld-decode metadata file for the primary input file";
        return false;
    }

    // Open the secondary source video metadata
    if (!secondaryLdDecodeMetaData.read(secondaryFilename + ".json")) {
        qInfo() << "Unable to open ld-decode metadata file for the secondary input file";
        return false;
    }

    // Make a copy of the primary source metadata to use as the output metadata
    if (!outputLdDecodeMetaData.read(primaryFilename + ".json")) {
        qInfo() << "Unable to open ld-decode metadata file for the output file";
        return false;
    }

    // Reverse field order if required
    if (reverse) {
        qInfo() << "Expected field order is reversed to second field/first field";
        primaryLdDecodeMetaData.setIsFirstFieldFirst(false);
        secondaryLdDecodeMetaData.setIsFirstFieldFirst(false);
    }

    primaryVideoParameters = primaryLdDecodeMetaData.getVideoParameters();
    secondaryVideoParameters = secondaryLdDecodeMetaData.getVideoParameters();
    qDebug() << "DropOutDetector::process(): Primary input source is" << primaryVideoParameters.fieldWidth << "x"
             << primaryVideoParameters.fieldHeight << "filename" << primaryFilename;
    qDebug() << "DropOutDetector::process(): Secondary input source is" << secondaryVideoParameters.fieldWidth << "x"
             << secondaryVideoParameters.fieldHeight << "filename" << secondaryFilename;

    // Confirm both sources are the same video standard
    if (primaryVideoParameters.isSourcePal != secondaryVideoParameters.isSourcePal) {
        // Primary and secondard input video standards do not match
        qInfo() << "Primary and secondard input files must both be PAL or NTSC, not a combination";
        return false;
    }

    // Open the primary source video
    if (!primarySourceVideo.open(primaryFilename, primaryVideoParameters.fieldWidth * primaryVideoParameters.fieldHeight)) {
        // Could not open source video file
        qInfo() << "Unable to open primary ld-decode video file";
        return false;
    }

    // Open the secondary source video
    if (!secondarySourceVideo.open(secondaryFilename, secondaryVideoParameters.fieldWidth * secondaryVideoParameters.fieldHeight)) {
        // Could not open source video file
        qInfo() << "Unable to open secondary ld-decode video file";
        return false;
    }

    // Open the target video
    QFile targetVideo(outputFilename);
    if (!targetVideo.open(QIODevice::WriteOnly)) {
            // Could not open target video file
            qInfo() << "Unable to open output video file";
            primarySourceVideo.close();
            secondarySourceVideo.close();
            return false;
    }

    // Check TBC and JSON field numbers match
    if (primarySourceVideo.getNumberOfAvailableFields() != primaryLdDecodeMetaData.getNumberOfFields()) {
        qInfo() << "Warning: Primary TBC file contains" << primarySourceVideo.getNumberOfAvailableFields() <<
                   "fields but the JSON indicates" << primaryLdDecodeMetaData.getNumberOfFields() <<
                   "fields - some fields will be ignored";
    }

    if (secondarySourceVideo.getNumberOfAvailableFields() != secondaryLdDecodeMetaData.getNumberOfFields()) {
        qInfo() << "Warning: Secondary TBC file contains" << secondarySourceVideo.getNumberOfAvailableFields() <<
                   "fields but the JSON indicates" << secondaryLdDecodeMetaData.getNumberOfFields() <<
                   "fields - some fields will be ignored";
    }

    // If there is a leading field in the primary TBC which is out of field order, we need to copy it
    // to ensure the JSON metadata files match up
    qint32 firstFieldNumber = primaryLdDecodeMetaData.getFirstFieldNumber(1);
    qint32 secondFieldNumber = primaryLdDecodeMetaData.getSecondFieldNumber(1);

    if (firstFieldNumber != 1 && secondFieldNumber != 1) {
        SourceField *sourceField;
        sourceField = primarySourceVideo.getVideoField(1);
        if (!targetVideo.write(sourceField->getFieldData(), sourceField->getFieldData().size())) {
            // Could not write to target TBC file
            qInfo() << "Writing first field to the output TBC file failed";
            targetVideo.close();
            primarySourceVideo.close();
            secondarySourceVideo.close();
            return false;
        }
        qInfo() << "Extra field at start of primary TBC - written field #1";
    }

    // Check the primary source disc type
    LdDecodeMetaData::VbiDiscTypes primaryDiscType = primaryLdDecodeMetaData.getDiscTypeFromVbi();
    if (primaryDiscType == LdDecodeMetaData::VbiDiscTypes::cav) {
        qInfo() << "Primary source disc type is CAV";
    } else if (primaryDiscType == LdDecodeMetaData::VbiDiscTypes::clv) {
        qInfo() << "Primary source disc type is CLV";
    } else {
        qCritical() << "Cannot determine if the primary source disc type is CAV or CLV!";
        return false;
    }

    // Check the secondary source disc type
    LdDecodeMetaData::VbiDiscTypes secondaryDiscType = secondaryLdDecodeMetaData.getDiscTypeFromVbi();
    if (secondaryDiscType == LdDecodeMetaData::VbiDiscTypes::cav) {
        qInfo() << "Secondary source disc type is CAV";
    } else if (secondaryDiscType == LdDecodeMetaData::VbiDiscTypes::clv) {
        qInfo() << "Secondary source disc type is CLV";
    } else {
        qCritical() << "Cannot determine if the secondary source disc type is CAV or CLV!";
        return false;
    }

    // Check the primary and secondary source disc types match
    if (primaryDiscType != secondaryDiscType) {
        qCritical() << "The disc type of the primary and secondary sources must be the same!";
        return false;
    }

    // Set the disc type for processing
    bool isDiscCav;
    if (primaryDiscType == LdDecodeMetaData::VbiDiscTypes::cav) isDiscCav = true; else isDiscCav = false;

    // Scan for lead-in frames in the primary and secondary sources (as there may be preceeding duplicate frames)
    qint32 primaryLeadinOffset = 0;
    qint32 secondardLeadinOffset = 0;

    qint32 endFrame = primaryLdDecodeMetaData.getNumberOfFrames();
    if (endFrame > 100) endFrame = 100; // Limit lead-in search to 100 frames
    for (qint32 primarySeqFrameNumber = 1; primarySeqFrameNumber <= endFrame; primarySeqFrameNumber++) {
        // Get the sequential field numbers for the primary source frame
        qint32 primaryFirstField = primaryLdDecodeMetaData.getFirstFieldNumber(primarySeqFrameNumber);
        qint32 primarySecondField = primaryLdDecodeMetaData.getSecondFieldNumber(primarySeqFrameNumber);

        if (primaryLdDecodeMetaData.getField(primaryFirstField).vbi.leadIn || primaryLdDecodeMetaData.getField(primarySecondField).vbi.leadIn)
            primaryLeadinOffset = primarySeqFrameNumber;
    }
    primaryLeadinOffset++; // Move to the next frame to correct offset

    endFrame = secondaryLdDecodeMetaData.getNumberOfFrames();
    if (endFrame > 100) endFrame = 100; // Limit lead-in search to 100 frames
    for (qint32 secondarySeqFrameNumber = 1; secondarySeqFrameNumber <= endFrame; secondarySeqFrameNumber++) {
        // Get the sequential field numbers for the primary source frame
        qint32 secondaryFirstField = secondaryLdDecodeMetaData.getFirstFieldNumber(secondarySeqFrameNumber);
        qint32 secondarySecondField = secondaryLdDecodeMetaData.getSecondFieldNumber(secondarySeqFrameNumber);

        if (secondaryLdDecodeMetaData.getField(secondaryFirstField).vbi.leadIn || secondaryLdDecodeMetaData.getField(secondarySecondField).vbi.leadIn)
            secondardLeadinOffset = secondarySeqFrameNumber;
    }
    secondardLeadinOffset++; // Move to the next frame to correct offset

    // Was a lead-in offset applied?
    if (primaryLeadinOffset != 1) {
        qInfo() << "Primary source contained lead-in frames, offsetting to frame" << primaryLeadinOffset;
    }
    if (secondardLeadinOffset != 1) {
        qInfo() << "Secondary source contained lead-in frames, offsetting to frame" << secondardLeadinOffset;
    }

    // Main combination process starts here
    QByteArray firstFieldData;
    QByteArray secondFieldData;
    for (qint32 primarySeqFrameNumber = primaryLeadinOffset; primarySeqFrameNumber <= primaryLdDecodeMetaData.getNumberOfFrames(); primarySeqFrameNumber++) {
        qint32 secondarySeqFrameNumber = getMatchingSecondaryFrame(isDiscCav, primarySeqFrameNumber, secondardLeadinOffset);

        // Get the sequential field numbers for the primary source frame
        qint32 primaryFirstField = primaryLdDecodeMetaData.getFirstFieldNumber(primarySeqFrameNumber);
        qint32 primarySecondField = primaryLdDecodeMetaData.getSecondFieldNumber(primarySeqFrameNumber);

        if (secondarySeqFrameNumber != -1) {
            // Found a match
            qDebug() << "Combine::process(): Primary sequential frame" << primarySeqFrameNumber << "matches secondary sequential frame" << secondarySeqFrameNumber;

            // Get the sequential field numbers for the secondary source frame
            qint32 secondaryFirstField = secondaryLdDecodeMetaData.getFirstFieldNumber(secondarySeqFrameNumber);
            qint32 secondarySecondField = secondaryLdDecodeMetaData.getSecondFieldNumber(secondarySeqFrameNumber);

            // Process the frame's field pair
            firstFieldData = processField(primaryFirstField, secondaryFirstField);
            secondFieldData = processField(primarySecondField, secondarySecondField);
        } else {
            // No matching frame found
            qDebug() << "Combine::process(): Frame" << primarySeqFrameNumber << "no matching frame found";

            // Just copy over the data from the primary source
            firstFieldData = primarySourceVideo.getVideoField(primaryLdDecodeMetaData.getFirstFieldNumber(primarySeqFrameNumber))->getFieldData();
            secondFieldData = primarySourceVideo.getVideoField(primaryLdDecodeMetaData.getSecondFieldNumber(primarySeqFrameNumber))->getFieldData();
        }

        // Write the output data to the output tbc file
        bool writeFail = false;
        if (firstFieldNumber < secondFieldNumber) {
            // Save the first field and then second field to the output file
            if (!targetVideo.write(firstFieldData.data(), firstFieldData.size())) writeFail = true;
            if (!targetVideo.write(secondFieldData.data(), secondFieldData.size())) writeFail = true;
        } else {
            // Save the second field and then first field to the output file
            if (!targetVideo.write(secondFieldData.data(), secondFieldData.size())) writeFail = true;
            if (!targetVideo.write(firstFieldData.data(), firstFieldData.size())) writeFail = true;
        }

        // Was the write successful?
        if (writeFail) {
            // Could not write to target TBC file
            qInfo() << "Writing fields to the output TBC file failed";
            targetVideo.close();
            primarySourceVideo.close();
            secondarySourceVideo.close();
            return false;
        }

        // Show an update to the user
        qInfo() << "Frame #" << primarySeqFrameNumber << "[" << primaryFirstField << "/" << primarySecondField << "] processed.";
    }

    qInfo() << "Creating JSON metadata file for output TBC";
    outputLdDecodeMetaData.write(outputFilename + ".json");

    qInfo() << "Processing complete - Replaced" << dropoutsReplaced << "dropouts and missed" << failedReplaced << "dropouts due to no suitable replacement";

    // Close the source videos
    primarySourceVideo.close();
    secondarySourceVideo.close();

    // Close the target video
    targetVideo.close();

    return true;
}

// Method to work out the required field offset (for the secondary source) in order to match
// the fields in the primary source
qint32 Combine::getMatchingSecondaryFrame(bool isDiscCav, qint32 seqFrameNumber, qint32 leadinOffset)
{
    qint32 matchingSeqFrameNumber = -1;

    // Get the VBI frame number for the sequential frame
    qint32 primaryVbiFrameNumber;
    if (isDiscCav) primaryVbiFrameNumber = getCavFrameNumber(seqFrameNumber, &primaryLdDecodeMetaData);
    else primaryVbiFrameNumber = getClvFrameNumber(seqFrameNumber, &primaryLdDecodeMetaData);

    if (primaryVbiFrameNumber == -1) {
        // Could not get a VBI frame number for the primary sequential frame
        return -1;
    }

    // Now we search the secondary source looking for a matching VBI frame number
    for (qint32 secondarySeqFrameNumber = leadinOffset; secondarySeqFrameNumber <= secondaryLdDecodeMetaData.getNumberOfFrames(); secondarySeqFrameNumber++) {
        qint32 secondaryVbiFrameNumber;
        if (isDiscCav) secondaryVbiFrameNumber = getCavFrameNumber(secondarySeqFrameNumber, &secondaryLdDecodeMetaData);
        else secondaryVbiFrameNumber = getClvFrameNumber(secondarySeqFrameNumber, &secondaryLdDecodeMetaData);

        // Match?
        if (secondaryVbiFrameNumber == primaryVbiFrameNumber) {
            // Match found
            matchingSeqFrameNumber = secondarySeqFrameNumber;
            break;
        }
    }

    return matchingSeqFrameNumber;
}

// Method to get the VBI frame number based on the sequential frame number (of the .tbc file)
qint32 Combine::getCavFrameNumber(qint32 frameSeqNumber, LdDecodeMetaData *ldDecodeMetaData)
{
    // Get the first and second field numbers for the frame
    qint32 firstField = ldDecodeMetaData->getFirstFieldNumber(frameSeqNumber);
    qint32 secondField = ldDecodeMetaData->getSecondFieldNumber(frameSeqNumber);

    // Determine the field number from the VBI
    LdDecodeMetaData::Field firstFieldData = ldDecodeMetaData->getField(firstField);
    LdDecodeMetaData::Field secondFieldData = ldDecodeMetaData->getField(secondField);

    qint32 frameNumber = -1;
    if (firstFieldData.vbi.inUse && firstFieldData.vbi.picNo != -1) {
        // Got frame number from the first field
        frameNumber = ldDecodeMetaData->getField(firstField).vbi.picNo;
    } else if (secondFieldData.vbi.inUse && secondFieldData.vbi.picNo != -1) {
        // Got frame number from the second field
        frameNumber = ldDecodeMetaData->getField(secondField).vbi.picNo;
    } else {
        // Couldn't get a frame number for the sequential frame number
        frameNumber = -1;
    }

    return frameNumber;
}

// Method to convert a CLV time code into an equivalent frame number (to make
// processing the timecodes easier)
qint32 Combine::getClvFrameNumber(qint32 frameSeqNumber, LdDecodeMetaData *ldDecodeMetaData)
{
    // Get the first and second field numbers for the frame
    qint32 firstField = ldDecodeMetaData->getFirstFieldNumber(frameSeqNumber);
    qint32 secondField = ldDecodeMetaData->getSecondFieldNumber(frameSeqNumber);

    // Determine the field number from the VBI
    LdDecodeMetaData::Field firstFieldData = ldDecodeMetaData->getField(firstField);
    LdDecodeMetaData::Field secondFieldData = ldDecodeMetaData->getField(secondField);

    LdDecodeMetaData::ClvTimecode clvTimecode;
    clvTimecode.hours = 0;
    clvTimecode.minutes = 0;
    clvTimecode.seconds = 0;
    clvTimecode.pictureNumber = 0;

    if (firstFieldData.vbi.inUse && firstFieldData.vbi.clvHr != -1) {
        // Get CLV data from the first field
        clvTimecode.hours = ldDecodeMetaData->getField(firstField).vbi.clvHr;
        clvTimecode.minutes = ldDecodeMetaData->getField(firstField).vbi.clvMin;
        clvTimecode.seconds = ldDecodeMetaData->getField(firstField).vbi.clvSec;
        clvTimecode.pictureNumber = ldDecodeMetaData->getField(firstField).vbi.clvPicNo;
    } else if (secondFieldData.vbi.inUse && secondFieldData.vbi.clvHr != -1) {
        // Got CLV data from the second field
        clvTimecode.hours = ldDecodeMetaData->getField(secondField).vbi.clvHr;
        clvTimecode.minutes = ldDecodeMetaData->getField(secondField).vbi.clvMin;
        clvTimecode.seconds = ldDecodeMetaData->getField(secondField).vbi.clvSec;
        clvTimecode.pictureNumber = ldDecodeMetaData->getField(secondField).vbi.clvPicNo;
    } else {
        clvTimecode.hours = -1;
        clvTimecode.minutes = -1;
        clvTimecode.seconds = -1;
        clvTimecode.pictureNumber = -1;
    }

    // Calculate the frame number
    return ldDecodeMetaData->convertClvTimecodeToFrameNumber(clvTimecode);
}

// Method to process two matching fields line by line, replacing lines
// based on the quality of the line in the primary and secondary sources
// Returns the corrected field data
QByteArray Combine::processField(qint32 primarySeqFieldNumber, qint32 secondarySeqFieldNumber)
{
    // Read the primary and secondary source video data for the field
    QByteArray primaryFieldData = primarySourceVideo.getVideoField(primarySeqFieldNumber)->getFieldData();
    QByteArray secondaryFieldData = secondarySourceVideo.getVideoField(secondarySeqFieldNumber)->getFieldData();

    QByteArray outputField = primaryFieldData;

    // Process the field line-by-line
    for (qint32 lineNumber = 1; lineNumber <= primaryVideoParameters.fieldHeight; lineNumber++) {
        qint32 primaryLineQuality = assessLineQuality(primaryLdDecodeMetaData.getField(primarySeqFieldNumber), lineNumber);

        // Is the primary line damaged?
        if (primaryLineQuality != 0) {
                // Replace any primary line dropouts with secondary (provided the
                // secondary line doesn't have dropouts in the same place)

                // Look at the dropouts in the primary line and only replace if there is no dropout covering the
                // same position in the secondard line
                LdDecodeMetaData::Field secondaryField = secondaryLdDecodeMetaData.getField(secondarySeqFieldNumber);

                LdDecodeMetaData::Field outputFieldMetaData = outputLdDecodeMetaData.getField(primarySeqFieldNumber);
                qint32 doCounter = 0;
                while (doCounter < outputFieldMetaData.dropOuts.startx.size()) {
                    if (outputFieldMetaData.dropOuts.fieldLine[doCounter] == lineNumber) {
                        // Found a dropout in the primary with the current line number
                        // Check if the secondary line is dropout free for the required section
                        bool replace = true;
                        for (qint32 secDoCounter = 0; secDoCounter < secondaryField.dropOuts.startx.size(); secDoCounter++) {
                            // Look for any dropouts on the required line in the secondary source
                            if (secondaryField.dropOuts.fieldLine[secDoCounter] == lineNumber) {
                                if ((secondaryField.dropOuts.endx[secDoCounter] - outputFieldMetaData.dropOuts.startx[doCounter] >= 0) &&
                                        (outputFieldMetaData.dropOuts.endx[doCounter] - secondaryField.dropOuts.startx[secDoCounter] >= 0)) {
                                    // Overlap
                                    replace = false;
                                }
                            }
                        }

                        // Replace the dropout?
                        if (replace) {
                            qInfo() << "[Dropout] - [Field #" << primarySeqFieldNumber << "] - [Line #" << lineNumber << "] - start =" <<
                                        outputFieldMetaData.dropOuts.startx[doCounter] << "end =" << outputFieldMetaData.dropOuts.endx[doCounter];

                            // Replace the dropout data
                            outputField = replaceVideoDropoutData(outputField, secondaryFieldData, lineNumber,
                                                                  outputFieldMetaData.dropOuts.startx[doCounter], outputFieldMetaData.dropOuts.endx[doCounter]);

                            // Remove the primary line dropout data from the metadata
                            outputFieldMetaData.dropOuts.fieldLine.remove(doCounter);
                            outputFieldMetaData.dropOuts.startx.remove(doCounter);
                            outputFieldMetaData.dropOuts.endx.remove(doCounter);

                            // Update the field's metadata
                            outputLdDecodeMetaData.updateField(outputFieldMetaData, primarySeqFieldNumber);

                            dropoutsReplaced++;
                        } else {
                            qInfo() << "[Fail   ] - [Field #" << primarySeqFieldNumber << "] - [Line #" << lineNumber << "] - start =" <<
                                        outputFieldMetaData.dropOuts.startx[doCounter] << "end =" << outputFieldMetaData.dropOuts.endx[doCounter] <<
                                       " - No replacement available";
                            failedReplaced++;

                            // Next dropout
                            doCounter++;
                        }
                    } else doCounter++;
            }
        }
    }

    return outputField;
}

// Method to assess the quality of a field line
// 0 = perfect, otherwise a negative number indicates a worse quality (bad lines are more negative)
qint32 Combine::assessLineQuality(LdDecodeMetaData::Field field, qint32 lineNumber)
{
    // Right now this is a simple determination based on the length of dropouts present on the line
    if (field.dropOuts.startx.size() == 0) {
        // Field contains no dropouts
        return 0;
    }

    qint32 doLength = 0;
    for (qint32 doCounter = 0; doCounter < field.dropOuts.startx.size(); doCounter++) {
        // Is the dropout on the correct field line?
        if (field.dropOuts.fieldLine[doCounter] == lineNumber) {
            doLength -= field.dropOuts.endx[doCounter] - field.dropOuts.startx[doCounter];
        }
    }

    return doLength;
}

// Method to replace primary video line source data with secondary line source data
QByteArray Combine::replaceVideoLineData(QByteArray primaryFieldData, QByteArray secondaryFieldData, qint32 lineNumber)
{
    QByteArray outputData = primaryFieldData;

    // Copy the line from the secondary field data to the primary
    qint32 startOfLine = (lineNumber - 1) * primaryVideoParameters.fieldWidth * 2;
    for (qint32 pointer = 0; pointer < (primaryVideoParameters.fieldWidth * 2); pointer++) {
        outputData[startOfLine + pointer] = secondaryFieldData[startOfLine + pointer];
    }

    return outputData;
}

// Method to replace primary video dropout source data with secondary source data
QByteArray Combine::replaceVideoDropoutData(QByteArray primaryFieldData, QByteArray secondaryFieldData, qint32 lineNumber, qint32 startx, qint32 endx)
{
    QByteArray outputData = primaryFieldData;

    // Copy the line from the secondary field data to the primary
    qint32 startOfLine = (lineNumber - 1) * primaryVideoParameters.fieldWidth * 2;
    for (qint32 pointer = startx * 2; pointer < endx * 2; pointer++) {
        outputData[startOfLine + pointer] = secondaryFieldData[startOfLine + pointer];
    }

    return outputData;
}
