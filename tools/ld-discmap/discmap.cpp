/************************************************************************

    discmap.cpp

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

#include "discmap.h"

DiscMap::DiscMap(const QFileInfo &metadataFileInfo, const bool &reverseFieldOrder)
            : m_metadataFileInfo(metadataFileInfo), m_reverseFieldOrder(reverseFieldOrder)
{
    m_tbcValid = true;

    // Open the metadata file
    LdDecodeMetaData ldDecodeMetaData;

    // Open the TBC metadata file
    if (!ldDecodeMetaData.read(metadataFileInfo.filePath())) {
        // Open failed
        qDebug() << "Cannot load JSON metadata from" << metadataFileInfo.filePath();
        m_tbcValid = false;
        return;
    }

    // If source is reverse-field order, set it up
    if (m_reverseFieldOrder) ldDecodeMetaData.setIsFirstFieldFirst(false);
    else ldDecodeMetaData.setIsFirstFieldFirst(true);

    // Get the number of available frames
    m_numberOfFrames = ldDecodeMetaData.getNumberOfFrames();

    if (m_numberOfFrames < 2) {
        qDebug() << "JSON metadata contains only" << m_numberOfFrames << "frames - too small";
        m_tbcValid = false;
        return;
    }

    if (m_numberOfFrames > 100000) {
        qDebug() << "JSON metadata contains" << m_numberOfFrames << "frames - too big";
        m_tbcValid = false;
        return;
    }

    // Resize the frame store
    m_frames.resize(m_numberOfFrames);

    // Decode the VBI information for the TBC and initialise the frame object
    VbiDecoder vbiDecoder;
    QVector<VbiDecoder::Vbi> vbiData(m_numberOfFrames);
    for (qint32 frameNumber = 0; frameNumber < m_numberOfFrames; frameNumber++) {
        // Store the original sequential frame number
        m_frames[frameNumber].seqFrameNumber(frameNumber + 1);

        // Get the VBI data and then decode (frames are indexed from 1)
        QVector<qint32> vbi1 = ldDecodeMetaData.getFieldVbi(ldDecodeMetaData.getFirstFieldNumber(frameNumber + 1)).vbiData;
        QVector<qint32> vbi2 = ldDecodeMetaData.getFieldVbi(ldDecodeMetaData.getSecondFieldNumber(frameNumber + 1)).vbiData;
        vbiData[frameNumber] = vbiDecoder.decodeFrame(vbi1[0], vbi1[1], vbi1[2], vbi2[0], vbi2[1], vbi2[2]);

        if (vbiData[frameNumber].leadIn || vbiData[frameNumber].leadOut) m_frames[frameNumber].isLeadInOrOut(true);
        else m_frames[frameNumber].isLeadInOrOut(false);
    }

    // Get the source format (PAL/NTSC)
    if (ldDecodeMetaData.getVideoParameters().isSourcePal) m_isDiscPal = true;
    else m_isDiscPal = false;

    // Get the disc type (CAV/CLV)
    qint32 framesToCheck = 100;
    if (m_numberOfFrames < framesToCheck) framesToCheck = m_numberOfFrames;
    qDebug() << "Checking first" << framesToCheck << "sequential frames for disc CAV/CLV type determination";

    qint32 cavCount = 0;
    qint32 clvCount = 0;
    // Count how many frames are marked as CAV or CLV in the metadata
    for (qint32 frameNumber = 0; frameNumber < framesToCheck; frameNumber++) {
        // Look for a complete, valid CAV picture number or CLV time-code
        if (vbiData[frameNumber].picNo > 0) cavCount++;
        if (vbiData[frameNumber].clvHr != -1 && vbiData[frameNumber].clvMin != -1 &&
                vbiData[frameNumber].clvSec != -1 && vbiData[frameNumber].clvPicNo != -1) clvCount++;
    }

    // If the metadata has no picture numbers or time-codes, we cannot use the source
    if (cavCount == 0 && clvCount == 0) {
        qDebug() << "Source does not seem to contain valid CAV picture numbers or CLV time-codes - cannot map";
        m_tbcValid = false;
        return;
    }

    // Determine disc type
    if (cavCount > clvCount) {
        m_isDiscCav = true;
        qDebug() << "Got" << cavCount << "valid CAV picture numbers from" << framesToCheck << "frames - source disc type is CAV";
    } else {
        m_isDiscCav = false;
        qDebug() << "Got" << clvCount << "valid CLV picture numbers from" << framesToCheck << "frames - source disc type is CLV";
    }

    // If the disc type is CLV, convert the timecodes into frame numbers and update the stored VBI
    // otherwise just store the CAV picture numbers
    if (m_isDiscCav)  qDebug() << "Storing VBI CAV picture numbers as frame numbers";
    else qDebug() << "Converting VBI CLV timecodes into frame numbers";
    for (qint32 frameNumber = 0; frameNumber < m_numberOfFrames; frameNumber++) {
        if (!m_isDiscCav) {
            // Attempt to translate the CLV timecode into a frame number
            LdDecodeMetaData::ClvTimecode clvTimecode;
            clvTimecode.hours = vbiData[frameNumber].clvHr;
            clvTimecode.minutes = vbiData[frameNumber].clvMin;
            clvTimecode.seconds = vbiData[frameNumber].clvSec;
            clvTimecode.pictureNumber = vbiData[frameNumber].clvPicNo;
            m_frames[frameNumber].vbiFrameNumber(ldDecodeMetaData.convertClvTimecodeToFrameNumber(clvTimecode));
        } else {
            m_frames[frameNumber].vbiFrameNumber(vbiData[frameNumber].picNo);
        }
    }

    // Check for the presence of pull-down frames (if NTSC CAV)
    m_numberOfPulldowns = false;
    if (!m_isDiscPal && m_isDiscCav) {
        qDebug() << "Disc type is NTSC CAV - checking for pull-down frames";

        for (qint32 frameNumber = 0; frameNumber < m_numberOfFrames; frameNumber++) {
            bool isPulldown = false;

            // Does the current frame have a frame number (and is not lead in/out)?
            if (m_frames[frameNumber].vbiFrameNumber() == -1 && !m_frames[frameNumber].isLeadInOrOut()) {
                // Get the phaseID of the preceeding frame (with underflow protection)
                qint32 lastPhase2 = -1;
                if (frameNumber > 0) lastPhase2 = ldDecodeMetaData.getField(
                            ldDecodeMetaData.getSecondFieldNumber(frameNumber)).fieldPhaseID; // -1

                // Get the phaseID of the current frame
                qint32 currentPhase1 = ldDecodeMetaData.getField(ldDecodeMetaData.getFirstFieldNumber(frameNumber + 1)).fieldPhaseID;
                qint32 currentPhase2 = ldDecodeMetaData.getField(ldDecodeMetaData.getSecondFieldNumber(frameNumber + 1)).fieldPhaseID;

                // Get the phaseID of the following frame (with overflow protection)
                qint32 nextPhase1 = -1;
                if (frameNumber < m_numberOfFrames - 1) nextPhase1 = ldDecodeMetaData.getField(
                            ldDecodeMetaData.getFirstFieldNumber(frameNumber + 2)).fieldPhaseID; // +1

                // Work out what the preceeding phase is expected to be
                qint32 expectedLastPhase;
                qint32 expectedNextPhase;
                qint32 expectedIntraPhase;

                if (!m_reverseFieldOrder) {
                    // Normal field order
                    expectedLastPhase = currentPhase1 - 1;
                    if (expectedLastPhase == 0) expectedLastPhase = 4;

                    // Work out what the subsequent phase is expected to be
                    expectedNextPhase = currentPhase2 + 1;
                    if (expectedNextPhase == 5) expectedNextPhase = 1;

                    // Work out what the infra-frame phase is expected to be
                    expectedIntraPhase = currentPhase1 + 1;
                    if (expectedIntraPhase == 5) expectedIntraPhase = 1;
                } else {
                    // Reversed field order
                    expectedLastPhase = currentPhase1 + 1;
                    if (expectedLastPhase == 5) expectedLastPhase = 1;

                    // Work out what the subsequent phase is expected to be
                    expectedNextPhase = currentPhase2 - 1;
                    if (expectedNextPhase == 0) expectedNextPhase = 4;

                    // Work out what the infra-frame phase is expected to be
                    expectedIntraPhase = currentPhase1 - 1;
                    if (expectedIntraPhase == 0) expectedIntraPhase = 4;
                }

                // Now confirm everything is sane
                if (currentPhase2 == expectedIntraPhase) {
                    if (lastPhase2 == expectedLastPhase || lastPhase2 == -1) {
                         if (nextPhase1 == expectedNextPhase || nextPhase1 == -1) {
                             // It's very likely this is a pulldown frame
                             isPulldown = true;
                         } else {
                             // Probably not a pull-down frame
                             qDebug() << "Seq. frame" << m_frames[frameNumber].seqFrameNumber() << "is not in phase sequence with the subsequent frame!";
                         }
                    } else {
                        // Probably not a pull-down frame
                        qDebug() << "Seq. frame" << m_frames[frameNumber].seqFrameNumber() << "is not in phase sequence with the preceeding frame!";
                    }
                } else {
                    // Probably not a pull-down frame
                    qDebug() << "Seq. frame" << m_frames[frameNumber].seqFrameNumber() << "has an incorrect intra-frame phaseID!";
                }

                // If we have a possible pull-down, perform an additional check based on the VBI numbering
                // If it's really a pull-down, then the VBI frame numbers should be missing 5 frames before
                // and after the current frame...
                qint32 doubleCheckCounter = 0;
                if (frameNumber > 5) {
                    if (vbiData[frameNumber - 5].picNo == -1) doubleCheckCounter++;
                }
                if (frameNumber < m_numberOfFrames - 5) {
                    if (vbiData[frameNumber + 5].picNo == -1) doubleCheckCounter++;
                }

                if (doubleCheckCounter < 1) {
                    qDebug() << "Seq. frame" << m_frames[frameNumber].seqFrameNumber() <<
                                "looks like a pull-down, but there is no pull-down sequence in the surrounding frames - marking as false-positive";
                    isPulldown = false;
                }

                m_frames[frameNumber].isPullDown(isPulldown);
                if (isPulldown) {
                    //qDebug() << "Seq. frame" << m_frames[frameNumber].seqFrameNumber << "marked as pulldown";
                    m_numberOfPulldowns++;
                }
            }
        }
    }

    // Measure and record a quality value for each frame
    qDebug() << "Performing a frame quality analysis for each frame";
    for (qint32 frameNumber = 0; frameNumber < m_numberOfFrames; frameNumber++) {
        // If the frame following the current one has a lower VBI number, give the current
        // frame a quality penalty as the likelyhood the player skipped is higher
        qreal penaltyPercent = 0;
        if (frameNumber < m_numberOfFrames - 1) {
            if (vbiData[frameNumber + 1].picNo < vbiData[frameNumber].picNo) penaltyPercent = 80.0;
            else penaltyPercent = 100.0;
        }

        // Add the Black SNR to the quality value (here we consider 45+45 to be 100%)
        qint32 bsnr = ldDecodeMetaData.getFieldVitsMetrics(ldDecodeMetaData.getFirstFieldNumber(frameNumber + 1)).bPSNR +
                ldDecodeMetaData.getFieldVitsMetrics(ldDecodeMetaData.getSecondFieldNumber(frameNumber + 1)).bPSNR;

        qreal bsnrPercent = (100 / 90) * static_cast<qreal>(bsnr);

        // Calculate the cumulative length of all the dropouts in the frame (by summing both fields)
        qint32 totalDotsInFrame = (ldDecodeMetaData.getVideoParameters().fieldHeight * 2) + ldDecodeMetaData.getVideoParameters().fieldWidth;
        LdDecodeMetaData::DropOuts dropOuts1 = ldDecodeMetaData.getFieldDropOuts(ldDecodeMetaData.getFirstFieldNumber(frameNumber + 1));
        LdDecodeMetaData::DropOuts dropOuts2 = ldDecodeMetaData.getFieldDropOuts(ldDecodeMetaData.getSecondFieldNumber(frameNumber + 1));

        qint32 frameDoLength = 0;
        for (qint32 i = 0; i < dropOuts1.startx.size(); i++) {
            frameDoLength += dropOuts1.endx[i] - dropOuts1.startx[i];
        }

        for (qint32 i = 0; i < dropOuts2.startx.size(); i++) {
            frameDoLength += dropOuts2.endx[i] - dropOuts2.startx[i];
        }

        qreal frameDoPercent = 100.0 - (static_cast<qreal>(frameDoLength) / static_cast<qreal>(totalDotsInFrame));

        // Include the sync confidence in the quality value (this is 100% where each measurement is 50% of the total)
        qint32 syncConfPercent = (ldDecodeMetaData.getField(ldDecodeMetaData.getFirstFieldNumber(frameNumber + 1)).syncConf +
                                  ldDecodeMetaData.getField(ldDecodeMetaData.getSecondFieldNumber(frameNumber + 1)).syncConf) / 2;

        m_frames[frameNumber].frameQuality((bsnrPercent + penaltyPercent + syncConfPercent + (frameDoPercent * 1000.0)) / 1004.0);
        //qDebug() << "Frame:" << frameNumber << bsnrPercent << penaltyPercent << syncConfPercent << frameDoPercent << "quality =" << m_frames[frameNumber].frameQuality;
    }

}

// Custom streaming operator (for debug)
QDebug operator<<(QDebug dbg, const DiscMap &discMap)
{
    dbg.nospace().noquote() << "DiscMap(Frames " << discMap.numberOfFrames() <<
                               ", disc type is " << discMap.discType() << ", video format is " <<
                               discMap.discFormat() << ", detected " <<
                               discMap.numberOfPulldowns() << " pulldown frames)";

    return dbg.maybeSpace();
}

// Get methods

// Get the metadata file name for the TBC
QString DiscMap::filename() const
{
    return m_metadataFileInfo.filePath();
}

// Get the validity flag
bool DiscMap::valid() const
{
    return m_tbcValid;
}

// Get the available number of frames
qint32 DiscMap::numberOfFrames() const
{
    return m_numberOfFrames;
}

// Get the disc type
bool DiscMap::isDiscCav() const
{
    return m_isDiscCav;
}

// Get the disc video format
bool DiscMap::isDiscPal() const
{
    return m_isDiscPal;
}

// Method to return the disc type as a string
QString DiscMap::discType() const
{
    QString discType;
    if (m_isDiscCav) discType = "CAV";
    else discType = "CLV";

    return discType;
}

// Method to return the disc format as a string
QString DiscMap::discFormat() const
{
    QString discFormat;
    if (m_isDiscPal) discFormat = "PAL";
    else discFormat = "NTSC";

    return discFormat;
}

// Method to return the VBI frame number
qint32 DiscMap::vbiFrameNumber(qint32 frameNumber) const
{
    if (frameNumber < 0 || frameNumber >= m_numberOfFrames) {
        qDebug() << "vbiFrameNumber out of frameNumber range";
        return -1;
    }
    return m_frames[frameNumber].vbiFrameNumber();
}

// Method to set the VBI frame number
void DiscMap::setVbiFrameNumber(qint32 frameNumber, qint32 vbiFrameNumber)
{
    if (frameNumber < 0 || frameNumber >= m_numberOfFrames) {
        qDebug() << "setVbiFrameNumber out of frameNumber range";
        return;
    }
    m_frames[frameNumber].vbiFrameNumber(vbiFrameNumber);
}

// Method to return the original sequential frame number (which maps to the lddecodemetadata VBI)
qint32 DiscMap::seqFrameNumber(qint32 frameNumber) const
{
    if (frameNumber < 0 || frameNumber >= m_numberOfFrames) {
        qDebug() << "seqFrameNumber out of frameNumber range";
        return -1;
    }
    return m_frames[frameNumber].seqFrameNumber();
}

// Get the pulldown flag for a frame
bool DiscMap::isPulldown(qint32 frameNumber) const
{
    if (frameNumber < 0 || frameNumber >= m_numberOfFrames) {
        qDebug() << "isPulldown out of frameNumber range";
        return false;
    }
    return m_frames[frameNumber].isPullDown();
}

// Get the picture stop flag for a frame
bool DiscMap::isPictureStop(qint32 frameNumber) const
{
    if (frameNumber < 0 || frameNumber >= m_numberOfFrames) {
        qDebug() << "isPictureStop out of frameNumber range";
        return false;
    }
    return m_frames[frameNumber].isPictureStop();
}

// Get the number of pulldown frames on the disc
qint32 DiscMap::numberOfPulldowns() const
{
    return m_numberOfPulldowns;
}

// Get the lead in/out flag for a frame
bool DiscMap::isLeadInOut(qint32 frameNumber) const
{
    if (frameNumber < 0 || frameNumber >= m_numberOfFrames) {
        qDebug() << "isLeadInOut out of frameNumber range";
        return false;
    }
    return m_frames[frameNumber].isLeadInOrOut();
}

// Get the frame quality
qreal DiscMap::frameQuality(qint32 frameNumber) const
{
    if (frameNumber < 0 || frameNumber >= m_numberOfFrames) {
        qDebug() << "frameQuality out of frameNumber range";
        return -1;
    }
    return m_frames[frameNumber].frameQuality();
}

// Get the isPadded flag
bool DiscMap::isPadded(qint32 frameNumber) const
{
    if (frameNumber < 0 || frameNumber >= m_numberOfFrames) {
        qDebug() << "isPadded out of frameNumber range";
        return false;
    }
    return m_frames[frameNumber].isPadded();
}

// Set a frame as marked for deletion
void DiscMap::setMarkedForDeletion(qint32 frameNumber)
{
    if (frameNumber < 0 || frameNumber >= m_numberOfFrames) {
        qDebug() << "setMarkedForDeletion out of frameNumber range";
        return;
    }
    m_frames[frameNumber].isMarkedForDeletion(true);
}

// Flush the frames (delete anything marked for deletion)
// Returns the number of frames deleted
qint32 DiscMap::flush()
{
    qint32 origSize = m_frames.size();

    // Erase
    m_frames.erase(
        std::remove_if(m_frames.begin(), m_frames.end(),
                       [](const Frame &o) { return o.isMarkedForDeletion(); }),
                m_frames.end());

    // Reset the number of available frames
    m_numberOfFrames = m_frames.size();

    return origSize - m_frames.size();
}

// Sort the discmap by frame number (accounting for pull-downs if required)
void DiscMap::sort()
{
    // Here we sort the disc map (m_frames) using frame numbers.  If a frame is NTSC CAV pull-down
    // it will not have a frame number - the only thing we can do is sort it so the
    // pull-downs are sorted following the preceeding numbered frame (which should keep
    // them in the right place).
    //
    // Note that the stuct has an overloaded < operator that controls the sort comparison
    // (see the .h file)
    std::sort(m_frames.begin(), m_frames.end());
}
