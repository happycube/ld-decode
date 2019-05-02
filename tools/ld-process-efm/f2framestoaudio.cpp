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
    audioSamples = 0;
}

// Method to write status information to qInfo
void F2FramesToAudio::reportStatus(void)
{
    qInfo() << "F2 Frames to audio converter:";
    qInfo() << "  Total number of stereo audio samples =" << audioSamples;
}

// Method to open the audio output file
bool F2FramesToAudio::openOutputFile(QString filename)
{
    // Open output file for writing
    outputFileHandle = new QFile(filename);
    if (!outputFileHandle->open(QIODevice::WriteOnly)) {
        // Failed to open source sample file
        qDebug() << "Could not open " << outputFileHandle << "as audio output file";
        return false;
    }
    qDebug() << "F2FramesToAudio::openOutputFile(): Opened" << filename << "as audio output file";

    // Exit with success
    return true;
}

// Method to close the audio output file
void F2FramesToAudio::closeOutputFile(void)
{
    // Is an output file open?
    if (outputFileHandle != nullptr) {
        outputFileHandle->close();
    }

    // Clear the file handle pointer
    delete outputFileHandle;
    outputFileHandle = nullptr;
}

// Convert F2 frames into audio sample data
void F2FramesToAudio::convert(QVector<F2Frame> f2Frames)
{
    for (qint32 i = 0; i < f2Frames.size(); i++) {
        outputFileHandle->write(f2Frames[i].getDataSymbols());
        audioSamples++;
    }
}
