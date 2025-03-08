/************************************************************************

    adfs_image.h

    vfs-verifier - Acorn VFS (Domesday) image verifier
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

#ifndef ADFS_IMAGE_H
#define ADFS_IMAGE_H

#include <QString>
#include <QDebug>
#include <QFile>

class AdfsImage
{
public:
    AdfsImage();

    bool open(QString filename);
    void close();
    QByteArray readSectors(quint64 sector, quint64 count, bool verifyChecksum);
    quint32 adfsSectorToEfmSector(quint32 adfsSector);
    bool isValid() const;

private:
    bool m_isValid;
    QFile *m_file;
    quint64 m_sector0Position;

    void findSector0();
    quint16 calculateChecksum(const QByteArray &buffer);
};

#endif // ADFS_IMAGE_H