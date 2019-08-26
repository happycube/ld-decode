/************************************************************************

    dropoutcorrect.cpp

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

#include "dropoutcorrect.h"
#include "correctorpool.h"

DropOutCorrect::DropOutCorrect(QAtomicInt& _abort, CorrectorPool& _correctorPool, QObject *parent)
    : QThread(parent), abort(_abort), correctorPool(_correctorPool)
{
}

void DropOutCorrect::run()
{
    // Variables for getInputFrame
    qint32 frameNumber;
    qint32 firstFieldSeqNo;
    qint32 secondFieldSeqNo;
    QByteArray firstSourceField;
    QByteArray secondSourceField;
    LdDecodeMetaData::Field firstFieldMetadata;
    LdDecodeMetaData::Field secondFieldMetadata;
    bool reverse, intraField, overCorrect;

    qDebug() << "DropOutCorrect::process(): Processing loop ready to go";

    while(!abort) {
        // Get the next field to process from the input file
        if (!correctorPool.getInputFrame(frameNumber, firstFieldSeqNo, firstSourceField, firstFieldMetadata,
                                       secondFieldSeqNo, secondSourceField, secondFieldMetadata,
                                       videoParameters, reverse, intraField, overCorrect)) {
            // No more input fields -- exit
            break;
        }
        qDebug() << "DropOutCorrect::process(): Got frame number" << frameNumber;

        // Set the output frame to the input frame's data
        QByteArray firstTargetFieldData = firstSourceField;
        QByteArray secondTargetFieldData = secondSourceField;

        // Check if the frame contains drop-outs
        if (firstFieldMetadata.dropOuts.startx.size() == 0 && secondFieldMetadata.dropOuts.startx.size() == 0) {
            // No correction required...
            qDebug() << "DropOutDetector::process(): Skipping fields [" <<
                        firstFieldSeqNo << "/" << secondFieldSeqNo << "]";
        } else {
            // Perform correction...
            qDebug() << "DropOutDetector::process(): Correcting fields [" <<
                        firstFieldSeqNo << "/" << secondFieldSeqNo << "] containing" <<
                        firstFieldMetadata.dropOuts.startx.size() + secondFieldMetadata.dropOuts.startx.size() <<
                        "drop-outs";

            // Analyse the drop out locations in the first field
            QVector<DropOutLocation> firstFieldDropouts;
            if (firstFieldMetadata.dropOuts.startx.size() > 0) firstFieldDropouts = setDropOutLocations(populateDropoutsVector(firstFieldMetadata, overCorrect));

            // Analyse the drop out locations in the second field
            QVector<DropOutLocation> secondFieldDropouts;
            if (secondFieldMetadata.dropOuts.startx.size() > 0) secondFieldDropouts = setDropOutLocations(populateDropoutsVector(secondFieldMetadata, overCorrect));

            // Process the first field if it contains drop-outs
            if (firstFieldDropouts.size() > 0) {
                // Process the dropouts for the first field
                QVector<Replacement> firstFieldReplacementLines;
                firstFieldReplacementLines.resize(firstFieldDropouts.size());
                for (qint32 dropoutIndex = 0; dropoutIndex < firstFieldDropouts.size(); dropoutIndex++) {
                    // Is the current dropout in the colour burst?
                    if (firstFieldDropouts[dropoutIndex].location == Location::colourBurst) {
                        firstFieldReplacementLines[dropoutIndex] = findReplacementLine(firstFieldDropouts, secondFieldDropouts, dropoutIndex, true, intraField);
                    }

                    // Is the current dropout in the visible video line?
                    if (firstFieldDropouts[dropoutIndex].location == Location::visibleLine) {
                        firstFieldReplacementLines[dropoutIndex] = findReplacementLine(firstFieldDropouts, secondFieldDropouts, dropoutIndex, false, intraField);
                    }
                }

                // Correct the data of the first field
                for (qint32 dropoutIndex = 0; dropoutIndex < firstFieldDropouts.size(); dropoutIndex++) {
                    if (firstFieldReplacementLines[dropoutIndex].isFirstField) {
                        // Correct the first field from the first field (intra-field correction)
                        correctDropOut(firstFieldDropouts[dropoutIndex], firstFieldReplacementLines[dropoutIndex], firstTargetFieldData, firstTargetFieldData);
                    } else {
                        // Correct the first field from the second field (inter-field correction)
                        correctDropOut(firstFieldDropouts[dropoutIndex], firstFieldReplacementLines[dropoutIndex], firstTargetFieldData, secondTargetFieldData);
                    }
                }
            }

            // Process the second field if it contains drop-outs
            if (secondFieldDropouts.size() > 0) {
                // Process the dropouts for the second field
                QVector<Replacement> secondFieldReplacementLines;
                secondFieldReplacementLines.resize(secondFieldDropouts.size());
                for (qint32 dropoutIndex = 0; dropoutIndex < secondFieldDropouts.size(); dropoutIndex++) {
                    // Is the current dropout in the colour burst?
                    if (secondFieldDropouts[dropoutIndex].location == Location::colourBurst) {
                        secondFieldReplacementLines[dropoutIndex] = findReplacementLine(secondFieldDropouts, firstFieldDropouts, dropoutIndex, true, intraField);
                    }

                    // Is the current dropout in the visible video line?
                    if (secondFieldDropouts[dropoutIndex].location == Location::visibleLine) {
                        secondFieldReplacementLines[dropoutIndex] = findReplacementLine(secondFieldDropouts, firstFieldDropouts, dropoutIndex, false, intraField);
                    }
                }

                // Correct the data of the second field
                for (qint32 dropoutIndex = 0; dropoutIndex < secondFieldDropouts.size(); dropoutIndex++) {
                    if (secondFieldReplacementLines[dropoutIndex].isFirstField) {
                        // Correct the second field from the second field (intra-field correction)
                        correctDropOut(secondFieldDropouts[dropoutIndex], secondFieldReplacementLines[dropoutIndex], secondTargetFieldData, secondSourceField);
                    } else {
                        // Correct the second field from the first field (inter-field correction)
                        correctDropOut(secondFieldDropouts[dropoutIndex], secondFieldReplacementLines[dropoutIndex], secondTargetFieldData, firstSourceField);
                    }
                }
            }
        }

        // Return the processed fields
        correctorPool.setOutputFrame(frameNumber, firstTargetFieldData, secondTargetFieldData, firstFieldSeqNo, secondFieldSeqNo);
    }
}

// Populate the dropouts vector
QVector<DropOutCorrect::DropOutLocation> DropOutCorrect::populateDropoutsVector(LdDecodeMetaData::Field field, bool overCorrect)
{
    QVector<DropOutLocation> fieldDropOuts;

    for (qint32 dropOutIndex = 0; dropOutIndex < field.dropOuts.startx.size(); dropOutIndex++) {
        DropOutLocation dropOutLocation;
        dropOutLocation.startx = field.dropOuts.startx[dropOutIndex];
        dropOutLocation.endx = field.dropOuts.endx[dropOutIndex];
        dropOutLocation.fieldLine = field.dropOuts.fieldLine[dropOutIndex];
        dropOutLocation.location = DropOutCorrect::Location::unknown;

        // Ignore dropouts outside the field's data
        if (dropOutLocation.fieldLine < 1 || dropOutLocation.fieldLine > videoParameters.fieldHeight) {
            continue;
        }

        // Is over correct mode selected?
        if (overCorrect) {
            // Here we deliberately extend the length of dropouts to ensure that the
            // correction captures as much as possible.  This is useful on heavily
            // damaged discs where drop-outs can 'slope' in and out fooling ld-decode's
            // detection mechanisms

            qint32 overCorrectionDots = 24;
            if (dropOutLocation.startx > overCorrectionDots) dropOutLocation.startx -= overCorrectionDots;
            else dropOutLocation.startx = 0;
            if (dropOutLocation.endx < videoParameters.fieldWidth - overCorrectionDots) dropOutLocation.endx += overCorrectionDots;
            else dropOutLocation.endx = videoParameters.fieldWidth;
        }

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
DropOutCorrect::Replacement DropOutCorrect::findReplacementLine(QVector<DropOutLocation> firstFieldDropouts, QVector<DropOutLocation> secondFieldDropouts,
                                                                qint32 dropOutIndex, bool isColourBurst, bool intraField)
{
    Replacement replacement;
    bool upFoundSource;
    bool downFoundSource;

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

    // Define the required step amount for colour burst replacement (to maintain line phase)
    qint32 stepAmount;
    if (!videoParameters.isSourcePal) {
        // PAL
        if (isColourBurst) stepAmount = 8;
        else stepAmount = 4;
    } else {
        if (isColourBurst) stepAmount = 4;
        else stepAmount = 2;
    }

    // Look for replacement lines
    qint32 upDistance = 0;
    qint32 downDistance = 0;
    qint32 upSourceLine = 0;
    qint32 downSourceLine = 0;
    qint32 firstFieldReplacementSourceLine = -1;
    qint32 secondFieldReplacementSourceLine = -1;

    // Examine the first field:
    upFoundSource = false;
    downFoundSource = false;

    // Look up the field for a replacement
    upSourceLine = firstFieldDropouts[dropOutIndex].fieldLine - stepAmount;
    while (upSourceLine > firstActiveFieldLine && upFoundSource == false) {
        // Is there a drop out on the proposed source line?
        upFoundSource = true;
        for (qint32 sourceIndex = 0; sourceIndex < firstFieldDropouts.size(); sourceIndex++) {
            if (firstFieldDropouts[sourceIndex].fieldLine == upSourceLine) {
                // Does the start<->end range overlap?
                if ((firstFieldDropouts[sourceIndex].endx - firstFieldDropouts[dropOutIndex].startx >= 0) && (firstFieldDropouts[dropOutIndex].endx - firstFieldDropouts[sourceIndex].startx >= 0)) {
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
   downSourceLine = firstFieldDropouts[dropOutIndex].fieldLine + stepAmount;
    while (downSourceLine < lastActiveFieldLine && downFoundSource == false) {
        // Is there a drop out on the proposed source line?
        downFoundSource = true;
        for (qint32 sourceIndex = 0; sourceIndex < firstFieldDropouts.size(); sourceIndex++) {
            if (firstFieldDropouts[sourceIndex].fieldLine == downSourceLine) {
                // Does the start<->end range overlap?
                if ((firstFieldDropouts[sourceIndex].endx - firstFieldDropouts[dropOutIndex].startx >= 0) && (firstFieldDropouts[dropOutIndex].endx - firstFieldDropouts[sourceIndex].startx >= 0)) {
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

    // Determine the replacement's distance from the dropout
    upDistance = firstFieldDropouts[dropOutIndex].fieldLine - upSourceLine;
    downDistance = downSourceLine - firstFieldDropouts[dropOutIndex].fieldLine;

    if (!upFoundSource && !downFoundSource) {
        // We didn't find a good replacement source in either direction
        firstFieldReplacementSourceLine = firstFieldDropouts[dropOutIndex].fieldLine - stepAmount;
    } else if (upFoundSource && !downFoundSource) {
        // We only found a replacement in the up direction
        firstFieldReplacementSourceLine = upSourceLine;
    } else if (!upFoundSource && downFoundSource) {
        // We only found a replacement in the down direction
        firstFieldReplacementSourceLine = downSourceLine;
    } else {
        // We found a replacement in both directions, pick the closest
        if (upDistance < downDistance)
        {
            firstFieldReplacementSourceLine = upSourceLine;
        } else {
            firstFieldReplacementSourceLine = downSourceLine;
        }
    }

    // Only check the second field for visible line replacements
    if (!isColourBurst) {
        // Examine the second field:
        upFoundSource = false;
        downFoundSource = false;

        // Look up the field for a replacement
        upSourceLine = firstFieldDropouts[dropOutIndex].fieldLine;
        while (upSourceLine > firstActiveFieldLine && upFoundSource == false) {
            // Is there a drop out on the proposed source line?
            upFoundSource = true;
            for (qint32 sourceIndex = 0; sourceIndex < secondFieldDropouts.size(); sourceIndex++) {
                if (secondFieldDropouts[sourceIndex].fieldLine == upSourceLine) {
                    if (secondFieldDropouts.size() < dropOutIndex && firstFieldDropouts.size() < sourceIndex) {
                        // Does the start<->end range overlap?
                        if ((firstFieldDropouts[sourceIndex].endx - secondFieldDropouts[dropOutIndex].startx >= 0) &&
                                (firstFieldDropouts[dropOutIndex].endx - secondFieldDropouts[sourceIndex].startx >= 0)) {
                            // Overlap
                            upSourceLine -= stepAmount;
                            upFoundSource = false;
                        } else {
                            upFoundSource = true; // Use the current source line
                            break;
                        }
                    } else {
                        upFoundSource = true; // Use the current source line
                        break;
                    }
                }
            }
        }
        if (!upFoundSource) upSourceLine = -1;

        // Look down the field for a replacement
       downSourceLine = firstFieldDropouts[dropOutIndex].fieldLine;
        while (downSourceLine < lastActiveFieldLine && downFoundSource == false) {
            // Is there a drop out on the proposed source line?
            downFoundSource = true;
            for (qint32 sourceIndex = 0; sourceIndex < secondFieldDropouts.size(); sourceIndex++) {
                if (secondFieldDropouts[sourceIndex].fieldLine == downSourceLine) {
                    if (secondFieldDropouts.size() < dropOutIndex && firstFieldDropouts.size() < sourceIndex) {
                        // Does the start<->end range overlap?
                        if ((firstFieldDropouts[sourceIndex].endx - secondFieldDropouts[dropOutIndex].startx >= 0) &&
                                (firstFieldDropouts[dropOutIndex].endx - secondFieldDropouts[sourceIndex].startx >= 0)) {
                            // Overlap
                            downSourceLine += stepAmount;
                            downFoundSource = false;
                        } else {
                            downFoundSource = true; // Use the current source line
                            break;
                        }
                    } else {
                        downFoundSource = true; // Use the current source line
                        break;
                    }
                }
            }
        }
        if (!downFoundSource) downSourceLine = -1;

        // Determine the replacement's distance from the dropout
        upDistance = firstFieldDropouts[dropOutIndex].fieldLine - upSourceLine;
        downDistance = downSourceLine - firstFieldDropouts[dropOutIndex].fieldLine;

        if (!upFoundSource && !downFoundSource) {
            // We didn't find a good replacement source in either direction
            secondFieldReplacementSourceLine = firstFieldDropouts[dropOutIndex].fieldLine - stepAmount;
        } else if (upFoundSource && !downFoundSource) {
            // We only found a replacement in the up direction
            secondFieldReplacementSourceLine = upSourceLine;
        } else if (!upFoundSource && downFoundSource) {
            // We only found a replacement in the down direction
            secondFieldReplacementSourceLine = downSourceLine;
        } else {
            // We found a replacement in both directions, pick the closest
            if (upDistance < downDistance)
            {
                secondFieldReplacementSourceLine = upSourceLine;
            } else {
                secondFieldReplacementSourceLine = downSourceLine;
            }
        }
    }

    // Determine which field we should take the replacement data from
    if (!isColourBurst) {
        qDebug() << "Visible video dropout on line" << firstFieldDropouts[dropOutIndex].fieldLine;
        qDebug() << "First field nearest replacement =" << firstFieldReplacementSourceLine;
        qDebug() << "Second field nearest replacement =" << secondFieldReplacementSourceLine;
    } else {
        qDebug() << "Colourburst dropout on line" << firstFieldDropouts[dropOutIndex].fieldLine;
        qDebug() << "First field nearest replacement =" << firstFieldReplacementSourceLine;
    }

    if (!isColourBurst) {
        if (!intraField) {
            // Use intra or inter-field
            if (firstFieldReplacementSourceLine < secondFieldReplacementSourceLine) {
                replacement.isFirstField = true;
                replacement.fieldLine = firstFieldReplacementSourceLine;
                qDebug() << "Using data from the first field as a replacement (intra-field)";
            } else {
                replacement.isFirstField = false;
                replacement.fieldLine = secondFieldReplacementSourceLine;
                qDebug() << "Using data from the second field as a replacement (inter-field)";
            }
        } else {
            // Force intra-field only
            replacement.isFirstField = true;
            replacement.fieldLine = firstFieldReplacementSourceLine;
            qDebug() << "Using data from the first field as a replacement (forced intra-field)";
        }
    } else {
        // Always use the same field for colour burst replacement
        replacement.isFirstField = true;
        replacement.fieldLine = firstFieldReplacementSourceLine;
    }

    return replacement;
}

// Correct a dropout by copying data from a replacement line.
void DropOutCorrect::correctDropOut(const DropOutLocation &dropOut, const Replacement &replacement, QByteArray &targetField, const QByteArray &sourceField)
{
    for (qint32 pixel = dropOut.startx; pixel < dropOut.endx; pixel++) {
        if (dropOut.fieldLine > 2) {
            *(targetField.data() + (((dropOut.fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2))) =
                    *(sourceField.data() + (((replacement.fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2)));
            *(targetField.data() + (((dropOut.fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2) + 1)) =
                    *(sourceField.data() + (((replacement.fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2) + 1));
        }
    }
}
