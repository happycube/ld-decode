/************************************************************************

    writer_f2section.h

    efm-stacker-f2 - EFM F2 Section stacker
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

#ifndef WRITER_F2SECTION_H
#define WRITER_F2SECTION_H

#include <QString>
#include <QDebug>
#include <QFile>
#include <QDataStream>

#include "section.h"

class WriterF2Section
{
public:
    WriterF2Section();
    ~WriterF2Section();

    bool open(const QString &filename);
    void write(const F2Section &f2Section);
    void close();
    qint64 size() const;
    bool isOpen() const { return m_file.isOpen(); };

private:
    QFile m_file;
    QDataStream* m_dataStream;
};

#endif // WRITER_F2SECTION_H