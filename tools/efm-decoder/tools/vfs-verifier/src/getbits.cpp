/************************************************************************

    getbits.cpp

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

#include "getbits.h"

quint32 get32(QByteArray &data, int byteOffset)
{
    quint8 b0 = static_cast<quint8>(data.at(byteOffset));
    quint8 b1 = static_cast<quint8>(data.at(byteOffset+1));
    quint8 b2 = static_cast<quint8>(data.at(byteOffset+2));
    quint8 b3 = static_cast<quint8>(data.at(byteOffset+3));

    return static_cast<quint32>(b0 | (b1 << 8) | (b2 << 16) | (b3 << 24));
}

quint32 get24(QByteArray &data, int byteOffset)
{
    quint8 b0 = static_cast<quint8>(data.at(byteOffset));
    quint8 b1 = static_cast<quint8>(data.at(byteOffset+1));
    quint8 b2 = static_cast<quint8>(data.at(byteOffset+2));

    return static_cast<quint32>(b0 | (b1 << 8) | (b2 << 16));
}

quint16 get16(QByteArray &data, int byteOffset)
{
    return static_cast<quint16>(static_cast<quint8>(data.at(byteOffset)) | (static_cast<quint8>(data.at(byteOffset+1)) << 8));
}

quint8 get8(QByteArray &data, int byteOffset)
{
    return static_cast<quint8>(data.at(byteOffset));
}

QString toString32bits(quint32 value)
{
    return QString("0x") + QString("%1").arg(value, 8, 16, QChar('0')).toUpper();
}

QString toString24bits(quint32 value)
{
    return QString("0x") + QString("%1").arg(value, 6, 16, QChar('0')).toUpper();
}

QString toString16bits(quint16 value)
{
    return QString("0x") + QString("%1").arg(value, 4, 16, QChar('0')).toUpper();
}

QString toString8bits(quint8 value)
{
    return QString("0x") + QString("%1").arg(value, 2, 16, QChar('0')).toUpper();
}