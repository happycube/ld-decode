/************************************************************************

    efmprocess.cpp

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

#include "efmprocess.h"

EfmProcess::EfmProcess()
{
    // Subcode block Q mode counters
    qMode0Count = 0;
    qMode1Count = 0;
    qMode2Count = 0;
    qMode3Count = 0;
    qMode4Count = 0;
    qModeICount = 0;
}

bool EfmProcess::process(QString inputFilename, QString outputFilename, bool verboseDebug)
{
    // Open the input file
    if (!openInputFile(inputFilename)) {
        qCritical("Could not open input file!");
        return false;
    }

    qint64 inputFileSize = inputFileHandle->size();
    qint64 inputBytesProcessed = 0;
    qint32 lastPercent = 0;

    // Open the audio decode output file
    decodeAudio.openOutputFile(outputFilename);

    // Open the data decode output file
    // To-do: data support

    // Turn on verbose debug if required
    if (verboseDebug) efmToF3Frames.setVerboseDebug(true);

    QByteArray efmBuffer;
    qint32 lastSeenQMode = -1;
    while ((efmBuffer = readEfmData()).size() != 0) {
        inputBytesProcessed += efmBuffer.size();

        // Convert the EFM buffer data into F3 frames
        QVector<F3Frame> f3Frames = efmToF3Frames.convert(efmBuffer);

        // Did we get any valid F3 Frames?
        if (f3Frames.size() != 0) {
            // Convert the F3 frames into subcode blocks
            QVector<SubcodeBlock> subcodeBlocks = f3FramesToSubcodeBlocks.convert(f3Frames);

            for (qint32 i = 0; i < subcodeBlocks.size(); i++) {
                // If the Q mode is invalid (failed CRC check) - then we need to decide
                // how to handle the subcode block.  The safest thing to do is to use
                // the last valid Q mode seen (provided this is not the first block after
                // sync)
                qint32 qMode = subcodeBlocks[i].getQMode();
                if (qMode == -1) {
                    qModeICount++;
                    if (subcodeBlocks[i].getFirstAfterSync()) {
                        qMode = -1;
                    } else {
                        qMode = lastSeenQMode;
                    }
                } else lastSeenQMode = qMode;

                // Depending on the subcode Q Mode, process the subcode
                if (qMode == 0) {
                    // Data
                    qMode0Count++;
                    qDebug() << "EfmProcess::process(): Subcode block Q mode ia 0 - unsupported!";
                } else if (qMode == 2) {
                    // Unique ID for disc
                    qMode1Count++;
                    qDebug() << "EfmProcess::process(): Subcode block Q mode ia 2 - unsupported!";
                } else if (qMode == 3) {
                    // Unique ID for track
                    qMode3Count++;
                    qDebug() << "EfmProcess::process(): Subcode block Q mode ia 3 - unsupported!";
                } else if (qMode == 1 || qMode == 4) {
                    // 1 = CD Audio, 2 = non-CD Audio (LaserDisc)
                    if (qMode == 1) qMode1Count++; else qMode4Count++;

                    //qDebug() << "Track time:" << subcodeBlocks[i].getQMetadata().qMode4.trackTime.getTimeAsQString();

                    // If this is the first audio block after a sync, clear the
                    // audio decode C1 and C2 buffers to prevent corruption
                    if (subcodeBlocks[i].getFirstAfterSync()) {
                        // Flush the audio decode buffers
                        decodeAudio.flush();
                    }

                    // Decode the audio
                    decodeAudio.process(subcodeBlocks[i]);
                }
                // All done, process the next subcode block
            }
            // All done, process the next F3 frame
        }

        // Show processing progress update to user
        qint32 subcodesTotal = qMode0Count + qMode1Count + qMode2Count + qMode3Count + qMode4Count + qModeICount;;
        qreal percent = (100.0 / static_cast<qreal>(inputFileSize)) * static_cast<qreal>(inputBytesProcessed);
        if (static_cast<qint32>(percent) > lastPercent) qInfo().nospace() << "Processed " << static_cast<qint32>(percent) << "% of the input EFM (" << subcodesTotal << " subcodes)";
        lastPercent = static_cast<qint32>(percent);
    }

    // Report on the status of the various processes
    reportStatus();

    // Close the input file
    closeInputFile();

    // Close the audio decode output file
    decodeAudio.closeOutputFile();

    return true;
}

// Method to open the input file for reading
bool EfmProcess::openInputFile(QString inputFileName)
{
    // Open input file for reading
    inputFileHandle = new QFile(inputFileName);
    if (!inputFileHandle->open(QIODevice::ReadOnly)) {
        // Failed to open source sample file
        qDebug() << "Could not open " << inputFileName << "as input file";
        return false;
    }
    qDebug() << "EfmProcess::openInputFile(): 10-bit input file is" << inputFileName << "and is" <<
                inputFileHandle->size() << "bytes in length";

    // Exit with success
    return true;
}

// Method to close the input file
void EfmProcess::closeInputFile(void)
{
    // Is an input file open?
    if (inputFileHandle != nullptr) {
        inputFileHandle->close();
    }

    // Clear the file handle pointer
    delete inputFileHandle;
    inputFileHandle = nullptr;
}

// Method to read EFM T value data from the input file
QByteArray EfmProcess::readEfmData(void)
{
    // Read EFM data in 64K blocks
    qint32 bufferSize = 1240 * 64;

    QByteArray outputData;
    outputData.resize(bufferSize);

    qint64 bytesRead = inputFileHandle->read(outputData.data(), outputData.size());
    if (bytesRead != bufferSize) outputData.resize(static_cast<qint32>(bytesRead));

    return outputData;
}

// Method to write status information to qInfo
void EfmProcess::reportStatus(void)
{
    qInfo() << "EFM processing:";
    qInfo() << "  Total number of Q subcodes processed =" << qMode0Count + qMode1Count + qMode2Count + qMode3Count + qMode4Count + qModeICount;
    qInfo() << "  Q Mode 0 subcodes =" << qMode0Count << "(Data)";
    qInfo() << "  Q Mode 1 subcodes =" << qMode1Count << "(CD Audio)";
    qInfo() << "  Q Mode 2 subcodes =" << qMode2Count << "(Disc ID)";
    qInfo() << "  Q Mode 3 subcodes =" << qMode3Count << "(Track ID)";
    qInfo() << "  Q Mode 4 subcodes =" << qMode4Count << "(Non-CD Audio)";
    qInfo() << "  Subcodes with failed CRC =" << qModeICount;

    efmToF3Frames.reportStatus();
    f3FramesToSubcodeBlocks.reportStatus();
    decodeAudio.reportStatus();
}
