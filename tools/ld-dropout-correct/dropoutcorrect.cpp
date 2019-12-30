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
#include "filters.h"

DropOutCorrect::DropOutCorrect(QAtomicInt& _abort, CorrectorPool& _correctorPool, QObject *parent)
    : QThread(parent), abort(_abort), correctorPool(_correctorPool)
{
}

void DropOutCorrect::run()
{
    // Variables for getInputFrame
    qint32 frameNumber;
    QVector<qint32> firstFieldSeqNo;
    QVector<qint32> secondFieldSeqNo;
    QVector<QByteArray> firstSourceField;
    QVector<QByteArray> secondSourceField;
    QVector<LdDecodeMetaData::Field> firstFieldMetadata;
    QVector<LdDecodeMetaData::Field> secondFieldMetadata;
    bool reverse, intraField, overCorrect;
    QVector<qint32> minVbiForSource;
    QVector<qint32> maxVbiForSource;

    while(!abort) {
        // Get the next field to process from the input file
        if (!correctorPool.getInputFrame(frameNumber, firstFieldSeqNo, firstSourceField, firstFieldMetadata,
                                       secondFieldSeqNo, secondSourceField, secondFieldMetadata,
                                       videoParameters, reverse, intraField, overCorrect,
                                       minVbiForSource, maxVbiForSource)) {
            // No more input fields -- exit
            break;
        }
        qDebug() << "DropOutCorrect::process(): Got sequential frame number" << frameNumber << "with" <<firstFieldSeqNo.size() << "sources available";

        // Copy the input frames' data to the target frames.
        // We'll use these both as source and target during correction, which
        // is OK because we're careful not to copy data from another dropout.
        QByteArray firstFieldData = firstSourceField[0];
        QByteArray secondFieldData = secondSourceField[0];

        // Check if the frame contains drop-outs
        if (firstFieldMetadata[0].dropOuts.startx.empty() && secondFieldMetadata[0].dropOuts.startx.empty()) {
            // No correction required...
            qDebug() << "DropOutCorrect::process(): Skipping fields [" <<
                        firstFieldSeqNo[0] << "/" << secondFieldSeqNo[0] << "]";
        } else {
            // Perform correction...
            qDebug().nospace() << "DropOutCorrect::process(): Correcting fields [" <<
                        firstFieldSeqNo[0] << "/" << secondFieldSeqNo[0] << "] containing " <<
                        firstFieldMetadata[0].dropOuts.startx.size() + secondFieldMetadata[0].dropOuts.startx.size() <<
                        " drop-outs";

            // Analyse the drop out locations in the first field
            QVector<DropOutLocation> firstFieldDropouts;
            if (firstFieldMetadata[0].dropOuts.startx.size() > 0) firstFieldDropouts = setDropOutLocations(populateDropoutsVector(firstFieldMetadata[0], overCorrect));

            // Analyse the drop out locations in the second field
            QVector<DropOutLocation> secondFieldDropouts;
            if (secondFieldMetadata[0].dropOuts.startx.size() > 0) secondFieldDropouts = setDropOutLocations(populateDropoutsVector(secondFieldMetadata[0], overCorrect));

            // Correct the first field
            correctField(firstFieldDropouts, secondFieldDropouts, firstFieldData, secondFieldData, true, intraField);

            // Correct the second field
            correctField(secondFieldDropouts, firstFieldDropouts, secondFieldData, firstFieldData, false, intraField);
        }

        // Return the processed fields
        correctorPool.setOutputFrame(frameNumber, firstFieldData, secondFieldData, firstFieldSeqNo[0], secondFieldSeqNo[0]);
    }
}

