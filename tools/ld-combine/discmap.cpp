/************************************************************************

    discmap.cpp

    ld-combine - TBC combination and enhancement tool
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

#include "discmap.h"

DiscMap::DiscMap(QObject *parent) : QObject(parent)
{

}

// Public methods -----------------------------------------------------------------------------------------------------

// Create a disc map based on the source's metadata
bool DiscMap::create(LdDecodeMetaData &ldDecodeMetaData)
{
    mapReport.clear();

    if (!discCheck(ldDecodeMetaData)) return false;
    if (!createInitialMap(ldDecodeMetaData)) return false;
    correctFrameNumbering();
    removeDuplicateFrames();
    detectMissingFrames();

    mapReport.append("");
    mapReport.append("Mapping Complete");

    return true;
}

// Return the disc mapping text report
QStringList DiscMap::getReport()
{
    return mapReport;
}

// Get the number of frames in the map
qint32 DiscMap::getNumberOfFrames()
{
    return frames.size();
}

// Get the start frame of the map
qint32 DiscMap::getStartFrame()
{
    return vbiStartFrameNumber;
}

// Get the end frame of the map
qint32 DiscMap::getEndFrame()
{
    return vbiEndFrameNumber;
}


// Get a frame record from the disc map
DiscMap::Frame DiscMap::getFrame(qint32 frameNumber)
{
    if (frameNumber < vbiStartFrameNumber || frameNumber > vbiEndFrameNumber) {
        // Return the frame as missing
        qDebug() << "DiscMap::getFrame(): Request for frameNumber" << frameNumber << "- returning missing frame";

        Frame frame;
        frame.firstField = -1;
        frame.secondField = -1;
        frame.isMissing = true;
        frame.isMarkedForDeletion = false;
        frame.vbiFrameNumber = frameNumber + 1;
        frame.syncConf = 0;
        frame.bSnr = 0;
        frame.dropOutLevel = 0;
        return frame;
    }

    //qDebug() << "DiscMap::getFrame(): Request for frameNumber" << frameNumber << "returning frame element" << frameNumber - vbiStartFrameNumber;
    return frames[frameNumber - vbiStartFrameNumber];
}

// Private methods ----------------------------------------------------------------------------------------------------

bool DiscMap::discCheck(LdDecodeMetaData &ldDecodeMetaData)
{
    qDebug() << "DiscMap::discCheck(): Disc check";
    mapReport.append("Disc check:");

    // Report number of available frames in the source
    mapReport.append("Source contains " + QString::number(ldDecodeMetaData.getNumberOfFrames()) + " frames");

    if (ldDecodeMetaData.getNumberOfFrames() < 2) {
        qDebug() << "DiscMap::discCheck(): Source file is too small to be valid!";
        mapReport.append("Source file is too small to be valid! - Cannot map");
        return false;
    }

    if (ldDecodeMetaData.getNumberOfFrames() > 100000) {
        qDebug() << "DiscMap::discCheck(): Source file is too large to be valid!";
        mapReport.append("Source file is too large to be valid! - Cannot map");
        return false;
    }

    // Check disc video standard
    isSourcePal = ldDecodeMetaData.getVideoParameters().isSourcePal;
    if (isSourcePal) mapReport.append("Source file standard is PAL");
    else mapReport.append("Source file standard is NTSC");

    // Determine the disc type (check 100 frames (or less if source is small)
    // Fail if picture numbers or timecodes are not available
    discType = discType_unknown;
    qint32 framesToCheck = 100;
    if (ldDecodeMetaData.getNumberOfFrames() < framesToCheck) framesToCheck = ldDecodeMetaData.getNumberOfFrames();
    qDebug() << "DiscMap::discCheck(): Checking first" << framesToCheck << "sequential frames for disc type determination";

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
    qDebug() << "DiscMap::discCheck(): Got" << cavCount << "CAV picture codes and" << clvCount << "CLV timecodes";

    // If the metadata has no picture numbers or time-codes, we cannot use the source
    if (cavCount == 0 && clvCount == 0) {
        qDebug() << "DiscMap::discCheck(): Source does not seem to contain valid CAV picture numbers or CLV time-codes - cannot continue!";
        return false;
    }

    // Determine disc type
    if (cavCount > clvCount) {
        discType = discType_cav;
        mapReport.append("Got " + QString::number(cavCount) + " valid CAV picture numbers from " + QString::number(framesToCheck) + " frames - source disc type is CAV");
    } else {
        discType = discType_clv;
        mapReport.append("Got " + QString::number(clvCount) + " valid CLV picture numbers from " + QString::number(framesToCheck) + " frames - source disc type is CLV");
    }

    return true;
}

// This method takes the original metadata and stores it in the disc map frames
// structure.  This is the last part of the process that interacts with the original
// metadata.
bool DiscMap::createInitialMap(LdDecodeMetaData &ldDecodeMetaData)
{
    qDebug() << "DiscMap::createInitialMap(): Creating initial map...";
    mapReport.append("");
    mapReport.append("Initial mapping:");

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

        // Get the VBI data and then decode
        QVector<qint32> vbi1 = ldDecodeMetaData.getFieldVbi(frame.firstField).vbiData;
        QVector<qint32> vbi2 = ldDecodeMetaData.getFieldVbi(frame.secondField).vbiData;
        VbiDecoder::Vbi vbi = vbiDecoder.decodeFrame(vbi1[0], vbi1[1], vbi1[2], vbi2[0], vbi2[1], vbi2[2]);

        // Check for lead in frame
        if (vbi.leadIn && !gotFirstFrame) {
            // We only detect a leadin frame if it comes before a real frame
            // Lead in frames are discarded
            leadInOrOutFrames++;            
        } else if (vbi.leadOut && (seqFrame > (ldDecodeMetaData.getNumberOfFrames() - 20))) {
            // We only detect a lead out frame if it is within 20 frames of the last frame
            // Lead out frames are discarded
            leadInOrOutFrames++;
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
                qDebug() << "DiscMap::createInitialMap(): Sequential frame" << seqFrame << "does not have a valid frame number";
                mapReport.append("Sequential frame " + QString::number(seqFrame) + " does not have a valid frame number");
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

    qDebug() << "DiscMap::createInitialMap(): Initial map created.  Got" << frames.size() <<
                "frames with" << missingFrameNumbers << "missing frame numbers and" <<
                leadInOrOutFrames << "discarded lead in/out frames";
    mapReport.append("Initial map created - Got " +
                 QString::number(frames.size()) +
                 " frames with " + QString::number(missingFrameNumbers) + " missing frame numbers and " +
                 QString::number(leadInOrOutFrames) + " discarded lead in/out frames");

    return true;
}

void DiscMap::correctFrameNumbering()
{
    qDebug() << "DiscMap::correctFrameNumbering(): Performing frame number correction...";
    mapReport.append("");
    mapReport.append("Frame number verification and correction:");

    qint32 correctedFrameNumber;
    qint32 frameNumberErrorCount = 0;
    qint32 frameMissingFrameNumberCount = 0;
    qint32 searchDistance = 5;

    // We must verify the very first and very last frames first in order to perform a valid
    // gap analysis

    // Correct from frames from start + 1 to end -1
    for (qint32 frameElement = 1; frameElement < frames.size(); frameElement++) {
        // If this is NTSC CAV only correct if the current frame number is valid (in all other
        // cases, correct even if the frame number is missing)
        if (!(!isSourcePal && discType == discType_cav && frames[frameElement].vbiFrameNumber < 1)) {
            // Check if frame number is missing
            if (frames[frameElement].vbiFrameNumber < 1) frameMissingFrameNumberCount++;

            // Are there enough remaining frames to perform the search?
            if ((frames.size() - frameElement) < searchDistance) searchDistance = frames.size() - frameElement;

            // Try up to a distance of 'searchDistance' frames to find the sequence
            for (qint32 gap = 1; gap < searchDistance; gap++) {
                if (frames[frameElement].vbiFrameNumber != (frames[frameElement - 1].vbiFrameNumber + 1)) {
                    if (frames[frameElement - 1].vbiFrameNumber == (frames[frameElement + gap].vbiFrameNumber - (gap + 1))) {
                        correctedFrameNumber = frames[frameElement - 1].vbiFrameNumber + 1;

                        if (correctedFrameNumber > 0 && correctedFrameNumber < 80000) {
                            qDebug() << "DiscMap::correctFrameNumbering(): Correction to seq. frame" << frameElement << ":";
                            qDebug() << "DiscMap::correctFrameNumbering():   Seq. frame" << frameElement - 1 << "has a VBI frame number of" << frames[frameElement - 1].vbiFrameNumber;
                            qDebug() << "DiscMap::correctFrameNumbering():   Seq. frame" << frameElement << "has a VBI frame number of" << frames[frameElement].vbiFrameNumber;
                            qDebug() << "DiscMap::correctFrameNumbering():   Seq. frame" << frameElement + gap << "has a VBI frame number of" << frames[frameElement + gap].vbiFrameNumber;
                            qDebug() << "DiscMap::correctFrameNumbering():   VBI frame number corrected to" << correctedFrameNumber;

                            mapReport.append("Correction to sequential frame number " + QString::number(frameElement) + ":");
                            mapReport.append("** Sequential frame " + QString::number(frameElement - 1) + " has a VBI frame number of " + QString::number(frames[frameElement - 1].vbiFrameNumber));
                            if (frames[frameElement].vbiFrameNumber> 0) {
                                mapReport.append("** Sequential frame " + QString::number(frameElement) + " has a VBI frame number of " + QString::number(frames[frameElement].vbiFrameNumber));
                            } else {
                                mapReport.append("** Sequential frame " + QString::number(frameElement) + " does not have a valid VBI frame number");
                            }
                            mapReport.append("** Sequential frame " + QString::number(frameElement + gap) + " has a VBI frame number of " + QString::number(frames[frameElement + gap].vbiFrameNumber));
                            mapReport.append("** VBI frame number corrected to " + QString::number(correctedFrameNumber));
                        } else {
                            // Correction was out of range...
                            qDebug() << "DiscMap::correctFrameNumbering(): Correction to sequential frame number" << frameElement << ": was out of range, setting to invalid";
                            mapReport.append("Correction to sequential frame number " + QString::number(frameElement) + ": was out of range, setting to invalid");
                            correctedFrameNumber = -1;
                        }

                        // Update the frame number
                        frames[frameElement].vbiFrameNumber = correctedFrameNumber;

                        frameNumberErrorCount++;
                        break; // done
                    }
                }
            }
        } else {
            // NTSC CAV missing frame number
            qCritical() << "DiscMap::correctFrameNumbering(): WARNING: NTSC CAV might not work properly yet (seeing missing frame numbers)!";
            mapReport.append("WARNING: NTSC CAV might not work properly yet (seeing missing frame numbers)!");
        }

    }
    qDebug() << "DiscMap::correctFrameNumbering(): Found and corrected" << frameNumberErrorCount << "bad/missing VBI frame numbers (of which" <<
                frameMissingFrameNumberCount << "had no frame number)";
    mapReport.append("Found and corrected " + QString::number(frameNumberErrorCount) + " bad/missing VBI frame numbers (of which " +
                QString::number(frameMissingFrameNumberCount) + " had no frame number set in the VBI)");
}

void DiscMap::removeDuplicateFrames()
{
    qDebug() << "DiscMap::removeDuplicateFrames(): Performing duplicate frame number analysis...";
    mapReport.append("");
    mapReport.append("Identify and remove duplicate frames:");

    for (qint32 frameElement = 0; frameElement < frames.size(); frameElement++) {
        if (frames[frameElement].vbiFrameNumber > 0) {
            QVector<qint32> duplicates;
            for (qint32 i = 0; i < frames.size(); i++) {
                if (frames[frameElement].vbiFrameNumber == frames[i].vbiFrameNumber && !frames[i].isMarkedForDeletion) duplicates.append(i);
            }
            if (duplicates.size() > 1) {
                qDebug() << "DiscMap::correctFrameNumbering(): Found" << duplicates.size() - 1 << "duplicates of VBI frame number" << frames[frameElement].vbiFrameNumber;
                mapReport.append("Found " + QString::number(duplicates.size() - 1) + " duplicates of VBI frame number " + QString::number(frames[frameElement].vbiFrameNumber));

                // Select one of the available frames based on black SNR (TODO: should also include sync confidence and DO levels)
                qint32 maxSnr = -1;
                qint32 selection = -1;
                for (qint32 i = 0; i < duplicates.size(); i++) {
                    if (frames[duplicates[i]].bSnr > maxSnr) {
                        selection = i;
                        maxSnr = frames[duplicates[i]].bSnr;
                    }
                }

                // Mark the loosing frames for deletion
                for (qint32 i = 0; i < duplicates.size(); i++) {
                    if (i != selection) {
                        frames[duplicates[i]].isMarkedForDeletion = true;
                        qDebug() << "DiscMap::correctFrameNumbering(): Frame seq" << duplicates[i] << "is marked for deletion ( SNR of" << frames[duplicates[i]].bSnr << ")";
                        mapReport.append("Frame with sequential number " + QString::number(duplicates[i]) + " is marked for deletion (has SNR of " + QString::number(frames[duplicates[i]].bSnr) + ")");
                    } else {
                        qDebug() << "DiscMap::correctFrameNumbering(): Frame seq" << duplicates[i] << "is selected ( SNR of" << frames[duplicates[i]].bSnr << ")";
                        mapReport.append("Frame with sequential number " + QString::number(duplicates[i]) + " is selected (has SNR of " + QString::number(frames[duplicates[i]].bSnr) + ")");
                    }
                }
            }
        } else {
            qDebug() << "DiscMap::correctFrameNumbering(): Frame sequence number" << frameElement << "is missing a VBI frame number!";
            mapReport.append("Frame with sequential number " + QString::number(frameElement) + " is missing a VBI frame number!");
        }
    }

    // Remove all frames marked for deletion from the map
    qint32 previousSize = frames.size();
    frames.erase(std::remove_if(frames.begin(), frames.end(), [](const Frame& f) {return f.isMarkedForDeletion == true;}), frames.end());
    qDebug() << "DiscMap::correctFrameNumbering(): Removed" << previousSize - frames.size() << "duplicate frames from the map -" << frames.size() << "frames remaining.";
    mapReport.append("Removed " + QString::number(previousSize - frames.size()) + " duplicate frames from the map - " + QString::number(frames.size()) + " frames remaining.");
}

void DiscMap::detectMissingFrames()
{
    // Sort the frame numbers into VBI number order and look for any missing frames
    // If a frame is missing, we create a record for it in the map and flag the record
    // as 'isMissing' so the source will align with other sources of the same disc

    qDebug() << "DiscMap::detectMissingFrames(): Searching for missing frames...";
    mapReport.append("");
    mapReport.append("Identify and include missing frames:");

    // Firstly we have to ensure that the map is in numerical order of frame numbers
    std::sort(frames.begin(), frames.end());
    qDebug() << "DiscMap::detectMissingFrames(): According to VBI first frame is" << frames.first().vbiFrameNumber << "and last frame is" << frames.last().vbiFrameNumber;
    qDebug() << "DiscMap::detectMissingFrames(): Map size is" << frames.size() << " - According to VBI the size should be " << frames.last().vbiFrameNumber - frames.first().vbiFrameNumber + 1;
    qDebug() << "DiscMap::detectMissingFrames(): Predicting" << (frames.last().vbiFrameNumber - frames.first().vbiFrameNumber + 1) - frames.size() << "missing frames in source";

    mapReport.append("According to VBI first frame is " + QString::number(frames.first().vbiFrameNumber) + " and last frame is " + QString::number(frames.last().vbiFrameNumber));
    mapReport.append("Map size is " + QString::number(frames.size()) + " - According to VBI the size should be " + QString::number(frames.last().vbiFrameNumber - frames.first().vbiFrameNumber + 1));
    mapReport.append("Predicting " + QString::number((frames.last().vbiFrameNumber - frames.first().vbiFrameNumber + 1) - frames.size()) + " missing frames in source");

    QVector<Frame> filledFrames;
    qint32 filledFrameCount = 0;
    qint32 iecOffset = 0;
    for (qint32 i = 0; i < frames.size(); i++) {
        // Copy the current frame to the output
        filledFrames.append(frames[i]);

        // If this is not the last frame, look at the next frame number
        // to see if there is a gap
        if (i != frames.size() - 1) {
            qint32 currentFrameNumber = frames[i].vbiFrameNumber;
            if (frames[i + 1].vbiFrameNumber != currentFrameNumber + 1) {

                // Is this an IEC NTSC amendment 2 NTSC CLV sequence frame number?
                if (isNtscAmendment2ClvFrameNumber(frames[i].vbiFrameNumber + 1 - iecOffset) && discType == discType_clv && !isSourcePal && (frames[i + 1].vbiFrameNumber - currentFrameNumber == 2)) {
                    qDebug() << "DiscMap::detectMissingFrames(): Gap at VBI frame" << currentFrameNumber << "is caused by IEC NTSC2 CLV offset sequence";
                    mapReport.append("Gap at VBI frame " + QString::number(currentFrameNumber) + " is caused by IEC NTSC2 CLV offset sequence");
                    iecOffset++;
                } else {
                    qDebug() << "DiscMap::detectMissingFrames(): Current frame number is" << currentFrameNumber << "next frame number is" << frames[i + 1].vbiFrameNumber <<
                                "- gap is " << frames[i + 1].vbiFrameNumber - currentFrameNumber << "frames";
                    mapReport.append("** Found gap between VBI frame number " + QString::number(currentFrameNumber) + " and " + QString::number(frames[i + 1].vbiFrameNumber));
                    // Frames are missing
                    for (qint32 p = 1; p < frames[i + 1].vbiFrameNumber - currentFrameNumber; p++) {
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
        qDebug() << "DiscMap::detectMissingFrames(): Adjusting frame numbers to allow for IEC NTSC2 CLV offset";
        mapReport.append("Adjusting frame numbers to allow for IEC NTSC2 CLV offset");
        qint32 element = 0;
        for (qint32 i = filledFrames.first().vbiFrameNumber; i < filledFrames.first().vbiFrameNumber + filledFrames.size(); i++) {
            filledFrames[element].vbiFrameNumber = i;
            element++;
        }
    }

    // Copy the filled frames over to the target
    frames = filledFrames;
    qDebug() << "DiscMap::detectMissingFrames(): Added" << filledFrameCount << "missing frames - Frame total now" << frames.size();
    mapReport.append("Added " + QString::number(filledFrameCount) + " missing frames - Frame total now " + QString::number(frames.size()));

    // Set the start frame (by setting the frameNumberOffset
    vbiStartFrameNumber = frames.first().vbiFrameNumber;
    vbiEndFrameNumber = frames.last().vbiFrameNumber;
    mapReport.append("Set source start frame as " + QString::number(vbiStartFrameNumber) + " and end frame as " + QString::number(vbiEndFrameNumber));
}

// Check if frame number matches IEC 60857-1986 LaserVision NTSC Amendment 2
// clause 10.1.10 CLV time-code skip frame number sequence
bool DiscMap::isNtscAmendment2ClvFrameNumber(qint32 frameNumber)
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

