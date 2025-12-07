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
#include "tbc/logging.h"

WriterF2Section::WriterF2Section() : m_dataStream(nullptr), m_usingStdout(false) { }

WriterF2Section::~WriterF2Section()
{
    close();
}

bool WriterF2Section::open(const QString &filename)
{
    if (filename == "-") {
        // Use stdout
        m_usingStdout = true;
        if (!m_file.open(stdout, QIODevice::WriteOnly)) {
            qCritical() << "WriterF2Section::open() - Could not open stdout for writing";
            return false;
        }
        tbcDebugStream() << "WriterF2Section::open() - Opened stdout for data writing";
    } else {
        // Use regular file
        m_usingStdout = false;
        m_file.setFileName(filename);
        if (!m_file.open(QIODevice::WriteOnly)) {
            qCritical() << "WriterF2Section::open() - Could not open file" << filename << "for writing";
            return false;
        }
        tbcDebugStream() << "WriterF2Section::open() - Opened file" << filename << "for data writing";
    }

    // Create a data stream for writing
    m_dataStream = new QDataStream(&m_file);
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
    if (m_dataStream) {
        delete m_dataStream;
        m_dataStream = nullptr;
    }

    if (m_usingStdout) {
        tbcDebugStream() << "WriterF2Section::close(): Closed stdout";
    } else {
        tbcDebugStream() << "WriterF2Section::close(): Closed the data file" << m_file.fileName();
    }
    m_file.close();
    m_usingStdout = false;
}

qint64 WriterF2Section::size() const
{
    if (m_usingStdout) {
        // Cannot determine size when writing to stdout
        return -1;
    }
    if (m_file.isOpen()) {
        return m_file.size();
    }
    return 0;
}

bool WriterF2Section::isStdout() const
{
    return m_usingStdout;
}
