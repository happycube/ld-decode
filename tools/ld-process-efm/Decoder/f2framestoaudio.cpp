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

#include "f2framestoaudio.h"
#include "logging.h"

F2FramesToAudio::F2FramesToAudio()
{
    reset();
}

// Method to reset and flush all buffers
void F2FramesToAudio::reset(void)
{
    resetStatistics();
}

// Methods to handle statistics
void F2FramesToAudio::resetStatistics(void)
{
    statistics.validAudioSamples = 0;
    statistics.invalidAudioSamples = 0;
    statistics.sectionsProcessed = 0;
    statistics.encoderRunning = 0;
    statistics.encoderStopped = 0;
    statistics.unknownQMode = 0;
    statistics.trackNumber = 0;
    statistics.discTime.setTime(0, 0, 0);
    statistics.trackTime.setTime(0, 0, 0);
}

F2FramesToAudio::Statistics F2FramesToAudio::getStatistics(void)
{
    return statistics;
}

// Method to write status information to qCInfo
void F2FramesToAudio::reportStatus(void)
{
    qInfo() << "F2 Frames to audio converter:";
    qInfo() << "  Valid audio samples =" << statistics.validAudioSamples;
    qInfo() << "  Invalid audio samples =" << statistics.invalidAudioSamples;
    qInfo() << "  Sections processed =" << statistics.sectionsProcessed;
    qInfo() << "  Encoder running sections =" << statistics.encoderRunning;
    qInfo() << "  Encoder stopped sections =" << statistics.encoderStopped;
    qInfo() << "  Unknown QMode sections =" << statistics.unknownQMode;
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
    qint32 f2FrameNumber = 0;
    qint32 sectionsToProcess = f2FramesIn.size() / 98;
    if (sectionsIn.size() < sectionsToProcess) sectionsToProcess = sectionsIn.size();

    for (qint32 sectionNo = 0; sectionNo < sectionsToProcess; sectionNo++) {
        // Ensure we have a valid QMode
        bool outputSamples = false;
        qint32 currentQMode = sectionsIn[sectionNo].getQMode();
        if (currentQMode == -1) {
            qDebug() << "F2FramesToAudio::processAudio(): Current section is invalid";
            outputSamples = true; // Output the samples anyway (for now!)
            statistics.unknownQMode++;
            statistics.trackNumber = -1;
            statistics.discTime.setTime(0, 0, 0);
            statistics.trackTime.setTime(0, 0, 0);
        } else {
            if (currentQMode == 1) {
                // Is the encoder running?
                if (sectionsIn[sectionNo].getQMetadata().qMode1.trackNumber > 0) {
                    outputSamples = true;
                    statistics.encoderRunning++;
                } else statistics.encoderStopped++;

                // Set QMode1 statistics
                statistics.trackNumber = sectionsIn[sectionNo].getQMetadata().qMode1.trackNumber;
                statistics.discTime = sectionsIn[sectionNo].getQMetadata().qMode1.discTime;
                statistics.trackTime = sectionsIn[sectionNo].getQMetadata().qMode1.trackTime;
            }

            if (currentQMode == 4) {
                // Is the encoder running?
                if (sectionsIn[sectionNo].getQMetadata().qMode4.trackNumber > 0) {
                    outputSamples = true;
                    statistics.encoderRunning++;
                } else statistics.encoderStopped++;

                // Set QMode 4 statistics
                statistics.trackNumber = sectionsIn[sectionNo].getQMetadata().qMode4.trackNumber;
                statistics.discTime = sectionsIn[sectionNo].getQMetadata().qMode4.discTime;
                statistics.trackTime = sectionsIn[sectionNo].getQMetadata().qMode4.trackTime;
            }
        }

        // Output the samples to file (98 f2 frames x 6 samples per frame = 588)
        for (qint32 i = f2FrameNumber; i < f2FrameNumber + 98; i++) {
            if (outputSamples) {
                // Check F2 Frame data payload validity
                if (!f2FramesIn[i].getDataValid()) {
                    qDebug() << "F2FramesToAudio::processAudio(): F2 Frame data has errors - 6 samples might be garbage";
                    statistics.invalidAudioSamples += 6;
                } else {
                    statistics.validAudioSamples += 6; // 24 bytes per F2 (/2 = 16-bit and /2 = stereo)
                }

                // Encoder running, output samples
                outputFileHandle->write(f2FramesIn[i].getDataSymbols()); // 24 bytes per F2
            } else {
                // Encoder stopped, output F2 frame's worth in zeros
                QByteArray dummy;
                dummy.fill(0, 24);
                outputFileHandle->write(dummy);
            }
        }
        f2FrameNumber += 98;

        statistics.sectionsProcessed++;
    }

    // Remove processed F2Frames and samples from buffer
    f2FramesIn.remove(0, sectionsToProcess * 98);
    sectionsIn.remove(0, sectionsToProcess);
}
