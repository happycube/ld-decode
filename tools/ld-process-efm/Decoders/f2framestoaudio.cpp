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
    abort = false;
}

// Public methods -----------------------------------------------------------------------------------------------------

void F2FramesToAudio::startProcessing(QFile *inputFileHandle, QFile *outputFileHandle)
{
    abort = false;

    // Clear the statistic counters
    clearStatistics();

    // Define an input data stream
    QDataStream inputDataStream(inputFileHandle);

    // Define an output data stream
    QDataStream outputDataStream(outputFileHandle);

    qDebug() << "F2FramesToAudio::startProcessing(): Initial input file size of" << inputFileHandle->bytesAvailable() << "bytes";

    // Initialise variables to track the disc time
    bool initialDiscTimeSet = false;
    TrackTime lastDiscTime;
    lastDiscTime.setTime(0, 0, 0);

    // Process the input F2 Frames
    while (inputFileHandle->bytesAvailable() != 0 && !abort) {
        // Process 98 F2 frames per pass (1 section)
        QVector<F2Frame> f2FrameBuffer;
        for (qint32 i = 0; i < 98; i++) {
            F2Frame f2Frame;
            inputDataStream >> f2Frame;
            f2FrameBuffer.append(f2Frame);
        }

        // Check for missing sections (and pad as required)
        if (!initialDiscTimeSet) {
            // First pass, set the initial disc time
            lastDiscTime = f2FrameBuffer[0].getDiscTime();
            statistics.sampleStart = lastDiscTime;
            statistics.sampleCurrent = lastDiscTime;
            initialDiscTimeSet = true;
            qDebug() << "F2FramesToAudio::startProcessing(): Initial disc time is" << lastDiscTime.getTimeAsQString();
        } else {
            TrackTime currentDiscTime = f2FrameBuffer[0].getDiscTime();

            // Check that this section is one frame difference from the previous
            qint32 sectionFrameGap = currentDiscTime.getDifference(lastDiscTime.getTime());

            if (sectionFrameGap > 1) {
                // Pad the output sample file according to the gap
                QByteArray sectionPadding;
                sectionPadding.fill(0, 98 * 24); // 24 bytes = 6 samples * 98 F2Frames per section
                for (qint32 p = 0; p < sectionFrameGap - 1; p++) {
                    //outputDataStream << sectionPadding;
                    outputFileHandle->write(sectionPadding);
                    statistics.missingSamples += 98 * 6;
                    statistics.totalSamples += 98 * 6;
                }
                qDebug() << "F2FramesToAudio::startProcessing(): Padded output sample by" << sectionFrameGap - 1 << "sections";
            }

            // Update the last disc time
            lastDiscTime = currentDiscTime;
            statistics.sampleCurrent = currentDiscTime;
        }

        // Now output the F2 Frames as samples
        for (qint32 i = 0; i < 98; i++) {
            if (f2FrameBuffer[i].getIsEncoderRunning() && f2FrameBuffer[i].getDataValid()) {
                // Encoder is running and data is valid, output samples
                //outputDataStream << f2FrameBuffer[i].getDataSymbols();
                outputFileHandle->write(f2FrameBuffer[i].getDataSymbols());
                statistics.validSamples += 6;
                statistics.totalSamples += 6;
            } else {
                QByteArray framePadding;
                framePadding.fill(0, 24); // 24 bytes = 6 samples
                //outputDataStream << framePadding;
                outputFileHandle->write(framePadding);
                if (!f2FrameBuffer[i].getDataValid()) statistics.corruptSamples += 6;
                else statistics.missingSamples += 6;
                statistics.totalSamples += 6;
            }
        }
    }

    qDebug() << "F2FramesToAudio::startProcessing(): No more data to processes";
}

void F2FramesToAudio::stopProcessing(void)
{
    abort = true;
}

F2FramesToAudio::Statistics F2FramesToAudio::getStatistics(void)
{
    return statistics;
}

void F2FramesToAudio::reportStatistics(void)
{
    qInfo() << "";
    qInfo() << "F2 Frames to audio samples:";
    qInfo() << "        Valid samples:" << statistics.validSamples;
    qInfo() << "      Corrupt samples:" << statistics.corruptSamples;
    qInfo() << "      Missing samples:" << statistics.missingSamples << "(" << statistics.missingSamples / 6 << "F3 Frames )";
    qInfo() << "        TOTAL samples:" << statistics.totalSamples;
    qInfo() << "";
    qInfo().noquote() << "    Sample start time:" << statistics.sampleStart.getTimeAsQString();
    qInfo().noquote() << "      Sample end time:" << statistics.sampleCurrent.getTimeAsQString();

    qint32 sampleFrameLength = statistics.sampleCurrent.getDifference(statistics.sampleStart.getTime());
    TrackTime sampleLength;
    sampleLength.setTime(0, 0, 0);
    sampleLength.addFrames(sampleFrameLength);
    qInfo().noquote() << "      Sample duration:" << sampleLength.getTimeAsQString();
    qInfo().noquote() << "  Sample frame length:" << sampleFrameLength << "(" << sampleFrameLength / 75.0 << "seconds )";
}

// Private methods ----------------------------------------------------------------------------------------------------

void F2FramesToAudio::clearStatistics(void)
{
    statistics.validSamples = 0;
    statistics.missingSamples = 0;
    statistics.totalSamples = 0;
    statistics.corruptSamples = 0;
}
