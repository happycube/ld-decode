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

F2FramesToAudio::F2FramesToAudio()
{
    debugOn = false;
    reset();
}

// Public methods -----------------------------------------------------------------------------------------------------

// Process F2 Frames into PCM audio data
QByteArray F2FramesToAudio::process(QVector<F2Frame> f2FramesIn)
{
    QByteArray audioBufferOut;

    // Make sure there is something to process
    if (f2FramesIn.isEmpty()) return audioBufferOut;

    // Ensure that the upstream is providing only complete sections of
    // 98 frames... otherwise we have an upstream bug.
    if (f2FramesIn.size() % 98 != 0) {
        qFatal("F2FramesToAudio::process(): Upstream has provided incomplete sections of 98 F2 frames - This is a bug!");
        // Exection stops...
        // return audioBufferOut;
    }

    // Process the input F2 Frames
    while (!f2FramesIn.isEmpty()) {
        // Process 98 F2 frames per pass (1 section)
        QVector<F2Frame> f2FrameBuffer;
        for (qint32 i = 0; i < 98; i++) {
            f2FrameBuffer.append(f2FramesIn[i]);
        }

        // Remove the consumed F2 frames from the input buffer
        f2FramesIn.remove(0, 98);

        // Check for missing sections (and pad as required)
        if (!initialDiscTimeSet) {
            // First pass, set the initial disc time
            lastDiscTime = f2FrameBuffer[0].getDiscTime();
            statistics.sampleStart = lastDiscTime;
            statistics.sampleCurrent = lastDiscTime;
            initialDiscTimeSet = true;
            if (debugOn) qDebug() << "F2FramesToAudio::startProcessing(): Initial disc time is" << lastDiscTime.getTimeAsQString();
        } else {
            TrackTime currentDiscTime = f2FrameBuffer[0].getDiscTime();

            // Check that this section is one frame difference from the previous
            qint32 sectionFrameGap = currentDiscTime.getDifference(lastDiscTime.getTime());

            if (sectionFrameGap > 1) {
                // Pad the output sample file according to the gap
                QByteArray sectionPadding;
                sectionPadding.fill(0, 98 * 24); // 24 bytes = 6 samples * 98 F2Frames per section
                for (qint32 p = 0; p < sectionFrameGap - 1; p++) {
                    audioBufferOut.append(sectionPadding);
                    statistics.missingSectionSamples += 98 * 6;
                    statistics.totalSamples += 98 * 6;
                }
                if (debugOn) qDebug() << "F2FramesToAudio::startProcessing(): Padded output sample by" << sectionFrameGap - 1 << "sections";
            }

            // Update the last disc time
            lastDiscTime = currentDiscTime;
            statistics.sampleCurrent = currentDiscTime;
        }

        // Now output the F2 Frames as samples
        for (qint32 i = 0; i < 98; i++) {
            if (f2FrameBuffer[i].getIsEncoderRunning() && f2FrameBuffer[i].getDataValid()) {
                // Encoder is running and data is valid, output samples
                audioBufferOut.append(f2FrameBuffer[i].getDataSymbols());
                statistics.validSamples += 6;
                statistics.totalSamples += 6;
            } else {
                QByteArray framePadding;
                framePadding.fill(0, 24); // 24 bytes = 6 samples
                audioBufferOut.append(framePadding);
                if (!f2FrameBuffer[i].getDataValid()) statistics.corruptSamples += 6;
                else statistics.encoderOffSamples += 6;
                statistics.totalSamples += 6;
            }
        }
    }

    return audioBufferOut;
}

// Get method - retrieve statistics
F2FramesToAudio::Statistics F2FramesToAudio::getStatistics()
{
    return statistics;
}

// Method to report decoding statistics to qInfo
void F2FramesToAudio::reportStatistics()
{
    qInfo() << "";
    qInfo() << "F2 Frames to audio samples:";
    qInfo() << "            Valid samples:" << statistics.validSamples;
    qInfo() << "          Corrupt samples:" << statistics.corruptSamples;
    qInfo() << "  Missing section samples:" << statistics.missingSectionSamples << "(" << statistics.missingSectionSamples / 6 << "F3 Frames )";
    qInfo() << "      Encoder off samples:" << statistics.encoderOffSamples;
    qInfo() << "            TOTAL samples:" << statistics.totalSamples;
    qInfo() << "";
    qInfo().noquote() << "        Sample start time:" << statistics.sampleStart.getTimeAsQString();
    qInfo().noquote() << "          Sample end time:" << statistics.sampleCurrent.getTimeAsQString();

    qint32 sampleFrameLength = statistics.sampleCurrent.getDifference(statistics.sampleStart.getTime());
    TrackTime sampleLength;
    sampleLength.setTime(0, 0, 0);
    sampleLength.addFrames(sampleFrameLength);
    qInfo().noquote() << "          Sample duration:" << sampleLength.getTimeAsQString();
    qInfo().noquote() << "      Sample frame length:" << sampleFrameLength << "(" << sampleFrameLength / 75.0 << "seconds )";
}

// Method to reset the class
void F2FramesToAudio::reset()
{
    // Initialise variables to track the disc time
    initialDiscTimeSet = false;
    lastDiscTime.setTime(0, 0, 0);

    clearStatistics();
}

// Private methods ----------------------------------------------------------------------------------------------------

// Method to clear the statistics counters
void F2FramesToAudio::clearStatistics()
{
    statistics.validSamples = 0;
    statistics.missingSectionSamples = 0;
    statistics.encoderOffSamples = 0;
    statistics.totalSamples = 0;
    statistics.corruptSamples = 0;

    statistics.sampleStart.setTime(0, 0, 0);
    statistics.sampleCurrent.setTime(0, 0, 0);
}
