/************************************************************************

    f2framestoaudio.cpp

    ld-process-efm - EFM data decoder
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-process-efm is free software: you can redistribute it and/or
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

#include "JsonWax/JsonWax.h"
#include "f2framestoaudio.h"
#include "logging.h"

F2FramesToAudio::F2FramesToAudio()
{
    reset();
}

// Method to reset and flush all buffers
void F2FramesToAudio::reset(void)
{
    sectionsIn.clear();
    f2FramesIn.clear();
    qMetaModeVector.clear();
    qMetaDataVector.clear();
    previousDiscTime.setTime(0, 0, 0);
    sampleGapFirstCheck = true;

    resetStatistics();
}

// Methods to handle statistics
void F2FramesToAudio::resetStatistics(void)
{
    statistics.totalAudioSamples = 0;
    statistics.validAudioSamples = 0;
    statistics.invalidAudioSamples = 0;
    statistics.paddedAudioSamples = 0;
    statistics.sectionsProcessed = 0;
    statistics.encoderRunning = 0;
    statistics.encoderStopped = 0;
    statistics.qModeInvalidCount = 0;
    statistics.qModeCorrectedCount = 0;
    statistics.trackNumber = 0;
    statistics.subdivision = 0;
    statistics.discTime.setTime(0, 0, 0);
    statistics.trackTime.setTime(0, 0, 0);
    statistics.initialDiscTime.setTime(0, 0, 0);

    // Subcode block Q mode counters
    statistics.qMode1Count = 0;
    statistics.qMode4Count = 0;
}

F2FramesToAudio::Statistics F2FramesToAudio::getStatistics(void)
{
    return statistics;
}

// Method to write status information to qCInfo
void F2FramesToAudio::reportStatus(void)
{
    qInfo() << "F2 Frames to audio converter:";
    qInfo() << "  Total audio samples =" << statistics.totalAudioSamples;
    qInfo() << "  Valid audio samples =" << statistics.validAudioSamples;
    qInfo() << "  Invalid audio samples =" << statistics.invalidAudioSamples;
    qInfo() << "  Padded audio samples =" << statistics.paddedAudioSamples;
    qInfo() << "  Sections processed =" << statistics.sectionsProcessed;
    qInfo() << "  Encoder running sections =" << statistics.encoderRunning;
    qInfo() << "  Encoder stopped sections =" << statistics.encoderStopped;
    qInfo() << "  Initial disc time =" << statistics.initialDiscTime.getTimeAsQString();

    qInfo() << "  Q Mode 1 sections =" << statistics.qMode1Count << "(CD Audio)";
    qInfo() << "  Q Mode 4 sections =" << statistics.qMode4Count << "(LD Audio)";
    qInfo() << "  Q Mode invalid sections =" << statistics.qModeInvalidCount;
    qInfo() << "  Q Mode corrected sections =" << statistics.qModeCorrectedCount;
}

// Method to set the audio output file
bool F2FramesToAudio::setOutputFile(QFile *outputFileHandle)
{
    // Open output file for writing
    this->outputFileHandle = outputFileHandle;

    // Exit with success
    return true;
}

// Convert F2 frames into audio sample data
void F2FramesToAudio::convert(QVector<F2Frame> f2Frames, QVector<Section> sections)
{
    // Note: At a sample rate of 44100Hz there are 44,100 samples per second
    // There are 75 sections per second
    // Therefore there are 588 samples per section

    // Each F2 frame contains 24 bytes and there are 4 bytes per stereo sample pair
    // therefore each F2 contains 6 samples
    // therefore there are 98 F2 frames per section
    f2FramesIn.append(f2Frames);
    sectionsIn.append(sections);

    // Do we have enough data to output audio information?
    if (f2FramesIn.size() >= 98 && sectionsIn.size() >= 1) processAudio();
}

// NOTE: keep track of the elapsed time by number of samples (independent of the sections etc)

void F2FramesToAudio::processAudio(void)
{
    QByteArray dummyF2Frame;
    dummyF2Frame.fill(0, 24);

    qint32 f2FrameNumber = 0;
    qint32 sectionsToProcess = f2FramesIn.size() / 98;
    if (sectionsIn.size() < sectionsToProcess) sectionsToProcess = sectionsIn.size();

    // Process one section of audio at a time (98 F2 Frames)
    for (qint32 sectionNo = 0; sectionNo < sectionsToProcess; sectionNo++) {
        // Get the required metadata for processing from the section
        Metadata metadata = sectionToMeta(sectionsIn[sectionNo]);

        // Check if there was a gap since the last output samples (and fill it if
        // necessary)
        TrackTime discTimeTemp = previousDiscTime; // Just for debug
        qint32 gap = checkForSampleGap(metadata);
        if (gap != 1) {
            if (gap > 1) {
                for (qint32 i = 0; i < (gap - 1); i++) {
                    statistics.paddedAudioSamples += 6 * 98;
                    statistics.totalAudioSamples += 6 * 98;
                    outputFileHandle->write(dummyF2Frame);
                }
                qDebug().noquote() << "F2FramesToAudio::processAudio(): Metadata indicates unwanted gap of" << gap << "F2 frames!" <<
                           "Previous good metadata was" << discTimeTemp.getTimeAsQString() << "and current metadata is" <<
                           metadata.discTime.getTimeAsQString();
                            } else {
                // Gap was zero... probably a skip/repeat causing the issue
                // So we ignore it and output nothing
                qDebug() << "F2FramesToAudio::processAudio(): Got F2 frame gap of" << gap << "between samples - possible skip/repeat error in EFM";
            }
        }

        // Output the samples to file (98 f2 frames x 6 samples per frame = 588)
        for (qint32 i = f2FrameNumber; i < f2FrameNumber + 98; i++) {
            if (metadata.encoderRunning && (metadata.qMode == 1 || metadata.qMode == 4)) {
                // Encoder running, output audio samples

                // Check F2 Frame data payload validity
                if (!f2FramesIn[i].getDataValid()) {
                    // F2 Frame data has errors - 6 samples might be garbage
                    statistics.invalidAudioSamples += 6;
                    statistics.totalAudioSamples += 6;
                    outputFileHandle->write(dummyF2Frame);
                } else {
                    // F2 Frame good
                    statistics.validAudioSamples += 6; // 24 bytes per F2 (/2 = 16-bit and /2 = stereo)
                    statistics.totalAudioSamples += 6;
                    outputFileHandle->write(f2FramesIn[i].getDataSymbols()); // 24 bytes per F2

                    // Note: At some point, audio error concealing should be implemented here
                }
            } else {
                // Encoder stopped (or current output isn't audio), output F2 frame's worth in zeros
                statistics.validAudioSamples += 6;
                statistics.totalAudioSamples += 6;
                outputFileHandle->write(dummyF2Frame);
            }
        }
        f2FrameNumber += 98;
        statistics.sectionsProcessed++;
    }

    // Remove processed F2Frames and samples from buffer
    f2FramesIn.remove(0, sectionsToProcess * 98);
    sectionsIn.remove(0, sectionsToProcess);
}

// Examine metadata and check for unwanted sample gaps (due to lower-level decoding
// failure)
qint32 F2FramesToAudio::checkForSampleGap(Metadata metadata)
{
    // Is this the first check performed?
    if (sampleGapFirstCheck) {
        if (metadata.qMode == 1 || metadata.qMode == 4) {
            previousDiscTime.setTime(metadata.discTime.getTime());
            sampleGapFirstCheck = false;

            // Store the initial disc time
            statistics.initialDiscTime.setTime(metadata.discTime.getTime());
            qDebug().noquote() << "F2FramesToAudio::checkForSampleGap(): First valid Q Mode 1 or 4 disc time seen is" << metadata.discTime.getTimeAsQString();
            return 0;
        } else {
            // Can do anything this time
            return 0;
        }
    }

    // Check that this sample is one frame difference from the previous
    qint32 gap = abs(metadata.discTime.getDifference(previousDiscTime.getTime()));
    previousDiscTime = metadata.discTime;
    return gap;
}

// Metadata processing ------------------------------------------------------------------------------------------------

// Method to open the metadata output file
bool F2FramesToAudio::setMetadataOutputFile(QFile *outputMetadataFileHandle)
{
    // Open output file for writing
    this->outputMetadataFileHandle = outputMetadataFileHandle;

    // Here we just store the required filename
    // The file is created and filled on close
    jsonFilename = outputMetadataFileHandle->fileName();

    // Exit with success
    return true;
}

// Method to flush the metadata to the output file
void F2FramesToAudio::flushMetadata(void)
{
    // Define the JSON object
    JsonWax json;

    // Write out the entries
    for (qint32 subcodeNo = 0; subcodeNo < qMetaDataVector.size(); subcodeNo++) {
        // Process entry
        json.setValue({"subcode", subcodeNo, "seqNo"}, subcodeNo);

        if (qMetaModeVector[subcodeNo] == 1) {
            // Q-Mode 1 - CD audio
            json.setValue({"subcode", subcodeNo, "qControl", "isAudio"}, qMetaDataVector[subcodeNo].qControl.isAudioNotData);
            json.setValue({"subcode", subcodeNo, "qControl", "isStereo"}, qMetaDataVector[subcodeNo].qControl.isStereoNotQuad);
            json.setValue({"subcode", subcodeNo, "qControl", "isNoPreemp"}, qMetaDataVector[subcodeNo].qControl.isNoPreempNotPreemp);
            json.setValue({"subcode", subcodeNo, "qControl", "isCopyProtected"}, qMetaDataVector[subcodeNo].qControl.isCopyProtectedNotUnprotected);

            json.setValue({"subcode", subcodeNo, "qData", "qMode"}, qMetaModeVector[subcodeNo]);
            json.setValue({"subcode", subcodeNo, "qData", "isLeadIn"}, qMetaDataVector[subcodeNo].qMode1.isLeadIn);
            json.setValue({"subcode", subcodeNo, "qData", "isLeadOut"}, qMetaDataVector[subcodeNo].qMode1.isLeadOut);
            json.setValue({"subcode", subcodeNo, "qData", "trackNumber"}, qMetaDataVector[subcodeNo].qMode1.trackNumber);
            json.setValue({"subcode", subcodeNo, "qData", "point"}, qMetaDataVector[subcodeNo].qMode1.point);
            json.setValue({"subcode", subcodeNo, "qData", "x"}, qMetaDataVector[subcodeNo].qMode1.x);
            json.setValue({"subcode", subcodeNo, "qData", "trackTime"}, qMetaDataVector[subcodeNo].qMode1.trackTime.getTimeAsQString());
            json.setValue({"subcode", subcodeNo, "qData", "discTime"}, qMetaDataVector[subcodeNo].qMode1.discTime.getTimeAsQString());
        } else if (qMetaModeVector[subcodeNo] == 4) {
            // Q-Mode 4 - LD Audio
            json.setValue({"subcode", subcodeNo, "qControl", "isAudio"}, qMetaDataVector[subcodeNo].qControl.isAudioNotData);
            json.setValue({"subcode", subcodeNo, "qControl", "isStereo"}, qMetaDataVector[subcodeNo].qControl.isStereoNotQuad);
            json.setValue({"subcode", subcodeNo, "qControl", "isNoPreemp"}, qMetaDataVector[subcodeNo].qControl.isNoPreempNotPreemp);
            json.setValue({"subcode", subcodeNo, "qControl", "isCopyProtected"}, qMetaDataVector[subcodeNo].qControl.isCopyProtectedNotUnprotected);

            json.setValue({"subcode", subcodeNo, "qData", "qMode"}, qMetaModeVector[subcodeNo]);
            json.setValue({"subcode", subcodeNo, "qData", "isLeadIn"}, qMetaDataVector[subcodeNo].qMode4.isLeadIn);
            json.setValue({"subcode", subcodeNo, "qData", "isLeadOut"}, qMetaDataVector[subcodeNo].qMode4.isLeadOut);
            json.setValue({"subcode", subcodeNo, "qData", "trackNumber"}, qMetaDataVector[subcodeNo].qMode4.trackNumber);
            json.setValue({"subcode", subcodeNo, "qData", "point"}, qMetaDataVector[subcodeNo].qMode4.point);
            json.setValue({"subcode", subcodeNo, "qData", "x"}, qMetaDataVector[subcodeNo].qMode4.x);
            json.setValue({"subcode", subcodeNo, "qData", "trackTime"}, qMetaDataVector[subcodeNo].qMode4.trackTime.getTimeAsQString());
            json.setValue({"subcode", subcodeNo, "qData", "discTime"}, qMetaDataVector[subcodeNo].qMode4.discTime.getTimeAsQString());
        } else {
            // Unknown Q Mode / Non-Audio Q Mode
            json.setValue({"subcode", subcodeNo, "qControl", "isAudio"}, qMetaDataVector[subcodeNo].qControl.isAudioNotData);
            json.setValue({"subcode", subcodeNo, "qControl", "isStereo"}, qMetaDataVector[subcodeNo].qControl.isStereoNotQuad);
            json.setValue({"subcode", subcodeNo, "qControl", "isNoPreemp"}, qMetaDataVector[subcodeNo].qControl.isNoPreempNotPreemp);
            json.setValue({"subcode", subcodeNo, "qControl", "isCopyProtected"}, qMetaDataVector[subcodeNo].qControl.isCopyProtectedNotUnprotected);

            json.setValue({"subcode", subcodeNo, "qData", "qMode"}, qMetaModeVector[subcodeNo]);
        }
    }

    // Write the JSON object to file
    qDebug() << "SectionToMeta::closeOutputFile(): Writing JSON metadata file";
    if (!json.saveAs(jsonFilename, JsonWax::Readable)) {
        qCritical("Writing JSON file failed!");
        return;
    }
}

// Method to process as section into audio metadata
F2FramesToAudio::Metadata F2FramesToAudio::sectionToMeta(Section section)
{
    Metadata metadata;

    // Get the Q Mode and update the statistics
    metadata.qMode = section.getQMode();
    if (metadata.qMode == 1) statistics.qMode1Count++;
    else if (metadata.qMode == 4) statistics.qMode4Count++;
    else statistics.qModeInvalidCount++;

    // Store the metadata (for the flush JSON operation)
    Section::QMetadata qMetaData = section.getQMetadata();
    qMetaModeVector.append(metadata.qMode);
    qMetaDataVector.append(qMetaData);

    // Simplify the metadata
    metadata = simplifyMetadata(qMetaData, metadata.qMode);

    // Perform metadata correction?
    // Note: This does not correct the JSON metadata, only the internal representation
    // this is to prevent the encoder being turned off when it shouldn't be (and therefore
    // preventing the decoder from outputting valid audio samples due to Q channel corruption)
    if (metadata.qMode != 1 && metadata.qMode != 4) {
        // Invalid section or Non-audio Q Mode

        // Find last known good audio metadata (Q Mode 1 or 4)
        qint32 lastKnownGood = -1;
        for (qint32 i = qMetaModeVector.size() - 1; i >= 0; i--) {
            if (qMetaModeVector[i] == 1 || qMetaModeVector[i] == 4) {
                lastKnownGood = i;
                break;
            }
        }

        // Found a good qMode?
        if (lastKnownGood != -1) {
            // Simplify last known good metadata
            metadata = simplifyMetadata(qMetaDataVector[lastKnownGood], qMetaModeVector[lastKnownGood]);
            qint32 frameDifference = (qMetaModeVector.size() - 1) - lastKnownGood;

            // Check for lead-in and/or audio pause encoding (as track time clock runs backwards during these sections)
            if (metadata.isClockRunningForwards) {
                // Not lead-in, so track time clock is running forwards
                metadata.discTime.addFrames(frameDifference);
                metadata.trackTime.addFrames(frameDifference);
            } else {
                // Lead-in, so clock is running backwards
                metadata.discTime.addFrames(frameDifference);
                metadata.trackTime.subtractFrames(frameDifference);
            }

            qDebug().noquote() << "F2FramesToAudio::sectionToMeta(): Corrected to disc time" << metadata.discTime.getTimeAsQString() <<
                        "and track time" << metadata.trackTime.getTimeAsQString() << "from last good metadata" << frameDifference <<
                                  "frame(s) back";
            metadata.isCorrected = true;
            statistics.qModeCorrectedCount++;
        } else {
            // No last known good metadata - cannot correct
            qDebug() << "F2FramesToAudio::sectionToMeta(): Unable to correct corrupt metadata entry - no last known good metadata";
            metadata.trackNumber = -1;
            metadata.subdivision = -1;
            metadata.trackTime.setTime(0, 0, 0);
            metadata.discTime.setTime(0, 0, 0);
            metadata.encoderRunning = false;
            metadata.isCorrected = false;
            metadata.isLeadIn = false;
        }
    }

    // Update statistics
    statistics.discTime = metadata.discTime;
    statistics.trackTime = metadata.trackTime;
    statistics.subdivision = metadata.subdivision;
    statistics.trackNumber = metadata.trackNumber;

    if (metadata.encoderRunning) statistics.encoderRunning++;
    else statistics.encoderStopped++;

    return metadata;
}

// Translate section metadata to our simple metadata format for internal processing
F2FramesToAudio::Metadata F2FramesToAudio::simplifyMetadata(Section::QMetadata qMetaData, qint32 qMode)
{
    Metadata metadata;

    // Set the qMode
    metadata.qMode = qMode;

    // Depending on the section Q Mode, process the section
    if (metadata.qMode == 1) {
        // CD Audio
        if (qMetaData.qMode1.isLeadIn) {
            // Q Mode 1 - Lead in section
            metadata.trackNumber = qMetaData.qMode1.trackNumber;
            metadata.subdivision = qMetaData.qMode1.point;
            metadata.trackTime = qMetaData.qMode1.trackTime;
            metadata.discTime = qMetaData.qMode1.discTime;
            metadata.encoderRunning = false;
            metadata.isCorrected = false;
            metadata.isLeadIn = true;
            metadata.isClockRunningForwards = false;
        } else if (qMetaData.qMode1.isLeadOut) {
            // Q Mode 1 - Lead out section
            if (qMetaData.qMode1.x == 0) {
                // Encoding paused
                metadata.trackNumber = qMetaData.qMode1.trackNumber;
                metadata.subdivision = 0;
                metadata.trackTime = qMetaData.qMode1.trackTime;
                metadata.discTime = qMetaData.qMode1.discTime;
                metadata.encoderRunning = false;
                metadata.isCorrected = false;
                metadata.isLeadIn = false;
                metadata.isClockRunningForwards = true;
            } else {
                // Encoding running
                metadata.trackNumber = qMetaData.qMode1.trackNumber;
                metadata.subdivision = 0;
                metadata.trackTime = qMetaData.qMode1.trackTime;
                metadata.discTime = qMetaData.qMode1.discTime;
                metadata.encoderRunning = true;
                metadata.isCorrected = false;
                metadata.isLeadIn = false;
                metadata.isClockRunningForwards = true;
            }
        } else {
            // Q Mode 1 - Audio section
            if (qMetaData.qMode1.x == 0) {
                // Encoding paused
                metadata.trackNumber = qMetaData.qMode1.trackNumber;
                metadata.subdivision = qMetaData.qMode1.x;
                metadata.trackTime = qMetaData.qMode1.trackTime;
                metadata.discTime = qMetaData.qMode1.discTime;
                metadata.encoderRunning = false;
                metadata.isCorrected = false;
                metadata.isLeadIn = false;
                metadata.isClockRunningForwards = false;
            } else {
                // Encoding running
                metadata.trackNumber = qMetaData.qMode1.trackNumber;
                metadata.subdivision = qMetaData.qMode1.x;
                metadata.trackTime = qMetaData.qMode1.trackTime;
                metadata.discTime = qMetaData.qMode1.discTime;
                metadata.encoderRunning = true;
                metadata.isCorrected = false;
                metadata.isLeadIn = false;
                metadata.isClockRunningForwards = true;
            }
        }
    } else if (metadata.qMode == 4) {
        // 4 = non-CD Audio (LaserDisc)
        if (qMetaData.qMode4.isLeadIn) {
            // Q Mode 4 - Lead in section
            metadata.trackNumber = qMetaData.qMode4.trackNumber;
            metadata.subdivision = qMetaData.qMode4.point;
            metadata.trackTime = qMetaData.qMode4.trackTime;
            metadata.discTime = qMetaData.qMode4.discTime;
            metadata.encoderRunning = false;
            metadata.isCorrected = false;
            metadata.isLeadIn = true;
            metadata.isClockRunningForwards = false;
        } else if (qMetaData.qMode4.isLeadOut) {
            // Q Mode 4 - Lead out section
            if (qMetaData.qMode4.x == 0) {
                // Encoding paused
                metadata.trackNumber = qMetaData.qMode4.trackNumber;
                metadata.subdivision = 0;
                metadata.trackTime = qMetaData.qMode4.trackTime;
                metadata.discTime = qMetaData.qMode4.discTime;
                metadata.encoderRunning = false;
                metadata.isCorrected = false;
                metadata.isLeadIn = false;
                metadata.isClockRunningForwards = true;
            } else {
                // Encoding running
                metadata.trackNumber = qMetaData.qMode4.trackNumber;
                metadata.subdivision = 0;
                metadata.trackTime = qMetaData.qMode4.trackTime;
                metadata.discTime = qMetaData.qMode4.discTime;
                metadata.encoderRunning = true;
                metadata.isCorrected = false;
                metadata.isLeadIn = false;
                metadata.isClockRunningForwards = true;
            }
        } else {
            // Q Mode 4 - Audio section
            if (qMetaData.qMode4.x == 0) {
                // Encoding paused
                metadata.trackNumber = qMetaData.qMode4.trackNumber;
                metadata.subdivision = qMetaData.qMode4.x;
                metadata.trackTime = qMetaData.qMode4.trackTime;
                metadata.discTime = qMetaData.qMode4.discTime;
                metadata.encoderRunning = false;
                metadata.isCorrected = false;
                metadata.isLeadIn = false;
                metadata.isClockRunningForwards = false;
            } else {
                // Encoding running
                metadata.trackNumber = qMetaData.qMode4.trackNumber;
                metadata.subdivision = qMetaData.qMode4.x;
                metadata.trackTime = qMetaData.qMode4.trackTime;
                metadata.discTime = qMetaData.qMode4.discTime;
                metadata.encoderRunning = true;
                metadata.isCorrected = false;
                metadata.isLeadIn = false;
                metadata.isClockRunningForwards = true;
            }
        }
    }

    return metadata;
}
