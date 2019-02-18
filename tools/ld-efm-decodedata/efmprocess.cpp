/************************************************************************

    efmprocess.cpp

    ld-efm-decodedata - EFM data decoder for ld-decode
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-efm-decodedata is free software: you can redistribute it and/or
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

#include "efmprocess.h"

EfmProcess::EfmProcess()
{
    decodeSubcode.setVerboseDebug(false);
}

bool EfmProcess::process(QString inputFilename, QString outputFilename)
{
    (void) outputFilename;

    // Open the input F3 data file
    if (!openInputF3File(inputFilename)) {
        qCritical() << "Could not open F3 data input file!";
        return false;
    }

    // To do: make this read many frames at a time to speed up I/O
    bool endOfFile = false;
    while (!endOfFile) {
        QByteArray f3Frame = readF3Frames(1);

        // Decode the subcode, returns a true if the frame is SYNC1
        // also returns the current reported qMode or -1 if unknown
        decodeSubcode.process(f3Frame);

        // Pass the frame and decoded subcode information to the audio processor
        decodeAudio.process(f3Frame);

        // Pass the frame and decoded subcode information to the data processor
        //decodeData.feed(f3Frame, sync1, qMode);

        if (f3Frame.isEmpty()) endOfFile = true;
    }

    // Close the input F3 data file
    closeInputF3File();
    return true;
}

// Method to open the input F3 data file for reading
bool EfmProcess::openInputF3File(QString filename)
{
    // Open the input file
    inputFile = new QFile(filename);
    if (!inputFile->open(QIODevice::ReadOnly)) {
        // Failed to open input file
        qDebug() << "EfmProcess::openInputSampleFile(): Could not open " << filename << "as sampled EFM input file";
        return false;
    }

    return true;
}

// Method to close the input F3 data file
void EfmProcess::closeInputF3File(void)
{
    // Close the input file
    inputFile->close();
}

// Method to read F3 frames from the input file
QByteArray EfmProcess::readF3Frames(qint32 numberOfFrames)
{
    QByteArray f3FrameData;

    qint32 bytesToRead = numberOfFrames * 34; // Each F3 frame is 34 bytes (1 sync indicator and 33 real bytes)
    f3FrameData.resize(bytesToRead);

    qint64 bytesRead = inputFile->read(f3FrameData.data(), bytesToRead);

    if (bytesRead != bytesToRead) {
        qDebug() << "EfmProcess::readF3Frames(): Ran out of input data";
        f3FrameData.clear();
    }

    return f3FrameData;
}

// Method to open the output data file for writing
bool EfmProcess::openOutputDataFile(QString filename)
{
    // Open the output file
    outputFile = new QFile(filename);
    if (!outputFile->open(QIODevice::WriteOnly)) {
        // Failed to open output file
        qDebug() << "EfmProcess::openOutputDataFile(): Could not open " << filename << "as output data file";
        return false;
    }

    return true;
}

// Method to close the output data file
void EfmProcess::closeOutputDataFile(void)
{
    // Close the output file
    outputFile->close();
}



