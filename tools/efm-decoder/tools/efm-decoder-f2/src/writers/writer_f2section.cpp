/************************************************************************

    writer_section.cpp

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

#include "writer_f2section.h"

WriterF2Section::WriterF2Section() { }

WriterF2Section::~WriterF2Section()
{
    if (m_file.isOpen()) {
        m_file.close();
    }
}

bool WriterF2Section::open(const QString &filename)
{
    m_file.setFileName(filename);
    if (!m_file.open(QIODevice::WriteOnly)) {
        qCritical() << "WriterData::open() - Could not open file" << filename << "for writing";
        return false;
    }

    // Create a data stream for writing
    m_dataStream = new QDataStream(&m_file);
    qDebug() << "WriterData::open() - Opened file" << filename << "for data writing";
    return true;
}

void WriterF2Section::write(const F2Section &f2Section)
{
    if (!m_file.isOpen()) {
        qCritical() << "WriterF2Section::write() - File is not open for writing";
        return;
    }

    *m_dataStream << f2Section;
}

void WriterF2Section::close()
{
    if (!m_file.isOpen()) {
        return;
    }

    // Close the data stream
    delete m_dataStream;
    m_dataStream = nullptr;

    m_file.close();
    qDebug() << "WriterF2Section::close(): Closed the data file" << m_file.fileName();
}

qint64 WriterF2Section::size() const
{
    if (m_file.isOpen()) {
        return m_file.size();
    }

    return 0;
}