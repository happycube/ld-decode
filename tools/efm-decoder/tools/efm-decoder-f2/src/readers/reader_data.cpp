/************************************************************************

    reader_data.cpp

    efm-decoder-f2 - EFM T-values to F2 Section decoder
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

#include "reader_data.h"

ReaderData::ReaderData() { }

ReaderData::~ReaderData()
{
    if (m_file.isOpen()) {
        m_file.close();
    }
}

bool ReaderData::open(const QString &filename)
{
    m_file.setFileName(filename);
    if (!m_file.open(QIODevice::ReadOnly)) {
        qCritical() << "ReaderData::open() - Could not open file" << filename << "for reading";
        return false;
    }
    qDebug() << "ReaderData::open() - Opened file" << filename << "for data reading with size"
             << m_file.size() << "bytes";
    return true;
}

QByteArray ReaderData::read(uint32_t chunkSize)
{
    if (!m_file.isOpen()) {
        qCritical() << "ReaderData::read() - File is not open for reading";
        return QByteArray();
    }
    QByteArray data = m_file.read(chunkSize);
    return data;
}

void ReaderData::close()
{
    if (!m_file.isOpen()) {
        return;
    }

    m_file.close();
    qDebug() << "ReaderData::close(): Closed the data file" << m_file.fileName();
}

qint64 ReaderData::size() const
{
    return m_file.size();
}