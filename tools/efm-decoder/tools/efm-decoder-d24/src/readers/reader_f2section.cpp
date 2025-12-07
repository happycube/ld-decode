/************************************************************************

    reader_f2section.cpp

    ld-efm-decoder - EFM data encoder
    Copyright (C) 2025 Simon Inns

    This file is part of ld-decode-tools.

    ld-efm-decoder is free software: you can redistribute it and/or
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

#include "reader_f2section.h"
#include "tbc/logging.h"

ReaderF2Section::ReaderF2Section() :
    m_dataStream(nullptr),
    m_fileSizeInSections(0),
    m_usingStdin(false)
{}

ReaderF2Section::~ReaderF2Section()
{
    if (m_file.isOpen()) {
        m_file.close();
    }
}

bool ReaderF2Section::open(const QString &filename)
{
    if (filename == "-") {
        // Use stdin
        m_usingStdin = true;
        if (!m_file.open(stdin, QIODevice::ReadOnly)) {
            qCritical() << "ReaderF2Section::open() - Could not open stdin for reading";
            return false;
        }
        
        // Create a data stream for reading
        m_dataStream = new QDataStream(&m_file);
        
        // Cannot determine size for stdin
        m_fileSizeInSections = -1;
        
        tbcDebugStream() << "ReaderF2Section::open() - Opened stdin for F2 Section data reading";
        return true;
    } else {
        // Use regular file
        m_usingStdin = false;
        m_file.setFileName(filename);
        if (!m_file.open(QIODevice::ReadOnly)) {
            qCritical() << "ReaderF2Section::open() - Could not open file" << filename << "for reading";
            return false;
        }

        // Create a data stream for reading
        m_dataStream = new QDataStream(&m_file);

        // Get total file size and current position
        qint64 currentPos = m_file.pos();
        qint64 totalSize = m_file.size();
        
        // Reset to start of file
        m_file.seek(0);

        // Get the size of one F2Section object in bytes
        F2Section dummy;
        *m_dataStream >> dummy;
        qint64 sectionSize = m_file.pos();

        // Calculate the number of F2Sections in the file
        m_fileSizeInSections = totalSize / sectionSize;
        
        // Restore original position
        m_file.seek(currentPos);

        tbcDebugStream() << "ReaderF2Section::open() - Opened file" << filename << "for data reading containing" << size() << "F2 Section objects";
        return true;
    }
}

F2Section ReaderF2Section::read()
{
    if (!m_file.isOpen()) {
        qCritical() << "ReaderF2Section::read() - File is not open for reading";
        return F2Section();
    }

    F2Section f2Section;
    *m_dataStream >> f2Section;
    
    // Check for stream errors, especially important when reading from stdin
    if (m_dataStream->status() != QDataStream::Ok) {
        tbcDebugStream() << "ReaderF2Section::read() - Data stream error occurred while reading F2Section";
        // Return an empty/invalid section to signal error
        F2Section emptySection;
        return emptySection;
    }
    
    return f2Section;
}

void ReaderF2Section::close()
{
    if (!m_file.isOpen()) {
        return;
    }

    // Close the data stream
    delete m_dataStream;
    m_dataStream = nullptr;

    if (m_usingStdin) {
        tbcDebugStream() << "ReaderF2Section::close(): Closed stdin";
    } else {
        tbcDebugStream() << "ReaderF2Section::close(): Closed the data file" << m_file.fileName();
    }
    m_file.close();
    m_usingStdin = false;
}

qint64 ReaderF2Section::size()
{
    return m_fileSizeInSections;
}

bool ReaderF2Section::isStdin() const
{
    return m_usingStdin;
}

bool ReaderF2Section::atEnd() const
{
    if (!m_file.isOpen()) {
        return true;
    }
    return m_file.atEnd();
}
