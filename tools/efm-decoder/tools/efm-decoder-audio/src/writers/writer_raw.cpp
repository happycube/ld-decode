/************************************************************************

    writer_raw.cpp

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

#include "writer_raw.h"
#include "tbc/logging.h"

// This writer class writes audio data to a file in raw format (no header)
// This is used when the output is stereo audio data without WAV header

WriterRaw::WriterRaw() : m_usingStdout(false) { }

WriterRaw::~WriterRaw()
{
    if (m_file.isOpen()) {
        m_file.close();
    }
}

bool WriterRaw::open(const QString &filename)
{
    if (filename == "-") {
        // Use stdout
        m_usingStdout = true;
        if (!m_file.open(stdout, QIODevice::WriteOnly)) {
            qCritical() << "WriterRaw::open() - Could not open stdout for writing";
            return false;
        }
        tbcDebugStream() << "WriterRaw::open() - Opened stdout for raw audio data writing";
    } else {
        // Use regular file
        m_usingStdout = false;
        m_file.setFileName(filename);
        if (!m_file.open(QIODevice::WriteOnly)) {
            qCritical() << "WriterRaw::open() - Could not open file" << filename << "for writing";
            return false;
        }
        tbcDebugStream() << "WriterRaw::open() - Opened file" << filename << "for raw audio data writing";
    }

    return true;
}

void WriterRaw::write(const AudioSection &audioSection)
{
    if (!m_file.isOpen()) {
        qCritical() << "WriterRaw::write() - File is not open for writing";
        return;
    }

    // Each Audio section contains 98 frames that we need to write to the output file
    for (int index = 0; index < 98; ++index) {
        Audio audio = audioSection.frame(index);
        m_file.write(reinterpret_cast<const char *>(audio.data().data()),
                     audio.frameSize() * sizeof(qint16));
    }
}

void WriterRaw::close()
{
    if (!m_file.isOpen()) {
        return;
    }

    // For raw audio, we just close the file - no header to write
    m_file.close();
    if (m_usingStdout) {
        tbcDebugStream() << "WriterRaw::close(): Closed stdout";
    } else {
        tbcDebugStream() << "WriterRaw::close(): Closed the raw audio file" << m_file.fileName();
    }
    m_usingStdout = false;
}

qint64 WriterRaw::size() const
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

bool WriterRaw::isStdout() const
{
    return m_usingStdout;
}
