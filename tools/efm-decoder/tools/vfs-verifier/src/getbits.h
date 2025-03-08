/************************************************************************

    getbits.h

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

#ifndef GETBITS_H
#define GETBITS_H

#include <QDebug>

quint32 get32(QByteArray &data, int byteOffset);
quint32 get24(QByteArray &data, int byteOffset);
quint16 get16(QByteArray &data, int byteOffset);
quint8 get8(QByteArray &data, int byteOffset);

QString toString32bits(quint32 value);
QString toString24bits(quint32 value);
QString toString16bits(quint16 value);
QString toString8bits(quint8 value);

#endif // GETBITS_H