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

bool DiscMap::create(LdDecodeMetaData &ldDecodeMetaData)
{
    mapReport.clear();

    if (!sanityCheck(ldDecodeMetaData)) return false;
    if (!createInitialMap(ldDecodeMetaData)) return false;
    correctFrameNumbering();
    removeDuplicateFrames();
    detectMissingFrames();

    mapReport.append("");
    mapReport.append("Mapping Complete");

    return true;
}

QStringList DiscMap::getReport()
{
    return mapReport;
}

// Private methods ----------------------------------------------------------------------------------------------------

bool DiscMap::sanityCheck(LdDecodeMetaData &ldDecodeMetaData)
{
    if (ldDecodeMetaData.getNumberOfFrames() < 2) {
        qDebug() << "DiscMap::sanityCheck(): Source file is too small to be valid!";
        mapReport.append("Source file is too small to be valid! - Failed");
        return false;
    }

    if (ldDecodeMetaData.getNumberOfFrames() > 100000) {
        qDebug() << "DiscMap::sanityCheck(): Source file is too large to be valid!";
        mapReport.append("Source file is too large to be valid! - Failed");
        return false;
    }

    return true;
}

bool DiscMap::createInitialMap(LdDecodeMetaData &ldDecodeMetaData)
{
    qDebug() << "DiscMap::createInitialMap(): Creating initial map...";
    mapReport.append("Performing initial mapping:");
    VbiDecoder vbiDecoder;
    discType = discType_unknown;
    isSourcePal = ldDecodeMetaData.getVideoParameters().isSourcePal;
    if (isSourcePal) mapReport.append("Source file standard is PAL");
    else mapReport.append("Source file standard is NTSC");
    mapReport.append("Source contains " + QString::number(ldDecodeMetaData.getNumberOfFrames()) + " frames");

    qint32 missingFrameNumbers = 0;
    qint32 leadInOrOutFrames = 0;

    for (qint32 seqFrame = 1; seqFrame <= ldDecodeMetaData.getNumberOfFrames(); seqFrame++) {
        Frame frame;
        // Get the required field numbers
        frame.firstField = ldDecodeMetaData.getFirstFieldNumber(seqFrame);
        frame.secondField = ldDecodeMetaData.getSecondFieldNumber(seqFrame);

        LdDecodeMetaData::Field firstFieldMeta = ldDecodeMetaData.getField(frame.firstField);
        LdDecodeMetaData::Field secondFieldMeta = ldDecodeMetaData.getField(frame.secondField);

        // Default the other parameters
        frame.isMissing = false;
        frame.isLeadInOrOut = false;
        frame.isMarkedForDeletion = false;

        // Get the VBI data and then decode
        QVector<qint32> vbi1 = ldDecodeMetaData.getFieldVbi(frame.firstField).vbiData;
        QVector<qint32> vbi2 = ldDecodeMetaData.getFieldVbi(frame.secondField).vbiData;
        VbiDecoder::Vbi vbi = vbiDecoder.decodeFrame(vbi1[0], vbi1[1], vbi1[2], vbi2[0], vbi2[1], vbi2[2]);

        // Check for lead in or out frame
        if (vbi.leadIn || vbi.leadOut) {
            frame.isLeadInOrOut = true;
            frame.vbiFrameNumber = -1;
            leadInOrOutFrames++;
        } else {
            // Check if we have a valid CAV picture number, if not, translated the CLV
            // timecode into a frame number (we only want to deal with one frame identifier in
            // the disc map)
            if (vbi.picNo > 0) {
                // Valid CAV picture number
                frame.vbiFrameNumber = vbi.picNo;
                if (discType == discType_unknown) discType = discType_cav;
            } else {
                // Attempt to translate the CLV timecode into a frame number
                LdDecodeMetaData::ClvTimecode clvTimecode;
                clvTimecode.hours = vbi.clvHr;
                clvTimecode.minutes = vbi.clvMin;
                clvTimecode.seconds = vbi.clvSec;
                clvTimecode.pictureNumber = vbi.clvPicNo;

                frame.vbiFrameNumber = ldDecodeMetaData.convertClvTimecodeToFrameNumber(clvTimecode);

                // If this fails the frame number will be -1 to indicate that it's not valid,
                // but just in case
                if (frame.vbiFrameNumber < 1) frame.vbiFrameNumber = -1;

                // Count the missing frame numbers
                if (frame.vbiFrameNumber < 1) missingFrameNumbers++;

                if (discType == discType_unknown) discType = discType_clv;
            }

            if (vbi.type == VbiDecoder::VbiDiscTypes::clv && discType == discType_cav) {
                qWarning() << "VBI indicates the disc is CLV but data suggests its CAV!";
            } else if (vbi.type == VbiDecoder::VbiDiscTypes::cav && discType == discType_clv) {
                qWarning() << "VBI indicates the disc is CAV but data suggests its CLV!";
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

//            qDebug() << "DiscMap::createInitialMap(): SeqF#" << seqFrame << "VBIF#" << frame.vbiFrameNumber <<
//                        "DOL =" << frame.dropOutLevel << "SNR =" << frame.bSnr << "SyncConf =" << frame.syncConf;
        }
    }

    qDebug() << "DiscMap::createInitialMap(): Initial map created.  Got" << ldDecodeMetaData.getNumberOfFrames() <<
                "frames with" << missingFrameNumbers << "missing frame numbers and" <<
                leadInOrOutFrames << "Lead in/out frames";
    mapReport.append("Initial map created - Got " +
                 QString::number(ldDecodeMetaData.getNumberOfFrames()) +
                 " frames with " + QString::number(missingFrameNumbers) + " missing frame numbers and " +
                 QString::number(leadInOrOutFrames) + " lead in/out frames");

    switch (discType) {
    case discType_cav:
        qDebug() << "DiscMap::createInitialMap(): Disc type is CAV";
        mapReport.append("LaserDisc type is CAV");
        break;
    case discType_clv:
        qDebug() << "DiscMap::createInitialMap(): Disc type is CLV";
        mapReport.append("LaserDisc type is CLV");
        break;
    case discType_unknown:
        qDebug() << "DiscMap::createInitialMap(): Disc type is UNKNOWN!";
        mapReport.append("LaserDisc type is UNKNOWN!");
        break;
    }

    // Don't continue if it wasn't possible to work out the type of disc...
    if (discType == discType_unknown) return false;

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
    for (qint32 seqNumber = 2; seqNumber < frames.size(); seqNumber++) {
        // Only process if fields aren't lead-in or lead-out
        if (!frames[seqNumber].isLeadInOrOut) {
            // If this is NTSC CAV only correct if the current frame number is valid (in all other
            // cases, correct even if the frame number is missing)
            if (!(!isSourcePal && discType == discType_cav && frames[seqNumber].vbiFrameNumber < 1)) {
                // Check if frame number is missing
                if (frames[seqNumber].vbiFrameNumber < 1) frameMissingFrameNumberCount++;

                // Are there enough remaining frames to perform the search?
                if ((frames.size() - seqNumber) < searchDistance) searchDistance = frames.size() - seqNumber;

                // Try up to a distance of 'searchDistance' frames to find the sequence
                for (qint32 gap = 1; gap < searchDistance; gap++) {
                    if (frames[seqNumber].vbiFrameNumber != (frames[seqNumber - 1].vbiFrameNumber + 1)) {
                        if (frames[seqNumber - 1].vbiFrameNumber == (frames[seqNumber + gap].vbiFrameNumber - (gap + 1))) {
                            correctedFrameNumber = frames[seqNumber - 1].vbiFrameNumber + 1;

                            if (correctedFrameNumber > 0 && correctedFrameNumber < 80000) {
                                qDebug() << "DiscMap::correctFrameNumbering(): Correction to seq. frame" << seqNumber << ":";
                                qDebug() << "DiscMap::correctFrameNumbering():   Seq. frame" << seqNumber - 1 << "has a VBI frame number of" << frames[seqNumber - 1].vbiFrameNumber;
                                qDebug() << "DiscMap::correctFrameNumbering():   Seq. frame" << seqNumber << "has a VBI frame number of" << frames[seqNumber].vbiFrameNumber;
                                qDebug() << "DiscMap::correctFrameNumbering():   Seq. frame" << seqNumber + gap << "has a VBI frame number of" << frames[seqNumber + gap].vbiFrameNumber;
                                qDebug() << "DiscMap::correctFrameNumbering():   VBI frame number corrected to" << correctedFrameNumber;

                                mapReport.append("Correction to sequential frame number " + QString::number(seqNumber) + ":");
                                mapReport.append("** Sequential frame " + QString::number(seqNumber - 1) + " has a VBI frame number of " + QString::number(frames[seqNumber - 1].vbiFrameNumber));
                                mapReport.append("** Sequential frame " + QString::number(seqNumber) + " has a VBI frame number of " + QString::number(frames[seqNumber].vbiFrameNumber));
                                mapReport.append("** Sequential frame " + QString::number(seqNumber + gap) + " has a VBI frame number of " + QString::number(frames[seqNumber + gap].vbiFrameNumber));
                                mapReport.append("** VBI frame number corrected to " + QString::number(correctedFrameNumber));
                            } else {
                                // Correction was out of range...
                                qDebug() << "DiscMap::correctFrameNumbering(): Correction to sequential frame number" << seqNumber << ": was out of range, setting to invalid";
                                mapReport.append("Correction to sequential frame number " + QString::number(seqNumber) + ": was out of range, setting to invalid");
                                correctedFrameNumber = -1;
                            }

                            // Update the frame number
                            frames[seqNumber].vbiFrameNumber = correctedFrameNumber;

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

    for (qint32 seqNumber = 0; seqNumber < frames.size(); seqNumber++) {
        if (frames[seqNumber].vbiFrameNumber > 0) {
            QVector<qint32> duplicates;
            for (qint32 i = 0; i < frames.size(); i++) {
                if (frames[seqNumber].vbiFrameNumber == frames[i].vbiFrameNumber && !frames[i].isMarkedForDeletion) duplicates.append(i);
            }
            if (duplicates.size() > 1) {
                qDebug() << "DiscMap::correctFrameNumbering(): Found" << duplicates.size() - 1 << "duplicates of VBI frame number" << frames[seqNumber].vbiFrameNumber;
                mapReport.append("Found " + QString::number(duplicates.size() - 1) + " duplicates of VBI frame number " + QString::number(frames[seqNumber].vbiFrameNumber));

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
            qDebug() << "DiscMap::correctFrameNumbering(): Frame sequence number" << seqNumber << "is missing a VBI frame number!";
            mapReport.append("Frame with sequential number " + QString::number(seqNumber) + " is missing a VBI frame number!");
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
    for (qint32 i = 0; i < frames.size(); i++) {
        // Copy the current frame to the output
        filledFrames.append(frames[i]);

        // If this is not the last frame, look at the next frame number
        // to see if there is a gap
        if (i != frames.size() - 1) {
            qint32 currentFrameNumber = frames[i].vbiFrameNumber;
            if (frames[i + 1].vbiFrameNumber != currentFrameNumber + 1) {
                qDebug() << "DiscMap::detectMissingFrames(): Current frame number is" << currentFrameNumber << "next frame number is" << frames[i + 1].vbiFrameNumber;
                mapReport.append("** Found gap between VBI frame number " + QString::number(currentFrameNumber) + " and " + QString::number(frames[i + 1].vbiFrameNumber));
                // Frames are missing
                for (qint32 p = 1; p < frames[i + 1].vbiFrameNumber - currentFrameNumber; p++) {
                    Frame frame;
                    frame.firstField = -1;
                    frame.secondField = -1;
                    frame.isMissing = true;
                    frame.isLeadInOrOut = false;
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

    // Copy the filled frames over to the target
    frames = filledFrames;
    qDebug() << "DiscMap::detectMissingFrames(): Added" << filledFrameCount << "missing frames - Frame total now" << frames.size();
    mapReport.append("Added " + QString::number(filledFrameCount) + " missing frames - Frame total now " + QString::number(frames.size()));
}

