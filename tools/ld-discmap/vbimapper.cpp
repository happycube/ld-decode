/************************************************************************

    vbimapper.cpp

    ld-discmap - TBC and VBI alignment and correction
    Copyright (C) 2019 Simon Inns

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

#include "vbimapper.h"

VbiMapper::VbiMapper(QObject *parent) : QObject(parent)
{

}

// Public methods -----------------------------------------------------------------------------------------------------

// Create a disc map based on the source's metadata
bool VbiMapper::create(LdDecodeMetaData &ldDecodeMetaData)
{
    qInfo() << "";
    qInfo() << "Performing VBI based disc mapping...";

    if (!discCheck(ldDecodeMetaData)) return false;
    if (!createInitialMap(ldDecodeMetaData)) return false;
    correctFrameNumbering();
    removeCorruptFrames();
    removeDuplicateFrames();
    detectMissingFrames();

    // Check that the number of VBI frames is equal to the number of sequential frames
    if ((vbiEndFrameNumber - vbiStartFrameNumber + 1) != frames.size()) {
        qInfo() << "Sequential frame size and VBI frame size does not match - Mapping has failed!";
        return false;
    } else {
        qInfo() << "VBI based disc mapping successfully completed";
    }

    return true;
}

// Get the number of frames in the map
qint32 VbiMapper::getNumberOfFrames()
{
    return frames.size();
}

// Get the start frame of the map
qint32 VbiMapper::getStartFrame()
{
    return vbiStartFrameNumber;
}

// Get the end frame of the map
qint32 VbiMapper::getEndFrame()
{
    return vbiEndFrameNumber;
}

// Get a frame record from the disc map
VbiMapper::Frame VbiMapper::getFrame(qint32 frameNumber)
{
    if (frameNumber < 0 || frameNumber > frames.size()) {
        qCritical() << "VbiMapper::getFrame(): Request for frameNumber" << frameNumber << "- returning missing frame";

        Frame frame;
        frame.firstField = -1;
        frame.secondField = -1;
        frame.isMissing = true;
        frame.isMarkedForDeletion = false;
        frame.vbiFrameNumber = 0;
        frame.syncConf = 0;
        frame.bSnr = 0;
        frame.dropOutLevel = 0;
        return frame;
    }

    return frames[frameNumber];
}

// Flag if the disc is CAV or CLV
bool VbiMapper::isDiscCav()
{
    if (discType == discType_cav) return true;
    return false;
}

// Private methods ----------------------------------------------------------------------------------------------------

bool VbiMapper::discCheck(LdDecodeMetaData &ldDecodeMetaData)
{
    qInfo() << "";
    qInfo() << "Performing initial disc check...";

    // Report number of available frames in the source
    qInfo() << "Source contains" << ldDecodeMetaData.getNumberOfFrames() << "sequential frames";

    if (ldDecodeMetaData.getNumberOfFrames() < 2) {
        qInfo() << "Source file is too small to be valid! - Cannot map";
        return false;
    }

    if (ldDecodeMetaData.getNumberOfFrames() > 100000) {
        qInfo() << "Source file is too large to be valid! - Cannot map";
        return false;
    }

    // Check disc video standard
    isSourcePal = ldDecodeMetaData.getVideoParameters().isSourcePal;
    if (isSourcePal) qInfo() << "Source file video format is PAL";
    else qInfo() << "Source file video format is NTSC";

    // Determine the disc type (CAV/CLV) - check 100 frames (or less if source is small)
    // Fail if both picture numbers and timecodes are not available
    discType = discType_unknown;
    qint32 framesToCheck = 100;
    if (ldDecodeMetaData.getNumberOfFrames() < framesToCheck) framesToCheck = ldDecodeMetaData.getNumberOfFrames();
    qDebug() << "VbiMapper::discCheck(): Checking first" << framesToCheck << "sequential frames for disc type determination";

    VbiDecoder vbiDecoder;
    qint32 cavCount = 0;
    qint32 clvCount = 0;
    // Using sequential frame numbering starting from 1
    for (qint32 seqFrame = 1; seqFrame <= framesToCheck; seqFrame++) {
        // Get the VBI data and then decode
        QVector<qint32> vbi1 = ldDecodeMetaData.getFieldVbi(ldDecodeMetaData.getFirstFieldNumber(seqFrame)).vbiData;
        QVector<qint32> vbi2 = ldDecodeMetaData.getFieldVbi(ldDecodeMetaData.getSecondFieldNumber(seqFrame)).vbiData;
        VbiDecoder::Vbi vbi = vbiDecoder.decodeFrame(vbi1[0], vbi1[1], vbi1[2], vbi2[0], vbi2[1], vbi2[2]);

        // Look for a complete, valid CAV picture number or CLV time-code
        if (vbi.picNo > 0) cavCount++;
        if (vbi.clvHr != -1 && vbi.clvMin != -1 &&
                vbi.clvSec != -1 && vbi.clvPicNo != -1) clvCount++;
    }
    qDebug() << "VbiMapper::discCheck(): Got" << cavCount << "CAV picture codes and" << clvCount << "CLV timecodes";

    // If the metadata has no picture numbers or time-codes, we cannot use the source
    if (cavCount == 0 && clvCount == 0) {
        qInfo() << "Source does not seem to contain valid CAV picture numbers or CLV time-codes - cannot map";
        return false;
    }

    // Determine disc type
    if (cavCount > clvCount) {
        discType = discType_cav;
        qDebug() << "Got" << cavCount << "valid CAV picture numbers from" << framesToCheck << "frames - source disc type is CAV";
        qInfo() << "Source disc mastering format is CAV";
    } else {
        discType = discType_clv;
        qDebug() << "Got" << clvCount << "valid CLV picture numbers from" << framesToCheck << "frames - source disc type is CLV";
        qInfo() << "Source disc mastering format is CLV";

    }

    // VBI mapping cannot support NTSC CAV discs with pull-down
    if (discType == discType_cav && !isSourcePal) {
        qWarning() << "Disc is NTSC CAV - If the disc contains pull-down frames mapping WILL FAIL";
    }

    return true;
}

// This method takes the original metadata and stores it in the disc map frames
// structure.  This is the last part of the process that interacts with the original
// metadata.
bool VbiMapper::createInitialMap(LdDecodeMetaData &ldDecodeMetaData)
{
    qInfo() << "";
    qInfo() << "Creating initial map...";

    VbiDecoder vbiDecoder;
    qint32 missingFrameNumbers = 0;
    qint32 leadInOrOutFrames = 0;
    bool gotFirstFrame = false; // Used to ensure we only detect lead-in before real frames

    // Using sequential frame numbering starting from 1
    for (qint32 seqFrame = 1; seqFrame <= ldDecodeMetaData.getNumberOfFrames(); seqFrame++) {
        Frame frame;
        // Get the required field numbers
        frame.firstField = ldDecodeMetaData.getFirstFieldNumber(seqFrame);
        frame.secondField = ldDecodeMetaData.getSecondFieldNumber(seqFrame);

        LdDecodeMetaData::Field firstFieldMeta = ldDecodeMetaData.getField(frame.firstField);
        LdDecodeMetaData::Field secondFieldMeta = ldDecodeMetaData.getField(frame.secondField);

        // Default the other parameters
        frame.isMissing = false;
        frame.isMarkedForDeletion = false;
        frame.isCorruptVbi = false;

        // Get the VBI data
        QVector<qint32> vbi1 = ldDecodeMetaData.getFieldVbi(frame.firstField).vbiData;
        QVector<qint32> vbi2 = ldDecodeMetaData.getFieldVbi(frame.secondField).vbiData;

        // Is the VBI data valid for the frame?
        if (vbi1[0] == -1 || vbi1[1] == -1 || vbi1[2] == -1 || vbi2[0] == -1 || vbi2[1] == -1 || vbi2[2] == -1) {
            // VBI is invalid
            qCritical() << "Metadata contains invalid/missing VBI data - please run ld-process-vbi on the source TBC";
            return false;
        }

        // Decode the VBI data
        VbiDecoder::Vbi vbi = vbiDecoder.decodeFrame(vbi1[0], vbi1[1], vbi1[2], vbi2[0], vbi2[1], vbi2[2]);

        // Check for lead in frame
        if (vbi.leadIn && !gotFirstFrame) {
            // We only detect a leadin frame if it comes before a real frame
            // Lead in frames are discarded
            leadInOrOutFrames++;
            if (vbi.leadIn) qInfo() << "Sequential frame" << seqFrame << "is a lead-in frame";
        } else if (vbi.leadOut && (seqFrame > (ldDecodeMetaData.getNumberOfFrames() - 20))) {
            // We only detect a lead out frame if it is within 20 frames of the last frame
            // Lead out frames are discarded
            leadInOrOutFrames++;
            if (vbi.leadOut) qInfo() << "Sequential frame" << seqFrame << "is a lead-out frame";
        } else {
            // Since this isn't lead-in or out, flag that a real frame has been seen
            gotFirstFrame = true;

            // Get either the CAV picture number or the CLV timecode
            // CLV timecodes are converted into the equivalent picture number
            if (discType == discType_cav) {
                // Get CAV picture number
                frame.vbiFrameNumber = vbi.picNo;
            } else {
                // Attempt to translate the CLV timecode into a frame number
                LdDecodeMetaData::ClvTimecode clvTimecode;
                clvTimecode.hours = vbi.clvHr;
                clvTimecode.minutes = vbi.clvMin;
                clvTimecode.seconds = vbi.clvSec;
                clvTimecode.pictureNumber = vbi.clvPicNo;
                frame.vbiFrameNumber = ldDecodeMetaData.convertClvTimecodeToFrameNumber(clvTimecode);
            }

            // Is the frame number missing?
            if (frame.vbiFrameNumber < 1) {
                missingFrameNumbers++;
                qInfo() << "Sequential frame" << seqFrame << "does not have a valid frame number";
            }

            // Get the frame's average sync confidence
            frame.syncConf = (firstFieldMeta.syncConf +
                              secondFieldMeta.syncConf) / 2;

            // Get the frame's average black SNR
            qreal frame1Snr = firstFieldMeta.vitsMetrics.bPSNR;
            qreal frame2Snr = secondFieldMeta.vitsMetrics.bPSNR;
            qreal combinedSnr = 0;
            if (frame1Snr > 1 && frame2Snr > 1) combinedSnr = (frame1Snr + frame2Snr) / 2;
            else if (frame1Snr > 1 && frame2Snr < 1) combinedSnr = frame1Snr;
            else if (frame2Snr > 1 && frame1Snr < 1) combinedSnr = frame1Snr;
            else combinedSnr = 0;
            frame.bSnr = static_cast<qint32>(combinedSnr);

            // Get the frames drop out level (this is the total number of picture dots lost to
            // dropouts across both fields that make up the frame
            // Calculate the total length of the dropouts
            frame.dropOutLevel = 0;
            for (qint32 i = 0; i < firstFieldMeta.dropOuts.startx.size(); i++) {
                frame.dropOutLevel += firstFieldMeta.dropOuts.endx[i] -
                        firstFieldMeta.dropOuts.startx[i];
            }
            for (qint32 i = 0; i < secondFieldMeta.dropOuts.startx.size(); i++) {
                frame.dropOutLevel += secondFieldMeta.dropOuts.endx[i] -
                        secondFieldMeta.dropOuts.startx[i];
            }

            // Store the frame
            frames.append(frame);
        }
    }

    qInfo() << "Initial map created - Got" << frames.size() <<
                "sequential frames with" << missingFrameNumbers << "missing frame numbers and" <<
                leadInOrOutFrames << "discarded lead in/out frames";

    return true;
}

void VbiMapper::correctFrameNumbering()
{
    qInfo() << "";
    qInfo() << "Performing frame number correction...";

    qint32 correctedFrameNumber = -1;
    qint32 frameNumberErrorCount = 0;
    qint32 frameMissingFrameNumberCount = 0;
    qint32 frameNumberCorruptCount = 0;
    qint32 searchDistance = 5;

    // Set the maximum frame number limit
    qint32 maxFrames;
    if (discType == discType_cav) maxFrames = 80000; // CAV maximum is 79999
    else {
        if (isSourcePal) maxFrames = 105000; // PAL CLV set to 70 minutes (70*60*25)
        else maxFrames = 121800; // NTSC CLV set to 70 minutes (70*60*29)
    }

    qInfo() << "Checking for missing frame numbers before correction";
    for (qint32 frameElement = 1; frameElement < frames.size(); frameElement++) {
        // Check if frame number is missing
        if (frames[frameElement].vbiFrameNumber < 1) {
            frameMissingFrameNumberCount++;

            // Set the frame number to a sane value ready for correction
            frames[frameElement].vbiFrameNumber = frames[frameElement - 1].vbiFrameNumber + 1;
            frames[frameElement].isCorruptVbi = true; // Flag that the VBI should be rewritten
            qInfo() << "Seq. frame" << frameElement << "has a VBI frame number of -1 - Setting to" <<
                       frames[frameElement].vbiFrameNumber;
        }
    }

    qInfo() << "Performing sequential VBI frame numbering check/correction";
    // Correct from frames from start + 1 to end
    for (qint32 frameElement = 1; frameElement < frames.size(); frameElement++) {
        // Are there enough remaining frames to perform the search?
        if ((frames.size() - frameElement) < searchDistance) searchDistance = frames.size() - frameElement;

        // Try up to a distance of 'searchDistance' frames to find the sequence
        for (qint32 gap = 1; gap < searchDistance; gap++) {
            if (frames[frameElement].vbiFrameNumber != (frames[frameElement - 1].vbiFrameNumber + 1)) {
                // Is the previous frame invalid?
                if (frames[frameElement - 1].vbiFrameNumber == -1) {
                    qInfo() << "Previous frame number is invalid - cannot correct, skipping";
                    break;
                }

                // Did the player stall and repeat the last frame?
                if (frames[frameElement - 1].vbiFrameNumber == frames[frameElement].vbiFrameNumber) {
                    // Give up and leave the frame number as-is
                    qInfo() << "Seq. frame" << frameElement << "repeats previous VBI frame number of" << frames[frameElement].vbiFrameNumber << "- player stalled/paused?";
                    break;
                } else {
                    // Doesn't look like the player has paused; assume we have progressed one frame
                    if (frames[frameElement - 1].vbiFrameNumber == (frames[frameElement + gap].vbiFrameNumber - (gap + 1))) {
                        correctedFrameNumber = frames[frameElement - 1].vbiFrameNumber + 1;

                        if (correctedFrameNumber > 0 && correctedFrameNumber < maxFrames) {
                            qInfo() << "Correction to seq. frame" << frameElement << ":";
                            qInfo() << "   Seq. frame" << frameElement - 1 << "has a VBI frame number of" << frames[frameElement - 1].vbiFrameNumber;
                            if (frames[frameElement].vbiFrameNumber > 0) {
                                qInfo() << "   Seq. frame" << frameElement << "has a VBI frame number of" << frames[frameElement].vbiFrameNumber;
                            } else {
                                qInfo() << "   Seq. frame" << frameElement << "does not have a valid VBI frame number";
                            }
                            qInfo() << "   Seq. frame" << frameElement + gap << "has a VBI frame number of" << frames[frameElement + gap].vbiFrameNumber;
                            qInfo() << "   VBI frame number corrected to" << correctedFrameNumber;
                        } else {
                            // Correction was out of range...
                            qInfo() << "Correction to sequential frame number" << frameElement << ": was out of range, setting to invalid";
                            correctedFrameNumber = -1;
                        }

                        // Update the frame number
                        frames[frameElement].vbiFrameNumber = correctedFrameNumber;
                        frames[frameElement].isCorruptVbi = true; // Flag that the VBI should be rewritten

                        frameNumberErrorCount++;
                        break; // done
                    } else {
                        if (gap == searchDistance - 1) {
                            qDebug() << "VbiMapper::correctFrameNumbering(): Search distance reached with no match found - previous" <<
                                        frames[frameElement - 1].vbiFrameNumber << "current" << frames[frameElement + gap].vbiFrameNumber <<
                                        "target" << frames[frameElement].vbiFrameNumber;

                            // Set the VBI as invalid
                            frames[frameElement].isMarkedForDeletion = true; // Flag that the frame should be removed
                            frameNumberCorruptCount++;
                            frameNumberErrorCount++;
                        }
                    }
                }
            }
        }
    }

    // All frame numbers are now checked and corrected except the first frame and last frame; so we do that here
    // since the second frame, and second from last frame should have been corrected already
    if (frames[0].vbiFrameNumber != frames[1].vbiFrameNumber - 1) {
        qInfo().nospace() << "The first frame does not have a valid frame number (" << frames[0].vbiFrameNumber <<
                             ") correcting to " << frames[1].vbiFrameNumber - 1 << " based on second frame VBI";
        frames[0].vbiFrameNumber = frames[1].vbiFrameNumber - 1;
        frames[0].isCorruptVbi = true;
        frameNumberErrorCount++;
    }

    if (frames[frames.size() - 1].vbiFrameNumber != frames[frames.size() - 2].vbiFrameNumber + 1) {
        qInfo().nospace() << "The last frame does not have a valid frame number (" << frames[frames.size() - 1].vbiFrameNumber <<
                             ") correcting to " << frames[frames.size() - 2].vbiFrameNumber + 1 << " based on second from last frame VBI";
        frames[frames.size() - 1].vbiFrameNumber = frames[frames.size() - 2].vbiFrameNumber + 1;
        frames[frames.size() - 1].isCorruptVbi = true; // Flag that the VBI should be rewritten
        frameNumberErrorCount++;
    }

    qInfo() << "Found and corrected" << frameNumberErrorCount << "bad/missing VBI frame numbers (of which" <<
                frameMissingFrameNumberCount << "had no frame number set in the VBI and" << frameNumberCorruptCount << "were unrecoverable)";
}

void VbiMapper::removeCorruptFrames()
{
    qInfo() << "";
    qInfo() << "Removing frames with unrecoverable corrupt VBI...";

    // Remove all frames marked for deletion from the map
    qint32 previousSize = frames.size();
    frames.erase(std::remove_if(frames.begin(), frames.end(), [](const Frame& f) {return f.isMarkedForDeletion == true;}), frames.end());
    qInfo() << "Removed" << previousSize - frames.size() << "corrupt VBI frames from the map -" << frames.size() << "sequential frames remaining.";
}

void VbiMapper::removeDuplicateFrames()
{
    qInfo() << "";
    qInfo() << "Identifying and removing duplicate frames...";

    for (qint32 frameElement = 0; frameElement < frames.size(); frameElement++) {
        if (frames[frameElement].vbiFrameNumber > 0) {
            QVector<qint32> duplicates;
            for (qint32 i = 0; i < frames.size(); i++) {
                if (frames[frameElement].vbiFrameNumber == frames[i].vbiFrameNumber && !frames[i].isMarkedForDeletion) duplicates.append(i);
            }
            if (duplicates.size() > 1) {
                qInfo() << "Found" << duplicates.size() - 1 << "duplicates of VBI frame number" << frames[frameElement].vbiFrameNumber;

                // Select one of the available frames based on black SNR (TODO: should also include sync confidence and DO levels)
                qint32 maxSnr = -1;
                qint32 selection = -1;
                for (qint32 i = 0; i < duplicates.size(); i++) {
                    qint32 frameNumber = duplicates[i];
                    qint32 snr = frames[frameNumber].bSnr;

                    // If there is a following frame with the same or lower frame number, the player
                    // must have skipped during this frame -- give it a big SNR penalty so it's
                    // unlikely to be selected
                    if (frameNumber + 1 < frames.size() &&
                        frames[frameNumber + 1].vbiFrameNumber <= frames[frameNumber].vbiFrameNumber) {
                        snr -= 20;
                    }

                    if (snr > maxSnr) {
                        selection = i;
                        maxSnr = snr;
                    }
                }

                // Mark the loosing frames for deletion
                for (qint32 i = 0; i < duplicates.size(); i++) {
                    if (i != selection) {
                        frames[duplicates[i]].isMarkedForDeletion = true;
                        qInfo() << "Frame with sequential number" << duplicates[i] << "is marked for deletion ( has SNR of" << frames[duplicates[i]].bSnr << ")";
                    } else {
                        qInfo() << "Frame with sequential number" << duplicates[i] << "is selected ( SNR of" << frames[duplicates[i]].bSnr << ")";
                    }
                }
            }
        } else {
            qInfo() << "Frame sequence number" << frameElement << "is missing a VBI frame number - this is probably a bug!";
        }
    }

    // Remove all frames marked for deletion from the map
    qint32 previousSize = frames.size();
    frames.erase(std::remove_if(frames.begin(), frames.end(), [](const Frame& f) {return f.isMarkedForDeletion == true;}), frames.end());
    qInfo() << "Removed" << previousSize - frames.size() << "duplicate frames from the map -" << frames.size() << "sequential frames remaining.";
}

void VbiMapper::detectMissingFrames()
{
    // Sort the frame numbers into VBI number order and look for any missing frames
    // If a frame is missing, we create a record for it in the map and flag the record
    // as 'isMissing' so the source will align with other sources of the same disc

    qInfo() << "";
    qInfo() << "Searching for missing frames and padding source...";

    // Firstly we have to ensure that the map is in numerical order of frame numbers
    std::sort(frames.begin(), frames.end());
    qInfo() << "According to VBI first frame is" << frames.first().vbiFrameNumber << "and last frame is" << frames.last().vbiFrameNumber;
    qInfo() << "Map size is" << frames.size() << "- According to VBI the size should be" << frames.last().vbiFrameNumber - frames.first().vbiFrameNumber + 1;
    qInfo() << "Predicting" << (frames.last().vbiFrameNumber - frames.first().vbiFrameNumber + 1) - frames.size() << "missing/IEC NTSC2 CLV offset frames in source";

    QVector<Frame> filledFrames;
    qint32 filledFrameCount = 0;
    qint32 iecOffset = 0;
    // Detect gaps between frames
    for (qint32 frameElement = 0; frameElement < frames.size(); frameElement++) {
        // Copy the current frame to the output
        filledFrames.append(frames[frameElement]);

        // Ensure we don't over flow
        if (frameElement < frames.size() - 1) {
            // Look at the next frame number
            // to see if there is a gap
            qint32 currentFrameNumber = frames[frameElement].vbiFrameNumber;
            qint32 nextFrameNumber = frames[frameElement + 1].vbiFrameNumber;

            if (currentFrameNumber + 1 != nextFrameNumber) {
                // Is this an IEC NTSC amendment 2 NTSC CLV sequence frame number?
                if (isNtscAmendment2ClvFrameNumber(currentFrameNumber + 1 - iecOffset) && discType == discType_clv && !isSourcePal && (nextFrameNumber - currentFrameNumber == 2)) {
                    qDebug() << "VbiMapper::detectMissingFrames(): Gap at VBI frame" << currentFrameNumber << "is caused by IEC NTSC2 CLV offset sequence";
                    iecOffset++;
                } else {
                    qInfo() << "Found gap between VBI frame number" << currentFrameNumber << "and" << nextFrameNumber <<
                                "- gap is" << nextFrameNumber - currentFrameNumber << "frames";
                    // Frames are missing
                    for (qint32 p = 1; p < nextFrameNumber - currentFrameNumber; p++) {
                        Frame frame;
                        frame.firstField = -1;
                        frame.secondField = -1;
                        frame.isMissing = true;
                        frame.isMarkedForDeletion = false;
                        frame.vbiFrameNumber = currentFrameNumber + p;
                        frame.syncConf = 0;
                        frame.bSnr = 0;
                        frame.dropOutLevel = 0;
                        filledFrames.append(frame);
                        filledFrameCount++;
                    }
                }
            }
        }
    }

    // If there were IEC NTSC CLV offsets, we need to correct the VBI frame numbering
    // before continuing (since we didn't fill the gaps there will still be missing
    // frame numbers)
    if (iecOffset > 0) {
        qInfo() << "Adjusting frame numbers to allow for" << iecOffset << "gaps caused by IEC NTSC2 CLV timecode offsets";
        qint32 element = 0;
        for (qint32 i = filledFrames.first().vbiFrameNumber; i < filledFrames.first().vbiFrameNumber + filledFrames.size(); i++) {
            filledFrames[element].vbiFrameNumber = i;
            element++;
        }
    }

    // Copy the filled frames over to the target
    frames = filledFrames;
    qInfo() << "Added" << filledFrameCount << "padding frames - Total number of sequential frames is now" << frames.size();

    // Set the start frame (by setting the frameNumberOffset
    vbiStartFrameNumber = frames.first().vbiFrameNumber;
    vbiEndFrameNumber = frames.last().vbiFrameNumber;
    qInfo() << "Setting source start VBI frame as" << vbiStartFrameNumber << "and end VBI frame as" << vbiEndFrameNumber <<
               "- total of" << vbiEndFrameNumber - vbiStartFrameNumber + 1 << "VBI frames";
}

// Check if frame number matches IEC 60857-1986 LaserVision NTSC Amendment 2
// clause 10.1.10 CLV time-code skip frame number sequence
bool VbiMapper::isNtscAmendment2ClvFrameNumber(qint32 frameNumber)
{
    bool response = false;
    for (qint32 l = 0; l < 9; l++) {
        for (qint32 m = 1; m <= 9; m++) {
            qint32 n = 8991 * l + 899 * m;
            if (n == frameNumber) {
                response = true;
                break;
            }
        }
    }
    return response;
}
