/************************************************************************

    dec_sectorcorrection.h

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

#ifndef DEC_SECTORCORRECTION_H
#define DEC_SECTORCORRECTION_H

#include "decoders.h"
#include "sector.h"

class SectorCorrection : public Decoder
{
public:
    SectorCorrection();
    void pushSector(const Sector &sector);
    Sector popSector();
    bool isReady() const;

    void showStatistics();

private:
    void processQueue();

    QQueue<Sector> m_inputBuffer;
    QQueue<Sector> m_outputBuffer;

    bool m_haveLastSectorInfo;
    SectorAddress m_lastSectorAddress;
    qint32 m_lastSectorMode;

    // Statistics
    quint32 m_goodSectors;
    quint32 m_missingLeadingSectors;
    quint32 m_missingSectors;
};

#endif // DEC_SECTORCORRECTION_H