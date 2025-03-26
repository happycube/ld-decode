/************************************************************************

    dec_rawsectortosector.cpp

    efm-decoder-data - EFM Data24 to data decoder
    Copyright (C) 2025 Simon Inns

    This file is part of ld-decode-tools.

    This application is free software: you can redistribute it and/or
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

#include "dec_rawsectortosector.h"

RawSectorToSector::RawSectorToSector()
    : m_validSectors(0),
    m_invalidSectors(0),
    m_correctedSectors(0),
    m_mode0Sectors(0),
    m_mode1Sectors(0),
    m_mode2Sectors(0),
    m_invalidModeSectors(0)
{}

void RawSectorToSector::pushSector(const RawSector &rawSector)
{
    // Add the data to the input buffer
    m_inputBuffer.enqueue(rawSector);

    // Process the queue
    processQueue();
}

Sector RawSectorToSector::popSector()
{
    // Return the first item in the output buffer
    return m_outputBuffer.dequeue();
}

bool RawSectorToSector::isReady() const
{
    // Return true if the output buffer is not empty
    return !m_outputBuffer.isEmpty();
}

// Note: Mode 0 and Mode 2 support missing
// Note: Does not fill missing sectors
void RawSectorToSector::processQueue()
{
    while (!m_inputBuffer.isEmpty()) {
        // Get the first item in the input buffer
        RawSector rawSector = m_inputBuffer.dequeue();
        bool rawSectorValid = false;

        // Verify the data sizes (sanity check)
        if (rawSector.data().size() != 2352) {
            if (m_showDebug) {
                qDebug() << "RawSectorToSector::processQueue(): Sector data size is incorrect. Expected 2352 bytes, got" << rawSector.data().size() << "bytes";
                qFatal("RawSectorToSector::processQueue(): Sector data size is incorrect");
            }
        }

        if (rawSector.errorData().size() != 2352) {
            if (m_showDebug) {
                qDebug() << "RawSectorToSector::processQueue(): Sector error data size is incorrect. Expected 2352 bytes, got" << rawSector.errorData().size() << "bytes";
                qFatal("RawSectorToSector::processQueue(): Sector error data size is incorrect");
            }
        }

        if (rawSector.paddedData().size() != 2352) {
            if (m_showDebug) {
                qDebug() << "RawSectorToSector::processQueue(): Sector padded data size is incorrect. Expected 2352 bytes, got" << rawSector.paddedData().size() << "bytes";
                qFatal("RawSectorToSector::processQueue(): Sector padded data size is incorrect");
            }
        }

        // Determine the sector mode (for modes 0 and 2 there is no correction available)
        qint32 mode = 0;

        // Is the mode byte valid (not error or padding)?
        if (static_cast<quint8>(rawSector.errorData()[15]) != 0) {
            // Mode byte is invalid
            if (m_showDebug) qDebug() << "RawSectorToSector::processQueue(): Sector mode byte is invalid. Assuming it's mode 1";
            mode = -1;
        } else {
            // Extract the sector mode data
            if (static_cast<quint8>(rawSector.data()[15]) == 0) mode = 0;
            else if (static_cast<quint8>(rawSector.data()[15]) == 1) mode = 1;
            else if (static_cast<quint8>(rawSector.data()[15]) == 2) mode = 2;
            else mode = -1;

            if (mode != 1) {
                if (m_showDebug) qDebug() << "RawSectorToSector::processQueue(): Sector mode byte is valid, but mode isn't? Mode reported as" << static_cast<quint8>(rawSector.data()[15]);
            }
        }

        // If the mode is invalid, we try to treat the sector as mode 1 to see if the error correction
        // makes the mode metadata valid.  If it doesn't we discard the sector as error
        if (mode == 1 || mode == -1) {
            // Compute the CRC32 of the sector data based on the EDC word
            quint32 originalEdcWord =
                ((static_cast<quint32>(static_cast<uchar>(rawSector.data()[2064]))) <<  0) |
                ((static_cast<quint32>(static_cast<uchar>(rawSector.data()[2065]))) <<  8) |
                ((static_cast<quint32>(static_cast<uchar>(rawSector.data()[2066]))) << 16) |
                ((static_cast<quint32>(static_cast<uchar>(rawSector.data()[2067]))) << 24);

            quint32 edcWord = crc32(rawSector.data(), 2064);

            // If the CRC32 of the sector data is incorrect, attempt to correct it using Q and P parity
            if (originalEdcWord != edcWord) {
                if (m_showDebug) {
                    qDebug() << "RawSectorToSector::processQueue(): CRC32 error - sector data is corrupt. EDC:" << originalEdcWord << "Calculated:" << edcWord << "attempting to correct";
                }

                // Attempt Q and P parity error correction on the sector data
                Rspc rspc;

                // Make a local copy of the sector data
                QByteArray correctedData = rawSector.data();
                QByteArray correctedErrorData = rawSector.errorData();

                rspc.qParityEcc(correctedData, correctedErrorData, m_showDebug);
                rspc.pParityEcc(correctedData, correctedErrorData, m_showDebug);

                // Copy the corrected data back to the raw sector
                rawSector.pushData(correctedData);
                rawSector.pushErrorData(correctedErrorData);

                // Computer CRC32 again for the corrected data
                quint32 correctedEdcWord =
                    ((static_cast<quint32>(static_cast<uchar>(rawSector.data()[2064]))) <<  0) |
                    ((static_cast<quint32>(static_cast<uchar>(rawSector.data()[2065]))) <<  8) |
                    ((static_cast<quint32>(static_cast<uchar>(rawSector.data()[2066]))) << 16) |
                    ((static_cast<quint32>(static_cast<uchar>(rawSector.data()[2067]))) << 24);

                edcWord = crc32(rawSector.data(), 2064);

                // Is the CRC now correct?
                if (correctedEdcWord != edcWord) {
                    // Error correction failed - sector is invalid and there's nothing more we can do

                    if (mode == 1) {
                        if (m_showDebug) qDebug() << "RawSectorToSector::processQueue(): CRC32 error - sector data cannot be recovered. EDC:" << correctedEdcWord << "Calculated:" << edcWord << "post correction";
                        m_mode1Sectors++;
                        rawSectorValid = false;
                    } else {
                        // Mode was invalid as the sector is completely invalid.  This is probably padding of some sort
                        if (m_showDebug) qDebug() << "RawSectorToSector::processQueue(): Sector mode was invalid and the sector doesn't appear to be mode 1";
                        m_invalidModeSectors++;
                        rawSectorValid = false;
                    }
                } else {
                    // Sector was invalid, but now corrected
                    if (m_showDebug) qDebug() << "RawSectorToSector::processQueue(): Sector data corrected. EDC:" << correctedEdcWord << "Calculated:" << edcWord << "";
                    m_correctedSectors++;
                    rawSectorValid = true;
                    mode = 1; // If error correction worked... this a mode 1 sector
                }
            } else {
                // Original sector data is valid
                m_validSectors++;
                rawSectorValid = true;

                // It's possible that the original mode byte was marked as error, but the RSCP error correction
                // was able to correct the data.  In this case, we need to update the mode byte
                if (static_cast<quint8>(rawSector.data()[15]) == 0) mode = 0;
                else if (static_cast<quint8>(rawSector.data()[15]) == 1) mode = 1;
                else if (static_cast<quint8>(rawSector.data()[15]) == 2) mode = 2;
                else mode = -1;

                if (mode == 0) m_mode0Sectors++;
                else if (mode == 1) m_mode1Sectors++;
                else if (mode == 2) m_mode2Sectors++;
                else {
                    qDebug() << "RawSectorToSector::processQueue(): EDC:" << originalEdcWord << "Calculated:" << edcWord << "Mode byte:" << static_cast<quint8>(rawSector.data()[15]);
                    qFatal("RawSectorToSector::processQueue(): Invalid sector mode of %d - even though sector data was valid - bug?", mode);
                }
            }
        } else {
            // Mode 0 and Mode 2 sectors are not corrected
            if (mode == 0) m_mode0Sectors++;
            else if (mode == 2) m_mode2Sectors++;
            rawSectorValid = true;

            qWarning() << "RawSectorToSector::processQueue(): Mode 0 and Mode 2 sectors are probably not handled correctly - consider submitting this as test data";
        }

        // Determine the sector's metadata
        SectorAddress sectorAddress(0, 0, 0);

        // If the raw sector data is valid, form a sector from it
        if (rawSectorValid) {
            // Extract the sector address data
            qint32 min = bcdToInt(rawSector.data()[12]);
            qint32 sec = bcdToInt(rawSector.data()[13]);
            qint32 frame = bcdToInt(rawSector.data()[14]);
            sectorAddress = SectorAddress(min, sec, frame);

            // Extract the sector mode data
            if (static_cast<quint8>(rawSector.data()[15]) == 0) mode = 0;
            else if (static_cast<quint8>(rawSector.data()[15]) == 1) mode = 1;
            else if (static_cast<quint8>(rawSector.data()[15]) == 2) mode = 2;
            else mode = -1;
        
            // Create an output sector
            Sector sector;
            sector.dataValid(rawSectorValid);
            sector.setAddress(sectorAddress);
            sector.setMode(mode);
            
            // Push only the user data to the output sector (bytes 16 to 2063 = 2KBytes data)
            sector.pushData(rawSector.data().mid(16, 2048));
            sector.pushErrorData(rawSector.errorData().mid(16, 2048));

            // Add the sector to the output buffer
            m_outputBuffer.enqueue(sector);
        } else {
            // Sector is invalid - discard it
            m_invalidSectors++;
        }
    }
}

// Convert 1 byte BCD to integer
quint8 RawSectorToSector::bcdToInt(quint8 bcd)
{
    return (bcd >> 4) * 10 + (bcd & 0x0F);
}

// CRC code adapted and used under GPLv3 from:
// https://github.com/claunia/edccchk/blob/master/edccchk.c
quint32 RawSectorToSector::crc32(const QByteArray &src, qint32 size)
{
    quint32 crc = 0;
    const uchar *data = reinterpret_cast<const uchar*>(src.constData());

    while(size--) {
        crc = (crc >> 8) ^ m_crc32Lut[(crc ^ (*data++)) & 0xFF];
    }

    return crc;
}

void RawSectorToSector::showStatistics()
{
    qInfo() << "Raw Sector to Sector (RSPC error-correction):";
    qInfo().nospace() << "  Valid sectors: " << m_validSectors + m_correctedSectors << " (corrected: " << m_correctedSectors << ")";
    qInfo() << "  Invalid sectors:" << m_invalidSectors;

    qInfo() << "  Sector metadata:";
    qInfo() << "    Mode 0 sectors:" << m_mode0Sectors;
    qInfo() << "    Mode 1 sectors:" << m_mode1Sectors;
    qInfo() << "    Mode 2 sectors:" << m_mode2Sectors;
    qInfo() << "    Invalid mode sectors:" << m_invalidModeSectors;
}