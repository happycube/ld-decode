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
    statistics.audioSamples = 0;
}

F2FramesToAudio::Statistics F2FramesToAudio::getStatistics(void)
{
    return statistics;
}

// Method to write status information to qCInfo
void F2FramesToAudio::reportStatus(void)
{
    qInfo() << "F2 Frames to audio converter:";
    qInfo() << "  Total number of stereo audio samples =" << statistics.audioSamples;
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
void F2FramesToAudio::convert(QVector<F2Frame> f2Frames)
{
    for (qint32 i = 0; i < f2Frames.size(); i++) {
        outputFileHandle->write(f2Frames[i].getDataSymbols());
        statistics.audioSamples++;
    }
}
