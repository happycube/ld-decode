/************************************************************************

    decodeaudio.cpp

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

#include "decodeaudio.h"

DecodeAudio::DecodeAudio()
{

}

DecodeAudio::~DecodeAudio()
{

}

// Method to write status information to qInfo
void DecodeAudio::reportStatus(void)
{
    // Show C1 CIRC status
    c1Circ.reportStatus();

    // Show C2 CIRC status
    c2Circ.reportStatus();

    // Show C2 Deinterleave status
    c2Deinterleave.reportStatus();
}

// Method to open the audio output file
bool DecodeAudio::openOutputFile(QString filename)
{
    // Open output file for writing
    outputFileHandle = new QFile(filename);
    if (!outputFileHandle->open(QIODevice::WriteOnly)) {
        // Failed to open source sample file
        qDebug() << "Could not open " << outputFileHandle << "as audio output file";
        return false;
    }
    qDebug() << "DecodeAudio::openOutputFile(): Opened" << filename << "as audio output file";

    // Create a data stream for the output file
    outputStream = new QDataStream(outputFileHandle);
    outputStream->setByteOrder(QDataStream::LittleEndian);

    // Exit with success
    return true;
}

// Method to close the audio output file
void DecodeAudio::closeOutputFile(void)
{
    // Is an output file open?
    if (outputFileHandle != nullptr) {
        outputFileHandle->close();
    }

    // Clear the file handle pointer
    delete outputFileHandle;
    outputFileHandle = nullptr;
}

// Flush the C1 and C2 audio decode buffers
void DecodeAudio::flush(void)
{
    // Flush all the decode buffers
    c1Circ.flush();
    c2Circ.flush();
    c2Deinterleave.flush();
}

// Process a subcode block
void DecodeAudio::process(SubcodeBlock subcodeBlock)
{
    // Process the 98 frames of the subcode block
    for (qint32 i = 0; i < 98; i++) {
        // Process C1 CIRC
        c1Circ.pushF3Frame(subcodeBlock.getFrame(i));

        // Get C1 results (if available)
        QByteArray c1DataSymbols = c1Circ.getDataSymbols();
        QByteArray c1ErrorSymbols = c1Circ.getErrorSymbols();

        // If we have C1 results, process C2
        if (!c1DataSymbols.isEmpty()) {
            // Process C2 CIRC
            c2Circ.pushC1(c1DataSymbols, c1ErrorSymbols);

            // Get C2 results (if available)
            QByteArray c2DataSymbols = c2Circ.getDataSymbols();
            QByteArray c2ErrorSymbols = c2Circ.getErrorSymbols();

            // Deinterleave the C2
            c2Deinterleave.pushC2(c2DataSymbols, c2ErrorSymbols);

            QByteArray c2DeinterleavedData = c2Deinterleave.getDataSymbols();
            QByteArray c2DeinterleavedErrors = c2Deinterleave.getErrorSymbols();

            // If we have deinterleaved C2s, process them
            if (!c2DeinterleavedData.isEmpty()) {
                writeAudioData(c2DeinterleavedData);
            }
        }
    }
}

// Method to write any available audio data to file
void DecodeAudio::writeAudioData(QByteArray audioData)
{
    // This test should never fail... but, hey, software...
    if ((audioData.size() % 4) != 0) {
        qCritical() << "DecodeAudio::writeAudioData(): Audio data has an invalid length and will not save correctly.";
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
    }
}
