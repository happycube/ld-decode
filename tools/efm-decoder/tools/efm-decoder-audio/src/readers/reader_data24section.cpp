/************************************************************************

    reader_data24section.cpp

    efm-decoder-audio - EFM Data24 to Audio decoder
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

#include "reader_data24section.h"
#include "tbc/logging.h"

ReaderData24Section::ReaderData24Section() :
    m_dataStream(nullptr),
    m_fileSizeInSections(0),
    m_usingStdin(false)
{}

ReaderData24Section::~ReaderData24Section()
{
    if (m_file.isOpen()) {
        m_file.close();
    }
}

bool ReaderData24Section::open(const QString &filename)
{
    if (filename == "-") {
        // Use stdin
        m_usingStdin = true;
        if (!m_file.open(stdin, QIODevice::ReadOnly)) {
            qCritical() << "ReaderData24Section::open() - Could not open stdin for reading";
            return false;
        }
        tbcDebugStream() << "ReaderData24Section::open() - Opened stdin for data reading";
        
        // Create a data stream for reading
        m_dataStream = new QDataStream(&m_file);
        
        // Cannot determine size when using stdin
        m_fileSizeInSections = -1;
        return true;
    } else {
        // Use regular file
        m_usingStdin = false;
        m_file.setFileName(filename);
        if (!m_file.open(QIODevice::ReadOnly)) {
            qCritical() << "ReaderData24Section::open() - Could not open file" << filename << "for reading";
            return false;
        }

        // Create a data stream for reading
        m_dataStream = new QDataStream(&m_file);

        // Get total file size and current position
        qint64 currentPos = m_file.pos();
        qint64 totalSize = m_file.size();
        
        // Reset to start of file
        m_file.seek(0);

        // Get the size of one Data24Section object in bytes
        Data24Section dummy;
        *m_dataStream >> dummy;
        qint64 sectionSize = m_file.pos();

        // Calculate the number of Data24Section in the file
        m_fileSizeInSections = totalSize / sectionSize;
        
        // Restore original position
        m_file.seek(currentPos);    

        tbcDebugStream() << "ReaderData24Section::open() - Opened file" << filename << "for data reading containing" << size() << "Data24 Section objects";
        return true;
    }
}

Data24Section ReaderData24Section::read()
{
    if (!m_file.isOpen()) {
        qCritical() << "ReaderData24Section::read() - File is not open for reading";
        return Data24Section();
    }

    Data24Section data24Section;
    *m_dataStream >> data24Section;
    
    // Check if the read operation was successful
    if (m_dataStream->status() != QDataStream::Ok) {
        // End of file or error - return invalid section
        data24Section.metadata.setValid(false);
    }
    
    return data24Section;
}

void ReaderData24Section::close()
{
    if (!m_file.isOpen()) {
        return;
    }

    // Close the data stream
    delete m_dataStream;
    m_dataStream = nullptr;

    if (m_usingStdin) {
        tbcDebugStream() << "ReaderData24Section::close(): Closed stdin";
    } else {
        tbcDebugStream() << "ReaderData24Section::close(): Closed the data file" << m_file.fileName();
    }
    m_file.close();
    m_usingStdin = false;
}

qint64 ReaderData24Section::size()
{
    return m_fileSizeInSections;
}

bool ReaderData24Section::isStdin() const
{
    return m_usingStdin;
}
