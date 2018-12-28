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

bool DropOutCorrect::process(QString inputFileName, QString outputFileName)
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
    for (qint32 frameNumber = 1; frameNumber <= ldDecodeMetaData.getNumberOfFrames(); frameNumber++) {
        SourceField *firstSourceField;
        SourceField *secondSourceField;

        // Get the field numbers for the frame
        qint32 firstFieldNumber = ldDecodeMetaData.getFirstFieldNumber(frameNumber);
        qint32 secondFieldNumber = ldDecodeMetaData.getSecondFieldNumber(frameNumber);

        // Get the source field data
        firstSourceField = sourceVideo.getVideoField(firstFieldNumber);
        secondSourceField = sourceVideo.getVideoField(secondFieldNumber);

        qDebug() << "DropOutDetector::process(): Processing frame" << frameNumber << "[" <<
                    firstFieldNumber << "/" << secondFieldNumber << "]";

        // Get the field meta data
        LdDecodeMetaData::Field firstField = ldDecodeMetaData.getField(firstFieldNumber);
        LdDecodeMetaData::Field secondField = ldDecodeMetaData.getField(secondFieldNumber);

        // Place the first field drop out data in the drop out correction structure
        QVector<DropOutLocation> firstFieldDropOuts;
        for (qint32 dropOutIndex = 0; dropOutIndex < firstField.dropOuts.startx.size(); dropOutIndex++) {
            DropOutLocation dropOutLocation;
            dropOutLocation.startx = firstField.dropOuts.startx[dropOutIndex];
            dropOutLocation.endx = firstField.dropOuts.endx[dropOutIndex];
            dropOutLocation.fieldLine = firstField.dropOuts.fieldLine[dropOutIndex];
            dropOutLocation.location = DropOutCorrect::Location::unknown;

            firstFieldDropOuts.append(dropOutLocation);
        }

        // Place the second field drop out data in the drop out correction structure
        QVector<DropOutLocation> secondFieldDropOuts;
        for (qint32 dropOutIndex = 0; dropOutIndex < secondField.dropOuts.startx.size(); dropOutIndex++) {
            DropOutLocation dropOutLocation;
            dropOutLocation.startx = secondField.dropOuts.startx[dropOutIndex];
            dropOutLocation.endx = secondField.dropOuts.endx[dropOutIndex];
            dropOutLocation.fieldLine = secondField.dropOuts.fieldLine[dropOutIndex];
            dropOutLocation.location = DropOutCorrect::Location::unknown;

            secondFieldDropOuts.append(dropOutLocation);
        }

        // Analyse the drop out locations in the first field
        firstFieldDropOuts = setDropOutLocation(firstFieldDropOuts, videoParameters);

        for (qint32 doCounter = 0; doCounter < firstFieldDropOuts.size(); doCounter++) {
            QString locationText;

            if (firstFieldDropOuts[doCounter].location == Location::unknown) locationText = "Unknown";
            else if (firstFieldDropOuts[doCounter].location == Location::colourBurst) locationText = "Colour burst";
            else locationText = "Active video";

            qDebug() << "DropOutDetector::process(): First field dropout [" << doCounter << "] -" <<
                        "pixel" << firstFieldDropOuts[doCounter].startx << "to" << firstFieldDropOuts[doCounter].endx <<
                        "(" << locationText << ")" <<
                        "on field-line" << firstFieldDropOuts[doCounter].fieldLine;
        }

        // Analyse the drop out locations in the second field
        secondFieldDropOuts = setDropOutLocation(secondFieldDropOuts, videoParameters);

        for (qint32 doCounter = 0; doCounter < secondFieldDropOuts.size(); doCounter++) {
            QString locationText;

            if (secondFieldDropOuts[doCounter].location == Location::unknown) locationText = "Unknown";
            else if (secondFieldDropOuts[doCounter].location == Location::colourBurst) locationText = "Colour burst";
            else locationText = "Active video";

            qDebug() << "DropOutDetector::process(): Second field dropout [" << doCounter << "] -" <<
                        "pixel" << secondFieldDropOuts[doCounter].startx << "to" << secondFieldDropOuts[doCounter].endx <<
                        "(" << locationText << ")" <<
                        "on field-line" << secondFieldDropOuts[doCounter].fieldLine;
        }

        // Perform dropout replacement
        QByteArray outputFirstFieldData;
        QByteArray outputSecondFieldData;

        // Copy the input data to the output data (to ensure the whole image is
        // transfered after drop-out correction)
        outputFirstFieldData.resize(firstSourceField->getFieldData().size());
        outputSecondFieldData.resize(secondSourceField->getFieldData().size());
        outputFirstFieldData = firstSourceField->getFieldData();
        outputSecondFieldData = secondSourceField->getFieldData();

        // Replace the detected drop-outs
        replaceDropOuts(firstFieldDropOuts, secondFieldDropOuts, videoParameters, firstSourceField->getFieldData(),
                        secondSourceField->getFieldData(), &outputFirstFieldData, &outputSecondFieldData);

        // Ensure we write the fields back in the correct order
        bool writeFail = false;
        if (firstFieldNumber < secondFieldNumber) {
            // Save the first field and then second field to the output file
            if (!targetVideo.write(outputFirstFieldData.data(), outputFirstFieldData.size())) writeFail = true;
            if (!targetVideo.write(outputSecondFieldData.data(), outputSecondFieldData.size())) writeFail = true;
        } else {
            // Save the second field and then first field to the output file
            if (!targetVideo.write(outputSecondFieldData.data(), outputSecondFieldData.size())) writeFail = true;
            if (!targetVideo.write(outputFirstFieldData.data(), outputFirstFieldData.size())) writeFail = true;
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
        qInfo() << "Frame #" << frameNumber << "-" << firstFieldDropOuts.size() + secondFieldDropOuts.size() << "dropouts corrected";
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

// Figure out where drop-outs occur and split them if in more than one area
QVector<DropOutCorrect::DropOutLocation> DropOutCorrect::setDropOutLocation(QVector<DropOutCorrect::DropOutLocation> dropOuts,
                                                                        LdDecodeMetaData::VideoParameters videoParameters)
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

// Replace the detected drop-outs according to location
void DropOutCorrect::replaceDropOuts(QVector<DropOutCorrect::DropOutLocation> firstFieldDropouts,
                                     QVector<DropOutCorrect::DropOutLocation> secondFieldDropouts,
                                     LdDecodeMetaData::VideoParameters videoParameters,
                                     QByteArray sourceFirstFieldData, QByteArray sourceSecondFieldData,
                                     QByteArray *targetFirstFieldData, QByteArray *targetSecondFieldData)
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

    // Active video drop-out correction
    replaceActiveVideoDropouts(firstFieldDropouts, firstActiveFieldLine, lastActiveFieldLine, sourceFirstFieldData, targetFirstFieldData, videoParameters);
    replaceActiveVideoDropouts(secondFieldDropouts, firstActiveFieldLine, lastActiveFieldLine, sourceSecondFieldData, targetSecondFieldData, videoParameters);

    // Colour burst
    replaceColourBurstDropouts(firstFieldDropouts, firstActiveFieldLine, lastActiveFieldLine, sourceFirstFieldData, targetFirstFieldData, videoParameters);
    replaceColourBurstDropouts(secondFieldDropouts, firstActiveFieldLine, lastActiveFieldLine, sourceSecondFieldData, targetSecondFieldData, videoParameters);
}

// Process dropouts in the active video area of the signal
void DropOutCorrect::replaceActiveVideoDropouts(QVector<DropOutCorrect::DropOutLocation> fieldDropouts,
                                               qint32 firstActiveFieldLine, qint32 lastActiveFieldLine,
                                               QByteArray sourceFieldData,
                                               QByteArray *targetFieldData,
                                               LdDecodeMetaData::VideoParameters videoParameters)
{
    for (qint32 index = 0; index < fieldDropouts.size(); index++) {
        if (fieldDropouts[index].location == Location::visibleLine) {
            // Find a good source for replacement
            bool foundSource = false;
            qint32 stepAmount = 2; // Move 2 field lines at a time (to maintain NTSC line phase)
            if (videoParameters.isSourcePal) stepAmount = 4; // Move 4 fields at a time (to maintain PAL line phase)

            // Look up the picture
            qint32 sourceLine = fieldDropouts[index].fieldLine - stepAmount;
            while (sourceLine > firstActiveFieldLine && foundSource == false) {
                // Is there a drop out on the proposed source line?
                foundSource = true;
                for (qint32 sourceIndex = 0; sourceIndex < fieldDropouts.size(); sourceIndex++) {
                    if (fieldDropouts[sourceIndex].fieldLine == sourceLine) {
                        // Does the start<->end range overlap?
                        if ((fieldDropouts[sourceIndex].endx - fieldDropouts[index].startx >= 0) && (fieldDropouts[index].endx - fieldDropouts[sourceIndex].startx >= 0)) {
                            // Overlap
                            sourceLine -= stepAmount;
                            foundSource = false;
                        } else {
                            foundSource = true; // Use the current source line
                            break;
                        }
                    }
                }
            }

            // Did we find a good source line?
            if (!foundSource) {
                // Look down the picture
                sourceLine = fieldDropouts[index].fieldLine + stepAmount;
                while (sourceLine < lastActiveFieldLine && foundSource == false) {
                    // Is there a drop out on the proposed source line?
                    foundSource = true;
                    for (qint32 sourceIndex = 0; sourceIndex < fieldDropouts.size(); sourceIndex++) {
                        if (fieldDropouts[sourceIndex].fieldLine == sourceLine) {
                            // Does the start<->end range overlap?
                            if ((fieldDropouts[sourceIndex].endx - fieldDropouts[index].startx >= 0) && (fieldDropouts[index].endx - fieldDropouts[sourceIndex].startx >= 0)) {
                                // Overlap
                                sourceLine += stepAmount;
                                foundSource = false;
                            } else {
                                foundSource = true; // Use the current source line
                                break;
                            }
                        }
                    }
                }
            }

            // If we still haven't found a good source, give up...
            if (!foundSource) sourceLine = fieldDropouts[index].fieldLine - stepAmount;

            // Replace the drop-out
            for (qint32 pixel = fieldDropouts[index].startx; pixel < fieldDropouts[index].endx; pixel++) {
                *(targetFieldData->data() + (((fieldDropouts[index].fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2))) =
                        *(sourceFieldData.data() + (((sourceLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2)));
                *(targetFieldData->data() + (((fieldDropouts[index].fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2) + 1)) =
                        *(sourceFieldData.data() + (((sourceLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2) + 1));
            }

            qDebug() << "DropOutCorrect::replaceActiveVideoDropouts(): Active video - Field-line" << fieldDropouts[index].fieldLine << "replacing" <<
                        fieldDropouts[index].startx << "to" << fieldDropouts[index].endx << "from source field-line" << sourceLine;
        }
    }
}

// Process dropouts in the colour burst area of the signal
void DropOutCorrect::replaceColourBurstDropouts(QVector<DropOutCorrect::DropOutLocation> fieldDropouts,
                                               qint32 firstActiveFieldLine, qint32 lastActiveFieldLine,
                                               QByteArray sourceFieldData,
                                               QByteArray *targetFieldData,
                                               LdDecodeMetaData::VideoParameters videoParameters)
{
    for (qint32 index = 0; index < fieldDropouts.size(); index++) {
        if (fieldDropouts[index].location == Location::colourBurst) {
            // Find a good source for replacement
            bool foundSource = false;
            qint32 stepAmount = 8; // Move eight field-lines at a time (to maintain PAL phase)
            if (!videoParameters.isSourcePal) stepAmount = 4; // Move four field-lines at a time (to maintain NTSC phase)

            // Look up the picture
            qint32 sourceLine = fieldDropouts[index].fieldLine - stepAmount;
            while (sourceLine > firstActiveFieldLine && foundSource == false) {
                // Is there a drop out on the proposed source line?
                foundSource = true;
                for (qint32 sourceIndex = 0; sourceIndex < fieldDropouts.size(); sourceIndex++) {
                    if (fieldDropouts[sourceIndex].fieldLine == sourceLine) {
                        // Does the start<->end range overlap?
                        if ((fieldDropouts[sourceIndex].endx - fieldDropouts[index].startx >= 0) && (fieldDropouts[index].endx - fieldDropouts[sourceIndex].startx >= 0)) {
                            // Overlap
                            sourceLine -= stepAmount;
                            foundSource = false;
                        } else {
                            foundSource = true; // Use the current source line
                            break;
                        }
                    }
                }
            }

            // Did we find a good source line?
            if (!foundSource) {
                // Look down the picture
                sourceLine = fieldDropouts[index].fieldLine + stepAmount;
                while (sourceLine < lastActiveFieldLine && foundSource == false) {
                    // Is there a drop out on the proposed source line?
                    foundSource = true;
                    for (qint32 sourceIndex = 0; sourceIndex < fieldDropouts.size(); sourceIndex++) {
                        if (fieldDropouts[sourceIndex].fieldLine == sourceLine) {
                            // Does the start<->end range overlap?
                            if ((fieldDropouts[sourceIndex].endx - fieldDropouts[index].startx >= 0) && (fieldDropouts[index].endx - fieldDropouts[sourceIndex].startx >= 0)) {
                                // Overlap
                                sourceLine += stepAmount;
                                foundSource = false;
                            } else {
                                foundSource = true; // Use the current source line
                                break;
                            }
                        }
                    }
                }
            }

            // If we still haven't found a good source, give up...
            if (!foundSource) sourceLine = fieldDropouts[index].fieldLine - stepAmount;

            // Replace the drop-out
            for (qint32 pixel = fieldDropouts[index].startx; pixel < fieldDropouts[index].endx; pixel++) {
                *(targetFieldData->data() + (((fieldDropouts[index].fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2))) =
                        *(sourceFieldData.data() + (((sourceLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2)));
                *(targetFieldData->data() + (((fieldDropouts[index].fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2) + 1)) =
                        *(sourceFieldData.data() + (((sourceLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2) + 1));
            }

            qDebug() << "DropOutCorrect::replaceColourBurstDropouts(): Colour burst - Field-line" << fieldDropouts[index].fieldLine << "replacing" <<
                        fieldDropouts[index].startx << "to" << fieldDropouts[index].endx << "from source field-line" << sourceLine;
        }
    }
}