// Correct dropouts within one field
void DropOutCorrect::correctField(const QVector<DropOutLocation> &thisFieldDropouts,
                                  const QVector<DropOutLocation> &otherFieldDropouts,
                                  QByteArray &thisFieldData, const QByteArray &otherFieldData,
                                  bool thisFieldIsFirst, bool intraField)
{
    for (qint32 dropoutIndex = 0; dropoutIndex < thisFieldDropouts.size(); dropoutIndex++) {
        Replacement replacement, chromaReplacement;

        // Is the current dropout in the colour burst?
        if (thisFieldDropouts[dropoutIndex].location == Location::colourBurst) {
            replacement = findReplacementLine(thisFieldDropouts, otherFieldDropouts,
                                              dropoutIndex, thisFieldIsFirst, true,
                                              true, intraField);
        }

        // Is the current dropout in the visible video line?
        if (thisFieldDropouts[dropoutIndex].location == Location::visibleLine) {
            // Find separate replacements for luma and chroma
            replacement = findReplacementLine(thisFieldDropouts, otherFieldDropouts,
                                              dropoutIndex, thisFieldIsFirst, false,
                                              false, intraField);
            chromaReplacement = findReplacementLine(thisFieldDropouts, otherFieldDropouts,
                                                    dropoutIndex, thisFieldIsFirst, true,
                                                    false, intraField);
        }

        // Correct the data
        correctDropOut(thisFieldDropouts[dropoutIndex], replacement, chromaReplacement, thisFieldData, otherFieldData);
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
        if (dropOutLocation.fieldLine < 1 || dropOutLocation.fieldLine > videoParameters[0].fieldHeight) {
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
            if (dropOutLocation.endx < videoParameters[0].fieldWidth - overCorrectionDots) dropOutLocation.endx += overCorrectionDots;
            else dropOutLocation.endx = videoParameters[0].fieldWidth;
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
            if (dropOuts[index].startx <= videoParameters[0].colourBurstEnd) {
                dropOuts[index].location = Location::colourBurst;

                // Does the drop-out end in the colour burst area?
                if (dropOuts[index].endx > videoParameters[0].colourBurstEnd) {
                    // Split the drop-out in two
                    DropOutLocation tempDropOut;
                    tempDropOut.startx = videoParameters[0].colourBurstEnd + 1;
                    tempDropOut.endx = dropOuts[index].endx;
                    tempDropOut.fieldLine = dropOuts[index].fieldLine;
                    tempDropOut.location = Location::colourBurst;
                    dropOuts.append(tempDropOut);

                    // Shorten the original drop out
                    dropOuts[index].endx = videoParameters[0].colourBurstEnd;

                    splitCount++;
                }
            }

            // Does the drop-out start in the active video area?
            // Note: Here we use the colour burst end as the active video start (to prevent a case where the
            // drop out begins between the colour burst level end and active video start and would go undetected)
            else if (dropOuts[index].startx > videoParameters[0].colourBurstEnd && dropOuts[index].startx <= videoParameters[0].activeVideoEnd) {
                dropOuts[index].location = Location::visibleLine;

                // Does the drop-out end in the active video area?
                if (dropOuts[index].endx > videoParameters[0].activeVideoEnd) {
                    // No need to split as we don't care about the sync area

                    // Shorten the original drop out
                    dropOuts[index].endx = videoParameters[0].activeVideoEnd;

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
                                                                qint32 dropOutIndex, bool thisFieldIsFirst, bool matchChromaPhase,
                                                                bool isColourBurst, bool intraField)
{
    // Determine the first and last active scan line based on the source format
    qint32 firstActiveFieldLine;
    qint32 lastActiveFieldLine;
    if (videoParameters[0].isSourcePal) {
        firstActiveFieldLine = 22;
        lastActiveFieldLine = 308;
    } else {
        firstActiveFieldLine = 20;
        lastActiveFieldLine = 259;
    }

    // Define the minimum step size to use when searching for replacement
    // lines, and the offset to the nearest replacement line in the other
    // field.
    qint32 stepAmount, otherFieldOffset;
    if (!matchChromaPhase) {
        // We're not trying to match the chroma phase, so any line will do.
        stepAmount = 1;
        otherFieldOffset = -1;
    } else if (videoParameters[0].isSourcePal) {
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

        // First field lines 1-313 are PAL line numbers 1-313.
        // Second field lines 1-312 are PAL line numbers 314-625.
        // Moving from first field line N to second field line N would give 313
        // lines = (nearly) 90 degrees phase shift; move by 310 lines to N-3 to
        // get (nearly) 0 degrees.
        if (thisFieldIsFirst) {
            otherFieldOffset = -3;
        } else {
            otherFieldOffset = -1;
        }
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

        // First field lines 1-263 are NTSC line numbers 1-263.
        // Second field lines 1-262 are NTSC line numbers 264-525.
        // Moving from first field line N to second field line N would give 263
        // lines = 180 degrees phase shift; move by 262 lines to N-1 to get 0
        // degrees.
        otherFieldOffset = -1;
    }

    // Look for potential replacement lines
    QVector<DropOutCorrect::Replacement> candidates;

    // Examine this field:

    // Look up the field for a replacement
    findPotentialReplacementLine(thisFieldDropouts, dropOutIndex,
                                 thisFieldDropouts, true, 0, -stepAmount,
                                 firstActiveFieldLine, lastActiveFieldLine,
                                 candidates);

    // Look down the field for a replacement
    findPotentialReplacementLine(thisFieldDropouts, dropOutIndex,
                                 thisFieldDropouts, true, stepAmount, stepAmount,
                                 firstActiveFieldLine, lastActiveFieldLine,
                                 candidates);

    // Only check the other field for visible line replacements
    if (!isColourBurst && !intraField) {
        // Examine the other field:

        // Look up the field for a replacement
        findPotentialReplacementLine(thisFieldDropouts, dropOutIndex,
                                     otherFieldDropouts, false, otherFieldOffset, -stepAmount,
                                     firstActiveFieldLine, lastActiveFieldLine,
                                     candidates);

        // Look down the field for a replacement
        findPotentialReplacementLine(thisFieldDropouts, dropOutIndex,
                                     otherFieldDropouts, false, otherFieldOffset + stepAmount, stepAmount,
                                     firstActiveFieldLine, lastActiveFieldLine,
                                     candidates);
    }

    qDebug() << (isColourBurst ? "Colourburst" : "Visible video") << "dropout on line"
             << thisFieldDropouts[dropOutIndex].fieldLine << "of" << (thisFieldIsFirst ? "first" : "second") << "field";

    // If no candidate is found, return no replacement
    Replacement replacement;

    if (!candidates.empty()) {
        // Find the candidate with the lowest spatial distance from the dropout
        qint32 lowestDistance = 1000000;
        for (const Replacement &candidate: candidates) {
            // Work out the corresponding output frame line numbers.
            // The first field (in a .tbc, for both PAL and NTSC) contains the top frame line.
            const qint32 dropoutFrameLine = (2 * thisFieldDropouts[dropOutIndex].fieldLine) + (thisFieldIsFirst ? 0 : 1);
            const qint32 sourceFrameLine = (2 * candidate.fieldLine) + (candidate.isSameField ? (thisFieldIsFirst ? 0 : 1)
                                                                                              : (thisFieldIsFirst ? 1 : 0));

            const qint32 distance = qAbs(dropoutFrameLine - sourceFrameLine);
            qDebug() << (candidate.isSameField ? "This" : "Other") << "field replacement candidate line"
                     << candidate.fieldLine << "distance" << distance;

            if (distance < lowestDistance) {
                replacement = candidate;
                lowestDistance = distance;
            }
        }
    }

    return replacement;
}

// Given a dropout, scan through a source field for the nearest replacement line that doesn't have overlapping dropouts.
// Adds a Replacement to candidates if one was found.
void DropOutCorrect::findPotentialReplacementLine(const QVector<DropOutLocation> &targetDropouts, qint32 targetIndex,
                                                  const QVector<DropOutLocation> &sourceDropouts, bool isSameField,
                                                  qint32 sourceOffset, qint32 stepAmount,
                                                  qint32 firstActiveFieldLine, qint32 lastActiveFieldLine,
                                                  QVector<Replacement> &candidates)
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
            Replacement replacement;
            replacement.isSameField = isSameField;
            replacement.fieldLine = sourceLine;
            candidates.push_back(replacement);
            return;
        }
    }
}

// Correct a dropout by copying data from a replacement line.
void DropOutCorrect::correctDropOut(const DropOutLocation &dropOut,
                                    const Replacement &replacement, const Replacement &chromaReplacement,
                                    QByteArray &thisFieldData, const QByteArray &otherFieldData)
{
    if (replacement.fieldLine == -1) {
        // No correction needed
        return;
    }

    const quint16 *sourceLine = reinterpret_cast<const quint16 *>(replacement.isSameField ? thisFieldData.data()
                                                                                          : otherFieldData.data())
                                + ((replacement.fieldLine - 1) * videoParameters[0].fieldWidth);
    quint16 *targetLine = reinterpret_cast<quint16 *>(thisFieldData.data())
                          + ((dropOut.fieldLine - 1) * videoParameters[0].fieldWidth);

    if (chromaReplacement.fieldLine == -1) {
        // No separate chroma replacement; just copy the whole signal

        for (qint32 pixel = dropOut.startx; pixel < dropOut.endx; pixel++) {
            targetLine[pixel] = sourceLine[pixel];
        }
    } else {
        // Combine low frequencies (mostly luma) from replacement with high
        // frequencies (mostly chroma) from chromaReplacement. As this is only
        // a 1D filter, it won't achieve very good separation, but it's good
        // enough for the purposes of replacing a dropout.

        Filters filters;
        QVector<quint16> lineBuf(videoParameters[0].fieldWidth);
        auto filterLineBuf = [&] {
            if (videoParameters[0].isSourcePal) {
                filters.palLumaFirFilter(lineBuf.data(), lineBuf.size());
            } else {
                filters.ntscLumaFirFilter(lineBuf.data(), lineBuf.size());
            }
        };

        // Extract LF from replacement
        for (qint32 pixel = 0; pixel < videoParameters[0].fieldWidth; pixel++) {
            lineBuf[pixel] = sourceLine[pixel];
        }
        filterLineBuf();
        for (qint32 pixel = dropOut.startx; pixel < dropOut.endx; pixel++) {
            targetLine[pixel] = lineBuf[pixel];
        }

        // Extract HF from chromaReplacement (by extracting LF, then subtracting from the original)
        const quint16 *chromaLine = reinterpret_cast<const quint16 *>(chromaReplacement.isSameField ? thisFieldData.data()
                                                                                                    : otherFieldData.data())
                                    + ((chromaReplacement.fieldLine - 1) * videoParameters[0].fieldWidth);
        for (qint32 pixel = 0; pixel < videoParameters[0].fieldWidth; pixel++) {
            lineBuf[pixel] = chromaLine[pixel];
        }
        filterLineBuf();
        for (qint32 pixel = dropOut.startx; pixel < dropOut.endx; pixel++) {
            targetLine[pixel] += chromaLine[pixel] - lineBuf[pixel];
        }
    }
}
