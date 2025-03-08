/************************************************************************

    writer_sector_metadata.h

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

#include "writer_sector_metadata.h"

// This writer class writes metadata about sector data to a file

WriterSectorMetadata::WriterSectorMetadata()
{}

WriterSectorMetadata::~WriterSectorMetadata()
{
    if (m_file.isOpen()) {
        m_file.close();
    }
}

bool WriterSectorMetadata::open(const QString &filename)
{
    m_file.setFileName(filename);
    if (!m_file.open(QIODevice::WriteOnly)) {
        qCritical() << "WriterSectorMetadata::open() - Could not open file" << filename << "for writing";
        return false;
    }
    qDebug() << "WriterSectorMetadata::open() - Opened file" << filename << "for metadata writing";

    return true;
}

void WriterSectorMetadata::write(const Sector &sector)
{
    if (!m_file.isOpen()) {
        qCritical() << "WriterSectorMetadata::write() - File is not open for writing";
        return;
    }

    // If the sector is not valid, write a metadata entry for it
    if (!sector.isDataValid()) {
        // Write a metadata entry for the sector
        QString metadata = QString::number(sector.address().address()) + "\n";
        m_file.write(metadata.toUtf8());
    }
}

void WriterSectorMetadata::close()
{
    if (!m_file.isOpen()) {
        return;
    }

    m_file.close();
    qDebug() << "WriterSectorMetadata::close(): Closed the bad sector map metadata file" << m_file.fileName();
}

qint64 WriterSectorMetadata::size() const
{
    if (m_file.isOpen()) {
        return m_file.size();
    }

    return 0;
}