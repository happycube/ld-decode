/************************************************************************

    dropoutcorrect.cpp

    ld-dropout-correct - Dropout correction for ld-decode
    Copyright (C) 2018 Simon Inns

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

#include "dropoutcorrect.h"

DropOutCorrect::DropOutCorrect(QObject *parent) : QObject(parent)
{

}

bool DropOutCorrect::process(QString inputFileName, QString outputFileName, bool isIntrafield)
{
    SourceVideo sourceVideo;
    (void)isIntrafield; // NOTE: Placeholder

    // Open the source video metadata
    if (!ldDecodeMetaData.read(inputFileName + ".json")) {
        qInfo() << "Unable to open ld-decode metadata file";
        return false;
    }

    videoParameters = ldDecodeMetaData.getVideoParameters();

    qDebug() << "DropOutDetector::process(): Input source is" << videoParameters.fieldWidth << "x" << videoParameters.fieldHeight << "filename" << inputFileName;

    // Open the source video
    if (!sourceVideo.open(inputFileName, videoParameters.fieldWidth * videoParameters.fieldHeight)) {
        // Could not open source video file
        qInfo() << "Unable to open ld-decode video file";
        return false;
    }

    // Open the target video
    QFile targetVideo(outputFileName);
    if (!targetVideo.open(QIODevice::WriteOnly)) {
            // Could not open target video file
            qInfo() << "Unable to open output video file";
            sourceVideo.close();
            return false;
    }

    // Check TBC and JSON field numbers match
    if (sourceVideo.getNumberOfAvailableFields() != ldDecodeMetaData.getNumberOfFields()) {
        qInfo() << "Warning: TBC file contains" << sourceVideo.getNumberOfAvailableFields() <<
                   "fields but the JSON indicates" << ldDecodeMetaData.getNumberOfFields() <<
                   "fields - some fields will be ignored";
    }

    // If there is a leading field in the TBC which is out of field order, we need to copy it
    // to ensure the JSON metadata files match up
    qint32 firstFieldNumber = ldDecodeMetaData.getFirstFieldNumber(1);
    qint32 secondFieldNumber = ldDecodeMetaData.getSecondFieldNumber(1);

    if (firstFieldNumber != 1 && secondFieldNumber != 1) {
        SourceField *sourceField;
        sourceField = sourceVideo.getVideoField(1);
        if (!targetVideo.write(sourceField->getFieldData(), sourceField->getFieldData().size())) {
            // Could not write to target TBC file
            qInfo() << "Writing first field to the output TBC file failed";
            targetVideo.close();
            sourceVideo.close();
            return false;
        }
    }

    // Process the frames

    // Define the required step amount for colour burst replacement (to maintain line phase)
    qint32 colourBurstStepAmount = 8; // PAL
    qint32 visibleLineStepAmount = 4; // PAL
    if (!videoParameters.isSourcePal) {
        colourBurstStepAmount = 4; // NTSC
        visibleLineStepAmount = 2; // PAL
    }

    for (qint32 frameNumber = 1; frameNumber <= ldDecodeMetaData.getNumberOfFrames(); frameNumber++) {
        // Get the field numbers for the frame
        qint32 firstFieldNumber = ldDecodeMetaData.getFirstFieldNumber(frameNumber);
        qint32 secondFieldNumber = ldDecodeMetaData.getSecondFieldNumber(frameNumber);

        qDebug() << "DropOutDetector::process(): Processing frame" << frameNumber << "[" <<
                    firstFieldNumber << "/" << secondFieldNumber << "]";

        // Analyse the drop out locations in the first and second fields
        QVector<DropOutLocation> firstFieldDropouts =
                setDropOutLocations(populateDropoutsVector(ldDecodeMetaData.getField(firstFieldNumber)));
        QVector<DropOutLocation> secondFieldDropouts =
                setDropOutLocations(populateDropoutsVector(ldDecodeMetaData.getField(secondFieldNumber)));

        // Process the dropouts for the first field
        QVector<Replacement> firstFieldReplacementLines;
        firstFieldReplacementLines.resize(firstFieldDropouts.size());
        for (qint32 dropoutIndex = 0; dropoutIndex < firstFieldDropouts.size(); dropoutIndex++) {
            // Is the current dropout in the colour burst?
            if (firstFieldDropouts[dropoutIndex].location == Location::colourBurst) {
                firstFieldReplacementLines[dropoutIndex].isFirstField = true;
                firstFieldReplacementLines[dropoutIndex].fieldLine = findReplacementLine(firstFieldDropouts, dropoutIndex, colourBurstStepAmount);
            }

            // Is the current dropout in the visible video line?
            if (firstFieldDropouts[dropoutIndex].location == Location::visibleLine) {
                firstFieldReplacementLines[dropoutIndex].isFirstField = true;
                firstFieldReplacementLines[dropoutIndex].fieldLine = findReplacementLine(firstFieldDropouts, dropoutIndex, visibleLineStepAmount);
            }
        }

        // Process the dropouts for the second field
        QVector<Replacement> secondFieldReplacementLines;
        secondFieldReplacementLines.resize(secondFieldDropouts.size());
        for (qint32 dropoutIndex = 0; dropoutIndex < secondFieldDropouts.size(); dropoutIndex++) {
            // Is the current dropout in the colour burst?
            if (secondFieldDropouts[dropoutIndex].location == Location::colourBurst) {
                secondFieldReplacementLines[dropoutIndex].isFirstField = true;
                secondFieldReplacementLines[dropoutIndex].fieldLine = findReplacementLine(secondFieldDropouts, dropoutIndex, colourBurstStepAmount);
            }

            // Is the current dropout in the visible video line?
            if (secondFieldDropouts[dropoutIndex].location == Location::visibleLine) {
                secondFieldReplacementLines[dropoutIndex].isFirstField = true;
                secondFieldReplacementLines[dropoutIndex].fieldLine = findReplacementLine(secondFieldDropouts, dropoutIndex, visibleLineStepAmount);
            }
        }

        // Get the source frame field data
        QByteArray firstSourceField = sourceVideo.getVideoField(firstFieldNumber)->getFieldData();
        QByteArray secondSourceField = sourceVideo.getVideoField(secondFieldNumber)->getFieldData();
        QByteArray firstTargetFieldData = firstSourceField;
        QByteArray secondTargetFieldData = secondSourceField;

        // Correct the data of the first field
        for (qint32 dropoutIndex = 0; dropoutIndex < firstFieldDropouts.size(); dropoutIndex++) {
            for (qint32 pixel = firstFieldDropouts[dropoutIndex].startx; pixel < firstFieldDropouts[dropoutIndex].endx; pixel++) {
                *(firstTargetFieldData.data() + (((firstFieldDropouts[dropoutIndex].fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2))) =
                        *(firstTargetFieldData.data() + (((firstFieldReplacementLines[dropoutIndex].fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2)));
                *(firstTargetFieldData.data() + (((firstFieldDropouts[dropoutIndex].fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2) + 1)) =
                        *(firstTargetFieldData.data() + (((firstFieldReplacementLines[dropoutIndex].fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2) + 1));
            }
        }

        // Correct the data of the second field
        for (qint32 dropoutIndex = 0; dropoutIndex < secondFieldDropouts.size(); dropoutIndex++) {
            for (qint32 pixel = secondFieldDropouts[dropoutIndex].startx; pixel < secondFieldDropouts[dropoutIndex].endx; pixel++) {
                *(secondTargetFieldData.data() + (((secondFieldDropouts[dropoutIndex].fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2))) =
                        *(secondSourceField.data() + (((secondFieldReplacementLines[dropoutIndex].fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2)));
                *(secondTargetFieldData.data() + (((secondFieldDropouts[dropoutIndex].fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2) + 1)) =
                        *(secondSourceField.data() + (((secondFieldReplacementLines[dropoutIndex].fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2) + 1));
            }
        }

        // Write the fields into the output TBC file in the correct order
        bool writeFail = false;
        if (firstFieldNumber < secondFieldNumber) {
            // Save the first field and then second field to the output file
            if (!targetVideo.write(firstTargetFieldData.data(), firstTargetFieldData.size())) writeFail = true;
            if (!targetVideo.write(secondTargetFieldData.data(), secondTargetFieldData.size())) writeFail = true;
        } else {
            // Save the second field and then first field to the output file
            if (!targetVideo.write(secondTargetFieldData.data(), secondTargetFieldData.size())) writeFail = true;
            if (!targetVideo.write(firstTargetFieldData.data(), firstTargetFieldData.size())) writeFail = true;
        }

        // Was the write successful?
        if (writeFail) {
            // Could not write to target TBC file
            qInfo() << "Writing fields to the output TBC file failed";
            targetVideo.close();
            sourceVideo.close();
            return false;
        }

        // Show an update to the user
        qInfo() << "Frame #" << frameNumber << "[" << firstFieldNumber << "/" << secondFieldNumber << "] -"
                << firstFieldDropouts.size() + secondFieldDropouts.size() << "dropouts corrected";
    }

    qInfo() << "Creating JSON metadata file for corrected TBC";
    ldDecodeMetaData.write(outputFileName + ".json");

    qInfo() << "Processing complete";

    // Close the source video
    sourceVideo.close();

    // Close the target video
    targetVideo.close();

    return true;
}

// Populate the dropouts vector
QVector<DropOutCorrect::DropOutLocation> DropOutCorrect::populateDropoutsVector(LdDecodeMetaData::Field field)
{
    QVector<DropOutLocation> fieldDropOuts;

    for (qint32 dropOutIndex = 0; dropOutIndex < field.dropOuts.startx.size(); dropOutIndex++) {
        DropOutLocation dropOutLocation;
        dropOutLocation.startx = field.dropOuts.startx[dropOutIndex];
        dropOutLocation.endx = field.dropOuts.endx[dropOutIndex];
        dropOutLocation.fieldLine = field.dropOuts.fieldLine[dropOutIndex];
        dropOutLocation.location = DropOutCorrect::Location::unknown;

        fieldDropOuts.append(dropOutLocation);
    }

    return fieldDropOuts;
}

// Figure out where drop-outs occur and split them if in more than one area
QVector<DropOutCorrect::DropOutLocation> DropOutCorrect::setDropOutLocations(QVector<DropOutCorrect::DropOutLocation> dropOuts)
{
    // Split count shows if a drop-out has been split (i.e. the original
    // drop-out covered more than one area).
    //
    // Since a drop-out can span multiple areas, we have to keep
    // spliting the drop-outs until there is nothing left to split
    qint32 splitCount = 0;

    do {
        qint32 noOfDropOuts = dropOuts.size();
        splitCount = 0;

        for (qint32 index = 0; index < noOfDropOuts; index++) {
            // Does the drop-out start in the colour burst area?
            if (dropOuts[index].startx <= videoParameters.colourBurstEnd) {
                dropOuts[index].location = Location::colourBurst;

                // Does the drop-out end in the colour burst area?
                if (dropOuts[index].endx > videoParameters.colourBurstEnd) {
                    // Split the drop-out in two
                    DropOutLocation tempDropOut;
                    tempDropOut.startx = videoParameters.colourBurstEnd + 1;
                    tempDropOut.endx = dropOuts[index].endx;
                    tempDropOut.fieldLine = dropOuts[index].fieldLine;
                    tempDropOut.location = Location::colourBurst;
                    dropOuts.append(tempDropOut);

                    // Shorten the original drop out
                    dropOuts[index].endx = videoParameters.colourBurstEnd;

                    splitCount++;
                }
            }

            // Does the drop-out start in the active video area?
            // Note: Here we use the colour burst end as the active video start (to prevent a case where the
            // drop out begins between the colour burst level end and active video start and would go undetected)
            else if (dropOuts[index].startx > videoParameters.colourBurstEnd && dropOuts[index].startx <= videoParameters.activeVideoEnd) {
                dropOuts[index].location = Location::visibleLine;

                // Does the drop-out end in the active video area?
                if (dropOuts[index].endx > videoParameters.activeVideoEnd) {
                    // No need to split as we don't care about the sync area

                    // Shorten the original drop out
                    dropOuts[index].endx = videoParameters.activeVideoEnd;

                    splitCount++;
                }
            }
        }
    } while (splitCount != 0);

    return dropOuts;
}

// Find a replacement line to take replacement data from.  This method looks both up and down the field
// for the nearest replacement line that doesn't contain a drop-out itself (to prevent copying bad data
// over bad data).
qint32 DropOutCorrect::findReplacementLine(QVector<DropOutLocation>dropOuts, qint32 dropOutIndex, qint32 stepAmount)
{
    // Determine the first and last active scan line based on the source format
    qint32 firstActiveFieldLine;
    qint32 lastActiveFieldLine;
    if (videoParameters.isSourcePal) {
        firstActiveFieldLine = 22;
        lastActiveFieldLine = 308;
    } else {
        firstActiveFieldLine = 20;
        lastActiveFieldLine = 259;
    }

    bool upFoundSource = false;
    bool downFoundSource = false;

    // Look up the field for a replacement
    qint32 upSourceLine = dropOuts[dropOutIndex].fieldLine - stepAmount;
    while (upSourceLine > firstActiveFieldLine && upFoundSource == false) {
        // Is there a drop out on the proposed source line?
        upFoundSource = true;
        for (qint32 sourceIndex = 0; sourceIndex < dropOuts.size(); sourceIndex++) {
            if (dropOuts[sourceIndex].fieldLine == upSourceLine) {
                // Does the start<->end range overlap?
                if ((dropOuts[sourceIndex].endx - dropOuts[dropOutIndex].startx >= 0) && (dropOuts[dropOutIndex].endx - dropOuts[sourceIndex].startx >= 0)) {
                    // Overlap
                    upSourceLine -= stepAmount;
                    upFoundSource = false;
                } else {
                    upFoundSource = true; // Use the current source line
                    break;
                }
            }
        }
    }
    if (!upFoundSource) upSourceLine = -1;

    // Look down the field for a replacement
   qint32 downSourceLine = dropOuts[dropOutIndex].fieldLine + stepAmount;
    while (downSourceLine < lastActiveFieldLine && downFoundSource == false) {
        // Is there a drop out on the proposed source line?
        downFoundSource = true;
        for (qint32 sourceIndex = 0; sourceIndex < dropOuts.size(); sourceIndex++) {
            if (dropOuts[sourceIndex].fieldLine == downSourceLine) {
                // Does the start<->end range overlap?
                if ((dropOuts[sourceIndex].endx - dropOuts[dropOutIndex].startx >= 0) && (dropOuts[dropOutIndex].endx - dropOuts[sourceIndex].startx >= 0)) {
                    // Overlap
                    downSourceLine += stepAmount;
                    downFoundSource = false;
                } else {
                    downFoundSource = true; // Use the current source line
                    break;
                }
            }
        }
    }
    if (!downFoundSource) downSourceLine = -1;

    qint32 sourceLine;
    if (!upFoundSource && !downFoundSource) {
        // We didn't find a good replacement source in either direction
        sourceLine = dropOuts[dropOutIndex].fieldLine - stepAmount;
    } else if (upFoundSource && !downFoundSource) {
        // We only found a replacement in the up direction
        sourceLine = upSourceLine;
    } else if (!upFoundSource && downFoundSource) {
        // We only found a replacement in the down direction
        sourceLine = downSourceLine;
    } else {
        // We found a replacement in both directions, pick the closest
        if (upSourceLine < downSourceLine) sourceLine = upSourceLine;
        else sourceLine = downSourceLine;
    }

    return sourceLine;
}

