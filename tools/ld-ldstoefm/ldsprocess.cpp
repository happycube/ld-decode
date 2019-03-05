/************************************************************************

    ldsprocess.cpp

    ld-ldstoefm - LDS sample to EFM data processing
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    ld-ldstoefm is free software: you can redistribute it and/or
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

#include "ldsprocess.h"

LdsProcess::LdsProcess()
{

}

// Note: This function reads qint16 sample data from the input LDS file and
// outputs a byte-stream of values between 3 and 11 representing the EFM data
// as read from the LaserDisc's surface.
//
// The basic process is:
//  1. Unpack 10-bit to 16-bit
//  2. Filter EFM signal
//  3. Pulse shape EFM signal
//  4. Zero cross the signal to get ZC sample deltas
//  5. Use a PLL to extract the data from the ZC deltas
//  6. Save the data to the output EFM data file

bool LdsProcess::process(QString inputFilename, QString outputFilename, bool outputSample, bool useFloatingPoint, bool noIsiFilter)
{
    // Open the input file
    if (!openInputFile(inputFilename)) {
        qCritical("Could not open input file!");
        return false;
    }
    qint64 inputFileSize = (inputFileHandle->size() / 10) * 16;
    qint64 inputProcessed = 0;

    // Warn if --sample has been selected
    if (outputSample) qInfo() << "Writing output as a 16-bit signed sample of the filter output";

    // Warn is --float has been selected
    if (useFloatingPoint) qInfo() << "Using floating-point filter processing";
    else qInfo() << "Using fixed-point filter processing";

    // Open the output file
    if (!openOutputFile(outputFilename)) {
        qCritical("Could not open output file!");
        return false;
    }

    QByteArray ldsData;
    QByteArray efmData;
    do {
        // Get qint16 sample data from the 10-bit packed LDS file
        ldsData = readAndUnpackLdsFile();

        if (ldsData.size() > 0) {
            inputProcessed += ldsData.size();

            // Filter out everything from the LDS to leave just the EFM signal
            qDebug() << "LdsProcess::process(): Applying EFM extraction filter...";
            if (useFloatingPoint) efmFilter.floatEfmProcess(ldsData);
            else efmFilter.fixedEfmProcess(ldsData);

            if (!noIsiFilter) {
                // Pulse shape the EFM data
                qDebug() << "LdsProcess::process(): Applying ISI correction filter...";
                if (useFloatingPoint) isiFilter.floatIsiProcess(ldsData);
                else isiFilter.fixedIsiProcess(ldsData);
            }

            // Output EFM data or sample (for testing)?
            if (!outputSample) {
                // Use zero-cross detection and a PLL to get the T values from the EFM signal
                qDebug() << "LdsProcess::process(): Performing EFM clock and data recovery...";
                efmData = pll.process(ldsData);

                // Save the resulting T values as a byte stream to the output file
                if (!outputFileHandle->write(reinterpret_cast<char *>(efmData.data()), efmData.size())) {
                    // File write failed
                    qCritical("Could not write to output file!");
                    closeInputFile();
                    closeOutputFile();
                    return false;
                }
            } else {
                // Save the filter output as a sample file (for testing filters)
                if (!outputFileHandle->write(reinterpret_cast<char *>(ldsData.data()), ldsData.size())) {
                    // File write failed
                    qCritical("Could not write to output file!");
                    closeInputFile();
                    closeOutputFile();
                    return false;
                }
            }

            // Show a progress update to the user
            //qInfo() << "Processed" << inputProcessed / 1024 << "Kbytes of" << inputFileSize / 1024 << "KBytes";
            qreal percentage = (100.0 / static_cast<qreal>(inputFileSize)) * static_cast<qreal>(inputProcessed);
            qInfo().nospace() << "Processed " << static_cast<qint32>(percentage) << "%";
        }
    } while (ldsData.size() > 0);

    // Close the input file
    closeInputFile();

    // Close the output file
    closeOutputFile();

    qInfo() << "Processing complete";

    return true;
}

// Method to open the input file for reading
bool LdsProcess::openInputFile(QString inputFileName)
{
    // Open input file for reading
    inputFileHandle = new QFile(inputFileName);
    if (!inputFileHandle->open(QIODevice::ReadOnly)) {
        // Failed to open source sample file
        qDebug() << "Could not open " << inputFileName << "as input file";
        return false;
    }
    qDebug() << "LdsProcess::openInputFile(): 10-bit input file is" << inputFileName << "and is" <<
                inputFileHandle->size() << "bytes in length";

    // Exit with success
    return true;
}

// Method to close the input file
void LdsProcess::closeInputFile(void)
{
    // Is an input file open?
    if (inputFileHandle != nullptr) {
        inputFileHandle->close();
    }

    // Clear the file handle pointer
    delete inputFileHandle;
    inputFileHandle = nullptr;
}

// Method to open the output file for writing
bool LdsProcess::openOutputFile(QString outputFileName)
{
    // Open the output file for writing
    outputFileHandle = new QFile(outputFileName);
    if (!outputFileHandle->open(QIODevice::WriteOnly)) {
        // Failed to open output file
        qDebug() << "Could not open " << outputFileName << "as output file";
        return false;
    }
    qDebug() << "LdsProcess::openOutputFile(): Output file is" << outputFileName;

    // Exit with success
    return true;
}

// Method to close the output file
void LdsProcess::closeOutputFile(void)
{
    // Is an output file open?
    if (outputFileHandle != nullptr) {
        outputFileHandle->close();
    }

    // Clear the file handle pointer
    delete outputFileHandle;
    outputFileHandle = nullptr;
}

// Method to unpack 10-bit data into 16-bit data
QByteArray LdsProcess::readAndUnpackLdsFile(void)
{
    QByteArray inputBuffer;
    QByteArray outputBuffer;

    // Input buffer must be divisible by 5 bytes due to 10-bit data format
    qint32 bufferSizeInBytes = (64 * 1024 * 1024); // 64 MiB
    inputBuffer.resize(bufferSizeInBytes);

    // Every 5 input bytes is 4 output words (8 bytes)
    outputBuffer.resize((bufferSizeInBytes / 5) * 8);

    // Fill the input buffer with data
    qint64 receivedBytes = 0;
    qint32 totalReceivedBytes = 0;
    do {
        receivedBytes = inputFileHandle->read(reinterpret_cast<char *>(inputBuffer.data() +totalReceivedBytes),
                                              bufferSizeInBytes - totalReceivedBytes);
        if (receivedBytes > 0) totalReceivedBytes += receivedBytes;
    } while (receivedBytes > 0 && totalReceivedBytes < bufferSizeInBytes);

    // Check for end of file
    if (receivedBytes == 0) {
        outputBuffer.clear();
        return outputBuffer;
    }

    if (totalReceivedBytes != 0) {
        qDebug() << "LdsProcess::readAndUnpackLdsFile(): Unpacking 10-bit data to 16-bit signed";

        // If we didn't fill the input buffer, resize it
        if (bufferSizeInBytes != totalReceivedBytes) {
            inputBuffer.resize(totalReceivedBytes);
            outputBuffer.resize((totalReceivedBytes / 5) * 8);
        }
        qDebug() << "LdsProcess::readAndUnpackLdsFile(): Got" << totalReceivedBytes << "bytes from input file";

        char byte0, byte1, byte2, byte3, byte4;
        qint32 word0, word1, word2, word3;
        qint32 outputBufferPointer = 0;

        qint16 *output = reinterpret_cast<qint16 *>(outputBuffer.data());

        for (qint32 bytePointer = 0; bytePointer < totalReceivedBytes; bytePointer += 5) {
            // Unpack the 5 bytes into 4x 10-bit values

            // Unpacked:                 Packed:
            // 0: xxxx xx00 0000 0000    0: 0000 0000 0011 1111
            // 1: xxxx xx11 1111 1111    2: 1111 2222 2222 2233
            // 2: xxxx xx22 2222 2222    4: 3333 3333
            // 3: xxxx xx33 3333 3333

            byte0 = inputBuffer[bytePointer + 0];
            byte1 = inputBuffer[bytePointer + 1];
            byte2 = inputBuffer[bytePointer + 2];
            byte3 = inputBuffer[bytePointer + 3];
            byte4 = inputBuffer[bytePointer + 4];

            // Use multiplication instead of left-shift to avoid implicit conversion issues
            word0  = ((byte0 & 0xFF) *   4) + ((byte1 & 0xC0) >> 6);
            word1  = ((byte1 & 0x3F) *  16) + ((byte2 & 0xF0) >> 4);
            word2  = ((byte2 & 0x0F) *  64) + ((byte3 & 0xFC) >> 2);
            word3  = ((byte3 & 0x03) * 256) + ((byte4 & 0xFF)     );

            output[outputBufferPointer + 0] = static_cast<qint16>((word0 - 512) * 64);
            output[outputBufferPointer + 1] = static_cast<qint16>((word1 - 512) * 64);
            output[outputBufferPointer + 2] = static_cast<qint16>((word2 - 512) * 64);
            output[outputBufferPointer + 3] = static_cast<qint16>((word3 - 512) * 64);

            // Increment the sample buffer pointer
            outputBufferPointer += 4;
        }
    }

    return outputBuffer;
}
