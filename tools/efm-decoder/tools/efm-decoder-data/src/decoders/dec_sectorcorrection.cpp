/************************************************************************

    dec_sectorcorrection.cpp

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

#include "dec_sectorcorrection.h"

SectorCorrection::SectorCorrection()
    : m_missingLeadingSectors(0),
    m_missingSectors(0),
    m_haveLastSectorInfo(false),
    m_lastSectorAddress(0),
    m_lastSectorMode(0),
    m_goodSectors(0)
{}

void SectorCorrection::pushSector(const Sector &sector)
{
    // Add the data to the input buffer
    m_inputBuffer.enqueue(sector);

    // Process the queue
    processQueue();
}

Sector SectorCorrection::popSector()
{
    // Return the first item in the output buffer
    return m_outputBuffer.dequeue();
}

void SectorCorrection::processQueue()
{
    while (!m_inputBuffer.isEmpty()) {
        // Get the first item in the input buffer
        Sector sector = m_inputBuffer.dequeue();

        if (!m_haveLastSectorInfo) {
            // This is the first sector - we have to fill the missing leading sectors
            // if the address isn't 0

            if (sector.address().frameNumber() != 0) {
                // Fill the missing leading sectors from address 0 to the first decoded sector address
                if (m_showDebug) {
                    qDebug().nospace().noquote() << "SectorCorrection::processQueue(): First received frame address is "
                        << sector.address().address() << " (" << sector.address().toString() << ")";
                    qDebug() << "SectorCorrection::processQueue(): Filling missing leading sectors with"
                        << sector.address().address() << "sectors";
                }
                for (int i = 0; i < sector.address().address(); i++) {
                    Sector missingSector;
                    missingSector.dataValid(false);
                    missingSector.setAddress(SectorAddress(i));
                    missingSector.setMode(1);
                    missingSector.pushData(QByteArray(2048, 0));
                    missingSector.pushErrorData(QByteArray(2048, 1));
                    m_outputBuffer.enqueue(missingSector);
                    m_missingLeadingSectors++;
                }
            }

            m_haveLastSectorInfo = true;
            m_lastSectorAddress = sector.address();
            m_lastSectorMode = sector.mode();
        } else {
            // Check if there is a gap between this sector and the last
            if (sector.address() != m_lastSectorAddress + 1) {
                // Calculate the number of missing sectors
                quint32 gap = sector.address().address() - m_lastSectorAddress.address() - 1;

                if (m_showDebug) {
                    qDebug() << "SectorCorrection::processQueue(): Sector is not in the correct position. Last good sector address:"
                        << m_lastSectorAddress.address() << m_lastSectorAddress.toString()
                        << "Current sector address:" << sector.address().address() << sector.address().toString() << "Gap:" << gap;
                }
                
                 // Add missing sectors
                for (int i = 0; i < gap; ++i) {
                    Sector missingSector;
                    missingSector.dataValid(false);
                    missingSector.setAddress(m_lastSectorAddress + 1 + i);
                    missingSector.setMode(1);
                    missingSector.pushData(QByteArray(2048, 0));
                    missingSector.pushErrorData(QByteArray(2048, 1));
                    m_outputBuffer.enqueue(missingSector);
                    m_missingSectors++;
                }
            }
        }

        // Add the sector to the output buffer
        m_outputBuffer.enqueue(sector);
        m_goodSectors++;

        // Update the last-good sector information
        m_lastSectorAddress = sector.address();
        m_lastSectorMode = sector.mode();
    }
}

bool SectorCorrection::isReady() const
{
    // Return true if the output buffer is not empty
    return !m_outputBuffer.isEmpty();
}

void SectorCorrection::showStatistics()
{
    qInfo().noquote() << "Sector gap correction:";
    qInfo().noquote() << "  Good sectors:" << m_goodSectors;
    qInfo().noquote() << "  Missing leading sectors:" << m_missingLeadingSectors;
    qInfo().noquote() << "  Missing/Gap sectors:" << m_missingSectors;
    qInfo().noquote() << "  Total sectors:" << m_goodSectors + m_missingLeadingSectors + m_missingSectors;
}