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

#ifndef WRITER_SECTOR_METADATA_H
#define WRITER_SECTOR_METADATA_H

#include <QString>
#include <QDebug>
#include <QFile>

#include "sector.h"

class WriterSectorMetadata
{
public:
    WriterSectorMetadata();
    ~WriterSectorMetadata();

    bool open(const QString &filename);
    void write(const Sector &sector);
    void close();
    qint64 size() const;
    bool isOpen() const { return m_file.isOpen(); };

private:
    QFile m_file;
};

#endif // WRITER_SECTOR_METADATA_H