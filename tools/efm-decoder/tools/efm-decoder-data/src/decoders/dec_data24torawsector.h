/************************************************************************

    dec_data24torawsector.h

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

#ifndef DEC_DATA24TORAWSECTOR_H
#define DEC_DATA24TORAWSECTOR_H

#include "decoders.h"
#include "sector.h"

class Data24ToRawSector : public Decoder
{
public:
    Data24ToRawSector();
    void pushSection(const Data24Section &data24Section);
    RawSector popSector();
    bool isReady() const;

    void showStatistics() const;

private:
    void processStateMachine();

    QQueue<Data24Section> m_inputBuffer;
    QQueue<RawSector> m_outputBuffer;

    // State machine states
    enum State { WaitingForSync, InSync, LostSync };

    State m_currentState;

    // 12 byte sync pattern
    const QByteArray m_syncPattern = QByteArray::fromHex("00FFFFFFFFFFFFFFFFFFFF00");

    // Sector data buffer
    QByteArray m_sectorData;
    QByteArray m_sectorErrorData;
    QByteArray m_sectorPaddedData;

    // State machine state processing functions
    State waitingForSync();
    State inSync();
    State lostSync();

    quint32 m_missedSyncPatternCount;
    quint32 m_goodSyncPatternCount;
    quint32 m_badSyncPatternCount;

    // Statistics
    quint32 m_validSectorCount;
    quint32 m_discardedBytes;
    quint32 m_discardedPaddingBytes;
    quint32 m_syncLostCount;
};

#endif // DEC_DATA24TORAWSECTOR_H