/************************************************************************

    sectorstodata.cpp

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

#include "sectorstodata.h"
#include "logging.h"

SectorsToData::SectorsToData()
{
    gotFirstValidSector = false;
    lastGoodAddress.setTime(0, 0, 0);

    resetStatistics();
}

// Methods to handle statistics
void SectorsToData::resetStatistics(void)
{
    statistics.sectorsWritten = 0;
    statistics.gapSectors = 0;
    statistics.missingSectors = 0;
}

SectorsToData::Statistics SectorsToData::getStatistics(void)
{
    return statistics;
}

// Method to write status information to qCInfo
void SectorsToData::reportStatus(void)
{
    qInfo() << "Sectors to data converter:";
    qInfo() << "  Total number of sectors written =" << statistics.sectorsWritten;
    qInfo() << "  Empty sectors (probably) due to EFM signal gaps =" << statistics.gapSectors;
    qInfo() << "  Empty sectors (probably) due to data loss =" << statistics.missingSectors;

    if (missingStartSector.size() > 0) {
        // Report gaps and missing data
        QString startAddress;
        QString endAddress;
        QString type;

        qInfo() << "  Empty sector analysis:";
        for (qint32 i = 0; i < missingStartSector.size(); i++) {
            startAddress = QString("0x%1").arg(missingStartSector[i], 8, 16, QChar('0'));
            endAddress = QString("0x%1").arg(missingEndSector[i], 8, 16, QChar('0'));
            if (isGap[i]) type = "EFM Gap"; else type = "Data Loss";

            qInfo().noquote() << "    " << startAddress << "-" << endAddress << type;
        }
    }
}

// Method to open the data output file
bool SectorsToData::setOutputFile(QFile *outputFileHandle)
{
    // Open output file for writing
    this->outputFileHandle = outputFileHandle;

    // Exit with success
    return true;
}

// Convert sectors into data (Note: This will probably only work for type 1 sectors as-is)
void SectorsToData::convert(QVector<Sector> sectors)
{
    for (qint32 i = 0; i < sectors.size(); i++) {
        // Is sector valid?
        if (sectors[i].isValid()) {
            // Output sector metadata to debug
            qDebug() << "SectorsToData::convert(): Writing mode" << sectors[i].getMode() <<
                        sectors[i].getUserData().size() << "byte" <<
                        "data sector with address of" << sectors[i].getAddress().getTimeAsQString();

            // Write the sector
            TrackTime expectedAddress = lastGoodAddress;
            expectedAddress.addFrames(1); // We expect the next frame

            // Is the current sector address the expected next sector address?
            if (gotFirstValidSector) {
                if (expectedAddress.getFrames() != sectors[i].getAddress().getFrames()) {
                    // Calculate the number of missing frames
                    qint32 missingFrames = (sectors[i].getAddress().getFrames() - expectedAddress.getFrames());

                    // Address is not the expected next sector, show debug
                    qDebug() << "SectorsToData::convert(): Unexpected sector address - missing" <<
                                missingFrames << "sectors -" <<
                                "padding output data!";

                    // Figure out how many bytes to pad the data file with
                    qint32 bytesToPad = 0;
                    switch(sectors[i].getMode()) {
                    case 0: bytesToPad = 2336;
                        break;
                    case 1: bytesToPad = 2048;
                        break;
                    case 2: bytesToPad = 2336;
                        break;
                    default: bytesToPad = 2048;
                    }

                    // If there is a big gap in EFM data it's probably because there is a break in the
                    // EFM signal on the disc (Domesday has a number of these).  If we loose just a few
                    // sectors, then it's very likely data is missing
                    if (missingFrames > 16) {
                        qDebug() << "SectorsToData::convert(): A gap of" << missingFrames << "sectors was detected in the EFM (probably a break in the EFM signal)";
                        statistics.gapSectors += missingFrames;

                        // Record the gap
                        missingStartSector.append(statistics.sectorsWritten * bytesToPad);
                        missingEndSector.append((statistics.sectorsWritten + missingFrames) * bytesToPad);
                        isGap.append(true);
                    } else {
                        qDebug() << "SectorsToData::convert(): A gap of" << missingFrames << "sectors was detected in the EFM (probably corrupt data!)";
                        statistics.missingSectors += missingFrames;

                        qDebug().noquote() << "SectorsToData::convert(): Gap started at position" << QString("0x%1").arg(statistics.sectorsWritten * bytesToPad, 0, 16) <<
                                      "and finished at" << QString("0x%1").arg((statistics.sectorsWritten + missingFrames) * bytesToPad, 0, 16);

                        // Record the data loss
                        missingStartSector.append(statistics.sectorsWritten * bytesToPad);
                        missingEndSector.append((statistics.sectorsWritten + missingFrames) * bytesToPad);
                        isGap.append(false);
                    }

                    QByteArray padding;
                    padding.fill(static_cast<char>(0x00), bytesToPad);
                    for (qint32 pad = 0; pad < missingFrames; pad++) outputFileHandle->write(padding);

                    // Add the padding to the sectors out count
                    statistics.sectorsWritten += missingFrames;
                }
            } else {
                // This is the first valid sector
                // First valid sector found
                gotFirstValidSector = true;
                qDebug() << "SectorsToData::convert(): First valid data sector found!";
            }

            // Write sector to disc
            outputFileHandle->write(sectors[i].getUserData());

            // Update tracking data
            lastGoodAddress = sectors[i].getAddress();
            statistics.sectorsWritten++;
        } else {
            qDebug() << "SectorsToData::convert(): Data sector is invalid - ignoring";
        }
    }
}
