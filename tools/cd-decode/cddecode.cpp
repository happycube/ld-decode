/************************************************************************

    cddecode.cpp

    cd-decode - Compact Disc RF to EFM converter
    Copyright (C) 2019 Simon Inns

    This file is part of ld-decode-tools.

    cd-decode is free software: you can redistribute it and/or
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

#include "cddecode.h"

CdDecode::CdDecode(QObject *parent) : QObject(parent)
{

}

bool CdDecode::process(QString inputFilename)
{
    // Open the input file
    if (!openInputFile(inputFilename)) {
        qCritical("Could not open input file!");
        return false;
    }

    // Open the output file
    if (!openOutputFile(inputFilename + ".efm")) {
        qCritical("Could not open output file!");
        return false;
    }

    // Store the input file data size for progress reporting
    qint64 inputFileSize = inputFileHandle->size();
    qint64 inputProcessed = 0;

    QByteArray inputData;
    QByteArray outputData;
    bool finished = false;

    do {
        qint32 bufferSizeInBytes = (1024 * 1024) * 128; // 128 MiB
        inputData.resize(bufferSizeInBytes);

        // Fill the input buffer with data
        qint64 receivedBytes = 0;
        qint32 totalReceivedBytes = 0;
        do {
            // In practice as long as the file descriptor is blocking this will read everything in one chunk...
            receivedBytes = inputFileHandle->read(reinterpret_cast<char *>(inputData.data() +totalReceivedBytes),
                                                bufferSizeInBytes - totalReceivedBytes);
            if (receivedBytes > 0) totalReceivedBytes += receivedBytes;
        } while (receivedBytes > 0 && totalReceivedBytes < bufferSizeInBytes);

        // Resize the input buffer to the received data size
        inputData.resize(totalReceivedBytes);

        if (inputData.size() > 0) {
            inputProcessed += inputData.size();

            // Pulse shape the EFM data
            qDebug() << "CdDecode::process(): Applying ISI pulse-shaping filter...";
            isiFilter.floatIsiProcess(inputData);

            // Use zero-cross detection and a PLL to get the T values from the EFM signal
            qDebug() << "CdDecode::process(): Performing EFM clock and data recovery...";
            outputData = pll.process(inputData);

            // Save the resulting T values as a byte stream to the output file
            if (outputData.size() > 0) {
                qDebug() << "CdDecode::process(): Output buffer is" << outputData.size() << "bytes";
                if (!outputFileHandle->write(reinterpret_cast<char *>(outputData.data()), outputData.size())) {
                    // File write failed
                    qCritical("Could not write to output file!");
                    closeInputFile();
                    closeOutputFile();
                    return false;
                }
            }

            // Show a progress update to the user
            qInfo() << "Processed" << inputProcessed / 1024 << "Kbytes of" << inputFileSize / 1024 << "KBytes";
            qreal percentage = (100.0 / static_cast<qreal>(inputFileSize)) * static_cast<qreal>(inputProcessed);
            qInfo().nospace() << "Processed " << static_cast<qint32>(percentage) << "%";
        }
    } while (inputData.size() > 0 && !finished);

    // Close the input file
    closeInputFile();

    // Close the output file
    closeOutputFile();

    return true;
}

// Private methods ----------------------------------------------------------------------------------------------------

// Method to open the input file for reading
bool CdDecode::openInputFile(QString inputFilename)
{
    // Open input file for reading
    inputFileHandle = new QFile(inputFilename);
    if (!inputFileHandle->open(QIODevice::ReadOnly)) {
        // Failed to open source sample file
        qDebug() << "Could not open " << inputFilename << "as input file";
        return false;
    }
    qDebug() << "CdDecode::openInputFile(): Input file is" << inputFilename << "and is" <<
                inputFileHandle->size() / 1024 << "Kbytes in length";

    // Exit with success
    return true;
}

// Method to close the input file
void CdDecode::closeInputFile()
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
bool CdDecode::openOutputFile(QString outputFilename)
{
    // Open the output file for writing
    outputFileHandle = new QFile(outputFilename);
    if (!outputFileHandle->open(QIODevice::WriteOnly)) {
        // Failed to open output file
        qDebug() << "CdDecode::openOutputFile(): Could not open " << outputFilename << "as output file";
        return false;
    }
    qDebug() << "CdDecode::openOutputFile(): Output file is" << outputFilename;

    // Exit with success
    return true;
}

// Method to close the output file
void CdDecode::closeOutputFile()
{
    // Is an output file open?
    if (outputFileHandle != nullptr) {
        outputFileHandle->close();
    }

    // Clear the file handle pointer
    delete outputFileHandle;
    outputFileHandle = nullptr;
}
