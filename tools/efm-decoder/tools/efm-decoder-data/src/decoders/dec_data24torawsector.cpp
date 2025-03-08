/************************************************************************

    dec_data24torawsector.cpp

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

#include "dec_data24torawsector.h"

Data24ToRawSector::Data24ToRawSector()
    : m_validSectorCount(0),
      m_discardedBytes(0),
      m_discardedPaddingBytes(0),
      m_missedSyncPatternCount(0),
      m_goodSyncPatternCount(0),
      m_syncLostCount(0),
      m_badSyncPatternCount(0),
      m_currentState(WaitingForSync)
{}

void Data24ToRawSector::pushSection(const Data24Section &data24Section)
{
    // Add the data to the input buffer
    m_inputBuffer.enqueue(data24Section);

    // Process the state machine
    processStateMachine();
}

RawSector Data24ToRawSector::popSector()
{
    // Return the first item in the output buffer
    return m_outputBuffer.dequeue();
}

bool Data24ToRawSector::isReady() const
{
    // Return true if the output buffer is not empty
    return !m_outputBuffer.isEmpty();
}

void Data24ToRawSector::processStateMachine()
{
    while (!m_inputBuffer.isEmpty()) {
        Data24Section data24Section = m_inputBuffer.dequeue();

        // Add the data24 section's data to the sector data buffer
        m_sectorData.reserve(m_sectorData.size() + 2352);
        m_sectorErrorData.reserve(m_sectorErrorData.size() + 2352);
        m_sectorPaddedData.reserve(m_sectorPaddedData.size() + 2352);

        for (int i = 0; i < 98; i++) {
            // Data
            const QVector<quint8>& frameData = data24Section.frame(i).data();
            QByteArray frameBytes = QByteArray(reinterpret_cast<const char*>(frameData.constData()), frameData.size());
            m_sectorData.append(frameBytes);

            // Add the error data
            const QVector<bool>& frameErrorData = data24Section.frame(i).errorData();
            QByteArray frameErrorBytes = QByteArray(reinterpret_cast<const char*>(frameErrorData.constData()), frameErrorData.size());
            m_sectorErrorData.append(frameErrorBytes);

            // Add the padding data
            const QVector<bool>& framePaddedData = data24Section.frame(i).paddedData();
            QByteArray framePaddedBytes = QByteArray(reinterpret_cast<const char*>(framePaddedData.constData()), framePaddedData.size());
            m_sectorPaddedData.append(framePaddedBytes);
        }

        switch (m_currentState) {
            case WaitingForSync:
                m_currentState = waitingForSync();
                break;
            case InSync:
                m_currentState = inSync();
                break;
            case LostSync:
                m_currentState = lostSync();
                break;
        }
    }
}

Data24ToRawSector::State Data24ToRawSector::waitingForSync()
{
    State nextState = WaitingForSync;

    // Is there enough data in the buffer to form a sector?
    if (m_sectorData.size() < 2352) {
        // Not enough data
        if (m_showDebug) qDebug() << "Data24ToRawSector::waitingForSync(): Not enough data in sectorData to form a sector, waiting for more data";

        // Get more data and try again
        nextState = WaitingForSync;
        return nextState;
    }

    // Does the sector data contain the sync pattern?
    quint32 syncPatternPosition = m_sectorData.indexOf(m_syncPattern);
    if (syncPatternPosition == -1) {
        // No sync pattern found
        //if (m_showDebug) qDebug() << "Data24ToRawSector::waitingForSync(): No sync pattern found in sectorData, discarding" << m_sectorData.size() - 11 << "bytes";

        // Clear the sector data buffer (except the last 11 bytes)
        m_discardedBytes += m_sectorData.size() - 11;
        m_sectorData = m_sectorData.right(11);
        m_sectorErrorData = m_sectorErrorData.right(11);

        // Get more data and try again
        nextState = WaitingForSync;
    } else {
        // Sync pattern found

        // Discard any data before the sync pattern
        m_discardedBytes += syncPatternPosition;
        m_sectorData = m_sectorData.right(m_sectorData.size() - syncPatternPosition);
        m_sectorErrorData = m_sectorErrorData.right(m_sectorErrorData.size() - syncPatternPosition);
        m_sectorPaddedData = m_sectorPaddedData.right(m_sectorPaddedData.size() - syncPatternPosition);
        if (m_showDebug) qDebug() << "Data24ToRawSector::waitingForSync(): Possible sync pattern found in sectorData at position:" << syncPatternPosition << "discarding" << syncPatternPosition << "bytes";

        // Do we really have a valid sector or is this a false positive?

        // Is the sector broken?  Count the total number of error bytes and padding bytes in the sector
        qint32 errorByteCount = 0;
        qint32 paddingByteCount = 0;
        for (int i = 0; i < 2352; i++) {
            if (static_cast<quint8>(m_sectorErrorData[i]) == 1) {
                errorByteCount++;
            }
            if (static_cast<quint8>(m_sectorPaddedData[i]) == 1) {
                paddingByteCount++;
            }
        }

        if (errorByteCount > 1000 || paddingByteCount > 1000) {
            if (m_showDebug) qDebug() << "Data24ToRawSector::waitingForSync(): Discarding sync as false positive due to" << errorByteCount << "error bytes and" << paddingByteCount << "padding bytes";
            nextState = WaitingForSync;
        } else {
            if (m_showDebug) qDebug() << "Data24ToRawSector::waitingForSync(): Valid sector sync found with" << errorByteCount << "error bytes and" << paddingByteCount << "padding bytes";
            nextState = InSync;
        }
    }

    return nextState;
}

Data24ToRawSector::State Data24ToRawSector::inSync()
{
    State nextState = InSync;

    // Is there enough data in the buffer to form a sector?
    if (m_sectorData.size() < 2352) {
        // Not enough data
        if (m_showDebug) qDebug() << "Data24ToRawSector::inSync(): Not enough data in sectorData to form a sector, waiting for more data";

        // Get more data and try again
        nextState = InSync;
        return nextState;
    } else {
        // Are there any error bytes or padding in the first 12 bytes?
        if (m_sectorErrorData.left(12).contains(1) || m_sectorPaddedData.left(12).contains(1)) {
            // Is the sector broken?  Count the total number of error bytes and padding bytes in the sector
            qint32 errorByteCount = 0;
            qint32 paddingByteCount = 0;
            for (int i = 0; i < 2352; i++) {
                if (static_cast<quint8>(m_sectorErrorData[i]) == 1) {
                    errorByteCount++;
                }
                if (static_cast<quint8>(m_sectorPaddedData[i]) == 1) {
                    paddingByteCount++;
                }
            }

            if (m_showDebug) {
                qDebug() << "Data24ToRawSector::inSync(): Sector header corrupt. Sector contains" << errorByteCount
                    << "error bytes and" << paddingByteCount << "padding bytes";
            }
        }

        // Is there a valid sync pattern at the beginning of the sector data?
        if (m_sectorData.left(12) != m_syncPattern) {
            // No sync pattern found
            m_missedSyncPatternCount++;
            m_badSyncPatternCount++;

            if (m_missedSyncPatternCount > 4) {
                // Too many missed sync patterns, lost sync
                if (m_showDebug) qDebug() << "Data24ToRawSector::inSync(): Too many missed sync patterns (4 missed), lost sync. Valid sector count:" << m_validSectorCount;
                nextState = LostSync;
                return nextState;
            } else {
                if (m_showDebug) {
                    QString foundPattern = m_sectorData.left(12).toHex(' ').toUpper();
                    qDebug() << "Data24ToRawSector::inSync(): Sync pattern mismatch:"
                        << "Found:" << foundPattern
                        << "Sector count:" << m_validSectorCount
                        << "Missed sync patterns:" << m_missedSyncPatternCount;
                }
            }
        } else {
            // Sync pattern found
            m_goodSyncPatternCount++;

            if (m_showDebug && m_missedSyncPatternCount) {
                qDebug() << "Data24ToRawSector::inSync(): Sync pattern found after" << m_missedSyncPatternCount << "missed sync patterns (resynced)";
            }

            m_missedSyncPatternCount = 0;
        }

        // Unscramble the sector (bytes 12 to 2351)
        QByteArray rawDataOut = m_sectorData.left(2352);
        QByteArray rawErrorDataOut = m_sectorErrorData.left(2352);
        QByteArray rawPaddedDataOut = m_sectorErrorData.left(2352);

        for (qint32 i = 0; i < 2352; i++) {
            if (i < 12) {
                // Replace the sync pattern (or the EDC will always be wrong)
                rawDataOut[i] = m_syncPattern[i];
                rawErrorDataOut[i] = 0;
                rawPaddedDataOut[i] = 0;
            } else {
                // Only bytes 12 to 2351 are scrambled
                rawDataOut[i] = rawDataOut[i] ^ m_unscrambleTable[i];
            }
        }

        // Create a new sector
        RawSector rawSector;
        rawSector.pushData(rawDataOut);
        rawSector.pushErrorData(rawErrorDataOut);
        rawSector.pushPaddedData(rawPaddedDataOut);

        m_outputBuffer.enqueue(rawSector);
        m_validSectorCount++;
        
        // Remove 2352 bytes of processed data from the buffers
        m_sectorData = m_sectorData.right(m_sectorData.size() - 2352);
        m_sectorErrorData = m_sectorErrorData.right(m_sectorErrorData.size() - 2352);
        m_sectorPaddedData = m_sectorErrorData.right(m_sectorPaddedData.size() - 2352);
    }

    return nextState;
}

Data24ToRawSector::State Data24ToRawSector::lostSync()
{
    State nextState = WaitingForSync;
    m_missedSyncPatternCount = 0;
    if (m_showDebug) qDebug() << "Data24ToRawSector::lostSync(): Lost sync";
    m_syncLostCount++;
    return nextState;
}

void Data24ToRawSector::showStatistics()
{
    qInfo() << "Data24ToRawSector statistics:";
    qInfo() << "  Valid sectors:" << m_validSectorCount;
    qInfo() << "  Discarded bytes:" << m_discardedBytes;
    qInfo() << "  Discarded padding bytes:" << m_discardedPaddingBytes;
    
    qInfo() << "  Good sync patterns:" << m_goodSyncPatternCount;
    qInfo() << "  Bad sync patterns:" << m_badSyncPatternCount;

    qInfo() << "  Missed sync patterns:" << m_missedSyncPatternCount;
    qInfo() << "  Sync lost count:" << m_syncLostCount;
}