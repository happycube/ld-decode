/************************************************************************

    writer_data24section.cpp

    efm-decoder-d24 - EFM F2Section to Data24 Section decoder
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

#include "writer_data24section.h"

// This writer class writes the Data24 sections to a file

WriterData24Section::WriterData24Section()
{}

WriterData24Section::~WriterData24Section()
{
    if (m_file.isOpen()) {
        m_file.close();
    }
}

bool WriterData24Section::open(const QString &filename)
{
    m_file.setFileName(filename);
    if (!m_file.open(QIODevice::WriteOnly)) {
        qCritical() << "WriterData24Section::open() - Could not open file" << filename << "for writing";
        return false;
    }

    // Create a data stream for writing
    m_dataStream = new QDataStream(&m_file);
    qDebug() << "WriterData24Section::open() - Opened file" << filename << "for data writing";
    return true;
}

void WriterData24Section::write(const Data24Section &data24Section)
{
    if (!m_file.isOpen()) {
        qCritical() << "WriterData24Section::write() - File is not open for writing";
        return;
    }

    *m_dataStream << data24Section;
}

void WriterData24Section::close()
{
    if (!m_file.isOpen()) {
        return;
    }

    // Close the data stream
    delete m_dataStream;
    m_dataStream = nullptr;

    m_file.close();
    qDebug() << "WriterData24Section::close(): Closed the data file" << m_file.fileName();
}

qint64 WriterData24Section::size() const
{
    if (m_file.isOpen()) {
        return m_file.size();
    }

    return 0;
}