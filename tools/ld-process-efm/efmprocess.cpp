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

// Note:
//
//   Audio is: EFM->F3->F2->Audio
//    Data is: EFM->F3->F2->F1->Sector->Data
// Section is: EFM->F3->Section
//
// See ECMA-130 for details

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

    // Open the audio output file
    f2FramesToAudio.openOutputFile(outputFilename);

    // Open the data decode output file
    // To-do: data support

    // Turn on verbose debug if required
    if (verboseDebug) efmToF3Frames.setVerboseDebug(true);

    QByteArray efmBuffer;
    while ((efmBuffer = readEfmData()).size() != 0) {
        inputBytesProcessed += efmBuffer.size();

        // Convert the EFM buffer data into F3 frames
        QVector<F3Frame> f3Frames = efmToF3Frames.convert(efmBuffer);

        // Convert the F3 frames into F2 frames
        QVector<F2Frame> f2Frames = f3ToF2Frames.convert(f3Frames);

        // Convert the F2 frames into F1 frames
        QVector<F1Frame> f1Frames = f2ToF1Frames.convert(f2Frames);

        // Process the F1 frames as sectors
        for (qint32 i = 0; i < f1Frames.size(); i++) {
            Sector sector;
            sector.setData(f1Frames[i]);
            if (sector.isValid()) {
                qDebug() << "F1Frame mode =" << sector.getMode() << "address =" << sector.getAddress().getTimeAsQString();
            } else {
                qDebug() << "F1Frame mode =" << sector.getMode() << "address =" << sector.getAddress().getTimeAsQString() << "Invalid";
            }
        }

        // Convert the F2 frames into audio
        f2FramesToAudio.convert(f2Frames);

        // Convert the F3 frames into subcode sections
        QVector<Section> sections = f3ToSections.convert(f3Frames);

        // Process the sections (doesn't really do much right now)
        processSections(sections);

        // Show EFM processing progress update to user
        qreal percent = (100.0 / static_cast<qreal>(inputFileSize)) * static_cast<qreal>(inputBytesProcessed);
        if (static_cast<qint32>(percent) > lastPercent) qInfo().nospace() << "Processed " << static_cast<qint32>(percent) << "% of the input EFM";
        lastPercent = static_cast<qint32>(percent);
    }

    // Report on the status of the various processes
    reportStatus();

    // Close the input file
    closeInputFile();

    // Close the audio output file
    f2FramesToAudio.closeOutputFile();

    return true;
}

// Method to process the decoded sections
void EfmProcess::processSections(QVector<Section> sections)
{
    // Did we get any sections?
    if (sections.size() != 0) {
        for (qint32 i = 0; i < sections.size(); i++) {
            qint32 qMode = sections[i].getQMode();

            // Depending on the section Q Mode, process the section
            if (qMode == 0) {
                // Data
                qMode0Count++;
                //qDebug() << "EfmProcess::showSections(): Section Q mode is 0 - Data!";
            } else if (qMode == 1) {
                // CD Audio
                qMode1Count++;
                //qDebug() << "EfmProcess::showSections(): Section Q mode is 1 - CD Audio - Track time:" << sections[i].getQMetadata().qMode4.trackTime.getTimeAsQString();
            } else if (qMode == 2) {
                // Unique ID for disc
                qMode2Count++;
                //qDebug() << "EfmProcess::showSections(): Section Q mode is 2 - Unique ID for disc";
            } else if (qMode == 3) {
                // Unique ID for track
                qMode3Count++;
                //qDebug() << "EfmProcess::showSections(): Section Q mode is 3 - Unique ID for track!";
            } else if (qMode == 4) {
                // 4 = non-CD Audio (LaserDisc)
                qMode4Count++;
                //qDebug() << "EfmProcess::showSections(): Section Q mode is 4 - non-CD Audio - Track time:" << sections[i].getQMetadata().qMode4.trackTime.getTimeAsQString();
            } else {
                // Invalid section
                qModeICount++;
                //qDebug() << "EfmProcess::showSections(): Invalid section";
            }
        }
    }
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
    qInfo() << "  Total number of sections processed =" << qMode0Count + qMode1Count + qMode2Count + qMode3Count + qMode4Count + qModeICount;
    qInfo() << "  Q Mode 0 sections =" << qMode0Count << "(Data)";
    qInfo() << "  Q Mode 1 sections =" << qMode1Count << "(CD Audio)";
    qInfo() << "  Q Mode 2 sections =" << qMode2Count << "(Disc ID)";
    qInfo() << "  Q Mode 3 sections =" << qMode3Count << "(Track ID)";
    qInfo() << "  Q Mode 4 sections =" << qMode4Count << "(Non-CD Audio)";
    qInfo() << "  Sections with failed Q CRC =" << qModeICount;

    efmToF3Frames.reportStatus();
    f3ToF2Frames.reportStatus();
    f2ToF1Frames.reportStatus();

    f3ToSections.reportStatus();
    f2FramesToAudio.reportStatus();
}
