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
#include "tbc/logging.h"

ReaderData::ReaderData() : m_stdinStream(nullptr), m_usingStdin(false) { }

ReaderData::~ReaderData()
{
    close();
}

bool ReaderData::open(const QString &filename)
{
    if (filename == "-") {
        // Use stdin
        m_usingStdin = true;
        if (!m_file.open(stdin, QIODevice::ReadOnly)) {
            qCritical() << "ReaderData::open() - Could not open stdin for reading";
            return false;
        }
        tbcDebugStream() << "ReaderData::open() - Opened stdin for data reading";
        return true;
    } else {
        // Use regular file
        m_usingStdin = false;
        m_file.setFileName(filename);
        if (!m_file.open(QIODevice::ReadOnly)) {
            qCritical() << "ReaderData::open() - Could not open file" << filename << "for reading";
            return false;
        }
        tbcDebugStream() << "ReaderData::open() - Opened file" << filename << "for data reading with size"
                 << m_file.size() << "bytes";
        return true;
    }
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

    if (m_usingStdin) {
        tbcDebugStream() << "ReaderData::close(): Closed stdin";
    } else {
        tbcDebugStream() << "ReaderData::close(): Closed the data file" << m_file.fileName();
    }
    m_file.close();
    
    if (m_stdinStream) {
        delete m_stdinStream;
        m_stdinStream = nullptr;
    }
    m_usingStdin = false;
}

qint64 ReaderData::size() const
{
    if (m_usingStdin) {
        // Cannot determine size of stdin
        return -1;
    }
    return m_file.size();
}

bool ReaderData::isStdin() const
{
    return m_usingStdin;
}
