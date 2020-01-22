/************************************************************************

    discmapper.cpp

    ld-discmap - TBC and VBI alignment and correction
    Copyright (C) 2019-2020 Simon Inns

    This file is part of ld-decode-tools.

    ld-discmap is free software: you can redistribute it and/or
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

#include "discmapper.h"

DiscMapper::DiscMapper()
{
    // This space for sale; please enquire within
}

// Method to perform disc mapping process
bool DiscMapper::process(QFileInfo _inputFileInfo, QFileInfo _inputMetadataFileInfo,
                         QFileInfo _outputFileInfo, bool _reverse, bool _mapOnly)
{
    inputFileInfo = _inputFileInfo;
    inputMetadataFileInfo = _inputMetadataFileInfo;
    outputFileInfo = _outputFileInfo;
    reverse = _reverse;
    mapOnly = _mapOnly;

    // Create the source metadata object
    qInfo().noquote() << "Processing input metadata for" << inputFileInfo.filePath();
    DiscMap discMap(inputMetadataFileInfo, reverse);
    if (!discMap.valid()) {
        qInfo() << "Could not process TBC metadata successfully - cannot map this disc";
        return false;
    }
    qDebug() << discMap;

    // Remove lead-in and lead-out frames from the map
    removeLeadInOut(discMap);

    // Detect and correct bad VBI frame numbers using sequence analysis
    correctVbiFrameNumbersUsingSequenceAnalysis(discMap);

    // Detect and remove duplicated frames (does not process pull-down frames)
    removeDuplicateNumberedFrames(discMap);

    // Reorder the frames according to VBI frame number order
    reorderFrames(discMap);

    // Verify that there are no frames without frame numbers in the map
    // (except frames marked as pulldown)
    if (!verifyFrameNumberPresence(discMap)) {
        qInfo() << "Verification failed - disc mapping has failed";
        return false;
    }

    // Pad any gaps in the sequential disc map
    padDiscMap(discMap);

    // TODO: Need additional step to spot repeated pull-down frames for NTSC CLV only

    // Remove any frames after lead-out (like on the Almanac side 1)

    return true;
}

// Method to remove lead in and lead out frames from the map
void DiscMapper::removeLeadInOut(DiscMap &discMap)
{
    qint32 leadInOutCounter = 0;
    for (qint32 frameNumber = 0; frameNumber < discMap.numberOfFrames(); frameNumber++) {
        if (discMap.isLeadInOut(frameNumber)) {
            discMap.setMarkedForDeletion(frameNumber);
            leadInOutCounter++;
        }
    }

    qInfo() << "Removing" << leadInOutCounter << "frames marked as lead in/out";
    discMap.flush();
}

// Method to find and correct bad VBI numbers using sequence analysis
void DiscMapper::correctVbiFrameNumbersUsingSequenceAnalysis(DiscMap &discMap)
{
    qInfo() << "Correcting frame numbers using sequence analysis";

    qint32 scanDistance = 10;
    qint32 corrections = 0;

    for (qint32 frameNumber = 0; frameNumber < discMap.numberOfFrames() - scanDistance; frameNumber++) {
        if (!discMap.isPulldown(frameNumber)) {
            qint32 startOfSequence = discMap.vbiFrameNumber(frameNumber);
            qint32 expectedIncrement = 1;

            QVector<bool> vbiGood;
            vbiGood.resize(scanDistance);
            bool sequenceIsGood = true;

            for (qint32 i = 0; i < scanDistance; i++) {
                if (!discMap.isPulldown(frameNumber + i + 1)) {
                    if ((discMap.vbiFrameNumber(frameNumber + i + 1) == startOfSequence + expectedIncrement) || (discMap.isPulldown(frameNumber + i + 1))) {
                        // Sequence is good
                        sequenceIsGood = true;
                    } else {
                        // Sequence is bad
                        sequenceIsGood = false;
                    }

                    // Set the good/bad flag and increase the frame number increment
                    if (sequenceIsGood) vbiGood[i] = true; else vbiGood[i] = false;
                    expectedIncrement++;
                } else {
                    // Set the good/bad flag but don't increase the frame number
                    // increment due to the pulldown
                    if (sequenceIsGood) vbiGood[i] = true; else vbiGood[i] = false;
                }
            }

            // Did the check pass?
            qint32 count = 0;
            for (qint32 i = 0; i < scanDistance; i++) {
                if (vbiGood[i]) count++;
            }

            // If any frame numbers were bad, check does not pass
            if (count != scanDistance) {
                // Do we have at least 2 good frame numbers (which are not pulldowns) before the error
                qint32 check1 = 0;
                for (qint32 i = 0; i < scanDistance; i++) {
                    if (vbiGood[i] && !discMap.isPulldown(frameNumber + i + 1)) check1++;
                    else if (!discMap.isPulldown(frameNumber + i + 1)) break;
                }

                // and another 2 good frame numbers (which are not pulldowns) after the error?
                qint32 check2 = 0;
                for (qint32 i = scanDistance - 1; i >= 0; i--) {
                    if (vbiGood[i] && !discMap.isPulldown(frameNumber + i + 1)) check2++;
                    else if (!discMap.isPulldown(frameNumber + i + 1)) break;
                }

                if (check1 >= 2 && check2 >= 2) {
                    // We have enough leading and trailing good frame numbers to be sure we are looking
                    // at a real error.  Now correct the error
                    qDebug() << "Broken VBI frame number sequence detected:";

                    bool inError = false;
                    expectedIncrement = 1;
                    for (qint32 i = 0; i < scanDistance; i++) {
                        if (!vbiGood[i]) {
                            inError = true;
                            // Only correct non-pulldown frame numbers
                            if (!discMap.isPulldown(frameNumber + i + 1)) {
                                // Ensure this is an error, not a repeating frame
                                if (discMap.vbiFrameNumber(frameNumber + i + 1) != discMap.vbiFrameNumber(frameNumber + i)) {
                                    qDebug() << "  Position BAD   " << i << "Seq." << discMap.seqFrameNumber(frameNumber + i + 1) <<
                                                "VBI was" << discMap.vbiFrameNumber(frameNumber + i + 1) << "now" << (startOfSequence + expectedIncrement);
                                    discMap.setVbiFrameNumber(frameNumber + i + 1, startOfSequence + expectedIncrement);
                                    if (!discMap.isPulldown(frameNumber + i + 1)) expectedIncrement++;
                                    corrections++;
                                } else {
                                    // Repeating frame
                                    qDebug() << "  Position REPEAT" << i << "Seq." << discMap.seqFrameNumber(frameNumber + i + 1) <<
                                                "VBI" << discMap.vbiFrameNumber(frameNumber + i + 1);
                                    qDebug() << "  Ignoring sequence break as frame is repeating rather than out of sequence";

                                    // If we have a repeat, this probably isn't a sequence issue, so we give up
                                    if (inError) break;
                                }
                            } else {
                                // Out of sequence frame number
                                if (!discMap.isPulldown(frameNumber + i + 1))
                                    qDebug() << "  Position BAD   " << i << "Seq." << discMap.seqFrameNumber(frameNumber + i + 1) <<
                                                "VBI" << discMap.vbiFrameNumber(frameNumber + i + 1);
                                else qDebug() << "  Position BAD   " << i << "Seq." << discMap.seqFrameNumber(frameNumber + i + 1) <<
                                                 "VBI pulldown";

                                if (!discMap.isPulldown(frameNumber + i + 1)) expectedIncrement++;
                            }
                        } else {
                            // In sequence frame number
                            if (!discMap.isPulldown(frameNumber + i + 1))
                                qDebug() << "  Position GOOD  " << i << "Seq." << discMap.seqFrameNumber(frameNumber + i + 1) <<
                                            "VBI" << discMap.vbiFrameNumber(frameNumber + i + 1);
                            else qDebug() << "  Position GOOD  " << i << "Seq." << discMap.seqFrameNumber(frameNumber + i + 1) <<
                                             "VBI pulldown";

                            if (!discMap.isPulldown(frameNumber + i + 1)) expectedIncrement++;

                            // Stop once we get a good frame after the bad ones
                            if (inError) break;
                        }
                    }
                }
            }
        }
    }

    qInfo() << "Sequence analysis corrected" << corrections << "frame numbers";
}

// Method to find and remove repeating frames
void DiscMapper::removeDuplicateNumberedFrames(DiscMap &discMap)
{
    qInfo() << "Searching for duplicate frames";
    QVector<qint32> uniqueVbis;
    QVector<qint32> duplicatedList;
    for (qint32 frameNumber = 0; frameNumber < discMap.numberOfFrames(); frameNumber++) {
        // Check the current VBI frame number is valid
        if (discMap.vbiFrameNumber(frameNumber) != -1) {
            // Is the current VBI number already in the unique VBI vector?
            bool alreadyOnUniqueList = false;
            for (qint32 i = 0; i < uniqueVbis.size(); i++) {
                if (uniqueVbis[i] == discMap.vbiFrameNumber(frameNumber)) {
                    // We have seen this VBI before, add it to the repeatList if it's not already there
                    alreadyOnUniqueList = true;
                    break;
                }
            }

            if (!alreadyOnUniqueList) {
                // VBI is not already on the unique VBI list... add it
                uniqueVbis.append(discMap.vbiFrameNumber(frameNumber));
            } else {
                // Current VBI is already on the unique list, so it's a repeat
                duplicatedList.append(discMap.vbiFrameNumber(frameNumber));
                qDebug() << "Seq. frame" << discMap.seqFrameNumber(frameNumber) << "with VBI" << discMap.vbiFrameNumber(frameNumber) << "is a duplicate";
            }
        }
    }
    qDebug() << "There are" << uniqueVbis.size() << "unique VBI frame numbers in the disc map of" << discMap.numberOfFrames() << "frames";

    // Now process the duplicate list
    qInfo() << "Processing the list of duplicated frames";
    if (duplicatedList.size() > 0) {
        // Sort the vector of repeated VBIs and remove duplicate VBI frame numbers
        qint32 totalRepeats = duplicatedList.size();
        std::sort(duplicatedList.begin(), duplicatedList.end());
        duplicatedList.erase(std::unique(duplicatedList.begin(), duplicatedList.end()), duplicatedList.end());

        qInfo() << "Found" << duplicatedList.size() << "duplicated VBI frame numbers across" << totalRepeats << "frames";

        // Process each unique duplicated frame number in turn
        for (qint32 repeatCounter = 0; repeatCounter < duplicatedList.size(); repeatCounter++) {
            // Find the best quality repeating frame
            qreal bestQuality = -1;
            qint32 bestFrame = -1;
            for (qint32 frameNumber = 0; frameNumber < discMap.numberOfFrames(); frameNumber++) {
                if (discMap.vbiFrameNumber(frameNumber) == duplicatedList[repeatCounter]) {
                    if (discMap.frameQuality(frameNumber) > bestQuality) {
                        bestQuality = discMap.frameQuality(frameNumber);
                        bestFrame = frameNumber;
                    }
                }
            }

            // Mark all the others for deletion
            for (qint32 frameNumber = 0; frameNumber < discMap.numberOfFrames(); frameNumber++) {
                if (frameNumber != bestFrame && discMap.vbiFrameNumber(frameNumber) == duplicatedList[repeatCounter]) {
                    discMap.setMarkedForDeletion(frameNumber);
                }

                if (frameNumber == bestFrame) {
                    qDebug() << "Seq. frame" << discMap.seqFrameNumber(frameNumber) << "with VBI" <<
                                discMap.vbiFrameNumber(frameNumber) << "has been picked with a quality of" <<
                                discMap.frameQuality(frameNumber);
                }
            }
        }

        // Delete everything marked for deletion
        qint32 originalSize = discMap.numberOfFrames();
        discMap.flush();
        qInfo() << "Removed" << originalSize - discMap.numberOfFrames() <<
                   "repeating frames - disc map size now" << discMap.numberOfFrames() << "frames";
    } else {
        qInfo() << "No repeating frames found";
    }
}

// Method to reorder frames according to VBI frame number order
void DiscMapper::reorderFrames(DiscMap &discMap)
{
    qInfo() << "Sorting the disc map according to VBI frame numbering";

    // Before sorting we have to give the pulldown frames a frame number
    // Since there doesn't seem to be a smarter way to do this we will
    // assign each pulldown frame, the frame number of the preceeding non-
    // pulldown frame
    for (qint32 i = 1; i < discMap.numberOfFrames(); i++) {
        if (discMap.isPulldown(i)) discMap.setVbiFrameNumber(i, discMap.vbiFrameNumber(i - 1));
    }

    // Check that the very first frame isn't a pull-down
    if (discMap.isPulldown(0)) {
        discMap.setVbiFrameNumber(0, discMap.vbiFrameNumber(1) - 1);
        qInfo() << "Attempted to reorder frames, but first frame is a pulldown... This probably isn't good, but continuing anyway";
    }

    // Now perform the sort
    discMap.sort();
}

// Method to verify that all frames in the map have VBI frame numbers
// (except frames marked as pulldown)
bool DiscMapper::verifyFrameNumberPresence(DiscMap &discMap)
{
    qInfo() << "Verifying frame numbers are present for all frames in the disc map (except pulldowns)";
    for (qint32 frameNumber = 0; frameNumber < discMap.numberOfFrames(); frameNumber++) {
        if (discMap.vbiFrameNumber(frameNumber) < 1 && !discMap.isPulldown(frameNumber)) return false;
    }
    return true;
}


// Method to reorder frames according to VBI frame number order
void DiscMapper::padDiscMap(DiscMap &discMap)
{
    qInfo() << "Looking for sequence gaps in the disc map and padding missing frames";

    qint32 numberOfGaps = 0;
    for (qint32 frameNumber = 0; frameNumber < discMap.numberOfFrames() - 1; frameNumber++) {
        if (discMap.vbiFrameNumber(frameNumber) + 1 != discMap.vbiFrameNumber(frameNumber + 1)) {
            // Is the current frame a pulldown?
            if (discMap.isPulldown(frameNumber)) {
                // Can't check anything for this condition, just skip it
            } else {
                // Is the next frame a pulldown?
                if (discMap.isPulldown(frameNumber + 1)) {
                    if (discMap.vbiFrameNumber(frameNumber) + 1 != discMap.vbiFrameNumber(frameNumber + 2)) {
                        qDebug() << "Sequence break over pulldown: Current VBI frame is" << discMap.vbiFrameNumber(frameNumber) <<
                                    "next frame is" << discMap.vbiFrameNumber(frameNumber + 1);
                        numberOfGaps++;
                    }

                } else {
                    qDebug() << "Sequence break: Current VBI frame is" << discMap.vbiFrameNumber(frameNumber) <<
                                "next frame is" << discMap.vbiFrameNumber(frameNumber + 1);
                    numberOfGaps++;
                }
            }
        }
    }

    qInfo() << "Found" << numberOfGaps << "gaps in the disc map";
}
















