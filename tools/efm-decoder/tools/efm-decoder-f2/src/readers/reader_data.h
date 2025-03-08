/************************************************************************

    reader_data.h

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

#ifndef READER_DATA_H
#define READER_DATA_H

#include <QString>
#include <QDebug>
#include <QFile>

class ReaderData
{
public:
    ReaderData();
    ~ReaderData();

    bool open(const QString &filename);
    QByteArray read(uint32_t chunkSize);
    void close();
    qint64 size() const;

private:
    QFile m_file;
};

#endif // READER_DATA_H