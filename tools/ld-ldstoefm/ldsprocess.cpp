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

#include <cstdio>

LdsProcess::LdsProcess()
{

}

// Note: This function reads qint16 sample data from the input LDS file and
// outputs a byte-stream of values between 3 and 11 representing the EFM data
// as read from the LaserDisc's surface.
//
// The basic process is:
//  1. Zero cross the signal to get ZC sample deltas
//  2. Use a PLL to extract the data from the ZC deltas
//  3. Save the data to the output EFM data file

bool LdsProcess::process(QString outputFilename)
{
    // Open the input file
    if (!stdinFileHandle.open(stdin, QIODevice::ReadOnly)) {
        qCritical("Could not open input file!");
        return false;
    }

    // Open the output file
    if (!openOutputFile(outputFilename)) {
        qCritical("Could not open output file!");
        return false;
    }

    QByteArray ldsData;
    QByteArray efmData;
    bool finished = false;
    do {
        qint32 bufferSizeInBytes = (1024 * 1024); // 1 MiB
        ldsData.resize(bufferSizeInBytes);

        // Fill the input buffer with data
        qint64 receivedBytes = 0;
        qint32 totalReceivedBytes = 0;
        do {
            // In practice as long as the file descriptor is blocking this will read everything in one chunk...
            receivedBytes = stdinFileHandle.read(reinterpret_cast<char *>(ldsData.data() + totalReceivedBytes),
                                                 bufferSizeInBytes - totalReceivedBytes);
            if (receivedBytes > 0) totalReceivedBytes += receivedBytes;
        } while (receivedBytes > 0 && totalReceivedBytes < bufferSizeInBytes);

        ldsData.resize(totalReceivedBytes);

        if (ldsData.size() > 0) {
            // Use zero-cross detection and a PLL to get the T values from the EFM signal
            qDebug() << "LdsProcess::process(): Performing EFM clock and data recovery...";
            efmData = pll.process(ldsData);

            // Save the resulting T values as a byte stream to the output file
            if (!outputFileHandle->write(reinterpret_cast<char *>(efmData.data()), efmData.size())) {
                // File write failed
                qCritical("Could not write to output file!");
                closeOutputFile();
                return false;
            }
		}
    } while (ldsData.size() > 0 && !finished);

    // Close the output file
    closeOutputFile();

    qInfo() << "Processing complete";

    return true;
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
