/************************************************************************

    writer_wav.h

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

#ifndef WRITER_WAV_H
#define WRITER_WAV_H

#include <QString>
#include <QDebug>
#include <QFile>

#include "section.h"

class WriterWav
{
public:
    WriterWav();
    ~WriterWav();

    bool open(const QString &filename);
    void write(const AudioSection &audioSection);
    void close();
    qint64 size() const;
    bool isOpen() const { return m_file.isOpen(); };

private:
    QFile m_file;
};

#endif // WRITER_WAV_H