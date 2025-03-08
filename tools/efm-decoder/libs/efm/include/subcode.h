/************************************************************************

    subcode.h

    EFM-library - Subcode channel functions
    Copyright (C) 2025 Simon Inns

    This file is part of EFM-Tools.

    This is free software: you can redistribute it and/or
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

#ifndef SUBCODE_H
#define SUBCODE_H

#include <QByteArray>
#include <QString>
#include <QDebug>

#include "section_metadata.h"

class Subcode
{
public:
    Subcode() : m_showDebug(false) { }

    SectionMetadata fromData(const QByteArray &data);
    QByteArray toData(const SectionMetadata &sectionMetadata);
    void setShowDebug(bool showDebug) { m_showDebug = showDebug; }

private:
    void setBit(QByteArray &data, quint8 bitPosition, bool value);
    bool getBit(const QByteArray &data, quint8 bitPosition);
    bool isCrcValid(QByteArray qChannelData);
    quint16 getQChannelCrc(QByteArray qChannelData);
    void setQChannelCrc(QByteArray &qChannelData);
    quint16 calculateQChannelCrc16(const QByteArray &data);
    bool repairData(QByteArray &qChannelData);

    quint8 countBits(quint8 byteValue);
    quint8 intToBcd2(quint8 value);
    quint8 bcd2ToInt(quint8 bcd);

    bool m_showDebug;
};

#endif // SUBCODE_H