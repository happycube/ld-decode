/************************************************************************

    writer_sector.h

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

#include "writer_sector.h"

// This writer class writes raw data to a file directly from the Data24 sections
// This is (generally) used when the output is not stereo audio data

WriterSector::WriterSector() { }

WriterSector::~WriterSector()
{
    if (m_file.isOpen()) {
        m_file.close();
    }
}

bool WriterSector::open(const QString &filename)
{
    m_file.setFileName(filename);
    if (!m_file.open(QIODevice::WriteOnly)) {
        qCritical() << "WriterSector::open() - Could not open file" << filename << "for writing";
        return false;
    }
    qDebug() << "WriterSector::open() - Opened file" << filename << "for data writing";
    return true;
}

void WriterSector::write(const Sector &sector)
{
    if (!m_file.isOpen()) {
        qCritical() << "WriterSector::write() - File is not open for writing";
        return;
    }

    // Each sector contains 2048 bytes that we need to write to the output file
    m_file.write(reinterpret_cast<const char *>(sector.data().data()),
                    sector.size() * sizeof(uint8_t));
}

void WriterSector::close()
{
    if (!m_file.isOpen()) {
        return;
    }

    m_file.close();
    qDebug() << "WriterSector::close(): Closed the data file" << m_file.fileName();
}

qint64 WriterSector::size() const
{
    if (m_file.isOpen()) {
        return m_file.size();
    }

    return 0;
}