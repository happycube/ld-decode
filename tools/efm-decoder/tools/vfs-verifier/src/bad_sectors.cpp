/************************************************************************

    bad_sectors.cpp

    vfs-verifier - Acorn VFS (Domesday) image verifier
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

#include "bad_sectors.h"

BadSectors::BadSectors() :
    m_isOpen(false)
{}

bool BadSectors::open(QString filename)
{
    m_file.setFileName(filename);
    if (!m_file.open(QIODevice::ReadOnly)) {
        qCritical() << "BadSectors::open() - Could not open file" << filename << "for reading";
        return false;
    }
    qDebug() << "BadSectors::open() - Opened file" << filename << "for reading";

    // Read the bad sector list (this is a text file with one sector number per line)
    while (!m_file.atEnd()) {
        QByteArray line = m_file.readLine();
        quint32 sector = line.toUInt();
        m_badSectors.append(sector);
    }

    qDebug() << "BadSectors::open() - Read" << m_badSectors.size() << "bad sectors from file" << filename;

    m_isOpen = true;
    return true;
}

void BadSectors::close()
{
    if (m_file.isOpen()) {
        m_file.close();
    }
    m_isOpen = false;
}

bool BadSectors::isSectorBad(quint32 sector) const
{
    return m_badSectors.contains(sector);
}