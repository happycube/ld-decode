/************************************************************************

    dropoutcorrect.cpp

    ld-dropout-correct - Dropout correction for ld-decode
    Copyright (C) 2018-2019 Simon Inns
    Copyright (C) 2019 Adam Sampson

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
                    firstFieldReplacementLines[dropoutIndex].fieldLine = -1;

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
                    if (firstFieldReplacementLines[dropoutIndex].fieldLine == -1) {
                        // Doesn't need correcting
                    } else if (firstFieldReplacementLines[dropoutIndex].isSameField) {
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
                    secondFieldReplacementLines[dropoutIndex].fieldLine = -1;

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
                    if (secondFieldReplacementLines[dropoutIndex].fieldLine == -1) {
                        // Doesn't need correcting
                    } else if (secondFieldReplacementLines[dropoutIndex].isSameField) {
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
DropOutCorrect::Replacement DropOutCorrect::findReplacementLine(const QVector<DropOutLocation> &thisFieldDropouts,
                                                                const QVector<DropOutLocation> &otherFieldDropouts,
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

    // Define the minimum step size to use when searching for replacement lines.
    //
    // At present the replacement line must match exactly in terms of chroma
    // encoding; we could use closer lines if we were willing to shift samples
    // horizontally to match the chroma encoding (or discard the chroma
    // entirely, as analogue LaserDisc players do).
    qint32 stepAmount, otherFieldOffset;
    if (videoParameters.isSourcePal) {
        // For PAL: [Poynton ch44 p529]
        //
        // - Subcarrier has 283.7516 cycles per line, so there's a (nearly) 90
        //   degree phase shift between adjacent field lines.
        // - Colourburst is +135 degrees and -135 degrees from the subcarrier
        //   on alternate field lines.
        // - The V-switch causes the V component to be inverted on alternate
        //   field lines.
        //
        // So the nearest line we can use which has the same subcarrier phase,
        // colourburst phase and V-switch state is 4 field lines away.
        stepAmount = 4;

        // Moving to the same line in the other field leaves us with the same
        // phase relationship.
        otherFieldOffset = 1;
    } else {
        // For NTSC: [Poynton ch42 p511]
        //
        // - Subcarrier has 227.5 cycles per line, so there's a 180 degree
        //   phase shift between adjacent field lines.
        // - Colourburst is always 180 degrees from the subcarrier.
        //
        // So the nearest line we can use which has the same subcarrier phase
        // and colourburst phase is 2 field lines away.
        stepAmount = 2;

        // Moving to the same line in the other field gives 180 degree phase
        // shift.
        otherFieldOffset = -1;
    }

    // Look for replacement lines
    qint32 upDistance = 0;
    qint32 downDistance = 0;
    qint32 upSourceLine = 0;
    qint32 downSourceLine = 0;
    qint32 thisFieldReplacementSourceLine = -1;
    qint32 otherFieldReplacementSourceLine = -1;

    // Examine the first field:

    // Look up the field for a replacement
    upSourceLine = findPotentialReplacementLine(thisFieldDropouts, dropOutIndex,
                                                thisFieldDropouts, 0, -stepAmount,
                                                firstActiveFieldLine, lastActiveFieldLine);
    upFoundSource = (upSourceLine != -1);

    // Look down the field for a replacement
    downSourceLine = findPotentialReplacementLine(thisFieldDropouts, dropOutIndex,
                                                  thisFieldDropouts, stepAmount, stepAmount,
                                                  firstActiveFieldLine, lastActiveFieldLine);
    downFoundSource = (downSourceLine != -1);

    // Determine the replacement's distance from the dropout
    upDistance = thisFieldDropouts[dropOutIndex].fieldLine - upSourceLine;
    downDistance = downSourceLine - thisFieldDropouts[dropOutIndex].fieldLine;

    if (!upFoundSource && !downFoundSource) {
        // We didn't find a good replacement source in either direction -- don't correct it
        thisFieldReplacementSourceLine = thisFieldDropouts[dropOutIndex].fieldLine;
    } else if (upFoundSource && !downFoundSource) {
        // We only found a replacement in the up direction
        thisFieldReplacementSourceLine = upSourceLine;
    } else if (!upFoundSource && downFoundSource) {
        // We only found a replacement in the down direction
        thisFieldReplacementSourceLine = downSourceLine;
    } else {
        // We found a replacement in both directions, pick the closest
        if (upDistance < downDistance)
        {
            thisFieldReplacementSourceLine = upSourceLine;
        } else {
            thisFieldReplacementSourceLine = downSourceLine;
        }
    }

    // Only check the second field for visible line replacements
    if (!isColourBurst) {
        // Examine the second field:

        // Look up the field for a replacement
        upSourceLine = findPotentialReplacementLine(thisFieldDropouts, dropOutIndex,
                                                    otherFieldDropouts, otherFieldOffset, -stepAmount,
                                                    firstActiveFieldLine, lastActiveFieldLine);
        upFoundSource = (upSourceLine != -1);

        // Look down the field for a replacement
        downSourceLine = findPotentialReplacementLine(thisFieldDropouts, dropOutIndex,
                                                      otherFieldDropouts, otherFieldOffset + stepAmount, stepAmount,
                                                      firstActiveFieldLine, lastActiveFieldLine);
        downFoundSource = (downSourceLine != -1);

        // Determine the replacement's distance from the dropout
        upDistance = thisFieldDropouts[dropOutIndex].fieldLine - upSourceLine;
        downDistance = downSourceLine - thisFieldDropouts[dropOutIndex].fieldLine;

        if (!upFoundSource && !downFoundSource) {
            // We didn't find a good replacement source in either direction -- don't correct it
            otherFieldReplacementSourceLine = thisFieldDropouts[dropOutIndex].fieldLine;
        } else if (upFoundSource && !downFoundSource) {
            // We only found a replacement in the up direction
            otherFieldReplacementSourceLine = upSourceLine;
        } else if (!upFoundSource && downFoundSource) {
            // We only found a replacement in the down direction
            otherFieldReplacementSourceLine = downSourceLine;
        } else {
            // We found a replacement in both directions, pick the closest
            if (upDistance < downDistance)
            {
                otherFieldReplacementSourceLine = upSourceLine;
            } else {
                otherFieldReplacementSourceLine = downSourceLine;
            }
        }
    }

    // Determine which field we should take the replacement data from
    if (!isColourBurst) {
        qDebug() << "Visible video dropout on line" << thisFieldDropouts[dropOutIndex].fieldLine;
        qDebug() << "This field nearest replacement =" << thisFieldReplacementSourceLine;
        qDebug() << "Other field nearest replacement =" << otherFieldReplacementSourceLine;
    } else {
        qDebug() << "Colourburst dropout on line" << thisFieldDropouts[dropOutIndex].fieldLine;
        qDebug() << "This field nearest replacement =" << thisFieldReplacementSourceLine;
    }

    if (!isColourBurst) {
        if (!intraField) {
            // Use intra or inter-field
            const qint32 thisFieldDistance = qAbs(thisFieldReplacementSourceLine - thisFieldDropouts[dropOutIndex].fieldLine);
            const qint32 otherFieldDistance = qAbs(otherFieldReplacementSourceLine - thisFieldDropouts[dropOutIndex].fieldLine);
            if (thisFieldDistance < otherFieldDistance) {
                replacement.isSameField = true;
                replacement.fieldLine = thisFieldReplacementSourceLine;
                qDebug() << "Using data from this field as a replacement (intra-field)";
            } else {
                replacement.isSameField = false;
                replacement.fieldLine = otherFieldReplacementSourceLine;
                qDebug() << "Using data from the other field as a replacement (inter-field)";
            }
        } else {
            // Force intra-field only
            replacement.isSameField = true;
            replacement.fieldLine = thisFieldReplacementSourceLine;
            qDebug() << "Using data from this field as a replacement (forced intra-field)";
        }
    } else {
        // Always use the same field for colour burst replacement
        replacement.isSameField = true;
        replacement.fieldLine = thisFieldReplacementSourceLine;
    }

    return replacement;
}

// Given a dropout, scan through a source field for the nearest replacement line that doesn't have overlapping dropouts.
// Returns the line number, or -1 if nothing was found.
qint32 DropOutCorrect::findPotentialReplacementLine(const QVector<DropOutLocation> &targetDropouts, qint32 targetIndex,
                                                    const QVector<DropOutLocation> &sourceDropouts, qint32 sourceOffset, qint32 stepAmount,
                                                    qint32 firstActiveFieldLine, qint32 lastActiveFieldLine)
{
    qint32 sourceLine = targetDropouts[targetIndex].fieldLine + sourceOffset;
    while (sourceLine >= firstActiveFieldLine && sourceLine < lastActiveFieldLine) {
        // Is there a dropout that overlaps the one we're trying to replace?
        bool hasOverlap = false;
        for (qint32 sourceIndex = 0; sourceIndex < sourceDropouts.size(); sourceIndex++) {
            if (sourceDropouts[sourceIndex].fieldLine == sourceLine &&
                (targetDropouts[targetIndex].endx - sourceDropouts[sourceIndex].startx) >= 0 &&
                (sourceDropouts[sourceIndex].endx - targetDropouts[targetIndex].startx) >= 0) {
                // Overlap -- can't use this line
                sourceLine += stepAmount;
                hasOverlap = true;
                break;
            }
        }
        if (!hasOverlap) {
            // No overlaps -- we can use this line
            return sourceLine;
        }
    }

    // No non-overlapping line found
    return -1;
}

// Correct a dropout by copying data from a replacement line.
void DropOutCorrect::correctDropOut(const DropOutLocation &dropOut, const Replacement &replacement, QByteArray &targetField, const QByteArray &sourceField)
{
    for (qint32 pixel = dropOut.startx; pixel < dropOut.endx; pixel++) {
        *(targetField.data() + (((dropOut.fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2))) =
                *(sourceField.data() + (((replacement.fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2)));
        *(targetField.data() + (((dropOut.fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2) + 1)) =
                *(sourceField.data() + (((replacement.fieldLine - 1) * videoParameters.fieldWidth * 2) + (pixel * 2) + 1));
    }
}
