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

    // Create a data stream for the output file
    outputStream = new QDataStream(outputFileHandle);
    outputStream->setByteOrder(QDataStream::LittleEndian);

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
        QByteArray audioData = f2Frames[i].getDataSymbols();

        // This test should never fail... but, hey, software...
        if ((audioData.size() % 4) != 0) {
            qCritical() << "F2FramesToAudio::convert(): Audio data has an invalid length and will not save correctly.";
            exit(1);
        }

        if (!audioData.isEmpty()) {
            // Save the audio data as little-endian stereo LLRRLLRR etc
            for (qint32 byteC = 0; byteC < audioData.size(); byteC += 4) {
                // 1 0 3 2
                *outputStream << static_cast<uchar>(audioData[byteC + 1])
                 << static_cast<uchar>(audioData[byteC + 0])
                 << static_cast<uchar>(audioData[byteC + 3])
                 << static_cast<uchar>(audioData[byteC + 2]);
            }
            audioSamples++;
        }
    }
}
