/************************************************************************

    writer_wav.cpp

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

#include "writer_wav.h"

// This writer class writes audio data to a file in WAV format
// This is used when the output is stereo audio data

WriterWav::WriterWav() { }

WriterWav::~WriterWav()
{
    if (m_file.isOpen()) {
        m_file.close();
    }
}

bool WriterWav::open(const QString &filename)
{
    m_file.setFileName(filename);
    if (!m_file.open(QIODevice::WriteOnly)) {
        qCritical() << "WriterWav::open() - Could not open file" << filename << "for writing";
        return false;
    }
    qDebug() << "WriterWav::open() - Opened file" << filename << "for data writing";

    // Add 44 bytes of blank header data to the file
    // (we will fill this in later once we know the size of the data)
    QByteArray header(44, 0);
    m_file.write(header);

    return true;
}

void WriterWav::write(const AudioSection &audioSection)
{
    if (!m_file.isOpen()) {
        qCritical() << "WriterWav::write() - File is not open for writing";
        return;
    }

    // Each Audio section contains 98 frames that we need to write to the output file
    for (int index = 0; index < 98; ++index) {
        Audio audio = audioSection.frame(index);
        m_file.write(reinterpret_cast<const char *>(audio.data().data()),
                     audio.frameSize() * sizeof(qint16));
    }
}

void WriterWav::close()
{
    if (!m_file.isOpen()) {
        return;
    }

    // Fill out the WAV header
    qDebug() << "WriterWav::close(): Filling out the WAV header before closing the wav file";

    // WAV file header
    struct WAVHeader
    {
        char riff[4] = { 'R', 'I', 'F', 'F' };
        quint32 chunkSize;
        char wave[4] = { 'W', 'A', 'V', 'E' };
        char fmt[4] = { 'f', 'm', 't', ' ' };
        quint32 subchunk1Size = 16; // PCM
        quint16 audioFormat = 1; // PCM
        quint16 numChannels = 2; // Stereo
        quint32 sampleRate = 44100; // 44.1kHz
        quint32 byteRate;
        quint16 blockAlign;
        quint16 bitsPerSample = 16; // 16 bits
        char data[4] = { 'd', 'a', 't', 'a' };
        quint32 subchunk2Size;
    };

    WAVHeader header;
    header.chunkSize = 36 + m_file.size();
    header.byteRate = header.sampleRate * header.numChannels * header.bitsPerSample / 8;
    header.blockAlign = header.numChannels * header.bitsPerSample / 8;
    header.subchunk2Size = m_file.size();

    // Move to the beginning of the file to write the header
    m_file.seek(0);
    m_file.write(reinterpret_cast<const char *>(&header), sizeof(WAVHeader));

    // Now close the file
    m_file.close();
    qDebug() << "WriterWav::close(): Closed the WAV file" << m_file.fileName();
}

qint64 WriterWav::size() const
{
    if (m_file.isOpen()) {
        return m_file.size();
    }

    return 0;
}