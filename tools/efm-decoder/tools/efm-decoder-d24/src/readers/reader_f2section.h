/************************************************************************

    reader_f2section.h

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

#ifndef READER_F2SECTION_H
#define READER_F2SECTION_H

#include <QString>
#include <QDebug>
#include <QFile>
#include <QDataStream>
#include "section.h"

class ReaderF2Section
{
public:
    ReaderF2Section();
    ~ReaderF2Section();

    bool open(const QString &filename);
    F2Section read();
    void close();
    qint64 size();

private:
    QFile m_file;
    QDataStream* m_dataStream;
    qint64 m_fileSizeInSections;
};

#endif // READER_F2SECTION_H