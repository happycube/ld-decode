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

    // Process the fields
    for (qint32 fieldNumber = 1; fieldNumber <= ldDecodeMetaData.getNumberOfFields(); fieldNumber++) {
        SourceField *sourceField;

        // Get the source frame
        sourceField = sourceVideo.getVideoField(fieldNumber);

        // Get the existing field data from the metadata
        qDebug() << "DropOutDetector::process(): Getting metadata for field" << fieldNumber;
        LdDecodeMetaData::Field field = ldDecodeMetaData.getField(fieldNumber);

        // Place the drop out data in the drop out correction structure
        QVector<DropOutLocation> dropOuts;
        for (qint32 dropOutIndex = 0; dropOutIndex < field.dropOuts.startx.size(); dropOutIndex++) {
            DropOutLocation dropOutLocation;
            dropOutLocation.startx = field.dropOuts.startx[dropOutIndex];
            dropOutLocation.endx = field.dropOuts.endx[dropOutIndex];
            dropOutLocation.fieldLine = field.dropOuts.fieldLine[dropOutIndex];
            dropOutLocation.location = DropOutCorrect::Location::unknown;

            dropOuts.append(dropOutLocation);
        }

        // Analyse the drop out locations
        dropOuts = setDropOutLocation(dropOuts, videoParameters);

        for (qint32 doCounter = 0; doCounter < dropOuts.size(); doCounter++) {
            QString locationText;

            if (dropOuts[doCounter].location == Location::unknown) locationText = "Unknown";
            else if (dropOuts[doCounter].location == Location::colourBurst) locationText = "Colour burst";
            else if (dropOuts[doCounter].location == Location::black) locationText = "Black level";
            else locationText = "Active video";

            qDebug() << "DropOutDetector::process(): Dropout [" << doCounter << "] -" <<
                        "pixel" << dropOuts[doCounter].startx << "to" << dropOuts[doCounter].endx <<
                        "(" << locationText << ")" <<
                        "on field-line" << dropOuts[doCounter].fieldLine;
        }

        // Perform dropout replacement
        QByteArray outputFieldData = replaceDropOuts(dropOuts, videoParameters, sourceField->getFieldData());

        // Save the frame data to the output file
        if (!targetVideo.write(outputFieldData.data(), outputFieldData.size())) {
            // Could not write to target video file
            qInfo() << "Writing to the output video file failed";
            targetVideo.close();
            sourceVideo.close();
            return false;
        }

        // Show an update to the user
        qInfo() << "Field #" << fieldNumber << "-" << dropOuts.size() << "dropouts corrected";
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

            // Does the drop-out start in the black level area?
            else if (dropOuts[index].startx > videoParameters.colourBurstEnd && dropOuts[index].startx <= videoParameters.blackLevelEnd) {
                dropOuts[index].location = Location::black;

                // Does the drop-out end in the black level area?
                if (dropOuts[index].endx > videoParameters.blackLevelEnd) {
                    // Split the drop-out in two
                    DropOutLocation tempDropOut;
                    tempDropOut.startx = videoParameters.blackLevelEnd + 1;
                    tempDropOut.endx = dropOuts[index].endx;
                    tempDropOut.fieldLine = dropOuts[index].fieldLine;
                    tempDropOut.location = Location::visibleLine;
                    dropOuts.append(tempDropOut);

                    // Shorten the original drop out
                    dropOuts[index].endx = videoParameters.blackLevelEnd;

                    splitCount++;
                }
            }

            // Does the drop-out start in the active video area?
            // Note: Here we use the black-level end as the active video start (to prevent a case where the
            // drop out begins between the black level end and active video start and would go undetected)
            else if (dropOuts[index].startx > videoParameters.blackLevelEnd && dropOuts[index].startx <= videoParameters.activeVideoEnd) {
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
QByteArray DropOutCorrect::replaceDropOuts(QVector<DropOutCorrect::DropOutLocation> dropOuts, LdDecodeMetaData::VideoParameters videoParameters,
                                     QByteArray sourceFieldData)
{
    QByteArray targetFieldData = sourceFieldData;

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
    for (qint32 index = 0; index < dropOuts.size(); index++) {
        if (dropOuts[index].location == Location::visibleLine) {
            // Find a good source for replacement
            bool foundSource = false;
            qint32 stepAmount = 2; // Move 2 field lines at a time (to maintain NTSC line phase)
            if (videoParameters.isSourcePal) stepAmount = 4; // Move 4 fields at a time (to maintain PAL line phase)

            // Look up the picture
            qint32 sourceLine = dropOuts[index].fieldLine - stepAmount;
            while (sourceLine > firstActiveFieldLine && foundSource == false) {
                // Is there a drop out on the proposed source line?
                foundSource = true;
                for (qint32 sourceIndex = 0; sourceIndex < dropOuts.size(); sourceIndex++) {
                    if (dropOuts[sourceIndex].fieldLine == sourceLine) {
                        // Does the start<->end range overlap?
                        if ((dropOuts[sourceIndex].endx - dropOuts[index].startx >= 0) && (dropOuts[index].endx - dropOuts[sourceIndex].startx >= 0)) {
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
                sourceLine = dropOuts[index].fieldLine + stepAmount;
                while (sourceLine < lastActiveFieldLine && foundSource == false) {
                    // Is there a drop out on the proposed source line?
                    foundSource = true;
                    for (qint32 sourceIndex = 0; sourceIndex < dropOuts.size(); sourceIndex++) {
                        if (dropOuts[sourceIndex].fieldLine == sourceLine) {
                            // Does the start<->end range overlap?
                            if ((dropOuts[sourceIndex].endx - dropOuts[index].startx >= 0) && (dropOuts[index].endx - dropOuts[sourceIndex].startx >= 0)) {
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
            if (!foundSource) sourceLine = dropOuts[index].fieldLine - stepAmount;

            // Replace the drop-out
            for (qint32 pixel = dropOuts[index].startx; pixel < dropOuts[index].endx; pixel++) {
                *(targetFieldData.data() + (((dropOuts[index].fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2))) =
                        *(sourceFieldData.data() + (((sourceLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2)));
                *(targetFieldData.data() + (((dropOuts[index].fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2) + 1)) =
                        *(sourceFieldData.data() + (((sourceLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2) + 1));
            }

            qDebug() << "DropOutCorrect::replaceDropOuts(): Active video - Field-line" << dropOuts[index].fieldLine << "replacing" <<
                        dropOuts[index].startx << "to" << dropOuts[index].endx << "from source field-line" << sourceLine;
        }
    }

    // Black level
    for (qint32 index = 0; index < dropOuts.size(); index++) {
        if (dropOuts[index].location == Location::black) {
            // Find a good source for replacement
            bool foundSource = false;
            qint32 stepAmount = 2; // Move two field-lines at a time

            // Look up the picture
            qint32 sourceLine = dropOuts[index].fieldLine - stepAmount;
            while (sourceLine > firstActiveFieldLine && foundSource == false) {
                // Is there a drop out on the proposed source line?
                foundSource = true;
                for (qint32 sourceIndex = 0; sourceIndex < dropOuts.size(); sourceIndex++) {
                    if (dropOuts[sourceIndex].fieldLine == sourceLine) {
                        // Does the start<->end range overlap?
                        if ((dropOuts[sourceIndex].endx - dropOuts[index].startx >= 0) && (dropOuts[index].endx - dropOuts[sourceIndex].startx >= 0)) {
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
                sourceLine = dropOuts[index].fieldLine + stepAmount;
                while (sourceLine < lastActiveFieldLine && foundSource == false) {
                    // Is there a drop out on the proposed source line?
                    foundSource = true;
                    for (qint32 sourceIndex = 0; sourceIndex < dropOuts.size(); sourceIndex++) {
                        if (dropOuts[sourceIndex].fieldLine == sourceLine) {
                            // Does the start<->end range overlap?
                            if ((dropOuts[sourceIndex].endx - dropOuts[index].startx >= 0) && (dropOuts[index].endx - dropOuts[sourceIndex].startx >= 0)) {
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
            if (!foundSource) sourceLine = dropOuts[index].fieldLine - stepAmount;

            // Replace the drop-out
            for (qint32 pixel = dropOuts[index].startx; pixel < dropOuts[index].endx; pixel++) {
                *(targetFieldData.data() + (((dropOuts[index].fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2))) =
                        *(sourceFieldData.data() + (((sourceLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2)));
                *(targetFieldData.data() + (((dropOuts[index].fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2) + 1)) =
                        *(sourceFieldData.data() + (((sourceLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2) + 1));
            }

            qDebug() << "DropOutCorrect::replaceDropOuts(): Black-level - Field-line" << dropOuts[index].fieldLine << "replacing" <<
                        dropOuts[index].startx << "to" << dropOuts[index].endx << "from source field-line" << sourceLine;
        }
    }

    // Colour burst
    for (qint32 index = 0; index < dropOuts.size(); index++) {
        if (dropOuts[index].location == Location::colourBurst) {
            // Find a good source for replacement
            bool foundSource = false;
            qint32 stepAmount = 8; // Move eight field-lines at a time (to maintain phase)
            if (!videoParameters.isSourcePal) stepAmount = 1; // For NTSC correction

            // Look up the picture
            qint32 sourceLine = dropOuts[index].fieldLine - stepAmount;
            while (sourceLine > firstActiveFieldLine && foundSource == false) {
                // Is there a drop out on the proposed source line?
                foundSource = true;
                for (qint32 sourceIndex = 0; sourceIndex < dropOuts.size(); sourceIndex++) {
                    if (dropOuts[sourceIndex].fieldLine == sourceLine) {
                        // Does the start<->end range overlap?
                        if ((dropOuts[sourceIndex].endx - dropOuts[index].startx >= 0) && (dropOuts[index].endx - dropOuts[sourceIndex].startx >= 0)) {
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
                sourceLine = dropOuts[index].fieldLine + stepAmount;
                while (sourceLine < lastActiveFieldLine && foundSource == false) {
                    // Is there a drop out on the proposed source line?
                    foundSource = true;
                    for (qint32 sourceIndex = 0; sourceIndex < dropOuts.size(); sourceIndex++) {
                        if (dropOuts[sourceIndex].fieldLine == sourceLine) {
                            // Does the start<->end range overlap?
                            if ((dropOuts[sourceIndex].endx - dropOuts[index].startx >= 0) && (dropOuts[index].endx - dropOuts[sourceIndex].startx >= 0)) {
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
            if (!foundSource) sourceLine = dropOuts[index].fieldLine - stepAmount;

            // Replace the drop-out
            for (qint32 pixel = dropOuts[index].startx; pixel < dropOuts[index].endx; pixel++) {
                *(targetFieldData.data() + (((dropOuts[index].fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2))) =
                        *(sourceFieldData.data() + (((sourceLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2)));
                *(targetFieldData.data() + (((dropOuts[index].fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2) + 1)) =
                        *(sourceFieldData.data() + (((sourceLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2) + 1));
            }

            qDebug() << "DropOutCorrect::replaceDropOuts(): Colour burst - Field-line" << dropOuts[index].fieldLine << "replacing" <<
                        dropOuts[index].startx << "to" << dropOuts[index].endx << "from source field-line" << sourceLine;
        }
    }

    return targetFieldData;
}
